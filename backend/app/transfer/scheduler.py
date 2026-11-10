import logging
from datetime import timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.common import db
from app.transfer import service

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
_scheduler: BackgroundScheduler | None = None


def _job() -> None:
    with db.connection() as conn:
        results = service.run_due_auto_transfers(conn)
    log.info("자동이체 실행 %d건", len(results))


def start() -> None:
    """매일 09:00(KST)에 자동이체를 실행한다."""
    global _scheduler
    _scheduler = BackgroundScheduler(timezone=KST)
    _scheduler.add_job(_job, CronTrigger(hour=9, minute=0, timezone=KST), id="auto-transfers",
                       max_instances=1, coalesce=True, misfire_grace_time=3600)
    _scheduler.start()


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
