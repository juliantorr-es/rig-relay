/**
 * Rig Relay static documentation site — progressive enhancement JS.
 *
 * Features:
 *  - Client-side search over docs/search-index.json
 *  - Audience/disclosure level controls
 *  - Expand/collapse all details
 *  - Copy link to section (headings)
 *
 * No framework. No remote CDNs. No tracking. No eval.
 * All core navigation and content work without JS.
 */

(() => {
	var BASE_PATH = document.querySelector('meta[name="base-path"]')
		? document.querySelector('meta[name="base-path"]').content
		: "/rig-relay";
	var RELATIVE_ROOT = document.querySelector('meta[name="relative-root"]')
		? document.querySelector('meta[name="relative-root"]').content
		: ".";
	var SEARCH_INDEX_URL = RELATIVE_ROOT + "/search-index.json";
	var searchData = null;
	var searchLoading = false;

	// ── DOM ready ────────────────────────────────────────────────
	function ready(fn) {
		if (document.readyState !== "loading") {
			fn();
		} else {
			document.addEventListener("DOMContentLoaded", fn);
		}
	}

	// ── Search ───────────────────────────────────────────────────
	function initSearch() {
		var container = document.getElementById("site-search");
		if (!container) return;

		var input = document.createElement("input");
		input.type = "search";
		input.placeholder = "Search documentation…";
		input.setAttribute("aria-label", "Search documentation");
		input.className = "search-input";
		container.appendChild(input);

		var results = document.createElement("div");
		results.id = "search-results";
		results.className = "search-results";
		results.setAttribute("role", "region");
		results.setAttribute("aria-live", "polite");
		results.setAttribute("aria-label", "Search results");
		container.appendChild(results);

		var debounce;
		input.addEventListener("input", () => {
			clearTimeout(debounce);
			var q = input.value.trim();
			if (q.length < 2) {
				results.innerHTML = "";
				return;
			}
			debounce = setTimeout(() => {
				doSearch(q, results);
			}, 200);
		});
	}

	function loadSearchIndex(cb) {
		if (searchData) {
			cb(searchData);
			return;
		}
		if (searchLoading) {
			setTimeout(() => {
				loadSearchIndex(cb);
			}, 100);
			return;
		}
		searchLoading = true;
		var xhr = new XMLHttpRequest();
		xhr.open("GET", SEARCH_INDEX_URL, true);
		xhr.onload = () => {
			if (xhr.status === 200) {
				try {
					searchData = JSON.parse(xhr.responseText);
				} catch (e) {
					searchData = [];
				}
			} else {
				searchData = [];
			}
			searchLoading = false;
			cb(searchData);
		};
		xhr.onerror = () => {
			searchData = [];
			searchLoading = false;
			cb(searchData);
		};
		xhr.send();
	}

	function doSearch(query, resultsEl) {
		loadSearchIndex((data) => {
			var q = query.toLowerCase();
			var matches = [];
			for (var i = 0; i < data.length; i++) {
				var doc = data[i];
				var score = 0;
				if (doc.title && doc.title.toLowerCase().indexOf(q) !== -1) score += 3;
				if (doc.summary && doc.summary.toLowerCase().indexOf(q) !== -1)
					score += 1;
				if (doc.tags) {
					for (var j = 0; j < doc.tags.length; j++) {
						if (doc.tags[j].toLowerCase().indexOf(q) !== -1) score += 1;
					}
				}
				if (score > 0) matches.push({ doc: doc, score: score });
			}
			matches.sort((a, b) => b.score - a.score);
			var top = matches.slice(0, 15);
			if (top.length === 0) {
				resultsEl.innerHTML =
					'<p class="search-empty">No results found for "' +
					escapeHtml(query) +
					'"</p>';
				return;
			}
			var html = '<ul class="search-list">';
			for (var k = 0; k < top.length; k++) {
				var m = top[k];
				var href = RELATIVE_ROOT + "/pages/" + m.doc.document_id + ".html";
				html +=
					'<li><a href="' +
					href +
					'"><strong>' +
					escapeHtml(m.doc.title) +
					"</strong></a>";
				if (m.doc.summary) {
					html +=
						' <span class="search-snippet">' +
						escapeHtml(m.doc.summary.substring(0, 120)) +
						"</span>";
				}
				html += "</li>";
			}
			html += "</ul>";
			resultsEl.innerHTML = html;
		});
	}

	function escapeHtml(text) {
		var d = document.createElement("div");
		d.appendChild(document.createTextNode(text));
		return d.innerHTML;
	}

	// ── Disclosure / audience controls ───────────────────────────
	function initDisclosureControls() {
		var bar = document.querySelector(".disclosure-controls");
		if (!bar) return;

		var modes = [
			{ key: "summary", label: "Summary" },
			{ key: "standard", label: "Standard" },
			{ key: "detailed", label: "Detailed" },
		];

		for (var i = 0; i < modes.length; i++) {
			var btn = document.createElement("button");
			btn.textContent = modes[i].label;
			btn.setAttribute("aria-pressed", "false");
			btn.setAttribute("data-mode", modes[i].key);
			btn.className = "disclosure-btn";
			btn.addEventListener("click", function () {
				applyDisclosureMode(this.getAttribute("data-mode"));
				updateDisclosureButtons(bar, this.getAttribute("data-mode"));
			});
			bar.appendChild(btn);
		}
		updateDisclosureButtons(bar, "standard");
	}

	function applyDisclosureMode(mode) {
		var blocks = document.querySelectorAll("[data-disclosure-level]");
		for (var i = 0; i < blocks.length; i++) {
			var level = blocks[i].getAttribute("data-disclosure-level");
			var visible = levelOrder(level) <= levelOrder(mode);
			blocks[i].style.display = visible ? "" : "none";
		}
	}

	function levelOrder(level) {
		if (level === "summary") return 0;
		if (level === "standard") return 1;
		if (level === "detailed") return 2;
		return 3;
	}

	function updateDisclosureButtons(bar, active) {
		var btns = bar.querySelectorAll(".disclosure-btn");
		for (var i = 0; i < btns.length; i++) {
			btns[i].setAttribute(
				"aria-pressed",
				btns[i].getAttribute("data-mode") === active ? "true" : "false",
			);
		}
	}

	
  // ── Persist disclosure mode ─────────────────────────────────
  var DISCLOSURE_STORAGE_KEY = "rig-relay-disclosure-mode";

  function saveDisclosureMode(mode) {
    try { localStorage.setItem(DISCLOSURE_STORAGE_KEY, mode); } catch (e) {}
  }

  function loadDisclosureMode() {
    try { return localStorage.getItem(DISCLOSURE_STORAGE_KEY) || "standard"; } catch (e) { return "standard"; }
  }

  // Override applyDisclosureMode to also save
  var _origApplyDisclosure = applyDisclosureMode;
  applyDisclosureMode = function(mode) {
    _origApplyDisclosure(mode);
    saveDisclosureMode(mode);
  };

// ── Expand / collapse all ────────────────────────────────────
	function initExpandCollapse() {
		var container = document.querySelector(".expand-collapse-controls");
		if (!container) return;

		var expandBtn = document.createElement("button");
		expandBtn.textContent = "Expand all";
		expandBtn.className = "expand-btn";
		expandBtn.setAttribute("aria-label", "Expand all collapsible sections");
		expandBtn.addEventListener("click", () => {
			toggleAllDetails(true);
		});
		container.appendChild(expandBtn);

		var collapseBtn = document.createElement("button");
		collapseBtn.textContent = "Collapse all";
		collapseBtn.className = "collapse-btn";
		collapseBtn.setAttribute("aria-label", "Collapse all sections");
		collapseBtn.addEventListener("click", () => {
			toggleAllDetails(false);
		});
		container.appendChild(collapseBtn);
	}

	function toggleAllDetails(open) {
		var details = document.querySelectorAll("details.disclosure-collapsible");
		for (var i = 0; i < details.length; i++) {
			details[i].open = open;
		}
	}

	// ── Copy section link ────────────────────────────────────────
	function initCopyLinks() {
		var headings = document.querySelectorAll(
			"h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]",
		);
		for (var i = 0; i < headings.length; i++) {
			var h = headings[i];
			var btn = document.createElement("button");
			btn.className = "copy-link-btn";
			btn.setAttribute("aria-label", "Copy link to section: " + h.textContent);
			btn.innerHTML = "#";
			btn.addEventListener("click", function (e) {
				var id = this.parentElement.id;
				var url = window.location.origin + window.location.pathname + "#" + id;
				copyToClipboard(url, this);
			});
			h.appendChild(btn);
		}
	}

	function copyToClipboard(text, btn) {
		if (navigator.clipboard && navigator.clipboard.writeText) {
			navigator.clipboard.writeText(text).then(
				() => {
					flashButton(btn, "Copied!");
				},
				() => {
					fallbackCopy(text, btn);
				},
			);
		} else {
			fallbackCopy(text, btn);
		}
	}

	function fallbackCopy(text, btn) {
		var ta = document.createElement("textarea");
		ta.value = text;
		ta.style.position = "fixed";
		ta.style.opacity = "0";
		document.body.appendChild(ta);
		ta.select();
		try {
			document.execCommand("copy");
			flashButton(btn, "Copied!");
		} catch (e) {
			flashButton(btn, "Failed");
		}
		document.body.removeChild(ta);
	}

	function flashButton(btn, msg) {
		var original = btn.textContent;
		btn.textContent = msg;
		setTimeout(() => {
			btn.textContent = original;
		}, 1500);
	}

	// ── Init ─────────────────────────────────────────────────────
	ready(() => {
		initSearch();
		initDisclosureControls();
		initExpandCollapse();
		initCopyLinks();
	});
})();
