// أدوات مشتركة لكل صفحات الموقع
export const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const numFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
export const num = (n) => numFmt.format(Number(n) || 0);
export const sar = (n) => `${num(n)} ر.س`;

export const toDate = (ts) => (ts ? (ts.toDate ? ts.toDate() : new Date(ts)) : null);
export const fmtDate = (ts) => {
  const d = toDate(ts);
  return d ? d.toLocaleDateString("en-CA") : "-";
};
export const fmtDateTime = (ts) => {
  const d = toDate(ts);
  return d ? `${d.toLocaleDateString("en-CA")} ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : "-";
};

export const PAID = new Set(["active", "expired"]);

export function isActive(sub, now = new Date()) {
  const end = toDate(sub.endDate);
  return sub.status === "active" && end && end >= now;
}

export function statusBadge(sub) {
  if (isActive(sub)) return '<span class="badge badge-good">نشط</span>';
  if (sub.status === "active" || sub.status === "expired") return '<span class="badge badge-muted">منتهي</span>';
  if (sub.status === "pending") return '<span class="badge badge-warn">بانتظار الدفع</span>';
  return '<span class="badge badge-bad">ملغي</span>';
}

let toastTimer;
export function toast(msg) {
  let el = document.querySelector(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3200);
}

// الأرقام العربية/الفارسية -> إنجليزية (حتى لا تختلف كلمة المرور حسب لوحة المفاتيح)
export const normDigits = (s) => String(s ?? "")
  .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
  .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06F0));

export function authErrorMessage(err) {
  const code = err?.code || "";
  const map = {
    "auth/invalid-email": "صيغة البريد الإلكتروني غير صحيحة.",
    "auth/missing-password": "اكتب كلمة المرور.",
    "auth/weak-password": "كلمة المرور ضعيفة، استخدم 6 أحرف على الأقل.",
    "auth/email-already-in-use": "هذا البريد مسجّل مسبقاً، سجّل الدخول بدلاً من ذلك.",
    "auth/invalid-credential": "اسم المستخدم أو كلمة المرور غير صحيحة.",
    "auth/wrong-password": "اسم المستخدم أو كلمة المرور غير صحيحة.",
    "auth/user-not-found": "لا يوجد حساب بهذا الاسم.",
    "auth/too-many-requests": "محاولات كثيرة، انتظر قليلاً ثم حاول مرة أخرى.",
    "auth/network-request-failed": "تعذر الاتصال، تأكد من الإنترنت.",
    "permission-denied": "ليس لديك صلاحية لتنفيذ هذا الإجراء.",
  };
  return map[code] || "حدث خطأ غير متوقع، حاول مرة أخرى.";
}

// ---------- الإحصائيات ----------
export function summarize(subs, payouts = []) {
  const now = new Date();
  const paid = subs.filter((s) => PAID.has(s.status));
  const active = paid.filter((s) => isActive(s, now));
  const gross = paid.reduce((a, s) => a + (Number(s.amount) || 0), 0);
  const share = paid.reduce((a, s) => a + (Number(s.ownerShare ?? s.amount) || 0), 0);
  const commission = paid.reduce((a, s) => a + (Number(s.commission) || 0), 0);
  const paidOut = payouts.reduce((a, p) => a + (Number(p.amount) || 0), 0);
  const uniqueUsers = new Set(paid.map((s) => s.telegramUserId)).size;
  const activeUsers = new Set(active.map((s) => `${s.telegramUserId}:${s.groupId}`)).size;
  const byPlan = {};
  for (const s of paid) {
    const k = s.planName || s.planKey || "—";
    byPlan[k] ??= { count: 0, amount: 0 };
    byPlan[k].count += 1;
    byPlan[k].amount += Number(s.amount) || 0;
  }
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const thisMonth = paid.filter((s) => (toDate(s.paidAt || s.startDate) || 0) >= monthStart);
  return {
    paid, active, gross, share, commission, paidOut,
    balance: Math.round((share - paidOut) * 100) / 100,
    uniqueUsers, activeUsers, byPlan,
    monthCount: thisMonth.length,
    monthShare: thisMonth.reduce((a, s) => a + (Number(s.ownerShare ?? s.amount) || 0), 0),
    renewals: paid.length - uniqueUsers,
  };
}

// مخطط أعمدة يومي لآخر N يوم (سلسلة واحدة) مع تلميح عند المرور
export function renderDailyChart(container, subs, { days = 30, valueKey = "ownerShare", label = "الإيراد" } = {}) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const buckets = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    buckets.push({ date: d, value: 0, count: 0 });
  }
  const first = buckets[0].date.getTime();
  for (const s of subs) {
    if (!PAID.has(s.status)) continue;
    const d = toDate(s.paidAt || s.startDate);
    if (!d) continue;
    const idx = Math.floor((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() - first) / 86400000);
    if (idx >= 0 && idx < days) {
      buckets[idx].value += Number(s[valueKey] ?? s.amount) || 0;
      buckets[idx].count += 1;
    }
  }

  const W = 720, H = 240, padL = 8, padR = 44, padT = 12, padB = 26;
  const max = Math.max(...buckets.map((b) => b.value), 1);
  const nice = niceMax(max);
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const slot = plotW / days;
  const barW = Math.max(4, slot - 4); // فراغ 2px على كل جانب بين الأعمدة
  const y = (v) => padT + plotH - (v / nice) * plotH;

  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)} اليومي لآخر ${days} يوم">`;
  for (let i = 0; i <= 4; i++) {
    const v = (nice / 4) * i;
    svg += `<line class="${i === 0 ? "base-line" : "grid-line"}" x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/>`;
    svg += `<g class="axis"><text x="${W - padR + 8}" y="${y(v) + 4}" text-anchor="start">${num(v)}</text></g>`;
  }
  buckets.forEach((b, i) => {
    const x = padL + i * slot + (slot - barW) / 2;
    const h = Math.max(0, plotH - (y(b.value) - padT));
    const r = Math.min(4, barW / 2, h);
    const top = padT + plotH - h;
    // عمود بأطراف علوية دائرية 4px وقاعدة مستقيمة على خط الصفر
    const path = h > 0
      ? `M${x},${padT + plotH} V${top + r} Q${x},${top} ${x + r},${top} H${x + barW - r} Q${x + barW},${top} ${x + barW},${top + r} V${padT + plotH} Z`
      : "";
    svg += `<g data-i="${i}"><rect class="bar-hit" x="${padL + i * slot}" y="${padT}" width="${slot}" height="${plotH}"/>${path ? `<path class="bar" d="${path}"/>` : ""}</g>`;
    if (i % 5 === 0 || i === days - 1) {
      svg += `<g class="axis"><text x="${x + barW / 2}" y="${H - 6}" text-anchor="middle">${b.date.getDate()}/${b.date.getMonth() + 1}</text></g>`;
    }
  });
  svg += "</svg>";
  container.innerHTML = `<div class="chart">${svg}<div class="tooltip hidden"></div></div>`;

  const chart = container.querySelector(".chart");
  const tip = chart.querySelector(".tooltip");
  chart.querySelectorAll("g[data-i]").forEach((g) => {
    g.addEventListener("mouseenter", () => {
      const b = buckets[Number(g.dataset.i)];
      tip.innerHTML = `<b>${sar(b.value)}</b>${b.count} اشتراك · ${b.date.toLocaleDateString("en-CA")}`;
      const box = g.querySelector(".bar-hit").getBoundingClientRect();
      const cbox = chart.getBoundingClientRect();
      tip.style.left = `${box.left - cbox.left + box.width / 2}px`;
      tip.style.top = `${Math.max(30, (g.querySelector(".bar")?.getBoundingClientRect().top ?? box.bottom) - cbox.top)}px`;
      tip.classList.remove("hidden");
    });
    g.addEventListener("mouseleave", () => tip.classList.add("hidden"));
  });
}

function niceMax(v) {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  const m = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return m * p;
}

export function renderPlanBars(container, byPlan) {
  const entries = Object.entries(byPlan).sort((a, b) => b[1].count - a[1].count);
  if (!entries.length) {
    container.innerHTML = '<div class="empty">لا توجد اشتراكات بعد</div>';
    return;
  }
  const max = Math.max(...entries.map(([, v]) => v.count));
  container.innerHTML = `<div class="hbars">${entries
    .map(
      ([name, v]) => `<div><div class="hbar-label"><span>${esc(name)}</span><span><b>${v.count}</b> <span class="muted">· ${sar(v.amount)}</span></span></div>
      <div class="hbar-track"><div class="hbar-fill" style="width:${(v.count / max) * 100}%"></div></div></div>`
    )
    .join("")}</div>`;
}

export function downloadCSV(filename, rows) {
  const csv = rows.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export const ICONS = {
  cloud: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H8a5 5 0 1 1 1.6-9.74A6 6 0 0 1 21 11.5 3.75 3.75 0 0 1 17.5 19z"/></svg>',
};
