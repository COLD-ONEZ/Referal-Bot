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
from aiogram.exceptions import TelegramNetworkError
from aiohttp import web

from config import BOT_TOKEN, INITIAL_REQUIRED_CHANNELS
from database.connection import connect as db_connect, close as db_close
from database import channels_db
from middlewares.middleware import AntiSpamMiddleware, UserUpdateMiddleware
from handlers import start, registration, admin, membership
from utils.logger import setup_logging

logger = logging.getLogger(__name__)

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


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _retry_telegram_call(coro_fn, max_retries: int = 7, base_delay: float = 5.0):
    """
    Retry a Telegram API call with exponential back-off.
    coro_fn must be a zero-arg callable that returns a fresh coroutine each time.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return await coro_fn()
        except (TelegramNetworkError, asyncio.TimeoutError, OSError) as exc:
            if attempt == max_retries:
                logger.error(f"All {max_retries} attempts failed: {exc}")
                raise
            wait = base_delay * (2 ** (attempt - 1))   # 5, 10, 20, 40 …
            logger.warning(
                f"Telegram API call failed (attempt {attempt}/{max_retries}): {exc}. "
                f"Retrying in {wait:.0f}s…"
            )
            await asyncio.sleep(wait)


# ── Startup / Shutdown ────────────────────────────────────────────────────────

async def on_startup(bot: Bot):
    """
    Called by aiogram after polling begins.
    All Telegram API calls use _retry_telegram_call so a flaky network on
    startup no longer crashes the whole process.
    """
    logger.info("🚀 Running startup tasks...")

    # Connect to MongoDB
    await db_connect()

    # Cache bot username with retry — a single timeout no longer kills startup
    me = await _retry_telegram_call(lambda: bot.get_me())
    import handlers.start as start_module
    start_module.BOT_USERNAME_CACHE = me.username
    logger.info(f"Bot: @{me.username}")

    # Seed initial required channels from env
    for ch_id in INITIAL_REQUIRED_CHANNELS:
        try:
            chat = await _retry_telegram_call(lambda cid=ch_id: bot.get_chat(cid))
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

    # Set bot commands (non-fatal if this fails)
    from aiogram.types import BotCommand
    try:
        await _retry_telegram_call(lambda: bot.set_my_commands([
            BotCommand(command="start",         description="Start the bot"),
            BotCommand(command="register",      description="Register yourself"),
            BotCommand(command="myinfo",        description="Your referral stats"),
            BotCommand(command="leaderboard",   description="Top referrers"),
            BotCommand(command="addchannel",    description="[Admin] Add required channel"),
            BotCommand(command="removechannel", description="[Admin] Remove channel"),
            BotCommand(command="channels",      description="[Admin] List channels"),
            BotCommand(command="broadcast",     description="[Admin] Broadcast message"),
            BotCommand(command="userstats",     description="[Admin] User statistics"),
        ]))
    except Exception as e:
        logger.warning(f"Could not set bot commands (non-fatal): {e}")

    logger.info("✅ Startup complete")


async def on_shutdown(bot: Bot):
    """Graceful shutdown."""
    logger.info("🛑 Shutting down...")
    await db_close()


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    setup_logging()

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set in environment variables!")

    # Start web server FIRST — Koyeb TCP health check must pass within ~30s
    await start_web_server()

    # AiohttpSession in older aiogram 3.x only accepts 'timeout' — do NOT pass
    # 'connector' here; it gets forwarded to BaseSession which rejects unknown args.
    # We set generous timeouts to survive Koyeb → Telegram latency spikes.
    from aiohttp import ClientTimeout
    from aiogram.client.session.aiohttp import AiohttpSession

    timeout = ClientTimeout(
        total=120,      # max total time per request
        connect=30,     # TCP connection timeout
        sock_connect=30,
        sock_read=60,
    )
    session = AiohttpSession(timeout=timeout)

    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.update.middleware(AntiSpamMiddleware())
    dp.update.middleware(UserUpdateMiddleware())

    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(registration.router)
    dp.include_router(membership.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    @dp.errors()
    async def global_error_handler(event: ErrorEvent):
        logger.error(f"Unhandled error: {event.exception}", exc_info=event.exception)

    logger.info("Starting polling...")
    try:
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
    finally:
        # Always close the session cleanly — prevents "Unclosed client session" warnings
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
