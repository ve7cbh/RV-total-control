#!/usr/bin/env python3
"""
set_forecast_widget.py — sets radar_html / radar_html_dark / radar_html_kiosk
in Belchertown's skin.conf to a static, self-contained forecast-strip
widget (icon + high/low per day, matching the compact horizontal-strip
style requested 2026-07-31, replacing the earlier full-page ECCC iframe
experiment which proved too cluttered and too fragile to crop reliably).

Unlike the iframe version, THIS WIDGET NEVER NEEDS TO CHANGE once set.
It's pure client-side JS that fetches ./forecast.json (relative path --
works because forecast.json is written into the same directory Belchertown
serves this page from) and renders whatever's in it. Forecast data updates
happen entirely via fetch_eccc_forecast.py's periodic run; this script only
needs to run once, or again if the widget's *appearance* changes.

Data source: forecast.json, written by fetch_eccc_forecast.py. If that
file is missing or stale, the widget shows a small inline message rather
than a blank box or a JS error -- see the fetch().catch() below.

Usage:
    python3 set_forecast_widget.py
"""

import re
import sys

PATH = "/data/docker/volumes/weewx/skins/Belchertown/skin.conf"

# key -> (visible width, visible height) -- same box sizes as before
SIZES = {
    "radar_html": (650, 360),
    "radar_html_dark": (650, 360),
    "radar_html_kiosk": (490, 362),
}


def widget_html(width: int, height: int) -> str:
    title_color = "#ffffff"
    return f'''<div class="rvtc-forecast" style="width:{width}px; height:{height}px; box-sizing:border-box; padding:6px 8px; font-family:inherit; display:flex; flex-direction:column;">
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
<div style="font-weight:bold; font-size:19px; color:{title_color};">Forecast</div>
<div id="rvtc-warnings"></div>
</div>
<div id="rvtc-forecast-days" style="flex:1; display:flex; gap:5px; align-items:stretch;">
<div style="margin:auto; color:#888; font-size:14px;">Loading forecast...</div>
</div>
<div style="display:flex; justify-content:flex-end; align-items:center; gap:5px; margin-top:4px;">
<img src="eccc_logo.png" alt="Environment Canada" style="height:15px; width:auto;">
<span id="rvtc-forecast-attribution" style="font-size:10px; color:#888;"></span>
</div>
</div>
<script>
(function() {{
  var container = document.currentScript.previousElementSibling;
  var daysEl = container.querySelector("#rvtc-forecast-days");
  var warnEl = container.querySelector("#rvtc-warnings");
  var attribEl = container.querySelector("#rvtc-forecast-attribution");
  fetch("forecast.json", {{cache: "no-store"}})
    .then(function(r) {{ if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }})
    .then(function(data) {{
      if (data.location) {{
        attribEl.textContent = "\\u2014 " + data.location + ", BC";
      }}
      if (data.warnings && data.warnings.active && data.warnings.events && data.warnings.events.length) {{
        var colourMap = {{
          yellow: {{bg: "#f4d03f", text: "#000"}},
          orange: {{bg: "#e67e22", text: "#000"}},
          red: {{bg: "#c0392b", text: "#fff"}}
        }};
        var ev = data.warnings.events[0];
        var c = colourMap[ev.colour] || {{bg: "#e67e22", text: "#000"}};
        var link = document.createElement("a");
        link.href = ev.url || ("https://weather.gc.ca/?layers=alert&center=48.691,-123.585&zoom=-1");
        link.target = "_blank";
        link.rel = "noopener";
        var label = "\\u26a0 " + (ev.description || "Warning in effect");
        if (data.warnings.count > 1) {{ label += " (+" + (data.warnings.count - 1) + " more)"; }}
        link.textContent = label;
        link.style.cssText = "color:" + c.text + "; font-weight:bold; font-size:12px; text-decoration:none; background:" + c.bg + "; padding:3px 8px; border-radius:4px; white-space:nowrap;";
        warnEl.appendChild(link);
      }}

      daysEl.innerHTML = "";
      (data.days || []).forEach(function(day) {{
        var card = document.createElement("div");
        card.style.cssText = "flex:1; display:flex; flex-direction:column; align-items:center; justify-content:flex-start; background:#eef3f8; border-radius:6px; padding:6px 3px; min-width:0;";

        var label = document.createElement("div");
        label.textContent = day.label;
        label.style.cssText = "font-weight:bold; font-size:15px; color:#2c3e50; margin-bottom:4px;";
        card.appendChild(label);

        var icon = document.createElement("img");
        icon.src = "https://weather.gc.ca/weathericons/" + day.icon_code + ".gif";
        icon.alt = "";
        icon.style.cssText = "width:44px; height:44px; margin:2px 0;";
        card.appendChild(icon);

        var pop = day.pop_percent;
        if (pop !== null && pop !== undefined && pop > 0) {{
          var popEl = document.createElement("div");
          popEl.textContent = "\\u2614 " + pop + "%";
          popEl.style.cssText = "font-size:12px; color:#2980b9; margin-top:2px;";
          card.appendChild(popEl);
        }}

        var temps = document.createElement("div");
        temps.style.cssText = "font-size:14px; text-align:center; line-height:1.4; margin-top:4px;";
        var high = (day.high_c !== null && day.high_c !== undefined) ? day.high_c + "\\u00b0" : "\\u2013";
        var low = (day.low_c !== null && day.low_c !== undefined) ? day.low_c + "\\u00b0" : "\\u2013";
        temps.innerHTML = "<span style=\\"color:#c0392b; font-weight:bold;\\">" + high + "</span><br><span style=\\"color:#2980b9;\\">" + low + "</span>";
        card.appendChild(temps);

        if (day.condition) {{
          var cond = document.createElement("div");
          cond.textContent = day.condition;
          cond.style.cssText = "font-size:11px; color:#555; text-align:center; margin-top:6px; line-height:1.3;";
          card.appendChild(cond);
        }}

        daysEl.appendChild(card);
      }});
    }})
    .catch(function(err) {{
      daysEl.innerHTML = "<div style=\\"margin:auto; color:#c0392b; font-size:12px;\\">Forecast unavailable</div>";
    }});
}})();
</script>'''


def main() -> int:
    with open(PATH) as f:
        content = f.read()

    for key, (w, h) in SIZES.items():
        html = widget_html(w, h)
        # Matches empty (""), an earlier triple-quoted iframe crop, or an
        # earlier triple-quoted widget from a prior run of this script.
        pattern = re.compile(
            rf"^(\s*{re.escape(key)}\s*=\s*)(?:\"\"|'''.*?''')\s*$",
            re.MULTILINE | re.DOTALL,
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

    print("Done. All three radar_html* lines now use the JSON-driven forecast widget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
