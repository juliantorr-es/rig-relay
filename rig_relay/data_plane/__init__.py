"""Rig Relay Operational Data Plane — PostgreSQL substrate.

Canonical evidence (JSON/JSONL/CSV ledgers and receipts) remains authority.
PostgreSQL stores durable operational projections, ingestion checkpoints,
indexed read models, and evidence references/digests.

DuckDB remains the disposable read-side analytics engine.
"""

from __future__ import annotations

__all__ = []
