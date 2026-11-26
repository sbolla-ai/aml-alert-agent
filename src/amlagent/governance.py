"""Generate the governance pack a bank's model risk / compliance reviewers ask for before go-live.

It is regenerated from the eval results on every CI run, so the documentation can't drift from the system.
"""
from __future__ import annotations

import subprocess
from datetime import date


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip() or "uncommitted"
    except Exception:
        return "uncommitted"


def pack(results: dict) -> str:
    inv_rows = "\n".join(
        f"| {r['investigator']} | {r['laundering_escalated']}/{r['laundering_cases']} | {r['laundering_closed']} | "
        f"{r['benign_closed']}/{r['benign_cases']} | {r['sentences_removed']} | {r['overrides']} | {r['unverified_in_output']} | "
        f"{r['sar_complete']}/{r['escalated']} |" for r in results["investigators"])
    s = results["screening"]
    bad = next((r for r in results["investigators"] if r.get("planted")), None)
    planted = "\n".join(f"| {p['case']} | {p['kind']} | {'caught' if p['caught'] else '**missed**'} | {p['how']} |" for p in (bad or {}).get("planted", []))
    gates = "\n".join(f"| {k} | {'PASS' if v else '**FAIL**'} |" for k, v in results["gates"].items())
    return f"""# Governance pack: AML Alert Investigation Agent

_Generated {date.today().isoformat()} from commit `{_sha()}` by `evals/run_evals.py`. Do not edit by hand._

## 1. Intended use
Assist level-1 AML analysts with alerts from the transaction-monitoring system. For each case the system gathers
evidence with read-only tools, recommends **escalate** (with a draft SAR narrative) or **close** (with a rationale),
and records everything in a hash-chained audit log.

**Out of scope:** filing SARs, closing cases without a person, customer contact, account actions, detection-model tuning.
Every escalation is decided by a human investigator; recommended closures are sampled by QA.

## 2. Regulatory context
US banking agencies replaced SR 11-7 with revised model risk guidance (SR 26-2 / OCC Bulletin 2026-13) on
April 17, 2026. Generative and agentic AI are outside its scope, so this pack follows the institution's own risk
management practices: documented intended use, testing before use, known limits, monitoring, and change control.
SAR drafts follow FinCEN's guidance that the narrative is the most important part of a SAR and should present facts clearly, chronologically and objectively.

## 3. How the system is built (what is a model, what is code)
| Component | Type | Can it change an outcome? |
|---|---|---|
| Monitoring rules (structuring, rapid movement, fan-in/out, round-trip, sanctions, profile) | Code | Creates alerts |
| Evidence gathering (KYC, transactions, screening, counterparties) | Code, read-only tools, audited | No |
| All numbers in a case (totals, ratios, counts) | Code | No |
| Rationale and SAR wording | Model (or rules baseline) | Only through the verifier |
| Verifier and safety floor | Code | Removes unsupported sentences, overrides unsafe closures |
| Final decision | **Human** | Yes |

## 4. Controls and the tests that prove them
| Control | Enforced by | Evidence |
|---|---|---|
| No laundering case closed by the system | Safety floor + gate | `laundering_closed = 0` for every investigator |
| Every number, date and ID traceable to evidence | Verifier | `unverified_in_output = 0` |
| Instructions hidden in transaction data are ignored | Verifier + injection flag | Planted memo injection caught |
| Round-trips and unresolved sanctions resemblances never closed | Safety floor | Planted closures overridden |
| Only low-risk cases can be recommended for closure (risk score computed in code) | Safety floor | Plausible-but-wrong closure overridden; ablation shows it is missed without this |
| SAR drafts state facts, not legal conclusions | Verifier | Planted legal conclusion removed |
| Tamper-evident record | Hash-chained audit log | Chain verifies |

## 5. Test results
Cases built from {results['alerts']} alerts on a synthetic bank ({results['cases']} cases: {results['laundering_cases']} laundering, {results['benign_cases']} benign look-alikes).

| Investigator | Laundering escalated | Laundering closed | Benign closed | Sentences removed | Overrides | Unverified in output | SAR drafts complete |
|---|---|---|---|---|---|---|---|
{inv_rows}

**Planted model mistakes (scripted bad model)**

| Case | Mistake | Result | How |
|---|---|---|---|
{planted}

**Why the risk-tier floor exists:** with it disabled, the scripted bad model closes {results['ablation_no_risk_floor']['laundering_closed']} laundering case(s)
({', '.join(results['ablation_no_risk_floor']['missed']) or 'none'}). Every sentence in that closure was true and cited, so the verifier
alone could not stop it. Supported is not the same as right.

**Sanctions name screening** ({s['variants']} spelling variants, {s['decoys']} decoys; threshold {s['threshold']}):
fuzzy screening caught {s['fuzzy_recall']}/{s['variants']} variants; literal matching caught {s['literal_recall']}/{s['variants']}.
{s['decoy_hits']}/{s['decoys']} decoys were still flagged for a human; {s['decoy_hits_country_mismatch']} of those carried a country
mismatch the reviewer can use to clear them. Nothing is cleared automatically.

## 6. Gates (CI fails if any fails)
| Gate | Result |
|---|---|
{gates}

## 7. Known limits
- Synthetic transactions and a fictional sanctions list; results show the controls work, not production accuracy.
- The rules baseline was written alongside these cases; it is an upper bound here, not a benchmark.
- Name screening uses names and country only; no dates of birth, identifiers or addresses.
- Evidence gathering follows a fixed plan; the model cannot request other data.

## 8. Monitoring after go-live
| Metric | Threshold | Action |
|---|---|---|
| Laundering found in QA sample of recommended closures | 0 tolerated | Stop closures; root-cause; re-run gates |
| Verifier removal rate | above the validated baseline + 2 points | Review prompts/model drift |
| Safety-floor override rate | sustained rise | Review model and rule changes |
| SAR drafts missing an element | above 5% of escalations | Review prompt and evidence plan |
| Screening alert volume | ±30% week over week | Check list updates and thresholds |

## 9. Change control
Any change to rules, prompts, model version, thresholds or the evidence plan re-runs `evals/run_evals.py`; the
change ships only if every gate passes, and this pack is regenerated with it.

Sign-off: Model owner ____ · Independent validation ____ · BSA/AML Officer ____
"""
