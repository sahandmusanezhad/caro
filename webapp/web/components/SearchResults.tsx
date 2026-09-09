'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { api, type SearchResponse, type WeightSet } from '@/lib/api';
import { faNum, faPlain, km, modelLabel, toman } from '@/lib/format';
import IntentPanel from '@/components/IntentPanel';
import ListingCard from '@/components/ListingCard';
import SearchBox from '@/components/SearchBox';
import WeightSliders from '@/components/WeightSliders';

/* The results screen, including the screen where there are no results to give.
 *
 * Four states, and the third is the one this project is actually about:
 *
 *   loading    nothing is claimed yet
 *   error      the API is unreachable, said plainly
 *   REFUSED    the estimator has not cleared the gate on this corpus, so no
 *              shortlist exists. The intent, the candidate count and the
 *              matching listings are still shown — evidence without a
 *              recommendation — and the page says why it is silent.
 *   served     a ranked shortlist with the arithmetic on every card
 *
 * The refusal is a 200 from the API and a first-class screen here. Rendering
 * it as an error page would tell the user something broke; nothing has.
 */
export default function SearchResults() {
  const params = useSearchParams();
  const router = useRouter();
  const q = params.get('q') ?? '';

  const [data, setData] = useState<SearchResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);

  useEffect(() => {
    if (!q) { setData(null); return; }
    let alive = true;
    setBusy(true); setErr(null);
    api.search(q, 8)
      .then((r) => { if (alive) { setData(r); setErr(null); } })
      .catch((e) => { if (alive) { setErr(String(e.message ?? e)); setData(null); } })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [q]);

  const reweight = useCallback((w: WeightSet) => {
    setBusy(true);
    api.reweight(q, w, 8)
      .then((r) => setData((prev) => (prev ? { ...prev, ...r } : r)))
      .catch((e) => setErr(String(e.message ?? e)))
      .finally(() => setBusy(false));
  }, [q]);

  const toggle = useCallback((id: string) => {
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id)
      : p.length >= 4 ? p : [...p, id]));
  }, []);

  if (!q) {
    return (
      <div className="flex flex-col gap-6">
        <div>
          <p className="eyebrow">جست‌وجو</p>
          <h1 className="text-[26px] font-bold m-0 mb-5">
            پرسشت را به فارسی بنویس
          </h1>
          <SearchBox autoFocus />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <SearchBox initial={q} showExamples={false} />
      </div>

      {err && (
        <div className="panel border-bad">
          <p className="eyebrow !text-bad">سرویس در دسترس نیست</p>
          <p className="m-0 text-[14px] text-ink-2">{err}</p>
          <p className="m-0 mt-2 text-[12.5px] text-ink-3 num">
            uvicorn webapp.api.main:app --reload
          </p>
        </div>
      )}

      {!data && !err && (
        <div className="panel text-ink-3 text-[13.5px]">در حال محاسبه…</div>
      )}

      {data && (
        <>
          {/* corpus note — the label is in the header, the caveat is here */}
          <p className={`m-0 text-[12.5px] leading-7 border-e-2 ps-0 pe-3
            text-ink-2 ${
            data.corpus.kind === 'UNUSABLE' ? 'border-e-bad'
              : data.corpus.kind === 'REAL' ? 'border-e-good'
                : 'border-e-warn'}`}>
            {data.corpus.note_fa}
          </p>

          <div className="flex flex-wrap gap-x-7 gap-y-1 text-[13px]
                          text-ink-2">
            <span>بررسی‌شده <b className="fig">{faNum(data.considered)}</b></span>
            {/* The gap between these two is the whole story on a real corpus:
                a published artifact carries no price/mileage provenance, so
                eligibility fails closed and nothing is appraisable. Showing
                only the first number would hide it. */}
            <span className={data.appraisable === 0 && data.considered > 0
              ? 'text-warn' : undefined}>
              قابل ارزش‌گذاری <b className="fig">{faNum(data.appraisable)}</b>
            </span>
            {data.served && (
              <>
                <span>منطبق <b className="fig">{faNum(data.candidates)}</b></span>
                <span>در فهرست کوتاه <b className="fig">
                  {faNum(data.items.length)}</b></span>
              </>
            )}
            {!data.served && data.evidence?.length > 0 && (
              <span>شواهد نمایش‌داده‌شده <b className="fig">
                {faNum(data.evidence.length)}</b></span>
            )}
          </div>

          {data.relaxed && (
            <div className="panel border-warn bg-warn-soft/40">
              <p className="eyebrow !text-warn">قید‌ها شل شد</p>
              <p className="m-0 text-[13.5px] text-ink-2">
                {data.relaxation_fa}
              </p>
              <p className="m-0 mt-2 text-[12px] text-ink-3">
                یک فهرست خالی بدون توضیح، بدترین پاسخ ممکن است. CARO به‌جای آن
                می‌گوید کدام قید را و به چه اندازه شل کرده است.
              </p>
            </div>
          )}

          <IntentPanel intent={data.intent} />

          {!data.served ? (
            <>
              <section className="panel border-bad">
                <div className="flex items-center gap-3 flex-wrap mb-3">
                  <span className="chip border-bad text-bad bg-bad-soft">
                    NOT SERVED
                  </span>
                  <p className="eyebrow !mb-0">رتبه‌بندی سرو نمی‌شود</p>
                </div>
                <p className="m-0 text-[15px] leading-[1.95] max-w-[62ch]">
                  {data.refusal?.fa}
                </p>
                {data.refusal?.detail && (
                  <p className="m-0 mt-3 num text-[11.5px] text-ink-3
                                leading-6 whitespace-pre-wrap">
                    {data.refusal.detail}
                  </p>
                )}
                {/* Two different situations reach this panel and only one of
                    them is "not an error". A corrupt artifact IS an error; it
                    is merely being reported as a product state instead of a
                    500, so the operator sees it. Saying «این یک خطا نیست»
                    there would be false. */}
                <p className="m-0 mt-4 text-[12.5px] text-ink-3 max-w-[62ch]">
                  {data.corpus.kind === 'UNUSABLE'
                    ? 'این یک خطای واقعی است و به‌عمد به‌جای ۵۰۰ اینجا نشان '
                      + 'داده می‌شود تا دیده شود. تا وقتی حل نشده، به داده‌ی '
                      + 'ساختگی برنمی‌گردیم — بازگشت بی‌صدا از خودِ خطا بدتر '
                      + 'است، چون سایت سالم به‌نظر می‌رسد.'
                    : 'این یک خطا نیست. یک حالت محصول است: ادعا اجازه ندارد '
                      + 'از شواهدش جلو بزند، پس آنچه هست را نشان می‌دهیم و '
                      + 'آنچه نیست را نمی‌سازیم.'}
                </p>
              </section>

              {data.evidence?.length > 0 && (
                <section>
                  <p className="eyebrow">
                    شواهد — آگهی‌های منطبق، بدون برآورد و بدون ترتیب
                  </p>
                  <div className="border border-line bg-surface rounded-[3px]
                                  overflow-x-auto">
                    <table className="w-full border-collapse text-[13px]
                                      min-w-[520px]">
                      <thead>
                        <tr className="text-ink-3 text-[11.5px]">
                          {['خودرو', 'مدل', 'کارکرد', 'قیمت پیشنهادی', ''].map(
                            (h) => (
                              <th key={h} className="text-right font-normal
                                                     px-4 py-2.5 border-b
                                                     border-line">{h}</th>
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
                            <td className="px-4 py-2.5 border-b border-line">
                              <Link href={`/car/${encodeURIComponent(r.id)}`}
                                    className="text-accent hover:underline
                                               text-[12.5px]">
                                پرونده
                              </Link>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}
            </>
          ) : (
            <>
              <WeightSliders weights={data.intent.weights}
                             onApply={reweight} busy={busy} />

              {picked.length > 1 && (
                <div className="flex items-center gap-3 flex-wrap panel
                                !py-3.5">
                  <span className="text-[13px] text-ink-2">
                    <b className="num">{faPlain(picked.length)}</b> خودرو
                    انتخاب شده
                  </span>
                  <button
                    type="button"
                    className="btn-solid !py-1.5 !px-4 !text-[13px]"
                    onClick={() => router.push(
                      `/compare?ids=${picked.map(encodeURIComponent).join(',')}`
                      + `&q=${encodeURIComponent(q)}`)}
                  >
                    مقایسه کن
                  </button>
                  <button type="button"
                          className="text-[12.5px] text-ink-3 hover:text-ink"
                          onClick={() => setPicked([])}>
                    پاک کن
                  </button>
                </div>
              )}

              <div className="flex flex-col gap-4">
                {data.items.map((it) => (
                  <ListingCard key={it.id} item={it}
                               selected={picked.includes(it.id)}
                               onToggle={toggle} />
                ))}
              </div>

              {data.items.length === 0 && (
                <div className="panel text-[13.5px] text-ink-2">
                  هیچ آگهی‌ای با این قیدها پیدا نشد و شل‌کردن قیدها هم چیزی
                  اضافه نکرد. جمله را کمی بازتر بنویس.
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
