"""
كل الإعدادات تُقرأ من متغيرات البيئة (Environment Variables)
لا تكتب أي قيم سرية هنا مباشرة.
"""
import os

# توكن البوت من BotFather
BOT_TOKEN = os.environ["BOT_TOKEN"]

# آيدي التليجرام الخاص فيك (الأدمن) - رقم وليس يوزرنيم
ADMIN_ID = int(os.environ["ADMIN_ID"])

# آيدي القروب اللي البوت بيديره (رقم سالب عادة مثل -1001234567890)
GROUP_ID = int(os.environ["GROUP_ID"])

# مفتاح ميسر السري (Secret Key) يبدأ بـ sk_
MOYASAR_SECRET_KEY = os.environ["MOYASAR_SECRET_KEY"]

# رابط السيرفر العام بعد الرفع على Render، مثال:
# https://my-sub-bot.onrender.com  (بدون سلاش في الآخر)
BASE_URL = os.environ["BASE_URL"].rstrip("/")

# جزء سري في رابط الويبهوك حتى ما يقدر أي أحد يرسل تحديثات وهمية للبوت
WEBHOOK_SECRET_PATH = os.environ.get("WEBHOOK_SECRET_PATH", "tg-webhook-9f31ac")

# البورت اللي يعطيه Render تلقائياً
PORT = int(os.environ.get("PORT", 10000))

# اسم قاعدة البيانات (ملف محلي على السيرفر)
DB_PATH = os.environ.get("DB_PATH", "bot.db")
