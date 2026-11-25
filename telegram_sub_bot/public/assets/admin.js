// لوحة أدمن المنصة: كل أصحاب القروبات، المستحقات، وتسجيل التحويلات
import {
  $, $$, esc, num, sar, fmtDate, fmtDateTime, toDate, isActive, statusBadge, PAID, toast,
  summarize, renderDailyChart, renderPlanBars, ICONS, authErrorMessage, downloadCSV, normDigits,
} from "/assets/common.js";
import {
  CFG, auth, db, configured, onAuthStateChanged, signOut, doc, getDoc, setDoc, updateDoc, addDoc, deleteDoc,
  collection, onSnapshot, serverTimestamp, reload, sendEmailVerification,
} from "/assets/firebase.js";

const PAGES = [
  ["overview", "نظرة عامة", "📊"],
  ["accounts", "الحسابات", "🔐"],
  ["link", "ربط قروب", "🔗"],
  ["owners", "أصحاب القروبات", "👑"],
  ["groups", "كل القروبات", "👥"],
  ["subs", "كل الاشتراكات", "🧾"],
  ["payouts", "التحويلات", "💸"],
];
const state = { user: null, owners: [], groups: [], subs: [], payouts: [], loaded: 0, q: "" };

$$(".logo").forEach((el) => (el.innerHTML = ICONS.cloud));
$$(".logout").forEach((b) => b.addEventListener("click", () => signOut(auth).then(() => location.replace("/"))));
const page = () => (PAGES.some((p) => p[0] === location.hash.slice(1)) ? location.hash.slice(1) : "overview");

function renderNav() {
  const html = PAGES.map(([id, l, i]) => `<a href="#${id}" class="${page() === id ? "active" : ""}"><span>${i}</span>${l}</a>`).join("");
  $("#nav").innerHTML = html;
  $("#mnav").innerHTML = html;
}
window.addEventListener("hashchange", () => { renderNav(); render(); });

const onErr = (err) => { console.error(err); toast(authErrorMessage(err)); };

if (configured) {
  onAuthStateChanged(auth, async (user) => {
    if (!user) return location.replace("/auth.html#login");
    state.user = user;
    $("#meEmail").textContent = user.email;
    let me = await getDoc(doc(db, "owners", user.uid));
    if (me.data()?.role !== "admin") {
      // محاولة تفعيل الأدمن فوراً (للإيميلات الموجودة في ADMIN_EMAILS بعد تأكيدها)
      await reload(user).catch(() => {});
      let claim = {};
      try {
        const res = await fetch(((window.CLOUD_CONFIG || {}).apiBase || "") + "/api/claim-admin", {
          method: "POST", headers: { Authorization: "Bearer " + (await user.getIdToken(true)) },
        });
        claim = await res.json().catch(() => ({}));
        if (res.ok) me = await getDoc(doc(db, "owners", user.uid));
      } catch (e) { /* يعرض الرسالة بالأسفل */ }
      if (me.data()?.role !== "admin") {
        const notVerified = claim.error === "email_not_verified";
        $("#main").innerHTML = notVerified
          ? `<div class="alert alert-warn">لتفعيل لوحة الأدمن أكّد بريدك الإلكتروني أولاً: افتح الرسالة التي وصلتك واضغط رابط التأكيد، ثم حدّث هذه الصفحة.</div>
             <button class="btn btn-primary" id="resend">إعادة إرسال رسالة التأكيد</button> <a class="btn btn-outline" href="/dashboard.html">العودة للوحة التحكم</a>`
          : `<div class="alert alert-error">هذه الصفحة لأدمن المنصة فقط.</div>
             <a class="btn btn-outline" href="/dashboard.html">العودة للوحة التحكم</a>`;
        $("#resend")?.addEventListener("click", () =>
          sendEmailVerification(user).then(() => toast("تم إرسال رسالة التأكيد ✅")).catch(onErr));
        return;
      }
    }
    renderNav();
    const listen = (col, key) => onSnapshot(collection(db, col), (s) => {
      const first = !state[key + "_ok"];
      state[key] = s.docs.map((d) => ({ id: d.id, ...d.data() }));
      state[key + "_ok"] = true;
      if (first) state.loaded += 1;
      render();
    }, onErr);
    listen("owners", "owners");
    listen("groups", "groups");
    listen("subscriptions", "subs");
    listen("payouts", "payouts");
  });
}

function render() {
  if (state.loaded < 4) return;
  // لا نعيد رسم صفحات النماذج أثناء الكتابة فيها
  if ((page() === "accounts" && $("#newUserForm")) || (page() === "link" && $("#linkPanel"))) {
    if (page() === "link") checkLinked();
    return;
  }
  ({ overview, accounts, link, owners, groups, subs, payouts })[page()]();
}

// ---------------------------------------------------------------------------
// الحسابات: الأدمن ينشئ حسابات أصحاب القروبات (اسم مستخدم + كلمة مرور)
// ---------------------------------------------------------------------------
const API = ((window.CLOUD_CONFIG || {}).apiBase || "").replace(/\/$/, "");
const USER_ERRORS = {
  weak_password: "كلمة المرور يجب أن تكون 6 أحرف على الأقل.",
  bad_username: "اسم المستخدم: 3 إلى 30 حرفاً إنجليزياً صغيراً أو أرقاماً (ويسمح بـ . _ -) ويبدأ بحرف أو رقم.",
  bad_name: "اكتب اسم صاحب الحساب.",
  username_taken: "اسم المستخدم مستخدم مسبقاً، اختر اسماً آخر.",
  admin_only: "هذه العملية للأدمن فقط.",
  not_found: "الحساب غير موجود.",
  bad_email: "الإيميل غير صحيح.",
};

async function adminUsers(payload) {
  const res = await fetch(`${API}/api/admin/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + (await state.user.getIdToken()) },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(USER_ERRORS[data.error] || "تعذر تنفيذ العملية، حاول مرة أخرى.");
  return data;
}

const loginName = (o) => o.username || o.email || "";

function accounts() {
  const list = [...state.owners].sort((a, b) => (toDate(b.createdAt) || 0) - (toDate(a.createdAt) || 0));
  $("#main").innerHTML = `
    ${head("الحسابات", "التسجيل مغلق للعامة — أنشئ هنا حساب كل صاحب قروب (اسم مستخدم + كلمة مرور) وأرسلها له.")}
    <div class="two-col">
      <div class="panel"><div class="panel-head"><h2>➕ إنشاء حساب جديد</h2></div>
        <form id="newUserForm" autocomplete="off">
          <div class="field"><label for="nuName">اسم صاحب الحساب</label><input id="nuName" maxlength="80" required /></div>
          <div class="field"><label for="nuUser">اسم المستخدم (للدخول)</label><input id="nuUser" name="cloud-new-login" class="ltr" maxlength="30" placeholder="ahmed" autocomplete="off" autocapitalize="none" spellcheck="false" required /><small>حروف إنجليزية صغيرة وأرقام فقط</small></div>
          <div class="field"><label for="nuPass">كلمة المرور</label><input id="nuPass" name="cloud-new-secret" class="ltr" minlength="6" autocomplete="new-password" autocapitalize="none" spellcheck="false" required /><small>6 أحرف على الأقل — تظهر لك هنا كما هي</small></div>
          <div class="field"><label for="nuPhone">رقم الجوال (اختياري)</label><input id="nuPhone" class="ltr" maxlength="20" placeholder="05xxxxxxxx" /></div>
          <button class="btn btn-primary btn-block" type="submit">إنشاء الحساب</button>
        </form>
        <div id="nuResult"></div>
      </div>
      <div class="panel"><div class="panel-head"><h2>🔑 تغيير كلمة مرور</h2></div>
        <form id="pwForm" autocomplete="off">
          <div class="field"><label for="pwUser">الحساب</label><select id="pwUser" required>
            <option value="">— اختر الحساب —</option>
            ${list.map((o) => `<option value="${esc(o.id)}">${esc(o.name)} — ${esc(loginName(o))}</option>`).join("")}
          </select></div>
          <div class="field"><label for="pwNew">كلمة المرور الجديدة</label><input id="pwNew" name="cloud-reset-secret" class="ltr" minlength="6" autocomplete="new-password" autocapitalize="none" spellcheck="false" required /></div>
          <button class="btn btn-outline btn-block" type="submit">حفظ كلمة المرور</button>
        </form>
        <hr style="margin:18px 0;opacity:.2" />
        <div class="panel-head"><h2>✉️ تغيير الإيميل / اسم المستخدم</h2></div>
        <form id="emForm" autocomplete="off">
          <div class="field"><label for="emUser">الحساب</label><select id="emUser" required>
            <option value="">— اختر الحساب —</option>
            ${list.map((o) => `<option value="${esc(o.id)}">${esc(o.name)} — ${esc(loginName(o))}</option>`).join("")}
          </select></div>
          <div class="field"><label for="emNew">الإيميل أو اسم المستخدم الجديد</label><input id="emNew" name="cloud-new-email" class="ltr" autocomplete="off" autocapitalize="none" spellcheck="false" required /></div>
          <button class="btn btn-outline btn-block" type="submit">حفظ</button>
        </form>
      </div>
    </div>
    <div class="panel"><div class="panel-head"><h2>كل الحسابات (${list.length})</h2></div><div class="table-wrap"><table>
      <thead><tr><th>الاسم</th><th>اسم المستخدم / الإيميل</th><th>الجوال</th><th>النوع</th><th>القروبات</th><th>تاريخ الإنشاء</th></tr></thead>
      <tbody>${list.map((o) => `<tr><td><b>${esc(o.name)}</b></td><td class="ltr">${esc(loginName(o))}</td><td class="ltr">${esc(o.phone || "-")}</td>
        <td>${o.role === "admin" ? '<span class="badge badge-muted">أدمن</span>' : "صاحب قروب"}</td>
        <td>${state.groups.filter((g) => g.ownerUid === o.id).length}</td><td>${fmtDate(o.createdAt)}</td></tr>`).join("")
        || '<tr><td colspan="6" class="empty">لا توجد حسابات</td></tr>'}</tbody></table></div></div>`;

  $("#newUserForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector("button");
    btn.disabled = true;
    const username = normDigits($("#nuUser").value).replace(/\s+/g, "").toLowerCase();
    const password = normDigits($("#nuPass").value);
    try {
      await adminUsers({ action: "create", name: $("#nuName").value.trim(), username, password, phone: $("#nuPhone").value.trim() });
      $("#nuResult").innerHTML = `<div class="alert alert-ok">✅ تم إنشاء الحساب. أرسل له بيانات الدخول:<br/>
        الرابط: <span class="ltr">${esc(location.origin)}/auth.html</span><br/>اسم المستخدم: <b class="ltr">${esc(username)}</b><br/>كلمة المرور: <b class="ltr">${esc(password)}</b></div>`;
      e.target.reset();
      toast("تم إنشاء الحساب ✅");
    } catch (err) {
      $("#nuResult").innerHTML = `<div class="alert alert-error">${esc(err.message)}</div>`;
    }
    btn.disabled = false;
  });
  $("#emForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector("button");
    btn.disabled = true;
    try {
      const self = $("#emUser").value === state.user.uid;
      const r = await adminUsers({ action: "email", uid: $("#emUser").value, login: $("#emNew").value.trim() });
      e.target.reset();
      toast(`تم التغيير ✅ الدخول الآن بـ ${r.email}`);
      if (self) setTimeout(() => signOut(auth).then(() => location.replace("/auth.html")), 1500);
    } catch (err) { toast(err.message); }
    btn.disabled = false;
  });
  $("#pwForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector("button");
    btn.disabled = true;
    try {
      await adminUsers({ action: "password", uid: $("#pwUser").value, password: normDigits($("#pwNew").value) });
      e.target.reset();
      toast("تم تغيير كلمة المرور ✅");
    } catch (err) { toast(err.message); }
    btn.disabled = false;
  });
}

// ---------------------------------------------------------------------------
// ربط قروب (للأدمن فقط): كود ربط باسم صاحب القروب المختار
// ---------------------------------------------------------------------------
const CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const CODE_TTL_MIN = 15;
let pendingLink = null; // { code, ownerUid, createdAt, knownGroups }
let linkTimer;

function newLinkCode() {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return [...bytes].map((b) => CODE_ALPHABET[b % CODE_ALPHABET.length]).join("");
}

function checkLinked() {
  if (!pendingLink) return;
  const fresh = state.groups.find((g) => g.ownerUid === pendingLink.ownerUid && !pendingLink.knownGroups.has(g.id));
  if (fresh) {
    toast(`✅ تم ربط القروب «${fresh.title || ""}» بنجاح`);
    pendingLink = null;
    link();
  }
}

function link() {
  const bot = CFG.botUsername;
  const owners = [...state.owners].sort((a, b) => String(a.name).localeCompare(String(b.name), "ar"));
  const pl = pendingLink;
  const left = pl ? CODE_TTL_MIN * 60 - Math.floor((Date.now() - pl.createdAt) / 1000) : 0;
  if (pl && left <= 0) pendingLink = null;
  const owner = pendingLink && state.owners.find((o) => o.id === pendingLink.ownerUid);

  $("#main").innerHTML = `
    ${head("ربط قروب", "ربط القروبات متاح للأدمن فقط. اختر حساب صاحب القروب ثم اربط القروب بالكود — إحصائيات القروب تظهر في حسابه.")}
    <div class="panel" id="linkPanel">
      <form id="linkForm" class="filters" style="align-items:flex-end">
        <div class="field" style="flex:1;min-width:220px"><label for="linkOwner">حساب صاحب القروب</label><select id="linkOwner" required>
          <option value="">— اختر الحساب —</option>
          ${owners.map((o) => `<option value="${esc(o.id)}" ${pendingLink?.ownerUid === o.id ? "selected" : ""}>${esc(o.name)} — ${esc(loginName(o))}</option>`).join("")}
        </select></div>
        <button class="btn btn-primary" type="submit">🔗 إنشاء كود ربط</button>
      </form>
      ${pendingLink ? `<div class="link-box">
        <div class="panel-head"><h2>كود الربط لحساب «${esc(owner?.name || "")}»</h2><span class="muted" id="countdown"></span></div>
        <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap"><span class="code ltr" id="linkCmd" dir="ltr" title="اضغط للنسخ" style="user-select:all;cursor:pointer">/link ${pendingLink.code}</span>
        <button class="btn btn-outline btn-sm" id="copyCode" type="button">نسخ الأمر</button></div>
        <ol class="link-steps">
          <li><b>الطريقة السريعة:</b> اضغط الزر واختر القروب — سيُضاف البوت مشرفاً ويتم الربط تلقائياً.<br/>
            ${bot ? `<a class="btn btn-primary btn-sm" style="margin-top:8px" target="_blank" rel="noopener" href="https://t.me/${encodeURIComponent(bot)}?startgroup=${pendingLink.code}&admin=delete_messages">➕ أضف البوت إلى القروب</a>` : ""}</li>
          <li><b>أو يدوياً:</b> أضف ${bot ? `<span class="ltr">@${esc(bot)}</span>` : "البوت"} للقروب، واجعله <b>مشرفاً</b> مع صلاحية <b>حذف الرسائل</b>.</li>
          <li>ثم أرسل داخل القروب: <code>/link ${pendingLink.code}</code></li>
          <li>الكود صالح ${CODE_TTL_MIN} دقيقة ولمرة واحدة.</li>
        </ol></div>` : ""}
    </div>`;

  $("#linkForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const ownerUid = $("#linkOwner").value;
    if (!ownerUid) return toast("اختر حساب صاحب القروب");
    for (let i = 0; i < 3; i++) {
      const code = newLinkCode();
      try {
        await setDoc(doc(db, "linkCodes", code), { ownerUid, createdAt: serverTimestamp() });
        pendingLink = { code, ownerUid, createdAt: Date.now(), knownGroups: new Set(state.groups.filter((g) => g.ownerUid === ownerUid).map((g) => g.id)) };
        link();
        return;
      } catch (err) { if (i === 2) onErr(err); }
    }
  });
  const copyCmd = () => navigator.clipboard?.writeText(`/link ${pendingLink.code}`).then(() => toast("تم نسخ الأمر: /link " + pendingLink.code));
  $("#copyCode")?.addEventListener("click", copyCmd);
  $("#linkCmd")?.addEventListener("click", copyCmd);

  clearInterval(linkTimer);
  if (pendingLink) {
    const tick = () => {
      if (!pendingLink || page() !== "link") return clearInterval(linkTimer);
      const s = CODE_TTL_MIN * 60 - Math.floor((Date.now() - pendingLink.createdAt) / 1000);
      if (s <= 0) { pendingLink = null; clearInterval(linkTimer); link(); return; }
      const el = $("#countdown");
      if (el) el.textContent = `ينتهي خلال ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    };
    tick();
    linkTimer = setInterval(tick, 1000);
  }
}

function ownerRows() {
  return state.owners.map((o) => {
    const subs = state.subs.filter((s) => s.ownerUid === o.id);
    const pays = state.payouts.filter((p) => p.ownerUid === o.id);
    const S = summarize(subs, pays);
    return { o, S, groups: state.groups.filter((g) => g.ownerUid === o.id) };
  });
}

const head = (t, s, a = "") => `<div class="page-head"><div><h1>${t}</h1>${s ? `<p>${s}</p>` : ""}</div><div>${a}</div></div>`;

function overview() {
  const S = summarize(state.subs, state.payouts);
  const rows = ownerRows();
  const owed = rows.reduce((a, r) => a + Math.max(0, r.S.balance), 0);
  $("#main").innerHTML = `
    ${head("لوحة الأدمن", "كل المدفوعات تدخل حسابك في ميسر — هنا ترى كم تحوّل لكل صاحب قروب.")}
    <div class="stats">
      <div class="stat hero-stat"><span>المستحق لأصحاب القروبات</span><b>${sar(owed)}</b><small>إجمالي الأرصدة غير المحوّلة</small></div>
      <div class="stat"><span>إجمالي المبيعات</span><b>${sar(S.gross)}</b><small>${num(S.paid.length)} اشتراك مدفوع</small></div>
      <div class="stat"><span>عمولتك</span><b>${sar(S.commission)}</b><small>${CFG.commissionPercent || 0}% من كل اشتراك</small></div>
      <div class="stat"><span>تم تحويله</span><b>${sar(S.paidOut)}</b><small>${num(state.payouts.length)} تحويل</small></div>
      <div class="stat"><span>مشتركين نشطين</span><b>${num(S.activeUsers)}</b></div>
      <div class="stat"><span>أصحاب القروبات</span><b>${num(state.owners.length)}</b></div>
      <div class="stat"><span>القروبات المربوطة</span><b>${num(state.groups.filter((g) => g.active !== false).length)}</b></div>
      <div class="stat"><span>هذا الشهر</span><b>${num(S.monthCount)}</b><small>اشتراك</small></div>
    </div>
    <div class="two-col">
      <div class="panel"><div class="panel-head"><h2>المبيعات اليومية — آخر 30 يوم</h2><span class="muted">ر.س</span></div><div id="chart"></div></div>
      <div class="panel"><div class="panel-head"><h2>حسب الباقة</h2></div><div id="plans"></div></div>
    </div>`;
  renderDailyChart($("#chart"), state.subs, { valueKey: "amount", label: "المبيعات" });
  renderPlanBars($("#plans"), S.byPlan);
}

function owners() {
  const rows = ownerRows().sort((a, b) => b.S.balance - a.S.balance);
  $("#main").innerHTML = `
    ${head("أصحاب القروبات", "الرصيد = صافي أرباحه − ما حوّلته له.", '<button class="btn btn-outline" id="exp">⬇️ تصدير</button>')}
    <div class="panel"><div class="table-wrap"><table>
      <thead><tr><th>صاحب القروب</th><th>التواصل</th><th>الحساب البنكي</th><th>القروبات</th><th>نشط</th><th>المبيعات</th><th>صافي له</th><th>حُوّل</th><th>الرصيد</th><th></th></tr></thead>
      <tbody>${rows.map(({ o, S, groups }) => `<tr>
        <td><b>${esc(o.name)}</b>${o.role === "admin" ? ' <span class="badge badge-muted">أدمن</span>' : ""}<span class="sub ltr">${esc(loginName(o))}</span><span class="sub">منذ ${fmtDate(o.createdAt)}</span></td>
        <td><span class="ltr">${esc(o.phone || "-")}</span>${o.telegramUsername ? `<span class="sub ltr"><a href="https://t.me/${encodeURIComponent(o.telegramUsername)}" target="_blank" rel="noopener">@${esc(o.telegramUsername)}</a></span>` : ""}</td>
        <td>${o.iban ? `${esc(o.accountHolder || "")}<span class="sub">${esc(o.bankName || "")}</span><span class="sub ltr">${esc(o.iban)}</span>` : '<span class="badge badge-warn">غير مضاف</span>'}</td>
        <td>${groups.length}</td>
        <td>${num(S.activeUsers)}</td>
        <td>${sar(S.gross)}</td>
        <td>${sar(S.share)}</td>
        <td>${sar(S.paidOut)}</td>
        <td><b>${sar(S.balance)}</b></td>
        <td><button class="btn btn-primary btn-sm" data-pay="${esc(o.id)}" ${S.balance > 0 ? "" : "disabled"}>تسجيل تحويل</button></td>
      </tr>`).join("") || '<tr><td colspan="10" class="empty">لا يوجد أصحاب قروبات بعد</td></tr>'}</tbody>
    </table></div></div>`;
  $$("[data-pay]").forEach((b) => b.addEventListener("click", () => openPayout(b.dataset.pay)));
  $("#exp").addEventListener("click", () => downloadCSV("cloud-owners.csv", [
    ["الاسم", "الإيميل", "الجوال", "صاحب الحساب", "البنك", "IBAN", "المبيعات", "صافي له", "حُوّل", "الرصيد"],
    ...rows.map(({ o, S }) => [o.name, o.email, o.phone, o.accountHolder, o.bankName, o.iban, S.gross, S.share, S.paidOut, S.balance]),
  ]));
}

let payoutOwner = null;
function openPayout(uid) {
  const r = ownerRows().find((x) => x.o.id === uid);
  payoutOwner = uid;
  $("#poName").textContent = r.o.name;
  $("#poBank").textContent = r.o.iban ? `${r.o.accountHolder || ""} — ${r.o.bankName || ""} — ${r.o.iban}` : "⚠️ لم يضف بياناته البنكية بعد";
  $("#poAmount").value = r.S.balance > 0 ? r.S.balance : "";
  $("#poRef").value = "";
  $("#poNote").value = "";
  $("#payoutModal").classList.remove("hidden");
}
$("#poCancel").addEventListener("click", () => $("#payoutModal").classList.add("hidden"));
$("#payoutForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const amount = Math.round(Number($("#poAmount").value) * 100) / 100;
  if (!(amount > 0)) return toast("اكتب مبلغاً صحيحاً");
  try {
    await addDoc(collection(db, "payouts"), {
      ownerUid: payoutOwner, amount, reference: $("#poRef").value.trim(), note: $("#poNote").value.trim(),
      createdAt: serverTimestamp(), createdBy: state.user.uid,
    });
    $("#payoutModal").classList.add("hidden");
    toast("تم تسجيل التحويل ✅ وسيظهر لصاحب القروب فوراً");
  } catch (err) { onErr(err); }
});

function groups() {
  const ownerName = (uid) => state.owners.find((o) => o.id === uid)?.name || "-";
  const now = new Date();
  $("#main").innerHTML = `
    ${head("كل القروبات", `${state.groups.length} قروب`)}
    <div class="panel"><div class="table-wrap"><table>
      <thead><tr><th>القروب</th><th>صاحبه</th><th>الحالة</th><th>الأعضاء</th><th>مشترك نشط</th><th>رسائل محذوفة</th><th>التذكير</th><th>تاريخ الربط</th><th></th></tr></thead>
      <tbody>${state.groups.map((g) => {
        const active = state.subs.filter((s) => String(s.groupId) === g.id && isActive(s, now)).length;
        const st = g.active === false ? '<span class="badge badge-bad">البوت خارج القروب</span>'
          : g.canDelete === false ? '<span class="badge badge-warn">بدون صلاحية حذف</span>' : '<span class="badge badge-good">يعمل</span>';
        return `<tr><td><b>${esc(g.title)}</b><span class="sub ltr">${esc(g.id)}</span></td><td>${esc(ownerName(g.ownerUid))}</td><td>${st}</td>
          <td>${num(g.memberCount || 0)}</td><td>${num(active)}</td><td>${num(g.blockedMessages || 0)}</td>
          <td><label class="switch" title="رسالة التذكير كل 30 دقيقة"><input type="checkbox" data-remind="${esc(g.id)}" ${g.remindersEnabled !== false ? "checked" : ""}/><span></span></label></td>
          <td>${fmtDate(g.linkedAt)}</td>
          <td><button class="btn btn-danger btn-sm" data-unlink="${esc(g.id)}">فك الربط</button></td></tr>`;
      }).join("") || '<tr><td colspan="9" class="empty">لا توجد قروبات</td></tr>'}</tbody>
    </table></div></div>`;
  $$("[data-remind]").forEach((el) => el.addEventListener("change", async () => {
    try {
      await updateDoc(doc(db, "groups", el.dataset.remind), { remindersEnabled: el.checked });
      toast(el.checked ? "تم تشغيل رسالة التذكير" : "تم إيقاف رسالة التذكير");
    } catch (err) { onErr(err); el.checked = !el.checked; }
  }));
  $$("[data-unlink]").forEach((b) => b.addEventListener("click", () =>
    confirmBox("فك ربط القروب؟", "سيتوقف البوت عن حماية هذا القروب.", () => deleteDoc(doc(db, "groups", b.dataset.unlink)).then(() => toast("تم")).catch(onErr))));
}

function subs() {
  const ownerName = (uid) => state.owners.find((o) => o.id === uid)?.name || "-";
  $("#main").innerHTML = `
    ${head("كل الاشتراكات", "")}
    <div class="panel"><div class="filters"><input id="q" placeholder="🔍 بحث بالاسم أو المعرف أو القروب" value="${esc(state.q)}"/></div><div id="body"></div></div>`;
  const draw = () => {
    const q = state.q.toLowerCase();
    const rows = state.subs
      // «بانتظار الدفع» تظهر فقط خلال مهلة الدفع (30 دقيقة)، بعدها تُعتبر ملغاة
      .filter((s) => PAID.has(s.status) || (s.status === "pending" && Date.now() - (toDate(s.createdAt) || 0) < 30 * 60 * 1000))
      .filter((s) => !q || `${s.telegramName} ${s.telegramUsername} ${s.telegramUserId} ${s.groupTitle}`.toLowerCase().includes(q))
      .sort((a, b) => (toDate(b.paidAt || b.createdAt) || 0) - (toDate(a.paidAt || a.createdAt) || 0));
    $("#body").innerHTML = rows.length ? `<div class="table-wrap"><table>
      <thead><tr><th>العضو</th><th>القروب</th><th>صاحب القروب</th><th>الباقة</th><th>المبلغ</th><th>العمولة</th><th>تاريخ الدفع</th><th>الانتهاء</th><th>الحالة</th><th>رقم الفاتورة</th></tr></thead>
      <tbody>${rows.map((s) => `<tr><td><b>${esc(s.telegramName)}</b><span class="sub ltr">${s.telegramUsername ? "@" + esc(s.telegramUsername) : esc(s.telegramUserId)}</span></td>
        <td>${esc(s.groupTitle)}</td><td>${esc(ownerName(s.ownerUid))}</td><td>${esc(s.planName)}</td><td>${sar(s.amount)}</td><td>${sar(s.commission || 0)}</td>
        <td>${fmtDateTime(s.paidAt)}</td><td>${fmtDate(s.endDate)}</td><td>${statusBadge(s)}</td><td class="ltr"><small>${esc(s.invoiceId || s.id)}</small></td></tr>`).join("")}</tbody></table></div>`
      : '<div class="empty">لا توجد اشتراكات</div>';
  };
  draw();
  $("#q").addEventListener("input", (e) => { state.q = e.target.value; draw(); });
}

function payouts() {
  const ownerName = (uid) => state.owners.find((o) => o.id === uid)?.name || "-";
  const list = [...state.payouts].sort((a, b) => (toDate(b.createdAt) || 0) - (toDate(a.createdAt) || 0));
  $("#main").innerHTML = `
    ${head("التحويلات", "كل التحويلات التي سجّلتها لأصحاب القروبات.")}
    <div class="panel"><div class="table-wrap"><table>
      <thead><tr><th>التاريخ</th><th>صاحب القروب</th><th>المبلغ</th><th>المرجع</th><th>ملاحظة</th><th></th></tr></thead>
      <tbody>${list.map((p) => `<tr><td>${fmtDateTime(p.createdAt)}</td><td>${esc(ownerName(p.ownerUid))}</td><td><b>${sar(p.amount)}</b></td>
        <td class="ltr">${esc(p.reference || "-")}</td><td>${esc(p.note || "")}</td><td><button class="btn btn-danger btn-sm" data-del="${esc(p.id)}">حذف</button></td></tr>`).join("")
        || '<tr><td colspan="6" class="empty">لا توجد تحويلات</td></tr>'}</tbody></table></div></div>`;
  $$("[data-del]").forEach((b) => b.addEventListener("click", () =>
    confirmBox("حذف التحويل؟", "سيُعاد المبلغ إلى رصيد صاحب القروب المستحق.", () => deleteDoc(doc(db, "payouts", b.dataset.del)).then(() => toast("تم الحذف")).catch(onErr))));
}

function confirmBox(title, text, onYes) {
  $("#confirmTitle").textContent = title;
  $("#confirmText").textContent = text;
  $("#confirmModal").classList.remove("hidden");
  const close = () => $("#confirmModal").classList.add("hidden");
  $("#confirmNo").onclick = close;
  $("#confirmYes").onclick = () => { close(); onYes(); };
}
