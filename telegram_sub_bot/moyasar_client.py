"""
moyasar_client.py
------------------
غلاف بسيط (Wrapper) حول Moyasar Invoice API.
التوثيق الرسمي: https://docs.moyasar.com/invoices

ملاحظة مهمة: تحقق دوماً من استجابة حسابك الفعلي على بيئة الاختبار (Test Mode)
لأن بعض الحقول (مثل رابط الفاتورة) قد يختلف اسمها بين إصدارات الـ API.
"""

from __future__ import annotations

import datetime as dt
import httpx

from config import settings, INVOICE_EXPIRY_MINUTES

MOYASAR_BASE_URL = "https://api.moyasar.com/v1"


class MoyasarError(Exception):
    pass


async def create_invoice(
    amount_sar: float,
    description: str,
    telegram_user_id: int,
    plan_key: str,
) -> dict:
    """
    ينشئ فاتورة جديدة في ميسر، وتنتهي صلاحيتها تلقائياً بعد
    INVOICE_EXPIRY_MINUTES دقيقة (30 دقيقة افتراضياً حسب config.py).

    نحفظ داخل metadata معرف المستخدم في تليجرام واسم الباقة، لأن هذه
    البيانات سترجع لنا كما هي داخل الـ Webhook عند نجاح الدفع، وهي
    الطريقة التي نطابق بها الفاتورة مع المستخدم الصحيح في قاعدة بياناتنا.
    """
    amount_halalas = int(round(amount_sar * 100))  # ميسر يتعامل بالهللة (Halalas) وليس بالريال
    expires_at = dt.datetime.utcnow() + dt.timedelta(minutes=INVOICE_EXPIRY_MINUTES)

    payload = {
        "amount": amount_halalas,
        "currency": "SAR",
        "description": description,
        "callback_url": f"{settings.PUBLIC_BASE_URL}/payment/callback",
        # يجب أن تكون بصيغة ISO 8601
        "expired_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": {
            "telegram_user_id": str(telegram_user_id),
            "plan_key": plan_key,
        },
    }

    async with httpx.AsyncClient(auth=(settings.MOYASAR_SECRET_KEY, "")) as client:
        response = await client.post(f"{MOYASAR_BASE_URL}/invoices", json=payload, timeout=20)

    if response.status_code not in (200, 201):
        raise MoyasarError(f"فشل إنشاء الفاتورة: {response.status_code} - {response.text}")

    return response.json()


async def fetch_invoice(invoice_id: str) -> dict:
    """جلب حالة فاتورة معينة من ميسر مباشرة (مفيد للتحقق اليدوي أو أوامر الإدارة)."""
    async with httpx.AsyncClient(auth=(settings.MOYASAR_SECRET_KEY, "")) as client:
        response = await client.get(f"{MOYASAR_BASE_URL}/invoices/{invoice_id}", timeout=20)

    if response.status_code != 200:
        raise MoyasarError(f"فشل جلب الفاتورة: {response.status_code} - {response.text}")

    return response.json()
