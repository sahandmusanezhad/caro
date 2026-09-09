/* The typed surface of `webapp/api/main.py`.
 *
 * These interfaces are hand-written against that module rather than generated,
 * and the reason is worth recording: the shapes below are a claim about what
 * the backend returns, and a generated client would make that claim silently.
 * Anything the API does not send is optional here, and the components render
 * the absence rather than a default.
 *
 * The one thing this file will not do is invent a fallback. If `/api/search`
 * is unreachable the caller gets a rejected promise and the page says the
 * backend is down — it does not quietly serve a fixture, because a screen that
 * cannot tell you where its numbers came from is the failure this whole
 * project is arguing against.
 */

/** Which exact bytes a served number rests on. Null when there are none. */
export interface CorpusIdentity {
  run_id: string;
  path: string;
  sha256: string;
  bytes: number;
}

export interface CorpusInfo {
  kind: 'SYNTHETIC' | 'REAL';
  label_fa: string;
  rows: number;
  gated: boolean;
  source: string;
  note_fa: string;
  /* How many of `rows` cleared eligibility and could reach W1. On a published
     artifact these diverge completely — promotion runs after parsing and
     cannot carry price/mileage provenance, so eligibility fails closed on all
     of it. Showing only one of the two would hide that gap. */
  appraisable: number;
  /* Null for a synthetic corpus — it is generated, so no artifact exists to
     hash. Rendered as an explicit absence, never as a blank: a missing digest
     and a digest nobody displayed look the same on screen otherwise. */
  identity: CorpusIdentity | null;
}

/** `8f3a…c21d`. The full digest stays in the payload for copying. */
export function shortSha(sha: string): string {
  return `${sha.slice(0, 4)}…${sha.slice(-4)}`;
}

export interface WeightSet {
  value: number;
  risk: number;
  running_cost: number;
  liquidity: number;
  mileage: number;
  recency: number;
}

export const WEIGHT_KEYS: (keyof WeightSet)[] = [
  'value', 'risk', 'running_cost', 'liquidity', 'mileage', 'recency',
];

export const WEIGHT_FA: Record<keyof WeightSet, string> = {
  value: 'صرفه',
  risk: 'ریسک',
  running_cost: 'هزینه‌ی نگهداری',
  liquidity: 'نقدشوندگی',
  mileage: 'کارکرد',
  recency: 'تازگی',
};

export interface Intent {
  query: string;
  budget_max_toman: number | null;
  budget_min_toman: number | null;
  budget_hard: boolean;
  models: string[];
  year_min: number | null;
  max_mileage_km: number | null;
  use_case: string | null;
  risk_profile: string | null;
  deal_breakers: string[];
  assumptions: string[];
  unparsed: string[];
  weights: WeightSet;
}

export interface Listing {
  id: string;
  model_key: string;
  make: string | null;
  model: string | null;
  trim: string | null;
  year_jalali: number;
  /* Null is reachable on the evidence path: a listing can be published with
     no odometer or no price that survived the guards, and the row is still
     evidence. The UI renders «ثبت‌نشده», never a zero. */
  mileage_km: number | null;
  asking_price_toman: number | null;
  features: Record<string, number | string | boolean | null>;
}

export interface ScoredListing extends Listing {
  /* Narrowed back from `Listing`. A row that was scored cleared eligibility,
     and eligibility is exactly the check that both of these are present and
     plausible — so on this type they cannot be null, by construction rather
     than by optimism. */
  mileage_km: number;
  asking_price_toman: number;
  rank: number;
  role_fa: string;
  score: number;
  estimate_toman: number;
  opportunity_toman: number;
  expected_damage_toman: number;
  terms: Record<string, number>;
}

export interface Refusal {
  reason: string;
  detail: string;
  fa?: string;
  still_available?: string[];
}

export interface SearchResponse {
  corpus: CorpusInfo;
  intent: Intent;
  considered: number;
  appraisable: number;
  candidates: number;
  relaxed: boolean;
  relaxation_fa: string;
  served: boolean;
  refusal: Refusal | null;
  items: ScoredListing[];
  /* Present when `served` is false: the matching listings as parsed, with no
     estimate, no score and no ordering. The refusal says evidence is still
     available; this is that evidence, rather than a promise of it. */
  evidence: Listing[];
}

export interface CompareResponse {
  corpus: CorpusInfo;
  served: boolean;
  refusal?: Refusal | null;
  rows: (Listing | ScoredListing)[];
}

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { cache: 'no-store', ...init });
  } catch {
    throw new ApiError(0, 'پاسخی از سرویس دریافت نشد. آیا بک‌اند بالا است؟');
  }
  if (!res.ok) {
    // A refusal is a 200 by design (D11). Reaching here means something
    // actually broke, so the message says so rather than dressing it up.
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch { /* body was not JSON; the status stands on its own */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  corpus: () => json<{ corpus: CorpusInfo }>('/api/corpus'),

  search: (q: string, k = 6) =>
    json<SearchResponse>(`/api/search?q=${encodeURIComponent(q)}&k=${k}`),

  reweight: (q: string, weights: Partial<WeightSet>, k = 6) =>
    json<SearchResponse>(
      `/api/search/reweight?q=${encodeURIComponent(q)}&k=${k}`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(weights),
      },
    ),

  listing: (id: string) =>
    json<{ corpus: CorpusInfo; listing: Listing }>(
      `/api/listing/${encodeURIComponent(id)}`),

  compare: (ids: string[], q = 'خودرو') =>
    json<CompareResponse>('/api/compare', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ids, q }),
    }),
};

/** Persian labels for the scoring terms `Ranker` puts in `breakdown`. */
export const TERM_FA: Record<string, string> = {
  value: 'صرفه',
  risk: 'ریسک',
  running_cost: 'هزینه‌ی نگهداری',
  liquidity: 'نقدشوندگی',
  mileage: 'کارکرد',
  recency: 'تازگی',
  opportunity: 'فرصت',
  penalty: 'جریمه',
};

export function termLabel(k: string): string {
  return TERM_FA[k] ?? k.replace(/_/g, ' ');
}
