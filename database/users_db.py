"""
Users Database Handler
Full CRUD operations for user management with anti-fraud support
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from database.connection import get_db

logger = logging.getLogger(__name__)


async def create_user(
    user_id: int,
    username: Optional[str],
    full_name: str,
) -> bool:
    """
    Insert a new user document (pre-registration stage).
    Returns True if inserted, False if already exists.
    """
    db = await get_db()
    doc = {
        "user_id": user_id,
        "username": username,
        "full_name": full_name,
        # Registration fields (filled during /register flow)
        "phone_number": None,
        "upi_id": None,
        "referral_code": None,
        "referred_by": None,          # user_id of referrer
        "referred_by_code": None,     # code used
        # Stats
        "total_invites": 0,
        "total_points": 0.0,
        "joined_referrals": [],       # list of user_ids who joined all channels
        "left_referrals": [],         # list of user_ids who left at least one channel
        # State
        "is_registered": False,
        "channels_joined": [],        # list of channel_ids user is currently in
        "channels_joined_history": [], # ever joined (for "no double points" rule)
        # Meta
        "registration_date": None,
        "created_at": datetime.now(timezone.utc),
        # Anti-fraud
        "fraud_flags": [],
        "is_banned": False,
        "reward_claimed": False,
    }
    try:
        await db.users.insert_one(doc)
        return True
    except Exception:
        # Duplicate key → user already exists; update name/username silently
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"username": username, "full_name": full_name}},
        )
        return False


async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a user document by Telegram user_id."""
    db = await get_db()
    return await db.users.find_one({"user_id": user_id})


async def get_user_by_referral_code(code: str) -> Optional[Dict[str, Any]]:
    """Fetch a user by their referral code."""
    db = await get_db()
    return await db.users.find_one({"referral_code": code})


async def get_user_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    """Fetch a user by their registered phone number."""
    db = await get_db()
    return await db.users.find_one({"phone_number": phone})


async def set_referred_by(user_id: int, referrer_id: int, code: str) -> bool:
    """Set the referrer for a user (before registration)."""
    db = await get_db()
    result = await db.users.update_one(
        {"user_id": user_id, "referred_by": None},  # Only set once
        {"$set": {"referred_by": referrer_id, "referred_by_code": code}},
    )
    return result.modified_count > 0


async def complete_registration(
    user_id: int,
    phone_number: str,
    upi_id: str,
    referral_code: str,
) -> bool:
    """Mark user as registered with all required fields."""
    db = await get_db()
    result = await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "phone_number": phone_number,
                "upi_id": upi_id,
                "referral_code": referral_code,
                "is_registered": True,
                "registration_date": datetime.now(timezone.utc),
            }
        },
    )
    return result.modified_count > 0


async def add_fraud_flag(user_id: int, reason: str):
    """Append a fraud flag to a user's record."""
    db = await get_db()
    await db.users.update_one(
        {"user_id": user_id},
        {
            "$push": {
                "fraud_flags": {
                    "reason": reason,
                    "timestamp": datetime.now(timezone.utc),
                }
            }
        },
    )


async def ban_user(user_id: int):
    """Ban a user from the bot."""
    db = await get_db()
    await db.users.update_one({"user_id": user_id}, {"$set": {"is_banned": True}})


async def is_banned(user_id: int) -> bool:
    db = await get_db()
    user = await db.users.find_one({"user_id": user_id}, {"is_banned": 1})
    return bool(user and user.get("is_banned"))


async def update_points(user_id: int, delta: float):
    """
    Increment (positive delta) or decrement (negative delta) user points.
    Points are clamped to >= 0.
    """
    db = await get_db()
    await db.users.update_one(
        {"user_id": user_id},
        {"$inc": {"total_points": delta}},
    )
    # Ensure points never go negative
    await db.users.update_one(
        {"user_id": user_id, "total_points": {"$lt": 0}},
        {"$set": {"total_points": 0.0}},
    )


async def update_invites(user_id: int, delta: int = 1):
    """Increment or decrement invite count."""
    db = await get_db()
    await db.users.update_one(
        {"user_id": user_id},
        {"$inc": {"total_invites": delta}},
    )
    # Clamp to 0
    await db.users.update_one(
        {"user_id": user_id, "total_invites": {"$lt": 0}},
        {"$set": {"total_invites": 0}},
    )


async def record_channel_join(user_id: int, channel_id: int):
    """
    Record that a user joined a channel.
    - channels_joined: current active memberships
    - channels_joined_history: all-time history (never removed, used to block double points)
    """
    db = await get_db()
    await db.users.update_one(
        {"user_id": user_id},
        {
            "$addToSet": {
                "channels_joined": channel_id,
                "channels_joined_history": channel_id,
            }
        },
    )


async def record_channel_leave(user_id: int, channel_id: int):
    """Record that a user left a channel (remove from active set)."""
    db = await get_db()
    await db.users.update_one(
        {"user_id": user_id},
        {"$pull": {"channels_joined": channel_id}},
    )


async def add_joined_referral(referrer_id: int, referee_id: int):
    """Record that a referred user is now fully joined (all channels)."""
    db = await get_db()
    await db.users.update_one(
        {"user_id": referrer_id},
        {"$addToSet": {"joined_referrals": referee_id}},
    )


async def add_left_referral(referrer_id: int, referee_id: int):
    """Record that a referred user has left at least one channel."""
    db = await get_db()
    await db.users.update_one(
        {"user_id": referrer_id},
        {
            "$addToSet": {"left_referrals": referee_id},
            "$pull": {"joined_referrals": referee_id},
        },
    )


async def get_leaderboard(limit: int = 10) -> List[Dict[str, Any]]:
    """Return top users sorted by total_points descending."""
    db = await get_db()
    cursor = db.users.find(
        {"is_registered": True, "is_banned": False},
        {
            "user_id": 1, "full_name": 1, "username": 1,
            "phone_number": 1, "upi_id": 1,
            "total_invites": 1, "total_points": 1,
        },
    ).sort("total_points", -1).limit(limit)
    return await cursor.to_list(length=limit)


async def get_stats() -> Dict[str, int]:
    """Return aggregate statistics."""
    db = await get_db()
    total = await db.users.count_documents({})
    registered = await db.users.count_documents({"is_registered": True})
    # Active = registered + not banned
    active = await db.users.count_documents({"is_registered": True, "is_banned": False})
    # Total referrals = sum of total_invites (simpler pipeline)
    pipeline = [
        {"$match": {"is_registered": True}},
        {"$group": {"_id": None, "total": {"$sum": "$total_invites"}}},
    ]
    agg = await db.users.aggregate(pipeline).to_list(length=1)
    total_referrals = agg[0]["total"] if agg else 0
    return {
        "total_users": total,
        "registered_users": registered,
        "active_users": active,
        "total_referrals": total_referrals,
    }


async def get_all_user_ids() -> List[int]:
    """Return all user_ids for broadcasting."""
    db = await get_db()
    cursor = db.users.find({}, {"user_id": 1})
    docs = await cursor.to_list(length=None)
    return [d["user_id"] for d in docs]
