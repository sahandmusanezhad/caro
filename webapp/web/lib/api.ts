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

/** UNUSABLE means nothing may be served and this is not the documented
 *  absence: either an artifact exists and would not load, or a run was asked
 *  for and is not there. It is NOT a fallback to synthetic — D49: a real
 *  failure that quietly becomes a synthetic success is worse than a crash,
 *  because the site looks healthy and labels itself honestly while ignoring
 *  the evidence it was built for. Which of the two it is, is `fault.code`. */
export type CorpusKind = 'SYNTHETIC' | 'REAL' | 'UNUSABLE';

export interface ServingStatus {
  kind: CorpusKind;
  /** Has an estimator cleared AcceptanceGate on this corpus? */
  gated: boolean;
  /** Did THIS request produce a ranking? */
  served: boolean;
}

/** Why we are in this state, as something to branch on — never as prose to
 *  read. Three groups, and which group a code is in decides what a screen may
 *  say:
 *
 *   about the SOURCE, nothing can be served — do not name a car
 *     CORPUS_INVALID         an artifact exists and will not load
 *     RUN_NOT_FOUND          CARO_RUN names a run with no artifact on disk
 *
 *   about the CLAIM, a corpus was read — show evidence, no estimate
 *     ESTIMATOR_NOT_GATED    nothing has cleared the acceptance gate here
 *
 *   about the RESOURCE, a corpus was read and lacks it — these ride on a 404
 *     LISTING_NOT_FOUND      that id is not in the corpus being served
 *     COMPARE_IDS_NOT_FOUND  not one of the requested ids is
 *
 * The split matters on screen: «this listing is not here» is a statement about
 * a corpus we READ, and a page that says it when no corpus was read at all is
 * claiming something it cannot know. Both used to arrive as a bare 404, so a
 * client branching on the status alone could not tell them apart. */
export type FaultCode =
  | 'CORPUS_INVALID'
  | 'RUN_NOT_FOUND'
  | 'ESTIMATOR_NOT_GATED'
  | 'LISTING_NOT_FOUND'
  | 'COMPARE_IDS_NOT_FOUND'
  | 'MODEL_NOT_FOUND';

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

/** What an odometer reading is worth, as `caro.ingest.quality.Validity`
 *  grades it (D21, D22). The contract suite holds this union to it, member
 *  for member. */
export type MileageStatus = 'plausible' | 'suspicious' | 'impossible' | 'unknown';

/* How a province was known: the listing names it (`stated`), a city that
   shares its province's name gave it (`city`), or there is none. Held to
   schemas.ProvinceSource by the contract suite, member for member. */
export type ProvinceSource = 'stated' | 'city' | 'none';

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
  /* How the province was known, so that a province read from a city's name
     is never drawn as one the listing stated. Null on an appraisal row. */
  province_source: ProvinceSource | null;
  seller_type: string | null;
  /* D52's gate: only `vehicle` is a car. Sent so the client can apply it —
     what the client should DO with a non-vehicle is not decided yet. */
  product_class: string | null;
  /* The two halves of the price rule FIELD_PROVENANCE.md states for a card:
     `price_status` grades the extraction, `price_kind` says what the number
     means. Null together on an appraisal row, which carries neither and does
     not need to: eligibility applied both before it could be scored. */
  price_status: string | null;
  price_kind: string | null;
  /* The odometer's status, beside the number it grades: FIELD_PROVENANCE.md
     says it travels with the number or neither renders. Null on an
     appraisal row, whose odometer eligibility already checked. */
  mileage_status: MileageStatus | null;
}

/** The constraints a listing can fail to be checked against — the names
 *  `webapp/api/constraints.py` judges them under: three stated as numbers,
 *  the province, then the red lines under their `DEAL_BREAKER_CUES` names.
 *  The contract suite holds this union to the Python Literal member for
 *  member. */
export type ConstraintKey =
  | 'budget' | 'year' | 'mileage' | 'province'
  | 'accident' | 'unclear_documents' | 'manual' | 'repaint';

/** A listing that breaks none of the buyer's constraints and could not be
 *  checked against at least one: it carries no value for it. Not a match —
 *  it never travels in `evidence` — and `unchecked` is never empty. */
export interface UncheckedItem extends EvidenceItem {
  unchecked: ConstraintKey[];
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
  provinces: string[];
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
  /* Only listings that MEET every constraint the buyer stated; one that
     carries no value for some constraint is in `evidence_unchecked`. Each
     list is the first k of its kind and each total counts them all. */
  evidence: EvidenceItem[];
  evidence_total: number;
  evidence_unchecked: UncheckedItem[];
  evidence_unchecked_total: number;
}

export interface ListingResponse extends Envelope {
  /** Null exactly when `status.kind === 'UNUSABLE'`: with no corpus loaded,
   *  "is this id in the corpus?" has no answer, so the endpoint returns the
   *  envelope and no listing rather than a 404 that would claim the car is
   *  not there. Check `fault.code` for which of the two causes it is. */
  listing: EvidenceItem | null;
}

export interface CompareResponse extends Envelope {
  rows: ScoredItem[];
  evidence: EvidenceItem[];
}

export type CorpusResponse = Envelope;

/* A model, as Torob shows a product (webapp/api/market.py). Every price is an
   ASKING price a listing stated, counted; a middle is given only where three
   priced listings or more stand behind it, and is null where fewer do. */
export interface ModelSummary {
  make: string | null;
  model: string;
  listings: number;
  priced: number;
  price_min: number | null;
  price_median: number | null;
  price_max: number | null;
  year_min: number | null;
  year_max: number | null;
}

export interface YearPoint {
  year_jalali: number;
  priced: number;
  price_median: number | null;
}

export interface HistoryPoint {
  run_id: string;
  collected_on: string;
  /** The source the run read, as its artifact names it: 'bama', 'khodro45'. */
  source: string;
  priced: number;
  price_median: number | null;
}

export interface ModelsResponse extends Envelope {
  models: ModelSummary[];
}

export interface ModelResponse extends Envelope {
  summary: ModelSummary | null;
  offers: EvidenceItem[];
  by_year: YearPoint[];
  history: HistoryPoint[];
}

/* ------------------------------------------------------------------ */

/** The price statuses `caro/ingest/quality.py` calls unusable, which is the
 *  first half of the rule FIELD_PROVENANCE.md states for a price on a card:
 *
 *      price_status ∉ this list   AND   price_kind === 'cash'
 *
 *  It is a third hand-written copy of a Python fact, and it is checked rather
 *  than trusted for the same reason the interfaces above are: the contract
 *  suite asserts this list is exactly `UNUSABLE_PRICE`, member for member. */
export const PRICE_STATUS_UNUSABLE: string[] = [
  'ambiguous', 'negotiable', 'absent',
];

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
  /** The envelope's fault, when the server sent one. A 404 from this API is
   *  still a typed response — same envelope, same `fault.code` — so a screen
   *  branches on the code and renders `fault.fa`. Without this the only thing
   *  that reached the UI was an English sentence from an exception, which a
   *  Persian page then had to print verbatim or interpret. */
  readonly fault: Fault | null;
  readonly envelope: Envelope | null;
  constructor(status: number, message: string, envelope: Envelope | null = null) {
    super(message);
    this.status = status;
    this.envelope = envelope;
    this.fault = envelope?.fault ?? null;
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
    // A refusal about the corpus is a 200 by design (D11). A 404 here means
    // something specific and true: a corpus WAS read and does not hold the
    // resource that was asked for — and it carries the same envelope as any
    // other response, so the fault travels with it.
    //
    // `detail` is the fallback for a non-envelope error, which now means
    // something outside this API answered — a proxy, a gateway, a 500 from a
    // path that never reached an endpoint. Those have no fault and the status
    // is all there is.
    let detail = `${res.status}`;
    let envelope: Envelope | null = null;
    try {
      const body = await res.json();
      if (body && typeof body === 'object' && 'status' in body
          && 'corpus' in body) {
        envelope = body as Envelope;
        detail = envelope.fault?.message ?? detail;
      } else if (body?.detail) {
        detail = String(body.detail);
      }
    } catch { /* body was not JSON; the status stands on its own */ }
    throw new ApiError(res.status, detail, envelope);
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

  models: () => json<ModelsResponse>('/api/models'),

  model: (make: string, model: string) =>
    json<ModelResponse>(
      `/api/model?make=${encodeURIComponent(make)}&model=${encodeURIComponent(model)}`),

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
