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
EDU_BOT_DATABASE_URL = os.getenv("EDU_BOT_DATABASE_URL", "").strip()
EDU_BOT_TOKEN    = os.getenv("EDU_BOT_TOKEN", "").strip()
EDU_BOT_USERNAME = os.getenv("EDU_BOT_USERNAME", "@zokirovicbbz3_bot").strip()

# ── Kino bot database ─────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# ── Payme ─────────────────────────────────────────────────────────────────────
PAYME_MERCHANT_ID  = os.getenv("PAYME_MERCHANT_ID", "6abe77e27d155b522f000bcd").strip()
PAYME_KEY          = os.getenv("PAYME_KEY", "").strip()
PAYME_TEST_KEY     = os.getenv("PAYME_TEST_KEY", "").strip()
PAYME_MXIK         = os.getenv("PAYME_MXIK", "11702004001000000").strip()
PAYME_TEST_MODE    = os.getenv("PAYME_TEST_MODE", "True").strip().lower() == "true"
PAYME_PACKAGE_CODE = "1184"  # dona (piece)

# To'lov tariflar (tiyin: 1 so'm = 100 tiyin)
PAYME_TARIFFS = {
    "vip":   {"days": None, "price": 5890000,  "label": "♾ VIP (cheksiz) — 58 900 so'm"},
    "day30": {"days": 30,   "price": 3580000,  "label": "📅 1 oylik — 35 800 so'm"},
    "day10": {"days": 10,   "price": 1320000,  "label": "📅 10 kun — 13 200 so'm"},
    "day5":  {"days": 5,    "price": 760000,   "label": "📅 5 kun — 7 600 so'm"},
    "day3":  {"days": 3,    "price": 390000,   "label": "📅 3 kun — 3 900 so'm"},
}

PAYME_URL = (
    "https://checkout.test.paycom.uz"
    if PAYME_TEST_MODE else
    "https://checkout.paycom.uz"
)

# ── Sozlamalar ────────────────────────────────────────────────────────────────
MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "10"))
ITEMS_PER_PAGE     = int(os.getenv("ITEMS_PER_PAGE", "8"))
