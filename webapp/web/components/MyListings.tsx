'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { faNum, faPlain, modelLabel, toman } from '@/lib/format';
import { listingState, sellerApi, type MineItem } from '@/lib/seller';

/* «آگهی‌های من»: where each listing stands, the operator's reason where one
 * was given, and the seller's own actions. A delete, of a listing or of the
 * account, asks a second time in the page itself -- the browser's confirm()
 * is not used anywhere on the site. */

function Twice({ label, sure, onSure }: { label: string; sure: string; onSure: () => void }) {
  const [asked, setAsked] = useState(false);
  if (!asked) return <button type="button" className="btn text-[12.5px]" onClick={() => setAsked(true)}>{label}</button>;
  return (
    <span className="flex gap-2 items-center">
      <button type="button" className="btn-solid text-[12.5px]" onClick={onSure}>{sure}</button>
      <button type="button" className="btn text-[12.5px]" onClick={() => setAsked(false)}>نه</button>
    </span>
  );
}

export function MineCard({ item, onChange }: { item: MineItem; onChange: () => void }) {
  const v = item.pending ?? item.live;
  const [msg, setMsg] = useState<string | null>(null);
  const days = Math.max(0, Math.ceil((item.ends_at - Date.now() / 1000) / 86400));
  return (
    <article className="panel flex flex-col gap-2" data-mine={item.id}>
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h3 className="m-0 text-[16px] font-bold">
          {v ? modelLabel(`${v.make}|${v.model}`) : 'آگهی'}
          {v ? <span className="text-ink-3 font-normal"> · مدل {faPlain(v.year_jalali)}</span> : null}
        </h3>
        <span className="fig text-[14px]">{v ? (v.negotiable ? 'توافقی' : toman(v.price_toman)) : ''}</span>
      </div>
      <p className="m-0 text-[13.5px]" data-state>{listingState(item)}</p>
      <p className="m-0 text-[12.5px] text-ink-3">
        {item.ended ? null : <>{faNum(days)} روز مانده · </>}
        شماره {faNum(item.reveals)} بار دیده شده
      </p>
      <div className="flex gap-2 flex-wrap mt-1">
        {!item.ended ? <Link href={`/sell?edit=${item.id}`} className="btn text-[12.5px] no-underline">ویرایش</Link> : null}
        <button type="button" className="btn text-[12.5px]"
                onClick={async () => { const r = await sellerApi.renew(item.id); setMsg(r.ok ? null : r.message); onChange(); }}>
          تمدید ۳۰ روزه
        </button>
        <Twice label="حذف آگهی" sure="بله، حذف کن"
               onSure={async () => { await sellerApi.remove(item.id); onChange(); }} />
      </div>
      {msg ? <p className="m-0 text-[12.5px] text-bad">{msg}</p> : null}
    </article>
  );
}

export default function MyListings() {
  const router = useRouter();
  const [items, setItems] = useState<MineItem[] | null>(null);
  const [phone, setPhone] = useState<string | null>(null);

  const load = useCallback(() => {
    sellerApi.mine().then((r) => {
      if (r.status === 401) { router.replace('/login'); return; }
      setItems(r.data?.listings ?? []);
    });
  }, [router]);

  useEffect(() => {
    sellerApi.me().then((r) => { if (r.ok && r.data) setPhone(r.data.phone); });
    load();
  }, [load]);

  const active = (items ?? []).some((i) => !i.ended);
  return (
    <div className="flex flex-col gap-5">
      <section className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <p className="eyebrow">آگهی فروشنده‌ها</p>
          <h1 className="m-0 text-[26px] font-bold">آگهی‌های من</h1>
          {phone ? <p className="m-0 mt-1 text-[12.5px] text-ink-3 num" dir="ltr">{phone}</p> : null}
        </div>
        {!active ? <Link href="/sell" className="btn-solid no-underline">ثبت آگهی</Link> : null}
      </section>
      {items === null ? <p className="m-0 text-[13px] text-ink-3">در حال خواندن…</p> : null}
      {items !== null && items.length === 0 ? (
        <div className="panel text-[13.5px] text-ink-3">هنوز آگهی‌ای ثبت نکرده‌ای. هر شماره یک آگهی فعال دارد.</div>
      ) : null}
      {(items ?? []).map((i) => <MineCard key={i.id} item={i} onChange={load} />)}
      <section className="flex gap-3 flex-wrap items-center border-t border-line pt-4">
        <button type="button" className="btn text-[12.5px]"
                onClick={async () => { await sellerApi.logout(); router.push('/'); }}>
          خروج
        </button>
        <Twice label="حذف حساب" sure="بله، حساب و همه‌ی آگهی‌هایم پاک شود"
               onSure={async () => { await sellerApi.deleteAccount(); router.push('/'); }} />
      </section>
    </div>
  );
}
