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

META_BASE_URL = "https://api.meta.ai/v1"


class BudgetExceeded(RuntimeError):
    """Raised before a call that would start once the token budget is used up."""


@dataclass
class Reply:
    text: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    seconds: float
    from_cache: bool


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

    def chat(self, messages: list[dict], temperature: float = 0.2, tag: str = "") -> Reply:
        key = hashlib.sha256(
            json.dumps([self.model, messages, temperature], sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            reply = _reply_from(data, seconds=0.0, from_cache=True)
        else:
            if self.spent() >= self.token_budget:
                raise BudgetExceeded(f"token budget {self.token_budget} used up ({self.spent()})")
            data, seconds = self._post(messages, temperature)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
            reply = _reply_from(data, seconds=seconds, from_cache=False)
            self._spent = self.spent() + reply.prompt_tokens + reply.completion_tokens
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "model": self.model,
                        "tag": tag,
                        "cache_key": key,
                        "from_cache": reply.from_cache,
                        "prompt_tokens": reply.prompt_tokens,
                        "completion_tokens": reply.completion_tokens,
                        "cached_tokens": reply.cached_tokens,
                        "seconds": reply.seconds,
                    }
                )
                + "\n"
            )
        return reply

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


def _reply_from(data: dict, seconds: float, from_cache: bool) -> Reply:
    usage = data.get("usage") or {}
    return Reply(
        text=data["choices"][0]["message"]["content"],
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        cached_tokens=int((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)),
        seconds=seconds,
        from_cache=from_cache,
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
