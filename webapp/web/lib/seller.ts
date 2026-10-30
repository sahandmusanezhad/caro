/* The listings sellers post on CARO itself: the site's half of
 * docs/SELLER_LISTINGS.md (step 5).
 *
 * Everything here talks to /api/account and /api/listings, which the site's
 * own rewrite carries to the API (next.config.mjs), so the session cookie is
 * the site's and every POST carries the site's Origin. The server holds every
 * rule; what the form checks before it sends is only there to save a seller
 * a round trip, and the server's `faults` are what the form shows.
 *
 * The provinces and the colours are the API's own lists, copied because a
 * form needs them before it asks anything; tests/test_screens.py holds the
 * copies to caro/ingest/persian.py and caro/ingest/divar_car.py, so the two
 * cannot drift apart unnoticed.
 */

export const PROVINCES_FA: readonly string[] = [
  'آذربایجان شرقی', 'آذربایجان غربی', 'اردبیل', 'اصفهان', 'البرز', 'ایلام',
  'بوشهر', 'تهران', 'چهارمحال و بختیاری', 'خراسان جنوبی', 'خراسان رضوی',
  'خراسان شمالی', 'خوزستان', 'زنجان', 'سمنان', 'سیستان و بلوچستان', 'فارس',
  'قزوین', 'قم', 'کردستان', 'کرمان', 'کرمانشاه', 'کهگیلویه و بویراحمد',
  'گلستان', 'گیلان', 'لرستان', 'مازندران', 'مرکزی', 'هرمزگان', 'همدان',
  'یزد',
];

export const COLORS_FA: readonly string[] = [
  'سفید', 'مشکی', 'نقره ای', 'خاکستری', 'نوک مدادی', 'آبی', 'قرمز',
  'سبز', 'بژ', 'قهوه ای', 'نقرآبی', 'زرد', 'بادمجانی', 'سربی',
];

export const GEARBOX_FA: Record<string, string> = { manual: 'دنده‌ای', automatic: 'اتوماتیک' };
export const FUEL_FA: Record<string, string> = {
  petrol: 'بنزینی', dual: 'دوگانه‌سوز', hybrid: 'هیبرید', ev: 'برقی',
};
export const BODY_KEYS: readonly string[] = ['intact', 'minor_paint', 'multi_paint', 'replaced_part', 'accident'];

export const REPORT_FA: Record<string, string> = {
  sold: 'فروخته شده', wrong: 'اطلاعات نادرست', fake: 'آگهی جعلی',
  spam: 'تبلیغ یا هرزنامه', offensive: 'توهین‌آمیز', other: 'دلیل دیگر',
};

export const KEPT_APART_FA =
  'این آگهی‌ها را خود فروشنده‌ها در کارو ثبت کرده‌اند و هر کدام پیش از انتشار تأیید شده است. '
  + 'جزو داده‌ی برآورد کارو نیستند و در هیچ داوری قیمتی به کار نمی‌روند.';
export const NUMBER_ON_PRESS_FA = 'شماره فقط با «نمایش شماره» و به انتخاب خود فروشنده نشان داده می‌شود.';
export const DESCRIPTION_RULE_FA = 'تا ۱۰۰۰ حرف، بدون عدد و بدون پیوند؛ شماره را «نمایش شماره» نشان می‌دهد.';
export const OFF_FA = 'آگهی فروشنده‌ها در این استقرار روشن نیست.';

export interface ListingFields {
  make: string;
  model: string;
  trim: string | null;
  year_jalali: number;
  mileage_km: number;
  price_toman: number | null;
  negotiable: boolean;
  province: string;
  city: string | null;
  gearbox: string | null;
  fuel: string | null;
  color: string | null;
  body: string | null;
  description: string;
  show_phone: boolean;
}

export interface PublicListing extends Omit<ListingFields, 'show_phone'> {
  id: number;
  ends_at: number;
  has_phone: boolean;
}

export interface MineItem {
  id: number;
  ends_at: number;
  ended: boolean;
  held: boolean;
  live: ListingFields | null;
  pending: ListingFields | null;
  last_review: { review: string; reason: string | null } | null;
  reveals: number;
}

export interface Answer<T> {
  ok: boolean;
  status: number;
  data: T | null;
  /** The server's sentence, in Persian, when there is one. */
  message: string | null;
  /** Which fields the server refused, and why. */
  faults: Record<string, string>;
}

/** One request to the seller API. Never throws: a page draws what came back. */
export async function call<T>(path: string, method: 'GET' | 'POST' = 'GET',
                              body?: unknown): Promise<Answer<T>> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      cache: 'no-store',
      credentials: 'same-origin',
      headers: body === undefined ? undefined : { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    return { ok: false, status: 0, data: null, message: 'سرویس در دسترس نیست.', faults: {} };
  }
  let payload: unknown = null;
  try { payload = await res.json(); } catch { /* no body */ }
  if (res.ok) return { ok: true, status: res.status, data: payload as T, message: null, faults: {} };
  return { ok: false, status: res.status, data: null, ...explain(res.status, payload) };
}

/** What a refusal says, in the seller's language: the server's own sentence
 *  where it gave one, the fields it refused, or a sentence for the status. */
export function explain(status: number, payload: unknown): { message: string | null; faults: Record<string, string> } {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === 'object' && 'faults' in detail) {
    return { message: 'چند بخش فرم درست نیست؛ کنار هر کدام نوشته شده است.',
             faults: (detail as { faults: Record<string, string> }).faults };
  }
  if (detail && typeof detail === 'object' && 'fa' in detail) {
    return { message: String((detail as { fa: unknown }).fa), faults: {} };
  }
  if (typeof detail === 'string' && /[؀-ۿ]/.test(detail)) return { message: detail, faults: {} };
  const by: Record<number, string> = {
    401: 'وارد نشده‌ای، یا نشستت به پایان رسیده است.',
    403: 'این درخواست از خود سایت کارو نیامده است.',
    404: 'پیدا نشد.',
    409: 'این کار الان شدنی نیست.',
    422: 'چیزی که فرستادی پذیرفته نشد.',
    429: 'درخواست‌ها زیاد بوده است. کمی بعد دوباره امتحان کن.',
  };
  return { message: by[status] ?? `خطای ${status}`, faults: {} };
}

/** A seller's listing as its seller sees it: one sentence for where it is. */
export function listingState(item: Pick<MineItem, 'ended' | 'held' | 'live' | 'pending' | 'last_review'>): string {
  if (item.ended) return 'تمام شده؛ تا ۹۰ روز می‌توانی تمدیدش کنی.';
  if (item.held) return 'با گزارش‌ها پایین آمده تا مدیر نگاهش کند.';
  const rejected = item.last_review?.review === 'rejected' ? item.last_review.reason : null;
  if (item.live && item.pending) return 'منتشر شده؛ ویرایشت در انتظار تأیید است.';
  if (item.live) return 'منتشر شده.';
  if (item.pending) return 'در انتظار تأیید.';
  return rejected ? `رد شد: ${rejected}` : 'منتشر نشده.';
}

export const sellerApi = {
  status: () => call<{ store: string; sms: string }>('/api/account/status'),
  sendCode: (phone: string) => call<{ sent: boolean; seconds: number }>('/api/account/code', 'POST', { phone }),
  login: (phone: string, code: string) =>
    call<{ phone: string; created: boolean }>('/api/account/login', 'POST', { phone, code }),
  me: () => call<{ phone: string }>('/api/account/me'),
  logout: () => call<{ ok: boolean }>('/api/account/logout', 'POST'),
  deleteAccount: () => call<{ deleted: boolean }>('/api/account/delete', 'POST'),
  mine: () => call<{ listings: MineItem[] }>('/api/listings/mine'),
  create: (x: ListingFields) => call<{ id: number }>('/api/listings', 'POST', x),
  edit: (id: number, x: ListingFields) => call<{ id: number }>(`/api/listings/${id}/edit`, 'POST', x),
  renew: (id: number) => call<{ ends_at: number }>(`/api/listings/${id}/renew`, 'POST'),
  remove: (id: number) => call<{ deleted: boolean }>(`/api/listings/${id}/delete`, 'POST'),
  list: (q = '') => call<{ listings: PublicListing[] }>(`/api/listings${q}`),
  reveal: (id: number) => call<{ phone: string }>(`/api/listings/${id}/reveal`, 'POST'),
  report: (id: number, reason: string) => call<{ reported: boolean }>(`/api/listings/${id}/report`, 'POST', { reason }),
};
