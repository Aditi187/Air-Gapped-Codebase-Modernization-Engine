from __future__ import annotations

import atexit
import importlib
import logging
import os
import re
from importlib import metadata as importlib_metadata
from typing import Any

_LOG = logging.getLogger(__name__)
_DEFAULT_TRACE_NAME = "CPP-Modernization"
_MIN_LANGFUSE_VERSION = (2, 0, 0)


def _parse_version(raw: str) -> tuple[int, int, int]:
    parts = [int(p) for p in raw.split(".") if p.isdigit()][:3]
    parts += [0] * (3 - len(parts))
    return parts[0], parts[1], parts[2]


def _is_supported_version() -> bool:
    try:
        return _parse_version(importlib_metadata.version("langfuse")) >= _MIN_LANGFUSE_VERSION
    except Exception:
        return False


def parse_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw or default)
    except ValueError:
        _LOG.warning("Invalid %s, using default=%d", name, default)
        return default


def expects_large_code_response(prompt: str) -> bool:
    triggers = os.environ.get("LLM_LARGE_RESPONSE_TRIGGERS", "")
    words = [w.strip().lower() for w in triggers.split(",") if w.strip()] or [
        "entire file", "full file", "whole file",
        "full updated code", "single function",
        "```cpp", "write_code", "modernize",
    ]
    prompt_lower = prompt.lower()
    return any(w in prompt_lower for w in words)


def _trace_ctx(trace: Any):
    return {"trace_id": str(trace["trace_id"])} if isinstance(trace, dict) and trace.get("trace_id") else None


def _trace_id(trace: Any) -> str | None:
    if isinstance(trace, dict) and trace.get("trace_id"):
        return str(trace["trace_id"])
    return None


def _safe_call(method: Any, kwargs: dict):
    while True:
        try:
            method(**kwargs)
            return
        except TypeError as e:
            msg = str(e)
            if "output" in kwargs and "output_data" not in kwargs:
                kwargs["output_data"] = kwargs.pop("output")
                continue
            bad = re.search(r"'([^']+)'", msg)
            if bad:
                kwargs.pop(bad.group(1), None)
                continue
            if kwargs:
                kwargs.clear()
                continue
            raise


try:
    Langfuse = getattr(importlib.import_module("langfuse"), "Langfuse", None)
except Exception:
    Langfuse = None


class LangfuseTracker:
    def __init__(self, logger: logging.Logger | None = None):
        self.log = logger or _LOG
        self.client = None
        self.auto_flush = os.getenv("LANGFUSE_AUTO_FLUSH", "1").lower() in {"1", "true"}

        pub = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        sec = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        host = os.getenv("LANGFUSE_HOST", "").strip()

        if not (pub and sec and host and Langfuse and _is_supported_version()):
            self.log.info("Langfuse disabled.")
            return

        try:
            self.client = Langfuse(public_key=pub, secret_key=sec, host=host)
            atexit.register(self.flush)
            self.log.info("Langfuse initialized.")
        except Exception as exc:
            self.log.exception("Init failed: %r", exc)

    def enabled(self):
        return self.client is not None

    def _flush(self):
        if self.auto_flush:
            self.flush()

    def flush(self):
        if self.enabled():
            try:
                self.client.flush()
            except Exception as exc:
                self.log.exception("Flush failed: %r", exc)

    def create_trace(self, name=None, input_data=None, input_payload=None, **_kwargs):
        if not self.enabled():
            return None
        try:
            payload = input_data if input_data is not None else input_payload
            if hasattr(self.client, "trace"):
                return self.client.trace(name=name or _DEFAULT_TRACE_NAME, input=payload)
            if hasattr(self.client, "create_trace_id"):
                trace_id = str(self.client.create_trace_id())
                # For newer SDKs, emit an explicit root span so traces are visible and searchable.
                if hasattr(self.client, "start_observation"):
                    try:
                        root = self.client.start_observation(
                            trace_context={"trace_id": trace_id},
                            name=name or _DEFAULT_TRACE_NAME,
                            as_type="span",
                            input=payload,
                            metadata={"source": "workflow"},
                        )
                        if hasattr(root, "end"):
                            _safe_call(root.end, {})
                    except Exception as obs_exc:
                        self.log.exception("Root observation create failed: %r", obs_exc)
                return {"trace_id": trace_id, "name": name or _DEFAULT_TRACE_NAME, "input": payload}
            return {"trace_id": None, "name": name or _DEFAULT_TRACE_NAME, "input": payload}
        except Exception as exc:
            self.log.exception("Trace failed: %r", exc)
            return None

    def start_span(self, trace=None, name=None, input_data=None, input_payload=None, **_kwargs):
        if not trace:
            return None
        try:
            payload = input_data if input_data is not None else input_payload
            if hasattr(trace, "span"):
                return trace.span(name=name, input=payload)
            ctx = _trace_ctx(trace)
            if ctx:
                return self.client.start_observation(trace_context=ctx, name=name, as_type="span", input=payload)
        except Exception as exc:
            self.log.exception("Span failed: %r", exc)

    def end_span(self, span=None, output=None, output_payload=None, input_data=None, input_payload=None, level=None, **_kwargs):
        if span and hasattr(span, "end"):
            try:
                payload = output if output is not None else output_payload
                kwargs = {"output": payload} if payload is not None else {}
                if input_data is not None or input_payload is not None:
                    kwargs["input"] = input_data if input_data is not None else input_payload
                if level is not None:
                    kwargs["level"] = level
                _safe_call(span.end, kwargs)
                self._flush()
            except Exception as exc:
                self.log.exception("End span failed: %r", exc)

    def create_generation(self, trace=None, name=None, model=None, input_data=None, input_payload=None, metadata=None, **_kwargs):
        if not trace:
            return None
        try:
            payload = input_data if input_data is not None else input_payload
            if hasattr(trace, "generation"):
                kwargs = {"name": name, "model": model, "input": payload}
                if metadata is not None:
                    kwargs["metadata"] = metadata
                return trace.generation(**kwargs)
            ctx = _trace_ctx(trace)
            if ctx:
                kwargs = {
                    "trace_context": ctx,
                    "name": name,
                    "as_type": "generation",
                    "model": model,
                    "input": payload,
                }
                if metadata is not None:
                    kwargs["metadata"] = metadata
                return self.client.start_observation(**kwargs)
        except Exception as exc:
            self.log.exception("Gen failed: %r", exc)

    def finalize_generation(self, gen=None, output=None, usage_details=None, model=None, metadata=None, level=None, status_message=None, **_kwargs):
        if gen:
            try:
                fn = getattr(gen, "end", None) or getattr(gen, "update", None)
                if fn:
                    kwargs = {"output": output} if output is not None else {}
                    if usage_details is not None:
                        kwargs["usage_details"] = usage_details
                    if model is not None:
                        kwargs["model"] = model
                    if metadata is not None:
                        kwargs["metadata"] = metadata
                    if level is not None:
                        kwargs["level"] = level
                    if status_message is not None:
                        kwargs["status_message"] = status_message
                    _safe_call(fn, kwargs)
                    self._flush()
            except Exception as exc:
                self.log.exception("Finalize failed: %r", exc)

    def mark_error(self, trace=None, msg=None, message=None, details=None, **_kwargs):
        if trace and hasattr(trace, "update"):
            try:
                trace.update(output={"error": message if message is not None else msg, "details": details})
                self._flush()
                return
            except Exception as exc:
                self.log.exception("Error mark failed: %r", exc)

        trace_id = _trace_id(trace)
        if trace_id and self.enabled() and hasattr(self.client, "start_observation"):
            try:
                err_obs = self.client.start_observation(
                    trace_context={"trace_id": trace_id},
                    name="workflow-error",
                    as_type="span",
                    output={"error": message if message is not None else msg, "details": details},
                    level="ERROR",
                )
                if hasattr(err_obs, "end"):
                    _safe_call(err_obs.end, {})
                self._flush()
            except Exception as exc:
                self.log.exception("Error mark failed: %r", exc)