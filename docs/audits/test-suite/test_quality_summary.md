# Test Quality Audit Summary

**Generated**: 2026-05-20T21:43:39Z
**Doctrine**: docs/governance/test-suite-doctrine.md

## Statistics

| Metric | Value |
|---|---|
| Total test files | 701 |
| Total findings | 445 |
| conftest.py exists | True |
| __pycache__/conftest*.pyc | 4 |

## Findings by Severity

- **critical**: 0
- **high**: 45
- **medium**: 20
- **low**: 109
- **info**: 271

## Findings by Rule

- **DETERM_HARDCODED_PATH**: 45
- **DETERM_SLEEP**: 16
- **DUPLICATE_KNOWN_PAIR**: 2
- **DUPLICATE_SAME_MODULE**: 271
- **DUPLICATE_SAME_NAME_CROSS_DIR**: 91
- **LAYOUT_MIS_SCOPED_SCRIPTS**: 3
- **LAYOUT_ROOT_LEVEL**: 15
- **NAMING_VAGUE**: 2

## Marker Coverage

| Marker | Count |
|---|---|
| contract | 252 |
| e2e | 23 |
| integration | 79 |
| slow | 9 |
| smoke | 10 |

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

