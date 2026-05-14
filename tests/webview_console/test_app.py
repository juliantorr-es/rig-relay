from __future__ import annotations

from types import SimpleNamespace

from vibe.cli.webview_console import app as webview_app


def test_main_starts_websocket_server_in_background_thread(monkeypatch) -> None:
    started = {}

    class FakeWS:
        def __init__(self, backend, port=0):
            self.backend = backend
            self.port = port
            self.token = "fake-token"
            self.closed = False

        async def start(self) -> None:
            self.port = 4321
            started["start"] = True

        async def close(self) -> None:
            self.closed = True

    class FakeThread:
        def __init__(self, target, args=(), daemon=False):
            self._target = target
            self._args = args
            self.daemon = daemon
            self._alive = False

        def start(self):
            self._alive = True
            self._target(*self._args)
            self._alive = False

        def is_alive(self):
            return self._alive

    def fake_create_window(*args, **kwargs):
        started["window_args"] = kwargs

    def fake_start(*args, **kwargs):
        started["webview_start"] = True

    fake_webview = SimpleNamespace(create_window=fake_create_window, start=fake_start)

    monkeypatch.setattr(webview_app, "RigConsoleBackend", lambda **kwargs: object())
    monkeypatch.setattr(webview_app, "ConsoleWebSocketServer", FakeWS)
    monkeypatch.setattr(webview_app.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        webview_app, "_run_ws_server", lambda ws, holder: setattr(ws, "port", 4321)
    )
    monkeypatch.setattr(webview_app, "_load_html", lambda: "<html></html>")

    def fake_bootstrap(html, port, token):
        started["bootstrap"] = {"port": port, "token": token}
        return html

    monkeypatch.setattr(webview_app, "_inject_bootstrap", fake_bootstrap)
    monkeypatch.setitem(__import__("sys").modules, "webview", fake_webview)
    monkeypatch.setattr(webview_app.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        webview_app.asyncio,
        "run_coroutine_threadsafe",
        lambda coro, loop: SimpleNamespace(result=lambda: None),
    )

    webview_app.main(["--mode", "fixture"])

    assert started["bootstrap"]["port"] == 4321
    assert started["webview_start"] is True
