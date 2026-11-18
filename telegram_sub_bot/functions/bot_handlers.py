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

import asyncio
import datetime as dt
import html
import logging
from typing import Callable, Optional

from telegram import (
    Bot,
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
        [[InlineKeyboardButton("✅ اشترك ✅", url=_subscribe_url(bot_username, chat_id))]]
    )


def _plans_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    rows = []
    for key, plan in PLANS.items():
        label = f"{plan['name']} ← {plan['price']:.0f} ريال ← {plan['days']} يوماً"
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
        await refresh_group_stats(context.bot, chat.id)
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

    user_id = update.effective_user.id
    arg = context.args[0] if context.args else ""
    if arg.startswith("sub_"):
        try:
            group_id = int(arg[4:])
        except ValueError:
            group_id = 0
        group = await db.get_linked_group(group_id) if group_id else None
        if group is None:
            await message.reply_text("عذراً، هذه المجموعة غير مفعّلة حالياً على البوت.")
            return
        await message.reply_text(**await _plans_message(group_id, group, user_id))
        return

    # /start بدون رابط: نبحث عن المجموعات المربوطة التي هو عضو فيها
    groups = await _user_groups(context, user_id)
    if len(groups) == 1:
        group_id, group = groups[0]
        await message.reply_text(**await _plans_message(group_id, group, user_id))
        return
    if len(groups) > 1:
        rows = [[InlineKeyboardButton(f"👥 {g.get('title', '')}", callback_data=f"grp|{gid}")] for gid, g in groups]
        await message.reply_text(
            f"أهلاً وسهلاً بك في بوت {settings.BOT_NAME} 🎉\n\nاختر المجموعة التي ترغب في الاشتراك بها 👇",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    await message.reply_text(
        f"أهلاً وسهلاً بك في بوت {settings.BOT_NAME} 🤖☁️\n\n"
        "👤 إن كنت عضواً: اضغط زر «اشترك» الموجود داخل المجموعة التي ترغب في النشر بها.\n\n"
        f"👑 إن كنت صاحب مجموعة: سجّل مجاناً في الموقع واربط مجموعتك:\n{settings.PUBLIC_BASE_URL}\n\n"
        "📋 لعرض اشتراكاتك: /mysubs\n"
        f"🛟 الدعم الفني: @{settings.SUPPORT_USERNAME}"
    )


async def _plans_message(group_id: int, group: dict, user_id: int) -> dict:
    """رسالة عرض الباقات (نفس أسلوب: 📦 قم باختيار إحدى باقات الاشتراك التالية)."""
    end = await db.get_active_end_date(user_id, group_id)
    current = (
        f"✅ اشتراكك الحالي ساري حتى {_fmt_date(end)}، ويمكنك التجديد مسبقاً وتُضاف المدة الجديدة إليه.\n\n"
        if end else ""
    )
    return {
        "text": f"👥 المجموعة: {group.get('title', '')}\n\n{current}📦 قم باختيار إحدى باقات الاشتراك التالية 📦",
        "reply_markup": _plans_keyboard(group_id),
    }


async def _user_groups(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[tuple[int, dict]]:
    found = []
    for group in (await db.list_active_groups())[:50]:
        gid = int(group["id"])
        try:
            member = await context.bot.get_chat_member(gid, user_id)
        except TelegramError:
            continue
        if member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED, *ADMIN_STATUSES):
            found.append((gid, group))
    return found


async def choose_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        group_id = int(query.data.split("|", 1)[1])
    except ValueError:
        return
    group = await db.get_linked_group(group_id)
    if group is None:
        await query.edit_message_text("عذراً، هذه المجموعة غير مفعّلة حالياً على البوت.")
        return
    await query.edit_message_text(**await _plans_message(group_id, group, query.from_user.id))


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
            f"📦 {plan['name']} — {plan['price']:.0f} ريال — {plan['days']} يوماً\n"
            f"👥 المجموعة: {group.get('title', '')}\n\n"
            f"اضغط للاشتراك. تنتهي العملية خلال {INVOICE_EXPIRY_MINUTES} دقيقة ⏳"
        ),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ اشترك ✅", web_app=WebAppInfo(url=hosted_url))]]
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


# يضبطها main.py لإرسال مهمة Cloud Tasks تحذف التنبيه بعد 20 ثانية.
# إن لم تتوفر (أو فشلت) نسجّل التنبيه في Firestore ويُحذف في أقرب فرصة.
enqueue_delete_task: Optional[Callable[[int, int, int], None]] = None


async def schedule_warning_delete(chat_id: int, message_id: int) -> None:
    if enqueue_delete_task is not None:
        try:
            await asyncio.to_thread(enqueue_delete_task, chat_id, message_id, WARNING_MESSAGE_AUTO_DELETE_SECONDS)
            return
        except Exception as exc:  # صلاحيات Cloud Tasks غير مضبوطة مثلاً
            logger.warning("تعذر جدولة حذف التنبيه عبر Cloud Tasks (%s)، سيتم الحذف الاحتياطي", exc)
    await db.add_pending_delete(
        chat_id, message_id, db.utcnow() + dt.timedelta(seconds=WARNING_MESSAGE_AUTO_DELETE_SECONDS)
    )


async def delete_due_warnings(bot: Bot, chat_id: Optional[int] = None) -> None:
    for item in await db.pop_due_deletes(chat_id):
        try:
            await bot.delete_message(chat_id=item["chatId"], message_id=item["messageId"])
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
            f"⚠️ عذراً {user.mention_html()}، النشر في هذه المجموعة متاحٌ للمشتركين فقط.\n"
            "اشترك الآن لتتمكن من المشاركة فوراً 👇"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=_subscribe_keyboard(context.bot.username, chat.id),
    )

    await schedule_warning_delete(warning.chat_id, warning.message_id)
    await delete_due_warnings(context.bot, chat.id)  # تنظيف أي تنبيهات قديمة متأخرة


# ---------------------------------------------------------------------------
# 5) تذكير دوري داخل كل قروب مربوط
# ---------------------------------------------------------------------------

def build_reminder_text(group_title: str) -> str:
    lines = [
        "⚠️ تنبيه هام لأعضاء المجموعة ⚠️",
        "",
        f"النشر في مجموعة «{group_title}» مقتصرٌ على المشتركين فقط؛ حفاظاً على جودة المحتوى، "
        "ومنعاً للإعلانات العشوائية والأرقام الوهمية والمحتالين.",
        "",
        "📦 باقات الاشتراك المتاحة:",
    ]
    for plan in PLANS.values():
        lines.append(f"• {plan['name']} — {plan['price']:.0f} ريال لمدة {plan['days']} يوماً")
    lines += ["", "للاشتراك وتفعيل صلاحية النشر فوراً، اضغط على الزر أدناه 👇"]
    return "\n".join(lines)


async def run_reminders(bot: Bot) -> int:
    """تُستدعى من الدالة المجدولة كل 30 دقيقة. ترجع عدد القروبات التي وصلها التذكير."""
    sent = 0
    for group in await db.list_active_groups():
        if not group.get("remindersEnabled", True):
            continue
        chat_id = int(group["id"])
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=build_reminder_text(group.get("title", "")),
                reply_markup=_subscribe_keyboard(bot.username, chat_id),
            )
            sent += 1
        except TelegramError as exc:
            logger.warning("تعذر إرسال التذكير في القروب %s: %s", chat_id, exc)
    await delete_due_warnings(bot)
    return sent


# ---------------------------------------------------------------------------
# 6) مهام دورية
# ---------------------------------------------------------------------------

async def run_expiry(bot: Bot) -> int:
    expired = await db.expire_outdated_subscriptions()
    for sub in expired:
        try:
            await bot.send_message(
                chat_id=sub["telegramUserId"],
                text=f"⚠️ انتهى اشتراكك في «{sub.get('groupTitle', '')}». يمكنك التجديد بالضغط على الزر أدناه 👇",
                reply_markup=_subscribe_keyboard(bot.username, sub["groupId"]),
            )
        except TelegramError:
            logger.info("تعذر إبلاغ المستخدم %s بانتهاء الاشتراك", sub["telegramUserId"])
    return len(expired)


async def refresh_group_stats(bot: Bot, chat_id: int) -> None:
    try:
        chat = await bot.get_chat(chat_id)
        count = await bot.get_chat_member_count(chat_id)
        await db.update_group(chat_id, title=chat.title or "", memberCount=count)
    except Exception as exc:  # الإحصائيات ثانوية: لا توقف الربط أو الصيانة
        logger.info("تعذر تحديث إحصائيات القروب %s: %s", chat_id, exc)


async def run_group_stats(bot: Bot) -> None:
    for group in await db.list_active_groups():
        await refresh_group_stats(bot, int(group["id"]))


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
    application.add_handler(CallbackQueryHandler(choose_group_callback, pattern=r"^grp\|"))
    application.add_handler(ChatMemberHandler(my_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, migrate_handler))
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, guard_group_messages)
    )
