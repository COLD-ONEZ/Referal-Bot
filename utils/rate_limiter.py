"""
Rate Limiter
In-memory rate limiting with per-user cooldowns.
MongoDB-backed suspicious activity detection.
"""
import time
import logging
from collections import defaultdict
from typing import Dict, Tuple
from database.connection import get_db
from config import RATE_LIMIT_SECONDS, MAX_REFERRALS_PER_HOUR
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# user_id -> (last_request_time, request_count_in_window)
_user_last_request: Dict[int, float] = defaultdict(float)


def is_rate_limited(user_id: int) -> bool:
    """
    Simple per-user cooldown check.
    Returns True if user is sending too fast.
    """
    now = time.monotonic()
    last = _user_last_request[user_id]
    if now - last < RATE_LIMIT_SECONDS:
        return True
    _user_last_request[user_id] = now
    return False


async def record_referral_attempt(referrer_id: int) -> bool:
    """
    Record a referral event for anti-abuse detection.
    Returns True if suspicious (too many referrals in 1 hour).
    """
    db = await get_db()
    from datetime import timedelta
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    # Insert this event
    await db.rate_limits.insert_one({
        "user_id": referrer_id,
        "timestamp": datetime.now(timezone.utc),
        "type": "referral",
    })

    # Count events in the last hour
    count = await db.rate_limits.count_documents({
        "user_id": referrer_id,
        "type": "referral",
        "timestamp": {"$gte": one_hour_ago},
    })

    if count > MAX_REFERRALS_PER_HOUR:
        logger.warning(f"Suspicious referral activity: user {referrer_id} has {count} referrals in 1h")
        return True
    return False
