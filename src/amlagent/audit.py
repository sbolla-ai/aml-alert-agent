"""Hash-chained audit log: every tool call, model output, verifier action and recommendation, in order.

Each entry carries the hash of the previous one, so a deleted or edited entry breaks the chain. This is the
record an examiner or internal audit asks for: what the system saw, what it said, and what code changed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

RESERVED = {"seq", "at", "event", "prev", "entry_hash"}


class AuditLog:
    def __init__(self):
        self.entries: list[dict] = []

    def log(self, event: str, **fields) -> dict:
        clash = RESERVED & fields.keys()
        if clash:
            raise ValueError(f"reserved audit field(s): {sorted(clash)}")
        prev = self.entries[-1]["entry_hash"] if self.entries else "0" * 64
        e = {"seq": len(self.entries) + 1, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields, "prev": prev}
        e["entry_hash"] = hashlib.sha256(json.dumps(e, sort_keys=True, default=str).encode()).hexdigest()
        self.entries.append(e)
        return e

    def verify(self) -> bool:
        prev = "0" * 64
        for e in self.entries:
            body = {k: v for k, v in e.items() if k != "entry_hash"}
            if e["prev"] != prev or hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest() != e["entry_hash"]:
                return False
            prev = e["entry_hash"]
        return True
