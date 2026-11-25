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
    upd.effective_message.reply_text.assert_not_awaited()  # قبل الربط: صمت تام
    # /link بدون كود: صمت أيضاً
    upd = make_update(ADMIN_TG)
    await bot_handlers.link_command(upd, make_ctx([], admins))
    upd.effective_message.reply_text.assert_not_awaited()

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
    assert f"start=sub_{GROUP_ID}" in str(ctx.bot.send_message.call_args.kwargs["reply_markup"].to_dict())
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

    # --- /start sub_<group> و /start بدون رابط ---
    upd = make_update(MEMBER_TG, chat_type=ChatType.PRIVATE, chat_id=MEMBER_TG)
    await bot_handlers.start_command(upd, make_ctx([f"sub_{GROUP_ID}"]))
    assert "قم باختيار إحدى باقات الاشتراك" in upd.effective_message.reply_text.call_args.kwargs["text"]
    upd = make_update(MEMBER_TG, chat_type=ChatType.PRIVATE, chat_id=MEMBER_TG)
    await bot_handlers.start_command(upd, make_ctx([], admins))
    assert f"plan|{GROUP_ID}|plan_6m" in str(upd.effective_message.reply_text.call_args.kwargs["reply_markup"].to_dict())

    # --- اختيار الباقة -> فاتورة ---
    invoices = {}

    async def fake_create_invoice(amount_sar, description, telegram_user_id, group_id, plan_key):
        inv_id = f"inv_{len(invoices) + 1}"
        invoices[inv_id] = {"id": inv_id, "status": "initiated", "amount": int(amount_sar * 100), "currency": "SAR",
                            "url": f"https://checkout.moyasar.com/invoices/{inv_id}", "payments": []}
        return invoices[inv_id]

    async def fake_fetch_invoice(inv_id):
        return invoices[inv_id]

    monkeypatch.setattr(moyasar_client, "create_invoice", fake_create_invoice)
    monkeypatch.setattr(moyasar_client, "fetch_invoice", fake_fetch_invoice)

    async def choose(plan_key):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = f"plan|{GROUP_ID}|{plan_key}"
        query.from_user = MagicMock(id=MEMBER_TG, full_name="عضو تجريبي", username="member1")
        await bot_handlers.choose_plan_callback(SimpleNamespace(callback_query=query), make_ctx())
        return query

    q = await choose("plan_3m")
    assert "checkout.moyasar.com" in str(q.edit_message_text.call_args.kwargs["reply_markup"].to_dict())
    sub = db.db().collection("subscriptions").document("inv_1").get().to_dict()
    assert sub["status"] == "pending" and sub["ownerUid"] == owner_uid
    assert sub["amount"] == 50.0 and sub["ownerShare"] == 45.0 and sub["commission"] == 5.0

    # --- Webhook ميسر ---
    hook = app_logic.handle_moyasar_webhook
    assert (await hook({"type": "invoice_paid", "data": {"id": "inv_1"}, "secret_token": "wrong"}, None))[0] == 401
    assert (await hook({"type": "invoice_paid", "data": {"id": "inv_1"}, "secret_token": "test-secret"}, None))[1]["status"] == "not_paid"
    invoices["inv_1"].update(status="paid", payments=[{"id": "pay_1", "status": "paid", "source": {}}])
    assert (await hook({"type": "payment_paid", "data": {"invoice_id": "inv_1"}, "secret_token": "test-secret"}, None))[1]["status"] == "ok"
    assert (await hook({"type": "invoice_paid", "data": {"id": "inv_1"}}, "test-secret"))[1]["status"] == "already"
    assert "تم تفعيل اشتراكك" in notify_ctx.bot.send_message.call_args.kwargs["text"]

    sub = db.db().collection("subscriptions").document("inv_1").get().to_dict()
    assert sub["status"] == "active" and sub["paymentId"] == "pay_1"
    first_end = sub["endDate"]
    assert 89 <= (first_end - db.utcnow()).days <= 90

    db.clear_caches()
    upd = make_update(MEMBER_TG)
    await bot_handlers.guard_group_messages(upd, make_ctx(members=admins))
    upd.effective_message.delete.assert_not_awaited()

    # --- التجديد يُضاف على نهاية الاشتراك الحالي (عبر صفحة الرجوع) ---
    await choose("plan_6m")
    invoices["inv_2"].update(status="paid", payments=[{"id": "pay_2", "status": "paid"}])
    assert "تم الدفع بنجاح" in await app_logic.payment_callback_html("pay_2", "inv_2")
    sub2 = db.db().collection("subscriptions").document("inv_2").get().to_dict()
    assert abs((sub2["startDate"] - first_end).total_seconds()) < 2
    assert (sub2["endDate"] - first_end).days == 180

    # --- مبلغ لا يطابق ---
    await choose("plan_6m")
    invoices["inv_3"].update(status="paid", amount=100)
    assert (await hook({"type": "invoice_paid", "data": {"id": "inv_3"}, "secret_token": "test-secret"}, None))[1]["status"] == "amount_mismatch"

    # --- الفاتورة غير المدفوعة تُلغى بعد انتهاء مهلة الـ 30 دقيقة ---
    assert await db.cancel_unpaid() == 0  # لسا داخل المهلة
    assert db.db().collection("subscriptions").document("inv_3").get().to_dict()["status"] == "pending"
    db.db().collection("subscriptions").document("inv_3").update({"createdAt": db.utcnow() - dt.timedelta(minutes=31)})
    assert await db.cancel_unpaid() == 1
    assert db.db().collection("subscriptions").document("inv_3").get().to_dict()["status"] == "canceled"
    assert db.db().collection("subscriptions").document("inv_1").get().to_dict()["status"] == "active"  # المدفوع لا يتأثر

    # --- شراء من البوت مباشرة (ليس عضواً في أي قروب) -> كود بعد الدفع يُكتب في القروب ---
    from telegram import ChatMemberLeft

    buyer = 444
    outsider = {buyer: ChatMemberLeft(user=User(buyer, "x", False))}
    upd = make_update(buyer, chat_type=ChatType.PRIVATE, chat_id=buyer)
    await bot_handlers.start_command(upd, make_ctx([], outsider))
    kw = upd.effective_message.reply_text.call_args.kwargs
    assert "قم باختيار إحدى باقات الاشتراك" in kw["text"] and "plan|0|plan_3m" in str(kw["reply_markup"].to_dict())

    async def choose_as(user_id, group, plan_key):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = f"plan|{group}|{plan_key}"
        query.from_user = MagicMock(id=user_id, full_name="مشتري", username="buyer1")
        await bot_handlers.choose_plan_callback(SimpleNamespace(callback_query=query), make_ctx())
        return query, f"inv_{len(invoices)}"

    q, inv_code = await choose_as(buyer, 0, "plan_3m")
    assert "checkout.moyasar.com" in str(q.edit_message_text.call_args.kwargs["reply_markup"].to_dict())
    assert db.db().collection("codeOrders").document(inv_code).get().to_dict()["status"] == "pending"
    assert not db.db().collection("subscriptions").document(inv_code).get().exists
    assert (await hook({"type": "invoice_paid", "data": {"id": inv_code}, "secret_token": "test-secret"}, None))[1]["status"] == "not_paid"

    invoices[inv_code].update(status="paid", payments=[{"id": "pay_code1", "status": "paid", "source": {}}])
    notify_ctx.bot.send_message.reset_mock()
    assert (await hook({"type": "payment_paid", "data": {"invoice_id": inv_code}, "secret_token": "test-secret"}, None))[1]["status"] == "ok"
    sent = notify_ctx.bot.send_message.call_args.kwargs
    code1 = db.db().collection("codeOrders").document(inv_code).get().to_dict()["code"]
    assert sent["chat_id"] == buyer and db.format_redeem_code(code1) in sent["text"] and "مرة واحدة" in sent["text"]
    # إعادة الإشعار لا تولّد كوداً جديداً ولا ترسله مرة ثانية
    notify_ctx.bot.send_message.reset_mock()
    assert (await hook({"type": "invoice_paid", "data": {"id": inv_code}, "secret_token": "test-secret"}, None))[1]["status"] == "already"
    notify_ctx.bot.send_message.assert_not_awaited()
    assert db.db().collection("codeOrders").document(inv_code).get().to_dict()["code"] == code1
    assert db.format_redeem_code(code1) in await app_logic.payment_callback_html(None, inv_code)

    # كل عملية دفع لها كود جديد مختلف
    _, inv_code2 = await choose_as(buyer, 0, "plan_6m")
    invoices[inv_code2].update(status="paid", payments=[{"id": "pay_code2", "status": "paid", "source": {}}])
    assert (await hook({"type": "invoice_paid", "data": {"id": inv_code2}, "secret_token": "test-secret"}, None))[1]["status"] == "ok"
    code2 = db.db().collection("codeOrders").document(inv_code2).get().to_dict()["code"]
    assert code2 != code1

    # الكود الصحيح داخل القروب: لا تُحذف رسالته ويتفعّل اشتراكه بمدة الباقة
    upd = make_update(buyer)
    upd.effective_message.text = db.format_redeem_code(code1).lower()
    ctx = make_ctx(members=admins)
    await bot_handlers.guard_group_messages(upd, ctx)
    upd.effective_message.delete.assert_not_awaited()
    assert "تم تفعيل اشتراكك" in ctx.bot.send_message.call_args.kwargs["text"]
    sub = db.db().collection("subscriptions").document(inv_code).get().to_dict()
    assert sub["status"] == "active" and sub["groupId"] == GROUP_ID and sub["ownerUid"] == owner_uid
    assert sub["telegramUserId"] == buyer and sub["source"] == "code" and sub["amount"] == 50.0
    assert 89 <= (sub["endDate"] - db.utcnow()).days <= 90

    # بعدها يكتب عادي بدون حذف
    db.clear_caches()
    upd = make_update(buyer)
    upd.effective_message.text = "السلام عليكم"
    await bot_handlers.guard_group_messages(upd, make_ctx(members=admins))
    upd.effective_message.delete.assert_not_awaited()

    # نفس الكود مرة ثانية (من شخص آخر): يُحذف ويُرفض
    upd = make_update(555)
    upd.effective_message.text = db.format_redeem_code(code1)
    ctx = make_ctx(members=admins)
    await bot_handlers.guard_group_messages(upd, ctx)
    upd.effective_message.delete.assert_awaited_once()
    assert "مستخدم مسبقاً" in ctx.bot.send_message.call_args.kwargs["text"]
    # كود غير صحيح: يُحذف ويُرفض
    upd = make_update(555)
    upd.effective_message.text = "ABCD-EFGH"
    ctx = make_ctx(members=admins)
    await bot_handlers.guard_group_messages(upd, ctx)
    upd.effective_message.delete.assert_awaited_once()
    assert "غير صحيح" in ctx.bot.send_message.call_args.kwargs["text"]

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
    assert statuses["inv_1"] == "expired" and statuses["inv_2"] == "expired"
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


def _emulator_sign_in(email, password):
    au = os.environ["FIREBASE_AUTH_EMULATOR_HOST"]
    r = httpx.post(f"http://{au}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=fake",
                   json={"email": email, "password": password, "returnSecureToken": True})
    return r.json().get("idToken")


async def test_admin_creates_accounts():
    from config import LOGIN_EMAIL_DOMAIN

    admin_uid = create_owner("chief@example.com", "Chief", verified=True)
    db.db().collection("owners").document(admin_uid).update({"role": "admin"})
    admin_token = _emulator_sign_in("chief@example.com", "secret123")
    normal_uid = create_owner("normal@example.com", "Normal")
    normal_token = _emulator_sign_in("normal@example.com", "secret123")
    assert admin_token and normal_token

    new = {"action": "create", "name": "أحمد", "username": "Ahmed_1", "password": "pass123", "phone": "0500000000"}
    # غير الأدمن ممنوع
    assert app_logic.admin_users_sync(normal_token, new)[0] == 403
    assert app_logic.admin_users_sync("bad-token", new)[0] == 401
    # تحقق من المدخلات
    assert app_logic.admin_users_sync(admin_token, {**new, "username": "a!"})[1]["error"] == "bad_username"
    assert app_logic.admin_users_sync(admin_token, {**new, "password": "123"})[1]["error"] == "weak_password"
    # إنشاء الحساب
    status, body = app_logic.admin_users_sync(admin_token, new)
    assert status == 200 and body["username"] == "ahmed_1"
    owner = db.db().collection("owners").document(body["uid"]).get().to_dict()
    assert owner["role"] == "owner" and owner["username"] == "ahmed_1" and owner["email"] == f"ahmed_1@{LOGIN_EMAIL_DOMAIN}"
    assert _emulator_sign_in(f"ahmed_1@{LOGIN_EMAIL_DOMAIN}", "pass123")
    # اسم مستخدم مكرر
    assert app_logic.admin_users_sync(admin_token, new)[0] == 409
    # تغيير كلمة المرور
    assert app_logic.admin_users_sync(admin_token, {"action": "password", "uid": body["uid"], "password": "newpass9"})[0] == 200
    assert _emulator_sign_in(f"ahmed_1@{LOGIN_EMAIL_DOMAIN}", "newpass9")
    assert not _emulator_sign_in(f"ahmed_1@{LOGIN_EMAIL_DOMAIN}", "pass123")
    assert app_logic.admin_users_sync(admin_token, {"action": "password", "uid": "nope", "password": "newpass9"})[0] == 404
    # تغيير الإيميل/اسم المستخدم
    assert app_logic.admin_users_sync(admin_token, {"action": "email", "uid": body["uid"], "login": "bad!name"})[1]["error"] == "bad_username"
    status, r = app_logic.admin_users_sync(admin_token, {"action": "email", "uid": body["uid"], "login": "New.Mail@Example.com"})
    assert status == 200 and r["email"] == "new.mail@example.com"
    assert _emulator_sign_in("new.mail@example.com", "newpass9")
    owner = db.db().collection("owners").document(body["uid"]).get().to_dict()
    assert owner["email"] == "new.mail@example.com" and "username" not in owner
    assert app_logic.admin_users_sync(admin_token, {"action": "email", "uid": body["uid"], "login": "normal@example.com"})[0] == 409
    assert app_logic.admin_users_sync(normal_token, {"action": "email", "uid": body["uid"], "login": "x@y.com"})[0] == 403
    assert normal_uid
    # الأرقام العربية في كلمة المرور تتحول لإنجليزية
    status, b2 = app_logic.admin_users_sync(admin_token, {"action": "create", "name": "سارة", "username": "sara ٢", "password": "pass١٢٣"})
    assert status == 200 and b2["username"] == "sara2"
    assert _emulator_sign_in(f"sara2@{LOGIN_EMAIL_DOMAIN}", "pass123")
