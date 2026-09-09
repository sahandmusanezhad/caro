'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  api, type CompareResponse, type ScoredItem, termLabel,
} from '@/lib/api';
import { faNum, faPlain, fixed, km, modelLabel, toman } from '@/lib/format';

/* Side by side, with every term kept apart.
 *
 * The comparison table this one argues against shows price and calls the
 * smallest number the winner. Here the cheapest car and the best opportunity
 * are separate rows, and they routinely disagree — because the opportunity is
 * the estimate minus the price minus the expected cost of the damage, and a
 * cheap car with a high risk figure loses the difference back.
 *
 * "Best in row" is marked, never "best overall". There is no such column: the
 * winner depends on the six weights, which the user set on the results page.
 */

type Metric = {
  key: string;
  fa: string;
  get: (r: ScoredItem) => number;
  fmt: (n: number) => string;
  better: 'high' | 'low';
  hint?: string;
  /* A bare signed decimal is a left-to-right run; a Persian phrase carrying
     a number is not. See the `.num` / `.fig` note in globals.css. */
  ltr?: boolean;
};

const METRICS: Metric[] = [
  { key: 'ask', fa: 'قیمت پیشنهادی', get: (r) => r.asking_price_toman,
    fmt: toman, better: 'low' },
  { key: 'est', fa: 'برآورد محافظه‌کارانه', get: (r) => r.estimate_toman,
    fmt: toman, better: 'high' },
  { key: 'dmg', fa: 'هزینه‌ی انتظاری خسارت', get: (r) => r.expected_damage_toman,
    fmt: toman, better: 'low', hint: 'از صرفه کم می‌شود، در آن ضرب نمی‌شود' },
  { key: 'opp', fa: 'صرفه', get: (r) => r.opportunity_toman,
    fmt: (n) => `${n >= 0 ? '+' : '−'} ${toman(Math.abs(n))}`, better: 'high',
    hint: 'برآورد − قیمت − خسارت' },
  { key: 'km', fa: 'کارکرد', get: (r) => r.mileage_km, fmt: km, better: 'low' },
  { key: 'year', fa: 'مدل', get: (r) => r.year_jalali, fmt: faPlain,
    better: 'high' },
  { key: 'score', fa: 'امتیاز کل', get: (r) => r.score,
    fmt: fixed, better: 'high', ltr: true },
];

export default function CompareTable() {
  const params = useSearchParams();
  const ids = (params.get('ids') ?? '').split(',').map((s) => s.trim())
    .filter(Boolean);
  const q = params.get('q') ?? 'خودرو';

  const [data, setData] = useState<CompareResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!ids.length) return;
    let alive = true;
    api.compare(ids, q)
      .then((r) => { if (alive) setData(r); })
      .catch((e) => { if (alive) setErr(String(e.message ?? e)); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.toString()]);

  if (!ids.length) {
    return (
      <div className="panel">
        <p className="eyebrow">مقایسه</p>
        <p className="m-0 text-[14px] text-ink-2">
          خودرویی انتخاب نشده. از صفحه‌ی نتایج، دو تا چهار خودرو را تیک بزن و
          «مقایسه کن» را بزن.
        </p>
        <Link href="/search" className="btn mt-4 inline-block">
          برو به جست‌وجو
        </Link>
      </div>
    );
  }

  if (err) {
    return (
      <div className="panel border-bad">
        <p className="eyebrow !text-bad">مقایسه ممکن نشد</p>
        <p className="m-0 text-[14px] text-ink-2">{err}</p>
      </div>
    );
  }

  if (!data) {
    return <div className="panel text-ink-3 text-[13.5px]">در حال بارگذاری…</div>;
  }

  if (!data.status.served) {
    return (
      <div className="flex flex-col gap-5">
        <section className="panel border-bad">
          <div className="flex items-center gap-3 flex-wrap mb-3">
            <span className="chip border-bad text-bad bg-bad-soft">
              NOT SERVED
            </span>
            <p className="eyebrow !mb-0">مقایسه‌ی تصمیمی سرو نمی‌شود</p>
          </div>
          <p className="m-0 text-[14px] leading-[1.95] max-w-[62ch]">
            مقایسه‌ی این خودروها روی محورهایی مثل صرفه و ریسک به برآوردگری
            نیاز دارد که روی همین پیکره پذیرفته شده باشد. چنین برآوردگری وجود
            ندارد، پس فقط آنچه از خود آگهی‌ها استخراج شده نمایش داده می‌شود.
          </p>
        </section>

        <div className="border border-line bg-surface rounded-[3px]
                        overflow-x-auto">
          <table className="w-full border-collapse text-[13px] min-w-[520px]">
            <thead>
              <tr className="text-ink-3 text-[11.5px]">
                {['خودرو', 'مدل', 'کارکرد', 'قیمت پیشنهادی'].map((h) => (
                  <th key={h} className="text-right font-normal px-4 py-2.5
                                         border-b border-line">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.evidence.map((r) => (
                <tr key={r.id}>
                  <td className="px-4 py-2.5 border-b border-line">
                    {modelLabel(r.model_key)}
                  </td>
                  <td className="px-4 py-2.5 border-b border-line num">
                    {faPlain(r.year_jalali)}
                  </td>
                  <td className="px-4 py-2.5 border-b border-line fig">
                    {km(r.mileage_km)}
                  </td>
                  <td className="px-4 py-2.5 border-b border-line fig">
                    {toman(r.asking_price_toman)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  const rows = data.rows;
  const termKeys = Array.from(
    new Set(rows.flatMap((r) => Object.keys(r.terms ?? {}))));

  return (
    <div className="flex flex-col gap-5">
      <div>
        <p className="eyebrow">مقایسه‌ی <span className="fig">
          {faPlain(rows.length)}</span> خودرو</p>
        <h1 className="m-0 text-[24px] font-bold">
          ارزان‌ترین ستون، لزوماً بهترین ستون نیست
        </h1>
        <p className="mt-2 mb-0 text-[13px] text-ink-3 max-w-[70ch]">
          نشانه‌ی ✓ یعنی بهترین مقدار در همان سطر — نه بهترین خودرو. «بهترین
          خودرو» به وزن‌هایی بستگی دارد که خودت در صفحه‌ی نتایج تنظیم کردی.
        </p>
      </div>

      <div className="border border-line bg-surface rounded-[3px]
                      overflow-x-auto">
        <table className="w-full border-collapse text-[13px]
                          min-w-[620px]">
          <thead>
            <tr>
              <th className="text-right font-normal text-[11.5px] text-ink-3
                             px-4 py-3 border-b border-line
                             sticky right-0 bg-surface">شاخص</th>
              {rows.map((r) => (
                <th key={r.id} className="text-right px-4 py-3 border-b
                                          border-line align-top">
                  <div className="font-medium text-[14px]">
                    {modelLabel(r.model_key)}{' '}
                    <span className="num text-ink-2">
                      {faPlain(r.year_jalali)}
                    </span>
                  </div>
                  {r.role_fa && (
                    <div className="text-[11.5px] text-accent mt-0.5">
                      {r.role_fa}
                    </div>
                  )}
                  {/* Two 206s of the same year are indistinguishable by
                      heading alone, which makes a comparison table useless
                      exactly when it is most needed. */}
                  <div className="num text-[11px] text-ink-3 mt-0.5">
                    {r.id}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {METRICS.map((m) => {
              const vals = rows.map(m.get);
              const best = m.better === 'high'
                ? Math.max(...vals) : Math.min(...vals);
              return (
                <tr key={m.key}>
                  <th className="text-right font-normal px-4 py-3 border-b
                                 border-line align-top sticky right-0
                                 bg-surface">
                    <div className="text-[12.5px] text-ink-2">{m.fa}</div>
                    {m.hint && (
                      <div className="text-[11px] text-ink-3 mt-0.5">
                        {m.hint}
                      </div>
                    )}
                  </th>
                  {rows.map((r, i) => {
                    const win = vals[i] === best;
                    return (
                      <td key={r.id}
                          className={`px-4 py-3 border-b border-line
                                      ${win ? 'text-accent font-medium' : ''}`}>
                        {/* The tick stays OUTSIDE the value's span. Inside an
                            LTR-isolated run it lands after the digits instead
                            of at the cell's reading edge, so the ✓ column
                            stops lining up down the table. */}
                        <span className={m.ltr ? 'num' : 'fig'}>
                          {m.fmt(vals[i])}
                        </span>
                        {win && <span className="mr-1.5">✓</span>}
                      </td>
                    );
                  })}
                </tr>
              );
            })}

            {termKeys.map((k) => {
              const vals = rows.map((r) => r.terms?.[k] ?? 0);
              const best = Math.max(...vals);
              return (
                <tr key={`t-${k}`}>
                  <th className="text-right font-normal px-4 py-2.5 border-b
                                 border-line sticky right-0 bg-surface">
                    <span className="text-[12px] text-ink-3">
                      سهم {termLabel(k)}
                    </span>
                  </th>
                  {rows.map((r, i) => (
                    <td key={r.id}
                        className={`px-4 py-2.5 border-b border-line num
                                    text-[12px] ${
                          vals[i] === best ? 'text-accent' : 'text-ink-3'}`}>
                      {vals[i] >= 0
                        ? `+${Math.abs(vals[i]).toFixed(3)}` : fixed(vals[i])}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="m-0 text-[12.5px] text-ink-3">
        پیکره: {data.corpus.label_fa} · <span className="fig">
        {faNum(data.corpus.rows)}</span> ردیف · <span className="num">
        {data.corpus.source}</span>
      </p>
    </div>
  );
}
