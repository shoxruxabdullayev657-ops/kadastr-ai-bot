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

# Kunlik tarif: 1 ta bepul savoldan keyin 2 000 so'mga 10 ta qo'shimcha savol
DAILY_PACK_PRICE_UZS = int(os.getenv("DAILY_PACK_PRICE_UZS", "2000"))
DAILY_PACK_QUESTIONS = int(os.getenv("DAILY_PACK_QUESTIONS", "10"))

# Sizning Telegram user ID'ingiz. /myid orqali bilib olishingiz mumkin.
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0") or "0")

# To'lov uchun ko'rsatma. Masalan karta raqami yoki Click/Payme havolasi.
PAYMENT_INSTRUCTIONS = os.getenv(
    "PAYMENT_INSTRUCTIONS",
    "To'lov uchun administrator bilan bog'laning. Kunlik 10 ta qo'shimcha savol: 2 000 so'm."
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

SYSTEM_PROMPT = r"""
Siz “Kadastr AI” (@Kadastryordamchibot) nomli virtual yordamchisiz.
Asosiy vazifangiz — O‘zbekiston Respublikasi fuqarolariga kadastr, ko‘chmas mulk,
uy-joy, bino-inshoot va yer bilan bog‘liq masalalarni sodda, tushunarli va amaliy
tarzda tushuntirish.

TIL VA USLUB:
- Foydalanuvchi o‘zbek tilida yozsa, o‘zbek tilida javob bering.
- Foydalanuvchi rus tilida yozsa, rus tilida javob bering.
- O‘zbekcha javoblarda sodda, tabiiy va hurmatli uslubdan foydalaning.
- Ortiqcha rasmiyatchilik, keraksiz uzun kirish va takrorlardan qoching.
- Avval qisqa xulosa bering, keyin amaliy qadamlarni ko‘rsating.

ASOSIY YO‘NALISHLAR:
- kadastr pasporti;
- ko‘chmas mulkni davlat ro‘yxatidan o‘tkazish;
- uy-joy va kvartira kadastri;
- yer uchastkasi bilan bog‘liq masalalar;
- bino va inshootlar;
- mulk huquqini rasmiylashtirish;
- meros yoki oldi-sotdidan keyingi rasmiylashtirish;
- kadastrdagi xatolarni tuzatish;
- yo‘qolgan yoki yangilanishi kerak bo‘lgan hujjatlar;
- elektron davlat xizmatlari va rasmiy tekshiruvlar.

ANIQLASHTIRISH QOIDASI:
- Savolga to‘g‘ri javob berish uchun muhim ma’lumot yetishmasa, taxmin qilmang.
- Bir yoki ikki qisqa aniqlashtiruvchi savol bering.
- Masalan: “Gap uy, kvartira, bino yoki yer uchastkasi haqida ketyaptimi?”
- Bir vaqtning o‘zida foydalanuvchini ko‘p savol bilan charchatmang.

JAVOB FORMATI:
Kerak bo‘lganda quyidagi tuzilmani ishlating, lekin har bir bo‘limni majburan qo‘shmang:

✅ Qisqa javob:
...

📌 Nima qilish kerak:
1. ...
2. ...
3. ...

📄 Kerakli hujjatlar:
• ...
• ...

📍 Qayerga murojaat qilish:
...

🔗 Rasmiy manba:
...

MUHIM FAKTLAR VA RASMIY MANBALAR:
- Qonun, qaror, modda, davlat boji, xizmat narxi, jarima, muddat, telefon raqami,
  manzil yoki talabni hech qachon o‘zingizdan to‘qib chiqarmang.
- Bunday ma’lumotlar o‘zgarishi mumkin bo‘lsa, buni ochiq ayting.
- Web qidiruv mavjud bo‘lsa, amaldagi ma’lumotlarni tekshirish uchun birinchi navbatda
  rasmiy O‘zbekiston manbalaridan foydalaning: lex.uz, my.gov.uz, kadastr.uz va
  tegishli davlat organlarining rasmiy saytlaridan.
- Rasmiy manbada aniq javob topilmasa, “aniq tasdiqlangan ma’lumot topilmadi” deb ayting;
  taxminni fakt sifatida bermang.
- Muhim huquqiy yoki to‘lov/muddatga oid ma’lumot berganda imkon qadar rasmiy manbani
  nomi bilan ko‘rsating va mavjud bo‘lsa havolasini keltiring.

HUQUQIY CHEGARA:
- O‘zingizni davlat organi, Kadastr agentligi xodimi yoki yurist deb ko‘rsatmang.
- Murakkab nizo, sud, mulk talashuvi yoki katta huquqiy oqibatli vaziyatlarda umumiy
  yo‘l-yo‘riq bering va kerak bo‘lsa tegishli davlat organi yoki malakali yuristga
  murojaat qilishni tavsiya qiling.
- Har bir oddiy javob oxirida avtomatik ravishda “yuristga boring” deb yozmang.

MAXFIYLIK VA XAVFSIZLIK:
- Pasport seriya-raqami, JShShIR/PINFL, bank karta raqami, CVV, parol, SMS tasdiqlash
  kodi kabi maxfiy ma’lumotlarni so‘ramang.
- Foydalanuvchi bunday ma’lumot yuborsa, uni qayta takrorlamang va keyingi xabarlarda
  bunday maxfiy ma’lumotlarni yubormaslikni muloyim eslating.

ASOSIY MAQSAD:
Har bir javobdan keyin foydalanuvchi “Endi nima qilishim kerakligini tushundim” deya
olishi kerak. Javobingiz foydalanuvchiga eng aniq keyingi qadamni ko‘rsatsin.
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
💳 Keyin shu kun uchun {DAILY_PACK_QUESTIONS} ta qo‘shimcha savol: {DAILY_PACK_PRICE_UZS:,} so‘m.

Savolingizni yozing yoki menyudan tanlang.

Eslatma: Kadastr AI — axborot va yo‘l-yo‘riq beruvchi yordamchi. Muhim huquqiy, to‘lov yoki muddatga oid ma’lumotlarda rasmiy manbani ham tekshiring.""".replace(",", " ")

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
                free_used_date TEXT,
                daily_pack_date TEXT,
                daily_pack_remaining INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Eski bazani buzmasdan yangi kunlik paket ustunlarini qo‘shamiz.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "daily_pack_date" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN daily_pack_date TEXT")
        if "daily_pack_remaining" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN daily_pack_remaining INTEGER NOT NULL DEFAULT 0")

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
            """SELECT paid_credits, free_used_date, daily_pack_date, daily_pack_remaining
               FROM users WHERE user_id=?""",
            (user_id,)
        ).fetchone()
    if not row:
        return {
            "paid_credits": 0,
            "free_used_date": None,
            "daily_pack_date": None,
            "daily_pack_remaining": 0,
        }
    acc = dict(row)
    if acc.get("daily_pack_date") != today_str():
        acc["daily_pack_remaining"] = 0
    return acc

def can_ask(user_id: int):
    acc = get_account(user_id)
    free_available = acc["free_used_date"] != today_str()
    if free_available:
        return True, "free"
    if acc["daily_pack_remaining"] > 0:
        return True, "daily_pack"
    return False, "none"

def consume_question(user_id: int, mode: str):
    with db() as conn:
        if mode == "free":
            conn.execute(
                "UPDATE users SET free_used_date=? WHERE user_id=?",
                (today_str(), user_id)
            )
        elif mode == "daily_pack":
            cur = conn.execute(
                """UPDATE users
                   SET daily_pack_remaining = daily_pack_remaining - 1
                   WHERE user_id=? AND daily_pack_date=? AND daily_pack_remaining > 0""",
                (user_id, today_str())
            )
            if cur.rowcount != 1:
                raise RuntimeError("Bugungi paket savollari tugagan.")
        conn.commit()

def refund_question(user_id: int, mode: str):
    with db() as conn:
        if mode == "free":
            conn.execute(
                "UPDATE users SET free_used_date=NULL WHERE user_id=? AND free_used_date=?",
                (user_id, today_str())
            )
        elif mode == "daily_pack":
            conn.execute(
                """UPDATE users
                   SET daily_pack_remaining = daily_pack_remaining + 1
                   WHERE user_id=? AND daily_pack_date=?""",
                (user_id, today_str())
            )
        conn.commit()

def activate_daily_pack(user_id: int, note: str = "Admin tasdiqladi"):
    with db() as conn:
        conn.execute(
            """INSERT INTO users(user_id, daily_pack_date, daily_pack_remaining)
               VALUES(?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 daily_pack_date=excluded.daily_pack_date,
                 daily_pack_remaining=excluded.daily_pack_remaining""",
            (user_id, today_str(), DAILY_PACK_QUESTIONS)
        )
        conn.execute(
            """INSERT INTO transactions(user_id, credits, amount_uzs, created_at, note)
               VALUES (?, ?, ?, ?, ?)""",
            (
                user_id,
                DAILY_PACK_QUESTIONS,
                DAILY_PACK_PRICE_UZS,
                datetime.now(TZ).isoformat(),
                note,
            )
        )
        conn.commit()

def balance_text(user_id: int):
    acc = get_account(user_id)
    free_available = acc["free_used_date"] != today_str()
    return (
        f"💰 Bugungi holat:\n\n"
        f"🎁 Bepul savol: {'mavjud ✅' if free_available else 'ishlatilgan ❌'}\n"
        f"💳 Kunlik paket qoldig‘i: {acc['daily_pack_remaining']} ta\n"
        f"💵 {DAILY_PACK_QUESTIONS} ta qo‘shimcha savol: {DAILY_PACK_PRICE_UZS:,} so‘m\n"
        f"⏰ Paket faqat bugun amal qiladi."
    ).replace(",", " ")

def build_input(chat_id: int, user_text: str):
    messages = list(history[chat_id])
    messages.append({"role": "user", "content": user_text})
    return messages


def looks_like_sensitive_data(text: str) -> bool:
    """Obvious secret/payment data patterns; avoids blocking ordinary cadastral numbers."""
    import re
    lowered = text.lower()
    risky_words = (
        "cvv", "cvc", "sms kod", "sms-kod", "tasdiqlash kodi",
        "parol", "password", "karta raqami", "bank karta"
    )
    if any(word in lowered for word in risky_words):
        return bool(re.search(r"\d{3,19}", text))
    # 16-digit payment-card-like sequence, with optional spaces/dashes.
    digits = re.sub(r"\D", "", text)
    return 16 <= len(digits) <= 19 and bool(re.search(r"(?:\d[ -]?){16,19}", text))

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
        f"💳 KUNLIK PAKET\n\n"
        f"{DAILY_PACK_QUESTIONS} ta qo‘shimcha savol — {DAILY_PACK_PRICE_UZS:,} so‘m.\n"
        f"Paket faqat bugun amal qiladi.\n\n"
        f"{PAYMENT_INSTRUCTIONS}\n\n"
        f"To‘lov qilganda Telegram ID’ingizni ko‘rsating:\n"
        f"`{update.effective_user.id}`\n\n"
        f"To‘lov tasdiqlangach, bugungi {DAILY_PACK_QUESTIONS} ta savol paketingiz faollashadi."
    ).replace(",", " ")
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=MENU)

async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_TELEGRAM_ID or update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("Bu buyruq faqat administrator uchun.")
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "Format: /activate USER_ID\nMasalan: /activate 123456789"
        )
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("USER_ID ni to‘g‘ri kiriting.")
        return

    activate_daily_pack(user_id)
    await update.message.reply_text(
        f"✅ {user_id} foydalanuvchiga bugun uchun "
        f"{DAILY_PACK_QUESTIONS} ta savol paketi faollashtirildi "
        f"({DAILY_PACK_PRICE_UZS:,} so‘m).".replace(",", " ")
    )
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ To‘lov tasdiqlandi!\n\n"
                f"Bugun uchun {DAILY_PACK_QUESTIONS} ta qo‘shimcha savol ochildi.\n"
                f"Paket bugun soat 23:59 gacha amal qiladi."
            ),
            reply_markup=MENU,
        )
    except Exception:
        pass

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history[update.effective_chat.id].clear()
    await update.message.reply_text("Suhbat tarixi tozalandi ✅", reply_markup=MENU)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Har kuni 1 ta savol bepul. Keyin bugun uchun {DAILY_PACK_QUESTIONS} ta savol — "
        f"{DAILY_PACK_PRICE_UZS:,} so‘m.\n\n"
        "/balance — bugungi qoldiq\n"
        "/buy — kunlik paket sotib olish\n"
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

    if looks_like_sensitive_data(mapped):
        await update.message.reply_text(
            "🔐 Xavfsizlik uchun karta raqami, CVV, parol yoki SMS kod kabi maxfiy "
            "ma’lumotlarni botga yubormang. Savolingizni maxfiy raqamlarsiz qayta yozing.",
            reply_markup=MENU,
        )
        return

    allowed, mode = can_ask(user_id)
    if not allowed:
        await update.message.reply_text(
            f"🎁 Bugungi bepul savolingiz ishlatildi.\n\n"
            f"💳 Bugun uchun {DAILY_PACK_QUESTIONS} ta qo‘shimcha savol — "
            f"{DAILY_PACK_PRICE_UZS:,} so‘m.\n"
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
        remaining = get_account(user_id)["daily_pack_remaining"]
        suffix = (
            "\n\n🎁 Bu bugungi bepul savolingiz edi."
            if mode == "free"
            else f"\n\n💳 Kunlik paketdan 1 ta savol ishlatildi. Bugungi qoldiq: {remaining} ta."
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
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    logger.info("Kadastr AI bot ishga tushdi.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
