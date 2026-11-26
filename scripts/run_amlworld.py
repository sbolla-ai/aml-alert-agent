"""Run the monitoring rules on IBM AMLworld data and measure them against its laundering labels.

AMLworld (Altman et al., NeurIPS 2023 Datasets & Benchmarks; data under CDLA-Sharing-1.0) is not included.
Download a file such as HI-Small_Trans.csv from https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml
  python scripts/run_amlworld.py path/to/HI-Small_Trans.csv --limit 200000

There is no KYC in AMLworld, so only the behavioural rules run (structuring, rapid movement, fan-in/out, cycles).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amlagent.data import Bank, load_amlworld  # noqa: E402
from amlagent.rules import cycle, fan, rapid_movement, structuring  # noqa: E402


def evaluate(txns: list[dict]) -> dict:
    bank = Bank({}, txns)
    alerts = []
    for acct in bank.by_account:
        alerts += structuring(bank, acct, None) + rapid_movement(bank, acct, None) + fan(bank, acct, None, "in") + fan(bank, acct, None, "out") + cycle(bank, acct, None)
    covered = {i for a in alerts for i in a["txn_ids"]}
    laundering = {t["id"] for t in txns if t["label"]}
    positive = [a for a in alerts if any(bank.txn_by_id[i]["label"] for i in a["txn_ids"])]
    by_rule = {}
    for a in alerts:
        r = by_rule.setdefault(a["rule"], [0, 0])
        r[0] += 1
        r[1] += any(bank.txn_by_id[i]["label"] for i in a["txn_ids"])
    return {"transactions": len(txns), "laundering_txns": len(laundering), "alerts": len(alerts),
            "alert_precision": round(len(positive) / len(alerts), 3) if alerts else 0.0,
            "laundering_txn_recall": round(len(laundering & covered) / len(laundering), 3) if laundering else 0.0,
            "by_rule": {k: {"alerts": v[0], "with_laundering": v[1]} for k, v in sorted(by_rule.items())}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--limit", type=int, default=200000)
    a = ap.parse_args()
    r = evaluate(load_amlworld(a.csv, a.limit))
    for k, v in r.items():
        print(f"{k}: {v}")
