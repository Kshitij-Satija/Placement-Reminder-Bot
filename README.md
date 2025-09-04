# Placement Reminder Bot

A Telegram bot for sending scheduled reminders, managing admins, broadcasting messages, and handling requests. Built with Python, MongoDB, and APScheduler.

---

## Features

- ✅ Set reminders for the channel
- ✅ Multi-level admin management (superadmin & admins)
- ✅ Pending approval system for reminder deletions
- ✅ Broadcast messages to a channel
- ✅ Spam protection and user blocking
- ✅ Auto-ping self to stay awake on Render
- ✅ `/ping` command for testing uptime

---

## Requirements

- Python 3.9+
- MongoDB instance
- Telegram Bot Token
- Render deployment URL (for uptime ping)

---

## Environment Variables

| Variable         | Description                                         |
|-----------------|-----------------------------------------------------|
| `BOT_TOKEN`      | Telegram bot token                                   |
| `CHANNEL_ID`     | Telegram channel username or ID                     |
| `SUPERADMIN_ID`  | Telegram user ID of superadmin                      |
| `MONGO_URI`      | MongoDB connection string                           |
| `DB_NAME`        | (Optional) MongoDB database name (default: placementreminderbot) |
| `RENDER_URL`     | Your bot's Render deployment URL                    |

---

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Kshitij-Satija/placement-reminder-bot.git
cd placement-reminder-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Set environment variables.

4. Run the bot:

```bash
python bot.py
```

## Commands

### User Commands

/start - Start the bot

/ping - Test bot uptime

/remind YYYY-MM-DD HH:MM message - Set a reminder

/listreminders - List all reminders

### Admin Commands

/deletereminder <id> - Request or delete a reminder

/approve <id> - Approve deletion request (superadmin only)

/reject <id> - Reject deletion request (superadmin only)

/broadcast <message> - Broadcast message to channel (superadmin only)

### Superadmin Commands

/addadmin <user_id> - Add new admin

/removeadmin <user_id> - Remove an admin

/listadmins - List all admins

/unblock <user_id> - Unblock a user

/listblocked - List blocked users

## Deployment

Works on any server supporting Python 3.9+.

Recommended: Deploy on Render or similar to use the auto-ping functionality.