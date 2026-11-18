"""
main.py — دوال Firebase (Cloud Functions, Python)

  telegramwebhook   تليجرام يرسل له كل رسالة/ضغطة زر         /telegram/webhook
  moyasarwebhook    إشعارات الدفع من ميسر                      /moyasar/webhook
  paymentcallback   الصفحة التي يرجع لها العضو بعد الدفع       /payment/callback
  webconfig         إعدادات الموقع                              /config.js
  claimadmin        تفعيل لوحة الأدمن لإيميلك                  /api/claim-admin
  setupwebhook      ضبط رابط البوت في تليجرام بعد الرفع        /api/setup-webhook
  reminders         كل 30 دقيقة: رسالة التذكير في القروبات
  maintenance       كل ساعة: الاشتراكات المنتهية + الإحصائيات + الصيانة
  deletewarning     Cloud Tasks: حذف تنبيه «يجب الاشتراك» بعد 20 ثانية
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading

from firebase_functions import https_fn, options, params, scheduler_fn, tasks_fn

import app_logic
import bot_handlers
from config import REGION, settings

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

options.set_global_options(region=REGION, max_instances=10)

BOT_TOKEN = params.SecretParam("BOT_TOKEN")
MOYASAR_SECRET_KEY = params.SecretParam("MOYASAR_SECRET_KEY")
MOYASAR_WEBHOOK_SECRET = params.SecretParam("MOYASAR_WEBHOOK_SECRET")
# 0 = توفير (قد تتأخر أول رسالة بعد فترة هدوء ثانية أو ثانيتين). 1 = استجابة فورية دائماً (تكلفة شهرية بسيطة)
MIN_INSTANCES = params.IntParam("MIN_INSTANCES", default=0)

ALL_SECRETS = [BOT_TOKEN, MOYASAR_SECRET_KEY, MOYASAR_WEBHOOK_SECRET]

# حلقة asyncio واحدة لكل نسخة (اتصالات البوت مرتبطة بها)
_loop = asyncio.new_event_loop()
_lock = threading.Lock()


def run(coro):
    with _lock:
        return _loop.run_until_complete(coro)


def _json(status: int, body: dict) -> https_fn.Response:
    return https_fn.Response(json.dumps(body, ensure_ascii=False), status=status, content_type="application/json")


def _emulators() -> dict:
    return {
        "firestore": os.environ.get("FIRESTORE_EMULATOR_HOST", ""),
        "auth": os.environ.get("FIREBASE_AUTH_EMULATOR_HOST", ""),
    }


def _enqueue_delete(chat_id: int, message_id: int, delay: int) -> None:
    from firebase_admin import functions as admin_functions

    queue = admin_functions.task_queue(f"locations/{REGION}/functions/deletewarning")
    queue.enqueue(
        {"chat_id": chat_id, "message_id": message_id},
        admin_functions.TaskOptions(schedule_delay_seconds=delay),
    )


# على السيرفر الحقيقي نستخدم Cloud Tasks؛ في المحاكي نستخدم الحذف الاحتياطي
if os.environ.get("FUNCTIONS_EMULATOR") != "true":
    bot_handlers.enqueue_delete_task = _enqueue_delete


# ---------------------------------------------------------------------------
# تليجرام
# ---------------------------------------------------------------------------

@https_fn.on_request(secrets=ALL_SECRETS, memory=options.MemoryOption.MB_512, min_instances=MIN_INSTANCES, timeout_sec=60)
def telegramwebhook(req: https_fn.Request) -> https_fn.Response:
    if req.method != "POST":
        return https_fn.Response("ok")
    if not app_logic.telegram_secret_ok(req.headers.get("X-Telegram-Bot-Api-Secret-Token")):
        return https_fn.Response("forbidden", status=403)
    data = req.get_json(silent=True)
    if data:
        try:
            run(app_logic.process_telegram_update(data))
        except Exception:
            logging.exception("فشل معالجة تحديث تليجرام")
    # نرجع 200 دائماً حتى لا يعيد تليجرام إرسال نفس التحديث مراراً
    return https_fn.Response("ok")


@tasks_fn.on_task_dispatched(
    secrets=[BOT_TOKEN],
    retry_config=options.RetryConfig(max_attempts=3, min_backoff_seconds=5),
    rate_limits=options.RateLimits(max_concurrent_dispatches=20),
)
def deletewarning(req: tasks_fn.CallableRequest) -> None:
    data = req.data or {}
    run(app_logic.delete_message(int(data["chat_id"]), int(data["message_id"])))


# ---------------------------------------------------------------------------
# ميسر
# ---------------------------------------------------------------------------

@https_fn.on_request(secrets=ALL_SECRETS, timeout_sec=60)
def moyasarwebhook(req: https_fn.Request) -> https_fn.Response:
    if req.method != "POST":
        return _json(405, {"error": "method not allowed"})
    payload = req.get_json(silent=True)
    if not isinstance(payload, dict):
        return _json(400, {"error": "invalid json"})
    status, body = run(app_logic.handle_moyasar_webhook(payload, req.headers.get("x-moyasar-token")))
    return _json(status, body)


@https_fn.on_request(secrets=ALL_SECRETS, timeout_sec=60)
def paymentcallback(req: https_fn.Request) -> https_fn.Response:
    html = run(app_logic.payment_callback_html(req.args.get("id"), req.args.get("invoice_id")))
    return https_fn.Response(html, content_type="text/html; charset=utf-8")


# ---------------------------------------------------------------------------
# الموقع
# ---------------------------------------------------------------------------

@https_fn.on_request(secrets=[BOT_TOKEN])
def webconfig(req: https_fn.Request) -> https_fn.Response:
    body = run(app_logic.config_js(_emulators()))
    return https_fn.Response(body, content_type="application/javascript; charset=utf-8", headers={"Cache-Control": "no-store"})


@https_fn.on_request()
def claimadmin(req: https_fn.Request) -> https_fn.Response:
    auth_header = req.headers.get("Authorization", "")
    if req.method != "POST" or not auth_header.startswith("Bearer "):
        return _json(400, {"error": "bad request"})
    status, body = run(app_logic.claim_admin(auth_header[7:]))
    return _json(status, body)


@https_fn.on_request(secrets=[BOT_TOKEN])
def setupwebhook(req: https_fn.Request) -> https_fn.Response:
    """يُفتح مرة بعد الرفع: https://<project>.web.app/api/setup-webhook — آمن، لا يكشف أي سر."""
    try:
        return _json(200, run(app_logic.ensure_webhook()))
    except Exception as exc:
        logging.exception("فشل ضبط Webhook")
        return _json(500, {"error": str(exc)[:200]})


# ---------------------------------------------------------------------------
# المهام المجدولة (بتوقيت الرياض)
# ---------------------------------------------------------------------------

@scheduler_fn.on_schedule(schedule="every 30 minutes", timezone=scheduler_fn.Timezone("Asia/Riyadh"), secrets=[BOT_TOKEN], timeout_sec=300)
def reminders(event: scheduler_fn.ScheduledEvent) -> None:
    sent = run(app_logic.scheduled_reminders())
    logging.info("تم إرسال التذكير إلى %s قروب", sent)


@scheduler_fn.on_schedule(schedule="every 60 minutes", timezone=scheduler_fn.Timezone("Asia/Riyadh"), secrets=[BOT_TOKEN], timeout_sec=540)
def maintenance(event: scheduler_fn.ScheduledEvent) -> None:
    logging.info("الصيانة: %s", run(app_logic.scheduled_maintenance()))
