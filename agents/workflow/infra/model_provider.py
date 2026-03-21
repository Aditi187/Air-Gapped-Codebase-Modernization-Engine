import os
import re
import time
import random
import hashlib
import threading
from typing import Any, Dict, Tuple, Optional, Callable
from functools import lru_cache

from core.openai_bridge import OpenAIBridge
from core.logger import get_logger
from agents.workflow.context import WorkflowContext
from agents.workflow.infra.exceptions import (
    ProviderError, RateLimitError, ProviderQuotaExhaustedError, ModelUnavailableError
)

# Fix 4: Import rule modernizer for fallback
try:
    from core.rule_modernizer import RuleModernizer
except ImportError:
    RuleModernizer = None

logger = get_logger(__name__)

# Fix 6 (Round 1): Code-block regex for stripping markdown fences from LLM output
_CODE_FENCE_RE = re.compile(r"```(?:cpp|c\+\+|cxx|cc|hpp|h)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)

# Fix 3 (Round 2): Extremely strict production-grade modernization prompt
_MODERNIZATION_ENFORCEMENT = """
You are a C++ modernization engine.

STRICT REQUIREMENTS:
- You MUST modify the code if any modernization is possible.
- Replace raw pointers with smart pointers (std::unique_ptr, std::shared_ptr).
- Replace manual memory management (malloc/free/new/delete) with RAII.
- Replace C-style arrays or raw pointers-as-arrays with STL containers (std::vector, std::array).
- Use modern C++17+ features (auto, nullptr, range-based for, std::optional).

OUTPUT FORMAT:
- ONLY return valid C++ code.
- NO explanations, no preambles, no markdown fences.
- NO comments outside code.

If and ONLY if absolutely no modernization is possible:
return EXACTLY: NO_CHANGE

Code to modernize:
"""

# Bridge creation lock for thread safety
_bridge_lock = threading.Lock()


class RetryHandler:
    @staticmethod
    def execute(func: Callable, max_attempts: int = 3, base_wait: float = 2.0) -> Any:
        last_error = None
        for attempt in range(max_attempts):
            try:
                return func()
            except (RateLimitError, ProviderQuotaExhaustedError, ModelUnavailableError) as e:
                last_error = e
                sleep_time = (2 ** attempt) * base_wait + random.uniform(0.1, 1.0)
                logger.warning(
                    "Retriable provider error (attempt %d/%d): %s. Retrying in %.2fs...",
                    attempt + 1, max_attempts, str(e), sleep_time
                )
                time.sleep(sleep_time)
            except Exception as e:
                raise e
        
        # Fix 7 (Round 2): Raise the last_error directly to preserve its type
        if last_error:
            raise last_error
        raise ProviderError(f"Max attempts ({max_attempts}) reached with unknown error")


class ModelClient:
    def __init__(self, context: WorkflowContext):
        self.context = context
        # Fix 4: Initialize optional rule modernizer instance
        self._rule_engine = RuleModernizer() if RuleModernizer else None

    @staticmethod
    def _classify_error(e: Exception) -> ProviderError:
        msg = str(e).lower()
        if "429" in msg or "rate limit" in msg or "timeout" in msg:
            return RateLimitError(message=str(e))
        elif "quota" in msg or "402" in msg or "provider_quota_exhausted" in msg:
            return ProviderQuotaExhaustedError(message=str(e))
        elif "unavailable" in msg or "503" in msg or "model_unavailable" in msg:
            return ModelUnavailableError(message=str(e))
        return ProviderError(message=str(e))

    @staticmethod
    def _extract_code(text: str) -> str:
        if not text:
            return ""
        # Fix 8 (Round 2): Clean regex extraction with correct fallback (already improved)
        m = _CODE_FENCE_RE.search(text)
        if m:
            return m.group(1).strip()
        return text.strip()

    # Fix 2 (Round 2): Strong code validation (must have class/brace or NO_CHANGE)
    @staticmethod
    def _is_valid_code(output: str) -> bool:
        if not output:
            return False
        stripped = output.strip()
        if stripped == "NO_CHANGE":
            return True
        if len(stripped) < 20:
            return False
        # Heuristic: valid code blocks usually have braces or class declarations or semi-colons
        if "{" not in stripped and "class" not in stripped.lower() and ";" not in stripped:
            return False
        return True

    def _role_extra_params(self, role: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        max_tokens = os.environ.get(f"{role.upper()}_MAX_TOKENS", "").strip()
        if max_tokens:
            try:
                params["max_tokens"] = max(1, int(max_tokens))
            except ValueError:
                pass
        top_p = os.environ.get(f"{role.upper()}_TOP_P", "").strip()
        if top_p:
            try:
                params["top_p"] = float(top_p)
            except ValueError:
                pass
        thinking_enabled = os.environ.get(f"{role.upper()}_ENABLE_THINKING", "false").strip().lower() == "true"
        if role == "analyzer" and os.environ.get("ANALYZER_THINKING", "true").strip().lower() == "true":
            thinking_enabled = True
        if thinking_enabled:
            thinking_key = os.environ.get(f"{role.upper()}_THINKING_KEY", "").strip() or (
                "thinking" if role == "analyzer" else "enable_thinking"
            )
            params["chat_template_kwargs"] = {thinking_key: True}
        if role == "analyzer":
            effort = os.environ.get("ANALYZER_REASONING_EFFORT", "high").strip()
            if effort:
                params["reasoning_effort"] = effort
        return params

    def _role_temperature(self, role: str) -> float:
        raw = os.environ.get(f"{role.upper()}_TEMPERATURE", "").strip()
        if raw:
            try:
                return max(0.0, min(1.0, float(raw)))
            except ValueError:
                pass
        return self.context.config.temperature

    def _get_api_config(self, role: str) -> Tuple[str, str, str]:
        key = os.environ.get(f"{role.upper()}_API_KEY", "").strip() or os.environ.get("API_KEY", "").strip()
        endpoint = os.environ.get(f"{role.upper()}_ENDPOINT_BASE", "").strip() or os.environ.get("OPENAI_ENDPOINT_BASE", "").strip()
        model = os.environ.get(f"{role.upper()}_MODEL", "").strip() or {
            "analyzer":   "deepseek-ai/deepseek-v3.2",
            "modernizer": "meta/llama-3.3-70b-instruct",
            "fixer":      "meta/llama-3.3-70b-instruct",
        }.get(role, "meta/llama-3.3-70b-instruct")
        return key, endpoint, model

    def _build_role_bridge(self, role: str) -> Any:
        key, endpoint, model = self._get_api_config(role)
        cache_key = f"{role}|{endpoint}|{model}|{hashlib.sha256(key.encode('utf-8')).hexdigest() if key else 'no-key'}"
        if cache_key in self.context.role_bridges:
            return self.context.role_bridges[cache_key]
        with _bridge_lock:
            if cache_key in self.context.role_bridges:
                return self.context.role_bridges[cache_key]
            try:
                bridge = OpenAIBridge(api_key=key, endpoint_base=endpoint, model=model, log_fn=logger.info)
            except TypeError:
                original = {
                    "API_KEY": os.environ.get("API_KEY"),
                    "OPENAI_ENDPOINT_BASE": os.environ.get("OPENAI_ENDPOINT_BASE"),
                    "OPENAI_MODELS": os.environ.get("OPENAI_MODELS"),
                }
                try:
                    os.environ["API_KEY"] = key
                    os.environ["OPENAI_ENDPOINT_BASE"] = endpoint
                    os.environ["OPENAI_MODELS"] = model
                    bridge = OpenAIBridge.from_env(log_fn=logger.info)
                finally:
                    for env_key, old_val in original.items():
                        if old_val is not None: os.environ[env_key] = old_val
                        else: os.environ.pop(env_key, None)
            self.context.role_bridges[cache_key] = bridge
            return bridge

    def call(self, system_prompt: str, user_prompt: str, role: str = "modernizer") -> Optional[str]:
        extra_params = self._role_extra_params(role)
        role_temp = self._role_temperature(role)
        _, _, actual_model = self._get_api_config(role)

        prompt_hash = hashlib.sha256(
            f"{role}:{system_prompt}:{user_prompt}:{role_temp}:{sorted(extra_params.items())}".encode("utf-8")
        ).hexdigest()
        
        if prompt_hash in self.context.llm_cache:
            logger.info("Cache hit for model call (role=%s).", role)
            return self.context.llm_cache[prompt_hash]

        span = self.context.tracer.start_span(
            name=f"{role}_call",
            input_payload={"role": role, "prompt_chars": len(user_prompt or "")},
            span_type="generation"
        )

        if role in ("modernizer", "fixer"):
            enforced_prompt = _MODERNIZATION_ENFORCEMENT + user_prompt
        else:
            enforced_prompt = user_prompt

        try:
            bridge = self._build_role_bridge(role)

            def attempt_call() -> Optional[str]:
                try:
                    raw = bridge.chat_completion(
                        system_prompt,
                        enforced_prompt,
                        temperature=role_temp,
                        extra_params=extra_params,
                    )
                except Exception as e:
                    raise ModelClient._classify_error(e) from e

                output = ModelClient._extract_code(raw) or raw.strip()

                # Fix 2 (Round 2): Stronger validation
                if not ModelClient._is_valid_code(output):
                    logger.warning("LLM returned invalid/trivial code (chars=%d). Retrying...", len(output))
                    raise ProviderError("Invalid LLM modernization output")

                # Fix 1 (Round 2): Return None for NO_CHANGE
                if output.strip() == "NO_CHANGE":
                    logger.info("LLM signaled NO_CHANGE for role=%s.", role)
                    return None

                return output

            output = RetryHandler.execute(attempt_call, max_attempts=3)

            # Fix 4 (Round 2): Fallback to rule-based system if LLM returns None (NO_CHANGE)
            if output is None and role == "modernizer":
                logger.info("LLM returned NO_CHANGE → Attempting rule-based fallback rewrite.")
                if self._rule_engine:
                    try:
                        # We pass the user_prompt (which is the source code) to the rule engine
                        output = self._rule_engine.modernize_text(user_prompt)
                        logger.info("Rule-based fallback successful.")
                    except Exception as re_err:
                        logger.warning("Rule-based fallback failed: %s", re_err)
                else:
                    logger.warning("RuleModernizer not available for fallback.")

            self.context.tracer.finish_span(span, output=output or "NO_CHANGE (after fallbacks)")

            # Fix 6 (Round 2): More realistic token estimation (/ 3.5)
            prompt_tokens = max(1, int(len(system_prompt + enforced_prompt) / 3.5))
            completion_tokens = max(1, int(len(output or "") / 3.5))
            self.context.tracer.track_cost(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=actual_model,
            )

            # Fix 5 (Round 2): Only cache successful modernizations
            if output and output.strip() != user_prompt.strip():
                self.context.llm_cache[prompt_hash] = output
            
            return output

        except (KeyboardInterrupt, SystemExit):
            self.context.tracer.finish_span(span, err=RuntimeError("interrupted"))
            raise
        except Exception as e:
            self.context.tracer.trace_event("error", {"error": str(e), "role": role})
            self.context.tracer.finish_span(span, err=e)
            raise

    def check_health(self) -> bool:
        bridge = self._build_role_bridge("modernizer")
        try:
            response = bridge.chat_completion(
                system_prompt="You are a health-check assistant.",
                user_prompt="Reply with exactly: OK",
                temperature=0.0,
            )
            is_healthy = "ok" in response.strip().lower()
            log_fn = logger.info if is_healthy else logger.error
            log_fn("[modernizer] %s health probe response: %r", "✅" if is_healthy else "❌", response[:80])
            return is_healthy
        except Exception as e:
            logger.error("[modernizer] ❌ Health check failed: %s", e)
            return False
