import os
from dataclasses import dataclass
from typing import Optional


def _read_bool_env(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable. Accepts 1/true/yes/on."""
    value = os.environ.get(name, "").strip().lower()
    if value:
        return value in {"1", "true", "yes", "on"}
    return default


def _read_int_env(name: str, default: int, min_val: int, max_val: int) -> int:
    """Read an integer environment variable, clamp to [min_val, max_val]."""
    value = os.environ.get(name, "").strip()
    if value:
        try:
            return max(min_val, min(max_val, int(value)))
        except ValueError:
            pass
    return default


def _read_float_env(name: str, default: float, min_val: float, max_val: float) -> float:
    """Read a float environment variable, clamp to [min_val, max_val]."""
    value = os.environ.get(name, "").strip()
    if value:
        try:
            return max(min_val, min(max_val, float(value)))
        except ValueError:
            pass
    return default


@dataclass
class WorkflowConfig:
    """
    Configuration for the C++ modernization workflow.

    All fields can be overridden via environment variables (see from_env()).
    """
    # Core workflow settings
    batch_size: int = 1
    max_attempts: int = 5
    escape_max_steps: int = 5
    stagnant_score_limit: int = 10
    min_final_score: int = 55

    # Pruning and validation
    enable_pruner: bool = False
    max_function_diff_ratio: float = 0.85
    min_function_similarity: float = 0.05
    enable_similarity_gate: bool = False
    enable_structure_validation: bool = False
    enable_strict_gate: bool = False

    # Debugging
    debug_log_prompts: bool = True
    debug_log_raw_llm_output: bool = True
    debug_one_function_only: bool = False

    # LLM and modernization
    enable_compiler_error_autofix: bool = True
    force_global_modernizer: bool = False
    use_llm: bool = True
    temperature: float = 0.1
    allow_signature_refactor: bool = False
    modernization_mode: str = "safe"
    strict_cpp17_mode: bool = False
    strict_cpp17_target_percent: int = 70
    model_min_score_delta: int = 8

    # Internal limits (not always exposed via CLI, but can be tuned)
    max_modernizer_function_chars: int = 3000
    modernizer_node_similarity_guard: float = 0.82

    @classmethod
    def from_env(cls) -> "WorkflowConfig":
        """
        Create a WorkflowConfig instance from environment variables.

        Environment variables:
            WORKFLOW_BATCH_SIZE                       (int, 1-5)
            WORKFLOW_MAX_ATTEMPTS                     (int, 1-15)
            WORKFLOW_ESCAPE_MAX_STEPS                 (int, 1-50)
            WORKFLOW_STAGNANT_SCORE_LIMIT             (int, 1-100)
            WORKFLOW_MIN_FINAL_SCORE                  (int, 0-100)
            WORKFLOW_ENABLE_PRUNER                    (bool)
            WORKFLOW_MAX_FUNCTION_DIFF_RATIO          (float, 0.05-0.99)
            WORKFLOW_MIN_FUNCTION_SIMILARITY          (float, 0.0-1.0)
            WORKFLOW_ENABLE_SIMILARITY_GATE           (bool)
            WORKFLOW_ENABLE_STRUCTURE_VALIDATION      (bool)
            WORKFLOW_DEBUG_LOG_PROMPTS                (bool)
            WORKFLOW_DEBUG_LOG_RAW_LLM_OUTPUT         (bool)
            WORKFLOW_DEBUG_ONE_FUNCTION_ONLY          (bool)
            WORKFLOW_ENABLE_COMPILER_ERROR_AUTOFIX    (bool)
            WORKFLOW_ENABLE_STRICT_GATE               (bool)
            WORKFLOW_FORCE_GLOBAL_MODERNIZER          (bool)
            WORKFLOW_USE_LLM                          (bool)
            LLM_TEMPERATURE                           (float, 0.0-1.0)
            WORKFLOW_ALLOW_SIGNATURE_REFACTOR         (bool)    # overridden by mode
            WORKFLOW_MODERNIZATION_MODE               (safe|aggressive)
            WORKFLOW_STRICT_CPP17_MODE                (bool)    # also checks CPP17_STRICT_MODE, WORKFLOW_STRICT_MODE, CPP23_STRICT_MODE
            CPP17_STRICT_TARGET_PERCENT               (int, 0-100) # fallback: 70
            WORKFLOW_MIN_SCORE_DELTA                  (int, 0-100)
            WORKFLOW_MAX_MODERNIZER_FUNCTION_CHARS    (int)
            WORKFLOW_MODERNIZER_NODE_SIMILARITY_GUARD (float)
        """
        # Determine if we should use LLM (disabled via env)
        use_llm = _read_bool_env("WORKFLOW_USE_LLM", True) and not _read_bool_env("WORKFLOW_DISABLE_LLM", False)

        # Modernization mode (safe/aggressive)
        mode = os.environ.get("WORKFLOW_MODERNIZATION_MODE", "safe").strip().lower()
        if mode not in {"safe", "aggressive"}:
            mode = "safe"
        # Allow signature refactor if env explicitly says so, but mode takes precedence
        allow_sig = _read_bool_env("WORKFLOW_ALLOW_SIGNATURE_REFACTOR", False)
        if allow_sig and mode == "safe":
            mode = "aggressive"

        # Strict C++17 mode (several possible env names)
        strict_mode = any(
            _read_bool_env(var, False)
            for var in [
                "WORKFLOW_STRICT_CPP17_MODE",
                "CPP17_STRICT_MODE",
                "WORKFLOW_STRICT_MODE",
                "CPP23_STRICT_MODE",
            ]
        )

        # Target percentage for strict mode
        strict_target = _read_int_env(
            "CPP17_STRICT_TARGET_PERCENT",
            default=70,
            min_val=0,
            max_val=100,
        )

        return cls(
            batch_size=_read_int_env("WORKFLOW_BATCH_SIZE", 1, 1, 5),
            max_attempts=_read_int_env("WORKFLOW_MAX_ATTEMPTS", 5, 1, 15),
            escape_max_steps=_read_int_env("WORKFLOW_ESCAPE_MAX_STEPS", 5, 1, 50),
            stagnant_score_limit=_read_int_env("WORKFLOW_STAGNANT_SCORE_LIMIT", 10, 1, 100),
            min_final_score=_read_int_env("WORKFLOW_MIN_FINAL_SCORE", 55, 0, 100),
            enable_pruner=_read_bool_env("WORKFLOW_ENABLE_PRUNER", False),
            max_function_diff_ratio=_read_float_env("WORKFLOW_MAX_FUNCTION_DIFF_RATIO", 0.85, 0.05, 0.99),
            min_function_similarity=_read_float_env("WORKFLOW_MIN_FUNCTION_SIMILARITY", 0.05, 0.0, 1.0),
            enable_similarity_gate=_read_bool_env("WORKFLOW_ENABLE_SIMILARITY_GATE", False),
            enable_structure_validation=_read_bool_env("WORKFLOW_ENABLE_STRUCTURE_VALIDATION", False),
            debug_log_prompts=_read_bool_env("WORKFLOW_DEBUG_LOG_PROMPTS", True),
            debug_log_raw_llm_output=_read_bool_env("WORKFLOW_DEBUG_LOG_RAW_LLM_OUTPUT", True),
            debug_one_function_only=_read_bool_env("WORKFLOW_DEBUG_ONE_FUNCTION_ONLY", False),
            enable_compiler_error_autofix=_read_bool_env("WORKFLOW_ENABLE_COMPILER_ERROR_AUTOFIX", True),
            enable_strict_gate=_read_bool_env("WORKFLOW_ENABLE_STRICT_GATE", False),
            force_global_modernizer=_read_bool_env("WORKFLOW_FORCE_GLOBAL_MODERNIZER", False),
            use_llm=use_llm,
            temperature=_read_float_env("LLM_TEMPERATURE", 0.1, 0.0, 1.0),
            allow_signature_refactor=(mode == "aggressive"),
            modernization_mode=mode,
            strict_cpp17_mode=strict_mode,
            strict_cpp17_target_percent=strict_target,
            model_min_score_delta=_read_int_env("WORKFLOW_MIN_SCORE_DELTA", 8, 0, 100),
            max_modernizer_function_chars=_read_int_env(
                "WORKFLOW_MAX_MODERNIZER_FUNCTION_CHARS", 3000, 100, 10000
            ),
            modernizer_node_similarity_guard=_read_float_env(
                "WORKFLOW_MODERNIZER_NODE_SIMILARITY_GUARD", 0.82, 0.0, 1.0
            ),
        )

    def __post_init__(self) -> None:
        """Optional post‑initialization validation."""
        if self.modernization_mode not in ("safe", "aggressive"):
            raise ValueError(f"modernization_mode must be 'safe' or 'aggressive', got {self.modernization_mode}")
        if self.strict_cpp17_target_percent < 0 or self.strict_cpp17_target_percent > 100:
            raise ValueError("strict_cpp17_target_percent must be in [0,100]")