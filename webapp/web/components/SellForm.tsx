'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { CONDITION_FA, asciiDigits, modelLabel } from '@/lib/format';
import {
  BODY_KEYS, COLORS_FA, DESCRIPTION_RULE_FA, FUEL_FA, GEARBOX_FA, PROVINCES_FA,
  sellerApi, type ListingFields,
} from '@/lib/seller';

/* «ثبت آگهی», and its edit. The server decides (webapp/api/listings.py,
 * faults()); this form only gathers, and draws each field's refusal beside
 * it. Make and model come from the site's own table where the car is in it,
 * so the listing appears on that model's page; «دیگر» takes the seller's own
 * words, kept as written. */

export const EMPTY: ListingFields = {
  make: '', model: '', trim: null, year_jalali: 0, mileage_km: 0, price_toman: null,
  negotiable: false, province: '', city: null, gearbox: null, fuel: null, color: null,
  body: null, description: '', show_phone: false,
};

/** The form's numbers, typed in any digits and with any separators. */
export function toInt(s: string): number | null {
  const d = asciiDigits(s).replace(/[^\d]/g, '');
  return d ? Number(d) : null;
}

type Pair = { make: string; model: string };

export default function SellForm({ editId, pairs = [] }: { editId?: number; pairs?: Pair[] }) {
  const router = useRouter();
  const [x, setX] = useState<ListingFields>(EMPTY);
  const [year, setYear] = useState('');
  const [mileage, setMileage] = useState('');
  const [price, setPrice] = useState('');
  const [other, setOther] = useState(false);
  const [faults, setFaults] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (editId === undefined) return;
    sellerApi.mine().then((r) => {
      const item = r.data?.listings.find((l) => l.id === editId);
      const v = item?.pending ?? item?.live;
      if (!v) return;
      setX(v);
      setYear(String(v.year_jalali));
      setMileage(String(v.mileage_km));
      setPrice(v.price_toman == null ? '' : String(v.price_toman));
      setOther(!pairs.some((p) => p.make === v.make && p.model === v.model));
    });
  }, [editId, pairs]);

  const set = <K extends keyof ListingFields>(k: K, v: ListingFields[K]) => setX((o) => ({ ...o, [k]: v }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const body: ListingFields = {
      ...x,
      year_jalali: toInt(year) ?? 0,
      mileage_km: toInt(mileage) ?? -1,
      price_toman: x.negotiable ? null : toInt(price),
    };
    setBusy(true); setMsg(null); setFaults({});
    const r = editId === undefined ? await sellerApi.create(body) : await sellerApi.edit(editId, body);
    setBusy(false);
    if (r.ok) { router.push('/my-listings'); return; }
    setFaults(r.faults);
    setMsg(r.message);
  }

  const field = (k: string) => faults[k]
    ? <span className="block mt-1 text-[12px] text-bad" data-fault={k}>{faults[k]}</span> : null;
  const input = 'w-full bg-ground border border-line rounded-2xl px-3.5 py-2.5 text-[14px] focus:border-accent';
  const pairValue = other ? '__other' : (x.make && x.model ? `${x.make}|${x.model}` : '');

  return (
    <form onSubmit={submit} className="panel grid gap-4 sm:grid-cols-2" data-form="sell">
      <label className="sm:col-span-2 text-[12.5px] text-ink-3">
        خودرو
        <select className={input} value={pairValue}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === '__other') { setOther(true); set('make', ''); set('model', ''); return; }
                  setOther(false);
                  const [mk, md] = v.split('|');
                  set('make', mk ?? ''); set('model', md ?? '');
                }}>
          <option value="">انتخاب کن</option>
          {pairs.map((p) => (
            <option key={`${p.make}|${p.model}`} value={`${p.make}|${p.model}`}>
              {modelLabel(`${p.make}|${p.model}`)}
            </option>
          ))}
          <option value="__other">دیگر (خودت بنویس)</option>
        </select>
        {field('make')}{field('model')}
      </label>
      {other ? (
        <>
          <label className="text-[12.5px] text-ink-3">سازنده
            <input className={input} value={x.make} onChange={(e) => set('make', e.target.value)} />
          </label>
          <label className="text-[12.5px] text-ink-3">مدل
            <input className={input} value={x.model} onChange={(e) => set('model', e.target.value)} />
          </label>
        </>
      ) : null}
      <label className="text-[12.5px] text-ink-3">تیپ (اختیاری)
        <input className={input} value={x.trim ?? ''} onChange={(e) => set('trim', e.target.value || null)} />
        {field('trim')}
      </label>
      <label className="text-[12.5px] text-ink-3">سال ساخت
        <input className={`${input} num`} inputMode="numeric" dir="ltr" value={year}
               placeholder="۱۳۹۸" onChange={(e) => setYear(e.target.value)} />
        {field('year_jalali')}
      </label>
      <label className="text-[12.5px] text-ink-3">کارکرد (کیلومتر)
        <input className={`${input} num`} inputMode="numeric" dir="ltr" value={mileage}
               onChange={(e) => setMileage(e.target.value)} />
        {field('mileage_km')}
      </label>
      <label className="text-[12.5px] text-ink-3">قیمت (تومان)
        <input className={`${input} num`} inputMode="numeric" dir="ltr" value={price} disabled={x.negotiable}
               onChange={(e) => setPrice(e.target.value)} />
        <span className="flex gap-2 items-center mt-1.5 text-ink-2">
          <input type="checkbox" checked={x.negotiable} onChange={(e) => set('negotiable', e.target.checked)} />
          توافقی
        </span>
        {field('price_toman')}
      </label>
      <label className="text-[12.5px] text-ink-3">استان
        <select className={input} value={x.province} onChange={(e) => set('province', e.target.value)}>
          <option value="">انتخاب کن</option>
          {PROVINCES_FA.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        {field('province')}
      </label>
      <label className="text-[12.5px] text-ink-3">شهر (اختیاری)
        <input className={input} value={x.city ?? ''} onChange={(e) => set('city', e.target.value || null)} />
        {field('city')}
      </label>
      {([['gearbox', 'گیربکس', GEARBOX_FA], ['fuel', 'سوخت', FUEL_FA]] as const).map(([k, fa, labels]) => (
        <label key={k} className="text-[12.5px] text-ink-3">{fa}
          <select className={input} value={x[k] ?? ''} onChange={(e) => set(k, e.target.value || null)}>
            <option value="">ثبت نمی‌کنم</option>
            {Object.entries(labels).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          {field(k)}
        </label>
      ))}
      <label className="text-[12.5px] text-ink-3">رنگ
        <select className={input} value={x.color ?? ''} onChange={(e) => set('color', e.target.value || null)}>
          <option value="">ثبت نمی‌کنم</option>
          {COLORS_FA.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        {field('color')}
      </label>
      <label className="text-[12.5px] text-ink-3">وضعیت بدنه
        <select className={input} value={x.body ?? ''} onChange={(e) => set('body', e.target.value || null)}>
          <option value="">ثبت نمی‌کنم</option>
          {BODY_KEYS.map((b) => <option key={b} value={b}>{CONDITION_FA[b]}</option>)}
        </select>
        {field('body')}
      </label>
      <label className="sm:col-span-2 text-[12.5px] text-ink-3">توضیح
        <textarea className={`${input} min-h-[7rem] leading-[1.9]`} value={x.description} maxLength={1000}
                  onChange={(e) => set('description', e.target.value)} />
        <span className="block mt-1 text-[12px] text-ink-3">{DESCRIPTION_RULE_FA}</span>
        {field('description')}
      </label>
      <label className="sm:col-span-2 flex gap-2 items-center text-[13.5px]">
        <input type="checkbox" checked={x.show_phone} onChange={(e) => set('show_phone', e.target.checked)} />
        شماره‌ام با دکمه‌ی «نمایش شماره» به خریدار نشان داده شود
      </label>
      <div className="sm:col-span-2 flex gap-3 items-center flex-wrap">
        <button type="submit" className="btn-solid" disabled={busy}>
          {busy ? 'در حال فرستادن…' : editId === undefined ? 'ثبت و فرستادن برای تأیید' : 'فرستادن ویرایش برای تأیید'}
        </button>
        <span className="text-[12.5px] text-ink-3">هر آگهی و هر ویرایش پیش از انتشار تأیید می‌شود.</span>
      </div>
      {msg ? <p className="sm:col-span-2 m-0 text-[13px] text-bad">{msg}</p> : null}
    </form>
  );
}
