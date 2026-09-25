import os
from dotenv import load_dotenv

load_dotenv()

# توكن البوت من BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# آيديات الأدمن المسموح لهم بتغيير الأسعار واسم البوت (مفصولة بفاصلة)
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# آيدي القروب اللي البوت يراقبه (اختياري، يتحدد تلقائي أول ما تضيف البوت كأدمن في القروب)
GROUP_ID = os.getenv("GROUP_ID")
GROUP_ID = int(GROUP_ID) if GROUP_ID else None

# مفاتيح ميسر
MOYASAR_SECRET_KEY = os.getenv("MOYASAR_SECRET_KEY", "")
MOYASAR_WEBHOOK_SECRET = os.getenv("MOYASAR_WEBHOOK_SECRET", "")  # secret token تحطه في لوحة ميسر

# الدومين العام اللي يوصل له سيرفر الويبهوك (مثال: https://yourdomain.com)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")

DB_PATH = os.getenv("DB_PATH", "bot.db")

CURRENCY = "SAR"

# كم ثانية بين تحذير وتحذير لنفس الشخص بالقروب (عشان ما يصير سبام)
WARN_COOLDOWN_SECONDS = 30
