"""
SchedulerEngine — wraps APScheduler and provides dependencies to jobs.
"""

from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger

from runtime.sender import Sender
from store.database import Database
from store.state_store import StateStore

logger = logging.getLogger(__name__)


class SchedulerEngine:
    def __init__(self, db: Database, sender: Sender, state_store: StateStore):
        self.db = db
        self.sender = sender
        self.state_store = state_store
        
        jobstores = {
            'default': SQLAlchemyJobStore(url='sqlite:///data/jobs.sqlite')
        }
        self.scheduler = BackgroundScheduler(jobstores=jobstores)

    def start(self):
        self.scheduler.start()
        logger.info("Scheduler started.")

    def shutdown(self):
        self.scheduler.shutdown(wait=False)
        logger.info("Scheduler shutdown.")

    def add_interval_job(
        self,
        job_id: str,
        func: Callable,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        **kwargs,
    ):
        """Add a job that runs on a fixed interval."""
        trigger = IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours)
        self._add_job(job_id, func, trigger, **kwargs)

    def add_cron_job(self, job_id: str, func: Callable, cron_expr: str, **kwargs):
        """Add a job that runs on a cron schedule."""
        trigger = CronTrigger.from_crontab(cron_expr)
        self._add_job(job_id, func, trigger, **kwargs)

    def add_date_job(self, job_id: str, func: Callable, run_date, **kwargs):
        """Add a job that runs once at a specific date/time."""
        trigger = DateTrigger(run_date=run_date)
        self._add_job(job_id, func, trigger, **kwargs)

    def _add_job(self, job_id: str, func: Callable, trigger, **kwargs):
        # We pass func directly to allow pickling in SQLAlchemyJobStore
        self.scheduler.add_job(
            func,
            trigger,
            id=job_id,
            kwargs=kwargs,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Added job %s with trigger %s", job_id, trigger)
