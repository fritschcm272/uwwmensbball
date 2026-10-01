# 01_uw_whitewater_scouting_parser.py -- code for the notebook section "UW-Whitewater Schedule and Scout Report Parser -- Portable Version"
# Runs inside the notebook via run_section("01_uw_whitewater_scouting_parser"); its settings are in that notebook cell.

# UW-Whitewater Schedule and Scout Report Parser -- Portable Version
#
# Converted from the Databricks notebook. All Databricks-specific dependencies replaced:
# - /Volumes/... and /Workspace/... paths -> configurable INPUT_DIR / OUTPUT_DIR below
# - dbutils.widgets -> plain variables below (edit these directly -- no widget UI outside Databricks)
# - spark.createDataFrame / saveAsTable -> removed (CSV export only)
# - display() -> print()
# - dbutils -> removed
# - ai_query() -> OpenAI client (via player_comparison module, when USE_LLM is enabled)

import email
import glob
import json
import logging
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime
from email import policy
from io import StringIO

import pandas as pd
from bs4 import BeautifulSoup

reference_date_str = "2026-1-7"   # games on/after this date are treated as not yet played; the first
                                     # scouted UWW game on/after it is flagged as the upcoming game
reference_date = datetime.strptime(reference_date_str, "%Y-%m-%d")
before_scout = "yes"      # "yes" = run as if the UPCOMING opponent's own scouting report does not exist yet,
                         # even when a "*_scout.html"/"*_scout.pdf" file for that game IS sitting in
                         # INPUT_DIR. Reports for games BEFORE the upcoming one are still used normally, and
                         # nothing is deleted from disk -- the upcoming game's report is simply filtered out
                         # of every scout-file lookup (and never re-downloaded) for this run. "no" = normal
                         # behaviour: use every report found.
_before_scout_enabled = str(before_scout).strip().lower() in {"yes", "y", "true", "1"}

os.makedirs(OUTPUT_DIR, exist_ok=True)


# --- Scout-report file discovery (honours `before_scout` above) ------------------------------------------
# Every cell that looks for scouting reports goes through find_scout_files() instead of globbing
# "*_scout.*" directly, so the `before_scout` switch has exactly ONE place to take effect rather than
# needing the same filter repeated (and kept in sync) at each glob site -- the "two places that both claim
# to mean the same thing" pattern that has bitten this notebook before.
_SCOUT_FILENAME_DATE_RE = re.compile(r"^(\d{1,2})_(\d{1,2})_(\d{2,4})\s")


def scout_file_game_date(path):
    """Parse the game date out of a "<M>_<D>_<YY> <Away> @ <Home>_scout.<ext>" filename.

    Returns a datetime, or None when the filename doesn't carry a parseable date."""
    m = _SCOUT_FILENAME_DATE_RE.match(os.path.basename(path))
    if not m:
        return None
    month, day, year = (int(g) for g in m.groups())
    if year < 100:
        year += 2000
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def find_scout_files(directory, extensions=("pdf", "html")):
    """Glob the scouting reports in `directory`, dropping the upcoming game's own report when
    `before_scout` is "yes".

    "Upcoming game" is identified by DATE rather than by opponent name, because this runs before the
    upcoming opponent has been resolved: reference_date is by definition the cutoff for "not yet played",
    so any report whose filename date is on/after it belongs to the upcoming matchup (or a later one that
    is out of scope for this run anyway). Reports dated strictly before reference_date -- the opponent's
    earlier games, and every previously-scouted opponent -- are always kept."""
    paths = []
    for ext in extensions:
        paths.extend(glob.glob(f"{directory}/*_scout.{ext}"))
    paths = sorted(paths)
    if not _before_scout_enabled:
        return paths

    kept, dropped, undated = [], [], []
    for p in paths:
        game_date = scout_file_game_date(p)
        if game_date is None:
            # Fail open: an undated filename can't be attributed to a specific game, so keep it rather
            # than silently dropping a report that may belong to a past opponent.
            undated.append(p)
            kept.append(p)
        elif game_date >= reference_date:
            dropped.append(p)
        else:
            kept.append(p)
    if dropped:
        print(f"  [before_scout=yes] Ignoring {len(dropped)} scouting report(s) dated on/after "
              f"{reference_date_str}: {[os.path.basename(p) for p in dropped]}")
    if undated:
        print(f"  [before_scout=yes] WARNING: could not read a game date from "
              f"{[os.path.basename(p) for p in undated]} -- keeping these; rename them to the "
              f"'<M>_<D>_<YY> <Away> @ <Home>_scout.<ext>' convention if one is the upcoming game's report.")
    return kept


print(f"Input directory: {INPUT_DIR}")
print(f"Output directory: {OUTPUT_DIR}")
print(f"LLM comparisons: {'enabled' if USE_LLM else 'disabled'}")
print(f"Reference date: {reference_date_str}")
print(f"Before scout: {before_scout} -- "
      + ("ignoring the upcoming opponent's own scouting report for this run"
         if _before_scout_enabled else "using every scouting report found"))

# Hosted URL of the Streamlit scouting app (e.g. "https://uww-scouting.streamlit.app"). The scouting brief links
# every condensed section into the app with it; leave blank and the brief prints "(in the app)" instead of links.
#
# SET THIS. With it blank, EVERY link in the emailed brief is dead text -- player names, "Clips, actions and
# spots", "All of our lineups", all of it. The staff gets a brief that says "(in the app)" 17+ times with no
# way to get there. Put the deployed URL in the string below (it wins over the environment variable), or
# export UWW_APP_URL before running.

if APP_BASE_URL:
    # A bare host is a RELATIVE href once it lands in the brief -- the browser resolves it against
    # wherever the file sits, so the link opens file:///.../uwwmensbball-new.streamlit.app/?page=...
    # instead of the app. Also repairs the usual scheme typos (https//host, https:/host).
    _raw_app_url = APP_BASE_URL
    APP_BASE_URL = APP_BASE_URL.strip().strip('"\'').rstrip("/")
    APP_BASE_URL = re.sub(r"^(https?)(?::/{0,2}|/{1,2})", r"\1://", APP_BASE_URL, flags=re.I)
    if not re.match(r"^https?://", APP_BASE_URL, flags=re.I):
        APP_BASE_URL = "https://" + APP_BASE_URL
    APP_BASE_URL = APP_BASE_URL.rstrip("/")
    if APP_BASE_URL != _raw_app_url:
        print(f"  APP_BASE_URL normalized: {_raw_app_url!r} -> {APP_BASE_URL}")
    print(f"Brief links -> {APP_BASE_URL}")
else:
    print("WARNING: APP_BASE_URL is blank -- the scouting brief will render every app link as dead "
          "\"(in the app)\" text. Set APP_BASE_URL in this cell (or the UWW_APP_URL env var) to make the "
          "brief's links actually open the app.")
