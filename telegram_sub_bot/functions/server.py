"""
server.py — تشغيل البوت كسيرفر ويب عادي (Render أو أي استضافة) بدل Cloud Functions.

نفس منطق main.py تماماً (app_logic)، مع:
  - المهام المجدولة داخل السيرفر: التذكير كل 30 دقيقة، والصيانة كل ساعة.
  - حذف تنبيه «يجب الاشتراك» بعد 20 ثانية بمؤقّت داخلي (بدل Cloud Tasks).
  - ضبط Webhook تليجرام تلقائياً عند التشغيل.

التشغيل:
  uvicorn server:app --host 0.0.0.0 --port $PORT --workers 1
(نسخة واحدة فقط: المهام المجدولة تعمل داخل السيرفر)

المسارات:
  POST /telegram/webhook      تليجرام
  POST /moyasar/webhook       إشعارات الدفع من ميسر
  GET  /payment/callback      صفحة الرجوع بعد الدفع
  GET  /config.js             إعدادات الموقع (الموقع على Firebase Hosting يحوّل إليها)
  POST /api/claim-admin       تفعيل لوحة الأدمن
  GET  /api/setup-webhook     ضبط Webhook تليجرام يدوياً
  GET  /healthz               فحص الحالة
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import os
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

import app_logic
import bot_handlers
import firebase_db as db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("server")

REMINDER_PERIOD = 30 * 60  # ثانية

_loop: asyncio.AbstractEventLoop | None = None
_background: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.ensure_future(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


def _emulators() -> dict:
    return {
        "firestore": os.environ.get("FIRESTORE_EMULATOR_HOST", ""),
        "auth": os.environ.get("FIREBASE_AUTH_EMULATOR_HOST", ""),
    }


# ---------------------------------------------------------------------------
# حذف التنبيه بعد 20 ثانية (يُستدعى من خيط عبر asyncio.to_thread في bot_handlers)
# ---------------------------------------------------------------------------

def _enqueue_delete(chat_id: int, message_id: int, delay: int) -> None:
    if _loop is None:
        raise RuntimeError("السيرفر لم يبدأ بعد")

    def _schedule() -> None:
        _loop.call_later(delay, lambda: _spawn(app_logic.delete_message(chat_id, message_id)))

    _loop.call_soon_threadsafe(_schedule)


# ---------------------------------------------------------------------------
# المهام المجدولة
# ---------------------------------------------------------------------------

async def _run_job(name: str, coro) -> None:
    try:
        logger.info("%s: %s", name, await coro)
    except Exception:
        logger.exception("فشلت المهمة المجدولة %s", name)


async def _scheduler() -> None:
    """كل نصف ساعة (عند :00 و :30): التذكير. كل ساعة (عند :00): الصيانة."""
    while True:
        now = time.time()
        slot = (int(now // REMINDER_PERIOD) + 1) * REMINDER_PERIOD
        await asyncio.sleep(slot - now)
        at = dt.datetime.fromtimestamp(slot, dt.timezone.utc)
        await _run_job("التذكير", app_logic.scheduled_reminders())
        if at.minute == 0:
            await _run_job("الصيانة", app_logic.scheduled_maintenance(at))


async def _startup_webhook() -> None:
    try:
        logger.info("Webhook تليجرام: %s", await app_logic.ensure_webhook())
    except Exception:
        logger.exception("تعذر ضبط Webhook تليجرام عند التشغيل (يُعاد كل ساعة، أو افتح /api/setup-webhook)")


@contextlib.asynccontextmanager
async def lifespan(_app):
    global _loop
    _loop = asyncio.get_running_loop()
    bot_handlers.enqueue_delete_task = _enqueue_delete
    db.init_firebase()
    _spawn(_startup_webhook())
    scheduler = asyncio.ensure_future(_scheduler())
    try:
        yield
    finally:
        scheduler.cancel()
        if app_logic._app is not None:
            with contextlib.suppress(Exception):
                await app_logic._app.shutdown()


# ---------------------------------------------------------------------------
# المسارات
# ---------------------------------------------------------------------------

def _cors(response: Response) -> Response:
    # الطلب يحمل توكن Firebase في الترويسة (لا كوكيز)، فالسماح لأي أصل آمن هنا
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Max-Age"] = "3600"
    return response


async def health(_req: Request) -> Response:
    return PlainTextResponse("ok")


async def telegram_webhook(req: Request) -> Response:
    if req.method != "POST":
        return PlainTextResponse("ok")
    if not app_logic.telegram_secret_ok(req.headers.get("X-Telegram-Bot-Api-Secret-Token")):
        return PlainTextResponse("forbidden", status_code=403)
    try:
        data = await req.json()
    except Exception:
        data = None
    if data:
        try:
            await app_logic.process_telegram_update(data)
        except Exception:
            logger.exception("فشل معالجة تحديث تليجرام")
    # نرجع 200 دائماً حتى لا يعيد تليجرام إرسال نفس التحديث مراراً
    return PlainTextResponse("ok")


async def moyasar_webhook(req: Request) -> Response:
    try:
        payload = await req.json()
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return JSONResponse({"error": "invalid json"}, status_code=400)
    status, body = await app_logic.handle_moyasar_webhook(payload, req.headers.get("x-moyasar-token"))
    return JSONResponse(body, status_code=status)


async def payment_callback(req: Request) -> Response:
    html = await app_logic.payment_callback_html(req.query_params.get("id"), req.query_params.get("invoice_id"))
    return HTMLResponse(html)


async def web_config(_req: Request) -> Response:
    body = await app_logic.config_js(_emulators())
    return Response(body, media_type="application/javascript; charset=utf-8", headers={"Cache-Control": "no-store"})


async def claim_admin(req: Request) -> Response:
    if req.method == "OPTIONS":
        return _cors(Response(status_code=204))
    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return _cors(JSONResponse({"error": "bad request"}, status_code=400))
    # verify_id_token و Firestore عمليات متزامنة: نشغّلها في خيط حتى لا توقف البوت
    status, body = await asyncio.to_thread(lambda: asyncio.run(app_logic.claim_admin(auth_header[7:])))
    return _cors(JSONResponse(body, status_code=status))


async def admin_users(req: Request) -> Response:
    if req.method == "OPTIONS":
        return _cors(Response(status_code=204))
    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return _cors(JSONResponse({"error": "bad request"}, status_code=400))
    try:
        payload = await req.json()
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return _cors(JSONResponse({"error": "invalid json"}, status_code=400))
    status, body = await asyncio.to_thread(app_logic.admin_users_sync, auth_header[7:], payload)
    return _cors(JSONResponse(body, status_code=status))


async def setup_webhook(_req: Request) -> Response:
    try:
        return JSONResponse(await app_logic.ensure_webhook())
    except Exception as exc:
        logger.exception("فشل ضبط Webhook")
        return JSONResponse({"error": str(exc)[:200]}, status_code=500)


app = Starlette(
    routes=[
        Route("/", health),
        Route("/healthz", health),
        Route("/telegram/webhook", telegram_webhook, methods=["GET", "POST"]),
        Route("/moyasar/webhook", moyasar_webhook, methods=["POST"]),
        Route("/payment/callback", payment_callback),
        Route("/config.js", web_config),
        Route("/api/claim-admin", claim_admin, methods=["POST", "OPTIONS"]),
        Route("/api/setup-webhook", setup_webhook),
        Route("/api/admin/users", admin_users, methods=["POST", "OPTIONS"]),
    ],
    lifespan=lifespan,
)
