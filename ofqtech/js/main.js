// بيانات الأعمال — عدّل هنا لإضافة أو تغيير مشروع (type: app | web)
const WORKS = [
  { title: "قدرات تايم", type: "web", img: "assets/qudurattime-mobile.jpg", url: "https://qudurattime.com" },
  { title: "أملاك", type: "web", img: "assets/amlak.png", url: "https://amlak-house.web.app/" },
  { title: "أملاك — التطبيق", type: "app", img: "assets/house-app.png", url: "https://house-48c4f.web.app/" },
];
const TYPE_LABEL = { app: "تطبيق جوال", web: "موقع ومنصة" };

const grid = document.getElementById("worksGrid");
grid.innerHTML = WORKS.map((w) => `
  <article class="work reveal" data-type="${w.type}">
    <a class="work__img" href="${w.url}" target="_blank" rel="noopener"><img src="${w.img}" alt="${w.title}" loading="lazy"></a>
    <div class="work__body">
      <h3>${w.title}</h3>
      <a class="work__link" href="${w.url}" target="_blank" rel="noopener">${TYPE_LABEL[w.type]} <span aria-hidden="true">←</span></a>
    </div>
  </article>`).join("");

// فلترة الأعمال
const filters = document.getElementById("filters");
filters.addEventListener("click", (e) => {
  const f = e.target.dataset.f;
  if (!f) return;
  [...filters.children].forEach((b) => b.classList.toggle("on", b === e.target));
  grid.querySelectorAll(".work").forEach((card, i) => {
    const vis = f === "all" || card.dataset.type === f;
    card.classList.toggle("hide", !vis);
    if (vis) {
      card.classList.remove("in", "done");
      card.style.setProperty("--d", `${i * 0.08}s`);
      requestAnimationFrame(() => requestAnimationFrame(() => show(card)));
    }
  });
});

// قائمة الجوال
const burger = document.getElementById("burger");
const nav = document.getElementById("nav");
const setMenu = (open) => {
  nav.classList.toggle("open", open);
  document.body.classList.toggle("menu", open);
  burger.setAttribute("aria-expanded", open);
};
burger.addEventListener("click", () => setMenu(!nav.classList.contains("open")));
document.getElementById("scrim").addEventListener("click", () => setMenu(false));
nav.addEventListener("click", (e) => { if (e.target.tagName === "A") setMenu(false); });

// ظهور تدريجي متتابع عند التمرير
const show = (el) => {
  el.classList.add("in");
  el.addEventListener("transitionend", () => el.classList.add("done"), { once: true });
};
document.querySelectorAll(".grid, .steps, .vm__item").forEach((group) => {
  group.querySelectorAll(":scope > .reveal, :scope > * > .reveal").forEach((el, i) => el.style.setProperty("--d", `${i * 0.12}s`));
});
const io = "IntersectionObserver" in window
  ? new IntersectionObserver((entries) => entries.forEach((en) => {
      if (en.isIntersecting) { show(en.target); io.unobserve(en.target); }
    }), { threshold: 0.15, rootMargin: "0px 0px -40px 0px" })
  : null;
document.querySelectorAll(".reveal").forEach((el) => (io ? io.observe(el) : el.classList.add("in")));

// تمييز الرابط النشط أثناء التمرير
const links = [...nav.querySelectorAll("a")];
const secs = links.map((a) => document.querySelector(a.getAttribute("href")));
addEventListener("scroll", () => {
  let cur = 0;
  secs.forEach((s, i) => { if (s && s.getBoundingClientRect().top < 140) cur = i; });
  links.forEach((a, i) => a.classList.toggle("active", i === cur));
}, { passive: true });

document.getElementById("year").textContent = new Date().getFullYear();
