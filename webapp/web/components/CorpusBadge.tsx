'use client';

import { useEffect, useState } from 'react';
import { api, shortSha, type CorpusResponse } from '@/lib/api';
import { faNum } from '@/lib/format';
import TechDetail from '@/components/TechDetail';

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
 *
 * When nothing may be served the chip reads the FAULT CODE, not the kind. Two
 * different things arrive as UNUSABLE — a file that will not load, and a run
 * that is not on disk — and «CORPUS UNUSABLE» over a missing run sends the
 * reader to inspect an artifact that is fine, or to look for one that was
 * never there.
 */
export default function CorpusBadge() {
  const [c, setC] = useState<CorpusResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    api.corpus()
      .then((r) => { if (alive) setC(r); })
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

  const broken = c.status.kind === 'UNUSABLE';
  const notFound = c.fault?.code === 'RUN_NOT_FOUND';
  const real = c.status.kind === 'REAL';
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
        {broken
          ? (notFound ? 'RUN NOT FOUND' : 'CORPUS UNUSABLE')
          : `${real ? 'REAL DATA' : 'SYNTHETIC'} · ${faNum(c.corpus.rows)}`}
      </button>

      {open && (
        <div
          className="absolute end-0 top-[calc(100%+8px)] z-20 w-[330px] panel
                     shadow-lg text-[13px] leading-7"
        >
          <p className="eyebrow">{c.corpus.label_fa}</p>
          <p className="m-0 mb-3 text-ink-2">{c.corpus.note_fa}</p>
          {c.fault && (
            <div className="mb-3">
              <p className="m-0 text-[12.5px] leading-6 text-bad">
                {c.fault.fa}
              </p>
              <TechDetail message={`${c.fault.code} — ${c.fault.message}`} />
            </div>
          )}
          <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1
                         text-[12.5px]">
            <dt className="text-ink-3">منبع</dt>
            <dd className="m-0 num text-[11.5px]">{c.corpus.source}</dd>
            <dt className="text-ink-3">ردیف</dt>
            <dd className="m-0 fig">{faNum(c.corpus.rows)}</dd>
            <dt className="text-ink-3">دروازه</dt>
            <dd className="m-0">
              {c.status.gated
                ? <span className="text-good">عبور کرده — رتبه‌بندی سرو می‌شود</span>
                : <span className="text-bad">عبور نکرده — رتبه‌بندی سرو نمی‌شود</span>}
            </dd>
          </dl>

          {/* The digest, or the reason there is none. Both are stated; a
              blank row would leave the reader unable to tell which. */}
          <div className="mt-3 pt-3 border-t border-line">
            {c.corpus.identity ? (
              <>
                <p className="m-0 text-[11.5px] text-ink-3">
                  شناسه‌ی شواهد
                </p>
                <p className="m-0 mt-1 num text-[12px] leading-6 break-all"
                   title={c.corpus.identity.sha256}>
                  {c.corpus.identity.run_id} · SHA-256 {shortSha(c.corpus.identity.sha256)}
                </p>
                <p className="m-0 mt-1.5 text-[11px] text-ink-3 leading-5">
                  همین عدد را با <span className="num">sha256sum</span> روی
                  خود فایل می‌گیری.
                </p>
              </>
            ) : (
              <p className="m-0 text-[11.5px] text-ink-3 leading-6">
                {notFound
                  ? 'شناسه‌ی شواهد وجود ندارد — فایلی که انتخاب شده روی دیسک '
                    + 'نیست، پس چیزی برای hash گرفتن نیست.'
                  : broken
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
