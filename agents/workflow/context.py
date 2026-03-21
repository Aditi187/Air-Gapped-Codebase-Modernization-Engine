import os
import hashlib
import logging
from typing import Any, Dict, Optional, OrderedDict
from collections import OrderedDict

from agents.workflow.config import WorkflowConfig
from agents.workflow.infra.langfuse import TracingWrapper

logger = logging.getLogger(__name__)


class WorkflowContext:
    """
    Thread‑safe context container for the modernization workflow.

    Holds configuration, tracing, caches, and function‑level memory.
    """

    def __init__(self, config: Optional[WorkflowConfig] = None):
        self.config = config or WorkflowConfig.from_env()
        self.tracer = TracingWrapper()
        # Start a trace with a default project name; can be overridden later
        self.tracer.start_workflow_trace(project_name="air-gapped-engine")

        # Caches for LLM responses (prompt hash -> response)
        self.llm_cache: OrderedDict[str, str] = OrderedDict()
        self.max_cache_size = 1000  # prevent unbounded growth

        # Role bridges and fallback bridges for multi‑provider support (unused)
        self.role_bridges: Dict[str, Any] = {}
        self.fallback_bridges: Dict[str, Any] = {}

        # Function‑level memory to track attempts and stagnation
        # Structure: {function_name: {"attempts": int, "last_score": int,
        #                             "stagnation_count": int, "best_version": str}}
        self.function_memory: Dict[str, Dict[str, Any]] = {}

        # Primary provider (currently not used, but reserved)
        self.primary_provider = "openai"

    def get_function_memory(self, function_name: str) -> Dict[str, Any]:
        """
        Retrieve the memory record for a function, initialising if missing.
        """
        if function_name not in self.function_memory:
            self.function_memory[function_name] = {
                "attempts": 0,
                "last_score": 0,
                "stagnation_count": 0,
                "best_version": "",
            }
        return self.function_memory[function_name]

    def update_function_memory(
        self,
        function_name: str,
        score: int,
        attempt_count: int,
        best_version: str,
    ) -> None:
        """
        Update the memory for a function based on the latest attempt.
        """
        mem = self.get_function_memory(function_name)

        if score > mem["last_score"]:
            mem["best_version"] = best_version
            mem["stagnation_count"] = 0
        elif score == mem["last_score"]:
            mem["stagnation_count"] += 1

        mem["last_score"] = score
        mem["attempts"] = attempt_count

    def cache_llm_response(self, prompt: str, response: str) -> None:
        """
        Store an LLM response in the cache, using a hash of the prompt as key.
        """
        key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        self.llm_cache[key] = response
        # Maintain cache size limit
        if len(self.llm_cache) > self.max_cache_size:
            # Remove the oldest entry (first item)
            self.llm_cache.popitem(last=False)
            logger.debug("LLM cache trimmed to %d entries", self.max_cache_size)

    def get_cached_llm_response(self, prompt: str) -> Optional[str]:
        """
        Retrieve a cached LLM response, if present.
        """
        key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if key in self.llm_cache:
            # Move to end to keep it fresh (OrderedDict)
            self.llm_cache.move_to_end(key)
            return self.llm_cache[key]
        return None

    def clear_cache(self) -> None:
        """Clear the LLM cache (useful for testing)."""
        self.llm_cache.clear()

    def close(self) -> None:
        """Flush tracing and clean up resources."""
        if self.tracer:
            self.tracer.flush()