# Test Quality Taxonomy

Categories used to classify tests in the Rig Relay test suite.

| Category | Code | Definition |
|----------|------|------------|
| **Contract High Value** | `contract_high_value` | Tests that lock down a public API contract, schema shape, or required behavior across tools. Highest preservation priority. |
| **Behavior High Value** | `behavior_high_value` | Tests that cover core end-to-end behavior not covered by narrower contract tests. |
| **Regression Specific** | `regression_specific` | Tests added in response to a concrete bug or failure. Must preserve the fix. |
| **Schema Validation** | `schema_validation` | Tests that validate a schema file (JSON Schema) or model dump against a schema. Low brittleness, high contract value. |
| **Receipt Policy** | `receipt_policy` | Tests that enforce content-light policy on tool receipts. Critical for privacy. |
| **Integration High Value** | `integration_high_value` | Tests that exercise a real subprocess (git, uv, shell) in a controlled temp directory. Valuable but slower. |
| **Smoke** | `smoke` | Quick pass/fail check that a component loads or produces expected output given trivial input. |
| **Duplicate** | `duplicate` | Exact copy of another test — same function body, same assertions. Should be removed. |
| **Near Duplicate** | `near_duplicate` | Same intent as another test with minor variations (slightly different input, different file). Should be parametrized. |
| **Implementation Detail** | `implementation_detail` | Asserts against private helper functions, internal data structures, or tightly coupled mock setups. High maintenance, low protection value. |
| **Brittle** | `brittle` | Asserts exact string matches against long messages, line numbers, or formatting that changes frequently. |
| **Overbroad** | `overbroad` | Tests too many things at once, making failure diagnosis unclear. Should be split. |
| **Slow Without Tier** | `slow_without_tier` | Takes >200ms due to real subprocess or git setup. Should be marked `slow` or assigned to a slower CI tier. |
| **Unclear Purpose** | `unclear_purpose` | Test name or assertions are ambiguous about what contract is being protected. |
| **Stale** | `stale` | Tests a feature or behavior that no longer exists. Should be removed. |
| **Missing Coverage** | `missing_coverage` | Gap: important contract, scenario, or pipeline without any test coverage. |
