// Rig Relay — Keyboard Navigation (WAI-ARIA Tab Panel Pattern)
// ───────────────────────────────────────────────────────────────
// Owner: frontend/desktop/js/keyboardNav.js
// Safety: Only mutates DOM focus/aria attributes, never injects content.
//
// Implements WAI-ARIA Design Pattern for Tabs:
// https://www.w3.org/WAI/ARIA/apg/patterns/tabs/
//
// Arrow keys navigate between tabs. Tab key moves focus from the active
// tab into the active tabpanel. Shift+Tab returns to the tab list.

// ── Surface tab navigation ──────────────────────────────────────────

function _getSurfaceTabs() {
  return document.querySelectorAll('#surface-nav .surface-tab[role="tab"]');
}

function _getActiveSurfaceTab() {
  var tabs = _getSurfaceTabs();
  for (var i = 0; i < tabs.length; i++) {
    if (tabs[i].classList.contains('active')) return tabs[i];
  }
  return tabs[0];
}

function _activateSurfaceTab(tab) {
  if (!tab) return;
  var tabs = _getSurfaceTabs();
  for (var i = 0; i < tabs.length; i++) {
    var isTarget = tabs[i] === tab;
    tabs[i].classList.toggle('active', isTarget);
    tabs[i].setAttribute('aria-selected', String(isTarget));
    tabs[i].setAttribute('tabindex', isTarget ? '0' : '-1');
  }
  tab.focus();
  // Trigger surface switch via the existing handler
  var surfaceId = tab.getAttribute('data-surface');
  if (surfaceId && typeof window.RigRelay !== 'undefined' && typeof window.RigRelay.switchSurface === 'function') {
    window.RigRelay.switchSurface(surfaceId);
  }
}

function _focusAdjacentSurfaceTab(direction) {
  var tabs = Array.from(_getSurfaceTabs());
  if (tabs.length === 0) return;
  var activeIdx = -1;
  for (var i = 0; i < tabs.length; i++) {
    if (tabs[i].classList.contains('active')) { activeIdx = i; break; }
  }
  if (activeIdx === -1) { _activateSurfaceTab(tabs[0]); return; }
  var nextIdx;
  if (direction === 'next') {
    nextIdx = (activeIdx + 1) % tabs.length;
  } else {
    nextIdx = (activeIdx - 1 + tabs.length) % tabs.length;
  }
  _activateSurfaceTab(tabs[nextIdx]);
}

// ── Mode tab navigation ─────────────────────────────────────────────

function _getModeTabs() {
  return document.querySelectorAll('#mode-bar .mode-option[role="tab"]');
}

function _getActiveModeTab() {
  var tabs = _getModeTabs();
  for (var i = 0; i < tabs.length; i++) {
    if (tabs[i].classList.contains('active')) return tabs[i];
  }
  return tabs[0];
}

function _activateModeTab(tab) {
  if (!tab) return;
  var tabs = _getModeTabs();
  for (var i = 0; i < tabs.length; i++) {
    var isTarget = tabs[i] === tab;
    tabs[i].classList.toggle('active', isTarget);
    tabs[i].setAttribute('aria-selected', String(isTarget));
    tabs[i].setAttribute('tabindex', isTarget ? '0' : '-1');
  }
  tab.focus();
  // Trigger mode switch
  var mode = tab.getAttribute('data-mode');
  if (mode && typeof window.RigRelay !== 'undefined' && typeof window.RigRelay.switchMode === 'function') {
    window.RigRelay.switchMode(mode);
  }
}

function _focusAdjacentModeTab(direction) {
  var tabs = Array.from(_getModeTabs());
  if (tabs.length === 0) return;
  var activeIdx = -1;
  for (var i = 0; i < tabs.length; i++) {
    if (tabs[i].classList.contains('active')) { activeIdx = i; break; }
  }
  if (activeIdx === -1) { _activateModeTab(tabs[0]); return; }
  var nextIdx;
  if (direction === 'next') {
    nextIdx = (activeIdx + 1) % tabs.length;
  } else {
    nextIdx = (activeIdx - 1 + tabs.length) % tabs.length;
  }
  _activateModeTab(tabs[nextIdx]);
}

// ── Setup ────────────────────────────────────────────────────────────

function setupKeyboardNavigation() {
  // Surface tabs: arrow keys navigate, Enter/Space activate
  document.getElementById('surface-nav').addEventListener('keydown', function(e) {
    var target = e.target;
    if (!target.classList.contains('surface-tab') || target.getAttribute('role') !== 'tab') return;

    switch (e.key) {
      case 'ArrowRight':
        e.preventDefault();
        _focusAdjacentSurfaceTab('next');
        break;
      case 'ArrowLeft':
        e.preventDefault();
        _focusAdjacentSurfaceTab('prev');
        break;
      case 'Home':
        e.preventDefault();
        var allTabs = _getSurfaceTabs();
        if (allTabs.length > 0) _activateSurfaceTab(allTabs[0]);
        break;
      case 'End':
        e.preventDefault();
        var endTabs = _getSurfaceTabs();
        if (endTabs.length > 0) _activateSurfaceTab(endTabs[endTabs.length - 1]);
        break;
      case 'Enter':
      case ' ':
        e.preventDefault();
        _activateSurfaceTab(target);
        break;
    }
  });

  // Surface tabs: click to activate (ARIA requires explicit activation)
  document.getElementById('surface-nav').addEventListener('click', function(e) {
    var tab = e.target.closest('.surface-tab[role="tab"]');
    if (!tab) return;
    _activateSurfaceTab(tab);
  });

  // Mode tabs: same pattern
  var modeBar = document.getElementById('mode-bar');
  if (modeBar) {
    modeBar.addEventListener('keydown', function(e) {
      var target = e.target;
      if (!target.classList.contains('mode-option') || target.getAttribute('role') !== 'tab') return;

      switch (e.key) {
        case 'ArrowRight':
          e.preventDefault();
          _focusAdjacentModeTab('next');
          break;
        case 'ArrowLeft':
          e.preventDefault();
          _focusAdjacentModeTab('prev');
          break;
        case 'Home':
          e.preventDefault();
          var allTabs = _getModeTabs();
          if (allTabs.length > 0) _activateModeTab(allTabs[0]);
          break;
        case 'End':
          e.preventDefault();
          var endTabs = _getModeTabs();
          if (endTabs.length > 0) _activateModeTab(endTabs[endTabs.length - 1]);
          break;
        case 'Enter':
        case ' ':
          e.preventDefault();
          _activateModeTab(target);
          break;
      }
    });

    modeBar.addEventListener('click', function(e) {
      var tab = e.target.closest('.mode-option[role="tab"]');
      if (!tab) return;
      _activateModeTab(tab);
    });
  }

  // Initialize tabindex for all tab groups (only active tab has tabindex=0)
  _initTabIndexes('#surface-nav .surface-tab[role="tab"]', '.active');
  _initTabIndexes('#mode-bar .mode-option[role="tab"]', '.active');

  // Focus management: when switching surfaces, focus the active tabpanel
  document.addEventListener('surface-switched', function(e) {
    var surfaceId = e.detail && e.detail.surfaceId;
    if (surfaceId) {
      // Move focus to the first focusable element in the tabpanel, or the tabpanel itself
      var panel = document.getElementById('surface-' + surfaceId);
      if (panel) {
        var focusable = panel.querySelector('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])');
        if (focusable) {
          setTimeout(function() { focusable.focus(); }, 50);
        }
      }
    }
  });

  return { ok: true };
}

function _initTabIndexes(selector, activeSelector) {
  var tabs = document.querySelectorAll(selector);
  for (var i = 0; i < tabs.length; i++) {
    var isActive = tabs[i].matches(activeSelector);
    tabs[i].setAttribute('tabindex', isActive ? '0' : '-1');
  }
}

// Expose for tests
function _testGetSurfaceTabs() { return _getSurfaceTabs(); }
function _testGetModeTabs() { return _getModeTabs(); }

export { setupKeyboardNavigation, _testGetSurfaceTabs, _testGetModeTabs,
         _activateSurfaceTab, _focusAdjacentSurfaceTab,
         _activateModeTab, _focusAdjacentModeTab };
