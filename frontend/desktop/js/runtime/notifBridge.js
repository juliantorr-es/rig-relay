// Rig Relay — Notification System Bridge
// Extracted from kernel.js: provides registerMachine, onReady, onNotReady,
// and a polymorphic subscribe that supports both generic and action-type
// filtered subscriptions. Used by notifications.js setup().

import { createStateMachine } from './stateMachine.js';
import { isBootReady } from './selectors.js';

export function createNotificationBridge(kernelInternals) {
  const { getState, subscribers, typedSubscribers } = kernelInternals;

  const _compatMachines = Object.create(null);
  const _readyCallbacks = [];
  const _notReadyCallbacks = [];

  function registerMachine(id, machineConfig) {
    if (_compatMachines[id]) return _compatMachines[id];
    var sm = createStateMachine({
      id,
      initial: machineConfig.initialState,
      states: Object.fromEntries(
        (machineConfig.states || []).map(function (s) { return [s, {}]; })
      ),
      transitions: Object.entries(machineConfig.transitions || {}).flatMap(
        function ([from, eventMap]) {
          return Object.entries(eventMap).map(function ([event, to]) {
            return { from, to, event };
          });
        }
      ),
    });
    if (typeof machineConfig.onTransition === 'function') {
      sm.subscribe(function (to) {
        machineConfig.onTransition({ nextState: to });
      });
    }
    _compatMachines[id] = sm;
    return sm;
  }

  function onReady(fn) {
    if (typeof fn !== 'function') return;
    _readyCallbacks.push(fn);
    if (isBootReady(getState())) fn();
  }

  function onNotReady(fn) {
    if (typeof fn !== 'function') return;
    _notReadyCallbacks.push(fn);
    if (!isBootReady(getState()) && getState().boot.phase !== 'static_shell_loaded') fn();
  }

  // Polymorphic subscribe: supports both generic and action-type filtering.
  // subscribe(fn) → called on every dispatch with (newState, oldState, action)
  // subscribe(actionType, fn) → called only for matching type with (action)
  function subscribe() {
    var listener, actionType;
    if (arguments.length === 2) {
      actionType = arguments[0];
      listener = arguments[1];
    } else {
      listener = arguments[0];
    }
    if (typeof listener !== 'function') return function () {};

    if (actionType) {
      if (!typedSubscribers[actionType]) typedSubscribers[actionType] = new Set();
      typedSubscribers[actionType].add(listener);
      return function () {
        if (typedSubscribers[actionType]) typedSubscribers[actionType].delete(listener);
      };
    }

    subscribers.add(listener);
    return function () { subscribers.delete(listener); };
  }

  // Fire ready/not-ready callbacks after each dispatch
  var _wasReady = false;
  subscribers.add(function () {
    var nowReady = isBootReady(getState());
    if (nowReady && !_wasReady) {
      _wasReady = true;
      for (var i = 0; i < _readyCallbacks.length; i++) {
        _readyCallbacks[i]();
      }
    } else if (!nowReady && _wasReady) {
      _wasReady = false;
      for (var j = 0; j < _notReadyCallbacks.length; j++) {
        _notReadyCallbacks[j]();
      }
    }
  });

  function destroy() {
    _readyCallbacks.length = 0;
    _notReadyCallbacks.length = 0;
    for (var key in _compatMachines) {
      delete _compatMachines[key];
    }
  }

  return { registerMachine, onReady, onNotReady, subscribe, destroy };
}
