"""
Multi-model LLM bridge for the Air-Gapped C++ Modernization Engine.

Role routing (from .env):
  analyze  → DeepSeek-V3   (deep reasoning, thinking mode)
  modernize → Llama-3.3-70B (code rewriting)
  fixer    → Qwen           (small compiler-error fixes)

Falls back to RuleModernizer if LLM is unavailable / returns invalid code.
"""
from __future__ import annotations

import logging
import os
import re
import time
import random
from typing import Optional, Tuple

from openai import OpenAI, RateLimitError as OpenAI_RateLimitError

from core.rule_modernizer import RuleModernizer
from agents.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(
    r"```(?:cpp|c\+\+|cxx|cc|hpp|h)?\s*\n?(.*?)```",
    re.DOTALL | re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProviderError(Exception): pass
class RateLimitError(ProviderError): pass
class ProviderQuotaExhaustedError(ProviderError): pass
class ModelUnavailableError(ProviderError): pass


# ---------------------------------------------------------------------------
# Per-role provider config (loaded once from env)
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()

def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key) or default)
    except ValueError:
        return default

def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key) or default)
    except ValueError:
        return default


class _RoleConfig:
    """Holds the model/endpoint/key/params for one role."""

    def __init__(self, prefix: str, fallback_key: str, fallback_url: str, fallback_model: str):
        self.api_key   = _env(f"{prefix}_API_KEY")   or _env(fallback_key)
        self.base_url  = _env(f"{prefix}_ENDPOINT_BASE") or fallback_url
        self.model     = _env(f"{prefix}_MODEL")     or fallback_model
        self.temp      = _env_float(f"{prefix}_TEMPERATURE", 0.1)
        self.top_p     = _env_float(f"{prefix}_TOP_P", 0.85)
        self.max_tokens = _env_int(f"{prefix}_MAX_TOKENS", 8192)
        self.thinking  = _env(f"{prefix}_ENABLE_THINKING") in ("1", "true", "yes")

    def client(self) -> OpenAI:
        return OpenAI(api_key=self.api_key, base_url=self.base_url)


_FALLBACK_URL   = "https://integrate.api.nvidia.com/v1"
_FALLBACK_KEY   = _env("API_KEY") or _env("OPENAI_API_KEY")

_ROLE_CONFIGS = {
    "analyzer":  _RoleConfig("ANALYZER",   "API_KEY", _FALLBACK_URL, "deepseek-ai/deepseek-v3"),
    "modernizer": _RoleConfig("MODERNIZER", "API_KEY", _FALLBACK_URL, "meta/llama-3.3-70b-instruct"),
    "fixer":     _RoleConfig("FIXER",      "API_KEY", _FALLBACK_URL, "qwen/qwen3-235b-a22b"),
}

# Default / planner role uses the global key + model
_DEFAULT_CONFIG = _RoleConfig("OPENAI", "API_KEY", _FALLBACK_URL, _env("OPENAI_MODELS", "meta/llama-3.3-70b-instruct"))


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _with_retry(fn, max_attempts: int = 3, base_wait: float = 2.0):
    last_err = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except OpenAI_RateLimitError as e:
            last_err = e
            wait = (2 ** attempt) * base_wait + random.uniform(0.5, 2.0)
            logger.warning("Rate-limited (attempt %d/%d). Waiting %.1fs…", attempt + 1, max_attempts, wait)
            time.sleep(wait)
        except Exception:
            raise
    raise RateLimitError(f"Rate limit persisted after {max_attempts} attempts: {last_err}")


# ---------------------------------------------------------------------------
# Core LLM call
# ---------------------------------------------------------------------------

def _call_llm(role: str, system: str, user: str) -> Optional[str]:
    cfg = _ROLE_CONFIGS.get(role, _DEFAULT_CONFIG)

    if not cfg.api_key:
        logger.warning("No API key for role=%s; skipping LLM call.", role)
        return None

    def _do_call():
        client = cfg.client()
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ]

        kwargs = dict(
            model=cfg.model,
            messages=messages,
            temperature=cfg.temp,
            top_p=cfg.top_p,
            max_tokens=cfg.max_tokens,
        )

        # DeepSeek thinking mode — pass extra param if enabled
        if cfg.thinking:
            kwargs["extra_body"] = {"thinking": {"type": "enabled", "budget_tokens": 2048}}

        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    try:
        raw = _with_retry(_do_call)
        logger.debug("LLM [%s/%s] returned %d chars.", role, cfg.model, len(raw))
        return raw
    except Exception as e:
        logger.error("LLM call failed for role=%s: %s", role, e)
        return None


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _extract_code(text: str) -> str:
    if not text:
        return ""
    m = _CODE_FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _is_valid_cpp(code: str) -> bool:
    s = code.strip()
    if not s or len(s) < 20:
        return False
    return ("{" in s or ";" in s) and s != "NO_CHANGE"


# ---------------------------------------------------------------------------
# Public ModelClient — drop-in replacement for the old stub
# ---------------------------------------------------------------------------

class ModelClient:
    """Routes LLM calls by role; falls back to RuleModernizer for code roles."""

    def __init__(self, context: WorkflowContext):
        self.context = context
        self._rules  = RuleModernizer()
        self._use_llm = getattr(context.config, "use_llm", True)

    # ------------------------------------------------------------------
    def call(self, system_prompt: str, user_prompt: str, role: str = "modernizer") -> Optional[str]:
        logger.info("ModelClient.call  role=%-12s  llm=%s", role, self._use_llm)

        # --- LLM path ---
        if self._use_llm:
            raw = _call_llm(role, system_prompt, user_prompt)
            if raw:
                code = _extract_code(raw) if role in ("modernizer", "fixer") else raw
                if role not in ("modernizer", "fixer") or _is_valid_cpp(code):
                    return code

        # --- Rule-based fallback (code roles only) ---
        if role in ("modernizer", "fixer"):
            m = _CODE_FENCE_RE.search(user_prompt)
            src = m.group(1) if m else user_prompt
            modernized = self._rules.modernize_text(src)
            logger.info("Fell back to RuleModernizer for role=%s.", role)
            return modernized

        return None

    # ------------------------------------------------------------------
    def check_health(self) -> Tuple[bool, str]:
        parts = []
        for role, cfg in _ROLE_CONFIGS.items():
            parts.append(f"{role}={cfg.model}")
        return True, "Multi-model bridge: " + " | ".join(parts)
