// بيانات الأعمال — عدّل هنا لإضافة أو تغيير مشروع
const WORKS = [
  {
    title: "قدرات تايم",
    tag: "منصة تعليمية",
    desc: "منصة اختبارات القدرات العامة: اختبارات محاكية وشرح مبسط لكل قسم.",
    img: "assets/qudurattime.png",
    url: "https://qudurattime.com",
  },
  {
    title: "أملاك",
    tag: "موقع عقارات",
    desc: "منصة عقارات سعودية مع بحث متقدم وخريطة وإعلانات وذكاء اصطناعي.",
    img: "assets/amlak.png",
    url: "https://amlak-house.web.app/",
  },
  {
    title: "أملاك — التطبيق",
    tag: "تطبيق جوال",
    desc: "تطبيق عقارات قابل للتثبيت على الجوال: بحث، مفضلة، وتصفح سريع.",
    img: "assets/house-app.png",
    url: "https://house-48c4f.web.app/",
    app: "app/",
  },
];

const grid = document.getElementById("worksGrid");
grid.innerHTML = WORKS.map((w) => `
  <article class="card work reveal">
    <div class="work__img"><img src="${w.img}" alt="${w.title}" loading="lazy"></div>
    <div class="work__body">
      <span class="work__tag">${w.tag}</span>
      <h3>${w.title}</h3>
      <p>${w.desc}</p>
      <div class="work__actions">
        <a class="btn btn--primary" href="${w.url}" target="_blank" rel="noopener">زيارة الموقع</a>
        ${w.app ? `<a class="btn btn--ghost" href="${w.app}">جرّب التطبيق</a>` : ""}
      </div>
    </div>
  </article>`).join("");

// قائمة الجوال
const burger = document.getElementById("burger");
const nav = document.getElementById("nav");
burger.addEventListener("click", () => {
  const open = nav.classList.toggle("open");
  burger.setAttribute("aria-expanded", open);
});
nav.addEventListener("click", (e) => {
  if (e.target.tagName === "A") { nav.classList.remove("open"); burger.setAttribute("aria-expanded", false); }
});

// ظهور تدريجي
const io = "IntersectionObserver" in window
  ? new IntersectionObserver((entries) => entries.forEach((en) => {
      if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
    }), { threshold: 0.12 })
  : null;
document.querySelectorAll(".reveal").forEach((el) => (io ? io.observe(el) : el.classList.add("in")));

document.getElementById("year").textContent = new Date().getFullYear();

// تثبيت التطبيق (PWA)
let deferred;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferred = e;
  document.getElementById("installBox").hidden = false;
});
document.getElementById("installBtn").addEventListener("click", async () => {
  if (!deferred) return;
  deferred.prompt();
  await deferred.userChoice;
  deferred = null;
  document.getElementById("installBox").hidden = true;
});
if ("serviceWorker" in navigator) navigator.serviceWorker.register("app/sw.js", { scope: "app/" }).catch(() => {});
