import os
import hashlib
import logging
from typing import Dict, Optional, Any
from collections import OrderedDict









try:
    import agents.workflow.config as config_mod
    WorkflowConfig = config_mod.WorkflowConfig
except (ImportError, AttributeError):
    raise ImportError("WorkflowConfig could not be imported from agents.workflow.config")


logger = logging.getLogger(__name__)


class WorkflowContext:
    """
    Persistent runtime context shared across workflow nodes.

    Phase 4 additions:
        - multi-model caching
        - semantic cache
        - dependency graph reuse
        - planner history
        - transformation stats
    """


    def __init__(self, config=None):
        self.config = config or WorkflowConfig.from_env()

        # ==========================================
        # LLM CACHE
        # ==========================================

        self.llm_cache: "OrderedDict[str, str]" = OrderedDict()

        self.max_cache_size: int = 500

        # ==========================================
        # PHASE 4 EXTENSIONS
        # ==========================================

        # reusable code graph
        self.code_graph = None

        # semantic extraction cache
        self.semantic_cache: Dict[str, Dict[str, Any]] = {}

        # planner history
        self.planner_history = []

        # transformation statistics
        self.transformation_stats: Dict[str, int] = {}

        # session tracking
        self.session_id: str = self._generate_session_id()

        logger.info(
            f"[WorkflowContext] session initialized | id={self.session_id}"
        )

    # ==========================================================
    # SESSION HELPERS
    # ==========================================================

    def _generate_session_id(self) -> str:

        random_bytes = os.urandom(8)

        return hashlib.sha1(random_bytes).hexdigest()[:10]

    # ==========================================================
    # CACHE KEY
    # ==========================================================

    def _make_cache_key(

        self,

        prompt: str,

        params: Optional[Dict[str, Any]],

        role: Optional[str] = None

    ) -> str:

        if not prompt:

            return ""

        params_str = ""

        if params:

            params_str = repr(

                sorted(params.items())
            )

        role_part = role or "default"

        raw_key = (

            f"{role_part}|"

            f"{self.config.model_name}|"

            f"{prompt}|"

            f"{params_str}"
        )

        return hashlib.sha256(

            raw_key.encode("utf-8")

        ).hexdigest()

    # ==========================================================

    def get_cached_llm_response(

        self,

        prompt: str,

        params: Optional[Dict[str, Any]] = None,

        role: Optional[str] = None

    ) -> Optional[str]:

        key = self._make_cache_key(

            prompt,

            params,

            role
        )

        if key not in self.llm_cache:

            return None

        self.llm_cache.move_to_end(key)

        return self.llm_cache[key]

    # ==========================================================

    def cache_llm_response(

        self,

        prompt: str,

        response: str,

        params: Optional[Dict[str, Any]] = None,

        role: Optional[str] = None

    ) -> None:

        if not prompt or not response:

            return

        key = self._make_cache_key(

            prompt,

            params,

            role
        )

        self.llm_cache[key] = response

        if len(self.llm_cache) > self.max_cache_size:

            self.llm_cache.popitem(last=False)

    # ==========================================================
    # SEMANTIC CACHE
    # ==========================================================

    def cache_semantic_result(

        self,

        code_hash: str,

        result: Dict[str, Any]

    ) -> None:

        self.semantic_cache[code_hash] = result

    def get_semantic_result(

        self,

        code_hash: str

    ) -> Optional[Dict[str, Any]]:

        return self.semantic_cache.get(code_hash)

    # ==========================================================
    # TRANSFORMATION STATS
    # ==========================================================

    def record_transformation(

        self,

        rule_name: str

    ):

        self.transformation_stats[rule_name] = (

            self.transformation_stats.get(

                rule_name,

                0
            ) + 1
        )

    # ==========================================================

    def to_dict(self) -> Dict[str, Any]:

        return {

            "session_id": self.session_id,

            "model": self.config.model_name,

            "cache_entries": len(self.llm_cache),

            "transformations": len(self.transformation_stats),

        }

    # ==========================================================

    def __repr__(self) -> str:

        return (

            "WorkflowContext("

            f"session_id={self.session_id}, "

            f"model={self.config.model_name}, "

            f"cache={len(self.llm_cache)}"

            ")"
        )