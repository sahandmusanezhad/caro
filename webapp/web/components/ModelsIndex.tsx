'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ApiError, api, type ModelsResponse } from '@/lib/api';
import { compact, faNum, faPlain, modelLabel } from '@/lib/format';

/* Every model the served corpus holds, as a price-comparison site lists its
   products: how many listings, how many priced, and the range of their asking
   prices. A middle is drawn only where three priced listings stand behind it
   (webapp/api/market.py). Nothing here is an estimate. */
export default function ModelsIndex() {
  const [data, setData] = useState<ModelsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.models().then(setData).catch((e) =>
      setErr(e instanceof ApiError ? e.message : 'پاسخی از سرویس دریافت نشد.'));
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="eyebrow">خودروها</p>
        <h1 className="m-0 text-[28px] font-bold">هر مدل، همه‌ی آگهی‌هایش</h1>
        <p className="mt-3 mb-0 text-[15px] text-ink-2 max-w-[62ch]">
          برای هر مدل: چند آگهی، چندتا با قیمت، و کمترین و بیشترین قیمت
          پیشنهادی. این‌ها قیمت‌هایی است که آگهی‌ها گفته‌اند، نه برآورد ما و نه
          حرفی درباره‌ی بازار.
          {data && <> پیکره: <span className="font-medium">{data.corpus.label_fa}</span>.</>}
        </p>
      </div>
      {err && <p className="panel !text-bad m-0">{err}</p>}
      {!data && !err && <p className="text-ink-3 m-0">در حال خواندن…</p>}
      {data && data.models.length === 0 && (
        <p className="panel m-0">این پیکره هیچ مدلی ندارد که نشان داده شود.</p>
      )}
      {data && data.models.length > 0 && (
        <div className="grid tiles sm:grid-cols-2 lg:grid-cols-3">
          {data.models.map((m) => (
            <Link key={`${m.make}|${m.model}`}
                  href={`/model/${encodeURIComponent(m.make ?? '_')}/${encodeURIComponent(m.model)}`}
                  className="p-5 no-underline text-ink hover:!border-accent transition-colors">
              <h2 className="m-0 text-[18px] font-bold">
                {modelLabel(`${m.make ?? ''}|${m.model}`)}
              </h2>
              <p className="mt-1 mb-3 text-[13px] text-ink-3">
                <span className="fig">{faNum(m.listings)}</span> آگهی ·{' '}
                <span className="fig">{faNum(m.priced)}</span> با قیمت
                {m.year_min && m.year_max && (
                  <> · مدل <span className="fig">{faPlain(m.year_min)}</span> تا{' '}
                    <span className="fig">{faPlain(m.year_max)}</span></>
                )}
              </p>
              {m.price_min != null && m.price_max != null ? (
                <p className="m-0 text-[14px]">
                  از <span className="fig font-bold text-accent">{compact(m.price_min)}</span> تا{' '}
                  <span className="fig font-bold">{compact(m.price_max)}</span> تومان
                  {m.price_median != null && (
                    <span className="block text-[12.5px] text-ink-3 mt-1">
                      میانه‌ی قیمت پیشنهادی <span className="fig">{compact(m.price_median)}</span> تومان
                    </span>
                  )}
                </p>
              ) : (
                <p className="m-0 text-[13px] text-ink-3">هیچ آگهی‌ای از این مدل قیمت پیشنهادی ندارد.</p>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
