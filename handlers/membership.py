"""
Membership Tracking Handler
Listens to chat_member updates to track joins/leaves in required channels.
Awards and revokes referral points accordingly.
"""
import logging
from aiogram import Router
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER, MEMBER
from aiogram.types import ChatMemberUpdated

from database import users_db, channels_db
from database.referral_events_db import (
    record_join_event,
    record_leave_event,
    mark_point_awarded,
    has_ever_joined,
)
from utils.points import calculate_point_per_channel

logger = logging.getLogger(__name__)
router = Router()


async def _get_required_channel_ids() -> set:
    """Return set of all required channel IDs."""
    channels = await channels_db.get_all_channels()
    return {ch["channel_id"] for ch in channels}


@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> MEMBER))
async def on_user_joined_channel(event: ChatMemberUpdated):
    """
    Fired when a user JOINS (or is added to) a chat.
    - Update their channel membership record
    - If they're a referred user, potentially award points to referrer
    """
    chat_id = event.chat.id
    user_id = event.new_chat_member.user.id

    if event.new_chat_member.user.is_bot:
        return

    required_ids = await _get_required_channel_ids()
    if chat_id not in required_ids:
        return  # Not a tracked channel

    logger.info(f"User {user_id} joined channel {chat_id}")

    # Update user's active channel list
    await users_db.record_channel_join(user_id, chat_id)

    # Check if this user is registered and was referred by someone
    db_user = await users_db.get_user(user_id)
    if not db_user or not db_user.get("referred_by"):
        return  # Not referred → no points to award

    referrer_id = db_user["referred_by"]

    # Anti-double-points: has this referee EVER joined this channel before?
    if await has_ever_joined(user_id, chat_id):
        logger.debug(f"User {user_id} previously joined channel {chat_id} — no points awarded")
        return

    # Record the join event
    is_new = await record_join_event(referrer_id, user_id, chat_id)
    if not is_new:
        return  # Already tracked

    # Calculate and award point
    total_channels = len(required_ids)
    point = calculate_point_per_channel(total_channels)

    await users_db.update_points(referrer_id, point)
    await mark_point_awarded(user_id, chat_id)

    logger.info(
        f"Awarded {point} points to {referrer_id} "
        f"(referee {user_id} joined channel {chat_id})"
    )

    # Check if referee is now in ALL required channels
    user_active_channels = set(db_user.get("channels_joined", []) + [chat_id])
    if required_ids.issubset(user_active_channels):
        await users_db.add_joined_referral(referrer_id, user_id)
        await users_db.update_invites(referrer_id, 1)
        logger.info(
            f"Referee {user_id} is now in ALL required channels — "
            f"incremented invite count for {referrer_id}"
        )


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_user_left_channel(event: ChatMemberUpdated):
    """
    Fired when a user LEAVES (or is kicked from) a chat.
    - Update their channel membership record
    - If they were a referred user with points awarded, REVOKE the point
    """
    chat_id = event.chat.id
    user_id = event.new_chat_member.user.id

    if event.new_chat_member.user.is_bot:
        return

    required_ids = await _get_required_channel_ids()
    if chat_id not in required_ids:
        return

    logger.info(f"User {user_id} left channel {chat_id}")

    # Update channel leave record
    await users_db.record_channel_leave(user_id, chat_id)

    # Check if they were referred
    db_user = await users_db.get_user(user_id)
    if not db_user or not db_user.get("referred_by"):
        return

    referrer_id = db_user["referred_by"]

    # Record leave and get referrer_id if points should be revoked
    revoke_from = await record_leave_event(user_id, chat_id)
    if revoke_from is None:
        return  # Points were never awarded for this channel

    # Deduct the point
    total_channels = len(required_ids)
    point = calculate_point_per_channel(total_channels)
    await users_db.update_points(referrer_id, -point)

    # Update invite counts
    await users_db.add_left_referral(referrer_id, user_id)
    await users_db.update_invites(referrer_id, -1)

    logger.info(
        f"Revoked {point} points from {referrer_id} "
        f"(referee {user_id} left channel {chat_id})"
    )
