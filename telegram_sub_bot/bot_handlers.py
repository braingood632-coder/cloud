"""
bot_handlers.py
----------------
منطق بوت Cloud (بوت واحد مركزي يخدم كل القروبات المربوطة):

1) /link CODE داخل القروب: يربط القروب بحساب صاحبه في الموقع
2) /start sub_<chatId> في الخاص: يعرض باقات الاشتراك لهذا القروب
3) اختيار باقة: فاتورة ميسر تُفتح داخل Telegram WebApp
4) حماية كل قروب مربوط: حذف رسائل غير المشتركين + تنبيه بزر الاشتراك
5) تذكير دوري داخل كل قروب مربوط بالباقات
6) مهام دورية: انتهاء الاشتراكات، تحديث عدد الأعضاء، صلاحيات الأدمن
7) متابعة حالة البوت في القروب (أُضيف/أُزيل/تغيرت صلاحياته)
"""

from __future__ import annotations

import html
import logging

from telegram import (
    ChatMemberAdministrator,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.constants import ChatMemberStatus, ChatType, ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import firebase_db as db
import moyasar_client
from config import (
    EXPIRY_CHECK_INTERVAL_SECONDS,
    GROUP_REMINDER_INTERVAL_SECONDS,
    GROUP_STATS_INTERVAL_SECONDS,
    INVOICE_EXPIRY_MINUTES,
    LINK_CODE_TTL_MINUTES,
    PLANS,
    WARNING_MESSAGE_AUTO_DELETE_SECONDS,
    settings,
)

logger = logging.getLogger(__name__)

ADMIN_STATUSES = (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)


def _subscribe_url(bot_username: str, chat_id: int) -> str:
    return f"https://t.me/{bot_username}?start=sub_{chat_id}"


def _subscribe_keyboard(bot_username: str, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("📝 اشترك الآن", url=_subscribe_url(bot_username, chat_id))]]
    )


def _plans_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    rows = []
    for key, plan in PLANS.items():
        label = f"{plan['name']} — {plan['price']:.0f} ريال ({plan['label']})"
        rows.append([InlineKeyboardButton(label, callback_data=f"plan|{chat_id}|{key}")])
    return InlineKeyboardMarkup(rows)


def _fmt_date(value) -> str:
    return value.strftime("%Y-%m-%d") if value else "-"


# ---------------------------------------------------------------------------
# 1) ربط القروب بحساب صاحبه: /link CODE
# ---------------------------------------------------------------------------

async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat is None or user is None or message is None:
        return

    if chat.type == ChatType.PRIVATE:
        await message.reply_text(
            "أمر /link يُرسل داخل القروب نفسه وليس هنا.\n\n"
            "1) أضفني إلى قروبك واجعلني مشرفاً مع صلاحية حذف الرسائل.\n"
            "2) انسخ كود الربط من لوحة التحكم في الموقع.\n"
            "3) أرسل داخل القروب: /link الكود"
        )
        return

    if not context.args:
        await message.reply_text("اكتب الأمر مع كود الربط من لوحة التحكم، مثال:\n/link AB12CD34")
        return

    # فقط مشرفو القروب يستطيعون ربطه
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
    except TelegramError:
        member = None
    if member is None or member.status not in ADMIN_STATUSES:
        await message.reply_text("⛔ ربط القروب متاح لمشرفي القروب فقط.")
        return

    # البوت يجب أن يكون مشرفاً ويملك صلاحية حذف الرسائل
    try:
        me = await context.bot.get_chat_member(chat.id, context.bot.id)
    except TelegramError:
        me = None
    if not isinstance(me, ChatMemberAdministrator) or not me.can_delete_messages:
        await message.reply_text(
            "⚠️ قبل الربط: اجعلني مشرفاً (Admin) في القروب وفعّل لي صلاحية «حذف الرسائل»، ثم أعد إرسال الأمر."
        )
        return

    code = context.args[0]
    status, group = await db.consume_link_code(code, chat.id, chat.title or "", user.id)

    if status == db.LINK_OK:
        try:
            await message.delete()  # حتى لا يبقى الكود ظاهراً
        except TelegramError:
            pass
        await db.update_group(chat.id, botIsAdmin=True, canDelete=True)
        await _refresh_group_stats(context, chat.id)
        await context.bot.send_message(
            chat.id,
            "✅ تم ربط القروب بنجاح بحساب «" + html.escape(group.get("ownerName") or "صاحب القروب") + "».\n\n"
            "من الآن: الكتابة هنا للمشتركين فقط. أي عضو غير مشترك تُحذف رسالته ويظهر له زر الاشتراك.",
            reply_markup=_subscribe_keyboard(context.bot.username, chat.id),
        )
        return

    messages = {
        db.LINK_INVALID: "❌ الكود غير صحيح أو مستخدم مسبقاً. ولّد كوداً جديداً من لوحة التحكم.",
        db.LINK_EXPIRED: f"⌛ انتهت صلاحية الكود (صالح {LINK_CODE_TTL_MINUTES} دقيقة). ولّد كوداً جديداً من لوحة التحكم.",
        db.LINK_TAKEN: "⛔ هذا القروب مربوط مسبقاً بحساب آخر. تواصل مع الدعم الفني @" + settings.SUPPORT_USERNAME,
        db.LINK_NO_OWNER: "❌ الحساب المرتبط بهذا الكود غير موجود. سجّل دخولك في الموقع وولّد كوداً جديداً.",
    }
    await message.reply_text(messages.get(status, "حدث خطأ غير متوقع، حاول مرة أخرى."))


# ---------------------------------------------------------------------------
# 2) /start في الخاص
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    if chat.type != ChatType.PRIVATE:
        # عند إضافة البوت عبر زر «أضف البوت إلى قروبك» يرسل تليجرام /start CODE داخل القروب
        if context.args:
            await link_command(update, context)
        return
    message = update.effective_message

    arg = context.args[0] if context.args else ""
    if arg.startswith("sub_"):
        try:
            group_id = int(arg[4:])
        except ValueError:
            group_id = 0
        group = await db.get_linked_group(group_id) if group_id else None
        if group is None:
            await message.reply_text("عذراً، هذا القروب غير مفعّل حالياً على بوت Cloud.")
            return

        end = await db.get_active_end_date(update.effective_user.id, group_id)
        current = f"\n✅ اشتراكك الحالي صالح حتى {_fmt_date(end)} — يمكنك التجديد مسبقاً وستُضاف المدة.\n" if end else ""
        await message.reply_text(
            f"اهلا وسهلا بك في بوت {settings.BOT_NAME} 🎉🎉\n"
            f"القروب: {group.get('title', '')}\n{current}\n"
            "اختر الباقة المناسبة لك من الأزرار بالأسفل للاشتراك 👇",
            reply_markup=_plans_keyboard(group_id),
        )
        return

    site = settings.PUBLIC_BASE_URL
    await message.reply_text(
        f"اهلا وسهلا بك في بوت {settings.BOT_NAME} 🤖☁️\n\n"
        "👤 إذا كنت عضواً: اضغط زر «اشترك الآن» الموجود داخل القروب الذي تريد الكتابة فيه.\n\n"
        f"👑 إذا كنت صاحب قروب: سجّل مجاناً في الموقع واربط قروبك:\n{site}\n\n"
        "📋 لعرض اشتراكاتك: /mysubs\n"
        f"🛟 الدعم الفني: @{settings.SUPPORT_USERNAME}"
    )


async def mysubs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_chat.type != ChatType.PRIVATE:
        return
    subs = await db.list_user_active_subscriptions(update.effective_user.id)
    if not subs:
        await update.effective_message.reply_text("لا يوجد لديك أي اشتراك نشط حالياً.")
        return
    lines = ["📋 اشتراكاتك النشطة:\n"]
    for s in sorted(subs, key=lambda x: x.get("endDate")):
        lines.append(f"• {s.get('groupTitle', '')} — {s.get('planName', '')} — حتى {_fmt_date(s.get('endDate'))}")
    await update.effective_message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# 3) اختيار باقة -> فاتورة ميسر
# ---------------------------------------------------------------------------

async def choose_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    try:
        _, group_id_str, plan_key = query.data.split("|", 2)
        group_id = int(group_id_str)
    except ValueError:
        await query.edit_message_text("طلب غير صالح، أعد المحاولة من زر الاشتراك في القروب.")
        return

    plan = PLANS.get(plan_key)
    group = await db.get_linked_group(group_id)
    if plan is None or group is None:
        await query.edit_message_text("عذراً، هذه الباقة أو هذا القروب لم يعد متاحاً.")
        return

    user = query.from_user
    try:
        invoice = await moyasar_client.create_invoice(
            amount_sar=plan["price"],
            description=f"اشتراك {plan['name']} - {group.get('title', '')}",
            telegram_user_id=user.id,
            group_id=group_id,
            plan_key=plan_key,
        )
    except Exception:
        logger.exception("فشل إنشاء فاتورة ميسر للمستخدم %s", user.id)
        await query.edit_message_text("حدث خطأ أثناء إنشاء فاتورة الدفع، حاول لاحقاً 🙏")
        return

    await db.create_pending_subscription(
        invoice_id=invoice["id"],
        telegram_user={"id": user.id, "name": user.full_name, "username": user.username},
        group=group,
        group_id=group_id,
        plan_key=plan_key,
    )

    hosted_url = invoice.get("url") or invoice.get("hosted_url") or invoice.get("hosted_page_url")
    if not hosted_url:
        logger.error("لم يُرجع ميسر رابط فاتورة صالح: %s", invoice)
        await query.edit_message_text("تعذر الحصول على رابط الدفع، تواصل مع الدعم.")
        return

    await query.edit_message_text(
        text=(
            f"تم إنشاء فاتورة {plan['name']} بقيمة {plan['price']:.0f} ريال ✅\n"
            f"القروب: {group.get('title', '')}\n"
            f"⏳ الفاتورة صالحة لمدة {INVOICE_EXPIRY_MINUTES} دقيقة فقط.\n\n"
            "اضغط الزر بالأسفل لإتمام الدفع 👇"
        ),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("💳 إتمام الدفع الآن", web_app=WebAppInfo(url=hosted_url))]]
        ),
    )


# ---------------------------------------------------------------------------
# 4) حماية القروبات المربوطة
# ---------------------------------------------------------------------------

async def _is_exempt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    # رسائل المشرف المجهول، أو القناة المرتبطة بالقروب
    if message.sender_chat is not None and (
        message.sender_chat.id == chat.id or message.is_automatic_forward
    ):
        return True

    if settings.OWNER_TELEGRAM_ID and user.id == settings.OWNER_TELEGRAM_ID:
        return True

    try:
        member = await context.bot.get_chat_member(chat_id=chat.id, user_id=user.id)
        return member.status in ADMIN_STATUSES
    except TelegramError:
        return False


async def _delete_later(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    try:
        await context.bot.delete_message(chat_id=data["chat_id"], message_id=data["message_id"])
    except TelegramError:
        pass


async def guard_group_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None or user.is_bot and message.sender_chat is None:
        return

    group = await db.get_linked_group(chat.id)
    if group is None:
        return  # القروب غير مربوط: البوت لا يتدخل

    if await _is_exempt(update, context):
        return

    if await db.is_user_active(user.id, chat.id):
        return

    try:
        await message.delete()
    except TelegramError:
        logger.warning("تعذر حذف رسالة في القروب %s (تأكد من صلاحية حذف الرسائل)", chat.id)
        return

    await db.increment_blocked_messages(chat.id)

    warning = await context.bot.send_message(
        chat_id=chat.id,
        text=(
            f"⚠️ عذراً {user.mention_html()}، هذا القروب مخصص للمشتركين فقط.\n"
            "اضغط الزر بالأسفل للاشتراك حتى تتمكن من الإرسال هنا 👇"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=_subscribe_keyboard(context.bot.username, chat.id),
    )

    if context.job_queue is not None:
        context.job_queue.run_once(
            _delete_later,
            when=WARNING_MESSAGE_AUTO_DELETE_SECONDS,
            data={"chat_id": warning.chat_id, "message_id": warning.message_id},
        )


# ---------------------------------------------------------------------------
# 5) تذكير دوري داخل كل قروب مربوط
# ---------------------------------------------------------------------------

def build_reminder_text(group_title: str) -> str:
    lines = [f"📢 تذكير: قروب «{group_title}» مخصص للمشتركين فقط.", "", "الباقات المتاحة:"]
    for plan in PLANS.values():
        lines.append(f"• {plan['name']} — {plan['price']:.0f} ريال / {plan['label']}")
    lines += ["", "اضغط الزر بالأسفل للاشتراك الآن 👇"]
    return "\n".join(lines)


async def group_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    for group in await db.list_active_groups():
        if not group.get("remindersEnabled", True):
            continue
        chat_id = int(group["id"])
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=build_reminder_text(group.get("title", "")),
                reply_markup=_subscribe_keyboard(context.bot.username, chat_id),
            )
        except TelegramError as exc:
            logger.warning("تعذر إرسال التذكير في القروب %s: %s", chat_id, exc)


# ---------------------------------------------------------------------------
# 6) مهام دورية
# ---------------------------------------------------------------------------

async def check_expired_subscriptions_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    for sub in await db.expire_outdated_subscriptions():
        try:
            await context.bot.send_message(
                chat_id=sub["telegramUserId"],
                text=f"⚠️ انتهى اشتراكك في «{sub.get('groupTitle', '')}». جدّد اشتراكك من الزر بالأسفل 👇",
                reply_markup=_subscribe_keyboard(context.bot.username, sub["groupId"]),
            )
        except TelegramError:
            logger.info("تعذر إبلاغ المستخدم %s بانتهاء الاشتراك", sub["telegramUserId"])


async def _refresh_group_stats(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    try:
        chat = await context.bot.get_chat(chat_id)
        count = await context.bot.get_chat_member_count(chat_id)
        await db.update_group(chat_id, title=chat.title or "", memberCount=count)
    except TelegramError as exc:
        logger.info("تعذر تحديث إحصائيات القروب %s: %s", chat_id, exc)


async def group_stats_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    for group in await db.list_active_groups():
        await _refresh_group_stats(context, int(group["id"]))


async def admin_sync_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.sync_admin_roles()


# ---------------------------------------------------------------------------
# 7) متابعة حالة البوت في القروب + تحويل القروب لـ Supergroup
# ---------------------------------------------------------------------------

async def my_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    change = update.my_chat_member
    if change is None or change.chat.type == ChatType.PRIVATE:
        return
    chat_id = change.chat.id
    new = change.new_chat_member

    if new.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
        await db.update_group(chat_id, active=False, botIsAdmin=False, canDelete=False)
        return

    is_admin = isinstance(new, ChatMemberAdministrator)
    can_delete = bool(is_admin and new.can_delete_messages)
    fields = {"botIsAdmin": is_admin, "canDelete": can_delete, "title": change.chat.title or ""}
    group = await db.get_linked_group(chat_id)
    if group is None:
        # ربما كان القروب معطلاً (أُزيل البوت سابقاً) وأُعيدت إضافته
        raw = await db._run(db._get_group_sync, chat_id)
        if raw is not None:
            fields["active"] = True
    await db.update_group(chat_id, **fields)


async def migrate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message and message.migrate_to_chat_id:
        await db.migrate_group(message.chat_id, message.migrate_to_chat_id)


# ---------------------------------------------------------------------------
# تسجيل الـ Handlers
# ---------------------------------------------------------------------------

def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("mysubs", mysubs_command))
    application.add_handler(CommandHandler("link", link_command))
    application.add_handler(CallbackQueryHandler(choose_plan_callback, pattern=r"^plan\|"))
    application.add_handler(ChatMemberHandler(my_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, migrate_handler))
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, guard_group_messages)
    )

    jq = application.job_queue
    if jq is not None:
        jq.run_repeating(check_expired_subscriptions_job, interval=EXPIRY_CHECK_INTERVAL_SECONDS, first=60)
        jq.run_repeating(group_reminder_job, interval=GROUP_REMINDER_INTERVAL_SECONDS, first=GROUP_REMINDER_INTERVAL_SECONDS)
        jq.run_repeating(group_stats_job, interval=GROUP_STATS_INTERVAL_SECONDS, first=120)
        jq.run_repeating(admin_sync_job, interval=600, first=5)
