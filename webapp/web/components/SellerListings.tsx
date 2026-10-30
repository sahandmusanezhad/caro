'use client';

import { useEffect, useState } from 'react';
import {
  conditionLabel, faNum, faPlain, km, modelLabel, toman, trimLabel,
} from '@/lib/format';
import {
  FUEL_FA, GEARBOX_FA, KEPT_APART_FA, NUMBER_ON_PRESS_FA, OFF_FA, REPORT_FA,
  sellerApi, type PublicListing,
} from '@/lib/seller';

/* Listings sellers posted on CARO themselves, under their own heading and
 * never among the corpus's (docs/SELLER_LISTINGS.md). Each is the version the
 * operator approved. The seller's number is in no page and no answer the list
 * gives: «نمایش شماره» asks for it, one press at a time, and only where the
 * seller chose to show it. */

export function SellerListingCard({ listing }: { listing: PublicListing }) {
  const title = modelLabel([listing.make, listing.model].join('|'));
  const facts = [
    `مدل ${faPlain(listing.year_jalali)}`,
    listing.mileage_km === 0 ? 'کارکرد صفر' : km(listing.mileage_km),
    listing.gearbox ? GEARBOX_FA[listing.gearbox] ?? listing.gearbox : null,
    listing.fuel ? FUEL_FA[listing.fuel] ?? listing.fuel : null,
    listing.color,
    listing.body ? conditionLabel(listing.body) : null,
  ].filter(Boolean) as string[];
  return (
    <article className="panel flex flex-col gap-2" data-seller-listing={listing.id}>
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h3 className="m-0 text-[16px] font-bold">
          {title}{listing.trim ? <span className="text-ink-3 font-normal"> · {trimLabel(listing.trim)}</span> : null}
        </h3>
        <span className="fig text-[15px] font-bold">
          {listing.negotiable || listing.price_toman == null ? 'توافقی' : toman(listing.price_toman)}
        </span>
      </div>
      <p className="m-0 text-[13px] text-ink-2">{facts.join(' · ')}</p>
      <p className="m-0 text-[12.5px] text-ink-3">
        {listing.province}{listing.city ? `، ${listing.city}` : ''}
      </p>
      {listing.description ? (
        <p className="m-0 text-[13.5px] leading-[1.9] whitespace-pre-line">{listing.description}</p>
      ) : null}
      <div className="flex gap-2 flex-wrap items-center mt-1">
        {listing.has_phone ? <RevealButton id={listing.id} /> : (
          <span className="text-[12.5px] text-ink-3">فروشنده شماره‌اش را نشان نمی‌دهد.</span>
        )}
        <ReportButton id={listing.id} />
      </div>
    </article>
  );
}

export function RevealButton({ id }: { id: number }) {
  const [phone, setPhone] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (phone) {
    const spaced = `${phone.slice(0, 4)} ${phone.slice(4, 7)} ${phone.slice(7)}`;
    return (
      <a href={`tel:${phone}`} className="btn-solid no-underline fig" dir="ltr">
        {spaced.replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[Number(d)])}
      </a>
    );
  }
  return (
    <>
      <button type="button" className="btn-solid" disabled={busy}
              onClick={async () => {
                setBusy(true); setErr(null);
                const r = await sellerApi.reveal(id);
                setBusy(false);
                if (r.ok && r.data) setPhone(r.data.phone);
                else setErr(r.message);
              }}>
        {busy ? 'در حال گرفتن…' : 'نمایش شماره'}
      </button>
      {err ? <span className="text-[12.5px] text-bad">{err}</span> : null}
    </>
  );
}

export function ReportButton({ id }: { id: number }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [done, setDone] = useState<string | null>(null);
  if (done) return <span className="text-[12.5px] text-ink-3">{done}</span>;
  if (!open) {
    return (
      <button type="button" className="btn text-[12.5px]" onClick={() => setOpen(true)}>
        گزارش آگهی
      </button>
    );
  }
  return (
    <span className="flex gap-2 items-center flex-wrap">
      <select value={reason} onChange={(e) => setReason(e.target.value)} aria-label="دلیل گزارش"
              className="bg-ground border border-line rounded-2xl px-3 py-1.5 text-[13px]">
        <option value="">دلیل را انتخاب کن</option>
        {Object.entries(REPORT_FA).map(([k, fa]) => <option key={k} value={k}>{fa}</option>)}
      </select>
      <button type="button" className="btn text-[12.5px]" disabled={!reason}
              onClick={async () => {
                const r = await sellerApi.report(id, reason);
                setDone(r.ok ? 'گزارشت ثبت شد. سپاس.' : (r.message ?? 'گزارش ثبت نشد.'));
              }}>
        بفرست
      </button>
    </span>
  );
}

export default function SellerListings({
  make, model, quietWhenEmpty = false,
}: { make?: string; model?: string; quietWhenEmpty?: boolean }) {
  const [state, setState] = useState<'loading' | 'off' | 'ready' | 'error'>('loading');
  const [items, setItems] = useState<PublicListing[]>([]);
  useEffect(() => {
    const q = new URLSearchParams();
    if (make) q.set('make', make);
    if (model) q.set('model', model);
    const qs = q.toString() ? `?${q.toString()}` : '';
    sellerApi.list(qs).then((r) => {
      if (r.ok && r.data) { setItems(r.data.listings); setState('ready'); }
      else setState(r.status === 503 ? 'off' : 'error');
    });
  }, [make, model]);

  if (quietWhenEmpty && (state !== 'ready' || items.length === 0)) return null;
  return (
    <section className="flex flex-col gap-3" data-section="seller-listings">
      <div>
        <h2 className="m-0 text-[18px] font-bold">آگهی‌های ثبت‌شده در کارو</h2>
        <p className="m-0 mt-1 text-[12.5px] text-ink-3 max-w-[72ch] leading-[1.9]">
          {KEPT_APART_FA} {NUMBER_ON_PRESS_FA}
        </p>
      </div>
      {state === 'loading' ? <p className="m-0 text-[13px] text-ink-3">در حال خواندن…</p> : null}
      {state === 'off' ? <div className="panel text-[13.5px] text-ink-3">{OFF_FA}</div> : null}
      {state === 'error' ? <div className="panel text-[13.5px] text-bad">فهرست خوانده نشد.</div> : null}
      {state === 'ready' && items.length === 0 ? (
        <div className="panel text-[13.5px] text-ink-3">هنوز آگهی تأییدشده‌ای نیست.</div>
      ) : null}
      {state === 'ready' && items.length > 0 ? (
        <>
          <p className="m-0 text-[12.5px] text-ink-3"><b className="fig">{faNum(items.length)}</b> آگهی</p>
          <div className="grid gap-3 md:grid-cols-2">
            {items.map((x) => <SellerListingCard key={x.id} listing={x} />)}
          </div>
        </>
      ) : null}
    </section>
  );
}
