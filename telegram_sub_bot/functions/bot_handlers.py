"""
bot_handlers.py
----------------
منطق بوت Cloud (بوت واحد مركزي يخدم كل القروبات المربوطة):

1) /link CODE داخل القروب: يربط القروب بحساب صاحبه في الموقع
2) زر «اشترك» يفتح صفحة الاشتراك في الموقع (المتصفح) — الدفع يتم في الموقع وليس داخل تليجرام
3) بعد الدفع يحصل العضو على كود تفعيل (مرة واحدة) يرسله للبوت أو داخل القروب فيتفعّل اشتراكه
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
from config import (
    LINK_CODE_TTL_MINUTES,
    WARNING_MESSAGE_AUTO_DELETE_SECONDS,
    settings,
)

logger = logging.getLogger(__name__)

ADMIN_STATUSES = (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)

SITE_PAY_TEXT = (
    "💳 الاشتراك والدفع يتم من خلال موقعنا الإلكتروني.\n\n"
    "1) اضغط «اشترك» ليفتح لك موقع الاشتراك في المتصفح.\n"
    "2) اختر الباقة وادفع المبلغ.\n"
    "3) بعد الدفع يظهر لك كود تفعيل، أرسله هنا أو داخل القروب ويتفعّل اشتراكك فوراً."
)


def _subscribe_url(bot_username: str, chat_id: Optional[int]) -> str:
    """رابط صفحة الاشتراك في الموقع (يُفتح في المتصفح وليس داخل تليجرام)."""
    base = f"{settings.PUBLIC_BASE_URL}/subscribe.html"
    return f"{base}?g={chat_id}" if chat_id else base


def _subscribe_keyboard(bot_username: str, chat_id: Optional[int]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ اشترك ✅", url=_subscribe_url(bot_username, chat_id))]]
    )


def _redeem_reply(status: str, data: Optional[dict]) -> str:
    if status == db.REDEEM_OK:
        return (
            "✅ تم تفعيل اشتراكك بنجاح!\n\n"
            f"👥 المجموعة: {data.get('groupTitle', '')}\n"
            f"📦 الباقة: {data.get('planName', '')}\n"
            f"📅 صالح حتى: {_fmt_date(data.get('endDate'))}\n\n"
            "يمكنك الآن الكتابة في المجموعة بكل حرية 🎉"
        )
    if status == db.REDEEM_USED:
        return "⛔ هذا الكود مستخدم مسبقاً. كل كود يُستخدم مرة واحدة فقط."
    if status == db.REDEEM_WRONG_GROUP:
        title = (data or {}).get("groupTitle") or ""
        return "⚠️ هذا الكود خاص بمجموعة أخرى" + (f": «{title}»." if title else ".") + " أرسله داخل تلك المجموعة."
    return "❌ الكود غير صحيح. تأكد منه وأعد إرساله كما ظهر لك في الموقع بعد الدفع."


def _tg_user(user) -> dict:
    return {"id": user.id, "name": user.full_name, "username": user.username}


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
# 2) /start في الخاص -> رابط صفحة الاشتراك في الموقع، أو تفعيل كود
# ---------------------------------------------------------------------------

def _site_message(group_id: Optional[int], current_end=None) -> dict:
    current = (
        f"✅ اشتراكك الحالي ساري حتى {_fmt_date(current_end)}، ويمكنك التجديد مسبقاً وتُضاف المدة الجديدة إليه.\n\n"
        if current_end else ""
    )
    return {
        "text": current + SITE_PAY_TEXT,
        "reply_markup": InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ اشترك ✅", url=_subscribe_url("", group_id))]]
        ),
    }


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

    # رابط «فعّل اشتراكك» من صفحة نجاح الدفع: /start code_XXXXXXXX
    if arg.startswith("code_"):
        await _redeem_in_private(update, context, arg[5:])
        return

    if arg.startswith("sub_"):
        try:
            group_id = int(arg[4:])
        except ValueError:
            group_id = 0
        group = await db.get_linked_group(group_id) if group_id else None
        if group is None:
            await message.reply_text("عذراً، هذه المجموعة غير مفعّلة حالياً على البوت.")
            return
        end = await db.get_active_end_date(user_id, group_id)
        await message.reply_text(**_site_message(group_id, end))
        return

    # /start بدون رابط: نبحث عن المجموعات المربوطة التي هو عضو فيها
    groups = await _user_groups(context, user_id)
    if len(groups) == 1:
        group_id, _group = groups[0]
        end = await db.get_active_end_date(user_id, group_id)
        await message.reply_text(**_site_message(group_id, end))
        return
    if len(groups) > 1:
        rows = [[InlineKeyboardButton(f"👥 {g.get('title', '')}", url=_subscribe_url("", gid))] for gid, g in groups]
        await message.reply_text(
            f"أهلاً وسهلاً بك في بوت {settings.BOT_NAME} 🎉\n\n{SITE_PAY_TEXT}\n\nاختر المجموعة التي ترغب في الاشتراك بها 👇",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    await message.reply_text(
        f"أهلاً وسهلاً بك في بوت {settings.BOT_NAME} 🤖☁️\n\n"
        "🔒 الكتابة في المجموعة متاحة للمشتركين فقط.\n\n"
        "✅ للاشتراك: اضغط زر «اشترك» الموجود داخل المجموعة التي ترغب في الكتابة بها، "
        "وسيفتح لك موقع الاشتراك لاختيار الباقة والدفع، وبعدها أرسل كود التفعيل هنا.\n\n"
        "📋 لعرض اشتراكاتك: /mysubs\n"
        f"🛟 الدعم الفني: @{settings.SUPPORT_USERNAME}"
    )


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
# 3) تفعيل كود الدفع (من الموقع) — في الخاص أو داخل القروب
# ---------------------------------------------------------------------------

async def _redeem_in_private(update: Update, context: ContextTypes.DEFAULT_TYPE, code_text: str) -> None:
    message = update.effective_message
    user = update.effective_user
    status, data = await db.redeem_code(code_text, _tg_user(user))
    if status == db.REDEEM_NO_GROUP:
        # الكود غير مرتبط بقروب: نختار القروب الذي هو عضو فيه
        groups = await _user_groups(context, user.id)
        if len(groups) == 1:
            status, data = await db.redeem_code(code_text, _tg_user(user), groups[0][0])
        elif len(groups) > 1:
            code = db.normalize_redeem_code(code_text)
            rows = [[InlineKeyboardButton(f"👥 {g.get('title', '')}", callback_data=f"rdm|{code}|{gid}")] for gid, g in groups]
            await message.reply_text("اختر المجموعة التي تريد تفعيل اشتراكك فيها 👇", reply_markup=InlineKeyboardMarkup(rows))
            return
        else:
            await message.reply_text(
                "لم أجدك عضواً في أي مجموعة مفعّلة على البوت.\nأرسل الكود داخل المجموعة التي تريد الاشتراك بها وسيتفعّل اشتراكك فوراً."
            )
            return
    await message.reply_text(_redeem_reply(status, data))


async def redeem_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        _, code, gid = query.data.split("|", 2)
        group_id = int(gid)
    except ValueError:
        return
    status, data = await db.redeem_code(code, _tg_user(query.from_user), group_id)
    await query.edit_message_text(_redeem_reply(status, data))


async def private_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """أي نص في الخاص: لو كان كود تفعيل نفعّله، وإلا نوضّح طريقة الاشتراك."""
    message = update.effective_message
    if message is None or not message.text:
        return
    if db.looks_like_redeem_code(message.text):
        await _redeem_in_private(update, context, message.text)
        return
    await message.reply_text(**_site_message(None))


async def legacy_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """أزرار الباقات القديمة داخل تليجرام: الدفع الآن من الموقع فقط."""
    query = update.callback_query
    await query.answer()
    group_id = None
    try:
        group_id = int(query.data.split("|")[1])
    except (ValueError, IndexError):
        pass
    await query.edit_message_text(**_site_message(group_id))


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

    # كود تفعيل من الموقع أُرسل داخل القروب: نفعّله ونحذف رسالته حتى لا يظهر الكود
    if message.text and db.looks_like_redeem_code(message.text):
        status, data = await db.redeem_code(message.text, _tg_user(user), chat.id)
        try:
            await message.delete()
        except TelegramError:
            pass
        reply = await context.bot.send_message(
            chat_id=chat.id,
            text=f"{user.mention_html()}\n" + html.escape(_redeem_reply(status, data)),
            parse_mode=ParseMode.HTML,
        )
        await schedule_warning_delete(reply.chat_id, reply.message_id)
        return

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
            f"{user.mention_html()}\n"
            "⚠️ الاشتراك إلزامي للجميع لمنع الأرقام الوهمية والمحتالين ⚠️\n"
            "الكتابة هنا للمشتركين فقط، اضغط «اشترك» 👇"
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
    return "⚠️ الاشتراك إلزامي للجميع لمنع الأرقام الوهمية والمحتالين ⚠️"


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
    application.add_handler(CallbackQueryHandler(redeem_group_callback, pattern=r"^rdm\|"))
    # أزرار قديمة (الباقات داخل تليجرام): تُحوَّل الآن لصفحة الاشتراك في الموقع
    application.add_handler(CallbackQueryHandler(legacy_plan_callback, pattern=r"^(plan|grp)\|"))
    application.add_handler(ChatMemberHandler(my_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, migrate_handler))
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_text)
    )
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, guard_group_messages)
    )
