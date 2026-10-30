'use client';

import { useEffect, useState } from 'react';
import { asciiDigits, faNum, faPlain } from '@/lib/format';

/* The admin view of the contact inbox.
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
 * app beside the token. A code opens once, so it is cleared after every try,
 * and its digits are sent in ASCII: a header carries no Persian digit.
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

export default function AdminInbox() {
  const [token, setToken] = useState('');
  const [msgs, setMsgs] = useState<Msg[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [second, setSecond] = useState<SecondFactor>('off');
  const [code, setCode] = useState('');
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/admin/status')
      .then((r) => r.json())
      .then((d) => {
        setConfigured(Boolean(d.configured));
        if (d.second_factor === 'on' || d.second_factor === 'unreadable') setSecond(d.second_factor);
      })
      .catch(() => setConfigured(null));
  }, []);

  async function load(e?: React.FormEvent) {
    e?.preventDefault();
    if (!token.trim()) return;
    setBusy(true); setErr(null);
    const typed = asciiDigits(code.trim());
    setCode('');
    try {
      const headers: Record<string, string> = { 'x-admin-token': token.trim() };
      if (second !== 'off' && typed) headers['x-admin-code'] = typed;
      const res = await fetch('/api/admin/messages', { headers });
      if (res.status === 401) {
        setErr(second === 'off'
          ? 'توکن پذیرفته نشد.'
          : 'توکن یا کد پذیرفته نشد. هر کد یک بار باز می‌کند؛ کد تازه‌ی اپ را بزن.');
        setMsgs(null);
        return;
      }
      if (res.status === 429) {
        setErr('تلاش‌های ناموفق این نشانی زیاد بوده است. چند دقیقه بعد دوباره امتحان کن.');
        setMsgs(null);
        return;
      }
      if (!res.ok) { setErr(`خطای ${res.status}`); setMsgs(null); return; }
      const d = await res.json();
      setMsgs(d.messages as Msg[]);
    } catch {
      setErr('سرویس در دسترس نیست');
      setMsgs(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <section>
        <p className="eyebrow">مدیریت · صندوق پیام</p>
        <h1 className="m-0 text-[26px] font-bold">پیام‌های دریافتی</h1>
      </section>

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
          {busy ? 'در حال بازکردن…' : 'باز کن'}
        </button>
      </form>

      {err && (
        <p className="m-0 text-[13px] text-bad bg-bad-soft border border-bad/40
                      rounded-lg px-3 py-2">{err}</p>
      )}

      {msgs && (
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
