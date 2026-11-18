# CLAUDE.md

## المشروع
منصة **Cloud**: موقع + بوت تليجرام لحماية القروبات وبيع اشتراكات أعضائها عبر ميسر.
كل شيء على **Firebase** داخل `telegram_sub_bot/`:

- `public/` موقع Firebase Hosting (صفحة هبوط، تسجيل، لوحة صاحب القروب، لوحة الأدمن)
- `functions/` Cloud Functions بايثون 3.12 (`main.py` تعريف الدوال، `app_logic.py`، `bot_handlers.py`، `firebase_db.py`، `moyasar_client.py`، `config.py`)
- `firestore.rules` قواعد الحماية — `firebase.json` التوجيهات (rewrites) والإعدادات
- `tests/` اختبارات على Firebase Emulator

## عند طلب المستخدم "ارفعه" / "سوّ deploy" / "شغّله على فايربيس"
اتبع `telegram_sub_bot/DEPLOY.md` القسم (ب) بالترتيب، من داخل `telegram_sub_bot/`:
1. تأكد من `firebase --version` (وإلا `npm install -g firebase-tools`) ثم `firebase login` إن لزم.
2. `firebase use` — إن لم يكن هناك مشروع مختار، اعرض `firebase projects:list` واسأل المستخدم أيهم.
3. أنشئ `functions/venv` بـ Python **3.12** وثبّت `functions/requirements.txt`.
4. إن لم يوجد `functions/.env` انسخه من `.env.example` واسأل المستخدم عن: إيميله (ADMIN_EMAILS)، معرفه الرقمي في تليجرام (OWNER_TELEGRAM_ID)، معرف الدعم، نسبة العمولة.
5. الأسرار: تحقق بـ `firebase functions:secrets:access BOT_TOKEN` (وكذلك MOYASAR_SECRET_KEY و MOYASAR_WEBHOOK_SECRET). الناقص اطلب من المستخدم تشغيل `firebase functions:secrets:set <NAME>` بنفسه ولصق القيمة هناك — **لا تطلب لصق الأسرار في المحادثة ولا تكتبها في ملفات**.
6. `firebase deploy` — إن فشل بسبب API غير مفعّل، انتظر وأعد المحاولة؛ إن كان السبب خطة Blaze أو Firestore/Auth غير مفعّلين، اطلب من المستخدم الخطوات اليدوية في القسم (أ).
7. افتح/استدعِ `https://<PROJECT_ID>.web.app/api/setup-webhook` وتأكد أن الرد فيه `"url": ".../telegram/webhook"`.
8. نفّذ أوامر gcloud لصلاحية Cloud Tasks (القسم 7) إن كان gcloud متوفراً ومسجلاً.
9. ذكّر المستخدم بإعداد Webhook ميسر (القسم 8) وتفعيل حساب الأدمن (القسم 9).
10. تحقق: `firebase functions:log --only telegramwebhook` بعد أن يرسل المستخدم رسالة للبوت.

## قواعد
- لا ترفع ملفات `.env`, `.secret.local`, `.env.local`, ولا `functions/venv`.
- أي تعديل على شكل البيانات يجب أن يتوافق مع `firestore.rules`.
- شغّل الاختبارات قبل الرفع إن أمكن (انظر آخر DEPLOY.md).
