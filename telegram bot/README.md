# بوت اشتراك القروب (تليجرام + ميسر)

بوت يدير اشتراك قروب واحد بدفع إلكتروني عبر ميسر:
- `/subscribe` يرسل للعضو رابط دفع
- بعد الدفع، يضاف العضو تلقائياً برابط دعوة لمرة واحدة
- رسالة تذكير كل 30 دقيقة بالسعر والمدة والمقاعد المتبقية
- طرد تلقائي لأي عضو منتهي الاشتراك أو دخل بدون اشتراك

## 1) قبل الرفع

### أ) إعداد البوت في تليجرام
1. تأكد إن البوت **أدمن في القروب** وعنده صلاحية "حظر/طرد الأعضاء".
2. أضف البوت للقروب.
3. عشان تعرف `GROUP_ID`: أرسل أي رسالة بالقروب، ثم افتح:
   `https://api.telegram.org/bot<التوكن>/getUpdates`
   وابحث عن `"chat":{"id": -100xxxxxxxxxx` — هذا هو GROUP_ID (رقم سالب).

### ب) إعداد ميسر
1. أنشئ حساب على [dashboard.moyasar.com](https://dashboard.moyasar.com)
2. من Settings → API Keys خذ **Secret Key** (يبدأ بـ `sk_`)
3. لا تحتاج تربط ويب هوك عام يدوياً — الكود يرسل `callback_url` مع كل فاتورة تلقائياً.

### ج) آيدي التليجرام الخاص فيك (ADMIN_ID)
كلّم البوت [@userinfobot](https://t.me/userinfobot) وراح يعطيك رقمك.

## 2) الرفع على Render (مجاني)

1. ارفع هذا المجلد كـ repository على GitHub:
   ```bash
   git init
   git add .
   git commit -m "init"
   git branch -M main
   git remote add origin <رابط_الريبو_تبعك>
   git push -u origin main
   ```
2. في [render.com](https://render.com): New → Web Service → اختر الريبو.
3. الإعدادات:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. في تبويب Environment أضف المتغيرات (نفس أسماء `.env.example`):
   `BOT_TOKEN, ADMIN_ID, GROUP_ID, MOYASAR_SECRET_KEY, BASE_URL, WEBHOOK_SECRET_PATH`
   - `BASE_URL` يكون رابط الخدمة نفسها اللي يعطيك ياه Render، مثال:
     `https://sub-bot-xxxx.onrender.com`
5. اضغط Deploy. لما تشوف الحالة "Live" افتح البوت في تليجرام وجرّب `/start`.

### ⚠️ ملاحظات على الخطة المجانية في Render
- الخدمة المجانية "تنام" بعد ~15 دقيقة بدون طلبات، وأول طلب بعدها يكون بطيء شوي (Cold Start). حل مجاني: سجّل حساب [UptimeRobot](https://uptimerobot.com) وخله يبينغ رابط `BASE_URL/` كل 5 دقائق.
- قاعدة البيانات SQLite (ملف `bot.db`) تُمسح إذا أعدت النشر (Redeploy) على الخطة المجانية لأن التخزين غير دائم. للتجربة تمام، لكن للاستخدام الجاد لاحقاً يفضّل ترقية الخطة أو استخدام قاعدة بيانات خارجية دائمة.

## 3) أوامر الأدمن (تكتبها بالخاص مع البوت وأنت صاحب ADMIN_ID)

| الأمر | الوظيفة |
|---|---|
| `/setprice 30` | تحديد سعر الاشتراك (ريال) |
| `/setduration 30` | تحديد مدة الاشتراك (يوم) |
| `/setcapacity 50` | تحديد عدد المقاعد |
| `/status` | عرض الإعدادات الحالية وعدد المشتركين الفعّالين |

## 4) أوامر المستخدم العادي

- `/start` أو `/subscribe` → يرسل رابط الدفع.
