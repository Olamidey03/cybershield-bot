# CyberShield Assistant Bot

A cybersecurity learning and assessment bot for Telegram, built with `python-telegram-bot`.

## Modules

| # | Module | Status | Description |
|---|--------|--------|-------------|
| 1 | Risk Assessment | ✅ Active | 9-question security posture evaluation with scoring |
| 2 | Password Analyzer | ✅ Active | Strength scoring, composition checks, pattern detection |
| 3 | Network Port Scanner | 🔒 Locked | Socket-based IP/port scanning (unlock via networking module) |
| 4 | Log Analysis Tool | 🔒 Locked | SIEM-style log pattern detection (unlock via SIEM module) |

## Setup

### Step 1: Get your Bot Token

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the token it gives you (format: `123456789:ABCdef...`)

### Step 2: Set the BOT_TOKEN

**On Replit (recommended):**
- Click the 🔒 **Secrets** tab in the left sidebar
- Add a secret: Key = `BOT_TOKEN`, Value = your token

**Locally:**
```bash
cp .env.example .env
# Edit .env and paste your token
```

### Step 3: Run the bot

```bash
cd cybershield
python bot.py
```

## Project Structure

```
cybershield/
├── bot.py                  # Main entry point, menu, and handler registration
├── .env.example            # Token setup instructions
├── README.md               # This file
└── modules/
    ├── __init__.py
    ├── risk_assessment.py  # Module 1 — risk scoring conversation
    ├── password_checker.py # Module 2 — password analysis
    └── locked.py           # Modules 3 & 4 — locked placeholders
```

## Adding More Questions (Module 1)

Open `modules/risk_assessment.py` and add to the `QUESTIONS` list:

```python
QUESTIONS = [
    ("Is a firewall enabled on all systems?", 15),
    ("Your new question here?", 10),   # <-- add here
    ...
]
```

Each entry is `(question_text, risk_points_if_no)`.
