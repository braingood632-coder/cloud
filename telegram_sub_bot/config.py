"""
config.py
---------
تحميل كل الإعدادات والمتغيرات السرية من ملف .env (أو من متغيرات البيئة في
Render) في مكان واحد.
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
    return value or ""


def _bool(key: str, default: str = "false") -> bool:
    return _get(key, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # --- تشغيل ---
    # RUN_BOT=false يشغّل الموقع فقط بدون البوت (مفيد للتجربة المحلية)
    RUN_BOT: bool = field(default_factory=lambda: _bool("RUN_BOT", "true"))

    # --- تليجرام ---
    BOT_TOKEN: str = field(default_factory=lambda: _get("BOT_TOKEN"))
    BOT_NAME: str = field(default_factory=lambda: _get("BOT_NAME", "Cloud"))
    # معرف تليجرام الرقمي لمالك المنصة (أنت). يُستثنى دائماً من فحص الاشتراك.
    OWNER_TELEGRAM_ID: int = field(default_factory=lambda: int(_get("OWNER_TELEGRAM_ID", "0") or 0))
    SUPPORT_USERNAME: str = field(default_factory=lambda: _get("SUPPORT_USERNAME", "radhadh91"))

    # --- ميسر (Moyasar) ---
    MOYASAR_SECRET_KEY: str = field(default_factory=lambda: _get("MOYASAR_SECRET_KEY"))
    MOYASAR_WEBHOOK_SECRET: str = field(default_factory=lambda: _get("MOYASAR_WEBHOOK_SECRET"))

    # --- المنصة ---
    # نسبة عمولتك من كل اشتراك (0 = كامل المبلغ لصاحب القروب)
    PLATFORM_COMMISSION_PERCENT: float = field(
        default_factory=lambda: float(_get("PLATFORM_COMMISSION_PERCENT", "0") or 0)
    )
    # إيميلات حسابات الأدمن في الموقع (أنت)، مفصولة بفاصلة
    ADMIN_EMAILS: list[str] = field(
        default_factory=lambda: [e.strip().lower() for e in _get("ADMIN_EMAILS", "").split(",") if e.strip()]
    )

    # --- Firebase (السيرفر) ---
    # إما محتوى ملف service account كاملاً (JSON) أو مسار الملف
    FIREBASE_SERVICE_ACCOUNT: str = field(default_factory=lambda: _get("FIREBASE_SERVICE_ACCOUNT"))
    FIREBASE_PROJECT_ID: str = field(default_factory=lambda: _get("FIREBASE_PROJECT_ID"))

    # --- Firebase (الموقع) — هذه القيم عامة وليست سرية ---
    FIREBASE_API_KEY: str = field(default_factory=lambda: _get("FIREBASE_API_KEY"))
    FIREBASE_AUTH_DOMAIN: str = field(default_factory=lambda: _get("FIREBASE_AUTH_DOMAIN"))
    FIREBASE_APP_ID: str = field(default_factory=lambda: _get("FIREBASE_APP_ID"))
    FIREBASE_STORAGE_BUCKET: str = field(default_factory=lambda: _get("FIREBASE_STORAGE_BUCKET"))
    FIREBASE_MESSAGING_SENDER_ID: str = field(default_factory=lambda: _get("FIREBASE_MESSAGING_SENDER_ID"))

    # --- السيرفر ---
    PUBLIC_BASE_URL: str = field(default_factory=lambda: _get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"))
    SERVER_HOST: str = field(default_factory=lambda: _get("SERVER_HOST", "0.0.0.0"))
    SERVER_PORT: int = field(default_factory=lambda: int(_get("PORT", _get("SERVER_PORT", "8000"))))

    def validate(self) -> None:
        missing = []
        if not self.FIREBASE_PROJECT_ID:
            missing.append("FIREBASE_PROJECT_ID")
        if self.RUN_BOT:
            for key in ("BOT_TOKEN", "MOYASAR_SECRET_KEY", "MOYASAR_WEBHOOK_SECRET"):
                if not getattr(self, key):
                    missing.append(key)
        if missing:
            raise RuntimeError("متغيرات البيئة التالية مطلوبة ولم يتم ضبطها: " + ", ".join(missing))


settings = Settings()


# ---------------------------------------------------------------------------
# الباقات التي يشترك فيها أعضاء القروبات — عدّل هنا فقط عند تغيير الأسعار
# ---------------------------------------------------------------------------
PLANS: dict[str, dict] = {
    "plan_3m": {"name": "الباقة الذهبية", "price": 50.0, "days": 90, "label": "3 أشهر"},
    "plan_6m": {"name": "باقة 80 ريال", "price": 80.0, "days": 180, "label": "6 أشهر"},
}

# مدة صلاحية فاتورة ميسر بالدقائق
INVOICE_EXPIRY_MINUTES = 30

# مدة صلاحية كود ربط القروب بالدقائق
LINK_CODE_TTL_MINUTES = 15

# فحص الاشتراكات المنتهية
EXPIRY_CHECK_INTERVAL_SECONDS = 3600

# رسالة التذكير داخل كل قروب مربوط (نصف ساعة)
GROUP_REMINDER_INTERVAL_SECONDS = 1800

# تحديث عدد أعضاء القروبات واسمها
GROUP_STATS_INTERVAL_SECONDS = 6 * 3600

# حذف تنبيه "يجب الاشتراك" تلقائياً بعد
WARNING_MESSAGE_AUTO_DELETE_SECONDS = 20

# مدة الكاش المحلي لنتائج فحص الاشتراك وبيانات القروب (ثواني)
CACHE_TTL_SECONDS = 60
