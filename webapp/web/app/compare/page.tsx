import { Suspense } from 'react';
import CompareTable from '@/components/CompareTable';

export const metadata = { title: 'مقایسه — CARO' };

export default function ComparePage() {
  return (
    <Suspense fallback={
      <div className="panel text-ink-3 text-[13.5px]">در حال بارگذاری…</div>
    }>
      <CompareTable />
    </Suspense>
  );
}
