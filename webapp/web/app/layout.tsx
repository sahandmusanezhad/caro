import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';
import CorpusBadge from '@/components/CorpusBadge';

export const metadata: Metadata = {
  title: 'CARO — تصمیم‌یار خرید خودروی کارکرده',
  description:
    'CARO یک موتور جست‌وجو نیست؛ یک تصمیم‌یار است که هر عدد را همراه با درجه‌ی '
    + 'شواهدش نشان می‌دهد و وقتی شواهد کافی نیست، توصیه نمی‌دهد.',
};

const NAV = [
  { href: '/', fa: 'خانه' },
  { href: '/search', fa: 'جست‌وجو' },
  { href: '/models', fa: 'خودروها' },
  { href: '/compare', fa: 'مقایسه' },
  { href: '/saved', fa: 'نشان‌شده‌ها' },
  { href: '/how-it-works', fa: 'چطور کار می‌کند' },
  { href: '/about', fa: 'درباره‌ی ما' },
  { href: '/contact', fa: 'تماس با ما' },
];

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fa" dir="rtl">
      <head>
        {/* The fonts are the site's own (globals.css). Every page's text is
            Persian, so the Arabic-script subset is asked for at once rather
            than when the stylesheet is read. */}
        <link rel="preload" href="/fonts/vazirmatn-arabic-wght-normal.woff2" as="font"
              type="font/woff2" crossOrigin="" />
      </head>
      <body>
        <header className="glass-bar sm:sticky top-0 z-40 border-b">
          {/* On a phone the logo and the badge share a row and the nav is the
              next one, a single row that scrolls sideways: wrapped, it took
              three rows and a third of the first screen. The same two rows
              hold up to 1280 px, below which the three do not fit in one;
              from there they stand in one row as before. */}
          <div className="mx-auto max-w-[1100px] px-5 py-4 flex items-center
                          gap-x-5 gap-y-3 flex-wrap">
            <Link href="/" className="order-1 flex items-baseline gap-3 no-underline">
              <span className="font-mono text-[22px] font-medium tracking-[0.14em]
                               text-accent">CARO</span>
              <span className="text-[12px] text-ink-3 hidden sm:inline">
                تصمیم‌یار خرید خودروی کارکرده
              </span>
            </Link>

            <nav className="order-3 xl:order-2 w-full xl:w-auto xl:mr-auto -mx-5 px-5
                            xl:mx-0 xl:px-0 flex gap-1 flex-nowrap xl:flex-wrap
                            overflow-x-auto xl:overflow-visible text-[13px]
                            [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              {NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  className="shrink-0 whitespace-nowrap px-3 py-1.5 rounded-full text-ink-2
                             hover:text-ink hover:bg-sunk transition-colors"
                >
                  {n.fa}
                </Link>
              ))}
            </nav>

            {/* Persistent, on every screen. Not a title card — see
                webapp/api/corpus.py and docs/DEMO_SCRIPT.md. */}
            <div className="order-2 xl:order-3 mr-auto xl:mr-0">
              <CorpusBadge />
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-[1100px] px-5 py-8 pb-20">
          {children}
        </main>

        <footer className="glass-bar border-t mt-10">
          <div className="mx-auto max-w-[1100px] px-5 py-7 text-[12.5px]
                          text-ink-3 flex flex-wrap gap-x-8 gap-y-2
                          justify-between">
            <p className="m-0 max-w-[62ch]">
              هیچ عددی در این سامانه بدون درجه‌ی شواهدش نمایش داده نمی‌شود.
              وقتی برآوردگر از دروازه‌ی پذیرش عبور نکرده باشد، CARO رتبه‌بندی
              را سرو نمی‌کند — شواهد را نشان می‌دهد و توصیه نمی‌دهد.
            </p>
            <p className="m-0 font-mono text-[11px] tracking-wider">
              CARO · W0 tracking · W1 appraisal · W2 agents · W3 ranking · W4 ingest
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
