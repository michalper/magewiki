from arq.connections import RedisSettings

from app.config import settings
from app.tasks.jobs import analyze_file, embed_chunks, synthesize_module


class WorkerSettings:
    functions = [analyze_file, synthesize_module, embed_chunks]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_tries = 5
