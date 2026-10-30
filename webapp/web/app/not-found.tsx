import Link from 'next/link';

/* An address the site does not have. Next's own page says it in English; a
   reader of this one is told in Persian, and given the three places a search
   for a car starts from. Nothing about the address is repeated back. */
export const NOT_FOUND_FA = 'این نشانی در کارو صفحه‌ای ندارد.';

export const metadata = { title: 'پیدا نشد — CARO' };

export default function NotFound() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="eyebrow">۴۰۴</p>
        <h1 className="m-0 text-[28px] font-bold">صفحه پیدا نشد</h1>
        <p className="mt-3 mb-0 text-[14px] text-ink-2 max-w-[62ch]">{NOT_FOUND_FA}</p>
      </div>
      <div className="panel flex flex-wrap gap-2">
        <Link href="/" className="btn">خانه</Link>
        <Link href="/models" className="btn">خودروها</Link>
        <Link href="/search" className="btn">جست‌وجو</Link>
      </div>
    </div>
  );
}
