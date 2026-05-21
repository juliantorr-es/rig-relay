// Rig Relay — Analytics Widgets
// Eight analytics widgets rendered from projection data.
// Dumb renderers — all data comes from the backend via WebSocket projection.

import { state } from '../state.js';
import { registerWidget, renderCompactChip, renderStandardCard, renderExpandedWidget } from '../widgets.js';
import { escapeHtml } from '../utils.js';

let _analyticsData = null;

export function updateAnalyticsData(data) {
  _analyticsData = data || null;
}

function analytics() {
  return _analyticsData || (state.projection && state.projection.analytics) || null;
}

// ── SVG Donut Chart Helper ──
function buildDonutSVG(segments, size) {
  size = size || 80;
  var cx = size / 2;
  var cy = size / 2;
  var r = (size / 2) - 8;
  var strokeW = (size / 2) - 4;
  var total = 0;
  var i;
  for (i = 0; i < segments.length; i++) {
    total += segments[i].value;
  }
  if (total === 0) return '';

  var colors = segments.map(function(s) { return s.color || 'var(--text-muted)'; });
  var offset = 0;
  var circum = 2 * Math.PI * r;

  var svg = '<svg width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size + '">';
  for (i = 0; i < segments.length; i++) {
    var fraction = segments[i].value / total;
    var dashLen = fraction * circum;
    var dashOffset = circum - offset;
    svg += '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none"';
    svg += ' stroke="' + colors[i] + '" stroke-width="' + strokeW + '"';
    svg += ' stroke-dasharray="' + dashLen.toFixed(1) + ' ' + (circum - dashLen).toFixed(1) + '"';
    svg += ' stroke-dashoffset="' + dashOffset.toFixed(1) + '"';
    svg += ' transform="rotate(-90 ' + cx + ' ' + cy + ')"/>';
    offset += dashLen;
  }
  // Inner circle for donut effect
  var innerR = r - strokeW / 2;
  svg += '<circle cx="' + cx + '" cy="' + cy + '" r="' + innerR + '" fill="var(--bg-card)"/>';
  // Center text
  svg += '<text x="' + cx + '" y="' + cy + '" text-anchor="middle" dominant-baseline="central" fill="var(--text-primary)" font-size="14" font-weight="600">' + total + '</text>';
  svg += '</svg>';
  return svg;
}

// ════════════════════════════════════════════════════════════════
// 1. Governance Gate Health
// ════════════════════════════════════════════════════════════════
registerWidget('governanceGateHealth', function(container, level) {
  var a = analytics();
  var g = (a && a.governance_gate_health) || {};

  if (!g.available) {
    if (level === 'compact') {
      renderCompactChip(container, 'Gate Health', function() {
        return { text: '\u2014', cls: '' };
      });
      return;
    }
  }

  if (level === 'compact') {
    var total = g.total || 0;
    var allowed = g.decisions ? (g.decisions.allowed || 0) : 0;
    var text = allowed + '/' + total + ' allowed';
    var cls = total === 0 ? '' : (allowed === total ? 'ok' : 'warn');
    renderCompactChip(container, 'Gate Health', function() {
      return { text: text, cls: cls };
    });
    return;
  }

  if (level === 'expanded') {
    var html = '<h3>Governance Gate Health</h3>';
    if (!g.available) {
      html += '<p class="analytics-unavailable">No gate health data available.</p>';
    } else {
      var dec = g.decisions || {};
      var al = dec.allowed || 0;
      var bl = dec.blocked || 0;
      var cr = dec.critical || 0;
      html += '<table class="kv-table">' +
        '<tr><td class="key">Allowed</td><td class="val ok">' + al + '</td></tr>' +
        '<tr><td class="key">Blocked</td><td class="val warn">' + bl + '</td></tr>' +
        '<tr><td class="key">Critical</td><td class="val error">' + cr + '</td></tr>' +
        '<tr><td class="key">Total</td><td class="val">' + (g.total || 0) + '</td></tr>' +
        '</table>';
    }
    renderExpandedWidget(container, 'Governance Gate Health', html);
    return;
  }

  if (!g.available) {
    renderStandardCard(container, 'Gate Health',
      '<span class="analytics-unavailable">Unavailable</span>', 'governanceGateHealth');
    return;
  }

  var decisions = g.decisions || {};
  var al2 = decisions.allowed || 0;
  var bl2 = decisions.blocked || 0;
  var cr2 = decisions.critical || 0;
  var tot = g.total || 0;

  var html = '<div class="analytics-bar-chart">' +
    '<div class="analytics-bar-col"><div class="analytics-bar analytics-bar-allowed" style="height:' + (tot > 0 ? Math.max(4, (al2 / Math.max(tot, 1)) * 50) : 0) + 'px"></div><span class="analytics-bar-label">Allowed</span></div>' +
    '<div class="analytics-bar-col"><div class="analytics-bar analytics-bar-blocked" style="height:' + (tot > 0 ? Math.max(4, (bl2 / Math.max(tot, 1)) * 50) : 0) + 'px"></div><span class="analytics-bar-label">Blocked</span></div>' +
    '<div class="analytics-bar-col"><div class="analytics-bar analytics-bar-critical" style="height:' + (tot > 0 ? Math.max(4, (cr2 / Math.max(tot, 1)) * 50) : 0) + 'px"></div><span class="analytics-bar-label">Critical</span></div>' +
    '</div>' +
    '<div style="font-size:var(--font-size-xs);color:var(--text-muted);margin-top:4px">' + al2 + ' allowed, ' + bl2 + ' blocked, ' + cr2 + ' critical</div>';

  var cls = (bl2 + cr2) > 0 ? 'warn' : 'ok';
  renderStandardCard(container, 'Gate Health', html, 'governanceGateHealth', cls);
});

// ════════════════════════════════════════════════════════════════
// 2. Session Health
// ════════════════════════════════════════════════════════════════
registerWidget('sessionHealth', function(container, level) {
  var a = analytics();
  var s = (a && a.session_health) || {};

  if (!s.available) {
    if (level === 'compact') {
      renderCompactChip(container, 'Sessions', function() {
        return { text: '\u2014', cls: '' };
      });
      return;
    }
  }

  if (level === 'compact') {
    var total = s.total || 0;
    var healthy = s.sessions ? (s.sessions.healthy || 0) : 0;
    var cls = total === 0 ? '' : (healthy === total ? 'ok' : 'warn');
    renderCompactChip(container, 'Sessions', function() {
      return { text: healthy + '/' + total + ' healthy', cls: cls };
    });
    return;
  }

  if (level === 'expanded') {
    var html = '<h3>Session Health Scorecard</h3>';
    if (!s.available) {
      html += '<p class="analytics-unavailable">No session health data available.</p>';
    } else {
      var ss = s.sessions || {};
      html += '<table class="kv-table">' +
        '<tr><td class="key">Healthy</td><td class="val ok">' + (ss.healthy || 0) + '</td></tr>' +
        '<tr><td class="key">Degraded</td><td class="val warn">' + (ss.degraded || 0) + '</td></tr>' +
        '<tr><td class="key">Failed</td><td class="val error">' + (ss.failed || 0) + '</td></tr>' +
        '<tr><td class="key">Total</td><td class="val">' + (s.total || 0) + '</td></tr>' +
        '</table>';
    }
    renderExpandedWidget(container, 'Session Health', html);
    return;
  }

  if (!s.available) {
    renderStandardCard(container, 'Session Health',
      '<span class="analytics-unavailable">Unavailable</span>', 'sessionHealth');
    return;
  }

  var ss2 = s.sessions || {};
  var h = ss2.healthy || 0;
  var d = ss2.degraded || 0;
  var f = ss2.failed || 0;
  var cls2 = f > 0 ? 'error' : d > 0 ? 'warn' : 'ok';

  var html = '<div class="analytics-scorecard">' +
    '<div class="analytics-score-item ok"><div class="analytics-score-value">' + h + '</div><div class="analytics-score-label">Healthy</div></div>' +
    '<div class="analytics-score-item warn"><div class="analytics-score-value">' + d + '</div><div class="analytics-score-label">Degraded</div></div>' +
    '<div class="analytics-score-item error"><div class="analytics-score-value">' + f + '</div><div class="analytics-score-label">Failed</div></div>' +
    '</div>';

  renderStandardCard(container, 'Session Health', html, 'sessionHealth', cls2);
});

// ════════════════════════════════════════════════════════════════
// 3. Tool Latency
// ════════════════════════════════════════════════════════════════
registerWidget('toolLatency', function(container, level) {
  var a = analytics();
  var t = (a && a.tool_latency) || {};

  if (level === 'compact') {
    // Tool latency only has standard/expanded display
    return;
  }

  if (level === 'expanded') {
    var html = '<h3>Tool Latency Heatmap</h3>';
    if (!t.available || !t.tools || !t.tools.length) {
      html += '<p class="analytics-unavailable">No tool latency data available.</p>';
    } else {
      html += '<table class="analytics-heatmap">' +
        '<thead><tr><th>Tool</th><th>p50</th><th>p95</th><th>p99</th></tr></thead><tbody>';
      t.tools.forEach(function(tool) {
        var p50 = tool.p50_ms || 0;
        var p95 = tool.p95_ms || 0;
        var p99 = tool.p99_ms || 0;
        var max = Math.max(p50, p95, p99, 1);
        var p95warn = p95 > 200;
        html += '<tr>' +
          '<td>' + escapeHtml(tool.name || '\u2014') + '</td>' +
          '<td class="mono">' + p50 + 'ms <span class="bar-bg"><span class="bar-fill" style="width:' + ((p50 / max) * 100).toFixed(1) + '%"></span></span></td>' +
          '<td class="mono">' + p95 + 'ms <span class="bar-bg"><span class="bar-fill' + (p95warn ? ' warn' : '') + '" style="width:' + ((p95 / max) * 100).toFixed(1) + '%"></span></span></td>' +
          '<td class="mono">' + p99 + 'ms</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
    }
    renderExpandedWidget(container, 'Tool Latency', html);
    return;
  }

  if (!t.available || !t.tools || !t.tools.length) {
    renderStandardCard(container, 'Tool Latency',
      '<span class="analytics-unavailable">Unavailable</span>', 'toolLatency');
    return;
  }

  var html = '<table class="analytics-heatmap">' +
    '<thead><tr><th>Tool</th><th>p50</th><th>p95</th></tr></thead><tbody>';
  t.tools.slice(0, 6).forEach(function(tool) {
    var p50 = tool.p50_ms || 0;
    var p95 = tool.p95_ms || 0;
    var max = Math.max(p50, p95, 1);
    var p95warn = p95 > 200;
    html += '<tr>' +
      '<td>' + escapeHtml(tool.name || '\u2014') + '</td>' +
      '<td class="mono">' + p50 + 'ms <span class="bar-bg"><span class="bar-fill" style="width:' + ((p50 / max) * 100).toFixed(1) + '%"></span></span></td>' +
      '<td class="mono">' + p95 + 'ms <span class="bar-bg"><span class="bar-fill' + (p95warn ? ' warn' : '') + '" style="width:' + ((p95 / max) * 100).toFixed(1) + '%"></span></span></td>' +
      '</tr>';
  });
  html += '</tbody></table>';

  var worst = t.tools.reduce(function(w, tool) { return (tool.p95_ms || 0) > (w.p95_ms || 0) ? tool : w; }, { name: '', p95_ms: 0 });
  var cls = (worst.p95_ms || 0) > 200 ? 'warn' : 'ok';

  renderStandardCard(container, 'Tool Latency', html, 'toolLatency', cls);
});

// ════════════════════════════════════════════════════════════════
// 4. Release Blocker
// ════════════════════════════════════════════════════════════════
registerWidget('releaseBlocker', function(container, level) {
  var a = analytics();
  var r = (a && a.release_blockers) || {};

  if (level === 'compact') {
    var open = r.available ? (r.open || 0) : -1;
    var text = open >= 0 ? open + ' open' : '\u2014';
    var cls = r.available ? (open === 0 ? 'ok' : 'error') : '';
    renderCompactChip(container, 'Blockers', function() {
      return { text: text, cls: cls };
    });
    return;
  }

  if (level === 'expanded') {
    var html = '<h3>Release Blocker Burndown</h3>';
    if (!r.available) {
      html += '<p class="analytics-unavailable">No release blocker data available.</p>';
    } else {
      var resolved = r.resolved || 0;
      var total = r.total || 0;
      var pct = total > 0 ? ((resolved / total) * 100).toFixed(0) : 100;
      html += '<div class="analytics-burndown">' +
        '<div class="analytics-burndown-label"><span>Resolved: ' + resolved + '/' + total + '</span><span>' + pct + '%</span></div>' +
        '<div class="analytics-burndown-bar"><div class="analytics-burndown-fill' + (r.open > 0 ? ' warn' : '') + '" style="width:' + pct + '%"></div></div>' +
        '</div>' +
        '<table class="kv-table" style="margin-top:8px">' +
        '<tr><td class="key">Open</td><td class="val error">' + (r.open || 0) + '</td></tr>' +
        '<tr><td class="key">Resolved</td><td class="val ok">' + (r.resolved || 0) + '</td></tr>' +
        '<tr><td class="key">Total</td><td class="val">' + (r.total || 0) + '</td></tr>' +
        '<tr><td class="key">Trend</td><td class="val">' + escapeHtml(r.trend || '\u2014') + '</td></tr>' +
        '</table>';
    }
    renderExpandedWidget(container, 'Release Blockers', html);
    return;
  }

  if (!r.available) {
    renderStandardCard(container, 'Release Blockers',
      '<span class="analytics-unavailable">Unavailable</span>', 'releaseBlocker');
    return;
  }

  var resolved2 = r.resolved || 0;
  var total2 = r.total || 0;
  var pct2 = total2 > 0 ? ((resolved2 / total2) * 100).toFixed(0) : 100;
  var cls2 = r.open > 0 ? 'error' : 'ok';

  var html = '<div class="analytics-burndown">' +
    '<div class="analytics-burndown-label"><span>Resolved</span><span>' + pct2 + '%</span></div>' +
    '<div class="analytics-burndown-bar"><div class="analytics-burndown-fill' + (r.open > 0 ? ' warn' : '') + '" style="width:' + pct2 + '%"></div></div>' +
    '</div>' +
    '<div style="font-size:var(--font-size-xs);color:var(--text-muted);margin-top:4px">' + (r.open || 0) + ' open, ' + resolved2 + ' resolved</div>';

  renderStandardCard(container, 'Release Blockers', html, 'releaseBlocker', cls2);
});

// ════════════════════════════════════════════════════════════════
// 5. Dependency Risk
// ════════════════════════════════════════════════════════════════
registerWidget('dependencyRisk', function(container, level) {
  var a = analytics();
  var d = (a && a.dependency_risk) || {};

  if (level === 'compact') {
    return;
  }

  if (level === 'expanded') {
    var html = '<h3>Dependency Risk</h3>';
    if (!d.available || !d.packages || !d.packages.length) {
      html += '<p class="analytics-unavailable">No dependency risk data available.</p>';
    } else {
      var riskCounts = { high: 0, medium: 0, low: 0 };
      d.packages.forEach(function(p) { riskCounts[p.risk] = (riskCounts[p.risk] || 0) + 1; });

      var segments = [
        { value: riskCounts.high, color: 'var(--error)' },
        { value: riskCounts.medium, color: 'var(--warn)' },
        { value: riskCounts.low, color: 'var(--ok)' },
      ];

      html += '<div class="analytics-donut-container">';
      html += buildDonutSVG(segments, 100);
      html += '<div class="analytics-donut-legend">' +
        '<div class="analytics-donut-legend-item"><span class="analytics-donut-legend-dot" style="background:var(--error)"></span> High: ' + riskCounts.high + '</div>' +
        '<div class="analytics-donut-legend-item"><span class="analytics-donut-legend-dot" style="background:var(--warn)"></span> Medium: ' + riskCounts.medium + '</div>' +
        '<div class="analytics-donut-legend-item"><span class="analytics-donut-legend-dot" style="background:var(--ok)"></span> Low: ' + riskCounts.low + '</div>' +
        '</div></div>';

      html += '<div class="analytics-risk-list" style="margin-top:8px">';
      d.packages.forEach(function(p) {
        html += '<div class="analytics-risk-item">' +
          '<span class="analytics-risk-name">' + escapeHtml(p.name || '\u2014') + '</span>' +
          '<span class="analytics-risk-version">' + escapeHtml(p.current || '') + (p.current !== p.latest ? ' \u2192 ' + escapeHtml(p.latest || '') : '') + '</span>' +
          '<span class="analytics-risk-tag ' + (p.risk || 'low') + '">' + escapeHtml(p.risk || 'low') + '</span>' +
          '</div>';
      });
      html += '</div>';
    }
    renderExpandedWidget(container, 'Dependency Risk', html);
    return;
  }

  if (!d.available || !d.packages || !d.packages.length) {
    renderStandardCard(container, 'Dependency Risk',
      '<span class="analytics-unavailable">Unavailable</span>', 'dependencyRisk');
    return;
  }

  var highs = 0;
  d.packages.forEach(function(p) { if (p.risk === 'high') highs++; });
  var cls = highs > 0 ? 'warn' : 'ok';

  var html = '<div class="analytics-risk-list">';
  d.packages.slice(0, 5).forEach(function(p) {
    html += '<div class="analytics-risk-item">' +
      '<span class="analytics-risk-name">' + escapeHtml(p.name || '\u2014') + '</span>' +
      '<span class="analytics-risk-tag ' + (p.risk || 'low') + '">' + escapeHtml(p.risk || 'low') + '</span>' +
      '</div>';
  });
  html += '</div>';
  if (d.packages.length > 5) {
    html += '<div style="font-size:var(--font-size-xs);color:var(--text-muted)">+ ' + (d.packages.length - 5) + ' more</div>';
  }

  renderStandardCard(container, 'Dependency Risk', html, 'dependencyRisk', cls);
});

// ════════════════════════════════════════════════════════════════
// 6. Findings
// ════════════════════════════════════════════════════════════════
registerWidget('findingsWidget', function(container, level) {
  var a = analytics();
  var f = (a && a.findings) || {};

  if (level === 'compact') {
    var open = f.available ? (f.open || 0) : -1;
    var text = open >= 0 ? open + ' open' : '\u2014';
    var cls = f.available ? (open === 0 ? 'ok' : 'warn') : '';
    renderCompactChip(container, 'Findings', function() {
      return { text: text, cls: cls };
    });
    return;
  }

  if (level === 'expanded') {
    var html = '<h3>Findings Summary</h3>';
    if (!f.available) {
      html += '<p class="analytics-unavailable">No findings data available.</p>';
    } else {
      var bySev = f.by_severity || {};
      html += '<table class="kv-table">' +
        '<tr><td class="key">Total</td><td class="val">' + (f.total || 0) + '</td></tr>' +
        '<tr><td class="key">Open</td><td class="val warn">' + (f.open || 0) + '</td></tr>' +
        '<tr><td class="key">Resolved</td><td class="val ok">' + (f.resolved || 0) + '</td></tr>' +
        '</table>' +
        '<h3 style="margin-top:12px">By Severity</h3>' +
        '<div class="analytics-findings-list">' +
        '<div class="analytics-findings-row"><span class="analytics-findings-label">Critical</span><span class="analytics-findings-value critical">' + (bySev.critical || 0) + '</span></div>' +
        '<div class="analytics-findings-row"><span class="analytics-findings-label">High</span><span class="analytics-findings-value high">' + (bySev.high || 0) + '</span></div>' +
        '<div class="analytics-findings-row"><span class="analytics-findings-label">Medium</span><span class="analytics-findings-value medium">' + (bySev.medium || 0) + '</span></div>' +
        '<div class="analytics-findings-row"><span class="analytics-findings-label">Low</span><span class="analytics-findings-value low">' + (bySev.low || 0) + '</span></div>' +
        '</div>';
    }
    renderExpandedWidget(container, 'Findings', html);
    return;
  }

  if (!f.available) {
    renderStandardCard(container, 'Findings',
      '<span class="analytics-unavailable">Unavailable</span>', 'findingsWidget');
    return;
  }

  var bySev2 = f.by_severity || {};
  var cls2 = (bySev2.critical || 0) > 0 ? 'error' : (bySev2.high || 0) > 0 ? 'warn' : 'ok';

  var html = '<div class="analytics-findings-list">' +
    '<div class="analytics-findings-row"><span class="analytics-findings-label">Critical</span><span class="analytics-findings-value critical">' + (bySev2.critical || 0) + '</span></div>' +
    '<div class="analytics-findings-row"><span class="analytics-findings-label">High</span><span class="analytics-findings-value high">' + (bySev2.high || 0) + '</span></div>' +
    '<div class="analytics-findings-row"><span class="analytics-findings-label">Medium</span><span class="analytics-findings-value medium">' + (bySev2.medium || 0) + '</span></div>' +
    '<div class="analytics-findings-row"><span class="analytics-findings-label">Low</span><span class="analytics-findings-value low">' + (bySev2.low || 0) + '</span></div>' +
    '</div>' +
    '<div style="font-size:var(--font-size-xs);color:var(--text-muted);margin-top:4px">' + (f.open || 0) + ' open, ' + (f.resolved || 0) + ' resolved</div>';

  renderStandardCard(container, 'Findings', html, 'findingsWidget', cls2);
});

// ════════════════════════════════════════════════════════════════
// 7. Correlation Integrity
// ════════════════════════════════════════════════════════════════
registerWidget('correlationIntegrity', function(container, level) {
  var a = analytics();
  var c = (a && a.correlation_integrity) || {};

  if (level === 'compact') {
    if (!c.available) {
      renderCompactChip(container, 'Correlation', function() {
        return { text: '\u2014', cls: '' };
      });
      return;
    }
    var status = c.status || 'unknown';
    var text = c.matched !== undefined ? (c.matched + '/' + (c.total || 0) + ' matched') : status;
    var cls = status === 'healthy' ? 'ok' : 'warn';
    renderCompactChip(container, 'Correlation', function() {
      return { text: text, cls: cls };
    });
    return;
  }

  if (level === 'expanded') {
    var html = '<h3>Correlation Integrity</h3>';
    if (!c.available) {
      html += '<p class="analytics-unavailable">No correlation data available.</p>';
    } else {
      html += '<table class="kv-table">' +
        '<tr><td class="key">Status</td><td class="val' + (c.status === 'healthy' ? ' ok' : ' warn') + '">' + escapeHtml(c.status || '\u2014') + '</td></tr>' +
        '<tr><td class="key">Matched</td><td class="val ok">' + (c.matched || 0) + '</td></tr>' +
        '<tr><td class="key">Unmatched</td><td class="val' + (c.unmatched > 0 ? ' error' : '') + '">' + (c.unmatched || 0) + '</td></tr>' +
        '<tr><td class="key">Total</td><td class="val">' + (c.total || 0) + '</td></tr>' +
        '</table>';
    }
    renderExpandedWidget(container, 'Correlation Integrity', html);
    return;
  }

  if (!c.available) {
    renderStandardCard(container, 'Correlation Integrity',
      '<span class="analytics-unavailable">Unavailable</span>', 'correlationIntegrity');
    return;
  }

  var cls2 = c.status === 'healthy' ? 'ok' : 'warn';

  var html = '<table class="kv-table">' +
    '<tr><td class="key">Status</td><td class="val' + (c.status === 'healthy' ? ' ok' : ' warn') + '">' + escapeHtml(c.status || '\u2014') + '</td></tr>' +
    '<tr><td class="key">Matched</td><td class="val">' + (c.matched || 0) + '/' + (c.total || 0) + '</td></tr>' +
    '</table>';

  renderStandardCard(container, 'Correlation Integrity', html, 'correlationIntegrity', cls2);
});

// ════════════════════════════════════════════════════════════════
// 8. Local Inference
// ════════════════════════════════════════════════════════════════
registerWidget('localInference', function(container, level) {
  var a = analytics();
  var l = (a && a.local_inference) || {};

  if (level === 'compact') {
    if (!l.available || !l.models) {
      renderCompactChip(container, 'Inference', function() {
        return { text: '\u2014', cls: '' };
      });
      return;
    }
    var running = 0;
    var total = 0;
    l.models.forEach(function(m) { if (m.status === 'running') running++; total++; });
    var text = running + '/' + total + ' running';
    var cls = running === total ? 'ok' : running > 0 ? 'warn' : '';
    renderCompactChip(container, 'Inference', function() {
      return { text: text, cls: cls };
    });
    return;
  }

  if (level === 'expanded') {
    var html = '<h3>Local Inference Status</h3>';
    if (!l.available || !l.models || !l.models.length) {
      html += '<p class="analytics-unavailable">No local inference data available.</p>';
    } else {
      html += '<table class="analytics-inference-table">' +
        '<thead><tr><th>Model</th><th>Status</th><th>Tokens/sec</th></tr></thead><tbody>';
      l.models.forEach(function(m) {
        var statusCls = m.status === 'running' ? 'analytics-status-running' : m.status === 'stopped' ? 'analytics-status-stopped' : 'analytics-status-error';
        var tps = m.tokens_per_sec != null ? m.tokens_per_sec.toFixed(1) : '\u2014';
        html += '<tr>' +
          '<td>' + escapeHtml(m.name || '\u2014') + '</td>' +
          '<td class="' + statusCls + '">' + escapeHtml(m.status || '\u2014') + '</td>' +
          '<td class="mono">' + tps + '</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
    }
    renderExpandedWidget(container, 'Local Inference', html);
    return;
  }

  if (!l.available || !l.models || !l.models.length) {
    renderStandardCard(container, 'Local Inference',
      '<span class="analytics-unavailable">Unavailable</span>', 'localInference');
    return;
  }

  var running2 = 0;
  l.models.forEach(function(m) { if (m.status === 'running') running2++; });
  var cls2 = running2 === l.models.length ? 'ok' : running2 > 0 ? 'warn' : '';

  var html = '<table class="analytics-inference-table">' +
    '<thead><tr><th>Model</th><th>Status</th></tr></thead><tbody>';
  l.models.slice(0, 4).forEach(function(m) {
    var statusCls = m.status === 'running' ? 'analytics-status-running' : m.status === 'stopped' ? 'analytics-status-stopped' : 'analytics-status-error';
    html += '<tr>' +
      '<td>' + escapeHtml(m.name || '\u2014') + '</td>' +
      '<td class="' + statusCls + '">' + escapeHtml(m.status || '\u2014') + '</td>' +
      '</tr>';
  });
  html += '</tbody></table>';

  renderStandardCard(container, 'Local Inference', html, 'localInference', cls2);
});
