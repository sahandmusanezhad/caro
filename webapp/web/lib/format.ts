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

/** Years and other bare counts: ۱۳۹۳, not ۱٬۳۹۳. */
export function faPlain(n: number): string {
  return FA_PLAIN.format(Math.round(n));
}

export function toman(n: number): string {
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
};

/** «پراید · EX» from a model_key, dropping the empty trim segment. */
export function modelLabel(key: string): string {
  return key.split('|').filter(Boolean)
    .map((part) => MODEL_FA[part.toLowerCase()] ?? part)
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
