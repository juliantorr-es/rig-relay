// Rig Relay — Status
// Top bar: connection indicator, session info, safety summary
// All DOM construction — no innerHTML

import { state } from './state.js';
import { el } from './utils.js';

function setChip(chip, className, text) {
  while (chip.firstChild) chip.removeChild(chip.firstChild);
  chip.className = 'header-chip ' + (className || '');
  const dot = document.createElement('span');
  dot.className = 'header-dot';
  chip.appendChild(dot);
  chip.appendChild(document.createTextNode(text));
}

export function renderStatusBar() {
  renderConnection();
  renderSession();
  renderSafety();
}

export function renderConnection() {
  const chip = el('status-connection');
  if (!chip) return;
  setChip(chip, state.wsConnected ? 'ok' : 'warn',
    state.wsConnected ? 'Connected' : 'Offline');
}

export function renderSession() {
  const proj = state.projection;
  const chip = el('status-session');
  if (!chip) return;

  if (proj && proj.current_state && proj.current_state.available) {
    const cs = proj.current_state;
    setChip(chip, 'ok', 'Session ' + (cs.generated_at || '').substring(0, 10));
  } else {
    setChip(chip, '', 'No session');
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
      setChip(chip, 'warn', writers + ' writers, ' + stale + ' stale');
    } else {
      setChip(chip, 'ok', 'Safe');
    }
  } else {
    setChip(chip, '', 'Unknown');
  }
}
