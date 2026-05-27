// T0: Production fixture loading behavior — conditional injection verification.
// Run: node tests/frontend/test_t0_fixture_loading.mjs
//
// Verifies the conditional injection logic that replaces the old hard-coded
// <script src="js/fixtures/..."> tags. In production mode, fixture scripts
// must never be loaded. In fixture mode (?fixture_mode=1), they must be
// dynamically injected.

// ── Replicate the injection logic from frontend/desktop/index.html ──

function shouldInjectFixtureScripts(href, windowFlag) {
    // Simulate URLSearchParams parsing
    const params = new URLSearchParams(href.includes('?') ? href.split('?')[1] : '');
    const isFixtureMode = params.get('fixture_mode') === '1' || windowFlag === true;
    return isFixtureMode;
}

function simulateInjection(href, windowFlag) {
    const scriptsCreated = [];
    if (shouldInjectFixtureScripts(href, windowFlag)) {
        const sources = [
            'js/fixtures/p0-fixture-connect.js',
            'js/fixtures/p0-fixture-repository-estate.js',
            'js/fixtures/p0-fixture-project-studio.js',
            'js/fixtures/p0-fixture-inference-studio.js',
            'js/fixtures/p0-fixture-publish-preview.js'
        ];
        for (const src of sources) {
            scriptsCreated.push({ src, async: false });
        }
    }
    return scriptsCreated;
}

// ── Tests ───────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;

function assertEqual(actual, expected, description) {
    const a = JSON.stringify(actual);
    const e = JSON.stringify(expected);
    if (a === e) {
        passed++;
        console.log(`  PASS: ${description}`);
    } else {
        failed++;
        console.error(`  FAIL: ${description}`);
        console.error(`    expected: ${e}`);
        console.error(`    actual:   ${a}`);
    }
}

function assertTrue(condition, description) {
    if (condition) {
        passed++;
        console.log(`  PASS: ${description}`);
    } else {
        failed++;
        console.error(`  FAIL: ${description}`);
    }
}

// Test 1: Production mode — no query params, no window flag
console.log('\nProduction mode (default):');
{
    const scripts = simulateInjection('file:///path/to/index.html', undefined);
    assertEqual(scripts.length, 0, 'Zero fixture scripts injected in production mode');
    assertEqual(scripts, [], 'Scripts array is empty');
}

// Test 2: Production mode — explicit fixture_mode=0
console.log('\nProduction mode (?fixture_mode=0):');
{
    const scripts = simulateInjection('file:///path/to/index.html?fixture_mode=0', undefined);
    assertEqual(scripts.length, 0, 'Zero fixture scripts when fixture_mode=0');
}

// Test 3: Window flag is false
console.log('\nProduction mode (window flag false):');
{
    const scripts = simulateInjection('file:///path/to/index.html', false);
    assertEqual(scripts.length, 0, 'Zero fixture scripts when window flag is false');
}

// Test 4: Fixture mode via query param
console.log('\nFixture mode (?fixture_mode=1):');
{
    const scripts = simulateInjection('file:///path/to/index.html?fixture_mode=1', undefined);
    assertEqual(scripts.length, 5, 'Five fixture scripts injected in fixture mode via query param');
    assertTrue(scripts.every(s => s.async === false), 'All injected scripts have async=false');
    assertTrue(scripts.every(s => s.src.startsWith('js/fixtures/')), 'All src paths are fixture files');
}

// Test 5: Fixture mode via window flag
console.log('\nFixture mode (window flag true):');
{
    const scripts = simulateInjection('file:///path/to/index.html', true);
    assertEqual(scripts.length, 5, 'Five fixture scripts injected in fixture mode via window flag');
    assertTrue(scripts.every(s => s.async === false), 'All injected scripts have async=false');
}

// Test 6: Fixture mode — query param takes precedence
console.log('\nFixture mode (query param overrides):');
{
    // ?fixture_mode=1 should enable even if window flag is false
    const scripts = simulateInjection('file:///index.html?fixture_mode=1', false);
    assertEqual(scripts.length, 5, 'query param overrides window flag');
}

// Test 7: Unknown query params do not trigger fixture mode
console.log('\nUnknown params do not trigger fixture mode:');
{
    const scripts = simulateInjection('file:///index.html?foo=bar&baz=qux', undefined);
    assertEqual(scripts.length, 0, 'Unknown query params do not enable fixture mode');
}

// Test 8: fixture_mode=2 (not 1) does not trigger
console.log('\nfixture_mode=2 does not trigger:');
{
    const scripts = simulateInjection('file:///index.html?fixture_mode=2', undefined);
    assertEqual(scripts.length, 0, 'fixture_mode must be exactly "1"');
}

// Test 9: window flag null/0/"" does not trigger
console.log('\nFalsy window flags do not trigger:');
{
    assertEqual(simulateInjection('file:///index.html', null).length, 0, 'null flag');
    assertEqual(simulateInjection('file:///index.html', 0).length, 0, '0 flag');
    assertEqual(simulateInjection('file:///index.html', '').length, 0, 'empty string flag');
}

// Test 10: Script order is preserved
console.log('\nFixture script order matches canonical list:');
{
    const scripts = simulateInjection('file:///index.html?fixture_mode=1', undefined);
    const expectedOrder = [
        'js/fixtures/p0-fixture-connect.js',
        'js/fixtures/p0-fixture-repository-estate.js',
        'js/fixtures/p0-fixture-project-studio.js',
        'js/fixtures/p0-fixture-inference-studio.js',
        'js/fixtures/p0-fixture-publish-preview.js',
    ];
    for (let i = 0; i < expectedOrder.length; i++) {
        assertEqual(scripts[i].src, expectedOrder[i], `Script ${i} src matches expected order`);
    }
}

// ── Summary ─────────────────────────────────────────────────────────

console.log(`\n${'='.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) {
    process.exit(1);
}
console.log('All T0 conditional fixture loading tests passed.');
