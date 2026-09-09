'use client';

import { useState } from 'react';

/* The form is validated on the client and again on the server, and the server
   is the one that counts. Client validation here exists to give an immediate,
   Persian error next to the field — not to be the gate. */

type State =
  | { k: 'idle' }
  | { k: 'sending' }
  | { k: 'sent'; ref: string }
  | { k: 'failed'; msg: string };

const EMPTY = { name: '', email: '', subject: '', body: '' };

export default function ContactForm() {
  const [f, setF] = useState(EMPTY);
  const [state, setState] = useState<State>({ k: 'idle' });

  const problems: Partial<Record<keyof typeof EMPTY, string>> = {};
  if (f.name && f.name.trim().length < 2) problems.name = 'نام خیلی کوتاه است';
  if (f.email && !/^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(f.email.trim())) {
    problems.email = 'نشانی ایمیل معتبر نیست';
  }
  if (f.subject && f.subject.trim().length < 2) problems.subject = 'موضوع لازم است';
  if (f.body && f.body.trim().length < 10) {
    problems.body = 'کمی بیشتر بنویس — دست‌کم ده نویسه';
  }

  const ready = f.name.trim().length >= 2
    && /^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(f.email.trim())
    && f.subject.trim().length >= 2
    && f.body.trim().length >= 10;

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setState({ k: 'sending' });
    try {
      const res = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(f),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setState({ k: 'failed', msg: String(body?.detail ?? `خطای ${res.status}`) });
        return;
      }
      setState({ k: 'sent', ref: String(body.ref ?? '') });
      setF(EMPTY);
    } catch {
      setState({ k: 'failed', msg: 'سرویس در دسترس نیست' });
    }
  }

  if (state.k === 'sent') {
    return (
      <section className="panel border-good">
        <p className="eyebrow !text-good">ثبت شد</p>
        <p className="m-0 text-[15px]">
          شماره‌ی پیگیری: <span className="num text-accent font-medium">
            {state.ref}</span>
        </p>
        <button type="button" className="btn mt-5"
                onClick={() => setState({ k: 'idle' })}>
          پیام دیگری بفرست
        </button>
      </section>
    );
  }

  return (
    <form onSubmit={send} className="panel flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="name" label="نام" value={f.name} err={problems.name}
               onChange={(v) => setF({ ...f, name: v })} />
        <Field id="email" label="ایمیل" value={f.email} err={problems.email}
               dir="ltr" onChange={(v) => setF({ ...f, email: v })} />
      </div>
      <Field id="subject" label="موضوع" value={f.subject} err={problems.subject}
             onChange={(v) => setF({ ...f, subject: v })} />
      <div>
        <label htmlFor="body" className="block text-[12.5px] text-ink-3 mb-1.5">
          پیام
        </label>
        <textarea
          id="body"
          rows={7}
          value={f.body}
          onChange={(e) => setF({ ...f, body: e.target.value })}
          className="w-full bg-ground border border-line rounded-[3px]
                     px-3.5 py-2.5 text-[14px] leading-[1.9] text-ink
                     focus:border-accent transition-colors resize-y"
        />
        {problems.body && (
          <p className="m-0 mt-1 text-[12px] text-bad">{problems.body}</p>
        )}
      </div>

      {state.k === 'failed' && (
        <p className="m-0 text-[13px] text-bad bg-bad-soft border border-bad/40
                      rounded-[2px] px-3 py-2">{state.msg}</p>
      )}

      <div className="flex items-center gap-3 flex-wrap">
        <button type="submit" className="btn-solid"
                disabled={!ready || state.k === 'sending'}>
          {state.k === 'sending' ? 'در حال ارسال…' : 'بفرست'}
        </button>
        <span className="text-[12px] text-ink-3">
          هیچ داده‌ای جز همین چهار فیلد ارسال نمی‌شود.
        </span>
      </div>
    </form>
  );
}

function Field({
  id, label, value, onChange, err, dir,
}: {
  id: string; label: string; value: string;
  onChange: (v: string) => void; err?: string; dir?: 'ltr' | 'rtl';
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-[12.5px] text-ink-3 mb-1.5">
        {label}
      </label>
      <input
        id={id}
        value={value}
        dir={dir}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-ground border border-line rounded-[3px]
                   px-3.5 py-2.5 text-[14px] text-ink focus:border-accent
                   transition-colors"
      />
      {err && <p className="m-0 mt-1 text-[12px] text-bad">{err}</p>}
    </div>
  );
}
