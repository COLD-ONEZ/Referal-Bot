# 🎯 Telegram Referral Reward Bot

A production-ready, fully async Telegram bot for referral-based reward systems. Built with **aiogram 3.x** and **MongoDB** — featuring an anti-fake system, point tracking, admin panel, and member verification.

---

## 📋 Table of Contents

- [Features](#-features)
- [Bot Flow Overview](#-bot-flow-overview)
- [Referral & Point System](#-referral--point-system)
- [Anti-Fake System](#-anti-fake-system)
- [Installation](#-installation)
- [BotFather Setup](#-botfather-setup)
- [MongoDB Setup](#-mongodb-setup)
- [Environment Variables](#-environment-variables)
- [Local Development](#-local-development)
- [VPS Deployment](#-vps-deployment)
- [Docker Deployment](#-docker-deployment)
- [Railway / Render Deployment](#-railway--render-deployment)
- [Admin Commands](#-admin-commands)
- [Project Structure](#-project-structure)

---

## ✨ Features

- ✅ Force-subscribe with live membership verification
- 🔗 Unique referral links & codes per user
- 📊 Real-time point tracking with per-channel granularity
- 🚫 Anti-fake system: phone validation, duplicate detection, rate limiting
- 🛡️ One phone number = one account enforcement
- 📣 Admin broadcast to all users
- 🏆 Leaderboard (top 3 referrers with full stats for admin)
- 📢 Dynamic channel management (add/remove without restart)
- 🔄 Auto point revocation when referred user leaves a channel
- 🐳 Docker & docker-compose ready
- ⚡ Fully async (aiogram 3.x + motor)

---

## 🔄 Bot Flow Overview

```
User sends /start
    │
    ├─► [Has not joined required channels]
    │       ├─ Shows JOIN buttons for each channel
    │       └─ Shows CHECK JOIN button
    │
    └─► [Has joined all channels]
            │
            ├─► [Came via referral link (?start=CODE)]
            │       └─ "Send /register to register"
            │
            └─► [Plain /start]
                    ├─► "YES I HAVE" → Ask for referral code → "Send /register"
                    └─► "I DON'T HAVE" → "Send /register"

/register command
    │
    ├─ Step 1: Ask for 10-digit Indian phone number
    │       ├─ Validate format (6-9 prefix, 10 digits)
    │       ├─ Reject duplicates (one phone = one account)
    │       └─ Store in session
    │
    └─ Step 2: Ask for UPI ID / GPay number
            ├─ Validate UPI format
            ├─ Generate referral code from phone (0=a, 1=b, ..., 9=j)
            └─ Complete registration → Show referral link
```

---

## 🎯 Referral & Point System

### How Points Work

- Each referred user is worth **1.0 point total**, split across required channels
- `point_per_channel = 1.0 / total_required_channels`

| Required Channels | Points per Channel |
|------------------|--------------------|
| 1                | 1.0                |
| 2                | 0.5                |
| 5                | 0.2                |

### Point Rules

- ✅ Points awarded when a referred user joins a required channel
- ❌ Points revoked instantly when a referred user leaves a channel
- 🚫 **No double points** — if a user leaves and rejoins, NO additional points
- 🔁 Invite count tracks users who are in ALL required channels simultaneously

### Referral Code Generation

Phone digits are converted to letters: `0=a, 1=b, 2=c, 3=d, 4=e, 5=f, 6=g, 7=h, 8=i, 9=j`

Example:
- Phone: `9876543210`
- Code: `jihgfedcba`
- Link: `https://t.me/YourBot?start=jihgfedcba`

---

## 🛡️ Anti-Fake System

| Protection | How it Works |
|-----------|-------------|
| Phone validation | Only valid Indian numbers (10 digits, starts 6-9) |
| Duplicate phone | One phone = one Telegram account |
| Self-referral | Prevented at code entry and link click |
| Double points | Points only awarded once per (referee, channel) pair |
| Fraud flags | Suspicious actions are logged per user |
| Rate limiting | Per-user request cooldown (configurable) |
| Hourly cap | Alert if referrer gains too many referrals in 1 hour |
| Re-join block | Leaving and rejoining a channel = no extra points |

---

## 🚀 Installation

### Prerequisites

- Python 3.10 or higher
- MongoDB (local or Atlas)
- A Telegram Bot Token from @BotFather

### Step-by-Step

```bash
# 1. Clone the repository
git clone https://github.com/yourname/referral-bot
cd referral-bot

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
nano .env   # Fill in your values

# 5. Run the bot
python main.py
```

---

## 🤖 BotFather Setup

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** to `BOT_TOKEN` in your `.env`
4. Send `/setprivacy` → Select your bot → **Disable** (allows the bot to see messages)
5. Add your bot as **admin** to all required channels with these permissions:
   - ✅ Invite Users via Link
   - ✅ Read Messages (to check membership)

---

## 🍃 MongoDB Setup

### Option A: MongoDB Atlas (Recommended for Cloud)

1. Go to [cloud.mongodb.com](https://cloud.mongodb.com)
2. Create a free **M0 cluster**
3. Create a database user with read/write permissions
4. Go to **Network Access** → Add IP → `0.0.0.0/0` (allow all)
5. Click **Connect** → **Connect your application** → Copy the URI
6. Set `DATABASE_URI=mongodb+srv://user:pass@cluster.mongodb.net/`

### Option B: Local MongoDB

```bash
# Ubuntu/Debian
sudo apt install -y mongodb
sudo systemctl start mongodb
sudo systemctl enable mongodb
```

Set `DATABASE_URI=mongodb://localhost:27017`

---

## ⚙️ Environment Variables

| Variable | Required | Description |
|---------|---------|-------------|
| `BOT_TOKEN` | ✅ | Telegram bot token from BotFather |
| `API_ID` | ✅ | Telegram API ID from my.telegram.org |
| `API_HASH` | ✅ | Telegram API Hash from my.telegram.org |
| `BOT_USERNAME` | ✅ | Bot username without @ |
| `ADMINS` | ✅ | Space-separated admin Telegram user IDs |
| `DATABASE_URI` | ✅ | MongoDB connection string |
| `DATABASE_NAME` | ✅ | MongoDB database name |
| `REQUIRED_CHANNELS` | ⚙️ | Comma-separated initial channel IDs |
| `MAX_POINTS_PER_REFERRAL` | ⚙️ | Default: 1.0 |
| `MAX_REFERRALS_PER_HOUR` | ⚙️ | Fraud threshold, default: 30 |
| `LOG_CHANNEL` | Optional | Telegram channel ID for logs |
| `RATE_LIMIT_SECONDS` | ⚙️ | Anti-spam cooldown, default: 2s |
| `FSM_TTL` | ⚙️ | Conversation state TTL in seconds, default: 600 |
| `BROADCAST_BATCH_SIZE` | ⚙️ | Broadcast batch size, default: 30 |

---

## 💻 Local Development

```bash
# Install dev dependencies
pip install -r requirements.txt

# Run with local MongoDB
DATABASE_URI=mongodb://localhost:27017 python main.py

# Or use docker-compose for full local stack
docker-compose up --build
```

---

## 🖥️ VPS Deployment

### Using systemd (recommended for production)

```bash
# 1. SSH into your VPS
ssh user@your-vps-ip

# 2. Clone the repo
git clone https://github.com/yourname/referral-bot /opt/referral-bot
cd /opt/referral-bot

# 3. Install Python 3.11
sudo apt update && sudo apt install -y python3.11 python3.11-venv

# 4. Set up venv and install
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Configure .env
cp .env.example .env
nano .env

# 6. Create systemd service
sudo nano /etc/systemd/system/referral-bot.service
```

Paste this into the service file:

```ini
[Unit]
Description=Telegram Referral Reward Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/referral-bot
EnvironmentFile=/opt/referral-bot/.env
ExecStart=/opt/referral-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# 7. Start and enable
sudo systemctl daemon-reload
sudo systemctl start referral-bot
sudo systemctl enable referral-bot

# 8. Check logs
sudo journalctl -u referral-bot -f
```

---

## 🐳 Docker Deployment

```bash
# Build and run with docker-compose (includes local MongoDB)
docker-compose up -d --build

# View logs
docker-compose logs -f bot

# Stop
docker-compose down

# Update bot without downtime
docker-compose pull && docker-compose up -d --build
```

---

## ☁️ Railway / Render Deployment

### Railway

1. Go to [railway.app](https://railway.app) → New Project
2. Connect your GitHub repository
3. Add a **MongoDB** plugin from Railway's marketplace
4. Set environment variables in the Railway dashboard:
   - All variables from `.env.example`
   - `DATABASE_URI` will be auto-provided by the MongoDB plugin
5. Deploy! Railway auto-deploys on every push.

### Render

1. Go to [render.com](https://render.com) → New Web Service
2. Connect your GitHub repository
3. Set **Runtime** to Python, **Build Command** to `pip install -r requirements.txt`
4. Set **Start Command** to `python main.py`
5. Add environment variables in the Render dashboard
6. Use [MongoDB Atlas](https://cloud.mongodb.com) for the database (Render has no built-in MongoDB)

---

## 👨‍💼 Admin Commands

| Command | Description |
|---------|-------------|
| `/addchannel` | Add a required channel (forward a message or send ID) |
| `/removechannel` | Remove a required channel (interactive buttons) |
| `/channels` | List all required channels |
| `/broadcast` | Send a message to all users |
| `/userstats` | View total/registered/active users & referral count |
| `/leaderboard` | Top 3 users with full stats (phone, UPI, points) |
| `/myinfo` | Your own referral stats |

---

## 📁 Project Structure

```
referral-bot/
├── main.py                    # Bot entry point, startup/shutdown
├── config.py                  # All configuration (env vars)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
│
├── database/
│   ├── __init__.py
│   ├── connection.py          # MongoDB connection & index management
│   ├── users_db.py            # User CRUD + stats + anti-fraud
│   ├── channels_db.py         # Required channels management
│   ├── referral_events_db.py  # Per-channel point tracking events
│   └── fsm_db.py              # FSM conversation state (MongoDB-backed)
│
├── handlers/
│   ├── __init__.py
│   ├── start.py               # /start, force-sub check, referral link
│   ├── registration.py        # /register flow (phone → UPI)
│   ├── membership.py          # chat_member join/leave tracking
│   └── admin.py               # Admin panel commands
│
├── middlewares/
│   ├── __init__.py
│   └── middleware.py          # AntiSpam + UserUpdate middlewares
│
└── utils/
    ├── __init__.py
    ├── helpers.py             # Channel check, validation, formatting
    ├── rate_limiter.py        # Rate limiting + abuse detection
    ├── points.py              # Point calculation formulas
    └── logger.py              # Logging setup
```

---

## 🗄️ Database Collections

| Collection | Purpose |
|-----------|---------|
| `users` | All user data: profile, registration, stats, fraud flags |
| `channels` | Required channels configuration |
| `referral_events` | Per (referee, channel) tracking for precise points |
| `fsm_states` | Conversation states with TTL auto-expiry |
| `rate_limits` | Per-user rate limit events (TTL: 1 hour) |

---

## 📞 Support

- Open an issue on GitHub
- Check logs: `sudo journalctl -u referral-bot -f`
- MongoDB issues: verify `DATABASE_URI` and network access rules
- Channel issues: ensure bot is admin with "Invite Users" permission
