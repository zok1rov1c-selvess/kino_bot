"""Kino bot konfiguratsiyasi."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN  = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS  = [int(x) for x in os.getenv("ADMIN_IDS", "8385661550").split(",") if x.strip()]

# ── Maxfiy admin paroli (/settings uchun) ─────────────────────────────────────
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Solixa@123").strip()

# ── Obuna tekshiruvi uchun kanallar ──────────────────────────────────────────
REQUIRED_CHANNELS = [
    os.getenv("KINO_CHANNEL", "").strip(),
    os.getenv("EDU_CHANNEL",  "").strip(),
]

# ── Edu bot ───────────────────────────────────────────────────────────────────
# Edu bot database URL — foydalanuvchi /start bosganmi tekshirish uchun
EDU_BOT_DATABASE_URL = os.getenv("EDU_BOT_DATABASE_URL", "").strip()
# Edu bot tokeni (keyinroq qo'shiladi)
EDU_BOT_TOKEN    = os.getenv("EDU_BOT_TOKEN", "").strip()
EDU_BOT_USERNAME = os.getenv("EDU_BOT_USERNAME", "@zokirovicbbz3_bot").strip()

# ── Kino bot database ─────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# ── Sozlamalar ────────────────────────────────────────────────────────────────
MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "10"))
ITEMS_PER_PAGE     = int(os.getenv("ITEMS_PER_PAGE", "8"))
