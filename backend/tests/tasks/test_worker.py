from app.tasks.jobs import analyze_file, embed_chunks, scan_repository_job, synthesize_module
from app.tasks.worker import WorkerSettings


def test_worker_settings_registers_every_job_function():
    assert WorkerSettings.functions == [analyze_file, synthesize_module, embed_chunks, scan_repository_job]


def test_worker_settings_registers_both_cron_jobs():
    names = {cj.coroutine.__name__ for cj in WorkerSettings.cron_jobs}
    assert names == {"nightly_scan_all", "refresh_magento_release_cache"}


def test_worker_settings_has_redis_settings_and_a_retry_limit():
    assert WorkerSettings.redis_settings is not None
    assert WorkerSettings.max_tries == 5
