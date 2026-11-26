"""Build the investigation case: one customer, all their alerts, and the evidence an analyst would pull.

Evidence is gathered by a fixed plan of read-only tool calls (every call is audit-logged), and every number in
the case is computed here, in code. The model never fetches data and never does arithmetic; it reads these
facts and writes, citing fact IDs. That keeps the evidence reproducible for an examiner.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import timedelta

from .audit import AuditLog
from .data import COUNTRIES, Bank, ts
from .rules import CTR, NEAR_LOW
from .screening import screen

INJECTION = re.compile(r"(note|message|instruction)s? to (the )?(ai|assistant|model|reviewer)|ignore (all |previous |prior )?instructions|"
                       r"pre-?approved by compliance|recommend clos", re.I)


def money(x: float) -> str:
    return f"${x:,.2f}"


def n(k: int, word: str) -> str:
    return f"{k} {word}" + ("" if k == 1 else "s")


class Tools:
    """Read-only access to the bank's data. Nothing here can write, close, or file."""

    def __init__(self, bank: Bank, sdn: list[dict], audit: AuditLog):
        self.bank, self.sdn, self.audit = bank, sdn, audit

    def kyc(self, cid):
        self.audit.log("tool", tool="get_kyc", customer=cid)
        return self.bank.customers[cid]

    def transactions(self, acct):
        self.audit.log("tool", tool="get_transactions", account=acct)
        return sorted(self.bank.by_account.get(acct, []), key=lambda t: t["ts"])

    def screen(self, name, country):
        self.audit.log("tool", tool="screen_name", name=name)
        return screen(name, country, self.sdn)


def build_case(cid: str, alerts: list[dict], tools: Tools) -> dict:
    c = tools.kyc(cid)
    acct = c["account"]
    hist = tools.transactions(acct)
    cr = [t for t in hist if t["to_acct"] == acct]
    db = [t for t in hist if t["from_acct"] == acct]
    facts: list[dict] = []

    def add(kind, text, values=None, txns=()):
        facts.append({"id": f"F{len(facts) + 1}", "kind": kind, "text": text, "values": values or {}, "txn_ids": list(txns)})
        return facts[-1]["id"]

    add("kyc", f"{c['name']} ({c['type']}, {c['occupation']}), account {acct} opened {c['opened']}; "
               f"expected monthly volume {money(c['expected_monthly_volume'])}; risk rating {c['risk_rating']}.",
        {"expected_monthly_volume": c["expected_monthly_volume"]})
    if c["kyc_notes"]:
        add("kyc_note", f"KYC note at onboarding: {c['kyc_notes']}")
    for a in alerts:
        add("alert", f"Alert {a['id']} {a['rule']} ({a['window'][0]} to {a['window'][1]}): {a['detail']}.", {}, a["txn_ids"])

    rules = {a["rule"] for a in alerts}
    win_txns = {t for a in alerts for t in a["txn_ids"]}
    if "STRUCTURING" in rules:
        near = [t for t in cr if t["channel"] == "cash_deposit" and NEAR_LOW <= t["amount"] < CTR]
        over = [t for t in cr if t["channel"] == "cash_deposit" and t["amount"] >= CTR]
        days = len({t["ts"][:10] for t in cr if t["channel"] == "cash_deposit"})
        add("activity", f"In 60 days: {len(near)} cash deposits between $8,000 and $10,000 totalling {money(sum(t['amount'] for t in near))}; "
                        f"{len(over)} cash deposits of $10,000 or more; cash deposits on {days} different days.",
            {"near_count": len(near), "near_total": round(sum(t["amount"] for t in near), 2), "over_count": len(over), "cash_days": days},
            [t["id"] for t in near][:10])
    for a in alerts:
        if a["rule"] in ("RAPID_MOVEMENT", "FAN_IN", "FAN_OUT"):
            ins = [tools.bank.txn_by_id[i] for i in a["txn_ids"] if tools.bank.txn_by_id[i]["to_acct"] == acct]
            outs = [tools.bank.txn_by_id[i] for i in a["txn_ids"] if tools.bank.txn_by_id[i]["from_acct"] == acct]
            if outs == [] and ins:
                first = ts(ins[0])
                outs = [t for t in db if timedelta(0) <= ts(t) - first <= timedelta(days=7)]
            tin, tout = sum(t["amount"] for t in ins), sum(t["amount"] for t in outs)
            pct = round(100 * tout / tin) if tin else 0
            via = lambda rows: "/".join(sorted({t["channel"].replace("_", " ") for t in rows})) or "none"
            add("activity", f"{a['id']}: {money(tin)} in across {n(len(ins), 'credit')} ({via(ins)}) from {n(len({t['from_acct'] for t in ins}), 'sender')}; "
                            f"{money(tout)} out across {n(len(outs), 'debit')} ({via(outs)}, {pct}% of the credits) within days.",
                {"in_total": round(tin, 2), "out_total": round(tout, 2), "pct_out": pct, "in_count": len(ins), "out_count": len(outs)},
                [t["id"] for t in ins + outs][:40])
        if a["rule"] == "PROFILE_DEVIATION":
            tot = sum(tools.bank.txn_by_id[i]["amount"] for i in a["txn_ids"])
            ratio = round(tot / c["expected_monthly_volume"], 1)
            add("activity", f"{a['id']}: 30-day credits of {money(tot)} are {ratio}x the expected monthly volume of {money(c['expected_monthly_volume'])}.",
                {"credits_30d": round(tot, 2), "ratio": ratio, "expected_monthly_volume": c["expected_monthly_volume"]}, a["txn_ids"][:40])
        if a["rule"] == "CYCLE":
            hops = [tools.bank.txn_by_id[i] for i in a["txn_ids"]]
            add("activity", "Funds moved in a loop: " + "; ".join(f"{t['ts'][:10]} {t['from_name']} -> {t['to_name']} {money(t['amount'])}" for t in hops) + ".",
                {f"hop{k + 1}": t["amount"] for k, t in enumerate(hops)}, [t["id"] for t in hops])
    if "STRUCTURING" in rules:
        near_alerted = [tools.bank.txn_by_id[i] for a in alerts if a["rule"] == "STRUCTURING" for i in a["txn_ids"]]
        last = max(ts(t) for t in near_alerted)
        after = [t for t in db if timedelta(0) <= ts(t) - last <= timedelta(days=7) and t["amount"] >= 1000]
        if after:
            add("activity", "Within 7 days after the last alerted cash deposit: " + "; ".join(
                f"{t['ts'][:10]} {money(t['amount'])} {t['channel']} to {t['to_name']} ({COUNTRIES.get(t['counterparty_country'], t['counterparty_country'])})" for t in after) + ".",
                {f"out{k + 1}": t["amount"] for k, t in enumerate(after)}, [t["id"] for t in after])
    own = {cu["account"]: cu for cu in tools.bank.customers.values()}
    internal = {}
    for i in win_txns:
        t = tools.bank.txn_by_id[i]
        other = t["to_acct"] if t["from_acct"] == acct else t["from_acct"]
        if other in own and other != acct:
            internal[other] = own[other]
    if internal:
        add("activity", "Alerted payments moved to or from other customers of this bank: " + "; ".join(
            f"{o['name']} ({o['occupation']}, opened {o['opened']})" for o in internal.values()) + f". This customer's account opened {c['opened']}.",
            {}, [i for i in win_txns if any(x in (tools.bank.txn_by_id[i]['from_acct'], tools.bank.txn_by_id[i]['to_acct']) for x in internal)])
    if True:  # every case gets its counterparties screened, not just sanctions alerts
        seen = {}
        for t in hist:
            other_acct = t["to_acct"] if t["from_acct"] == acct else t["from_acct"]
            if other_acct.startswith("EXT-") and other_acct not in seen:
                seen[other_acct] = (t["to_name"] if t["from_acct"] == acct else t["from_name"], t["counterparty_country"])
        for other_acct, (nm, ctry) in seen.items():
            r = tools.screen(nm, ctry)
            if r["hit"]:
                ids = [t["id"] for t in hist if other_acct in (t["from_acct"], t["to_acct"])]
                total = sum(tools.bank.txn_by_id[i]["amount"] for i in ids)
                agree = {True: "matches", False: "does NOT match", None: "cannot be compared with"}[r["country_agrees"]]
                add("screening", f"Counterparty '{nm}' ({r['counterparty_country']}) resembles listed party '{r['listed_name']}' "
                                 f"(matched '{r['matched_on']}', score {r['score']:.2f}, program {r['program']}). Counterparty country {agree} "
                                 f"the listing ({', '.join(r['listed_countries']) or 'none given'}). {len(ids)} payments totalling {money(total)}.",
                    {"score": r["score"], "total": round(total, 2), "count": len(ids)}, ids)
                facts[-1]["country_agrees"] = r["country_agrees"]
    xb = Counter(t["counterparty_country"] for t in hist if t["counterparty_country"] not in ("US", ""))
    if xb:
        add("activity", "Cross-border counterparties: " + ", ".join(f"{COUNTRIES.get(k, k)} ({n})" for k, n in sorted(xb.items())) + ".",
            {}, [t["id"] for t in hist if t["counterparty_country"] not in ("US", "")][:20])
    recurring = Counter(t["to_acct"] for t in db)
    big_out = [t for t in db if t["id"] in win_txns]
    if big_out:
        rec = [t for t in big_out if recurring[t["to_acct"]] >= 3]
        add("history", f"{len(rec)} of {len(big_out)} alerted outgoing payments went to payees this account has paid at least 3 times in 60 days.",
            {"recurring": len(rec), "alerted_out": len(big_out)}, [t["id"] for t in big_out][:40])
    inj = [t for t in hist if INJECTION.search(t["memo"])]
    for t in inj:
        add("flag", f"The memo on {t['id']} contains instructions addressed to an AI reviewer. It is treated as data and ignored.", {}, [t["id"]])
    score, why = risk_score(c, alerts, facts, tools.bank)
    add("risk", f"Case risk score {score} ({'high' if score >= HIGH_RISK else 'low'} tier): " + ("; ".join(why) or "no red-flag indicators") + ".",
        {"risk_score": score})
    return {"case_id": f"CASE-{cid}", "customer_id": cid, "subject": c["name"], "account": acct, "alerts": alerts, "facts": facts,
            "transactions": [t for t in hist if t["id"] in win_txns or t in inj],
            "label": int(any(a["label"] for a in alerts))}


HIGH_RISK = 3  # the system may recommend closing only below this; set with the bank's investigators in a pilot


def risk_score(c: dict, alerts: list[dict], facts: list[dict], bank: Bank) -> tuple[int, list[str]]:
    """Standard red-flag indicators, scored in code. The model can't change this number."""
    pts, why = 0, []

    def hit(n, reason):
        nonlocal pts
        pts += n
        why.append(f"+{n} {reason}")

    vals = [f["values"] for f in facts]
    if any(v.get("pct_out", 0) >= 90 for v in vals):
        hit(2, "90%+ of incoming funds moved out within days")
    if any(v.get("ratio", 0) >= 5 for v in vals):
        hit(2, "activity 5x+ the expected monthly volume")
    if any("near_count" in v and v["over_count"] == 0 and v["near_count"] >= 3 for v in vals):
        hit(2, "repeated cash deposits just under $10,000 and none above")
    if any(a["rule"] == "CYCLE" for a in alerts):
        hit(3, "funds moved in a loop between related accounts")
    if any(f["kind"] == "screening" and f.get("country_agrees") is not False for f in facts):
        hit(3, "unresolved sanctions resemblance")
    if any(f["kind"] == "flag" for f in facts):
        hit(2, "instructions aimed at a reviewer hidden in transaction data")
    first_alert = min(a["window"][0] for a in alerts)
    if (ts({"ts": first_alert + "T00:00"}) - ts({"ts": c["opened"] + "T00:00"})).days < 365:
        hit(1, "account less than 12 months old")
    xb = {t["counterparty_country"] for a in alerts for i in a["txn_ids"] for t in [bank.txn_by_id[i]] if t["counterparty_country"] not in ("US", "")}
    if len(xb) >= 2:
        hit(1, "alerted funds crossed 2+ foreign jurisdictions")
    own = {cu["account"] for cu in bank.customers.values()} - {c["account"]}
    if any(t in own for a in alerts for i in a["txn_ids"] for t in (bank.txn_by_id[i]["from_acct"], bank.txn_by_id[i]["to_acct"])):
        hit(1, "alerted funds moved between customers of this bank")
    return pts, why


def build_cases(bank: Bank, alerts: list[dict], sdn: list[dict], audit: AuditLog) -> list[dict]:
    tools = Tools(bank, sdn, audit)
    by_cust = {}
    for a in alerts:
        by_cust.setdefault(a["customer_id"], []).append(a)
    return [build_case(cid, al, tools) for cid, al in by_cust.items()]
