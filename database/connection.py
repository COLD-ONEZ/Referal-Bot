"""
MongoDB Connection Manager
Async connection with auto-reconnect and health checks
"""
import logging
import asyncio
import motor.motor_asyncio
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
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


async def _ensure_indexes():
    """Create all necessary database indexes for performance and uniqueness."""
    db = _db
    try:
        # Users collection
        await db.users.create_index("user_id", unique=True)
        await db.users.create_index("referral_code", unique=True, sparse=True)
        await db.users.create_index("phone_number", unique=True, sparse=True)
        await db.users.create_index("referred_by")
        await db.users.create_index("total_points")
        await db.users.create_index("total_invites")

        # Channels collection
        await db.channels.create_index("channel_id", unique=True)

        # Referral events collection
        await db.referral_events.create_index("referrer_id")
        await db.referral_events.create_index("referee_id")
        await db.referral_events.create_index([("referee_id", 1), ("channel_id", 1)], unique=True)

        # Rate limiting collection
        await db.rate_limits.create_index("user_id")
        await db.rate_limits.create_index("timestamp", expireAfterSeconds=3600)

        logger.info("✅ MongoDB indexes ensured")
    except Exception as e:
        logger.warning(f"Index creation warning (may already exist): {e}")


async def close():
    """Close the MongoDB connection."""
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed")
