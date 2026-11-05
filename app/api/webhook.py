from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from app.services.auth import validate_webhook_secret

router = APIRouter(tags=["webhook"])

async def dispatch_update_task(update: dict[str, Any]) -> None:
    try:
        from app.services.bot_service import handle_update
        await handle_update(update)
    except Exception:
        pass

@router.post("/webhook")
async def handle_webhook(
    update: dict[str, Any],
    background_tasks: BackgroundTasks,
    _: None = Depends(validate_webhook_secret),
):
    background_tasks.add_task(dispatch_update_task, update)
    return {"status": "ok"}
