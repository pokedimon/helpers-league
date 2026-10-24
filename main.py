import os
import time
import requests
import urllib3
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

TOKEN = os.getenv("MAX_BOT_TOKEN")
BASE_URL = "https://platform-api2.max.ru"
HEADERS = {"Authorization": TOKEN}

REPLY_TEXT = "привет"

LONG_POLL_TIMEOUT = 30
HTTP_TIMEOUT = LONG_POLL_TIMEOUT + 15

BOT_ID = None


def get_bot_id():
    global BOT_ID
    if BOT_ID is not None:
        return BOT_ID
    try:
        res = requests.get(f"{BASE_URL}/me", headers=HEADERS, timeout=10, verify=False)
        if res.status_code == 200:
            BOT_ID = res.json().get("user_id")
            return BOT_ID
    except Exception:
        pass
    return None


def send_message(text, chat_id=None, user_id=None):
    params = {}
    if chat_id is not None and int(chat_id) != 0:
        params["chat_id"] = int(chat_id)
    elif user_id is not None and int(user_id) != 0:
        params["user_id"] = int(user_id)
    else:
        return None

    try:
        response = requests.post(
            f"{BASE_URL}/messages",
            params=params,
            json={"text": text},
            headers=HEADERS,
            timeout=30,
            verify=False,
        )
        if response.status_code == 200:
            return response.json() if response.content else None
        print(f"[send error] {response.status_code}: {response.text}")
    except requests.RequestException as e:
        print(f"[network error] {e}")
    return None


def handle_update(update):
    utype = update.get("update_type")

    if utype == "bot_started":
        chat_id = update.get("chat_id")
        user = update.get("user") or {}
        user_id = user.get("user_id")

        if chat_id is not None and int(chat_id) != 0:
            send_message(REPLY_TEXT, chat_id=int(chat_id))
        elif user_id is not None and int(user_id) != 0:
            send_message(REPLY_TEXT, user_id=int(user_id))
        return

    if utype == "message_created":
        message = update.get("message") or {}
        sender = message.get("sender") or {}
        sender_id = sender.get("user_id")
        current_bot_id = get_bot_id()

        if sender_id == current_bot_id or sender.get("is_bot"):
            return

        recipient = message.get("recipient") or {}
        chat_type = recipient.get("chat_type")
        chat_id = recipient.get("chat_id") or message.get("chat_id") or update.get("chat_id")

        print(f"[received] chat_type={chat_type} chat_id={chat_id} sender_id={sender_id}")

        if chat_type == "chat" or (chat_id is not None and int(chat_id) != 0 and chat_type != "dialog"):
            send_message(REPLY_TEXT, chat_id=int(chat_id))
        elif sender_id is not None and int(sender_id) != 0:
            send_message(REPLY_TEXT, user_id=int(sender_id))


def poll():
    if not TOKEN:
        print("MAX_BOT_TOKEN is not set in .env")
        return

    get_bot_id()
    marker = None
    print(f"Responder is running (bot_id={BOT_ID}). Waiting for updates...")

    while True:
        params = {"timeout": LONG_POLL_TIMEOUT, "limit": 100}
        if marker is not None:
            params["marker"] = marker

        try:
            response = requests.get(
                f"{BASE_URL}/updates",
                params=params,
                headers=HEADERS,
                timeout=HTTP_TIMEOUT,
                verify=False,
            )
        except requests.Timeout:
            time.sleep(1)
            continue
        except requests.RequestException as e:
            print(f"[poll error] {e}")
            time.sleep(3)
            continue

        if response.status_code != 200:
            print(f"[poll error] {response.status_code}: {response.text}")
            time.sleep(3)
            continue

        try:
            data = response.json()
        except ValueError:
            time.sleep(3)
            continue

        marker = data.get("marker")
        for update in data.get("updates", []):
            try:
                handle_update(update)
            except Exception as e:
                print(f"[handle error] {e}")


if __name__ == "__main__":
    poll()
