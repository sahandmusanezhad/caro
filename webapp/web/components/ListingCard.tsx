'use client';

import Link from 'next/link';
import { useState } from 'react';
import type { ScoredItem } from '@/lib/api';
import { compact, faNum, faPlain, km, modelLabel, toman } from '@/lib/format';
import TermBars from '@/components/TermBars';

/* One car, with the whole arithmetic on the card.
 *
 *     صرفه = برآورد − قیمت پیشنهادی − هزینه‌ی انتظاری خسارت
 *
 * All three terms are in tomans and all three are printed, because the
 * subtraction is the product. A card that showed only «صرفه ۲۲۹ میلیون» would
 * be asking to be trusted; a card that shows the three numbers it came from is
 * asking to be checked.
 *
 * `role_fa` is the reason this card is in the list at all — «امن‌ترین گزینه»
 * is a different claim from «بیشترین صرفه» and the shortlist deliberately
 * contains both, so a buyer sees the trade-off rather than one end of it.
 */
export default function ListingCard({
  item,
  selected,
  onToggle,
}: {
  item: ScoredItem;
  selected?: boolean;
  onToggle?: (id: string) => void;
}) {
  const [openTerms, setOpenTerms] = useState(false);
  const gain = item.opportunity_toman >= 0;

  return (
    <article className="panel">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-baseline gap-3 flex-wrap">
          <span className="num text-[12px] text-ink-3">
            #{faPlain(item.rank)}
          </span>
          <h3 className="m-0 text-[19px] font-medium">
            {modelLabel(item.model_key)}
            <span className="num text-ink-2 text-[16px] mr-2">
              {faPlain(item.year_jalali)}
            </span>
          </h3>
          {item.role_fa && (
            <span className="chip border-accent text-accent bg-accent-soft
                             !font-fa !normal-case !tracking-normal"
                  style={{ direction: 'rtl' }}>
              {item.role_fa}
            </span>
          )}
        </div>

        {onToggle && (
          <label className="flex items-center gap-2 text-[12.5px] text-ink-2
                            cursor-pointer select-none">
            <input
              type="checkbox"
              checked={!!selected}
              onChange={() => onToggle(item.id)}
              className="accent-[var(--accent)] w-4 h-4"
            />
            مقایسه
          </label>
        )}
      </div>

      {/* the arithmetic ------------------------------------------------- */}
      <div className="mt-5 grid gap-px bg-line border border-line
                      sm:grid-cols-4">
        <Cell k="قیمت پیشنهادی" v={toman(item.asking_price_toman)}
              hint={compact(item.asking_price_toman)} />
        <Cell k="برآورد محافظه‌کارانه" v={toman(item.estimate_toman)}
              hint={compact(item.estimate_toman)} />
        <Cell k="هزینه‌ی انتظاری خسارت"
              v={`− ${toman(item.expected_damage_toman)}`}
              hint="از صرفه کم شده، نه در آن ضرب" tone="bad" />
        <Cell k={gain ? 'صرفه' : 'زیان'}
              v={`${gain ? '+' : '−'} ${toman(Math.abs(item.opportunity_toman))}`}
              hint="برآورد − قیمت − خسارت"
              tone={gain ? 'good' : 'bad'} strong />
      </div>

      {/* facts ---------------------------------------------------------- */}
      <dl className="mt-4 m-0 flex flex-wrap gap-x-7 gap-y-1 text-[13px]">
        <Fact k="کارکرد" v={km(item.mileage_km)} />
        <Fact k="مدل" v={faPlain(item.year_jalali)} />
        {typeof item.features.risk === 'number' && (
          <Fact k="ریسک برآوردشده"
                v={`${faNum(item.features.risk * 100)}٪`} />
        )}
        {typeof item.features.liquidity === 'number' && (
          <Fact k="نقدشوندگی"
                v={`${faNum(item.features.liquidity * 100)}٪`} />
        )}
      </dl>

      <div className="mt-4 flex gap-2 flex-wrap items-center">
        <button type="button" onClick={() => setOpenTerms((v) => !v)}
                className="text-[13px] text-accent hover:underline">
          {openTerms ? 'بستن تفکیک امتیاز' : 'چرا این رتبه؟'}
        </button>
        <span className="text-ink-3">·</span>
        <Link href={`/car/${encodeURIComponent(item.id)}`}
              className="text-[13px] text-accent hover:underline">
          پرونده‌ی این خودرو
        </Link>
      </div>

      {openTerms && <TermBars terms={item.terms} score={item.score} />}
    </article>
  );
}

function Cell({
  k, v, hint, tone, strong,
}: {
  k: string; v: string; hint?: string;
  tone?: 'good' | 'bad'; strong?: boolean;
}) {
  const color = tone === 'good' ? 'text-good'
    : tone === 'bad' ? 'text-bad' : 'text-ink';
  return (
    <div className="bg-surface px-3.5 py-3">
      <div className="text-[11.5px] text-ink-3">{k}</div>
      <div className={`fig mt-0.5 ${color} ${
        strong ? 'text-[15px] font-medium' : 'text-[14px]'}`}>{v}</div>
      {hint && <div className="text-[11px] text-ink-3 mt-1">{hint}</div>}
    </div>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-2">
      <dt className="text-ink-3">{k}</dt>
      <dd className="m-0 fig">{v}</dd>
    </div>
  );
}
