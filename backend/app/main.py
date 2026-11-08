from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.api.routes.llm_settings import router as llm_settings_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.modules import router as modules_router
from app.api.routes.search import router as search_router
from app.api.routes.webhooks import router as webhooks_router
from app.config import settings
from app.observability import RequestIdMiddleware, configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="MageWiki-AI API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)

    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(modules_router)
    app.include_router(search_router)
    app.include_router(chat_router)
    app.include_router(webhooks_router)
    app.include_router(llm_settings_router)

    return app


app = create_app()
