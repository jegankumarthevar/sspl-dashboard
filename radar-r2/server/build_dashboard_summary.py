#!/usr/bin/env python3
"""Build the small public dashboard view of the append-only Radar ledger.

The full ledger remains the source of truth. This file is a derived read model for
mobile browsers: it keeps every paper-trading record and a light token index, but
omits bulky historical research/decision/score blobs that make the full JSON slow
to parse on phones.
"""
import gzip
import json
import sys
from pathlib import Path

KEEP_ENGINE_STATE_SCALARS = (
    "schema", "build", "settings", "running", "watchlist", "portfolio", "sources",
    "lastScan", "page", "policyVersion", "scoreVersion", "strategyVersion",
    "snapshots", "outcomes", "clusterEvidence", "filters", "latestSlot",
    "evidenceBudget", "strictEvidenceStatus", "discoveryCoverage",
)


def load_json(path: Path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(path.read_text(encoding="utf-8"))


def compact_field(field):
    if not isinstance(field, dict):
        return {"value": field}
    return {
        key: field.get(key)
        for key in ("value", "observedAt", "source", "dataState")
        if field.get(key) is not None
    }


def compact_token(token):
    fields = token.get("fields", {}) if isinstance(token, dict) else {}
    return {
        "url": token.get("url") if isinstance(token, dict) else None,
        "fields": {
            "symbol": compact_field(fields.get("symbol")),
            "name": compact_field(fields.get("name")),
        },
    }


def build(full):
    engine_state = full.get("engineState", {})
    tokens = engine_state.get("tokens", {})
    compact_tokens = {mint: compact_token(token) for mint, token in tokens.items()}

    summary_state = {
        key: engine_state.get(key)
        for key in KEEP_ENGINE_STATE_SCALARS
        if key in engine_state
    }
    summary_state.update({
        "tokens": compact_tokens,
        "wallets": {},
        "clusters": [],
        "signals": [],
        "decisions": [],
        "scores": [],
        "logs": (engine_state.get("logs") or [])[-100:],
        "autoPaper": engine_state.get("autoPaper"),
        "discoveryPaperArchives": engine_state.get("discoveryPaperArchives") or [],
        "discoveryPaper": engine_state.get("discoveryPaper"),
    })

    return {
        "schema": full.get("schema"),
        "engine": full.get("engine"),
        "engineState": summary_state,
        "events": full.get("events") or [],
        "testEvents": full.get("testEvents") or [],
        "processedRuns": full.get("processedRuns") or [],
        "lastRun": full.get("lastRun"),
        "relay": full.get("relay"),
        "summary": full.get("summary"),
        "recovery": full.get("recovery"),
        "legacySummary": full.get("legacySummary"),
        "dashboardSummary": {
            "version": 1,
            "source": "radar-r2/server-ledger.json.gz",
            "tokensIndexed": len(compact_tokens),
            "note": "Derived mobile read model; full append-only ledger remains server-ledger.json.gz.",
        },
    }


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_dashboard_summary.py <server-ledger.json[.gz]> <output.json>")
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    full = load_json(source)
    summary = build(full)
    required = (
        summary.get("schema") in (1, 2),
        isinstance(summary.get("engine"), str),
        isinstance(summary["engineState"].get("autoPaper"), dict),
        isinstance(summary["engineState"].get("discoveryPaper"), dict),
        isinstance(summary["engineState"].get("tokens"), dict),
        isinstance(summary.get("events"), list),
        isinstance(summary.get("summary"), dict),
        isinstance(summary.get("lastRun"), dict),
    )
    if not all(required):
        raise SystemExit("dashboard summary validation failed")
    target.write_text(json.dumps(summary, separators=(",", ":")), encoding="utf-8")
    print(f"dashboard summary: {target} {target.stat().st_size} bytes, {len(summary['engineState']['tokens'])} token indexes")


if __name__ == "__main__":
    main()
