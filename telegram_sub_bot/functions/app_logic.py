"""
app_logic.py
------------
المنطق الأساسي لكل الدوال (مستقل عن Firebase Functions حتى يسهل اختباره):
- استقبال تحديثات تليجرام (Webhook)
- التحقق من دفع ميسر وتفعيل الاشتراك
- صفحة الرجوع بعد الدفع
- /config.js للموقع
- المهام المجدولة
"""

from __future__ import annotations

import datetime as dt
import hmac
import json
import logging
from typing import Optional

from telegram import Update
from telegram.ext import Application

import bot_handlers
import firebase_db as db
import moyasar_client
from config import PLANS, settings

logger = logging.getLogger(__name__)

_app: Optional[Application] = None
_app_token: str = ""

ALLOWED_UPDATES = ["message", "callback_query", "my_chat_member"]


async def get_application() -> Application:
    """تطبيق البوت (يُنشأ مرة واحدة لكل نسخة من الدالة)."""
    global _app, _app_token
    if _app is not None and _app_token == settings.BOT_TOKEN:
        return _app
    db.init_firebase()
    app = (
        Application.builder()
        .token(settings.BOT_TOKEN)
        .base_url(f"{settings.TELEGRAM_API_BASE}/bot")
        .base_file_url(f"{settings.TELEGRAM_API_BASE}/file/bot")
        .updater(None)
        .build()
    )
    bot_handlers.register_handlers(app)

    async def _on_error(update, context):
        logger.error("خطأ أثناء معالجة تحديث تليجرام", exc_info=context.error)

    app.add_error_handler(_on_error)
    await app.initialize()
    _app, _app_token = app, settings.BOT_TOKEN
    return app


# ---------------------------------------------------------------------------
# تليجرام
# ---------------------------------------------------------------------------

def telegram_secret_ok(header_value: Optional[str]) -> bool:
    return bool(settings.BOT_TOKEN) and hmac.compare_digest(header_value or "", settings.TELEGRAM_WEBHOOK_SECRET)


async def process_telegram_update(data: dict) -> None:
    app = await get_application()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)


async def ensure_webhook() -> dict:
    """يضبط رابط الـ Webhook في تليجرام إن لم يكن مضبوطاً (يُستدعى كل ساعة وعند الإعداد)."""
    app = await get_application()
    url = f"{settings.API_BASE_URL}/telegram/webhook"
    info = await app.bot.get_webhook_info()
    if info.url != url:
        await app.bot.set_webhook(
            url=url,
            secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
            allowed_updates=ALLOWED_UPDATES,
            max_connections=40,
        )
        logger.info("تم ضبط Webhook تليجرام على %s", url)
        return {"changed": True, "url": url}
    return {"changed": False, "url": url, "pending": info.pending_update_count, "last_error": info.last_error_message}


async def delete_message(chat_id: int, message_id: int) -> None:
    app = await get_application()
    try:
        await app.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass  # حُذفت مسبقاً


# ---------------------------------------------------------------------------
# ميسر
# ---------------------------------------------------------------------------

async def verify_and_activate(invoice_id: str) -> str:
    """
    لا نثق بأي بيانات واردة: نجلب الفاتورة من ميسر مباشرة بمفتاحنا السري،
    ونتأكد أنها مدفوعة وأن المبلغ يطابق المبلغ المحفوظ عندنا.
    """
    db.init_firebase()
    sub = await db.get_subscription(invoice_id)
    if sub is None:
        return "not_found"
    if sub.get("status") in ("active", "expired"):
        return "already"

    invoice = await moyasar_client.fetch_invoice(invoice_id)
    if invoice.get("status") != "paid":
        return "not_paid"
    expected = int(round(float(sub["amount"]) * 100))
    if int(invoice.get("amount", 0)) != expected or invoice.get("currency", "SAR") != "SAR":
        logger.error("مبلغ الفاتورة %s لا يطابق المتوقع (%s)", invoice_id, expected)
        return "amount_mismatch"

    payment = moyasar_client.paid_payment(invoice) or {}
    source = payment.get("source") if isinstance(payment.get("source"), dict) else {}
    status, data = await db.activate_subscription(invoice_id, payment.get("id"), source.get("phone"))

    if status == "ok":
        try:
            app = await get_application()
            await app.bot.send_message(
                chat_id=int(data["telegramUserId"]),
                text=(
                    "✅ تم تفعيل اشتراكك بنجاح!\n\n"
                    f"👥 المجموعة: {data.get('groupTitle', '')}\n"
                    f"📦 الباقة: {data.get('planName', '')}\n"
                    f"📅 صالح حتى: {data['endDate'].strftime('%Y-%m-%d')}\n\n"
                    "يمكنك الآن النشر داخل المجموعة بكل حرية 🎉"
                ),
            )
        except Exception:
            logger.warning("تعذر إرسال رسالة التفعيل للمستخدم %s", data.get("telegramUserId"))
    return status


async def handle_moyasar_webhook(payload: dict, header_token: Optional[str]) -> tuple[int, dict]:
    token = header_token or payload.get("secret_token") or ""
    token_ok = bool(settings.MOYASAR_WEBHOOK_SECRET) and hmac.compare_digest(str(token), settings.MOYASAR_WEBHOOK_SECRET)

    # تأكيد الـ Webhook من لوحة ميسر: يرسل رمزاً من 6 أرقام يجب إدخاله في اللوحة، فنطبعه في السجلات
    if str(payload.get("type", "")) == "webhook_verification":
        code = (payload.get("data") or {}).get("verification_code")
        logger.warning("رمز تأكيد Webhook ميسر: %s (السر %s)", code, "مطابق" if token_ok else "غير مطابق")
        return 200, {"status": "verification_received"}

    if not token_ok:
        logger.warning("محاولة Webhook ميسر بتوكن غير صحيح")
        return 401, {"error": "invalid token"}

    event_type = str(payload.get("type", ""))
    data = payload.get("data") or {}
    invoice_id = data.get("id") if event_type.startswith("invoice") else data.get("invoice_id")

    if event_type not in ("invoice_paid", "invoice.paid", "payment_paid", "payment.paid") or not invoice_id:
        return 200, {"status": "ignored", "event": event_type}

    try:
        status = await verify_and_activate(invoice_id)
    except moyasar_client.MoyasarError:
        logger.exception("فشل التحقق من الفاتورة %s", invoice_id)
        return 502, {"error": "verification failed"}  # ميسر يعيد المحاولة
    return 200, {"status": status}


_RESULT_PAGE = """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Cloud — نتيجة الدفع</title>
<link rel="stylesheet" href="{site}/assets/style.css"></head><body class="center-page">
<div class="card result-card"><div class="result-icon">{icon}</div><h1>{title}</h1><p>{text}</p>
{button}</div></body></html>"""


async def payment_callback_html(payment_id: Optional[str], invoice_id: Optional[str]) -> str:
    result = "not_found"
    try:
        if not invoice_id and payment_id:
            payment = await moyasar_client.fetch_payment(payment_id)
            invoice_id = payment.get("invoice_id")
        if invoice_id:
            result = await verify_and_activate(invoice_id)
    except Exception:
        logger.exception("فشل التحقق في صفحة الرجوع")
        result = "error"

    username = await bot_username()
    button = f'<a class="btn btn-primary" href="https://t.me/{username}">العودة إلى البوت</a>' if username else ""
    if result in ("ok", "already"):
        return _RESULT_PAGE.format(site=settings.PUBLIC_BASE_URL, icon="✅", title="تم الدفع بنجاح",
                                   text="تم تفعيل اشتراكك، ويمكنك الآن النشر في المجموعة. وصلتك رسالة تأكيد من البوت.", button=button)
    if result == "not_paid":
        return _RESULT_PAGE.format(site=settings.PUBLIC_BASE_URL, icon="⚠️", title="لم تكتمل عملية الدفع",
                                   text="لم يتم خصم أي مبلغ. يمكنك المحاولة مرة أخرى من البوت.", button=button)
    return _RESULT_PAGE.format(site=settings.PUBLIC_BASE_URL, icon="⏳", title="جارٍ التحقق من الدفع",
                               text="إذا تم الخصم فسيُفعَّل اشتراكك خلال دقائق وتصلك رسالة من البوت. لأي استفسار تواصل مع الدعم الفني @"
                               + settings.SUPPORT_USERNAME, button=button)


# ---------------------------------------------------------------------------
# الموقع
# ---------------------------------------------------------------------------

_cached_username = ""


async def bot_username() -> str:
    global _cached_username
    if settings.BOT_USERNAME:
        return settings.BOT_USERNAME
    if not _cached_username and settings.BOT_TOKEN:
        try:
            _cached_username = (await get_application()).bot.username or ""
        except Exception:
            logger.warning("تعذر جلب اسم مستخدم البوت")
    return _cached_username


async def config_js(emulators: dict) -> str:
    cfg = {
        # إعدادات Firebase للويب تُجلب تلقائياً من /__/firebase/init.json على Firebase Hosting
        "firebase": {"projectId": settings.FIREBASE_PROJECT_ID} if any(emulators.values()) else {},
        "emulators": emulators,
        "firestoreDatabase": "" if any(emulators.values()) else settings.FIRESTORE_DATABASE,
        # رابط سيرفر البوت إن كان منفصلاً عن الموقع (Render)، وإلا فارغ (نفس الموقع)
        "apiBase": settings.API_BASE_URL if settings.API_BASE_URL != settings.PUBLIC_BASE_URL else "",
        "botUsername": await bot_username(),
        "botName": settings.BOT_NAME,
        "supportUsername": settings.SUPPORT_USERNAME,
        "commissionPercent": settings.PLATFORM_COMMISSION_PERCENT,
        "plans": PLANS,
    }
    return "window.CLOUD_CONFIG = " + json.dumps(cfg, ensure_ascii=False) + ";"


async def claim_admin(id_token: str) -> tuple[int, dict]:
    """يمنح صلاحية الأدمن فوراً لصاحب إيميل موجود في ADMIN_EMAILS (بشرط أن يكون الإيميل مؤكَّداً)."""
    from firebase_admin import auth as fb_auth

    db.init_firebase()
    try:
        decoded = fb_auth.verify_id_token(id_token)
    except Exception:
        return 401, {"error": "invalid token"}
    email = (decoded.get("email") or "").lower()
    if email not in settings.ADMIN_EMAILS:
        return 403, {"error": "not an admin email"}
    if not decoded.get("email_verified"):
        return 403, {"error": "email_not_verified"}
    ref = db.db().collection("owners").document(decoded["uid"])
    if not ref.get().exists:
        return 404, {"error": "no profile"}
    ref.update({"role": "admin"})
    return 200, {"status": "ok"}


# ---------------------------------------------------------------------------
# المهام المجدولة
# ---------------------------------------------------------------------------

async def scheduled_reminders() -> int:
    app = await get_application()
    return await bot_handlers.run_reminders(app.bot)


async def scheduled_maintenance(now: Optional[dt.datetime] = None) -> dict:
    now = now or db.utcnow()
    app = await get_application()
    result = {"expired": await bot_handlers.run_expiry(app.bot)}
    await db.sync_admin_roles()
    await bot_handlers.delete_due_warnings(app.bot)
    if now.hour % 6 == 0:
        await bot_handlers.run_group_stats(app.bot)
        result["stats"] = True
    try:
        result["webhook"] = await ensure_webhook()
    except Exception as exc:
        logger.warning("تعذر التحقق من Webhook تليجرام: %s", exc)
    return result
