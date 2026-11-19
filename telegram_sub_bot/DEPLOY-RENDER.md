# تشغيل منصة Cloud على Render + Firebase (الخطة المجانية)

| الجزء | أين |
|---|---|
| الموقع + تسجيل الدخول + قاعدة البيانات | Firebase (Spark مجاني): Hosting + Auth + Firestore |
| البوت + إشعار ميسر + صفحة الرجوع + `/config.js` + التذكير والصيانة | Render (`functions/server.py`) |

الموقع يجلب `/config.js` من سيرفر Render (تحويل 302 في `firebase.json`)، ومنه يعرف رابط السيرفر (`apiBase`).

## 1) Firebase (مرة واحدة، من المتصفح)
1. **Authentication → Get started → Email/Password → Enable**.
2. **Firestore Database → Create database** → Production → الموقع `eur3`.
3. **⚙️ Project settings → Service accounts → Generate new private key** → يُحمَّل ملف JSON (سرّي، لا ترفعه لأي مكان غير Render).

## 2) Render
1. render.com → **New → Blueprint** → اختر مستودع GitHub والفرع → يقرأ `render.yaml`.
2. يطلب قيم الأسرار:
   - `BOT_TOKEN` من @BotFather
   - `MOYASAR_SECRET_KEY` (`sk_test_...` للتجربة / `sk_live_...` للحقيقي)
   - `MOYASAR_WEBHOOK_SECRET` نص عشوائي طويل تختاره (نفسه يوضع في ميسر)
   - `FIREBASE_SERVICE_ACCOUNT` الصق **محتوى** ملف JSON كاملاً
3. **Apply** → بعد البناء يظهر الرابط مثل `https://cloud-bot-xxxx.onrender.com`.
   عند التشغيل يضبط السيرفر Webhook تليجرام تلقائياً. للتأكد افتح `https://<render>/api/setup-webhook`.

## 3) ربط الموقع بالسيرفر ورفعه
في `firebase.json` ضع رابط Render مكان `RENDER_URL` ثم:
```bash
cd telegram_sub_bot
firebase deploy --only hosting,firestore
```

## 4) ميسر
Developers → Webhooks → Add:
- URL: `https://<render>/moyasar/webhook`
- Secret Token: نفس `MOYASAR_WEBHOOK_SECRET`
- Events: `payment_paid` (و `invoice_paid`)

## 5) الأدمن
سجّل في الموقع بإيميل `ADMIN_EMAILS` ← أكّد الإيميل ← افتح `/admin.html`.

## دومين خاص
- الموقع: Firebase Hosting → Add custom domain، ثم غيّر `PUBLIC_BASE_URL` في Render إلى الدومين.
- (اختياري) السيرفر: Render → Settings → Custom Domains (مثل `api.دومينك`)، ثم ضع الرابط في `API_BASE_URL` في Render، وحدّث تحويل `/config.js` في `firebase.json` وأعد رفع الموقع، وحدّث رابط Webhook ميسر.

## الاختبار المحلي
```bash
cd telegram_sub_bot
python tests/fake_services.py 8900 &
firebase emulators:start --only auth,firestore,hosting --project demo-cloud &
cd functions
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099 FIREBASE_PROJECT_ID=demo-cloud \
BOT_TOKEN=123:TEST TELEGRAM_API_BASE=http://127.0.0.1:8900 MOYASAR_BASE_URL=http://127.0.0.1:8900/v1 \
MOYASAR_SECRET_KEY=sk_test MOYASAR_WEBHOOK_SECRET=test-secret PUBLIC_BASE_URL=http://127.0.0.1:5000 \
API_BASE_URL=http://127.0.0.1:8000 uvicorn server:app --port 8000 &
cd .. && E2E_API_BASE=http://127.0.0.1:8000 functions/venv/Scripts/python tests/e2e_emulator.py
```

## السجلات
Render → الخدمة → **Logs**.
