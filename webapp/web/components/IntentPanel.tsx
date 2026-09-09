'use client';

import type { Intent } from '@/lib/api';
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

  if (intent.models.length) {
    // Taxonomy keys are ASCII (`pride`, `206`); the panel shows the buyer
    // what CARO understood, so it shows it in their own script.
    known.push(['خودرو', intent.models
      .map((m) => MODEL_FA[m.toLowerCase()] ?? m).join('، ')]);
  }
  if (intent.budget_max_toman != null) {
    known.push([
      intent.budget_hard ? 'سقف بودجه' : 'سقف بودجه (انعطاف‌پذیر)',
      toman(intent.budget_max_toman),
    ]);
  }
  if (intent.budget_min_toman != null) {
    known.push(['کف بودجه', toman(intent.budget_min_toman)]);
  }
  if (intent.year_min != null) {
    known.push(['حداقل مدل', faPlain(intent.year_min)]);
  }
  if (intent.max_mileage_km != null) {
    known.push(['سقف کارکرد', `${faNum(intent.max_mileage_km)} کیلومتر`]);
  }
  if (intent.use_case && intent.use_case !== 'unspecified') {
    known.push(['کاربرد', USE_CASE_FA[intent.use_case] ?? intent.use_case]);
  }
  if (intent.risk_profile) {
    known.push(['پروفایل ریسک',
      RISK_FA[intent.risk_profile] ?? intent.risk_profile]);
  }
  if (intent.deal_breakers.length) {
    known.push(['خط قرمز', intent.deal_breakers
      .map((d) => BREAKER_FA[d] ?? d).join('، ')]);
  }

  return (
    <section className="panel">
      <p className="eyebrow">آنچه از جمله‌ی تو فهمیدیم</p>

      {known.length === 0 ? (
        <p className="m-0 text-[13.5px] text-ink-2">
          هیچ قید مشخصی در جمله پیدا نشد — پس هیچ فیلتری هم اعمال نشده است.
        </p>
      ) : (
        <dl className="m-0 grid gap-px bg-line border border-line
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
                                     border border-warn/40 rounded-[2px]
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
                               border-line rounded-[2px] px-2.5 py-1">
                {u}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
