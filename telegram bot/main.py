"""
البوت الرئيسي: يدير اشتراك قروب تليجرام واحد عبر بوابة دفع ميسر.
يعمل كسيرفر ويب واحد (FastAPI) يستقبل:
  - تحديثات تليجرام على /webhook/<secret>
  - إشعار دفع ميسر على /moyasar/callback
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_ID, GROUP_ID, BASE_URL, WEBHOOK_SECRET_PATH
import database as db
import moyasar_client as moyasar

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sub_bot")

application = Application.builder().token(BOT_TOKEN).build()
scheduler = AsyncIOScheduler()
BOT_USERNAME = {"value": None}  # يُعبّى عند الإقلاع


# ==================== أوامر المستخدم العادي ====================

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await send_subscribe_message(update.effective_user.id, update.effective_user.username)


async def subscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await send_subscribe_message(update.effective_user.id, update.effective_user.username)


async def send_subscribe_message(user_id: int, username: str | None):
    if db.is_active(user_id):
        row = db.get_subscriber(user_id)
        exp = datetime.fromisoformat(row["expires_at"]).strftime("%Y-%m-%d %H:%M")
        await application.bot.send_message(
            user_id, f"اشتراكك فعّال حالياً وينتهي بتاريخ {exp}."
        )
        return

    if db.get_active_count() >= db.get_capacity():
        await application.bot.send_message(
            user_id, "عذراً، كل المقاعد المتاحة محجوزة حالياً. حاول لاحقاً."
        )
        return

    price = db.get_price()
    days = db.get_duration_days()
    try:
        invoice = moyasar.create_invoice(
            amount_sar=price,
            description=f"اشتراك {days} يوم",
            callback_url=f"{BASE_URL}/moyasar/callback",
            success_url=f"https://t.me/{BOT_USERNAME['value']}",
            metadata={"telegram_user_id": str(user_id)},
        )
    except Exception:
        log.exception("فشل إنشاء الفاتورة")
        await application.bot.send_message(
            user_id, "صار خطأ أثناء إنشاء رابط الدفع، حاول بعد شوي."
        )
        return

    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("💳 ادفع الآن", url=invoice["url"])]]
    )
    await application.bot.send_message(
        user_id,
        f"سعر الاشتراك: {price} ريال\nالمدة: {days} يوم\n\n"
        "اضغط الزر تحت وأكمل الدفع، وبعد نجاح العملية راح أرسل لك رابط الدخول للقروب تلقائياً.",
        reply_markup=kb,
    )


# ==================== أوامر الأدمن ====================

def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == ADMIN_ID


async def setprice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("استخدم: /setprice 30")
        return
    db.set_config("price_sar", context.args[0])
    await update.message.reply_text(f"تم تحديث السعر إلى {context.args[0]} ريال.")


async def setduration_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("استخدم: /setduration 30")
        return
    db.set_config("duration_days", context.args[0])
    await update.message.reply_text(f"تم تحديث مدة الاشتراك إلى {context.args[0]} يوم.")


async def setcapacity_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("استخدم: /setcapacity 50")
        return
    db.set_config("capacity", context.args[0])
    await update.message.reply_text(f"تم تحديث عدد المقاعد إلى {context.args[0]}.")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    active = db.get_active_count()
    await update.message.reply_text(
        f"السعر: {db.get_price()} ريال\n"
        f"المدة: {db.get_duration_days()} يوم\n"
        f"السعة: {db.get_capacity()}\n"
        f"المشتركين الفعّالين حالياً: {active}"
    )


# ==================== متابعة الأعضاء في القروب ====================

async def on_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        if db.is_active(member.id):
            continue
        # مو مشترك -> يُطرد فوراً
        try:
            await context.bot.ban_chat_member(GROUP_ID, member.id)
            await context.bot.unban_chat_member(GROUP_ID, member.id)
        except Exception:
            log.exception("فشل طرد عضو غير مشترك")
        try:
            await context.bot.send_message(
                member.id,
                f"لازم تشترك أولاً قبل الدخول للقروب. تواصل مع البوت @{BOT_USERNAME['value']} "
                "واكتب /subscribe.",
            )
        except Exception:
            pass


# ==================== المهام الدورية ====================

async def broadcast_job():
    price = db.get_price()
    days = db.get_duration_days()
    capacity = db.get_capacity()
    active = db.get_active_count()
    left = max(capacity - active, 0)
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔔 اشترك الآن", url=f"https://t.me/{BOT_USERNAME['value']}?start=1")]]
    )
    try:
        await application.bot.send_message(
            GROUP_ID,
            f"💳 سعر الاشتراك: {price} ريال\n⏳ المدة: {days} يوم\n🪑 المقاعد المتبقية: {left}/{capacity}",
            reply_markup=kb,
        )
    except Exception:
        log.exception("فشل إرسال رسالة التذكير الدورية")


async def sweep_expired_job():
    for row in db.get_expired_subscribers():
        user_id = row["user_id"]
        db.mark_expired(user_id)
        try:
            await application.bot.ban_chat_member(GROUP_ID, user_id)
            await application.bot.unban_chat_member(GROUP_ID, user_id)
        except Exception:
            log.exception(f"فشل طرد المنتهي {user_id}")
        try:
            await application.bot.send_message(
                user_id, "انتهى اشتراكك وتم إزالتك من القروب. اكتب /subscribe للتجديد."
            )
        except Exception:
            pass


# ==================== FastAPI ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("subscribe", subscribe_cmd))
    application.add_handler(CommandHandler("setprice", setprice_cmd))
    application.add_handler(CommandHandler("setduration", setduration_cmd))
    application.add_handler(CommandHandler("setcapacity", setcapacity_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member)
    )

    await application.initialize()
    me = await application.bot.get_me()
    BOT_USERNAME["value"] = me.username
    await application.bot.set_webhook(url=f"{BASE_URL}/webhook/{WEBHOOK_SECRET_PATH}")
    await application.start()

    scheduler.add_job(broadcast_job, "interval", minutes=30, id="broadcast")
    scheduler.add_job(sweep_expired_job, "interval", minutes=15, id="sweep")
    scheduler.start()

    log.info("البوت شغّال: @%s", me.username)
    yield

    scheduler.shutdown(wait=False)
    await application.stop()
    await application.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def health():
    # يُستخدم لأدوات إبقاء السيرفر مستيقظ (UptimeRobot)
    return PlainTextResponse("OK")


@app.post(f"/webhook/{WEBHOOK_SECRET_PATH}")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}


@app.post("/moyasar/callback")
async def moyasar_callback(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    invoice_id = (
        body.get("id")
        or body.get("data", {}).get("id")
        or request.query_params.get("id")
    )
    if not invoice_id:
        return {"ok": False, "error": "no invoice id"}

    if db.invoice_already_processed(invoice_id):
        return {"ok": True, "note": "already processed"}

    # لا نثق ببيانات الطلب وحدها، نتحقق مباشرة من سيرفر ميسر
    try:
        invoice = moyasar.fetch_invoice(invoice_id)
    except Exception:
        log.exception("فشل التحقق من الفاتورة عند ميسر")
        return {"ok": False}

    if invoice.get("status") != "paid":
        return {"ok": True, "note": "not paid yet"}

    metadata = invoice.get("metadata") or {}
    user_id_str = metadata.get("telegram_user_id")
    if not user_id_str:
        log.warning("فاتورة مدفوعة بدون telegram_user_id: %s", invoice_id)
        return {"ok": False}

    user_id = int(user_id_str)
    days = db.get_duration_days()
    expires_at = db.add_or_renew_subscriber(user_id, "", days)
    db.mark_invoice_processed(invoice_id, user_id)

    try:
        link = await application.bot.create_chat_invite_link(
            chat_id=GROUP_ID, member_limit=1
        )
        exp = datetime.fromisoformat(expires_at).strftime("%Y-%m-%d")
        await application.bot.send_message(
            user_id,
            f"✅ تم الدفع بنجاح!\nاشتراكك فعّال حتى {exp}.\n\n"
            f"رابط الدخول للقروب (لمرة واحدة فقط):\n{link.invite_link}",
        )
    except Exception:
        log.exception("فشل إرسال رابط الدخول للمستخدم")

    return {"ok": True}
