import { Suspense } from 'react';
import SearchResults from '@/components/SearchResults';

export const metadata = { title: 'فیلتر آگهی‌ها — CARO' };

/* The filter page (the owner's choice of 2026-11-25): the panel alone, as on
   Divar, without a sentence. It draws with the search's own component in its
   filter mode, so the two pages say the same things the same way. The
   boundary is the search page's, for the same reason: `useSearchParams`. */
export default function FilterPage() {
  return (
    <>
      <h1 className="sr-only">فیلتر آگهی‌های خودرو</h1>
      <Suspense fallback={
        <div className="panel text-ink-3 text-[13.5px]">در حال بارگذاری…</div>
      }>
        <SearchResults mode="filter" />
      </Suspense>
    </>
  );
}
