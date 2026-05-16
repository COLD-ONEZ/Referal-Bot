"""
Registration Handler
Multi-step /register flow: phone → UPI → complete
Anti-fake: validates Indian phone, prevents duplicate registrations.
"""
import re
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from database import users_db
from database.fsm_db import (
    set_state, get_state, get_state_data, clear_state, States,
)
from utils.helpers import (
    is_valid_indian_phone, is_valid_upi, clean_phone,
    phone_to_referral_code, generate_referral_link, escape_html,
)

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("register"))
async def cmd_register(message: Message):
    """Start the registration flow."""
    user = message.from_user
    db_user = await users_db.get_user(user.id)

    if db_user and db_user.get("is_registered"):
        ref_link = generate_referral_link(db_user["referral_code"])
        await message.answer(
            f"✅ <b>You are already registered!</b>\n\n"
            f"Your referral link:\n<code>{ref_link}</code>",
            parse_mode="HTML",
        )
        return

    # Clear any pre-existing FSM state (e.g. started_with_link, WAITING_REFERRAL_CODE)
    # before starting registration so the phone-input step is never blocked.
    await clear_state(user.id)

    # Start phone collection step
    await set_state(user.id, States.WAITING_PHONE)
    await message.answer(
        "📱 <b>Send Your 10 digit phone number</b>\n"
        "<i>(This is used to avoid Fake Members)</i>",
        parse_mode="HTML",
    )


# FIX: Added ~F.text.startswith("/") to exclude command messages.
# Without this, messages like /register sent while in WAITING_REFERRAL_CODE
# or WAITING_PHONE state were caught here first (F.text matches ALL text
# including commands), processed as phone/code input, silently failed
# validation, and the actual Command handler never fired — making the bot
# appear completely unresponsive to /register.
@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_input(message: Message):
    """
    Route text messages to the correct FSM step.
    ONLY fires when user is in an active registration/referral FSM state
    AND the message is not a command (does not start with /).
    """
    user = message.from_user
    state = await get_state(user.id)

    # Only handle states this router owns — ignore everything else silently
    if state == States.WAITING_REFERRAL_CODE:
        await _process_referral_code(message)
    elif state == States.WAITING_PHONE:
        await _process_phone(message)
    elif state == States.WAITING_UPI:
        await _process_upi(message)
    # All other states (admin flows, started_with_link, None) → do nothing


async def _process_referral_code(message: Message):
    """Validate and save the referral code entered by user."""
    user = message.from_user
    code = message.text.strip().lower()

    if not re.fullmatch(r"[a-j]{10}", code):
        await message.answer(
            "❌ Invalid referral code format.\n"
            "Please send a valid 10-character referral code.\n\n"
            "Example: <code>hdagahgccd</code>",
            parse_mode="HTML",
        )
        return

    referrer = await users_db.get_user_by_referral_code(code)
    if not referrer:
        await message.answer("❌ Referral code not found. Please check and try again.")
        return

    if referrer["user_id"] == user.id:
        await message.answer("❌ You cannot use your own referral code!")
        return

    if not referrer.get("is_registered"):
        await message.answer("❌ This referral code belongs to an unregistered user.")
        return

    db_user = await users_db.get_user(user.id)
    if db_user and not db_user.get("referred_by"):
        await users_db.set_referred_by(
            user_id=user.id,
            referrer_id=referrer["user_id"],
            code=code,
        )

    await clear_state(user.id)
    await message.answer(
        "✅ Referral code saved! Now send /register to complete your registration.",
        parse_mode="HTML",
    )


async def _process_phone(message: Message):
    """Validate and save phone number (Step 1 of registration)."""
    user = message.from_user
    raw_phone = message.text.strip()

    phone = clean_phone(raw_phone)

    if not is_valid_indian_phone(phone):
        await message.answer(
            "❌ Invalid phone number.\n\n"
            "Please send a valid <b>10-digit Indian mobile number</b>\n"
            "(Starting with 6, 7, 8, or 9)\n\n"
            "Example: <code>9876543210</code>",
            parse_mode="HTML",
        )
        return

    # Check if this phone is already registered to another account
    existing = await users_db.get_user_by_phone(phone)
    if existing and existing["user_id"] != user.id:
        await users_db.add_fraud_flag(
            user.id,
            f"Tried to register with phone already used by {existing['user_id']}"
        )
        await message.answer(
            "❌ This phone number is already registered with another account.\n"
            "<b>One phone number = one account only.</b>",
            parse_mode="HTML",
        )
        return

    # Prevent same user from changing phone after partial registration
    db_user = await users_db.get_user(user.id)
    if db_user and db_user.get("phone_number") and db_user["phone_number"] != phone:
        await message.answer(
            "❌ You already have a phone registered. Re-registration is not allowed."
        )
        return

    # Advance to UPI step — store phone in state data
    await set_state(user.id, States.WAITING_UPI, data={"phone": phone})

    await message.answer(
        "💳 <b>Now Send Your Gpay Number or UPI ID</b>\n"
        "<i>(This is used to give rewards those who invite the most people.)</i>\n\n"
        "Example: <code>name@upi</code> or <code>9876543210@paytm</code>",
        parse_mode="HTML",
    )


async def _process_upi(message: Message):
    """Validate and save UPI ID, then complete registration (Step 2)."""
    user = message.from_user
    upi_id = message.text.strip()

    if not is_valid_upi(upi_id):
        await message.answer(
            "❌ Invalid UPI ID format.\n\n"
            "Please enter a valid UPI ID.\n"
            "Examples:\n"
            "• <code>name@upi</code>\n"
            "• <code>9876543210@paytm</code>\n"
            "• <code>user@okicici</code>",
            parse_mode="HTML",
        )
        return

    state_data = await get_state_data(user.id)
    phone = state_data.get("phone")

    if not phone:
        await clear_state(user.id)
        await message.answer(
            "⚠️ Session expired. Please send /register to start again."
        )
        return

    referral_code = phone_to_referral_code(phone)

    # Handle referral code collision while keeping code in [a-j] alphabet
    existing_code_user = await users_db.get_user_by_referral_code(referral_code)
    if existing_code_user and existing_code_user["user_id"] != user.id:
        _digit_map = {
            "0": "a", "1": "b", "2": "c", "3": "d", "4": "e",
            "5": "f", "6": "g", "7": "h", "8": "i", "9": "j",
        }
        suffix = "".join(_digit_map[d] for d in str(user.id)[-2:])
        referral_code = referral_code[:8] + suffix

    success = await users_db.complete_registration(
        user_id=user.id,
        phone_number=phone,
        upi_id=upi_id,
        referral_code=referral_code,
    )

    if not success:
        await message.answer("⚠️ Registration failed. Please try again with /register.")
        return

    await clear_state(user.id)

    from handlers.start import BOT_USERNAME_CACHE
    from config import BOT_USERNAME as _cfg_username
    username = BOT_USERNAME_CACHE or _cfg_username
    ref_link = f"https://t.me/{username}?start={referral_code}"

    await message.answer(
        "🎉 <b>Registration is Complete</b>\n\n"
        "This is your referral link:\n"
        f"<code>{ref_link}</code>\n\n"
        "Share this link with your friends to earn points! 🚀",
        parse_mode="HTML",
    )

    logger.info(
        f"User {user.id} (@{user.username}) registered | "
        f"Phone: {phone[:4]}***{phone[-2:]} | Code: {referral_code}"
    )
