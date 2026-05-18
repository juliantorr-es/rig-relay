// Rig Relay — Generic Finite State Machine Factory
// Guards runtime state transitions in the frontend kernel.
// Preconditions: config.states must contain config.initial.
// Each transition requires the current state to match `from` (or wildcard '*').
// Guards assert domain invariants before a transition commits; effects run
// side-effects after the state change is committed.

const WILDCARD = '*';

function matchesFrom(from, currentState) {
  if (from === WILDCARD) return true;
  if (Array.isArray(from)) return from.includes(currentState);
  return from === currentState;
}

function toArray(maybeArray) {
  if (maybeArray == null) return [];
  return Array.isArray(maybeArray) ? maybeArray : [maybeArray];
}

export function createStateMachine(config) {
  const frozenConfig = Object.freeze({
    id: config.id,
    initial: config.initial,
    states: Object.freeze({ ...config.states }),
    transitions: Object.freeze([...config.transitions]),
    effects: config.effects ? Object.freeze(toArray(config.effects)) : null,
    guards: config.guards ? Object.freeze(toArray(config.guards)) : null,
  });

  let currentState = frozenConfig.initial;
  const listeners = new Set();

  function getState() {
    return currentState;
  }

  function reset() {
    currentState = frozenConfig.initial;
  }

  function subscribe(listener) {
    listeners.add(listener);
    return function unsubscribe() {
      listeners.delete(listener);
    };
  }

  function notifyListeners(newState, oldState) {
    for (const listener of listeners) {
      try {
        listener(newState, oldState);
      } catch (_) {
        // Swallow listener errors so one broken listener does not break others.
      }
    }
  }

  function transition(event, ctx) {
    const oldState = currentState;

    // --- Guard phase: locate the first passing transition ---
    // Iterate through ALL matching transitions; skip guards that fail.
    var matching = null;
    var blockedCount = 0;
    for (var i = 0; i < frozenConfig.transitions.length; i++) {
      var t = frozenConfig.transitions[i];
      if (t.event !== event || !matchesFrom(t.from, oldState)) continue;
      if (t.guard && !t.guard(ctx)) {
        blockedCount++;
        continue;
      }
      matching = t;
      break;
    }

    if (!matching) {
      return {
        success: false,
        from: oldState,
        error: 'no transition for event "' + event + '" from state "' + oldState + '"',
        blocked: blockedCount > 0 ? blockedCount : undefined,
      };
    }

    if (frozenConfig.guards) {
      for (const guard of frozenConfig.guards) {
        if (!guard(ctx)) {
          return { success: false, from: oldState, blocked: true };
        }
      }
    }

    const newState = matching.to;
    const isSelfTransition = oldState === newState;

    // --- Exit old state (skip on self-transitions) ---
    if (!isSelfTransition) {
      const oldDef = frozenConfig.states[oldState];
      if (oldDef && oldDef.exit) oldDef.exit(ctx);
    }

    // Commit
    currentState = newState;

    // --- Enter new state (skip on self-transitions) ---
    if (!isSelfTransition) {
      const newDef = frozenConfig.states[newState];
      if (newDef && newDef.entry) newDef.entry(ctx);
    }

    // --- Effects run after the state change is committed ---
    if (matching.effect) matching.effect(ctx);

    if (frozenConfig.effects) {
      for (const effect of frozenConfig.effects) {
        effect(ctx);
      }
    }

    notifyListeners(newState, oldState);

    return { success: true, from: oldState, to: newState };
  }

  // dispatch is an alias for transition — compat with notification subsystem
  function dispatch(event, ctx) {
    return transition(event, ctx);
  }

  // snapshot returns a plain object with the current state
  function snapshot() {
    return { state: currentState };
  }

  return Object.freeze({
    transition,
    dispatch,
    getState,
    subscribe,
    reset,
    snapshot,
  });
}
