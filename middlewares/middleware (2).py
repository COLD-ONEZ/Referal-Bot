"""
Middlewares
- AntiSpamMiddleware: rate limiting on incoming messages
- UserUpdateMiddleware: auto-create user in DB and check ban status
"""
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from database import users_db
from utils.rate_limiter import is_rate_limited

logger = logging.getLogger(__name__)


class AntiSpamMiddleware(BaseMiddleware):
    """Drop messages from users who are sending too fast."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user and is_rate_limited(user.id):
            logger.debug(f"Rate limited user {user.id}")
            if isinstance(event, CallbackQuery):
                await event.answer("⏳ Please slow down!", show_alert=False)
            return  # Drop the update silently

        return await handler(event, data)


class UserUpdateMiddleware(BaseMiddleware):
    """
    Ensure every interacting user exists in the database.
    Injects 'db_user' into handler data dict.
    Blocks banned users.

    Performance: we do a single create_user upsert (which also keeps
    username/full_name fresh), then ONE get_user fetch that provides
    both the ban flag and the full document for handlers — down from
    the original 3–4 serial round-trips per update.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user and not user.is_bot:
            # 1) Upsert — creates if new, updates name/username if existing
            await users_db.create_user(
                user_id=user.id,
                username=user.username,
                full_name=user.full_name,
            )

            # 2) Single fetch — covers both ban check and injecting db_user for handlers
            db_user = await users_db.get_user(user.id)

            if db_user and db_user.get("is_banned"):
                if isinstance(event, Message):
                    await event.answer("🚫 You are banned from this bot.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🚫 You are banned.", show_alert=True)
                return

            data["db_user"] = db_user

        return await handler(event, data)
