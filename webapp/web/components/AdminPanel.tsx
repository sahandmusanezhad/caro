'use client';

import { useEffect, useState } from 'react';
import { asciiDigits, faNum, faPlain, km, toman } from '@/lib/format';
import { REPORT_FA, type ListingFields } from '@/lib/seller';

/* The operator's panel (the plan's phase 5): the contact inbox, the listings
 * sellers post that wait for review, the ones three reports took down, and
 * the corpus being served -- one door, the operator's token, for the first
 * three; the corpus is public.
 *
 * The token is held in component state for the session and nothing else. Not
 * localStorage: an admin credential that survives a closed tab on a shared
 * machine is a credential that outlives the person who typed it, and the cost
 * of re-typing it is one field.
 *
 * `/api/admin/status` exists so this screen can say "this deployment has no
 * admin token configured" instead of "your token is wrong" — the 401 itself
 * refuses to distinguish the two, on purpose.
 *
 * With CARO_ADMIN_TOTP_SECRET set (O1, the owner's choice of 2026-10-30) the
 * status says so, and the screen asks for the six digits of the authenticator
 * app beside the token. A code opens once, so it is cleared after every
 * request -- each list asked for, each listing approved -- and the next asks
 * for the app's next code; its digits are sent in ASCII: a header carries no
 * Persian digit. No answer the panel is given holds a seller's number.
 */

type SecondFactor = 'off' | 'on' | 'unreadable';

interface Msg {
  ref: string;
  received_at: string;
  name: string;
  email: string;
  subject: string;
  body: string;
  read: boolean;
}

type View = 'messages' | 'pending' | 'held';
const VIEWS: [View, string][] = [
  ['messages', 'پیام‌ها'], ['pending', 'در انتظار تأیید'], ['held', 'پایین‌آمده با گزارش'],
];

interface Pending { version: number; listing: number; created_at: number; kind: 'first' | 'edit';
  fields: ListingFields }
interface Held { listing: number; fields: ListingFields | null; reports: Record<string, number> }
interface Served { run: string; kind: string; gated: boolean; rows: number; sha: string | null;
  build: string | null }

const STORE_OFF_FA = 'آگهی فروشنده‌ها در این استقرار روشن نیست؛ چیزی برای بررسی نیست.';

export default function AdminPanel() {
  const [token, setToken] = useState('');
  const [msgs, setMsgs] = useState<Msg[] | null>(null);
  const [pending, setPending] = useState<Pending[] | null>(null);
  const [heldList, setHeldList] = useState<Held[] | null>(null);
  const [view, setView] = useState<View>('messages');
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [second, setSecond] = useState<SecondFactor>('off');
  const [code, setCode] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const [reason, setReason] = useState<Record<number, string>>({});
  const [served, setServed] = useState<Served | null>(null);

  useEffect(() => {
    fetch('/api/admin/status')
      .then((r) => r.json())
      .then((d) => {
        setConfigured(Boolean(d.configured));
        if (d.second_factor === 'on' || d.second_factor === 'unreadable') setSecond(d.second_factor);
      })
      .catch(() => setConfigured(null));
    // The corpus being served: public, and asked for without the token.
    Promise.all([fetch('/api/corpus').then((r) => r.json()), fetch('/api/health').then((r) => r.json())])
      .then(([c, h]) => setServed({
        run: c?.corpus?.identity?.run_id ?? '-', kind: c?.status?.kind ?? '-', gated: Boolean(c?.status?.gated),
        rows: Number(c?.corpus?.rows ?? 0), sha: c?.corpus?.identity?.sha256 ?? null, build: h?.build ?? null,
      }))
      .catch(() => setServed(null));
  }, []);

  /* One request with the operator's door: the token, and the code where a
   * second factor is set -- spent by this request, so cleared at once. The
   * answer's JSON, or null with the reason said. */
  async function call(path: string, method = 'GET', body?: unknown): Promise<Record<string, unknown> | null> {
    setBusy(true); setErr(null); setNote(null);
    const typed = asciiDigits(code.trim());
    setCode('');
    try {
      const headers: Record<string, string> = { 'x-admin-token': token.trim() };
      if (second !== 'off' && typed) headers['x-admin-code'] = typed;
      if (body !== undefined) headers['content-type'] = 'application/json';
      const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
      const d = await res.json().catch(() => ({}));
      if (res.ok) return d as Record<string, unknown>;
      if (res.status === 401) {
        setErr(second === 'off'
          ? 'توکن پذیرفته نشد.'
          : 'توکن یا کد پذیرفته نشد. هر کد یک بار باز می‌کند؛ کد تازه‌ی اپ را بزن.');
      } else if (res.status === 429) {
        setErr('تلاش‌های ناموفق این نشانی زیاد بوده است. چند دقیقه بعد دوباره امتحان کن.');
      } else if (res.status === 503 && JSON.stringify(d).includes('STORE_OFF')) {
        setErr(STORE_OFF_FA);
      } else {
        const said = (d as { detail?: unknown }).detail;
        setErr(typeof said === 'string' && /[؀-ۿ]/.test(said) ? said : `خطای ${res.status}`);
      }
      return null;
    } catch {
      setErr('سرویس در دسترس نیست');
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function load(e?: React.FormEvent) {
    e?.preventDefault();
    if (!token.trim()) return;
    if (view === 'messages') {
      const d = await call('/api/admin/messages');
      setMsgs(d ? (d.messages as Msg[]) : null);
    } else if (view === 'pending') {
      const d = await call('/api/admin/listings/pending');
      setPending(d ? (d.pending as Pending[]) : null);
    } else {
      const d = await call('/api/admin/listings/held');
      setHeldList(d ? (d.held as Held[]) : null);
    }
  }

  async function decide(p: Pending, how: 'approve' | 'reject') {
    const why = (reason[p.version] ?? '').trim();
    if (how === 'reject' && !why) { setErr('دلیل را بنویس؛ فروشنده آن را می‌بیند.'); return; }
    const d = await call(`/api/admin/listings/versions/${p.version}/${how}`, 'POST',
                         how === 'reject' ? { reason: why } : undefined);
    if (d) {
      setPending((xs) => (xs ?? []).filter((x) => x.version !== p.version));
      setNote(how === 'approve' ? `نسخه‌ی ${faPlain(p.version)} منتشر شد.` : `نسخه‌ی ${faPlain(p.version)} رد شد.`);
    }
  }

  async function settle(h: Held, how: 'release' | 'remove') {
    const why = (reason[-h.listing] ?? '').trim();
    if (how === 'remove' && !why) { setErr('دلیل را بنویس؛ فروشنده آن را می‌بیند.'); return; }
    const d = await call(`/api/admin/listings/${h.listing}/${how}`, 'POST',
                         how === 'remove' ? { reason: why } : undefined);
    if (d) {
      setHeldList((xs) => (xs ?? []).filter((x) => x.listing !== h.listing));
      setNote(how === 'release' ? `آگهی ${faPlain(h.listing)} برگشت.` : `آگهی ${faPlain(h.listing)} برداشته شد.`);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <section>
        <p className="eyebrow">مدیریت</p>
        <h1 className="m-0 text-[26px] font-bold">پیام‌ها، آگهی‌ها و پیکره</h1>
      </section>

      <section className="panel" data-panel="corpus">
        <p className="eyebrow">پیکره‌ای که همین حالا سرو می‌شود</p>
        {served ? (
          <p className="m-0 text-[13.5px] text-ink-2 leading-[1.9]">
            <span className="num">{served.run}</span> · {served.kind} ·{' '}
            {served.gated ? 'برآوردگر از دروازه گذشته' : 'هیچ برآوردگری از دروازه نگذشته'} ·{' '}
            <span className="fig">{faNum(served.rows)}</span> ردیف ·{' '}
            <span className="num">{served.sha ? served.sha.slice(0, 12) : '-'}</span>
            {served.build ? <> · ساخته از <span className="num">{served.build.slice(0, 7)}</span></> : null}
          </p>
        ) : (
          <p className="m-0 text-[13.5px] text-ink-3">پاسخی نرسید.</p>
        )}
      </section>

      <nav className="flex gap-2 flex-wrap" aria-label="بخش‌های مدیریت">
        {VIEWS.map(([v, label]) => (
          <button key={v} type="button" aria-pressed={view === v}
                  className={view === v ? 'btn-solid' : 'btn'} onClick={() => { setView(v); setErr(null); setNote(null); }}>
            {label}
          </button>
        ))}
      </nav>

      {configured === false && (
        <div className="panel border-warn">
          <p className="eyebrow !text-warn">هیچ توکن مدیریتی تنظیم نشده است</p>
          <p className="m-0 text-[13.5px] text-ink-2 leading-[1.9]
                        max-w-[64ch]">
            این استقرار متغیر <span className="num">CARO_ADMIN_TOKEN</span> را
            ندارد، پس صندوق با هیچ توکنی باز نمی‌شود. این حالتِ امن است، نه یک
            خرابی: قفلی که «تنظیم نشده» باشد، قفل نیست.
          </p>
          <p className="m-0 mt-3 num text-[12px] text-ink-3" dir="ltr">
            CARO_ADMIN_TOKEN=… uvicorn webapp.api.main:app
          </p>
        </div>
      )}

      {second === 'unreadable' && (
        <div className="panel border-warn">
          <p className="eyebrow !text-warn">کلید ورود دومرحله‌ای خوانده نمی‌شود</p>
          <p className="m-0 text-[13.5px] text-ink-2 leading-[1.9] max-w-[64ch]">
            متغیر <span className="num">CARO_ADMIN_TOTP_SECRET</span> تنظیم شده، ولی یک کلید
            base32 دست‌کم ۱۲۸ بیتی نیست؛ تا درست نشود صندوق با هیچ توکن و کدی باز نمی‌شود.
          </p>
        </div>
      )}

      <form onSubmit={load} className="panel flex gap-2 flex-wrap items-end">
        <div className="flex-1 min-w-[240px]">
          <label htmlFor="tok"
                 className="block text-[12.5px] text-ink-3 mb-1.5">
            توکن مدیریت
          </label>
          <input
            id="tok"
            type="password"
            value={token}
            dir="ltr"
            onChange={(e) => setToken(e.target.value)}
            className="w-full bg-ground border border-line rounded-2xl
                       px-3.5 py-2.5 text-[14px] num focus:border-accent
                       transition-colors"
          />
        </div>
        {second !== 'off' && (
          <div className="w-[11rem]">
            <label htmlFor="code"
                   className="block text-[12.5px] text-ink-3 mb-1.5">
              کد شش‌رقمی اپ احراز هویت
            </label>
            <input
              id="code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              dir="ltr"
              onChange={(e) => setCode(e.target.value)}
              className="w-full bg-ground border border-line rounded-2xl
                         px-3.5 py-2.5 text-[14px] num tracking-[0.3em] focus:border-accent
                         transition-colors"
            />
          </div>
        )}
        <button type="submit" className="btn-solid"
                disabled={busy || !token.trim() || (second !== 'off' && !code.trim())}>
          {busy ? 'در حال بازکردن…' : `${VIEWS.find(([v]) => v === view)?.[1] ?? ''} را باز کن`}
        </button>
      </form>

      {err && (
        <p className="m-0 text-[13px] text-bad bg-bad-soft border border-bad/40
                      rounded-lg px-3 py-2">{err}</p>
      )}

      {note && (
        <p className="m-0 text-[13px] text-ink-2 bg-sunk border border-line rounded-lg px-3 py-2">{note}</p>
      )}

      {view === 'pending' && pending && (
        pending.length === 0 ? (
          <div className="panel text-[13.5px] text-ink-3">چیزی در انتظار تأیید نیست.</div>
        ) : (
          <ul className="m-0 p-0 list-none flex flex-col gap-3" data-review="pending">
            {pending.map((p) => (
              <li key={p.version} className="panel flex flex-col gap-3">
                <Listing fields={p.fields}
                         tag={p.kind === 'edit' ? `ویرایشِ آگهی ${faPlain(p.listing)}` : `آگهی تازه‌ی ${faPlain(p.listing)}`} />
                <div className="flex gap-2 flex-wrap items-end">
                  <button type="button" className="btn-solid" disabled={busy || (second !== 'off' && !code.trim())}
                          onClick={() => decide(p, 'approve')}>تأیید و انتشار</button>
                  <input aria-label="دلیل رد" placeholder="دلیل رد، که فروشنده می‌بیند"
                         value={reason[p.version] ?? ''} maxLength={300}
                         onChange={(e) => setReason({ ...reason, [p.version]: e.target.value })}
                         className="flex-1 min-w-[12rem] bg-ground border border-line rounded-2xl px-3.5 py-2 text-[13.5px]
                                    focus:border-accent transition-colors" />
                  <button type="button" className="btn" disabled={busy || (second !== 'off' && !code.trim())}
                          onClick={() => decide(p, 'reject')}>رد</button>
                </div>
              </li>
            ))}
          </ul>
        )
      )}

      {view === 'held' && heldList && (
        heldList.length === 0 ? (
          <div className="panel text-[13.5px] text-ink-3">هیچ آگهی‌ای با گزارش پایین نیامده است.</div>
        ) : (
          <ul className="m-0 p-0 list-none flex flex-col gap-3" data-review="held">
            {heldList.map((h) => (
              <li key={h.listing} className="panel flex flex-col gap-3">
                {h.fields ? <Listing fields={h.fields} tag={`آگهی ${faPlain(h.listing)}`} /> : null}
                <p className="m-0 text-[13px] text-ink-2">
                  گزارش‌ها: {Object.entries(h.reports).map(([k, n]) => `${REPORT_FA[k] ?? k} ${faPlain(n)}`).join('، ')}
                </p>
                <div className="flex gap-2 flex-wrap items-end">
                  <button type="button" className="btn-solid" disabled={busy || (second !== 'off' && !code.trim())}
                          onClick={() => settle(h, 'release')}>برگرداندن</button>
                  <input aria-label="دلیل برداشتن" placeholder="دلیل برداشتن، که فروشنده می‌بیند"
                         value={reason[-h.listing] ?? ''} maxLength={300}
                         onChange={(e) => setReason({ ...reason, [-h.listing]: e.target.value })}
                         className="flex-1 min-w-[12rem] bg-ground border border-line rounded-2xl px-3.5 py-2 text-[13.5px]
                                    focus:border-accent transition-colors" />
                  <button type="button" className="btn" disabled={busy || (second !== 'off' && !code.trim())}
                          onClick={() => settle(h, 'remove')}>برداشتن</button>
                </div>
              </li>
            ))}
          </ul>
        )
      )}

      {view === 'messages' && msgs && (
        <>
          <p className="m-0 text-[13px] text-ink-2">
            <b className="fig">{faNum(msgs.length)}</b> پیام
          </p>

          {msgs.length === 0 ? (
            <div className="panel text-[13.5px] text-ink-3">
              صندوق خالی است.
            </div>
          ) : (
            <ul className="m-0 p-0 list-none flex flex-col tiles">
              {msgs.map((m) => (
                <li key={m.ref} className="bg-surface">
                  <button
                    type="button"
                    onClick={() => setOpen(open === m.ref ? null : m.ref)}
                    className="w-full text-right px-4 py-3 grid gap-x-4
                               gap-y-1 sm:grid-cols-[1fr_auto] items-baseline"
                  >
                    <span>
                      <span className="text-[14px] font-medium">
                        {m.subject}
                      </span>
                      <span className="text-[12.5px] text-ink-3 mr-2">
                        — {m.name}
                      </span>
                    </span>
                    <span className="num text-[11.5px] text-ink-3" dir="ltr">
                      {m.received_at} · {m.ref}
                    </span>
                  </button>
                  {open === m.ref && (
                    <div className="px-4 pb-4 border-t border-line pt-3">
                      <p className="m-0 num text-[12px] text-ink-3 mb-2"
                         dir="ltr">{m.email}</p>
                      <p className="m-0 text-[14px] leading-[1.95]
                                    whitespace-pre-wrap">{m.body}</p>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}

          <p className="m-0 text-[12px] text-ink-3">
            پیام شماره‌ی <span className="fig">{faPlain(1)}</span> تازه‌ترین
            است؛ ترتیب از جدید به قدیم.
          </p>
        </>
      )}
    </div>
  );
}

/* A listing as the operator reads it to decide: what the seller wrote, and
 * nothing of the seller. */
function Listing({ fields: f, tag }: { fields: ListingFields; tag: string }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="eyebrow !mb-0">{tag}</p>
      <p className="m-0 text-[15px] font-medium">
        {f.make} {f.model}{f.trim ? ` ${f.trim}` : ''} · <span className="fig">{faPlain(f.year_jalali)}</span>
      </p>
      <p className="m-0 text-[13px] text-ink-2">
        {km(f.mileage_km)} · {f.price_toman ? toman(f.price_toman) : 'بی‌قیمت'}{f.negotiable ? ' · توافقی' : ''} ·{' '}
        {f.province}{f.city ? `، ${f.city}` : ''}
      </p>
      {f.description ? (
        <p className="m-0 text-[13.5px] leading-[1.9] whitespace-pre-wrap max-w-[70ch]">{f.description}</p>
      ) : null}
    </div>
  );
}
