'use client';

import type { FilterKey, Intent } from '@/lib/api';
import { MODEL_FA, faNum, faPlain, toman } from '@/lib/format';

/* What CARO understood, what it assumed, and what it did not understand.
 *
 * The third column is the one that earns the panel. Every parser guesses;
 * the difference between a parser you can trust and one you cannot is whether
 * the guess is printed next to the result. `assumptions` and `unparsed` come
 * straight out of `IntentSpec` and are never summarised away here — an
 * assumption the buyer cannot see is one they cannot correct.
 */

const USE_CASE_FA: Record<string, string> = {
  ride_hailing: 'مسافرکشی (اسنپ/تپسی)',
  family_first_car: 'ماشین اول خانواده',
  commute: 'رفت‌وآمد شهری',
  resale_flip: 'خرید برای فروش مجدد',
  cargo: 'باربری',
  unspecified: 'مشخص نشده',
};

/* The keys are `RISK_PROFILE_QUANTILE` in caro/ranking.py. `balanced` is the
   default and was missing here, so every query with no risk cue printed the
   raw English token on the page. */
const RISK_FA: Record<string, string> = {
  risk_averse: 'ریسک‌گریز',
  balanced: 'متعادل',
  risk_tolerant: 'ریسک‌پذیر',
};

/* The keys are `DEAL_BREAKER_CUES` in caro/ranking.py. Each is phrased as the
   buyer's own requirement, not as the field name it filters on. */
const BREAKER_FA: Record<string, string> = {
  accident: 'تصادفی نباشد',
  repaint: 'رنگ‌شدگی نداشته باشد',
  unclear_documents: 'سند بی‌مشکل باشد',
  manual: 'دنده‌ای نباشد',
};

export default function IntentPanel({ intent }: { intent: Intent }) {
  const known: [string, string][] = [];
  // A constraint the filter panel stated says so beside its name: where the
  // sentence and the panel both state one, the panel's stands (the owner's
  // choice of 2026-11-25), and the reader must see which they are reading.
  const from = new Set(intent.from_filter ?? []);
  const by = (label: string, key: FilterKey) => (from.has(key) ? `${label} — از فیلتر` : label);

  if ((intent.makes ?? []).length) {
    known.push([by('برند', 'make'), intent.makes
      .map((m) => MODEL_FA[m.toLowerCase()] ?? m).join('، ')]);
  }
  if (intent.models.length) {
    // Taxonomy keys are ASCII (`pride`, `206`); the panel shows the buyer
    // what CARO understood, so it shows it in their own script.
    known.push([by('خودرو', 'model'), intent.models
      .map((m) => MODEL_FA[m.toLowerCase()] ?? m).join('، ')]);
  }
  if (intent.budget_max_toman != null) {
    known.push([
      by(intent.budget_hard ? 'سقف بودجه' : 'سقف بودجه (انعطاف‌پذیر)', 'budget'),
      toman(intent.budget_max_toman),
    ]);
  }
  if (intent.budget_min_toman != null) {
    known.push([by('کف بودجه', 'budget'), toman(intent.budget_min_toman)]);
  }
  if (intent.year_min != null) {
    known.push([by('حداقل مدل', 'year'), faPlain(intent.year_min)]);
  }
  if (intent.year_max != null) {
    known.push([by('حداکثر مدل', 'year'), faPlain(intent.year_max)]);
  }
  if (intent.min_mileage_km != null) {
    known.push([by('کف کارکرد', 'mileage'), `${faNum(intent.min_mileage_km)} کیلومتر`]);
  }
  if (intent.max_mileage_km != null) {
    known.push([by('سقف کارکرد', 'mileage'), `${faNum(intent.max_mileage_km)} کیلومتر`]);
  }
  if (intent.provinces.length) {
    // Several are any-of: a car in any of them meets it.
    known.push([by('استان', 'province'), intent.provinces.join('، ')]);
  }
  if (intent.use_case && intent.use_case !== 'unspecified') {
    known.push(['کاربرد', USE_CASE_FA[intent.use_case] ?? intent.use_case]);
  }
  // A risk profile weighs a ranking; the filter page asks for none, so it
  // is not said there (an intent with no sentence is the filter page's).
  if (intent.risk_profile && intent.query) {
    known.push(['پروفایل ریسک',
      RISK_FA[intent.risk_profile] ?? intent.risk_profile]);
  }
  if (intent.deal_breakers.length) {
    known.push(['خط قرمز', intent.deal_breakers
      .map((d) => BREAKER_FA[d] ?? d).join('، ')]);
  }

  return (
    <section className="panel">
      <p className="eyebrow">
        {!intent.query ? 'فیلترهایی که به‌کار رفت'
          : from.size ? 'آنچه از جمله‌ی تو و فیلترها فهمیدیم' : 'آنچه از جمله‌ی تو فهمیدیم'}
      </p>

      {known.length === 0 ? (
        <p className="m-0 text-[13.5px] text-ink-2">
          {!intent.query
            ? 'هیچ فیلتری انتخاب نشده — همه‌ی آگهی‌های این پیکره در نظر گرفته شد.'
            : 'هیچ قید مشخصی در جمله پیدا نشد — پس هیچ فیلتری هم اعمال نشده است.'}
        </p>
      ) : (
        <dl className="m-0 grid tiles
                       sm:grid-cols-3">
          {known.map(([k, v]) => (
            <div key={k} className="bg-surface px-3.5 py-2.5">
              <dt className="text-[11.5px] text-ink-3">{k}</dt>
              <dd className="m-0 text-[13.5px] mt-0.5">{v}</dd>
            </div>
          ))}
          {/* The 1px gaps are the container's background showing through, so
              a part-filled last row would show as a bar of border colour.
              These pad the row out; they carry nothing. */}
          {Array.from({ length: (3 - (known.length % 3)) % 3 }).map((_, i) => (
            <div key={`pad-${i}`} className="bg-surface hidden sm:block"
                 aria-hidden />
          ))}
        </dl>
      )}

      {intent.assumptions.length > 0 && (
        <div className="mt-4">
          <p className="text-[11.5px] text-ink-3 mb-1.5">
            فرض‌هایی که گذاشتیم — اگر غلط‌اند، جمله را عوض کن
          </p>
          <ul className="m-0 ps-0 list-none flex flex-col gap-1">
            {intent.assumptions.map((a) => (
              <li key={a} className="text-[13px] text-warn bg-warn-soft
                                     border border-warn/40 rounded-lg
                                     px-3 py-1.5">
                {a}
              </li>
            ))}
          </ul>
        </div>
      )}

      {intent.unparsed.length > 0 && (
        <div className="mt-4">
          <p className="text-[11.5px] text-ink-3 mb-1.5">
            بخش‌هایی که نفهمیدیم — نادیده گرفته شدند، حذف نشدند
          </p>
          <div className="flex flex-wrap gap-1.5">
            {intent.unparsed.map((u, i) => (
              <span key={`${u}-${i}`}
                    className="text-[12.5px] text-ink-3 bg-sunk border
                               border-line rounded-lg px-2.5 py-1">
                {u}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
