"""Kino bot database — PostgreSQL."""
from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

DATABASE_URL     = os.getenv("DATABASE_URL", "").strip()
EDU_DB_URL       = os.getenv("EDU_BOT_DATABASE_URL", "").strip()


class KinoDB:
    def __init__(self) -> None:
        self._pool: Optional[object] = None
        self._edu_pool: Optional[object] = None
        self.ready     = False
        self.edu_ready = False

    # ── Ulanish ───────────────────────────────────────────────────────────────
    async def connect(self) -> None:
        if not HAS_ASYNCPG:
            log.warning("asyncpg o'rnatilmagan")
            return

        # Kino bot DB
        if DATABASE_URL:
            try:
                url = DATABASE_URL
                if "railway" in url and "sslmode" not in url:
                    url += "?sslmode=require"
                self._pool = await asyncpg.create_pool(url, min_size=1, max_size=10)
                await self._init_tables()
                self.ready = True
                log.info("KinoDB ulandi ✅")
            except Exception as e:
                log.error("KinoDB ulanmadi: %s", e)
        else:
            log.warning("DATABASE_URL yo'q — kino DB o'chirilgan")

        # Edu bot DB (faqat agar URL berilgan bo'lsa)
        if EDU_DB_URL:
            try:
                edu_url = EDU_DB_URL
                if "railway" in edu_url and "sslmode" not in edu_url:
                    edu_url += "?sslmode=require"
                self._edu_pool = await asyncpg.create_pool(edu_url, min_size=1, max_size=5)
                self.edu_ready = True
                log.info("EduDB ulandi ✅")
            except Exception as e:
                log.warning("EduDB ulanmadi: %s", e)

    async def _init_tables(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id    BIGINT PRIMARY KEY,
                    username   TEXT,
                    full_name  TEXT,
                    joined_at  TIMESTAMPTZ DEFAULT NOW(),
                    last_seen  TIMESTAMPTZ DEFAULT NOW(),
                    is_blocked BOOLEAN DEFAULT FALSE
                );

                CREATE TABLE IF NOT EXISTS movies (
                    id          SERIAL PRIMARY KEY,
                    code        TEXT UNIQUE NOT NULL,
                    title       TEXT NOT NULL,
                    file_id     TEXT NOT NULL,
                    poster_id   TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    year        INTEGER,
                    country     TEXT DEFAULT '',
                    language    TEXT DEFAULT 'O''zbek',
                    quality     TEXT DEFAULT 'HD',
                    type        TEXT DEFAULT 'kino',
                    genre       TEXT DEFAULT '',
                    duration    TEXT DEFAULT '',
                    views       INTEGER DEFAULT 0,
                    added_at    TIMESTAMPTZ DEFAULT NOW(),
                    is_active   BOOLEAN DEFAULT TRUE
                );

                CREATE TABLE IF NOT EXISTS episodes (
                    id         SERIAL PRIMARY KEY,
                    movie_id   INTEGER REFERENCES movies(id) ON DELETE CASCADE,
                    season     INTEGER DEFAULT 1,
                    episode    INTEGER NOT NULL,
                    file_id    TEXT NOT NULL,
                    title      TEXT DEFAULT '',
                    added_at   TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS watch_history (
                    id         SERIAL PRIMARY KEY,
                    user_id    BIGINT REFERENCES users(user_id),
                    movie_id   INTEGER REFERENCES movies(id),
                    watched_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS favorites (
                    user_id    BIGINT REFERENCES users(user_id),
                    movie_id   INTEGER REFERENCES movies(id),
                    added_at   TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (user_id, movie_id)
                );

                CREATE INDEX IF NOT EXISTS idx_movies_code   ON movies(code);
                CREATE INDEX IF NOT EXISTS idx_movies_type   ON movies(type);
                CREATE INDEX IF NOT EXISTS idx_movies_genre  ON movies(genre);
                CREATE INDEX IF NOT EXISTS idx_movies_search ON movies USING gin(to_tsvector('simple', title));
                CREATE INDEX IF NOT EXISTS idx_history_user  ON watch_history(user_id, watched_at DESC);
            """)
        log.info("Jadvallar tayyor ✅")

    # ── Edu bot tekshiruvi ────────────────────────────────────────────────────
    async def is_edu_user(self, user_id: int) -> bool:
        """Foydalanuvchi edu_botga /start bosganmi tekshiradi."""
        if not self.edu_ready or not self._edu_pool:
            # Edu DB ulanmagan — tekshiruvni o'tkazib yuborish (ruxsat beriladi)
            log.warning("EduDB ulanmagan — edu tekshiruvi o'tkazib yuborildi")
            return True
        try:
            async with self._edu_pool.acquire() as conn:
                # Edu bot users jadvalidagi standart tuzilish
                result = await conn.fetchval(
                    "SELECT 1 FROM users WHERE user_id = $1", user_id
                )
                return result is not None
        except Exception as e:
            log.warning("Edu tekshiruvi xato: %s", e)
            return True  # Xato bo'lsa ruxsat beriladi

    # ── Foydalanuvchi ─────────────────────────────────────────────────────────
    async def upsert_user(self, user_id: int, username: str | None, full_name: str) -> None:
        if not self.ready:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO users (user_id, username, full_name)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id) DO UPDATE
                        SET username  = EXCLUDED.username,
                            full_name = EXCLUDED.full_name,
                            last_seen = NOW()
                """, user_id, username, full_name)
        except Exception as e:
            log.debug("upsert_user: %s", e)

    async def get_user_count(self) -> int:
        if not self.ready:
            return 0
        async with self._pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM users") or 0

    async def get_today_user_count(self) -> int:
        """Bugun qo'shilgan foydalanuvchilar soni."""
        if not self.ready:
            return 0
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE joined_at >= CURRENT_DATE"
            ) or 0

    async def get_all_user_ids(self) -> list[int]:
        if not self.ready:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id FROM users WHERE is_blocked=FALSE")
            return [r["user_id"] for r in rows]

    async def get_users_list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Username va ismlari bilan foydalanuvchilar ro'yxati."""
        if not self.ready:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id, username, full_name, joined_at, last_seen
                FROM users
                ORDER BY joined_at DESC
                LIMIT $1 OFFSET $2
            """, limit, offset)
            return [dict(r) for r in rows]

    # ── Kino CRUD ─────────────────────────────────────────────────────────────
    async def add_movie(self, data: dict) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO movies
                    (code, title, file_id, poster_id, description,
                     year, country, language, quality, type, genre, duration)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT (code) DO UPDATE SET
                    title=$2, file_id=$3, poster_id=$4, description=$5,
                    year=$6, country=$7, language=$8, quality=$9,
                    type=$10, genre=$11, duration=$12
                RETURNING id
            """,
            data["code"], data["title"], data["file_id"],
            data.get("poster_id", ""), data.get("description", ""),
            data.get("year"), data.get("country", ""),
            data.get("language", "O'zbek"), data.get("quality", "HD"),
            data.get("type", "kino"), data.get("genre", ""),
            data.get("duration", ""))
            return row["id"]

    async def get_movie_by_code(self, code: str) -> dict | None:
        if not self.ready:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM movies WHERE code=$1 AND is_active=TRUE", code
            )
            return dict(row) if row else None

    async def get_movie_by_id(self, movie_id: int) -> dict | None:
        if not self.ready:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM movies WHERE id=$1 AND is_active=TRUE", movie_id
            )
            return dict(row) if row else None

    async def increment_views(self, movie_id: int) -> None:
        if not self.ready:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE movies SET views=views+1 WHERE id=$1", movie_id
            )

    async def log_watch(self, user_id: int, movie_id: int) -> None:
        if not self.ready:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO watch_history (user_id,movie_id) VALUES ($1,$2)",
                    user_id, movie_id
                )
        except Exception:
            pass

    async def search_movies(self, query: str, limit: int = 10) -> list[dict]:
        if not self.ready:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, code, title, type, genre, year, quality, views
                FROM movies
                WHERE is_active=TRUE AND (
                    LOWER(title) LIKE LOWER($1) OR code = $2
                )
                ORDER BY views DESC
                LIMIT $3
            """, f"%{query}%", query, limit)
            return [dict(r) for r in rows]

    async def get_movies_by_type(self, movie_type: str, offset: int = 0,
                                  limit: int = 8) -> list[dict]:
        if not self.ready:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, code, title, type, genre, year, quality, views
                FROM movies WHERE is_active=TRUE AND type=$1
                ORDER BY added_at DESC
                LIMIT $2 OFFSET $3
            """, movie_type, limit, offset)
            return [dict(r) for r in rows]

    async def get_movies_by_genre(self, genre: str, offset: int = 0,
                                   limit: int = 8) -> list[dict]:
        if not self.ready:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, code, title, type, genre, year, quality, views
                FROM movies WHERE is_active=TRUE AND LOWER(genre) LIKE LOWER($1)
                ORDER BY views DESC LIMIT $2 OFFSET $3
            """, f"%{genre}%", limit, offset)
            return [dict(r) for r in rows]

    async def get_top_movies(self, limit: int = 10) -> list[dict]:
        if not self.ready:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, code, title, type, genre, year, views
                FROM movies WHERE is_active=TRUE
                ORDER BY views DESC LIMIT $1
            """, limit)
            return [dict(r) for r in rows]

    async def get_movie_stats(self) -> dict:
        if not self.ready:
            return {}
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN type='kino'     THEN 1 ELSE 0 END) AS kinolar,
                    SUM(CASE WHEN type='serial'   THEN 1 ELSE 0 END) AS seriallar,
                    SUM(CASE WHEN type='multfilm' THEN 1 ELSE 0 END) AS multfilmlar,
                    SUM(views) AS total_views
                FROM movies WHERE is_active=TRUE
            """)
            return dict(row) if row else {}

    # ── Sevimlilar ────────────────────────────────────────────────────────────
    async def add_favorite(self, user_id: int, movie_id: int) -> bool:
        if not self.ready:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO favorites (user_id,movie_id) VALUES ($1,$2)",
                    user_id, movie_id
                )
            return True
        except Exception:
            return False

    async def remove_favorite(self, user_id: int, movie_id: int) -> None:
        if not self.ready:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM favorites WHERE user_id=$1 AND movie_id=$2",
                user_id, movie_id
            )

    async def is_favorite(self, user_id: int, movie_id: int) -> bool:
        if not self.ready:
            return False
        async with self._pool.acquire() as conn:
            r = await conn.fetchval(
                "SELECT 1 FROM favorites WHERE user_id=$1 AND movie_id=$2",
                user_id, movie_id
            )
            return bool(r)

    async def get_favorites(self, user_id: int) -> list[dict]:
        if not self.ready:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT m.id, m.code, m.title, m.type, m.genre, m.year, m.views
                FROM favorites f JOIN movies m ON f.movie_id=m.id
                WHERE f.user_id=$1 AND m.is_active=TRUE
                ORDER BY f.added_at DESC
            """, user_id)
            return [dict(r) for r in rows]

    # ── Seriyalar ─────────────────────────────────────────────────────────────
    async def add_episode(self, movie_id: int, season: int,
                          episode: int, file_id: str, title: str = "") -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO episodes (movie_id, season, episode, file_id, title)
                VALUES ($1,$2,$3,$4,$5)
                ON CONFLICT DO NOTHING
            """, movie_id, season, episode, file_id, title)

    async def get_episodes(self, movie_id: int, season: int = 1) -> list[dict]:
        if not self.ready:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM episodes
                WHERE movie_id=$1 AND season=$2
                ORDER BY episode
            """, movie_id, season)
            return [dict(r) for r in rows]

    async def delete_movie(self, code: str) -> bool:
        if not self.ready:
            return False
        async with self._pool.acquire() as conn:
            r = await conn.execute(
                "UPDATE movies SET is_active=FALSE WHERE code=$1", code
            )
            return r != "UPDATE 0"


db = KinoDB()
