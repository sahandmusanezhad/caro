'use client';

import { termLabel } from '@/lib/api';
import { fixed } from '@/lib/format';

/* Why this car ranked here, term by term.
 *
 * The score is a weighted sum, so it decomposes exactly — there is no residual
 * and nothing to round off. Showing the six contributions is not a courtesy:
 * a single number the user cannot decompose is a number they cannot disagree
 * with, and a recommendation nobody can disagree with is not a recommendation,
 * it is an instruction.
 *
 * Positive contributions run one way from the centre line and negative ones
 * the other, on a shared scale, so a big red `risk` bar next to a small green
 * `value` bar reads as what it is.
 */
export default function TermBars({
  terms,
  score,
}: {
  terms: Record<string, number>;
  score: number;
}) {
  const entries = Object.entries(terms);
  const span = Math.max(0.001, ...entries.map(([, v]) => Math.abs(v)));

  return (
    <div className="mt-4">
      <div className="flex items-baseline justify-between mb-2">
        <span className="text-[11.5px] text-ink-3">سهم هر مؤلفه در امتیاز</span>
        <span className="num text-[12px] text-ink-2">
          Σ = {fixed(score)}
        </span>
      </div>

      <ul className="m-0 p-0 list-none flex flex-col gap-1.5">
        {entries.map(([k, v]) => {
          const w = (Math.abs(v) / span) * 50;
          const pos = v >= 0;
          return (
            <li key={k} className="grid grid-cols-[7.5rem_1fr_4.5rem]
                                   items-center gap-2">
              <span className="text-[12.5px] text-ink-2">{termLabel(k)}</span>
              <span className="relative h-[7px] bg-sunk rounded-[1px]
                               overflow-hidden">
                {/* The page is right-to-left, so a positive contribution
                    grows toward the start of the line — the right — and a
                    negative one away from it. Mirroring a chart is not
                    decoration in RTL; a bar that grows leftward for "more"
                    reads as "less" to someone scanning from the right. */}
                <i
                  className={`absolute top-0 bottom-0 block ${
                    pos ? 'bg-good' : 'bg-bad'}`}
                  style={pos
                    ? { left: '50%', width: `${w}%` }
                    : { right: '50%', width: `${w}%` }}
                />
                <i className="absolute top-0 bottom-0 right-1/2 w-px
                              bg-line-2" />
              </span>
              <span className={`num text-[11.5px] text-left ${
                pos ? 'text-good' : 'text-bad'}`}>
                {v >= 0 ? `+${Math.abs(v).toFixed(3)}` : fixed(v)}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
