"""Meta Model API adapter (Muse Spark), OpenAI-compatible chat completions, standard library only.

Same request format, disk cache and token ledger as System 1's client (`synthesizer/llm.py`), and by
default the same ledger file, so both systems spend from one visible budget. A hard token budget
is checked before every uncached call.

Effort levels map to request settings per call:
- FAST (explainer) and DELIBERATE (diagnoser): one call each.
- PARALLEL (proposer agents): `n` independent calls run concurrently.
How the API selects Muse Spark's Instant / Thinking / Contemplating modes is not documented in this
repo, so `EffortSetting.extra` is empty by default and nothing unconfirmed is sent. Run
`uv run python -m ants.adversary.models.probe` where the key is set to test candidate settings,
then put the accepted ones here.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ants.adversary.models.base import Effort, Message, ModelError, ModelResponse

META_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"


class BudgetExceeded(ModelError):
    """The token budget is used up; raised before the call that would exceed it."""


@dataclass(frozen=True)
class EffortSetting:
    model: str = DEFAULT_MODEL
    temperature: float = 0.2
    extra: Mapping[str, Any] = field(default_factory=dict)  # e.g. a confirmed reasoning-mode field


DEFAULT_EFFORTS: dict[Effort, EffortSetting] = {
    Effort.FAST: EffortSetting(temperature=0.3),
    Effort.DELIBERATE: EffortSetting(temperature=0.2),
    Effort.PARALLEL: EffortSetting(temperature=0.8),
}


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ, keeping keys already set. Values are never logged."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class MetaModel:
    cache_dir: Path = Path("data/llm_cache")
    ledger: Path = Path("data/llm_ledger.jsonl")
    token_budget: int = 2_000_000
    efforts: Mapping[Effort, EffortSetting] = field(default_factory=lambda: dict(DEFAULT_EFFORTS))
    base_url: str = META_BASE_URL
    api_key_env: str = "META_API_KEY"
    timeout_s: float = 600.0
    tag: str = "system2"
    name: str = "muse-spark"
    _spent: int | None = field(default=None, repr=False)

    # --- public ------------------------------------------------------------------------------
    def complete(
        self,
        messages: Sequence[Message],
        effort: Effort = Effort.FAST,
        json_schema: Mapping[str, Any] | None = None,
        n: int = 1,
    ) -> ModelResponse:
        setting = self.efforts[effort]
        payload = [self._message(m) for m in messages]
        if json_schema is not None:
            payload = [*payload, {"role": "system", "content": "Reply with one JSON object only."}]
        if n == 1:
            replies = [self._call(payload, setting, 0)]
        else:
            with ThreadPoolExecutor(max_workers=min(n, 8)) as pool:
                replies = list(pool.map(lambda i: self._call(payload, setting, i), range(n)))
        usage = {
            k: sum(r["usage"].get(k, 0) for r in replies)
            for k in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_calls")
        }
        return ModelResponse(tuple(r["text"] for r in replies), setting.model, usage)

    def spent(self) -> int:
        if self._spent is None:
            self._spent = 0
            if self.ledger.exists():
                for line in self.ledger.read_text(encoding="utf-8").splitlines():
                    entry = json.loads(line)
                    if not entry.get("from_cache"):
                        self._spent += entry["prompt_tokens"] + entry["completion_tokens"]
        return self._spent

    # --- internals ---------------------------------------------------------------------------
    def _message(self, m: Message) -> dict[str, Any]:
        if not m.images:
            return {"role": m.role, "content": m.content}
        parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
        for path in m.images:
            mime = mimetypes.guess_type(path)[0] or "image/png"
            data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
        return {"role": m.role, "content": parts}

    def _call(self, messages: list[dict], setting: EffortSetting, sample: int) -> dict[str, Any]:
        body = {
            "model": setting.model,
            "messages": messages,
            "temperature": setting.temperature,
            **setting.extra,
        }
        key = hashlib.sha256(
            json.dumps([body, sample], sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            data, seconds, cached = json.loads(path.read_text(encoding="utf-8")), 0.0, True
        else:
            if self.spent() >= self.token_budget:
                raise BudgetExceeded(f"token budget {self.token_budget} used up ({self.spent()})")
            data, seconds = self._post(body)
            cached = False
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError(f"unexpected response shape: {str(data)[:200]}") from exc
        usage = data.get("usage") or {}
        prompt, completion = (
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
        )
        reasoning = int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0))
        if not cached:
            self._spent = self.spent() + prompt + completion
        self._log(setting.model, key, cached, prompt, completion, reasoning, seconds)
        return {
            "text": text or "",
            "usage": {
                "prompt_tokens": 0 if cached else prompt,
                "completion_tokens": 0 if cached else completion,
                "reasoning_tokens": 0 if cached else reasoning,
                "cached_calls": int(cached),
            },
        }

    def _post(self, body: dict[str, Any]) -> tuple[dict, float]:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ModelError(f"{self.api_key_env} is not set")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise ModelError(f"HTTP {exc.code} from the Meta API: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ModelError(f"Meta API call failed: {exc}") from exc
        return data, round(time.time() - t0, 1)

    def _log(self, model, key, cached, prompt, completion, reasoning, seconds) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": model,
            "tag": self.tag,
            "cache_key": key,
            "from_cache": cached,
            "prompt_tokens": 0 if cached else prompt,
            "completion_tokens": 0 if cached else completion,
            "reasoning_tokens": 0 if cached else reasoning,
            "seconds": seconds,
        }
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
