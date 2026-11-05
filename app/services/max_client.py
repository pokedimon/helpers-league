import asyncio
from typing import Any, Optional, Union
import httpx
from app.config import get_settings

class MaxApiError(Exception):
    def __init__(self, message: str, status_code: int = 500, response_data: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_data = response_data

class MaxAuthError(MaxApiError):
    pass

class MaxNetworkError(MaxApiError):
    pass

def build_callback_button(text: str, payload: str = "", callback_data: Optional[str] = None) -> dict[str, Any]:
    return {
        "type": "callback",
        "text": text,
        "payload": callback_data if callback_data is not None else payload,
    }

def build_link_button(text: str, url: str) -> dict[str, Any]:
    return {
        "type": "link",
        "text": text,
        "url": url,
    }

def build_open_app_button(
    text: str,
    web_app: str = "",
    payload: Optional[str] = None,
    url: Optional[str] = None,
) -> dict[str, Any]:
    btn: dict[str, Any] = {
        "type": "open_app",
        "text": text,
    }
    if web_app:
        btn["web_app"] = web_app
    if payload is not None:
        btn["payload"] = payload
    if url is not None:
        btn["url"] = url
    return btn

def format_inline_keyboard(buttons: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "inline_keyboard",
            "payload": {
                "buttons": buttons,
            },
        }
    ]

def build_verification_keyboard(answer_id: Union[int, str]) -> list[dict[str, Any]]:
    return format_inline_keyboard(
        [
            [
                build_callback_button("✅ Помог", payload=f"verify_help:{answer_id}:yes"),
                build_callback_button("❌ Не помог", payload=f"verify_help:{answer_id}:no"),
            ]
        ]
    )

def build_teacher_menu_keyboard(webapp_url: str) -> list[dict[str, Any]]:
    return format_inline_keyboard(
        [
            [
                build_link_button("Панель учителя (Webapp)", url=webapp_url)
            ]
        ]
    )

class KeyboardBuilder:
    @staticmethod
    def question_verification_keyboard(answer_id: Union[int, str]) -> list[dict[str, Any]]:
        return build_verification_keyboard(answer_id)

    @staticmethod
    def teacher_menu_keyboard(webapp_url: str) -> list[dict[str, Any]]:
        return build_teacher_menu_keyboard(webapp_url)

class MaxBotClient:
    def __init__(
        self,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        transport: Optional[Union[httpx.BaseTransport, httpx.AsyncBaseTransport]] = None,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        verify_ssl: Optional[bool] = None,
    ) -> None:
        settings = get_settings()
        self.token = token if token is not None else settings.MAX_BOT_TOKEN
        raw_url = base_url if base_url is not None else settings.MAX_API_BASE_URL
        self.base_url = raw_url.rstrip("/")
        self.transport = transport
        self.client = client
        self.timeout = timeout
        self.max_retries = max_retries
        self.verify_ssl = verify_ssl if verify_ssl is not None else settings.MAX_SSL_VERIFY

    @property
    def headers(self) -> dict[str, str]:
        hdr: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.token:
            hdr["Authorization"] = self.token
        return hdr

    async def _send_request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        retries = max(1, self.max_retries)
        last_error: Optional[Exception] = None
        req_timeout = timeout if timeout is not None else self.timeout

        for attempt in range(retries):
            try:
                if self.client is not None:
                    response = await self.client.request(
                        method=method,
                        url=url,
                        params=params,
                        json=json_data,
                        headers=self.headers,
                        timeout=req_timeout,
                    )
                else:
                    async with httpx.AsyncClient(
                        transport=self.transport,
                        timeout=req_timeout,
                        headers=self.headers,
                        verify=self.verify_ssl,
                    ) as direct_client:
                        response = await direct_client.request(
                            method=method,
                            url=url,
                            params=params,
                            json=json_data,
                        )

                if response.status_code == 401 or response.status_code == 403:
                    raise MaxAuthError(
                        message=f"Authentication failed with status {response.status_code}",
                        status_code=response.status_code,
                        response_data=response.text,
                    )

                if 400 <= response.status_code < 500:
                    raise MaxApiError(
                        message=f"Client request failed with status {response.status_code}",
                        status_code=response.status_code,
                        response_data=response.text,
                    )

                if response.status_code >= 500:
                    if attempt < retries - 1:
                        await asyncio.sleep(0.05 * (2 ** attempt))
                        continue
                    raise MaxApiError(
                        message=f"Server error with status {response.status_code}",
                        status_code=response.status_code,
                        response_data=response.text,
                    )

                if not response.content:
                    return {"success": True}
                return response.json()

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt < retries - 1:
                    await asyncio.sleep(0.05 * (2 ** attempt))
                    continue
                raise MaxNetworkError(
                    message=f"Network communication failed: {exc}",
                    status_code=504,
                ) from exc

        if last_error is not None:
            raise MaxNetworkError(message=str(last_error))
        raise MaxApiError(message="Unexpected request termination")

    async def get_me(self) -> dict[str, Any]:
        return await self._send_request(method="GET", path="/me")

    async def send_message(
        self,
        chat_id: Optional[Union[int, str]] = None,
        user_id: Optional[Union[int, str]] = None,
        text: str = "",
        attachments: Optional[list[dict[str, Any]]] = None,
        reply_to: Optional[Union[int, str]] = None,
        format: str = "markdown",
        format_type: Optional[str] = None,
        disable_link_preview: bool = False,
        link: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if chat_id is not None:
            c_str = str(chat_id).strip()
            if c_str.lstrip("-").isdigit():
                params["chat_id"] = int(c_str)
            else:
                params["chat_id"] = chat_id
        if user_id is not None:
            params["user_id"] = int(user_id) if str(user_id).isdigit() else user_id
        if disable_link_preview:
            params["disable_link_preview"] = True

        fmt = format_type or format
        body: dict[str, Any] = {
            "text": text,
            "format": fmt,
        }
        if attachments is not None:
            body["attachments"] = attachments
        if link is not None:
            body["link"] = link
        elif reply_to is not None:
            body["link"] = {
                "type": "reply",
                "mid": str(reply_to),
            }

        return await self._send_request(
            method="POST",
            path="/messages",
            params=params,
            json_data=body,
        )

    async def answer_callback(
        self,
        callback_id: str,
        text: Optional[str] = None,
        notification: Optional[str] = None,
        message: Optional[dict[str, Any]] = None,
        disable_link_preview: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "callback_id": str(callback_id),
        }
        if disable_link_preview:
            params["disable_link_preview"] = True

        body: dict[str, Any] = {}
        if notification is not None:
            body["notification"] = notification
        if message is not None:
            body["message"] = message
        elif text is not None:
            body["message"] = {
                "text": text,
                "format": "markdown",
            }

        return await self._send_request(
            method="POST",
            path="/answers",
            params=params,
            json_data=body,
        )

    async def get_subscriptions(self) -> dict[str, Any]:
        return await self._send_request(method="GET", path="/subscriptions")

    async def subscribe(
        self,
        url: str,
        secret: Optional[str] = None,
        update_types: Optional[list[str]] = None,
        events: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "url": url,
        }
        if secret is not None:
            body["secret"] = secret
        target_events = events or update_types
        if target_events is not None:
            body["update_types"] = target_events
            body["events"] = target_events

        return await self._send_request(
            method="POST",
            path="/subscriptions",
            json_data=body,
        )

    async def unsubscribe(self, url: Optional[str] = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if url is not None:
            params["url"] = url

        return await self._send_request(
            method="DELETE",
            path="/subscriptions",
            params=params,
        )

    async def get_updates(
        self,
        limit: int = 100,
        timeout: int = 30,
        marker: Optional[int] = None,
        types: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
        }
        if marker is not None:
            params["marker"] = marker
        if types is not None:
            params["types"] = ",".join(types)

        return await self._send_request(
            method="GET",
            path="/updates",
            params=params,
            timeout=float(timeout + 15),
        )

_default_bot_client: Optional[MaxBotClient] = None

def get_bot_client(
    transport: Optional[Union[httpx.BaseTransport, httpx.AsyncBaseTransport]] = None,
    token: Optional[str] = None,
    base_url: Optional[str] = None,
    verify_ssl: Optional[bool] = None,
) -> MaxBotClient:
    global _default_bot_client
    if transport is not None or token is not None or base_url is not None or verify_ssl is not None:
        return MaxBotClient(
            token=token,
            base_url=base_url,
            transport=transport,
            verify_ssl=verify_ssl,
        )
    if _default_bot_client is None:
        _default_bot_client = MaxBotClient()
    return _default_bot_client
