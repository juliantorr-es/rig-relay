// Rig Relay — Status
// Top bar: connection indicator, session info, safety summary

import { state } from './state.js';
import { setText, el } from './utils.js';

export function renderStatusBar() {
  renderConnection();
  renderSession();
  renderSafety();
}

export function renderConnection() {
  const chip = el('status-connection');
  if (!chip) return;
  chip.className = 'header-chip ' + (state.wsConnected ? 'ok' : 'warn');
  chip.innerHTML = '<span class="header-dot"></span>' +
    (state.wsConnected ? 'Connected' : 'Bridge');
}

export function renderSession() {
  const proj = state.projection;
  const chip = el('status-session');
  if (!chip) return;

  if (proj && proj.current_state && proj.current_state.available) {
    const cs = proj.current_state;
    chip.className = 'header-chip ok';
    chip.innerHTML = '<span class="header-dot"></span>Session ' +
      (cs.generated_at || '').substring(0, 10);
  } else {
    chip.className = 'header-chip';
    chip.innerHTML = '<span class="header-dot"></span>No session';
  }
}

export function renderSafety() {
  const proj = state.projection;
  const chip = el('status-safety');
  if (!chip) return;

  if (proj && proj.current_state && proj.current_state.available) {
    const cs = proj.current_state;
    const writers = (cs.active_writers || 0) + (cs.active_readers || 0);
    const stale = cs.stale_leases || 0;

    if (writers > 0 || stale > 0) {
      chip.className = 'header-chip warn';
      chip.innerHTML = '<span class="header-dot"></span>' + writers + ' writers, ' + stale + ' stale';
    } else {
      chip.className = 'header-chip ok';
      chip.innerHTML = '<span class="header-dot"></span>Safe';
    }
  } else {
    chip.className = 'header-chip';
    chip.innerHTML = '<span class="header-dot"></span>Unknown';
  }
}
