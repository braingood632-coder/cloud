"""
سيرفر صغير يستقبل إشعار الدفع من ميسر (Webhook) بعد إتمام العملية،
يتأكد من حالة الفاتورة، يمدد اشتراك المستخدم في قاعدة البيانات،
ويرسل له رسالة تأكيد داخل تيليجرام.

يشتغل هذا السيرفر بشكل منفصل عن bot.py (عملية/Process ثانية) لأنه يستقبل
طلبات HTTP من الإنترنت (من ميسر) وليس Long Polling من تيليجرام.
"""
import logging
import requests
from flask import Flask, request, jsonify

import config
import database as dbm
import payments

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)


def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)


@app.route("/moyasar/webhook", methods=["POST"])
def moyasar_webhook():
    # تحقق أمني بسيط عبر secret token لو مفعّل في لوحة ميسر
    if config.MOYASAR_WEBHOOK_SECRET:
        sent_secret = request.headers.get("X-Moyasar-Secret") or request.args.get("secret")
        if sent_secret != config.MOYASAR_WEBHOOK_SECRET:
            return jsonify({"ok": False, "error": "invalid secret"}), 403

    data = request.get_json(silent=True) or {}
    invoice_id = data.get("id") or data.get("data", {}).get("id")
    if not invoice_id:
        return jsonify({"ok": False, "error": "no invoice id"}), 400

    # لا نثق بالبيانات القادمة بالـ webhook فقط، نتأكد من ميسر مباشرة
    try:
        invoice = payments.get_invoice(invoice_id)
    except Exception:
        logging.exception("failed to verify invoice with moyasar")
        return jsonify({"ok": False}), 500

    status = invoice.get("status")
    payment_row = dbm.get_payment(invoice_id)
    if not payment_row:
        logging.warning(f"invoice {invoice_id} not found locally")
        return jsonify({"ok": True})

    if status == "paid" and payment_row["status"] != "paid":
        dbm.mark_payment_status(invoice_id, "paid")
        new_end = dbm.extend_subscription(payment_row["telegram_id"], payment_row["plan_months"])
        import datetime
        d = datetime.datetime.fromtimestamp(new_end).strftime("%Y-%m-%d %H:%M")
        send_telegram_message(
            payment_row["telegram_id"],
            f"✅ تم تأكيد دفعك بنجاح!\nاشتراكك فعّال الآن حتى: {d}\nتقدر ترسل بالقروب مباشرة.",
        )
    elif status in ("failed", "canceled") and payment_row["status"] not in ("paid",):
        dbm.mark_payment_status(invoice_id, status)

    return jsonify({"ok": True})


@app.route("/payment/success")
def payment_success():
    return "تم الدفع بنجاح، ارجع لتطبيق تيليجرام."


@app.route("/payment/cancel")
def payment_cancel():
    return "تم إلغاء عملية الدفع."


if __name__ == "__main__":
    dbm.init_db()
    app.run(host="0.0.0.0", port=5000)
