# Kadastr AI — pullik savol-javob

## Tarif
- Har foydalanuvchiga har kalendar kuni 1 ta savol bepul.
- O'sha kundagi 2-savoldan boshlab har bir savol 10 000 so'm.
- Pullik savollar kredit sifatida balansda saqlanadi.
- Ma'lumot SQLite bazasida saqlanadi, bot qayta ishga tushsa ham balans yo'qolmaydi.

## Hozirgi to'lov oqimi
Bu versiyada to'lov tasdiqlashi administrator orqali ishlaydi:

1. Mijoz `/buy` yoki `💳 Savol sotib olish`ni bosadi.
2. Bot PAYMENT_INSTRUCTIONS matnini va foydalanuvchining Telegram ID'sini ko'rsatadi.
3. Siz to'lovni tekshirasiz.
4. Admin sifatida:
   `/addcredit USER_ID 1`
5. Mijoz balansiga 1 ta pullik savol tushadi.

Misol:
`/addcredit 123456789 3`
— 3 ta savol, jami 30 000 so'm.

## Admin ID
Botga o'z akkauntingizdan `/myid` yuboring. Chiqqan raqamni `.env` ichidagi:
`ADMIN_TELEGRAM_ID=...`
qatoriga yozing.

## Ishga tushirish
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

## Muhim
Telegram ichidagi raqamli xizmatlarni Telegram Payments orqali avtomatik sotishda Telegram Stars (XTR) talabi mavjud. Shu sabab bu versiya 10 000 so'm narxni aniq saqlash uchun admin tasdiqlaydigan balans tizimidan foydalanadi.

Keyingi versiyada:
- Telegram Stars
- tashqi Click/Payme integratsiyasi (platforma qoidalariga mos holda)
- to'lov webhook'i
- admin panel
- statistika
qo'shish mumkin.
