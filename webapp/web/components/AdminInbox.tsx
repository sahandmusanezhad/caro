'use client';

import { useEffect, useState } from 'react';
import { faNum, faPlain } from '@/lib/format';

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
 */

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
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/admin/status')
      .then((r) => r.json())
      .then((d) => setConfigured(Boolean(d.configured)))
      .catch(() => setConfigured(null));
  }, []);

  async function load(e?: React.FormEvent) {
    e?.preventDefault();
    if (!token.trim()) return;
    setBusy(true); setErr(null);
    try {
      const res = await fetch('/api/admin/messages', {
        headers: { 'x-admin-token': token.trim() },
      });
      if (res.status === 401) {
        setErr('توکن پذیرفته نشد.');
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
            className="w-full bg-ground border border-line rounded-[3px]
                       px-3.5 py-2.5 text-[14px] num focus:border-accent
                       transition-colors"
          />
        </div>
        <button type="submit" className="btn-solid"
                disabled={busy || !token.trim()}>
          {busy ? 'در حال بازکردن…' : 'باز کن'}
        </button>
      </form>

      {err && (
        <p className="m-0 text-[13px] text-bad bg-bad-soft border border-bad/40
                      rounded-[2px] px-3 py-2">{err}</p>
      )}

      {msgs && (
        <>
          <p className="m-0 text-[13px] text-ink-2">
            <b className="num">{faNum(msgs.length)}</b> پیام
          </p>

          {msgs.length === 0 ? (
            <div className="panel text-[13.5px] text-ink-3">
              صندوق خالی است.
            </div>
          ) : (
            <ul className="m-0 p-0 list-none flex flex-col gap-px bg-line
                           border border-line">
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
            پیام شماره‌ی <span className="num">{faPlain(1)}</span> تازه‌ترین
            است؛ ترتیب از جدید به قدیم.
          </p>
        </>
      )}
    </div>
  );
}
