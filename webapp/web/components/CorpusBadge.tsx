'use client';

import { useEffect, useState } from 'react';
import { api, shortSha, type CorpusInfo } from '@/lib/api';
import { faNum } from '@/lib/format';

/* The label that never leaves the screen.
 *
 * A listing card looks identical whether it came from a real Bama page or a
 * generated fixture, which is precisely why this sits in the layout rather
 * than on the results page: the moment the marker becomes something you can
 * navigate away from, it stops being a property of the data and becomes a
 * decoration.
 *
 * Three states, all of them stated rather than hidden:
 *   loading   the corpus is not known yet, so nothing is claimed
 *   error     the backend is unreachable — said plainly, not silently
 *   loaded    SYNTHETIC or REAL, with the row count and the source path
 */
export default function CorpusBadge() {
  const [c, setC] = useState<CorpusInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    api.corpus()
      .then((r) => { if (alive) setC(r.corpus); })
      .catch((e) => { if (alive) setErr(String(e.message ?? e)); });
    return () => { alive = false; };
  }, []);

  if (err) {
    return (
      <span className="chip border-bad text-bad bg-bad-soft" title={err}>
        API OFFLINE
      </span>
    );
  }

  if (!c) {
    return <span className="chip border-line text-ink-3">…</span>;
  }

  const broken = c.kind === 'UNUSABLE';
  const real = c.kind === 'REAL';
  const tone = broken
    ? 'border-bad text-bad bg-bad-soft'
    : real
      ? 'border-good text-good bg-good-soft'
      : 'border-warn text-warn bg-warn-soft';

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={`chip ${tone} cursor-pointer`}
      >
        {broken ? 'CORPUS UNUSABLE'
          : `${real ? 'REAL DATA' : 'SYNTHETIC'} · ${faNum(c.rows)}`}
      </button>

      {open && (
        <div
          className="absolute end-0 top-[calc(100%+8px)] z-20 w-[330px] panel
                     shadow-lg text-[13px] leading-7"
        >
          <p className="eyebrow">{c.label_fa}</p>
          <p className="m-0 mb-3 text-ink-2">{c.note_fa}</p>
          {c.fault && (
            <p className="m-0 mb-3 num text-[11px] leading-5 text-bad
                          bg-bad-soft border border-bad/40 rounded-[2px]
                          px-2.5 py-2 break-all">{c.fault}</p>
          )}
          <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1
                         text-[12.5px]">
            <dt className="text-ink-3">منبع</dt>
            <dd className="m-0 num text-[11.5px]">{c.source}</dd>
            <dt className="text-ink-3">ردیف</dt>
            <dd className="m-0 fig">{faNum(c.rows)}</dd>
            <dt className="text-ink-3">دروازه</dt>
            <dd className="m-0">
              {c.gated
                ? <span className="text-good">عبور کرده — رتبه‌بندی سرو می‌شود</span>
                : <span className="text-bad">عبور نکرده — رتبه‌بندی سرو نمی‌شود</span>}
            </dd>
          </dl>

          {/* The digest, or the reason there is none. Both are stated; a
              blank row would leave the reader unable to tell which. */}
          <div className="mt-3 pt-3 border-t border-line">
            {c.identity ? (
              <>
                <p className="m-0 text-[11.5px] text-ink-3">
                  شناسه‌ی شواهد
                </p>
                <p className="m-0 mt-1 num text-[12px] leading-6 break-all"
                   title={c.identity.sha256}>
                  {c.identity.run_id} · SHA-256 {shortSha(c.identity.sha256)}
                </p>
                <p className="m-0 mt-1.5 text-[11px] text-ink-3 leading-5">
                  همین عدد را با <span className="num">sha256sum</span> روی
                  خود فایل می‌گیری.
                </p>
              </>
            ) : (
              <p className="m-0 text-[11.5px] text-ink-3 leading-6">
                {broken
                  ? 'شناسه‌ی شواهد گرفته نشد — فایل هست ولی خوانده نمی‌شود، '
                    + 'پس hash آن چیزی را تأیید نمی‌کند.'
                  : 'شناسه‌ی شواهد ندارد — این پیکره از کد تولید می‌شود و '
                    + 'فایلی برای hash گرفتن وجود ندارد.'}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
