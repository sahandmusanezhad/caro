'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

/* The one input on the site.
 *
 * It takes a Persian sentence, not a grid of dropdowns, and that is the
 * product argument rather than a styling choice: «ماشین برای اسنپ، کم‌مصرف،
 * قطعاتش ارزون باشه، زیر ۸۰۰ میلیون» carries a use case, two constraints and
 * a budget, and a filter panel can represent exactly one of those four.
 *
 * What the box does NOT do is interpret anything. It hands the raw string to
 * `RuleIntentParser` and the results page prints back everything that was
 * understood, everything that was assumed, and everything that was not
 * understood at all.
 */

const EXAMPLES = [
  '۲۰۶',
  '۲۰۶ زیر ۸۰۰ میلیون',
  'ماشین برای اسنپ، کم‌مصرف، قطعاتش ارزون باشه، زیر ۸۰۰ میلیون',
  'ماشین اول خانواده، تصادفی نباشه، بودجه ۱.۲ میلیارد',
  'یه ۲۰۶ اتومات کم‌کارکرد تا ۱.۵ میلیارد میخوام',
];

export default function SearchBox({
  initial = '',
  autoFocus = false,
  showExamples = true,
}: {
  initial?: string;
  autoFocus?: boolean;
  showExamples?: boolean;
}) {
  const [q, setQ] = useState(initial);
  const router = useRouter();

  function go(text: string) {
    const t = text.trim();
    if (t.length < 2) return;
    router.push(`/search?q=${encodeURIComponent(t)}`);
  }

  return (
    <div>
      <form
        onSubmit={(e) => { e.preventDefault(); go(q); }}
        className="flex gap-2 flex-wrap"
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoFocus={autoFocus}
          placeholder="چه ماشینی می‌خواهی؟ به فارسی و با جمله‌ی خودت بنویس"
          aria-label="پرسش"
          className="flex-1 min-w-[260px] bg-surface border border-line
                     rounded-[3px] px-4 py-3 text-[15px] text-ink
                     placeholder:text-ink-3 focus:border-accent
                     transition-colors"
        />
        <button type="submit" className="btn-solid px-7" disabled={q.trim().length < 2}>
          جست‌وجو
        </button>
      </form>

      {showExamples && (
        <div className="mt-3 flex gap-1.5 flex-wrap items-center">
          <span className="text-[12px] text-ink-3 ml-1">مثلاً</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => { setQ(ex); go(ex); }}
              className="text-[12.5px] bg-surface border border-line
                         rounded-[2px] px-2.5 py-1 text-ink-2
                         hover:border-line-2 hover:text-ink transition-colors"
            >
              {ex}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
