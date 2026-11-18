"""
webhook_server.py
------------------
سيرفر واحد يشغّل كل شيء:
- الموقع (صفحة الهبوط + التسجيل + لوحة التحكم + لوحة الأدمن) من مجلد web/
- /config.js : إعدادات Firebase العامة للموقع (تُقرأ من متغيرات البيئة)
- /moyasar/webhook : إشعارات الدفع من ميسر
- /payment/callback : الصفحة التي يرجع لها العضو بعد الدفع
- بوت التليجرام (Polling) داخل نفس العملية
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

import bot_handlers
import firebase_db as db
import moyasar_client
from config import PLANS, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"

telegram_app: Optional[Application] = None
bot_username: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app, bot_username

    settings.validate()
    db.init_firebase()
    await db.sync_admin_roles()

    if settings.RUN_BOT:
        telegram_app = Application.builder().token(settings.BOT_TOKEN).build()
        bot_handlers.register_handlers(telegram_app)
        await telegram_app.initialize()
        bot_username = telegram_app.bot.username or ""
        await telegram_app.start()
        await telegram_app.updater.start_polling(drop_pending_updates=True)
        logger.info("تم تشغيل البوت @%s والموقع بنجاح ✅", bot_username)
    else:
        logger.info("RUN_BOT=false: تم تشغيل الموقع فقط بدون البوت")

    yield

    if telegram_app is not None:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(title="Cloud Platform", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/config.js")
async def web_config():
    """إعدادات عامة للموقع. مفتاح Firebase للويب ليس سرياً (الحماية في firestore.rules)."""
    cfg = {
        "firebase": {
            "apiKey": settings.FIREBASE_API_KEY,
            "authDomain": settings.FIREBASE_AUTH_DOMAIN or f"{settings.FIREBASE_PROJECT_ID}.firebaseapp.com",
            "projectId": settings.FIREBASE_PROJECT_ID,
            "appId": settings.FIREBASE_APP_ID,
            "storageBucket": settings.FIREBASE_STORAGE_BUCKET,
            "messagingSenderId": settings.FIREBASE_MESSAGING_SENDER_ID,
        },
        "emulators": {
            "firestore": os.getenv("FIRESTORE_EMULATOR_HOST", ""),
            "auth": os.getenv("FIREBASE_AUTH_EMULATOR_HOST", ""),
        },
        "botUsername": bot_username or os.getenv("BOT_USERNAME", ""),
        "botName": settings.BOT_NAME,
        "supportUsername": settings.SUPPORT_USERNAME,
        "commissionPercent": settings.PLATFORM_COMMISSION_PERCENT,
        "plans": PLANS,
    }
    body = "window.CLOUD_CONFIG = " + json.dumps(cfg, ensure_ascii=False) + ";"
    return Response(body, media_type="application/javascript", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# التحقق من الدفع وتفعيل الاشتراك (مشترك بين الـ Webhook وصفحة الرجوع)
# ---------------------------------------------------------------------------

async def verify_and_activate(invoice_id: str) -> str:
    """
    لا نثق بأي بيانات واردة: نجلب الفاتورة من ميسر مباشرة بمفتاحنا السري،
    ونتأكد أنها مدفوعة وأن المبلغ يطابق المبلغ المحفوظ عندنا.
    """
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

    if status == "ok" and telegram_app is not None:
        try:
            await telegram_app.bot.send_message(
                chat_id=int(data["telegramUserId"]),
                text=(
                    "✅ تم تفعيل اشتراكك بنجاح!\n"
                    f"القروب: {data.get('groupTitle', '')}\n"
                    f"الباقة: {data.get('planName', '')}\n"
                    f"صالح حتى: {data['endDate'].strftime('%Y-%m-%d')}\n\n"
                    "يمكنك الآن الكتابة داخل القروب بكل حرية 🎉"
                ),
            )
        except Exception:
            logger.warning("تعذر إرسال رسالة التفعيل للمستخدم %s", data.get("telegramUserId"))
    return status


@app.post("/moyasar/webhook")
async def moyasar_webhook(request: Request, x_moyasar_token: Optional[str] = Header(default=None)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    token = x_moyasar_token or payload.get("secret_token") or ""
    if not settings.MOYASAR_WEBHOOK_SECRET or not hmac.compare_digest(str(token), settings.MOYASAR_WEBHOOK_SECRET):
        logger.warning("محاولة Webhook بتوكن غير صحيح")
        raise HTTPException(status_code=401, detail="توكن الـ Webhook غير صحيح")

    event_type = str(payload.get("type", ""))
    data = payload.get("data") or {}

    if event_type.startswith("invoice"):
        invoice_id = data.get("id")
    else:
        invoice_id = data.get("invoice_id")

    if event_type not in ("invoice_paid", "invoice.paid", "payment_paid", "payment.paid") or not invoice_id:
        return {"status": "ignored", "event": event_type}

    try:
        status = await verify_and_activate(invoice_id)
    except moyasar_client.MoyasarError:
        logger.exception("فشل التحقق من الفاتورة %s", invoice_id)
        raise HTTPException(status_code=502, detail="moyasar verification failed")  # ميسر يعيد المحاولة
    return {"status": status}


_RESULT_PAGE = """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Cloud — نتيجة الدفع</title>
<link rel="stylesheet" href="/assets/style.css"></head><body class="center-page">
<div class="card result-card"><div class="result-icon">{icon}</div><h1>{title}</h1><p>{text}</p>
{button}</div></body></html>"""


@app.get("/payment/callback", response_class=HTMLResponse)
async def payment_callback(id: Optional[str] = None, invoice_id: Optional[str] = None, status: Optional[str] = None):
    """صفحة الرجوع بعد الدفع. نتحقق من ميسر مباشرة (احتياط لو تأخر الـ Webhook)."""
    result = "not_found"
    try:
        if not invoice_id and id:
            payment = await moyasar_client.fetch_payment(id)
            invoice_id = payment.get("invoice_id")
        if invoice_id:
            result = await verify_and_activate(invoice_id)
    except Exception:
        logger.exception("فشل التحقق في صفحة الرجوع")
        result = "error"

    tg = f'<a class="btn btn-primary" href="https://t.me/{bot_username}">العودة إلى البوت</a>' if bot_username else ""
    if result in ("ok", "already"):
        page = _RESULT_PAGE.format(icon="✅", title="تم الدفع بنجاح", text="تم تفعيل اشتراكك، يمكنك الآن الكتابة في القروب. وصلتك رسالة تأكيد من البوت.", button=tg)
    elif result == "not_paid":
        page = _RESULT_PAGE.format(icon="⚠️", title="لم تكتمل عملية الدفع", text="لم يتم خصم أي مبلغ. يمكنك المحاولة مرة أخرى من البوت.", button=tg)
    else:
        page = _RESULT_PAGE.format(icon="⏳", title="جاري التحقق من الدفع", text="إذا تم الخصم سيتفعّل اشتراكك خلال دقائق وتصلك رسالة من البوت. لأي مشكلة تواصل مع الدعم @" + settings.SUPPORT_USERNAME, button=tg)
    return HTMLResponse(page)


# الموقع (يجب أن يكون آخر شيء حتى لا يغطي المسارات السابقة)
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
