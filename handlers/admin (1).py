"""
Admin Panel Handler
Admin-only commands: addchannel, removechannel, channels, broadcast,
userstats, leaderboard, myinfo
"""
import asyncio
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import ADMINS, BROADCAST_BATCH_SIZE, BROADCAST_DELAY
from database import users_db, channels_db
from database.fsm_db import set_state, get_state, clear_state, States
from utils.helpers import (
    get_or_create_invite_link, escape_html,
    format_leaderboard_entry, MEDAL_EMOJIS,
)

logger = logging.getLogger(__name__)
router = Router()


# ─── Admin Filter ──────────────────────────────────────────────────────────────
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


# ─── /myinfo — available to ALL registered users ──────────────────────────────
@router.message(Command("myinfo"))
async def cmd_my_info(message: Message):
    """Show the requesting user's referral stats."""
    user = message.from_user
    db_user = await users_db.get_user(user.id)

    if not db_user or not db_user.get("is_registered"):
        await message.answer(
            "❌ You are not registered yet.\nSend /register to get started!"
        )
        return

    from handlers.start import BOT_USERNAME_CACHE
    from config import BOT_USERNAME as _cfg_username
    username = BOT_USERNAME_CACHE or _cfg_username
    ref_link = f"https://t.me/{username}?start={db_user['referral_code']}"

    await message.answer(
        f"👤 <b>Your Referral Stats</b>\n\n"
        f"<b>Name:</b> {escape_html(db_user.get('full_name', 'N/A'))}\n"
        f"<b>Referral Code:</b> <code>{db_user.get('referral_code', 'N/A')}</code>\n"
        f"<b>Referral Link:</b>\n<code>{ref_link}</code>\n\n"
        f"<b>Total Invites:</b> {db_user.get('total_invites', 0)}\n"
        f"<b>Total Points:</b> {db_user.get('total_points', 0):.2f}\n"
        f"<b>UPI ID:</b> <code>{db_user.get('upi_id', 'N/A')}</code>",
        parse_mode="HTML",
    )


# ─── /leaderboard ─────────────────────────────────────────────────────────────
@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    """Show top referrers. Admins get full data (phone + UPI), others see name + points."""
    top_users = await users_db.get_leaderboard(limit=10)

    if not top_users:
        await message.answer("📭 No registered users yet.")
        return

    parts = ["🏆 <b>Leaderboard — Top Referrers</b>\n"]
    for rank, user in enumerate(top_users):
        if is_admin(message.from_user.id):
            parts.append(format_leaderboard_entry(rank, user))
        else:
            medal = MEDAL_EMOJIS[rank] if rank < len(MEDAL_EMOJIS) else f"#{rank + 1}"
            name = escape_html(user.get("full_name", "Unknown"))
            parts.append(
                f"{medal} <b>Total invites :</b> {user.get('total_invites', 0)}\n"
                f"<b>Name :</b> {name}\n"
                f"<b>Points :</b> {user.get('total_points', 0):.2f}"
            )
        parts.append("")  # blank line between entries

    await message.answer("\n".join(parts), parse_mode="HTML")


# ─── /addchannel ──────────────────────────────────────────────────────────────
@router.message(Command("addchannel"))
async def cmd_add_channel(message: Message):
    """Prompt admin for channel ID to add."""
    if not is_admin(message.from_user.id):
        return

    await set_state(message.from_user.id, States.ADMIN_ADD_CHANNEL)
    await message.answer(
        "➕ <b>Add Required Channel</b>\n\n"
        "Forward any message from the channel, or send the channel ID.\n\n"
        "Example: <code>-1001234567890</code>",
        parse_mode="HTML",
    )


# ─── /removechannel ───────────────────────────────────────────────────────────
@router.message(Command("removechannel"))
async def cmd_remove_channel(message: Message):
    """Show list of channels to remove."""
    if not is_admin(message.from_user.id):
        return

    channels = await channels_db.get_all_channels()
    if not channels:
        await message.answer("📭 No required channels configured.")
        return

    buttons = []
    for ch in channels:
        label = f"❌ {ch.get('title', str(ch['channel_id']))}"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"rmch_{ch['channel_id']}",
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Select a channel to remove:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("rmch_"))
async def callback_remove_channel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Admin only", show_alert=True)
        return

    channel_id = int(callback.data.split("_", 1)[1])
    success = await channels_db.remove_channel(channel_id)

    if success:
        await callback.message.edit_text(
            f"✅ Channel <code>{channel_id}</code> removed.",
            parse_mode="HTML",
        )
    else:
        await callback.answer("❌ Channel not found.", show_alert=True)


# ─── /channels ────────────────────────────────────────────────────────────────
@router.message(Command("channels"))
async def cmd_channels(message: Message):
    """List all required channels."""
    if not is_admin(message.from_user.id):
        return

    channels = await channels_db.get_all_channels()
    if not channels:
        await message.answer("📭 No required channels configured yet.\nUse /addchannel to add one.")
        return

    lines = ["<b>📢 Required Channels/Groups</b>\n"]
    for i, ch in enumerate(channels, 1):
        title = escape_html(ch.get("title", "Unknown"))
        cid = ch["channel_id"]
        username = ch.get("username", "")
        tag = f"@{username}" if username else f"<code>{cid}</code>"
        lines.append(f"{i}. {title} — {tag}")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── /broadcast ───────────────────────────────────────────────────────────────
@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    """Start broadcast."""
    if not is_admin(message.from_user.id):
        return

    if message.reply_to_message:
        await _do_broadcast(message, message.reply_to_message)
        return

    await set_state(message.from_user.id, States.ADMIN_BROADCAST)
    await message.answer(
        "📣 <b>Broadcast Mode</b>\n\n"
        "Reply to this message with the content you want to broadcast,\n"
        "or send your message now:",
        parse_mode="HTML",
    )


# ─── /userstats ───────────────────────────────────────────────────────────────
@router.message(Command("userstats"))
async def cmd_user_stats(message: Message):
    """Display overall bot statistics."""
    if not is_admin(message.from_user.id):
        return

    stats = await users_db.get_stats()
    ch_count = await channels_db.count_channels()

    await message.answer(
        "📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total Users: <b>{stats['total_users']}</b>\n"
        f"✅ Registered Users: <b>{stats['registered_users']}</b>\n"
        f"🟢 Active Users: <b>{stats['active_users']}</b>\n"
        f"🔗 Total Referrals: <b>{stats['total_referrals']}</b>\n"
        f"📢 Required Channels: <b>{ch_count}</b>",
        parse_mode="HTML",
    )


# ─── FSM text handlers for admin flows ────────────────────────────────────────
# These MUST come AFTER all Command() handlers so they only fire when an admin
# is already mid-conversation (has an active FSM state).

@router.message(F.forward_from_chat)
async def handle_admin_forward(message: Message):
    """Process forwarded channel message when admin is in ADMIN_ADD_CHANNEL state."""
    if not is_admin(message.from_user.id):
        return
    state = await get_state(message.from_user.id)
    if state != States.ADMIN_ADD_CHANNEL:
        return
    await _process_add_channel(message)


@router.message(F.text)
async def handle_admin_text_states(message: Message):
    """
    Handle plain text only when admin is inside an FSM flow.
    This runs AFTER all Command() handlers — Command() filters in aiogram 3
    match before F.text for messages that start with /, so /myinfo etc are safe.
    """
    if not is_admin(message.from_user.id):
        return

    state = await get_state(message.from_user.id)

    if state == States.ADMIN_ADD_CHANNEL:
        await _process_add_channel(message)
    elif state == States.ADMIN_BROADCAST:
        await clear_state(message.from_user.id)
        await _do_broadcast(message, message)


async def _process_add_channel(message: Message):
    """Shared logic: add a channel from either a forwarded message or a typed ID."""
    channel_id = None
    title = None

    if message.forward_from_chat:
        channel_id = message.forward_from_chat.id
        title = message.forward_from_chat.title or "Channel"
    elif message.text:
        text = message.text.strip()
        if text.lstrip("-").isdigit():
            channel_id = int(text)
        else:
            await message.answer(
                "❌ Please send a valid channel ID (e.g. <code>-1001234567890</code>)",
                parse_mode="HTML",
            )
            return

    if not channel_id:
        await message.answer("❌ Could not determine channel. Please try again.")
        return

    try:
        chat = await message.bot.get_chat(channel_id)
        title = chat.title or f"Channel {channel_id}"
        username = chat.username
    except Exception as e:
        await message.answer(
            f"⚠️ Could not verify channel: {e}\n"
            "Make sure the bot is an admin in the channel.",
            parse_mode="HTML",
        )
        await clear_state(message.from_user.id)
        return

    invite_link = None
    if hasattr(chat, "username") and chat.username:
        invite_link = f"https://t.me/{chat.username}"
    else:
        invite_link = await get_or_create_invite_link(message.bot, channel_id)

    success = await channels_db.add_channel(
        channel_id=channel_id,
        title=title,
        username=getattr(chat, "username", None),
        invite_link=invite_link,
    )

    await clear_state(message.from_user.id)

    if success:
        await message.answer(
            f"✅ Channel added successfully!\n\n"
            f"<b>Title:</b> {escape_html(title)}\n"
            f"<b>ID:</b> <code>{channel_id}</code>",
            parse_mode="HTML",
        )
    else:
        await message.answer("❌ Failed to add channel. Check logs.")


async def _do_broadcast(trigger_message: Message, content_message: Message):
    """Send a message to all users."""
    user_ids = await users_db.get_all_user_ids()
    total = len(user_ids)

    status_msg = await trigger_message.answer(
        f"📣 Broadcasting to <b>{total}</b> users...", parse_mode="HTML"
    )

    sent = 0
    failed = 0
    blocked = 0

    for i, uid in enumerate(user_ids):
        try:
            await content_message.copy_to(uid)
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
        except TelegramBadRequest:
            failed += 1
        except Exception as e:
            failed += 1
            logger.error(f"Broadcast error for {uid}: {e}")

        if (i + 1) % BROADCAST_BATCH_SIZE == 0:
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(BROADCAST_DELAY)

    await status_msg.edit_text(
        f"✅ <b>Broadcast Complete</b>\n\n"
        f"Total: {total}\n"
        f"✅ Sent: {sent}\n"
        f"🚫 Blocked: {blocked}\n"
        f"❌ Failed: {failed}",
        parse_mode="HTML",
    )
    logger.info(f"Broadcast done: {sent}/{total} sent, {blocked} blocked, {failed} failed")
