import os
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional


logger = logging.getLogger(__name__)


# ============================================================
# ENV HELPERS
# ============================================================

def _read_bool_env(name: str, default: bool) -> bool:

    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {

        "1",
        "true",
        "yes",
        "on"
    }


def _read_int_env(

    name: str,

    default: int,

    min_val: int,

    max_val: int

) -> int:

    value = os.getenv(name)

    if value is None:
        return default

    try:

        parsed = int(value)

        return max(

            min_val,

            min(max_val, parsed)
        )

    except ValueError:

        return default


def _read_float_env(

    name: str,

    default: float,

    min_val: float,

    max_val: float

) -> float:

    value = os.getenv(name)

    if value is None:
        return default

    try:

        parsed = float(value)

        return max(

            min_val,

            min(max_val, parsed)
        )

    except ValueError:

        return default


# ============================================================
# ENUMS
# ============================================================

class ModernizationMode(str, Enum):

    SAFE = "safe"

    BALANCED = "balanced"

    AGGRESSIVE = "aggressive"


class PlannerStrategy(str, Enum):

    RISK_AWARE = "risk_aware"

    STRUCTURE_FIRST = "structure_first"

    API_SAFE = "api_safe"

    PERFORMANCE = "performance"


# ============================================================
# CONFIG
# ============================================================

@dataclass
class WorkflowConfig:

    # ======================================================
    # MODEL SETTINGS
    # ======================================================

    use_llm: bool = True

    model_name: str = "gpt-4-turbo"

    temperature: float = 0.2

    enable_multi_model: bool = False

    analyzer_model: Optional[str] = None

    planner_model: Optional[str] = None

    modernizer_model: Optional[str] = None

    fixer_model: Optional[str] = None


    # ======================================================
    # LOOP CONTROL
    # ======================================================

    max_attempts: int = 3

    max_fix_attempts: int = 2

    planner_max_iterations: int = 2


    # ======================================================
    # CORE FEATURES
    # ======================================================

    enable_planner: bool = True

    enable_semantic_guard: bool = True

    enable_code_graph: bool = True

    enable_risk_analysis: bool = True


    # ======================================================
    # MODERNIZATION STRATEGY
    # ======================================================

    modernization_mode: ModernizationMode = ModernizationMode.SAFE

    planner_strategy: PlannerStrategy = PlannerStrategy.RISK_AWARE

    transformation_depth: int = 2

    """
    1 → syntax only
    2 → ownership changes
    3 → structural refactors
    """


    # ======================================================
    # RISK CONTROL
    # ======================================================

    max_allowed_risk: float = 0.7

    semantic_strict_mode: bool = True


    # ======================================================
    # RULE FLAGS
    # ======================================================

    enable_pointer_modernization: bool = True

    enable_string_modernization: bool = True

    enable_container_modernization: bool = True

    enable_loop_modernization: bool = True

    enable_include_cleanup: bool = True

    enable_nullptr_upgrade: bool = True

    enable_auto_keyword: bool = True

    enable_template_refactoring: bool = False

    enable_interface_extraction: bool = False


    # ======================================================
    # GRAPH SETTINGS
    # ======================================================

    graph_max_nodes: int = 5000

    graph_include_headers: bool = True


    # ======================================================
    # DEBUGGING
    # ======================================================

    enable_metrics: bool = True

    log_plans: bool = True

    log_graph: bool = False

    log_transformations: bool = True


    # ======================================================
    # ENV LOADER
    # ======================================================

    @classmethod
    def from_env(cls) -> "WorkflowConfig":

        mode_str = os.getenv(

            "MODERNIZATION_MODE",

            "safe"
        ).lower()

        try:

            mode = ModernizationMode(mode_str)

        except ValueError:

            logger.warning(

                f"Invalid MODERNIZATION_MODE: {mode_str}"

            )

            mode = ModernizationMode.SAFE


        planner_str = os.getenv(

            "PLANNER_STRATEGY",

            "risk_aware"
        ).lower()

        try:

            planner_strategy = PlannerStrategy(

                planner_str
            )

        except ValueError:

            planner_strategy = PlannerStrategy.RISK_AWARE


        return cls(

            # model
            use_llm=_read_bool_env(

                "USE_LLM",

                True
            ),

            model_name=os.getenv(

                "LLM_MODEL",

                "gpt-4-turbo"
            ),

            temperature=_read_float_env(

                "LLM_TEMPERATURE",

                0.2,

                0.0,

                1.0
            ),

            enable_multi_model=_read_bool_env(

                "MULTI_MODEL",

                False
            ),

            analyzer_model=os.getenv(

                "ANALYZER_MODEL"
            ),

            planner_model=os.getenv(

                "PLANNER_MODEL"
            ),

            modernizer_model=os.getenv(

                "MODERNIZER_MODEL"
            ),

            fixer_model=os.getenv(

                "FIXER_MODEL"
            ),

            # loops
            max_attempts=_read_int_env(

                "MAX_ATTEMPTS",

                3,

                1,

                10
            ),

            max_fix_attempts=_read_int_env(

                "MAX_FIX_ATTEMPTS",

                2,

                0,

                6
            ),

            planner_max_iterations=_read_int_env(

                "PLANNER_MAX_ITER",

                2,

                1,

                5
            ),

            # features
            enable_planner=_read_bool_env(

                "ENABLE_PLANNER",

                True
            ),

            enable_semantic_guard=_read_bool_env(

                "ENABLE_SEMANTIC_GUARD",

                True
            ),

            enable_code_graph=_read_bool_env(

                "ENABLE_GRAPH",

                True
            ),

            enable_risk_analysis=_read_bool_env(

                "ENABLE_RISK",

                True
            ),

            modernization_mode=mode,

            planner_strategy=planner_strategy,

            transformation_depth=_read_int_env(

                "TRANSFORMATION_DEPTH",

                2,

                1,

                3
            ),

            max_allowed_risk=_read_float_env(

                "MAX_ALLOWED_RISK",

                0.7,

                0.0,

                1.0
            ),

            semantic_strict_mode=_read_bool_env(

                "SEMANTIC_STRICT",

                True
            ),

            enable_pointer_modernization=_read_bool_env(

                "MOD_POINTERS",

                True
            ),

            enable_string_modernization=_read_bool_env(

                "MOD_STRING",

                True
            ),

            enable_container_modernization=_read_bool_env(

                "MOD_CONTAINERS",

                True
            ),

            enable_loop_modernization=_read_bool_env(

                "MOD_LOOPS",

                True
            ),

            enable_include_cleanup=_read_bool_env(

                "MOD_INCLUDES",

                True
            ),

            enable_nullptr_upgrade=_read_bool_env(

                "MOD_NULLPTR",

                True
            ),

            enable_auto_keyword=_read_bool_env(

                "MOD_AUTO",

                True
            ),

            enable_template_refactoring=_read_bool_env(

                "MOD_TEMPLATES",

                False
            ),

            enable_interface_extraction=_read_bool_env(

                "MOD_INTERFACE",

                False
            ),

            graph_max_nodes=_read_int_env(

                "GRAPH_MAX_NODES",

                5000,

                100,

                20000
            ),

            graph_include_headers=_read_bool_env(

                "GRAPH_HEADERS",

                True
            ),

            enable_metrics=_read_bool_env(

                "ENABLE_METRICS",

                True
            ),

            log_plans=_read_bool_env(

                "LOG_PLANS",

                True
            ),

            log_graph=_read_bool_env(

                "LOG_GRAPH",

                False
            ),

            log_transformations=_read_bool_env(

                "LOG_TRANSFORMS",

                True
            ),
        )