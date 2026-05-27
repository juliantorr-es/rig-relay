-- Migration 002: Atomic ingestion and concurrent idempotency closure
-- 
-- No structural schema changes required. The evidence_sources.evidence_id
-- PRIMARY KEY already provides the UNIQUE constraint arbiter for atomic
-- INSERT ... ON CONFLICT handling in the application code.
--
-- This migration records the version bump so that T2->T2.1 upgrade
-- provenance is tracked. The atomicity repair is in _store.py.

BEGIN;

SET search_path TO {schema_name};

UPDATE _schema_version
SET current_version = 2,
    last_migration_id = '002_atomic_ingestion',
    last_applied_at = now(),
    schema_hash = '{sql_hash}'
WHERE schema_name = '{schema_name}';

COMMIT;
