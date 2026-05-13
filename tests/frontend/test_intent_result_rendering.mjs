// Test intent result rendering functions (app.js displayIntentResult helpers)
// Run: node tests/frontend/test_intent_result_rendering.mjs

// Replicate the rendering functions from app.js for testing
function escapeHtml(str) {
  if (typeof str !== 'string') return String(str);
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function row(key, value, cls) {
  const valStr = value === null || value === undefined ? '\u2014' : String(value);
  const clsAttr = cls ? ' class="' + cls + '"' : '';
  return '<tr><td class="k">' + escapeHtml(key) + '</td><td' + clsAttr + '>' + valStr + '</td></tr>';
}

function renderStructuredCard(kind, summary, result) {
  switch (kind) {
    case 'validation_suite':
      return renderValidationSuiteCard(summary);
    case 'storage_audit':
      return renderStorageAuditCard(summary);
    case 'report':
      return renderReportCard(summary);
    case 'packets':
      return renderPacketsCard(summary);
    case 'projection':
      return renderProjectionCard(summary);
    case 'checkpoint':
      return renderCheckpointCard(summary);
    case 'lease_cleanup':
      return renderLeaseCleanupCard(summary);
    case 'bundle_dry_run':
    case 'plan_dry_run':
    case 'validation':
    case 'chat_state':
    case 'authorization_receipt':
    case 'summary':
    default:
      return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  }
}

function renderValidationSuiteCard(summary) {
  const m = summary.match(/Validation suite '(.+?)':\s*(\w+)\.\s*(\d+)\s+executed,\s*(\d+)\s+skipped\.\s*Steps:\s*\[(.+?)\]\s*\.\s*sha256:\s*(\S+)/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Suite', m[1]) +
    row('Status', m[2]) +
    row('Executed', m[3]) +
    row('Skipped', m[4]) +
    row('Steps', m[5]) +
    row('SHA256', m[6]) +
    '</table>';
}

function renderStorageAuditCard(summary) {
  var m = summary.match(/Storage audit:\s*([\d.]+)\s*MB,\s*budget=(\w+),\s*stale_leases=(\d+),\s*rollup_candidates=(\d+),\s*prune_candidates=(\d+),\s*(\d+)\s*recommendations/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  var budgetCls = m[2] === 'ok' ? 'ok' : 'warning';
  return '<table class="kv">' +
    row('Total', m[1] + ' MB') +
    row('Budget', m[2], budgetCls) +
    row('Stale Leases', m[3]) +
    row('Rollup Candidates', m[4]) +
    row('Prune Candidates', m[5]) +
    row('Recommendations', m[6]) +
    '</table>';
}

function renderReportCard(summary) {
  var m = summary.match(/(\d+)\s+backlog items/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Backlog Items', m[1]) +
    row('Summary', summary) +
    '</table>';
}

function renderPacketsCard(summary) {
  var m = summary.match(/(\d+)\s+packets/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Packets Created', m[1]) +
    row('Mode', 'dry-run') +
    '</table>';
}

function renderProjectionCard(summary) {
  var m = summary.match(/(\d+)\/(\d+)\s+sources/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Sources', m[1] + ' / ' + m[2] + ' available') +
    '</table>';
}

function renderCheckpointCard(summary) {
  var m = summary.match(/committed:\s*(\S+)\.\s*(\d+)\s+files/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  var shaM = summary.match(/sha256:\s*(\S+)/);
  return '<table class="kv">' +
    row('Commit', m[1]) +
    row('Files', m[2]) +
    row('SHA256', shaM ? shaM[1] : '\u2014') +
    '</table>';
}

function renderLeaseCleanupCard(summary) {
  var m = summary.match(/archive:\s*(\w+)\.\s*(\d+)\s+entries/);
  if (!m) return '<div class="detail-line">' + escapeHtml(summary) + '</div>';
  return '<table class="kv">' +
    row('Action', m[1]) +
    row('Entries', m[2]) +
    '</table>';
}

// ── Tests ──────────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;

function assert(condition, name) {
  if (condition) {
    passed++;
  } else {
    failed++;
    console.error('FAIL:', name);
  }
}

// 1. validation_suite card renders correctly
const vsSummary = "Validation suite 'desktop_validation_suite': passed. 6 executed, 0 skipped. Steps: [ruff_check:passed; pyright:passed; storage_audit:passed]. sha256: abc123def456";
const vsHtml = renderValidationSuiteCard(vsSummary);
assert(vsHtml.includes('Suite'), 'vs includes Suite');
assert(vsHtml.includes('desktop_validation_suite'), 'vs includes suite name');
assert(vsHtml.includes('6'), 'vs includes executed count');
assert(vsHtml.includes('abc123def456'), 'vs includes sha256');

// 2. storage_audit card renders correctly
const saSummary = "Storage audit: 4.3 MB, budget=ok, stale_leases=3, rollup_candidates=9, prune_candidates=0, 3 recommendations.";
const saHtml = renderStorageAuditCard(saSummary);
assert(saHtml.includes('4.3 MB'), 'sa includes total');
assert(saHtml.includes('ok'), 'sa includes budget');
assert(saHtml.includes('>3<'), 'sa includes recommendations count');

// 3. refinement report card
const rpSummary = "Refinement report generated: 12 backlog items.";
const rpHtml = renderReportCard(rpSummary);
assert(rpHtml.includes('12'), 'report includes item count');

// 4. packets card
const pkSummary = "Refinement packets: 5 packets (dry-run).";
const pkHtml = renderPacketsCard(pkSummary);
assert(pkHtml.includes('5'), 'packets includes count');

// 5. projection card
const pjSummary = "Projection rebuilt: 3/6 sources available.";
const pjHtml = renderProjectionCard(pjSummary);
assert(pjHtml.includes('3 / 6'), 'projection includes sources');

// 6. checkpoint card
const cpSummary = "Checkpoint committed: abcdef123456. 4 files. sha256: sha256:xyz789";
const cpHtml = renderCheckpointCard(cpSummary);
assert(cpHtml.includes('abcdef123456'), 'checkpoint includes commit sha');
assert(cpHtml.includes('4'), 'checkpoint includes file count');

// 7. lease_cleanup card
const lcSummary = "Lease cleanup archive: archive. 15 entries processed.";
const lcHtml = renderLeaseCleanupCard(lcSummary);
assert(lcHtml.includes('archive'), 'lease includes action');
assert(lcHtml.includes('15'), 'lease includes entry count');

// 8. renderStructuredCard dispatches correctly
const validationResult = renderStructuredCard('validation_suite', vsSummary, {});
assert(validationResult.includes('Suite'), 'dispatch validation_suite works');

const auditResult = renderStructuredCard('storage_audit', saSummary, {});
assert(auditResult.includes('Total'), 'dispatch storage_audit works');

const summaryResult = renderStructuredCard('chat_state', 'Chat state: 5 messages.', {});
assert(summaryResult.includes('Chat state: 5 messages.'), 'dispatch unknown uses default');

// 9. Fallback for unknown renderer
const unknownResult = renderStructuredCard('unknown_kind', 'Some summary text.', {});
assert(unknownResult.includes('detail-line'), 'unknown kind falls back to detail-line');
assert(unknownResult.includes('Some summary text.'), 'unknown kind shows summary');

// 10. Unparseable summary falls back to detail-line
const badSummary = 'Some completely different format string';
const fallback = renderValidationSuiteCard(badSummary);
assert(fallback.includes('detail-line'), 'unparseable summary falls back');
assert(fallback.includes(badSummary), 'unparseable summary shows raw text');

// Summary
console.log(`\nResults: ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
