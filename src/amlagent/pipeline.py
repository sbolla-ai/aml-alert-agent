"""Run cases end to end: investigate -> verify -> (facts-only draft if needed) -> audit."""
from __future__ import annotations

from .investigators import facts_only_draft
from .verify import verify


def run_case(case: dict, investigator, bank, audit, risk_floor: bool = True) -> dict:
    audit.log("model_input", case=case["case_id"], investigator=investigator.name, facts=len(case["facts"]))
    out = investigator.investigate(case)
    audit.log("model_output", case=case["case_id"], recommendation=out.get("recommendation"),
              sentences=len(out.get("rationale") or []) + len(out.get("sar") or []))
    v = verify(out, case, bank, audit, risk_floor)
    if v["recommendation"] == "escalate" and not v["sar"]:
        v = verify({**out, "recommendation": "escalate", "sar": facts_only_draft(case)}, case, bank, None, risk_floor)
        v.update({"model_recommendation": out.get("recommendation"), "facts_only_draft": True,
                  "overrides": verify(out, case, bank, None, risk_floor)["overrides"]})
        audit.log("facts_only_draft", case=case["case_id"])
    return v
