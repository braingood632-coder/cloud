// لوحة تحكم صاحب القروب
import {
  $, $$, esc, num, sar, fmtDate, fmtDateTime, toDate, isActive, statusBadge, PAID, toast,
  summarize, renderDailyChart, renderPlanBars, downloadCSV, ICONS, authErrorMessage,
} from "/assets/common.js";
import {
  CFG, auth, db, configured, onAuthStateChanged, signOut, doc, getDoc, setDoc, updateDoc, deleteDoc,
  collection, query, where, onSnapshot, serverTimestamp,
} from "/assets/firebase.js";

const PAGES = [
  ["overview", "نظرة عامة", "📊"],
  ["groups", "القروبات", "👥"],
  ["subscribers", "المشتركين", "🧾"],
  ["payouts", "المستحقات", "💸"],
  ["account", "حسابي", "⚙️"],
];

const state = {
  user: null, owner: null, groups: [], subs: [], payouts: [],
  loaded: { groups: false, subs: false, payouts: false },
  pendingCode: null, // { code, createdAt }
  filters: { q: "", group: "", status: "paid", plan: "" },
};

$$(".logo").forEach((el) => (el.innerHTML = ICONS.cloud));
$$(".logout").forEach((b) => b.addEventListener("click", () => signOut(auth).then(() => location.replace("/"))));

const page = () => {
  const h = location.hash.replace("#", "");
  return PAGES.some((p) => p[0] === h) ? h : "overview";
};

function renderNav() {
  const items = [...PAGES];
  const html = items
    .map(([id, label, icon]) => `<a href="#${id}" class="${page() === id ? "active" : ""}"><span>${icon}</span>${label}</a>`)
    .join("");
  $("#nav").innerHTML = html;
  $("#mnav").innerHTML = html;
}

window.addEventListener("hashchange", () => { renderNav(); render(); window.scrollTo(0, 0); });

// ---------------------------------------------------------------------------
// تحميل البيانات (تحديث لحظي)
// ---------------------------------------------------------------------------
if (!configured) {
  $("#main").innerHTML = '<div class="alert alert-error">لم يتم ضبط إعدادات Firebase في السيرفر بعد.</div>';
} else {
  onAuthStateChanged(auth, async (user) => {
    if (!user) return location.replace("/auth.html#login");
    state.user = user;
    $("#meEmail").textContent = user.email;

    // الحسابات ينشئها الأدمن فقط؛ حساب بدون ملف = غير مفعّل
    const ownerRef = doc(db, "owners", user.uid);
    const snap = await getDoc(ownerRef).catch(() => null);
    if (!snap || !snap.exists()) {
      $("#main").innerHTML = '<div class="alert alert-error">هذا الحساب غير مفعّل. تواصل مع إدارة المنصة.</div>';
      return;
    }
    // الأدمن يدخل مباشرة على لوحة الأدمن
    if (snap.data()?.role === "admin") return location.replace("/admin.html");

    onSnapshot(ownerRef, (s) => {
      state.owner = s.data();
      $("#meName").textContent = state.owner?.name || "";
      renderNav();
      if (page() !== "account" || !$("#accountForm")) render();
    });

    const mine = (col) => query(collection(db, col), where("ownerUid", "==", user.uid));
    onSnapshot(mine("groups"), (s) => {
      const before = new Set(state.groups.map((g) => g.id));
      state.groups = s.docs.map((d) => ({ id: d.id, ...d.data() }));
      state.loaded.groups = true;
      if (state.pendingCode && state.groups.some((g) => !before.has(g.id)) && before.size + 1 <= state.groups.length) {
        const g = state.groups.find((x) => !before.has(x.id));
        state.pendingCode = null;
        toast(`✅ تم ربط القروب «${g?.title || ""}» بنجاح`);
      }
      render();
    }, onErr);
    onSnapshot(mine("subscriptions"), (s) => {
      state.subs = s.docs.map((d) => ({ id: d.id, ...d.data() }));
      state.loaded.subs = true;
      render();
    }, onErr);
    onSnapshot(mine("payouts"), (s) => {
      state.payouts = s.docs.map((d) => ({ id: d.id, ...d.data() }));
      state.loaded.payouts = true;
      render();
    }, onErr);
  });
}

function onErr(err) {
  console.error(err);
  toast(authErrorMessage(err));
}

// ---------------------------------------------------------------------------
// العرض
// ---------------------------------------------------------------------------
function render() {
  if (!state.owner || !state.loaded.groups || !state.loaded.subs || !state.loaded.payouts) return;
  const views = { overview, groups, subscribers, payouts, account };
  // لا نعيد رسم نموذج الحساب أثناء الكتابة فيه
  if (page() === "account" && $("#accountForm")) return;
  views[page()]();
}

function head(title, sub, actions = "") {
  return `<div class="page-head"><div><h1>${title}</h1>${sub ? `<p>${sub}</p>` : ""}</div><div>${actions}</div></div>`;
}

function groupStats() {
  const now = new Date();
  const map = {};
  for (const g of state.groups) map[g.id] = { active: 0, total: 0, revenue: 0 };
  for (const s of state.subs) {
    const k = String(s.groupId);
    if (!map[k] || !PAID.has(s.status)) continue;
    map[k].total += 1;
    map[k].revenue += Number(s.ownerShare ?? s.amount) || 0;
    if (isActive(s, now)) map[k].active += 1;
  }
  return map;
}

function overview() {
  const S = summarize(state.subs, state.payouts);
  const members = state.groups.reduce((a, g) => a + (g.memberCount || 0), 0);
  const blocked = state.groups.reduce((a, g) => a + (g.blockedMessages || 0), 0);
  const welcome = new URLSearchParams(location.search).has("welcome") && !state.groups.length;
  const recent = [...S.paid].sort((a, b) => (toDate(b.paidAt) || 0) - (toDate(a.paidAt) || 0)).slice(0, 6);

  $("#main").innerHTML = `
    ${head(`أهلاً ${esc(state.owner.name)} 👋`, "ملخص قروباتك ومشتركيك وأرباحك — يتحدث تلقائياً لحظة بلحظة.", `<a href="#groups" class="btn btn-primary">+ ربط قروب جديد</a>`)}
    ${!state.owner.iban ? `<div class="alert alert-warn">أضف بياناتك البنكية (الآيبان) من <a href="#account"><b>صفحة حسابي</b></a> حتى نستطيع تحويل مستحقاتك.</div>` : ""}
    <div class="stats">
      <div class="stat hero-stat"><span>الرصيد المستحق لك</span><b>${sar(S.balance)}</b><small>بانتظار التحويل</small></div>
      <div class="stat"><span>المشتركين النشطين الآن</span><b>${num(S.activeUsers)}</b><small>من أصل ${num(S.uniqueUsers)} عضو اشترك</small></div>
      <div class="stat"><span>إجمالي الاشتراكات</span><b>${num(S.paid.length)}</b><small>منها ${num(S.renewals)} تجديد</small></div>
      <div class="stat"><span>صافي أرباحك</span><b>${sar(S.share)}</b><small>${S.commission > 0 ? `بعد عمولة ${sar(S.commission)}` : "إجمالي المبيعات " + sar(S.gross)}</small></div>
      <div class="stat"><span>هذا الشهر</span><b>${sar(S.monthShare)}</b><small>${num(S.monthCount)} اشتراك</small></div>
      <div class="stat"><span>تم تحويله لك</span><b>${sar(S.paidOut)}</b><small>${num(state.payouts.length)} تحويل</small></div>
      <div class="stat"><span>القروبات المربوطة</span><b>${num(state.groups.filter((g) => g.active !== false).length)}</b><small>${num(members)} عضو إجمالاً</small></div>
      <div class="stat"><span>رسائل محذوفة</span><b>${num(blocked)}</b><small>لأعضاء غير مشتركين</small></div>
    </div>
    <div class="two-col">
      <div class="panel"><div class="panel-head"><h2>أرباحك اليومية — آخر 30 يوم</h2><span class="muted">ر.س</span></div><div id="dailyChart"></div></div>
      <div class="panel"><div class="panel-head"><h2>الاشتراكات حسب الباقة</h2></div><div id="planBars"></div></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>آخر الاشتراكات</h2><a href="#subscribers" class="btn btn-outline btn-sm">عرض الكل</a></div>
      ${recent.length ? subsTable(recent, false) : `<div class="empty">لا توجد اشتراكات بعد. ${state.groups.length ? "بمجرد أن يشترك أحد أعضاء قروبك سيظهر هنا فوراً." : '<a href="#groups">اربط قروبك</a> لتبدأ.'}</div>`}
    </div>`;
  renderDailyChart($("#dailyChart"), state.subs, { label: "أرباحك" });
  renderPlanBars($("#planBars"), S.byPlan);
}

function subsTable(rows, withGroup = true) {
  return `<div class="table-wrap"><table>
    <thead><tr><th>العضو</th>${withGroup ? "<th>القروب</th>" : ""}<th>الباقة</th><th>المبلغ</th><th>حصتك</th><th>البداية</th><th>الانتهاء</th><th>الحالة</th></tr></thead>
    <tbody>${rows.map((s) => `<tr>
      <td><b>${esc(s.telegramName || "—")}</b><span class="sub ltr">${s.telegramUsername ? "@" + esc(s.telegramUsername) : "ID " + esc(s.telegramUserId)}</span></td>
      ${withGroup ? `<td>${esc(groupTitle(s))}</td>` : ""}
      <td>${esc(s.planName || "")}</td>
      <td>${sar(s.amount)}</td>
      <td>${sar(s.ownerShare ?? s.amount)}</td>
      <td>${fmtDate(s.startDate)}</td>
      <td>${fmtDate(s.endDate)}</td>
      <td>${statusBadge(s)}</td></tr>`).join("")}</tbody></table></div>`;
}

function groupTitle(s) {
  return state.groups.find((g) => g.id === String(s.groupId))?.title || s.groupTitle || "";
}

// ---------------------------------------------------------------------------
// القروبات + الربط
// ---------------------------------------------------------------------------
function groups() {
  const stats = groupStats();

  // ربط القروبات صار من لوحة الأدمن فقط؛ صاحب القروب يشاهد الإحصائيات
  const linkBox = `<div class="link-box center"><p>ربط القروبات يتم عن طريق إدارة المنصة. لربط قروب جديد تواصل مع الدعم الفني${
    CFG.supportUsername ? ` <a class="ltr" href="https://t.me/${encodeURIComponent(CFG.supportUsername)}" target="_blank" rel="noopener">@${esc(CFG.supportUsername)}</a>` : ""}.</p></div>`;
  const rows = state.groups
    .sort((a, b) => (toDate(b.linkedAt) || 0) - (toDate(a.linkedAt) || 0))
    .map((g) => {
      const st = stats[g.id] || { active: 0, total: 0, revenue: 0 };
      let botStatus = '<span class="badge badge-good">يعمل</span>';
      if (g.active === false) botStatus = '<span class="badge badge-bad">البوت خارج القروب</span>';
      else if (g.botIsAdmin === false) botStatus = '<span class="badge badge-bad">البوت ليس مشرفاً</span>';
      else if (g.canDelete === false) botStatus = '<span class="badge badge-warn">بدون صلاحية الحذف</span>';
      return `<tr>
        <td><b>${esc(g.title || "قروب")}</b><span class="sub ltr">${esc(g.id)}</span></td>
        <td>${botStatus}</td>
        <td>${num(g.memberCount || 0)}</td>
        <td><b>${num(st.active)}</b></td>
        <td>${num(st.total)}</td>
        <td>${sar(st.revenue)}</td>
        <td>${num(g.blockedMessages || 0)}</td>
        <td>${g.remindersEnabled !== false ? "مفعّل" : "متوقف"}</td>
        <td>${fmtDate(g.linkedAt)}</td>
      </tr>`;
    }).join("");

  $("#main").innerHTML = `
    ${head("القروبات", "قروباتك المربوطة بالبوت وحالة كل قروب.")}
    <div class="panel">${linkBox}</div>
    <div class="panel">
      <div class="panel-head"><h2>قروباتي (${state.groups.length})</h2></div>
      ${state.groups.length ? `<div class="table-wrap"><table><thead><tr>
        <th>القروب</th><th>حالة البوت</th><th>الأعضاء</th><th>مشترك نشط</th><th>إجمالي الاشتراكات</th><th>أرباحك</th><th>رسائل محذوفة</th><th>التذكير</th><th>تاريخ الربط</th>
      </tr></thead><tbody>${rows}</tbody></table></div>` : '<div class="empty">لا توجد قروبات مربوطة بحسابك بعد.</div>'}
    </div>`;

}

// ---------------------------------------------------------------------------
// المشتركين
// ---------------------------------------------------------------------------
function filteredSubs() {
  const f = state.filters;
  const q = f.q.trim().toLowerCase();
  return state.subs
    .filter((s) => {
      if (f.group && String(s.groupId) !== f.group) return false;
      if (f.plan && s.planKey !== f.plan) return false;
      if (f.status === "paid" && !PAID.has(s.status)) return false;
      if (f.status === "active" && !isActive(s)) return false;
      if (f.status === "expired" && !(PAID.has(s.status) && !isActive(s))) return false;
      if (f.status === "pending" && s.status !== "pending") return false;
      if (q && !`${s.telegramName} ${s.telegramUsername} ${s.telegramUserId}`.toLowerCase().includes(q)) return false;
      return true;
    })
    .sort((a, b) => (toDate(b.paidAt || b.createdAt) || 0) - (toDate(a.paidAt || a.createdAt) || 0));
}

function subscribers() {
  const f = state.filters;
  const plans = Object.entries(CFG.plans || {});
  $("#main").innerHTML = `
    ${head("المشتركين", "كل من اشترك في قروباتك ونوع اشتراكه وتاريخ انتهائه.", `<button class="btn btn-outline" id="exportCsv">⬇️ تصدير Excel</button>`)}
    <div class="panel">
      <div class="filters">
        <input id="fQ" placeholder="🔍 بحث بالاسم أو المعرف" value="${esc(f.q)}"/>
        <select id="fGroup"><option value="">كل القروبات</option>${state.groups.map((g) => `<option value="${esc(g.id)}" ${f.group === g.id ? "selected" : ""}>${esc(g.title)}</option>`).join("")}</select>
        <select id="fStatus">
          ${[["paid", "كل المدفوعة"], ["active", "النشطة فقط"], ["expired", "المنتهية"], ["pending", "بانتظار الدفع"], ["all", "الكل"]]
            .map(([v, l]) => `<option value="${v}" ${f.status === v ? "selected" : ""}>${l}</option>`).join("")}
        </select>
        <select id="fPlan"><option value="">كل الباقات</option>${plans.map(([k, p]) => `<option value="${k}" ${f.plan === k ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
      </div>
      <p class="muted" id="subsCount" style="margin-bottom:10px"></p>
      <div id="subsBody"></div>
    </div>`;

  const draw = () => {
    const rows = filteredSubs();
    const total = rows.filter((s) => PAID.has(s.status)).reduce((a, s) => a + (Number(s.ownerShare ?? s.amount) || 0), 0);
    $("#subsCount").textContent = `${rows.length} نتيجة · حصتك منها ${sar(total)}`;
    $("#subsBody").innerHTML = rows.length ? subsTable(rows) : '<div class="empty">لا توجد نتائج</div>';
  };
  draw();
  $("#fQ").addEventListener("input", (e) => { f.q = e.target.value; draw(); });
  $("#fGroup").addEventListener("change", (e) => { f.group = e.target.value; draw(); });
  $("#fStatus").addEventListener("change", (e) => { f.status = e.target.value; draw(); });
  $("#fPlan").addEventListener("change", (e) => { f.plan = e.target.value; draw(); });
  $("#exportCsv").addEventListener("click", () => {
    const rows = filteredSubs().map((s) => [
      s.telegramName, s.telegramUsername ? "@" + s.telegramUsername : "", s.telegramUserId, groupTitle(s), s.planName,
      s.amount, s.ownerShare ?? s.amount, fmtDate(s.startDate), fmtDate(s.endDate),
      isActive(s) ? "نشط" : PAID.has(s.status) ? "منتهي" : s.status === "pending" ? "بانتظار الدفع" : "ملغي",
    ]);
    downloadCSV("cloud-subscribers.csv", [["الاسم", "المعرف", "Telegram ID", "القروب", "الباقة", "المبلغ", "حصتك", "البداية", "الانتهاء", "الحالة"], ...rows]);
  });
}

// ---------------------------------------------------------------------------
// المستحقات
// ---------------------------------------------------------------------------
function payouts() {
  const S = summarize(state.subs, state.payouts);
  const list = [...state.payouts].sort((a, b) => (toDate(b.createdAt) || 0) - (toDate(a.createdAt) || 0));
  $("#main").innerHTML = `
    ${head("المستحقات والتحويلات", "المبالغ تُحصَّل عبر ميسر لحساب المنصة ثم تُحوَّل لحسابك البنكي.")}
    <div class="stats">
      <div class="stat"><span>إجمالي مبيعات قروباتك</span><b>${sar(S.gross)}</b></div>
      ${S.commission > 0 ? `<div class="stat"><span>عمولة المنصة (${CFG.commissionPercent}%)</span><b>${sar(S.commission)}</b></div>` : ""}
      <div class="stat"><span>صافي أرباحك</span><b>${sar(S.share)}</b></div>
      <div class="stat"><span>تم تحويله لك</span><b>${sar(S.paidOut)}</b></div>
      <div class="stat hero-stat"><span>الرصيد المستحق</span><b>${sar(S.balance)}</b></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>حساب التحويل</h2><a href="#account" class="btn btn-outline btn-sm">تعديل</a></div>
      ${state.owner.iban
        ? `<p>${esc(state.owner.accountHolder || state.owner.name)} — ${esc(state.owner.bankName || "")}<br/><span class="ltr">${esc(state.owner.iban)}</span></p>`
        : '<div class="alert alert-warn" style="margin:0">لم تضف بياناتك البنكية بعد. أضفها من صفحة حسابي حتى نستطيع التحويل لك.</div>'}
    </div>
    <div class="panel">
      <div class="panel-head"><h2>سجل التحويلات</h2></div>
      ${list.length ? `<div class="table-wrap"><table><thead><tr><th>التاريخ</th><th>المبلغ</th><th>رقم المرجع</th><th>ملاحظة</th></tr></thead><tbody>
        ${list.map((p) => `<tr><td>${fmtDateTime(p.createdAt)}</td><td><b>${sar(p.amount)}</b></td><td class="ltr">${esc(p.reference || "-")}</td><td>${esc(p.note || "")}</td></tr>`).join("")}
      </tbody></table></div>` : '<div class="empty">لا توجد تحويلات بعد</div>'}
    </div>`;
}

// ---------------------------------------------------------------------------
// حسابي
// ---------------------------------------------------------------------------
function account() {
  const o = state.owner;
  $("#main").innerHTML = `
    ${head("حسابي", "بياناتك الشخصية وبيانات التحويل البنكي.")}
    <form class="panel" id="accountForm" style="max-width:640px">
      <div class="field"><label>البريد الإلكتروني</label><input value="${esc(o.email)}" disabled class="ltr"/></div>
      <div class="field"><label for="aName">الاسم الكامل</label><input id="aName" value="${esc(o.name)}" maxlength="80" required/></div>
      <div class="field"><label for="aPhone">رقم الجوال</label><input id="aPhone" value="${esc(o.phone || "")}" maxlength="20" class="ltr"/></div>
      <div class="field"><label for="aTg">معرّف تليجرام</label><input id="aTg" value="${esc(o.telegramUsername || "")}" maxlength="40" class="ltr" placeholder="username"/></div>
      <h3 style="margin:26px 0 14px">🏦 بيانات التحويل البنكي</h3>
      <div class="field"><label for="aHolder">اسم صاحب الحساب</label><input id="aHolder" value="${esc(o.accountHolder || "")}" maxlength="80"/></div>
      <div class="field"><label for="aBank">اسم البنك</label><input id="aBank" value="${esc(o.bankName || "")}" maxlength="60"/></div>
      <div class="field"><label for="aIban">رقم الآيبان (IBAN)</label><input id="aIban" value="${esc(o.iban || "")}" maxlength="34" class="ltr" placeholder="SA0000000000000000000000"/><small>يبدأ بـ SA ويتكون من 24 خانة</small></div>
      <div id="accMsg"></div>
      <button class="btn btn-primary" type="submit">حفظ التغييرات</button>
    </form>`;

  $("#accountForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const iban = $("#aIban").value.replace(/\s+/g, "").toUpperCase();
    const name = $("#aName").value.trim();
    const showErr = (t) => ($("#accMsg").innerHTML = `<div class="alert alert-error">${esc(t)}</div>`);
    if (name.length < 2) return showErr("اكتب اسمك الكامل.");
    if (iban && !/^SA\d{22}$/.test(iban)) return showErr("رقم الآيبان غير صحيح: يجب أن يبدأ بـ SA ويليه 22 رقماً.");
    try {
      await updateDoc(doc(db, "owners", state.user.uid), {
        name,
        phone: $("#aPhone").value.trim(),
        telegramUsername: $("#aTg").value.trim().replace(/^@/, ""),
        accountHolder: $("#aHolder").value.trim(),
        bankName: $("#aBank").value.trim(),
        iban,
        updatedAt: serverTimestamp(),
      });
      $("#accMsg").innerHTML = "";
      toast("تم حفظ بياناتك ✅");
    } catch (err) { onErr(err); }
  });
}

// ---------------------------------------------------------------------------
function confirmBox(title, text, onYes) {
  $("#confirmTitle").textContent = title;
  $("#confirmText").textContent = text;
  $("#confirmModal").classList.remove("hidden");
  const close = () => $("#confirmModal").classList.add("hidden");
  $("#confirmNo").onclick = close;
  $("#confirmYes").onclick = () => { close(); onYes(); };
}
