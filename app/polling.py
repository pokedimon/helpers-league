import asyncio
import sys
from typing import Optional
from app.config import get_settings
from app.database.session import init_db
from app.services.bot_service import handle_update
from app.services.max_client import MaxBotClient, get_bot_client

async def run_polling(client: Optional[MaxBotClient] = None) -> None:
    await init_db()
    settings = get_settings()
    active_client = client or get_bot_client()
    if not settings.MAX_BOT_TOKEN and not active_client.token:
        print("Error: MAX_BOT_TOKEN is not set in environment or .env file", file=sys.stderr)
        return

    marker: Optional[int] = None
    print("MAX Bot Long Polling started. Press Ctrl+C to stop.")

    while True:
        try:
            data = await active_client.get_updates(limit=100, timeout=30, marker=marker)
            updates = data.get("updates", [])
            for update in updates:
                try:
                    await handle_update(update, client=active_client)
                except Exception as update_err:
                    err_detail = getattr(update_err, "response_data", None)
                    if err_detail:
                        print(f"Error handling update: {update_err} ({err_detail})", file=sys.stderr)
                    else:
                        print(f"Error handling update: {update_err}", file=sys.stderr)
            new_marker = data.get("marker")
            if new_marker is not None:
                marker = new_marker
        except (asyncio.CancelledError, KeyboardInterrupt):
            print("\nLong polling stopped.")
            break
        except Exception as poll_err:
            print(f"Polling connection error: {poll_err}", file=sys.stderr)
            await asyncio.sleep(2)

def main() -> None:
    try:
        asyncio.run(run_polling())
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    main()

