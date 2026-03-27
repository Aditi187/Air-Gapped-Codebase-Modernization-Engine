import logging

from typing import Any, Dict, Optional

logger = logging.getLogger("metrics")

class MetricsCollector:
    def __init__(self, initial_metrics: Optional[Dict[str, Any]] = None):
        self.metrics = initial_metrics or {}

    def add(self, key: str, value: Any):
        self.metrics[key] = value

    def report(self) -> Dict[str, Any]:
        return self.metrics

__all__ = ["MetricsCollector"]
