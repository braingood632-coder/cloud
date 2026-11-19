"""
اختبار شامل للنظام كاملاً كما سيعمل على Firebase:
Hosting -> Functions -> Firestore، مع تليجرام وميسر وهميين.

يتطلب تشغيل:
  python tests/fake_services.py 8900
  firebase emulators:start --only auth,firestore,functions,hosting --project demo-cloud
ثم:
  functions/venv/bin/python tests/e2e_emulator.py
"""

from __future__ import annotations

import os
import sys
import time

import httpx

os.environ.update(FIRESTORE_EMULATOR_HOST="127.0.0.1:8080", FIREBASE_AUTH_EMULATOR_HOST="127.0.0.1:9099",
                  FIREBASE_PROJECT_ID="demo-cloud")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))
import firebase_db as db  # noqa: E402

SITE = "http://127.0.0.1:5000"
FN = "http://127.0.0.1:5001/demo-cloud/europe-west1"
# نفس توجيهات firebase.json (rewrites). نستدعي الدوال مباشرة لأن بروكسي بيئة الاختبار
# يعترض تحويل Hosting المحلي؛ على Firebase الحقيقي يمر الطلب عبر Hosting.
ROUTES = {"/config.js": "webconfig", "/telegram/webhook": "telegramwebhook", "/moyasar/webhook": "moyasarwebhook",
          "/payment/callback": "paymentcallback", "/api/setup-webhook": "setupwebhook", "/api/claim-admin": "claimadmin"}


# وضع السيرفر (Render): E2E_API_BASE=http://127.0.0.1:8000 — كل مسارات البوت تذهب لسيرفر server.py
API = os.environ.get("E2E_API_BASE", "").rstrip("/")


def url(path: str) -> str:
    base, _, query = path.partition("?")
    if base in ROUTES and API:
        return API + path
    return f"{FN}/{ROUTES[base]}" + (f"?{query}" if query else "") if base in ROUTES else SITE + path
FAKE = "http://127.0.0.1:8900"
GROUP = -100777
ADMIN = 111
MEMBER = 200000 + int(time.time()) % 100000  # عضو جديد في كل تشغيل
failures = 0
upd_id = 1


def check(cond, msg):
    global failures
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        failures += 1


def calls(method=None):
    data = httpx.get(FAKE + "/_calls").json()
    return [c for c in data if method is None or c["method"] == method]


def tg(update: dict, secret: str | None):
    global upd_id
    upd_id += 1
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret else {}
    return httpx.post(url("/telegram/webhook"), json={"update_id": upd_id, **update}, headers=headers, timeout=60)


def msg(user_id, chat_id, text, message_id):
    chat = {"id": chat_id, "type": "supergroup", "title": "قروب عقارات الرياض"} if chat_id < 0 else {"id": chat_id, "type": "private", "first_name": "u"}
    m = {"message_id": message_id, "date": int(time.time()), "chat": chat,
         "from": {"id": user_id, "is_bot": False, "first_name": "عضو", "username": f"user{user_id}"}, "text": text}
    if text.startswith("/"):
        m["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    return {"message": m}


def main():
    db.init_firebase()
    httpx.delete("http://127.0.0.1:8080/emulator/v1/projects/demo-cloud/databases/(default)/documents")

    # 1) config.js عبر Hosting -> webconfig
    js = httpx.get(url("/config.js"), timeout=60).text
    check("CloudTestBot" in js and "plan_3m" in js, "config.js served through Hosting rewrite (bot username from Telegram)")

    # 2) ضبط Webhook
    httpx.post(FAKE + "/_reset", json={"webhook": True})
    r = httpx.get(url("/api/setup-webhook"), timeout=60).json()
    sw = calls("setWebhook")
    check(r.get("changed") and sw and sw[-1]["params"]["url"] == (API or SITE) + "/telegram/webhook", "setup-webhook registers Telegram webhook (Hosting URL)")
    secret = sw[-1]["params"]["secret_token"]
    check(set(sw[-1]["params"]["allowed_updates"]) == {"message", "callback_query", "my_chat_member"}, "allowed_updates set")

    # 3) صاحب قروب + كود ربط
    owner = db.db().collection("owners").document("owner-uid")
    owner.set({"name": "محمد", "email": "o@example.com", "role": "owner", "createdAt": db.utcnow()})
    db.db().collection("linkCodes").document("LINK2345").set({"ownerUid": "owner-uid", "createdAt": db.utcnow()})

    # 4) طلب بدون التوكن السري يُرفض
    check(tg(msg(ADMIN, GROUP, "/link LINK2345", 1), None).status_code == 403, "webhook rejects requests without secret token")

    # 5) الربط
    httpx.post(FAKE + "/_reset")
    check(tg(msg(ADMIN, GROUP, "/link LINK2345", 2), secret).status_code == 200, "link update accepted")
    g = db.db().collection("groups").document(str(GROUP)).get()
    check(g.exists and g.to_dict()["ownerUid"] == "owner-uid" and g.to_dict()["memberCount"] == 350, "group linked in Firestore")
    check(any(c["params"].get("message_id") == 2 for c in calls("deleteMessage")), "link command message deleted")
    check(any("تم ربط القروب بنجاح" in c["params"].get("text", "") for c in calls("sendMessage")), "success message sent to group")

    # 6) غير مشترك يكتب -> حذف + تنبيه
    httpx.post(FAKE + "/_reset")
    tg(msg(MEMBER, GROUP, "إعلان: شقة للبيع", 10), secret)
    check(any(c["params"].get("message_id") == 10 for c in calls("deleteMessage")), "non-subscriber message deleted")
    warn = [c for c in calls("sendMessage") if "للمشتركين فقط" in c["params"].get("text", "")]
    check(bool(warn) and f"sub_{GROUP}" in str(warn[-1]["params"].get("reply_markup")), "warning with subscribe button sent")
    if API:
        # السيرفر يحذف التنبيه بمؤقّت داخلي بعد 20 ثانية
        warn_ids = {c["params"].get("message_id") for c in calls("deleteMessage")}
        time.sleep(22)
        later = [c for c in calls("deleteMessage") if c["params"].get("message_id") not in warn_ids]
        check(bool(later), "warning auto-deleted after 20 seconds (server timer)")
    else:
        check(len(list(db.db().collection("pendingDeletes").stream())) == 1, "warning scheduled for deletion")

    # 7) /start في الخاص بدون رابط -> الباقات مباشرة
    httpx.post(FAKE + "/_reset")
    tg(msg(MEMBER, MEMBER, "/start", 11), secret)
    sm = calls("sendMessage")
    check(sm and "قم باختيار إحدى باقات الاشتراك" in sm[-1]["params"]["text"] and f"plan|{GROUP}|plan_3m" in str(sm[-1]["params"]["reply_markup"]), "/start shows plans for member's group")

    # 8) اختيار باقة -> فاتورة ميسر
    httpx.post(FAKE + "/_reset")
    cb = {"callback_query": {"id": "cb1", "chat_instance": "x", "data": f"plan|{GROUP}|plan_3m",
                             "from": {"id": MEMBER, "is_bot": False, "first_name": "عضو", "username": "member"},
                             "message": {"message_id": 12, "date": int(time.time()), "chat": {"id": MEMBER, "type": "private", "first_name": "u"}, "text": "x"}}}
    tg(cb, secret)
    ed = calls("editMessageText")
    check(ed and "checkout.moyasar.com" in str(ed[-1]["params"].get("reply_markup")) and "✅ اشترك ✅" in str(ed[-1]["params"].get("reply_markup")), "plan choice returns Moyasar pay button")
    subs = [d for d in db.db().collection("subscriptions").stream()]
    check(len(subs) == 1 and subs[0].to_dict()["status"] == "pending" and subs[0].to_dict()["ownerUid"] == "owner-uid", "pending subscription saved")
    inv_id = subs[0].id

    # 9) إشعار ميسر قبل الدفع الفعلي -> لا تفعيل
    r = httpx.post(url("/moyasar/webhook"), json={"type": "invoice_paid", "secret_token": "test-secret", "data": {"id": inv_id}}, timeout=60)
    check(r.json().get("status") == "not_paid", "fake webhook before payment is rejected (not_paid)")
    r = httpx.post(url("/moyasar/webhook"), json={"type": "invoice_paid", "secret_token": "bad", "data": {"id": inv_id}}, timeout=60)
    check(r.status_code == 401, "webhook with wrong secret rejected")

    # 10) الدفع ثم الإشعار
    httpx.post(FAKE + f"/_pay/{inv_id}")
    httpx.post(FAKE + "/_reset")
    r = httpx.post(url("/moyasar/webhook"), json={"type": "payment_paid", "secret_token": "test-secret", "data": {"invoice_id": inv_id}}, timeout=60)
    check(r.json().get("status") == "ok", "payment webhook activates subscription")
    sub = db.db().collection("subscriptions").document(inv_id).get().to_dict()
    check(sub["status"] == "active" and (sub["endDate"] - db.utcnow()).days >= 89, "subscription active for 90 days (saved in Firestore)")
    check(any("تم تفعيل اشتراكك" in c["params"].get("text", "") and int(c["params"]["chat_id"]) == MEMBER for c in calls("sendMessage")), "member notified of activation")

    # 11) المشترك يكتب -> لا حذف
    httpx.post(FAKE + "/_reset")
    tg(msg(MEMBER, GROUP, "السلام عليكم", 20), secret)
    check(not any(c["params"].get("message_id") == 20 for c in calls("deleteMessage")), "subscriber message NOT deleted")

    # 12) صفحة الرجوع
    page = httpx.get(url(f"/payment/callback?invoice_id={inv_id}"), timeout=60).text
    check("تم الدفع بنجاح" in page, "payment callback page shows success")

    if API:
        pre = httpx.options(url("/api/claim-admin"), headers={"Origin": SITE, "Access-Control-Request-Method": "POST"}, timeout=30)
        check(pre.status_code == 204 and pre.headers.get("access-control-allow-origin") == "*", "claim-admin CORS preflight ok (site on another domain)")
        bad = httpx.post(url("/api/claim-admin"), headers={"Authorization": "Bearer bad"}, timeout=30)
        check(bad.status_code == 401, "claim-admin rejects invalid token")
        check("apiBase" in js and API in js, "config.js tells the site where the bot server is")

    # 13) الموقع الثابت
    check("بوت Cloud" in httpx.get(SITE + "/").text, "landing page served by Hosting")

    print("\nALL E2E CHECKS PASSED" if not failures else f"\n{failures} FAILURES")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
