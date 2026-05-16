# Test Quality Audit Summary

**Generated**: 2026-05-16T04:45:48Z
**Doctrine**: docs/governance/test-suite-doctrine.md

## Statistics

| Metric | Value |
|---|---|
| Total test files | 327 |
| Total findings | 239 |
| conftest.py exists | True |
| __pycache__/conftest*.pyc | 1 |

## Findings by Severity

- **critical**: 0
- **high**: 11
- **medium**: 20
- **low**: 64
- **info**: 144

## Findings by Rule

- **DETERM_HARDCODED_PATH**: 11
- **DETERM_SLEEP**: 7
- **DUPLICATE_KNOWN_PAIR**: 2
- **DUPLICATE_SAME_MODULE**: 144
- **DUPLICATE_SAME_NAME_CROSS_DIR**: 55
- **LAYOUT_MIS_SCOPED_SCRIPTS**: 3
- **LAYOUT_ROOT_LEVEL**: 15
- **NAMING_VAGUE**: 2

## Marker Coverage

| Marker | Count |
|---|---|
| contract | 3 |
| integration | 7 |
| slow | 8 |
| smoke | 11 |

## Commands

```bash
# Smoke suite (fastest confidence)
uv run pytest -m smoke

# Default developer suite (no slow/legacy/flaky/network/provider/destructive)
uv run pytest -m "not slow and not legacy and not flaky and not network and not provider and not destructive"

# Full suite
uv run pytest

# Test quality audit
uv run python scripts/rig_relay_test_quality_audit.py
```

