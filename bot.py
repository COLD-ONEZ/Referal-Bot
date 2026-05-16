"""
Referral Reward Bot — Main Entry Point
Async aiogram 3.x bot with MongoDB backend + aiohttp web server for Koyeb

Runs in WEBHOOK mode by default (set WEBHOOK_URL env var).
Falls back to long-polling when WEBHOOK_URL is not set (local dev only).

Why webhooks on Koyeb?
  Long-polling holds a 30-second outbound TCP connection to api.telegram.org
  open on every cycle.  Koyeb's egress to Telegram is unreliable — those
  connections time out repeatedly.  With webhooks Telegram connects IN to
  this service; the bot only needs short outbound calls (send_message etc.)
  which are far less likely to time out.
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent
from aiogram.exceptions import TelegramNetworkError
from aiohttp import web, ClientTimeout

from config import BOT_TOKEN, INITIAL_REQUIRED_CHANNELS
from database.connection import connect as db_connect, close as db_close
from database import channels_db
from middlewares.middleware import AntiSpamMiddleware, UserUpdateMiddleware
from handlers import start, registration, admin, membership
from utils.logger import setup_logging

logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", "8000"))
# Full public URL of this Koyeb service, e.g.
#   https://sophisticated-barbara-cold-onez-1ed5e63e.koyeb.app
# Set this as an environment variable in your Koyeb service settings.
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").rstrip("/")
WEBHOOK_PATH = "/webhook"


# ── Retry helper ─────────────────────────────────────────────────────────────

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
    logger.info("🚀 Running startup tasks...")

    await db_connect()

    me = await _retry_telegram_call(lambda: bot.get_me())
    import handlers.start as start_module
    start_module.BOT_USERNAME_CACHE = me.username
    logger.info(f"Bot: @{me.username}")

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
    logger.info("🛑 Shutting down...")
    await db_close()


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    setup_logging()

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set in environment variables!")

    timeout = ClientTimeout(total=60, connect=20, sock_connect=20, sock_read=30)
    from aiogram.client.session.aiohttp import AiohttpSession
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

    @dp.errors()
    async def global_error_handler(event: ErrorEvent):
        logger.error(f"Unhandled error: {event.exception}", exc_info=event.exception)

    # ── Choose mode ───────────────────────────────────────────────────────────
    if WEBHOOK_URL:
        await _run_webhook(bot, dp)
    else:
        logger.warning(
            "WEBHOOK_URL is not set — falling back to long-polling. "
            "This is unreliable on Koyeb; set WEBHOOK_URL for production."
        )
        await _run_polling(bot, dp)


async def _run_webhook(bot: Bot, dp: Dispatcher):
    """
    Webhook mode — recommended for Koyeb.

    Telegram POSTs each update to /webhook; the aiohttp server handles it.
    No persistent outbound connection to api.telegram.org is needed for
    receiving updates.
    """
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
    logger.info(f"Starting in WEBHOOK mode: {webhook_url}")

    # Build the aiohttp application
    app = web.Application()

    async def health(_request):
        return web.Response(text="OK", status=200)

    app.router.add_get("/", health)

    # Register aiogram webhook handler at /webhook
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    # setup_application wires dp.startup / dp.shutdown into aiohttp's lifecycle
    setup_application(app, dp, bot=bot)

    # Start the web server (health check + webhook endpoint)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"✅ Web server listening on 0.0.0.0:{PORT}")

    # Tell Telegram where to send updates (with retry)
    await _retry_telegram_call(lambda: bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
    ))
    logger.info(f"✅ Webhook set: {webhook_url}")

    # Block forever (aiohttp handles incoming updates in the background)
    try:
        await asyncio.Event().wait()
    finally:
        await bot.delete_webhook()
        await bot.session.close()


async def _run_polling(bot: Bot, dp: Dispatcher):
    """
    Long-polling fallback — for local development only.
    Not recommended on Koyeb due to unreliable Telegram connectivity.
    """
    # Still start the health-check web server so Koyeb doesn't kill the instance
    app = web.Application()

    async def health(_request):
        return web.Response(text="OK", status=200)

    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"✅ Web server listening on 0.0.0.0:{PORT}")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Starting polling...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
            drop_pending_updates=True,
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
