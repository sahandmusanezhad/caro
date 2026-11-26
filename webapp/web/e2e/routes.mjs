// The site's key routes in a browser (docs/REARCHITECTURE.md, phase 5):
// every page CARO links to, at a desk and on a phone, in the light scheme
// and the dark, against the site and the API running side by side.
//
//   CARO_SITE=http://127.0.0.1:3000 node e2e/routes.mjs
//
// For each page and each of the four views it asks what a person would see
// go wrong, and what the suites cannot see without a browser:
//
//   the page answers 200, right to left and in Persian, with one heading
//   nothing it draws is wider than the screen
//   nothing is asked of another origin -- no font, no script, no tracker --
//     where the build drew no Turnstile
//   no error is thrown, none is printed to the console, and nothing of ours
//     answers 400 or more -- but the 401 that says nobody is logged in
//   nothing in what the server sends waits on a module straight under an
//     HTML element, which made React redraw whole pages at random (React's
//     error 418)
//
// and, once each: the dark scheme is another ground than the light; the
// panels of the public pages and of the operator's and the seller's are the
// same panel; a search for «سمند زیر ۲ میلیارد» shows its listings; a
// model's page draws its history. It exits 1 and names every failure.
//
// Where the API runs a seller store with the fake SMS, its code echoed into
// CARO_API_LOG, and CARO_E2E_ADMIN_TOKEN names the operator's token, it also
// walks the seller listings from end to end, as PHASE2_SETUP asks the owner
// to on staging: a code that arrives and logs in, a car posted, approved in
// /admin, on /listings, and its number shown. CI runs it on the tree (the
// e2e job) and on the two images before they are pushed (the images
// workflow), where the log is a container's, written a moment after the
// answer: the code is waited for.
// Playwright is installed for this check alone (CI's e2e job), never into
// the site's dependencies.
import { readFileSync } from 'node:fs';
import { chromium } from 'playwright';

const SITE = (process.env.CARO_SITE || 'http://127.0.0.1:3000').replace(/\/$/, '');
const ORIGIN = new URL(SITE).origin;
const Q = 'سمند زیر ۲ میلیارد';
// The filter page, bare and with fields set, and the search with the panel
// set beside the sentence (the owner's choice of 2026-11-25).
const FILTERED = 'make=IKCO&year_min=1398&year_max=1404&price_max=4000000000&sort=market&k=12';
const ROUTES = [
  '/', `/search?q=${encodeURIComponent(Q)}`, `/search?q=${encodeURIComponent(Q)}&${FILTERED}`,
  '/filter', `/filter?${FILTERED}`, '/models', '/model/IKCO/Samand', '/compare', '/saved',
  '/how-it-works', '/before-buying', '/about', '/contact', '/login', '/admin',
];
const VIEWS = [
  { name: 'desk, light', viewport: { width: 1280, height: 900 }, colorScheme: 'light' },
  { name: 'desk, dark', viewport: { width: 1280, height: 900 }, colorScheme: 'dark' },
  { name: 'phone, light', viewport: { width: 360, height: 740 }, colorScheme: 'light', isMobile: true, hasTouch: true },
  { name: 'phone, dark', viewport: { width: 360, height: 740 }, colorScheme: 'dark', isMobile: true, hasTouch: true },
];

const failures = [];
const fail = (where, what) => failures.push(`${where}: ${what}`);

/* What the server sends, read for what made React redraw whole pages at
   random (React's error 418, about once in some hundreds of views). The
   data a page hydrates from describes its elements, and an element whose
   props name a client module waits until that module's script has run: the
   router element that carries every page names the error page's
   (app/error.tsx). Where such an element sits straight under an HTML
   element (<main>, <div>), or a lazy node there names a row that is one,
   React waits under that element, and the React that Next 15.5 bundles
   replays the wait by claiming the element's server node again from inside
   it: error 418, and the whole page drawn again. The layout holds the page
   in a fragment, which claims no node (app/layout.tsx). This reads the
   cause on every page; the walk itself meets it only by chance. */
function waitsUnderAnElement(html) {
  let data = '';
  for (const [, push] of html.matchAll(/self\.__next_f\.push\((\[[\s\S]*?\])\)<\/script>/g)) {
    const [kind, text] = JSON.parse(push);
    if (kind === 1) data += text;
  }
  const rows = new Map();
  for (const line of data.split('\n')) {
    const m = line.match(/^([0-9a-f]+):([\s\S]*)$/);
    if (m) rows.set(m[1], m[2]);
  }
  const modules = new Set([...rows].filter(([, row]) => row.startsWith('I[')).map(([id]) => id));
  const parsed = new Map();
  const row = (id) => {
    if (!parsed.has(id)) {
      let v = null;
      try { v = JSON.parse(rows.get(id) ?? 'null'); } catch { /* a module's row, or text */ }
      parsed.set(id, v);
    }
    return parsed.get(id);
  };
  const element = (x) => Array.isArray(x) && x.length === 4 && x[0] === '$' && x[3] !== null && typeof x[3] === 'object';
  const waits = (x) => (element(x) ? Object.keys(x[3]).filter((k) => typeof x[3][k] === 'string'
    && /^\$[0-9a-f]+$/.test(x[3][k]) && modules.has(x[3][k].slice(1))) : []);
  const found = new Set();
  const note = (under, x) => {
    const w = waits(x);
    if (under && w.length) found.add(`<${under}> holds an element that waits on a module (${w.join(', ')})`);
  };
  // `under` is the HTML element a node sits straight under, or null.
  const read = (x, under) => {
    if (typeof x === 'string') {
      const lazy = x.match(/^\$L([0-9a-f]+)$/);
      if (under && lazy && rows.has(lazy[1])) {
        const v = row(lazy[1]);
        for (const e of Array.isArray(v) && !element(v) ? v : [v]) note(under, e);
      }
    } else if (element(x)) {
      note(under, x);
      const type = x[1];
      const html = typeof type === 'string' && /^[a-z][a-z0-9-]*$/.test(type) ? type : null;
      for (const v of Object.values(x[3])) read(v, html);
    } else if (Array.isArray(x)) {
      for (const v of x) read(v, under);
    } else if (x !== null && typeof x === 'object') {
      for (const v of Object.values(x)) read(v, null);
    }
  };
  for (const id of rows.keys()) read(row(id), null);
  return [...found];
}

async function visit(browser, view, path) {
  const context = await browser.newContext({ ...view, locale: 'fa-IR' });
  const page = await context.newPage();
  const errors = [];
  const elsewhere = [];
  page.on('pageerror', (e) => errors.push(`thrown: ${e.message}`));
  // A refusal the page asked for is not an error: «am I logged in?» is a 401
  // where nobody is. Every other answer of ours over 399 is one, and the
  // browser's own line for it is left to this.
  page.on('response', (r) => {
    const u = new URL(r.url());
    if (u.origin !== ORIGIN || r.status() < 400) return;
    if (r.status() === 401 && u.pathname === '/api/account/me') return;
    errors.push(`answered ${r.status()}: ${u.pathname}`);
  });
  page.on('console', (m) => {
    if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) errors.push(`console: ${m.text()}`);
  });
  page.on('request', (r) => {
    const u = r.url();
    if (!u.startsWith('data:') && !u.startsWith('blob:') && new URL(u).origin !== ORIGIN) elsewhere.push(u);
  });
  const where = `${path} (${view.name})`;
  const res = await page.goto(SITE + path, { waitUntil: 'networkidle' });
  if (!res || res.status() !== 200) fail(where, `answered ${res ? res.status() : 'nothing'}`);
  // The server sends one page whatever the view; it is read once.
  if (res && view === VIEWS[0]) for (const w of waitsUnderAnElement(await res.text())) fail(where, w);
  const seen = await page.evaluate(() => ({
    dir: document.documentElement.getAttribute('dir'),
    lang: document.documentElement.getAttribute('lang'),
    h1: [...document.querySelectorAll('h1')].map((h) => h.textContent.trim()),
    wide: document.documentElement.scrollWidth - window.innerWidth,
    ground: getComputedStyle(document.body).backgroundColor,
    // the panel's shape: its corners and its border's width; a dashed border
    // is the system's own variant for what is not there, not another panel
    panel: (() => {
      const p = document.querySelector('.panel');
      if (!p) return null;
      const s = getComputedStyle(p);
      return [s.borderTopLeftRadius, s.borderTopWidth].join(' ');
    })(),
    // a listing as the search shows it: a card where a ranking is served,
    // a row of the evidence where it is not
    articles: document.querySelectorAll('article.panel, [data-listing]').length,
    runs: document.querySelectorAll('[data-source]').length,
  }));
  if (seen.dir !== 'rtl') fail(where, `dir is ${seen.dir}`);
  if (seen.lang !== 'fa') fail(where, `lang is ${seen.lang}`);
  if (seen.h1.length !== 1 || !seen.h1[0]) fail(where, `${seen.h1.length} headings: ${JSON.stringify(seen.h1)}`);
  if (seen.wide > 1) fail(where, `${seen.wide}px wider than the screen`);
  if (elsewhere.length) fail(where, `asked another origin: ${[...new Set(elsewhere)].join(', ')}`);
  for (const e of errors) fail(where, e);
  await context.close();
  return seen;
}

const LOG = process.env.CARO_API_LOG || '';
const ADMIN = process.env.CARO_E2E_ADMIN_TOKEN || '';

function codeLines(phone) {
  try {
    return readFileSync(LOG, 'utf-8').split('\n').filter((l) => l.includes(`] ${phone}:`));
  } catch {
    return [];
  }
}

/* The code echoed for the request made after `before` lines were in the log:
   waited for, five seconds at most, since a container's log reaches its file
   a moment after the answer -- and never an earlier request's. */
async function codeAfter(phone, before) {
  for (let i = 0; i < 50; i++) {
    const lines = codeLines(phone);
    if (lines.length > before) {
      const m = lines[lines.length - 1].match(/(\d{6})\s*$/);
      return m ? m[1] : null;
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  return null;
}

/* The seller listings, from the seller's number to the buyer's press. */
async function sellerFlow(browser) {
  const phone = '09120000999';
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: 'fa-IR' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => fail('the seller listings', `thrown: ${e.message}`));
  try {
    await page.goto(`${SITE}/login`, { waitUntil: 'networkidle' });
    await page.getByLabel('شماره‌ی همراه').fill(phone);
    const before = codeLines(phone).length;
    await page.getByRole('button', { name: 'بفرست' }).click();
    await page.locator('form[data-step="code"]').waitFor();
    const code = await codeAfter(phone, before);
    if (!code) { fail('the seller listings', 'no code reached the log'); return; }
    await page.getByLabel('کد شش‌رقمی').fill(code);
    await page.getByRole('button', { name: 'ورود', exact: true }).click();
    await page.waitForURL('**/my-listings');

    await page.goto(`${SITE}/sell`, { waitUntil: 'networkidle' });
    await page.getByLabel('خودرو').selectOption({ index: 1 });
    await page.getByLabel('سال ساخت').fill('1398');
    await page.getByLabel('کارکرد (کیلومتر)').fill('85000');
    await page.getByLabel('قیمت (تومان)').fill('1200000000');
    await page.getByLabel('استان').selectOption('تهران');
    await page.getByLabel('توضیح').fill('بی‌رنگ، سرویس‌ها به‌موقع، فقط برای آزمون.');
    await page.getByLabel('شماره‌ام با دکمه‌ی «نمایش شماره» به خریدار نشان داده شود').check();
    await page.getByRole('button', { name: 'ثبت و فرستادن برای تأیید' }).click();
    await page.waitForURL('**/my-listings');

    const admin = await ctx.newPage();
    await admin.goto(`${SITE}/admin`, { waitUntil: 'networkidle' });
    await admin.getByLabel('توکن مدیریت').fill(ADMIN);
    await admin.getByRole('button', { name: 'در انتظار تأیید', exact: true }).click();
    await admin.getByRole('button', { name: 'در انتظار تأیید را باز کن' }).click();
    await admin.locator('[data-review="pending"] li').first().waitFor();
    await admin.getByRole('button', { name: 'تأیید و انتشار' }).first().click();
    await admin.getByText(/منتشر شد/).waitFor();

    await page.goto(`${SITE}/listings`, { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'نمایش شماره' }).first().click();
    await page.locator(`a[href="tel:${phone}"]`).waitFor();
  } catch (e) {
    fail('the seller listings', e.message.split('\n')[0]);
  } finally {
    await ctx.close();
  }
}

const browser = await chromium.launch();
const seen = {};
let walked = false;
try {
  for (const view of VIEWS) {
    for (const path of ROUTES) seen[`${view.name} ${path}`] = await visit(browser, view, path);
  }
  if (LOG && ADMIN) { await sellerFlow(browser); walked = true; }
} finally {
  await browser.close();
}

const at = (view, path) => seen[`${view} ${path}`];
if (at('desk, light', '/').ground === at('desk, dark', '/').ground) {
  fail('the schemes', `light and dark draw the same ground, ${at('desk, light', '/').ground}`);
}
const panels = new Set(ROUTES.map((p) => at('desk, light', p).panel).filter(Boolean));
if (panels.size !== 1) fail('the system', `the pages draw ${panels.size} kinds of panel: ${[...panels].join(' | ')}`);
for (const p of ['/', '/admin', '/login', '/contact']) {
  if (!at('desk, light', p).panel) fail('the system', `${p} draws no panel`);
}
const search = at('desk, light', `/search?q=${encodeURIComponent(Q)}`);
if (search.articles < 1) fail('the search', `«${Q}» showed no listing`);
if (at('desk, light', '/model/IKCO/Samand').runs < 1) fail("a model's page", 'drew no history');

const pages = ROUTES.length * VIEWS.length;
if (failures.length) {
  console.log(`${failures.length} failure(s) over ${pages} page views:`);
  for (const f of failures) console.log(`  ✗ ${f}`);
  process.exit(1);
}
console.log(`${pages} page views, ${ROUTES.length} routes in ${VIEWS.length} views: right to left, one heading, ` +
            `nothing wider than the screen, nothing from another origin, no error, nothing waiting on a module ` +
            `under an HTML element; the schemes two, ` +
            `the panel one, «${Q}» ${search.articles} listing(s) shown` +
            (walked ? '; a seller logged in by code, posted, was approved in /admin, and the number was shown'
                    : '; the seller listings not walked (no store, or no operator token)'));
