// بيانات الأعمال — عدّل هنا لإضافة أو تغيير مشروع
const WORKS = [
  {
    title: "قدرات تايم",
    tag: "منصة تعليمية",
    desc: "منصة اختبارات القدرات العامة: اختبارات محاكية وشرح مبسط لكل قسم.",
    img: "assets/qudurattime-mobile.jpg",
    url: "https://qudurattime.com",
    label: "زيارة الموقع",
  },
  {
    title: "أملاك",
    tag: "موقع عقارات",
    desc: "منصة عقارات سعودية مع بحث متقدم وخريطة وإعلانات وذكاء اصطناعي.",
    img: "assets/amlak.png",
    url: "https://amlak-house.web.app/",
    label: "زيارة الموقع",
  },
  {
    title: "أملاك — التطبيق",
    tag: "تطبيق جوال",
    desc: "تطبيق عقارات للجوال: بحث، مفضلة، وتصفح سريع.",
    img: "assets/house-app.png",
    url: "https://house-48c4f.web.app/",
    label: "زيارة التطبيق",
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
      <a class="btn btn--navy btn--sm" href="${w.url}" target="_blank" rel="noopener">${w.label}</a>
    </div>
  </article>`).join("");

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

// ظهور تدريجي
const io = "IntersectionObserver" in window
  ? new IntersectionObserver((entries) => entries.forEach((en) => {
      if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
    }), { threshold: 0.12 })
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
