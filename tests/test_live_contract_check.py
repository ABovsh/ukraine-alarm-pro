"""The live contract check walks the same WebSocket handshake as the integration."""

import importlib.util
import json
from pathlib import Path

import aiohttp

from custom_components.ukraine_alarm_pro.api import ws as ws_mod

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "live_contract_check.py"


def _script():
    spec = importlib.util.spec_from_file_location("live_contract_check", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Msg:
    type = aiohttp.WSMsgType.TEXT

    def __init__(self, data):
        self.data = data


class _Socket:
    """Answers every command; a history request gets a Centrifugo error."""

    def __init__(self, history_error):
        self.sent = []
        self._history_error = history_error

    async def send_str(self, text):
        self.sent.append(json.loads(text))

    async def receive(self, timeout=None):
        last = self.sent[-1]
        if last.get("method") == ws_mod._METHOD_HISTORY and self._history_error:
            return _Msg(json.dumps({"id": last["id"], "error": {"code": 108, "message": "not available"}}))
        return _Msg(json.dumps({"id": last["id"], "result": {}}))

    async def close(self):
        pass


class _Session:
    def __init__(self, sock):
        self._sock = sock

    async def ws_connect(self, url, **kwargs):
        return self._sock


async def test_check_ws_sends_the_integrations_history_request():
    sock = _Socket(history_error=False)
    await _script().check_ws(_Session(sock), "token", "wss://example.invalid")
    assert [frame.get("method") for frame in sock.sent] == [
        None,
        ws_mod._METHOD_SUBSCRIBE,
        ws_mod._METHOD_HISTORY,
    ]


async def test_a_refused_history_request_fails_the_check():
    """The integration cannot connect without it, so neither may the check."""
    sock = _Socket(history_error=True)
    try:
        await _script().check_ws(_Session(sock), "token", "wss://example.invalid")
    except ws_mod.TransportError as err:
        assert "centrifugo error" in str(err)
    else:
        raise AssertionError("a refused history request passed the check")
