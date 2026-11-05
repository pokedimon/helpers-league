from datetime import datetime, timezone
from typing import Any, Optional, Union
import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.database.models import Answer, Question, User
from app.database.session import async_session_factory
from app.services.anti_cheat import AntiCheatService
from app.services.gamification import GamificationService
from app.services.max_client import (
    KeyboardBuilder,
    MaxApiError,
    MaxAuthError,
    MaxBotClient,
    MaxNetworkError,
    build_callback_button,
    build_link_button,
    build_open_app_button,
    build_teacher_menu_keyboard,
    build_verification_keyboard,
    format_inline_keyboard,
    get_bot_client,
)

def to_int_id(val: Any) -> Optional[int]:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s.startswith("-") and s[1:].isdigit():
        return -int(s[1:])
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits:
        val_int = int(digits)
        return -val_int if s.startswith("-") else val_int
    return None

class BotService:
    def __init__(self, client: Optional[MaxBotClient] = None) -> None:
        self.client = client or get_bot_client()

    async def ensure_user(
        self,
        session: AsyncSession,
        max_user_id: Union[int, str],
        display_name: Optional[str] = None,
        role: str = "student",
    ) -> User:
        uid_str = str(max_user_id).strip()
        conditions = [User.max_user_id == uid_str]
        if uid_str.isdigit():
            conditions.append(User.max_user_id.endswith(f"_{uid_str}"))
        if display_name:
            conditions.append(User.display_name == display_name)
        stmt = select(User).where(or_(*conditions))
        res = await session.execute(stmt)
        user = res.scalars().first()
        if user is None:
            name = display_name or f"Ученик {uid_str}"
            user = User(
                max_user_id=uid_str,
                display_name=name,
                role=role,
                balance_spasibki=0,
                xp=0,
                rank="Новичок",
            )
            session.add(user)
            await session.flush()
        return user

    async def handle_ask_command(
        self,
        session: AsyncSession,
        message: dict[str, Any],
        client: MaxBotClient,
    ) -> None:
        recipient = message.get("recipient", {})
        chat_type = recipient.get("chat_type")
        raw_chat_id = message.get("chat_id") or recipient.get("chat_id")
        sender = message.get("sender", {})
        raw_sender_id = str(sender.get("user_id", ""))
        sender_name = sender.get("name") or sender.get("username") or f"Ученик {raw_sender_id}"
        user = await self.ensure_user(session, raw_sender_id, display_name=sender_name)
        sender_id = user.max_user_id

        raw_text = (
            message.get("body", {}).get("text")
            if isinstance(message.get("body"), dict)
            else None
        ) or message.get("text") or ""
        raw_text = raw_text.strip()
        parts = raw_text.split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            return
        question_text = parts[1].strip()

        announcement = (
            f"❓ Вопрос от пользователя {sender_name}:\n"
            f"{question_text}\n"
            f"Ответьте реплаем на это сообщение, чтобы помочь!"
        )
        target_chat_id = to_int_id(raw_chat_id) or raw_chat_id
        target_uid = to_int_id(raw_sender_id) or raw_sender_id

        if target_chat_id and target_chat_id != 0 and chat_type != "dialog" and target_chat_id != target_uid:
            resp = await client.send_message(chat_id=target_chat_id, text=announcement)
            group_cid = str(target_chat_id)
        else:
            resp = await client.send_message(user_id=target_uid, text=announcement)
            group_cid = str(target_uid)

        bot_msg = resp.get("message", {})
        bot_mid = (
            bot_msg.get("body", {}).get("mid")
            if isinstance(bot_msg.get("body"), dict)
            else None
        ) or bot_msg.get("id") or bot_msg.get("mid") or ""

        question = Question(
            group_chat_id=group_cid,
            group_message_id=str(bot_mid),
            author_max_id=sender_id,
            text=question_text,
            status="open",
        )
        session.add(question)
        await session.flush()
        await GamificationService.evaluate_achievements(session, sender_id)
        await session.commit()

    async def handle_reply_message(
        self,
        session: AsyncSession,
        message: dict[str, Any],
        client: MaxBotClient,
        reply_to_mid: str,
    ) -> None:
        recipient = message.get("recipient", {})
        chat_type = recipient.get("chat_type")
        raw_chat_id = message.get("chat_id") or recipient.get("chat_id")
        sender = message.get("sender", {})
        raw_sender_id = str(sender.get("user_id", ""))
        sender_name = sender.get("name") or sender.get("username") or f"Ученик {raw_sender_id}"
        user = await self.ensure_user(session, raw_sender_id, display_name=sender_name)
        sender_id = user.max_user_id

        stmt = select(Question).where(
            Question.group_message_id == str(reply_to_mid),
            Question.status == "open",
        )
        res = await session.execute(stmt)
        question = res.scalar_one_or_none()
        if question is None:
            return

        is_same_author = (
            str(question.author_max_id).strip().lower() == sender_id.strip().lower()
            or str(question.author_max_id).strip().lower() == raw_sender_id.strip().lower()
            or to_int_id(question.author_max_id) == to_int_id(raw_sender_id)
        )
        target_chat = to_int_id(raw_chat_id) or raw_chat_id
        target_uid = to_int_id(raw_sender_id) or raw_sender_id

        if is_same_author or not AntiCheatService.validate_answer_eligibility(question.author_max_id, sender_id):
            reject_text = f"⚠️ {sender_name}, вы не можете отвечать на собственный вопрос в Лиге Помощников!"
            if target_chat and target_chat != 0 and chat_type != "dialog" and target_chat != target_uid:
                await client.send_message(chat_id=target_chat, text=reject_text)
            else:
                await client.send_message(user_id=target_uid, text=reject_text)
            return

        incoming_mid = (
            message.get("body", {}).get("mid")
            if isinstance(message.get("body"), dict)
            else None
        ) or message.get("id") or message.get("mid") or ""
        answer_text = (
            message.get("body", {}).get("text")
            if isinstance(message.get("body"), dict)
            else None
        ) or message.get("text") or ""

        answer = Answer(
            question_id=question.id,
            author_max_id=sender_id,
            group_message_id=str(incoming_mid),
            text=answer_text,
            status="pending",
        )
        session.add(answer)
        await session.flush()

        keyboard = KeyboardBuilder.question_verification_keyboard(answer.id)
        author_target_uid = to_int_id(question.author_max_id)
        dm_resp = await client.send_message(
            user_id=author_target_uid,
            text=f"К вашему вопросу получен ответ:\n\"{answer_text}\"\nПомог ли этот ответ?",
            attachments=keyboard,
        )
        dm_msg = dm_resp.get("message", {})
        dm_mid = (
            dm_msg.get("body", {}).get("mid")
            if isinstance(dm_msg.get("body"), dict)
            else None
        ) or dm_msg.get("id") or dm_msg.get("mid")
        if dm_mid:
            answer.dm_approval_message_id = str(dm_mid)
        await session.commit()

    async def handle_manage_command(
        self,
        session: AsyncSession,
        message: dict[str, Any],
        client: MaxBotClient,
    ) -> None:
        recipient = message.get("recipient", {})
        chat_type = recipient.get("chat_type")
        raw_chat_id = message.get("chat_id") or recipient.get("chat_id")
        sender = message.get("sender", {})
        raw_sender_id = str(sender.get("user_id", ""))
        sender_name = sender.get("name") or sender.get("username")
        user = await self.ensure_user(session, raw_sender_id, display_name=sender_name)
        target_uid = to_int_id(raw_sender_id)
        target_chat = to_int_id(raw_chat_id) or raw_chat_id
        is_group = target_chat and target_chat != 0 and chat_type != "dialog" and target_chat != target_uid

        if user.role not in ("teacher", "admin"):
            err_text = "⛔ Доступ запрещен. Панель управления доступна только учителям и администраторам."
            if is_group:
                await client.send_message(chat_id=target_chat, text=err_text)
            else:
                await client.send_message(user_id=target_uid, text=err_text)
            return

        webapp_url = f"http://localhost:8000/webapp?user_id={user.max_user_id}"
        keyboard = KeyboardBuilder.teacher_menu_keyboard(webapp_url)
        menu_text = "👨‍🏫 Панель управления учителя\nИспользуйте веб-кабинет для модерации вопросов, подтверждения наград и управления балансами:"
        if is_group:
            await client.send_message(chat_id=target_chat, text=menu_text, attachments=keyboard)
        else:
            await client.send_message(user_id=target_uid, text=menu_text, attachments=keyboard)

    async def handle_message_callback(
        self,
        session: AsyncSession,
        callback: dict[str, Any],
        client: MaxBotClient,
    ) -> None:
        callback_id = str(callback.get("callback_id", ""))
        payload = str(callback.get("payload", "")).strip()
        user_info = callback.get("user", {})
        raw_user_id = str(user_info.get("user_id", ""))
        user = await self.ensure_user(session, raw_user_id, display_name=user_info.get("name"))

        answer_id: Optional[int] = None
        decision: Optional[str] = None

        if payload.startswith("verify_help:"):
            parts = payload.split(":")
            if len(parts) >= 3 and parts[1].isdigit():
                answer_id = int(parts[1])
                decision = parts[2]
        elif payload.startswith("verify_yes:"):
            parts = payload.split(":")
            if len(parts) >= 2 and parts[1].isdigit():
                answer_id = int(parts[1])
                decision = "yes"
        elif payload.startswith("verify_no:"):
            parts = payload.split(":")
            if len(parts) >= 2 and parts[1].isdigit():
                answer_id = int(parts[1])
                decision = "no"

        if answer_id is None or decision not in ("yes", "no"):
            return

        ans_stmt = select(Answer).where(Answer.id == answer_id)
        ans_res = await session.execute(ans_stmt)
        answer = ans_res.scalar_one_or_none()
        if answer is None:
            await client.answer_callback(callback_id=callback_id, notification="Ответ не найден")
            return

        if answer.status != "pending":
            await client.answer_callback(callback_id=callback_id, notification="Ответ уже обработан")
            return

        q_stmt = select(Question).where(Question.id == answer.question_id)
        q_res = await session.execute(q_stmt)
        question = q_res.scalar_one_or_none()
        if question is None:
            await client.answer_callback(callback_id=callback_id, notification="Вопрос не найден")
            return

        is_author = (
            str(question.author_max_id).strip().lower() == user.max_user_id.strip().lower()
            or str(question.author_max_id).strip().lower() == raw_user_id.strip().lower()
            or to_int_id(question.author_max_id) == to_int_id(raw_user_id)
        )
        if not is_author:
            await client.answer_callback(
                callback_id=callback_id,
                notification="Только автор вопроса может подтвердить ответ!",
            )
            return

        helper_uid = to_int_id(answer.author_max_id)
        group_cid = to_int_id(question.group_chat_id) or question.group_chat_id

        if decision == "yes":
            spasibki, xp = await GamificationService.award_gratitude(session, question, answer)
            await client.answer_callback(
                callback_id=callback_id,
                notification="Благодарность отправлена помощнику!",
                message={"text": "✅ Вопрос закрыт. Спасибо за подтверждение!"},
            )
            await client.send_message(
                user_id=helper_uid,
                text=f"Твой ответ помог однокласснику! Начислено: +{spasibki} спасибка, +{xp} XP ⭐️",
            )
            if group_cid and str(group_cid).strip() != "0" and to_int_id(group_cid) != helper_uid:
                helper_stmt = select(User).where(User.max_user_id == answer.author_max_id)
                helper_res = await session.execute(helper_stmt)
                helper_user = helper_res.scalar_one_or_none()
                helper_name = helper_user.display_name if helper_user else "пользователю"
                await client.send_message(
                    chat_id=group_cid,
                    text=f"🎉 Вопрос решён! Спасибо {helper_name} за помощь.",
                )
        else:
            answer.status = "rejected"
            await session.commit()
            await client.answer_callback(
                callback_id=callback_id,
                notification="Принято",
                message={"text": "Принято. Вопрос остаётся открытым, ждём другие ответы."},
            )
            await client.send_message(
                user_id=helper_uid,
                text="Автор отметил, что ответ не решил вопрос полностью, но спасибо за участие!",
            )
            if group_cid and str(group_cid).strip() != "0" and to_int_id(group_cid) != helper_uid:
                await client.send_message(
                    chat_id=group_cid,
                    text="Ответ пока не помог решить вопрос. Другие ответы по-прежнему принимаются! ✍️",
                )

    async def handle_bot_started(
        self,
        session: AsyncSession,
        update: dict[str, Any],
        client: MaxBotClient,
    ) -> None:
        user_info = update.get("user", {})
        uid = str(user_info.get("user_id", ""))
        name = user_info.get("name") or user_info.get("username") or f"Ученик {uid}"
        await self.ensure_user(session, uid, display_name=name)
        chat_id = update.get("chat_id")
        user_target = to_int_id(uid)
        c_id = to_int_id(chat_id)
        welcome_text = (
            f"Привет, {name}! Добро пожаловать в Лигу Помощников 🎓\n"
            "Задавай вопросы в чате класса с помощью команды /ask или отвечай на вопросы одноклассников, чтобы получать спасибоки и опыт!"
        )
        if c_id and c_id != 0 and c_id != user_target:
            await client.send_message(chat_id=c_id, text=welcome_text)
        else:
            await client.send_message(user_id=user_target, text=welcome_text)

    async def handle_message_created(
        self,
        session: AsyncSession,
        message: dict[str, Any],
        client: MaxBotClient,
    ) -> None:
        raw_text = (
            message.get("body", {}).get("text")
            if isinstance(message.get("body"), dict)
            else None
        ) or message.get("text") or ""
        text = raw_text.strip()

        if text.startswith("/ask"):
            await self.handle_ask_command(session, message, client)
            return

        if text.startswith("/manage"):
            await self.handle_manage_command(session, message, client)
            return

        if text.startswith(("/start", "/help")) or text.lower() in ("привет", "здравствуйте", "помощь", "меню", "хелп", "start", "help"):
            recipient = message.get("recipient", {})
            chat_type = recipient.get("chat_type")
            raw_chat_id = message.get("chat_id") or recipient.get("chat_id")
            sender = message.get("sender", {})
            raw_sender_id = str(sender.get("user_id", ""))
            sender_name = sender.get("name") or sender.get("username") or f"Ученик {raw_sender_id}"
            await self.ensure_user(session, raw_sender_id, display_name=sender_name)
            target_chat = to_int_id(raw_chat_id) or raw_chat_id
            target_uid = to_int_id(raw_sender_id)
            help_text = (
                f"👋 Привет, {sender_name}! Я бот «Лига Помощников» 🎓\n\n"
                "📌 Как мной пользоваться:\n"
                "• В чате класса отправьте команду `/ask <текст вопроса>`, чтобы попросить помощи.\n"
                "• Отвечайте реплаем (ответом) на сообщение бота с вопросом, чтобы помочь однокласснику.\n"
                "• Автор вопроса получит кнопки с подтверждением и начислит вам спасибоки и опыт! ⭐️\n"
                "• Для учителей доступна команда `/manage` для открытия панели управления."
            )
            if target_chat and target_chat != 0 and chat_type != "dialog" and target_chat != target_uid:
                await client.send_message(chat_id=target_chat, text=help_text)
            else:
                await client.send_message(user_id=target_uid, text=help_text)
            return

        reply_to_mid = None
        if "reply_to" in message and message["reply_to"]:
            rt = message["reply_to"]
            if isinstance(rt, dict):
                reply_to_mid = rt.get("id") or rt.get("mid")
            else:
                reply_to_mid = str(rt)
        elif "link" in message and isinstance(message["link"], dict):
            link = message["link"]
            reply_to_mid = link.get("id") or link.get("mid")
            if not reply_to_mid and "message" in link and isinstance(link["message"], dict):
                reply_to_mid = link["message"].get("mid") or link["message"].get("id")

        if reply_to_mid:
            await self.handle_reply_message(session, message, client, str(reply_to_mid))

    async def dispatch(
        self,
        session: AsyncSession,
        update: dict[str, Any],
        client: Optional[MaxBotClient] = None,
    ) -> None:
        active_client = client or self.client
        utype = update.get("update_type")
        if utype == "message_created":
            await self.handle_message_created(session, update.get("message", {}), active_client)
        elif utype == "message_callback":
            await self.handle_message_callback(session, update.get("callback", {}), active_client)
        elif utype == "bot_started":
            await self.handle_bot_started(session, update, active_client)

default_bot_service = BotService()

async def handle_update(
    arg1: Any = None,
    arg2: Any = None,
    *,
    session: Optional[AsyncSession] = None,
    update: Optional[dict[str, Any]] = None,
    client: Optional[MaxBotClient] = None,
) -> None:
    target_session: Optional[AsyncSession] = session
    target_update: Optional[dict[str, Any]] = update

    if isinstance(arg1, AsyncSession):
        target_session = arg1
        if isinstance(arg2, dict):
            target_update = arg2
    elif isinstance(arg1, dict):
        target_update = arg1
        if isinstance(arg2, AsyncSession):
            target_session = arg2

    if target_update is None:
        return

    active_client = client or get_bot_client()

    if target_session is not None:
        await default_bot_service.dispatch(target_session, target_update, client=active_client)
    else:
        async with async_session_factory() as new_session:
            await default_bot_service.dispatch(new_session, target_update, client=active_client)
