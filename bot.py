"""
Referral Reward Bot — Main Entry Point
Async aiogram 3.x bot with MongoDB backend + aiohttp web server for Koyeb
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent
from aiohttp import web

from config import BOT_TOKEN, INITIAL_REQUIRED_CHANNELS
from database.connection import connect as db_connect, close as db_close
from database import channels_db
from middlewares.middleware import AntiSpamMiddleware, UserUpdateMiddleware
from handlers import start, registration, admin, membership
from utils.logger import setup_logging

logger = logging.getLogger(__name__)

# Koyeb default port is 8000 — must match your service port setting
PORT = int(os.environ.get("PORT", "8000"))


# ── Web server ────────────────────────────────────────────────────────────────

async def start_web_server():
    """Start aiohttp health-check server BEFORE polling so Koyeb passes the TCP check."""
    app = web.Application()

    async def health(_request):
        return web.Response(text="OK", status=200)

    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"✅ Web server listening on 0.0.0.0:{PORT}")


# ── Startup / Shutdown ────────────────────────────────────────────────────────

async def on_startup(bot: Bot):
    """
    Called by aiogram after polling begins.
    NOTE: aiogram passes the Bot instance as first argument — the function
    signature MUST accept it. Using `lambda: on_startup(bot)` previously
    caused "coroutine never awaited" because aiogram called the lambda,
    got back a coroutine object, and never awaited it.
    """
    logger.info("🚀 Running startup tasks...")

    # Connect to MongoDB
    await db_connect()

    # Cache bot username so handlers never need to call get_me() during updates.
    # get_me() inside an update handler causes TelegramNetworkError on slow networks.
    me = await bot.get_me()
    import handlers.start as start_module
    start_module.BOT_USERNAME_CACHE = me.username
    logger.info(f"Bot: @{me.username}")

    # Seed initial required channels from env
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
            logger.info(f"Seeded channel: {ch_id} ({chat.title})")
        except Exception as e:
            logger.warning(f"Could not seed channel {ch_id}: {e}")

    # Set bot commands
    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start",         description="Start the bot"),
        BotCommand(command="register",      description="Register yourself"),
        BotCommand(command="myinfo",        description="Your referral stats"),
        BotCommand(command="leaderboard",   description="Top referrers"),
        BotCommand(command="addchannel",    description="[Admin] Add required channel"),
        BotCommand(command="removechannel", description="[Admin] Remove channel"),
        BotCommand(command="channels",      description="[Admin] List channels"),
        BotCommand(command="broadcast",     description="[Admin] Broadcast message"),
        BotCommand(command="userstats",     description="[Admin] User statistics"),
    ])

    logger.info("✅ Startup complete")


async def on_shutdown(bot: Bot):
    """Graceful shutdown — also receives Bot as first arg."""
    logger.info("🛑 Shutting down...")
    await db_close()


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    setup_logging()

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set in environment variables!")

    # Start web server FIRST — Koyeb TCP health check must pass within ~30s
    # of instance start or the instance is killed. Polling is started after.
    await start_web_server()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Middlewares
    dp.update.middleware(AntiSpamMiddleware())
    dp.update.middleware(UserUpdateMiddleware())

    # Routers — order matters:
    # admin BEFORE registration so Command() filters in admin.py are matched
    # before registration.py's catch-all F.text handler.
    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(registration.router)
    dp.include_router(membership.router)

    # Register lifecycle hooks by passing the coroutine FUNCTION directly.
    # aiogram will call on_startup(bot) and on_shutdown(bot) passing the Bot
    # instance automatically. Do NOT wrap in lambda — that breaks awaiting.
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    @dp.errors()
    async def global_error_handler(event: ErrorEvent):
        logger.error(f"Unhandled error: {event.exception}", exc_info=event.exception)

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
