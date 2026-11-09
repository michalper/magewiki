from typing import ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.cron import CronJob
from arq.typing import WorkerCoroutine

from app.config import settings
from app.tasks.jobs import (
    analyze_file,
    embed_chunks,
    nightly_scan_all,
    prune_module_history,
    refresh_magento_release_cache,
    scan_repository_job,
    synthesize_module,
)


class WorkerSettings:
    # arq reads these as plain class attributes, never instantiates this class with
    # per-instance state — ClassVar documents that's intentional, not the mutable-
    # default-argument footgun RUF012 otherwise exists to catch.
    functions: ClassVar[list[WorkerCoroutine]] = [analyze_file, synthesize_module, embed_chunks, scan_repository_job]
    cron_jobs: ClassVar[list[CronJob]] = [
        cron(nightly_scan_all, hour=3, minute=0),
        cron(refresh_magento_release_cache, hour=2, minute=30),
        cron(prune_module_history, hour=4, minute=0),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_tries = 5
