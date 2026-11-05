"""ToonForge cost tracking — every Meta Model API call lands here.

Pricing (contributor tier, dev runs):
    muse-spark-1.3-contributor  $0.10 / 1M input tokens, $0.20 / 1M output
    muse-image-1.0              $0.01 / image
Standard tier (muse-spark-1.3: $1.25/$4.25) is priced too, for final runs.

usage dicts come from the API responses (OpenAI format). completion_tokens
already includes reasoning tokens, so no separate accounting is needed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

PRICE_IN_PER_M = {
    "muse-spark-1.3-contributor": 0.10,
    "muse-spark-1.3": 1.25,
}
PRICE_OUT_PER_M = {
    "muse-spark-1.3-contributor": 0.20,
    "muse-spark-1.3": 4.25,
}
PRICE_PER_IMAGE = {
    "muse-image-1.0": 0.01,
}

COST_LOG_DEFAULT = "cost_log.jsonl"


def _model_key(model: str) -> str:
    for k in PRICE_IN_PER_M:
        if k in model:
            return k
    return "muse-spark-1.3-contributor"


def call_cost_usd(model: str, usage: dict | None, images: int = 0) -> float:
    """USD cost of one call from its usage dict (+ image count)."""
    key = _model_key(model)
    cost = 0.0
    if usage:
        cost += usage.get("prompt_tokens", 0) / 1e6 * PRICE_IN_PER_M[key]
        cost += usage.get("completion_tokens", 0) / 1e6 * PRICE_OUT_PER_M[key]
    if images:
        cost += images * PRICE_PER_IMAGE.get(model, 0.01)
    return cost


def log_call(stage: str, model: str, usage: dict | None = None,
             images: int = 0, *, log_path: str = COST_LOG_DEFAULT,
             note: str = "") -> float:
    """Append one call record to the JSONL cost log. Returns its USD cost."""
    cost = call_cost_usd(model, usage, images)
    record = {
        "ts": time.time(),
        "stage": stage,
        "model": model,
        "prompt_tokens": (usage or {}).get("prompt_tokens", 0),
        "completion_tokens": (usage or {}).get("completion_tokens", 0),
        "images": images,
        "cost_usd": round(cost, 6),
        "note": note,
    }
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return cost


def log_image(stage: str, model: str = "muse-image-1.0", *,
              log_path: str = COST_LOG_DEFAULT, note: str = "") -> float:
    """Shorthand for logging one image generation."""
    return log_call(stage, model, usage=None, images=1,
                    log_path=log_path, note=note)


def estimate_cost(log_path: str = COST_LOG_DEFAULT) -> dict:
    """Sum a cost log. Returns {total_usd, calls, images, by_stage}."""
    total, calls, images = 0.0, 0, 0
    by_stage: dict[str, float] = {}
    p = Path(log_path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            total += r.get("cost_usd", 0.0)
            calls += 1
            images += r.get("images", 0)
            by_stage[r.get("stage", "?")] = by_stage.get(r.get("stage", "?"), 0.0) \
                + r.get("cost_usd", 0.0)
    return {"total_usd": round(total, 4), "calls": calls, "images": images,
            "by_stage": {k: round(v, 4) for k, v in by_stage.items()}}
