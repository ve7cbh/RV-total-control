#!/usr/bin/env python3
"""
fetch_eccc_sample.py — one-off diagnostic: locates and downloads a real
citypage_weather XML file for our site (Duncan, BC — s0000863), so the
actual forecast-widget parser can be built against real tag names instead
of documentation/memory of the schema.

Why this is needed: the XML files are NOT at a stable URL. They're
distributed hourly, in per-hour directories, with a timestamp prefixed to
the filename -- see the file name nomenclature in ECCC's own docs:
    {YYYYMMDD}T{HHmmss.sss}Z_MSC_CitypageWeather_{SiteCode}_{L}.xml
under:
    https://dd.weather.gc.ca/today/citypage_weather/{PROV}/{HH}/

This script walks backward from the current UTC hour (data can lag or a
folder can be mid-rotation) until it finds our site's file, downloads it,
and both prints it and saves it locally for inspection.

Usage:
    python3 fetch_eccc_sample.py
"""

import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

PROV_DEFAULT = "BC"
SITE_CODE_DEFAULT = "s0000863"  # Duncan, BC -- nearest confirmed site, 2026-07-31
LANG = "en"
MAX_HOURS_BACK = 6

SAVE_PATH = "eccc_sample.xml"


def fetch_url(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "RVTC-schema-check/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def main() -> int:
    if len(sys.argv) == 3:
        prov, site_code = sys.argv[1].upper(), sys.argv[2]
    elif len(sys.argv) == 1:
        prov, site_code = PROV_DEFAULT, SITE_CODE_DEFAULT
    else:
        print("Usage: fetch_eccc_sample.py [PROV SiteCode]")
        print("  e.g. fetch_eccc_sample.py BC s0000173")
        return 1

    base = f"https://dd.weather.gc.ca/today/citypage_weather/{prov}"
    now = datetime.now(timezone.utc)

    for hours_back in range(MAX_HOURS_BACK):
        hh = (now - timedelta(hours=hours_back)).strftime("%H")
        dir_url = f"{base}/{hh}/"
        print(f"Checking {dir_url} ...")
        try:
            listing = fetch_url(dir_url)
        except Exception as e:
            print(f"  couldn't list: {e}")
            continue

        # Apache-style autoindex: href="20260731T160512.34Z_MSC_CitypageWeather_s0000863_en.xml"
        pattern = re.compile(
            rf'href="([^"]*_{re.escape(site_code)}_{LANG}\.xml)"'
        )
        match = pattern.search(listing)
        if not match:
            print(f"  no {site_code}_{LANG}.xml file in this hour")
            continue

        filename = match.group(1)
        file_url = dir_url + filename
        print(f"Found: {file_url}")

        try:
            xml_content = fetch_url(file_url)
        except Exception as e:
            print(f"  download failed: {e}")
            continue

        with open(SAVE_PATH, "w") as f:
            f.write(xml_content)

        print(f"\nSaved to {SAVE_PATH} ({len(xml_content)} bytes)\n")
        print("=" * 70)
        print(xml_content[:6000])
        print("=" * 70)
        if len(xml_content) > 6000:
            print(f"(truncated -- full file saved to {SAVE_PATH})")
        return 0

    print(f"\nNo file found for {site_code} in the last {MAX_HOURS_BACK} hour folders.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
