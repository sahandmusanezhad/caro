'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { asciiDigits } from '@/lib/format';
import { OFF_FA, sellerApi } from '@/lib/seller';

/* A seller's login: the number, then the six digits the SMS brought
 * (webapp/api/accounts.py). The number is sent in whichever digits it was
 * typed in -- the server reads Persian ones -- and the code in ASCII, the way
 * the operator's code is. Nothing is kept in the browser but the cookie the
 * server sets, which no script can read. */

export const LOGIN_INTRO_FA =
  'برای ثبت آگهی با شماره‌ی همراهت وارد شو. کد شش‌رقمی پیامک می‌شود و دو دقیقه اعتبار دارد.';

export default function SellerLogin() {
  const router = useRouter();
  const [on, setOn] = useState<boolean | null>(null);
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'phone' | 'code'>('phone');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    sellerApi.status().then((r) => setOn(Boolean(r.ok && r.data?.store === 'on' && r.data?.sms !== 'off'
                                                  && r.data?.sms !== 'refused')));
    sellerApi.me().then((r) => { if (r.ok) router.replace('/my-listings'); });
  }, [router]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    const r = await sellerApi.sendCode(phone.trim());
    setBusy(false);
    if (r.ok) { setStep('code'); setMsg('کد فرستاده شد. اگر نرسید، دو دقیقه بعد دوباره بگیر.'); }
    else setMsg(r.message);
  }

  async function enter(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    const r = await sellerApi.login(phone.trim(), asciiDigits(code.trim()));
    setBusy(false);
    setCode('');
    if (r.ok) router.push('/my-listings');
    else setMsg(r.message);
  }

  return (
    <div className="flex flex-col gap-5 max-w-[30rem]">
      <section>
        <p className="eyebrow">آگهی فروشنده‌ها</p>
        <h1 className="m-0 text-[26px] font-bold">ورود</h1>
        <p className="m-0 mt-2 text-[13.5px] text-ink-2 leading-[1.9]">{LOGIN_INTRO_FA}</p>
      </section>
      {on === false ? <div className="panel text-[13.5px] text-ink-3">{OFF_FA}</div> : (
        step === 'phone' ? (
          <form onSubmit={send} className="panel flex gap-2 flex-wrap items-end" data-step="phone">
            <div className="flex-1 min-w-[14rem]">
              <label htmlFor="phone" className="block text-[12.5px] text-ink-3 mb-1.5">شماره‌ی همراه</label>
              <input id="phone" type="tel" inputMode="tel" autoComplete="tel" dir="ltr" value={phone}
                     placeholder="۰۹۱۲۳۴۵۶۷۸۹" onChange={(e) => setPhone(e.target.value)}
                     className="w-full bg-ground border border-line rounded-2xl px-3.5 py-2.5 text-[15px] num
                                focus:border-accent transition-colors" />
            </div>
            <button type="submit" className="btn-solid" disabled={busy || !phone.trim()}>
              {busy ? 'در حال فرستادن…' : 'بفرست'}
            </button>
          </form>
        ) : (
          <form onSubmit={enter} className="panel flex gap-2 flex-wrap items-end" data-step="code">
            <div className="w-[12rem]">
              <label htmlFor="code" className="block text-[12.5px] text-ink-3 mb-1.5">کد شش‌رقمی</label>
              <input id="code" type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={6}
                     dir="ltr" value={code} onChange={(e) => setCode(e.target.value)}
                     className="w-full bg-ground border border-line rounded-2xl px-3.5 py-2.5 text-[15px] num
                                tracking-[0.3em] focus:border-accent transition-colors" />
            </div>
            <button type="submit" className="btn-solid" disabled={busy || !code.trim()}>
              {busy ? 'در حال ورود…' : 'ورود'}
            </button>
            <button type="button" className="btn" onClick={() => { setStep('phone'); setMsg(null); }}>
              شماره را عوض کن
            </button>
          </form>
        )
      )}
      {msg ? <p className="m-0 text-[13px] text-ink-2 bg-sunk border border-line rounded-lg px-3 py-2">{msg}</p> : null}
    </div>
  );
}
