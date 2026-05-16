// Rig Relay — Status
// Top bar: connection indicator, session info, safety summary
// All DOM construction — no innerHTML
// Renders ONLY from the canonical transport state authority.

import { state } from './state.js';
import { TransportStatus, STATUS_LABELS, STATUS_CHIP_CLASS, detectStatusContradiction } from './transportState.js';
import { el } from './utils.js';
import { recordFrontendEvent } from './telemetry/frontendTrace.js';

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

export function renderStatusFromState(snap) {
  const chip = el('status-connection');
  if (!chip || !snap) return;
  const label = snap.label || STATUS_LABELS[snap.transport.status] || 'Unknown';
  const chipClass = snap.chipClass || STATUS_CHIP_CLASS[snap.transport.status] || 'warn';
  setChip(chip, chipClass, label);
}

export function renderConnection() {
  const chip = el('status-connection');
  if (!chip) return;

  const status = state.transport.status || TransportStatus.IDLE;
  const label = STATUS_LABELS[status] || 'Unknown';
  const chipClass = STATUS_CHIP_CLASS[status] || 'warn';

  recordFrontendEvent('frontend_status_rendered', {
    connection_state: status,
    ws_connected: state.wsConnected,
    label: label,
    phase: state.transport.phase || 'unknown',
    last_event: state.transport.lastEvent || '',
  });

  // Golden-path contradiction detection
  detectStatusContradiction({ transport: state.transport, wsConnected: state.wsConnected }, label);

  setChip(chip, chipClass, label);
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
