import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatMemberUpdated,
)
from aiogram.enums import ChatType

import config
import database as dbm
import payments

logging.basicConfig(level=logging.INFO)
router = Router()

bot: Bot = None  # يُهيأ في main()


# ---------------- أدوات مساعدة ----------------
def is_admin(telegram_id: int) -> bool:
    return telegram_id in config.ADMIN_IDS


# الأسعار الرسمية الثابتة — مو قابلة للتعديل من داخل البوت (حتى الأدمن)
PLANS = {
    3: 50,
    6: 80,
}


def plans_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"اشتراك 3 أشهر — {PLANS[3]} ريال", callback_data="plan:3")],
            [InlineKeyboardButton(text=f"اشتراك 6 أشهر — {PLANS[6]} ريال", callback_data="plan:6")],
        ]
    )


def contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ تأكيد رقم الهاتف", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


WELCOME_TEXT = (
    "اهلا وسهلا بك في بوت {name} 🎉🎉\n\n"
    "⚠️ من اجل منع عمليات الاحتيال داخل المجموعة, يجب التاكيد على رقم الهاتف للمستخدم ⚠️\n\n"
    "اضغط على الزر في الاسفل ⬇️⬇️"
)


# ---------------- خاص: /start ----------------
@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def start_handler(message: Message):
    dbm.upsert_user(
        message.from_user.id,
        first_name=message.from_user.first_name,
        username=message.from_user.username,
    )
    bot_name = dbm.get_setting("bot_display_name", "cloud")

    if dbm.has_phone(message.from_user.id):
        if dbm.is_subscribed(message.from_user.id):
            await message.answer("اشتراكك فعّال حاليا ✅، تقدر ترسل في القروب بدون مشاكل.")
        else:
            await message.answer(
                "اختر مدة الاشتراك المناسبة لك:",
                reply_markup=plans_keyboard(),
            )
        return

    await message.answer(
        WELCOME_TEXT.format(name=bot_name),
        reply_markup=contact_keyboard(),
    )


# ---------------- خاص: استلام رقم الهاتف ----------------
@router.message(F.contact, F.chat.type == ChatType.PRIVATE)
async def contact_handler(message: Message):
    if message.contact.user_id != message.from_user.id:
        await message.answer("الرجاء إرسال رقم هاتفك أنت فقط عبر الزر.")
        return

    dbm.upsert_user(message.from_user.id, phone=message.contact.phone_number)

    await message.answer("تم تأكيد رقمك بنجاح ✅", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "اختر مدة الاشتراك المناسبة لك:",
        reply_markup=plans_keyboard(),
    )


# ---------------- خاص: اختيار الخطة وإصدار فاتورة الدفع ----------------
@router.callback_query(F.data.startswith("plan:"))
async def plan_chosen(callback):
    months = int(callback.data.split(":")[1])
    if months not in PLANS:
        await callback.answer("باقة غير متاحة.")
        return
    amount = PLANS[months]

    try:
        invoice = payments.create_invoice(amount, callback.from_user.id, months)
    except Exception as e:
        logging.exception("Moyasar invoice error")
        await callback.message.answer("صار خطأ أثناء إنشاء عملية الدفع، حاول لاحقاً.")
        await callback.answer()
        return

    dbm.create_payment(invoice["id"], callback.from_user.id, months, amount)

    pay_url = invoice["url"]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💳 ادفع الآن عبر ميسر", url=pay_url)]]
    )
    await callback.message.answer(
        f"الاشتراك: {months} شهر\nالمبلغ: {amount} ريال\n\nاضغط الزر بالأسفل لإتمام الدفع:",
        reply_markup=kb,
    )
    await callback.answer()


# ---------------- أوامر الأدمن (تعمل بالخاص فقط) ----------------
# ملاحظة: لا يوجد أمر لتغيير السعر — الأسعار (3 أشهر=50 ريال / 6 أشهر=80 ريال) ثابتة ورسمية
# ومكتوبة مباشرة في الكود (متغيّر PLANS بالأعلى). لو احتجت تغييرها مستقبلاً، التعديل يكون
# يدويًا في الكود من قِبل المطوّر فقط، وليس عبر أي أمر داخل تيليجرام.

@router.message(Command("setbotname"), F.chat.type == ChatType.PRIVATE)
async def set_bot_name(message: Message):
    if not is_admin(message.from_user.id):
        return
    new_name = message.text.partition(" ")[2].strip()
    if not new_name:
        await message.answer("الاستخدام: /setbotname الاسم الجديد")
        return
    await bot.set_my_name(new_name)
    dbm.set_setting("bot_display_name", new_name)
    await message.answer(f"تم تغيير اسم البوت إلى: {new_name} ✅")


@router.message(Command("mystatus"), F.chat.type == ChatType.PRIVATE)
async def my_status(message: Message):
    end = dbm.get_subscription_end(message.from_user.id)
    if dbm.is_subscribed(message.from_user.id):
        import datetime
        d = datetime.datetime.fromtimestamp(end).strftime("%Y-%m-%d %H:%M")
        await message.answer(f"اشتراكك فعّال حتى: {d}")
    else:
        await message.answer("ماعندك اشتراك فعّال حالياً.")


# ---------------- تحديد القروب تلقائياً عند إضافة البوت كأدمن ----------------
@router.my_chat_member()
async def on_added_to_group(event: ChatMemberUpdated):
    if event.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        if event.new_chat_member.status in ("administrator", "member"):
            dbm.set_setting("group_id", str(event.chat.id))
            logging.info(f"Group id set to {event.chat.id}")


# ---------------- مراقبة رسائل القروب ----------------
@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def group_message_handler(message: Message):
    configured_group = dbm.get_setting("group_id", "")
    if configured_group and str(message.chat.id) != configured_group:
        return  # يراقب فقط القروب المحدد

    user = message.from_user
    if user is None or user.is_bot:
        return

    # لا نحذف رسائل الأدمنية
    if is_admin(user.id):
        return

    member = await bot.get_chat_member(message.chat.id, user.id)
    if member.status in ("administrator", "creator"):
        return

    if dbm.is_subscribed(user.id):
        return  # مشترك، اتركه يرسل بحرية

    # مو مشترك -> نحذف رسالته فوراً
    try:
        await message.delete()
    except Exception:
        logging.warning("تعذر حذف الرسالة (صلاحيات؟)")

    if not dbm.should_warn(user.id, config.WARN_COOLDOWN_SECONDS):
        return  # تفادي تكرار التحذير كل رسالة

    me = await bot.get_me()
    deep_link = f"https://t.me/{me.username}?start=sub"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔔 اشترك الآن", url=deep_link)]]
    )
    await message.answer(
        f"⚠️ {user.first_name}، يجب الاشتراك أولاً حتى تقدر ترسل بالقروب.",
        reply_markup=kb,
    )


async def main():
    global bot
    bot = Bot(token=config.BOT_TOKEN)
    dbm.init_db()
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
