/* Persian number rendering, in one place.
 *
 * Two rules, both of which have bitten this project before:
 *
 * 1. A toman figure is never rounded on the way to the screen. `compact()`
 *    exists for headlines and is always accompanied by the exact number
 *    somewhere on the same card — a rounded price that the user cannot
 *    un-round is a number whose provenance has been quietly destroyed.
 *
 * 2. Nothing here invents a value. `maybe()` returns «ثبت‌نشده» for null,
 *    which is the same distinction `corpus_reader.py` refuses to blur: "the
 *    seller wrote nothing" and "this representation does not carry it" are
 *    different facts, and neither of them is zero.
 */

import {
  PRICE_STATUS_UNUSABLE, type ConstraintKey, type EvidenceItem,
  type MileageStatus, type ProvinceSource,
} from '@/lib/api';

const FA = new Intl.NumberFormat('fa-IR', { useGrouping: true });
const FA_PLAIN = new Intl.NumberFormat('fa-IR', { useGrouping: false });

/** ۵۹۲٬۹۸۴٬۰۶۳ — grouped, Persian digits, never rounded. */
export function faNum(n: number): string {
  return FA.format(Math.round(n));
}

/** Years and other bare counts: ۱۳۹۳, not ۱٬۳۹۳.
 *
 *  Accepts null because `EvidenceItem.year_jalali` is nullable: a published
 *  listing can carry no year that survived the guards, and the row is still
 *  evidence. «ثبت‌نشده» is the answer; a zero would be a fabricated year. */
export function faPlain(n: number | null | undefined): string {
  if (n == null) return 'ثبت‌نشده';
  return FA_PLAIN.format(Math.round(n));
}

export function toman(n: number | null | undefined): string {
  if (n == null) return 'ثبت‌نشده';
  return `${faNum(n)} تومان`;
}

/* What a row's number IS when it is not a cash asking price.
 *
 * `negotiable` and `financing_total` are `price_kind` — what the number
 * means (D52). The other three are the statuses `caro/ingest/quality.py`
 * calls unusable, which say the extraction cannot be believed rather than
 * what the figure is. The two vocabularies share the word `negotiable` and
 * are kept in separate maps for that reason. */
export const PRICE_KIND_FA: Record<string, string> = {
  negotiable: 'توافقی',
  financing_total: 'قیمت کل اقساط',
  absent: 'قیمت اعلام‌نشده',
};

export const PRICE_STATUS_FA: Record<string, string> = {
  ambiguous: 'قیمت مبهم',
  negotiable: 'توافقی',
  absent: 'قیمت اعلام‌نشده',
};

/* What a listing shown apart has no value for — one phrase per
 * `ConstraintKey`, said about the record rather than about the seller: a
 * value can be missing because the page never gave it or because it was never
 * recorded, and the table cannot tell which. A `Record` over the union, so a
 * key the server adds without a phrase here stops the build. */
export const UNCHECKED_FA: Record<ConstraintKey, string> = {
  budget: 'قیمت نقدی ثبت‌نشده',
  year: 'سال ساخت ثبت‌نشده',
  mileage: 'کارکرد ثبت‌نشده',
  province: 'استان ثبت‌نشده',
  accident: 'وضعیت بدنه ثبت‌نشده',
  unclear_documents: 'وضعیت سند ثبت‌نشده',
  manual: 'نوع گیربکس ثبت‌نشده',
  repaint: 'وضعیت رنگ بدنه ثبت‌نشده',
};

/** The rule `docs/FIELD_PROVENANCE.md` states for a price on a card and
 *  on the car page:
 *
 *      price_status ∉ PRICE_STATUS_UNUSABLE   AND   price_kind === 'cash'
 *
 *  Both null means the row carries no price provenance at all, and that is
 *  an appraisal row: eligibility applied both gates before it could be
 *  scored (D52), so the number stands. Otherwise the gates decide, and a row
 *  that fails them says what it IS rather than showing a figure that is not
 *  an asking price. A financing total reads like a bargain next to real
 *  ones, which is the same mistake D52 caught one layer down. */
export function askingPrice(
  price: number | null | undefined,
  status: string | null | undefined,
  kind: string | null | undefined,
): string {
  if (status == null && kind == null) return toman(price ?? null);
  if (kind != null && kind !== 'cash') {
    return PRICE_KIND_FA[kind] ?? 'قیمت نقدی نیست';
  }
  if (status != null && PRICE_STATUS_UNUSABLE.includes(status)) {
    return PRICE_STATUS_FA[status] ?? 'قیمت قابل اتکا نیست';
  }
  return toman(price ?? null);
}

/** «۵۹۳ میلیون» for headlines. Always shown beside the exact figure. */
export function compact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) {
    return `${FA.format(Math.round(n / 100_000_000) / 10)} میلیارد`;
  }
  if (abs >= 1_000_000) return `${FA.format(Math.round(n / 1_000_000))} میلیون`;
  if (abs >= 1_000) return `${FA.format(Math.round(n / 1_000))} هزار`;
  return faNum(n);
}

/** Signed, for a saving or a loss: the sign leads, in LTR isolation. */
export function signed(n: number): string {
  const s = n < 0 ? '−' : '+';
  return `${s}${faNum(Math.abs(n))}`;
}

export function km(n: number | null | undefined): string {
  if (n == null) return 'ثبت‌نشده';
  return `${faNum(n)} کیلومتر`;
}

/** An appraisal row carries no provenance fields at all — eligibility checked
 *  them before it could be scored — and every listing carries at least its
 *  price kind: corpus_reader records `absent` rather than nothing. The same
 *  test `askingPrice()` makes. */
export function isAppraisalRow(
  r: Pick<EvidenceItem, 'price_status' | 'price_kind'>,
): boolean {
  return r.price_status == null && r.price_kind == null;
}

/* What an odometer reading is said as, by its grade (D21, D22). Three
 * phrases, because D22 keeps three things apart: no number, a number the
 * seller should not be believed on, and a number no car can have. Counting
 * them together would hide all three. */
export const ODOMETER_FA: Record<Exclude<MileageStatus, 'plausible'>, string> = {
  unknown: 'کارکرد ثبت‌نشده',
  suspicious: 'کارکرد مشکوک',
  impossible: 'کارکرد ناممکن',
};

/* A listing whose record carries a number and no grade at all. Only an
   artifact without the field can send one; the contract suite checks that
   the corpus the site serves does not. */
export const ODOMETER_UNGRADED_FA = 'وضعیت کارکرد ثبت‌نشده';

/** An odometer, drawn with the grade that travels with it. FIELD_PROVENANCE.md
 *  says the status travels with the number or neither renders, so a number is
 *  drawn only where its grade says it is a reading — `plausible` — or on an
 *  appraisal row, which carries no grade: on a real corpus eligibility
 *  required a plausible odometer before the row could be scored, and a
 *  generated row has none to give. Any other grade is said in the number's
 *  place. The number stays in the payload; the page does not draw what it
 *  would not stand behind. */
export function odometer(
  n: number | null | undefined,
  status: MileageStatus | null | undefined,
  row: boolean,
): string {
  if (status === 'plausible' || (status == null && row)) return km(n);
  if (status == null) return n == null ? ODOMETER_FA.unknown : ODOMETER_UNGRADED_FA;
  return ODOMETER_FA[status];
}

/** Why a listing held apart could not be checked against an odometer cap:
 *  which of the grades it carries. A plausible reading is judged, never held
 *  apart on the odometer, so that branch is a fallback only. */
export function odometerWhy(
  n: number | null | undefined,
  status: MileageStatus | null | undefined,
): string {
  if (status == null) return n == null ? ODOMETER_FA.unknown : ODOMETER_UNGRADED_FA;
  if (status === 'plausible') return UNCHECKED_FA.mileage;
  return ODOMETER_FA[status];
}

export function maybe(v: string | number | null | undefined): string {
  if (v == null || v === '') return 'ثبت‌نشده';
  return typeof v === 'number' ? faNum(v) : v;
}

/* The keys of `MODEL_ALIASES` in caro/ranking.py are ASCII identifiers, which
 * is right for a taxonomy key and wrong for a page a Persian buyer reads: the
 * corpus calls a Pride `pride` and a 206 `206`, and printing either verbatim
 * is printing an internal name at the user. The map is the display layer for
 * that key and nothing more — it never travels back into a query.
 *
 * An unmapped key falls through unchanged rather than being transliterated by
 * guesswork, so a model added to the taxonomy shows up as itself until it is
 * given a Persian name here. Visible, and wrong in a way someone will notice.
 */
export const MODEL_FA: Record<string, string> = {
  '206': '۲۰۶', '207': '۲۰۷', '405': '۴۰۵',
  pride: 'پراید', tiba: 'تیبا', quik: 'کوییک', pars: 'پارس',
  dena: 'دنا', shahin: 'شاهین', saina: 'ساینا',
  // Manufacturers. The corpus stores `Saipa` and the page was printing it, so
  // a Persian site showed a Latin brand beside a Persian model — «Saipa ·
  // پراید» — in an h1.
  saipa: 'سایپا', ikco: 'ایران‌خودرو', 'iran khodro': 'ایران‌خودرو',
  mvm: 'ام‌وی‌ام', kia: 'کیا', hyundai: 'هیوندای', renault: 'رنو',
  peugeot: 'پژو',
};

/* Trim words, which are NOT the same problem as model names.
 *
 * A trim is part vocabulary and part code: «۱۳۱ SE» is how an Iranian seller
 * writes it, letters and all, so transliterating SE to «اس‌ای» would be less
 * readable rather than more. What IS Persian is the descriptive half —
 * `basic`, `sedan`, `hatchback` — and printing those in Latin on a Persian
 * page is the same mistake as printing `Saipa`.
 *
 * So: descriptive words translate, model codes stay Latin and go uppercase,
 * digits become Persian digits, and anything unrecognised falls through
 * EXACTLY as it is. The corpus holds `manualr` on three listings, which is a
 * parse artefact, and it must keep looking like one. */
const TRIM_FA: Record<string, string> = {
  basic: 'ساده', sedan: 'صندوق‌دار', hatchback: 'هاچ‌بک',
  manual: 'دنده‌ای', automatic: 'اتوماتیک', plus: 'پلاس',
};
const TRIM_CODE = new Set(['se', 'ex', 'sx', 'le', 'lx', 'gx', 'tu5', 'lmt',
                           'ex7', 's', 'r']);

export function trimLabel(trim: string | null | undefined): string {
  if (!trim) return 'ثبت‌نشده';
  return trim.split(/\s+/).filter(Boolean).map((w) => {
    const k = w.toLowerCase();
    if (TRIM_FA[k]) return TRIM_FA[k];
    if (/^\d+$/.test(w)) return faPlain(Number(w));
    if (TRIM_CODE.has(k)) return w.toUpperCase();
    return w;                       // unmapped: shown as it is, on purpose
  }).join(' ');
}

/* Body condition. These labels are not translations I chose — they are the
 * phrases `caro/ingest/divar_car.py` MATCHES ON to assign each label, so the
 * page says back to the reader what the listing said in the first place.
 *
 * `unknown` is the row that matters and it does not mean «سالم». A listing
 * that states no condition carries CONDITION_RISK 0.35 in `caro/ranking.py`,
 * between a disclosed scratch and several painted panels, because silence
 * could be either and treating it as intact would rank undisclosed cars above
 * disclosed ones. So it renders as "not stated" and never as a clean bill. */
export const CONDITION_FA: Record<string, string> = {
  intact: 'بدون رنگ',
  minor_paint: 'لکه‌رنگ یا خط و خش',
  multi_paint: 'دور رنگ — چند قطعه',
  replaced_part: 'قطعه‌ی تعویضی',
  accident: 'تصادفی یا شاسی‌خورده',
  unknown: 'ثبت‌نشده',
};

/* D52's gate, for a screen that is handed one listing by id.
 *
 * Search applies the gate before a row is shown (D60). Detail and compare
 * answer for whatever id they are asked about, so a screen there has to
 * decide what the listing IS before it decides how to draw it. Only
 * `vehicle` is a car. `unknown` is a class nobody determined, and it never
 * decays to `vehicle`. Null is the one other case, and it is an appraisal
 * Row — a Row carries no class, and only a vehicle becomes one — so it is
 * drawn as a car: the same null rule `askingPrice` uses. */
export function isVehicleClass(pc: string | null | undefined): boolean {
  return pc == null || pc === 'vehicle';
}

export const PRODUCT_CLASS_FA: Record<string, string> = {
  assignment: 'حواله',
  unknown: 'نوعش تعیین نشده',
};

export function classLabel(pc: string | null | undefined): string {
  if (!pc) return 'ثبت‌نشده';
  return PRODUCT_CLASS_FA[pc] ?? pc;
}

/** The one sentence every surface uses when it will not present a listing
 *  as a car. One string, so the words are the same on every page and a
 *  guard can look for them without keeping a copy. */
export const NOT_A_CAR_FA = 'به‌عنوان خودرو نمایش داده نمی‌شود';

export function conditionLabel(c: string | null | undefined): string {
  if (!c) return 'ثبت‌نشده';
  return CONDITION_FA[c.toLowerCase()] ?? c;
}

/* A province, said with how it was known (FIELD_PROVENANCE.md). Where the
 * listing names its province it is drawn alone. Where a city that shares its
 * province's name gave it — «تهران، آذری» names Tehran the city — the page
 * says so, so a province CARO inferred is never drawn as one the listing
 * stated. A province with no recorded source says that instead, because
 * drawn alone it would read as stated. */
export const PROVINCE_FROM_CITY_FA = 'از روی نام شهر';
export const PROVINCE_SOURCE_UNRECORDED_FA = 'منبعش ثبت‌نشده';

export function provinceLabel(
  p: string | null | undefined,
  source: ProvinceSource | null | undefined,
): string {
  if (!p) return 'ثبت‌نشده';
  if (source === 'stated') return p;
  if (source === 'city') return `${p} — ${PROVINCE_FROM_CITY_FA}`;
  return `${p} — ${PROVINCE_SOURCE_UNRECORDED_FA}`;
}

/** «پراید · EX» from a model_key, dropping the empty trim segment. */
export function modelLabel(key: string): string {
  const parts = key.split('|').filter(Boolean);
  return parts
    .map((part, i) => {
      const fa = MODEL_FA[part.toLowerCase()];
      if (fa) return fa;
      // The third segment of a model_key is the trim, and it is the only one
      // with its own vocabulary. Earlier segments fall through as before.
      return i === 2 ? trimLabel(part) : part;
    })
    .join(' · ');
}

/* The way to a car's seller is its listing on its source: the seller's number
   is there, behind the source's own login, and CARO keeps none (DATA_CONTRACT).
   So the link says where it goes and what it is for. */
const SOURCE_FA: Record<string, string> = {
  'bama.ir': 'باما',
  'divar.ir': 'دیوار',
  'sheypoor.com': 'شیپور',
  'khodro45.com': 'خودرو۴۵',
};

/** The source a listing's url is on, by its host; «منبع» for any other. */
export function sourceName(url: string | null | undefined): string {
  try {
    const host = new URL(url ?? '').hostname.replace(/^www\./, '');
    return SOURCE_FA[host] ?? 'منبع';
  } catch {
    return 'منبع';
  }
}

/** A published run's source as its artifact names it ('bama', 'khodro45'),
 *  by the same table; an id the table does not hold is shown as written. */
export function runSourceName(id: string): string {
  const host = Object.keys(SOURCE_FA).find((h) => h.split('.')[0] === id);
  return host ? SOURCE_FA[host] : id;
}

export const NUMBER_ON_SOURCE_FA =
  'شماره‌ی فروشنده در صفحه‌ی خود آگهی است؛ کارو آن را نگه نمی‌دارد و نشان نمی‌دهد.';

export function contactLabel(url: string | null | undefined): string {
  return `تماس با فروشنده در ${sourceName(url)} ↗`;
}

/** A code typed on a Persian keyboard, in the ASCII digits an HTTP header can
 *  carry: a header holds no Persian digit, and a browser refuses to send one.
 *  Persian (U+06F0..) and Arabic-Indic (U+0660..) digits both. */
export function asciiDigits(s: string): string {
  return s
    .replace(/[\u06F0-\u06F9]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[\u0660-\u0669]/g, (d) => String(d.charCodeAt(0) - 0x0660));
}

/** A model page's title: the model as the page draws it, then the site, so
 *  two tabs or two search results of two models do not read the same. `_`
 *  is the page's placeholder for a make the corpus does not give. */
export function modelTitle(make: string, model: string): string {
  const key = [make === '_' ? '' : make, model].filter(Boolean).join('|');
  return `${modelLabel(key)}: آگهی‌ها و قیمت‌ها — CARO`;
}

/** A signed decimal that survives bidi: U+2212, never the ASCII hyphen.
 *  In an RTL line the ASCII `-` from `toFixed` is reordered to the far side
 *  and «−۰٫۱۹۸» renders as «۰٫۱۹۸−». */
export function fixed(n: number, digits = 3): string {
  const v = Math.abs(n) < 0.5 / 10 ** digits ? 0 : n;
  return `${v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}`;
}

export function pct(x: number): string {
  return `${FA.format(Math.round(x * 100))}٪`;
}
