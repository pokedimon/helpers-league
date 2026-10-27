import csv
import os
import re
import time
import requests
import urllib3
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

TOKEN = os.getenv("MAX_BOT_TOKEN")
BASE_URL = "https://platform-api2.max.ru"
HEADERS = {"Authorization": TOKEN}

LONG_POLL_TIMEOUT = 30
HTTP_TIMEOUT = LONG_POLL_TIMEOUT + 15

BOT_ID = None
DB_DIR = "db"
CSV_FILE = os.path.join(DB_DIR, "questions.csv")
CSV_HEADERS = ["mid", "asker_id", "asker_name", "question", "chat_id"]


def init_csv():
    os.makedirs(DB_DIR, exist_ok=True)
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)


def save_question(mid, asker_id, asker_name, question, chat_id=None):
    if not mid:
        return
    init_csv()
    with open(CSV_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([str(mid), asker_id, asker_name, question, chat_id if chat_id is not None else ""])


def get_question(mid):
    if not mid or not os.path.exists(CSV_FILE):
        return None
    mid_str = str(mid)
    result = None
    with open(CSV_FILE, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("mid") == mid_str:
                result = {
                    "asker_id": int(row["asker_id"]) if row.get("asker_id") else None,
                    "asker_name": row.get("asker_name", ""),
                    "question": row.get("question", ""),
                    "chat_id": int(row["chat_id"]) if row.get("chat_id") else None,
                }
    return result


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


def get_user_name(user):
    if not user:
        return "Аноним"
    name = user.get("name")
    if name:
        return name.strip()
    first_name = (user.get("first_name") or "").strip()
    last_name = (user.get("last_name") or "").strip()
    full_name = f"{first_name} {last_name}".strip()
    if full_name:
        return full_name
    if user.get("username"):
        return f"@{user.get('username')}"
    user_id = user.get("user_id")
    if user_id:
        return f"Пользователь {user_id}"
    return "Пользователь"


def send_message(text, chat_id=None, user_id=None, reply_to_mid=None):
    params = {}
    if chat_id is not None and int(chat_id) != 0:
        params["chat_id"] = int(chat_id)
    elif user_id is not None and int(user_id) != 0:
        params["user_id"] = int(user_id)
    else:
        return None

    payload = {"text": text}
    if reply_to_mid:
        payload["link"] = {
            "type": "reply",
            "mid": str(reply_to_mid),
        }

    try:
        response = requests.post(
            f"{BASE_URL}/messages",
            params=params,
            json=payload,
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


def extract_mid_from_send_response(res):
    if not res:
        return None
    msg_obj = res.get("message") or res
    msg_body = msg_obj.get("body") or {}
    return msg_body.get("mid") or msg_obj.get("mid") or msg_obj.get("message_id")


def handle_update(update):
    utype = update.get("update_type")

    if utype == "bot_started":
        chat_id = update.get("chat_id")
        user = update.get("user") or {}
        user_id = user.get("user_id")
        welcome_text = "Привет! Чтобы задать вопрос, используйте: /ask <ваш вопрос>"
        if chat_id is not None and int(chat_id) != 0:
            send_message(welcome_text, chat_id=int(chat_id))
        elif user_id is not None and int(user_id) != 0:
            send_message(welcome_text, user_id=int(user_id))
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

        body = message.get("body") or {}
        mid = body.get("mid") or message.get("mid") or message.get("message_id") or update.get("message_id")
        text = (body.get("text") or message.get("text") or "").strip()

        print(f"[received] chat_type={chat_type} chat_id={chat_id} sender_id={sender_id} mid={mid} text={text}")

        ask_match = re.match(r"^/ask(?:@\w+)?(?:\s+([\s\S]+))?$", text, re.IGNORECASE)
        if ask_match:
            question = (ask_match.group(1) or "").strip()
            if not question:
                help_text = "Чтобы задать вопрос, укажите текст: /ask <ваш вопрос>"
                if chat_type == "chat" or (chat_id is not None and int(chat_id) != 0 and chat_type != "dialog"):
                    send_message(help_text, chat_id=int(chat_id), reply_to_mid=mid)
                elif sender_id is not None and int(sender_id) != 0:
                    send_message(help_text, user_id=int(sender_id), reply_to_mid=mid)
                return

            sender_name = get_user_name(sender)
            reply_text = f"Вопрос от {sender_name}:\n{question}"
            target_chat_id = None
            if chat_type == "chat" or (chat_id is not None and int(chat_id) != 0 and chat_type != "dialog"):
                target_chat_id = int(chat_id)
                res = send_message(reply_text, chat_id=target_chat_id, reply_to_mid=mid)
            elif sender_id is not None and int(sender_id) != 0:
                res = send_message(reply_text, user_id=int(sender_id), reply_to_mid=mid)

            bot_mid = extract_mid_from_send_response(res)
            if bot_mid:
                save_question(bot_mid, sender_id, sender_name, question, target_chat_id)
            if mid:
                save_question(mid, sender_id, sender_name, question, target_chat_id)
            return

        reply_match = re.match(r"^/reply(?:@\w+)?(?:\s+([\s\S]+))?$", text, re.IGNORECASE)
        if reply_match:
            answer = (reply_match.group(1) or "").strip()
            if not answer:
                help_text = "Чтобы ответить, укажите текст: /reply <ваш ответ>"
                if chat_type == "chat" or (chat_id is not None and int(chat_id) != 0 and chat_type != "dialog"):
                    send_message(help_text, chat_id=int(chat_id), reply_to_mid=mid)
                elif sender_id is not None and int(sender_id) != 0:
                    send_message(help_text, user_id=int(sender_id), reply_to_mid=mid)
                return

            link = message.get("link") or {}
            link_msg = link.get("message") or {}
            linked_mid = link_msg.get("mid") or link.get("mid")
            linked_sender = link.get("sender") or {}
            linked_sender_id = linked_sender.get("user_id")

            question_data = get_question(linked_mid) if linked_mid else None
            asker_id = None
            if question_data:
                asker_id = question_data.get("asker_id")
            elif linked_sender_id and linked_sender_id != current_bot_id:
                asker_id = linked_sender_id

            if asker_id:
                replier_name = get_user_name(sender)
                notification_text = f"На Ваш вопрос ответили\n{replier_name}:\n{answer}"
                send_message(notification_text, user_id=int(asker_id))
            return


def poll():
    if not TOKEN:
        print("MAX_BOT_TOKEN is not set in .env")
        return

    init_csv()
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
