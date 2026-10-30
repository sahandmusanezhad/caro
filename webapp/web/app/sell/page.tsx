import SellPage from '@/components/SellPage';

export const metadata = { title: 'ثبت آگهی — CARO' };

export default async function Page({ searchParams }: { searchParams: Promise<{ edit?: string }> }) {
  const { edit } = await searchParams;
  return <SellPage editId={edit && /^\d+$/.test(edit) ? Number(edit) : undefined} />;
}
