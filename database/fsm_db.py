"""
FSM (Finite State Machine) State Manager
MongoDB-backed conversation states with TTL expiry
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, Dict
from database.connection import get_db
from config import FSM_TTL

logger = logging.getLogger(__name__)

# ─── State Constants ──────────────────────────────────────────────────────────
class States:
    # Referral flow
    WAITING_REFERRAL_CODE = "waiting_referral_code"
    # Registration flow
    WAITING_PHONE = "waiting_phone"
    WAITING_UPI = "waiting_upi"
    # Admin flow
    ADMIN_BROADCAST = "admin_broadcast"
    ADMIN_ADD_CHANNEL = "admin_add_channel"
    ADMIN_REMOVE_CHANNEL = "admin_remove_channel"


async def _ensure_ttl_index():
    """Create TTL index on state documents."""
    db = await get_db()
    try:
        await db.fsm_states.create_index("expires_at", expireAfterSeconds=0)
    except Exception:
        pass  # Already exists


async def set_state(user_id: int, state: str, data: Optional[Dict[str, Any]] = None):
    """Set FSM state for a user with optional payload."""
    db = await get_db()
    await _ensure_ttl_index()
    expires = datetime.now(timezone.utc) + timedelta(seconds=FSM_TTL)
    await db.fsm_states.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "state": state,
                "data": data or {},
                "updated_at": datetime.now(timezone.utc),
                "expires_at": expires,
            }
        },
        upsert=True,
    )


async def get_state(user_id: int) -> Optional[str]:
    """Get current FSM state for a user."""
    db = await get_db()
    doc = await db.fsm_states.find_one({"user_id": user_id})
    return doc["state"] if doc else None


async def get_state_data(user_id: int) -> Dict[str, Any]:
    """Get state data payload for a user."""
    db = await get_db()
    doc = await db.fsm_states.find_one({"user_id": user_id})
    return doc.get("data", {}) if doc else {}


async def update_state_data(user_id: int, **kwargs):
    """Merge additional data into the current state payload."""
    db = await get_db()
    updates = {f"data.{k}": v for k, v in kwargs.items()}
    updates["expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=FSM_TTL)
    await db.fsm_states.update_one({"user_id": user_id}, {"$set": updates})


async def clear_state(user_id: int):
    """Remove FSM state for a user (end of conversation)."""
    db = await get_db()
    await db.fsm_states.delete_one({"user_id": user_id})
