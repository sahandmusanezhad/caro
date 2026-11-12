// Render print.html (two A4 sheets) to a PDF with Chromium.
//   node tools/make_pdf.js            -> diyako-menu-A4.pdf
// Needs Playwright with Chromium (npm i -D playwright && npx playwright install chromium).
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const root = path.resolve(__dirname, "..");
  const src = "file://" + path.join(root, "print.html");
  const out = path.join(root, process.argv[2] || "diyako-menu-A4.pdf");
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(src, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  await page.emulateMedia({ media: "print" });
  await page.pdf({ path: out, format: "A4", printBackground: true, preferCSSPageSize: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  await browser.close();
  console.log("wrote", out);
})().catch((e) => { console.error(e); process.exit(1); });
