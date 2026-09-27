"""
bot_handlers.py
----------------
كل منطق البوت في مكان واحد:
1) رسالة الترحيب وعرض الباقات (/start)
2) عند اختيار باقة: إنشاء فاتورة ميسر وفتحها عبر Telegram WebApp
3) حماية القروب: حذف رسائل أي شخص غير مشترك، مع إرسال تنبيه له للاشتراك
4) رسالة تذكير دورية داخل القروب كل نصف ساعة بالأسعار والباقات
5) مهمة دورية لتحديث حالة الاشتراكات المنتهية
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import database as db
import moyasar_client
from config import (
    EXPIRY_CHECK_INTERVAL_SECONDS,
    GROUP_REMINDER_INTERVAL_SECONDS,
    INVOICE_EXPIRY_MINUTES,
    PLANS,
    WARNING_MESSAGE_AUTO_DELETE_SECONDS,
    settings,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1) رسالة الترحيب وعرض الباقات
# ---------------------------------------------------------------------------

def build_welcome_text() -> str:
    return (
        f"اهلا وسهلا بك في بوت {settings.BOT_NAME} 🎉🎉\n"
        f"{settings.CHANNEL_NAME}\n\n"
        "اختر الباقة المناسبة لك من الأزرار بالأسفل للاشتراك 👇"
    )


def build_plans_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, plan in PLANS.items():
        label = f"{plan['name']} - {plan['price']:.0f} ريال ({plan['days']} يوم)"
        buttons.append([InlineKeyboardButton(label, callback_data=f"choose_plan:{key}")])
    return InlineKeyboardMarkup(buttons)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # أزرار WebApp (فتح رابط الدفع) لا تعمل إلا في محادثة خاصة مع البوت
    if update.effective_chat is None or update.effective_chat.type != ChatType.PRIVATE:
        return
    await update.message.reply_text(build_welcome_text(), reply_markup=build_plans_keyboard())


# ---------------------------------------------------------------------------
# 2) عند اختيار باقة: إنشاء فاتورة ميسر وفتحها عبر WebApp
# ---------------------------------------------------------------------------

async def choose_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    plan_key = query.data.split(":", 1)[1]
    plan = PLANS.get(plan_key)
    if plan is None:
        await query.edit_message_text("عذراً، هذه الباقة لم تعد متاحة.")
        return

    user_id = query.from_user.id

    try:
        invoice = await moyasar_client.create_invoice(
            amount_sar=plan["price"],
            description=f"اشتراك {plan['name']} - {settings.CHANNEL_NAME}",
            telegram_user_id=user_id,
            plan_key=plan_key,
        )
    except moyasar_client.MoyasarError:
        logger.exception("فشل إنشاء فاتورة ميسر للمستخدم %s", user_id)
        await query.edit_message_text("حدث خطأ أثناء إنشاء فاتورة الدفع، حاول لاحقاً 🙏")
        return

    await db.create_pending_invoice(
        telegram_user_id=user_id,
        invoice_id=invoice["id"],
        plan_key=plan_key,
        plan_name=plan["name"],
        amount=plan["price"],
    )

    # حسب إصدار حسابك في ميسر قد يكون اسم الحقل "url" أو "hosted_url" — تحقق منه فعلياً
    hosted_url = invoice.get("url") or invoice.get("hosted_url") or invoice.get("hosted_page_url")
    if not hosted_url:
        logger.error("لم يُرجع ميسر رابط فاتورة صالح: %s", invoice)
        await query.edit_message_text("تعذر الحصول على رابط الدفع، تواصل مع الدعم.")
        return

    pay_button = InlineKeyboardButton(text="💳 إتمام الدفع الآن", web_app=WebAppInfo(url=hosted_url))

    await query.edit_message_text(
        text=(
            f"تم إنشاء فاتورة {plan['name']} بقيمة {plan['price']:.0f} ريال ✅\n"
            f"⏳ الفاتورة صالحة لمدة {INVOICE_EXPIRY_MINUTES} دقيقة فقط، "
            "وبعدها يتم إلغاؤها تلقائياً وعليك طلب فاتورة جديدة.\n\n"
            "اضغط الزر بالأسفل لإتمام الدفع 👇"
        ),
        reply_markup=InlineKeyboardMarkup([[pay_button]]),
    )


# ---------------------------------------------------------------------------
# 3) حماية القروب: حذف رسائل غير المشتركين + تنبيههم بضرورة الاشتراك
# ---------------------------------------------------------------------------

async def _is_exempt_from_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    يرجع True إذا كان يجب استثناء المستخدم من فحص الاشتراك:
    مالك البوت، أو مشرف/مالك القروب نفسه.
    """
    user_id = update.effective_user.id

    if settings.OWNER_TELEGRAM_ID and user_id == settings.OWNER_TELEGRAM_ID:
        return True

    try:
        member = await context.bot.get_chat_member(chat_id=update.effective_chat.id, user_id=user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        return False


async def _delete_temporary_message(context: ContextTypes.DEFAULT_TYPE) -> None:
    """يحذف رسالة التنبيه تلقائياً بعد مدة معينة حتى لا يمتلئ القروب برسائل البوت."""
    job_data = context.job.data
    try:
        await context.bot.delete_message(chat_id=job_data["chat_id"], message_id=job_data["message_id"])
    except Exception:
        pass  # قد تكون حُذفت يدوياً بالفعل


async def guard_group_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None or user.is_bot:
        return

    # لا نلمس رسائل مالك البوت أو مشرفي/مالك القروب أبداً
    if await _is_exempt_from_check(update, context):
        return

    if await db.is_user_active(user.id):
        return  # مشترك ونشط: الرسالة تمر بشكل طبيعي تماماً

    try:
        await message.delete()
    except TelegramError:
        logger.warning(
            "تعذر حذف رسالة المستخدم %s في القروب %s (تأكد أن البوت مشرف وله صلاحية حذف الرسائل)",
            user.id,
            update.effective_chat.id,
        )
        return  # لو فشل الحذف لا نرسل تنبيهاً مضللاً

    bot_username = context.bot.username
    subscribe_button = InlineKeyboardButton(
        text="📝 اشترك الآن",
        url=f"https://t.me/{bot_username}?start=subscribe",
    )

    warning = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"⚠️ عذراً {user.mention_html()}، هذا القروب مخصص للمشتركين فقط.\n"
            "اضغط الزر بالأسفل للاشتراك حتى تتمكن من الإرسال هنا 👇"
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[subscribe_button]]),
    )

    if context.job_queue is not None:
        context.job_queue.run_once(
            _delete_temporary_message,
            when=WARNING_MESSAGE_AUTO_DELETE_SECONDS,
            data={"chat_id": warning.chat_id, "message_id": warning.message_id},
        )


# ---------------------------------------------------------------------------
# 4) رسالة تذكير دورية داخل القروب (كل نصف ساعة) بالأسعار والباقات
# ---------------------------------------------------------------------------

def _build_reminder_text() -> str:
    lines = [
        f"📢 تذكير: هذا القروب مخصص لمشتركي {settings.CHANNEL_NAME} فقط.",
        "",
        "الباقات المتاحة:",
    ]
    for plan in PLANS.values():
        lines.append(f"• {plan['name']} — {plan['price']:.0f} ريال / {plan['days']} يوم")
    lines.append("")
    lines.append("اضغط الزر بالأسفل للاشتراك الآن 👇")
    return "\n".join(lines)


async def group_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not settings.ADMIN_GROUP_ID:
        return

    bot_username = context.bot.username
    subscribe_button = InlineKeyboardButton(
        text="📝 اشترك الآن",
        url=f"https://t.me/{bot_username}?start=subscribe",
    )

    try:
        await context.bot.send_message(
            chat_id=settings.ADMIN_GROUP_ID,
            text=_build_reminder_text(),
            reply_markup=InlineKeyboardMarkup([[subscribe_button]]),
        )
    except TelegramError:
        logger.warning("تعذر إرسال رسالة التذكير الدورية في القروب %s", settings.ADMIN_GROUP_ID)


# ---------------------------------------------------------------------------
# 5) مهمة دورية: تحديث حالة الاشتراكات المنتهية
# ---------------------------------------------------------------------------

async def check_expired_subscriptions_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    expired_user_ids = await db.expire_outdated_subscriptions()
    for user_id in expired_user_ids:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ انتهى اشتراكك في " + settings.CHANNEL_NAME + ". جدّد اشتراكك بالضغط على /start",
            )
        except Exception:
            logger.warning("تعذر إبلاغ المستخدم %s بانتهاء الاشتراك", user_id)


# ---------------------------------------------------------------------------
# تسجيل كل الـ Handlers والمهام الدورية على تطبيق البوت
# ---------------------------------------------------------------------------

def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(choose_plan_callback, pattern=r"^choose_plan:"))
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, guard_group_messages)
    )

    if application.job_queue is not None:
        application.job_queue.run_repeating(
            check_expired_subscriptions_job,
            interval=EXPIRY_CHECK_INTERVAL_SECONDS,
            first=EXPIRY_CHECK_INTERVAL_SECONDS,
        )
        application.job_queue.run_repeating(
            group_reminder_job,
            interval=GROUP_REMINDER_INTERVAL_SECONDS,
            first=GROUP_REMINDER_INTERVAL_SECONDS,
        )
