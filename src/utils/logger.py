import logging
import sys
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logs_dir = Path(os.getenv("LOGS_DIR", "logs"))
    logs_dir.mkdir(parents=True, exist_ok=True)

    fh = logging.FileHandler(logs_dir / "pipeline.log", encoding="utf-8")
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.propagate = False

    return logger
