// Rig Relay — Status
// Top bar: connection indicator, session info, safety summary
// All DOM construction — no innerHTML

import { state } from './state.js';
import { TransportState } from './transportState.js';
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
  if (state.wsConnected) {
    setChip(chip, 'ok', 'Connected');
  } else if (state.transport === TransportState.AUTHENTICATING) {
    setChip(chip, '', 'Authenticating…');
  } else if (state.transport === TransportState.TOKEN_MISSING || state._transportStatus === 'token_missing') {
    setChip(chip, 'warn', 'Token Missing');
  } else if (state.transport === TransportState.BACKEND_UNAVAILABLE || state._transportStatus === 'offline') {
    setChip(chip, 'warn', 'Backend Unavailable');
  } else if (state.transport === TransportState.PROJECTION_READY) {
    setChip(chip, 'ok', 'Projection Ready');
  } else if (state.transport === TransportState.AUTH_FAILED) {
    setChip(chip, 'warn', 'Auth Failed');
  } else {
    setChip(chip, 'warn', 'Offline');
  }
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
