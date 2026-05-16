// Rig Relay — Runtime Config Loading

import { recordFrontendEvent } from '../telemetry/frontendTrace.js';

export async function fetchRuntimeConfig() {
  recordFrontendEvent('frontend_runtime_config_requested');

  return new Promise((resolve) => {
    // 1. Pywebview native injection (primary)
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_runtime_config) {
      window.pywebview.api.get_runtime_config().then(config => {
        recordFrontendEvent('frontend_runtime_config_loaded', { source: 'pywebview' });
        resolve(config);
      }).catch(err => {
        recordFrontendEvent('frontend_runtime_config_invalid', { source: 'pywebview', reason: String(err) });
        resolve(getFallbackConfig());
      });
      return;
    }

    // 2. Fetch fallback (for browser debug)
    fetch('/runtime-config')
      .then(res => res.json())
      .then(config => {
        recordFrontendEvent('frontend_runtime_config_loaded', { source: 'fetch' });
        resolve(config);
      })
      .catch(err => {
        recordFrontendEvent('frontend_runtime_config_invalid', { source: 'fetch', reason: String(err) });
        resolve(getFallbackConfig());
      });
  });
}

function getFallbackConfig() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  return {
    ws_url: `${protocol}//${host}/ws`,
    auth_token: null,
    handshake_id: null
  };
}
