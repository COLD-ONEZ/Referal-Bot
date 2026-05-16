"""
Start Handler
Handles /start command with deep-link referral support and force-sub verification.
"""
import asyncio
import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramNetworkError

from database import users_db, channels_db
from database.fsm_db import set_state, get_state, get_state_data, clear_state, States
from utils.helpers import (
    get_channels_user_not_in,
    get_or_create_invite_link,
    is_valid_referral_code,
    escape_html,
)

logger = logging.getLogger(__name__)
router = Router()

# Populated by bot.py on_startup — avoids get_me() API call inside every update handler
BOT_USERNAME_CACHE: str = ""


def _bot_username() -> str:
    """Return cached username, falling back to config."""
    if BOT_USERNAME_CACHE:
        return BOT_USERNAME_CACHE
    try:
        from config import BOT_USERNAME
        return BOT_USERNAME
    except Exception:
        return "bot"


async def _safe_answer(callback: CallbackQuery, **kwargs):
    """Answer a callback query, ignoring network timeouts (non-critical)."""
    try:
        await callback.answer(**kwargs)
    except (TelegramNetworkError, Exception):
        pass  # Spinner timeout is cosmetic — don't crash the handler


async def _build_join_keyboard(bot, channels: list) -> InlineKeyboardMarkup:
    """Build inline keyboard with JOIN buttons + CHECK button."""
    buttons = []
    for ch in channels:
        title = ch.get("title", "Channel")
        invite_link = ch.get("invite_link")
        if not invite_link:
            invite_link = await get_or_create_invite_link(bot, ch["channel_id"])
            if invite_link:
                await channels_db.update_invite_link(ch["channel_id"], invite_link)
        if invite_link:
            buttons.append([InlineKeyboardButton(text=f"📢 Join {title}", url=invite_link)])
    buttons.append([InlineKeyboardButton(text="✅ I've Joined — Check Now", callback_data="check_join")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _handle_after_join_verified(message_or_callback, user, came_via_referral_link: bool = False):
    """
    Called after confirming user has joined all required channels.

    came_via_referral_link=True  → skip YES/NO buttons, go straight to /register prompt
    came_via_referral_link=False → show YES I HAVE / I DON'T HAVE buttons

    Does NOT take the referral code itself — that was already saved to DB in cmd_start.
    """
    name = escape_html(user.full_name)
    db_user = await users_db.get_user(user.id)
    username = _bot_username()

    # Already registered — show their referral link
    if db_user and db_user.get("is_registered"):
        ref_link = f"https://t.me/{username}?start={db_user['referral_code']}"
        text = (
            f"✅ <b>Welcome back, {name}!</b>\n\n"
            f"You are already registered.\n"
            f"Your referral link:\n"
            f"<code>{ref_link}</code>"
        )
        if isinstance(message_or_callback, Message):
            await message_or_callback.answer(text, parse_mode="HTML")
        else:
            await message_or_callback.message.answer(text, parse_mode="HTML")
        return

    # Came via referral link → skip code prompt, go straight to /register
    if came_via_referral_link:
        text = (
            f"Hey <b>{name}</b>\n\n"
            f"Thanks For Joining Our Group And Channel.\n\n"
            f"Send /register to register yourself."
        )
        if isinstance(message_or_callback, Message):
            await message_or_callback.answer(text, parse_mode="HTML")
        else:
            await message_or_callback.message.answer(text, parse_mode="HTML")
        return

    # No referral link → ask YES/NO
    text = (
        f"Hey <b>{name}</b>\n"
        f"Thanks For Joining Our Group And Channel.\n\n"
        f"Do you have an invite code?"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ YES I HAVE", callback_data="has_code"),
            InlineKeyboardButton(text="❌ I DON'T HAVE", callback_data="no_code"),
        ]
    ])
    if isinstance(message_or_callback, Message):
        await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message_or_callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    """
    /start — with or without referral deep-link arg.
    Referral code is saved to DB immediately here so it survives
    across the force-sub join flow.
    """
    user = message.from_user
    referral_code = None

    if command.args:
        arg = command.args.strip()
        if is_valid_referral_code(arg):
            referral_code = arg.lower()

    # Upsert user (middleware does this too, but be safe)
    await users_db.create_user(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
    )

    # Save referral immediately — before join check — so it's never lost
    if referral_code:
        referrer = await users_db.get_user_by_referral_code(referral_code)
        if referrer and referrer["user_id"] != user.id:
            db_user = await users_db.get_user(user.id)
            if db_user and not db_user.get("referred_by"):
                await users_db.set_referred_by(
                    user_id=user.id,
                    referrer_id=referrer["user_id"],
                    code=referral_code,
                )

    # Store whether user came via referral link in FSM.
    # We only need a boolean flag — the code is already saved in DB above.
    if referral_code:
        await set_state(user.id, "started_with_link", data={"via_link": True})
    else:
        # Clear stale referral-link state if user restarts without the link
        existing_state = await get_state(user.id)
        if existing_state == "started_with_link":
            await clear_state(user.id)

    channels = await channels_db.get_all_channels()

    if not channels:
        await _handle_after_join_verified(message, user, came_via_referral_link=bool(referral_code))
        return

    not_joined = await get_channels_user_not_in(message.bot, user.id, channels)

    if not_joined:
        name = escape_html(user.full_name) or user.first_name
        text = (
            f"Hey {name}\n"
            f"You have not joined our Group and Channel yet.\n"
            f"Please join and click the check button below 😊"
        )
        keyboard = await _build_join_keyboard(message.bot, not_joined)
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await _handle_after_join_verified(message, user, came_via_referral_link=bool(referral_code))


@router.callback_query(F.data == "check_join")
async def callback_check_join(callback: CallbackQuery):
    """User pressed CHECK JOIN — re-verify membership."""
    # Answer immediately (cosmetic — suppress spinner).
    # Use _safe_answer so a network timeout here doesn't abort the whole handler.
    await _safe_answer(callback)

    user = callback.from_user
    channels = await channels_db.get_all_channels()

    # Read FSM flag BEFORE any state-clearing below
    state = await get_state(user.id)
    came_via_link = False
    if state == "started_with_link":
        data = await get_state_data(user.id)
        came_via_link = data.get("via_link", False)

    if not channels:
        try:
            await callback.message.delete()
        except Exception:
            pass
        if state == "started_with_link":
            await clear_state(user.id)
        await _handle_after_join_verified(callback, user, came_via_referral_link=came_via_link)
        return

    not_joined = await get_channels_user_not_in(callback.bot, user.id, channels)

    if not_joined:
        names = ", ".join(ch.get("title", str(ch["channel_id"])) for ch in not_joined)
        try:
            keyboard = await _build_join_keyboard(callback.bot, not_joined)
            await callback.message.edit_reply_markup(reply_markup=keyboard)
        except Exception:
            pass
        try:
            await callback.message.answer(
                f"❌ You haven't joined: <b>{escape_html(names)}</b>\n\n"
                f"Please join and click the check button again.",
                parse_mode="HTML",
            )
        except TelegramNetworkError:
            pass
        return

    # All joined — clear state and proceed
    if state == "started_with_link":
        await clear_state(user.id)

    try:
        await callback.message.delete()
    except Exception:
        pass

    await _handle_after_join_verified(callback, user, came_via_referral_link=came_via_link)


@router.callback_query(F.data == "has_code")
async def callback_has_code(callback: CallbackQuery):
    """User has a referral code → ask for it."""
    await set_state(callback.from_user.id, States.WAITING_REFERRAL_CODE)
    try:
        await callback.message.edit_text("📨 Send your referral code:", reply_markup=None)
    except Exception:
        pass
    await _safe_answer(callback)


@router.callback_query(F.data == "no_code")
async def callback_no_code(callback: CallbackQuery):
    """User has no referral code → proceed to register."""
    await clear_state(callback.from_user.id)
    try:
        await callback.message.edit_text(
            "✅ No problem!\n\nSend /register to register yourself.",
            reply_markup=None,
        )
    except Exception:
        pass
    await _safe_answer(callback)
