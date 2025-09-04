import logging
import time
from datetime import datetime, timedelta
from collections import defaultdict
import os
import aiohttp
from pymongo import MongoClient
from bson import ObjectId
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)
from zoneinfo import ZoneInfo  # Python 3.9+
from dotenv import load_dotenv
# Load .env file
load_dotenv()  # This will load the variables from .env into os.environ

# Required environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
SUPERADMIN_ID = int(os.environ.get("SUPERADMIN_ID", 0))
MONGO_URI = os.environ.get("MONGO_URI")
DB_NAME = os.environ.get("DB_NAME", "placementreminderbot")
RENDER_URL = os.environ.get("RENDER_URL")

# Ensure all required variables are set
missing_vars = [var for var in ["BOT_TOKEN", "CHANNEL_ID", "SUPERADMIN_ID", "MONGO_URI", "RENDER_URL"] if not os.environ.get(var)]
if missing_vars:
    raise ValueError(f"❌ Missing required environment variables: {', '.join(missing_vars)}")

print("✅ All environment variables loaded successfully!")
# --- Setup ---
logging.basicConfig(level=logging.INFO)
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
admins = db["admins"]
reminders = db["reminders"]
blocked = db["blocked_users"]
pending_deletes = db["pending_deletes"]

scheduler = AsyncIOScheduler()
scheduler.start()

# --- Ensure superadmin exists ---
if not admins.find_one({"role": "superadmin"}):
    admins.insert_one({"user_id": SUPERADMIN_ID, "role": "superadmin"})
    logging.info("✅ Superadmin inserted into DB")

# --- Helpers ---
def is_superadmin(user_id: int) -> bool:
    return admins.find_one({"user_id": user_id, "role": "superadmin"}) is not None

def is_admin_or_superadmin(user_id: int) -> bool:
    return admins.find_one({"user_id": user_id}) is not None

def format_user(user) -> str:
    if user.username:
        return f"@{user.username}"
    return str(user.id)

async def send_reminder(context: ContextTypes.DEFAULT_TYPE, message: str):
    await context.bot.send_message(chat_id=CHANNEL_ID, text=message)

# --- Spam Protection ---
user_requests = defaultdict(list)
REQUEST_LIMIT = 5
TIME_WINDOW = 10

def is_blocked(user_id: int) -> bool:
    return blocked.find_one({"user_id": user_id}) is not None

def block_user(user_id: int, reason="Spam detected"):
    blocked.update_one(
        {"user_id": user_id},
        {"$set": {"reason": reason, "blocked_at": time.time()}},
        upsert=True
    )

def unblock_user(user_id: int):
    blocked.delete_one({"user_id": user_id})

def rate_limit(user_id: int) -> bool:
    now = time.time()
    user_requests[user_id] = [t for t in user_requests[user_id] if now - t < TIME_WINDOW]
    user_requests[user_id].append(now)
    if len(user_requests[user_id]) > REQUEST_LIMIT:
        block_user(user_id)
        return False
    return True

async def check_spam(update: Update) -> bool:
    user_id = update.effective_user.id
    if is_admin_or_superadmin(user_id):
        return True
    if is_blocked(user_id):
        await update.message.reply_text("⛔ You are blocked. Contact the superadmin to be unblocked.")
        return False
    if not rate_limit(user_id):
        await update.message.reply_text("⛔ You have been blocked for spamming. Contact the superadmin.")
        return False
    return True

# --- Reminder helpers ---
def _get_intervals():
    return [
        (timedelta(hours=2), "⏰ Reminder in 2 hours:"),
        (timedelta(hours=1), "⏰ Reminder in 1 hour:"),
        (timedelta(minutes=30), "⏰ Reminder in 30 minutes:"),
        (timedelta(minutes=15), "⏰ Reminder in 15 minutes:"),
        (timedelta(), "🔔 It's time!"),
    ]

def schedule_reminder_jobs(context: ContextTypes.DEFAULT_TYPE, reminder_id: str, reminder_time: datetime, message: str):
    now = datetime.now()
    for i, (offset, prefix) in enumerate(_get_intervals()):
        run_time = reminder_time - offset
        if run_time > now:
            job_id = f"{reminder_id}_{i}"
            try:
                scheduler.remove_job(job_id)
            except Exception:
                pass
            scheduler.add_job(
                send_reminder,
                "date",
                run_date=run_time,
                args=[context, f"{prefix} {message}"],
                id=job_id
            )

def remove_reminder_jobs(reminder_id: str):
    for job in scheduler.get_jobs():
        if job.id.startswith(f"{reminder_id}_"):
            try:
                scheduler.remove_job(job.id)
            except Exception:
                pass

# --- Cron job to ping Render URL ---
async def ping_self():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(RENDER_URL) as resp:
                logging.info(f"🌐 Pinged {RENDER_URL}, status: {resp.status}")
    except Exception as e:
        logging.error(f"❌ Failed to ping {RENDER_URL}: {e}")

scheduler.add_job(ping_self, "interval", minutes=2, id="ping_self_job")
logging.info("⏱ Scheduled cron job to ping bot URL every 2 minutes.")

# --- Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam(update): return
    await update.message.reply_text("👋 Hi! I'm your reminder bot.\nUse /remind to set reminders.\nPing me with /ping to test uptime.")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")

# --- Include all your previous commands here ---

# --- Admin Management ---
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam(update): return
    if not is_superadmin(update.effective_user.id):
        return await update.message.reply_text("❌ Only superadmin can add admins.")
    try:
        user_id = int(context.args[0])
        if not admins.find_one({"user_id": user_id}):
            admins.insert_one({"user_id": user_id, "role": "admin"})
            await update.message.reply_text(f"✅ Added {user_id} as admin.")
        else:
            await update.message.reply_text("⚠️ That user is already an admin.")
    except Exception as e:
        await update.message.reply_text(f"Usage: /addadmin <user_id>\nError: {e}")

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam(update): return
    if not is_superadmin(update.effective_user.id):
        return await update.message.reply_text("❌ Only superadmin can remove admins.")
    try:
        user_id = int(context.args[0])
        result = admins.delete_one({"user_id": user_id, "role": "admin"})
        if result.deleted_count > 0:
            await update.message.reply_text(f"✅ Removed {user_id} from admins.")
        else:
            await update.message.reply_text("⚠️ User is not an admin.")
    except Exception as e:
        await update.message.reply_text(f"Usage: /removeadmin <user_id>\nError: {e}")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam(update): return
    if not is_superadmin(update.effective_user.id):
        return await update.message.reply_text("❌ Only superadmin can list admins.")
    all_admins = [f"{a['user_id']} ({a['role']})" for a in admins.find()]
    await update.message.reply_text("👮 Admins:\n" + "\n".join(all_admins))

# --- Blocking ---
async def unblock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam(update): return
    if not is_superadmin(update.effective_user.id):
        return await update.message.reply_text("❌ Only superadmin can unblock users.")
    try:
        user_id = int(context.args[0])
        if is_blocked(user_id):
            unblock_user(user_id)
            await update.message.reply_text(f"✅ User {user_id} has been unblocked.")
        else:
            await update.message.reply_text("⚠️ That user is not blocked.")
    except Exception as e:
        await update.message.reply_text(f"Usage: /unblock <user_id>\nError: {e}")

async def list_blocked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam(update): return
    if not is_superadmin(update.effective_user.id):
        return await update.message.reply_text("❌ Only superadmin can list blocked users.")
    users = blocked.find()
    if users.count() == 0:
        return await update.message.reply_text("✅ No users are currently blocked.")
    lines = []
    for u in users:
        blocked_time = datetime.fromtimestamp(u.get("blocked_at", 0)).strftime("%Y-%m-%d %H:%M:%S")
        reason = u.get("reason", "No reason")
        lines.append(f"🚫 {u['user_id']} | Reason: {reason} | Blocked at: {blocked_time}")
    await update.message.reply_text("🔒 Blocked Users:\n" + "\n".join(lines))

# --- Broadcasting ---
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam(update): return
    if not is_superadmin(update.effective_user.id):
        return await update.message.reply_text("❌ Only superadmin can broadcast messages.")
    message = " ".join(context.args)
    if not message:
        return await update.message.reply_text("⚠️ Usage: /broadcast <message>")
    await context.bot.send_message(chat_id=CHANNEL_ID, text=f"📢 {message}")
    await update.message.reply_text("✅ Message broadcasted to the channel.")

# --- Reminder management ---
async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam(update): return
    if not is_admin_or_superadmin(update.effective_user.id):
        return await update.message.reply_text("❌ You are not an admin.")
    try:
        dt_str = context.args[0] + " " + context.args[1]
        naive_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        reminder_time = naive_time.replace(tzinfo=ZoneInfo("Asia/Kolkata"))  # input is IST
        server_time = reminder_time.astimezone()  # convert to server local time for scheduler

        message = " ".join(context.args[2:])
        if not message:
            return await update.message.reply_text("⚠️ Reminder message cannot be empty.")
        user_fmt = format_user(update.effective_user)
        res = reminders.insert_one({
            "time": server_time,
            "message": message,
            "created_by": update.effective_user.id,
            "creator_name": user_fmt,
            "created_at": datetime.utcnow()
        })
        rid = str(res.inserted_id)
        schedule_reminder_jobs(context, rid, server_time, message)

        ist_str = reminder_time.strftime('%Y-%m-%d %H:%M IST')
        await update.message.reply_text(
            f"✅ Reminder set (ID: `{rid}`)\n⏰ {ist_str}\n📌 {message}\n👤 Created by {user_fmt}",
            parse_mode="Markdown"
        )
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📌 New reminder!\n🆔 `{rid}`\n⏰ {ist_str}\n📌 {message}\n👤 {user_fmt}",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"Usage: /remind YYYY-MM-DD HH:MM message\nError: {e}")

async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam(update): return
    docs = reminders.find().sort("time", 1)
    lines = []
    for r in docs:
        rid = str(r["_id"])
        ist_time_str = r['time'].astimezone(ZoneInfo('Asia/Kolkata')).strftime("%Y-%m-%d %H:%M IST")
        lines.append(
            f"🆔 `{rid}`\n⏰ {ist_time_str}\n📌 {r['message']}\n👤 {r.get('creator_name','unknown')}\n---"
        )
    await update.message.reply_text("\n".join(lines)[:3900], parse_mode="Markdown" if lines else "📭 No reminders set.")

# --- Remaining delete/approve/reject commands ---

async def delete_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam(update): return
    try:
        rid = context.args[0]
        reminder = reminders.find_one({"_id": ObjectId(rid)})
        if not reminder:
            return await update.message.reply_text("❌ Reminder not found.")
        user_id = update.effective_user.id
        if is_superadmin(user_id):
            reminders.delete_one({"_id": ObjectId(rid)})
            remove_reminder_jobs(rid)
            await update.message.reply_text(f"✅ Reminder {rid} deleted.")
        elif is_admin_or_superadmin(user_id):
            pending_deletes.update_one(
                {"rid": rid},
                {"$set": {"requested_by": user_id, "requested_at": time.time()}},
                upsert=True
            )
            await update.message.reply_text("⌛ Deletion request sent to superadmin.")
            await context.bot.send_message(
                chat_id=SUPERADMIN_ID,
                text=f"⚠️ Admin {user_id} requested deletion of reminder `{rid}`.\nUse /approve {rid} or /reject {rid}.",
                parse_mode="Markdown"
            )
    except Exception as e:
        await update.message.reply_text(f"Usage: /deletereminder <id>\nError: {e}")

async def approve_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam(update): return
    if not is_superadmin(update.effective_user.id):
        return
    rid = context.args[0]
    req = pending_deletes.find_one({"rid": rid})
    if not req:
        return await update.message.reply_text("❌ No pending request.")
    reminders.delete_one({"_id": ObjectId(rid)})
    remove_reminder_jobs(rid)
    requester = req["requested_by"]
    pending_deletes.delete_one({"rid": rid})
    await update.message.reply_text(f"✅ Reminder {rid} deleted after approval.")
    await context.bot.send_message(requester, f"✅ Your deletion request for {rid} was approved.")

async def reject_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam(update): return
    if not is_superadmin(update.effective_user.id):
        return
    rid = context.args[0]
    req = pending_deletes.find_one({"rid": rid})
    if not req:
        return await update.message.reply_text("❌ No pending request.")
    requester = req["requested_by"]
    pending_deletes.delete_one({"rid": rid})
    await update.message.reply_text(f"🚫 Deletion of {rid} rejected.")
    await context.bot.send_message(requester, f"🚫 Your deletion request for {rid} was rejected.")

# --- Reload reminders on startup ---
async def reload_reminders(app):
    now = datetime.now()
    for r in reminders.find({"time": {"$gte": now}}):
        rid = str(r["_id"])
        schedule_reminder_jobs(app, rid, r["time"], r["message"])
    logging.info("♻️ Reloaded all pending reminders into scheduler.")

# --- Main ---
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # --- Commands ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("remind", remind))
    app.add_handler(CommandHandler("listreminders", list_reminders))
    app.add_handler(CommandHandler("deletereminder", delete_reminder))
    app.add_handler(CommandHandler("approve", approve_delete))
    app.add_handler(CommandHandler("reject", reject_delete))
    app.add_handler(CommandHandler("addadmin", add_admin))
    app.add_handler(CommandHandler("removeadmin", remove_admin))
    app.add_handler(CommandHandler("listadmins", list_admins))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("unblock", unblock_cmd))
    app.add_handler(CommandHandler("listblocked", list_blocked))


    # --- Auto-reload reminders ---
    app.post_init = reload_reminders

    logging.info("🤖 Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
