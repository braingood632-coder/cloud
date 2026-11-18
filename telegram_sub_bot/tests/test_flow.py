"""
اختبار شامل للبوت + قاعدة البيانات على Firebase Emulator (بدون تليجرام أو ميسر حقيقي).

التشغيل:
  firebase emulators:start --only auth,firestore --project demo-cloud
  FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099 \
    python -m pytest tests -q
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
    RUN_BOT="false",
    MOYASAR_WEBHOOK_SECRET="test-secret",
    MOYASAR_SECRET_KEY="sk_test",
    PLATFORM_COMMISSION_PERCENT="10",
    ADMIN_EMAILS="boss@example.com",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from telegram import ChatMemberAdministrator, ChatMemberMember, User  # noqa: E402
from telegram.constants import ChatType  # noqa: E402

import bot_handlers  # noqa: E402
import firebase_db as db  # noqa: E402
import moyasar_client  # noqa: E402
import webhook_server  # noqa: E402

GROUP_ID = -1001234567890
ADMIN_TG = 111
MEMBER_TG = 222


def _clear_emulator():
    httpx.delete("http://127.0.0.1:8080/emulator/v1/projects/demo-cloud/databases/(default)/documents")
    httpx.delete("http://127.0.0.1:9099/emulator/v1/projects/demo-cloud/accounts")


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
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(title="قروب عقارات"))
    bot.get_chat_member_count = AsyncMock(return_value=350)
    return SimpleNamespace(bot=bot, args=args or [], job_queue=None)


def make_update(user_id, chat_type=ChatType.SUPERGROUP, chat_id=GROUP_ID, text="hi"):
    message = MagicMock()
    message.reply_text = AsyncMock()
    message.delete = AsyncMock()
    message.sender_chat = None
    message.is_automatic_forward = False
    user = MagicMock(id=user_id, is_bot=False, full_name="عضو تجريبي", username="member1")
    user.mention_html.return_value = "<a>عضو</a>"
    chat = SimpleNamespace(id=chat_id, type=chat_type, title="قروب عقارات")
    return SimpleNamespace(effective_message=message, effective_user=user, effective_chat=chat, callback_query=None)


def create_owner(email="owner@example.com", name="صاحب القروب"):
    from firebase_admin import auth

    user = auth.create_user(email=email, password="secret123")
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
    ctx = make_ctx(["aaaa2222"], admins)  # حروف صغيرة تُقبل
    await bot_handlers.start_command(upd, ctx)
    group = db.db().collection("groups").document(str(GROUP_ID)).get().to_dict()
    assert group["ownerUid"] == owner_uid and group["active"] is True
    assert group["memberCount"] == 350 and group["canDelete"] is True
    assert not db.db().collection("linkCodes").document("AAAA2222").get().exists
    assert "تم ربط القروب بنجاح" in ctx.bot.send_message.call_args.args[1]

    # --- الكود لا يُستخدم مرتين ---
    upd = make_update(ADMIN_TG)
    await bot_handlers.link_command(upd, make_ctx(["AAAA2222"], admins))
    assert "غير صحيح" in upd.effective_message.reply_text.call_args.args[0]

    # --- حساب آخر لا يستطيع سرقة القروب ---
    create_code("BBBB3333", other_uid)
    upd = make_update(ADMIN_TG)
    await bot_handlers.link_command(upd, make_ctx(["BBBB3333"], admins))
    assert "مربوط مسبقاً" in upd.effective_message.reply_text.call_args.args[0]

    # --- غير المشترك تُحذف رسالته ---
    upd = make_update(MEMBER_TG)
    ctx = make_ctx(members=admins)
    await bot_handlers.guard_group_messages(upd, ctx)
    upd.effective_message.delete.assert_awaited_once()
    assert f"start=sub_{GROUP_ID}" in str(ctx.bot.send_message.call_args.kwargs["reply_markup"].to_dict())
    assert db.db().collection("groups").document(str(GROUP_ID)).get().to_dict()["blockedMessages"] == 1

    # --- المشرف لا تُحذف رسالته ---
    upd = make_update(ADMIN_TG)
    await bot_handlers.guard_group_messages(upd, make_ctx(members=admins))
    upd.effective_message.delete.assert_not_awaited()

    # --- قروب غير مربوط: البوت لا يتدخل ---
    upd = make_update(MEMBER_TG, chat_id=-100555)
    await bot_handlers.guard_group_messages(upd, make_ctx(members=admins))
    upd.effective_message.delete.assert_not_awaited()

    # --- /start sub_<group> في الخاص يعرض الباقات ---
    upd = make_update(MEMBER_TG, chat_type=ChatType.PRIVATE, chat_id=MEMBER_TG)
    await bot_handlers.start_command(upd, make_ctx([f"sub_{GROUP_ID}"]))
    kb = upd.effective_message.reply_text.call_args.kwargs["reply_markup"].to_dict()
    assert f"plan|{GROUP_ID}|plan_3m" in str(kb)
    assert "قم باختيار إحدى باقات الاشتراك" in upd.effective_message.reply_text.call_args.kwargs["text"]

    # --- /start بدون رابط: يكتشف مجموعة العضو ويعرض الباقات مباشرة ---
    upd = make_update(MEMBER_TG, chat_type=ChatType.PRIVATE, chat_id=MEMBER_TG)
    await bot_handlers.start_command(upd, make_ctx([], admins))
    assert f"plan|{GROUP_ID}|plan_6m" in str(upd.effective_message.reply_text.call_args.kwargs["reply_markup"].to_dict())

    # --- رسالة التذكير ---
    text = bot_handlers.build_reminder_text("قروب عقارات")
    assert "مقتصرٌ على المشتركين" in text and "50 ريال" in text

    # --- اختيار الباقة ينشئ فاتورة واشتراك pending ---
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
        upd = SimpleNamespace(callback_query=query)
        await bot_handlers.choose_plan_callback(upd, make_ctx())
        return query

    q = await choose("plan_3m")
    assert "checkout.moyasar.com" in str(q.edit_message_text.call_args.kwargs["reply_markup"].to_dict())
    sub = db.db().collection("subscriptions").document("inv_1").get().to_dict()
    assert sub["status"] == "pending" and sub["ownerUid"] == owner_uid
    assert sub["amount"] == 50.0 and sub["ownerShare"] == 45.0 and sub["commission"] == 5.0

    # --- Webhook ---
    with TestClient(webhook_server.app) as client:
        r = client.post("/moyasar/webhook", json={"type": "invoice_paid", "data": {"id": "inv_1"}, "secret_token": "wrong"})
        assert r.status_code == 401

        # غير مدفوعة فعلياً عند ميسر -> لا تفعيل (حماية من إشعار مزيف)
        r = client.post("/moyasar/webhook", json={"type": "invoice_paid", "data": {"id": "inv_1"}, "secret_token": "test-secret"})
        assert r.json()["status"] == "not_paid"

        invoices["inv_1"].update(status="paid", payments=[{"id": "pay_1", "status": "paid", "source": {}}])
        r = client.post("/moyasar/webhook", json={"type": "payment_paid", "data": {"invoice_id": "inv_1"}, "secret_token": "test-secret"})
        assert r.json()["status"] == "ok"
        r = client.post("/moyasar/webhook", json={"type": "invoice_paid", "data": {"id": "inv_1"}},
                        headers={"x-moyasar-token": "test-secret"})
        assert r.json()["status"] == "already"

        sub = db.db().collection("subscriptions").document("inv_1").get().to_dict()
        assert sub["status"] == "active" and sub["paymentId"] == "pay_1"
        first_end = sub["endDate"]
        assert 89 <= (first_end - db.utcnow()).days <= 90

        # المشترك الآن تمر رسالته
        db.clear_caches()
        upd = make_update(MEMBER_TG)
        await bot_handlers.guard_group_messages(upd, make_ctx(members=admins))
        upd.effective_message.delete.assert_not_awaited()

        # --- التجديد يُضاف على نهاية الاشتراك الحالي ---
        await choose("plan_6m")
        invoices["inv_2"].update(status="paid", amount=8000, payments=[{"id": "pay_2", "status": "paid"}])
        r = client.get("/payment/callback", params={"id": "pay_2", "invoice_id": "inv_2"})
        assert "تم الدفع بنجاح" in r.text
        sub2 = db.db().collection("subscriptions").document("inv_2").get().to_dict()
        assert abs((sub2["startDate"] - first_end).total_seconds()) < 2
        assert (sub2["endDate"] - first_end).days == 180

        # --- مبلغ لا يطابق -> رفض ---
        await choose("plan_6m")
        invoices["inv_3"].update(status="paid", amount=100)
        r = client.post("/moyasar/webhook", json={"type": "invoice_paid", "data": {"id": "inv_3"}, "secret_token": "test-secret"})
        assert r.json()["status"] == "amount_mismatch"

        # --- الموقع و config.js ---
        assert "window.CLOUD_CONFIG" in client.get("/config.js").text
        assert "بوت Cloud" in client.get("/").text

    # --- الانتهاء ---
    for doc in db.db().collection("subscriptions").where("status", "==", "active").stream():
        doc.reference.update({"endDate": db.utcnow() - dt.timedelta(minutes=1)})
    ctx = make_ctx()
    await bot_handlers.check_expired_subscriptions_job(ctx)
    statuses = {d.id: d.to_dict()["status"] for d in db.db().collection("subscriptions").stream()}
    assert statuses["inv_1"] == "expired" and statuses["inv_2"] == "expired"
    assert ctx.bot.send_message.await_count == 2
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


async def test_admin_sync():
    from firebase_admin import auth

    user = auth.create_user(email="boss@example.com", password="secret123")
    db.db().collection("owners").document(user.uid).set({"name": "Boss", "email": "boss@example.com", "role": "owner"})
    await db.sync_admin_roles()
    assert db.db().collection("owners").document(user.uid).get().to_dict()["role"] == "admin"
