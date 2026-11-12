(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  /* ---- today's date on the dateline, in the Persian calendar ---- */
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

  /* ---- sticky index: show the small badge once stuck, follow the page being read ---- */
  const nav = $(".sections");
  const sentinel = $(".sections-sentinel");
  if (nav && sentinel && "IntersectionObserver" in window) {
    new IntersectionObserver(([e]) => nav.classList.toggle("is-stuck", !e.isIntersecting && e.boundingClientRect.top < 0))
      .observe(sentinel);
  }
  const list = $(".sections__list");
  const links = $$(".sections__list a");
  const byId = new Map(links.map((a) => [decodeURIComponent(a.hash.slice(1)), a]));
  const pages = $$("main > section[id]");
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
      const line = (nav ? nav.getBoundingClientRect().bottom : 0) + 24;
      let id = null;
      for (const p of pages) {
        if (p.hidden) continue;
        if (p.getBoundingClientRect().top <= line) id = p.id; else break;
      }
      setActive(id);
    });
  }
  addEventListener("scroll", onScroll, { passive: true });
  addEventListener("resize", onScroll);
  onScroll();

  /* ---- search the menu ---- */
  const toggle = $(".sections__search");
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
    $$(".item, .ad-card").forEach((el) => {
      const ok = !q || (el.dataset.q || "").includes(q);
      el.hidden = !ok;
      if (ok && q) hits++;
    });
    $$(".cat").forEach((c) => { c.hidden = !!q && !c.querySelector(".item:not([hidden]), .ad-card:not([hidden])"); });
    pages.forEach((p) => {
      if (p.id === "front") return;
      p.hidden = !!q && !p.querySelector(".cat:not([hidden])");
    });
    if (empty) empty.hidden = !q || hits > 0;
    if (q) {
      // results start right under the sticky index
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
      const top = $("main").getBoundingClientRect().top + scrollY - nav.offsetHeight + 1;
      if (scrollY < top) scrollTo({ top, behavior: "smooth" });
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

  /* ---- فال قهوه ---- */
  const FORTUNES = /*FORTUNES*/[];
  const fBtn = $(".fortune__btn");
  const fText = $(".fortune__text");
  let last = -1;
  if (fBtn && fText && FORTUNES.length) {
    fBtn.addEventListener("click", () => {
      let i;
      do { i = Math.floor(Math.random() * FORTUNES.length); } while (FORTUNES.length > 1 && i === last);
      last = i;
      fText.classList.add("is-turning");
      setTimeout(() => {
        fText.textContent = FORTUNES[i];
        fText.classList.remove("is-turning");
        fBtn.textContent = "یک فالِ دیگر";
      }, 220);
    });
  }
})();
