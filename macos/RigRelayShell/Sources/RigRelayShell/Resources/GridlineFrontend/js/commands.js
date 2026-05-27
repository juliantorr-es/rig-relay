// Rig Relay — Commands
// Slash command registry and autocomplete

import { dispatchIntent, clearChat, cancelChat, sendChatMessage } from './chat.js';
import { sendMessage } from './transport.js';
import { el } from './utils.js';
import { state } from './state.js';

// Command table: prefix -> { execute, help, category }
const COMMANDS = {
  '/clear': {
    execute: function() { clearChat(); },
    help: 'Clear the chat transcript',
    category: 'Chat',
  },
  '/cancel': {
    execute: function() { cancelChat(); },
    help: 'Cancel the active agent turn',
    category: 'Chat',
  },
  '/mode': {
    execute: function(args) {
      if (!args || !['operator','review','system','technical'].includes(args)) {
        return 'Usage: /mode <operator|review|system|technical>';
      }
      // Switch mode via DOM click on the mode button
      const btn = document.querySelector('.mode-option[data-mode="' + args + '"]');
      if (btn) btn.click();
      else return 'Mode "' + args + '" not found.';
      return null;
    },
    help: 'Switch layout mode. Usage: /mode <operator|review|system|technical>',
    category: 'Layout',
  },
  '/intent': {
    execute: function(args) {
      if (!args) return 'Usage: /intent <name> [param=value ...]';
      const parts = args.split(/\s+/);
      const name = parts[0];
      const params = {};
      for (let i = 1; i < parts.length; i++) {
        const kv = parts[i].split('=');
        if (kv.length === 2) params[kv[0]] = kv[1];
      }
      dispatchIntent(name, params);
      return 'Dispatched intent: ' + name;
    },
    help: 'Dispatch a desktop intent. Usage: /intent <name> [key=value ...]',
    category: 'Actions',
  },
  '/projection': {
    execute: function() {
      const sent = sendMessage({ type: 'get_projection' });
      return sent ? null : 'WebSocket not connected.';
    },
    help: 'Request a fresh projection',
    category: 'Actions',
  },
  '/refresh': {
    execute: function() { dispatchIntent('refresh_projection'); return null; },
    help: 'Refresh the projection data',
    category: 'Actions',
  },
  '/validate': {
    execute: function() { dispatchIntent('run_validation_suite'); return null; },
    help: 'Run the validation suite',
    category: 'Actions',
  },
  '/audit': {
    execute: function() { dispatchIntent('run_storage_audit'); return null; },
    help: 'Run a storage audit',
    category: 'Actions',
  },
  '/worktree': {
    execute: function(args) {
      if (!args) return 'Usage: /worktree <list|create|remove> [workspace_id] [branch_name]';
      const parts = args.split(/\s+/);
      const sub = parts[0];
      if (sub === 'list') { dispatchIntent('worktree_list'); return null; }
      if (sub === 'create') {
        if (parts.length < 3) return 'Usage: /worktree create <workspace_id> <branch_name>';
        dispatchIntent('worktree_create', { workspace_id: parts[1], branch_name: parts[2] });
        return null;
      }
      if (sub === 'remove') {
        if (parts.length < 2) return 'Usage: /worktree remove <workspace_id>';
        dispatchIntent('worktree_remove', { workspace_id: parts[1] });
        return null;
      }
      return 'Unknown subcommand: ' + sub + '. Use list, create, or remove.';
    },
    help: 'Manage git worktrees. /worktree <list|create|remove> ...',
    category: 'Workspace',
  },
  '/init': {
    execute: function(args) {
      dispatchIntent('workspace_init', { workspace_id: args || '' });
      return null;
    },
    help: 'Bootstrap workspace. Checks git state, suggests worktree. /init [workspace_id]',
    category: 'Workspace',
  },
  '/fleet': {
    execute: function(args) {
      if (!args || args === 'queue') { dispatchIntent('fleet_queue_snapshot'); return null; }
      if (args === 'plan') { dispatchIntent('run_queue_plan_dry_run'); return null; }
      if (args === 'spawn') { dispatchIntent('run_spawn_plan_dry_run'); return null; }
      if (args === 'run') { dispatchIntent('fleet_orchestrate'); return null; }
      return 'Usage: /fleet <queue|plan|spawn|run>';
    },
    help: 'Fleet operations. /fleet <queue|plan|spawn|run>',
    category: 'Fleet',
  },
  '/orchestrator': {
    execute: function() {
      // The orchestrator agent is activated via agent profile switch.
      // When the user types /orchestrator, we tell them to use the
      // backend agent command or start a conversation about the roadmap.
      return 'Orchestrator agent ready. Tell me about your project:\n' +
        '  • What do you want to build? (scope)\n' +
        '  • What stack should be used?\n' +
        '  • New project or existing codebase?\n' +
        '  • How many sprints?';
    },
    help: 'Start a roadmap conversation with the fleet orchestrator',
    category: 'Fleet',
  },
  '/provider': {
    execute: function(args) {
      var valid = ['chatgpt','claude','gemini','deepseek','mistral','perplexity','copilot'];
      if (!args || valid.indexOf(args) < 0) {
        return 'Usage: /provider <chatgpt|claude|gemini|deepseek|mistral|perplexity|copilot>\n'
          + 'Opens the provider web app in your browser.';
      }
      if (window.pywebview && window.pywebview.api && window.pywebview.api.open_provider_web) {
        window.pywebview.api.open_provider_web(args);
        return 'Opening ' + args + ' in your browser...';
      }
      return args + ' web app: open in your browser manually.';
    },
    help: 'Open a provider web app. /provider <chatgpt|claude|gemini|deepseek|mistral|perplexity|copilot>',
    category: 'Providers',
  },
  '/send_to': {
    execute: function(args) {
      var valid = ['chatgpt','claude','gemini','deepseek','mistral','perplexity'];
      if (!args || valid.indexOf(args) < 0) {
        return 'Usage: /send_to <chatgpt|claude|gemini|deepseek|mistral|perplexity>';
      }
      window.RigRelay.sendToProvider(args);
      return 'Sent to ' + args + '.';
    },
    help: 'Push chat text to a provider companion window. /send_to <provider>',
    category: 'Providers',
  },
  '/read_from': {
    execute: function(args) {
      var valid = ['chatgpt','claude','gemini','deepseek','mistral','perplexity'];
      if (!args || valid.indexOf(args) < 0) {
        return 'Usage: /read_from <chatgpt|claude|gemini|deepseek|mistral|perplexity>';
      }
      window.RigRelay.readFromProvider(args);
      return null;
    },
    help: 'Read response from a provider companion window. /read_from <provider>',
    category: 'Providers',
  },
  '/council': {
    execute: function(args) {
      dispatchIntent('council_consult', { question: args || '' });
      return 'Council: sending structured consultation to all open provider windows...';
    },
    help: 'Send structured consultation to all open providers. /council [question]',
    category: 'Providers',
  },
  '/help': {
    execute: function() {
      let out = '';
      const cats = {};
      for (const [cmd, def] of Object.entries(COMMANDS)) {
        if (cmd === '/help') continue;
        const cat = def.category || 'Other';
        if (!cats[cat]) cats[cat] = [];
        cats[cat].push(cmd + ' — ' + def.help);
      }
      for (const [cat, lines] of Object.entries(cats)) {
        out += cat + ':\n  ' + lines.join('\n  ') + '\n';
      }
      return out;
    },
    help: 'Show available commands',
    category: 'Help',
  },
  '/ralph': {
    execute: function(args) {
      if (!args) return 'Usage: /ralph <scan|approve|decline|rescan>';
      const parts = args.split(/\s+/);
      const sub = parts[0];
      if (sub === 'scan') {
        dispatchIntent('ralph_scan');
        return null;
      }
      if (sub === 'lifecycle') {
        const lc = state.ralph.lifecycle;
        if (!lc) return 'No lifecycle data. Run ralph_scan first.';
        return 'Background: ' + (lc.background_enabled ? 'ON' : 'OFF') +
          ' | Active lanes: ' + (lc.active_lane_count || 0) +
          ' | Completed: ' + (lc.completed_lane_count || 0) +
          ' | Merge: ' + (lc.merge_enabled ? 'allowed' : 'gated') +
          ' | Push: ' + (lc.push_enabled ? 'allowed' : 'gated');
      }
      if (sub === 'background') {
        const toggle = parts[1];
        if (toggle === 'on') { dispatchIntent('ralph_background_toggle_on'); return null; }
        if (toggle === 'off') { dispatchIntent('ralph_background_toggle_off'); return null; }
        return 'Usage: /ralph background <on|off>';
      }
      if (sub === 'approve') {
        const panel = state.ralph.panel;
        if (!panel) return 'No Ralph scan found. Run /ralph scan first.';
        dispatchIntent('ralph_approve', {
          run_id: state.ralph.runState ? state.ralph.runState.run_id : '',
          scan_id: panel.scan_id || '',
          panel_sha256: panel.panel_sha256,
          mission_candidate_sha256: panel.mission_candidate_sha256
        });
        return null;
      }
      if (sub === 'decline') {
        const panel = state.ralph.panel;
        if (!panel) return 'No Ralph scan found. Run /ralph scan first.';
        dispatchIntent('ralph_decline', {
          run_id: state.ralph.runState ? state.ralph.runState.run_id : '',
          scan_id: panel.scan_id || '',
          panel_sha256: panel.panel_sha256,
          mission_candidate_sha256: panel.mission_candidate_sha256
        });
        return null;
      }
      if (sub === 'rescan') {
        dispatchIntent('ralph_rescan');
        return null;
      }
      return 'Unknown subcommand: ' + sub + '. Use scan, approve, decline, or rescan.';
    },
    help: 'Ralph maintenance loop. /ralph <scan|approve|decline|rescan>',
    category: 'Ralph',
  },
};

// Build autocomplete list sorted by command name
const AUTOCOMPLETE_LIST = Object.keys(COMMANDS).sort();

export function isCommand(text) {
  return typeof text === 'string' && text.length > 0 && text[0] === '/';
}

export function getAutocompleteMatches(prefix) {
  if (!prefix || prefix[0] !== '/') return [];
  return AUTOCOMPLETE_LIST.filter(function(c) { return c.startsWith(prefix); });
}

export function getAutocompleteList() {
  return AUTOCOMPLETE_LIST;
}

export function executeCommand(text) {
  const spaceIdx = text.indexOf(' ');
  const cmd = spaceIdx >= 0 ? text.substring(0, spaceIdx) : text;
  const args = spaceIdx >= 0 ? text.substring(spaceIdx + 1) : '';

  const def = COMMANDS[cmd];
  if (!def) return 'Unknown command: ' + cmd + '. Type /help for available commands.';
  return def.execute(args);
}
