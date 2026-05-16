// Rig Relay — Frontend Correlation Telemetry
// Provides handshake generation and trace propagation

export function generateHandshakeId() {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  for (let i = 0; i < 12; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return `hs_${result}`;
}

export function getSafeTimestamp() {
  return new Date().toISOString();
}
