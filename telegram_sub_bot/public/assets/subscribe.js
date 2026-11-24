// صفحة الاشتراك: العضو يختار الباقة ويدفع في الموقع (عبر ميسر)، ثم يحصل على كود تفعيل
// يرسله للبوت أو داخل القروب. الكود يُستخدم مرة واحدة فقط.
import { ICONS, esc, num, toast } from "/assets/common.js";

const cfg = window.CLOUD_CONFIG || {};
const api = (cfg.apiBase || "").replace(/\/$/, "");
const app = document.getElementById("app");
const params = new URLSearchParams(location.search);
const groupId = (params.get("g") || "").trim();
const PENDING_KEY = "cloud_pending_invoice";

document.getElementById("logo").innerHTML = ICONS.cloud;

const supportLink = cfg.supportUsername
  ? `<a href="https://t.me/${encodeURIComponent(cfg.supportUsername)}" target="_blank" rel="noopener">@${esc(cfg.supportUsername)}</a>`
  : "الدعم الفني";

function showError(text) {
  app.innerHTML = `<div class="card done-card"><div class="result-icon">⚠️</div><h2>${esc(text)}</h2>
    <p class="muted">لأي استفسار تواصل مع ${supportLink}</p>
    <div class="row-btns"><a class="btn btn-primary" href="${location.pathname}${groupId ? "?g=" + encodeURIComponent(groupId) : ""}">العودة لصفحة الاشتراك</a></div></div>`;
}

// ---------------------------------------------------------------------------
// 1) عرض الباقات
// ---------------------------------------------------------------------------
async function renderPlans() {
  let groupTitle = "";
  if (groupId) {
    try {
      const res = await fetch(`${api}/api/group?g=${encodeURIComponent(groupId)}`);
      if (res.ok) groupTitle = (await res.json()).title || "";
    } catch (e) { /* نكمل بدون اسم القروب */ }
  }

  const plans = Object.entries(cfg.plans || {});
  app.innerHTML = `
    <div class="sub-head">
      <span class="pill">الاشتراك في المجموعة</span>
      <h1>📦 اختر باقة الاشتراك</h1>
      <p class="muted">ادفع بأمان من هنا عبر بوابة ميسر، وبعد الدفع يظهر لك <b>كود تفعيل</b> ترسله للبوت أو داخل القروب فيتفعّل اشتراكك فوراً.</p>
      ${groupTitle ? `<div class="group-name badge badge-good">👥 المجموعة: ${esc(groupTitle)}</div>` : ""}
    </div>
    <div class="plans">
      ${plans.map(([key, p], i) => `
        <div class="plan ${i === 0 ? "gold" : ""}">
          <span class="tag">${i === 0 ? "الأكثر طلباً" : "خيار إضافي"}</span>
          <h3>${esc(p.name)}</h3>
          <div class="price">${num(p.price)} <small>ريال سعودي</small></div>
          <hr/>
          <dl><dt>المدة</dt><dd>${esc(p.label || "")} (${num(p.days)} يوم)</dd>
          <dt>المميزات</dt><dd>صلاحية كاملة للكتابة في المجموعة بدون حذف رسائلك، وتفعيل فوري بعد الدفع.</dd></dl>
          <button class="btn ${i === 0 ? "btn-gold" : "btn-primary"}" data-plan="${esc(key)}">اشترك وادفع ${num(p.price)} ريال</button>
        </div>`).join("")}
    </div>
    <label class="check terms-check"><input type="checkbox" id="agree" /> <span>أوافق على <a href="/#terms" target="_blank">شروط الخدمة وسياسة الاسترجاع</a></span></label>
    <div class="pay-note muted">🔒 الدفع آمن عبر ميسر: مدى، فيزا، ماستركارد، Apple Pay. تنتهي صلاحية عملية الدفع خلال 30 دقيقة.</div>
    <div class="grid grid-4" style="margin-top:34px">
      <div class="step"><div class="num">1</div><h3>اختر الباقة</h3><p>اختر الباقة المناسبة واضغط «اشترك وادفع».</p></div>
      <div class="step"><div class="num">2</div><h3>ادفع بأمان</h3><p>تنتقل لصفحة الدفع الآمنة من ميسر وتدفع بالبطاقة أو Apple Pay.</p></div>
      <div class="step"><div class="num">3</div><h3>استلم الكود</h3><p>بعد نجاح الدفع يظهر لك كود تفعيل خاص بك (يُستخدم مرة واحدة).</p></div>
      <div class="step"><div class="num">4</div><h3>فعّل اشتراكك</h3><p>أرسل الكود للبوت أو داخل القروب، ويتفعّل اشتراكك فوراً.</p></div>
    </div>`;

  app.querySelectorAll("[data-plan]").forEach((btn) => btn.addEventListener("click", () => checkout(btn)));
}

async function checkout(btn) {
  if (!document.getElementById("agree").checked) {
    toast("يجب الموافقة على شروط الخدمة وسياسة الاسترجاع أولاً");
    return;
  }
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = "جارٍ تجهيز صفحة الدفع…";
  try {
    const res = await fetch(`${api}/api/checkout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: btn.dataset.plan, g: groupId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.url) throw new Error(data.error || "checkout");
    localStorage.setItem(PENDING_KEY, data.invoiceId);
    location.href = data.url;
  } catch (e) {
    btn.disabled = false;
    btn.textContent = label;
    toast("تعذر فتح صفحة الدفع، حاول مرة أخرى");
  }
}

// ---------------------------------------------------------------------------
// 2) بعد الرجوع من ميسر: التحقق من الدفع وعرض كود التفعيل
// ---------------------------------------------------------------------------
async function renderResult() {
  const invoiceId = params.get("invoice_id") || localStorage.getItem(PENDING_KEY) || "";
  const paymentId = params.get("id") || "";
  app.innerHTML = `<div class="card done-card"><div class="result-icon">⏳</div><h2>جارٍ التحقق من الدفع…</h2></div>`;

  const q = new URLSearchParams();
  if (invoiceId) q.set("invoice_id", invoiceId);
  if (paymentId) q.set("id", paymentId);

  let data = {};
  for (let i = 0; i < 6; i++) {
    try {
      const res = await fetch(`${api}/api/order?${q}`, { cache: "no-store" });
      data = await res.json().catch(() => ({}));
    } catch (e) { data = { status: "error" }; }
    if (data.status === "ok" || data.status === "not_found" || data.status === "amount_mismatch") break;
    await new Promise((r) => setTimeout(r, 3000));
  }

  if (data.status === "ok") {
    const bot = data.botUsername ? "@" + esc(data.botUsername) : "البوت";
    app.innerHTML = `
      <div class="card done-card">
        <div class="result-icon">✅</div>
        <h2>تم الدفع بنجاح</h2>
        <p>${esc(data.planName || "")} — ${num(data.planDays || 0)} يوم${data.groupTitle ? ` — 👥 ${esc(data.groupTitle)}` : ""}</p>
        <p class="muted">كود التفعيل الخاص بك (يُستخدم مرة واحدة فقط):</p>
        <div class="code-box" id="code">${esc(data.code)}</div>
        ${data.used ? `<div class="alert alert-warn">هذا الكود تم استخدامه وتفعيل الاشتراك به مسبقاً.</div>` : ""}
        <div class="row-btns">
          <button class="btn btn-outline" id="copy">نسخ الكود</button>
          ${data.botLink ? `<a class="btn btn-primary" href="${esc(data.botLink)}">فعّل اشتراكك في البوت</a>` : ""}
        </div>
        <ol>
          <li>اضغط «فعّل اشتراكك في البوت»، أو انسخ الكود وأرسله إلى ${bot}.</li>
          <li>أو أرسل الكود مباشرة داخل المجموعة التي اشتركت فيها.</li>
          <li>يتفعّل اشتراكك فوراً وتقدر تكتب في المجموعة بدون حذف لرسائلك.</li>
        </ol>
        <p class="muted">احتفظ بالكود حتى تستخدمه. لأي مشكلة تواصل مع ${supportLink}</p>
      </div>`;
    document.getElementById("copy").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(data.code); toast("تم نسخ الكود ✅"); }
      catch (e) { toast("انسخ الكود يدوياً"); }
    });
    return;
  }

  if (data.status === "not_paid") {
    localStorage.removeItem(PENDING_KEY);
    app.innerHTML = `<div class="card done-card"><div class="result-icon">⚠️</div><h2>لم تكتمل عملية الدفع</h2>
      <p>لم يتم خصم أي مبلغ. يمكنك المحاولة مرة أخرى.</p>
      <div class="row-btns"><a class="btn btn-primary" href="${location.pathname}${groupId ? "?g=" + encodeURIComponent(groupId) : ""}">العودة لصفحة الاشتراك</a></div></div>`;
    return;
  }
  showError(data.status === "amount_mismatch" ? "حدث خطأ في مبلغ العملية" : "تعذر التحقق من الدفع حالياً، إذا تم الخصم أعد فتح هذه الصفحة بعد دقائق");
}

if (params.get("paid") || params.get("id") || params.get("invoice_id")) {
  renderResult();
} else {
  renderPlans();
}
