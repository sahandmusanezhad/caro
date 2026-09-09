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
  { href: '/compare', fa: 'مقایسه' },
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
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap"
        />
      </head>
      <body>
        <header className="border-b border-line bg-surface">
          <div className="mx-auto max-w-[1100px] px-5 py-4 flex items-center
                          gap-5 flex-wrap">
            <Link href="/" className="flex items-baseline gap-3 no-underline">
              <span className="font-mono text-[22px] font-medium tracking-[0.14em]
                               text-accent">CARO</span>
              <span className="text-[12px] text-ink-3 hidden sm:inline">
                تصمیم‌یار خرید خودروی کارکرده
              </span>
            </Link>

            <nav className="flex gap-1 flex-wrap text-[13px] mr-auto">
              {NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  className="px-2.5 py-1.5 rounded-[2px] text-ink-2
                             hover:text-ink hover:bg-sunk transition-colors"
                >
                  {n.fa}
                </Link>
              ))}
            </nav>

            {/* Persistent, on every screen. Not a title card — see
                webapp/api/corpus.py and docs/DEMO_SCRIPT.md. */}
            <CorpusBadge />
          </div>
        </header>

        <main className="mx-auto max-w-[1100px] px-5 py-8 pb-20">
          {children}
        </main>

        <footer className="border-t border-line mt-10">
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
