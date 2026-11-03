"""OpenAI-compatible chat client for the generator (Muse on the Meta Model API by default).

Every call is cached on disk (keyed by model, messages and temperature) and logged to a
ledger with its token usage. A hard token budget is checked before each uncached call, so an
experiment can never spend more than it was given.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

META_BASE_URL = "https://api.meta.ai/v1"


class BudgetExceeded(RuntimeError):
    """Raised before a call that would start once the token budget is used up."""


@dataclass
class Reply:
    text: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    reasoning_tokens: int  # part of completion_tokens spent on chain of thought
    seconds: float
    from_cache: bool
    raw: dict = field(default_factory=dict)  # full API response, not only the text
    cache_kind: str = "miss"  # miss | exact | legacy | canonical


@dataclass
class ChatClient:
    """Chat-completions client with a disk cache and a token ledger.

    Attributes:
        model: model id, e.g. "muse-wonder-1.0".
        cache_dir: one JSON file per distinct request.
        ledger: JSONL file; one line per call (cached calls are logged with zero spend).
        token_budget: maximum total tokens (prompt + completion) across the ledger.
    """

    model: str
    cache_dir: Path
    ledger: Path
    token_budget: int
    base_url: str = META_BASE_URL
    api_key_env: str = "META_API_KEY"
    timeout_s: float = 900.0
    _spent: int | None = field(default=None, repr=False)

    def spent(self) -> int:
        if self._spent is None:
            self._spent = 0
            if self.ledger.exists():
                for line in self.ledger.read_text(encoding="utf-8").splitlines():
                    entry = json.loads(line)
                    if not entry.get("from_cache"):
                        self._spent += entry["prompt_tokens"] + entry["completion_tokens"]
        return self._spent

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        tag: str = "",
        sample_index: int = 0,
        canonical_key: str | None = None,
    ) -> Reply:
        """Return a reply, reusing an exact, legacy or strict-canonical cache entry.

        ``canonical_key`` is caller-built (see ``generator.repair_cache_key``): it must
        already encode every stable part of the request that may change the reply.
        A canonical hit therefore never crosses model, endpoint, temperature or
        sample boundaries, and rollout/gate code still validates the program.
        """
        request = {"messages": messages, "temperature": temperature}
        key_material = {
            "key_schema": 2,
            "endpoint_host": urlparse(self.base_url).hostname or "",
            "model": self.model,
            "request": request,
            "sample_index": sample_index,
        }
        key = _sha(key_material)[:24]
        path = self.cache_dir / f"{key}.json"
        data = self._read_entry(path, key, request, sample_index)
        cache_kind = "exact" if data is not None else "miss"
        hit_key = key
        if data is None and sample_index == 0:
            legacy_key = hashlib.sha256(
                json.dumps([self.model, messages, temperature], sort_keys=True).encode("utf-8")
            ).hexdigest()[:24]
            legacy_path = self.cache_dir / f"{legacy_key}.json"
            if legacy_path != path:
                data = self._read_entry(legacy_path, legacy_key, request, sample_index)
                if data is not None:
                    cache_kind, hit_key = "legacy", legacy_key
        if data is None and canonical_key:
            found = self._find_canonical(canonical_key, temperature, sample_index)
            if found is not None:
                hit_key, data = found
                cache_kind = "canonical"
        if data is not None:
            reply = _reply_from(data, seconds=0.0, from_cache=True, cache_kind=cache_kind)
        else:
            self._spent = None  # re-read the ledger: another process may have spent
            if self.spent() >= self.token_budget:
                raise BudgetExceeded(f"token budget {self.token_budget} used up ({self.spent()})")
            data, seconds = self._post(messages, temperature)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            envelope = {
                "key_schema": 2,
                "cache_key": key,
                "canonical_key": canonical_key,
                "sample_index": sample_index,
                "endpoint_host": key_material["endpoint_host"],
                "model": self.model,
                "request": request,
                "response": data,
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "client_version": "llm.py:2",
            }
            tmp = self.cache_dir / f"{key}.tmp-{os.getpid()}"
            tmp.write_text(json.dumps(envelope), encoding="utf-8")
            os.replace(tmp, path)
            reply = _reply_from(data, seconds=seconds, from_cache=False)
            self._spent = self.spent() + reply.prompt_tokens + reply.completion_tokens
        self._append_ledger(tag, hit_key, reply, request, data, canonical_key)
        return reply

    def _append_ledger(
        self,
        tag: str,
        key: str,
        reply: Reply,
        request: dict,
        data: dict,
        canonical_key: str | None,
    ) -> None:
        messages = request["messages"]
        system = next((m.get("content") for m in messages if m.get("role") == "system"), "")
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "model": self.model,
                        "tag": tag,
                        "cache_key": key,
                        "cache_kind": reply.cache_kind,
                        "canonical_key": canonical_key or "",
                        "from_cache": reply.from_cache,
                        "prompt_tokens": reply.prompt_tokens,
                        "completion_tokens": reply.completion_tokens,
                        "cached_tokens": reply.cached_tokens,
                        "reasoning_tokens": reply.reasoning_tokens,
                        "seconds": reply.seconds,
                        "prompt_sha": _sha(messages),
                        "system_sha": _sha(system),
                        "response_model": data.get("model", ""),
                    }
                )
                + "\n"
            )

    def _read_entry(
        self, path: Path, key: str, request: dict | None, sample_index: int
    ) -> dict | None:
        """Return the stored API response, or None (quarantining a corrupt entry)."""
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("key_schema") == 2:
                if data.get("cache_key") != key or data.get("sample_index") != sample_index:
                    raise ValueError("cache key mismatch")
                if request is not None and data.get("request") != request:
                    raise ValueError("cache request mismatch")
                data = data["response"]
            if not data["choices"][0]["message"]["content"]:
                raise ValueError("cache response has no content")
            return data
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            try:
                os.replace(path, self.cache_dir / f"{key}.corrupt.json")
            except OSError:
                pass
            return None

    def _find_canonical(
        self, canonical_key: str, temperature: float, sample_index: int
    ) -> tuple[str, dict] | None:
        if not self.cache_dir.exists():
            return None
        host = urlparse(self.base_url).hostname or ""
        for path in sorted(self.cache_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict) or data.get("key_schema") != 2:
                continue
            request = data.get("request") or {}
            if (
                data.get("canonical_key") != canonical_key
                or data.get("model") != self.model
                or data.get("endpoint_host") != host
                or data.get("sample_index") != sample_index
                or request.get("temperature") != temperature
            ):
                continue
            response = self._read_entry(path, data.get("cache_key", ""), None, sample_index)
            if response is not None:
                return data["cache_key"], response
        return None

    def _post(self, messages: list[dict], temperature: float) -> tuple[dict, float]:
        body = json.dumps(
            {"model": self.model, "messages": messages, "temperature": temperature}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {os.environ[self.api_key_env]}",
                "Content-Type": "application/json",
            },
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data, round(time.time() - t0, 1)


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _reply_from(data: dict, seconds: float, from_cache: bool, cache_kind: str = "miss") -> Reply:
    usage = data.get("usage") or {}
    return Reply(
        text=data["choices"][0]["message"]["content"],
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        cached_tokens=int((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)),
        reasoning_tokens=int(
            (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
        ),
        seconds=seconds,
        from_cache=from_cache,
        raw=data,
        cache_kind=cache_kind,
    )


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ (only keys that are not set yet)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
