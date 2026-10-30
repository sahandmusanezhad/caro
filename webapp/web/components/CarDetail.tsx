'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  ApiError, api, type CompareResponse, type CorpusMeta, type EvidenceItem,
  type Fault, type ListingResponse, type ScoredItem,
} from '@/lib/api';
import {
  NOT_A_CAR_FA, askingPrice, classLabel, compact, conditionLabel, faNum,
  faPlain,
  isAppraisalRow, isVehicleClass, modelLabel, odometer, provinceLabel, toman,
  trimLabel,
} from '@/lib/format';
import SaveButton from '@/components/SaveButton';
import TechDetail from '@/components/TechDetail';
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
 *
 * Three ways this page can have no car, and they are not the same sentence:
 *
 *   blocked    the API answered with a fault. Two kinds, and the difference
 *              is what the page is allowed to say:
 *                source    no corpus was read (RUN_NOT_FOUND, CORPUS_INVALID).
 *                          «پیدا نشد» would be false — the car may be sitting
 *                          right there; we have nowhere to look.
 *                resource  a corpus WAS read and does not hold this id
 *                          (LISTING_NOT_FOUND). That is ours to say.
 *   no_answer  nothing came back at all, or something answered that was not
 *              this API. No fault, so no reason beyond the status.
 *   loading    none of the above has happened yet.
 *
 * All three were one branch printing «پیدا نشد» until the API could put a
 * whole deployment in the first state: with `CARO_RUN` naming a run that is
 * not on disk, every car on the site reported itself missing.
 *
 * All three are about the LISTING. A decision that does not come back is not
 * a fourth: the listing did come back, so its file is drawn, and only the
 * decision's own panel says the decision did not arrive (`unanswered`). It
 * used to be drawn as the page failing — «هیچ چیزی نمی‌دانیم» under a listing
 * that had just arrived, or «این آگهی در پیکره‌ی جاری نیست» about one the
 * corpus had just returned — and the first was seen on the deployed site,
 * when a network change dropped the second request.
 *
 * Where that is decided. The effect in `CarDetail` only records what each
 * request came to, as data — an `Outcome` — and `detailScreen` decides from
 * the two what the page is. It fetches nothing, so every state this page can
 * be in can be reached without a network. What stays out of its reach is the
 * effect itself: that it records what it was given, and asks for a decision
 * exactly when `asksForDecision` says to.
 */

/* Codes that mean NO CORPUS WAS READ. The page may not name a car in this
   state — not even to say it is absent. */
const SOURCE_FAULTS = new Set(['CORPUS_INVALID', 'RUN_NOT_FOUND']);

/** What one request came to — as data, not as a thrown error, so the page can
 *  be decided from it by a function that fetches nothing. `fault` is the
 *  envelope's, and only this API sends one: a proxy, a gateway or a dead
 *  socket leave it null, and the status is all there is.
 *
 *  Held as `listingOutcome`, never `listing`: tests/test_corpus.py reads
 *  every `listing.X` in this file as a field the detail page draws, and an
 *  outcome named `listing` put `k` and `body` on that list. */
export type Outcome<T> =
  | { k: 'pending' }
  | { k: 'ok'; body: T }
  | { k: 'failed'; status: number; message: string; fault: Fault | null };

type Failed = Extract<Outcome<unknown>, { k: 'failed' }>;

/** What the page is. `blocked` and `no_answer` are the two ways it has no
 *  listing to draw; `file` has one, and a decision in some state beside it. */
export type Screen =
  | { k: 'loading' }
  | { k: 'blocked'; fault: Fault }
  | { k: 'no_answer'; message: string }
  | { k: 'file'; listing: EvidenceItem; corpus: CorpusMeta | null;
      decision: Decision };

export type Decision =
  | { k: 'not_asked' }
  | { k: 'deciding' }
  | { k: 'scored'; row: ScoredItem }
  | { k: 'refused'; message: string }
  | { k: 'unanswered'; message: string };

/* The API answered with no listing and no fault, which the contract does not
   allow: `listing` is null only when UNUSABLE, and UNUSABLE carries its fault.
   Written out rather than asserted — a page that throws because a field it
   expected was absent is a worse answer than a page that says less. */
const NO_CORPUS: Fault = {
  code: 'CORPUS_INVALID',
  message: 'the corpus could not be read',
  fa: 'پیکره‌ای بارگذاری نشده است، پس چیزی سرو نمی‌شود.',
  still_available: [],
};

/** Whether a listing gets a decision asked for. One that is not a car does
 *  not: an estimate of an assignment is the mistake D52 exists to prevent. */
export function asksForDecision(r: ListingResponse): boolean {
  return r.listing !== null && isVehicleClass(r.listing.product_class);
}

/** The page, from what its two requests came to. `compareOutcome` is null
 *  until a decision is asked for — and, for a listing that is not a car,
 *  always. */
export function detailScreen(
  listingOutcome: Outcome<ListingResponse>,
  compareOutcome: Outcome<CompareResponse> | null,
): Screen {
  if (listingOutcome.k === 'pending') return { k: 'loading' };
  if (listingOutcome.k === 'failed') return fromFailure(listingOutcome);
  const r = listingOutcome.body;
  // Null only ever means UNUSABLE — see lib/api.ts.
  if (r.listing === null) return { k: 'blocked', fault: r.fault ?? NO_CORPUS };
  return { k: 'file', listing: r.listing, corpus: r.corpus,
           decision: decisionFor(r.listing, compareOutcome) };
}

/* A 404 from this API carries the envelope, so the reason is typed and in
   Persian. Only something that is NOT this API — a proxy, a dead socket —
   arrives without one, and that is `no_answer`. */
function fromFailure(f: Failed): Screen {
  return f.fault ? { k: 'blocked', fault: f.fault }
    : { k: 'no_answer', message: f.message };
}

function decisionFor(
  listing: EvidenceItem, compareOutcome: Outcome<CompareResponse> | null,
): Decision {
  if (!isVehicleClass(listing.product_class)) return { k: 'not_asked' };
  // The listing is here and its decision is not. That is a fact about the
  // decision, so it is drawn where the decision would have been. Whatever the
  // failure was — no answer, something that was not this API, or this API's
  // own fault — it is not a statement about the car, so it replaces nothing
  // the listing said.
  if (compareOutcome?.k === 'failed') {
    return { k: 'unanswered', message: compareOutcome.message };
  }
  if (compareOutcome?.k !== 'ok') return { k: 'deciding' };
  return decisionOf(compareOutcome.body);
}

/* What a compare answer decides for one car. The effect reads each answer
   through this before keeping it, so a body it cannot read is a failed
   request — as it always was — and never a page that throws while drawing. */
function decisionOf(c: CompareResponse): Decision {
  if (c.status.served && c.rows.length) return { k: 'scored', row: c.rows[0] };
  // `message`, not `fa`: this feeds the technical detail, and the Persian
  // explanation is the prose the panel already carries. The branch is only
  // reachable when a corpus WAS read, so ESTIMATOR_NOT_GATED is the only
  // fault that can arrive and that prose is right for it. The `blocked`
  // screen is where the cause varies, and there the Persian is read off the
  // fault.
  return {
    k: 'refused',
    message: c.fault?.message ?? 'no estimator is gated on this corpus',
  };
}

/* A request that threw, as an Outcome. The message is the error's own, as the
   page has always shown it. */
function failure(e: unknown): Failed {
  if (e instanceof ApiError) {
    return {
      k: 'failed', status: e.status, message: e.message, fault: e.fault,
    };
  }
  const m = (e as { message?: unknown } | null)?.message;
  return { k: 'failed', status: 0, message: String(m ?? e), fault: null };
}

export default function CarDetail({ id }: { id: string }) {
  const [listingOutcome, setListingOutcome] =
    useState<Outcome<ListingResponse>>({ k: 'pending' });
  const [compareOutcome, setCompareOutcome] =
    useState<Outcome<CompareResponse> | null>(null);

  useEffect(() => {
    let alive = true;
    // A new id starts from nothing. No link on the site goes from one car to
    // another, but a file must never be drawn under an id it is not for.
    setListingOutcome({ k: 'pending' });
    setCompareOutcome(null);
    api.listing(id)
      .then((r) => {
        const ask = asksForDecision(r);     // reads the body — see decisionOf
        if (!alive) return;
        setListingOutcome({ k: 'ok', body: r });
        if (!ask) return;
        setCompareOutcome({ k: 'pending' });
        api.compare([id])
          .then((c) => {
            decisionOf(c);
            if (alive) setCompareOutcome({ k: 'ok', body: c });
          })
          .catch((e) => { if (alive) setCompareOutcome(failure(e)); });
      })
      .catch((e) => { if (alive) setListingOutcome(failure(e)); });
    return () => { alive = false; };
  }, [id]);

  return <CarDetailView id={id} listingOutcome={listingOutcome}
                        compareOutcome={compareOutcome} />;
}

/* The page, drawn from the two outcomes. Pure, like `ListingFile` below:
 * nothing is fetched here, so any state the page can be in can be drawn from
 * data. */
export function CarDetailView({
  id, listingOutcome, compareOutcome,
}: {
  id: string;
  listingOutcome: Outcome<ListingResponse>;
  compareOutcome: Outcome<CompareResponse> | null;
}) {
  const s = detailScreen(listingOutcome, compareOutcome);

  if (s.k === 'blocked') {
    const noCorpus = SOURCE_FAULTS.has(s.fault.code);
    return (
      <div className="panel border-bad">
        <div className="flex items-center gap-3 flex-wrap mb-3">
          {/* NOT SERVED, not the fault code. The code is already in the badge
              that never leaves the header; repeating it here would put the
              same words twice on one screen. This chip says what is true of
              THIS page, and the reason comes from the fault below it. */}
          <span className="chip border-bad text-bad bg-bad-soft">
            NOT SERVED
          </span>
          <p className="eyebrow !mb-0">
            {noCorpus ? 'این صفحه چیزی نشان نمی‌دهد، چون پیکره‌ای خوانده نشده'
              : 'این آگهی در پیکره‌ی جاری نیست'}
          </p>
        </div>
        <p className="m-0 text-[15px] leading-[1.95] max-w-[62ch]">
          {s.fault.fa}
        </p>
        {/* The distinction the old «پیدا نشد» destroyed, said out loud — and
            only in the state where it is true. */}
        {noCorpus && (
          <p className="m-0 mt-4 text-[12.5px] text-ink-3 max-w-[62ch]">
            پیکره‌ای خوانده نشده که بشود در آن دنبال{' '}
            <span className="num">{id}</span> گشت. پس نمی‌گوییم این آگهی وجود
            ندارد — دربارهٔ خودش هیچ ادعایی نمی‌کنیم؛ این جمله دربارهٔ منبع
            است، نه دربارهٔ خودرو.
          </p>
        )}
        {s.fault.message && <TechDetail message={s.fault.message} />}
        <Link href="/search" className="btn mt-4 inline-block">
          برگرد به جست‌وجو
        </Link>
      </div>
    );
  }

  if (s.k === 'no_answer') {
    return (
      <div className="panel border-bad">
        <p className="eyebrow !text-bad">پاسخی نرسید</p>
        <p className="m-0 text-[14px] text-ink-2 max-w-[62ch]">
          سرویس جواب نداد یا جوابی داد که از این API نبود، پس دربارهٔ این
          خودرو هیچ چیزی نمی‌دانیم — نه اینکه پیدا نشد.
        </p>
        <TechDetail message={s.message} />
        <Link href="/search" className="btn mt-4 inline-block">
          برگرد به جست‌وجو
        </Link>
      </div>
    );
  }

  if (s.k === 'loading') {
    return <div className="panel text-ink-3 text-[13.5px]">در حال بارگذاری…</div>;
  }

  const d = s.decision;
  return (
    <ListingFile id={id} listing={s.listing} corpus={s.corpus}
                 scored={d.k === 'scored' ? d.row : null}
                 refused={d.k === 'refused' ? d.message : null}
                 unanswered={d.k === 'unanswered' ? d.message : null} />
  );
}

/* What a loaded listing looks like, with nothing fetched here.
 *
 * Pure on purpose. `tests/test_screens.py` renders exactly this
 * component with what the API really returns — for a vehicle, for the
 * assignment in run11 and for a row whose class nobody determined — and
 * checks the markup a reader would get. A branch that can only be reached
 * through `useEffect` is a branch no test can see. */
export function ListingFile({
  id, listing, corpus, scored, refused, unanswered = null,
}: {
  id: string;
  listing: EvidenceItem;
  corpus: CorpusMeta | null;
  scored: ScoredItem | null;
  refused: string | null;
  /** Why the decision did not arrive, when it did not. */
  unanswered?: string | null;
}) {
  if (!isVehicleClass(listing.product_class)) {
    return <NotACarFile id={id} listing={listing} corpus={corpus} />;
  }

  const gain = scored ? scored.opportunity_toman >= 0 : false;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="eyebrow">پرونده‌ی خودرو · <span className="num">{id}</span></p>
        <h1 className="m-0 text-[28px] font-bold">
          {modelLabel(listing.model_key)}
          {/* `bdi`, not `span`: the year must not join the name's last run.
              A name that ends in a trim code or a number — «۱۳۱ SE»,
              «manualr ۲۰۲۲» — is a left-to-right run, and a plain span of
              digits after it became part of that run: drawn on the name's
              wrong side with no gap, «SE۱۳۹۶», or read as one number,
              «۲۰۲۲۱۴۰۱». Measured on run11's car pages, 69 of 75 headings
              did that. Isolated, the year is a unit of its own and the line
              puts it after the name, where the margin keeps them apart. */}
          <bdi className="fig text-ink-2 text-[22px] mr-3">
            {faPlain(listing.year_jalali)}
          </bdi>
        </h1>
        {/* The price by the rule search and compare draw it with,
            `askingPrice()`: a figure that is not a cash asking price is said
            as what it is. With `toman()` here, the two run11 listings whose
            price is «توافقی» everywhere else were «ثبت‌نشده» on this page. */}
        <p className="mt-2 mb-0 text-[15px] text-ink-2">
          <span className="fig">
            {askingPrice(listing.asking_price_toman, listing.price_status,
                         listing.price_kind)}
          </span>
          <span className="text-ink-3"> · </span>
          <span className="fig">
            {odometer(listing.mileage_km, listing.mileage_status,
                      isAppraisalRow(listing))}
          </span>
        </p>
        {/* Keep it, see its model's every listing, or open it where it was
            published: what a price-comparison page offers beside an item. */}
        <div className="mt-4 flex flex-wrap gap-2 items-center">
          <SaveButton id={id} />
          {listing.model && (
            <Link className="btn no-underline"
                  href={`/model/${encodeURIComponent(listing.make ?? '_')}/${encodeURIComponent(listing.model)}`}>
              همه‌ی آگهی‌های {modelLabel(listing.model)}
            </Link>
          )}
          {listing.url && /^https:\/\//.test(listing.url) && (
            <a className="btn no-underline" href={listing.url} target="_blank"
               rel="noopener noreferrer nofollow">
              دیدن آگهی در منبع ↗
            </a>
          )}
        </div>
      </div>

      {/* --- what was parsed --------------------------------------------- */}
      <section className="panel">
        <p className="eyebrow">آنچه از آگهی استخراج شد</p>
        <dl className="m-0 grid tiles
                       sm:grid-cols-3">
          {/* Through modelLabel, like the heading above — a taxonomy key is
              an internal name and «pride» has no business on the page. */}
          <F k="سازنده" v={listing.make ? modelLabel(listing.make) : '—'} />
          <F k="مدل" v={listing.model ? modelLabel(listing.model) : '—'} />
          <F k="تیپ" v={trimLabel(listing.trim)} />
          <F k="سال (شمسی)" v={faPlain(listing.year_jalali)} num />
          <F k="کارکرد" v={odometer(listing.mileage_km, listing.mileage_status,
                                     isAppraisalRow(listing))} num />
          <F k="قیمت پیشنهادی" v={askingPrice(listing.asking_price_toman,
                                             listing.price_status,
                                             listing.price_kind)} num />
          <F k="رنگ" v={listing.color ?? 'ثبت‌نشده'} />
          <F k="وضعیت بدنه" v={conditionLabel(listing.condition)} />
          <F k="استان" v={provinceLabel(listing.province,
                                         listing.province_source)} />
          {/* Nine cells. «استان» is back, drawn with how it was known:
              docs/FIELD_PROVENANCE.md measures it on the corpus served and
              allows this surface, and `provinceLabel` never draws a
              province read from a city's name as one the listing stated.
              «گیربکس», «سوخت» and «نوع فروشنده» stay out: the first two are
              carried and allowed on no surface of this page, and seller
              type is still PENDING_LIVE_VALIDATION. All four were here
              once, falling back to «ثبت‌نشده» — a sentence about the
              LISTING — while no published corpus carried them.

              Do not add one back by hand: tests/test_corpus.py reads this
              file and fails on any `listing.X` the document does not allow
              on this surface. */}
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

          <div className="mt-4 grid tiles
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

          {/* Derived, not parsed. These come out of `features_from_listing`
              during appraisal and exist only on a row that was scored — which
              is why they sit here and not in the grid above. */}
          {Object.keys(scored.features).length > 0 && (
            <dl className="m-0 mt-4 flex flex-wrap gap-x-7 gap-y-1
                           text-[13px]">
              {Object.entries(scored.features).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="text-ink-3">{FEATURE_FA[k] ?? k}</dt>
                  <dd className="m-0 fig">
                    {v <= 1 && v >= 0 ? `${faNum(v * 100)}٪` : faNum(v)}
                  </dd>
                </div>
              ))}
            </dl>
          )}

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
          <TechDetail message={refused} />
        </section>
      ) : unanswered ? (
        <section className="panel border-bad">
          {/* The listing came back and its decision did not. What is above
              is the listing's own and stays: a request that failed says
              nothing about the car, so it takes nothing with it. No «NOT
              SERVED» chip either — that names a refusal, and this page never
              received one. */}
          <p className="eyebrow !text-bad">تصمیمی به این صفحه نرسید</p>
          <p className="m-0 text-[14px] leading-[1.95] max-w-[62ch]">
            آنچه بالا می‌بینی از خود آگهی آمده و به این بخش وابسته نیست.
            درخواستِ تصمیم — برآورد قیمت و محاسبه‌ی صرفه — پاسخی نگرفت که
            بشود نشانش داد؛ پس اینجا نه برآوردی هست و نه ادعایی درباره‌ی اینکه
            برآوردی هست یا نیست.
          </p>
          <TechDetail message={unanswered} />
        </section>
      ) : (
        <div className="panel text-ink-3 text-[13.5px]">
          در حال محاسبه‌ی تصمیم…
        </div>
      )}

      <Provenance corpus={corpus} />

      <div>
        <Link href="/search" className="btn">جست‌وجوی دیگر</Link>
      </div>
    </div>
  );
}

/* A listing that is in the corpus and is not a car.
 *
 * It is not refused: the listing exists, and what it says is a fact worth
 * showing — the assignment in run11 has a make, a model, a year and an
 * amount. What changes is the frame. The page says what the listing IS
 * before anything else, calls it a listing and not a car, prints the amount
 * without calling it a car's asking price, and asks for no decision. */
function NotACarFile({
  id, listing, corpus,
}: {
  id: string;
  listing: EvidenceItem;
  corpus: CorpusMeta | null;
}) {
  const pc = listing.product_class;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="eyebrow">پرونده‌ی آگهی · <span className="num">{id}</span></p>
        <h1 className="m-0 text-[28px] font-bold">
          {pc === 'unknown' ? 'نوع این آگهی تعیین نشده است'
            : `این آگهی خودرو نیست — ${classLabel(pc)}`}
        </h1>
      </div>

      <section className="panel border-bad">
        <div className="flex items-center gap-3 flex-wrap mb-3">
          <span className="chip border-bad text-bad bg-bad-soft
                           !font-fa !normal-case !tracking-normal">
            {classLabel(pc)}
          </span>
          <p className="eyebrow !mb-0">{NOT_A_CAR_FA}</p>
        </div>
        <p className="m-0 text-[14px] leading-[1.95] max-w-[62ch]">
          {pc === 'assignment'
            ? 'حواله ادعایی است بر خودرویی که هنوز تحویل نشده، نه خود خودرو. '
              + 'سال، مدل و مبلغی که پایین می‌بینی درباره‌ی همین حواله است؛ '
              + 'پس اینجا نه قیمت یک خودرو گفته می‌شود و نه برآوردی، و در '
              + 'جست‌وجو هم این آگهی به‌جای خودرو نشان داده نمی‌شود.'
            : pc === 'unknown'
              ? 'منبع نگفته این آگهی خودرو است یا چیز دیگری، و نوعی که تعیین '
                + 'نشده به «خودرو» تبدیل نمی‌شود. آنچه پایین می‌بینی فقط چیزی '
                + 'است که خود آگهی گفته.'
              : 'این آگهی در پیکره هست، ولی از نوعی است که خودرو نیست. آنچه '
                + 'پایین می‌بینی فقط چیزی است که خود آگهی گفته.'}
        </p>
      </section>

      <section className="panel">
        <p className="eyebrow">آنچه خود آگهی می‌گوید</p>
        <dl className="m-0 grid tiles
                       sm:grid-cols-3">
          <F k="سازنده" v={listing.make ? modelLabel(listing.make) : '—'} />
          <F k="مدل" v={listing.model ? modelLabel(listing.model) : '—'} />
          <F k="تیپ" v={trimLabel(listing.trim)} />
          <F k="سال (شمسی)" v={faPlain(listing.year_jalali)} num />
          <F k="مبلغ اعلام‌شده" v={toman(listing.asking_price_toman)} num />
        </dl>
      </section>

      <Provenance corpus={corpus} />

      <div>
        <Link href="/search" className="btn">جست‌وجوی دیگر</Link>
      </div>
    </div>
  );
}

/* What a published corpus does not carry, and which bytes this page rests
   on. Shared by both files: it is as true of an assignment as of a car. */
function Provenance({ corpus }: { corpus: CorpusMeta | null }) {
  return (
    <section className="panel border-dashed">
      <p className="eyebrow">عکس و متن آگهی — عمداً اینجا نیست</p>
      <p className="m-0 text-[13.5px] text-ink-2 leading-[1.95]
                    max-w-[68ch]">
        پیکره‌ی منتشرشده هیچ متنی از نوشته‌ی فروشنده را حمل نمی‌کند: نه
        عنوان، نه توضیح، نه خط کارکرد. آنچه لازم بوده پیش از انتشار از دل
        متن استخراج و خودِ متن دور ریخته شده است. این خلأ، خرابی نیست — قرارداد
        داده است.
      </p>
      {/* Provenance, on the page where a buyer decides. `source` says which
          file; the digest says which bytes — and only the second is
          checkable, because two deployments can serve different files from
          one path and both report it honestly. */}
      {corpus && (
        <dl className="m-0 mt-4 pt-3 border-t border-line grid
                       grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
          <dt className="text-ink-3">منبع</dt>
          <dd className="m-0 num text-[11.5px]">{corpus.source}</dd>
          {corpus.identity ? (
            <>
              <dt className="text-ink-3">اجرا</dt>
              <dd className="m-0 num text-[11.5px]">
                {corpus.identity.run_id}
              </dd>
              <dt className="text-ink-3">SHA-256</dt>
              <dd className="m-0 num text-[11.5px] break-all">
                {corpus.identity.sha256}
              </dd>
            </>
          ) : (
            <>
              <dt className="text-ink-3">SHA-256</dt>
              <dd className="m-0 text-ink-3">
                ندارد — پیکره‌ی ساختگی فایلی برای hash گرفتن ندارد
              </dd>
            </>
          )}
        </dl>
      )}
    </section>
  );
}

/* SELLER_FA lived here — dealer / private / «نامشخص — نشان کسب‌وکاری روی
   آگهی نبود» — and had exactly one reader, the seller cell above. With the
   cell gone it is dead, and dead code beside a field that is coming back is
   how a stale label returns with it. Git has it; the day `seller_type`
   clears PENDING_LIVE_VALIDATION the labels get written against whatever
   that run actually observed, not against what we guessed in September. */

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
