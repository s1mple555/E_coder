"""Session-owned cron prompt queue, based on learn-claude-code/s12.

Runs on the server's asyncio loop. Durable pending deliveries survive restart;
model receipt acknowledges delivery, not successful completion of the work.
"""
import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import logging
import re

from .store import uid


TIMEZONE = "Asia/Shanghai"
SHANGHAI = timezone(timedelta(hours=8), TIMEZONE)
logger = logging.getLogger(__name__)


@lru_cache(maxsize=512)
def parse_cron(expression):
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("Cron 必须包含五段：分钟 小时 日 月 星期")
    result = []
    for field, (minimum, maximum) in zip(fields, [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]):
        values = set()
        for part in field.split(','):
            if part == '*':
                values.update(range(minimum, maximum + 1))
            elif re.fullmatch(r'\*/[0-9]+', part):
                step = int(part[2:])
                if step < 1:
                    raise ValueError("Cron 步长必须大于零")
                values.update(value for value in range(minimum, maximum + 1) if value % step == 0)
            elif re.fullmatch(r'[0-9]+(?:-[0-9]+)?', part):
                bounds = [int(value) for value in part.split('-')]
                start, end = bounds[0], bounds[-1]
                if not minimum <= start <= end <= maximum:
                    raise ValueError(f"Cron 字段 {field} 超出范围 {minimum}–{maximum}")
                values.update(range(start, end + 1))
            else:
                raise ValueError(f"无效 Cron 字段: {field}")
        result.append(frozenset(values))
    return tuple(result)


def cron_matches(expression, moment):
    minute, hour, day, month, weekday = parse_cron(expression)
    fields = expression.split()
    if moment.minute not in minute or moment.hour not in hour or moment.month not in month:
        return False
    day_match = moment.day in day
    weekday_match = (moment.weekday() + 1) % 7 in weekday
    if fields[2] == '*':
        return weekday_match
    if fields[4] == '*':
        return day_match
    return day_match or weekday_match


@dataclass(frozen=True)
class CronJob:
    id: str
    session: str
    cron: str
    prompt: str
    recurring: bool = True
    durable: bool = True
    pending_delivery: bool = False
    last_fired: str | None = None
    next_attempt: float = 0
    queued_at: float = 0
    attempts: int = 0
    timezone: str = TIMEZONE


class Scheduler:
    def __init__(self, runtime):
        self.runtime, self.store = runtime, runtime.store
        self.jobs = {}
        self.inflight = {}
        self.task = None
        self.retry_seconds = 60
        self.last_error = None
        self.now = lambda: datetime.now(SHANGHAI)
        for item in self.store.crons():
            job = CronJob(**item)
            parse_cron(job.cron)
            if self.store.exists(job.session):
                self.jobs[job.id] = job

    def status(self):
        return {"running": self.task is not None and not self.task.done(),
                "timezone": TIMEZONE, "jobs": len(self.jobs), "last_error": self.last_error}

    def _save(self, job):
        # Write first, then expose the new state to dispatch. Failure leaves the
        # old in-memory queue intact, just as s12's durable JSON rollback does.
        if job.durable:
            self.store.save_cron(job.session, asdict(job))
        self.jobs[job.id] = job

    def list_jobs(self, session):
        return [asdict(job) for job in self.jobs.values() if job.session == session]

    def _updated(self, session):
        self.store.event(session, "crons_update", crons=self.list_jobs(session))

    def schedule(self, session, cron, prompt, recurring=True, durable=True):
        if not self.store.exists(session):
            raise ValueError("会话不存在")
        parse_cron(cron)
        if not prompt.strip():
            raise ValueError("定时任务内容不能为空")
        job = CronJob(id="cron_" + uid()[:12], session=session,
                      cron=" ".join(cron.split()), prompt=prompt.strip(),
                      recurring=recurring, durable=durable)
        self._save(job)
        self._updated(session)
        return asdict(job)

    def cancel(self, session, job_id):
        job = self.jobs.get(job_id)
        if job is None or job.session != session:
            raise ValueError("当前会话中不存在此定时任务")
        if job.durable:
            self.store.delete_cron(session, job_id)
        self.jobs.pop(job_id)
        self._updated(session)
        return {"cancelled": True, "job_id": job_id}

    def remove_session(self, session):
        # Store.delete_session already removed its durable rows atomically.
        self.jobs = {key: job for key, job in self.jobs.items() if job.session != session}

    def poll_due_jobs(self, moment):
        moment = moment.replace(tzinfo=SHANGHAI) if moment.tzinfo is None else moment.astimezone(SHANGHAI)
        marker = moment.strftime('%Y-%m-%d %H:%M')
        for job in list(self.jobs.values()):
            if not self.store.exists(job.session):
                self.remove_session(job.session)
                continue
            if job.pending_delivery or job.last_fired == marker:
                continue
            if cron_matches(job.cron, moment):
                self._save(replace(job, pending_delivery=True, last_fired=marker, next_attempt=0, queued_at=moment.timestamp()))
                self._updated(job.session)

    def deliver_pending(self, moment):
        for job_id, task in list(self.inflight.items()):
            if task.done():
                self.inflight.pop(job_id, None)
        for job in sorted(self.jobs.values(), key=lambda item: item.queued_at):
            if (not job.pending_delivery or job.next_attempt > moment.timestamp()
                    or job.id in self.inflight or job.session in self.runtime.active
                    or job.session in self.runtime.uploading):
                continue
            if not self.store.exists(job.session):
                self.remove_session(job.session)
                continue
            self._save(replace(job, attempts=job.attempts + 1))
            self.runtime.start(job.session, f"[Scheduled] {job.prompt}", schedule_id=job.id)
            self.inflight[job.id] = self.runtime.active[job.session].task

    def acknowledge(self, session, job_id):
        job = self.jobs.get(job_id)
        if job is None or job.session != session:
            return
        if job.recurring:
            self._save(replace(job, pending_delivery=False, next_attempt=0, queued_at=0))
            self._updated(session)
        else:
            self.cancel(session, job_id)

    def finish(self, session, run, status):
        if not run.schedule_id or run.schedule_acknowledged:
            return
        job = self.jobs.get(run.schedule_id)
        if job is None or job.session != session:
            return
        if status == 'cancelled':
            # Stop skips this delivery; cancel_cron removes future occurrences.
            if not run.preserve_schedule:
                self.acknowledge(session, job.id)
        else:
            self._save(replace(job, next_attempt=self.now().timestamp() + self.retry_seconds))
            self._updated(session)

    def tick(self, moment=None):
        moment = moment or self.now()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=SHANGHAI)
        self.poll_due_jobs(moment)
        self.deliver_pending(moment)

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop())

    async def _loop(self):
        while True:
            try:
                self.tick()
                self.last_error = None
            except Exception as error:
                kind = type(error).__name__
                if self.last_error != kind:
                    logger.error("Cron scheduler tick failed (%s)", kind)
                self.last_error = kind
            await asyncio.sleep(1)

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
