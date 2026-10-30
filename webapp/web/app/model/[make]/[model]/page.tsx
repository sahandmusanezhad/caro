import ModelDetail from '@/components/ModelDetail';

export const metadata = { title: 'یک مدل، همه‌ی آگهی‌هایش — CARO' };

export default async function ModelPage({
  params,
}: {
  params: Promise<{ make: string; model: string }>;
}) {
  const { make, model } = await params;
  const mk = decodeURIComponent(make);
  // `_` is the placeholder for a model whose make the corpus does not give.
  return <ModelDetail make={mk === '_' ? '' : mk} model={decodeURIComponent(model)} />;
}
