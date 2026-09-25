"""
تكامل بوابة الدفع ميسر (Moyasar) عن طريق Invoice API.
نولّد رابط دفع مستضاف من ميسر ونرسله كزر رابط داخل تيليجرام (يفتح داخل المتصفح المدمج بالتطبيق).
بعد الدفع، ميسر يرسل Webhook لسيرفرنا (webhook_server.py) لتأكيد الدفع وتفعيل الاشتراك تلقائيًا.
"""
import requests
from requests.auth import HTTPBasicAuth
from config import MOYASAR_SECRET_KEY, PUBLIC_BASE_URL, CURRENCY

MOYASAR_API = "https://api.moyasar.com/v1/invoices"


def create_invoice(amount_sar: int, telegram_id: int, plan_months: int) -> dict:
    """
    ينشئ فاتورة دفع في ميسر ويرجع dict فيه id ورابط الدفع.
    amount_sar: المبلغ بالريال (رقم صحيح، مثلا 50)
    """
    payload = {
        "amount": amount_sar * 100,  # ميسر يتوقع المبلغ بالهللة
        "currency": CURRENCY,
        "description": f"اشتراك {plan_months} شهر - Telegram ID {telegram_id}",
        "callback_url": f"{PUBLIC_BASE_URL}/moyasar/webhook",
        "success_url": f"{PUBLIC_BASE_URL}/payment/success",
        "back_url": f"{PUBLIC_BASE_URL}/payment/cancel",
        "metadata": {
            "telegram_id": str(telegram_id),
            "plan_months": str(plan_months),
        },
    }
    resp = requests.post(
        MOYASAR_API,
        json=payload,
        auth=HTTPBasicAuth(MOYASAR_SECRET_KEY, ""),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_invoice(invoice_id: str) -> dict:
    resp = requests.get(
        f"{MOYASAR_API}/{invoice_id}",
        auth=HTTPBasicAuth(MOYASAR_SECRET_KEY, ""),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
