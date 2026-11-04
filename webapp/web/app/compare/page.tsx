import { Suspense } from 'react';
import CompareTable from '@/components/CompareTable';

export const metadata = { title: 'مقایسه — CARO' };

export default function ComparePage() {
  return (
    <>
      {/* The page's one heading, on every state of it: nothing picked, a
          refusal, or the table, whose own title is the second heading. */}
      <h1 className="sr-only">مقایسه‌ی خودروها</h1>
      <Suspense fallback={
        <div className="panel text-ink-3 text-[13.5px]">در حال بارگذاری…</div>
      }>
        <CompareTable />
      </Suspense>
    </>
  );
}
