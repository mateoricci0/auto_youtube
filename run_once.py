"""
Run the pipeline immediately for a specific channel — useful for testing.

Usage:
  python run_once.py                         # uses first channel in channels.json
  python run_once.py --channel channel_main  # specific channel by ID
"""
import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.pipeline import run_pipeline
from src.utils.logger import get_logger

logger = get_logger("run_once")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the YouTube pipeline once.")
    parser.add_argument("--channel", help="Channel ID from channels.json (default: first channel)")
    args = parser.parse_args()

    config_path = Path("config/channels.json")
    if not config_path.exists():
        logger.error("config/channels.json not found!")
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        channels = json.load(f)["channels"]

    if not channels:
        logger.error("No channels in config.")
        sys.exit(1)

    if args.channel:
        channel = next((c for c in channels if c["id"] == args.channel), None)
        if not channel:
            logger.error("Channel '%s' not found in config.", args.channel)
            sys.exit(1)
    else:
        channel = channels[0]

    logger.info("Running pipeline now for: %s", channel.get("name", channel["id"]))
    result = run_pipeline(channel)

    if result["status"] == "success":
        logger.info("SUCCESS: %s", result.get("url"))
        sys.exit(0)
    else:
        logger.error("FAILED at step '%s': %s", result.get("step"), result.get("error"))
        sys.exit(1)


if __name__ == "__main__":
    main()
