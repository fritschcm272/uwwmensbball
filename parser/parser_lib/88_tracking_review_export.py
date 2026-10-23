# 88_tracking_review_export.py -- code for the notebook section "Tracking review export (requested: a permanent version of the review export, instead of pa"
# Runs inside the notebook via run_section("88_tracking_review_export"); its settings are in that notebook cell.

# --- Tracking review export (requested: a permanent version of the review export, instead of pasting code) ------
import zipfile, io

# ---- cache files that survive a full disk (shared helper; the same copy is in every section that uses them) ---------
# CONFIRMED BUG (fixed; "Jersey-number recognizer skipped: EOFError: Ran out of input", and tracking's "jersey numbers not
# read this run (EOFError ...)"): a run that filled the disk left a cache file empty / cut short, and loading it stopped the
# section. A damaged cache is now set aside as "<name>.broken" (it's rebuilt), and caches are written to a temporary file
# first and swapped in only when complete, so a full disk can no longer leave a half-written cache behind.
def _safe_read_pickle(path, default=None):
    try:
        return pd.read_pickle(path)
    except Exception as _e:
        try:
            if os.path.isfile(path):
                os.replace(path, path + ".broken")
        except Exception:
            pass
        print(f"  [cache] {os.path.basename(str(path))} was damaged ({type(_e).__name__}) -- set aside as .broken and "
              f"rebuilt (a disk that filled up mid-save does this)", flush=True)
        return {} if default is None else default


def _safe_read_latest(paths, default=None):
    """The newest readable file of several (e.g. detections_*.pkl), newest first; damaged ones are set aside."""
    for p_ in sorted(paths, key=lambda q: os.path.getmtime(q) if os.path.exists(q) else 0, reverse=True):
        d_ = _safe_read_pickle(p_, default=False)
        if d_ is not False:
            return d_
    return {} if default is None else default


def _safe_to_pickle(obj, path):
    if not isinstance(path, (str, bytes, os.PathLike)):
        return pd.to_pickle(obj, path)                    # an in-memory buffer
    root, ext = os.path.splitext(str(path))
    tmp = f"{root}.tmp{ext}"
    try:
        pd.to_pickle(obj, tmp)
    except OSError as _e:
        try:
            os.remove(tmp)
        except Exception:
            pass
        print(f"  [cache] {os.path.basename(str(path))} NOT saved ({type(_e).__name__}: {_e}) -- free disk space; the "
              f"previous copy is kept", flush=True)
        return
    # CONFIRMED BUG (fixed; "PermissionError: [WinError 5] Access is denied: ...jersey_numbers.tmp.pkl -> jersey_numbers.pkl"):
    # on Windows, OneDrive or antivirus holds a file open for a moment while it syncs / scans it, and swapping the new copy in
    # fails then. It's retried for a few seconds; if the file stays locked, it's written in place instead.
    import time as _sp_time
    for _try in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            _sp_time.sleep(0.25 * (_try + 1))
        except OSError:
            break
    try:
        pd.to_pickle(obj, path)
    except OSError as _e:
        print(f"  [cache] {os.path.basename(str(path))} NOT saved -- the file is locked by another program (OneDrive sync or "
              f"antivirus?) ({type(_e).__name__}); the previous copy is kept and it's saved again on the next save", flush=True)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass



if EXPORT_TRACKING_REVIEW:
    try:
        for _c in ("track_files", "frame_files", "clip_number", "game_code", "track_clip_key"):
            if _c not in play_calls.columns:
                play_calls[_c] = None
        _pc = play_calls[play_calls["track_files"].notna()
                         & play_calls["game_code"].astype(str).str.contains(REVIEW_GAME, regex=False)]
        _pc = _pc.sort_values("clip_number").head(REVIEW_POSSESSIONS)
        _keys = set(_pc["track_clip_key"])
        _files = [f for col in ("track_files", "frame_files") for v in _pc[col].dropna() for f in v.split(";") if f]
        _out = os.path.join(INPUT_DIR, "tracking_review_first5.zip")

        def _subset_pickle(pattern, keep):
            for p in glob.glob(os.path.join(TRACK_DIR, pattern)):
                d = _safe_read_pickle(p)
                buf = io.BytesIO()
                _safe_to_pickle({k: v for k, v in d.items() if k in keep or k == "_sig"
                              or (isinstance(k, str) and k.split("|")[0] in keep)}, buf)
                yield os.path.basename(p), buf.getvalue()

        if "vision_frames_ensure" in globals():
            vision_frames_ensure([os.path.join(VISION_FRAMES_DIR, f) for f in _files])     # archived clips -> JPEGs
        with zipfile.ZipFile(_out, "w", zipfile.ZIP_DEFLATED) as z:
            # CONFIRMED BUG (fixed; "FileNotFoundError: [WinError 3] ... Jan_2_2026_UWOshkosh@UWWhitewater/track1024v2/
            # 1_1450ff05_t000.jpg"): a frame in a game folder moved to the F: drive looked present, but the zip read it from
            # _vision_frames. The real file is used now (vision_real_path, section 46a); a frame that can't be found is
            # counted and skipped instead of stopping the export.
            _real_of = globals().get("vision_real_path") or (lambda p: p if os.path.isfile(p) else None)
            _n_miss = 0
            for f in _files:
                _src = _real_of(os.path.join(VISION_FRAMES_DIR, f))
                if _src:
                    try:
                        z.write(_src, "frames/" + f)
                        continue
                    except OSError:
                        pass
                _n_miss += 1
            if _n_miss:
                print(f"  ({_n_miss} of {len(_files)} frame(s) not on disk -- left out of the export)", flush=True)
            z.writestr("play_calls.csv", _pc.to_csv(index=False))
            _sl = globals().get("trk_lineup_slots", pd.DataFrame())
            if isinstance(_sl, pd.DataFrame) and not _sl.empty:
                z.writestr("lineup_slots.csv", _sl[_sl["clip_key"].isin(_keys)].to_csv(index=False))
            # CONFIRMED BUG (fixed): "Tracking review export skipped: KeyError: 'clip_key'" when Player tracking produced
            # no tracks -- the export now still packs the frames and tables and says so.
            _pt = player_tracks if isinstance(globals().get("player_tracks"), pd.DataFrame) else pd.DataFrame()
            if _pt.empty or "clip_key" not in _pt.columns:
                print("  (no player tracks to export -- check the Player tracking printout above)")
                _pt = pd.DataFrame(columns=["clip_key", "track", "path"])
            z.writestr("player_tracks.csv", _pt[_pt["clip_key"].isin(_keys)].to_csv(index=False))
            for _nm in ("tracking_report", "court_report"):
                _t = globals().get(_nm)
                z.writestr(f"{_nm}.csv", _t.to_csv(index=False) if isinstance(_t, pd.DataFrame) else "")
            if isinstance(globals().get("clip_frames"), pd.DataFrame):
                z.writestr("clip_frames.csv", clip_frames.to_csv(index=False))   # the capture log: starts, errors
            z.writestr("rosters.json", json.dumps(_pl_jersey_book()))
            for pat in ("detections_*.pkl", "pose_*.pkl", "court_homographies.pkl", "jersey_numbers.pkl"):
                for name, data in _subset_pickle(pat, set(_files)):
                    z.writestr("saved/" + name, data)
            for f in glob.glob(os.path.join(COURT_CAL_DIR, "court_calibration_*.json")):
                z.write(f, "calibration/" + os.path.basename(f))
            for f in glob.glob(os.path.join(TRACK_DIR, "checks", "*.jpg")):
                z.write(f, "checks/" + os.path.basename(f))
            # EVERY play-by-play event candidate in the game (not just these possessions): 4 of its tallest crops each,
            # named <n>_<event>_<name>_c<clip>_t<track>_<k>.jpg, plus the table -- for checking the event names by eye
            _ec = globals().get("trk_event_candidates", pd.DataFrame())
            if isinstance(_ec, pd.DataFrame) and not _ec.empty and len(_pt):
                from PIL import Image as _Im
                z.writestr("event_candidates.csv", _ec.to_csv(index=False))
                _detp = _trk_det_cache_path()
                _det = _safe_read_pickle(_detp) if os.path.exists(_detp) else {}
                _files_of = dict(zip(play_calls["track_clip_key"], play_calls["track_files"]))
                for _n, _r in _ec.reset_index(drop=True).iterrows():
                    _row = _pt[(_pt["clip_key"] == _r["clip_key"]) & (_pt["track"] == _r["track"])]
                    _fl = str(_files_of.get(_r["clip_key"], "")).split(";")
                    if _row.empty:
                        continue
                    _items = []
                    for _p in json.loads(_row.iloc[0]["path"]):
                        if len(_p) < 6 or int(_p[0]) >= len(_fl) or _fl[int(_p[0])] not in _det or not len(_det[_fl[int(_p[0])]]["p"]):
                            continue
                        _d = _det[_fl[int(_p[0])]]["p"]
                        _j = int(np.argmin(np.hypot((_d[:, 0] + _d[:, 2]) / 2 - _p[4], _d[:, 3] - _p[5])))
                        _items.append((_d[_j, 3] - _d[_j, 1], _fl[int(_p[0])], _d[_j, :4]))
                    for _k, (_h, _f, (_x1, _y1, _x2, _y2)) in enumerate(sorted(_items, key=lambda q: -q[0])[:4]):
                        try:
                            _im = _Im.open(os.path.join(VISION_FRAMES_DIR, _f)).convert("RGB").crop(
                                (int(_x1) - 2, int(_y1) - 2, int(_x2) + 2, int(_y2) + 2))
                            _b = io.BytesIO()
                            _im.save(_b, "JPEG", quality=90)
                            _nm = re.sub(r"[^A-Za-z]+", "", str(_r["name"]))
                            z.writestr(f"event_candidates/{_n:03d}_{_r['event']}_{_nm}_c{_r['clip_number']}_t{_r['track']}_{_k}.jpg",
                                       _b.getvalue())
                        except Exception:
                            pass
        print(f"Tracking review export: {_out} ({os.path.getsize(_out) // 1024:,} KB) -- upload this file for a review.")
    except Exception as _e:
        print(f"Tracking review export skipped: {type(_e).__name__}: {_e}")
