"""
التعامل مع Moyasar Invoices API
https://docs.moyasar.com/api/invoices/01-create-invoice/
"""
import requests
from config import MOYASAR_SECRET_KEY

BASE = "https://api.moyasar.com/v1"


def create_invoice(amount_sar: float, description: str, callback_url: str,
                    success_url: str, metadata: dict) -> dict:
    """ينشئ فاتورة دفع ويرجّع الاستجابة (تحتوي id و url)."""
    resp = requests.post(
        f"{BASE}/invoices",
        auth=(MOYASAR_SECRET_KEY, ""),
        json={
            "amount": int(round(amount_sar * 100)),  # هللات
            "currency": "SAR",
            "description": description,
            "callback_url": callback_url,
            "success_url": success_url,
            "metadata": metadata,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_invoice(invoice_id: str) -> dict:
    """يجلب حالة الفاتورة مباشرة من سيرفر ميسر (لا نثق بأي بيانات من الويبهوك وحدها)."""
    resp = requests.get(
        f"{BASE}/invoices/{invoice_id}",
        auth=(MOYASAR_SECRET_KEY, ""),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
