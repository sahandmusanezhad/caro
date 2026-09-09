'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  api, type CorpusInfo, type Listing, type ScoredListing,
} from '@/lib/api';
import { compact, faNum, faPlain, km, modelLabel, toman } from '@/lib/format';
import TermBars from '@/components/TermBars';

/* One car's file.
 *
 * The page is built from two calls, and the split is the point. `/api/listing`
 * returns what was PARSED — year, odometer, asking price, the derived feature
 * values — and nothing that required an estimator. `/api/compare` with a
 * single id then asks for the DECISION, which may be refused. So a car always
 * has a file, even on a corpus where CARO will not rank anything, and the file
 * never quietly acquires an estimate it has not earned.
 *
 * What is missing here is missing on purpose. A published corpus carries no
 * title and no seller description, because the data contract forbids
 * publishing seller-authored text; `corpus_reader.py` sets both to "" rather
 * than reconstructing them. This page says so where a photo gallery and a
 * description would otherwise sit, instead of leaving an empty box that reads
 * as a loading failure.
 */
export default function CarDetail({ id }: { id: string }) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [corpus, setCorpus] = useState<CorpusInfo | null>(null);
  const [scored, setScored] = useState<ScoredListing | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.listing(id)
      .then((r) => {
        if (!alive) return;
        setListing(r.listing);
        setCorpus(r.corpus);
        return api.compare([id]);
      })
      .then((c) => {
        if (!alive || !c) return;
        if (c.served && c.rows.length) {
          setScored(c.rows[0] as ScoredListing);
        } else {
          setRefused(c.refusal?.detail ?? 'رتبه‌بندی روی این پیکره سرو نمی‌شود');
        }
      })
      .catch((e) => { if (alive) setErr(String(e.message ?? e)); });
    return () => { alive = false; };
  }, [id]);

  if (err) {
    return (
      <div className="panel border-bad">
        <p className="eyebrow !text-bad">پیدا نشد</p>
        <p className="m-0 text-[14px] text-ink-2">{err}</p>
        <Link href="/search" className="btn mt-4 inline-block">
          برگرد به جست‌وجو
        </Link>
      </div>
    );
  }

  if (!listing) {
    return <div className="panel text-ink-3 text-[13.5px]">در حال بارگذاری…</div>;
  }

  const gain = scored ? scored.opportunity_toman >= 0 : false;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="eyebrow">پرونده‌ی خودرو · <span className="num">{id}</span></p>
        <h1 className="m-0 text-[28px] font-bold">
          {modelLabel(listing.model_key)}
          <span className="num text-ink-2 text-[22px] mr-3">
            {faPlain(listing.year_jalali)}
          </span>
        </h1>
        <p className="mt-2 mb-0 text-[15px] text-ink-2">
          <span className="fig">{toman(listing.asking_price_toman)}</span>
          <span className="text-ink-3"> · </span>
          <span className="fig">{km(listing.mileage_km)}</span>
        </p>
      </div>

      {/* --- what was parsed --------------------------------------------- */}
      <section className="panel">
        <p className="eyebrow">آنچه از آگهی استخراج شد</p>
        <dl className="m-0 grid gap-px bg-line border border-line
                       sm:grid-cols-3">
          <F k="سازنده" v={listing.make ?? '—'} />
          <F k="مدل" v={listing.model ?? '—'} />
          <F k="تیپ" v={listing.trim ?? 'ثبت‌نشده'} />
          <F k="سال (شمسی)" v={faPlain(listing.year_jalali)} num />
          <F k="کارکرد" v={km(listing.mileage_km)} num />
          <F k="قیمت پیشنهادی" v={toman(listing.asking_price_toman)} num />
          {Object.entries(listing.features).map(([k, v]) => (
            <F key={k} k={FEATURE_FA[k] ?? k}
               v={typeof v === 'number'
                 ? (v <= 1 && v >= 0 ? `${faNum(v * 100)}٪` : faNum(v))
                 : String(v ?? '—')}
               num />
          ))}
          {/* Pads the last row so the container's border colour does not show
              through the 1px gaps as an empty bar. */}
          {Array.from({
            length: (3 - ((6 + Object.keys(listing.features).length) % 3)) % 3,
          }).map((_, i) => (
            <div key={`pad-${i}`} className="bg-surface hidden sm:block"
                 aria-hidden />
          ))}
        </dl>
      </section>

      {/* --- the decision, or the refusal --------------------------------- */}
      {scored ? (
        <section className="panel">
          <div className="flex items-center gap-3 flex-wrap">
            <p className="eyebrow !mb-0">تصمیم</p>
            {scored.role_fa && (
              <span className="chip border-accent text-accent bg-accent-soft
                               !font-fa !normal-case !tracking-normal"
                    style={{ direction: 'rtl' }}>{scored.role_fa}</span>
            )}
          </div>

          <div className="mt-4 grid gap-px bg-line border border-line
                          sm:grid-cols-4">
            <Cell k="برآورد محافظه‌کارانه" v={toman(scored.estimate_toman)}
                  hint={compact(scored.estimate_toman)} />
            <Cell k="قیمت پیشنهادی" v={toman(scored.asking_price_toman)}
                  hint={compact(scored.asking_price_toman)} />
            <Cell k="هزینه‌ی انتظاری خسارت"
                  v={`− ${toman(scored.expected_damage_toman)}`}
                  tone="bad" hint="از صرفه کم می‌شود" />
            <Cell k={gain ? 'صرفه' : 'زیان'} strong
                  tone={gain ? 'good' : 'bad'}
                  v={`${gain ? '+' : '−'} ${toman(
                    Math.abs(scored.opportunity_toman))}`}
                  hint="برآورد − قیمت − خسارت" />
          </div>

          <TermBars terms={scored.terms} score={scored.score} />
        </section>
      ) : refused ? (
        <section className="panel border-bad">
          <div className="flex items-center gap-3 flex-wrap mb-3">
            <span className="chip border-bad text-bad bg-bad-soft">
              NOT SERVED
            </span>
            <p className="eyebrow !mb-0">برآوردی برای این خودرو سرو نمی‌شود</p>
          </div>
          <p className="m-0 text-[14px] leading-[1.95] max-w-[62ch]">
            آنچه بالا می‌بینی استخراج‌شده از خود آگهی است و به برآوردگر نیازی
            ندارد. برآورد قیمت و محاسبه‌ی صرفه به برآوردگری نیاز دارد که روی
            همین پیکره سنجیده و پذیرفته شده باشد، و چنین چیزی وجود ندارد.
          </p>
          <p className="m-0 mt-3 num text-[11.5px] text-ink-3 leading-6
                        whitespace-pre-wrap">{refused}</p>
        </section>
      ) : (
        <div className="panel text-ink-3 text-[13.5px]">
          در حال محاسبه‌ی تصمیم…
        </div>
      )}

      {/* --- what a published corpus does not carry ----------------------- */}
      <section className="panel border-dashed">
        <p className="eyebrow">عکس و متن آگهی — عمداً اینجا نیست</p>
        <p className="m-0 text-[13.5px] text-ink-2 leading-[1.95]
                      max-w-[68ch]">
          پیکره‌ی منتشرشده هیچ متنی از نوشته‌ی فروشنده را حمل نمی‌کند: نه
          عنوان، نه توضیح، نه خط کارکرد. آنچه لازم بوده پیش از انتشار از دل
          متن استخراج و خودِ متن دور ریخته شده است. این خلأ، خرابی نیست — قرارداد
          داده است.
        </p>
        {corpus && (
          <p className="m-0 mt-3 text-[12px] text-ink-3">
            منبع این پیکره: <span className="num">{corpus.source}</span>
          </p>
        )}
      </section>

      <div>
        <Link href="/search" className="btn">جست‌وجوی دیگر</Link>
      </div>
    </div>
  );
}

const FEATURE_FA: Record<string, string> = {
  risk: 'ریسک برآوردشده',
  ownership_risk: 'ریسک مالکیت',
  liquidity: 'نقدشوندگی',
  has_accident: 'نشانه‌ی تصادف',
};

function F({ k, v, num }: { k: string; v: string; num?: boolean }) {
  return (
    <div className="bg-surface px-3.5 py-2.5">
      <dt className="text-[11.5px] text-ink-3">{k}</dt>
      <dd className={`m-0 mt-0.5 text-[13.5px] ${num ? 'fig' : ''}`}>{v}</dd>
    </div>
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
