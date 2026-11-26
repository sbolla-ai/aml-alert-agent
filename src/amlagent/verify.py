"""Verifier and safety floor. Whatever the investigator (rules, Claude, or a bad model) says, this runs after it.

Sentence checks (rationale and SAR draft):
  * every cited fact exists in this case
  * every transaction / account / alert ID mentioned belongs to this case
  * every amount, count, percentage, ratio and date appears in the facts or transactions the sentence cites
  * SAR sentences state facts, not legal conclusions ("is laundering money", "criminal")
Recommendation checks (code decides, not the model):
  * a round-trip (CYCLE) case is never closed by the system
  * a sanctions resemblance is never closed unless the counterparty's country contradicts the listing and the
    rationale cites that screening evidence
  * a close is only allowed for low-risk cases: the risk score is computed in code from red-flag indicators,
    so a well-written, well-cited but wrong closure still goes to a human
  * a close needs at least one surviving sentence citing real evidence (KYC note, history, screening, activity)
  * a rationale that relies on a memo instruction, or on "pre-approved", is rejected
  * the only outputs are "escalate" (to a human investigator) or "close" (recommended; a human QA samples it).
    Nothing is filed and nothing is closed without a person.
"""
from __future__ import annotations

import re
from datetime import datetime

ID_RE = re.compile(r"\b(T\d{5}|W\d{7}|ACC-\d+|EXT-\d+|A\d{3}|CASE-C\d+|F\d+)\b")
DATE_RE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b|\b((?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, 20\d\d)\b")
NUM_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?x?")
LEGAL = re.compile(r"\b(is|was|are|were|has been) (?:\w+ )?launder\w*|\blaunder(?:ed|s|ing) (?:money|funds|proceeds)\b|\bcriminals?\b|"
                   r"\bcommitted\b|\bguilty\b|\bterroris\w+|\bfraudsters?\b|\bmoney mule\b", re.I)
RELIANCE = re.compile(r"pre-?approved|per the (wire )?memo|as instructed|memo (says|states|confirms)|compliance (already )?approved", re.I)
EVIDENCE_KINDS = {"kyc_note", "history", "screening", "activity"}


def _num(tok: str) -> float | None:
    t = tok.replace("$", "").replace(",", "").rstrip("%x")
    try:
        return round(float(t), 2)
    except ValueError:
        return None


def numbers(text: str) -> set[float]:
    text = ID_RE.sub(" ", text)
    text = DATE_RE.sub(" ", text)
    return {n for n in (_num(m.group(0)) for m in NUM_RE.finditer(text)) if n is not None}


def dates(text: str) -> set[str]:
    out = set()
    for iso, long_ in DATE_RE.findall(text):
        out.add(iso or datetime.strptime(long_, "%B %d, %Y").strftime("%Y-%m-%d"))
    return out


class CaseIndex:
    def __init__(self, case: dict, bank):
        self.case, self.bank = case, bank
        self.facts = {f["id"]: f for f in case["facts"]}
        self.txn_ids = {t for f in case["facts"] for t in f["txn_ids"]} | {t["id"] for t in case["transactions"]}
        self.ids = self.txn_ids | {case["account"], case["case_id"]} | {a["id"] for a in case["alerts"]} | set(self.facts)
        for t in self.txn_ids:
            tx = bank.txn_by_id[t]
            self.ids |= {tx["from_acct"], tx["to_acct"]}

    def allowed(self, fact_ids: list[str]) -> tuple[set[float], set[str]]:
        nums, ds = set(), set()
        for fid in fact_ids:
            f = self.facts[fid]
            nums |= numbers(f["text"]) | {round(float(v), 2) for v in f["values"].values() if isinstance(v, (int, float))}
            ds |= dates(f["text"])
            for t in f["txn_ids"]:
                tx = self.bank.txn_by_id[t]
                nums.add(round(tx["amount"], 2))
                ds.add(tx["ts"][:10])
        return nums, ds


def check_sentence(s: dict, idx: CaseIndex, sar: bool) -> str | None:
    text, cited = str(s.get("text", "")), list(s.get("facts", []))
    if not cited:
        return "cites no facts"
    bad = [f for f in cited if f not in idx.facts]
    if bad:
        return f"cites facts that don't exist: {bad}"
    unknown = sorted({m for m in ID_RE.findall(text) if m not in idx.ids})
    if unknown:
        return f"mentions IDs not in this case: {unknown}"
    nums, ds = idx.allowed(cited)
    stray = sorted(n for n in numbers(text) if n not in nums and not (n.is_integer() and n <= 3))
    if stray:
        return f"numbers not in the cited evidence: {stray}"
    stray_d = sorted(dates(text) - ds)
    if stray_d:
        return f"dates not in the cited evidence: {stray_d}"
    if RELIANCE.search(text) or any(idx.facts[f]["kind"] == "flag" for f in cited):
        return "relies on an instruction found in transaction data"
    if sar and LEGAL.search(text):
        return "states a legal conclusion; a SAR describes facts and why they are suspicious"
    return None


SAR_ELEMENTS = {
    "who": lambda t, c: c["subject"].lower() in t.lower(),
    "where": lambda t, c: c["account"] in t,
    "when": lambda t, c: bool(dates(t)),
    "what": lambda t, c: "$" in t,
    "how": lambda t, c: bool(re.search(r"\b(cash|wire|ach|p2p|transfer|deposit|crypto|payment)", t, re.I)),
}


def verify(output: dict, case: dict, bank, audit=None, risk_floor: bool = True) -> dict:
    idx = CaseIndex(case, bank)
    removed, kept = [], {"rationale": [], "sar": []}
    for part, is_sar in (("rationale", False), ("sar", True)):
        for s in output.get(part, []) or []:
            why = check_sentence(s, idx, is_sar)
            if why:
                removed.append({"part": part, "text": s.get("text", ""), "reason": why})
            else:
                kept[part].append(s)
    rec = output.get("recommendation")
    final, overrides = (rec if rec in ("escalate", "close") else "escalate"), []
    if rec not in ("escalate", "close"):
        overrides.append(f"unknown recommendation {rec!r}; sent to a human")
    rules = {a["rule"] for a in case["alerts"]}
    screening = [f for f in case["facts"] if f["kind"] == "screening"]
    if final == "close":
        cited = {f for s in kept["rationale"] for f in s["facts"]}
        risk = next((f["values"]["risk_score"] for f in case["facts"] if f["kind"] == "risk"), 0)
        if risk_floor and risk >= 3:
            overrides.append(f"risk score {risk} is high tier; the system may only recommend closing low-risk cases")
        if "CYCLE" in rules:
            overrides.append("round-trip (CYCLE) cases are never closed by the system")
        unresolved = [f["id"] for f in screening if f.get("country_agrees") is not False]
        if unresolved:
            overrides.append(f"unresolved sanctions resemblance {unresolved}; only a human can clear it")
        elif screening and not any(f["id"] in cited for f in screening):
            overrides.append("closing a sanctions alert must cite the screening evidence that clears it")
        if not any(idx.facts[f]["kind"] in EVIDENCE_KINDS for f in cited):
            overrides.append("no verified benign explanation survived verification")
        if any(r["reason"].startswith("relies on an instruction") for r in removed):
            overrides.append("the model relied on an instruction embedded in transaction data")
        if overrides:
            final = "escalate"
    missing = []
    if final == "escalate":
        sar_text = " ".join(s["text"] for s in kept["sar"])
        missing = [k for k, test in SAR_ELEMENTS.items() if not test(sar_text, case)]
        if not any(idx.facts[f]["kind"] in ("alert", "activity", "screening") for s in kept["sar"] for f in s["facts"]):
            missing.append("why")
    result = {"case_id": case["case_id"], "model_recommendation": rec, "recommendation": final, "overrides": overrides,
              "removed": removed, "rationale": kept["rationale"], "sar": kept["sar"] if final == "escalate" else [],
              "sar_missing": missing, "typology": output.get("typology", "")}
    if audit is not None:
        audit.log("decision", case=case["case_id"], model_recommendation=rec, final=final, overrides=overrides, removed=len(removed))
    return result
