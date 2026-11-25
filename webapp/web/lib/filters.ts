import { PRICE_STATUS_UNUSABLE, type EvidenceItem, type Filters, type SortKey } from '@/lib/api';
import { asciiDigits, faNum, pct } from '@/lib/format';

/* The filter panel's state, as the page's address carries it (the owner's
 * choice of 2026-11-25: a reader filters as on Divar, chooses the order and
 * how many listings to see, and can send the page as it stands).
 *
 * The address uses the API's own names (webapp/api/main.py, `filters`), so a
 * filtered page and the request it makes say the same thing. A field the
 * address does not carry, or carries as something that is not a number in
 * range, is a field left empty: an address is typed by people, and a wrong
 * one is read as the filter it can be, never as an error page. The API is the
 * one that refuses (422); this only never sends what it would refuse. */

export const SORTS: readonly SortKey[] = ['market', 'price', 'mileage'];

export const SORT_FA: Record<SortKey, string> = {
  market: 'ارزان نسبت به بازار',
  price: 'ارزان‌ترین',
  mileage: 'کم‌کارکردترین',
};

/* What each order means, said under the menu, so that «نسبت به بازار» is
   never read as more than it is: the asking prices of the same make, model
   and year in this collection, and no estimate (D36, D50). */
export const SORT_WHY_FA: Record<SortKey, string> = {
  market: 'قیمت هر آگهی در برابر میانه‌ی قیمت درخواستیِ همان برند، مدل و سال در همین '
    + 'جمع‌آوری؛ هرچه پایین‌تر از میانه، بالاتر. آگهی‌ای که میانه‌ای برای مقایسه ندارد '
    + '(کمتر از سه آگهی قیمت‌دار) بعد از این‌ها می‌آید. این برآورد ارزش خودرو نیست.',
  price: 'از قیمت کمتر به بیشتر؛ آگهی بدون قیمت در آخر.',
  mileage: 'از کارکرد کمتر به بیشتر؛ آگهی‌ای که کارکردش ثبت یا باورپذیر نیست در آخر.',
};

export const K_DEFAULT = 12;
export const K_MAX = 100;
export const YEARS: readonly [number, number] = [1300, 1499];

/* Prices are typed in millions of toman and odometers in thousands of km,
   as a reader says them («۵۰۰ میلیون», «۸۰ هزار»); the API takes toman and km. */
export const PRICE_UNIT = 1_000_000;
export const KM_UNIT = 1_000;

export interface FilterState {
  f: Filters;
  sort: SortKey;
  k: number;
}

function whole(raw: string | null, lo: number, hi: number): number | undefined {
  if (raw === null) return undefined;
  const t = asciiDigits(raw).replace(/[,،٬\s]/g, '');
  if (!/^\d+$/.test(t)) return undefined;
  const n = Number(t);
  return Number.isSafeInteger(n) && n >= lo && n <= hi ? n : undefined;
}

function text(raw: string | null, max = 60): string | undefined {
  const t = (raw ?? '').trim();
  return t && t.length <= max ? t : undefined;
}

/** A range whose two ends are the wrong way round asks for nothing that
 *  could exist; the low end is dropped rather than the page sent to a 422. */
function ordered(lo: number | undefined, hi: number | undefined): [number | undefined, number | undefined] {
  return lo !== undefined && hi !== undefined && lo > hi ? [undefined, hi] : [lo, hi];
}

export function readFilters(params: URLSearchParams, sortDefault: SortKey = 'market'): FilterState {
  const [pmin, pmax] = ordered(whole(params.get('price_min'), 0, 10 ** 12),
                               whole(params.get('price_max'), 0, 10 ** 12));
  const [ymin, ymax] = ordered(whole(params.get('year_min'), YEARS[0], YEARS[1]),
                               whole(params.get('year_max'), YEARS[0], YEARS[1]));
  const [kmin, kmax] = ordered(whole(params.get('km_min'), 0, 10_000_000),
                               whole(params.get('km_max'), 0, 10_000_000));
  const f: Filters = {};
  if (pmin !== undefined) f.price_min = pmin;
  if (pmax !== undefined) f.price_max = pmax;
  if (ymin !== undefined) f.year_min = ymin;
  if (ymax !== undefined) f.year_max = ymax;
  if (kmin !== undefined) f.km_min = kmin;
  if (kmax !== undefined) f.km_max = kmax;
  const make = text(params.get('make'));
  const model = text(params.get('model'));
  const province = text(params.get('province'), 40);
  if (make) f.make = make;
  if (model) f.model = model;
  if (province) f.province = province;
  const s = params.get('sort');
  const sort = (SORTS as readonly string[]).includes(s ?? '') ? (s as SortKey) : sortDefault;
  const k = whole(params.get('k'), 1, K_MAX) ?? K_DEFAULT;
  return { f, sort, k };
}

/** The page's address for a state: the sentence first where there is one,
 *  then the filter's fields that are set, the order and the count. */
export function filterHref(path: string, s: FilterState, q?: string): string {
  const p = new URLSearchParams();
  if (q) p.set('q', q);
  for (const [key, v] of Object.entries(s.f)) {
    if (v !== undefined && `${v}`.trim() !== '') p.set(key, `${v}`);
  }
  p.set('sort', s.sort);
  p.set('k', `${s.k}`);
  return `${path}?${p.toString()}`;
}

/** The filter's fields, the order and the count as an address's tail
 *  («&price_max=…&sort=market&k=12»), for a link that changes something
 *  else -- the sentence -- and keeps the panel as it stands. */
export function filterParamsOf(s: FilterState): string {
  const tail = filterHref('', s).slice(1);
  return tail ? `&${tail}` : '';
}

export function countSet(f: Filters): number {
  return Object.values(f).filter((v) => v !== undefined && `${v}`.trim() !== '').length;
}

/** Where a listing's price stands against its make, model and year's middle,
 *  in words, or null where it was not looked up. Never an estimate: the
 *  middle of asking prices, and how many stand behind it. */
export function middleLabel(r: Pick<EvidenceItem, 'asking_price_toman' | 'price_status' | 'price_kind'
  | 'year_middle_toman' | 'year_middle_priced'>): string | null {
  if (r.year_middle_priced === null || r.year_middle_priced === undefined) return null;
  const n = r.year_middle_priced;
  if (r.year_middle_toman === null || r.year_middle_toman === undefined) {
    return n === 0 ? 'میانه‌ای برای مقایسه نیست'
      : `میانه‌ای نیست؛ فقط ${faNum(n)} آگهی قیمت‌دار`;
  }
  // The same reading of a price as the middle's own (market.priced): a
  // cash figure whose status is not one of the unusable ones.
  const p = r.asking_price_toman;
  const usable = p !== null && p > 0 && (r.price_kind == null || r.price_kind === 'cash')
    && (r.price_status == null || !PRICE_STATUS_UNUSABLE.includes(r.price_status));
  if (!usable || p === null) return `میانه‌ی ${faNum(n)} آگهی؛ این آگهی قیمتی برای مقایسه ندارد`;
  const gap = (p - r.year_middle_toman) / r.year_middle_toman;
  if (Math.abs(gap) < 0.005) return `هم‌اندازه‌ی میانه‌ی ${faNum(n)} آگهی`;
  return `${pct(Math.abs(gap))} ${gap < 0 ? 'زیر' : 'بالای'} میانه‌ی ${faNum(n)} آگهی`;
}
