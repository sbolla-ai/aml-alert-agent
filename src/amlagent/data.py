"""Loaders: the synthetic bank, OFAC's SDN list files, and IBM AMLworld transaction CSVs.

The OFAC and AMLworld loaders follow the published formats so real files drop in:
  SDN.CSV  ent_num, SDN_Name, SDN_Type, Program, Title, Call_Sign, Vess_type, Tonnage, GRT, Vess_flag, Vess_owner, Remarks
  ALT.CSV  ent_num, alt_num, alt_type, alt_name, alt_remarks
  ADD.CSV  ent_num, add_num, address, city/state/postal, country, add_remarks         ("-0-" means empty)
  AMLworld Timestamp, From Bank, Account, To Bank, Account, Amount Received, Receiving Currency, Amount Paid,
           Payment Currency, Payment Format, Is Laundering
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COUNTRIES = {"US": "United States", "MT": "Malta", "CA": "Canada", "AE": "United Arab Emirates", "CY": "Cyprus",
             "VG": "British Virgin Islands", "PA": "Panama", "HK": "Hong Kong", "RS": "Serbia", "RU": "Russia", "GB": "United Kingdom", "CZ": "Czechia"}


@dataclass
class Bank:
    customers: dict
    transactions: list
    by_account: dict = field(default_factory=dict)
    txn_by_id: dict = field(default_factory=dict)

    def __post_init__(self):
        self.txn_by_id = {t["id"]: t for t in self.transactions}
        for t in self.transactions:
            self.by_account.setdefault(t["from_acct"], []).append(t)
            self.by_account.setdefault(t["to_acct"], []).append(t)

    def customer_for(self, account: str) -> dict | None:
        return next((c for c in self.customers.values() if c["account"] == account), None)


def load_bank(path: str | Path | None = None) -> Bank:
    d = json.loads(Path(path or ROOT / "data" / "bank.json").read_text())
    return Bank({c["id"]: c for c in d["customers"]}, d["transactions"])


def ts(t: dict) -> datetime:
    return datetime.fromisoformat(t["ts"])


def _rows(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rows = [r for r in csv.reader(f) if r and any(x.strip() for x in r)]
    if rows and not rows[0][0].strip().isdigit():  # tolerate a header row if one is present
        rows = rows[1:]
    return [[("" if x.strip() == "-0-" else x.strip()) for x in r] for r in rows]


def load_sdn(directory: str | Path | None = None) -> list[dict]:
    """One entry per listed party: primary name, aliases, type, programs, countries."""
    d = Path(directory or ROOT / "data" / "sanctions")
    entries = {}
    for r in _rows(d / "SDN.CSV"):
        entries[r[0]] = {"ent_num": r[0], "name": r[1], "type": r[2] or "entity", "program": r[3], "aliases": [], "countries": set()}
    for r in _rows(d / "ALT.CSV"):
        if r[0] in entries and len(r) > 3 and r[3]:
            entries[r[0]]["aliases"].append(r[3])
    for r in _rows(d / "ADD.CSV"):
        if r[0] in entries and len(r) > 4 and r[4]:
            entries[r[0]]["countries"].add(r[4])
    return list(entries.values())


def load_amlworld(path: str | Path, limit: int | None = None) -> list[dict]:
    """IBM AMLworld (Altman et al., NeurIPS 2023; CDLA-Sharing-1.0) rows into this project's transaction shape.
    Accounts become "<bank>:<account>" to avoid cross-bank collisions. Amounts are taken as paid by the sender."""
    out = []
    with open(path, newline="") as f:
        rd = csv.reader(f)
        next(rd)  # header has "Account" twice, so read by position
        for i, r in enumerate(rd):
            if limit and i >= limit:
                break
            stamp = datetime.strptime(r[0], "%Y/%m/%d %H:%M")
            channel = {"Cash": "cash_deposit", "Wire": "wire", "ACH": "ach", "Cheque": "check", "Credit Card": "card",
                       "Bitcoin": "crypto_exchange", "Reinvestment": "internal"}.get(r[9], r[9].lower())
            out.append({"id": f"W{i + 1:07d}", "ts": stamp.strftime("%Y-%m-%dT%H:%M"), "from_acct": f"{r[1]}:{r[2]}", "from_name": f"{r[1]}:{r[2]}",
                        "to_acct": f"{r[3]}:{r[4]}", "to_name": f"{r[3]}:{r[4]}", "amount": float(r[7]), "currency": r[8],
                        "channel": channel, "counterparty_country": "", "memo": "", "label": int(r[10])})
    return out
