'use client';

import { useState } from 'react';
import { WEIGHT_FA, WEIGHT_KEYS, type WeightSet } from '@/lib/api';
import { pct } from '@/lib/format';

/* «بهترین» is a function, and this is where the user gets to edit it.
 *
 * The parser derives an opening set of weights from the query — a driver's
 * running cost outweighs their appetite for a bargain, a family's risk
 * outweighs both — and those are a starting point, not a verdict about the
 * buyer. Moving a slider re-scores the same candidate set through the same
 * ranker; nothing about the evidence changes, only the objective.
 *
 * That is the honest version of personalisation: not a hidden profile that
 * quietly reorders results, but six numbers on the screen that the user can
 * see, change, and reset.
 */
export default function WeightSliders({
  weights,
  onApply,
  busy,
}: {
  weights: WeightSet;
  onApply: (w: WeightSet) => void;
  busy?: boolean;
}) {
  const [w, setW] = useState<WeightSet>(weights);
  const [touched, setTouched] = useState(false);

  const total = WEIGHT_KEYS.reduce((s, k) => s + w[k], 0) || 1;

  function set(k: keyof WeightSet, v: number) {
    setTouched(true);
    setW((prev) => ({ ...prev, [k]: v }));
  }

  return (
    <section className="panel">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <p className="eyebrow !mb-0">وزن‌ها — «بهترین» را خودت تعریف کن</p>
        <span className="text-[11.5px] text-ink-3">
          نسبت‌ها نرمال می‌شوند؛ عدد مطلق مهم نیست
        </span>
      </div>

      <ul className="m-0 mt-4 p-0 list-none grid gap-x-8 gap-y-3
                     sm:grid-cols-2">
        {WEIGHT_KEYS.map((k) => (
          <li key={k} className="grid grid-cols-[6.5rem_1fr_3rem]
                                 items-center gap-2">
            <label htmlFor={`w-${k}`} className="text-[13px] text-ink-2">
              {WEIGHT_FA[k]}
            </label>
            <input
              id={`w-${k}`}
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={w[k]}
              onChange={(e) => set(k, Number(e.target.value))}
              className="w-full accent-[var(--accent)]"
            />
            <span className="num text-[12px] text-ink-2 text-left">
              {pct(w[k] / total)}
            </span>
          </li>
        ))}
      </ul>

      <div className="mt-5 flex gap-2 flex-wrap">
        <button
          type="button"
          className="btn-solid"
          disabled={!touched || busy}
          onClick={() => onApply(w)}
        >
          {busy ? 'در حال محاسبه…' : 'دوباره رتبه‌بندی کن'}
        </button>
        <button
          type="button"
          className="btn"
          disabled={!touched || busy}
          onClick={() => { setW(weights); setTouched(false); onApply(weights); }}
        >
          بازگشت به وزن‌های استنباط‌شده
        </button>
      </div>
    </section>
  );
}
