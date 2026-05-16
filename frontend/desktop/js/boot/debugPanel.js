// Rig Relay — Debug Panel Boot Helper
// Replaces main.js raw innerHTML debug panel rendering

export function createDebugPanel(containerId = 'debug-panel') {
  let panel = document.getElementById(containerId);
  if (!panel) {
    panel = document.createElement('div');
    panel.id = containerId;
    document.body.appendChild(panel);
  }
  return panel;
}

export function updateDebugPanel(panel, state) {
  if (!panel) return;
  panel.textContent = JSON.stringify(state, null, 2);
}
