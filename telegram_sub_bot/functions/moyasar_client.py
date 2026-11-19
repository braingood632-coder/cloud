"""
moyasar_client.py
------------------
غلاف بسيط حول Moyasar API (الفواتير والمدفوعات).
التوثيق الرسمي: https://docs.moyasar.com

كل المدفوعات تدخل حساب ميسر الخاص بك (مالك المنصة)، ثم تحوّل أنت لكل
صاحب قروب حصته من لوحة الأدمن في الموقع.
"""

from __future__ import annotations

import datetime as dt

import httpx

from config import INVOICE_EXPIRY_MINUTES, settings




class MoyasarError(Exception):
    pass


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(auth=(settings.MOYASAR_SECRET_KEY, ""), timeout=20)


async def create_invoice(
    amount_sar: float,
    description: str,
    telegram_user_id: int,
    group_id: int,
    plan_key: str,
) -> dict:
    """ينشئ فاتورة تنتهي صلاحيتها بعد INVOICE_EXPIRY_MINUTES دقيقة."""
    amount_halalas = int(round(amount_sar * 100))  # ميسر يتعامل بالهللة
    expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=INVOICE_EXPIRY_MINUTES)

    payload = {
        "amount": amount_halalas,
        "currency": "SAR",
        "description": description,
        "callback_url": f"{settings.API_BASE_URL}/payment/callback",
        "expired_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": {
            "telegram_user_id": str(telegram_user_id),
            "group_id": str(group_id),
            "plan_key": plan_key,
        },
    }

    async with _client() as client:
        response = await client.post(f"{settings.MOYASAR_BASE_URL}/invoices", json=payload)

    if response.status_code not in (200, 201):
        raise MoyasarError(f"فشل إنشاء الفاتورة: {response.status_code} - {response.text}")
    return response.json()


async def fetch_invoice(invoice_id: str) -> dict:
    async with _client() as client:
        response = await client.get(f"{settings.MOYASAR_BASE_URL}/invoices/{invoice_id}")
    if response.status_code != 200:
        raise MoyasarError(f"فشل جلب الفاتورة: {response.status_code} - {response.text}")
    return response.json()


async def fetch_payment(payment_id: str) -> dict:
    async with _client() as client:
        response = await client.get(f"{settings.MOYASAR_BASE_URL}/payments/{payment_id}")
    if response.status_code != 200:
        raise MoyasarError(f"فشل جلب عملية الدفع: {response.status_code} - {response.text}")
    return response.json()


def paid_payment(invoice: dict) -> dict | None:
    """يرجع أول عملية دفع ناجحة داخل الفاتورة (إن وُجدت)."""
    for payment in invoice.get("payments") or []:
        if payment.get("status") == "paid":
            return payment
    return None
