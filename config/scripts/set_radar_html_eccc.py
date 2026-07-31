#!/usr/bin/env python3
"""
set_radar_html_eccc.py — swaps the (currently empty) radar_html /
radar_html_dark / radar_html_kiosk values in Belchertown's skin.conf for
an ECCC weather.gc.ca iframe, using ConfigObj's triple-quote syntax so the
double quotes inside the <iframe> tag don't need any escaping at all.

Why not sed: the first attempt at this used shell-escaped \" inside a
double-quoted skin.conf value. ConfigObj accepted it as literal text
instead of erroring, so the generated HTML ended up with literal
backslash-quote characters in the iframe's src attribute -- which mangled
the tag enough that the browser never actually requested weather.gc.ca.
Triple-quoting the whole value sidesteps needing any escaping.

Safety: aborts with no changes written if any of the three expected
patterns isn't found exactly once -- matching the project's stated
preference for scripted edits with an explicit "pattern not found"
check over hand-editing, given transposition-prone typing.

Usage:
    python3 set_radar_html_eccc.py
"""

import re
import sys

PATH = "/data/docker/volumes/weewx/skins/Belchertown/skin.conf"
ECCC_URL = "https://weather.gc.ca/en/location/index.html?coords=48.691,-123.585#wb-cont"

# Measured 2026-07-31 via window.scrollY in a browser resized to ~650px wide,
# scrolled so the "Forecast" heading sits at the very top of the viewport.
# If ECCC ever redesigns the page, re-measure and update this one number.
OFFSET_PX = 1282

# Generous inner height so the iframe's own document renders far enough down
# to cover offset + the tallest visible window (offset + 362 needs ~1644px;
# this leaves comfortable headroom without being wasteful).
IFRAME_INNER_HEIGHT_PX = 1800

# key -> (visible width, visible height) -- this is the cropped window size,
# not the iframe's actual (much taller) rendered height.
SIZES = {
    "radar_html": (650, 360),
    "radar_html_dark": (650, 360),
    "radar_html_kiosk": (490, 362),
}


def cropped_iframe_html(width: int, height: int) -> str:
    return (
        f'<div style="width:{width}px; height:{height}px; overflow:hidden; position:relative;">'
        f'<iframe style="position:absolute; top:-{OFFSET_PX}px; left:0; '
        f'width:{width}px; height:{IFRAME_INNER_HEIGHT_PX}px; border:0;" '
        f'src="{ECCC_URL}"></iframe>'
        f'</div>'
    )


def main() -> int:
    with open(PATH) as f:
        content = f.read()

    for key, (w, h) in SIZES.items():
        html = cropped_iframe_html(w, h)
        # Matches either the original empty value (radar_html = "") or an
        # existing single-line triple-quoted value from a previous run of
        # this script -- lets you re-run after tweaking OFFSET_PX without
        # reverting to the backup first.
        pattern = re.compile(
            rf"^(\s*{re.escape(key)}\s*=\s*)(?:\"\"|'''.*?''')\s*$", re.MULTILINE
        )
        new_content, n = pattern.subn(
            lambda m: f"{m.group(1)}'''{html}'''", content, count=1
        )
        if n == 0:
            print(f"ABORTING — pattern not found for key: {key!r}. No changes written.")
            return 1
        content = new_content
        print(f"OK — updated {key}")

    with open(PATH, "w") as f:
        f.write(content)

    print("Done. All three radar_html* lines updated with cropped ECCC forecast view.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
