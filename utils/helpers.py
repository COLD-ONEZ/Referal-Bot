"""
Utility Functions
Referral code generation, validation helpers, and channel membership checks
"""
import re
import logging
import asyncio
from typing import Optional, Tuple, List

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import PHONE_REGEX, UPI_REGEX, BOT_USERNAME

logger = logging.getLogger(__name__)

# Digit → letter mapping for phone-based referral codes
_DIGIT_MAP = {
    "0": "a", "1": "b", "2": "c", "3": "d", "4": "e",
    "5": "f", "6": "g", "7": "h", "8": "i", "9": "j",
}


def phone_to_referral_code(phone: str) -> str:
    """
    Convert a 10-digit phone number to a referral code using
    0=a, 1=b, ... 9=j mapping.
    E.g. '9876543210' → 'jihgfedcba'
    """
    return "".join(_DIGIT_MAP.get(ch, ch) for ch in phone)


def generate_referral_link(code: str) -> str:
    """Build the full Telegram deep-link for a referral code."""
    return f"https://t.me/{BOT_USERNAME}?start={code}"


# ─── Validation ───────────────────────────────────────────────────────────────

def is_valid_indian_phone(phone: str) -> bool:
    """Validate a 10-digit Indian mobile number (starts with 6-9)."""
    cleaned = phone.strip().replace(" ", "").replace("-", "")
    # Strip country code if present
    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    return bool(re.fullmatch(PHONE_REGEX, cleaned)) and cleaned == phone.strip()


def clean_phone(phone: str) -> str:
    """Return clean 10-digit phone number."""
    cleaned = phone.strip().replace(" ", "").replace("-", "")
    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    return cleaned


def is_valid_upi(upi_id: str) -> bool:
    """Validate a UPI ID format (handle@provider)."""
    return bool(re.fullmatch(UPI_REGEX, upi_id.strip()))


def is_valid_referral_code(code: str) -> bool:
    """Referral codes are 10 lowercase alpha characters."""
    return bool(re.fullmatch(r"[a-j]{10}", code.strip().lower()))


# ─── Telegram Channel Membership ─────────────────────────────────────────────

async def check_user_in_channel(bot: Bot, user_id: int, channel_id: int) -> bool:
    """
    Return True if the user is an active member of channel_id.
    Handles all edge cases gracefully.
    """
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramForbiddenError:
        logger.warning(f"Bot has no access to channel {channel_id}")
        return False
    except TelegramBadRequest as e:
        if "user not found" in str(e).lower() or "chat not found" in str(e).lower():
            return False
        logger.error(f"BadRequest checking channel {channel_id} for user {user_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error checking channel {channel_id} for user {user_id}: {e}")
        return False


async def get_channels_user_not_in(
    bot: Bot,
    user_id: int,
    channels: List[dict],
) -> List[dict]:
    """
    Given a list of channel dicts (with 'channel_id', 'title', 'invite_link'),
    return only those the user is NOT a member of.
    """
    not_joined = []
    tasks = [check_user_in_channel(bot, user_id, ch["channel_id"]) for ch in channels]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for ch, result in zip(channels, results):
        if isinstance(result, Exception) or not result:
            not_joined.append(ch)
    return not_joined


async def get_or_create_invite_link(bot: Bot, channel_id: int) -> Optional[str]:
    """
    Try to create an invite link for a channel.
    Falls back to username link if creation fails.
    """
    try:
        link_obj = await bot.create_chat_invite_link(chat_id=channel_id)
        return link_obj.invite_link
    except TelegramForbiddenError:
        logger.warning(f"No permission to create invite link for {channel_id}")
    except Exception as e:
        logger.error(f"Error creating invite link for {channel_id}: {e}")
    return None


# ─── Formatting Helpers ────────────────────────────────────────────────────────

def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def format_points(points: float) -> str:
    """Format points to max 2 decimal places, dropping trailing zeros."""
    return f"{points:.2f}".rstrip("0").rstrip(".")


MEDAL_EMOJIS = ["🥇", "🥈", "🥉"]


def format_leaderboard_entry(rank: int, user: dict) -> str:
    """Format a single leaderboard entry."""
    medal = MEDAL_EMOJIS[rank] if rank < len(MEDAL_EMOJIS) else f"#{rank + 1}"
    name = escape_html(user.get("full_name", "Unknown"))
    uid = user.get("user_id", "N/A")
    invites = user.get("total_invites", 0)
    points = format_points(user.get("total_points", 0))
    phone = user.get("phone_number", "N/A")
    upi = user.get("upi_id", "N/A")

    return (
        f"{medal} <b>Total invites :</b> {invites}\n"
        f"<b>Name :</b> {name}\n"
        f"<b>Id :</b> <code>{uid}</code>\n"
        f"<b>Point :</b> {points}\n"
        f"<b>Ph No :</b> <code>{phone}</code>\n"
        f"<b>Payment :</b> <code>{upi}</code>"
    )
