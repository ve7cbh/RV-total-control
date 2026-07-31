#!/usr/bin/env python3
"""
fetch_eccc_forecast.py — RVTC forecast-widget data source.

Fetches Environment Canada's citypage_weather XML for our nearest official
forecast site (Duncan, BC — s0000863, confirmed 2026-07-31 via
find_nearest_eccc_site.py), parses the 7-day forecast into simple day/night
paired cards, and writes them as JSON to Belchertown's own served directory.

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
      "days": [
        {"label": "Today", "icon_code": "02", "high_c": 24, "low_c": 16},
        {"label": "Sat",   "icon_code": "09", "high_c": 22, "low_c": 12},
        ...
      ]
    }

Intended to run periodically (hourly is plenty — ECCC itself only updates
hourly at minimum) via fetch_eccc_forecast.timer, not continuously.

Usage:
    python3 fetch_eccc_forecast.py
"""

import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

PROV = "BC"
SITE_CODE = "s0000863"  # Duncan, BC -- see find_nearest_eccc_site.py
LANG = "en"
BASE = f"https://dd.weather.gc.ca/today/citypage_weather/{PROV}"
MAX_HOURS_BACK = 6

OUTPUT_PATH = "/data/docker/volumes/weewx/public_html/belchertown/forecast.json"

# Full weekday name (as ECCC gives it, e.g. "Saturday") -> 3-letter header label
WEEKDAY_ABBR = {
    "Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed", "Thursday": "Thu",
    "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun",
}


def fetch_url(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "RVTC-forecast-widget/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def find_and_fetch_xml() -> str:
    now = datetime.now(timezone.utc)
    pattern = re.compile(rf'href="([^"]*_{re.escape(SITE_CODE)}_{LANG}\.xml)"')

    for hours_back in range(MAX_HOURS_BACK):
        hh = (now - timedelta(hours=hours_back)).strftime("%H")
        dir_url = f"{BASE}/{hh}/"
        try:
            listing = fetch_url(dir_url)
        except Exception:
            continue
        match = pattern.search(listing)
        if not match:
            continue
        file_url = dir_url + match.group(1)
        return fetch_url(file_url)

    raise RuntimeError(f"No {SITE_CODE}_{LANG}.xml found in the last {MAX_HOURS_BACK} hours")


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
            }
            days.append(current_card)
        else:
            if current_card is not None:
                current_card["low_c"] = low_c
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
                })

    return days, warnings


def main() -> int:
    try:
        xml_text = find_and_fetch_xml()
    except Exception as e:
        print(f"Fetch failed: {e}")
        return 1

    try:
        days, warnings = parse_forecast_days(xml_text)
    except Exception as e:
        print(f"Parse failed: {e}")
        return 1

    if not days:
        print("Parsed zero forecast days -- aborting rather than writing an empty widget")
        return 1

    output = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "location": "Duncan",
        "warnings": warnings,
        "days": days,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(days)} day(s) to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
