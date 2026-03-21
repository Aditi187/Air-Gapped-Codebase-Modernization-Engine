import os
import uuid
import random
from typing import Any, Optional
from core.logger import get_logger

logger = get_logger(__name__)

try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

# Model-aware pricing table
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "qwen/qwen3.5-122b-a10b":    (0.001, 0.002),
    "gpt-4o":                     (0.005, 0.015),
    "gpt-4o-mini":                (0.00015, 0.0006),
    "gpt-4-turbo":                (0.010, 0.030),
    "claude-3-5-sonnet-20241022": (0.003, 0.015),
    "claude-3-haiku-20240307":    (0.00025, 0.00125),
}
_DEFAULT_PRICING = (0.001, 0.002)


class TracingWrapper:
    """Production-grade Langfuse tracing wrapper.

    Design principles (Phase 3 improvements):
    - Fix 1: '_ended' flag protection to prevent double-ending in SDK
    - Fix 2: Metadata merging (don't overwrite existing meta with cost)
    - Fix 3: Auto-detect span_type based on name ('llm'/'call' -> generation)
    - Fix 4: Prefer span stack over _current_trace for consistent hierarchy
    - Fix 5: Tie loose events to the parent span via metadata
    - Fix 6: Safe payload truncation (2000 chars) for performance
    - Fix 7: Sampling support (via TRACE_SAMPLE_RATE env)
    - Fix 8: Exposed get_trace_id() for system-wide correlation
    """

    def __init__(self, client: Optional[Any] = None):
        self._client = client
        self._current_trace: Any = None
        self._trace_id: str = str(uuid.uuid4())
        self._span_stack: list[Any] = []
        
        # Build sampling config (Fix 7)
        try:
            self._sample_rate = float(os.environ.get("TRACE_SAMPLE_RATE", "1.0"))
        except ValueError:
            self._sample_rate = 1.0
        self._is_sampled = random.random() <= self._sample_rate

        if Langfuse is not None and not self._client and self._is_sampled:
            try:
                self._client = Langfuse()
            except Exception as e:
                logger.debug("Langfuse client init failed: %s", e)

    def get_trace_id(self) -> str:
        """Expose current trace_id for correlation (Fix 8)."""
        return self._trace_id

    def _safe_payload(self, payload: Any) -> Any:
        """Truncate large payloads to 2000 chars to avoid UI lag (Fix 6)."""
        if payload is None:
            return None
        s = str(payload)
        if len(s) > 2000:
            return s[:2000] + " ... [TRUNCATED]"
        return payload

    # -------------------------------------------------------------------------
    # Trace lifecycle
    # -------------------------------------------------------------------------
    def start_workflow_trace(self, project_name: str = "air-gapped-engine") -> None:
        self._trace_id = str(uuid.uuid4())
        self._span_stack = []
        self._is_sampled = random.random() <= self._sample_rate

        if not self._client or not self._is_sampled:
            logger.debug("Tracing disabled (sampled=%s) — local trace_id=%s", self._is_sampled, self._trace_id)
            return

        metadata = {
            "project": project_name,
            "env": os.getenv("ENV", "dev"),
            "user": os.getenv("LANGFUSE_USER", "system"),
            "version": os.getenv("APP_VERSION", "0.1.0"),
        }

        try:
            trace_fn = getattr(self._client, "trace", None)
            if callable(trace_fn):
                self._current_trace = trace_fn(
                    name="modernization-workflow",
                    metadata=metadata,
                )
                return

            if hasattr(self._client, "create_trace_id"):
                self._trace_id = str(self._client.create_trace_id())

            if hasattr(self._client, "start_observation"):
                root = self._client.start_observation(
                    trace_context={"trace_id": self._trace_id},
                    name="modernization-workflow",
                    as_type="span",
                    metadata=metadata,
                )
                if root is not None:
                    self._span_stack.append(root)
        except Exception as exc:
            logger.debug("Langfuse trace init failed: %s", exc)

    # -------------------------------------------------------------------------
    # Span creation
    # -------------------------------------------------------------------------
    def start_span(
        self,
        name: str,
        input_payload: Any = None,
        span_type: Optional[str] = None,
    ) -> Any:
        """Start a named span. Auto-detects 'generation' if type not provided (Fix 3)."""
        if not self._is_sampled:
            return None

        # Fix 3: Auto-detect generation type
        if span_type is None:
            lower_name = name.lower()
            if "llm" in lower_name or "call" in lower_name or "generate" in lower_name:
                span_type = "generation"
            else:
                span_type = "span"

        # Fix 6: Safe payload
        safe_input = self._safe_payload(input_payload)
        span = None

        # Fix 4: Prefer stack/observation model for consistent nested hierarchy
        if self._client is not None and hasattr(self._client, "start_observation"):
            try:
                parent_id = (
                    getattr(self._span_stack[-1], "id", None)
                    if self._span_stack else None
                )
                try:
                    span = self._client.start_observation(
                        trace_context={"trace_id": self._trace_id},
                        parent_observation_id=parent_id,
                        name=name,
                        as_type=span_type,
                        input=safe_input,
                    )
                except TypeError:
                    span = self._client.start_observation(
                        trace_context={"trace_id": self._trace_id},
                        name=name,
                        as_type=span_type,
                        input=safe_input,
                    )
            except Exception as e:
                logger.debug("Langfuse start_observation failed: %s", e)

        # Fallback to trace object if observation failed and trace exists
        if span is None and self._current_trace is not None:
            try:
                if span_type == "generation":
                    gen_fn = getattr(self._current_trace, "generation", None)
                    if callable(gen_fn):
                        span = gen_fn(name=name, input=safe_input)
                else:
                    span_fn = getattr(self._current_trace, "span", None)
                    if callable(span_fn):
                        span = span_fn(name=name, input=safe_input)
            except Exception as e:
                logger.debug("Langfuse trace.%s failed: %s", span_type, e)

        if span is not None:
            # Fix 1: protection flag
            setattr(span, "_ended", False)
            self._span_stack.append(span)
        return span

    def finish_span(self, span: Any, output: Any = None, err: Exception | None = None) -> None:
        """Finish a span. Safe to call multiple times (Fix 1)."""
        if span is None or getattr(span, "_ended", False):
            return
        
        try:
            safe_output = self._safe_payload(output)
            if err is not None and hasattr(span, "update"):
                span.update(level="ERROR", status_message=str(err), output=str(safe_output) if safe_output else None)
            elif hasattr(span, "update"):
                span.update(output=safe_output)
            
            if hasattr(span, "end"):
                span.end()
                setattr(span, "_ended", True) # Fix 1
        except Exception as e:
            logger.debug("Langfuse finish_span failed: %s", e)

        if self._span_stack and self._span_stack[-1] is span:
            self._span_stack.pop()

    # -------------------------------------------------------------------------
    # Events
    # -------------------------------------------------------------------------
    def trace_event(self, name: str, metadata: dict[str, Any] | None = None) -> None:
        if not self._is_sampled:
            return
            
        meta = metadata or {}
        
        # Fix 5: Tie loose events to active span hierarchy
        if self._span_stack:
            parent_id = getattr(self._span_stack[-1], "id", None)
            if parent_id:
                meta["parent_span_id"] = parent_id

        if self._current_trace is None and not self._span_stack:
            logger.debug("[TRACE EVENT] %s: %s", name, meta)
            return

        # Prefer observation-based events attached to stack
        if self._client is not None and hasattr(self._client, "start_observation"):
            try:
                parent_id = getattr(self._span_stack[-1], "id", None) if self._span_stack else None
                try:
                    self._client.start_observation(
                        trace_context={"trace_id": self._trace_id},
                        parent_observation_id=parent_id,
                        name=name,
                        as_type="event",
                        metadata=meta,
                    )
                    return
                except TypeError:
                    self._client.start_observation(
                        trace_context={"trace_id": self._trace_id},
                        name=name,
                        as_type="event",
                        metadata=meta,
                    )
                    return
            except Exception as e:
                logger.debug("Langfuse observation event failed: %s", e)

        if self._current_trace is not None:
            try:
                event_fn = getattr(self._current_trace, "event", None)
                if callable(event_fn):
                    event_fn(name=name, metadata=meta)
            except Exception as e:
                logger.debug("Langfuse trace.event failed: %s", e)

    # -------------------------------------------------------------------------
    # Cost tracking
    # -------------------------------------------------------------------------
    def track_cost(self, prompt_tokens: int, completion_tokens: int, model: str) -> None:
        """Log cost and attach it to the active span metadata (Fix 2/5)."""
        in_price, out_price = MODEL_PRICING.get(model, _DEFAULT_PRICING)
        estimated_cost = (prompt_tokens * in_price / 1000) + (completion_tokens * out_price / 1000)
        cost_meta = {
            "model": model,
            "tokens": {"prompt": prompt_tokens, "completion": completion_tokens, "total": prompt_tokens + completion_tokens},
            "usd": round(estimated_cost, 6),
        }

        # Fix 2: Merge metadata instead of overwriting
        if self._span_stack:
            active_span = self._span_stack[-1]
            try:
                if hasattr(active_span, "update"):
                    # Attempt to preserve existing metadata if SDK allows access
                    meta_attr = getattr(active_span, "metadata", {})
                    existing = meta_attr if isinstance(meta_attr, dict) else {}
                    existing["cost"] = cost_meta
                    active_span.update(metadata=existing)
            except Exception:
                # If metadata retrieval fails, just try updating
                try: active_span.update(metadata={"cost": cost_meta})
                except: pass

        self.trace_event("cost", cost_meta)

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------
    def flush(self) -> None:
        while self._span_stack:
            span = self._span_stack.pop()
            # Fix 1: Protection check
            if not getattr(span, "_ended", False):
                try:
                    if hasattr(span, "end"):
                        span.end()
                        setattr(span, "_ended", True)
                except Exception as e:
                    logger.debug("Flush end span failed: %s", e)

        if self._current_trace is not None:
            try:
                if hasattr(self._current_trace, "end"):
                    self._current_trace.end()
            except Exception as e:
                logger.debug("Flush end trace failed: %s", e)

        if self._client is not None:
            try:
                if hasattr(self._client, "flush"):
                    self._client.flush()
            except Exception as e:
                logger.debug("Flush client failed: %s", e)

        self._current_trace = None
        self._trace_id = str(uuid.uuid4())
        self._span_stack = []

    def log_diagnostics(self) -> None:
        public_key = bool(os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip())
        secret_key = bool(os.environ.get("LANGFUSE_SECRET_KEY", "").strip())
        logger.info(
            "Langfuse diagnostics: sampled=%s sdk=%s public=%s secret=%s host=%s trace_id=%s depth=%d",
            self._is_sampled,
            "yes" if Langfuse is not None else "no",
            "yes" if public_key else "no",
            "yes" if secret_key else "no",
            os.environ.get("LANGFUSE_HOST", "default"),
            self._trace_id,
            len(self._span_stack),
        )
