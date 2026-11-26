"""Transaction-monitoring rules: the stand-in for the bank's existing detection system.

Each rule is a common money-laundering pattern ("typology"). Rules are deliberately broad, like real ones:
they catch the planted cases and also legitimate businesses whose normal activity looks the same.
That is the false-positive load the investigation agent exists to reduce.
"""
from __future__ import annotations

from datetime import timedelta

from .data import Bank, ts
from .screening import screen

NEAR_LOW, CTR = 8000.0, 10000.0


def _credits(bank: Bank, acct: str):
    return [t for t in bank.by_account.get(acct, []) if t["to_acct"] == acct]


def _debits(bank: Bank, acct: str):
    return [t for t in bank.by_account.get(acct, []) if t["from_acct"] == acct]


def _alert(rule, acct, cust, txns, detail):
    txns = sorted({t["id"]: t for t in txns}.values(), key=lambda t: t["ts"])
    return {"rule": rule, "account": acct, "customer_id": cust["id"] if cust else None, "txn_ids": [t["id"] for t in txns],
            "window": [txns[0]["ts"][:10], txns[-1]["ts"][:10]], "detail": detail}


def structuring(bank, acct, cust):
    near = [t for t in _credits(bank, acct) if t["channel"] == "cash_deposit" and NEAR_LOW <= t["amount"] < CTR]
    for i, t in enumerate(near):
        win = [u for u in near[i:] if ts(u) - ts(t) <= timedelta(days=7)]
        if len(win) >= 3:
            return [_alert("STRUCTURING", acct, cust, win, f"{len(win)} cash deposits between $8,000 and $10,000 within 7 days")]
    return []


def rapid_movement(bank, acct, cust):
    cr, db = _credits(bank, acct), _debits(bank, acct)
    for t in cr:
        win_in = [u for u in cr if timedelta(0) <= ts(u) - ts(t) <= timedelta(days=3)]
        total_in = sum(u["amount"] for u in win_in)
        if total_in < 25000:
            continue
        out = [u for u in db if timedelta(0) <= ts(u) - ts(t) <= timedelta(days=4)]
        if sum(u["amount"] for u in out) >= 0.8 * total_in:
            return [_alert("RAPID_MOVEMENT", acct, cust, win_in + out, "80%+ of incoming funds moved out within days")]
    return []


def fan(bank, acct, cust, direction):
    rows = _credits(bank, acct) if direction == "in" else _debits(bank, acct)
    key = "from_acct" if direction == "in" else "to_acct"
    limit = 8 if direction == "in" else 10
    if direction == "in" and cust and cust["type"] != "individual":
        return []  # businesses receive from many customers by design
    for t in rows:
        win = [u for u in rows if timedelta(0) <= ts(u) - ts(t) <= timedelta(days=7)]
        if len({u[key] for u in win}) >= limit:
            return [_alert(f"FAN_{direction.upper()}", acct, cust, win, f"{len({u[key] for u in win})} distinct counterparties in 7 days")]
    return []


def cycle(bank, acct, cust):
    """Funds that leave and come back through other accounts at this bank within 10 days (at most 3 hops)."""
    internal = {c["account"] for c in bank.customers.values()}
    for t1 in _debits(bank, acct):
        if internal and t1["to_acct"] not in internal:  # no customer registry (e.g. AMLworld): every account counts
            continue
        for t2 in _debits(bank, t1["to_acct"]):
            if not (timedelta(0) <= ts(t2) - ts(t1) <= timedelta(days=10)) or abs(t2["amount"] - t1["amount"]) > 0.1 * t1["amount"]:
                continue
            for t3 in _debits(bank, t2["to_acct"]):
                if t3["to_acct"] == acct and timedelta(0) <= ts(t3) - ts(t1) <= timedelta(days=10) and abs(t3["amount"] - t1["amount"]) <= 0.1 * t1["amount"]:
                    return [_alert("CYCLE", acct, cust, [t1, t2, t3], "Funds returned to the originating account through two other accounts")]
    return []


def sanctions(bank, acct, cust, sdn):
    out = []
    for t in _debits(bank, acct) + _credits(bank, acct):
        other = t["to_name"] if t["from_acct"] == acct else t["from_name"]
        other_acct = t["to_acct"] if t["from_acct"] == acct else t["from_acct"]
        if not other_acct.startswith("EXT-"):
            continue
        r = screen(other, t["counterparty_country"], sdn)
        if r["hit"]:
            out.append(_alert("SANCTIONS", acct, cust, [u for u in bank.by_account[acct] if other_acct in (u["from_acct"], u["to_acct"])],
                              f"Counterparty '{other}' resembles listed party '{r['listed_name']}' (score {r['score']:.2f})"))
            break
    return out


def profile(bank, acct, cust):
    if not cust:
        return []
    cr = _credits(bank, acct)
    for t in cr:
        win = [u for u in cr if timedelta(0) <= ts(u) - ts(t) <= timedelta(days=30)]
        if sum(u["amount"] for u in win) > 3 * cust["expected_monthly_volume"]:
            return [_alert("PROFILE_DEVIATION", acct, cust, win, "30-day credits above 3x the expected monthly volume")]
    return []


def run_rules(bank: Bank, sdn: list[dict]) -> list[dict]:
    alerts = []
    for cust in bank.customers.values():
        a = cust["account"]
        alerts += structuring(bank, a, cust) + rapid_movement(bank, a, cust) + fan(bank, a, cust, "in") + fan(bank, a, cust, "out")
        alerts += cycle(bank, a, cust) + sanctions(bank, a, cust, sdn) + profile(bank, a, cust)
    for i, al in enumerate(alerts, 1):
        al["id"] = f"A{i:03d}"
        al["label"] = int(any(bank.txn_by_id[t]["label"] for t in al["txn_ids"]))
    return alerts
