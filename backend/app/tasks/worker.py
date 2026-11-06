from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.tasks.jobs import (
    analyze_file,
    embed_chunks,
    nightly_scan_all,
    refresh_magento_release_cache,
    scan_repository_job,
    synthesize_module,
)


class WorkerSettings:
    functions = [analyze_file, synthesize_module, embed_chunks, scan_repository_job]
    cron_jobs = [
        cron(nightly_scan_all, hour=3, minute=0),
        cron(refresh_magento_release_cache, hour=2, minute=30),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_tries = 5
