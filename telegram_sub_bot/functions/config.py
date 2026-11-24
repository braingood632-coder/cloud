"""
config.py
---------
الإعدادات. على Firebase تأتي من مصدرين:
  - functions/.env            إعدادات عادية (غير سرية) تُرفع مع الدوال
  - Secret Manager            المفاتيح السرية: BOT_TOKEN, MOYASAR_SECRET_KEY, MOYASAR_WEBHOOK_SECRET
                              (تُضبط بالأمر: firebase functions:secrets:set BOT_TOKEN)
"""

from __future__ import annotations

import hashlib
import json
import os

# المنطقة التي تعمل فيها الدوال (بلجيكا: الأقرب والأرخص للسعودية بين المناطق المدعومة بالكامل)
REGION = "europe-west1"


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default) or default


def _project_id() -> str:
    pid = _get("GCLOUD_PROJECT") or _get("GOOGLE_CLOUD_PROJECT") or _get("FIREBASE_PROJECT_ID")
    if not pid and _get("FIREBASE_CONFIG"):
        try:
            pid = json.loads(_get("FIREBASE_CONFIG")).get("projectId", "")
        except ValueError:
            pid = ""
    if not pid:
        pid = (service_account_info() or {}).get("project_id", "")
    return pid


def service_account_info() -> dict | None:
    """
    مفتاح Service Account لتشغيل البوت خارج Firebase (مثل Render):
      FIREBASE_SERVICE_ACCOUNT  محتوى ملف JSON كاملاً، أو مسار الملف (مثل /etc/secrets/firebase.json)
    """
    raw = _get("FIREBASE_SERVICE_ACCOUNT").strip()
    if not raw:
        return None
    if not raw.startswith("{"):
        with open(raw, encoding="utf-8") as f:
            raw = f.read()
    return json.loads(raw)


class Settings:
    """تُقرأ القيم عند كل استخدام (الأسرار تُحقن في البيئة عند تشغيل الدالة)."""

    # --- أسرار ---
    @property
    def BOT_TOKEN(self) -> str:
        return _get("BOT_TOKEN")

    @property
    def MOYASAR_SECRET_KEY(self) -> str:
        return _get("MOYASAR_SECRET_KEY")

    @property
    def MOYASAR_WEBHOOK_SECRET(self) -> str:
        return _get("MOYASAR_WEBHOOK_SECRET")

    @property
    def TELEGRAM_WEBHOOK_SECRET(self) -> str:
        """توكن سري يرسله تليجرام مع كل تحديث؛ مشتق من توكن البوت فلا يحتاج إعداداً إضافياً."""
        return hashlib.sha256(("cloud-webhook:" + self.BOT_TOKEN).encode()).hexdigest()[:48]

    # --- إعدادات عادية (functions/.env) ---
    @property
    def BOT_NAME(self) -> str:
        return _get("BOT_NAME", "Cloud")

    @property
    def BOT_USERNAME(self) -> str:
        return _get("BOT_USERNAME").lstrip("@")

    @property
    def OWNER_TELEGRAM_ID(self) -> int:
        return int(_get("OWNER_TELEGRAM_ID", "0") or 0)

    @property
    def SUPPORT_USERNAME(self) -> str:
        return _get("SUPPORT_USERNAME", "radhadh91").lstrip("@")

    @property
    def PLATFORM_COMMISSION_PERCENT(self) -> float:
        return float(_get("PLATFORM_COMMISSION_PERCENT", "0") or 0)

    @property
    def ADMIN_EMAILS(self) -> list[str]:
        return [e.strip().lower() for e in _get("ADMIN_EMAILS").split(",") if e.strip()]

    @property
    def FIREBASE_PROJECT_ID(self) -> str:
        return _project_id()

    @property
    def FIRESTORE_DATABASE(self) -> str:
        """اسم قاعدة Firestore (فارغ = (default)). يفيد عند مشاركة مشروع Firebase مع تطبيق آخر."""
        return _get("FIRESTORE_DATABASE").strip()

    @property
    def PUBLIC_BASE_URL(self) -> str:
        """رابط الموقع. افتراضياً رابط Firebase Hosting: https://<project>.web.app"""
        url = _get("PUBLIC_BASE_URL")
        if not url and self.FIREBASE_PROJECT_ID:
            url = f"https://{self.FIREBASE_PROJECT_ID}.web.app"
        return url.rstrip("/")

    @property
    def API_BASE_URL(self) -> str:
        """
        رابط سيرفر البوت (Webhook تليجرام، إشعار ميسر، صفحة الرجوع، /config.js).
        على Firebase Functions = رابط الموقع نفسه. على Render يُؤخذ تلقائياً من RENDER_EXTERNAL_URL.
        """
        url = _get("API_BASE_URL") or _get("RENDER_EXTERNAL_URL") or self.PUBLIC_BASE_URL
        return url.rstrip("/")

    # --- للاختبار فقط (توجيه الطلبات لخوادم وهمية) ---
    @property
    def TELEGRAM_API_BASE(self) -> str:
        return _get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")

    @property
    def MOYASAR_BASE_URL(self) -> str:
        return _get("MOYASAR_BASE_URL", "https://api.moyasar.com/v1").rstrip("/")


settings = Settings()


# ---------------------------------------------------------------------------
# الباقات التي يشترك فيها أعضاء القروبات — عدّل هنا فقط عند تغيير الأسعار
# ---------------------------------------------------------------------------
PLANS: dict[str, dict] = {
    "plan_3m": {"name": "الباقة الذهبية", "price": 50.0, "days": 90, "label": "3 أشهر"},
    "plan_6m": {"name": "باقة 6 أشهر", "price": 80.0, "days": 180, "label": "6 أشهر"},
}

INVOICE_EXPIRY_MINUTES = 30          # صلاحية فاتورة ميسر
REDEEM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # بدون 0/O/1/I لتفادي اللبس
REDEEM_CODE_LENGTH = 8               # كود التفعيل الذي يظهر بعد الدفع في الموقع (يُستخدم مرة واحدة)
LINK_CODE_TTL_MINUTES = 15           # صلاحية كود ربط القروب
REMINDER_EVERY_MINUTES = 30          # رسالة التذكير داخل القروبات
WARNING_MESSAGE_AUTO_DELETE_SECONDS = 20  # حذف تنبيه "يجب الاشتراك"
CACHE_TTL_SECONDS = 60               # كاش محلي داخل نسخة الدالة
