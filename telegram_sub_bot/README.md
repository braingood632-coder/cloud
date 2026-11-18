# منصة Cloud — موقع + بوت تليجرام + Firebase

نظام كامل من جزأين يعملان معاً في سيرفر واحد:

1. **الموقع** (نفس تصميم صفحة كانفا): صفحة هبوط، تسجيل وإنشاء حساب، لوحة
   تحكم لصاحب القروب، ولوحة أدمن لك.
2. **بوت Cloud** (بوت واحد مركزي): يحمي كل قروب مربوط، ويبيع اشتراكات
   لأعضاء القروب عبر ميسر.

## كيف يعمل؟

| من | ماذا يفعل |
|---|---|
| **صاحب القروب** | يسجّل في الموقع **مجاناً** (لا يدفع أي اشتراك)، يولّد كود ربط، يضيف البوت لقروبه، ويتابع مشتركيه وأرباحه. |
| **عضو القروب** | يكتب في القروب → تُحذف رسالته ويظهر له زر «اشترك الآن» → يختار باقة ويدفع داخل تليجرام → يُفعَّل فوراً. |
| **أنت (الأدمن)** | كل المدفوعات تدخل حساب ميسر الخاص بك. من لوحة الأدمن ترى كم تستحق لكل صاحب قروب وتسجّل التحويل، فيظهر عنده فوراً. |

### لوحة تحكم صاحب القروب
- **نظرة عامة:** الرصيد المستحق، المشتركين النشطين، إجمالي الاشتراكات والتجديدات، صافي الأرباح، أرباح الشهر، المحوَّل له، عدد الأعضاء، الرسائل المحذوفة، رسم بياني لأرباح آخر 30 يوم، وتوزيع حسب الباقة.
- **القروبات:** ربط قروب جديد (كود صالح 15 دقيقة + زر «أضف البوت إلى قروبك» يربط تلقائياً)، حالة البوت في كل قروب، تشغيل/إيقاف رسالة التذكير، فك الربط.
- **المشتركين:** كل مشترك ونوع اشتراكه وتاريخ بدايته وانتهائه وحالته، مع بحث وفلترة وتصدير Excel.
- **المستحقات:** المبيعات، العمولة، الصافي، المحوَّل، الرصيد، وسجل التحويلات.
- **حسابي:** الاسم والجوال وبيانات التحويل البنكي (الآيبان).

### لوحة الأدمن (لك فقط)
إجمالي المبيعات والعمولة والمستحقات، جدول أصحاب القروبات مع الآيبان والرصيد
وزر «تسجيل تحويل»، كل القروبات، كل الاشتراكات، وسجل التحويلات.

### الحماية
- قواعد `firestore.rules` تمنع أي صاحب قروب من رؤية بيانات غيره، أو تزوير
  اشتراك، أو منح نفسه صلاحية أدمن، أو تسجيل تحويل لنفسه، أو سرقة قروب غيره.
- الدفع لا يُفعَّل بمجرد وصول إشعار: السيرفر يجلب الفاتورة من ميسر مباشرة
  ويتأكد أنها مدفوعة وأن المبلغ مطابق.
- ربط القروب متاح لمشرفي القروب فقط، والكود لمرة واحدة.

---

## خطوات التشغيل

### 1) إنشاء مشروع Firebase
1. ادخل [console.firebase.google.com](https://console.firebase.google.com) → **Add project**.
2. **Build → Authentication → Get started → Email/Password → Enable**.
3. **Build → Firestore Database → Create database** (اختر Production mode وموقع `eur3` أو الأقرب لك).
4. **Firestore → Rules:** انسخ محتوى ملف `firestore.rules` كاملاً والصقه ثم **Publish**.
   (أو عبر الطرفية: `npx firebase-tools deploy --only firestore:rules --project <PROJECT_ID>`)
5. **Project settings (⚙️) → General → Your apps → أيقونة الويب `</>`**: سجّل تطبيق ويب،
   وانسخ القيم من `firebaseConfig` إلى متغيرات البيئة:
   `apiKey → FIREBASE_API_KEY`، `authDomain → FIREBASE_AUTH_DOMAIN`، `projectId → FIREBASE_PROJECT_ID`،
   `appId → FIREBASE_APP_ID`، `storageBucket`، `messagingSenderId`. هذه القيم **ليست سرية**.
6. **Project settings → Service accounts → Generate new private key**: ينزل ملف JSON.
   هذا الملف **سري جداً**: لا ترفعه على GitHub ولا ترسله لأحد. ضع محتواه كاملاً
   في متغير `FIREBASE_SERVICE_ACCOUNT` في Render.
7. **Authentication → Settings → Authorized domains:** أضف نطاق موقعك (مثل `cloud-bot.onrender.com`).

### 2) البوت وميسر
- `BOT_TOKEN` من [@BotFather](https://t.me/BotFather). ومن BotFather أيضاً:
  `/setjoingroups` → Enable، و `/setprivacy` → يمكن تركه Enabled أو Disabled (يُفضّل **Disable** حتى يرى البوت كل رسائل القروب).
- `MOYASAR_SECRET_KEY` من لوحة ميسر → API Keys.
- في ميسر → **Developers → Webhooks → Add**:
  - URL: `PUBLIC_BASE_URL/moyasar/webhook`
  - Secret Token: نفس `MOYASAR_WEBHOOK_SECRET`
  - Events: `payment_paid` (و `invoice_paid` إن ظهر)

### 3) النشر على Render
1. **New → Web Service** واختر هذا المستودع، **Root Directory:** `telegram_sub_bot`
2. **Build:** `pip install -r requirements.txt` — **Start:** `python main.py`
3. في **Environment** أضف كل المتغيرات الموجودة في `.env.example`.
   `ADMIN_EMAILS` = الإيميل الذي ستسجل به في الموقع (يصبح أدمن تلقائياً خلال دقائق).
4. بعد أول نشر انسخ رابط Render إلى `PUBLIC_BASE_URL` وأعد النشر.
5. ⚠️ على خطة Render المجانية ينام السيرفر بعد 15 دقيقة بدون زيارات فيتوقف البوت.
   استخدم خطة مدفوعة (Starter) حتى يعمل البوت 24 ساعة.

> لم يعد هناك قاعدة بيانات SQLite: كل البيانات في Firestore، فلا تضيع عند إعادة النشر.

### 4) التجربة
1. افتح موقعك → **سجّل مجاناً** بإيميل `ADMIN_EMAILS`.
2. من **القروبات** اضغط «ربط قروب جديد» ثم «أضف البوت إلى قروبك» واختر قروباً تجريبياً.
3. اكتب في القروب من حساب آخر → تُحذف الرسالة ويظهر زر الاشتراك.
4. اشترك بمفاتيح ميسر التجريبية (Test) → يظهر الاشتراك فوراً في لوحة التحكم.

## تعديل الأسعار والعمولة
- الباقات في `config.py → PLANS` (تظهر تلقائياً في الموقع والبوت).
- العمولة: متغير `PLATFORM_COMMISSION_PERCENT`.

## أوامر البوت
| الأمر | أين | الوظيفة |
|---|---|---|
| `/link CODE` | القروب | ربط القروب بحساب صاحبه (للمشرفين فقط) |
| `/start` | الخاص | ترحيب وشرح |
| `/mysubs` | الخاص | اشتراكات العضو النشطة |

## هيكل المشروع
```
telegram_sub_bot/
├── config.py           الإعدادات والباقات
├── firebase_db.py      قاعدة البيانات (Firestore)
├── moyasar_client.py   ميسر
├── bot_handlers.py     منطق البوت
├── webhook_server.py   السيرفر: الموقع + Webhook + تشغيل البوت
├── main.py             python main.py
├── firestore.rules     قواعد حماية قاعدة البيانات
├── web/                الموقع (index, auth, dashboard, admin)
└── tests/              اختبارات على Firebase Emulator
```

## تشغيل الاختبارات محلياً
```bash
npx firebase-tools emulators:start --only auth,firestore --project demo-cloud
python -m pytest tests -q
```
وللموقع محلياً بدون بوت:
```bash
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099 \
FIREBASE_PROJECT_ID=demo-cloud RUN_BOT=false python main.py
```
