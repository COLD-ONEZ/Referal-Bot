"""
Start Handler
Handles /start command with deep-link referral support and force-sub verification.
"""
import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from database import users_db, channels_db
from database.fsm_db import set_state, get_state, get_state_data, clear_state, States
from utils.helpers import (
    check_user_in_channel,
    get_channels_user_not_in,
    get_or_create_invite_link,
    is_valid_referral_code,
    escape_html,
)

logger = logging.getLogger(__name__)
router = Router()


async def _build_join_keyboard(bot, channels: list) -> InlineKeyboardMarkup:
    """Build inline keyboard with JOIN buttons for each unjoined channel + CHECK button."""
    buttons = []
    for ch in channels:
        title = ch.get("title", "Channel")
        invite_link = ch.get("invite_link")
        if not invite_link:
            invite_link = await get_or_create_invite_link(bot, ch["channel_id"])
            # Refresh invite link in DB so it's available next time
            if invite_link:
                await channels_db.update_invite_link(ch["channel_id"], invite_link)
        if invite_link:
            buttons.append([InlineKeyboardButton(text=f"📢 Join {title}", url=invite_link)])
    buttons.append([InlineKeyboardButton(text="✅ I've Joined — Check Now", callback_data="check_join")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _handle_after_join_verified(message_or_callback, user, referral_code_from_link: str = None):
    """
    Called after confirming user has joined all channels.
    Shows YES/NO referral code buttons OR skips directly if referral link was used.
    """
    name = escape_html(user.full_name)
    db_user = await users_db.get_user(user.id)

    if db_user and db_user.get("is_registered"):
        bot_info = await message_or_callback.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={db_user['referral_code']}"
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

    if referral_code_from_link:
        text = (
            f"Hey <b>{name}</b>\n\n"
            f"Thanks For Joining Our Group And Channel.\n\n"
            f"Send /register to register yourself."
        )
        if isinstance(message_or_callback, Message):
            await message_or_callback.answer(text, parse_mode="HTML")
        else:
            await message_or_callback.message.answer(text, parse_mode="HTML")
    else:
        text = (
            f"Hey <b>{name}</b>\n"
            f"Thanks For Joining Our Group And Channel.\n\n"
            f"Do you have invite code or not?"
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
    Entry point. Handles:
    - /start                    → plain start
    - /start REFERRALCODE       → deep link with referral
    """
    user = message.from_user
    referral_code = None

    if command.args:
        arg = command.args.strip()
        if is_valid_referral_code(arg):
            referral_code = arg.lower()

    await users_db.create_user(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
    )

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

    # Always persist the referral code in FSM so check_join can retrieve it
    if referral_code:
        await set_state(user.id, "started_with_link", data={"link_code": referral_code})
    else:
        # Clear any stale state from a previous /start
        existing_state = await get_state(user.id)
        if existing_state == "started_with_link":
            await clear_state(user.id)

    channels = await channels_db.get_all_channels()

    if not channels:
        await _handle_after_join_verified(message, user, referral_code)
        return

    not_joined = await get_channels_user_not_in(message.bot, user.id, channels)

    if not_joined:
        name = escape_html(user.full_name) or user.first_name
        text = (
            f"Hey {name}\n"
            f"You are not joined our Group and Channel.\n"
            f"Please join and click the check button below 😊"
        )
        keyboard = await _build_join_keyboard(message.bot, not_joined)
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await _handle_after_join_verified(message, user, referral_code)


@router.callback_query(F.data == "check_join")
async def callback_check_join(callback: CallbackQuery):
    """User pressed CHECK JOIN — re-verify membership."""
    await callback.answer()  # Dismiss loading indicator immediately

    user = callback.from_user
    channels = await channels_db.get_all_channels()

    if not channels:
        # No channels configured — let them through
        await callback.message.delete()
        state = await get_state(user.id)
        link_code = None
        if state == "started_with_link":
            data = await get_state_data(user.id)
            link_code = data.get("link_code")
            await clear_state(user.id)
        await _handle_after_join_verified(callback, user, link_code)
        return

    not_joined = await get_channels_user_not_in(callback.bot, user.id, channels)

    if not_joined:
        # Still hasn't joined — update the keyboard with fresh invite links
        names = ", ".join(ch.get("title", str(ch["channel_id"])) for ch in not_joined)
        try:
            keyboard = await _build_join_keyboard(callback.bot, not_joined)
            await callback.message.edit_reply_markup(reply_markup=keyboard)
        except Exception:
            pass  # If edit fails, leave the old keyboard
        # Show alert to user
        await callback.message.answer(
            f"❌ You haven't joined: <b>{escape_html(names)}</b>\n\n"
            f"Please join and click the check button again.",
            parse_mode="HTML",
        )
        return

    # All joined!
    try:
        await callback.message.delete()
    except Exception:
        pass

    state = await get_state(user.id)
    link_code = None
    if state == "started_with_link":
        data = await get_state_data(user.id)
        link_code = data.get("link_code")
        await clear_state(user.id)

    await _handle_after_join_verified(callback, user, link_code)


@router.callback_query(F.data == "has_code")
async def callback_has_code(callback: CallbackQuery):
    """User has a referral code → ask for it."""
    await set_state(callback.from_user.id, States.WAITING_REFERRAL_CODE)
    await callback.message.edit_text(
        "📨 Send your referral code:",
        reply_markup=None,
    )
    await callback.answer()


@router.callback_query(F.data == "no_code")
async def callback_no_code(callback: CallbackQuery):
    """User has no referral code → proceed to register."""
    await clear_state(callback.from_user.id)
    await callback.message.edit_text(
        "✅ No problem!\n\nSend /register to register yourself.",
        reply_markup=None,
    )
    await callback.answer()
