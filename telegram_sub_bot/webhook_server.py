"""
webhook_server.py
------------------
نقطة الدخول الرئيسية للمشروع:
- يشغّل سيرفر FastAPI الذي يستقبل Webhook من ميسر عند نجاح الدفع.
- يشغّل بوت التليجرام (بنظام Polling) داخل نفس العملية عبر lifespan،
  حتى لا نحتاج تشغيل عمليتين منفصلتين.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from telegram.ext import Application

import database as db
import bot_handlers
from config import PLANS, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

telegram_app: Optional[Application] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app

    await db.init_db()

    telegram_app = Application.builder().token(settings.BOT_TOKEN).build()
    bot_handlers.register_handlers(telegram_app)

    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)

    logger.info("تم تشغيل بوت التليجرام وسيرفر الـ Webhook بنجاح ✅")
    yield

    await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()
    logger.info("تم إيقاف البوت والسيرفر.")


app = FastAPI(title="Cloud Subscription Bot", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/moyasar/webhook")
async def moyasar_webhook(request: Request, x_moyasar_token: Optional[str] = Header(default=None)):
    """
    نقطة استقبال إشعارات ميسر الفورية (invoice_paid).

    ميسر يرسل معه توكن سري (secret token) في الهيدر يتم ضبطه من لوحة
    تحكم ميسر عند إنشاء الـ Webhook. تحقق منه دائماً قبل الوثوق بأي
    بيانات واردة، حتى لا يستطيع أي شخص تفعيل اشتراكات مجانية بمجرد
    معرفة رابط الـ Webhook.
    """
    if x_moyasar_token != settings.MOYASAR_WEBHOOK_SECRET:
        logger.warning("محاولة Webhook بتوكن غير صحيح")
        raise HTTPException(status_code=401, detail="توكن الـ Webhook غير صحيح")

    payload = await request.json()
    event_type = payload.get("type")
    data = payload.get("data", {})

    if event_type not in ("invoice_paid", "invoice.paid"):
        return {"status": "ignored", "event": event_type}

    invoice_id = data.get("id")
    metadata = data.get("metadata") or {}
    plan_key = metadata.get("plan_key")
    telegram_user_id = metadata.get("telegram_user_id")

    if not invoice_id or not plan_key or not telegram_user_id:
        logger.warning("Webhook وصل ببيانات ناقصة: %s", payload)
        return {"status": "invalid_payload"}

    plan = PLANS.get(plan_key)
    if plan is None:
        logger.warning("باقة غير معروفة وردت في الـ Webhook: %s", plan_key)
        return {"status": "unknown_plan"}

    source = data.get("source")
    phone_number = source.get("phone") if isinstance(source, dict) else None

    record = await db.activate_subscription_by_invoice(
        invoice_id=invoice_id,
        plan_days=plan["days"],
        phone_number=phone_number,
    )

    if record is None:
        logger.warning("لم يتم إيجاد فاتورة مطابقة في قاعدة بياناتنا: %s", invoice_id)
        return {"status": "invoice_not_found"}

    if telegram_app is not None:
        await telegram_app.bot.send_message(
            chat_id=int(telegram_user_id),
            text=(
                "✅ تم تفعيل اشتراكك بنجاح!\n"
                f"الباقة: {plan['name']}\n"
                f"صالح حتى: {record.end_date.strftime('%Y-%m-%d')}\n\n"
                "يمكنك الآن الكتابة داخل القروب بكل حرية 🎉"
            ),
        )

    return {"status": "ok"}
