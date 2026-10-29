# 00b_season_switch.py -- the season the run is on, and the switch to a new season.
# Runs inside the notebook via run_section("00b_season_switch") in the first settings cell (setting: SEASON).
#
# CONFIRMED CHANGE (requested: "build that switch because we are now in the 2026-27 season" -- with the film side kept on
# last season's games: "Keep 2025-26 film"). The parser reads ONE season's FastScout pages (schedules, rosters, games). When
# the season changes, that season's files are archived and the next run reads the new season from FastScout:
#   inputs\  ->  inputs_2025-26\   the season's FastScout pages: schedules, rosters, every game's _pbp / _scout / _video file
#                                  (MOVED -- the same way inputs_2024-25 was made). Everything else stays where it is: the
#                                  film (uww_plays.csv, frames, tracking, court calibrations, the models, play reviews), the
#                                  playbook, older seasons' head-to-head pages ("- PBP 2024_25 ...", "Schedule_2024") and
#                                  next season's rosters ("Roster_2026").
#   ..\data\ ->  ..\data_2025-26\  last season's tables, COPIED (data\ itself is untouched until the next run rewrites it).
#                                  The app lists it in Previous Games' season picker automatically, and the brief / Upcoming
#                                  Game page read it for "this season vs last season". The film tables (tracking, play
#                                  calls, model reports) are not copied -- they stay current in data\ for both seasons.
# Film Tagging and tracking on last season's games keep going after the switch: each run saves the season's play-by-play
# (inputs\_film_pbp\<season>\), and after the switch the film cells add last season's to this season's (47_play_calls) --
# all of UWW's games, and an opponent's games when that team is up next again. The brief cells only see this season's.
#
# SEASON = "auto"     switch once UWW's first game of the new season is played (FastScout's count from the new-season
#                     check, or an EXTRA_GAMES real game whose date has passed). Before that, a new-season run would have
#                     no games at all -- the opener brief is built from last season, labeled that way.
# SEASON = "2026-27"  switch now (or stay on it).      SEASON = "2025-26"  stay on (or go back to) that season's data.
# undo_season_switch() moves the archived input files back and clears the switch (data_<season>\ is left in place).
import os as _ss_os
import re as _ss_re
import json as _ss_json
import shutil as _ss_shutil
import glob as _ss_glob
from datetime import datetime as _ss_dt
import pandas as pd

_SS_MARK = _ss_os.path.join(INPUT_DIR, "_season.json")
_SS_FILM_TABLE = _ss_re.compile(r"^uww_(trk_|player_tracks|tag_model|tracking_|model_version|film_|play_calls|"
                                r"court_|defensive_roles|title_|tracks)", _ss_re.I)


def _ss_label(year):
    return f"{int(year)}-{str(int(year) + 1)[-2:]}"


def _ss_year(label):
    m = _ss_re.match(r"\s*(\d{4})", str(label or ""))
    return int(m.group(1)) if m else None


def _ss_season_of(d):
    return d.year if d.month >= 8 else d.year - 1


def _ss_read_mark():
    try:
        with open(_SS_MARK, encoding="utf-8") as fh:
            return _ss_json.load(fh)
    except Exception:
        return {}


def _ss_data_season():
    """The season of the FastScout files in INPUT_DIR: the switch marker, else the latest dated UWW game file."""
    mk = _ss_read_mark()
    if _ss_year(mk.get("season")):
        return _ss_year(mk["season"])
    last = None
    for f in _ss_glob.glob(_ss_os.path.join(INPUT_DIR, "*")):
        b = _ss_os.path.basename(f)
        m = _ss_re.match(r"^(\d{1,2})_(\d{1,2})_(\d{2,4})\s.*whitewater.*_(pbp|scout|video)\.", b, _ss_re.I)
        if not m:
            continue
        y = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
        try:
            d = _ss_dt(y, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        last = d if last is None or d > last else last
    return _ss_season_of(last) if last else None


def _ss_new_season_started(year):
    """Has UWW played a game in season `year`? (FastScout's count saved by the last run's new-season check, or an
    EXTRA_GAMES real game -- not a scrimmage -- in that season whose date has passed.)"""
    try:
        with open(_ss_os.path.join(INPUT_DIR, "_new_season_check.json"), encoding="utf-8") as fh:
            ck = _ss_json.load(fh)
        if str(ck.get("season")) == f"{year % 100:02d}" and int((ck.get("played") or {}).get("UW-Whitewater") or 0) > 0:
            return "FastScout shows UWW has played"
    except Exception:
        pass
    today = _ss_dt.now()
    for g in (globals().get("EXTRA_GAMES") or []):
        if not g or _ss_re.search(r"scrimmage|exhibition", str(g.get("type") or "scrimmage"), _ss_re.I):
            continue
        try:
            d = pd.to_datetime(g.get("real_date"), errors="coerce")
        except Exception:
            d = None
        if d is not None and pd.notna(d) and _ss_season_of(d) == year and d.date() < today.date():
            return f"the {g.get('opponent')} game ({d:%b %d}) has been played"
    return None


def _ss_season_file(base, year):
    """Is this INPUT_DIR file one of season `year`'s FastScout pages (moved by the switch)?"""
    if _ss_re.search(r"_(pbp|scout|video|box|recap)\.(m?html|pdf|csv)$", base, _ss_re.I):
        return True
    m = _ss_re.search(r" - (Schedule|Roster)(?:_(\d{4}))?\.m?html$", base, _ss_re.I)
    if m:
        return m.group(2) is None or int(m.group(2)) == year           # older seasons (head-to-head) / next season's stay
    if base.lower().startswith(("myteam - analytics dashboard", "synergy - login page")):
        return True
    if _ss_re.match(rf"^{year}-{str(year + 1)[-2:]} .*roster", base, _ss_re.I):
        return True
    return base == "_new_season_check.json"


def film_pbp_dir(season_label=None):
    return _ss_os.path.join(INPUT_DIR, "_film_pbp", season_label or SEASON_NOW)


def _ss_switch(old, new):
    """Archive season `old` (inputs moved, data copied) and mark INPUT_DIR as season `new`."""
    old_l, new_l = _ss_label(old), _ss_label(new)
    in_arch = _ss_os.path.normpath(_ss_os.path.abspath(INPUT_DIR)) + "_" + old_l
    out_arch = _ss_os.path.normpath(_ss_os.path.abspath(OUTPUT_DIR)) + "_" + old_l
    _ss_os.makedirs(in_arch, exist_ok=True)
    moved, kept = [], 0
    for f in sorted(_ss_glob.glob(_ss_os.path.join(INPUT_DIR, "*"))):
        b = _ss_os.path.basename(f)
        if not _ss_os.path.isfile(f) or not _ss_season_file(b, old):
            continue
        dst = _ss_os.path.join(in_arch, b)
        if _ss_os.path.exists(dst):
            kept += 1                                                       # already archived: the inputs copy stays
            continue
        _ss_shutil.move(f, dst)
        moved.append(b)
    copied = 0
    if _ss_os.path.isdir(OUTPUT_DIR):
        _ss_os.makedirs(out_arch, exist_ok=True)
        for f in sorted(_ss_glob.glob(_ss_os.path.join(OUTPUT_DIR, "*.csv"))):
            b = _ss_os.path.basename(f)
            if _SS_FILM_TABLE.match(b) or _ss_os.path.exists(_ss_os.path.join(out_arch, b)):
                continue
            _ss_shutil.copy2(f, _ss_os.path.join(out_arch, b))
            copied += 1
        for sub in ("logo", "player_images", "uww_player_pictures"):
            s_ = _ss_os.path.join(OUTPUT_DIR, sub)
            if _ss_os.path.isdir(s_) and not _ss_os.path.exists(_ss_os.path.join(out_arch, sub)):
                _ss_shutil.copytree(s_, _ss_os.path.join(out_arch, sub))
    mark = {"season": new_l, "last_season": old_l, "switched": _ss_dt.now().isoformat(timespec="seconds"),
            "inputs_archive": in_arch, "data_archive": out_arch, "moved": moved}
    with open(_SS_MARK, "w", encoding="utf-8") as fh:
        _ss_json.dump(mark, fh, indent=1)
    print("  " + "=" * 100)
    print(f"  SEASON SWITCH: {old_l} -> {new_l}")
    print(f"    {len(moved)} {old_l} FastScout file(s) moved to {in_arch}" + (f" ({kept} were already there)" if kept else ""))
    print(f"    {copied} {old_l} table(s) copied to {out_arch} (the app's Previous Games season picker shows it)")
    print(f"    The film (uww_plays.csv, frames, tracking, models, play reviews) stays -- last season's games keep their "
          f"Film Tagging. This run reads {new_l} from FastScout.")
    print("    Commit and push the new data folder with the rest. undo_season_switch() puts the inputs back.")
    print("  " + "=" * 100, flush=True)
    return mark


def undo_season_switch():
    """Move the archived FastScout files back into INPUT_DIR and clear the switch (data_<season> is left in place)."""
    mk = _ss_read_mark()
    if not mk.get("moved"):
        print("No season switch to undo.")
        return
    n = 0
    for b in mk["moved"]:
        src = _ss_os.path.join(mk["inputs_archive"], b)
        if _ss_os.path.exists(src) and not _ss_os.path.exists(_ss_os.path.join(INPUT_DIR, b)):
            _ss_shutil.move(src, _ss_os.path.join(INPUT_DIR, b))
            n += 1
    _ss_os.replace(_SS_MARK, _SS_MARK + ".undone")
    print(f"Season switch undone: {n} file(s) moved back to {INPUT_DIR}. Set SEASON = \"{mk.get('last_season')}\" in the "
          f"first settings cell so the next run doesn't switch again.")


# ---- which season this run is on ----------------------------------------------------------------------------------
_ss_setting = str(globals().get("SEASON", "auto") or "auto").strip().lower()
_ss_have = _ss_data_season()
_ss_cal = _ss_season_of(_ss_dt.now())
if _ss_year(_ss_setting):
    _ss_want = _ss_year(_ss_setting)
else:
    _ss_want = _ss_have if _ss_have is not None else _ss_cal
    if _ss_have is not None and _ss_cal > _ss_have:
        _why = _ss_new_season_started(_ss_cal)
        if _why:
            _ss_want = _ss_cal
            print(f"SEASON = \"auto\": the {_ss_label(_ss_cal)} season has started for UWW ({_why}) -- switching to it.")
        else:
            print(f"SEASON = \"auto\": UWW hasn't played a {_ss_label(_ss_cal)} game yet -- this run stays on "
                  f"{_ss_label(_ss_have)} (every number in the brief is labeled last season). It switches by itself after "
                  f"UWW's first game; SEASON = \"{_ss_label(_ss_cal)}\" switches now.")
if _ss_have is not None and _ss_want > _ss_have:
    if not _ss_os.path.exists(_ss_os.path.join(film_pbp_dir(_ss_label(_ss_have)), "uww.pkl")):
        print("  " + "!" * 100)
        print(f"  !! Not switching to {_ss_label(_ss_want)} on THIS run: last season's play-by-play for Film Tagging hasn't "
              f"been saved yet. This run stays on {_ss_label(_ss_have)} and saves it (Play calls cell); the NEXT run switches.")
        print("  " + "!" * 100, flush=True)
        _ss_want = _ss_have
    else:
        _ss_switch(_ss_have, _ss_want)
        _ss_have = _ss_want
elif _ss_have is not None and _ss_want < _ss_have:
    print(f"  !! SEASON = \"{_ss_label(_ss_want)}\" but INPUT_DIR holds {_ss_label(_ss_have)} -- run undo_season_switch() "
          f"first to go back. This run stays on {_ss_label(_ss_have)}.")
    _ss_want = _ss_have

SEASON_START_YEAR = _ss_want
SEASON_NOW = _ss_label(_ss_want)
_ss_mk = _ss_read_mark()
LAST_SEASON = _ss_mk.get("last_season") if _ss_mk.get("season") == SEASON_NOW else None
LAST_SEASON_DATA_DIR = (_ss_mk.get("data_archive") if LAST_SEASON and _ss_os.path.isdir(_ss_mk.get("data_archive") or "")
                        else None)
if LAST_SEASON:
    # the new season's own games are on FastScout's schedule: an EXTRA_GAMES real game (not a scrimmage) is dropped, and a
    # "today" from last season is replaced by the real one
    _ss_drop = [g for g in (globals().get("EXTRA_GAMES") or [])
                if g and not _ss_re.search(r"scrimmage|exhibition", str(g.get("type") or "scrimmage"), _ss_re.I)]
    if _ss_drop:
        EXTRA_GAMES = [g for g in EXTRA_GAMES if g not in _ss_drop]
        print(f"  EXTRA_GAMES: {', '.join(str(g.get('opponent')) for g in _ss_drop)} is on the {SEASON_NOW} FastScout "
              f"schedule now -- not added as an extra game (set EXTRA_GAMES = [] in this cell).")
    _ss_ref = pd.to_datetime(str(globals().get("REFERENCE_DATE") or ""), errors="coerce")
    if pd.isna(_ss_ref) or _ss_ref < pd.Timestamp(SEASON_START_YEAR, 8, 1):
        REFERENCE_DATE = f"{_ss_dt.now().year}-{_ss_dt.now().month}-{_ss_dt.now().day}"
        print(f"  REFERENCE_DATE was before the {SEASON_NOW} season -- this run uses today ({REFERENCE_DATE}).")
print(f"Season: {SEASON_NOW}" + (f" (last season {LAST_SEASON}: {LAST_SEASON_DATA_DIR})" if LAST_SEASON else ""), flush=True)
