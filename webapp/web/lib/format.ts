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

export function conditionLabel(c: string | null | undefined): string {
  if (!c) return 'ثبت‌نشده';
  return CONDITION_FA[c.toLowerCase()] ?? c;
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
