"""
Configuration file for Referral Reward Bot
All settings loaded from environment variables with fallback defaults
"""
import os
from os import environ
from typing import List


# ─── Bot Credentials ─────────────────────────────────────────────────────────
API_ID: int = int(environ.get("API_ID", "20400973"))
API_HASH: str = environ.get("API_HASH", "047838cb76d54bc445e155a7cab44664")
BOT_TOKEN: str = environ.get("BOT_TOKEN", "8991082716:AAFcSp7o_9H6RvWOiVEXuqBOIXuwRAKGoLY")
BOT_USERNAME: str = environ.get("BOT_USERNAME", "SF_ReferalBoT")  # Without @, e.g. MyReferralBot

# ─── Database ─────────────────────────────────────────────────────────────────
DATABASE_URI: str = environ.get("DATABASE_URI", "mongodb+srv://amalabraham989:seriesfactory@sfactory.a7gq1.mongodb.net/?retryWrites=true&w=majority&appName=sfactory")
DATABASE_NAME: str = environ.get("DATABASE_NAME", "sfactory")

# ─── Admin Settings ───────────────────────────────────────────────────────────
_admins_raw = environ.get("ADMINS", "5677517133")
ADMINS: List[int] = [
    int(a.strip()) for a in _admins_raw.split() if a.strip().isdigit()
]

# ─── Required Channels (stored in DB, but initial seed from env) ──────────────
# Comma-separated list of channel IDs, e.g. "-1001234567890,-1009876543210"
_channels_raw = environ.get("REQUIRED_CHANNELS", "-1002028603218")
INITIAL_REQUIRED_CHANNELS: List[int] = [
    int(c.strip()) for c in _channels_raw.split(",") if c.strip().lstrip("-").isdigit()
]

# ─── Point System ────────────────────────────────────────────────────────────
# Max points awarded per referred user (split across required channels)
MAX_POINTS_PER_REFERRAL: float = float(environ.get("MAX_POINTS_PER_REFERRAL", "1.0"))

# ─── Anti-Abuse Settings ─────────────────────────────────────────────────────
# Maximum referrals per hour to detect suspicious activity
MAX_REFERRALS_PER_HOUR: int = int(environ.get("MAX_REFERRALS_PER_HOUR", "50"))
# Minimum account age in days to be counted (0 = disabled)
MIN_ACCOUNT_AGE_DAYS: int = int(environ.get("MIN_ACCOUNT_AGE_DAYS", "0"))

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_CHANNEL: int = int(environ.get("LOG_CHANNEL", "-1002028603218")) if environ.get("LOG_CHANNEL", "0").lstrip("-").isdigit() else 0
LOG_LEVEL: str = environ.get("LOG_LEVEL", "INFO")

# ─── FSM State TTL (seconds) ─────────────────────────────────────────────────
# How long to keep conversation state alive
FSM_TTL: int = int(environ.get("FSM_TTL", "600"))

# ─── Rate Limiting ────────────────────────────────────────────────────────────
RATE_LIMIT_SECONDS: int = int(environ.get("RATE_LIMIT_SECONDS", "2"))

# ─── Validation Patterns ─────────────────────────────────────────────────────
# Indian phone numbers: starts with 6-9, 10 digits total
PHONE_REGEX: str = r"^[6-9]\d{9}$"
# UPI ID pattern
UPI_REGEX: str = r"^[\w.\-]{2,256}@[a-zA-Z]{2,64}$"

# ─── Referral Code Config ─────────────────────────────────────────────────────
REFERRAL_CODE_LENGTH: int = int(environ.get("REFERRAL_CODE_LENGTH", "10"))

# ─── Broadcast ────────────────────────────────────────────────────────────────
BROADCAST_BATCH_SIZE: int = int(environ.get("BROADCAST_BATCH_SIZE", "30"))
BROADCAST_DELAY: float = float(environ.get("BROADCAST_DELAY", "0.05"))  # seconds between messages
