import CarDetail from '@/components/CarDetail';

export const metadata = { title: 'پرونده‌ی خودرو — CARO' };

export default async function CarPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <CarDetail id={decodeURIComponent(id)} />;
}
