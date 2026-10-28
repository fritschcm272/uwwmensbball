# 00_parser_modes.py -- run ONLY the parts of the parser a job needs (requested: "separate the parser notebooks into different
# notebooks based on what I need to accomplish without it needing to run every single thing").
#
# The three small notebooks next to parser_nb.ipynb each run one of these:
#   parser_models.ipynb  -> run_parser("models")   make the models better: frame capture, jersey-number reader, player
#                                                   tracking (starters checks, player checks), court calibration, the tag
#                                                   model (automatic Titles), the Play review / Film Tagging batches.
#                                                   No scouting brief.
#   parser_tagging.ipynb -> run_parser("tagging")  new clips for the coaches to tag, fast: frame capture + play calls + the
#                                                   Film Tagging batches. No tag model (automatic Titles), no tracking.
#   parser_brief.ipynb   -> run_parser("brief")    the scouting brief and the app's data for the upcoming opponent, from
#                                                   everything done before: no capture, no tracking, no model training --
#                                                   the last run's tracking / court / automatic-Title results are reused.
#
# How it works: it runs parser_nb.ipynb's own cells, in order, with the settings saved in that notebook (change a setting
# THERE and save it -- one place for every setting). Sections a job doesn't need are skipped, and the slow steps a job doesn't
# need are switched off (their last results are put back -- nothing is lost). The full notebook still runs everything.
#
# After a stop (court calibration, starters check) or an error, continue from a section without redoing the ones above it:
#   run_parser("models", start_at="50_player_tracking")
import json as _pm_json
import re as _pm_re
import os as _pm_os

# the sections every job needs: schedules, rosters, play-by-play, lineups, ... (01-45)
_PM_CORE_MAX = 45
_PM_MODEL = {"46_frame_capture", "47_play_calls", "48_jersey_number_recognizer", "49_jersey_number_reader_test",
             "50c_outfit_check", "50d_reid_check", "50_player_tracking", "50b_detector_compare", "51_court_mapping",
             "53_tag_model", "54_tracking_insights", "55_court_insights", "55c_play_review", "55d_defensive_roles",
             "55e_film_quality", "88_tracking_review_export", "46a_frame_archive", "89_cleanup", "90_model_versions"}

PARSER_MODES = {
    "models": {
        "label": "Make the models better (tracking, court, jersey numbers, automatic Titles, checks for the app)",
        "run": _PM_MODEL,
        "flags": {},                                                        # the notebook's own settings
        "save": "models",
    },
    "tagging": {
        "label": "New clips for Film Tagging, fast (no automatic Titles, no tracking)",
        "run": {"46_frame_capture", "47_play_calls", "50_player_tracking", "53_tag_model", "55c_play_review"},
        "flags": {"46_frame_capture": {"RUN_FRAME_CAPTURE": True},
                  "50_player_tracking": {"RUN_PLAYER_TRACKING": False},     # (its code is still needed; last results kept)
                  "53_tag_model": {"RUN_TAG_MODEL": False},                 # no automatic Titles (last ones kept)
                  "55c_play_review": {"RUN_PLAY_REVIEW": False, "RUN_TAG_QUEUE": True}},
        "save": "tagging",
    },
    "brief": {
        "label": "Scouting brief + app data for the upcoming opponent, from everything done before",
        "run": {"46_frame_capture", "47_play_calls", "50_player_tracking", "51_court_mapping", "53_tag_model",
                "54_tracking_insights", "55_court_insights", "55c_play_review", "55d_defensive_roles", "55e_film_quality",
                "90_model_versions", "*brief*"},
        "flags": {"46_frame_capture": {"RUN_FRAME_CAPTURE": False},       # loads the captured clips, captures nothing
                  "50_player_tracking": {"RUN_PLAYER_TRACKING": False},
                  "51_court_mapping": {"RUN_COURT_MAPPING": False},
                  "53_tag_model": {"RUN_TAG_MODEL": False},
                  "55c_play_review": {"RUN_PLAY_REVIEW": False, "RUN_TAG_QUEUE": False}},
        "save": None,                                                       # section 80 exports everything
    },
}


def _pm_num(name):
    m = _pm_re.match(r"^(\d+)", str(name))
    return int(m.group(1)) if m else None


def _pm_wanted(mode, section):
    """Does this job run this section?"""
    plan = PARSER_MODES[mode]
    n = _pm_num(section)
    if n is not None and n <= _PM_CORE_MAX and section not in _PM_MODEL:
        return True                                                        # 01-45: every job
    if section in plan["run"]:
        return True
    if "*brief*" in plan["run"] and n is not None and 56 <= n <= 87:
        return True                                                        # the brief sections 56-87
    return False


def _pm_save(kind):
    """The models / tagging jobs skip the brief's export (section 80): their own results are written here instead."""
    d = globals().get("APP_DATA_DIR") or OUTPUT_DIR
    tabs = {"uww_play_calls": globals().get("play_calls")}
    if kind == "models":
        tabs.update({"uww_player_tracks": globals().get("player_tracks"),
                     "uww_tracking_report": globals().get("tracking_report"),
                     "uww_trk_event_candidates": globals().get("trk_event_candidates"),
                     "uww_trk_lineup_slots": globals().get("trk_lineup_slots"),
                     "uww_tag_model_report": globals().get("tag_model_report")})
        tabs.update(globals().get("_ti_tables") or {})
        tabs.update(globals().get("_cz_tables") or {})
    n = 0
    for name, df in tabs.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue                                                       # nothing new: the last file stays
        try:
            df.to_csv(_pm_os.path.join(d, f"{name}.csv"), index=False)
            n += 1
        except Exception as e:
            print(f"  [{kind}] {name}.csv not saved ({type(e).__name__}: {e})", flush=True)
    print(f"[{kind}] saved {n} table(s) to {d} -- commit and push the data folder for the app", flush=True)


def run_parser(mode, start_at=None, stop_after=None, notebook="parser_nb.ipynb"):
    """Run parser_nb.ipynb's cells for one job: "models", "tagging" or "brief" (see the top of this file).
    start_at = a section name ("50_player_tracking") to continue from after a stop -- the sections above it are not run
    again (their results are still in this notebook's memory from the earlier run). stop_after = a section to stop after."""
    if mode not in PARSER_MODES:
        raise ValueError(f"mode must be one of {list(PARSER_MODES)}")
    G = globals()
    plan = PARSER_MODES[mode]
    with open(notebook, encoding="utf-8") as fh:
        nb = _pm_json.load(fh)
    print(f"=== {mode.upper()}: {plan['label']} ===", flush=True)
    started = start_at is None
    if not started and "run_section" not in G:
        raise RuntimeError("start_at needs an earlier run in this notebook (run it once without start_at first)")
    _skipped = []
    G["_pm_depth"] = 0
    for ci, cell in enumerate(nb["cells"]):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source") or [])
        secs = _pm_re.findall(r'run_section\("([^"]+)"', src)
        is_setup = "def run_section(" in src
        if not started:
            if start_at in secs:
                started = True
            elif not is_setup:
                continue
        lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith(("%", "!"))]   # no shell / magic lines
        code = "\n".join(lines)
        if not code.strip():
            continue
        exec(compile(code, f"<{notebook} cell {ci}>", "exec"), G)
        if is_setup:
            # the notebook's run_section, wrapped: a section this job doesn't need is skipped, and the job's switches are
            # set right before a section runs (after its cell's own settings)
            _orig = G["run_section"]
            if not getattr(_orig, "_pm_wrapped", False):
                def _run_section(name, _orig=_orig):
                    base = _pm_os.path.basename(str(name))[:-3] if str(name).endswith(".py") else str(name)
                    m = G.get("_PARSER_MODE")
                    depth = G.get("_pm_depth", 0)
                    if depth == 0 and m:                 # (a section that runs another one -- e.g. the frame hooks -- always does)
                        if not _pm_wanted(m, base):
                            _skipped.append(base)
                            return None
                        for k, v in PARSER_MODES[m]["flags"].get(base, {}).items():
                            G[k] = v
                    G["_pm_depth"] = depth + 1
                    try:
                        return _orig(name)
                    finally:
                        G["_pm_depth"] = depth
                _run_section._pm_wrapped = True
                G["run_section"] = _run_section
            G["_PARSER_MODE"] = mode
        if stop_after and stop_after in secs:
            break
    if not started:
        raise ValueError(f"start_at={start_at!r}: no cell in {notebook} runs that section")
    if plan.get("save"):
        _pm_save(plan["save"])
    if _skipped:
        print(f"[{mode}] skipped {len(_skipped)} section(s) this job doesn't need: " + ", ".join(_skipped), flush=True)
