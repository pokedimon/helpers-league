import hashlib
import hmac
import json
from typing import Any, Callable, Optional, Sequence
from urllib.parse import parse_qsl
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database.models import User
from app.database.session import get_db_session

def validate_init_data(init_data: str, bot_token: str) -> dict[str, str]:
    if not init_data:
        raise ValueError("Empty initData")
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    if "hash" not in parsed:
        raise ValueError("Missing hash parameter")
    received_hash = parsed.pop("hash")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash.lower(), received_hash.lower()):
        raise ValueError("Invalid initData signature")
    return parsed

def parse_user_payload(raw_user: str) -> dict[str, Any]:
    try:
        user_data = json.loads(raw_user)
        if not isinstance(user_data, dict):
            raise ValueError("User payload must be a JSON object")
        if "id" not in user_data and "user_id" not in user_data:
            raise ValueError("Missing user id")
        return user_data
    except json.JSONDecodeError as err:
        raise ValueError("Malformed user JSON") from err

async def get_or_create_user(
    session: AsyncSession,
    max_user_id: str,
    display_name: str,
    default_role: str = "student",
    role_override: Optional[str] = None,
) -> User:
    query = select(User).where(User.max_user_id == max_user_id)
    result = await session.execute(query)
    user = result.scalar_one_or_none()
    if user is None:
        target_role = role_override or default_role
        if target_role not in ("student", "teacher", "admin"):
            target_role = "student"
        user = User(
            max_user_id=max_user_id,
            display_name=display_name or f"User {max_user_id}",
            role=target_role,
            balance_spasibki=0,
            xp=0,
            rank="Новичок",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    elif role_override is not None and role_override in ("student", "teacher", "admin") and user.role != role_override:
        user.role = role_override
        await session.commit()
        await session.refresh(user)
    return user

async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> User:
    header_user_id = request.headers.get("X-User-Id") or request.headers.get("X-Max-User-Id")
    if header_user_id:
        role_override = request.headers.get("X-User-Role")
        display_name = (
            request.headers.get("X-User-First-Name")
            or request.headers.get("X-User-Name")
            or f"User {header_user_id}"
        )
        return await get_or_create_user(
            session=session,
            max_user_id=header_user_id,
            display_name=display_name,
            default_role="student",
            role_override=role_override,
        )

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if "hash=" in token or "query_id=" in token or "user=" in token:
            pass
        elif token:
            role_override = request.headers.get("X-User-Role")
            display_name = (
                request.headers.get("X-User-First-Name")
                or request.headers.get("X-User-Name")
                or f"User {token}"
            )
            return await get_or_create_user(
                session=session,
                max_user_id=token,
                display_name=display_name,
                default_role="student",
                role_override=role_override,
            )

    query_user_id = request.query_params.get("user_id")
    if query_user_id:
        role_override = request.headers.get("X-User-Role") or request.query_params.get("role")
        name = (
            request.headers.get("X-User-First-Name")
            or request.query_params.get("name")
            or f"User {query_user_id}"
        )
        return await get_or_create_user(
            session=session,
            max_user_id=query_user_id,
            display_name=name,
            default_role="student",
            role_override=role_override,
        )

    cookie_user_id = request.cookies.get("user_id") or request.cookies.get("hl_user_id")
    if cookie_user_id:
        role_override = request.headers.get("X-User-Role") or request.cookies.get("user_role")
        return await get_or_create_user(
            session=session,
            max_user_id=cookie_user_id,
            display_name=f"User {cookie_user_id}",
            default_role="student",
            role_override=role_override,
        )

    init_data_raw = (
        request.headers.get("X-Max-Init-Data")
        or request.query_params.get("initData")
        or request.query_params.get("init_data")
    )
    if not init_data_raw and auth_header and auth_header.startswith("initData "):
        init_data_raw = auth_header[9:].strip()
    elif not init_data_raw and auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if "hash=" in token or "query_id=" in token or "user=" in token:
            init_data_raw = token

    if init_data_raw:
        bot_token = settings.MAX_BOT_TOKEN
        try:
            if bot_token:
                parsed = validate_init_data(init_data_raw, bot_token)
            else:
                parsed = dict(parse_qsl(init_data_raw, keep_blank_values=True))
                if "hash" in parsed:
                    parsed.pop("hash")
            raw_user = parsed.get("user")
            if not raw_user and "user_id" in parsed:
                uid = str(parsed["user_id"])
                fn = parsed.get("first_name", "")
                ln = parsed.get("last_name", "")
                un = parsed.get("username", "")
                name = f"{fn} {ln}".strip() or un or f"User {uid}"
                return await get_or_create_user(
                    session=session,
                    max_user_id=uid,
                    display_name=name,
                    default_role="student",
                    role_override=None,
                )
            if not raw_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing user object in initData",
                )
            user_payload = parse_user_payload(raw_user)
            uid = str(user_payload.get("id") or user_payload.get("user_id"))
            fn = user_payload.get("first_name", "")
            ln = user_payload.get("last_name", "")
            un = user_payload.get("username", "")
            name = f"{fn} {ln}".strip() or un or f"User {uid}"
            return await get_or_create_user(
                session=session,
                max_user_id=uid,
                display_name=name,
                default_role="student",
                role_override=None,
            )
        except HTTPException:
            raise
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(err),
            ) from err

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication credentials",
    )

def require_role(allowed_roles: Sequence[str]) -> Callable[..., Any]:
    async def role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user
    return role_checker

require_teacher = require_role(["teacher", "admin"])

async def validate_webhook_secret(request: Request) -> None:
    expected_secret = settings.MAX_BOT_API_SECRET
    if not expected_secret:
        return
    secret_header = request.headers.get("X-Max-Bot-Api-Secret")
    if not secret_header or not hmac.compare_digest(secret_header, expected_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook secret",
        )
