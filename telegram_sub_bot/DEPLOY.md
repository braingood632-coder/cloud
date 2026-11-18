# رفع منصة Cloud على Firebase (خطوة بخطوة)

كل المنصة على Firebase:

| الجزء | الخدمة |
|---|---|
| الموقع (الصفحة الرئيسية، التسجيل، لوحة صاحب القروب، لوحة الأدمن) | Firebase Hosting |
| تسجيل الدخول | Firebase Authentication |
| قاعدة البيانات (المشتركين، القروبات، التحويلات) | Cloud Firestore |
| البوت + إشعار الدفع من ميسر + صفحة الرجوع | Cloud Functions (Python) |
| التذكير كل 30 دقيقة + فحص الانتهاء كل ساعة | Scheduled Functions |
| حذف تنبيه «يجب الاشتراك» بعد 20 ثانية | Cloud Tasks |

> **يتطلب خطة Blaze** (Cloud Functions لا تعمل على الخطة المجانية).
> فيها نفس الحصة المجانية، وغالباً تكون التكلفة صفراً أو بضعة ريالات شهرياً لمشروع بهذا الحجم.

---

## أ) خطوات يدوية في المتصفح (صاحب المشروع فقط — مرة واحدة)

1. ادخل [console.firebase.google.com](https://console.firebase.google.com) ← **Add project** ← سمّه مثلاً `cloud-bot`.
2. **⚙️ → Usage and billing → Details & settings → Modify plan → Blaze** واربط بطاقة.
   ثم من **Google Cloud Console → Billing → Budgets & alerts** أنشئ تنبيه ميزانية (مثلاً 10$).
3. **Build → Authentication → Get started → Email/Password → Enable → Save**.
4. **Build → Firestore Database → Create database** ← Production mode ← الموقع: **`eur3 (europe)`**.
5. اجهز هذه القيم:
   - توكن البوت من [@BotFather](https://t.me/BotFather).
   - مفتاح ميسر السري `sk_live_...` (أو `sk_test_...` للتجربة) من لوحة ميسر ← API Keys.
   - كلمة سر تختارها لإشعارات ميسر (Webhook secret)، أي نص طويل عشوائي.

## ب) خطوات على اللابتوب (يقدر Claude Code ينفذها كلها)

المتطلبات: **Node.js 20+** و **Python 3.12** و git.

```bash
# 1) أدوات Firebase وتسجيل الدخول (يفتح المتصفح مرة واحدة)
npm install -g firebase-tools
firebase login

# 2) المشروع
cd telegram_sub_bot
firebase use --add            # اختر مشروعك، والاسم المستعار: default

# 3) بيئة بايثون للدوال (لازم اسمها venv وبإصدار 3.12)
cd functions
python3.12 -m venv venv       # على ويندوز: py -3.12 -m venv venv
venv/bin/pip install -r requirements.txt     # ويندوز: venv\Scripts\pip install -r requirements.txt
cp .env.example .env          # ثم عدّل القيم داخل .env (ADMIN_EMAILS = إيميلك، OWNER_TELEGRAM_ID، ...)
cd ..

# 4) المفاتيح السرية (كل أمر يطلب منك لصق القيمة — لا تكتبها في أي ملف)
firebase functions:secrets:set BOT_TOKEN
firebase functions:secrets:set MOYASAR_SECRET_KEY
firebase functions:secrets:set MOYASAR_WEBHOOK_SECRET

# 5) الرفع (قواعد الحماية + الدوال + الموقع)
firebase deploy

# 6) ربط البوت بتليجرام — افتح الرابط مرة واحدة:
#    https://<PROJECT_ID>.web.app/api/setup-webhook
#    يجب أن يظهر: {"changed": true, "url": ".../telegram/webhook"}
```

> أول `firebase deploy` قد يأخذ 5–10 دقائق ويطلب تفعيل بعض خدمات Google Cloud
> تلقائياً (Cloud Build, Artifact Registry, Cloud Scheduler, Cloud Tasks, Secret Manager) — وافق عليها.
> إذا فشل بسبب "API not enabled" انتظر دقيقتين وأعد الأمر.

### 7) صلاحية Cloud Tasks (لحذف التنبيه بعد 20 ثانية بالضبط)
```bash
PROJECT_ID=<PROJECT_ID>
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
SA=$PROJECT_NUMBER-compute@developer.gserviceaccount.com
gcloud projects add-iam-policy-binding $PROJECT_ID --member=serviceAccount:$SA --role=roles/cloudtasks.enqueuer
gcloud projects add-iam-policy-binding $PROJECT_ID --member=serviceAccount:$SA --role=roles/iam.serviceAccountUser
```
بدون هذه الخطوة كل شيء يعمل، لكن التنبيه يُحذف مع الرسالة التالية في القروب أو خلال 30 دقيقة بدل 20 ثانية.

### 8) ميسر
لوحة ميسر ← **Developers → Webhooks → Add**:
- URL: `https://<PROJECT_ID>.web.app/moyasar/webhook`
- Secret Token: نفس `MOYASAR_WEBHOOK_SECRET`
- Events: `payment_paid` (و `invoice_paid` إن ظهر)

### 9) حساب الأدمن
1. افتح `https://<PROJECT_ID>.web.app` ← سجّل بنفس الإيميل الموجود في `ADMIN_EMAILS`.
2. افتح رسالة التأكيد في بريدك واضغط الرابط.
3. افتح `https://<PROJECT_ID>.web.app/admin.html` ← تتفعل لوحة الأدمن فوراً.

### 10) التجربة
1. من لوحة التحكم ← القروبات ← «ربط قروب جديد» ← «أضف البوت إلى قروبك».
2. اكتب في القروب من حساب آخر ← تُحذف الرسالة ويظهر زر الاشتراك.
3. اشترك (بمفتاح ميسر Test وبطاقة اختبار) ← تصلك رسالة التفعيل ← تكتب في القروب بدون حذف.
4. يظهر الاشتراك فوراً في لوحة صاحب القروب ولوحة الأدمن.

---

## التحديث لاحقاً
أي تعديل ← `firebase deploy` (أو `firebase deploy --only functions` / `--only hosting`).

## السجلات والأخطاء
`firebase functions:log` أو Google Cloud Console ← Logging.

## خيارات
- `MIN_INSTANCES=1` في `functions/.env` ← البوت يرد فوراً دائماً (بدون تأخير التشغيل البارد)، بتكلفة شهرية بسيطة.
- الباقات والأسعار: `functions/config.py → PLANS`.
- العمولة: `PLATFORM_COMMISSION_PERCENT` في `functions/.env`.

## الاختبارات المحلية (اختياري)
```bash
cd telegram_sub_bot
python tests/fake_services.py 8900 &                       # تليجرام وميسر وهميين
firebase emulators:start --only auth,firestore,functions,hosting --project demo-cloud
functions/venv/bin/python -m pytest tests/test_flow.py -q   # منطق البوت والدفع
functions/venv/bin/python tests/e2e_emulator.py             # النظام كاملاً عبر الدوال
```
للمحاكي ضع في `functions/.env.local` و `functions/.secret.local` قيماً تجريبية (انظر أعلى `tests/e2e_emulator.py`).
