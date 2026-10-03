# 🎬 Kino Bot

Telegram kino boti — foydalanuvchilar kod orqali kino topishi, qidirishi, sevimlilarga qo'shishi mumkin.

## ⚙️ O'rnatish

### 1. `.env` faylini to'ldiring

```env
BOT_TOKEN=your_bot_token_here
ADMIN_IDS=your_telegram_id

# Obuna tekshiruvi uchun kanallar (@ belgisi bilan)
KINO_CHANNEL=@kanalingiz_username
EDU_CHANNEL=@ikkinchi_kanal

# Railway / Supabase / boshqa PostgreSQL URL
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

### 2. Kutubxonalarni o'rnating

```bash
pip install -r requirements.txt
```

### 3. Botni ishga tushiring

```bash
python bot.py
```

---

## 🚀 Railway ga deploy qilish

1. Railway.app da yangi loyiha oching
2. GitHub reponi ulang yoki fayllarni yuklang
3. **Environment Variables** bo'limida yuqoridagi `.env` qiymatlarini kiriting
4. Railway avtomatik `Procfile` yoki `nixpacks.toml` orqali ishga tushiradi

---

## 📋 Buyruqlar

### Foydalanuvchilar uchun
| Buyruq | Tavsif |
|---|---|
| `/start` | Botni boshlash |
| `/help` | Yordam |
| `/search` | Kino qidirish |
| `/categories` | Kategoriyalar va janrlar |
| `/favorites` | Sevimlilar ro'yxati |
| `/top` | Eng ko'p ko'rilganlar |
| `/stats` | Statistika |
| `1267` | Kod yuboring → kino chiqadi |

### Admin uchun
| Buyruq | Tavsif |
|---|---|
| `/admin` | Admin panel |
| `/add` | Yangi kino qo'shish |
| `/delete <kod>` | Kino o'chirish |
| `/broadcast <matn>` | Barcha foydalanuvchilarga xabar yuborish |

---

## 🗄 Database

Bot **PostgreSQL** ishlatadi (asyncpg orqali). Jadvallar birinchi ishga tushirishda avtomatik yaratiladi:

- `users` — foydalanuvchilar
- `movies` — kinolar (kod, fayl, poster, meta)
- `episodes` — serial epizodlari
- `watch_history` — ko'rish tarixi
- `favorites` — sevimlilar

---

## 📌 Eslatmalar

- `DATABASE_URL` bo'sh bo'lsa bot ishga tushadi, lekin kino saqlanmaydi
- Obuna kanallarini bo'sh qoldirsa — tekshiruv o'chiriladi
- Bot Railway da **worker** sifatida ishlaydi (webhook emas, polling)
