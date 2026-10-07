"""Payme Merchant API webhook serveri."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from aiohttp import web

import config
from database import db

log = logging.getLogger(__name__)

# ── Payme xato kodlari ────────────────────────────────────────────────────────
ERR_INVALID_AMOUNT        = -31001
ERR_TRANSACTION_NOT_FOUND = -31003
ERR_INVALID_STATE         = -31008
ERR_ALREADY_DONE          = -31060
ERR_METHOD_NOT_FOUND      = -32601
ERR_FORBIDDEN             = -32504
ERR_INTERNAL              = -32400

# Tranzaksiya holatlari
STATE_CREATED   =  1
STATE_COMPLETED =  2
STATE_CANCELLED = -1
STATE_CANCEL_AFTER_COMPLETE = -2


def _error(code: int, message: str, data: dict | None = None) -> dict:
    err: dict = {"code": code, "message": {"uz": message, "ru": message, "en": message}}
    if data:
        err["data"] = data
    return {"error": err}


def _result(result: dict) -> dict:
    return {"result": result}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _check_auth(request: web.Request) -> bool:
    """Basic Auth tekshirish."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        _, password = decoded.split(":", 1)
        expected_key = config.PAYME_TEST_KEY if config.PAYME_TEST_MODE else config.PAYME_KEY
        return password == expected_key
    except Exception:
        return False


# ── Handler ───────────────────────────────────────────────────────────────────

async def handle_payme(request: web.Request) -> web.Response:
    """Barcha Payme so'rovlarini qabul qiladi."""
    if not _check_auth(request):
        body = _error(ERR_FORBIDDEN, "Ruxsat yo'q")
        return web.Response(
            text=json.dumps(body), content_type="application/json", status=401
        )

    try:
        data = await request.json()
    except Exception:
        return web.Response(
            text=json.dumps(_error(ERR_INTERNAL, "JSON xato")),
            content_type="application/json", status=400
        )

    method = data.get("method", "")
    params = data.get("params", {})
    req_id = data.get("id", 1)

    log.info("Payme request: method=%s params=%s", method, params)

    handlers = {
        "CheckPerformTransaction": check_perform_transaction,
        "CreateTransaction":       create_transaction,
        "PerformTransaction":      perform_transaction,
        "CancelTransaction":       cancel_transaction,
        "CheckTransaction":        check_transaction,
        "GetStatement":            get_statement,
    }

    if method not in handlers:
        result = _error(ERR_METHOD_NOT_FOUND, f"Method not found: {method}")
    else:
        result = await handlers[method](params)

    response_body = {"id": req_id}
    response_body.update(result)

    return web.Response(
        text=json.dumps(response_body),
        content_type="application/json"
    )


# ── Metodlar ──────────────────────────────────────────────────────────────────

async def check_perform_transaction(params: dict) -> dict:
    """To'lovni bajarish mumkinligini tekshiradi."""
    account = params.get("account", {})
    user_id = account.get("user_id")
    tariff  = account.get("tariff", "")
    amount  = params.get("amount", 0)

    if not user_id or not tariff:
        return _error(ERR_INVALID_AMOUNT, "user_id yoki tariff yo'q")

    tariff_info = config.PAYME_TARIFFS.get(tariff)
    if not tariff_info:
        return _error(ERR_INVALID_AMOUNT, "Noto'g'ri tariff")

    if amount != tariff_info["price"]:
        return _error(ERR_INVALID_AMOUNT,
                      f"Summa noto'g'ri. Kutilgan: {tariff_info['price']} tiyin")

    return _result({
        "allow": True,
        "detail": {
            "receipt_type": 0,
            "items": [{
                "title":        tariff_info["label"],
                "price":        tariff_info["price"],
                "count":        1,
                "code":         config.PAYME_MXIK,
                "package_code": config.PAYME_PACKAGE_CODE,
                "vat_percent":  12,
            }]
        }
    })


async def create_transaction(params: dict) -> dict:
    """Tranzaksiya yaratadi."""
    account        = params.get("account", {})
    user_id        = account.get("user_id")
    tariff         = account.get("tariff", "")
    transaction_id = params.get("id", "")
    amount         = params.get("amount", 0)
    create_time    = params.get("time", _now_ms())

    tariff_info = config.PAYME_TARIFFS.get(tariff)
    if not tariff_info:
        return _error(ERR_INVALID_AMOUNT, "Noto'g'ri tariff")

    if amount != tariff_info["price"]:
        return _error(ERR_INVALID_AMOUNT, "Summa noto'g'ri")

    # Mavjud tranzaksiyani tekshirish
    existing = await db.payme_get_transaction(transaction_id)
    if existing:
        if existing["state"] == STATE_CREATED:
            return _result({
                "create_time": existing["create_time"],
                "transaction": str(existing["id"]),
                "state":       STATE_CREATED,
            })
        return _error(ERR_INVALID_STATE, "Tranzaksiya allaqachon mavjud")

    # Yangi tranzaksiya yaratish
    await db.payme_create_transaction(
        transaction_id=transaction_id,
        user_id=int(user_id),
        tariff=tariff,
        amount=amount,
        create_time=create_time,
    )

    tx = await db.payme_get_transaction(transaction_id)
    return _result({
        "create_time": create_time,
        "transaction": str(tx["id"]) if tx else "0",
        "state":       STATE_CREATED,
    })


async def perform_transaction(params: dict) -> dict:
    """To'lovni tasdiqlaydi va obuna beradi."""
    transaction_id = params.get("id", "")
    perform_time   = _now_ms()

    tx = await db.payme_get_transaction(transaction_id)
    if not tx:
        return _error(ERR_TRANSACTION_NOT_FOUND, "Tranzaksiya topilmadi")

    if tx["state"] == STATE_COMPLETED:
        return _result({
            "perform_time": tx["perform_time"],
            "transaction":  str(tx["id"]),
            "state":        STATE_COMPLETED,
        })

    if tx["state"] != STATE_CREATED:
        return _error(ERR_INVALID_STATE, "Tranzaksiya bekor qilingan")

    # Tranzaksiyani tasdiqlash
    await db.payme_perform_transaction(transaction_id, perform_time)

    # Obuna berish
    tariff_info = config.PAYME_TARIFFS.get(tx["tariff"], {})
    days = tariff_info.get("days")
    is_vip = days is None
    expires_at = None
    if days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=days)

    await db.set_subscription(
        user_id=tx["user_id"],
        tariff=tx["tariff"],
        is_vip=is_vip,
        expires_at=expires_at,
    )

    log.info("✅ To'lov tasdiqlandi: user=%s tariff=%s", tx["user_id"], tx["tariff"])

    # Botga xabar yuborish (ixtiyoriy — token kerak)
    try:
        from telegram import Bot
        from telegram.constants import ParseMode
        bot_token = config.BOT_TOKEN
        if bot_token:
            bot = Bot(token=bot_token)
            label = tariff_info.get("label", tx["tariff"])
            msg = (
                f"✅ <b>To'lov qabul qilindi!</b>\n\n"
                f"📦 Tarif: {label}\n"
                f"{'♾ Cheksiz obuna faollashtirildi!' if is_vip else f'📅 Obuna {days} kun davomida amal qiladi.'}"
            )
            await bot.send_message(chat_id=tx["user_id"], text=msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        log.warning("Bot xabari yuborilmadi: %s", e)

    return _result({
        "perform_time": perform_time,
        "transaction":  str(tx["id"]),
        "state":        STATE_COMPLETED,
    })


async def cancel_transaction(params: dict) -> dict:
    """Tranzaksiyani bekor qiladi."""
    transaction_id = params.get("id", "")
    reason         = params.get("reason", 0)
    cancel_time    = _now_ms()

    tx = await db.payme_get_transaction(transaction_id)
    if not tx:
        return _error(ERR_TRANSACTION_NOT_FOUND, "Tranzaksiya topilmadi")

    if tx["state"] == STATE_COMPLETED:
        # Tasdiqlangan to'lovni bekor qilish
        await db.payme_cancel_transaction(transaction_id, cancel_time, reason)
        return _result({
            "cancel_time": cancel_time,
            "transaction": str(tx["id"]),
            "state":       STATE_CANCEL_AFTER_COMPLETE,
        })

    if tx["state"] in (STATE_CANCELLED, STATE_CANCEL_AFTER_COMPLETE):
        return _result({
            "cancel_time": tx["cancel_time"],
            "transaction": str(tx["id"]),
            "state":       tx["state"],
        })

    await db.payme_cancel_transaction(transaction_id, cancel_time, reason)
    return _result({
        "cancel_time": cancel_time,
        "transaction": str(tx["id"]),
        "state":       STATE_CANCELLED,
    })


async def check_transaction(params: dict) -> dict:
    """Tranzaksiya holatini tekshiradi."""
    transaction_id = params.get("id", "")
    tx = await db.payme_get_transaction(transaction_id)
    if not tx:
        return _error(ERR_TRANSACTION_NOT_FOUND, "Tranzaksiya topilmadi")

    return _result({
        "create_time":  tx["create_time"] or 0,
        "perform_time": tx["perform_time"] or 0,
        "cancel_time":  tx["cancel_time"] or 0,
        "transaction":  str(tx["id"]),
        "state":        tx["state"],
        "reason":       tx["reason"],
    })


async def get_statement(params: dict) -> dict:
    """Tranzaksiyalar ro'yxatini qaytaradi."""
    from_time = params.get("from", 0)
    to_time   = params.get("to", _now_ms())

    transactions = await db.payme_get_statement(from_time, to_time)
    result = []
    for tx in transactions:
        result.append({
            "id":           tx["transaction_id"],
            "time":         tx["create_time"] or 0,
            "amount":       tx["amount"],
            "account": {
                "user_id": str(tx["user_id"]),
                "tariff":  tx["tariff"],
            },
            "create_time":  tx["create_time"] or 0,
            "perform_time": tx["perform_time"] or 0,
            "cancel_time":  tx["cancel_time"] or 0,
            "transaction":  str(tx["id"]),
            "state":        tx["state"],
            "reason":       tx["reason"],
            "detail": {
                "receipt_type": 0,
                "items": [{
                    "title":        config.PAYME_TARIFFS.get(tx["tariff"], {}).get("label", "Obuna"),
                    "price":        tx["amount"],
                    "count":        1,
                    "code":         config.PAYME_MXIK,
                    "package_code": config.PAYME_PACKAGE_CODE,
                    "vat_percent":  12,
                }]
            }
        })

    return _result({"transactions": result})


# ── Server ishga tushirish ────────────────────────────────────────────────────

async def start_webhook_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Payme webhook serverini ishga tushiradi."""
    app = web.Application()
    app.router.add_post("/payme", handle_payme)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("Payme webhook server: http://%s:%d/payme", host, port)
