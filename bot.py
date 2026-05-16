"""
Referral Reward Bot — Main Entry Point
Async aiogram 3.x bot with MongoDB backend
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import ErrorEvent

from config import BOT_TOKEN, INITIAL_REQUIRED_CHANNELS
from database.connection import connect as db_connect, close as db_close
from database import channels_db
from middlewares.middleware import AntiSpamMiddleware, UserUpdateMiddleware
from handlers import start, registration, admin, membership
from utils.logger import setup_logging

logger = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    """Run startup tasks: DB connect, seed channels, set bot commands."""
    logger.info("🚀 Starting Referral Bot...")

    # Connect to MongoDB
    await db_connect()

    # Seed initial required channels from env (if any)
    for ch_id in INITIAL_REQUIRED_CHANNELS:
        try:
            chat = await bot.get_chat(ch_id)
            inv = None
            if chat.username:
                inv = f"https://t.me/{chat.username}"
            else:
                try:
                    link_obj = await bot.create_chat_invite_link(ch_id)
                    inv = link_obj.invite_link
                except Exception:
                    pass
            await channels_db.add_channel(
                channel_id=ch_id,
                title=chat.title or f"Channel {ch_id}",
                username=chat.username,
                invite_link=inv,
            )
            logger.info(f"Seeded required channel: {ch_id} ({chat.title})")
        except Exception as e:
            logger.warning(f"Could not seed channel {ch_id}: {e}")

    # Set bot commands
    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start", description="Start the bot"),
        BotCommand(command="register", description="Register yourself"),
        BotCommand(command="myinfo", description="Your referral stats"),
        BotCommand(command="leaderboard", description="Top referrers"),
        BotCommand(command="addchannel", description="[Admin] Add required channel"),
        BotCommand(command="removechannel", description="[Admin] Remove channel"),
        BotCommand(command="channels", description="[Admin] List channels"),
        BotCommand(command="broadcast", description="[Admin] Broadcast message"),
        BotCommand(command="userstats", description="[Admin] User statistics"),
    ])

    logger.info("✅ Bot startup complete")


async def on_shutdown(bot: Bot):
    """Graceful shutdown."""
    logger.info("🛑 Shutting down...")
    await db_close()


async def main():
    setup_logging()

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set in environment variables!")

    # ── Bot & Dispatcher ─────────────────────────────────────────────────────
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # ── Middlewares (order matters) ──────────────────────────────────────────
    # Applied to ALL updates
    dp.update.middleware(AntiSpamMiddleware())
    dp.update.middleware(UserUpdateMiddleware())

    # ── Routers ─────────────────────────────────────────────────────────────
    # Order matters: more specific routers first
    dp.include_router(start.router)
    dp.include_router(registration.router)
    dp.include_router(admin.router)
    dp.include_router(membership.router)

    # ── Lifecycle hooks ──────────────────────────────────────────────────────
    dp.startup.register(lambda: on_startup(bot))
    dp.shutdown.register(lambda: on_shutdown(bot))

    # ── Error handler ────────────────────────────────────────────────────────
    @dp.errors()
    async def global_error_handler(event: ErrorEvent):
        logger.error(f"Unhandled error: {event.exception}", exc_info=event.exception)

    # ── Start polling ────────────────────────────────────────────────────────
    logger.info("Starting polling...")
    await dp.start_polling(
        bot,
        allowed_updates=[
            "message",
            "callback_query",
            "chat_member",
            "my_chat_member",
        ],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
