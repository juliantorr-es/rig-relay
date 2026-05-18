// Rig Relay — Frontend Runtime Multi-Tab Detection
// Multi-tab detection. NEVER transmits tokens, secrets, or handshake IDs.
// Only transmits { type: 'cockpit_present', timestamp }.

import { ActionTypes as AT } from './actions.js';

export function setupBroadcastChannel(dispatch) {
  let channel = null;

  try {
    if (typeof BroadcastChannel !== 'undefined') {
      channel = new BroadcastChannel('rig-relay-cockpit');
      channel.onmessage = () => {
        dispatch({ type: AT.MULTI_TAB_SECONDARY_DETECTED });
      };
      channel.postMessage({ type: 'cockpit_present', timestamp: Date.now() });
    }
  } catch (_) {
    // BroadcastChannel unavailable.
  }

  return {
    channel,
    close() {
      if (channel) {
        try { channel.close(); } catch (_) { /* ignore */ }
        channel = null;
      }
    },
  };
}
