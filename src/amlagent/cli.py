"""amlagent CLI.

    amlagent alerts                          run the monitoring rules on the synthetic bank
    amlagent case C1002                      investigate one customer's case (rules investigator)
    amlagent case C1006 --investigator bad   see the verifier and safety floor stop a bad model
    amlagent case C1003 --investigator anthropic   Claude as the investigator (needs ANTHROPIC_API_KEY)
"""
from __future__ import annotations

import argparse
import sys

from .audit import AuditLog
from .casefile import build_cases
from .data import load_bank, load_sdn
from .investigators import LLMInvestigator, RulesInvestigator, ScriptedBadModel
from .pipeline import run_case
from .rules import run_rules


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="amlagent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("alerts")
    c = sub.add_parser("case")
    c.add_argument("customer")
    c.add_argument("--investigator", default="rules", help="rules | bad | anthropic | openai")
    a = ap.parse_args(argv)
    bank, sdn, audit = load_bank(), load_sdn(), AuditLog()
    alerts = run_rules(bank, sdn)
    if a.cmd == "alerts":
        for al in alerts:
            print(f"{al['id']}  {al['rule']:18s} {bank.customers[al['customer_id']]['name']:32s} {al['window'][0]}..{al['window'][1]}  {al['detail']}")
        return 0
    cases = {cs["customer_id"]: cs for cs in build_cases(bank, alerts, sdn, audit)}
    if a.customer not in cases:
        print(f"No alerts for {a.customer}. Customers with cases: {', '.join(cases)}")
        return 2
    case = cases[a.customer]
    inv = {"rules": RulesInvestigator, "bad": ScriptedBadModel}.get(a.investigator)
    if inv:
        inv = inv()
    else:
        from .providers import get_provider
        inv = LLMInvestigator(get_provider(a.investigator))
    v = run_case(case, inv, bank, audit)
    print(f"{case['case_id']}  {case['subject']}  ({len(case['alerts'])} alerts)\n\nEVIDENCE (gathered and computed by code)")
    for f in case["facts"]:
        print(f"  {f['id']:>3} [{f['kind']}] {f['text']}")
    print(f"\nRECOMMENDATION: {v['recommendation'].upper()}" + (f"   (model said: {v['model_recommendation']})" if v["model_recommendation"] != v["recommendation"] else ""))
    for o in v["overrides"]:
        print(f"  safety floor: {o}")
    for r in v["removed"]:
        print(f"  removed: \"{r['text']}\"\n           because it {r['reason']}")
    print("\nMODEL'S RATIONALE (overruled; shown so the reviewer sees what it claimed)" if v["overrides"] else "\nRATIONALE")
    for s in v["rationale"]:
        print(f"  - {s['text']}  {s['facts']}")
    if v["sar"]:
        print("\nDRAFT SAR NARRATIVE (for the investigator to edit and approve)" + ("  [facts-only draft]" if v.get("facts_only_draft") else ""))
        for s in v["sar"]:
            print(f"  {s['text']}  {s['facts']}")
        if v["sar_missing"]:
            print(f"  missing: {', '.join(v['sar_missing'])}")
    print(f"\nAudit log: {len(audit.entries)} entries, chain {'intact' if audit.verify() else 'BROKEN'}. Nothing was filed or closed; a person decides.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
