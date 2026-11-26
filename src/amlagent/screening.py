"""Sanctions screening: fuzzy name matching against primary names and aliases, plus a secondary-identifier check.

Deterministic and explainable: every result says which listed name it matched, the score, and whether the
counterparty's country agrees with the listing. The code never clears a hit; a country mismatch is recorded as
evidence a human can use to clear it.
"""
from __future__ import annotations

import re
import unicodedata

from .data import COUNTRIES

ALERT_THRESHOLD = 0.78  # tuned on data/screening_cases.json; see README
SUFFIXES = {"LLC", "LTD", "LIMITED", "INC", "INCORPORATED", "CO", "CORP", "CORPORATION", "SA", "FZE", "FZCO", "LP",
            "LLP", "PLC", "GMBH", "BV", "AG", "SRL", "PTE", "THE", "AND", "OF"}


def normalize(name: str) -> list[str]:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s.replace("&", " AND "))
    toks = [t for t in s.split() if t not in SUFFIXES]
    return [t[:-1] if len(t) > 4 and t.endswith("S") else t for t in toks]  # HOLDINGS ~ HOLDING


# Words that appear in thousands of company names carry little identifying weight.
GENERIC = {"HOLDING", "TRADING", "GROUP", "VENTURE", "CAPITAL", "INTERNATIONAL", "GLOBAL", "PARTNER", "SERVICE",
           "LOGISTIC", "SHIPPING", "MARITIME", "MARINE", "ENERGY", "GENERAL", "COMPANY", "IMPORT", "EXPORT", "SUPPLY",
           "INDUSTRIE", "INVESTMENT", "MANAGEMENT", "CONSULTING", "SOLUTION", "ENTERPRISE", "FREIGHT", "EXCHANGE", "BANK"}


def jaro_winkler(a: str, b: str) -> float:
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    win = max(la, lb) // 2 - 1
    ma, mb = [False] * la, [False] * lb
    m = 0
    for i, ch in enumerate(a):
        for j in range(max(0, i - win), min(lb, i + win + 1)):
            if not mb[j] and b[j] == ch:
                ma[i] = mb[j] = True
                m += 1
                break
    if not m:
        return 0.0
    t, k = 0, 0
    for i in range(la):
        if ma[i]:
            while not mb[k]:
                k += 1
            t += a[i] != b[k]
            k += 1
    jaro = (m / la + m / lb + (m - t / 2) / m) / 3
    prefix = 0
    for x, y in zip(a[:4], b[:4]):
        if x != y:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


def name_score(a: str, b: str) -> float:
    """Token-level match, order-independent, tolerant of a missing middle name and spelling variants."""
    ta, tb = normalize(a), normalize(b)
    if not ta or not tb:
        return 0.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    w = [0.3 if s in GENERIC else 1.0 for s in short]
    best = sum(wi * max(jaro_winkler(s, l) for l in long_) for s, wi in zip(short, w)) / sum(w)
    coverage = len(short) / len(long_)
    return round(best * (0.85 + 0.15 * coverage), 3)


def screen(name: str, country_code: str, sdn: list[dict]) -> dict:
    best = {"score": 0.0}
    for e in sdn:
        for listed in [e["name"]] + e["aliases"]:
            sc = name_score(name, listed)
            if sc > best["score"]:
                best = {"score": sc, "ent_num": e["ent_num"], "listed_name": e["name"], "matched_on": listed,
                        "alias": listed != e["name"], "program": e["program"], "listed_countries": sorted(e["countries"])}
    country = COUNTRIES.get(country_code, country_code)
    if best["score"] < ALERT_THRESHOLD:
        return {"name": name, "hit": False, "score": best["score"]}
    listed = best["listed_countries"]
    best.update({"name": name, "hit": True, "counterparty_country": country,
                 "country_agrees": (country in listed) if (listed and country) else None})
    return best
