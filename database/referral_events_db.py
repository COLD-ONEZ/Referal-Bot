"""
Referral Events Database Handler
Tracks per-channel membership for accurate point calculation.
One document per (referee_id, channel_id) pair.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from database.connection import get_db

logger = logging.getLogger(__name__)


async def record_join_event(referrer_id: int, referee_id: int, channel_id: int) -> bool:
    """
    Record that referee joined channel_id (referred by referrer_id).
    Returns True if this is a NEW join (not seen before = eligible for points).
    Returns False if already recorded (prevent double points).
    """
    db = await get_db()
    doc = {
        "referrer_id": referrer_id,
        "referee_id": referee_id,
        "channel_id": channel_id,
        "is_active": True,
        "first_join": datetime.now(timezone.utc),
        "last_updated": datetime.now(timezone.utc),
        "point_awarded": False,  # Will be set True after points are given
        "point_revoked": False,
    }
    try:
        await db.referral_events.insert_one(doc)
        return True  # Fresh join → award points
    except Exception:
        # Duplicate (referee_id, channel_id) — already exists
        # Only allow re-activation if this is a re-join AND points were already taken back
        existing = await db.referral_events.find_one(
            {"referee_id": referee_id, "channel_id": channel_id}
        )
        if existing and existing.get("point_revoked") and not existing.get("is_active"):
            # User previously left and points were removed; now rejoined
            # Policy: NO points on re-join
            await db.referral_events.update_one(
                {"referee_id": referee_id, "channel_id": channel_id},
                {"$set": {"is_active": True, "last_updated": datetime.now(timezone.utc)}},
            )
        return False  # No new points


async def record_leave_event(referee_id: int, channel_id: int) -> Optional[int]:
    """
    Record that referee left channel_id.
    Returns referrer_id if points should be deducted, else None.
    """
    db = await get_db()
    event = await db.referral_events.find_one(
        {"referee_id": referee_id, "channel_id": channel_id, "is_active": True, "point_awarded": True}
    )
    if not event:
        # Either not tracked or points never awarded — no action
        await db.referral_events.update_one(
            {"referee_id": referee_id, "channel_id": channel_id},
            {"$set": {"is_active": False, "last_updated": datetime.now(timezone.utc)}},
        )
        return None

    await db.referral_events.update_one(
        {"referee_id": referee_id, "channel_id": channel_id},
        {
            "$set": {
                "is_active": False,
                "point_revoked": True,
                "last_updated": datetime.now(timezone.utc),
            }
        },
    )
    return event["referrer_id"]


async def mark_point_awarded(referee_id: int, channel_id: int):
    """Mark that the point for this (referee, channel) has been awarded."""
    db = await get_db()
    await db.referral_events.update_one(
        {"referee_id": referee_id, "channel_id": channel_id},
        {"$set": {"point_awarded": True, "last_updated": datetime.now(timezone.utc)}},
    )


async def get_active_channels_for_referee(referee_id: int) -> List[int]:
    """Return list of channel_ids the referee is currently active in (tracked)."""
    db = await get_db()
    cursor = db.referral_events.find(
        {"referee_id": referee_id, "is_active": True},
        {"channel_id": 1},
    )
    docs = await cursor.to_list(length=None)
    return [d["channel_id"] for d in docs]


async def get_referrer_for_referee(referee_id: int) -> Optional[int]:
    """Find who referred this user (from any event record)."""
    db = await get_db()
    event = await db.referral_events.find_one({"referee_id": referee_id})
    return event["referrer_id"] if event else None


async def has_ever_joined(referee_id: int, channel_id: int) -> bool:
    """Check if referee has ever joined this channel (blocks double points)."""
    db = await get_db()
    doc = await db.referral_events.find_one({"referee_id": referee_id, "channel_id": channel_id})
    return doc is not None


async def get_all_tracked_referees() -> List[Dict[str, Any]]:
    """Return all unique referee → referrer pairs for batch checks."""
    db = await get_db()
    pipeline = [
        {"$group": {"_id": "$referee_id", "referrer_id": {"$first": "$referrer_id"}}},
    ]
    return await db.referral_events.aggregate(pipeline).to_list(length=None)
