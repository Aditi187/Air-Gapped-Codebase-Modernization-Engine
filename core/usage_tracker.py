from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple
import json
import os
import threading
import tempfile

_DEFAULT_USAGE_FILENAME = "token_usage.json"
_USAGE_LOCK = threading.Lock()

# Cost per 1K tokens (USD)
_MODEL_COSTS_PER_1K: dict[str, float] = {
    "gpt-4o": 0.0050,
    "gpt-4o-mini": 0.0006,
    "anthropic/claude-3.5-sonnet": 0.0090,
}


def _usage_path() -> Path:
    filename = os.environ.get("LLM_TOKEN_USAGE_FILE", "").strip() or _DEFAULT_USAGE_FILENAME
    return Path(os.getcwd()) / filename


def _current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")



def _load_usage() -> dict[str, Any]:
    path = _usage_path()
    if not path.exists():
        return {"months": {}}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("months"), dict):
            return data
    except Exception:
        pass

    return {"months": {}}


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Atomic write to prevent file corruption."""
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as tmp:
            json.dump(data, tmp, ensure_ascii=True, indent=2)
            temp_name = tmp.name
        Path(temp_name).replace(path)
    except Exception:
        pass


def _save_usage(data: dict[str, Any]) -> None:
    path = _usage_path()
    try:
        _atomic_write(path, data)
    except Exception:
        pass


def _resolve_model_cost_per_1k(model_name: str) -> float:
    normalized = (model_name or "").strip().lower()
    for key, cost in _MODEL_COSTS_PER_1K.items():
        if key in normalized:
            return cost
    return 0.0020  # default fallback


def estimate_call_cost_usd(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    total_tokens = max(0, int(prompt_tokens or 0)) + max(0, int(completion_tokens or 0))
    return round((total_tokens / 1000.0) * _resolve_model_cost_per_1k(model_name), 6)


def monthly_cost_limit_usd() -> float:
    raw = os.environ.get("LLM_MONTHLY_COST_LIMIT", "").strip()
    try:
        return max(0.0, float(raw)) if raw else 0.0
    except ValueError:
        return 0.0


def monthly_cost_warning_ratio() -> float:
    raw = os.environ.get("LLM_COST_WARNING_RATIO", "0.8").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 0.8
    return min(1.0, max(0.1, value))


def current_month_cost_usd() -> float:
    with _USAGE_LOCK:
        usage = _load_usage().get("months", {}).get(_current_month_key(), {})
        cost = usage.get("cost_usd", 0.0)
        try:
            return float(cost) if cost else 0.0
        except (TypeError, ValueError):
            return 0.0


def is_near_monthly_cost_limit() -> bool:
    limit = monthly_cost_limit_usd()
    if limit <= 0:
        return False
    return current_month_cost_usd() >= (limit * monthly_cost_warning_ratio())


def reorder_models_by_cost(models: list[str] | tuple[str, ...]) -> list[str]:
    indexed = list(enumerate(models))
    indexed.sort(key=lambda item: (_resolve_model_cost_per_1k(item[1]), item[0]))
    return [model for _, model in indexed]

def record_token_usage(
    *,
    provider: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> Tuple[float, float]:
    call_cost = estimate_call_cost_usd(model_name, prompt_tokens, completion_tokens)
    total_tokens = max(0, int(prompt_tokens or 0)) + max(0, int(completion_tokens or 0))

    with _USAGE_LOCK:
        usage = _load_usage()
        months = usage.setdefault("months", {})
        month_key = _current_month_key()

        month_bucket = months.setdefault(
            month_key,
            {"tokens": 0, "cost_usd": 0.0, "by_model": {}}
        )

        # Update totals
        month_bucket["tokens"] = (month_bucket.get("tokens", 0) or 0) + total_tokens
        month_bucket["cost_usd"] = round(
            (month_bucket.get("cost_usd", 0.0) or 0.0) + call_cost, 6
        )

        # Per-model tracking
        by_model = month_bucket.setdefault("by_model", {})
        model_bucket = by_model.setdefault(
            model_name,
            {"provider": provider, "tokens": 0, "cost_usd": 0.0}
        )

        model_bucket["provider"] = provider
        model_bucket["tokens"] = (model_bucket.get("tokens", 0) or 0) + total_tokens
        model_bucket["cost_usd"] = round(
            (model_bucket.get("cost_usd", 0.0) or 0.0) + call_cost, 6
        )

        _save_usage(usage)
        month_cost = month_bucket.get("cost_usd", 0.0)

    return call_cost, month_cost


def reset_usage_file() -> None:
    """Delete usage file (useful in testing/dev)."""
    with _USAGE_LOCK:
        path = _usage_path()
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass