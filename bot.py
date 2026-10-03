"""Kino Bot — asosiy fayl."""
from __future__ import annotations

import logging
from datetime import datetime

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    Update, ChatMember,
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ContextTypes, ConversationHandler, MessageHandler,
    filters,
)

import config
from database import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ── ConversationHandler holatlari ────────────────────────────────────────────
(
    ADD_FILE,
    ADD_POSTER,
    ADD_TITLE,
    ADD_META,
    ADD_CONFIRM,
    SEARCH_QUERY,
    SETTINGS_PASSWORD,
    SETTINGS_MENU,
    SET_CHANNEL,
    SET_WELCOME,
    SET_HELP_TEXT,
    SET_NEW_ADMIN,
) = range(12)

# ── Konstantalar ──────────────────────────────────────────────────────────────
GENRES = [
    "Komediya", "Drama", "Ujas", "Triller", "Romantik",
    "Fantastika", "Jangari", "Sarguzasht", "Animatsiya",
    "Tarixiy", "Biografik", "Musiqiy", "Sport", "Oilaviy",
]

TYPES = {
    "kino":      "🎬 Kino",
    "serial":    "📺 Serial",
    "multfilm":  "🎠 Multfilm",
    "shounomas": "🎭 Shou/Nomas",
}

QUALITIES = ["CAM", "HD", "FHD", "4K"]

# ── Runtime sozlamalari (DB tayyor bo'lgunga qadar default) ───────────────────
# Bu sozlamalar /settings orqali o'zgartiriladi, xotirada saqlanadi
_runtime: dict = {
    "welcome_text": None,   # None = default xabar
    "help_text":    None,   # None = default xabar
    "admin_ids":    None,   # None = config.ADMIN_IDS ishlatiladi
}


# ── Yordamchi funksiyalar ─────────────────────────────────────────────────────
def _user_info(update: Update) -> tuple[int, str | None, str]:
    u = update.effective_user
    return u.id, u.username, (u.full_name or u.first_name or "Foydalanuvchi")


def is_admin(user_id: int) -> bool:
    if _runtime["admin_ids"] is not None:
        return user_id in _runtime["admin_ids"]
    return user_id in config.ADMIN_IDS


def _movie_caption(m: dict, is_fav: bool = False) -> str:
    lines = [
        f"🎬 <b>{m['title']}</b>",
        "",
        f"📌 Kod: <code>{m['code']}</code>",
    ]
    if m.get("type"):
        lines.append(f"📺 Tur: {TYPES.get(m['type'], m['type'])}")
    if m.get("genre"):
        lines.append(f"🎭 Janr: {m['genre']}")
    if m.get("year"):
        lines.append(f"📅 Yil: {m['year']}")
    if m.get("country"):
        lines.append(f"🌍 Mamlakat: {m['country']}")
    if m.get("language"):
        lines.append(f"🗣 Til: {m['language']}")
    if m.get("quality"):
        lines.append(f"📽 Sifat: {m['quality']}")
    if m.get("duration"):
        lines.append(f"⏱ Davomiyligi: {m['duration']}")
    if m.get("views"):
        lines.append(f"👁 Ko'rishlar: {m['views']:,}")
    if m.get("description"):
        lines.append(f"\n📝 {m['description']}")
    return "\n".join(lines)


def _movie_keyboard(movie_id: int, is_fav: bool = False) -> InlineKeyboardMarkup:
    fav_text = "❤️ Sevimlilardan olib tashlash" if is_fav else "🤍 Sevimlilarga qo'shish"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(fav_text, callback_data=f"fav_{movie_id}")],
    ])


async def _check_subscriptions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Kanal obunasini tekshiradi. Kanal linki oshkor etilmaydi."""
    user_id = update.effective_user.id
    channels = [ch for ch in config.REQUIRED_CHANNELS if ch]
    if not channels:
        return True

    not_subscribed_idx = []  # indekslar: 0 = 1-kanal, 1 = 2-kanal
    for i, channel in enumerate(channels):
        try:
            member = await ctx.bot.get_chat_member(channel, user_id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                not_subscribed_idx.append(i)
        except Exception:
            not_subscribed_idx.append(i)

    if not not_subscribed_idx:
        return True

    # Tugmalar — link ko'rsatiladi, lekin matnda faqat "1-kanal", "2-kanal"
    buttons = []
    channel_names = []
    for i in not_subscribed_idx:
        ch = channels[i]
        label = f"{i + 1}-kanal"
        channel_names.append(label)
        # URL: agar @ bilan bo'lsa t.me/username, agar raqam bo'lsa to'g'ridan link
        if ch.startswith("@"):
            url = f"https://t.me/{ch.lstrip('@')}"
        elif ch.startswith("-100"):
            # Raqamli kanal ID — invite link yo'q, faqat bot admin bo'lsa ishlaydi
            url = "https://t.me"
        else:
            url = ch  # to'g'ridan URL
        buttons.append([InlineKeyboardButton(
            f"📢 {label}ga obuna bo'lish", url=url
        )])

    buttons.append([InlineKeyboardButton(
        "✅ Obuna bo'ldim — tekshirish",
        callback_data="check_sub"
    )])

    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if msg:
        await msg.reply_text(
            "🔒 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n"
            + "\n".join(f"• {name}" for name in channel_names),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    return False


async def _check_edu_bot(update: Update) -> bool:
    """Foydalanuvchi edu_botga /start bosganmi tekshiradi."""
    user_id = update.effective_user.id
    if not db.edu_ready:
        # Edu DB ulanmagan — o'tkazib yuboramiz
        return True
    result = await db.is_edu_user(user_id)
    if not result:
        msg = update.message or (update.callback_query.message if update.callback_query else None)
        if not msg:
            return False
        await msg.reply_text(
            "📚 <b>Diqqat!</b>\n\n"
            f"Kinoni ko'rish uchun avval {config.EDU_BOT_USERNAME} botga "
            "o'tib <b>/start</b> bosishingiz kerak.\n\n"
            f"👉 <a href='https://t.me/{config.EDU_BOT_USERNAME.lstrip('@')}'>Edu botga o'tish</a>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# FOYDALANUVCHI BUYRUQLARI
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid, uname, fname = _user_info(update)
    await db.upsert_user(uid, uname, fname)

    if not await _check_subscriptions(update, ctx):
        return

    if _runtime["welcome_text"]:
        text = _runtime["welcome_text"].replace("{ism}", fname)
    else:
        text = (
            f"👋 <b>Salom, {fname}!</b>\n\n"
            "🎬 <b>Kino Botga xush kelibsiz!</b>\n\n"
            "📌 <b>Kino topish:</b> Kino kodini yuboring\n"
            "    Masalan: <code>1267</code>\n\n"
            "🔍 /search — Kino qidirish\n"
            "📺 /categories — Kategoriyalar\n"
            "❤️ /favorites — Sevimlilar\n"
            "🔥 /top — Eng ko'p ko'rilganlar\n"
            "ℹ️ /help — Yordam"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if _runtime["help_text"]:
        text = _runtime["help_text"]
    else:
        text = (
            "📖 <b>YORDAM</b>\n\n"
            "Kino topish uchun kino kodini yuboring:\n"
            "<code>1267</code>\n\n"
            "<b>Buyruqlar:</b>\n"
            "🔍 /search — Nom bo'yicha qidirish\n"
            "📺 /categories — Barcha kategoriyalar\n"
            "❤️ /favorites — Sevimlilar ro'yxati\n"
            "🔥 /top — Eng ko'p ko'rilganlar\n"
            "📊 /stats — Statistika"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def handle_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Foydalanuvchi raqam kod yuborganda kino qaytaradi."""
    uid, uname, fname = _user_info(update)
    await db.upsert_user(uid, uname, fname)

    if not await _check_subscriptions(update, ctx):
        return

    # Edu bot tekshiruvi
    if not await _check_edu_bot(update):
        return

    code = update.message.text.strip()
    movie = await db.get_movie_by_code(code)
    if not movie:
        await update.message.reply_text(
            f"❌ <b>{code}</b> kodli kino topilmadi.\n"
            "/search orqali qidiring.",
            parse_mode=ParseMode.HTML,
        )
        return

    await db.increment_views(movie["id"])
    await db.log_watch(uid, movie["id"])
    is_fav = await db.is_favorite(uid, movie["id"])

    caption = _movie_caption(movie, is_fav)
    kb = _movie_keyboard(movie["id"], is_fav)

    if movie.get("poster_id"):
        await update.message.reply_photo(
            photo=movie["poster_id"],
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    else:
        await update.message.reply_text(
            caption, parse_mode=ParseMode.HTML, reply_markup=kb
        )

    await update.message.reply_video(
        video=movie["file_id"],
        caption=f"🎬 {movie['title']} | 📌 Kod: {movie['code']}",
        parse_mode=ParseMode.HTML,
    )


# ── /search ───────────────────────────────────────────────────────────────────
async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _check_subscriptions(update, ctx):
        return ConversationHandler.END
    await update.message.reply_text(
        "🔍 <b>Qidiruv</b>\n\nKino nomini yozing:",
        parse_mode=ParseMode.HTML,
    )
    return SEARCH_QUERY


async def search_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.message.text.strip()
    results = await db.search_movies(query, limit=config.MAX_SEARCH_RESULTS)

    if not results:
        await update.message.reply_text(
            f"❌ <b>{query}</b> bo'yicha natija topilmadi.",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    lines = [f"🔍 <b>'{query}' bo'yicha natijalar ({len(results)} ta):</b>\n"]
    for m in results:
        genre = f" | {m['genre']}" if m.get("genre") else ""
        year  = f" ({m['year']})" if m.get("year") else ""
        lines.append(
            f"📌 <code>{m['code']}</code> — <b>{m['title']}</b>"
            f"{year} {TYPES.get(m['type'], '')} {genre}"
        )
    lines.append("\n💡 Kod yuborish orqali kinoni oling")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    return ConversationHandler.END


# ── /categories ───────────────────────────────────────────────────────────────
async def cmd_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_subscriptions(update, ctx):
        return
    await update.message.reply_text(
        "📺 <b>Kategoriyalar</b>\n\nTurni yoki janrni tanlang:",
        parse_mode=ParseMode.HTML,
        reply_markup=_categories_keyboard(),
    )


def _categories_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Kinolar",     callback_data="cat_kino"),
         InlineKeyboardButton("📺 Seriallar",   callback_data="cat_serial")],
        [InlineKeyboardButton("🎠 Multfilmlar", callback_data="cat_multfilm"),
         InlineKeyboardButton("🎭 Shounomas",   callback_data="cat_shounomas")],
        [InlineKeyboardButton("── Janrlar ──", callback_data="noop")],
        *[[InlineKeyboardButton(g, callback_data=f"genre_{g}")] for g in GENRES[:8]],
    ])


async def category_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "noop":
        return

    if data == "back_cat":
        await query.edit_message_text(
            "📺 <b>Kategoriyalar</b>\n\nTurni yoki janrni tanlang:",
            parse_mode=ParseMode.HTML,
            reply_markup=_categories_keyboard(),
        )
        return

    if data == "check_sub":
        uid = query.from_user.id
        channels = [ch for ch in config.REQUIRED_CHANNELS if ch]
        not_subscribed_idx = []
        for i, channel in enumerate(channels):
            try:
                member = await ctx.bot.get_chat_member(channel, uid)
                if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                    not_subscribed_idx.append(i)
            except Exception:
                not_subscribed_idx.append(i)

        if not not_subscribed_idx:
            # Hammasi tekshirildi — xabarni o'zgartiramiz
            await query.edit_message_text(
                "✅ Obuna tasdiqlandi! Endi botdan foydalanishingiz mumkin.\n\n"
                "/start bosing.",
                parse_mode=ParseMode.HTML,
            )
        else:
            # Hali ham obuna bo'lmagan kanallar bor
            buttons = []
            channel_names = []
            for i in not_subscribed_idx:
                ch = channels[i]
                label = f"{i + 1}-kanal"
                channel_names.append(label)
                if ch.startswith("@"):
                    url = f"https://t.me/{ch.lstrip('@')}"
                else:
                    url = ch
                buttons.append([InlineKeyboardButton(
                    f"📢 {label}ga obuna bo'lish", url=url
                )])
            buttons.append([InlineKeyboardButton(
                "✅ Obuna bo'ldim — tekshirish",
                callback_data="check_sub"
            )])
            await query.edit_message_text(
                "❌ <b>Siz hali quyidagi kanallarga obuna bo'lmadingiz:</b>\n\n"
                + "\n".join(f"• {name}" for name in channel_names)
                + "\n\nObuna bo'lgach, tugmani qayta bosing.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        return

    if data.startswith("fav_"):
        movie_id = int(data.replace("fav_", ""))
        uid = query.from_user.id
        if await db.is_favorite(uid, movie_id):
            await db.remove_favorite(uid, movie_id)
            await query.answer("💔 Sevimlilardan olib tashlandi", show_alert=False)
        else:
            await db.add_favorite(uid, movie_id)
            await query.answer("❤️ Sevimlilarga qo'shildi", show_alert=False)
        movie = await db.get_movie_by_id(movie_id)
        if movie:
            is_fav = await db.is_favorite(uid, movie_id)
            try:
                await query.edit_message_caption(
                    caption=_movie_caption(movie, is_fav),
                    parse_mode=ParseMode.HTML,
                    reply_markup=_movie_keyboard(movie_id, is_fav),
                )
            except Exception:
                pass
        return

    if data.startswith("cat_"):
        movie_type = data.replace("cat_", "")
        movies = await db.get_movies_by_type(movie_type, limit=config.ITEMS_PER_PAGE)
        type_name = TYPES.get(movie_type, movie_type)
    elif data.startswith("genre_"):
        genre = data.replace("genre_", "")
        movies = await db.get_movies_by_genre(genre, limit=config.ITEMS_PER_PAGE)
        type_name = f"🎭 {genre}"
    else:
        return

    if not movies:
        await query.edit_message_text(
            f"❌ {type_name} bo'yicha kino topilmadi.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Orqaga", callback_data="back_cat")
            ]])
        )
        return

    lines = [f"<b>{type_name} ({len(movies)} ta):</b>\n"]
    for m in movies:
        year  = f" ({m['year']})" if m.get("year") else ""
        views = f" 👁{m['views']:,}" if m.get("views") else ""
        lines.append(f"📌 <code>{m['code']}</code> — <b>{m['title']}</b>{year}{views}")
    lines.append("\n💡 Kod yuborish orqali kinoni oling")

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Orqaga", callback_data="back_cat")
        ]])
    )


# ── /favorites ────────────────────────────────────────────────────────────────
async def cmd_favorites(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_subscriptions(update, ctx):
        return
    uid, _, _ = _user_info(update)
    favs = await db.get_favorites(uid)
    if not favs:
        await update.message.reply_text(
            "❤️ Sevimlilar ro'yxatingiz bo'sh.\n"
            "Kino yuborganda ❤️ tugmasini bosing."
        )
        return
    lines = [f"❤️ <b>Sevimlilar ({len(favs)} ta):</b>\n"]
    for m in favs:
        lines.append(f"📌 <code>{m['code']}</code> — <b>{m['title']}</b>")
    lines.append("\n💡 Kod yuborish orqali kinoni oling")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ── /top ──────────────────────────────────────────────────────────────────────
async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_subscriptions(update, ctx):
        return
    movies = await db.get_top_movies(10)
    if not movies:
        await update.message.reply_text("Hali kino yo'q.")
        return
    lines = ["🔥 <b>Eng ko'p ko'rilgan 10 ta kino:</b>\n"]
    for i, m in enumerate(movies, 1):
        lines.append(
            f"{i}. <code>{m['code']}</code> — <b>{m['title']}</b> "
            f"👁 {m['views']:,}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ── /stats ────────────────────────────────────────────────────────────────────
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    stats = await db.get_movie_stats()
    users = await db.get_user_count()
    await update.message.reply_text(
        "📊 <b>STATISTIKA</b>\n\n"
        f"🎬 Kinolar: {stats.get('kinolar', 0)}\n"
        f"📺 Seriallar: {stats.get('seriallar', 0)}\n"
        f"🎠 Multfilmlar: {stats.get('multfilmlar', 0)}\n"
        f"👁 Jami ko'rishlar: {stats.get('total_views', 0) or 0:,}\n\n"
        f"👥 Foydalanuvchilar: {users:,}",
        parse_mode=ParseMode.HTML,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN: KINO QO'SHISH
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Ruxsat yo'q.")
        return ConversationHandler.END
    ctx.user_data.clear()
    ctx.user_data["adding"] = {}
    await update.message.reply_text(
        "➕ <b>Yangi kino qo'shish</b>\n\n1️⃣ Video faylni yuboring:",
        parse_mode=ParseMode.HTML,
    )
    return ADD_FILE


async def add_receive_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.video and not update.message.document:
        await update.message.reply_text("❌ Video fayl yuboring.")
        return ADD_FILE
    file_id = (update.message.video or update.message.document).file_id
    ctx.user_data["adding"]["file_id"] = file_id
    await update.message.reply_text(
        "✅ Video qabul qilindi.\n\n2️⃣ Poster (rasm) yuboring yoki /skip:"
    )
    return ADD_POSTER


async def add_receive_poster(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.photo:
        ctx.user_data["adding"]["poster_id"] = update.message.photo[-1].file_id
    await update.message.reply_text("3️⃣ Kino nomini yozing:")
    return ADD_TITLE


async def add_skip_poster(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["adding"]["poster_id"] = ""
    await update.message.reply_text("3️⃣ Kino nomini yozing:")
    return ADD_TITLE


async def add_receive_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["adding"]["title"] = update.message.text.strip()
    await update.message.reply_text(
        "4️⃣ Kino ma'lumotlarini quyidagi formatda yozing:\n\n"
        "<code>kod: 1267\n"
        "tur: kino\n"
        "janr: Komediya\n"
        "yil: 2024\n"
        "mamlakat: AQSh\n"
        "til: O'zbek\n"
        "sifat: HD\n"
        "davomiyligi: 2 soat\n"
        "tavsif: Qisqa tavsif</code>\n\n"
        "(<i>Faqat 'kod' majburiy</i>)",
        parse_mode=ParseMode.HTML,
    )
    return ADD_META


async def add_receive_meta(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    meta = {}
    for line in text.split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip().lower()] = val.strip()

    d = ctx.user_data["adding"]
    d["code"]        = meta.get("kod", "")
    d["type"]        = meta.get("tur", "kino").lower()
    d["genre"]       = meta.get("janr", "")
    d["year"]        = int(meta["yil"]) if meta.get("yil", "").isdigit() else None
    d["country"]     = meta.get("mamlakat", "")
    d["language"]    = meta.get("til", "O'zbek")
    d["quality"]     = meta.get("sifat", "HD").upper()
    d["duration"]    = meta.get("davomiyligi", "")
    d["description"] = meta.get("tavsif", "")

    if not d["code"]:
        await update.message.reply_text("❌ 'kod' majburiy. Qaytadan yozing.")
        return ADD_META

    caption = (
        f"✅ <b>Tasdiqlash</b>\n\n"
        f"📌 Kod: <code>{d['code']}</code>\n"
        f"🎬 Nom: <b>{d['title']}</b>\n"
        f"📺 Tur: {TYPES.get(d['type'], d['type'])}\n"
        f"🎭 Janr: {d['genre']}\n"
        f"📅 Yil: {d['year']}\n"
        f"🌍 Mamlakat: {d['country']}\n"
        f"🗣 Til: {d['language']}\n"
        f"📽 Sifat: {d['quality']}\n"
        f"⏱ Davomiyligi: {d['duration']}\n"
        f"📝 Tavsif: {d['description'][:100]}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data="confirm_add"),
        InlineKeyboardButton("❌ Bekor",     callback_data="cancel_add"),
    ]])
    await update.message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    return ADD_CONFIRM


async def add_confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_add":
        ctx.user_data.clear()
        await query.edit_message_text("❌ Bekor qilindi.")
        return ConversationHandler.END

    d = ctx.user_data.get("adding", {})
    try:
        movie_id = await db.add_movie(d)
        await query.edit_message_text(
            f"✅ <b>'{d['title']}'</b> qo'shildi!\n"
            f"📌 Kod: <code>{d['code']}</code>\n"
            f"🆔 ID: {movie_id}",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await query.edit_message_text(f"❌ Xato: {e}")
    ctx.user_data.clear()
    return ConversationHandler.END


# ── ADMIN: Kino o'chirish ─────────────────────────────────────────────────────
async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Ishlatish: /delete <kod>")
        return
    code = parts[1].strip()
    ok = await db.delete_movie(code)
    if ok:
        await update.message.reply_text(
            f"✅ <code>{code}</code> o'chirildi.", parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            f"❌ <code>{code}</code> topilmadi.", parse_mode=ParseMode.HTML
        )


# ── ADMIN: /broadcast ─────────────────────────────────────────────────────────
async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text(
            "Ishlatish: /broadcast <xabar matni>\n"
            "Misol: /broadcast 🎬 Yangi kinolar qo'shildi!"
        )
        return

    text = parts[1].strip()
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        await update.message.reply_text("❌ Foydalanuvchilar topilmadi.")
        return

    sent, failed = 0, 0
    status_msg = await update.message.reply_text(
        f"📤 Yuborilmoqda... (0/{len(user_ids)})"
    )

    for uid in user_ids:
        try:
            await ctx.bot.send_message(
                chat_id=uid, text=text, parse_mode=ParseMode.HTML
            )
            sent += 1
        except Exception:
            failed += 1
        if (sent + failed) % 50 == 0:
            try:
                await status_msg.edit_text(
                    f"📤 Yuborilmoqda... ({sent + failed}/{len(user_ids)})"
                )
            except Exception:
                pass

    await status_msg.edit_text(
        f"✅ <b>Xabar yuborildi!</b>\n\n"
        f"✔️ Muvaffaqiyatli: {sent}\n"
        f"❌ Xato (bloklagan): {failed}",
        parse_mode=ParseMode.HTML,
    )


# ── ADMIN: /admin panel ───────────────────────────────────────────────────────
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    stats = await db.get_movie_stats()
    users = await db.get_user_count()
    await update.message.reply_text(
        "🛠 <b>ADMIN PANEL</b>\n\n"
        f"👥 Foydalanuvchilar: {users:,}\n"
        f"🎬 Kinolar: {stats.get('kinolar', 0)}\n"
        f"📺 Seriallar: {stats.get('seriallar', 0)}\n"
        f"🎠 Multfilmlar: {stats.get('multfilmlar', 0)}\n"
        f"👁 Jami ko'rishlar: {stats.get('total_views', 0) or 0:,}\n\n"
        "<b>Buyruqlar:</b>\n"
        "/add — Kino qo'shish\n"
        "/delete &lt;kod&gt; — Kino o'chirish\n"
        "/broadcast &lt;matn&gt; — Hammaga xabar",
        parse_mode=ParseMode.HTML,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# /settings — MAXFIY ADMIN PANELI
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Faqat admin biladi. Parol so'raladi."""
    # Admin bo'lmagan odamga oddiy xabar
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❓ Bunday buyruq yo'q.")
        return ConversationHandler.END

    await update.message.reply_text(
        "🔐 <b>Assalomu aleykum Babalov Bobur Zokirovich</b>\n\n"
        "Iltimos kirishni tasdiqlang.\n\n"
        "<i>Parolni kiriting:</i>",
        parse_mode=ParseMode.HTML,
    )
    return SETTINGS_PASSWORD


async def settings_check_password(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> int:
    entered = update.message.text.strip()
    # Kiritilgan parolni xabardan o'chiramiz (xavfsizlik)
    try:
        await update.message.delete()
    except Exception:
        pass

    if entered != config.ADMIN_PASSWORD:
        await update.message.reply_text(
            "❌ Noto'g'ri parol. Qayta urinib ko'ring yoki /cancel."
        )
        return SETTINGS_PASSWORD

    # Parol to'g'ri — avval barcha yashirin buyruqlarni ko'rsat
    await update.message.reply_text(
        "✅ <b>Xush kelibsiz, Admin!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>BARCHA ADMIN BUYRUQLARI:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎬 <b>Kino boshqaruvi:</b>\n"
        "  /add — Yangi kino qo'shish\n"
        "  /delete &lt;kod&gt; — Kinoni o'chirish\n"
        "    Misol: <code>/delete 1267</code>\n\n"
        "📢 <b>Xabar yuborish:</b>\n"
        "  /broadcast &lt;matn&gt; — Barcha userlarga xabar\n"
        "    Misol: <code>/broadcast Yangi kino qo'shildi!</code>\n\n"
        "📊 <b>Statistika:</b>\n"
        "  /admin — Admin panel va statistika\n"
        "  /stats — Umumiy statistika\n\n"
        "⚙️ <b>Sozlamalar:</b>\n"
        "  /settings — Bu panel (parol kerak)\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👤 <b>Foydalanuvchi buyruqlari:</b>\n"
        "  /start — Botni boshlash\n"
        "  /search — Kino qidirish\n"
        "  /categories — Kategoriyalar\n"
        "  /favorites — Sevimlilar\n"
        "  /top — Top 10 kino\n"
        "  /help — Yordam\n"
        "━━━━━━━━━━━━━━━━━━━━",
        parse_mode=ParseMode.HTML,
    )

    # Keyin sozlamalar panelini ko'rsat
    await update.message.reply_text(
        "⚙️ <b>Sozlamalar paneli</b>\n\nNimani o'zgartirmoqchisiz?",
        parse_mode=ParseMode.HTML,
        reply_markup=_settings_keyboard(),
    )
    return SETTINGS_MENU


def _settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Kanallarni o'zgartirish",  callback_data="set_channels")],
        [InlineKeyboardButton("👥 Foydalanuvchilar soni",    callback_data="set_users_count")],
        [InlineKeyboardButton("📋 Foydalanuvchilar ro'yxati", callback_data="set_users_list")],
        [InlineKeyboardButton("👤 Yangi admin qo'shish",     callback_data="set_add_admin")],
        [InlineKeyboardButton("✏️ Xush kelibsiz xabarini tahrirlash", callback_data="set_welcome")],
        [InlineKeyboardButton("📖 Yordam xabarini tahrirlash", callback_data="set_help")],
        [InlineKeyboardButton("❌ Chiqish",                   callback_data="set_exit")],
    ])


async def settings_menu_callback(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── Kanallarni ko'rsatish va o'zgartirish ─────────────────────────────────
    if data == "set_channels":
        ch1 = config.REQUIRED_CHANNELS[0] or "— yo'q —"
        ch2 = config.REQUIRED_CHANNELS[1] if len(config.REQUIRED_CHANNELS) > 1 else "— yo'q —"
        await query.edit_message_text(
            f"📢 <b>Hozirgi kanallar:</b>\n\n"
            f"1️⃣ Kino kanali: <code>{ch1}</code>\n"
            f"2️⃣ Edu kanali: <code>{ch2}</code>\n\n"
            "Yangi kanal yuboring (@ bilan, masalan: <code>@mening_kanal</code>).\n"
            "Ikkita kanal uchun qatorga yozing:\n"
            "<code>@kanal1\n@kanal2</code>\n\n"
            "/cancel — bekor qilish",
            parse_mode=ParseMode.HTML,
        )
        ctx.user_data["settings_action"] = "channel"
        return SET_CHANNEL

    # ── Foydalanuvchilar soni ─────────────────────────────────────────────────
    elif data == "set_users_count":
        total = await db.get_user_count()
        today = await db.get_today_user_count()
        await query.edit_message_text(
            f"👥 <b>Foydalanuvchilar statistikasi:</b>\n\n"
            f"📊 Jami: <b>{total:,}</b>\n"
            f"📅 Bugun qo'shilgan: <b>{today:,}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Orqaga", callback_data="set_back")
            ]])
        )
        return SETTINGS_MENU

    # ── Foydalanuvchilar ro'yxati ─────────────────────────────────────────────
    elif data == "set_users_list":
        users = await db.get_users_list(limit=50)
        if not users:
            text = "❌ Foydalanuvchilar topilmadi."
        else:
            lines = [f"📋 <b>So'nggi {len(users)} ta foydalanuvchi:</b>\n"]
            for u in users:
                uname = f"@{u['username']}" if u.get("username") else "—"
                name  = u.get("full_name") or "—"
                joined = u["joined_at"].strftime("%d.%m.%Y") if u.get("joined_at") else "—"
                lines.append(
                    f"👤 <code>{u['user_id']}</code> | {uname} | {name} | {joined}"
                )
            text = "\n".join(lines)
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Orqaga", callback_data="set_back")
            ]])
        )
        return SETTINGS_MENU

    # ── Yangi admin qo'shish ──────────────────────────────────────────────────
    elif data == "set_add_admin":
        current_ids = _runtime["admin_ids"] or config.ADMIN_IDS
        ids_str = ", ".join(str(i) for i in current_ids)
        await query.edit_message_text(
            f"👤 <b>Hozirgi adminlar:</b> <code>{ids_str}</code>\n\n"
            "Yangi admin Telegram ID sini yuboring:\n"
            "<i>Masalan: <code>123456789</code></i>\n\n"
            "/cancel — bekor qilish",
            parse_mode=ParseMode.HTML,
        )
        ctx.user_data["settings_action"] = "new_admin"
        return SET_NEW_ADMIN

    # ── Xush kelibsiz xabarini tahrirlash ─────────────────────────────────────
    elif data == "set_welcome":
        current = _runtime["welcome_text"] or "(default xabar)"
        await query.edit_message_text(
            f"✏️ <b>Hozirgi xush kelibsiz xabari:</b>\n\n"
            f"{current}\n\n"
            "Yangi xabarni yuboring. Foydalanuvchi ismini kiritish uchun "
            "<code>{ism}</code> yozing.\n\n"
            "/cancel — bekor qilish",
            parse_mode=ParseMode.HTML,
        )
        ctx.user_data["settings_action"] = "welcome"
        return SET_WELCOME

    # ── Yordam xabarini tahrirlash ────────────────────────────────────────────
    elif data == "set_help":
        current = _runtime["help_text"] or "(default xabar)"
        await query.edit_message_text(
            f"📖 <b>Hozirgi yordam xabari:</b>\n\n"
            f"{current}\n\n"
            "Yangi xabarni yuboring.\n\n"
            "/cancel — bekor qilish",
            parse_mode=ParseMode.HTML,
        )
        ctx.user_data["settings_action"] = "help"
        return SET_HELP_TEXT

    # ── Orqaga ────────────────────────────────────────────────────────────────
    elif data == "set_back":
        await query.edit_message_text(
            "✅ <b>Sozlamalar paneli</b>\n\nNimani o'zgartirmoqchisiz?",
            parse_mode=ParseMode.HTML,
            reply_markup=_settings_keyboard(),
        )
        return SETTINGS_MENU

    # ── Chiqish ───────────────────────────────────────────────────────────────
    elif data == "set_exit":
        ctx.user_data.clear()
        await query.edit_message_text("👋 Sozlamalar panelidan chiqildi.")
        return ConversationHandler.END

    return SETTINGS_MENU


# ── Kanal o'zgartirish ────────────────────────────────────────────────────────
async def settings_set_channel(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> int:
    text = update.message.text.strip()
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    new_channels = []
    for line in lines[:2]:
        ch = line if line.startswith("@") else f"@{line}"
        new_channels.append(ch)

    # Runtime da yangilash
    while len(new_channels) < 2:
        new_channels.append("")
    config.REQUIRED_CHANNELS[0] = new_channels[0]
    if len(config.REQUIRED_CHANNELS) > 1:
        config.REQUIRED_CHANNELS[1] = new_channels[1]
    else:
        config.REQUIRED_CHANNELS.append(new_channels[1])

    await update.message.reply_text(
        f"✅ Kanallar yangilandi:\n"
        f"1️⃣ {new_channels[0] or '—'}\n"
        f"2️⃣ {new_channels[1] or '—'}\n\n"
        "<b>Eslatma:</b> Bu o'zgarish faqat bot qayta ishga tushguncha amal qiladi. "
        "Doimiy qilish uchun Railway .env ni yangilang.",
        parse_mode=ParseMode.HTML,
        reply_markup=_settings_keyboard(),
    )
    return SETTINGS_MENU


# ── Yangi admin ───────────────────────────────────────────────────────────────
async def settings_set_admin(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text(
            "❌ Telegram ID faqat raqamlardan iborat bo'lishi kerak.\n"
            "Qaytadan yuboring yoki /cancel."
        )
        return SET_NEW_ADMIN

    new_id = int(text)
    if _runtime["admin_ids"] is None:
        _runtime["admin_ids"] = list(config.ADMIN_IDS)
    if new_id not in _runtime["admin_ids"]:
        _runtime["admin_ids"].append(new_id)

    ids_str = ", ".join(str(i) for i in _runtime["admin_ids"])
    await update.message.reply_text(
        f"✅ Admin qo'shildi!\n"
        f"👤 Hozirgi adminlar: <code>{ids_str}</code>\n\n"
        "<b>Eslatma:</b> Bu o'zgarish faqat bot qayta ishga tushguncha amal qiladi.",
        parse_mode=ParseMode.HTML,
        reply_markup=_settings_keyboard(),
    )
    return SETTINGS_MENU


# ── Xush kelibsiz xabar ───────────────────────────────────────────────────────
async def settings_set_welcome(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> int:
    _runtime["welcome_text"] = update.message.text.strip()
    await update.message.reply_text(
        "✅ Xush kelibsiz xabari yangilandi!",
        reply_markup=_settings_keyboard(),
    )
    return SETTINGS_MENU


# ── Yordam xabari ─────────────────────────────────────────────────────────────
async def settings_set_help(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> int:
    _runtime["help_text"] = update.message.text.strip()
    await update.message.reply_text(
        "✅ Yordam xabari yangilandi!",
        reply_markup=_settings_keyboard(),
    )
    return SETTINGS_MENU


# ── Cancel ────────────────────────────────────────────────────────────────────
async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════════
# ISHGA TUSHIRISH
# ═══════════════════════════════════════════════════════════════════════════════

async def post_init(app: Application) -> None:
    await db.connect()
    log.info("KinoDB: %s", "ulandi ✅" if db.ready else "ulanmadi ❌")
    log.info("EduDB: %s", "ulandi ✅" if db.edu_ready else "ulanmadi (ixtiyoriy)")


def main() -> None:
    token = config.BOT_TOKEN
    if not token:
        raise RuntimeError("BOT_TOKEN topilmadi!")

    log.info("Kino Bot ishga tushmoqda...")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .read_timeout(120)
        .write_timeout(120)
        .build()
    )

    # ── Kino qo'shish conversation ────────────────────────────────────────────
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            ADD_FILE: [
                MessageHandler(filters.VIDEO | filters.Document.VIDEO, add_receive_file)
            ],
            ADD_POSTER: [
                MessageHandler(filters.PHOTO, add_receive_poster),
                CommandHandler("skip", add_skip_poster),
            ],
            ADD_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_receive_title)
            ],
            ADD_META: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_receive_meta)
            ],
            ADD_CONFIRM: [
                CallbackQueryHandler(
                    add_confirm_callback, pattern=r"^(confirm|cancel)_add$"
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        conversation_timeout=300,
    )

    # ── Qidiruv conversation ──────────────────────────────────────────────────
    search_conv = ConversationHandler(
        entry_points=[CommandHandler("search", cmd_search)],
        states={
            SEARCH_QUERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_query)
            ]
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        conversation_timeout=120,
    )

    # ── /settings maxfiy admin paneli ─────────────────────────────────────────
    settings_conv = ConversationHandler(
        entry_points=[CommandHandler("settings", cmd_settings)],
        states={
            SETTINGS_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_check_password)
            ],
            SETTINGS_MENU: [
                CallbackQueryHandler(settings_menu_callback, pattern=r"^set_")
            ],
            SET_CHANNEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_set_channel)
            ],
            SET_NEW_ADMIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_set_admin)
            ],
            SET_WELCOME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_set_welcome)
            ],
            SET_HELP_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_set_help)
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        conversation_timeout=300,
    )

    # ── Handlerlarni qo'shish ─────────────────────────────────────────────────
    app.add_handler(settings_conv)          # /settings eng birinchi
    app.add_handler(add_conv)
    app.add_handler(search_conv)
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("favorites",  cmd_favorites))
    app.add_handler(CommandHandler("top",        cmd_top))
    app.add_handler(CommandHandler("stats",      cmd_stats))
    app.add_handler(CommandHandler("admin",      cmd_admin))
    app.add_handler(CommandHandler("delete",     cmd_delete))
    app.add_handler(CommandHandler("broadcast",  cmd_broadcast))
    app.add_handler(CallbackQueryHandler(category_callback))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\d+$"),
        handle_code,
    ))

    log.info("Polling boshlandi...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
