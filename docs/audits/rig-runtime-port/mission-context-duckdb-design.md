# Mission Context DuckDB Design

This design keeps DuckDB in the role of a rebuildable analytical index, not a canonical governance store.

## What DuckDB Is For

- Indexing canonical docs, schemas, audits, receipts, and optional work ledger files.
- Running deterministic queries to locate relevant packet sources.
- Producing typed packet components from explicit allow-listed roots.

## What DuckDB Is Not For

- It is not the source of truth.
- It is not a shared mutable ledger.
- It is not a daemon.
- It is not the packet format.

## Rebuildability Rule

If the cache disappears, the compiler must be able to rebuild it from canonical files.

## Compilation Rule

Packet compilation should:

- read from explicit source paths only,
- remain deterministic,
- preserve ordering where the schema requires it,
- reject raw content fields,
- emit a content-light receipt.

The prototype compiler may operate directly on the filesystem first and add DuckDB later without changing the packet contract.

## Likely Helper Boundary

If a helper is added later, it should:

- open a local cache under `.build/rig/context/`,
- ingest from explicit allow-listed roots,
- return typed packet components,
- avoid ambient filesystem crawling.

## Future Integration

DuckDB can later support packet source discovery, but the executable contract is the packet model and receipt schema first.
