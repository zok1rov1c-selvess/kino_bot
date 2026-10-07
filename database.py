"""Kino bot database — PostgreSQL (psycopg2-binary)."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import contextmanager
from typing import Optional

log = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

DATABASE_URL     = os.getenv("DATABASE_URL", "").strip()
EDU_DB_URL       = os.getenv("EDU_BOT_DATABASE_URL", "").strip()


class KinoDB:
    def __init__(self) -> None:
        self._pool = None
        self._edu_pool = None
        self.ready     = False
        self.edu_ready = False

    # ── Ulanish ───────────────────────────────────────────────────────────────
    async def connect(self) -> None:
        if not HAS_PSYCOPG2:
            log.warning("psycopg2 o'rnatilmagan")
            return

        if DATABASE_URL:
            try:
                self._pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1, maxconn=10, dsn=DATABASE_URL
                )
                await asyncio.to_thread(self._init_tables)
                self.ready = True
                log.info("KinoDB ulandi ✅")
            except Exception as e:
                log.error("KinoDB ulanmadi: %s", e)
        else:
            log.warning("DATABASE_URL yo'q")

        if EDU_DB_URL:
            try:
                self._edu_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1, maxconn=5, dsn=EDU_DB_URL
                )
                self.edu_ready = True
                log.info("EduDB ulandi ✅")
            except Exception as e:
                log.warning("EduDB ulanmadi: %s", e)

    @contextmanager
    def _get_conn(self, pool=None):
        p = pool or self._pool
        conn = p.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            p.putconn(conn)

    def _init_tables(self) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
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

                    -- Payme tranzaksiyalari
                    CREATE TABLE IF NOT EXISTS payme_transactions (
                        id             SERIAL PRIMARY KEY,
                        transaction_id TEXT UNIQUE NOT NULL,
                        user_id        BIGINT NOT NULL,
                        tariff         TEXT NOT NULL,
                        amount         BIGINT NOT NULL,
                        state          INTEGER DEFAULT 1,
                        create_time    BIGINT,
                        perform_time   BIGINT DEFAULT 0,
                        cancel_time    BIGINT DEFAULT 0,
                        reason         INTEGER,
                        created_at     TIMESTAMPTZ DEFAULT NOW()
                    );

                    -- Foydalanuvchi obunalari
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        id          SERIAL PRIMARY KEY,
                        user_id     BIGINT UNIQUE NOT NULL,
                        tariff      TEXT NOT NULL,
                        is_vip      BOOLEAN DEFAULT FALSE,
                        expires_at  TIMESTAMPTZ,
                        created_at  TIMESTAMPTZ DEFAULT NOW(),
                        updated_at  TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_movies_code   ON movies(code);
                    CREATE INDEX IF NOT EXISTS idx_movies_type   ON movies(type);
                    CREATE INDEX IF NOT EXISTS idx_movies_genre  ON movies(genre);
                    CREATE INDEX IF NOT EXISTS idx_history_user  ON watch_history(user_id, watched_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_payme_trans   ON payme_transactions(transaction_id);
                    CREATE INDEX IF NOT EXISTS idx_subs_user     ON subscriptions(user_id);
                """)
        log.info("Jadvallar tayyor ✅")

    def _fetchone(self, sql: str, params: tuple = (), pool=None) -> Optional[dict]:
        with self._get_conn(pool) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return dict(row) if row else None

    def _fetchall(self, sql: str, params: tuple = (), pool=None) -> list[dict]:
        with self._get_conn(pool) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]

    def _fetchval(self, sql: str, params: tuple = (), pool=None):
        with self._get_conn(pool) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return row[0] if row else None

    def _execute(self, sql: str, params: tuple = (), pool=None) -> str:
        with self._get_conn(pool) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.statusmessage or ""

    # ── Edu bot tekshiruvi ────────────────────────────────────────────────────
    async def is_edu_user(self, user_id: int) -> bool:
        if not self.edu_ready or not self._edu_pool:
            return True
        try:
            result = await asyncio.to_thread(
                self._fetchval,
                "SELECT 1 FROM users WHERE user_id = %s",
                (user_id,),
                self._edu_pool
            )
            return result is not None
        except Exception as e:
            log.warning("Edu tekshiruvi xato: %s", e)
            return True

    # ── Foydalanuvchi ─────────────────────────────────────────────────────────
    async def upsert_user(self, user_id: int, username: Optional[str], full_name: str) -> None:
        if not self.ready:
            return
        try:
            await asyncio.to_thread(
                self._execute,
                """INSERT INTO users (user_id, username, full_name)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id) DO UPDATE
                   SET username=EXCLUDED.username,
                       full_name=EXCLUDED.full_name,
                       last_seen=NOW()""",
                (user_id, username, full_name)
            )
        except Exception as e:
            log.debug("upsert_user: %s", e)

    async def get_user_count(self) -> int:
        if not self.ready:
            return 0
        result = await asyncio.to_thread(
            self._fetchval, "SELECT COUNT(*) FROM users"
        )
        return result or 0

    async def get_today_user_count(self) -> int:
        if not self.ready:
            return 0
        result = await asyncio.to_thread(
            self._fetchval,
            "SELECT COUNT(*) FROM users WHERE joined_at >= CURRENT_DATE"
        )
        return result or 0

    async def get_all_user_ids(self) -> list[int]:
        if not self.ready:
            return []
        rows = await asyncio.to_thread(
            self._fetchall,
            "SELECT user_id FROM users WHERE is_blocked=FALSE"
        )
        return [r["user_id"] for r in rows]

    async def get_users_list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        if not self.ready:
            return []
        return await asyncio.to_thread(
            self._fetchall,
            "SELECT user_id, username, full_name, joined_at, last_seen "
            "FROM users ORDER BY joined_at DESC LIMIT %s OFFSET %s",
            (limit, offset)
        )

    # ── Kino CRUD ─────────────────────────────────────────────────────────────
    async def add_movie(self, data: dict) -> int:
        if not self.ready:
            raise RuntimeError("DB ulanmagan")
        def _add():
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO movies
                            (code, title, file_id, poster_id, description,
                             year, country, language, quality, type, genre, duration)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (code) DO UPDATE SET
                            title=%s, file_id=%s, poster_id=%s, description=%s,
                            year=%s, country=%s, language=%s, quality=%s,
                            type=%s, genre=%s, duration=%s
                        RETURNING id
                    """, (
                        data["code"], data["title"], data["file_id"],
                        data.get("poster_id", ""), data.get("description", ""),
                        data.get("year"), data.get("country", ""),
                        data.get("language", "O'zbek"), data.get("quality", "HD"),
                        data.get("type", "kino"), data.get("genre", ""),
                        data.get("duration", ""),
                        # ON CONFLICT DO UPDATE SET values
                        data["title"], data["file_id"],
                        data.get("poster_id", ""), data.get("description", ""),
                        data.get("year"), data.get("country", ""),
                        data.get("language", "O'zbek"), data.get("quality", "HD"),
                        data.get("type", "kino"), data.get("genre", ""),
                        data.get("duration", ""),
                    ))
                    return cur.fetchone()[0]
        return await asyncio.to_thread(_add)

    async def get_movie_by_code(self, code: str) -> Optional[dict]:
        if not self.ready:
            return None
        return await asyncio.to_thread(
            self._fetchone,
            "SELECT * FROM movies WHERE code=%s AND is_active=TRUE",
            (code,)
        )

    async def get_movie_by_id(self, movie_id: int) -> Optional[dict]:
        if not self.ready:
            return None
        return await asyncio.to_thread(
            self._fetchone,
            "SELECT * FROM movies WHERE id=%s AND is_active=TRUE",
            (movie_id,)
        )

    async def increment_views(self, movie_id: int) -> None:
        if not self.ready:
            return
        await asyncio.to_thread(
            self._execute,
            "UPDATE movies SET views=views+1 WHERE id=%s",
            (movie_id,)
        )

    async def log_watch(self, user_id: int, movie_id: int) -> None:
        if not self.ready:
            return
        try:
            await asyncio.to_thread(
                self._execute,
                "INSERT INTO watch_history (user_id,movie_id) VALUES (%s,%s)",
                (user_id, movie_id)
            )
        except Exception:
            pass

    async def search_movies(self, query: str, limit: int = 10) -> list[dict]:
        if not self.ready:
            return []
        return await asyncio.to_thread(
            self._fetchall,
            """SELECT id, code, title, type, genre, year, quality, views
               FROM movies
               WHERE is_active=TRUE AND (
                   LOWER(title) LIKE LOWER(%s) OR code = %s
               )
               ORDER BY views DESC LIMIT %s""",
            (f"%{query}%", query, limit)
        )

    async def get_movies_by_type(self, movie_type: str, offset: int = 0,
                                  limit: int = 8) -> list[dict]:
        if not self.ready:
            return []
        return await asyncio.to_thread(
            self._fetchall,
            """SELECT id, code, title, type, genre, year, quality, views
               FROM movies WHERE is_active=TRUE AND type=%s
               ORDER BY added_at DESC LIMIT %s OFFSET %s""",
            (movie_type, limit, offset)
        )

    async def get_movies_by_genre(self, genre: str, offset: int = 0,
                                   limit: int = 8) -> list[dict]:
        if not self.ready:
            return []
        return await asyncio.to_thread(
            self._fetchall,
            """SELECT id, code, title, type, genre, year, quality, views
               FROM movies WHERE is_active=TRUE AND LOWER(genre) LIKE LOWER(%s)
               ORDER BY views DESC LIMIT %s OFFSET %s""",
            (f"%{genre}%", limit, offset)
        )

    async def get_top_movies(self, limit: int = 10) -> list[dict]:
        if not self.ready:
            return []
        return await asyncio.to_thread(
            self._fetchall,
            """SELECT id, code, title, type, genre, year, views
               FROM movies WHERE is_active=TRUE
               ORDER BY views DESC LIMIT %s""",
            (limit,)
        )

    async def get_movie_stats(self) -> dict:
        if not self.ready:
            return {}
        result = await asyncio.to_thread(
            self._fetchone,
            """SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN type='kino'     THEN 1 ELSE 0 END) AS kinolar,
                SUM(CASE WHEN type='serial'   THEN 1 ELSE 0 END) AS seriallar,
                SUM(CASE WHEN type='multfilm' THEN 1 ELSE 0 END) AS multfilmlar,
                SUM(views) AS total_views
               FROM movies WHERE is_active=TRUE"""
        )
        return result or {}

    # ── Sevimlilar ────────────────────────────────────────────────────────────
    async def add_favorite(self, user_id: int, movie_id: int) -> bool:
        if not self.ready:
            return False
        try:
            await asyncio.to_thread(
                self._execute,
                "INSERT INTO favorites (user_id,movie_id) VALUES (%s,%s)",
                (user_id, movie_id)
            )
            return True
        except Exception:
            return False

    async def remove_favorite(self, user_id: int, movie_id: int) -> None:
        if not self.ready:
            return
        await asyncio.to_thread(
            self._execute,
            "DELETE FROM favorites WHERE user_id=%s AND movie_id=%s",
            (user_id, movie_id)
        )

    async def is_favorite(self, user_id: int, movie_id: int) -> bool:
        if not self.ready:
            return False
        result = await asyncio.to_thread(
            self._fetchval,
            "SELECT 1 FROM favorites WHERE user_id=%s AND movie_id=%s",
            (user_id, movie_id)
        )
        return result is not None

    async def get_favorites(self, user_id: int) -> list[dict]:
        if not self.ready:
            return []
        return await asyncio.to_thread(
            self._fetchall,
            """SELECT m.id, m.code, m.title, m.type, m.genre, m.year, m.views
               FROM favorites f JOIN movies m ON f.movie_id=m.id
               WHERE f.user_id=%s AND m.is_active=TRUE
               ORDER BY f.added_at DESC""",
            (user_id,)
        )

    # ── Seriyalar ─────────────────────────────────────────────────────────────
    async def add_episode(self, movie_id: int, season: int,
                          episode: int, file_id: str, title: str = "") -> None:
        if not self.ready:
            return
        try:
            await asyncio.to_thread(
                self._execute,
                """INSERT INTO episodes (movie_id, season, episode, file_id, title)
                   VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (movie_id, season, episode, file_id, title)
            )
        except Exception:
            pass

    async def get_episodes(self, movie_id: int, season: int = 1) -> list[dict]:
        if not self.ready:
            return []
        return await asyncio.to_thread(
            self._fetchall,
            "SELECT * FROM episodes WHERE movie_id=%s AND season=%s ORDER BY episode",
            (movie_id, season)
        )

    async def delete_movie(self, code: str) -> bool:
        if not self.ready:
            return False
        status = await asyncio.to_thread(
            self._execute,
            "UPDATE movies SET is_active=FALSE WHERE code=%s",
            (code,)
        )
        return status != "UPDATE 0"

    # ── Payme: Tranzaksiya ────────────────────────────────────────────────────
    async def payme_create_transaction(self, transaction_id: str, user_id: int,
                                       tariff: str, amount: int, create_time: int) -> None:
        if not self.ready:
            return
        await asyncio.to_thread(
            self._execute,
            """INSERT INTO payme_transactions
               (transaction_id, user_id, tariff, amount, state, create_time)
               VALUES (%s, %s, %s, %s, 1, %s)
               ON CONFLICT (transaction_id) DO NOTHING""",
            (transaction_id, user_id, tariff, amount, create_time)
        )

    async def payme_get_transaction(self, transaction_id: str) -> Optional[dict]:
        if not self.ready:
            return None
        return await asyncio.to_thread(
            self._fetchone,
            "SELECT * FROM payme_transactions WHERE transaction_id=%s",
            (transaction_id,)
        )

    async def payme_perform_transaction(self, transaction_id: str, perform_time: int) -> None:
        if not self.ready:
            return
        await asyncio.to_thread(
            self._execute,
            """UPDATE payme_transactions
               SET state=2, perform_time=%s WHERE transaction_id=%s""",
            (perform_time, transaction_id)
        )

    async def payme_cancel_transaction(self, transaction_id: str,
                                       cancel_time: int, reason: int) -> None:
        if not self.ready:
            return
        await asyncio.to_thread(
            self._execute,
            """UPDATE payme_transactions
               SET state=-1, cancel_time=%s, reason=%s WHERE transaction_id=%s""",
            (cancel_time, reason, transaction_id)
        )

    async def payme_get_statement(self, from_time: int, to_time: int) -> list[dict]:
        if not self.ready:
            return []
        return await asyncio.to_thread(
            self._fetchall,
            """SELECT * FROM payme_transactions
               WHERE create_time >= %s AND create_time <= %s
               ORDER BY create_time""",
            (from_time, to_time)
        )

    # ── Obuna ────────────────────────────────────────────────────────────────
    async def set_subscription(self, user_id: int, tariff: str,
                                is_vip: bool, expires_at) -> None:
        """Foydalanuvchiga obuna berish."""
        if not self.ready:
            return
        await asyncio.to_thread(
            self._execute,
            """INSERT INTO subscriptions (user_id, tariff, is_vip, expires_at)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (user_id) DO UPDATE SET
                 tariff=%s, is_vip=%s, expires_at=%s, updated_at=NOW()""",
            (user_id, tariff, is_vip, expires_at,
             tariff, is_vip, expires_at)
        )

    async def get_subscription(self, user_id: int) -> Optional[dict]:
        """Foydalanuvchi obunasini tekshirish."""
        if not self.ready:
            return None
        return await asyncio.to_thread(
            self._fetchone,
            """SELECT * FROM subscriptions
               WHERE user_id=%s AND (expires_at IS NULL OR expires_at > NOW())""",
            (user_id,)
        )

    async def is_subscribed(self, user_id: int) -> bool:
        """Foydalanuvchi aktiv obunasi bormi."""
        sub = await self.get_subscription(user_id)
        return sub is not None


db = KinoDB()
