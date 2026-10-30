'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { sellerApi } from '@/lib/seller';
import SellForm from '@/components/SellForm';

/* The page around «ثبت آگهی»: a seller who is not logged in is sent to log
 * in, and the form is given the site's own table of models, so a car chosen
 * from it appears on its model's page. */
export default function SellPage({ editId }: { editId?: number }) {
  const router = useRouter();
  const [pairs, setPairs] = useState<{ make: string; model: string }[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    sellerApi.me().then((r) => { if (r.status === 401) router.replace('/login'); else setReady(r.ok); });
    api.models()
      .then((d) => setPairs(d.models.filter((m) => m.make).map((m) => ({ make: m.make as string, model: m.model }))))
      .catch(() => setPairs([]));
  }, [router]);

  return (
    <div className="flex flex-col gap-5">
      <section>
        <p className="eyebrow">آگهی فروشنده‌ها</p>
        <h1 className="m-0 text-[26px] font-bold">{editId === undefined ? 'ثبت آگهی' : 'ویرایش آگهی'}</h1>
      </section>
      {ready ? <SellForm editId={editId} pairs={pairs} /> : <p className="m-0 text-[13px] text-ink-3">در حال خواندن…</p>}
    </div>
  );
}
