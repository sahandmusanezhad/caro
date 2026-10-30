import type { Metadata } from 'next';
import ModelDetail from '@/components/ModelDetail';
import { modelTitle } from '@/lib/format';

type Params = Promise<{ make: string; model: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { make, model } = await params;
  return { title: modelTitle(decodeURIComponent(make), decodeURIComponent(model)) };
}

export default async function ModelPage({ params }: { params: Params }) {
  const { make, model } = await params;
  const mk = decodeURIComponent(make);
  // `_` is the placeholder for a model whose make the corpus does not give.
  return <ModelDetail make={mk === '_' ? '' : mk} model={decodeURIComponent(model)} />;
}
