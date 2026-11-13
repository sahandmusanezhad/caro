(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  /* ---- today's date, Persian calendar ---- */
  const today = $("[data-today]");
  if (today) {
    try {
      const parts = new Intl.DateTimeFormat("fa-IR-u-ca-persian-nu-arabext", {
        weekday: "long", day: "numeric", month: "long", year: "numeric",
      }).formatToParts(new Date());
      const get = (t) => (parts.find((p) => p.type === t) || {}).value || "";
      const text = [get("weekday"), get("day"), get("month"), get("year")].filter(Boolean).join(" ");
      if (text) today.textContent = text;
    } catch (e) { /* keep the printed fallback */ }
  }

  /* ---- sticky index: small badge once stuck, follow the section being read ---- */
  const nav = $(".nav");
  const sentinel = $(".nav-sentinel");
  if (nav && sentinel && "IntersectionObserver" in window) {
    new IntersectionObserver(([e]) => nav.classList.toggle("is-stuck", !e.isIntersecting && e.boundingClientRect.top < 0))
      .observe(sentinel);
  }
  const list = $(".nav__list");
  const links = $$(".nav__list a");
  const byId = new Map(links.map((a) => [decodeURIComponent(a.hash.slice(1)), a]));
  const targets = links.map((a) => document.getElementById(decodeURIComponent(a.hash.slice(1)))).filter(Boolean)
    .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  let current = null;

  function centreLink(a) {
    if (!list || !a) return;
    const lr = list.getBoundingClientRect();
    const ar = a.getBoundingClientRect();
    const delta = (ar.left + ar.width / 2) - (lr.left + lr.width / 2);
    if (Math.abs(delta) > 4) list.scrollBy({ left: delta, behavior: "smooth" });
  }
  function setActive(id) {
    if (id === current) return;
    current = id;
    links.forEach((a) => a.removeAttribute("aria-current"));
    const a = byId.get(id);
    if (a) { a.setAttribute("aria-current", "true"); centreLink(a); }
  }
  let ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      const line = (nav ? nav.getBoundingClientRect().bottom : 0) + 30;
      let id = null;
      for (const t of targets) {
        if (t.offsetParent === null) continue;
        if (t.getBoundingClientRect().top <= line) id = t.id;
      }
      setActive(id);
    });
  }
  addEventListener("scroll", onScroll, { passive: true });
  addEventListener("resize", onScroll);
  onScroll();

  /* ---- search ---- */
  const toggle = $(".nav__search");
  const box = $(".search");
  const input = box && $("input", box);
  const empty = $(".search-empty");
  const norm = (s) => s
    .replace(/[يى]/g, "ی").replace(/ك/g, "ک")
    .replace(/[‌ًٔ-ٟ]/g, "")
    .replace(/[()/·،]/g, " ")
    .replace(/\s+/g, " ").trim().toLowerCase();

  function runSearch() {
    const q = norm(input.value);
    document.body.classList.toggle("is-searching", !!q);
    let hits = 0;
    $$(".item, .ht__item").forEach((el) => {
      const ok = !q || (el.dataset.q || "").includes(q);
      el.hidden = !ok;
      if (ok && q) hits++;
    });
    $$(".cat").forEach((c) => { c.hidden = !!q && !c.querySelector(".item:not([hidden]), .ht__item:not([hidden])"); });
    $$("main .sec").forEach((s) => { s.hidden = !!q && !s.querySelector(".cat:not([hidden])"); });
    if (empty) empty.hidden = !q || hits > 0;
    if (q) {
      const top = $("main").getBoundingClientRect().top + scrollY - nav.offsetHeight + 1;
      if (Math.abs(scrollY - top) > 2) scrollTo({ top, behavior: "auto" });
    }
    onScroll();
  }
  function openSearch(open) {
    if (!box) return;
    box.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (open) {
      input.focus({ preventScroll: true });
    } else {
      input.value = "";
      runSearch();
    }
  }
  if (toggle && input) {
    toggle.addEventListener("click", () => openSearch(box.hidden));
    input.addEventListener("input", runSearch);
    input.addEventListener("keydown", (e) => { if (e.key === "Escape") { openSearch(false); toggle.focus(); } });
  }
})();
