'use client';

import Link from 'next/link';

/* A page that threw while it was drawn. Next's own screen says it in English
   and, in development, prints the error; this one says it in Persian and
   prints only the digest -- the reference a reader can quote, and the
   operator can find in the server's log. The message is never drawn: it can
   carry a path, a query or a value that is nobody's business on a screen. */
export const BROKE_FA = 'این صفحه هنگام ساخته شدن به خطا خورد. دوباره امتحان کن؛ اگر باز هم خطا داد، از صفحه‌ی تماس خبر بده.';
export const REFERENCE_FA = 'شماره‌ی پیگیری';

export default function BrokenPage({ error, reset }: {
  error: Error & { digest?: string };
  reset?: () => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="eyebrow">خطا</p>
        <h1 className="m-0 text-[28px] font-bold">چیزی درست کار نکرد</h1>
        <p className="mt-3 mb-0 text-[14px] text-ink-2 max-w-[62ch]">{BROKE_FA}</p>
        {error?.digest && (
          <p className="mt-2 mb-0 text-[12.5px] text-ink-3">
            {REFERENCE_FA}: <span className="num">{error.digest}</span>
          </p>
        )}
      </div>
      <div className="panel flex flex-wrap gap-2">
        <button type="button" className="btn btn-solid" onClick={() => reset?.()}>
          دوباره امتحان کن
        </button>
        <Link href="/" className="btn">خانه</Link>
        <Link href="/contact" className="btn">تماس با ما</Link>
      </div>
    </div>
  );
}
