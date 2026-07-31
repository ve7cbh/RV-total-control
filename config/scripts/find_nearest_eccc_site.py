#!/usr/bin/env python3
"""
find_nearest_eccc_site.py — one-off diagnostic: fetches Environment Canada's
official site list (GeoJSON) and finds the citypage_weather site code
nearest our coordinates, for use in the forecast-widget fetch script.

Why this is a separate script rather than baking a guess into the real
fetcher: ECCC's citypage_weather product only covers fixed named forecast
sites (towns/regions), not arbitrary lat/lon -- unlike the RSS feed we used
for the (now-reverted) iframe experiment, which accepted our exact
coordinates directly. The site list is ~1-2MB and only needs fetching once
to find the right code, not on every forecast refresh, so this is meant to
be run manually, not scheduled.

Note: the source host's robots.txt disallows generic crawler access -- this
is a one-time interactive lookup of official open data explicitly published
for this kind of reuse (see the MSC Open Data documentation), not automated
scraping, but flagging it here for transparency.

Usage:
    python3 find_nearest_eccc_site.py
"""

import json
import math
import sys
import urllib.request

GEOJSON_URL = "https://collaboration.cmc.ec.gc.ca/cmc/cmos/public_doc/msc-data/citypage-weather/site_list_en.geojson"

# Default: our own coordinates. Override with two CLI args (lat lon) to
# look up any other location -- e.g. to grab a real populated <warnings>
# sample from wherever an alert is currently active, for schema-checking.
DEFAULT_LAT = 48.691
DEFAULT_LON = -123.585

N_CLOSEST = 5  # show a few candidates, not just the single nearest


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def main() -> int:
    if len(sys.argv) == 3:
        try:
            lat, lon = float(sys.argv[1]), float(sys.argv[2])
        except ValueError:
            print("Usage: find_nearest_eccc_site.py [lat lon]")
            return 1
    elif len(sys.argv) == 1:
        lat, lon = DEFAULT_LAT, DEFAULT_LON
    else:
        print("Usage: find_nearest_eccc_site.py [lat lon]")
        return 1

    req = urllib.request.Request(GEOJSON_URL, headers={"User-Agent": "RVTC-site-lookup/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except Exception as e:
        print(f"Fetch failed: {e}")
        return 1

    candidates = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        site_lon, site_lat = coords[0], coords[1]
        # Property key names vary by ECCC file version -- try the common ones.
        site_code = props.get("Codes") or props.get("SiteCode") or props.get("codes")
        name_en = (
            props.get("English Names")
            or props.get("EnglishNames")
            or props.get("name_en")
            or props.get("NameEN")
            or "?"
        )
        prov = props.get("Province Codes") or props.get("ProvinceCodes") or props.get("prov") or "?"
        dist = haversine_km(lat, lon, site_lat, site_lon)
        candidates.append((dist, site_code, name_en, prov, site_lat, site_lon))

    if not candidates:
        print("No features parsed -- GeoJSON structure may differ from what this script expects.")
        print("Raw top-level keys:", list(data.keys()))
        if data.get("features"):
            print("First feature properties, for reference:", data["features"][0].get("properties"))
        return 1

    candidates.sort(key=lambda c: c[0])
    print(f"Nearest {N_CLOSEST} ECCC forecast sites to {lat}, {lon}:\n")
    for dist, code, name, prov, site_lat, site_lon in candidates[:N_CLOSEST]:
        print(f"  {dist:6.1f} km  {code!s:12} {name} ({prov})  [{site_lat}, {site_lon}]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
