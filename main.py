import os
import sqlite3
import logging
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID_RAW = os.getenv("OWNER_ID", "").strip()
OWNER_ID = int(OWNER_ID_RAW) if OWNER_ID_RAW.isdigit() else None
DB_PATH = os.getenv("DB_PATH", "products.db")
TZ = ZoneInfo("Asia/Tashkent")
NAME, QUANTITY, EXPIRY, NOTE = range(4)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

MENU = ReplyKeyboardMarkup(
    [
        ["➕ Tovar qo‘shish", "📋 Barcha tovarlar"],
        ["🔍 Tovar qidirish", "⏳ 3 kun qolganlar"],
        ["❌ Muddati o‘tganlar", "📊 Hisobot"],
        ["🗑 Tovarni o‘chirish", "ℹ️ Yordam"],
    ],
    resize_keyboard=True,
)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                quantity TEXT NOT NULL,
                expiry TEXT NOT NULL,
                note TEXT DEFAULT '',
                notified_for TEXT DEFAULT ''
            )
        """)

def is_owner(update: Update) -> bool:
    return OWNER_ID is not None and update.effective_user and update.effective_user.id == OWNER_ID

async def deny(update: Update):
    await update.effective_message.reply_text(
        "Bot hali egasiga sozlanmagan yoki bu akkauntga ruxsat berilmagan."
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if OWNER_ID is None:
        await update.message.reply_text(
            f"Bot ishga tushdi. Sizning Telegram ID raqamingiz: {uid}\n\n"
            "Endi Render sozlamalarida OWNER_ID nomli Environment Variable yarating "
            "va qiymatiga shu ID raqamini kiriting. So‘ng servisni qayta ishga tushiring."
        )
        return
    if not is_owner(update):
        await deny(update)
        return
    await update.message.reply_text(
        "Assalomu alaykum! Srok nazorati botiga xush kelibsiz.\n"
        "Tovarlarni qo‘lda kiriting. Yaroqlilik muddati tugashiga 3 kun qolganda xabar beraman.",
        reply_markup=MENU,
    )

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Telegram ID: {update.effective_user.id}")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await deny(update); return
    await update.message.reply_text(
        "Tovar qo‘shish: nomi → miqdori → sana (YYYY-MM-DD) → izoh.\n"
        "Sana misoli: 2026-12-31\n"
        "Tovarni o‘chirish uchun /delete ID buyrug‘idan foydalaning."
    )

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await deny(update); return ConversationHandler.END
    await update.message.reply_text("Tovar nomini yozing:", reply_markup=ReplyKeyboardRemove())
    return NAME

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Tovar miqdorini yozing (masalan: 12 dona):")
    return QUANTITY

async def add_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["quantity"] = update.message.text.strip()
    await update.message.reply_text("Yaroqlilik muddatini kiriting: YYYY-MM-DD\nMasalan: 2026-12-31")
    return EXPIRY

async def add_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        await update.message.reply_text("Sana noto‘g‘ri. YYYY-MM-DD shaklida kiriting. Masalan: 2026-12-31")
        return EXPIRY
    context.user_data["expiry"] = parsed.isoformat()
    await update.message.reply_text("Izoh yozing yoki izoh bo‘lmasa — nuqta (.) yuboring:")
    return NOTE

async def add_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = update.message.text.strip()
    if note == ".":
        note = ""
    d = context.user_data
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO products(name, quantity, expiry, note) VALUES (?, ?, ?, ?)",
            (d["name"], d["quantity"], d["expiry"], note),
        )
        pid = cur.lastrowid
    await update.message.reply_text(
        f"✅ Tovar saqlandi!\nID: {pid}\n📦 {d['name']}\n"
        f"🔢 Miqdori: {d['quantity']}\n📅 Muddati: {d['expiry']}\n"
        f"📝 Izoh: {note or '—'}",
        reply_markup=MENU,
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Amal bekor qilindi.", reply_markup=MENU)
    return ConversationHandler.END

def format_product(row):
    return (
        f"🆔 ID: {row['id']}\n📦 {row['name']}\n🔢 Miqdori: {row['quantity']}\n"
        f"📅 Muddati: {row['expiry']}\n📝 Izoh: {row['note'] or '—'}"
    )

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await deny(update); return
    with db() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY expiry, name").fetchall()
    if not rows:
        await update.message.reply_text("Hozircha tovarlar yo‘q.", reply_markup=MENU); return
    text = "\n\n".join(format_product(r) for r in rows)
    await update.message.reply_text(text[:4000], reply_markup=MENU)

async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await deny(update); return
    await update.message.reply_text("Qidiriladigan tovar nomini yozing:", reply_markup=ReplyKeyboardRemove())
    return NAME

async def search_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await deny(update); return ConversationHandler.END
    q = update.message.text.strip()
    with db() as conn:
        rows = conn.execute("SELECT * FROM products WHERE name LIKE ? ORDER BY expiry", (f"%{q}%",)).fetchall()
    if rows:
        await update.message.reply_text("\n\n".join(format_product(r) for r in rows)[:4000], reply_markup=MENU)
    else:
        await update.message.reply_text("Bunday tovar topilmadi.", reply_markup=MENU)
    return ConversationHandler.END

async def expiring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await deny(update); return
    target = (date.today() + timedelta(days=3)).isoformat()
    with db() as conn:
        rows = conn.execute("SELECT * FROM products WHERE expiry = ? ORDER BY name", (target,)).fetchall()
    if rows:
        await update.message.reply_text("⏳ Muddati tugashiga aynan 3 kun qolgan tovarlar:\n\n" + "\n\n".join(format_product(r) for r in rows)[:3800], reply_markup=MENU)
    else:
        await update.message.reply_text("Aynan 3 kundan keyin muddati tugaydigan tovar yo‘q.", reply_markup=MENU)

async def expired(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await deny(update); return
    today = date.today().isoformat()
    with db() as conn:
        rows = conn.execute("SELECT * FROM products WHERE expiry < ? ORDER BY expiry", (today,)).fetchall()
    if rows:
        await update.message.reply_text("❌ Muddati o‘tgan tovarlar:\n\n" + "\n\n".join(format_product(r) for r in rows)[:3800], reply_markup=MENU)
    else:
        await update.message.reply_text("Muddati o‘tgan tovar yo‘q.", reply_markup=MENU)

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await deny(update); return
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=3)).isoformat()
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM products").fetchone()["n"]
        old = conn.execute("SELECT COUNT(*) n FROM products WHERE expiry < ?", (today,)).fetchone()["n"]
        near = conn.execute("SELECT COUNT(*) n FROM products WHERE expiry = ?", (soon,)).fetchone()["n"]
    await update.message.reply_text(
        f"📊 HISOBOT\n\n📦 Jami tovarlar: {total}\n⏳ 3 kun qolgan: {near}\n❌ Muddati o‘tgan: {old}",
        reply_markup=MENU,
    )

async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await deny(update); return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("O‘chirish uchun: /delete ID\nMasalan: /delete 4", reply_markup=MENU); return
    with db() as conn:
        cur = conn.execute("DELETE FROM products WHERE id = ?", (int(context.args[0]),))
    await update.message.reply_text("🗑 Tovar o‘chirildi." if cur.rowcount else "Bunday ID topilmadi.", reply_markup=MENU)

async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    if OWNER_ID is None:
        return
    target = (datetime.now(TZ).date() + timedelta(days=3)).isoformat()
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM products WHERE expiry = ? AND notified_for != ?",
            (target, target),
        ).fetchall()
        for row in rows:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text="🔔 YAROQLILIK MUDDATIGA 3 KUN QOLDI!\n\n" + format_product(row),
            )
            conn.execute("UPDATE products SET notified_for = ? WHERE id = ?", (target, row["id"]))

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable kiritilmagan.")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Tovar qo‘shish$"), add_start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_quantity)],
            EXPIRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_expiry)],
            NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_note)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    search_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 Tovar qidirish$"), search_start)],
        states={NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_result)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(add_conv)
    app.add_handler(search_conv)
    app.add_handler(MessageHandler(filters.Regex("^📋 Barcha tovarlar$"), list_products))
    app.add_handler(MessageHandler(filters.Regex("^⏳ 3 kun qolganlar$"), expiring))
    app.add_handler(MessageHandler(filters.Regex("^❌ Muddati o‘tganlar$"), expired))
    app.add_handler(MessageHandler(filters.Regex("^📊 Hisobot$"), report))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ Yordam$"), help_cmd))
    app.job_queue.run_daily(daily_reminder, time=datetime.strptime("09:00", "%H:%M").time(), name="daily_expiry_check")
    log.info("Srok bot ishga tushmoqda")
    app.run_polling()

if __name__ == "__main__":
    main()
