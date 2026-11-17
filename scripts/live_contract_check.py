"""Check that the live sources still match what the integration expects.

1. The map page carries the anonymous WebSocket token and URL.
2. The WebSocket connects and subscribes to the alert map in 20 seconds.
3. The official HTTP snapshot parses and keeps its known keys.
4. The siren.pp.ua fallback parses.

Run from the repository root with the test environment, for example
`.venv/bin/python scripts/live_contract_check.py`. Exit code 0 when every
check passes, 1 otherwise; one line per check on stdout. The URLs can be
overridden to rehearse a failure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.ukraine_alarm_pro.api import ws as ws_mod
from custom_components.ukraine_alarm_pro.api.poll import (
    DEFAULT_BASE_URL,
    OFFICIAL_URL,
    OfficialPollTransport,
    PollTransport,
)

# Keys of the official snapshot as verified on 2026-11-17.
OFFICIAL_KEYS = {
    "alerts",
    "migAlerts",
    "mapNotifications",
    "artillery",
    "reasons",
    "rfAlerts",
    "locations",
    "actionIndex",
}
TIMEOUT = aiohttp.ClientTimeout(total=30)


async def check_page(session: aiohttp.ClientSession, map_url: str) -> tuple[str, str]:
    async with session.get(map_url, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        html = await resp.text()
    token = ws_mod._TOKEN_RE.search(html)
    url = ws_mod._URL_RE.search(html)
    missing = [name for name, match in (("centrifugo-token", token), ("centrifugo-url", url)) if not match]
    if missing:
        raise AssertionError(f"map page lacks {', '.join(missing)}")
    return token.group(1), url.group(1)


async def check_ws(session: aiohttp.ClientSession, token: str, url: str) -> None:
    transport = ws_mod.WsTransport(session)
    pending: list[dict] = []
    async with asyncio.timeout(20):
        sock = await session.ws_connect(url)
        try:
            await sock.send_str(json.dumps({"id": 1, "params": {"token": token}}))
            await transport._recv_id(sock, 1, pending)
            await sock.send_str(
                json.dumps(
                    {"id": 2, "method": ws_mod._METHOD_SUBSCRIBE, "params": {"channel": ws_mod.CHANNEL}}
                )
            )
            await transport._recv_id(sock, 2, pending)
        finally:
            await sock.close()


async def check_official(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        payload = await resp.json()
    missing = OFFICIAL_KEYS - set(payload) if isinstance(payload, dict) else OFFICIAL_KEYS
    if missing:
        raise AssertionError(f"snapshot lacks {', '.join(sorted(missing))}")
    snap = OfficialPollTransport(session, url)._parse(payload)
    return f"{len(snap.active)} regions under alert"


async def check_siren(session: aiohttp.ClientSession, base_url: str) -> str:
    snap = await PollTransport(session, base_url=base_url).fetch()
    return f"{len(snap.active)} regions under alert"


async def run(args: argparse.Namespace) -> int:
    failed = False

    def report(name: str, error: BaseException | None, detail: str = "") -> None:
        nonlocal failed
        if error is None:
            print(f"OK   {name}{': ' + detail if detail else ''}")
        else:
            failed = True
            print(f"FAIL {name}: {type(error).__name__}: {error}")

    async with aiohttp.ClientSession() as session:
        token = url = None
        try:
            token, url = await check_page(session, args.map_url)
            report("map page token", None)
        except Exception as err:  # noqa: BLE001
            report("map page token", err)
        if token and url:
            try:
                await check_ws(session, token, url)
                report("websocket subscribe", None)
            except Exception as err:  # noqa: BLE001
                report("websocket subscribe", err)
        else:
            report("websocket subscribe", RuntimeError("skipped: no token"))
        for name, check, target in (
            ("official snapshot", check_official, args.official_url),
            ("siren.pp.ua", check_siren, args.siren_url),
        ):
            try:
                report(name, None, await check(session, target))
            except Exception as err:  # noqa: BLE001
                report(name, err)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--map-url", default=ws_mod.DEFAULT_MAP_URL)
    parser.add_argument("--official-url", default=OFFICIAL_URL)
    parser.add_argument("--siren-url", default=DEFAULT_BASE_URL)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
