import os
import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict, deque

from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip()
USE_WEB_SEARCH = os.getenv("USE_WEB_SEARCH", "true").lower() in {"1", "true", "yes", "on"}

# 10 000 so'm = 1 savol
QUESTION_PRICE_UZS = int(os.getenv("QUESTION_PRICE_UZS", "10000"))

# Sizning Telegram user ID'ingiz. /myid orqali bilib olishingiz mumkin.
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0") or "0")

# To'lov uchun ko'rsatma. Masalan karta raqami yoki Click/Payme havolasi.
PAYMENT_INSTRUCTIONS = os.getenv(
    "PAYMENT_INSTRUCTIONS",
    "To'lov uchun administrator bilan bog'laning. 1 ta savol narxi: 10 000 so'm."
).strip()

TZ = ZoneInfo("Asia/Samarkand")
DB_PATH = os.getenv("DB_PATH", "kadastr_bot.db")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN topilmadi. .env faylini tekshiring.")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY topilmadi. .env faylini tekshiring.")

client = OpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("kadastr-bot")

SYSTEM_PROMPT = """
Siz O'zbekistondagi kadastr va ko'chmas mulk masalalari bo'yicha foydalanuvchiga
oddiy, tushunarli o'zbek tilida yo'l-yo'riq beradigan "Kadastr AI" yordamchisiz.

ASOSIY VAZIFALAR:
- Kadastr pasporti, davlat ro'yxatidan o'tkazish, mulk huquqi, uy-joy va yer
  hujjatlari bo'yicha umumiy tartibni tushuntiring.
- Foydalanuvchiga odatda kerak bo'lishi mumkin bo'lgan hujjatlarni sanab bering.
- Holat noaniq bo'lsa, qisqa aniqlashtiruvchi savol bering.
- Javobni qisqa, amaliy va bosqichma-bosqich yozing.
- Foydalanuvchi rus tilida yozsa, rus tilida; o'zbek tilida yozsa, o'zbek tilida javob bering.

MUHIM:
- O'zingizni davlat organi yoki rasmiy kadastr xodimi deb ko'rsatmang.
- Qonun, to'lov, muddat yoki talab o'zgarishi mumkin bo'lsa, buni ayting.
- Huquqiy nizoda qat'iy yuridik hukm bermang.
- Zarur bo'lsa Kadastr agentligi, Davlat xizmatlari markazi, my.gov.uz yoki boshqa
  amaldagi rasmiy manbani tekshirishni tavsiya qiling.
- Pasport seriyasi, PINFL, bank karta raqami, parol kabi maxfiy ma'lumotlarni so'ramang.
"""

history = defaultdict(lambda: deque(maxlen=16))

MENU = ReplyKeyboardMarkup(
    [
        ["🏠 Uy kadastri", "🌍 Yer kadastri"],
        ["📄 Kerakli hujjatlar", "🔑 Mulk huquqi"],
        ["💰 Balans", "💳 Savol sotib olish"],
        ["🧹 Suhbatni tozalash", "ℹ️ Yordam"],
    ],
    resize_keyboard=True,
)

WELCOME = f"""Assalomu alaykum! 👋

Men Kadastr AI yordamchisiman.

✅ Har kuni 1 ta savol BEPUL.
💳 Shu kundagi keyingi har bir savol: {QUESTION_PRICE_UZS:,} so'm.

Savolingizni yozing yoki menyudan tanlang.

Eslatma: javoblar ma'lumot va yo'l-yo'riq uchun. Yakuniy talablar rasmiy tartibga bog'liq bo'lishi mumkin.""".replace(",", " ")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                paid_credits INTEGER NOT NULL DEFAULT 0,
                free_used_date TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                credits INTEGER NOT NULL,
                amount_uzs INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                note TEXT
            )
        """)
        conn.commit()

def today_str():
    return datetime.now(TZ).date().isoformat()

def ensure_user(update: Update):
    u = update.effective_user
    with db() as conn:
        conn.execute(
            """INSERT INTO users(user_id, username, full_name)
               VALUES(?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username,
                 full_name=excluded.full_name""",
            (u.id, u.username or "", u.full_name or "")
        )
        conn.commit()

def get_account(user_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT paid_credits, free_used_date FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
    if not row:
        return {"paid_credits": 0, "free_used_date": None}
    return dict(row)

def can_ask(user_id: int):
    acc = get_account(user_id)
    free_available = acc["free_used_date"] != today_str()
    if free_available:
        return True, "free"
    if acc["paid_credits"] > 0:
        return True, "paid"
    return False, "none"

def consume_question(user_id: int, mode: str):
    with db() as conn:
        if mode == "free":
            conn.execute(
                "UPDATE users SET free_used_date=? WHERE user_id=?",
                (today_str(), user_id)
            )
        elif mode == "paid":
            cur = conn.execute(
                """UPDATE users
                   SET paid_credits = paid_credits - 1
                   WHERE user_id=? AND paid_credits > 0""",
                (user_id,)
            )
            if cur.rowcount != 1:
                raise RuntimeError("Balans yetarli emas.")
        conn.commit()

def refund_question(user_id: int, mode: str):
    # AI texnik xato bersa foydalanuvchining bepul/pullik haqqini qaytaramiz.
    with db() as conn:
        if mode == "free":
            conn.execute(
                "UPDATE users SET free_used_date=NULL WHERE user_id=? AND free_used_date=?",
                (user_id, today_str())
            )
        elif mode == "paid":
            conn.execute(
                "UPDATE users SET paid_credits = paid_credits + 1 WHERE user_id=?",
                (user_id,)
            )
        conn.commit()

def add_credits(user_id: int, credits: int, note: str = "Admin tasdiqladi"):
    amount = credits * QUESTION_PRICE_UZS
    with db() as conn:
        conn.execute(
            """INSERT INTO users(user_id, paid_credits)
               VALUES(?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 paid_credits = paid_credits + excluded.paid_credits""",
            (user_id, credits)
        )
        conn.execute(
            """INSERT INTO transactions(user_id, credits, amount_uzs, created_at, note)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, credits, amount, datetime.now(TZ).isoformat(), note)
        )
        conn.commit()

def balance_text(user_id: int):
    acc = get_account(user_id)
    free_available = acc["free_used_date"] != today_str()
    return (
        f"💰 Balansingiz:\n\n"
        f"🎁 Bugungi bepul savol: {'mavjud ✅' if free_available else 'ishlatilgan ❌'}\n"
        f"💳 Pullik savollar: {acc['paid_credits']} ta\n"
        f"💵 1 ta qo‘shimcha savol: {QUESTION_PRICE_UZS:,} so‘m"
    ).replace(",", " ")

def build_input(chat_id: int, user_text: str):
    messages = list(history[chat_id])
    messages.append({"role": "user", "content": user_text})
    return messages

def ask_openai(chat_id: int, user_text: str) -> str:
    kwargs = {
        "model": OPENAI_MODEL,
        "instructions": SYSTEM_PROMPT,
        "input": build_input(chat_id, user_text),
        "store": False,
    }
    if USE_WEB_SEARCH:
        kwargs["tools"] = [{"type": "web_search"}]

    response = client.responses.create(**kwargs)
    answer = (response.output_text or "").strip()
    if not answer:
        raise RuntimeError("AI bo'sh javob qaytardi.")

    history[chat_id].append({"role": "user", "content": user_text})
    history[chat_id].append({"role": "assistant", "content": answer})
    return answer

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update)
    await update.message.reply_text(WELCOME, reply_markup=MENU)

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update)
    await update.message.reply_text(f"Sizning Telegram ID: `{update.effective_user.id}`", parse_mode="Markdown")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update)
    await update.message.reply_text(balance_text(update.effective_user.id), reply_markup=MENU)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update)
    text = (
        f"💳 1 ta qo‘shimcha savol — {QUESTION_PRICE_UZS:,} so‘m.\n\n"
        f"{PAYMENT_INSTRUCTIONS}\n\n"
        f"To‘lov qilganda Telegram ID’ingizni ko‘rsating:\n"
        f"`{update.effective_user.id}`\n\n"
        f"To‘lov tasdiqlangach, balansingizga savol qo‘shiladi."
    ).replace(",", " ")
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=MENU)

async def addcredit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_TELEGRAM_ID or update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("Bu buyruq faqat administrator uchun.")
        return

    if len(context.args) != 2:
        await update.message.reply_text("Format: /addcredit USER_ID SAVOL_SONI\nMasalan: /addcredit 123456789 1")
        return

    try:
        user_id = int(context.args[0])
        credits = int(context.args[1])
        if credits <= 0 or credits > 1000:
            raise ValueError
    except ValueError:
        await update.message.reply_text("USER_ID va savol sonini to‘g‘ri kiriting.")
        return

    add_credits(user_id, credits)
    amount = credits * QUESTION_PRICE_UZS
    await update.message.reply_text(
        f"✅ {user_id} foydalanuvchiga {credits} ta savol qo‘shildi "
        f"({amount:,} so‘m).".replace(",", " ")
    )
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ To‘lov tasdiqlandi. Balansingizga {credits} ta pullik savol qo‘shildi.",
            reply_markup=MENU,
        )
    except Exception:
        pass

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history[update.effective_chat.id].clear()
    await update.message.reply_text("Suhbat tarixi tozalandi ✅", reply_markup=MENU)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Har kuni 1 ta savol bepul. Keyingi savollar {QUESTION_PRICE_UZS:,} so‘mdan.\n\n"
        "/balance — balans\n"
        "/buy — savol sotib olish\n"
        "/myid — Telegram ID\n"
        "/clear — suhbatni tozalash".replace(",", " "),
        reply_markup=MENU,
    )

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    ensure_user(update)
    text = update.message.text.strip()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    quick_map = {
        "🏠 Uy kadastri": "Uyga kadastr pasporti olish tartibini va odatda kerak bo'ladigan hujjatlarni tushuntiring.",
        "🌍 Yer kadastri": "Yer uchastkasi kadastri bo'yicha umumiy tartib va kerakli hujjatlarni tushuntiring.",
        "📄 Kerakli hujjatlar": "Uy yoki yer kadastrini rasmiylashtirishda odatda qanday hujjatlar kerak bo'lishini tushuntiring.",
        "🔑 Mulk huquqi": "Ko'chmas mulkka egalik/mulk huquqini davlat ro'yxatidan o'tkazish tartibini tushuntiring.",
        "💰 Balans": "__BALANCE__",
        "💳 Savol sotib olish": "__BUY__",
        "🧹 Suhbatni tozalash": "__CLEAR__",
        "ℹ️ Yordam": "__HELP__",
    }

    mapped = quick_map.get(text, text)

    if mapped == "__BALANCE__":
        await balance(update, context)
        return
    if mapped == "__BUY__":
        await buy(update, context)
        return
    if mapped == "__CLEAR__":
        await clear_command(update, context)
        return
    if mapped == "__HELP__":
        await help_command(update, context)
        return

    allowed, mode = can_ask(user_id)
    if not allowed:
        await update.message.reply_text(
            f"🎁 Bugungi bepul savolingiz ishlatildi.\n\n"
            f"Keyingi har bir savol — {QUESTION_PRICE_UZS:,} so‘m.\n"
            f"To‘lov qilish uchun «💳 Savol sotib olish» tugmasini bosing.".replace(",", " "),
            reply_markup=MENU,
        )
        return

    # Savolni AI'ga yuborishdan oldin haqqini band qilamiz.
    consume_question(user_id, mode)
    await update.message.chat.send_action("typing")

    try:
        import asyncio
        answer = await asyncio.to_thread(ask_openai, chat_id, mapped)
        remaining = get_account(user_id)["paid_credits"]
        suffix = (
            "\n\n🎁 Bu bugungi bepul savolingiz edi."
            if mode == "free"
            else f"\n\n💳 1 ta pullik savol ishlatildi. Qoldi: {remaining} ta."
        )
        answer += suffix

        for i in range(0, len(answer), 3900):
            await update.message.reply_text(
                answer[i:i + 3900],
                reply_markup=MENU if i == 0 else None
            )
    except Exception as exc:
        logger.exception("AI javobida xato: %s", exc)
        refund_question(user_id, mode)
        await update.message.reply_text(
            "Texnik xatolik bo‘ldi. Savol haqqingiz qaytarildi, qayta urinib ko‘ring.",
            reply_markup=MENU,
        )

def main():
    init_db()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("addcredit", addcredit))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    logger.info("Kadastr AI bot ishga tushdi.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
