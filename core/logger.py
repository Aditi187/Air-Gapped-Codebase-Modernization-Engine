from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import json

_CONFIGURED = False
_CONFIG_LOCK = threading.Lock()

_DEFAULT_LOG_FILE = "modernization.log"
_DEFAULT_LOG_LEVEL = "WARNING"
_DEFAULT_MAX_BYTES = 5_000_000
_DEFAULT_BACKUPS = 3

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "time": self.formatTime(record, _DATE_FORMAT),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record, ensure_ascii=False)



def _configure() -> None:
    global _CONFIGURED

    if _CONFIGURED:
        return

    with _CONFIG_LOCK:
        if _CONFIGURED:
            return

        # ---------------- ENV CONFIG ----------------
        level_name = os.environ.get("LOG_LEVEL", _DEFAULT_LOG_LEVEL).strip().upper()
        level = getattr(logging, level_name, logging.INFO)

        log_file = os.environ.get("LOG_FILE", _DEFAULT_LOG_FILE).strip() or _DEFAULT_LOG_FILE

        try:
            max_bytes = int(os.environ.get("LOG_FILE_MAX_BYTES", str(_DEFAULT_MAX_BYTES)).strip())
        except ValueError:
            max_bytes = _DEFAULT_MAX_BYTES

        try:
            backup_count = int(os.environ.get("LOG_FILE_BACKUPS", str(_DEFAULT_BACKUPS)).strip())
        except ValueError:
            backup_count = _DEFAULT_BACKUPS

        use_json = os.environ.get("LOG_JSON", "false").strip().lower() == "true"

        formatter = JsonFormatter() if use_json else logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        # ---------------- HANDLERS ----------------
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)

        handlers: list[logging.Handler] = [console_handler]

        # File handler (safe)
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)
        except OSError:
            # fallback silently if file cannot be created
            pass

        root = logging.getLogger()


        if not root.handlers:
            for handler in handlers:
                root.addHandler(handler)

        root.setLevel(level)

        _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(name)