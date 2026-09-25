# بوت اشتراك القروب — دليل التشغيل والاستضافة

## طريقة عمل البوت
1. أي شخص يرسل بالقروب وهو غير مشترك → البوت يحذف رسالته فورًا ويرد برسالة فيها زر "اشترك الآن" يوديه لخاص البوت.
2. بالخاص: يضغط /start → يأكد رقم هاتفه (زر مدمج، ما يكتبه يدوي) → تظهر له باقتان: 3 أشهر (50 ريال) أو 6 أشهر (80 ريال).
3. يختار باقة → البوت يسوي فاتورة دفع في ميسر ويرسل له زر "ادفع الآن" يفتح صفحة الدفع داخل تطبيق تيليجرام (متصفح مدمج).
4. بعد الدفع، ميسر يرسل إشعار لسيرفرك (Webhook) → يتأكد البوت من نجاح الدفع → يفعّل اشتراكه فورًا برسالة تأكيد.
5. المشترك يقدر يرسل بالقروب بحرية طول مدة اشتراكه، وبعد ما تنتهي يرجع يُحذف له تلقائيًا لين يجدد.

## الأسعار
الأسعار **ثابتة ورسمية** ومكتوبة مباشرة بالكود (`bot.py` → متغيّر `PLANS`)، ومافي أي أمر بالبوت يقدر يغيّرها (ولا حتى الأدمن):
- اشتراك 3 أشهر = **50 ريال**
- اشتراك 6 أشهر = **80 ريال**

لو احتجت تغييرها مستقبلاً، التعديل يكون يدويًا بالكود فقط من قِبل المطوّر، ثم إعادة تشغيل البوت.

## التحكم كأدمن (ترسلها بخاص البوت)
- `/setbotname اسم جديد` — يغيّر اسم البوت الظاهر لليوزرات (عبر Telegram API مباشرة).
- `/mystatus` — يعرض حالة اشتراكك.

## الخطوة 1: إنشاء البوت
1. افتح محادثة مع [@BotFather](https://t.me/BotFather) بتيليجرام.
2. أرسل `/newbot` واتبع الخطوات، وخذ الـ **Token**.
3. حط التوكن في ملف `.env` (انسخه من `.env.example`).

## الخطوة 2: حساب ميسر
1. سجّل حساب تاجر في [moyasar.com](https://moyasar.com).
2. من لوحة التحكم → API Keys، خذ **Secret Key** وحطه بـ `MOYASAR_SECRET_KEY`.
3. من إعدادات Webhooks بلوحة ميسر: أضف رابط `https://yourdomain.com/moyasar/webhook`، واختر Secret Token عشوائي وحطه بنفس القيمة بـ `MOYASAR_WEBHOOK_SECRET`.

⚠️ ميسر يتطلب أن يكون حسابك مفعّل (موثّق تجاريًا) عشان يستقبل مدفوعات حقيقية؛ بوضع Test تقدر تجرب بمفاتيح `sk_test_...` قبل التفعيل.

## الخطوة 3: تجهيز السيرفر (VPS)
أبسط طريقة: أي VPS رخيص (Hetzner / DigitalOcean / Contabo) بنظام Ubuntu، أو حتى خدمة مثل Railway/Render لو تفضل بدون سيرفر يدوي.

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv nginx certbot python3-certbot-nginx
git clone <رابط مشروعك أو ارفع الملفات بـ scp/FTP>
cd telegram_subscription_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # عبّي القيم الحقيقية
```

## الخطوة 4: تشغيل البوت + سيرفر الدفع مع systemd (يشتغلون دايمًا ويعيدون التشغيل تلقائي)

أنشئ `/etc/systemd/system/tgbot.service`:
```ini
[Unit]
Description=Telegram Subscription Bot
After=network.target

[Service]
WorkingDirectory=/root/telegram_subscription_bot
ExecStart=/root/telegram_subscription_bot/venv/bin/python bot.py
Restart=always
EnvironmentFile=/root/telegram_subscription_bot/.env

[Install]
WantedBy=multi-user.target
```

وأنشئ `/etc/systemd/system/tgwebhook.service`:
```ini
[Unit]
Description=Moyasar Webhook Server
After=network.target

[Service]
WorkingDirectory=/root/telegram_subscription_bot
ExecStart=/root/telegram_subscription_bot/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 webhook_server:app
Restart=always
EnvironmentFile=/root/telegram_subscription_bot/.env

[Install]
WantedBy=multi-user.target
```
(ثبّت gunicorn: `pip install gunicorn`)

شغّلهم:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tgbot tgwebhook
```

## الخطوة 5: ربط الدومين بـ HTTPS (مطلوب لميسر)
اعمل Reverse Proxy بـ Nginx يوجّه `yourdomain.com` إلى `127.0.0.1:5000`، وفعّل شهادة SSL مجانية:
```bash
sudo certbot --nginx -d yourdomain.com
```
تأكد إن `PUBLIC_BASE_URL` بالـ `.env` = `https://yourdomain.com` بالضبط (نفس الرابط اللي حطيته بويبهوك ميسر).

## الخطوة 6: إضافة البوت للقروب
1. أضف البوت للقروب كـ **Admin** وفعّل له صلاحية "حذف الرسائل" على الأقل.
2. أول رسالة أو تفاعل بالقروب بعد الإضافة، البوت يحفظ آيدي القروب تلقائيًا (تقدر كمان تحطه يدوي بـ `GROUP_ID` بالـ `.env`).

## ملاحظات مهمة
- قاعدة البيانات SQLite (`bot.db`) تُنشأ تلقائيًا بأول تشغيل، وتُحفظ بنفس مجلد المشروع — خذ نسخة احتياطية منها بشكل دوري.
- تغيير اسم البوت عبر `/setbotname` يغيّر **الاسم الظاهر** فقط (مثل "SubmKut")، أما تغيير **اليوزرنيم** (`@something_bot`) فهذا لازم يدويًا عبر BotFather.
- إذا البوت ما قدر يحذف رسائل بالقروب، تأكد إنه أدمن وعنده صلاحية "Delete Messages".
- شغّل البوت أول بوضع اختبار (`sk_test_` بميسر) قبل ما تفعّل مدفوعات حقيقية.
