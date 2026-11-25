'use client';

import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { api, type Filters, type ModelSummary, type SortKey } from '@/lib/api';
import { asciiDigits, faPlain, modelLabel } from '@/lib/format';
import {
  K_MAX, KM_UNIT, PRICE_UNIT, SORTS, SORT_FA, SORT_WHY_FA, countSet, type FilterState,
} from '@/lib/filters';
import { PROVINCES_FA } from '@/lib/seller';

/* The filter panel, as on Divar (the owner's choice of 2026-11-25): a make
 * and its model, the model year between two years, the price between two
 * amounts, the mileage between two readings, a province; the order, and how
 * many listings to see. It stands beside the sentence on the search page and
 * alone on the filter page, and the page's address carries what it states.
 *
 * It decides nothing about a listing: it hands its fields to the API, which
 * judges them as it judges a sentence's constraints (webapp/api/constraints.py)
 * and holds apart a listing that carries no value for one. What it does is
 * never send a range the wrong way round: it says so beside the field, in the
 * page, and waits (no browser alert, the site's rule).
 *
 * The makes, the models and the years offered are the served corpus's own
 * (`/api/models`), so the panel never offers a model nobody listed. Until they
 * arrive the two lists offer «همه» alone, and the rest of the panel works. */

const FIELD = 'w-full bg-ground border border-line rounded-2xl px-3.5 py-2.5 text-[14px] '
  + 'text-ink focus:border-accent transition-colors';
const LABEL = 'block text-[12.5px] text-ink-3 mb-1.5';

/* A number as the field shows it: in Persian digits, as the rest of the page
   writes numbers, and read back from either (`fromText`). */
function asText(n: number | undefined, unit = 1): string {
  return n === undefined ? ''
    : (n / unit).toLocaleString('fa-IR', { useGrouping: false, maximumFractionDigits: 3 });
}

/** A typed amount in units («۱٬۵۰۰» million), back to a whole number, or
 *  undefined where the field is empty or is not a number. */
function fromText(t: string, unit = 1): number | undefined | 'bad' {
  const s = asciiDigits(t).replace(/[,،٬\s]/g, '').replace('٫', '.');
  if (!s) return undefined;
  if (!/^\d+(\.\d+)?$/.test(s)) return 'bad';
  return Math.round(Number(s) * unit);
}

export default function FilterPanel({
  initial,
  onApply,
  busy = false,
  heading = 'فیلتر آگهی‌ها',
  defaultOpen = true,
}: {
  initial: FilterState;
  onApply: (s: FilterState) => void;
  busy?: boolean;
  heading?: string;
  /* Whether the fields show before the reader asks for them. The search
     page keeps them folded under the sentence until a filter is set; the
     filter page opens them. On a phone the fields are a screen of their
     own, so folded they leave the listings in reach. */
  defaultOpen?: boolean;
}) {
  const id = useId();
  const [open, setOpen] = useState(defaultOpen);
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [make, setMake] = useState(initial.f.make ?? '');
  const [model, setModel] = useState(initial.f.model ?? '');
  const [yearMin, setYearMin] = useState(asText(initial.f.year_min));
  const [yearMax, setYearMax] = useState(asText(initial.f.year_max));
  const [priceMin, setPriceMin] = useState(asText(initial.f.price_min, PRICE_UNIT));
  const [priceMax, setPriceMax] = useState(asText(initial.f.price_max, PRICE_UNIT));
  const [kmMin, setKmMin] = useState(asText(initial.f.km_min, KM_UNIT));
  const [kmMax, setKmMax] = useState(asText(initial.f.km_max, KM_UNIT));
  const [province, setProvince] = useState(initial.f.province ?? '');
  const [sort, setSort] = useState<SortKey>(initial.sort);
  const [k, setK] = useState(asText(initial.k));
  const [faults, setFaults] = useState<Record<string, string>>({});

  useEffect(() => {
    let alive = true;
    api.models().then((r) => { if (alive) setModels(r.models); }).catch(() => { /* the lists stay «همه» */ });
    return () => { alive = false; };
  }, []);

  const makes = useMemo(() => {
    const n = new Map<string, number>();
    for (const m of models) if (m.make) n.set(m.make, (n.get(m.make) ?? 0) + m.listings);
    if (make && !n.has(make)) n.set(make, 0);
    return [...n.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([mk]) => mk);
  }, [models, make]);

  const modelsOf = useMemo(() => {
    const out = models.filter((m) => !make || m.make === make).map((m) => m.model);
    const uniq = [...new Set(out)];
    if (model && !uniq.includes(model)) uniq.unshift(model);
    return uniq;
  }, [models, make, model]);

  const years = useMemo(() => {
    const lo = Math.min(...models.map((m) => m.year_min ?? Infinity), 1380);
    const hi = Math.max(...models.map((m) => m.year_max ?? -Infinity), 1405);
    const out: number[] = [];
    for (let y = hi; y >= lo; y -= 1) out.push(y);
    return out;
  }, [models]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const bad: Record<string, string> = {};
    const pmin = fromText(priceMin, PRICE_UNIT);
    const pmax = fromText(priceMax, PRICE_UNIT);
    const kmin = fromText(kmMin, KM_UNIT);
    const kmax = fromText(kmMax, KM_UNIT);
    const ymin = fromText(yearMin);
    const ymax = fromText(yearMax);
    const count = fromText(k);
    for (const [key, v] of Object.entries({ price: [pmin, pmax], km: [kmin, kmax], year: [ymin, ymax] })) {
      const [lo, hi] = v as (number | undefined | 'bad')[];
      if (lo === 'bad' || hi === 'bad') bad[key] = 'فقط عدد بنویس.';
      else if (lo !== undefined && hi !== undefined && lo > hi) bad[key] = '«از» بیشتر از «تا» است.';
    }
    if (count === 'bad' || count === undefined || count < 1 || count > K_MAX) {
      bad.k = `عددی از ۱ تا ${faPlain(K_MAX)}.`;
    }
    setFaults(bad);
    if (Object.keys(bad).length) return;
    const f: Filters = {};
    if (typeof pmin === 'number') f.price_min = pmin;
    if (typeof pmax === 'number') f.price_max = pmax;
    if (typeof ymin === 'number') f.year_min = ymin;
    if (typeof ymax === 'number') f.year_max = ymax;
    if (typeof kmin === 'number') f.km_min = kmin;
    if (typeof kmax === 'number') f.km_max = kmax;
    if (make) f.make = make;
    if (model) f.model = model;
    if (province) f.province = province;
    onApply({ f, sort, k: count as number });
  }

  function clear() {
    setMake(''); setModel(''); setYearMin(''); setYearMax(''); setPriceMin(''); setPriceMax('');
    setKmMin(''); setKmMax(''); setProvince(''); setFaults({});
    onApply({ f: {}, sort, k: Number(asciiDigits(k)) || initial.k });
  }

  const fault = (key: string) => (faults[key]
    ? <span id={`${id}-${key}-fault`} className="block mt-1 text-[12px] text-bad" data-fault={key}>{faults[key]}</span>
    : null);
  const set = countSet(initial.f);

  return (
    <form onSubmit={submit} className="panel" data-filter-panel aria-labelledby={`${id}-h`} noValidate>
      <div className={`flex items-center justify-between gap-3 flex-wrap ${open ? 'mb-4' : ''}`}>
        <h2 id={`${id}-h`} className="m-0 text-[16px] font-bold">{heading}</h2>
        <div className="flex items-center gap-3">
          {set > 0 && (
            <span className="text-[12.5px] text-ink-3">
              <b className="fig">{faPlain(set)}</b> فیلتر فعال
            </span>
          )}
          <button type="button" className="btn !py-1.5 !px-3.5 !text-[13px]"
                  aria-expanded={open} aria-controls={`${id}-body`}
                  onClick={() => setOpen((o) => !o)}>
            {open ? 'بستن فیلترها' : 'نمایش فیلترها'}
          </button>
        </div>
      </div>

      <div id={`${id}-body`} hidden={!open}>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block">
          <span className={LABEL}>برند</span>
          <select className={FIELD} value={make}
                  onChange={(e) => { setMake(e.target.value); setModel(''); }}>
            <option value="">همه‌ی برندها</option>
            {makes.map((mk) => <option key={mk} value={mk}>{modelLabel(mk)}</option>)}
          </select>
        </label>

        <label className="block">
          <span className={LABEL}>مدل</span>
          <select className={FIELD} value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="">همه‌ی مدل‌ها</option>
            {modelsOf.map((md) => <option key={md} value={md}>{modelLabel(md)}</option>)}
          </select>
        </label>

        <label className="block">
          <span className={LABEL}>استان</span>
          <select className={FIELD} value={province} onChange={(e) => setProvince(e.target.value)}>
            <option value="">همه‌ی استان‌ها</option>
            {PROVINCES_FA.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>

        <label className="block">
          <span className={LABEL}>مرتب‌سازی</span>
          <select className={FIELD} value={sort} onChange={(e) => setSort(e.target.value as SortKey)}
                  aria-describedby={`${id}-sort-why`}>
            {SORTS.map((s) => <option key={s} value={s}>{SORT_FA[s]}</option>)}
          </select>
        </label>

        <fieldset className="m-0 p-0 border-0 sm:col-span-2 lg:col-span-1">
          <legend className={LABEL}>سال ساخت</legend>
          <div className="grid grid-cols-2 gap-2">
            <select className={FIELD} aria-label="سال ساخت، از" value={yearMin}
                    aria-invalid={!!faults.year} aria-describedby={faults.year ? `${id}-year-fault` : undefined}
                    onChange={(e) => setYearMin(e.target.value)}>
              <option value="">از</option>
              {years.map((y) => <option key={y} value={y}>{faPlain(y)}</option>)}
            </select>
            <select className={FIELD} aria-label="سال ساخت، تا" value={yearMax}
                    aria-invalid={!!faults.year} aria-describedby={faults.year ? `${id}-year-fault` : undefined}
                    onChange={(e) => setYearMax(e.target.value)}>
              <option value="">تا</option>
              {years.map((y) => <option key={y} value={y}>{faPlain(y)}</option>)}
            </select>
          </div>
          {fault('year')}
        </fieldset>

        <fieldset className="m-0 p-0 border-0 sm:col-span-2 lg:col-span-1">
          <legend className={LABEL}>قیمت (میلیون تومان)</legend>
          <div className="grid grid-cols-2 gap-2">
            <input className={FIELD} inputMode="decimal" placeholder="از" aria-label="قیمت، از، میلیون تومان"
                   value={priceMin} onChange={(e) => setPriceMin(e.target.value)}
                   aria-invalid={!!faults.price} aria-describedby={faults.price ? `${id}-price-fault` : undefined} />
            <input className={FIELD} inputMode="decimal" placeholder="تا" aria-label="قیمت، تا، میلیون تومان"
                   value={priceMax} onChange={(e) => setPriceMax(e.target.value)}
                   aria-invalid={!!faults.price} aria-describedby={faults.price ? `${id}-price-fault` : undefined} />
          </div>
          {fault('price')}
        </fieldset>

        <fieldset className="m-0 p-0 border-0 sm:col-span-2 lg:col-span-1">
          <legend className={LABEL}>کارکرد (هزار کیلومتر)</legend>
          <div className="grid grid-cols-2 gap-2">
            <input className={FIELD} inputMode="decimal" placeholder="از" aria-label="کارکرد، از، هزار کیلومتر"
                   value={kmMin} onChange={(e) => setKmMin(e.target.value)}
                   aria-invalid={!!faults.km} aria-describedby={faults.km ? `${id}-km-fault` : undefined} />
            <input className={FIELD} inputMode="decimal" placeholder="تا" aria-label="کارکرد، تا، هزار کیلومتر"
                   value={kmMax} onChange={(e) => setKmMax(e.target.value)}
                   aria-invalid={!!faults.km} aria-describedby={faults.km ? `${id}-km-fault` : undefined} />
          </div>
          {fault('km')}
        </fieldset>

        <label className="block">
          <span className={LABEL}>تعداد پیشنهاد</span>
          <input className={FIELD} inputMode="numeric" value={k} onChange={(e) => setK(e.target.value)}
                 aria-invalid={!!faults.k} aria-describedby={faults.k ? `${id}-k-fault` : undefined} />
          {fault('k')}
        </label>
      </div>

      <p id={`${id}-sort-why`} className="m-0 mt-3 text-[12px] leading-6 text-ink-3 max-w-[72ch]">
        {SORT_WHY_FA[sort]}
      </p>

      <div className="flex gap-2 flex-wrap mt-4">
        <button type="submit" className="btn-solid px-6" disabled={busy}>اعمال فیلتر</button>
        <button type="button" className="btn" onClick={clear} disabled={busy}>پاک‌کردن فیلترها</button>
      </div>
      </div>
    </form>
  );
}
