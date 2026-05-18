# Conversation Summary: Resolving Rig Relay Frontend Boot & Eliminating Connection Lost Toast

- **Date:** 2026-05-18
- **Project:** Rig Relay
- **Phase:** no-phase
- **Topic:** Frontend Boot Stabilization, FSM Guards, and Effect System Dispatch

## USER Objective
The user's objective was to resolve a persistent "Connection Lost" boot failure in the Rig Relay desktop application by fixing a faulty Finite State Machine (FSM) guard in `kernel.js` that improperly accessed configuration variables, and by rectifying a `TypeError` in the effect system caused by an uninitialized `dispatch` dependency. These fixes were intended to allow the Boot FSM to reach the `READY` state, thereby suppressing false-positive connection warning toasts and ensuring proper initialization of the operator cockpit.

## Key Findings & Root Cause Analysis

### 1. Boot FSM Guard Configuration Access (`wsUrlGuard`)
- **Symptom:** The Boot FSM stalled at `BP.RUNTIME_CONFIG_LOADED`, preventing the transition to `BP.TRANSPORT_CONNECTING`.
- **Root Cause:** `wsUrlGuard` in `kernel.js` inspected the global `config` object (which lacked `wsUrl` during kernel initialization) instead of inspecting the transition context (`ctx`).
- **Remediation:** Updated `wsUrlGuard(ctx)` to check `ctx?.wsUrl || ctx?.ws_url || config?.wsUrl || config?.ws_url`. Additionally, updated `orchestrator.js` to pass `wsUrl: config.ws_url` into `createRuntime` and `{ wsUrl: config.ws_url }` into `runtime.bootFSM.transition('boot:transport_connecting', ...)`.

### 2. Effect System Dispatch TypeError (`_registerEffects`)
- **Symptom:** Uncaught `TypeError: dispatch is not a function` during `AT.PROJECTION_RECEIVED` events.
- **Root Cause:** `_registerEffects` in `kernel.js` was invoked early during kernel setup, binding its `dispatch` parameter to `_dispatch` while `_dispatch` was still `undefined`.
- **Remediation:** Updated `_registerEffects` callbacks to reference `effectRunner.dispatch` directly, which is dynamically updated by the kernel once `_dispatch` is fully constructed.

### 3. Asynchronous WebSocket Boot Race Condition
- **Symptom:** Even after fixing `wsUrlGuard` and the `TypeError`, the Boot FSM remained in `BP.PROJECTION_WAITING` and did not reach `BP.READY`.
- **Root Cause:** `orchestrator.js` attempted to execute `boot:rendering` and `boot:ready` synchronously at the end of `boot()`. Because the WebSocket connection is asynchronous, the FSM was still in `BP.TRANSPORT_CONNECTING` at that moment, causing the synchronous transitions to be rejected. When the WebSocket connected and received the first projection, it transitioned the FSM to `BP.PROJECTION_WAITING`, but nothing ever transitioned it further.
- **Remediation:** Added `boot:rendering` and `boot:ready` transitions directly into the `onProjection` handlers of `protocolClient` and `wsClient` in `orchestrator.js`.

## Verification Results
- **Browser Subagent Audit:** Executed a live browser inspection subagent (`cockpit_verification_flawless`) against `http://127.0.0.1:56293/index.html`.
- **Outcome:** The application successfully boots and reaches `BP.READY`. All 16 registered cockpit widgets instantly mount in the `READY` state without errors. The false "Connection Lost" toast is completely eliminated.
- **Schema Validation:** All 169 schemas validated successfully (`scripts/rig_relay_validate_schemas.py`).
- **Canonical Report:** Persisted structured mission report to `docs/json/2026-05-18--rig-relay--frontend-boot-stabilization--mission-report.json`.

## Next Steps / Remaining Seams
- Consolidate duplicate projection waiting/rendering transition triggers between `protocolClient` and `wsClient`.
- Refactor legacy bare-message intent paths to use v1 protocol client envelopes.
