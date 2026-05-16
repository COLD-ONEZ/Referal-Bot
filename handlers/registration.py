"""
Registration Handler
Multi-step /register flow: phone → UPI → complete
Anti-fake: validates Indian phone, prevents duplicate registrations.
"""
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from database import users_db
from database.fsm_db import (
    set_state, get_state, get_state_data, update_state_data,
    clear_state, States,
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

    # Start phone collection step
    await set_state(user.id, States.WAITING_PHONE)
    await message.answer(
        "📱 <b>Send Your 10 digit phone number</b>\n"
        "<i>(This is used to avoid Fake Members)</i>",
        parse_mode="HTML",
    )


@router.message(F.text)
async def handle_text_input(message: Message):
    """
    Route text messages to the correct FSM step.
    This catches messages when user is in a conversation state.
    """
    user = message.from_user
    state = await get_state(user.id)

    if state == States.WAITING_REFERRAL_CODE:
        await _process_referral_code(message)
    elif state == States.WAITING_PHONE:
        await _process_phone(message)
    elif state == States.WAITING_UPI:
        await _process_upi(message)
    # Other states are handled by their own handlers (admin flows)


async def _process_referral_code(message: Message):
    """Validate and save the referral code entered by user."""
    user = message.from_user
    code = message.text.strip().lower()

    # Validate format
    import re
    if not re.fullmatch(r"[a-j]{10}", code):
        await message.answer(
            "❌ Invalid referral code format.\n"
            "Please send a valid 10-character referral code.\n\n"
            "Example: <code>hdagahgccd</code>",
            parse_mode="HTML",
        )
        return

    # Look up referrer
    referrer = await users_db.get_user_by_referral_code(code)
    if not referrer:
        await message.answer("❌ Referral code not found. Please check and try again.")
        return

    # Anti-self-referral
    if referrer["user_id"] == user.id:
        await message.answer("❌ You cannot use your own referral code!")
        return

    # Check referrer is registered
    if not referrer.get("is_registered"):
        await message.answer("❌ This referral code belongs to an unregistered user.")
        return

    # Save referral
    db_user = await users_db.get_user(user.id)
    if db_user and not db_user.get("referred_by"):
        await users_db.set_referred_by(
            user_id=user.id,
            referrer_id=referrer["user_id"],
            code=code,
        )

    await clear_state(user.id)
    await message.answer(
        "✅ Done. Now send /register to register yourself.",
        parse_mode="HTML",
    )


async def _process_phone(message: Message):
    """Validate and save phone number (Step 1 of registration)."""
    user = message.from_user
    raw_phone = message.text.strip()

    # Clean
    phone = clean_phone(raw_phone)

    # Validate format
    if not is_valid_indian_phone(phone):
        await message.answer(
            "❌ Invalid phone number.\n\n"
            "Please send a valid <b>10-digit Indian mobile number</b>\n"
            "(Starting with 6, 7, 8, or 9)\n\n"
            "Example: <code>9876543210</code>",
            parse_mode="HTML",
        )
        return

    # Check for duplicate phone number (one account per phone)
    existing = await users_db.get_user_by_phone(phone)
    if existing and existing["user_id"] != user.id:
        # Another account already uses this phone
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

    # Check if THIS user already used a phone (already registered → handled at /register)
    db_user = await users_db.get_user(user.id)
    if db_user and db_user.get("phone_number") and db_user["phone_number"] != phone:
        await message.answer("❌ You already have a phone registered. Re-registration is not allowed.")
        return

    # Save phone in state data, move to UPI step
    await update_state_data(user.id, phone=phone)
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

    # Validate UPI format
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

    # Retrieve phone from state
    state_data = await get_state_data(user.id)
    phone = state_data.get("phone")

    if not phone:
        # State expired or corrupted
        await clear_state(user.id)
        await message.answer(
            "⚠️ Session expired. Please send /register to start again."
        )
        return

    # Generate referral code from phone
    referral_code = phone_to_referral_code(phone)

    # Ensure referral code is unique (collision handling: append user_id suffix if needed)
    existing_code_user = await users_db.get_user_by_referral_code(referral_code)
    if existing_code_user and existing_code_user["user_id"] != user.id:
        # Very rare collision: append last 2 chars of user_id
        referral_code = referral_code[:8] + str(user.id)[-2:]

    # Save to database
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

    # Build referral link
    bot_info = await message.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={referral_code}"

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
