"""
MongoDB Connection Manager
Async connection with auto-reconnect and health checks
"""
import logging
import asyncio
import motor.motor_asyncio
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, OperationFailure
from config import DATABASE_URI, DATABASE_NAME

logger = logging.getLogger(__name__)

_client: motor.motor_asyncio.AsyncIOMotorClient = None
_db = None


async def get_db():
    """Return the active database, reconnecting if necessary."""
    global _client, _db
    if _client is None or _db is None:
        await connect()
    return _db


async def connect(retries: int = 5, delay: float = 3.0):
    """Establish connection to MongoDB with retry logic."""
    global _client, _db
    for attempt in range(1, retries + 1):
        try:
            _client = motor.motor_asyncio.AsyncIOMotorClient(
                DATABASE_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                socketTimeoutMS=10000,
                maxPoolSize=50,
                minPoolSize=5,
                retryWrites=True,
            )
            # Ping to confirm connection
            await _client.admin.command("ping")
            _db = _client[DATABASE_NAME]
            logger.info(f"✅ Connected to MongoDB: {DATABASE_NAME}")
            await _ensure_indexes()
            return _db
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"❌ MongoDB connection attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                await asyncio.sleep(delay)
            else:
                raise RuntimeError("Could not connect to MongoDB after multiple attempts.") from e


async def _drop_index_if_exists(collection, index_name: str):
    """Drop an index by name, silently ignoring if it doesn't exist."""
    try:
        await collection.drop_index(index_name)
        logger.info(f"Dropped old index '{index_name}' from {collection.name}")
    except OperationFailure as e:
        # 27 = IndexNotFound — perfectly fine
        if e.code != 27:
            logger.warning(f"Could not drop index '{index_name}': {e}")
    except Exception as e:
        logger.warning(f"Could not drop index '{index_name}': {e}")


async def _ensure_indexes():
    """
    Create all necessary database indexes for performance and uniqueness.

    The users.user_id field should never be null in a real document, but
    legacy data may contain null-valued documents.  A non-sparse unique index
    treats all nulls as duplicates of each other and raises E11000 on startup.
    Fix: drop the old non-sparse index first, then recreate it with sparse=True
    so null documents are simply skipped by the index.
    """
    db = _db

    # ── users ──────────────────────────────────────────────────────────────────
    # Drop old non-sparse indexes that cause E11000 on null documents.
    # drop_index is idempotent — safe to call even if the index doesn't exist.
    await _drop_index_if_exists(db.users, "user_id_1")
    await _drop_index_if_exists(db.users, "referral_code_1")
    await _drop_index_if_exists(db.users, "phone_number_1")

    try:
        await db.users.create_index("user_id",       unique=True, sparse=True)
        await db.users.create_index("referral_code", unique=True, sparse=True)
        await db.users.create_index("phone_number",  unique=True, sparse=True)
        await db.users.create_index("referred_by")
        await db.users.create_index("total_points")
        await db.users.create_index("total_invites")
    except Exception as e:
        logger.warning(f"users index warning: {e}")

    # ── channels ───────────────────────────────────────────────────────────────
    try:
        await db.channels.create_index("channel_id", unique=True)
    except Exception as e:
        logger.warning(f"channels index warning: {e}")

    # ── referral_events ────────────────────────────────────────────────────────
    try:
        await db.referral_events.create_index("referrer_id")
        await db.referral_events.create_index("referee_id")
        await db.referral_events.create_index(
            [("referee_id", 1), ("channel_id", 1)], unique=True
        )
    except Exception as e:
        logger.warning(f"referral_events index warning: {e}")

    # ── rate_limits ────────────────────────────────────────────────────────────
    try:
        await db.rate_limits.create_index("user_id")
        await db.rate_limits.create_index("timestamp", expireAfterSeconds=3600)
    except Exception as e:
        logger.warning(f"rate_limits index warning: {e}")

    logger.info("✅ MongoDB indexes ensured")


async def close():
    """Close the MongoDB connection."""
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed")
