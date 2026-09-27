"""
config.py
---------
تحميل كل الإعدادات والمتغيرات السرية من ملف .env في مكان واحد،
حتى لا تتكرر عمليات os.getenv في كل ملف من ملفات المشروع.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _get(key: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(key, default)
    if required and not value:
        raise RuntimeError(f"متغير البيئة {key} مطلوب ولم يتم ضبطه في ملف .env")
    return value


@dataclass
class Settings:
    # --- تليجرام ---
    BOT_TOKEN: str = field(default_factory=lambda: _get("BOT_TOKEN", required=True))
    BOT_NAME: str = field(default_factory=lambda: _get("BOT_NAME", "Cloud"))
    CHANNEL_NAME: str = field(default_factory=lambda: _get("CHANNEL_NAME", "قناة عقارات السعودية 2030"))
    ADMIN_GROUP_ID: int = field(default_factory=lambda: int(_get("ADMIN_GROUP_ID", "0")))
    # معرف تليجرام لمالك البوت (رقمي)، يُستثنى دائماً من فحص الاشتراك حتى لو لم يكن
    # مشرفاً رسمياً في القروب. احصل عليه عبر @userinfobot.
    OWNER_TELEGRAM_ID: int = field(default_factory=lambda: int(_get("OWNER_TELEGRAM_ID", "0")))

    # --- ميسر (Moyasar) ---
    MOYASAR_SECRET_KEY: str = field(default_factory=lambda: _get("MOYASAR_SECRET_KEY", required=True))
    MOYASAR_WEBHOOK_SECRET: str = field(default_factory=lambda: _get("MOYASAR_WEBHOOK_SECRET", required=True))

    # --- السيرفر ---
    PUBLIC_BASE_URL: str = field(default_factory=lambda: _get("PUBLIC_BASE_URL", required=True))
    SERVER_HOST: str = field(default_factory=lambda: _get("SERVER_HOST", "0.0.0.0"))
    # Render (وأغلب منصات الاستضافة) تحقن متغير PORT تلقائياً ويجب الاستماع عليه؛
    # SERVER_PORT يبقى فقط كخيار احتياطي للتشغيل المحلي على جهازك.
    SERVER_PORT: int = field(default_factory=lambda: int(_get("PORT", _get("SERVER_PORT", "8000"))))

    # --- قاعدة البيانات ---
    DATABASE_URL: str = field(
        default_factory=lambda: _get("DATABASE_URL", "sqlite+aiosqlite:///./subscribers.db")
    )


settings = Settings()


# ---------------------------------------------------------------------------
# الباقات المتاحة — عدّل هنا فقط عند تغيير الأسعار أو المدد
# ---------------------------------------------------------------------------
PLANS: dict[str, dict] = {
    "plan_3m": {"name": "باقة 3 أشهر", "price": 50.0, "days": 90},
    "plan_6m": {"name": "باقة 6 أشهر", "price": 80.0, "days": 180},
}

# مدة صلاحية فاتورة ميسر بالدقائق قبل إلغائها تلقائياً
INVOICE_EXPIRY_MINUTES = 30

# كل كم دقيقة يتم فحص الاشتراكات المنتهية تلقائياً
EXPIRY_CHECK_INTERVAL_SECONDS = 3600  # كل ساعة

# كل كم ثانية يتم إرسال رسالة تذكير بالاشتراك داخل القروب (نصف ساعة)
GROUP_REMINDER_INTERVAL_SECONDS = 1800

# بعد كم ثانية يتم حذف تنبيه "يجب الاشتراك" تلقائياً من القروب حتى لا يمتلئ بالرسائل
WARNING_MESSAGE_AUTO_DELETE_SECONDS = 20
