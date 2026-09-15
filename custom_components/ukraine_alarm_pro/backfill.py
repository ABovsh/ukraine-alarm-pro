"""Official alert history from the alert map, for the episode journal.

The live feed only shows what is happening now, so the journal used to start
empty and keep a hole for every outage. The map's history endpoint (the same
anonymous page token the map uses) returns every finished alert of a region's
districts for a date range. It carries air alerts only and no levels.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.util import dt as dt_util

from .api.errors import TransportError

MAP_URL = "https://map.ukrainealarm.com/"
RANGED_URL = MAP_URL + "api/v2/data/mapGetRangedAlerts"
_TOKEN_RE = re.compile(r'id="api-token"[^>]*value="([^"]+)"')
_TIMEOUT = aiohttp.ClientTimeout(total=60)

type Record = tuple[str, datetime, datetime]


def parse_ranged_alerts(body: str) -> list[Record]:
    """Finished alerts as (region id, start, end); raises on an unusable answer."""
    try:
        data: Any = json.loads(body)
        # The answer is a JSON string that itself holds the JSON list.
        if isinstance(data, str):
            data = json.loads(data)
    except ValueError as err:
        raise ValueError(f"history answer is not JSON: {err}") from err
    if not isinstance(data, list):
        raise ValueError("history answer is not a list")  # noqa: TRY004
    records: list[Record] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        region = item.get("regionId")
        start = _parse(item.get("startDate"))
        end = _parse(item.get("endDate"))
        if (
            not isinstance(region, (str, int))
            or isinstance(region, bool)
            or start is None
            or end is None
            # A still-active alert carries the end date 0001-01-01.
            or end <= start
        ):
            continue
        records.append((str(region), start, end))
    return records


def _parse(stamp: Any) -> datetime | None:
    if not isinstance(stamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_util.UTC)


def root_regions(regions: dict[str, dict[str, Any]]) -> list[str]:
    """One query per top-level region: it returns all of its districts."""
    return sorted({(info.get("ancestors") or [rid])[-1] for rid, info in regions.items()})


def official_intervals(
    records: list[Record], region_id: str, info: dict[str, Any]
) -> list[tuple[datetime, datetime]]:
    """Periods with any alert affecting the region, overlaps merged."""
    relevant = {region_id, *info.get("ancestors", []), *info.get("descendants", [])}
    spans = sorted((start, end) for rid, start, end in records if rid in relevant)
    merged: list[tuple[datetime, datetime]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


async def async_fetch_official_history(
    session: aiohttp.ClientSession,
    roots: list[str],
    start: datetime,
    end: datetime,
) -> list[Record]:
    """Finished alerts of the given top-level regions between two moments."""
    try:
        page = await session.get(MAP_URL, timeout=_TIMEOUT)
        page.raise_for_status()
        match = _TOKEN_RE.search(await page.text())
        if match is None:
            raise TransportError("map page has no api token (page changed?)")
        records: list[Record] = []
        for root in roots:
            resp = await session.get(
                f"{RANGED_URL}?startDate={start:%Y%m%d}"
                f"&endDate={end + timedelta(days=1):%Y%m%d}"
                f"&regionId={root}&apiToken={match.group(1)}",
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            records += parse_ranged_alerts(await resp.text())
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
        raise TransportError(f"alert history fetch failed: {err}") from err
    return records


# Indirection so tests can replace the network part only.
_fetch = async_fetch_official_history
