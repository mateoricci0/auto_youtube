"""
Main entry point. Loads channel configs and schedules the pipeline for each.
Runs indefinitely — keep this running on your server or in Docker.

Schedule example in channels.json:
  "schedule": { "days_of_week": "mon,wed,fri", "hour": 14, "minute": 0 }
"""
import json
import signal
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

from src.pipeline import run_pipeline
from src.utils.logger import get_logger

logger = get_logger("scheduler")


def _load_channels() -> list:
    config_path = Path("config/channels.json")
    if not config_path.exists():
        logger.error("config/channels.json not found!")
        sys.exit(1)
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)["channels"]


def _schedule_channel(scheduler: BlockingScheduler, channel: dict) -> None:
    schedule = channel.get("schedule", {})
    days = schedule.get("days_of_week", "mon,wed,fri")
    hour = schedule.get("hour", 14)
    minute = schedule.get("minute", 0)

    trigger = CronTrigger(day_of_week=days, hour=hour, minute=minute)

    scheduler.add_job(
        run_pipeline,
        trigger=trigger,
        args=[channel],
        id=channel["id"],
        name=f"Pipeline: {channel.get('name', channel['id'])}",
        max_instances=1,       # prevent overlapping runs
        coalesce=True,         # if multiple fires missed, run only once
        misfire_grace_time=3600,
    )

    logger.info(
        "Scheduled '%s' → %s at %02d:%02d UTC",
        channel.get("name", channel["id"]),
        days,
        hour,
        minute,
    )


def main() -> None:
    channels = _load_channels()
    if not channels:
        logger.error("No channels configured in channels.json")
        sys.exit(1)

    scheduler = BlockingScheduler(timezone="UTC")

    for channel in channels:
        _schedule_channel(scheduler, channel)

    def _shutdown(signum, frame):
        logger.info("Shutting down scheduler…")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("Scheduler started. %d channel(s) registered. Ctrl+C to stop.", len(channels))
    scheduler.start()


if __name__ == "__main__":
    main()
