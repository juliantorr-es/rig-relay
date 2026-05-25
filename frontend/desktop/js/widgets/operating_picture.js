// Operating Picture Widget — Slice 1A
// Renders repository preview operating picture from projection data.

(function() {
  'use strict';

  const OperatingPictureWidget = {
    name: 'operating_picture',
    container: null,

    init: function(containerId) {
      this.container = document.getElementById(containerId || 'widget-operating-picture');
    },

    render: function(projection) {
      if (!this.container) return;
      
      const op = projection.operating_picture;
      if (!op || !op.available) {
        this._renderEmpty();
        return;
      }

      const data = op.picture || op;
      const repo = data.repository || {};
      const dirty = data.dirty_state || {};
      const ecosystems = data.detected_ecosystems || [];
      const commands = data.detected_commands || [];
      const instructions = data.instruction_files || [];
      const topology = data.topology || [];
      const mission = data.mission_proposal || {};
      const recs = data.recommendations || [];

      let html = '<div class="operating-picture-widget">';
      
      // Repository header
      const repoName = (repo.root_path || '').split('/').pop() || 'Unknown';
      const branch = repo.branch || 'unknown';
      const dirtyTotal = (dirty.modified || 0) + (dirty.staged || 0) + 
                         (dirty.untracked || 0) + (dirty.deleted || 0);
      
      html += '<div class="op-header">';
      html += '<h3 class="op-repo-name">' + escapeHtml(repoName) + '</h3>';
      html += '<span class="op-git-badge">git: ' + escapeHtml(branch) + '</span>';
      if (dirtyTotal > 0) {
        html += '<span class="op-dirty-badge">' + dirtyTotal + ' files dirty</span>';
      } else {
        html += '<span class="op-clean-badge">clean</span>';
      }
      html += '</div>';

      // Ecosystems
      if (ecosystems.length > 0) {
        html += '<div class="op-section">';
        html += '<h4>Ecosystems</h4>';
        html += '<div class="op-tags">';
        for (const eco of ecosystems) {
          const conf = eco.confidence === 'definite' ? 'op-tag-definite' : 'op-tag-inferred';
          html += '<span class="op-tag ' + conf + '">' + escapeHtml(eco.language);
          if (eco.package_manager) {
            html += ' · ' + escapeHtml(eco.package_manager);
          }
          html += '</span>';
        }
        html += '</div></div>';
      }

      // Commands
      if (commands.length > 0) {
        html += '<div class="op-section">';
        html += '<h4>Detected Commands</h4>';
        html += '<ul class="op-cmd-list">';
        for (const cmd of commands.slice(0, 8)) {
          const safetyClass = cmd.safety_classification === 'read_only_validation' ? 
            'op-cmd-safe' : 'op-cmd-warn';
          html += '<li class="' + safetyClass + '">' +
            '<span class="op-cmd-kind">[' + escapeHtml(cmd.kind) + ']</span> ' +
            escapeHtml(cmd.command) + '</li>';
        }
        if (commands.length > 8) {
          html += '<li class="op-cmd-more">+ ' + (commands.length - 8) + ' more</li>';
        }
        html += '</ul></div>';
      }

      // Instructions
      if (instructions.length > 0) {
        html += '<div class="op-section">';
        html += '<h4>Instructions</h4>';
        html += '<div class="op-tags">';
        for (const inst of instructions.slice(0, 6)) {
          html += '<span class="op-tag">' + escapeHtml(inst.scope.kind) + '</span>';
        }
        html += '</div></div>';
      }

      // Topology
      if (topology.length > 0) {
        const kinds = {};
        for (const t of topology) {
          kinds[t.kind] = (kinds[t.kind] || 0) + 1;
        }
        html += '<div class="op-section">';
        html += '<h4>Topology</h4>';
        html += '<div class="op-topo-grid">';
        for (const [kind, count] of Object.entries(kinds)) {
          html += '<span class="op-topo-item">' + escapeHtml(kind) + ': ' + count + '</span>';
        }
        html += '</div></div>';
      }

      // Mission proposal summary
      if (mission.source_candidates && mission.source_candidates.length > 0) {
        html += '<div class="op-section">';
        html += '<h4>Mission Candidates</h4>';
        html += '<div class="op-tags">';
        for (const src of mission.source_candidates.slice(0, 4)) {
          html += '<span class="op-tag op-tag-source">' + escapeHtml(src) + '</span>';
        }
        html += '</div>';
        html += '<button class="op-propose-btn" disabled>Propose Mission (coming soon)</button>';
        html += '</div>';
      }

      // Recommendations
      if (recs.length > 0) {
        html += '<div class="op-section">';
        html += '<h4>Recommendations</h4>';
        html += '<ul class="op-rec-list">';
        for (const rec of recs.slice(0, 3)) {
          html += '<li>' + escapeHtml(rec) + '</li>';
        }
        html += '</ul></div>';
      }

      html += '</div>';
      this.container.innerHTML = html;
    },

    _renderEmpty: function() {
      if (!this.container) return;
      this.container.innerHTML = '' +
        '<div class="operating-picture-empty">' +
        '<p>No repository opened.</p>' +
        '<p class="op-empty-hint">Select Open Local Repository to begin.</p>' +
        '</div>';
    }
  };

  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Export
  if (typeof window !== 'undefined') {
    window.RigRelay = window.RigRelay || {};
    window.RigRelay.widgets = window.RigRelay.widgets || {};
    window.RigRelay.widgets.operatingPicture = OperatingPictureWidget;
  }
})();
