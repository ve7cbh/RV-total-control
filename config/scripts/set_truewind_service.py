#!/usr/bin/env python3
"""
set_truewind_service.py — adds user.truewind.TrueWindService to weewx.conf's
[Engine][[Services]] process_services list, right after StdWXCalculate
(same reasoning as its placement: this is a derived-field computation on
the loop packet, same event StdWXCalculate itself hooks).

Idempotent and safe to re-run: if the service is already present, does
nothing rather than duplicating it. Aborts with no changes written if the
expected process_services line isn't found exactly once -- same "pattern
not found" discipline as every other config editor in this project.

Always backs up weewx.conf before writing, given how much rides on this
file staying valid.

Usage:
    python3 set_truewind_service.py
"""

import re
import shutil
import sys
from datetime import datetime

WEEWX_CONF_PATH = "/data/docker/volumes/weewx/weewx.conf"
SERVICE = "user.truewind.TrueWindService"
ANCHOR = "weewx.wxservices.StdWXCalculate"


def main() -> int:
    with open(WEEWX_CONF_PATH) as f:
        content = f.read()

    if SERVICE in content:
        print(f"{SERVICE} is already present in weewx.conf -- nothing to do.")
        return 0

    pattern = re.compile(
        rf"^(\s*process_services\s*=\s*.*?{re.escape(ANCHOR)})(,?\s*)$",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(content))
    if len(matches) != 1:
        print(f"ABORTING — expected exactly 1 process_services line containing "
              f"{ANCHOR!r}, found {len(matches)}. No changes written.")
        return 1

    def _insert(m):
        prefix, trailing = m.group(1), m.group(2)
        # trailing is either "" (StdWXCalculate is the last item) or ", " /
        # "," (more items follow) -- insert right after StdWXCalculate
        # either way, preserving whatever came after it.
        return f"{prefix}, {SERVICE}{trailing}"

    new_content = pattern.sub(_insert, content, count=1)

    if SERVICE not in new_content:
        print("ABORTING — substitution didn't actually insert the service. No changes written.")
        return 1

    backup_path = f"{WEEWX_CONF_PATH}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(WEEWX_CONF_PATH, backup_path)
    print(f"Backed up weewx.conf to {backup_path}")

    with open(WEEWX_CONF_PATH, "w") as f:
        f.write(new_content)

    print(f"Added {SERVICE} to process_services, after {ANCHOR}.")
    print("Restart the weewx container for this to take effect:")
    print("    docker restart weewx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
