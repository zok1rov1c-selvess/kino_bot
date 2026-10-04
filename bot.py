"""Kino Bot — asosiy fayl."""
from __future__ import annotations

import logging

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters,
)

import config
from database import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ── Conversation holatlari ────────────────────────────────────────────────────
(
    ADD_FILE, ADD_POSTER, ADD_TITLE, ADD_CATEGORY,
    ADD_YEAR, ADD_COUNTRY, ADD_LANGUAGE, ADD_QUALITY,
    ADD_DESCRIPTION, ADD_CONFIRM, ADD_EDIT,
    SEARCH_QUERY,
    SETTINGS_PASSWORD, SETTINGS_MENU,
    SET_CHANNEL, SET_WELCOME, SET_HELP_TEXT, SET_NEW_ADMIN,
) = range(18)

TYPES = {
    "kino":      "🎬 Kino",
    "serial":    "📺 Serial",
    "multfilm":  "🎠 Multfilm",
    "shounomas": "🎭 Shou/Nomas",
}

GENRES = [
    "Komediya", "Drama", "Ujas", "Triller", "Romantik",
    "Fantastika", "Jangari", "Sarguzasht", "Animatsiya",
    "Tarixiy", "Biografik", "Musiqiy", "Sport", "Oilaviy",
]

# Asosiy super admin — faqat u boshqa adminlarni o'chira oladi
SUPER_ADMIN_ID = 8385661550

# Runtime o'zgaruvchilar (bot ishlayotgan vaqtda saqlanadi)
_rt: dict = {
    "welcome_text": None,
    "help_text":    None,
    "admin_ids":    None,  # None bo'lsa config.ADMIN_IDS ishlatiladi
}


# ═══════════════════════════════════════════════════════════════════════════════
# YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════════════════════════════════

def _get_admin_ids() -> list[int]:
    """Hozirgi admin IDlar ro'yxatini qaytaradi."""
    if _rt["admin_ids"] is not None:
        return _rt["admin_ids"]
    return list(config.ADMIN_IDS)


def is_admin(user_id: int) -> bool:
    return user_id in _get_admin_ids()


def _user_info(update: Update) -> tuple[int, str | None, str]:
    u = update.effective_user
    return u.id, u.username, (u.full_name or u.first_name or "Foydalanuvchi")


def _format_duration(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "Noma'lum"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h} soat {m} daqiqa" if h > 0 else f"{m} daqiqa"


def _movie_caption(m: dict, is_fav: bool = False) -> str:
    lines = [f"🎬 <b>{m['title']}</b>", "", f"📌 Kod: <code>{m['code']}</code>"]
    if m.get("type"):   lines.append(f"📺 Tur: {TYPES.get(m['type'], m['type'])}")
    if m.get("genre"):  lines.append(f"🎭 Janr: {m['genre']}")
    if m.get("year"):   lines.append(f"📅 Yil: {m['year']}")
    if m.get("country"): lines.append(f"🌍 Mamlakat: {m['country']}")
    if m.get("language"): lines.append(f"🗣 Til: {m['language']}")
    if m.get("quality"): lines.append(f"📽 Sifat: {m['quality']}")
    if m.get("duration"): lines.append(f"⏱ Davomiyligi: {m['duration']}")
    if m.get("views"):  lines.append(f"👁 Ko'rishlar: {m['views']:,}")
    if m.get("description"): lines.append(f"\n📝 {m['description']}")
    return "\n".join(lines)


def _movie_kb(movie_id: int, is_fav: bool = False) -> InlineKeyboardMarkup:
    txt = "❤️ Sevimlilardan olib tashlash" if is_fav else "🤍 Sevimlilarga qo'shish"
    return InlineKeyboardMarkup([[InlineKeyboardButton(txt, callback_data=f"fav_{movie_id}")]])


async def _check_sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Kanal obunasini tekshiradi. Link ko'rsatilmaydi."""
    user_id = update.effective_user.id
    channels = [ch for ch in config.REQUIRED_CHANNELS if ch]
    if not channels:
        return True

    unsub = []
    for i, ch in enumerate(channels):
        try:
            m = await ctx.bot.get_chat_member(ch, user_id)
            if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                unsub.append(i)
        except Exception:
            unsub.append(i)

    if not unsub:
        return True

    buttons = []
    names = []
    for i in unsub:
        ch = channels[i]
        label = f"{i+1}-kanal"
        names.append(label)
        url = f"https://t.me/{ch.lstrip('@')}" if ch.startswith("@") else ch
        buttons.append([InlineKeyboardButton(f"📢 {label}ga obuna bo'lish", url=url)])
    buttons.append([InlineKeyboardButton("✅ Obuna bo'ldim — tekshirish", callback_data="check_sub")])

    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if msg:
        await msg.reply_text(
            "🔒 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n"
            + "\n".join(f"• {n}" for n in names),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    return False


async def _check_edu(update: Update) -> bool:
    """Edu botga /start bosganmi tekshiradi."""
    if not db.edu_ready:
        return True
    uid = update.effective_user.id
    result = await db.is_edu_user(uid)
    if not result:
        msg = update.message or (update.callback_query.message if update.callback_query else None)
        if msg:
            await msg.reply_text(
                f"📚 Kinoni ko'rish uchun avval {config.EDU_BOT_USERNAME} botga "
                f"o'tib /start bosing.\n\n"
                f"👉 https://t.me/{config.EDU_BOT_USERNAME.lstrip('@')}",
                parse_mode=ParseMode.HTML,
            )
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# FOYDALANUVCHI BUYRUQLARI
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid, uname, fname = _user_info(update)
    await db.upsert_user(uid, uname, fname)
    if not await _check_sub(update, ctx):
        return
    text = (_rt["welcome_text"] or "").replace("{ism}", fname) if _rt["welcome_text"] else (
        f"👋 <b>Salom, {fname}!</b>\n\n"
        "🎬 <b>Kino Botga xush kelibsiz!</b>\n\n"
        "📌 Kino kodini yuboring. Masalan: <code>1267</code>\n\n"
        "🔍 /search — Qidirish\n"
        "📺 /categories — Kategoriyalar\n"
        "❤️ /favorites — Sevimlilar\n"
        "🔥 /top — Top kinolar\n"
        "ℹ️ /help — Yordam"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = _rt["help_text"] or (
        "📖 <b>YORDAM</b>\n\n"
        "Kino kodini yuboring:\n<code>1267</code>\n\n"
        "🔍 /search — Nom bo'yicha qidirish\n"
        "📺 /categories — Kategoriyalar\n"
        "❤️ /favorites — Sevimlilar\n"
        "🔥 /top — Eng ko'p ko'rilganlar\n"
        "📊 /stats — Statistika"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def handle_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid, uname, fname = _user_info(update)
    await db.upsert_user(uid, uname, fname)
    if not await _check_sub(update, ctx):
        return
    if not await _check_edu(update):
        return
    code = update.message.text.strip()
    movie = await db.get_movie_by_code(code)
    if not movie:
        await update.message.reply_text(
            f"❌ <b>{code}</b> kodli kino topilmadi.", parse_mode=ParseMode.HTML
        )
        return
    await db.increment_views(movie["id"])
    await db.log_watch(uid, movie["id"])
    is_fav = await db.is_favorite(uid, movie["id"])
    caption = _movie_caption(movie, is_fav)
    kb = _movie_kb(movie["id"], is_fav)
    if movie.get("poster_id"):
        await update.message.reply_photo(photo=movie["poster_id"], caption=caption,
                                         parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await update.message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    await update.message.reply_video(
        video=movie["file_id"],
        caption=f"🎬 {movie['title']} | 📌 Kod: {movie['code']}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _check_sub(update, ctx):
        return ConversationHandler.END
    await update.message.reply_text("🔍 Kino nomini yozing:", parse_mode=ParseMode.HTML)
    return SEARCH_QUERY


async def search_query_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.message.text.strip()
    results = await db.search_movies(q, limit=config.MAX_SEARCH_RESULTS)
    if not results:
        await update.message.reply_text(f"❌ <b>{q}</b> topilmadi.", parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    lines = [f"🔍 <b>'{q}' natijalari ({len(results)} ta):</b>\n"]
    for m in results:
        g = f" | {m['genre']}" if m.get("genre") else ""
        y = f" ({m['year']})" if m.get("year") else ""
        lines.append(f"📌 <code>{m['code']}</code> — <b>{m['title']}</b>{y} {TYPES.get(m['type'], '')}{g}")
    lines.append("\n💡 Kod yuborish orqali kinoni oling")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    return ConversationHandler.END


def _cat_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Kinolar", callback_data="cat_kino"),
         InlineKeyboardButton("📺 Seriallar", callback_data="cat_serial")],
        [InlineKeyboardButton("🎠 Multfilmlar", callback_data="cat_multfilm"),
         InlineKeyboardButton("🎭 Shounomas", callback_data="cat_shounomas")],
        [InlineKeyboardButton("── Janrlar ──", callback_data="noop")],
        *[[InlineKeyboardButton(g, callback_data=f"genre_{g}")] for g in GENRES[:8]],
    ])


async def cmd_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_sub(update, ctx):
        return
    await update.message.reply_text("📺 <b>Kategoriyalar</b>\n\nTurni tanlang:",
                                    parse_mode=ParseMode.HTML, reply_markup=_cat_kb())


async def category_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "noop":
        return

    if data == "back_cat":
        await q.edit_message_text("📺 <b>Kategoriyalar</b>\n\nTurni tanlang:",
                                  parse_mode=ParseMode.HTML, reply_markup=_cat_kb())
        return

    if data == "check_sub":
        uid = q.from_user.id
        channels = [ch for ch in config.REQUIRED_CHANNELS if ch]
        unsub = []
        for i, ch in enumerate(channels):
            try:
                m = await ctx.bot.get_chat_member(ch, uid)
                if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                    unsub.append(i)
            except Exception:
                unsub.append(i)
        if not unsub:
            await q.edit_message_text("✅ Obuna tasdiqlandi! /start bosing.", parse_mode=ParseMode.HTML)
        else:
            buttons = []
            names = []
            for i in unsub:
                ch = channels[i]
                label = f"{i+1}-kanal"
                names.append(label)
                url = f"https://t.me/{ch.lstrip('@')}" if ch.startswith("@") else ch
                buttons.append([InlineKeyboardButton(f"📢 {label}ga obuna bo'lish", url=url)])
            buttons.append([InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub")])
            await q.edit_message_text(
                "❌ <b>Hali obuna bo'lmadingiz:</b>\n\n" + "\n".join(f"• {n}" for n in names),
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        return

    if data.startswith("fav_"):
        mid = int(data[4:])
        uid = q.from_user.id
        if await db.is_favorite(uid, mid):
            await db.remove_favorite(uid, mid)
            fav_msg = "💔 Sevimlilardan olib tashlandi"
        else:
            await db.add_favorite(uid, mid)
            fav_msg = "❤️ Sevimlilarga qo'shildi"
        await q.answer(fav_msg, show_alert=False)
        movie = await db.get_movie_by_id(mid)
        if movie:
            fav = await db.is_favorite(uid, mid)
            try:
                await q.edit_message_caption(caption=_movie_caption(movie, fav),
                                             parse_mode=ParseMode.HTML, reply_markup=_movie_kb(mid, fav))
            except Exception:
                pass
        return

    if data.startswith("cat_"):
        mtype = data[4:]
        movies = await db.get_movies_by_type(mtype, limit=config.ITEMS_PER_PAGE)
        tname = TYPES.get(mtype, mtype)
    elif data.startswith("genre_"):
        genre = data[6:]
        movies = await db.get_movies_by_genre(genre, limit=config.ITEMS_PER_PAGE)
        tname = f"🎭 {genre}"
    else:
        return

    if not movies:
        await q.edit_message_text(f"❌ {tname} bo'yicha kino topilmadi.",
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Orqaga", callback_data="back_cat")]]))
        return

    lines = [f"<b>{tname} ({len(movies)} ta):</b>\n"]
    for m in movies:
        y = f" ({m['year']})" if m.get("year") else ""
        v = f" 👁{m['views']:,}" if m.get("views") else ""
        lines.append(f"📌 <code>{m['code']}</code> — <b>{m['title']}</b>{y}{v}")
    lines.append("\n💡 Kod yuborish orqali kinoni oling")
    await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML,
                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Orqaga", callback_data="back_cat")]]))


async def cmd_favorites(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_sub(update, ctx):
        return
    uid, _, _ = _user_info(update)
    favs = await db.get_favorites(uid)
    if not favs:
        await update.message.reply_text("❤️ Sevimlilar bo'sh.")
        return
    lines = [f"❤️ <b>Sevimlilar ({len(favs)} ta):</b>\n"]
    for m in favs:
        lines.append(f"📌 <code>{m['code']}</code> — <b>{m['title']}</b>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_sub(update, ctx):
        return
    movies = await db.get_top_movies(10)
    if not movies:
        await update.message.reply_text("Hali kino yo'q.")
        return
    lines = ["🔥 <b>Top 10 kino:</b>\n"]
    for i, m in enumerate(movies, 1):
        lines.append(f"{i}. <code>{m['code']}</code> — <b>{m['title']}</b> 👁{m['views']:,}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    stats = await db.get_movie_stats()
    users = await db.get_user_count()
    await update.message.reply_text(
        f"📊 <b>STATISTIKA</b>\n\n"
        f"🎬 Kinolar: {stats.get('kinolar', 0)}\n"
        f"📺 Seriallar: {stats.get('seriallar', 0)}\n"
        f"🎠 Multfilmlar: {stats.get('multfilmlar', 0)}\n"
        f"👁 Ko'rishlar: {stats.get('total_views', 0) or 0:,}\n"
        f"👥 Foydalanuvchilar: {users:,}",
        parse_mode=ParseMode.HTML,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN: KINO QO'SHISH
# ═══════════════════════════════════════════════════════════════════════════════

def _add_cat_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Kino", callback_data="ac_type_kino"),
         InlineKeyboardButton("📺 Serial", callback_data="ac_type_serial")],
        [InlineKeyboardButton("🎠 Multfilm", callback_data="ac_type_multfilm"),
         InlineKeyboardButton("🎭 Shounomas", callback_data="ac_type_shounomas")],
        [InlineKeyboardButton("── Janrlar ──", callback_data="ac_noop")],
        [InlineKeyboardButton("😂 Komediya", callback_data="ac_genre_Komediya"),
         InlineKeyboardButton("🎭 Drama", callback_data="ac_genre_Drama")],
        [InlineKeyboardButton("👻 Ujas", callback_data="ac_genre_Ujas"),
         InlineKeyboardButton("🔪 Triller", callback_data="ac_genre_Triller")],
        [InlineKeyboardButton("💕 Romantik", callback_data="ac_genre_Romantik"),
         InlineKeyboardButton("🚀 Fantastika", callback_data="ac_genre_Fantastika")],
        [InlineKeyboardButton("💥 Jangari", callback_data="ac_genre_Jangari"),
         InlineKeyboardButton("🗺 Sarguzasht", callback_data="ac_genre_Sarguzasht")],
        [InlineKeyboardButton("🎨 Animatsiya", callback_data="ac_genre_Animatsiya"),
         InlineKeyboardButton("📜 Tarixiy", callback_data="ac_genre_Tarixiy")],
        [InlineKeyboardButton("🏆 Sport", callback_data="ac_genre_Sport"),
         InlineKeyboardButton("👨‍👩‍👧 Oilaviy", callback_data="ac_genre_Oilaviy")],
        [InlineKeyboardButton("✅ Davom etish", callback_data="ac_skip")],
    ])


def _add_qual_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 480p", callback_data="aq_480p")],
        [InlineKeyboardButton("🎬 720p HD", callback_data="aq_720p")],
        [InlineKeyboardButton("🎥 1080p Full HD", callback_data="aq_1080p")],
    ])


def _confirm_text(d: dict) -> str:
    return (
        f"📋 <b>Kino ma'lumotlari:</b>\n\n"
        f"📌 Kod: <code>{d.get('code') or '—'}</code>\n"
        f"🎬 Nom: <b>{d.get('title') or '—'}</b>\n"
        f"📺 Tur: {TYPES.get(d.get('type', ''), d.get('type') or '—')}\n"
        f"🎭 Janr: {d.get('genre') or '—'}\n"
        f"📅 Yil: {d.get('year') or '—'}\n"
        f"🌍 Mamlakat: {d.get('country') or '—'}\n"
        f"🗣 Til: {d.get('language') or '—'}\n"
        f"📽 Sifat: {d.get('quality') or '—'}\n"
        f"⏱ Davomiyligi: {d.get('duration') or '—'}\n"
        f"📝 Tavsif: {(d.get('description') or '—')[:100]}"
    )


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Tasdiqlash", callback_data="aconf_yes")],
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data="aconf_edit")],
        [InlineKeyboardButton("❌ Bekor", callback_data="aconf_cancel")],
    ])


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Ruxsat yo'q.")
        return ConversationHandler.END
    ctx.user_data.clear()
    ctx.user_data["d"] = {}
    await update.message.reply_text(
        "➕ <b>Yangi kino qo'shish</b>\n\n1️⃣ Video faylni yuboring:",
        parse_mode=ParseMode.HTML,
    )
    return ADD_FILE


async def add_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    video = msg.video or msg.document
    if not video:
        await msg.reply_text("❌ Video fayl yuboring.")
        return ADD_FILE
    d = ctx.user_data["d"]
    d["file_id"] = video.file_id
    dur = getattr(msg.video, "duration", 0) or 0
    d["duration"] = _format_duration(dur)
    dur_txt = f"⏱ Davomiyligi: <b>{d['duration']}</b>" if dur > 0 else "⏱ Davomiylik aniqlanmadi"
    await msg.reply_text(f"✅ Video qabul qilindi. {dur_txt}\n\n2️⃣ Poster (rasm) yuboring yoki /skip:",
                         parse_mode=ParseMode.HTML)
    return ADD_POSTER


async def add_poster(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.photo:
        ctx.user_data["d"]["poster_id"] = update.message.photo[-1].file_id
    else:
        ctx.user_data["d"]["poster_id"] = ""
    await update.message.reply_text("3️⃣ Kino nomini yozing:", parse_mode=ParseMode.HTML)
    return ADD_TITLE


async def add_poster_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["d"]["poster_id"] = ""
    await update.message.reply_text("3️⃣ Kino nomini yozing:", parse_mode=ParseMode.HTML)
    return ADD_TITLE


async def add_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["d"]["title"] = update.message.text.strip()
    await update.message.reply_text("4️⃣ Kategoriya va janrni tanlang:",
                                    parse_mode=ParseMode.HTML, reply_markup=_add_cat_kb())
    return ADD_CATEGORY


async def add_category_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    data = q.data
    d = ctx.user_data["d"]

    if data == "ac_noop":
        return ADD_CATEGORY

    if data == "ac_skip":
        d.setdefault("type", "kino")
        d.setdefault("genre", "")
        await q.edit_message_text("5️⃣ Yilini yozing yoki /skip:\n<i>Masalan: 2024</i>",
                                  parse_mode=ParseMode.HTML)
        return ADD_YEAR

    if data.startswith("ac_type_"):
        d["type"] = data[8:]
        await q.edit_message_text(
            f"✅ Tur: <b>{TYPES.get(d['type'], d['type'])}</b>\n\nJanr tanlang yoki ✅ Davom etish:",
            parse_mode=ParseMode.HTML, reply_markup=_add_cat_kb())
        return ADD_CATEGORY

    if data.startswith("ac_genre_"):
        d["genre"] = data[9:]
        d.setdefault("type", "kino")
        await q.edit_message_text(
            f"✅ Janr: <b>{d['genre']}</b>\n\n5️⃣ Yilini yozing yoki /skip:",
            parse_mode=ParseMode.HTML)
        return ADD_YEAR

    return ADD_CATEGORY


async def add_year(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    t = update.message.text.strip()
    ctx.user_data["d"]["year"] = int(t) if t.isdigit() else None
    await update.message.reply_text("6️⃣ Mamlakati:\n<i>Masalan: AQSh</i>\n\nYoki /skip",
                                    parse_mode=ParseMode.HTML)
    return ADD_COUNTRY


async def add_year_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["d"]["year"] = None
    await update.message.reply_text("6️⃣ Mamlakati:\n<i>Masalan: AQSh</i>\n\nYoki /skip",
                                    parse_mode=ParseMode.HTML)
    return ADD_COUNTRY


async def add_country(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["d"]["country"] = update.message.text.strip()
    await update.message.reply_text("7️⃣ Video tili:\n<i>Masalan: O'zbek, Rus</i>",
                                    parse_mode=ParseMode.HTML)
    return ADD_LANGUAGE


async def add_country_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["d"]["country"] = ""
    await update.message.reply_text("7️⃣ Video tili:\n<i>Masalan: O'zbek, Rus</i>",
                                    parse_mode=ParseMode.HTML)
    return ADD_LANGUAGE


async def add_language(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["d"]["language"] = update.message.text.strip()
    await update.message.reply_text("8️⃣ Video sifatini tanlang:",
                                    parse_mode=ParseMode.HTML, reply_markup=_add_qual_kb())
    return ADD_QUALITY


async def add_quality_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    qmap = {"aq_480p": "480p", "aq_720p": "720p HD", "aq_1080p": "1080p Full HD"}
    if q.data not in qmap:
        return ADD_QUALITY
    ctx.user_data["d"]["quality"] = qmap[q.data]
    await q.edit_message_text(
        f"✅ Sifat: <b>{qmap[q.data]}</b>\n\n9️⃣ Kino kodini yozing:\n<i>Masalan: 1267</i>",
        parse_mode=ParseMode.HTML)
    return ADD_CONFIRM


async def add_receive_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip()
    if not code.isdigit():
        await update.message.reply_text("❌ Kod faqat raqamlardan iborat bo'lishi kerak.")
        return ADD_CONFIRM
    ctx.user_data["d"]["code"] = code
    await update.message.reply_text(
        "🔟 Tavsif yozing yoki /skip:", parse_mode=ParseMode.HTML)
    return ADD_DESCRIPTION


async def add_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["d"]["description"] = update.message.text.strip()
    d = ctx.user_data["d"]
    await update.message.reply_text(_confirm_text(d), parse_mode=ParseMode.HTML, reply_markup=_confirm_kb())
    return ADD_CONFIRM


async def add_description_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["d"]["description"] = ""
    d = ctx.user_data["d"]
    await update.message.reply_text(_confirm_text(d), parse_mode=ParseMode.HTML, reply_markup=_confirm_kb())
    return ADD_CONFIRM


async def add_confirm_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "aconf_cancel":
        ctx.user_data.clear()
        await q.edit_message_text("❌ Bekor qilindi.")
        return ConversationHandler.END

    if data == "aconf_yes":
        d = ctx.user_data.get("d", {})
        if not d.get("code"):
            await q.message.reply_text("🔢 Avval kino kodini yozing:")
            return ADD_CONFIRM
        try:
            mid = await db.add_movie(d)
            await q.edit_message_text(
                f"✅ <b>'{d['title']}'</b> qo'shildi!\n📌 Kod: <code>{d['code']}</code>\n🆔 ID: {mid}",
                parse_mode=ParseMode.HTML)
        except Exception as e:
            await q.edit_message_text(f"❌ Xato: {e}")
        ctx.user_data.clear()
        return ConversationHandler.END

    if data == "aconf_edit":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📌 Kodni o'zgartirish", callback_data="ae_code")],
            [InlineKeyboardButton("🎬 Nomni o'zgartirish", callback_data="ae_title")],
            [InlineKeyboardButton("📺 Tur/Janr", callback_data="ae_category")],
            [InlineKeyboardButton("📅 Yil", callback_data="ae_year")],
            [InlineKeyboardButton("🌍 Mamlakat", callback_data="ae_country")],
            [InlineKeyboardButton("🗣 Til", callback_data="ae_language")],
            [InlineKeyboardButton("📽 Sifat", callback_data="ae_quality")],
            [InlineKeyboardButton("📝 Tavsif", callback_data="ae_desc")],
            [InlineKeyboardButton("◀️ Orqaga", callback_data="ae_back")],
        ])
        await q.edit_message_text("✏️ Nimani o'zgartirmoqchisiz?",
                                  parse_mode=ParseMode.HTML, reply_markup=kb)
        return ADD_EDIT

    return ADD_CONFIRM


async def add_edit_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    data = q.data
    d = ctx.user_data.get("d", {})

    if data == "ae_back":
        await q.edit_message_text(_confirm_text(d), parse_mode=ParseMode.HTML, reply_markup=_confirm_kb())
        return ADD_CONFIRM

    if data == "ae_category":
        await q.edit_message_text("Yangi kategoriyani tanlang:", reply_markup=_add_cat_kb())
        return ADD_CATEGORY

    if data == "ae_quality":
        await q.edit_message_text("Yangi sifatni tanlang:", reply_markup=_add_qual_kb())
        return ADD_QUALITY

    prompts = {
        "ae_code": "📌 Yangi kodni yozing:",
        "ae_title": "🎬 Yangi nomni yozing:",
        "ae_year": "📅 Yangi yilni yozing (yoki /skip):",
        "ae_country": "🌍 Yangi mamlakatni yozing (yoki /skip):",
        "ae_language": "🗣 Yangi tilni yozing:",
        "ae_desc": "📝 Yangi tavsifni yozing (yoki /skip):",
    }
    if data in prompts:
        ctx.user_data["edit_field"] = data
        await q.message.reply_text(prompts[data])
        return ADD_EDIT

    return ADD_EDIT


async def add_edit_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    field = ctx.user_data.get("edit_field", "")
    raw = update.message.text or ""
    # /skip buyrug'i bo'lsa — bo'sh string
    text = "" if raw.startswith("/skip") else raw.strip()
    d = ctx.user_data["d"]
    fmap = {
        "ae_code": ("code", text),
        "ae_title": ("title", text),
        "ae_year": ("year", int(text) if text.isdigit() else None),
        "ae_country": ("country", text),
        "ae_language": ("language", text),
        "ae_desc": ("description", text),
    }
    if field in fmap:
        k, v = fmap[field]
        d[k] = v
    ctx.user_data.pop("edit_field", None)
    await update.message.reply_text(_confirm_text(d), parse_mode=ParseMode.HTML, reply_markup=_confirm_kb())
    return ADD_CONFIRM


# ── ADMIN: Kino o'chirish ─────────────────────────────────────────────────────
async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Ishlatish: /delete <kod>")
        return
    ok = await db.delete_movie(parts[1].strip())
    if ok:
        await update.message.reply_text(f"✅ <code>{parts[1].strip()}</code> o'chirildi.", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"❌ <code>{parts[1].strip()}</code> topilmadi.", parse_mode=ParseMode.HTML)


# ── SUPER ADMIN: Admin o'chirish buyrug'i ─────────────────────────────────────
async def cmd_del_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/set_del_admin <id> — Adminni o'chirish (faqat super admin)."""
    uid = update.effective_user.id
    if uid != SUPER_ADMIN_ID:
        await update.message.reply_text("❌ Bu buyruq faqat asosiy admin uchun.")
        return

    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        # ID berilmagan — ro'yxatni ko'rsat
        if _rt["admin_ids"] is None:
            _rt["admin_ids"] = list(config.ADMIN_IDS)
        removable = [i for i in _rt["admin_ids"] if i != SUPER_ADMIN_ID]
        if not removable:
            await update.message.reply_text("ℹ️ Boshqa admin yo'q.")
            return
        ids_str = "\n".join(f"• <code>{i}</code>" for i in removable)
        await update.message.reply_text(
            f"🗑 <b>Adminlar ro'yxati:</b>\n\n{ids_str}\n\n"
            "O'chirish uchun:\n<code>/set_del_admin ID</code>\n"
            "Masalan: <code>/set_del_admin 123456789</code>",
            parse_mode=ParseMode.HTML)
        return

    text = parts[1].strip()
    if not text.isdigit():
        await update.message.reply_text("❌ ID faqat raqam bo'lishi kerak.")
        return

    target = int(text)
    if target == SUPER_ADMIN_ID:
        await update.message.reply_text("❌ Asosiy adminni o'chirib bo'lmaydi!")
        return

    if _rt["admin_ids"] is None:
        _rt["admin_ids"] = list(config.ADMIN_IDS)

    if target not in _rt["admin_ids"]:
        await update.message.reply_text(f"❌ <code>{target}</code> adminlar ro'yxatida yo'q.", parse_mode=ParseMode.HTML)
        return

    _rt["admin_ids"].remove(target)
    remaining = ", ".join(str(i) for i in _rt["admin_ids"]) or str(SUPER_ADMIN_ID)
    await update.message.reply_text(
        f"✅ Admin o'chirildi: <code>{target}</code>\n"
        f"Qolgan adminlar: <code>{remaining}</code>",
        parse_mode=ParseMode.HTML)


# ── SUPER ADMIN: Foydalanuvchilar ro'yxati ────────────────────────────────────
async def cmd_users_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/users — Foydalanuvchilar ro'yxatini ko'rish."""
    if not is_admin(update.effective_user.id):
        return

    if not db.ready:
        await update.message.reply_text("❌ Database ulanmagan.")
        return

    parts = update.message.text.split(maxsplit=1)
    try:
        offset = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        offset = 0

    users = await db.get_users_list(limit=30, offset=offset)
    total = await db.get_user_count()
    today = await db.get_today_user_count()

    if not users:
        await update.message.reply_text(
            f"👥 Jami: {total:,} | Bugun: {today:,}\n\n❌ Bu sahifada foydalanuvchi yo'q.")
        return

    lines = [f"👥 <b>Foydalanuvchilar</b> (jami: {total:,}, bugun: +{today})\n"
             f"📄 {offset+1}–{offset+len(users)} ta ko'rsatilmoqda:\n"]
    for u in users:
        uname = f"@{u['username']}" if u.get("username") else "—"
        name = (u.get("full_name") or "—")[:15]
        try:
            joined = u["joined_at"].strftime("%d.%m.%Y") if u.get("joined_at") else "—"
        except Exception:
            joined = "—"
        lines.append(f"<code>{u['user_id']}</code> | {uname} | {name} | {joined}")

    if offset + len(users) < total:
        lines.append(f"\n➡️ Keyingisi: <code>/users {offset + 30}</code>")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ── ADMIN: Broadcast ──────────────────────────────────────────────────────────
async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Ishlatish: /broadcast <matn>")
        return
    text = parts[1].strip()
    uids = await db.get_all_user_ids()
    if not uids:
        await update.message.reply_text("❌ Foydalanuvchilar yo'q.")
        return
    sent = failed = 0
    smsg = await update.message.reply_text(f"📤 Yuborilmoqda... (0/{len(uids)})")
    for uid in uids:
        try:
            await ctx.bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1
        if (sent + failed) % 50 == 0:
            try:
                await smsg.edit_text(f"📤 Yuborilmoqda... ({sent+failed}/{len(uids)})")
            except Exception:
                pass
    await smsg.edit_text(
        f"✅ <b>Tayyor!</b>\n✔️ Muvaffaqiyatli: {sent}\n❌ Xato: {failed}",
        parse_mode=ParseMode.HTML)


# ── ADMIN: Panel ──────────────────────────────────────────────────────────────
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    stats = await db.get_movie_stats()
    users = await db.get_user_count()
    await update.message.reply_text(
        f"🛠 <b>ADMIN PANEL</b>\n\n"
        f"👥 Foydalanuvchilar: {users:,}\n"
        f"🎬 Kinolar: {stats.get('kinolar', 0)}\n"
        f"📺 Seriallar: {stats.get('seriallar', 0)}\n"
        f"🎠 Multfilmlar: {stats.get('multfilmlar', 0)}\n"
        f"👁 Ko'rishlar: {stats.get('total_views', 0) or 0:,}\n\n"
        "/add — Kino qo'shish\n"
        "/delete &lt;kod&gt; — O'chirish\n"
        "/broadcast &lt;matn&gt; — Hammaga xabar",
        parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════════════════════
# /settings — MAXFIY ADMIN PANELI
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❓ Bunday buyruq yo'q.")
        return ConversationHandler.END
    await update.message.reply_text(
        "🔐 <b>Assalomu aleykum Babalov Bobur Zokirovich</b>\n\n"
        "Iltimos kirishni tasdiqlang.\n\n<i>Parolni kiriting:</i>",
        parse_mode=ParseMode.HTML)
    return SETTINGS_PASSWORD


async def settings_password(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    entered = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    if entered != config.ADMIN_PASSWORD:
        await update.message.reply_text("❌ Noto'g'ri parol. Qayta urinib ko'ring yoki /cancel.")
        return SETTINGS_PASSWORD

    # Parol to'g'ri — barcha buyruqlar + panel bitta xabarda
    await update.message.reply_text(
        "✅ <b>Xush kelibsiz, Admin!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>ADMIN BUYRUQLARI:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎬 /add — Kino qo'shish\n"
        "🗑 /delete &lt;kod&gt; — Kinoni o'chirish\n"
        "📢 /broadcast &lt;matn&gt; — Hammaga xabar\n"
        "📊 /admin — Panel\n"
        "📊 /stats — Statistika\n"
        "👥 /users — Foydalanuvchilar ro'yxati\n"
        "🗑 /set_del_admin &lt;id&gt; — Adminni o'chirish\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ <b>Quyidan sozlamalarni tanlang:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=_settings_kb(),
    )
    return SETTINGS_MENU


def _settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Kanallarni o'zgartirish", callback_data="s_channels")],
        [InlineKeyboardButton("👥 Foydalanuvchilar soni", callback_data="s_ucount")],
        [InlineKeyboardButton("📋 Foydalanuvchilar ro'yxati", callback_data="s_ulist")],
        [InlineKeyboardButton("👤 Yangi admin qo'shish", callback_data="s_addadmin")],
        [InlineKeyboardButton("🗑 Adminni o'chirish", callback_data="s_deladmin")],
        [InlineKeyboardButton("✏️ Xush kelibsiz xabarini tahrirlash", callback_data="s_welcome")],
        [InlineKeyboardButton("📖 Yordam xabarini tahrirlash", callback_data="s_help")],
        [InlineKeyboardButton("❌ Chiqish", callback_data="s_exit")],
    ])


async def settings_menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    data = q.data
    log.info("settings_menu_cb called with data=%s from user=%s", data, q.from_user.id)

    if data == "s_back":
        await q.edit_message_text("⚙️ <b>Sozlamalar paneli</b>",
                                  parse_mode=ParseMode.HTML, reply_markup=_settings_kb())
        return SETTINGS_MENU

    if data == "s_exit":
        ctx.user_data.clear()
        await q.edit_message_text("👋 Chiqildi.")
        return ConversationHandler.END

    if data == "s_ucount":
        total = await db.get_user_count()
        today = await db.get_today_user_count()
        await q.edit_message_text(
            f"👥 <b>Foydalanuvchilar:</b>\n\n📊 Jami: <b>{total:,}</b>\n📅 Bugun: <b>{today:,}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Orqaga", callback_data="s_back")]]))
        return SETTINGS_MENU

    if data == "s_ulist":
        if not db.ready:
            await q.edit_message_text(
                "❌ Database ulanmagan.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Orqaga", callback_data="s_back")]]))
            return SETTINGS_MENU
        users = await db.get_users_list(limit=50)
        if not users:
            await q.edit_message_text(
                "❌ Foydalanuvchilar topilmadi.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Orqaga", callback_data="s_back")]]))
            return SETTINGS_MENU
        lines = []
        for u in users:
            uname = f"@{u['username']}" if u.get("username") else "—"
            name = (u.get("full_name") or "—")[:12]
            joined = u["joined_at"].strftime("%d.%m") if u.get("joined_at") else "—"
            lines.append(f"<code>{u['user_id']}</code> | {uname} | {name} | {joined}")

        # Birinchi xabar edit orqali (max 4096 belgi)
        header = f"📋 <b>Foydalanuvchilar ({len(users)} ta):</b>\n\n"
        first_chunk = header + "\n".join(lines[:20])
        if len(first_chunk) > 4000:
            first_chunk = header + "\n".join(lines[:10])

        await q.edit_message_text(
            first_chunk,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Orqaga", callback_data="s_back")]]))

        # Qolganlarni yangi xabar sifatida
        remaining = lines[20:] if len(header + "\n".join(lines[:20])) <= 4000 else lines[10:]
        chunk = []
        for line in remaining:
            chunk.append(line)
            if len(chunk) >= 20:
                await q.message.reply_text("\n".join(chunk), parse_mode=ParseMode.HTML)
                chunk = []
        if chunk:
            await q.message.reply_text("\n".join(chunk), parse_mode=ParseMode.HTML)
        return SETTINGS_MENU

    if data == "s_channels":
        ch1 = config.REQUIRED_CHANNELS[0] if config.REQUIRED_CHANNELS else "—"
        ch2 = config.REQUIRED_CHANNELS[1] if len(config.REQUIRED_CHANNELS) > 1 else "—"
        await q.edit_message_text(
            f"📢 <b>Hozirgi kanallar:</b>\n1️⃣ {ch1}\n2️⃣ {ch2}\n\n"
            "Yangi kanallarni qatorga yozing:\n<code>@kanal1\n@kanal2</code>",
            parse_mode=ParseMode.HTML)
        ctx.user_data["s_action"] = "channel"
        return SET_CHANNEL

    if data == "s_addadmin":
        ids = _get_admin_ids()
        ids_str = ", ".join(str(i) for i in ids)
        await q.edit_message_text(
            f"👤 <b>Hozirgi adminlar:</b> <code>{ids_str}</code>\n\nYangi admin ID sini yuboring:",
            parse_mode=ParseMode.HTML)
        ctx.user_data["s_action"] = "add_admin"
        return SET_NEW_ADMIN

    if data == "s_deladmin":
        # Faqat super admin
        if q.from_user.id != SUPER_ADMIN_ID:
            await q.message.reply_text("❌ Faqat asosiy admin o'chira oladi!")
            return SETTINGS_MENU
        # Admin listini initialize qilamiz
        if _rt["admin_ids"] is None:
            _rt["admin_ids"] = list(config.ADMIN_IDS)
        removable = [i for i in _rt["admin_ids"] if i != SUPER_ADMIN_ID]
        if not removable:
            await q.message.reply_text("ℹ️ Boshqa admin yo'q.")
            return SETTINGS_MENU
        ids_str = "\n".join(f"• <code>{i}</code>" for i in removable)
        await q.edit_message_text(
            f"🗑 <b>O'chirish uchun admin ID yuboring:</b>\n\n{ids_str}\n\n"
            "<i>Asosiy admin o'chirilmaydi.</i>",
            parse_mode=ParseMode.HTML)
        ctx.user_data["s_action"] = "del_admin"
        return SET_NEW_ADMIN

    if data == "s_welcome":
        cur = _rt["welcome_text"] or "(default)"
        await q.edit_message_text(
            f"✏️ Hozirgi xabar:\n{cur}\n\nYangi xabarni yuboring. {{ism}} — foydalanuvchi ismi.",
            parse_mode=ParseMode.HTML)
        ctx.user_data["s_action"] = "welcome"
        return SET_WELCOME

    if data == "s_help":
        cur = _rt["help_text"] or "(default)"
        await q.edit_message_text(f"📖 Hozirgi xabar:\n{cur}\n\nYangi xabarni yuboring.",
                                  parse_mode=ParseMode.HTML)
        ctx.user_data["s_action"] = "help"
        return SET_HELP_TEXT

    return SETTINGS_MENU


async def settings_set_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    lines = [l.strip() for l in update.message.text.strip().split("\n") if l.strip()]
    chs = [(l if l.startswith("@") else f"@{l}") for l in lines[:2]]
    while len(chs) < 2:
        chs.append("")
    config.REQUIRED_CHANNELS[0] = chs[0]
    if len(config.REQUIRED_CHANNELS) > 1:
        config.REQUIRED_CHANNELS[1] = chs[1]
    else:
        config.REQUIRED_CHANNELS.append(chs[1])
    await update.message.reply_text(
        f"✅ Kanallar yangilandi:\n1️⃣ {chs[0] or '—'}\n2️⃣ {chs[1] or '—'}",
        reply_markup=_settings_kb())
    return SETTINGS_MENU


async def settings_set_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ ID faqat raqam bo'lishi kerak. Qayta yuboring:")
        return SET_NEW_ADMIN

    target = int(text)
    action = ctx.user_data.get("s_action", "add_admin")

    # Admin listini har doim initialize qilamiz
    if _rt["admin_ids"] is None:
        _rt["admin_ids"] = list(config.ADMIN_IDS)

    if action == "add_admin":
        if target not in _rt["admin_ids"]:
            _rt["admin_ids"].append(target)
        ids_str = ", ".join(str(i) for i in _rt["admin_ids"])
        await update.message.reply_text(
            f"✅ Admin qo'shildi: <code>{target}</code>\nJami adminlar: <code>{ids_str}</code>",
            parse_mode=ParseMode.HTML, reply_markup=_settings_kb())

    elif action == "del_admin":
        if target == SUPER_ADMIN_ID:
            await update.message.reply_text("❌ Asosiy adminni o'chirib bo'lmaydi!",
                                            reply_markup=_settings_kb())
        elif target in _rt["admin_ids"]:
            _rt["admin_ids"].remove(target)
            remaining = ", ".join(str(i) for i in _rt["admin_ids"]) or str(SUPER_ADMIN_ID)
            await update.message.reply_text(
                f"✅ Admin o'chirildi: <code>{target}</code>\nQolganlar: <code>{remaining}</code>",
                parse_mode=ParseMode.HTML, reply_markup=_settings_kb())
        else:
            await update.message.reply_text(
                f"❌ <code>{target}</code> ro'yxatda yo'q.",
                parse_mode=ParseMode.HTML, reply_markup=_settings_kb())

    ctx.user_data.pop("s_action", None)
    return SETTINGS_MENU


async def settings_set_welcome(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    _rt["welcome_text"] = update.message.text.strip()
    await update.message.reply_text("✅ Xush kelibsiz xabari yangilandi!", reply_markup=_settings_kb())
    return SETTINGS_MENU


async def settings_set_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    _rt["help_text"] = update.message.text.strip()
    await update.message.reply_text("✅ Yordam xabari yangilandi!", reply_markup=_settings_kb())
    return SETTINGS_MENU


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def post_init(app: Application) -> None:
    await db.connect()
    log.info("KinoDB: %s", "✅" if db.ready else "❌")
    log.info("EduDB: %s", "✅" if db.edu_ready else "yo'q")


def main() -> None:
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi!")

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .read_timeout(120)
        .write_timeout(120)
        .build()
    )

    _fallbacks = [
        CommandHandler("cancel", cmd_cancel),
        CommandHandler("start", cmd_start),
        CommandHandler("settings", cmd_settings),
        CommandHandler("admin", cmd_admin),
        CommandHandler("broadcast", cmd_broadcast),
        CommandHandler("delete", cmd_delete),
        CommandHandler("search", cmd_search),
        CommandHandler("categories", cmd_categories),
        CommandHandler("favorites", cmd_favorites),
        CommandHandler("top", cmd_top),
        CommandHandler("stats", cmd_stats),
        CommandHandler("help", cmd_help),
    ]

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            ADD_FILE: [MessageHandler(filters.VIDEO | filters.Document.ALL, add_file)],
            ADD_POSTER: [
                MessageHandler(filters.PHOTO, add_poster),
                CommandHandler("skip", add_poster_skip),
            ],
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_title)],
            ADD_CATEGORY: [CallbackQueryHandler(add_category_cb, pattern=r"^ac_")],
            ADD_YEAR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_year),
                CommandHandler("skip", add_year_skip),
            ],
            ADD_COUNTRY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_country),
                CommandHandler("skip", add_country_skip),
            ],
            ADD_LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_language)],
            ADD_QUALITY: [CallbackQueryHandler(add_quality_cb, pattern=r"^aq_")],
            ADD_CONFIRM: [
                CallbackQueryHandler(add_confirm_cb, pattern=r"^aconf_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_receive_code),
            ],
            ADD_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_description),
                CommandHandler("skip", add_description_skip),
            ],
            ADD_EDIT: [
                CallbackQueryHandler(add_edit_cb, pattern=r"^ae_"),
                CommandHandler("skip", add_edit_text),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_edit_text),
            ],
        },
        fallbacks=_fallbacks,
        allow_reentry=True,
        conversation_timeout=600,
    )

    search_conv = ConversationHandler(
        entry_points=[CommandHandler("search", cmd_search)],
        states={SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_query_handler)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
        conversation_timeout=120,
    )

    settings_conv = ConversationHandler(
        entry_points=[CommandHandler("settings", cmd_settings)],
        states={
            SETTINGS_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_password)],
            SETTINGS_MENU: [CallbackQueryHandler(settings_menu_cb, pattern=r"^s_")],
            SET_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_set_channel)],
            SET_NEW_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_set_admin)],
            SET_WELCOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_set_welcome)],
            SET_HELP_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_set_help)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
        conversation_timeout=300,
    )

    app.add_handler(settings_conv)
    app.add_handler(add_conv)
    app.add_handler(search_conv)
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("favorites",  cmd_favorites))
    app.add_handler(CommandHandler("top",        cmd_top))
    app.add_handler(CommandHandler("stats",      cmd_stats))
    app.add_handler(CommandHandler("admin",          cmd_admin))
    app.add_handler(CommandHandler("delete",         cmd_delete))
    app.add_handler(CommandHandler("broadcast",      cmd_broadcast))
    app.add_handler(CommandHandler("set_del_admin",  cmd_del_admin))
    app.add_handler(CommandHandler("users",          cmd_users_list))
    app.add_handler(CallbackQueryHandler(category_callback))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\d+$"),
        handle_code,
    ))

    log.info("Bot ishga tushmoqda...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
