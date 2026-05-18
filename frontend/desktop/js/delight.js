// Rig Relay — Motion + Sound + Delight System
// Subtle animations and Web Audio generated sound cues.
// All motion respects OS reduced-motion preference.
// Sound is opt-in, generated via Web Audio API (no audio files).
// Mounts on window.RigRelay.delight after boot via orchestrator.

import { createStateMachine } from './runtime/stateMachine.js'
import { recordFrontendEvent } from './telemetry/frontendTrace.js'
import { auditLog } from './audit.js'

// ── Internal state ────────────────────────────────────────────────────

const _motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
let _reducedMotion = _motionQuery.matches
let _audioContext = null
let _masterGain = null
const _customSounds = Object.create(null)
const _activePulses = new Set()
let _muted = true
let _volume = 0.3
let _initialized = false
let _runtime = null

// Load persisted preferences
try {
  const stored = localStorage.getItem('rig-relay-sound-muted')
  if (stored !== null) _muted = stored === 'true'
} catch (_) { /* localStorage unavailable */ }

try {
  const stored = localStorage.getItem('rig-relay-sound-volume')
  if (stored !== null) {
    const v = parseFloat(stored)
    if (!isNaN(v)) _volume = Math.max(0, Math.min(1, v))
  }
} catch (_) { /* noop */ }

// ── Sound definitions (hardcoded — no user/LLM content) ────────────────

const SOUND_KINDS = Object.freeze({
  click:           { frequency: 1600, duration: 35,  type: 'sine' },
  message_send:    { frequency: 900,  duration: 70,  type: 'sine' },
  message_receive: { frequency: 1100, duration: 100, type: 'sine' },
  error:           { frequency: 240,  duration: 200, type: 'square' },
  success:         { frequency: 1400, duration: 90,  type: 'sine' },
})

// ── Web Animations keyframes ──────────────────────────────────────────

const _entranceFrames = {
  fadeIn:  [{ opacity: 0 },              { opacity: 1 }],
  slideUp: [{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'translateY(0)' }],
  slideIn: [{ opacity: 0, transform: 'translateX(-8px)' }, { opacity: 1, transform: 'translateX(0)' }],
  scaleIn: [{ opacity: 0, transform: 'scale(0.96)' }, { opacity: 1, transform: 'scale(1)' }],
}

const _exitFrames = {
  fadeOut:   [{ opacity: 1 },              { opacity: 0 }],
  slideDown: [{ opacity: 1, transform: 'translateY(0)' }, { opacity: 0, transform: 'translateY(8px)' }],
  slideOut:  [{ opacity: 1, transform: 'translateX(0)' }, { opacity: 0, transform: 'translateX(-8px)' }],
  scaleOut:  [{ opacity: 1, transform: 'scale(1)' }, { opacity: 0, transform: 'scale(0.96)' }],
}

// ── Motion system ─────────────────────────────────────────────────────

const motion = {
  prefersReducedMotion() {
    return _reducedMotion
  },

  duration(kind) {
    if (_reducedMotion) return 0
    switch (kind) {
      case 'instant': return 0
      case 'fast':    return 120
      case 'base':    return 200
      case 'slow':    return 300
      case 'layout':  return 350
      default:        return 200
    }
  },

  animateEntrance(element, kind, options = {}) {
    if (_reducedMotion || !element || kind === 'none') return Promise.resolve()
    const frames = _entranceFrames[kind]
    if (!frames) return Promise.resolve()
    const dur = options.duration != null ? options.duration : motion.duration('slow')
    if (!dur) return Promise.resolve()
    return new Promise((resolve) => {
      const anim = element.animate(frames, {
        duration: dur,
        fill: 'forwards',
        easing: options.easing || 'ease',
      })
      anim.onfinish = () => {
        anim.commitStyles()
        anim.cancel()
        resolve()
      }
    })
  },

  animateExit(element, kind, options = {}) {
    if (_reducedMotion || !element || kind === 'none') return Promise.resolve()
    const frames = _exitFrames[kind]
    if (!frames) return Promise.resolve()
    const dur = options.duration != null ? options.duration : motion.duration('fast')
    if (!dur) return Promise.resolve()
    return new Promise((resolve) => {
      const anim = element.animate(frames, {
        duration: dur,
        fill: 'forwards',
        easing: options.easing || 'ease',
      })
      anim.onfinish = () => resolve()
    })
  },

  staggerChildren(container, selector, kind, staggerMs) {
    if (_reducedMotion || !container) return Promise.resolve()
    const children = Array.from(container.querySelectorAll(selector))
    if (!children.length) return Promise.resolve()
    const frames = _entranceFrames[kind]
    if (!frames) return Promise.resolve()
    const dur = motion.duration('slow')
    if (!dur) return Promise.resolve()

    const promises = []
    for (let i = 0; i < children.length; i++) {
      const child = children[i]
      const anim = child.animate(frames, {
        duration: dur,
        delay: i * staggerMs,
        fill: 'forwards',
        easing: 'ease',
      })
      promises.push(new Promise((resolve) => {
        anim.onfinish = () => {
          anim.commitStyles()
          anim.cancel()
          resolve()
        }
      }))
    }
    return Promise.all(promises)
  },

  pulse(element, options = {}) {
    if (_reducedMotion || !element) return { stop() {} }
    const dur = options.duration || 1600
    const minOpacity = options.minOpacity || 0.6
    const anim = element.animate([
      { opacity: 1 },
      { opacity: minOpacity, offset: 0.5 },
      { opacity: 1 },
    ], {
      duration: dur,
      iterations: Infinity,
      easing: 'ease-in-out',
    })

    let stopped = false
    const stop = () => {
      if (stopped) return
      stopped = true
      anim.cancel()
      _activePulses.delete(stop)
    }
    _activePulses.add(stop)

    return { stop }
  },

  drawAttention(element) {
    if (_reducedMotion || !element) return Promise.resolve()
    const dur = motion.duration('slow')
    if (!dur) return Promise.resolve()
    const computed = getComputedStyle(document.documentElement)
    const highlight = computed.getPropertyValue('--accent-subtle').trim() || 'rgba(79,143,204,0.12)'
    return new Promise((resolve) => {
      const anim = element.animate([
        { backgroundColor: highlight },
        { backgroundColor: 'transparent' },
      ], {
        duration: dur,
        fill: 'forwards',
        easing: 'ease',
      })
      anim.onfinish = () => resolve()
    })
  },
}

// ── Sound system ──────────────────────────────────────────────────────

function _ensureContext() {
  if (_audioContext && _audioContext.state === 'suspended') {
    _audioContext.resume().catch(() => {})
  }
}

function _playTone(config) {
  if (_muted || !_audioContext || _reducedMotion) return
  _ensureContext()
  try {
    const now = _audioContext.currentTime
    const osc = _audioContext.createOscillator()
    const env = _audioContext.createGain()
    osc.type = config.type || 'sine'
    osc.frequency.setValueAtTime(config.frequency, now)
    env.gain.setValueAtTime(0, now)
    env.gain.linearRampToValueAtTime(Math.min(_volume * 0.5, 0.3), now + 0.004)
    env.gain.linearRampToValueAtTime(0.001, now + (config.duration / 1000))
    osc.connect(env)
    env.connect(_masterGain)
    osc.start(now)
    osc.stop(now + (config.duration / 1000) + 0.01)
  } catch (_) {
    /* sound is non-critical */
  }
}

const sound = {
  isAvailable() {
    return typeof window !== 'undefined'
      && (typeof window.AudioContext !== 'undefined' || typeof window.webkitAudioContext !== 'undefined')
  },

  init() {
    // AudioContext MUST be created from a user gesture handler.
    // This is enforced at call site — never call init() at module load.
    if (_audioContext) return
    if (!sound.isAvailable()) return
    try {
      const AC = window.AudioContext || window.webkitAudioContext
      _audioContext = new AC()
      _masterGain = _audioContext.createGain()
      _masterGain.gain.value = _muted ? 0 : _volume
      _masterGain.connect(_audioContext.destination)
      recordFrontendEvent('delight_sound_context_created', {
        sampleRate: _audioContext.sampleRate,
      })
    } catch (e) {
      console.warn('[delight] AudioContext creation failed:', e)
    }
  },

  preload(name, frequency, duration, type = 'sine') {
    if (!name || typeof name !== 'string') return
    if (typeof frequency !== 'number' || typeof duration !== 'number') return
    _customSounds[name] = { frequency, duration, type }
  },

  play(name) {
    if (_muted || !_audioContext || _reducedMotion) return
    const config = _customSounds[name] || SOUND_KINDS[name]
    if (!config) return
    _playTone(config)
  },

  setMuted(muted) {
    _muted = !!muted
    if (_masterGain) {
      _masterGain.gain.value = _muted ? 0 : _volume
    }
    try {
      localStorage.setItem('rig-relay-sound-muted', String(_muted))
    } catch (_) {}
    if (_runtime && typeof _runtime.dispatch === 'function') {
      _runtime.dispatch({
        type: 'PREFERENCE_CHANGE',
        payload: { soundEnabled: !_muted },
      })
    }
    recordFrontendEvent('delight_sound_muted_changed', { muted: _muted })
  },

  isMuted() {
    return _muted
  },

  setVolume(volume) {
    _volume = Math.max(0, Math.min(1, typeof volume === 'number' ? volume : 0.5))
    if (_masterGain && !_muted) {
      _masterGain.gain.value = _volume
    }
    try {
      localStorage.setItem('rig-relay-sound-volume', String(_volume))
    } catch (_) {}
    recordFrontendEvent('delight_sound_volume_changed', { volume: _volume })
  },

  getVolume() {
    return _volume
  },
}

// ── Initialisation — called by orchestrator ───────────────────────────

function _stopAllPulses() {
  for (const stop of _activePulses) stop()
  _activePulses.clear()
}

export function initDelight(kernel) {
  if (!kernel || _initialized) {
    return { motion, sound, machine: null }
  }
  _initialized = true

  // Store runtime reference for PREFERENCE_CHANGE dispatch
  _runtime = kernel

  // Create delight state machine (uses runtime stateMachine.js API)
  const machine = createStateMachine({
    id: 'delight',
    initial: 'UNINITIALIZED',
    states: {
      UNINITIALIZED: { entry() {} },
      READY: { entry() {} },
      MUTED: { entry() {} },
      REDUCED_MOTION: { entry() {} },
    },
    transitions: [
      { from: 'UNINITIALIZED',  event: 'INIT',           to: 'READY' },
      { from: 'READY',          event: 'MUTE',           to: 'MUTED' },
      { from: 'READY',          event: 'REDUCE_MOTION',  to: 'REDUCED_MOTION' },
      { from: 'MUTED',          event: 'UNMUTE',         to: 'READY' },
      { from: 'MUTED',          event: 'REDUCE_MOTION',  to: 'REDUCED_MOTION' },
      { from: 'REDUCED_MOTION', event: 'RESTORE_MOTION', to: 'READY' },
      { from: 'REDUCED_MOTION', event: 'MUTE',           to: 'MUTED' },
      { from: 'REDUCED_MOTION', event: 'UNMUTE',         to: 'READY' },
    ],
  })

  // Transition to initial loaded state
  machine.transition('INIT', {})

  if (_muted) {
    machine.transition('MUTE', {})
  }
  if (_reducedMotion) {
    machine.transition('REDUCE_MOTION', {})
  }

  // Listen for OS reduced-motion preference changes
  _motionQuery.addEventListener('change', (event) => {
    _reducedMotion = event.matches
    if (event.matches) {
      _stopAllPulses()
      machine.transition('REDUCE_MOTION', {})
    } else {
      machine.transition('RESTORE_MOTION', {})
    }
    if (_runtime && typeof _runtime.dispatch === 'function') {
      _runtime.dispatch({
        type: 'PREFERENCE_CHANGE',
        payload: { animationEnabled: !event.matches },
      })
    }
    recordFrontendEvent('delight_motion_preference_changed', {
      reducedMotion: event.matches,
    })
  })

  // Wire readiness detection: subscribe to runtime state
  if (typeof kernel.subscribe === 'function') {
    let _wasReady = false
    kernel.subscribe((state) => {
      const isNowReady = state && state.boot && state.boot.phase === 'ready'
      if (isNowReady && !_wasReady) {
        _wasReady = true
        recordFrontendEvent('delight_system_ready', {
          reducedMotion: _reducedMotion,
          soundMuted: _muted,
          soundAvailable: sound.isAvailable(),
        })
        auditLog('delight', 'system_ready', {
          reducedMotion: _reducedMotion,
          soundMuted: _muted,
        })
      }
      if (!isNowReady && _wasReady) {
        _wasReady = false
        _stopAllPulses()
        recordFrontendEvent('delight_system_not_ready', {})
      }
    })
  }

  // If kernel has onReady/onNotReady (legacy compat), wire those too
  if (typeof kernel.onReady === 'function') {
    kernel.onReady(() => {
      recordFrontendEvent('delight_system_ready', {
        reducedMotion: _reducedMotion,
        soundMuted: _muted,
        soundAvailable: sound.isAvailable(),
      })
      auditLog('delight', 'system_ready', {
        reducedMotion: _reducedMotion,
        soundMuted: _muted,
      })
    })
  }
  if (typeof kernel.onNotReady === 'function') {
    kernel.onNotReady(() => {
      _stopAllPulses()
      recordFrontendEvent('delight_system_not_ready', {})
    })
  }

  recordFrontendEvent('delight_system_initialized', {
    reducedMotion: _reducedMotion,
    soundMuted: _muted,
    volume: _volume,
    soundAvailable: sound.isAvailable(),
  })

  return { motion, sound, machine }
}

// Attach allowed sound names for runtime introspection
export const allowedSoundNames = Object.freeze(Object.keys(SOUND_KINDS))
