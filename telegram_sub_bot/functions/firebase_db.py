"""
firebase_db.py
--------------
طبقة قاعدة البيانات على Firebase Firestore (بدل SQLite).

المجموعات (Collections):
  owners/{uid}            حسابات أصحاب القروبات (تُنشأ من الموقع عند التسجيل)
  linkCodes/{code}        أكواد ربط مؤقتة يولّدها صاحب القروب من لوحة التحكم
  groups/{chatId}         القروبات المربوطة بالبوت ولمن تتبع
  subscriptions/{invoice} كل اشتراك (فاتورة ميسر) لعضو في قروب معيّن
  payouts/{id}            التحويلات التي حوّلتها أنت لأصحاب القروبات

كل الدوال هنا async وتشغّل عميل Firestore المتزامن داخل thread منفصل حتى
لا توقف البوت.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import secrets
import time
from typing import Any, Optional

import firebase_admin
from firebase_admin import auth as fb_auth
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from config import (
    INVOICE_EXPIRY_MINUTES,
    CACHE_TTL_SECONDS,
    LINK_CODE_TTL_MINUTES,
    PLANS,
    REDEEM_CODE_ALPHABET,
    REDEEM_CODE_LENGTH,
    service_account_info,
    settings,
)

logger = logging.getLogger(__name__)

_db: Optional[firestore.firestore.Client] = None


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def init_firebase() -> None:
    """تهيئة Firebase Admin مرة واحدة لكل نسخة من الدالة (بدون مفاتيح: Cloud Functions توفرها تلقائياً)."""
    global _db
    if _db is not None:
        return

    if not firebase_admin._apps:
        options = {"projectId": settings.FIREBASE_PROJECT_ID} if settings.FIREBASE_PROJECT_ID else None
        sa = service_account_info()
        if sa and not os.getenv("FIRESTORE_EMULATOR_HOST"):
            # خارج Firebase (Render): الدخول بمفتاح Service Account
            from firebase_admin import credentials

            firebase_admin.initialize_app(credentials.Certificate(sa), options=options)
        else:
            firebase_admin.initialize_app(options=options)

    if os.getenv("FIRESTORE_EMULATOR_HOST"):
        # التجربة المحلية على Firebase Emulator
        from google.auth.credentials import AnonymousCredentials
        from google.cloud import firestore as gc_firestore

        _db = gc_firestore.Client(project=settings.FIREBASE_PROJECT_ID, credentials=AnonymousCredentials())
    else:
        _db = firestore.client(database_id=settings.FIRESTORE_DATABASE or None)


def db() -> firestore.firestore.Client:
    if _db is None:
        raise RuntimeError("Firebase لم تتم تهيئته بعد، استدعِ init_firebase() أولاً")
    return _db


async def _run(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


# ---------------------------------------------------------------------------
# كاش بسيط في الذاكرة لتقليل قراءات Firestore مع كل رسالة في القروب
# ---------------------------------------------------------------------------

class _TTLCache:
    def __init__(self, ttl: float):
        self.ttl = ttl
        self._data: dict[Any, tuple[float, Any]] = {}

    def get(self, key):
        item = self._data.get(key)
        if item is None:
            return None, False
        expires, value = item
        if expires < time.monotonic():
            self._data.pop(key, None)
            return None, False
        return value, True

    def set(self, key, value, ttl: Optional[float] = None):
        self._data[key] = (time.monotonic() + (ttl if ttl is not None else self.ttl), value)

    def pop(self, key):
        self._data.pop(key, None)

    def clear(self):
        self._data.clear()


_group_cache = _TTLCache(CACHE_TTL_SECONDS)
_active_cache = _TTLCache(CACHE_TTL_SECONDS)


def clear_caches() -> None:
    _group_cache.clear()
    _active_cache.clear()


# ---------------------------------------------------------------------------
# القروبات وربطها
# ---------------------------------------------------------------------------

LINK_OK = "ok"
LINK_INVALID = "invalid"
LINK_EXPIRED = "expired"
LINK_TAKEN = "taken"  # القروب مربوط بحساب آخر
LINK_NO_OWNER = "no_owner"


def _consume_link_code_sync(code: str, chat_id: int, title: str, telegram_user_id: int) -> tuple[str, Optional[dict]]:
    client = db()
    code_ref = client.collection("linkCodes").document(code)
    group_ref = client.collection("groups").document(str(chat_id))

    @firestore.transactional
    def txn(transaction):
        code_snap = code_ref.get(transaction=transaction)
        if not code_snap.exists:
            return LINK_INVALID, None
        data = code_snap.to_dict()
        owner_uid = data.get("ownerUid")
        created_at = data.get("createdAt")
        if created_at is None or utcnow() - created_at > dt.timedelta(minutes=LINK_CODE_TTL_MINUTES):
            transaction.delete(code_ref)
            return LINK_EXPIRED, None

        owner_snap = client.collection("owners").document(owner_uid).get(transaction=transaction)
        if not owner_snap.exists:
            return LINK_NO_OWNER, None

        group_snap = group_ref.get(transaction=transaction)
        if group_snap.exists and group_snap.to_dict().get("ownerUid") not in (None, owner_uid):
            return LINK_TAKEN, None

        now = utcnow()
        group_data = {
            "ownerUid": owner_uid,
            "ownerName": owner_snap.to_dict().get("name", ""),
            "title": title,
            "chatId": chat_id,
            "linkedAt": now,
            "linkedByTelegramId": telegram_user_id,
            "active": True,
            "remindersEnabled": True,
            "updatedAt": now,
        }
        if not group_snap.exists:
            group_data.update({"blockedMessages": 0, "memberCount": 0})
        transaction.set(group_ref, group_data, merge=True)
        transaction.delete(code_ref)
        return LINK_OK, group_data

    return txn(client.transaction())


async def consume_link_code(code: str, chat_id: int, title: str, telegram_user_id: int) -> tuple[str, Optional[dict]]:
    result = await _run(_consume_link_code_sync, code.strip().upper(), chat_id, title, telegram_user_id)
    _group_cache.pop(chat_id)
    return result


def _get_group_sync(chat_id: int) -> Optional[dict]:
    snap = db().collection("groups").document(str(chat_id)).get()
    return snap.to_dict() if snap.exists else None


async def get_linked_group(chat_id: int) -> Optional[dict]:
    """يرجع بيانات القروب إذا كان مربوطاً ومفعّلاً، وإلا None."""
    cached, hit = _group_cache.get(chat_id)
    if hit:
        return cached
    data = await _run(_get_group_sync, chat_id)
    if data is not None and not data.get("active", True):
        data = None
    _group_cache.set(chat_id, data)
    return data


async def update_group(chat_id: int, **fields) -> None:
    def _sync():
        ref = db().collection("groups").document(str(chat_id))
        if ref.get().exists:
            ref.update({**fields, "updatedAt": utcnow()})

    await _run(_sync)
    _group_cache.pop(chat_id)


async def increment_blocked_messages(chat_id: int) -> None:
    def _sync():
        db().collection("groups").document(str(chat_id)).update(
            {"blockedMessages": firestore.Increment(1), "lastBlockedAt": utcnow()}
        )

    try:
        await _run(_sync)
    except Exception:
        logger.debug("تعذر تحديث عداد الرسائل المحذوفة للقروب %s", chat_id)


async def list_active_groups() -> list[dict]:
    def _sync():
        docs = db().collection("groups").where(filter=FieldFilter("active", "==", True)).stream()
        return [d.to_dict() | {"id": d.id} for d in docs]

    return await _run(_sync)


async def migrate_group(old_chat_id: int, new_chat_id: int) -> None:
    """عند تحويل القروب العادي إلى Supergroup يتغير الـ ID: ننقل البيانات."""

    def _sync():
        client = db()
        old_ref = client.collection("groups").document(str(old_chat_id))
        snap = old_ref.get()
        if not snap.exists:
            return
        data = snap.to_dict()
        data["chatId"] = new_chat_id
        data["migratedFrom"] = old_chat_id
        client.collection("groups").document(str(new_chat_id)).set(data)
        old_ref.delete()

        batch = client.batch()
        count = 0
        for sub in client.collection("subscriptions").where(filter=FieldFilter("groupId", "==", old_chat_id)).stream():
            batch.update(sub.reference, {"groupId": new_chat_id})
            count += 1
            if count % 400 == 0:
                batch.commit()
                batch = client.batch()
        batch.commit()

    await _run(_sync)
    _group_cache.pop(old_chat_id)
    _group_cache.pop(new_chat_id)
    _active_cache.clear()


# ---------------------------------------------------------------------------
# الاشتراكات
# ---------------------------------------------------------------------------

def _active_end_date_sync(telegram_user_id: int, group_id: int) -> Optional[dt.datetime]:
    docs = (
        db()
        .collection("subscriptions")
        .where(filter=FieldFilter("telegramUserId", "==", telegram_user_id))
        .where(filter=FieldFilter("groupId", "==", group_id))
        .where(filter=FieldFilter("status", "==", "active"))
        .stream()
    )
    now = utcnow()
    best = None
    for d in docs:
        end = d.to_dict().get("endDate")
        if end and end >= now and (best is None or end > best):
            best = end
    return best


async def get_active_end_date(telegram_user_id: int, group_id: int) -> Optional[dt.datetime]:
    return await _run(_active_end_date_sync, telegram_user_id, group_id)


async def is_user_active(telegram_user_id: int, group_id: int) -> bool:
    key = (telegram_user_id, group_id)
    cached, hit = _active_cache.get(key)
    if hit:
        return cached
    end = await get_active_end_date(telegram_user_id, group_id)
    active = end is not None
    # نخزّن "مشترك" فقط. "غير مشترك" لا يُخزَّن أبداً: التفعيل يحدث في دالة أخرى
    # (Webhook ميسر) فلا يمكنها مسح كاش هذه النسخة، والعضو يجب أن يُفتح له القروب فور الدفع.
    if active:
        _active_cache.set(key, True)
    return active


def compute_shares(amount: float) -> tuple[float, float]:
    """يرجع (حصة صاحب القروب، عمولة المنصة)."""
    commission = round(amount * settings.PLATFORM_COMMISSION_PERCENT / 100.0, 2)
    return round(amount - commission, 2), commission


async def create_pending_subscription(
    invoice_id: str,
    telegram_user: dict,
    group: dict,
    group_id: int,
    plan_key: str,
) -> None:
    plan = PLANS[plan_key]
    owner_share, commission = compute_shares(plan["price"])

    def _sync():
        db().collection("subscriptions").document(invoice_id).set(
            {
                "invoiceId": invoice_id,
                "telegramUserId": telegram_user["id"],
                "telegramName": telegram_user.get("name", ""),
                "telegramUsername": telegram_user.get("username") or "",
                "groupId": group_id,
                "groupTitle": group.get("title", ""),
                "ownerUid": group["ownerUid"],
                "planKey": plan_key,
                "planName": plan["name"],
                "planDays": plan["days"],
                "amount": plan["price"],
                "ownerShare": owner_share,
                "commission": commission,
                "status": "pending",
                "createdAt": utcnow(),
            }
        )

    await _run(_sync)


async def get_subscription(invoice_id: str) -> Optional[dict]:
    def _sync():
        snap = db().collection("subscriptions").document(invoice_id).get()
        return snap.to_dict() if snap.exists else None

    return await _run(_sync)


def _activate_sync(invoice_id: str, payment_id: Optional[str], phone: Optional[str]) -> tuple[str, Optional[dict]]:
    client = db()
    ref = client.collection("subscriptions").document(invoice_id)
    snap = ref.get()
    if not snap.exists:
        return "not_found", None
    data = snap.to_dict()
    if data.get("status") == "active" or data.get("status") == "expired":
        return "already", data

    # التجديد: لو عنده اشتراك نشط في نفس القروب نكمّل من تاريخ انتهائه
    current_end = _active_end_date_sync(data["telegramUserId"], data["groupId"])
    now = utcnow()
    start = current_end if current_end and current_end > now else now
    end = start + dt.timedelta(days=int(data.get("planDays") or PLANS.get(data["planKey"], {}).get("days", 30)))

    @firestore.transactional
    def txn(transaction):
        fresh = ref.get(transaction=transaction).to_dict()
        if fresh.get("status") != "pending" and fresh.get("status") != "canceled":
            return "already", fresh
        update = {"status": "active", "startDate": start, "endDate": end, "paidAt": now}
        if payment_id:
            update["paymentId"] = payment_id
        if phone:
            update["phone"] = phone
        transaction.update(ref, update)
        return "ok", fresh | update

    return txn(client.transaction())


async def activate_subscription(invoice_id: str, payment_id: Optional[str] = None, phone: Optional[str] = None):
    status, data = await _run(_activate_sync, invoice_id, payment_id, phone)
    if data:
        _active_cache.pop((data["telegramUserId"], data["groupId"]))
    return status, data


async def expire_outdated_subscriptions() -> list[dict]:
    def _sync():
        client = db()
        now = utcnow()
        expired = []
        for d in client.collection("subscriptions").where(filter=FieldFilter("status", "==", "active")).stream():
            data = d.to_dict()
            if data.get("endDate") and data["endDate"] < now:
                d.reference.update({"status": "expired"})
                expired.append(data)
        return expired

    expired = await _run(_sync)
    for data in expired:
        _active_cache.pop((data["telegramUserId"], data["groupId"]))
    return expired


async def cancel_unpaid(now: Optional[dt.datetime] = None) -> int:
    """
    يلغي كل فاتورة لم تُدفع بعد انتهاء مهلة الدفع (30 دقيقة) حتى لا تبقى «بانتظار الدفع» في اللوحات.
    لو دفع العضو لاحقاً (نادراً، مثلاً تأخر إشعار ميسر) يتفعّل اشتراكه عادي لأن التفعيل يقبل الملغاة.
    """
    def _sync():
        client = db()
        cutoff = (now or utcnow()) - dt.timedelta(minutes=INVOICE_EXPIRY_MINUTES)
        count = 0
        for col in ("subscriptions", "codeOrders"):
            for d in client.collection(col).where(filter=FieldFilter("status", "==", "pending")).stream():
                created = d.to_dict().get("createdAt")
                if created and created < cutoff:
                    d.reference.update({"status": "canceled", "canceledAt": utcnow()})
                    count += 1
        return count

    return await _run(_sync)


async def list_user_active_subscriptions(telegram_user_id: int) -> list[dict]:
    def _sync():
        now = utcnow()
        docs = (
            db()
            .collection("subscriptions")
            .where(filter=FieldFilter("telegramUserId", "==", telegram_user_id))
            .where(filter=FieldFilter("status", "==", "active"))
            .stream()
        )
        return [d.to_dict() for d in docs if (d.to_dict().get("endDate") or now) >= now]

    return await _run(_sync)


# ---------------------------------------------------------------------------
# الشراء من البوت مباشرة (بدون قروب): طلب دفع (codeOrders) -> بعد الدفع كود (redeemCodes)
# الكود يُكتب داخل أي قروب مربوط فيتفعّل الاشتراك بمدة الباقة. كل كود يُستخدم مرة واحدة،
# وكل عملية دفع لها كود جديد مختلف.
# ---------------------------------------------------------------------------

ORDER_PENDING = "pending"
ORDER_PAID = "paid"
ORDER_REDEEMED = "redeemed"

REDEEM_OK = "ok"
REDEEM_INVALID = "invalid"
REDEEM_USED = "used"
REDEEM_NO_GROUP = "no_group"


def normalize_redeem_code(text: str) -> str:
    return "".join(ch for ch in (text or "").upper() if ch.isalnum())


def looks_like_redeem_code(text: str) -> bool:
    raw = (text or "").strip()
    if not raw or len(raw) > 20:
        return False
    code = normalize_redeem_code(raw)
    return len(code) == REDEEM_CODE_LENGTH and all(ch in REDEEM_CODE_ALPHABET for ch in code)


def format_redeem_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


async def create_code_order(invoice_id: str, telegram_user: dict, plan_key: str) -> None:
    plan = PLANS[plan_key]

    def _sync():
        db().collection("codeOrders").document(invoice_id).set(
            {
                "invoiceId": invoice_id,
                "buyerTelegramId": telegram_user["id"],
                "buyerName": telegram_user.get("name", ""),
                "buyerUsername": telegram_user.get("username") or "",
                "planKey": plan_key,
                "planName": plan["name"],
                "planDays": plan["days"],
                "amount": plan["price"],
                "status": ORDER_PENDING,
                "createdAt": utcnow(),
            }
        )

    await _run(_sync)


async def get_code_order(invoice_id: str) -> Optional[dict]:
    def _sync():
        snap = db().collection("codeOrders").document(invoice_id).get()
        return snap.to_dict() if snap.exists else None

    return await _run(_sync)


def _new_code() -> str:
    return "".join(secrets.choice(REDEEM_CODE_ALPHABET) for _ in range(REDEEM_CODE_LENGTH))


def _mark_code_order_paid_sync(invoice_id: str, payment_id: Optional[str]) -> tuple[str, Optional[dict]]:
    """يعلّم الطلب مدفوعاً ويولّد له كوداً فريداً واحداً. يرجع ('new'|'already', الطلب)."""
    client = db()
    order_ref = client.collection("codeOrders").document(invoice_id)

    for _ in range(5):  # احتمال تكرار الكود ضئيل جداً، نعيد المحاولة احتياطاً
        code = _new_code()
        code_ref = client.collection("redeemCodes").document(code)

        @firestore.transactional
        def txn(transaction):
            snap = order_ref.get(transaction=transaction)
            if not snap.exists:
                return "missing", None
            data = snap.to_dict()
            if data.get("code"):
                return "already", data
            if code_ref.get(transaction=transaction).exists:
                return "retry", None
            now = utcnow()
            update = {"status": ORDER_PAID, "code": code, "paidAt": now}
            if payment_id:
                update["paymentId"] = payment_id
            transaction.update(order_ref, update)
            transaction.set(code_ref, {"invoiceId": invoice_id, "used": False, "createdAt": now})
            return "new", data | update

        status, data = txn(client.transaction())
        if status != "retry":
            return status, data
    raise RuntimeError("تعذر توليد كود فريد")


async def mark_code_order_paid(invoice_id: str, payment_id: Optional[str] = None) -> tuple[str, Optional[dict]]:
    return await _run(_mark_code_order_paid_sync, invoice_id, payment_id)


def _redeem_code_sync(code: str, telegram_user: dict, group_id: int) -> tuple[str, Optional[dict]]:
    client = db()
    code_ref = client.collection("redeemCodes").document(code)
    code_snap = code_ref.get()
    if not code_snap.exists:
        return REDEEM_INVALID, None
    if code_snap.to_dict().get("used"):
        return REDEEM_USED, None

    group_snap = client.collection("groups").document(str(group_id)).get()
    group = group_snap.to_dict() if group_snap.exists else None
    if group is None or not group.get("active", True):
        return REDEEM_NO_GROUP, None

    invoice_id = code_snap.to_dict()["invoiceId"]
    order_ref = client.collection("codeOrders").document(invoice_id)
    order = order_ref.get().to_dict() or {}

    tg_id = int(telegram_user["id"])
    current_end = _active_end_date_sync(tg_id, int(group_id))
    now = utcnow()
    start = current_end if current_end and current_end > now else now
    end = start + dt.timedelta(days=int(order.get("planDays") or PLANS.get(order.get("planKey"), {}).get("days", 30)))
    owner_share, commission = compute_shares(float(order["amount"]))
    sub_ref = client.collection("subscriptions").document(invoice_id)

    @firestore.transactional
    def txn(transaction):
        fresh = code_ref.get(transaction=transaction).to_dict()
        if fresh.get("used"):
            return REDEEM_USED, None
        sub = {
            "invoiceId": invoice_id,
            "telegramUserId": tg_id,
            "telegramName": telegram_user.get("name", ""),
            "telegramUsername": telegram_user.get("username") or "",
            "groupId": int(group_id),
            "groupTitle": group.get("title", ""),
            "ownerUid": group["ownerUid"],
            "planKey": order.get("planKey"),
            "planName": order.get("planName"),
            "planDays": order.get("planDays"),
            "amount": order["amount"],
            "ownerShare": owner_share,
            "commission": commission,
            "status": "active",
            "source": "code",
            "redeemCode": code,
            "buyerTelegramId": order.get("buyerTelegramId"),
            "createdAt": order.get("createdAt") or now,
            "paidAt": order.get("paidAt") or now,
            "startDate": start,
            "endDate": end,
        }
        if order.get("paymentId"):
            sub["paymentId"] = order["paymentId"]
        transaction.set(sub_ref, sub)
        transaction.update(code_ref, {"used": True, "usedBy": tg_id, "usedAt": now, "groupId": int(group_id)})
        transaction.update(order_ref, {"status": ORDER_REDEEMED, "redeemedBy": tg_id, "redeemedAt": now})
        return REDEEM_OK, sub

    return txn(client.transaction())


async def redeem_code(code: str, telegram_user: dict, group_id: int) -> tuple[str, Optional[dict]]:
    status, data = await _run(_redeem_code_sync, normalize_redeem_code(code), telegram_user, group_id)
    if status == REDEEM_OK and data:
        _active_cache.pop((data["telegramUserId"], data["groupId"]))
    return status, data


# ---------------------------------------------------------------------------
# الأدمن
# ---------------------------------------------------------------------------

async def sync_admin_roles() -> None:
    """يعطي صلاحية admin للحسابات المسجلة بالإيميلات الموجودة في ADMIN_EMAILS."""
    if not settings.ADMIN_EMAILS:
        return

    def _sync():
        for email in settings.ADMIN_EMAILS:
            try:
                user = fb_auth.get_user_by_email(email)
            except fb_auth.UserNotFoundError:
                continue
            except Exception:
                logger.exception("تعذر جلب حساب الأدمن %s", email)
                continue
            if not user.email_verified:
                continue  # حتى لا يسجّل أحد بإيميلك قبلك ويأخذ صلاحية الأدمن
            ref = db().collection("owners").document(user.uid)
            snap = ref.get()
            if snap.exists and snap.to_dict().get("role") != "admin":
                ref.update({"role": "admin"})
                logger.info("تم منح صلاحية الأدمن للحساب %s", email)

    await _run(_sync)


# ---------------------------------------------------------------------------
# حذف تنبيهات "يجب الاشتراك" لاحقاً (احتياط إذا تعذر استخدام Cloud Tasks)
# ---------------------------------------------------------------------------

async def add_pending_delete(chat_id: int, message_id: int, delete_at: dt.datetime) -> None:
    def _sync():
        db().collection("pendingDeletes").document(f"{chat_id}_{message_id}").set(
            {"chatId": chat_id, "messageId": message_id, "deleteAt": delete_at}
        )

    await _run(_sync)


async def pop_due_deletes(chat_id: Optional[int] = None) -> list[dict]:
    """يرجع التنبيهات التي حان وقت حذفها ويزيلها من السجل."""

    def _sync():
        now = utcnow()
        q = db().collection("pendingDeletes")
        if chat_id is not None:
            q = q.where(filter=FieldFilter("chatId", "==", chat_id))
        due = []
        for d in q.stream():
            data = d.to_dict()
            if data.get("deleteAt") and data["deleteAt"] <= now:
                due.append(data)
                d.reference.delete()
        return due

    return await _run(_sync)
