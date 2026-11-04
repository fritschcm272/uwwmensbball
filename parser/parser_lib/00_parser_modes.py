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
        # CONFIRMED CHANGE (requested: "parser_models needs to remove the print out and tables similar to parser_brief"):
        # one "done" line per section; everything else goes to the log. The lines you act on still show up AS THEY HAPPEN
        # (quiet_show): problems ("!!"), the Synergy export, the court calibration and the starters check.
        "quiet": True,
        # (+ the tracking scorecard and the jersey-vote test -- requested: compare the new tracking with the old)
        "quiet_show": r"!!|\[export\]|\[court\]|\[starters\]|\[scorecard\]|jersey vote \(|Starters to validate|calibrat|STOP",
        # the one updating status line: each section's steps and progress (see _PmQuietBuf)
        "quiet_status": r"\[(tracking|court|play review|tag model[^\]]*|recognizer|jersey|outfit|reid|frame archive|saves)\]|min left|so far|step \d",
    },
    "tagging": {
        "label": "New clips for Film Tagging, fast (no automatic Titles, no tracking)",
        "run": {"46_frame_capture", "47_play_calls", "50_player_tracking", "53_tag_model", "55c_play_review"},
        "flags": {"46_frame_capture": {"RUN_FRAME_CAPTURE": True},
                  "50_player_tracking": {"RUN_PLAYER_TRACKING": False},     # (its code is still needed; last results kept)
                  "53_tag_model": {"RUN_TAG_MODEL": False},                 # no automatic Titles (last ones kept)
                  "55c_play_review": {"RUN_PLAY_REVIEW": False, "RUN_TAG_QUEUE": True}},
        "save": "tagging",
        # CONFIRMED CHANGE (requested: "Does parser_tagging have a similar 'quiet' output as the parser_brief and
        # parser_models notebooks?"): one "done" line per section; everything else goes to the log. Shown as it happens:
        # problems ("!!"), the Synergy export, each game's Film Tagging result (clips to tag / left out / removed / no
        # batch) and the tagging-progress lines; the updating status line follows frame capture and the play videos.
        "quiet": True,
        "quiet_show": r"!!|\[export\]|STOP|\[film tagging\]|Film Tagging: .*(clip\(s\) to tag|left out|removed|no batch|rebuilt)"
                      r"|Film Tagging -- tagging progress|^  \d{4}-\d\d-\d\d .*clip\(s\) tagged",
        "quiet_status": r"Frame capture|\[frame archive\]|Frame archive|Film Tagging: .*(checking|reading|making the video|open batch)"
                        r"|min left|so far|step \d",
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


import io as _pm_io_mod
import time as _pm_time


class _PmQuietBuf(_pm_io_mod.StringIO):
    """Quiet mode's capture: everything is kept for the log; a line matching `show` (a regex) also goes to the notebook
    right away."""

    # CONFIRMED CHANGE (requested: "this has taken a long time -- can you make a better description"). Two things while a
    # quiet section runs: (1) ONE status line in the notebook that keeps updating in place -- the section, its current step
    # and its latest progress ("frames checked for players: 120 / 400 (30%) -- 2.1 min so far, ~5 min left"); lines that
    # match `status` (a regex) feed it. (2) The log file is written AS the section runs (it used to be written when the
    # section finished), so the log always shows where a long run is.
    def __init__(self, show=None, out=None, status=None, log=None, header=None, section=""):
        super().__init__()
        self._rx = _pm_re.compile(show) if show else None
        self._st_rx = _pm_re.compile(status) if status else None
        self._step_rx = _pm_re.compile(r"\[(?:tracking|court|play review|tag model[^\]]*|recognizer|export)\] (?:step [\w.]+:.*|[A-Z].*)")
        self._out = out
        self._part = ""
        self._section = section
        self._step = ""
        self._st_len = 0
        self._t0 = _pm_time.time()
        self._fh = None
        if log:
            try:
                self._fh = open(log, "a", encoding="utf-8")
                if header:
                    self._fh.write(header)
                    self._fh.flush()
            except Exception:
                self._fh = None

    def _status(self, text):
        if self._out is None:
            return
        el = (_pm_time.time() - self._t0) / 60
        line = f"  ... {self._section} ({el:.0f} min): {text}"[:220]
        pad = max(0, self._st_len - len(line))
        self._out.write("\r" + line + " " * pad)
        self._out.flush()
        self._st_len = len(line)

    def end_status(self):
        """Clears the status line (the 'done' line is printed in its place)."""
        if self._out is not None and self._st_len:
            self._out.write("\r" + " " * self._st_len + "\r")
            self._out.flush()
            self._st_len = 0

    def write(self, s):
        n = super().write(s)
        if self._fh is not None:
            try:
                self._fh.write(str(s))
                self._fh.flush()
            except Exception:
                pass
        if self._out is not None and (self._rx is not None or self._st_rx is not None):
            self._part += str(s)
            *lines, self._part = self._part.split("\n")
            for ln in lines:
                if self._rx is not None and self._rx.search(ln):
                    self.end_status()
                    self._out.write(ln + "\n")
                    self._out.flush()
                elif self._st_rx is not None and self._st_rx.search(ln):
                    txt = ln.strip()
                    if self._step_rx.search(ln) and "min left" not in ln and "so far" not in ln:
                        self._step = _pm_re.sub(r"^\[[^\]]+\]\s*", "", txt)[:110]
                        self._status(self._step)
                    else:
                        self._status((self._step[:60] + " | " if self._step else "")
                                     + _pm_re.sub(r"^\[[^\]]+\]\s*", "", txt))
        return n

    def finish(self):
        self.end_status()
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None


def _pm_core_fingerprint(nb, upto):
    """Everything the core sections (01-45: schedules, rosters, play-by-play, lineups ...) read: their cells' code and
    settings, their parser_lib files, the FastScout pages in INPUT_DIR (names, sizes, times), today's date."""
    import hashlib as _h
    import datetime as _dt
    parts = [str(_dt.date.today())]
    lib = globals().get("PARSER_LIB") or _pm_os.path.join(_pm_os.getcwd(), "parser_lib")
    for ci, cell in enumerate(nb["cells"][:upto]):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source") or [])
        parts.append(src)
        for sec in _pm_re.findall(r'run_section\("([^"]+)"', src):
            f = _pm_os.path.join(lib, sec if sec.endswith(".py") else sec + ".py")
            try:
                st_ = _pm_os.stat(f)
                parts.append(f"{sec}:{st_.st_size}:{int(st_.st_mtime)}")
            except OSError:
                parts.append(f"{sec}:missing")
    ind = globals().get("INPUT_DIR") or "./inputs"
    try:
        for e in sorted(_pm_os.scandir(ind), key=lambda e: e.name):
            # (left out: files the run itself rewrites every time -- caches "_*", the film tables "uww_*", and the
            # FastScout / Synergy pages saved at each login)
            if e.is_file() and not e.name.startswith(("_", "uww_", "myTeam - ", "Synergy - ")):
                st_ = e.stat()
                parts.append(f"in:{e.name}:{st_.st_size}:{int(st_.st_mtime)}")
    except OSError:
        pass
    return _h.md5("\n".join(parts).encode("utf-8", "replace")).hexdigest()


# CONFIRMED CHANGE (requested: "Is parser_models always re-training things or is it possible to set a new game, get the
# video export and apply the current models for player number tracking and film tagging? Maybe add some simple options that
# I can change in the first cell"). run_parser(..., options={...}) -- set in the job notebook's first cell:
#   TRAIN_MODELS = False   use the SAVED tag model (automatic Titles) and jersey-number reader as they are: no retraining,
#                          no new training crops. (TAG_MODEL_RETRAIN = False, JERSEY_TRAIN_NOW = False,
#                          JERSEY_TRAIN_ADD_FRAMES = False.) True / None = parser_nb's own settings ("auto").
#   ADD_GAMES = [...]      games added to PLAYER_TRACKING_GAMES for this run (same name format as the _pbp files, e.g.
#                          "11_12_25 Beloit Buccaneers @ Carroll (WI) Pioneers"): exported from Synergy, tracked, and given a
#                          Film Tagging batch (PLAY_TAG_INCLUDE_TRACKING_GAMES). Games already listed are not doubled.
# Nothing else changes: existing Film Tagging batches and saved answers are untouched. (The quick per-game pieces tracking
# learns from the coach checks each run -- referee / team colors, player look -- still run; they are part of applying.)
def _pm_apply_options(G):
    o = G.get("_PM_OPTIONS") or {}
    if o.get("TRAIN_MODELS") is False:
        G["TAG_MODEL_RETRAIN"] = False
        G["JERSEY_TRAIN_NOW"] = False
        G["JERSEY_TRAIN_ADD_FRAMES"] = False
    # CONFIRMED CHANGE (requested: "another simple option to decide if I want to do player tracking or film tagging during
    # the parser_models run"). DO_PLAYER_TRACKING = False: no tracking (the last tracks are kept), no player checks for
    # Player Number Tracking, and the jersey reader / its tests are skipped. DO_FILM_TAGGING = False: no new Film Tagging
    # batches and the open ones are left exactly as they are. Either way nothing saved is touched.
    if o.get("DO_PLAYER_TRACKING") is False:
        G["RUN_PLAYER_TRACKING"] = False
        G["RUN_PLAY_REVIEW"] = False
        G["RUN_JERSEY_RECOGNIZER"] = False
    if o.get("DO_FILM_TAGGING") is False:
        G["RUN_TAG_QUEUE"] = False
    add = o.get("ADD_GAMES") or []
    if isinstance(add, str):
        add = [add]
    add = [str(x).strip() for x in add if str(x).strip()]
    if add:
        G["PLAYER_TRACKING_GAMES"] = list(dict.fromkeys(list(G.get("PLAYER_TRACKING_GAMES") or []) + add))


_PM_TRACKING_ONLY = {"48_jersey_number_recognizer", "49_jersey_number_reader_test", "50b_detector_compare",
                     "50c_outfit_check", "50d_reid_check", "88_tracking_review_export"}


def run_parser(mode, start_at=None, stop_after=None, notebook="parser_nb.ipynb", quiet=None, fresh=False, options=None):
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
    G["_PM_OPTIONS"] = dict(options or {})
    if G["_PM_OPTIONS"]:
        _o = G["_PM_OPTIONS"]
        print("Options: " + ("models NOT retrained (saved tag model + jersey reader used as they are)"
                             if _o.get("TRAIN_MODELS") is False else "models retrain as parser_nb says")
              + (f"; games added to Player Number Tracking + Film Tagging: {', '.join(map(str, [_o['ADD_GAMES']] if isinstance(_o.get('ADD_GAMES'), str) else _o.get('ADD_GAMES')))}"
                 if _o.get("ADD_GAMES") else "")
              + ("; player tracking OFF" if _o.get("DO_PLAYER_TRACKING") is False else "")
              + ("; Film Tagging OFF" if _o.get("DO_FILM_TAGGING") is False else ""), flush=True)
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
    # CONFIRMED CHANGE (requested: "does parser_models really need to run all of the cells through 44 ... when it is being
    # run for a game that stopped at court calibration? nothing should change for the same game"). The core sections
    # (01-45) are skipped when THIS notebook session already ran them and nothing they read has changed since: their cells
    # and settings, their code, the FastScout pages in INPUT_DIR, the date (_pm_core_fingerprint). Their results are still in
    # memory, exactly as after a start_at. A restarted kernel has nothing in memory, so it runs them; run_parser(...,
    # fresh=True) forces them.
    _first_model = next((ci for ci, c in enumerate(nb["cells"]) if c.get("cell_type") == "code" and any(
        (_pm_num(x) is not None and _pm_num(x) > _PM_CORE_MAX) or x in _PM_MODEL
        for x in _pm_re.findall(r'run_section\("([^"]+)"', "".join(c.get("source") or [])))), len(nb["cells"]))
    _core_fp = _pm_core_fingerprint(nb, _first_model) if start_at is None else None
    _skip_core = bool(start_at is None and not fresh and G.get("_pm_core_ok") and G.get("_pm_core_fp") == _core_fp
                      and "run_section" in G)
    if _skip_core:
        print("(sections 01-45 skipped: this session already ran them and nothing they read has changed -- "
              "run_parser(..., fresh=True) runs them again)", flush=True)
    elif start_at is None:
        G["_pm_core_ok"] = False
    for ci, cell in enumerate(nb["cells"]):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source") or [])
        secs = _pm_re.findall(r'run_section\("([^"]+)"', src)
        is_setup = "def run_section(" in src
        if start_at is None and ci >= _first_model and not G.get("_pm_core_ok"):
            # the core cells all ran: remember what they read, as it is NOW (they save the pages they scrape)
            G["_pm_core_ok"], G["_pm_core_fp"] = True, _pm_core_fingerprint(nb, _first_model)
        if _skip_core and ci < _first_model and not is_setup:
            continue
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
            _buf = _PmQuietBuf(plan.get("quiet_show"), _real_out, status=plan.get("quiet_status"), log=_log,
                               header=f"\n===== cell {ci} {', '.join(secs)} =====\n", section=", ".join(secs) or f"cell {ci}")
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
                _buf.finish()                               # (the log was written as the section ran)
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
                        if not _pm_wanted(m, base) or (base in _PM_TRACKING_ONLY and
                                                       (G.get("_PM_OPTIONS") or {}).get("DO_PLAYER_TRACKING") is False):
                            _skipped.append(base)
                            return None
                        for k, v in PARSER_MODES[m]["flags"].get(base, {}).items():
                            G[k] = v
                        _pm_apply_options(G)                 # the job notebook's first-cell options (see above)
                    G["_pm_depth"] = depth + 1
                    _q, _out = G.get("_pm_quiet") or (False, None)
                    _t0 = _pm_time.time()
                    _mark = _pm_sys.stdout.tell() if _q and depth == 0 and hasattr(_pm_sys.stdout, "tell") else None
                    _cb = _pm_sys.stdout if isinstance(_pm_sys.stdout, _PmQuietBuf) else None
                    if _cb is not None and depth == 0:
                        _cb._section, _cb._step, _cb._t0 = base, "", _pm_time.time()   # the status line names this section
                        _cb._status("starting")
                    try:
                        r_ = _orig(name)
                    finally:
                        G["_pm_depth"] = depth
                    if _q and depth == 0 and _out is not None:
                        if _cb is not None:
                            _cb.end_status()
                        _probs = []
                        if PARSER_MODES.get(m or "", {}).get("quiet_show"):
                            _mark = None                       # (already shown as they happened)
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
