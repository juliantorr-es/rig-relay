// Rig Relay — Frontend Event Trace Emission
// Unified trace point for frontend lifecycle observability

import { getSafeTimestamp } from "./correlation.js";
import { nextFrontendSequence, getTraceContext, setHandshakeId } from './traceContext.js'
import { sanitize } from './sanitizer.js'

export function setFrontendHandshakeId(id) {
	setHandshakeId(id)
}

export function recordFrontendEvent(type, detail = {}) {
	var seq = nextFrontendSequence()
	var ctx = getTraceContext()
	const payload = {
		type,
		handshake_id: ctx.handshakeId,
		frontend_session_id: ctx.frontendSessionId,
		frontend_sequence: seq,
		timestamp: getSafeTimestamp(),
		...detail,
	};

	// 1. Pywebview native injection (primary)
	if (
		window.pywebview &&
		window.pywebview.api &&
		window.pywebview.api.record_frontend_event
	) {
		try {
			window.pywebview.api.record_frontend_event(payload).catch((err) => {
				console.warn("Pywebview event emission failed:", err);
			});
			return;
		} catch (e) {
			console.warn("Pywebview API access error:", e);
		}
	}

	// 2. HTTP GET fallback (for browser debug) — uses query params, never hits /ws
	const detailParam = encodeURIComponent(JSON.stringify(sanitize(detail || {}, 0)));
	const url = `/frontend-event?type=${encodeURIComponent(type)}&handshake_id=${encodeURIComponent(ctx.handshakeId || "")}&detail=${detailParam}`;
	try {
		fetch(url, {
			method: "GET",
			credentials: "same-origin",
			cache: "no-store",
			keepalive: true,
		}).catch(() => {
			/* silent fallback */
		});
	} catch (e) {
		// silent
	}
}
