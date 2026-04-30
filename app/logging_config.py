import os
import logging


def configure_logging() -> None:
    """Configure logging to stdout and to a file for Promtail ingestion."""
    log_path = os.environ.get("SQUIRREL_LOG_PATH", "/tmp/squirrel-logs/backend.log")
    log_dir = os.path.dirname(log_path)

    try:
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
    except Exception:
        # If we can't create the directory, fall back to stdout-only.
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        return

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(log_path))
    except Exception:
        # If file handler can't be created, continue with stdout-only.
        pass

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )
