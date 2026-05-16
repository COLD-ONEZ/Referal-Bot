"""
Channels Database Handler
Manage required channels/groups for the force-subscribe system
"""
import logging
from typing import List, Dict, Any, Optional
from database.connection import get_db

logger = logging.getLogger(__name__)


async def add_channel(channel_id: int, title: str, username: Optional[str] = None, invite_link: Optional[str] = None) -> bool:
    """Add a required channel. Returns True if inserted, False if already exists."""
    db = await get_db()
    doc = {
        "channel_id": channel_id,
        "title": title,
        "username": username,
        "invite_link": invite_link,
    }
    try:
        await db.channels.update_one(
            {"channel_id": channel_id},
            {"$set": doc},
            upsert=True,
        )
        logger.info(f"Channel added/updated: {channel_id} ({title})")
        return True
    except Exception as e:
        logger.error(f"Error adding channel {channel_id}: {e}")
        return False


async def remove_channel(channel_id: int) -> bool:
    """Remove a required channel."""
    db = await get_db()
    result = await db.channels.delete_one({"channel_id": channel_id})
    return result.deleted_count > 0


async def get_all_channels() -> List[Dict[str, Any]]:
    """Return all required channels."""
    db = await get_db()
    cursor = db.channels.find({})
    return await cursor.to_list(length=None)


async def get_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    """Get a specific channel document."""
    db = await get_db()
    return await db.channels.find_one({"channel_id": channel_id})


async def count_channels() -> int:
    """Return total number of required channels."""
    db = await get_db()
    return await db.channels.count_documents({})


async def update_invite_link(channel_id: int, invite_link: str):
    """Update cached invite link for a channel."""
    db = await get_db()
    await db.channels.update_one(
        {"channel_id": channel_id},
        {"$set": {"invite_link": invite_link}},
    )
