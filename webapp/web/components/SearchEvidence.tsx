import Link from 'next/link';
import type { ReactNode } from 'react';
import type { EvidenceItem, SearchResponse, UncheckedItem } from '@/lib/api';
import {
  UNCHECKED_FA, askingPrice, faNum, faPlain, isAppraisalRow, modelLabel,
  odometer, odometerWhy, provinceLabel,
} from '@/lib/format';

/* The evidence a refusal can still show, in two tables that never mix.
 *
 *   matched   every constraint the buyer stated was checked against a value
 *             the listing carries, and met
 *   apart     none was broken and at least one could not be checked, because
 *             the listing carries no value for it. Not a match, so never drawn
 *             under the heading that says «منطبق»; the cell beside its name
 *             says what is missing — beside it, so that a phone, which shows
 *             a table's first columns and scrolls for the rest, shows it.
 *
 * Each row says its province as the car page does, with how it was known —
 * «تهران — از روی نام شهر» where a city's name gave it — so that a province
 * the listing did not state is never drawn as one it did (D77, D81).
 *
 * The API decides which is which (`webapp/api/constraints.py`); this only
 * draws what it was sent. Each table is the first k of its kind, and the line
 * above it says how many there are in all, so eight rows never stand for
 * fifty-one. A pure view, so tests/test_screens.py can draw it with what the
 * API really returns.
 */

export const MATCHED_FA = 'شواهد — آگهی‌های منطبق، بدون برآورد و بدون ترتیب';
export const APART_FA =
  'جدا — با هیچ قیدی مخالف نیستند، ولی همه‌ی قیدها را نمی‌شود برایشان سنجید';
export const NONE_FA = 'هیچ آگهی منطبقی پیدا نشد';

type Evidence = Pick<SearchResponse, 'considered' | 'evidence'
  | 'evidence_total' | 'evidence_unchecked' | 'evidence_unchecked_total'>;

const TH = 'text-right font-normal px-4 py-2.5 border-b border-line';
const TD = 'px-4 py-2.5 border-b border-line';

function Name({ r }: { r: EvidenceItem }) {
  return <td className={TD}>{modelLabel(r.model_key)}</td>;
}

function Facts({ r }: { r: EvidenceItem }) {
  return (
    <>
      <td className={`${TD} fig`}>{faPlain(r.year_jalali)}</td>
      <td className={`${TD} fig`}>
        {odometer(r.mileage_km, r.mileage_status, isAppraisalRow(r))}
      </td>
      <td className={`${TD} fig`}>
        {askingPrice(r.asking_price_toman, r.price_status, r.price_kind)}
      </td>
      <td className={TD} data-cell="province">
        {provinceLabel(r.province, r.province_source)}
      </td>
    </>
  );
}

function FileLink({ id }: { id: string }) {
  return (
    <td className={TD}>
      <Link href={`/car/${encodeURIComponent(id)}`}
            className="text-accent hover:underline text-[12.5px]">
        پرونده
      </Link>
    </td>
  );
}

/* «۸ از ۵۱» — said only when the table is not all of them. */
function OfAll({ shown, total, noun }:
  { shown: number; total: number; noun: string }) {
  if (total <= shown) return null;
  return (
    <p className="m-0 mb-2 text-[12.5px] text-ink-3">
      <b className="fig">{faNum(shown)}</b> از{' '}
      <b className="fig">{faNum(total)}</b> {noun} نشان داده شده است.
    </p>
  );
}

function Table({ head, children }:
  { head: string[]; children: ReactNode }) {
  return (
    <div className="border border-line bg-surface rounded-2xl overflow-x-auto">
      <table className="w-full border-collapse text-[13px] min-w-[520px]">
        <thead>
          <tr className="text-ink-3 text-[11.5px]">
            {head.map((h, i) => <th key={`${h}-${i}`} className={TH}>{h}</th>)}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

const FACTS = ['مدل', 'کارکرد', 'قیمت پیشنهادی', 'استان'];

export function SearchEvidence({ data }: { data: Evidence }) {
  const matched: EvidenceItem[] = data.evidence;
  const apart: UncheckedItem[] = data.evidence_unchecked;
  const matchedTotal = data.evidence_total;
  const apartTotal = data.evidence_unchecked_total;

  return (
    <>
      {matchedTotal === 0 ? (
        <section className="panel" data-evidence="none">
          <p className="eyebrow">{NONE_FA}</p>
          <p className="m-0 text-[14.5px] leading-[1.95] text-ink-2
                        max-w-[62ch]">
            این جدا از بالاست. رتبه‌بندی به‌خاطر دروازه‌ی پذیرش سرو
            نمی‌شود؛ این یکی درباره‌ی خودِ پرسش است: از{' '}
            <b className="fig text-ink">{faNum(data.considered)}</b>{' '}
            آگهی این پیکره، هیچ‌کدام با قیدهایی که نوشتی منطبق نبود.
            {apartTotal > 0 && (
              <>
                {' '}<b className="fig text-ink">{faNum(apartTotal)}</b>{' '}
                آگهی با هیچ قیدی مخالف نیست ولی همه‌ی قیدها را نمی‌شود
                برایش سنجید؛ پایین‌تر، جدا آمده‌اند.
              </>
            )}
          </p>
          {/* And the reader must not be left thinking the ladder ran and
              failed. It never runs here — see `search()` in
              webapp/api/main.py: relaxing a buyer's constraints to hunt for
              a shortlist that cannot be served would report «قیدها شل شد»
              when the constraints were never the problem. */}
          <p className="m-0 mt-3 text-[12.5px] leading-[1.9] text-ink-3
                        max-w-[62ch]">
            قیدها همان‌طور که گفتی به‌کار رفتند و شل نشدند — وقتی
            رتبه‌بندی سرو نمی‌شود، شل‌کردن قیدها دنبال فهرستی می‌گردد
            که به‌هرحال ساخته نمی‌شود. جمله را بازتر بنویس تا دوباره
            امتحان کنیم.
          </p>
        </section>
      ) : (
        <section data-evidence="matched">
          <p className="eyebrow">{MATCHED_FA}</p>
          <OfAll shown={matched.length} total={matchedTotal}
                 noun="آگهی منطبق" />
          <Table head={['خودرو', ...FACTS, '']}>
            {matched.map((r) => (
              <tr key={r.id} data-listing={r.id}>
                <Name r={r} />
                <Facts r={r} />
                <FileLink id={r.id} />
              </tr>
            ))}
          </Table>
        </section>
      )}

      {apartTotal > 0 && (
        <section data-evidence="apart">
          <p className="eyebrow">{APART_FA}</p>
          <p className="m-0 mb-2 text-[12.5px] leading-[1.9] text-ink-3
                        max-w-[62ch]">
            این‌ها منطبق شمرده نمی‌شوند. هیچ قیدی را که سنجیده شد نقض
            نمی‌کنند، اما برای قیدی که ستون دوم نام می‌برد مقداری ثبت نشده
            است — پس معلوم نیست آن را دارند یا نه.
          </p>
          <OfAll shown={apart.length} total={apartTotal} noun="آگهی جدا" />
          <Table head={['خودرو', 'چه چیزی ثبت نشده', ...FACTS, '']}>
            {apart.map((r) => (
              <tr key={r.id} data-listing={r.id}>
                <Name r={r} />
                <td className={`${TD} text-warn text-[12.5px]`}>
                  {r.unchecked.map((k) => (k === 'mileage'
                    ? odometerWhy(r.mileage_km, r.mileage_status)
                    : UNCHECKED_FA[k] ?? k)).join('، ')}
                </td>
                <Facts r={r} />
                <FileLink id={r.id} />
              </tr>
            ))}
          </Table>
        </section>
      )}
    </>
  );
}
