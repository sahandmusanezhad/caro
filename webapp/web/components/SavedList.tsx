'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ApiError, api, type EvidenceItem } from '@/lib/api';
import { askingPrice, faPlain, modelLabel, odometer } from '@/lib/format';
import { onSavedChange, savedIds } from '@/lib/saved';
import SaveButton from '@/components/SaveButton';

/* The listings kept in this browser (lib/saved.ts), each read again from the
   corpus being served. One that the corpus no longer holds says so, and can be
   taken off the list; nothing is sent anywhere but the API's own listing
   endpoint, one id at a time. */
type Kept = { id: string; listing: EvidenceItem | null; gone: boolean };

export default function SavedList() {
  const [ids, setIds] = useState<string[] | null>(null);
  const [kept, setKept] = useState<Kept[]>([]);
  useEffect(() => {
    const sync = () => setIds(savedIds());
    sync();
    return onSavedChange(sync);
  }, []);
  useEffect(() => {
    if (!ids) return;
    let live = true;
    Promise.all(ids.map((id) => api.listing(id)
      .then((r) => ({ id, listing: r.listing, gone: r.listing == null }))
      .catch((e) => ({ id, listing: null, gone: e instanceof ApiError && e.status === 404 }))))
      .then((got) => { if (live) setKept(got); });
    return () => { live = false; };
  }, [ids]);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="eyebrow">نشان‌شده‌ها</p>
        <h1 className="m-0 text-[28px] font-bold">آگهی‌هایی که نگه داشته‌ای</h1>
        <p className="mt-3 mb-0 text-[14px] text-ink-2 max-w-[62ch]">
          فقط در همین مرورگر نگه داشته می‌شوند؛ حسابی در کار نیست و چیزی به جایی
          فرستاده نمی‌شود. مرورگر دیگر، یا پاک کردن داده‌های سایت، فهرست را خالی می‌کند.
        </p>
      </div>
      {ids && ids.length === 0 && (
        <p className="panel m-0">
          هنوز چیزی نشان نکرده‌ای. در <Link href="/models">صفحه‌ی هر مدل</Link> یا پرونده‌ی هر
          خودرو، «نشان کن» را بزن.
        </p>
      )}
      {kept.length > 0 && (
        <ul className="m-0 p-0 list-none flex flex-col tiles">
          {kept.map((k) => (
            <li key={k.id} className="p-4 flex flex-wrap items-center gap-x-6 gap-y-2">
              {k.listing ? (
                <>
                  <div className="grow">
                    <Link href={`/car/${encodeURIComponent(k.id)}`} className="text-[16px] font-bold text-ink">
                      {modelLabel(k.listing.model_key)}{' '}
                      <bdi className="fig text-ink-3 font-normal">{faPlain(k.listing.year_jalali)}</bdi>
                    </Link>
                    <p className="m-0 text-[13px] text-ink-2 fig">
                      {askingPrice(k.listing.asking_price_toman, k.listing.price_status, k.listing.price_kind)}
                      {' · '}
                      {odometer(k.listing.mileage_km, k.listing.mileage_status, false)}
                    </p>
                  </div>
                  <SaveButton id={k.id} compact />
                </>
              ) : (
                <>
                  <p className="m-0 grow text-[13.5px] text-ink-3">
                    <span className="num">{k.id}</span> — {k.gone
                      ? 'در پیکره‌ای که سرو می‌شود نیست.'
                      : 'خوانده نشد.'}
                  </p>
                  <SaveButton id={k.id} compact />
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
