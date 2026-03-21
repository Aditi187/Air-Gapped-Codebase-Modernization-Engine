"""
Retry policy helpers: delay parsing, jitter, and a thread‑safe rate limiter.
"""

from __future__ import annotations

import os
import random
import threading
import time
from typing import Tuple


def parse_retry_delays_from_env(
    env_name: str, default_delays: Tuple[float, ...]
) -> Tuple[float, ...]:
    """
    Read a comma‑separated list of delays (in seconds) from an environment variable.

    Example:
        export LLM_RETRY_DELAYS="0.5,1.0,2.0"

    Args:
        env_name: The environment variable name.
        default_delays: A tuple of default delays (used if the variable is missing or invalid).

    Returns:
        A tuple of positive floats (empty tuple not allowed; returns defaults if all tokens invalid).
    """
    configured = os.environ.get(env_name, "").strip()
    if not configured:
        return default_delays

    delays: list[float] = []
    for token in configured.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            value = float(token)
            if value > 0:
                delays.append(value)
        except ValueError:
            continue

    return tuple(delays) if delays else default_delays


def with_jitter(base_delay_seconds: float) -> float:
    """
    Apply a random jitter to a base delay.

    The jitter ratio is read from the environment variable `LLM_RETRY_JITTER_RATIO`
    (default 0.2, clamped to [0,1]).

    Args:
        base_delay_seconds: The nominal delay (must be ≥ 0).

    Returns:
        A delay in seconds, possibly jittered, never negative.
    """
    if base_delay_seconds <= 0:
        return 0.0

    raw_ratio = os.environ.get("LLM_RETRY_JITTER_RATIO", "0.2").strip()
    try:
        jitter_ratio = float(raw_ratio)
    except ValueError:
        jitter_ratio = 0.2
    jitter_ratio = max(0.0, min(1.0, jitter_ratio))

    spread = base_delay_seconds * jitter_ratio
    # Uniform jitter in [-spread, +spread]
    return max(0.0, base_delay_seconds + random.uniform(-spread, spread))


class RateLimiter:
    """
    A simple thread‑safe rate limiter based on a fixed calls per minute limit.

    Example:
        limiter = RateLimiter(max_calls_per_minute=30)
        for _ in range(100):
            limiter.wait()          # sleeps if necessary
            # make a call
    """

    def __init__(self, max_calls_per_minute: float) -> None:
        """
        Args:
            max_calls_per_minute: The maximum number of calls allowed per minute.
                                  Must be positive; values ≤ 0 are treated as 1.
        """
        safe_rate = max(1.0, float(max_calls_per_minute or 1.0))
        self._interval_seconds = 60.0 / safe_rate
        self._last_call_time = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        """
        Wait until the next allowed call time, respecting the rate limit.
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call_time
            if elapsed < self._interval_seconds:
                time.sleep(self._interval_seconds - elapsed)
            self._last_call_time = time.monotonic()

    def reset(self) -> None:
        """
        Reset the rate limiter, clearing the last call time.
        Useful when starting a new batch of calls.
        """
        with self._lock:
            self._last_call_time = 0.0