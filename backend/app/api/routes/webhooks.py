import hashlib
import hmac
import json
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
from app.tasks.queue import get_arq_pool

router = APIRouter()


class WebhookScanResponse(BaseModel):
    status: str


def _verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(settings.webhook_hmac_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


@router.post("/webhooks/scan", response_model=WebhookScanResponse, status_code=202)
async def webhook_scan(request: Request) -> WebhookScanResponse:
    if not settings.webhook_hmac_secret:
        raise HTTPException(status_code=503, detail="webhook not configured")

    raw_body = await request.body()
    signature = request.headers.get("X-Signature-256")
    if not _verify_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="invalid or missing signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc

    path = payload.get("path")
    # Same real access-control gate as POST /scan[/stream] — settings.scan_roots was
    # previously only surfaced as UI text, never actually enforced here either.
    if not path or not settings.is_within_scan_roots(path) or not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=f"not a directory: {path}")

    pool = await get_arq_pool()
    # arq's _job_id dedup covers both a still-queued/in-progress job AND one whose
    # result is still retained (keep_result) — so this also debounces a webhook
    # firing again for a path that was already scanned very recently, not just one
    # that's still running.
    job = await pool.enqueue_job("scan_repository_job", path, _job_id=f"webhook-scan:{path}")
    return WebhookScanResponse(status="enqueued" if job is not None else "duplicate")
