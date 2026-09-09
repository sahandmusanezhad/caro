/* The typed surface of `webapp/api/schemas.py`.
 *
 * These interfaces are hand-written rather than generated, and that is a real
 * cost: two hand-written descriptions of one contract drift, and TypeScript
 * validates this file against its own belief about the server — which is
 * precisely the belief that goes stale.
 *
 * So the duplication is checked instead of trusted. `tests/test_api_contract.py`
 * reads this file, extracts every interface's field names, and asserts they
 * are exactly the fields of the matching Pydantic model. Adding a field on one
 * side and not the other fails the suite rather than surfacing months later as
 * an `undefined` on a screen.
 *
 * Codegen would remove the duplication outright and is the better answer at a
 * larger size. It is not worth a build step for eleven interfaces, and the
 * check above closes the gap it would have closed.
 *
 * The one thing this file will not do is invent a fallback. If `/api/search`
 * is unreachable the caller gets a rejected promise and the page says the
 * backend is down — it does not quietly serve a fixture, because a screen that
 * cannot tell you where its numbers came from is the failure this whole
 * project is arguing against.
 */

/* ------------------------------------------------------------------ *
 * The envelope: three questions, three fields.
 *   corpus  what the data is
 *   status  what may be done with it
 *   fault   why we are in that state
 * ------------------------------------------------------------------ */

/** Which exact bytes a served number rests on. Null when there are none. */
export interface CorpusIdentity {
  run_id: string;
  path: string;
  sha256: string;
  bytes: number;
}

export interface CorpusMeta {
  label_fa: string;
  source: string;
  note_fa: string;
  /** Everything the corpus holds. */
  rows: number;
  /* How much of it cleared eligibility and could reach W1. On a published
     artifact these are N and 0 — promotion runs after parsing and cannot carry
     price/mileage provenance — and the gap is the point, not a detail. */
  appraisable: number;
  /* Null when there is no artifact to hash: a generated corpus, or one that
     would not load. Never a placeholder — a digest that renders like a real
     one beside a corpus with no evidence is worse than an absence (D50). */
  identity: CorpusIdentity | null;
}

/** UNUSABLE means an artifact exists on disk and would not load. It is NOT a
 *  fallback to synthetic — D49: a real failure that quietly becomes a
 *  synthetic success is worse than a crash, because the site looks healthy and
 *  labels itself honestly while ignoring the evidence it was built for. */
export type CorpusKind = 'SYNTHETIC' | 'REAL' | 'UNUSABLE';

export interface ServingStatus {
  kind: CorpusKind;
  /** Has an estimator cleared AcceptanceGate on this corpus? */
  gated: boolean;
  /** Did THIS request produce a ranking? */
  served: boolean;
}

export type FaultCode = 'CORPUS_INVALID' | 'ESTIMATOR_NOT_GATED';

export interface Fault {
  code: FaultCode;
  /** The specific detail, for a person. */
  message: string;
  fa: string;
  still_available: string[];
}

export interface Envelope {
  corpus: CorpusMeta;
  status: ServingStatus;
  fault: Fault | null;
}

/* ------------------------------------------------------------------ *
 * Payload
 * ------------------------------------------------------------------ */

/** A listing as parsed. There is no estimate field here, by design (D50):
 *  a refusal returns these, so a refusal carrying an estimate cannot be
 *  constructed on either side of the wire. */
export interface EvidenceItem {
  id: string;
  url: string;
  model_key: string;
  make: string | null;
  model: string | null;
  trim: string | null;
  year_jalali: number | null;
  mileage_km: number | null;
  asking_price_toman: number | null;
  gearbox: string | null;
  fuel: string | null;
  color: string | null;
  condition: string | null;
  province: string | null;
  seller_type: string | null;
}

export interface ScoredItem extends EvidenceItem {
  /* Narrowed from `EvidenceItem`: a row that was scored cleared eligibility,
     and eligibility is exactly the check that these are present and
     plausible — so they cannot be null, by construction. */
  year_jalali: number;
  mileage_km: number;
  asking_price_toman: number;
  rank: number;
  role_fa: string;
  score: number;
  estimate_toman: number;
  opportunity_toman: number;
  expected_damage_toman: number;
  terms: Record<string, number>;
  features: Record<string, number>;
}

export interface WeightSet {
  value: number;
  risk: number;
  running_cost: number;
  liquidity: number;
  mileage: number;
  recency: number;
}

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

/* ------------------------------------------------------------------ *
 * Responses
 * ------------------------------------------------------------------ */

export interface SearchResponse extends Envelope {
  intent: Intent;
  considered: number;
  appraisable: number;
  candidates: number;
  relaxed: boolean;
  relaxation_fa: string;
  items: ScoredItem[];
  evidence: EvidenceItem[];
}

export interface ListingResponse extends Envelope {
  listing: EvidenceItem;
}

export interface CompareResponse extends Envelope {
  rows: ScoredItem[];
  evidence: EvidenceItem[];
}

export type CorpusResponse = Envelope;

/* ------------------------------------------------------------------ */

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
  corpus: () => json<CorpusResponse>('/api/corpus'),

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
    json<ListingResponse>(`/api/listing/${encodeURIComponent(id)}`),

  compare: (ids: string[], q = 'خودرو') =>
    json<CompareResponse>('/api/compare', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ids, q }),
    }),
};

/** `8f3a…c21d`. The full digest stays in the payload for copying. */
export function shortSha(sha: string): string {
  return `${sha.slice(0, 4)}…${sha.slice(-4)}`;
}

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
