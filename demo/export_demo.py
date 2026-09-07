"""Export the eight demo scenarios as JSON, straight from the orchestrator.

Nothing here is hand-written. Every number, finding and trace line in the
demo page is whatever the real pipeline produced.
"""
import json
from dataclasses import asdict
import tests.test_agents as T   # running it builds all eight scenarios

def dump(label, title, r):
    v = r.verdict
    return {
        "label": label, "title": title,
        "decision": v.decision,
        "status": v.status, "status_before": v.status_before_review,
        "downgrade_reasons": list(v.downgrade_reasons),
        "estimate": {str(k): v.estimate[k] for k in sorted(v.estimate)} if v.estimate else {},
        "confidence": {
            "evidence": v.confidence.evidence_strength,
            "comparable": v.confidence.comparable_strength,
            "temporal": v.confidence.temporal_strength,
            "calibration": v.confidence.model_calibration,
            "data_quality": v.confidence.data_quality,
            "anomaly_risk": v.confidence.anomaly_risk,
            "score": v.confidence.score,
            "notes": list(v.confidence.notes),
        },
        "findings": [{"code": f.code, "severity": f.severity, "text": f.text_fa,
                      "action": f.recommended_action, "hard": f.hard,
                      "evidence_ids": list(f.evidence_ids)} for f in v.findings],
        "trace": [{"agent": e.agent, "summary": e.summary} for e in r.trace],
        "explanation": r.explanation_fa,
        "claims": [{"text": c.text_fa, "kind": c.kind,
                    "evidence": [ {"id": i.evidence_id, "summary": i.summary,
                                   "kind": i.kind,
                                   "on": i.observed_on.isoformat() if i.observed_on else None}
                                 for i in r.ledger.trace(c.claim_id)]}
                   for c in r.ledger.claims],
        "unsupported": len(r.unsupported_claims),
    }

cases = [
    dump("A", "شواهد قوی — برآورد تأییدشده", T.ra),
    dump("B", "آگهی مشابه کم — اطمینان پایین", T.rb),
    dump("C", "تجدید آگهی و کاهش قیمت", T.rc),
    dump("D", "شکاف نامعلوم — غیبت فرض نمی‌شود", T.rd),
    dump("E", "بازبینی انتقادی: وتوی سخت", T.re_),
    dump("F", "برآوردگر پذیرفته نشده — سرو نمی‌شود", T.rf),
    dump("H", "بدون تاریخچه‌ی رصد", T.rh),
]
out = {"cases": cases, "policy": T.DEFAULT_POLICY.explain(),
       "benchmark": {k: {"pinball": v.mean_pinball,
                         "crossing": v.crossing_rate_before_rearrange,
                         "cov_err": v.overall.max_abs_coverage_error}
                     for k, v in T.BASE.items()}}
open("demo_data.json", "w").write(json.dumps(out, ensure_ascii=False, indent=1))
print(f"exported {len(cases)} cases, {len(json.dumps(out))} bytes")
