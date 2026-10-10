#!/usr/bin/env python3
"""
fetch_eccc_forecast.py — RVTC forecast-widget data source.

Fetches Environment Canada's citypage_weather XML for whichever forecast
site is currently nearest our position, parses the 7-day forecast into
simple day/night paired cards, and writes them as JSON to Belchertown's own
served directory.

Site selection is now dynamic, not hardcoded (fixed 2026-08-18 -- the
original version hardcoded SITE_CODE to Duncan, BC after a one-time
find_nearest_eccc_site.py lookup on 2026-07-31, and nothing ever refreshed
it. It quietly kept serving Duncan's forecast for ~2.5 weeks and through at
least one real move before this was noticed). Each run now reads the
CURRENT latitude/longitude straight out of weewx.conf's [Station] section
-- already the authoritative, correctly-updated position (confirmed
2026-08-17: weewx.conf's own lat/lon do track real moves; the forecast
script simply wasn't consulting it) -- and only re-runs the nearest-site
lookup if we've moved more than SITE_RECHECK_KM from wherever we were when
the current site was chosen. The ECCC site list (~1-2MB) is itself cached
locally and only re-fetched when a recheck is actually triggered, not on
every hourly run -- this preserves the original script's stated reasoning
("only needs fetching once... not on every refresh") while fixing the
actual bug, which was "once" being interpreted as "forever" rather than
"once per move."

Why JSON, not HTML: the rendering (icons, layout, colours) lives in a
static HTML/JS snippet set once via skin.conf's radar_html (see
set_forecast_widget.py). This script's only job is producing fresh data.
That split means forecast updates never require a WeeWX restart — only
this script's output file changes, and the page's own JS re-fetches it.

Where the XML actually lives: NOT a stable URL. Files are distributed
hourly, in per-hour directories, with a timestamp prefixed to the filename:
    https://dd.weather.gc.ca/today/citypage_weather/{PROV}/{HH}/
    {YYYYMMDD}T{HHmmss.sss}Z_MSC_CitypageWeather_{SiteCode}_{L}.xml
This script walks backward from the current UTC hour until it finds our
site's file — same approach as fetch_eccc_sample.py, which was used to
confirm the real XML schema before this parser was written.

Output: <belchertown_public_html>/forecast.json
    {
      "generated_utc": "...",
      "location": "Duncan",
      "site_code": "s0000863",
      "site_distance_km": 3.2,
      "issued": "Friday July 31, 2026 at 11:00 PDT",
      "days": [
        {"label": "Today", "icon_code": "02", "high_c": 24, "low_c": 16,
         "night_icon_code": "..", "night_condition": "..."},
        {"label": "Sat",   "icon_code": "09", "high_c": 22, "low_c": 12,
         "night_icon_code": "..", "night_condition": "..."},
        ...
      ]
    }

Intended to run periodically (hourly is plenty — ECCC itself only updates
hourly at minimum) via fetch_eccc_forecast.timer, not continuously.

Usage:
    python3 fetch_eccc_forecast.py
"""

import json
import math
import os
import re
import socket
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

PROV_DEFAULT = "BC"
LANG = "en"
MAX_HOURS_BACK = 6

OUTPUT_PATH = "/data/docker/volumes/weewx/public_html/belchertown/forecast.json"
WEEWX_CONF_PATH = "/data/docker/volumes/weewx/weewx.conf"

# How far (great-circle) we have to move from the position where the
# current site was chosen before we bother re-querying ECCC's site list.
# ECCC forecast sites are town/region-level, not hyper-local, so this
# doesn't need to be small -- 25km avoids constant re-lookups from GPS
# jitter or short local drives while still catching real relocations.
SITE_RECHECK_KM = 25

# Site-selection state: which site we're using, where we were when we
# picked it, and a local cache of ECCC's own site list so a recheck
# doesn't always mean a fresh 1-2MB download.
SITE_STATE_PATH = "/data/docker/volumes/weewx/public_html/belchertown/.eccc_site_state.json"
SITE_LIST_CACHE_PATH = "/data/docker/volumes/weewx/public_html/belchertown/.eccc_site_list_cache.json"
SITE_LIST_URL = "https://collaboration.cmc.ec.gc.ca/cmc/cmos/public_doc/msc-data/citypage-weather/site_list_en.geojson"
# Re-fetch the site list itself at most this often even across many
# recheck-triggering moves -- the list of towns ECCC publishes barely
# changes, no need to hit their server every time we cross 25km.
SITE_LIST_MAX_AGE_DAYS = 30

# Full weekday name (as ECCC gives it, e.g. "Saturday") -> 3-letter header label
WEEKDAY_ABBR = {
    "Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed", "Thursday": "Thu",
    "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun",
}


def has_network(host: str = "dd.weather.gc.ca", port: int = 443, timeout: float = 5.0) -> bool:
    """Fast, cheap reachability check against the actual host this script
    needs -- not a generic 'is the internet up' probe. Deliberately short
    timeout: this only needs to distinguish 'clearly offline, don't
    bother' from 'reachable, worth trying the real fetch' -- the real
    fetches below have their own longer timeouts for genuine slow-network
    cases once we know basic reachability exists."""
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_weewx_position(conf_path: str) -> tuple:
    """Reads latitude/longitude directly out of weewx.conf's [Station]
    section. Deliberately a targeted line scan, not configparser --
    weewx.conf is ConfigObj format (nested [[ ]] subsections) which
    configparser doesn't fully agree with, and we only need two values
    from one top-level section."""
    with open(conf_path) as f:
        lines = f.readlines()

    in_station = False
    lat = lon = None
    for line in lines:
        stripped = line.strip()
        if re.match(r"^\[Station\]\s*(#.*)?$", stripped):
            in_station = True
            continue
        if in_station and re.match(r"^\[[^\[]", stripped):
            break  # left the [Station] section
        if in_station:
            m = re.match(r"^latitude\s*=\s*([-\d.]+)", stripped)
            if m:
                lat = float(m.group(1))
            m = re.match(r"^longitude\s*=\s*([-\d.]+)", stripped)
            if m:
                lon = float(m.group(1))

    if lat is None or lon is None:
        raise ValueError(f"Could not find latitude/longitude in [Station] section of {conf_path}")
    return lat, lon


def load_site_state() -> dict:
    if os.path.exists(SITE_STATE_PATH):
        try:
            with open(SITE_STATE_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_site_state(state: dict) -> None:
    with open(SITE_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def load_site_list(force_refresh: bool = False) -> list:
    """Returns the ECCC site list (list of {code, name, prov, lat, lon}
    dicts), using a local cache unless it's missing, unparseable, or older
    than SITE_LIST_MAX_AGE_DAYS -- avoids re-downloading ~1-2MB on every
    move-triggered recheck."""
    if not force_refresh and os.path.exists(SITE_LIST_CACHE_PATH):
        try:
            with open(SITE_LIST_CACHE_PATH) as f:
                cached = json.load(f)
            fetched = datetime.fromisoformat(cached["fetched_utc"])
            age_days = (datetime.now(timezone.utc) - fetched).days
            if age_days < SITE_LIST_MAX_AGE_DAYS:
                return cached["sites"]
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            pass  # fall through to a fresh fetch

    req = urllib.request.Request(SITE_LIST_URL, headers={"User-Agent": "RVTC-forecast-widget/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)

    sites = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        site_lon, site_lat = coords[0], coords[1]
        site_code = props.get("Codes") or props.get("SiteCode") or props.get("codes")
        name_en = (
            props.get("English Names") or props.get("EnglishNames")
            or props.get("name_en") or props.get("NameEN") or "?"
        )
        prov = props.get("Province Codes") or props.get("ProvinceCodes") or props.get("prov") or "?"
        if not site_code:
            continue
        sites.append({"code": site_code, "name": name_en, "prov": prov, "lat": site_lat, "lon": site_lon})

    with open(SITE_LIST_CACHE_PATH, "w") as f:
        json.dump({"fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sites": sites}, f)

    return sites


def nearest_site(lat: float, lon: float, sites: list) -> dict:
    best = min(sites, key=lambda s: haversine_km(lat, lon, s["lat"], s["lon"]))
    dist = haversine_km(lat, lon, best["lat"], best["lon"])
    return {**best, "distance_km": round(dist, 1)}


def resolve_current_site() -> dict:
    """Returns {"code", "name", "prov", "distance_km"} for the site to use
    this run -- reusing the cached site if we haven't moved far since it
    was chosen, otherwise re-querying ECCC's site list for a fresh nearest
    match."""
    lat, lon = load_weewx_position(WEEWX_CONF_PATH)
    state = load_site_state()

    needs_recheck = True
    if state.get("site_code") and "chosen_at_lat" in state and "chosen_at_lon" in state:
        moved_km = haversine_km(lat, lon, state["chosen_at_lat"], state["chosen_at_lon"])
        needs_recheck = moved_km > SITE_RECHECK_KM

    if not needs_recheck:
        return {
            "code": state["site_code"], "name": state.get("site_name", "?"),
            "prov": state.get("site_prov", "?"), "distance_km": state.get("site_distance_km"),
        }

    sites = load_site_list()
    chosen = nearest_site(lat, lon, sites)
    save_site_state({
        "site_code": chosen["code"], "site_name": chosen["name"], "site_prov": chosen["prov"],
        "site_distance_km": chosen["distance_km"],
        "chosen_at_lat": lat, "chosen_at_lon": lon,
        "chosen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    print(f"Site re-check triggered: now using {chosen['code']} ({chosen['name']}, {chosen['prov']}), "
          f"{chosen['distance_km']} km away")
    return chosen


def fetch_url(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "RVTC-forecast-widget/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def find_and_fetch_xml(prov: str, site_code: str) -> str:
    base = f"https://dd.weather.gc.ca/today/citypage_weather/{prov}"
    now = datetime.now(timezone.utc)
    pattern = re.compile(rf'href="([^"]*_{re.escape(site_code)}_{LANG}\.xml)"')

    for hours_back in range(MAX_HOURS_BACK):
        hh = (now - timedelta(hours=hours_back)).strftime("%H")
        dir_url = f"{base}/{hh}/"
        try:
            listing = fetch_url(dir_url)
        except Exception:
            continue
        match = pattern.search(listing)
        if not match:
            continue
        file_url = dir_url + match.group(1)
        return fetch_url(file_url)

    raise RuntimeError(f"No {site_code}_{LANG}.xml found in the last {MAX_HOURS_BACK} hours")


def parse_issued(root) -> str:
    """Returns the forecast-issued date/time as ECCC's own textSummary
    string (e.g. "Friday July 31, 2026 at 11:00 PDT"), preferring the
    local-timezone entry over UTC -- matches what the ECCC page itself
    displays ("Forecast issued: ..."). Confirmed present in forecastGroup
    2026-08-01 against the real Duncan sample. Falls back to UTC if no
    non-UTC entry exists, and to an empty string (not None -- keeps the
    JSON schema stable for the widget's JS) if neither is found."""
    forecast_group = root.find("forecastGroup")
    if forecast_group is None:
        return ""
    local_text = None
    utc_text = None
    for dt in forecast_group.findall("dateTime[@name='forecastIssue']"):
        text_el = dt.find("textSummary")
        text = text_el.text.strip() if text_el is not None and text_el.text else None
        if dt.get("zone") == "UTC":
            utc_text = text
        else:
            local_text = text
    return local_text or utc_text or ""


def parse_warnings(root) -> dict:
    """Parses the top-level <warnings> element. CONFIRMED 2026-07-31 against
    a real populated example (Merritt, BC, s0000006 -- an active air quality
    warning): each active alert is an <event> child with type,
    alertColourLevel, description, expiryTime, and url attributes, e.g.:

        <event type="warning" alertColourLevel="orange"
               description="ORANGE WARNING - AIR QUALITY"
               expiryTime="20260801104928"
               url="https://weather.gc.ca/warnings/report_air_quality_e.html?..."/>

    Only one <event> was seen in the real sample, but this handles multiple
    defensively (e.g. an air quality warning and a wind warning both active
    at once) since nothing in the schema suggests only one is possible.
    """
    warnings_el = root.find("warnings")
    if warnings_el is None or len(warnings_el) == 0:
        return {"active": False, "count": 0, "events": []}

    events = []
    for event in warnings_el.findall("event"):
        events.append({
            "type": event.get("type"),
            "colour": event.get("alertColourLevel"),
            "description": event.get("description"),
            "url": event.get("url"),
        })

    return {"active": len(events) > 0, "count": len(events), "events": events}


def parse_forecast_days(xml_text: str) -> tuple:
    root = ET.fromstring(xml_text)
    forecast_group = root.find("forecastGroup")
    if forecast_group is None:
        raise ValueError("No <forecastGroup> in XML -- schema may have changed")

    warnings = parse_warnings(root)
    issued = parse_issued(root)
    days = []
    current_card = None

    for forecast in forecast_group.findall("forecast"):
        period_el = forecast.find("period")
        name = period_el.get("textForecastName", "") if period_el is not None else ""
        is_night = name.strip().lower() == "tonight" or name.strip().lower().endswith(" night")

        icon_el = forecast.find("abbreviatedForecast/iconCode")
        icon_code = (icon_el.text or "").strip() if icon_el is not None else ""

        condition_el = forecast.find("abbreviatedForecast/textSummary")
        condition = (condition_el.text or "").strip() if condition_el is not None else ""

        pop_el = forecast.find("abbreviatedForecast/pop")
        pop_text = (pop_el.text or "").strip() if pop_el is not None else ""
        pop_percent = int(pop_text) if pop_text.isdigit() else None

        high_el = forecast.find("temperatures/temperature[@class='high']")
        low_el = forecast.find("temperatures/temperature[@class='low']")
        high_c = int(high_el.text) if high_el is not None and high_el.text else None
        low_c = int(low_el.text) if low_el is not None and low_el.text else None

        if not is_night:
            label = name if name.strip().lower() == "today" else WEEKDAY_ABBR.get(name, name)
            current_card = {
                "label": label, "icon_code": icon_code, "high_c": high_c, "low_c": None,
                "pop_percent": pop_percent, "condition": condition,
                "night_icon_code": None, "night_condition": None,
            }
            days.append(current_card)
        else:
            if current_card is not None:
                current_card["low_c"] = low_c
                current_card["night_icon_code"] = icon_code
                current_card["night_condition"] = condition
                if not current_card["icon_code"]:
                    current_card["icon_code"] = icon_code
                if not current_card["condition"]:
                    current_card["condition"] = condition
                # Keep the higher of day/night pop if the night period has its
                # own (e.g. daytime clear, evening showers) -- worst case wins,
                # more useful for "should I expect rain today" at a glance.
                if pop_percent is not None:
                    existing = current_card.get("pop_percent")
                    current_card["pop_percent"] = max(existing, pop_percent) if existing is not None else pop_percent
            else:
                # Orphan night entry (forecast starting mid-night) -- give it its own card
                base_name = re.sub(r"\s+night$", "", name, flags=re.IGNORECASE)
                label = "Tonight" if name.strip().lower() == "tonight" else WEEKDAY_ABBR.get(base_name, base_name)
                days.append({
                    "label": label, "icon_code": icon_code, "high_c": None, "low_c": low_c,
                    "pop_percent": pop_percent, "condition": condition,
                    "night_icon_code": icon_code, "night_condition": condition,
                })

    return days, warnings, issued


def main() -> int:
    if not has_network():
        print("No network connection -- skipping this run. Existing forecast.json "
              "and site-selection state left untouched; will try again next hour.")
        return 0

    try:
        site = resolve_current_site()
    except Exception as e:
        print(f"Site resolution failed: {e}")
        return 1

    try:
        xml_text = find_and_fetch_xml(site["prov"], site["code"])
    except Exception as e:
        print(f"Fetch failed: {e}")
        return 1

    try:
        days, warnings, issued = parse_forecast_days(xml_text)
    except Exception as e:
        print(f"Parse failed: {e}")
        return 1

    if not days:
        print("Parsed zero forecast days -- aborting rather than writing an empty widget")
        return 1

    output = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "location": site["name"],
        "site_code": site["code"],
        "site_distance_km": site["distance_km"],
        "issued": issued,
        "warnings": warnings,
        "days": days,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(days)} day(s) for {site['name']} ({site['code']}) to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
