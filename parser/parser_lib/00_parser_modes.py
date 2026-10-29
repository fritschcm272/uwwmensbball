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
        "quiet": True,                                                      # one "done" line per section (see run_parser)
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


def run_parser(mode, start_at=None, stop_after=None, notebook="parser_nb.ipynb", quiet=None):
    """Run parser_nb.ipynb's cells for one job: "models", "tagging" or "brief" (see the top of this file).
    start_at = a section name ("50_player_tracking") to continue from after a stop -- the sections above it are not run
    again (their results are still in this notebook's memory from the earlier run). stop_after = a section to stop after.
    CONFIRMED CHANGE (requested: "for the parser_brief, can we only print out when each cell is done instead of printing out the
    stuff from the cell?"): quiet (the brief's default; quiet=False shows everything) prints one line per section when it's
    done -- with its time and any "!!" problem lines -- and writes everything else to a log file
    (inputs/_logs/<job>_<date>.log). If a section fails, the last lines it printed are shown with the error."""
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
    import io as _pm_io
    import sys as _pm_sys
    import time as _pm_time
    import contextlib as _pm_ctx
    quiet = plan.get("quiet", False) if quiet is None else bool(quiet)
    _real_out = _pm_sys.stdout
    _log = None
    if quiet:
        _ld = _pm_os.path.join(G.get("INPUT_DIR") or "./inputs", "_logs")
        _pm_os.makedirs(_ld, exist_ok=True)
        _log = _pm_os.path.join(_ld, f"{mode}_{_pm_time.strftime('%Y%m%d_%H%M%S')}.log")
        print(f"(quiet: one line per section; everything else goes to {_log})", flush=True)
    G["_pm_quiet"] = (quiet, _real_out)
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
        if not quiet:
            exec(compile(code, f"<{notebook} cell {ci}>", "exec"), G)
        else:
            _buf = _pm_io.StringIO()
            _disp = G.get("display")
            _to_log = lambda *a, **k: _buf.write("".join(str(x) for x in a) + "\n")       # tables go to the log too
            G["display"] = _to_log
            # CONFIRMED BUG (fixed; "I'm still getting some printouts of tables in the parser_brief"): _show() (01) draws
            # tables with IPython's own display(), imported inside the call -- that bypassed the swap above and went
            # straight to the notebook. IPython's display() is swapped too while a quiet cell runs.
            _ipy_mods, _ipy_old = [], []
            for _mn in ("IPython.display", "IPython.core.display_functions", "IPython.core.display"):
                _m = _pm_sys.modules.get(_mn)
                if _m is not None and hasattr(_m, "display"):
                    _ipy_mods.append(_m)
                    _ipy_old.append(_m.display)
                    _m.display = _to_log
            try:
                with _pm_ctx.redirect_stdout(_buf), _pm_ctx.redirect_stderr(_buf):
                    exec(compile(code, f"<{notebook} cell {ci}>", "exec"), G)
            except BaseException:
                _tail = _buf.getvalue().splitlines()[-60:]
                _real_out.write("\n".join(["--- the last lines it printed ---"] + _tail) + "\n")
                _real_out.flush()
                raise
            finally:
                for _m, _o in zip(_ipy_mods, _ipy_old):
                    _m.display = _o
                if _disp is not None:
                    G["display"] = _disp
                else:
                    G.pop("display", None)
                with open(_log, "a", encoding="utf-8") as _fh:
                    _fh.write(f"\n===== cell {ci} {', '.join(secs)} =====\n" + _buf.getvalue())
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
                    _q, _out = G.get("_pm_quiet") or (False, None)
                    _t0 = _pm_time.time()
                    _mark = _pm_sys.stdout.tell() if _q and depth == 0 and hasattr(_pm_sys.stdout, "tell") else None
                    try:
                        r_ = _orig(name)
                    finally:
                        G["_pm_depth"] = depth
                    if _q and depth == 0 and _out is not None:
                        _probs = []
                        if _mark is not None and hasattr(_pm_sys.stdout, "getvalue"):
                            _probs = [ln.strip() for ln in _pm_sys.stdout.getvalue()[_mark:].splitlines() if "!!" in ln][:5]
                        _out.write(f"done  {base}  ({_pm_time.time() - _t0:.0f} s)\n"
                                   + "".join(f"      {ln}\n" for ln in _probs))
                        _out.flush()
                    return r_
                _run_section._pm_wrapped = True
                G["run_section"] = _run_section
            G["_PARSER_MODE"] = mode
        if stop_after and stop_after in secs:
            break
    if not started:
        raise ValueError(f"start_at={start_at!r}: no cell in {notebook} runs that section")
    if plan.get("save"):
        _pm_save(plan["save"])
    if quiet:
        G["_pm_quiet"] = (False, None)
        print(f"[{mode}] finished -- everything the sections printed is in {_log}", flush=True)
    if _skipped:
        print(f"[{mode}] skipped {len(_skipped)} section(s) this job doesn't need: " + ", ".join(_skipped), flush=True)
