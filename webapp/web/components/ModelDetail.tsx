'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ApiError, api, type HistoryPoint, type ModelResponse } from '@/lib/api';
import {
  askingPrice, compact, faNum, faPlain, modelLabel, odometer, provinceLabel,
} from '@/lib/format';
import SaveButton from '@/components/SaveButton';
import { type OfferSort, offersOfYear, sortOffers } from '@/lib/offers';

/* One model, as a price-comparison site shows a product: the range of the
   asking prices, how they stood in every published run, and every listing,
   the cheapest first, each with its file here and its page on its source.

   What the chart is NOT. Each point is the middle asking price of one run's
   priced listings of this model, drawn only where three or more stand behind
   it; a run with fewer is named with its count and is no point. Four runs of
   one source are four samples, not a market (D36), and the caption says so.

   The listings can be read three ways -- cheapest, newest, least driven
   (lib/offers.ts says what each does with a listing it cannot place) -- and
   kept to one year by its chip. */

const SORTS: { by: OfferSort; fa: string; heading: string; note: string }[] = [
  { by: 'price', fa: 'ارزان‌ترین', heading: 'آگهی‌ها، ارزان‌ترین اول',
    note: 'قیمت‌ها همان‌اند که آگهی‌ها گفته‌اند. آگهی‌ای که قیمتش قابل استفاده نیست بعد از آگهی‌های با قیمت آمده است.' },
  { by: 'year', fa: 'جدیدترین', heading: 'آگهی‌ها، جدیدترین مدل اول',
    note: 'آگهی‌ای که سال ساختش معلوم نیست آخر آمده است؛ هم‌سال‌ها ارزان‌ترین اول.' },
  { by: 'mileage', fa: 'کم‌کارکردترین', heading: 'آگهی‌ها، کم‌کارکردترین اول',
    note: 'کارکردی که مشکوک یا ناممکن خوانده شده، یا معلوم نیست، بعد از بقیه آمده است.' },
];

function History({ points }: { points: HistoryPoint[] }) {
  const drawn = points.filter((p) => p.price_median != null);
  if (drawn.length === 0) {
    return <p className="m-0 text-[13px] text-ink-3">در هیچ اجرای منتشرشده‌ای سه آگهی با قیمت از این مدل نبود.</p>;
  }
  const W = 640, H = 180, PX = 36, PY = 24;
  const vals = drawn.map((p) => p.price_median as number);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || hi * 0.1 || 1;
  const x = (i: number) => PX + (points.length === 1 ? (W - 2 * PX) / 2 : (i * (W - 2 * PX)) / (points.length - 1));
  const y = (v: number) => H - PY - ((v - lo) / span) * (H - 2 * PY);
  const segs: string[] = [];
  points.forEach((p, i) => {
    const prev = points[i - 1];
    if (i > 0 && p.price_median != null && prev.price_median != null) {
      segs.push(`M${x(i - 1)},${y(prev.price_median)} L${x(i)},${y(p.price_median)}`);
    }
  });
  return (
    <figure className="m-0">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto max-w-[760px] mx-auto block" role="img"
           aria-label="میانه‌ی قیمت پیشنهادی در هر اجرای منتشرشده">
        {segs.map((d) => <path key={d} d={d} fill="none" stroke="var(--accent)" strokeWidth="2.5" />)}
        {points.map((p, i) => p.price_median != null ? (
          <g key={p.run_id}>
            <circle cx={x(i)} cy={y(p.price_median)} r="5" fill="var(--accent)" />
            <text x={x(i)} y={y(p.price_median) - 12} textAnchor="middle" fontSize="13"
                  fill="var(--ink)">{compact(p.price_median)}</text>
          </g>
        ) : null)}
        {points.map((p, i) => (
          <text key={`l-${p.run_id}`} x={x(i)} y={H - 4} textAnchor="middle" fontSize="11.5"
                fill="var(--ink-3)">{p.run_id} · {faNum(p.priced)} آگهی</text>
        ))}
      </svg>
      <figcaption className="text-[12.5px] text-ink-3 mt-2">
        هر نقطه میانه‌ی قیمت پیشنهادیِ آگهی‌های با قیمتِ این مدل در یک اجرای منتشرشده
        است، و فقط جایی کشیده می‌شود که دست‌کم سه آگهی پشتش باشد. این چند اجرا
        نمونه‌اند، نه بازار: نمودار درباره‌ی گران یا ارزان شدن چیزی نمی‌گوید.
      </figcaption>
    </figure>
  );
}

export default function ModelDetail({ make, model }: { make: string; model: string }) {
  const [data, setData] = useState<ModelResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [by, setBy] = useState<OfferSort>('price');
  const [year, setYear] = useState<number | null>(null);
  useEffect(() => {
    api.model(make, model).then(setData).catch((e) => {
      if (e instanceof ApiError && e.fault?.code === 'MODEL_NOT_FOUND') {
        setErr('این مدل در پیکره‌ای که همین حالا سرو می‌شود آگهی‌ای ندارد.');
      } else {
        setErr(e instanceof ApiError ? e.message : 'پاسخی از سرویس دریافت نشد.');
      }
    });
  }, [make, model]);

  const name = modelLabel(`${make}|${model}`);
  if (err) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="m-0 text-[26px] font-bold">{name}</h1>
        <p className="panel !text-bad m-0">{err}</p>
        <Link href="/models" className="btn self-start no-underline">همه‌ی مدل‌ها</Link>
      </div>
    );
  }
  if (!data || !data.summary) {
    return <p className="text-ink-3">در حال خواندن…</p>;
  }
  const s = data.summary;
  const sort = SORTS.find((x) => x.by === by) ?? SORTS[0];
  const shown = offersOfYear(sortOffers(data.offers, by), year);
  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="eyebrow"><Link href="/models" className="text-ink-3">خودروها</Link> · {name}</p>
        <h1 className="m-0 text-[28px] font-bold">{name}</h1>
        <p className="mt-2 mb-0 text-[14px] text-ink-2">
          <span className="fig">{faNum(s.listings)}</span> آگهی در پیکره‌ی «{data.corpus.label_fa}»،{' '}
          <span className="fig">{faNum(s.priced)}</span> با قیمت پیشنهادی.
        </p>
      </div>

      <div className="grid tiles grid-cols-3">
        {([['کمترین', s.price_min], ['میانه', s.price_median], ['بیشترین', s.price_max]] as const).map(([k, v]) => (
          <div key={k} className="p-4 text-center">
            <p className="m-0 text-[12.5px] text-ink-3">{k} قیمت پیشنهادی</p>
            <p className={`m-0 mt-1 text-[19px] font-bold fig ${k === 'کمترین' ? 'text-accent' : ''}`}>
              {v != null ? `${compact(v)}` : '—'}
            </p>
            <p className="m-0 text-[11.5px] text-ink-3">{v != null ? 'تومان' : 'کمتر از سه آگهی'}</p>
          </div>
        ))}
      </div>

      <section className="panel">
        <p className="eyebrow">در اجراهای منتشرشده</p>
        <History points={data.history} />
      </section>

      {data.by_year.length > 0 && (
        <section className="panel">
          <p className="eyebrow">بر اساس سال ساخت — روی هر سال بزن تا فقط آگهی‌های همان سال بماند</p>
          <div className="flex flex-wrap gap-2">
            {data.by_year.map((y) => (
              <button key={y.year_jalali} type="button" aria-pressed={year === y.year_jalali}
                      onClick={() => setYear(year === y.year_jalali ? null : y.year_jalali)}
                      className={`glass rounded-xl px-3 py-1.5 text-[13px] text-ink cursor-pointer
                                  ${year === y.year_jalali ? '!border-accent' : ''}`}>
                <span className="fig font-bold">{faPlain(y.year_jalali)}</span>{' '}
                <span className="text-ink-3">· <span className="fig">{faNum(y.priced)}</span> آگهی با قیمت</span>
                {y.price_median != null && <> · میانه <span className="fig">{compact(y.price_median)}</span></>}
              </button>
            ))}
          </div>
        </section>
      )}

      <section>
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3.5">
          <p className="eyebrow !mb-0">
            {sort.heading}
            {year != null && <> · مدل <span className="fig">{faPlain(year)}</span> ({faNum(shown.length)} آگهی)</>}
          </p>
          <div className="flex flex-wrap gap-2" role="group" aria-label="ترتیب آگهی‌ها">
            {SORTS.map((x) => (
              <button key={x.by} type="button" aria-pressed={by === x.by} onClick={() => setBy(x.by)}
                      className={`btn px-3 py-1 text-[12.5px] ${by === x.by ? '!bg-accent-soft !text-ink font-bold' : ''}`}>
                {x.fa}
              </button>
            ))}
            {year != null && (
              <button type="button" onClick={() => setYear(null)} className="btn px-3 py-1 text-[12.5px]">
                همه‌ی سال‌ها
              </button>
            )}
          </div>
        </div>
        <ul className="m-0 p-0 list-none flex flex-col tiles">
          {shown.map((o) => (
            <li key={o.id} className="p-4 flex flex-wrap items-center gap-x-6 gap-y-2">
              <div className="min-w-[11rem]">
                <p className="m-0 text-[17px] font-bold fig">
                  {askingPrice(o.asking_price_toman, o.price_status, o.price_kind)}
                </p>
                <p className="m-0 text-[12.5px] text-ink-3">
                  {o.trim ? modelLabel(`||${o.trim}`) + ' · ' : ''}
                  مدل <span className="fig">{faPlain(o.year_jalali)}</span>
                </p>
              </div>
              <p className="m-0 text-[13.5px] text-ink-2 grow">
                <span className="fig">{odometer(o.mileage_km, o.mileage_status, false)}</span>
                {/* No body condition here: FIELD_PROVENANCE.md has it card=no, so
                    a list draws it nowhere; the car's file does. */}
                {o.province && <> · {provinceLabel(o.province, o.province_source)}</>}
              </p>
              <div className="flex flex-wrap gap-2">
                <SaveButton id={o.id} compact />
                <Link className="btn px-3 py-1 text-[12.5px] no-underline" href={`/car/${encodeURIComponent(o.id)}`}>پرونده</Link>
                {o.url && /^https:\/\//.test(o.url) && (
                  <a className="btn-solid px-3 py-1 text-[12.5px] no-underline" href={o.url}
                     target="_blank" rel="noopener noreferrer nofollow">دیدن در منبع ↗</a>
                )}
              </div>
            </li>
          ))}
        </ul>
        <p className="text-[12px] text-ink-3 mt-3 mb-0">{sort.note}</p>
      </section>
    </div>
  );
}
