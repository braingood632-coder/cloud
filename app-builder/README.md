# بنّاء التطبيقات (App Builder)

تكتب وصف تطبيق بالعربي أو الإنجليزي، فيولّد مشروع أندرويد (Kotlin + Jetpack Compose) ويبني ملف APK.

## كيف يعمل
1. **المحلّل** (`server/src/parser.js`) يحوّل الوصف إلى مواصفة JSON: الاسم واللون واللغة والشاشات.
2. **المولّد** (`server/src/generator.js` و`components.js`) يركّب مشروع Gradle كامل من مكتبة شاشات جاهزة:
   عداد، مهام، ملاحظات، حاسبة، ساعة إيقاف، كتلة الجسم، محوّل وحدات، نرد، حول.
3. **البناء** (`server/src/builder.js`) يشغّل `gradle assembleDebug` في طابور (بناء واحد في كل مرة).
4. **الذكاء الاصطناعي اختياري** (`server/src/llm.js`): للأفكار التي لا تغطيها القوالب. ضع أحد المفتاحين:
   - `ANTHROPIC_API_KEY` (النموذج من `ANTHROPIC_MODEL`)
   - `GEMINI_API_KEY` (النموذج من `GEMINI_MODEL`، الافتراضي `gemini-2.0-flash`)

   إذا فشل البناء يُرسل سجل الأخطاء للنموذج ليصلحها (حتى `MAX_REPAIRS=3` محاولات).
   بدون مفتاح يعمل كل شيء بالقوالب فقط.

## التشغيل
```bash
# مع Docker (يجهّز Android SDK تلقائياً)
docker build -t app-builder .
docker run -p 3000:3000 -v appdata:/data \
  -e ACCESS_TOKEN=كلمة-سر-خاصة \
  -e GEMINI_API_KEY=... \
  app-builder
```
افتح `http://localhost:3000`. بدون Docker: ثبّت JDK 17 وGradle 8.9 وAndroid SDK، واضبط `ANDROID_HOME`، ثم `npm start`.

وضع تجربة بدون Android SDK: `BUILD_DRY_RUN=1 npm start` يولّد المشروع فقط ويتيح تحميل الكود المصدري.

## متغيرات البيئة
| المتغير | الوصف |
|---|---|
| `PORT` | المنفذ (3000) |
| `ACCESS_TOKEN` | إن وُضع، تتطلب كل طلبات `/api` هذا الرمز. **أنصح به بشدة عند النشر العلني.** |
| `DATA_DIR` | مكان المشاريع والـ APK |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | تفعيل وضع الذكاء الاصطناعي |
| `MAX_QUEUE`, `BUILD_TIMEOUT_MS`, `MAX_REPAIRS` | حدود الطابور والمهلة والإصلاح |

## ملاحظات مهمة
- الـ APK من نوع **debug** للتثبيت المباشر على جوالك. النشر في Google Play يحتاج توقيع release بمفتاحك.
- شيفرة Kotlin المولّدة تُفحص بنيوياً في الاختبارات (`npm test`) لكنها لم تُجمَّع فعلياً في بيئة التطوير لأن Android SDK لم يتوفر فيها؛ أول بناء حقيقي يكون على سيرفرك.
- لا تفتح السيرفر للعامة بدون `ACCESS_TOKEN`: كل بناء يستهلك CPU وذاكرة، وأي وضع ذكاء اصطناعي يستهلك رصيد مفتاحك.

## الاختبار
```bash
npm test
```
