"""
اختبار منطق البوت + قاعدة البيانات على Firebase Emulator (بدون تليجرام أو ميسر حقيقي).

التشغيل (من مجلد telegram_sub_bot):
  firebase emulators:start --only auth,firestore --project demo-cloud
  functions/venv/bin/python -m pytest tests/test_flow.py -q
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
os.environ.setdefault("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
os.environ.update(
    FIREBASE_PROJECT_ID="demo-cloud",
    MOYASAR_WEBHOOK_SECRET="test-secret",
    MOYASAR_SECRET_KEY="sk_test",
    PLATFORM_COMMISSION_PERCENT="10",
    ADMIN_EMAILS="boss@example.com",
    BOT_USERNAME="CloudTestBot",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functions"))

import httpx  # noqa: E402
from telegram import ChatMemberAdministrator, ChatMemberMember, User  # noqa: E402
from telegram.constants import ChatType  # noqa: E402

import app_logic  # noqa: E402
import bot_handlers  # noqa: E402
import firebase_db as db  # noqa: E402
import moyasar_client  # noqa: E402

pytestmark = pytest.mark.asyncio

GROUP_ID = -1001234567890
ADMIN_TG = 111
MEMBER_TG = 222


def _clear_emulator():
    fs = os.environ["FIRESTORE_EMULATOR_HOST"]
    au = os.environ["FIREBASE_AUTH_EMULATOR_HOST"]
    httpx.delete(f"http://{fs}/emulator/v1/projects/demo-cloud/databases/(default)/documents")
    httpx.delete(f"http://{au}/emulator/v1/projects/demo-cloud/accounts")


@pytest.fixture(scope="module", autouse=True)
def setup_module():
    _clear_emulator()
    db.init_firebase()
    yield


@pytest.fixture(autouse=True)
def _fresh_cache():
    db.clear_caches()


def admin_member(can_delete=True):
    return ChatMemberAdministrator(
        user=User(999, "Cloud", True), can_be_edited=False, is_anonymous=False, can_manage_chat=True,
        can_delete_messages=can_delete, can_manage_video_chats=False, can_restrict_members=True,
        can_promote_members=False, can_change_info=False, can_invite_users=True,
        can_post_stories=False, can_edit_stories=False, can_delete_stories=False,
    )


def make_ctx(args=None, members=None):
    members = members or {}
    bot = MagicMock()
    bot.id = 999
    bot.username = "CloudTestBot"

    async def get_chat_member(chat_id, user_id):
        return members.get(user_id) or ChatMemberMember(user=User(user_id, "x", False))

    bot.get_chat_member = AsyncMock(side_effect=get_chat_member)
    bot.send_message = AsyncMock(return_value=SimpleNamespace(chat_id=GROUP_ID, message_id=5))
    bot.delete_message = AsyncMock()
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(title="قروب عقارات"))
    bot.get_chat_member_count = AsyncMock(return_value=350)
    return SimpleNamespace(bot=bot, args=args or [], job_queue=None)


def make_update(user_id, chat_type=ChatType.SUPERGROUP, chat_id=GROUP_ID):
    message = MagicMock()
    message.reply_text = AsyncMock()
    message.delete = AsyncMock()
    message.sender_chat = None
    message.is_automatic_forward = False
    message.text = None
    user = MagicMock(id=user_id, is_bot=False, full_name="عضو تجريبي", username="member1")
    user.mention_html.return_value = "<a>عضو</a>"
    chat = SimpleNamespace(id=chat_id, type=chat_type, title="قروب عقارات")
    return SimpleNamespace(effective_message=message, effective_user=user, effective_chat=chat, callback_query=None)


def create_owner(email="owner@example.com", name="صاحب القروب", verified=False):
    from firebase_admin import auth

    user = auth.create_user(email=email, password="secret123", email_verified=verified)
    db.db().collection("owners").document(user.uid).set(
        {"name": name, "email": email, "role": "owner", "createdAt": db.utcnow()}
    )
    return user.uid


def create_code(code, owner_uid, age_minutes=0):
    db.db().collection("linkCodes").document(code).set(
        {"ownerUid": owner_uid, "createdAt": db.utcnow() - dt.timedelta(minutes=age_minutes)}
    )


# ---------------------------------------------------------------------------

async def test_full_flow(monkeypatch):
    owner_uid = create_owner()
    other_uid = create_owner("other@example.com", "منافس")
    admins = {ADMIN_TG: admin_member(), 999: admin_member()}
    notify_ctx = make_ctx()
    monkeypatch.setattr(app_logic, "get_application", AsyncMock(return_value=SimpleNamespace(bot=notify_ctx.bot)))

    # --- عضو عادي لا يستطيع الربط ---
    create_code("AAAA2222", owner_uid)
    upd = make_update(MEMBER_TG)
    await bot_handlers.link_command(upd, make_ctx(["AAAA2222"], admins))
    assert "لمشرفي القروب فقط" in upd.effective_message.reply_text.call_args.args[0]

    # --- البوت بدون صلاحية حذف ---
    upd = make_update(ADMIN_TG)
    await bot_handlers.link_command(upd, make_ctx(["AAAA2222"], {ADMIN_TG: admin_member(), 999: admin_member(False)}))
    assert "حذف الرسائل" in upd.effective_message.reply_text.call_args.args[0]

    # --- كود منتهي ---
    create_code("OLDC0DE2", owner_uid, age_minutes=20)
    upd = make_update(ADMIN_TG)
    await bot_handlers.link_command(upd, make_ctx(["OLDC0DE2"], admins))
    assert "انتهت صلاحية" in upd.effective_message.reply_text.call_args.args[0]

    # --- الربط الناجح عبر /start CODE (زر أضف البوت) ---
    upd = make_update(ADMIN_TG)
    ctx = make_ctx(["aaaa2222"], admins)
    await bot_handlers.start_command(upd, ctx)
    group = db.db().collection("groups").document(str(GROUP_ID)).get().to_dict()
    assert group["ownerUid"] == owner_uid and group["active"] is True
    assert group["memberCount"] == 350 and group["canDelete"] is True
    assert not db.db().collection("linkCodes").document("AAAA2222").get().exists
    assert "تم ربط القروب بنجاح" in ctx.bot.send_message.call_args.args[1]

    # --- الكود لا يُستخدم مرتين / لا أحد يسرق القروب ---
    upd = make_update(ADMIN_TG)
    await bot_handlers.link_command(upd, make_ctx(["AAAA2222"], admins))
    assert "غير صحيح" in upd.effective_message.reply_text.call_args.args[0]
    create_code("BBBB3333", other_uid)
    upd = make_update(ADMIN_TG)
    await bot_handlers.link_command(upd, make_ctx(["BBBB3333"], admins))
    assert "مربوط مسبقاً" in upd.effective_message.reply_text.call_args.args[0]

    # --- غير المشترك تُحذف رسالته + يُجدول حذف التنبيه ---
    upd = make_update(MEMBER_TG)
    ctx = make_ctx(members=admins)
    await bot_handlers.guard_group_messages(upd, ctx)
    upd.effective_message.delete.assert_awaited_once()
    assert f"/subscribe.html?g={GROUP_ID}" in str(ctx.bot.send_message.call_args.kwargs["reply_markup"].to_dict())
    assert db.db().collection("groups").document(str(GROUP_ID)).get().to_dict()["blockedMessages"] == 1
    pending = db.db().collection("pendingDeletes").document(f"{GROUP_ID}_5").get().to_dict()
    assert pending and (pending["deleteAt"] - db.utcnow()).total_seconds() > 10
    # بعد مرور الوقت يُحذف التنبيه
    db.db().collection("pendingDeletes").document(f"{GROUP_ID}_5").update({"deleteAt": db.utcnow()})
    await bot_handlers.delete_due_warnings(ctx.bot)
    ctx.bot.delete_message.assert_awaited_once_with(chat_id=GROUP_ID, message_id=5)

    # --- مع Cloud Tasks: تُرسل مهمة بدل التسجيل الاحتياطي ---
    tasks = []
    monkeypatch.setattr(bot_handlers, "enqueue_delete_task", lambda c, m, d: tasks.append((c, m, d)))
    await bot_handlers.guard_group_messages(make_update(MEMBER_TG), make_ctx(members=admins))
    assert tasks == [(GROUP_ID, 5, 20)]
    monkeypatch.setattr(bot_handlers, "enqueue_delete_task", None)

    # --- المشرف لا تُحذف رسالته، والقروب غير المربوط لا يُلمس ---
    upd = make_update(ADMIN_TG)
    await bot_handlers.guard_group_messages(upd, make_ctx(members=admins))
    upd.effective_message.delete.assert_not_awaited()
    upd = make_update(MEMBER_TG, chat_id=-100555)
    await bot_handlers.guard_group_messages(upd, make_ctx(members=admins))
    upd.effective_message.delete.assert_not_awaited()

    # --- /start sub_<group> و /start بدون رابط -> رابط صفحة الاشتراك في الموقع ---
    upd = make_update(MEMBER_TG, chat_type=ChatType.PRIVATE, chat_id=MEMBER_TG)
    await bot_handlers.start_command(upd, make_ctx([f"sub_{GROUP_ID}"]))
    kw = upd.effective_message.reply_text.call_args.kwargs
    assert "موقعنا" in kw["text"] and f"subscribe.html?g={GROUP_ID}" in str(kw["reply_markup"].to_dict())
    upd = make_update(MEMBER_TG, chat_type=ChatType.PRIVATE, chat_id=MEMBER_TG)
    await bot_handlers.start_command(upd, make_ctx([], admins))
    assert f"subscribe.html?g={GROUP_ID}" in str(upd.effective_message.reply_text.call_args.kwargs["reply_markup"].to_dict())

    # --- الدفع من صفحة الاشتراك في الموقع ---
    invoices = {}

    async def fake_create_invoice(amount_sar, description, metadata, success_url=None, back_url=None):
        inv_id = f"inv_{len(invoices) + 1}"
        invoices[inv_id] = {"id": inv_id, "status": "initiated", "amount": int(amount_sar * 100), "currency": "SAR",
                            "url": f"https://checkout.moyasar.com/invoices/{inv_id}", "payments": [],
                            "metadata": metadata, "success_url": success_url}
        return invoices[inv_id]

    async def fake_fetch_invoice(inv_id):
        return invoices[inv_id]

    monkeypatch.setattr(moyasar_client, "create_invoice", fake_create_invoice)
    monkeypatch.setattr(moyasar_client, "fetch_invoice", fake_fetch_invoice)

    async def paid_code(plan_key, group=GROUP_ID):
        status, body = await app_logic.web_checkout(plan_key, str(group) if group else None)
        assert status == 200
        inv = body["invoiceId"]
        invoices[inv].update(status="paid", payments=[{"id": "pay_" + inv, "status": "paid", "source": {}}])
        status, body = await app_logic.web_order_status(inv, None)
        assert status == 200 and body["status"] == "ok"
        return inv, body["code"]

    assert (await app_logic.web_checkout("nope", str(GROUP_ID)))[0] == 400
    assert (await app_logic.web_checkout("plan_3m", "-1"))[0] == 404
    assert (await app_logic.web_group_info(str(GROUP_ID)))[1]["title"] == "قروب عقارات"
    status, body = await app_logic.web_checkout("plan_3m", str(GROUP_ID))
    assert status == 200 and body["invoiceId"] == "inv_1" and body["url"].startswith("https://checkout.moyasar.com")
    assert f"subscribe.html?g={GROUP_ID}" in invoices["inv_1"]["success_url"] and "paid=1" in invoices["inv_1"]["success_url"]
    order = db.db().collection("webOrders").document("inv_1").get().to_dict()
    assert order["status"] == "pending" and order["groupId"] == GROUP_ID and order["amount"] == 50.0

    # قبل الدفع: لا يوجد كود
    assert (await app_logic.web_order_status("inv_1", None))[1]["status"] == "not_paid"

    # --- Webhook ميسر يجهّز الكود حتى لو أغلق العضو الصفحة ---
    hook = app_logic.handle_moyasar_webhook
    assert (await hook({"type": "invoice_paid", "data": {"id": "inv_1"}, "secret_token": "wrong"}, None))[0] == 401
    assert (await hook({"type": "invoice_paid", "data": {"id": "inv_1"}, "secret_token": "test-secret"}, None))[1]["status"] == "not_paid"
    invoices["inv_1"].update(status="paid", payments=[{"id": "pay_1", "status": "paid", "source": {}}])
    assert (await hook({"type": "payment_paid", "data": {"invoice_id": "inv_1"}, "secret_token": "test-secret"}, None))[1]["status"] == "ok"
    status, body = await app_logic.web_order_status("inv_1", None)
    code1 = body["code"]
    assert status == 200 and len(code1) == 9 and code1[4] == "-" and body["botLink"].endswith("code_" + code1.replace("-", ""))
    assert (await app_logic.web_order_status("inv_1", None))[1]["code"] == code1  # نفس الكود دائماً
    assert code1 in await app_logic.payment_callback_html("pay_1", "inv_1")  # صفحة الرجوع تعرض الكود

    # --- تفعيل الكود في الخاص (حتى بأحرف صغيرة) ---
    upd = make_update(MEMBER_TG, chat_type=ChatType.PRIVATE, chat_id=MEMBER_TG)
    upd.effective_message.text = code1.lower()
    await bot_handlers.private_text(upd, make_ctx([], admins))
    assert "تم تفعيل اشتراكك" in upd.effective_message.reply_text.call_args.args[0]
    sub = db.db().collection("subscriptions").document("inv_1").get().to_dict()
    assert sub["status"] == "active" and sub["ownerUid"] == owner_uid and sub["paymentId"] == "pay_1"
    assert sub["telegramUserId"] == MEMBER_TG and sub["source"] == "web"
    assert sub["amount"] == 50.0 and sub["ownerShare"] == 45.0 and sub["commission"] == 5.0
    first_end = sub["endDate"]
    assert 89 <= (first_end - db.utcnow()).days <= 90

    # الكود يُستخدم مرة واحدة فقط
    upd = make_update(333, chat_type=ChatType.PRIVATE, chat_id=333)
    upd.effective_message.text = code1
    await bot_handlers.private_text(upd, make_ctx([], admins))
    assert "مستخدم مسبقاً" in upd.effective_message.reply_text.call_args.args[0]
    assert (await app_logic.web_order_status("inv_1", None))[1]["used"] is True

    # كود غير صحيح + رسالة عادية في الخاص توجّه للموقع
    upd = make_update(MEMBER_TG, chat_type=ChatType.PRIVATE, chat_id=MEMBER_TG)
    upd.effective_message.text = "ABCD-EFGH"
    await bot_handlers.private_text(upd, make_ctx([], admins))
    assert "غير صحيح" in upd.effective_message.reply_text.call_args.args[0]
    upd = make_update(MEMBER_TG, chat_type=ChatType.PRIVATE, chat_id=MEMBER_TG)
    upd.effective_message.text = "السلام عليكم"
    await bot_handlers.private_text(upd, make_ctx([], admins))
    assert "subscribe.html" in str(upd.effective_message.reply_text.call_args.kwargs["reply_markup"].to_dict())

    # المشترك يكتب في القروب بدون حذف
    db.clear_caches()
    upd = make_update(MEMBER_TG)
    upd.effective_message.text = "مرحبا"
    await bot_handlers.guard_group_messages(upd, make_ctx(members=admins))
    upd.effective_message.delete.assert_not_awaited()

    # --- التجديد: الكود يُرسل داخل القروب، يُحذف ويُضاف للمدة الحالية ---
    inv2, code2 = await paid_code("plan_6m")
    upd = make_update(MEMBER_TG)
    upd.effective_message.text = code2
    ctx = make_ctx(members=admins)
    await bot_handlers.guard_group_messages(upd, ctx)
    upd.effective_message.delete.assert_awaited_once()
    assert "تم تفعيل اشتراكك" in ctx.bot.send_message.call_args.kwargs["text"]
    sub2 = db.db().collection("subscriptions").document(inv2).get().to_dict()
    assert abs((sub2["startDate"] - first_end).total_seconds()) < 2
    assert (sub2["endDate"] - first_end).days == 180

    # --- كود قروب آخر لا يُفعَّل هنا ---
    db.db().collection("groups").document("-100777").set(
        {"ownerUid": other_uid, "title": "قروب آخر", "chatId": -100777, "active": True})
    inv3, code3 = await paid_code("plan_3m")
    upd = make_update(MEMBER_TG, chat_id=-100777)
    upd.effective_message.text = code3
    ctx = make_ctx(members=admins)
    await bot_handlers.guard_group_messages(upd, ctx)
    assert "خاص بمجموعة أخرى" in ctx.bot.send_message.call_args.kwargs["text"]
    assert db.db().collection("redeemCodes").document(code3.replace("-", "")).get().to_dict()["used"] is False
    db.db().collection("groups").document("-100777").update({"active": False})
    db.clear_caches()

    # --- كود بدون قروب (من صفحة الاشتراك مباشرة) يُفعَّل في قروب العضو ---
    inv4, code4 = await paid_code("plan_3m", group=None)
    assert db.db().collection("webOrders").document(inv4).get().to_dict()["groupId"] is None
    upd = make_update(MEMBER_TG, chat_type=ChatType.PRIVATE, chat_id=MEMBER_TG)
    await bot_handlers.start_command(upd, make_ctx(["code_" + code4.replace("-", "")], admins))
    assert "تم تفعيل اشتراكك" in upd.effective_message.reply_text.call_args.args[0]
    assert db.db().collection("subscriptions").document(inv4).get().to_dict()["groupId"] == GROUP_ID

    # --- مبلغ لا يطابق ---
    status, body = await app_logic.web_checkout("plan_6m", str(GROUP_ID))
    invoices[body["invoiceId"]].update(status="paid", amount=100)
    assert (await app_logic.web_order_status(body["invoiceId"], None))[1]["status"] == "amount_mismatch"

    # --- config.js ---
    js = await app_logic.config_js({"firestore": "", "auth": ""})
    assert "window.CLOUD_CONFIG" in js and "CloudTestBot" in js and "plan_3m" in js

    # --- التذكير ---
    ctx = make_ctx()
    assert await bot_handlers.run_reminders(ctx.bot) == 1
    assert "الاشتراك إلزامي للجميع" in ctx.bot.send_message.call_args.kwargs["text"]

    # --- الانتهاء ---
    for doc in db.db().collection("subscriptions").where("status", "==", "active").stream():
        doc.reference.update({"endDate": db.utcnow() - dt.timedelta(minutes=1)})
    ctx = make_ctx()
    assert await bot_handlers.run_expiry(ctx.bot) == 3
    statuses = {d.id: d.to_dict()["status"] for d in db.db().collection("subscriptions").stream()}
    assert statuses["inv_1"] == "expired" and statuses["inv_2"] == "expired" and statuses["inv_4"] == "expired"
    upd = make_update(MEMBER_TG)
    await bot_handlers.guard_group_messages(upd, make_ctx(members=admins))
    upd.effective_message.delete.assert_awaited_once()

    # --- إزالة البوت من القروب تعطّل الحماية ---
    change = SimpleNamespace(
        chat=SimpleNamespace(id=GROUP_ID, type=ChatType.SUPERGROUP, title="قروب عقارات"),
        new_chat_member=SimpleNamespace(status="left"),
    )
    await bot_handlers.my_chat_member_update(SimpleNamespace(my_chat_member=change), make_ctx())
    assert await db.get_linked_group(GROUP_ID) is None

    # --- تحويل القروب لـ supergroup ينقل البيانات ---
    await db.migrate_group(GROUP_ID, -100999)
    assert db.db().collection("groups").document("-100999").get().exists
    assert all(d.to_dict()["groupId"] == -100999 for d in db.db().collection("subscriptions").stream())


async def test_admin_requires_verified_email():
    from firebase_admin import auth

    uid = create_owner("boss@example.com", "Boss", verified=False)
    await db.sync_admin_roles()
    assert db.db().collection("owners").document(uid).get().to_dict()["role"] == "owner"
    auth.update_user(uid, email_verified=True)
    await db.sync_admin_roles()
    assert db.db().collection("owners").document(uid).get().to_dict()["role"] == "admin"
