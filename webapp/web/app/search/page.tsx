import { Suspense } from 'react';
import SearchResults from '@/components/SearchResults';

export const metadata = { title: 'جست‌وجو — CARO' };

/* `useSearchParams` opts the subtree into client-side rendering, so Next
   requires the boundary. The fallback is deliberately plain: a skeleton that
   mimics result cards would be showing shapes of cars that may not exist. */
export default function SearchPage() {
  return (
    <Suspense fallback={
      <div className="panel text-ink-3 text-[13.5px]">در حال بارگذاری…</div>
    }>
      <SearchResults />
    </Suspense>
  );
}
