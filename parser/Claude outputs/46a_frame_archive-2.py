# 46a_frame_archive.py -- code for the notebook sections "Frame archive (hooks)" and "Frame archive: pack finished games"
# Runs inside the notebook via run_section("46a_frame_archive"); its settings are in those notebook cells.
#
# CONFIRMED CHANGE (requested: "_vision_frames ... is getting extremely large for each game" -> "Archive finished games").
# A finished game's TRACKING frames (track1024v2/, track1280v2/ -- ~3 GB a game as JPEGs) are packed into ONE video per clip
# (<clip>.mp4, H.264 at FRAME_ARCHIVE_CRF -- visually the same picture, ~10-20x smaller) plus a list of which frame is which
# (_archive.json in that folder). The JPEGs are then deleted, EXCEPT the frames anything still points at directly:
#   * frames with a coach check on them (player checks -- the jersey reader's answer key and training crops)
#   * frames your court calibration uses
# Nothing else changes. When any step reads an archived frame -- a rerun of tracking, a Play review or Film Tagging batch,
# the reader test -- the whole clip is unpacked back to its JPEGs automatically (the "hooks" installed below: cv2.imread,
# PIL Image.open, os.path.exists / getsize see archived frames as present). The 5 tag-model frames per clip are never
# archived (they're small).
#
# A game is "finished" when it isn't part of the current run (see _fa_current_run), OR when: every clip with tracking frames
# has been tracked (player tracks exist for it), it has no open Play review or Film Tagging batch in the app data folder, and
# no more than FRAME_ARCHIVE_MAX_UNTAGGED of its clips are still Untagged. FRAME_ARCHIVE_GAMES:
# "finished" (default), a list of game folder names under _vision_frames (archive exactly those), or [] (off).
# FRAME_RESTORE_GAMES: game folder names to unpack back to JPEGs for good (e.g. to recapture or re-check a whole game).

import glob
import json
import os
import re
import time

_FA_INDEX_NAME = "_archive.json"


# ---- The index: every archived frame -> (its clip video, frame number) -------------------------------------------------
def _fa_norm(p):
    return os.path.normcase(os.path.abspath(str(p)))


def _fa_load_index():
    """{normalized frame path: (video path, frame number, manifest path, clip)} for every archived clip on disk."""
    idx = {}
    base = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    for man in glob.glob(os.path.join(base, "*", "track*", _FA_INDEX_NAME)):
        try:
            with open(man, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        folder = os.path.dirname(man)
        for clip, info in (d.get("clips") or {}).items():
            vid = os.path.join(folder, info["video"])
            for k, name in enumerate(info.get("frames", [])):
                idx[_fa_norm(os.path.join(folder, name))] = (vid, k, man, clip)
    globals()["_fa_index"] = idx
    return idx


def _fa_lookup(p):
    idx = globals().get("_fa_index")
    if not idx:
        return None
    try:
        return idx.get(_fa_norm(p))
    except Exception:
        return None


def _fa_restore_clip(video, man, clip):
    """Unpack one archived clip back to its JPEG files (the ones missing). -> number of frames written."""
    import cv2
    import imageio.v2 as imageio
    with open(man, encoding="utf-8") as fh:
        info = json.load(fh)["clips"][clip]
    folder = os.path.dirname(man)
    names = info.get("frames", [])
    q = int(globals().get("FRAME_ARCHIVE_RESTORE_JPEG", 95))
    n = 0
    rd = imageio.get_reader(video)
    try:
        for k, fr in enumerate(rd):
            if k >= len(names):
                break
            dst = os.path.join(folder, names[k])
            if _FA_ORIG["exists"](dst):
                continue
            _FA_ORIG["imwrite"](dst, cv2.cvtColor(fr, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q])
            n += 1
    finally:
        rd.close()
    globals()["_fa_restored"] = globals().get("_fa_restored", 0) + n
    return n


def vision_frames_ensure(paths):
    """Make sure these frame files exist as JPEGs (unpacking their archived clips if needed). -> number unpacked."""
    done, n = set(), 0
    for p in paths:
        if _fx_lookup(p) is not None and not _FA_ORIG["exists"](p):
            n += bool(_fx_write(p))                       # a frame of a Synergy export: written from its clip video
            continue
        hit = _fa_lookup(p)
        if hit is None or _FA_ORIG["exists"](p):
            continue
        vid, _k, man, clip = hit
        if (man, clip) in done:
            continue
        done.add((man, clip))
        try:
            n += _fa_restore_clip(vid, man, clip)
        except Exception as e:
            print(f"  [frame archive] couldn't unpack {os.path.basename(vid)}: {type(e).__name__}: {e}", flush=True)
    return n


def vision_frame_archived(p):
    """True when this frame is packed in its clip video right now (not on disk as a JPEG) -- steps that only make
    optional pictures skip such clips instead of unpacking them."""
    return _fa_lookup(p) is not None and not _FA_ORIG["exists"](p)


# ---- Frames read straight from a game's Synergy export (no JPEGs on disk) ---------------------------------------------------
# CONFIRMED CHANGE (requested: "build everything to use these [Synergy Editor exports] instead of the web scraping"). A game
# exported from Synergy Editor (1080p, 30 frames a second, one .mp4 per clip, see section 46) gets its tracking frames named
# exactly like captured ones (<game>/track1920v2/<clip>_t000.jpg ...), but they are NOT written to disk: <track folder>/
# _export.json says which clip video and which video frame each one is. The hooks below hand any step that reads such a frame
# (cv2.imread, PIL Image.open) the picture decoded straight from the clip video, at the game's tracking width; os.path.exists
# sees it as present. A step that needs the actual file (a copy, a web page) calls vision_frames_ensure() first, which writes
# those JPEGs. Disk cost: the export itself (~3 GB a game) and nothing per frame.
_FX_INDEX_NAME = "_export.json"


def _fx_load_index():
    """{normalized frame path: (clip video, video frame number, width)} for every export-backed frame on disk."""
    idx, clips = {}, {}
    base = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    for man in glob.glob(os.path.join(base, "*", "track*", _FX_INDEX_NAME)):
        try:
            with open(man, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        folder = os.path.dirname(man)
        for clip, info in (d.get("clips") or {}).items():
            vid = os.path.normpath(os.path.join(folder, info["video"]))
            w = int(info.get("w") or 0)
            for name, k in zip(info.get("frames", []), info.get("src", [])):
                idx[_fa_norm(os.path.join(folder, name))] = (vid, int(k), w)
            clips[(vid, w)] = sorted(set(int(k) for k in info.get("src", [])))
    globals()["_fx_index"] = idx
    globals()["_fx_clips"] = clips
    return idx


def _fx_lookup(p):
    idx = globals().get("_fx_index")
    if not idx:
        return None
    try:
        return idx.get(_fa_norm(p))
    except Exception:
        return None


def _fx_clip_cache(video, w, need):
    """All of a clip's tracking frames, decoded ONCE and kept as compressed pictures (JPEG 95, ~0.3 MB each at 1920) for the
    last few clips -- steps that jump around inside a clip (player fingerprints, review pictures) don't decode it again."""
    import cv2
    from collections import OrderedDict
    st = globals().setdefault("_fx_cc", OrderedDict())
    key = (video, w)
    if key in st:
        st.move_to_end(key)
        return st[key]
    want, got = set(need), {}
    c = cv2.VideoCapture(video)
    if not c.isOpened():
        return None
    last, i, top = None, 0, max(want)
    q = [cv2.IMWRITE_JPEG_QUALITY, int(globals().get("FRAME_ARCHIVE_RESTORE_JPEG", 95))]
    try:
        while i <= top:
            if i in want:
                ok, fr = c.read()
                if not ok:
                    break
                if w and fr.shape[1] > w:
                    fr = cv2.resize(fr, (int(w), int(round(fr.shape[0] * w / fr.shape[1]))), interpolation=cv2.INTER_AREA)
                ok, buf = cv2.imencode(".jpg", fr, q)
                got[i] = last = buf
            elif not c.grab():
                break
            i += 1
    finally:
        c.release()
    for k in want:                                       # asked past the clip's last frame: its last frame
        got.setdefault(k, last)
    st[key] = got
    while len(st) > int(globals().get("FRAME_EXPORT_CLIP_CACHE", 4)):
        st.popitem(last=False)
    return got


def _fx_decode(video, k, w):
    """Frame k of a clip video (BGR), shrunk to width w. A tracking frame comes from its clip's cache (the clip is decoded
    once); any other frame (the tag-model frames when a game is registered) is read forward from the open video."""
    import cv2
    from collections import OrderedDict
    need = (globals().get("_fx_clips") or {}).get((video, w))
    if need and k in need:
        got = _fx_clip_cache(video, w, need)
        buf = got.get(k) if got else None
        if buf is not None:
            return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    st = globals().setdefault("_fx_state", {"caps": OrderedDict(), "memo": OrderedDict()})
    key = (video, k, w)
    if key in st["memo"]:
        st["memo"].move_to_end(key)
        return st["memo"][key].copy()
    cap = st["caps"].get(video)
    if cap is None or k < cap["next"]:
        if cap is not None:
            cap["cap"].release()
        c = cv2.VideoCapture(video)
        if not c.isOpened():
            return None
        cap = st["caps"][video] = {"cap": c, "next": 0, "last": None}
        while len(st["caps"]) > 3:
            _v, old = st["caps"].popitem(last=False)
            old["cap"].release()
    st["caps"].move_to_end(video)
    c = cap["cap"]
    while cap["next"] < k:
        if not c.grab():
            break
        cap["next"] += 1
    ok, fr = c.read()
    if ok:
        cap["next"] += 1
        cap["last"] = fr
    else:
        fr = cap["last"]                                  # asked past the clip's last frame: its last frame
        if fr is None:
            return None
    if w and fr.shape[1] > w:
        fr = cv2.resize(fr, (int(w), int(round(fr.shape[0] * w / fr.shape[1]))), interpolation=cv2.INTER_AREA)
    st["memo"][key] = fr
    while len(st["memo"]) > 24:
        st["memo"].popitem(last=False)
    return fr.copy()


def _fx_write(p):
    """Write one export-backed frame to disk as a JPEG (for steps that need the file itself)."""
    import cv2
    hit = _fx_lookup(p)
    if hit is None or _FA_ORIG["exists"](p):
        return False
    fr = _fx_decode(*hit)
    if fr is None:
        return False
    return bool(_FA_ORIG["imwrite"](p, fr, [cv2.IMWRITE_JPEG_QUALITY, int(globals().get("FRAME_ARCHIVE_RESTORE_JPEG", 95))]))


# ---- Hooks: archived frames look present, and are unpacked the moment something reads one ------------------------------
def _fa_install_hooks():
    import cv2
    from PIL import Image as _PILImage
    # CONFIRMED BUG (fixed; detector compare on the WashU export: "'NoneType' object has no attribute 'shape'" from
    # cv2.imread). On Windows, the YOLO library (ultralytics) REPLACES cv2.imread / cv2.imwrite with its own versions the
    # first time it's imported (ultralytics/utils/__init__.py: "if WINDOWS: cv2.imread, cv2.imwrite, cv2.imshow = ...").
    # When that happened after these hooks were installed, the hook was gone and every frame inside an export read as None.
    # Now: ultralytics is imported FIRST (its patch lands before ours and ours wraps it), each original is kept per function
    # (never our own hook -- that would call itself), and vision_hooks_ensure() puts the hooks back if anything replaces them.
    try:
        import importlib.util as _ilu
        if _ilu.find_spec("ultralytics") is not None:
            import ultralytics.utils  # noqa: F401  (applies its cv2 patch now, before ours)
    except Exception:
        pass
    O = globals().get("_FA_ORIG") or {}
    for _k, _f in (("imread", cv2.imread), ("imwrite", cv2.imwrite), ("pil_open", _PILImage.open),
                   ("exists", os.path.exists), ("getsize", os.path.getsize), ("isfile", os.path.isfile)):
        if not getattr(_f, "_fa_hook", False):
            O[_k] = _f                        # the function underneath ours (the original, or another library's patch)
    globals()["_FA_ORIG"] = O

    def _restore_for(p):
        hit = _fa_lookup(p)
        if hit is not None and not O["exists"](p):
            try:
                _fa_restore_clip(hit[0], hit[2], hit[3])
            except Exception as e:
                print(f"  [frame archive] couldn't unpack {os.path.basename(hit[0])}: {type(e).__name__}: {e}", flush=True)

    def _virtual(p):
        """A Synergy-export frame that isn't on disk: (video, frame, width), else None."""
        if not isinstance(p, (str, os.PathLike)):
            return None
        hit = _fx_lookup(p)
        return hit if hit is not None and not O["exists"](p) else None

    def imread(filename, *a, **k):
        hit = _virtual(filename)
        if hit is not None:
            fr = _fx_decode(*hit)
            flags = a[0] if a else k.get("flags", cv2.IMREAD_COLOR)
            if fr is not None and flags == cv2.IMREAD_GRAYSCALE:
                fr = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            return fr
        if isinstance(filename, (str, os.PathLike)):
            _restore_for(filename)
        return O["imread"](filename, *a, **k)

    def pil_open(fp, *a, **k):
        hit = _virtual(fp)
        if hit is not None:
            fr = _fx_decode(*hit)
            if fr is None:
                raise FileNotFoundError(f"couldn't read frame {hit[1]} of {hit[0]}")
            return _PILImage.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
        if isinstance(fp, (str, os.PathLike)):
            _restore_for(fp)
        return O["pil_open"](fp, *a, **k)

    def exists(p):
        r = O["exists"](p)
        return r or (isinstance(p, (str, os.PathLike)) and (_fa_lookup(p) is not None or _fx_lookup(p) is not None))

    def isfile(p):
        r = O["isfile"](p)
        return r or (isinstance(p, (str, os.PathLike)) and (_fa_lookup(p) is not None or _fx_lookup(p) is not None))

    def getsize(p):
        if isinstance(p, (str, os.PathLike)) and not O["exists"](p) and (_fa_lookup(p) is not None or _fx_lookup(p) is not None):
            return 1                                       # archived / in a Synergy export: present, just inside a video
        return O["getsize"](p)

    for f in (imread, pil_open, exists, isfile, getsize):
        f._fa_hook = True
    cv2.imread = imread
    _PILImage.open = pil_open
    os.path.exists = exists
    os.path.isfile = isfile
    os.path.getsize = getsize


def vision_hooks_ensure():
    """Put the frame hooks back if another library replaced them (ultralytics does on Windows). Cheap; call before reading."""
    import cv2
    from PIL import Image as _PILImage
    if not (getattr(cv2.imread, "_fa_hook", False) and getattr(_PILImage.open, "_fa_hook", False)
            and getattr(os.path.exists, "_fa_hook", False)):
        _fa_install_hooks()


# ---- Which frames must stay as JPEGs --------------------------------------------------------------------------------------
def _fa_keep_set():
    base = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    keep = set()
    try:
        for ch in coach_checks_all()[0]:
            if ch.get("frame_file"):
                keep.add(_fa_norm(os.path.join(base, str(ch["frame_file"]))))
    except Exception:
        pass
    cal_dir = globals().get("COURT_CAL_DIR") or os.path.join(INPUT_DIR, "court_calibration")
    for f in glob.glob(os.path.join(cal_dir, "court_calibration_*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                for fr in json.load(fh).get("frames", []):
                    keep.add(_fa_norm(os.path.join(base, fr["file"])))
        except Exception:
            pass
    return keep


# ---- Which games are finished ----------------------------------------------------------------------------------------------
def _fa_game_dirs():
    base = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    return sorted(d for d in glob.glob(os.path.join(base, "*")) if os.path.isdir(d) and glob.glob(os.path.join(d, "track*")))


# ---- Is a game part of THIS run? -------------------------------------------------------------------------------------------
# CONFIRMED CHANGE (requested: "archive the Jan_2_2026_UWOshkosh@UWWhitewater game when I don't have the upcoming opponent being
# Oshkosh or the game right after them. My coaches should have already finished working on that game even if not every clip is
# tracked"). A game that isn't part of the current run counts as finished whatever its tracking / tagging / open reviews:
# part of the run = the upcoming opponent's games (theirs before facing us, and any earlier meeting with us) and UWW's most
# recent FRAME_ARCHIVE_KEEP_RECENT played game(s) before reference_date (the game the staff is still reviewing).
def _fa_dates_near(d, dates, days=1):
    return any(abs((d - x).days) <= days for x in dates)


def _fa_as_date(v):
    try:
        t = pd.to_datetime(v, errors="coerce")
        return None if pd.isna(t) else t.date()
    except Exception:
        return None


def _fa_folder_date(gdir):
    """'Jan_2_2026_UWOshkosh@UWWhitewater' -> date(2026, 1, 2) (the clip page's own date)."""
    m = re.match(r"^([A-Za-z]{3})_(\d{1,2})_(\d{4})", os.path.basename(gdir))
    return _fa_as_date(f"{m.group(1)} {m.group(2)} {m.group(3)}") if m else None


def _fa_words(t):
    return {w for w in re.findall(r"[a-z]+", str(t).lower()) if len(w) > 2 and w not in ("university", "college", "the", "uww")}


def _fa_current_run():
    """(dates of games in this run, why each is in it) -- computed once per archive pass."""
    # CONFIRMED BUG (fixed; run with MSOE as the upcoming opponent: our Coe and Oshkosh games were "part of this run" because
    # MSOE played within a day of them). Each entry now says WHOSE game it is -- (date, "opp" / "uww" / "both", why) -- and a
    # game folder must carry that team's name too (see _fa_finished), not only a date within a day.
    cur = {}
    ref = _fa_as_date(globals().get("reference_date"))
    opp = globals().get("upcoming_opponent_short")
    pg = globals().get("prev_games")
    if isinstance(pg, pd.DataFrame) and "game_date" in pg.columns:
        for d in pg["game_date"].map(_fa_as_date).dropna():
            cur.setdefault((d, "opp"), f"{opp}'s game before facing us (upcoming opponent)")
    ev = globals().get("pbp_events")
    if isinstance(ev, pd.DataFrame) and not ev.empty and "game_date" in ev.columns:
        g = ev.dropna(subset=["game_date"]).groupby("game_date")["opponent"].first()
        played = sorted(d for d in (_fa_as_date(x) for x in g.index) if d is not None and (ref is None or d < ref))
        for d in played[-int(globals().get("FRAME_ARCHIVE_KEEP_RECENT", 1)):] if played else []:
            cur.setdefault((d, "uww"), "our most recent game (still being reviewed)")
        if opp:
            ow = _fa_words(opp)
            for gd, o in g.items():
                d = _fa_as_date(gd)
                if d is not None and ow & _fa_words(o):
                    cur.setdefault((d, "both"), f"our earlier game against {opp} (upcoming opponent)")
    return cur


def _fa_finished(gdir):
    """(finished?, why not) for one game folder under _vision_frames."""
    base = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    rel = os.path.relpath(gdir, base).replace(os.sep, "/")
    pc, _pt_ = _fa_tables()
    mine = pd.DataFrame()
    if isinstance(pc, pd.DataFrame) and not pc.empty and "track_files" in pc.columns:
        tf = pc["track_files"].astype(str)
        mine = pc[tf.str.startswith(rel + "/") | tf.str.contains(";" + re.escape(rel) + "/", regex=True)]
    # not part of this run -> finished, whatever else
    if globals().get("FRAME_ARCHIVE_OUTSIDE_RUN", True):
        cur = globals().get("_fa_cur_run")
        if cur is None:
            cur = globals()["_fa_cur_run"] = _fa_current_run()
        dates = [d for d in (_fa_as_date(x) for x in (mine["game_date"].unique() if not mine.empty else [])) if d]
        fd = _fa_folder_date(gdir)
        dates = dates or ([fd] if fd else [])
        low = os.path.basename(gdir).lower().replace("-", "").replace(" ", "")
        if not mine.empty:
            low += " " + " ".join(str(x).lower() for x in mine.get("game_code", pd.Series(dtype=object)).dropna().unique())
        is_uww = any(k in low for k in ("whitewater", "www", "uww"))
        ow = list(_fa_words(globals().get("upcoming_opponent_short") or ""))
        is_opp = any(w in low for w in ow) or bool(not mine.empty and "side" in mine.columns and (mine["side"] == "Opponent").any())
        need = {"opp": is_opp, "uww": is_uww, "both": is_uww and is_opp}
        hit = next((cur[c] for d in dates for c in cur if abs((d - c[0]).days) <= 1 and need[c[1]]), None)
        if dates and hit is None:
            return True, "not part of this run"
        if hit is not None:
            globals().setdefault("_fa_why_current", {})[os.path.basename(gdir)] = hit
    if not isinstance(pc, pd.DataFrame) or pc.empty or "track_files" not in pc.columns:
        return False, "play calls not loaded (run the notebook through the Play review first)"
    if mine.empty:
        return False, "none of its clips are in the play calls"
    pt = _pt_
    if not isinstance(pt, pd.DataFrame) or pt.empty or "clip_key" not in pt.columns or "track_clip_key" not in mine.columns:
        return False, "no player tracks loaded"
    untracked = int((~mine["track_clip_key"].isin(set(pt["clip_key"]))).sum())
    if untracked:
        return False, f"{untracked} clip(s) not tracked yet"
    _nu = int((mine["decode_quality"] == "Untagged").sum()) if "decode_quality" in mine.columns else 0
    if _nu > int(globals().get("FRAME_ARCHIVE_MAX_UNTAGGED", 10)):
        return False, f"{_nu} clip(s) not tagged yet"
    appd = globals().get("APP_DATA_DIR") or OUTPUT_DIR
    games = set((mine["game_date"].astype(str) + "|" + mine["game_code"].astype(str)).unique())
    for kind in ("play_review", "play_tag"):
        for f in glob.glob(os.path.join(appd, kind, "*", "review.json")):
            try:
                with open(f, encoding="utf-8") as fh:
                    if str(json.load(fh).get("game")) in games:
                        return False, f"open {'Play review' if kind == 'play_review' else 'Film Tagging batch'} in the app"
            except Exception:
                continue
    return True, ""


# ---- Packing one game -------------------------------------------------------------------------------------------------------
def _fa_encode(frames, vid, fps):
    """RGB frames -> H.264 video at the archive's settings. The last frame is written twice (a video can drop its last frame
    on read-back; restoring only ever takes the first N). -> number of frames written (without the pad)."""
    import imageio.v2 as imageio
    wr = imageio.get_writer(vid, fps=fps, codec="libx264", quality=None, macro_block_size=1,
                            pixelformat=str(globals().get("FRAME_ARCHIVE_PIXFMT", "yuv420p")),
                            ffmpeg_params=["-crf", str(int(globals().get("FRAME_ARCHIVE_CRF", 20))),
                                           "-preset", str(globals().get("FRAME_ARCHIVE_PRESET", "medium"))])
    n, last = 0, None
    try:
        for fr in frames:
            wr.append_data(fr)
            last = fr
            n += 1
        if last is not None:
            wr.append_data(last)
    finally:
        wr.close()
    return n


def _fa_count(vid):
    import imageio.v2 as imageio
    try:
        rd = imageio.get_reader(vid)
        n = sum(1 for _ in rd)
        rd.close()
        return n
    except Exception:
        return -1


def _fa_settings():
    return {"crf": int(globals().get("FRAME_ARCHIVE_CRF", 20)), "pix": str(globals().get("FRAME_ARCHIVE_PIXFMT", "yuv420p"))}


def frame_archive_game(gdir, keep=None):
    """Pack every clip of every tracking-frame folder of one game into a video; delete the JPEGs not in `keep`.
    -> (clips packed, MB before, MB after).
    CONFIRMED BUG (fixed; first real run: Alma went 607 MB -> 765 MB, and a 69-frame clip read back as 68). The first
    settings (near-lossless, full colour) made videos BIGGER than the JPEGs: at 4 frames a second the camera moves a lot
    between frames, so a video can't lean on the previous frame much. Now: FRAME_ARCHIVE_CRF 20 + standard colour (yuv420p;
    jersey numbers are in the brightness, which keeps full detail), a clip is only packed when its video is at most
    FRAME_ARCHIVE_MAX_SHARE of its JPEGs (else its JPEGs stay), the last frame is padded so read-back never comes up one
    short, and clips packed with the old settings are re-packed (video -> video) when that makes them smaller."""
    import cv2
    import imageio.v2 as imageio
    keep = keep if keep is not None else _fa_keep_set()
    fps = float(globals().get("VISION_TRACK_FPS") or 4.0)
    share = float(globals().get("FRAME_ARCHIVE_MAX_SHARE", 0.6))
    cur = _fa_settings()
    n_clips, before, after = 0, 0, 0
    for folder in sorted(glob.glob(os.path.join(gdir, "track*"))):
        if not os.path.isdir(folder):
            continue
        man = os.path.join(folder, _FA_INDEX_NAME)
        try:
            with open(man, encoding="utf-8") as fh:
                index = json.load(fh)
        except Exception:
            index = {"clips": {}}

        def _save_index():
            with open(man, "w", encoding="utf-8") as fh:
                json.dump(index, fh)

        # 1) clips packed with older settings: re-pack video -> video when that's smaller (no JPEGs needed)
        stale = [c for c, i in index["clips"].items()
                 if (i.get("crf"), i.get("pix", "yuv444p")) != (cur["crf"], cur["pix"])
                 and _FA_ORIG["exists"](os.path.join(folder, i["video"]))]
        if stale:
            print(f"  [frame archive] {os.path.basename(gdir)}/{os.path.basename(folder)}: re-packing {len(stale)} clip(s) "
                  f"from the older settings...", flush=True)
        for c in stale:
            i = index["clips"][c]
            old = os.path.join(folder, i["video"])
            tmp = old[:-4] + "_repack.mp4"
            try:
                rd = imageio.get_reader(old)
                n = _fa_encode((fr for k, fr in enumerate(rd) if k < len(i["frames"])), tmp, fps)
                rd.close()
                if n == len(i["frames"]) and _fa_count(tmp) >= n and _FA_ORIG["getsize"](tmp) < _FA_ORIG["getsize"](old):
                    before += _FA_ORIG["getsize"](old)
                    after += _FA_ORIG["getsize"](tmp)
                    os.replace(tmp, old)
                    i.update(crf=cur["crf"], pix=cur["pix"], packed=time.strftime("%Y-%m-%d %H:%M"))
                    _save_index()
                else:
                    os.remove(tmp)
                    i.update(crf=cur["crf"], pix=cur["pix"])      # not smaller: keep the old video, don't try again
                    _save_index()
            except Exception as e:
                _FA_ORIG["exists"](tmp) and os.remove(tmp)
                print(f"  [frame archive]   {c}: not re-packed ({type(e).__name__}: {e})", flush=True)

        # 2) clips still as JPEGs
        by_clip = {}
        for f in sorted(glob.glob(os.path.join(folder, "*.jpg"))):
            m = re.match(r"^(.*)_t(\d{3,})\.jpg$", os.path.basename(f))
            if m:
                by_clip.setdefault(m.group(1), []).append((int(m.group(2)), f))
        # (a clip whose only JPEGs left are the kept ones -- coach-check frames -- is already packed)
        by_clip = {c: v for c, v in by_clip.items()
                   if not (c in index["clips"] and all(_fa_norm(f) in keep for _t, f in v))}
        if not by_clip:
            continue
        # CONFIRMED CHANGE (requested: "How long should this take?"): progress every ~10% of the clips, with time left
        _t0, _n_tot, _f_done = time.time(), len(by_clip), 0
        _f_tot = sum(len(v) for v in by_clip.values())
        print(f"  [frame archive] {os.path.basename(gdir)}/{os.path.basename(folder)}: {_n_tot} clip(s), {_f_tot:,} frame(s) "
              f"to pack...", flush=True)
        n_big = 0
        for _ci, (clip, items) in enumerate(by_clip.items(), 1):
            _f_done += len(items)
            if _ci % max(1, _n_tot // 10) == 0 and _ci < _n_tot:
                _el = time.time() - _t0
                print(f"  [frame archive]   {_ci}/{_n_tot} clips ({_f_done:,} frames, {_f_done / max(_el, 1e-6):.0f} frames/s) -- "
                      f"~{_el / _f_done * (_f_tot - _f_done) / 60:.0f} min left for this game", flush=True)
            items.sort()
            names = [os.path.basename(f) for _t, f in items]
            info = index["clips"].get(clip)
            vid = os.path.join(folder, f"{clip}.mp4")
            jpg_bytes = sum(_FA_ORIG["getsize"](f) for _t, f in items)
            if not (info and _FA_ORIG["exists"](vid) and info.get("frames") == names):
                first = cv2.imread(items[0][1])
                if first is None:
                    continue
                h, w = first.shape[:2]
                ok = [True]

                def _frames():
                    for _t, f in items:
                        im = cv2.imread(f)
                        if im is None or im.shape[:2] != (h, w):
                            ok[0] = False
                            return
                        yield cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
                n = _fa_encode(_frames(), vid, fps)
                n_read = _fa_count(vid)
                if not ok[0] or n != len(items) or n_read < len(items):
                    _FA_ORIG["exists"](vid) and os.remove(vid)
                    print(f"  [frame archive]   {clip}: not packed (frames {len(items)}, video {n_read}) -- its JPEGs are kept",
                          flush=True)
                    continue
                if _FA_ORIG["getsize"](vid) > share * jpg_bytes:
                    os.remove(vid)                                 # no real saving: leave this clip as JPEGs
                    n_big += 1
                    continue
                index["clips"][clip] = {"video": os.path.basename(vid), "frames": names, "w": w, "h": h,
                                        "crf": cur["crf"], "pix": cur["pix"], "packed": time.strftime("%Y-%m-%d %H:%M")}
                _save_index()
            n_clips += 1
            for _t, f in items:
                sz = _FA_ORIG["getsize"](f)
                before += sz
                if _fa_norm(f) in keep:
                    after += sz
                else:
                    os.remove(f)
            after += _FA_ORIG["getsize"](vid)
        if n_big:
            print(f"  [frame archive]   {n_big} clip(s) left as JPEGs: their video wasn't smaller than "
                  f"{share:.0%} of the pictures (FRAME_ARCHIVE_MAX_SHARE)", flush=True)
    _fa_load_index()
    return n_clips, before / 1e6, after / 1e6


def frame_restore_game(gdir):
    """Unpack every archived clip of one game back to JPEGs, and drop its videos and index."""
    n = 0
    for man in glob.glob(os.path.join(gdir, "track*", _FA_INDEX_NAME)):
        with open(man, encoding="utf-8") as fh:
            clips = json.load(fh).get("clips", {})
        folder = os.path.dirname(man)
        for clip, info in clips.items():
            vid = os.path.join(folder, info["video"])
            if _FA_ORIG["exists"](vid):
                n += _fa_restore_clip(vid, man, clip)
                os.remove(vid)
        os.remove(man)
    _fa_load_index()
    return n


# =====================================================================================================================
# LEAN MODE -- keep only what's still needed once a game is tracked
# CONFIRMED CHANGE (requested: "It is really hard to do the 2 previous games for whitewater and the opponent when these
# folders are ~3GB each" -> "Let's do #1 lean mode"). Once EVERY clip of a game is tracked, its results (detections, team
# colors, jersey reads, court positions, appearance fingerprints, camera pan) are saved, so the full set of tracking frames
# isn't needed any more. Per clip, lean mode keeps:
#   * the small play video the Play review / Film Tagging show (made once, <game>/media/<clip>.mp4 + cover picture)
#   * the check frame -- the frame with the most players visible, the picture the player checks use (start + end too
#     with PLAY_REVIEW_PICTURES = 2)
#   * every frame with a coach check, and court-calibration frames
#   * (FRAME_LEAN_KEEP_CLOSEUPS = True: the frame each player's close-up is cut from -- sharper close-ups, more space)
# and deletes the rest. The 5 tag-model frames per clip are never touched. <game>/_lean.json records it: the game counts
# as captured (never recaptured), and a step that would need a deleted frame skips it. To rebuild a game in full, delete
# its _lean.json (and media/) and run Frame capture for it again.
_FL_NAME = "_lean.json"


def _fl_load_index():
    """{normalized path of every frame lean mode deleted} and {game dir: lean record}."""
    base = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    gone, recs = set(), {}
    for f in glob.glob(os.path.join(base, "*", _FL_NAME)):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        gdir = os.path.dirname(f)
        recs[_fa_norm(gdir)] = d
        for clip, info in (d.get("clips") or {}).items():
            folder = os.path.join(gdir, info.get("folder", ""))
            keep = set(info.get("kept", []))
            for name in info.get("frames", []):
                if name not in keep:
                    gone.add(_fa_norm(os.path.join(folder, name)))
    globals()["_fl_gone"], globals()["_fl_recs"] = gone, recs
    return gone


def vision_frame_leaned(p):
    """True when lean mode deleted this frame on purpose (its game is tracked; the frame isn't needed)."""
    g = globals().get("_fl_gone")
    return bool(g) and _fa_norm(p) in g


def vision_clip_media(files):
    """The clip's ready-made play video (lean mode) for its tracking frames, or None."""
    if not files:
        return None
    base = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    first = os.path.join(base, files[0])
    m = re.match(r"^(.*)_t\d{3,}\.jpg$", os.path.basename(first))
    if not m:
        return None
    vid = os.path.join(os.path.dirname(os.path.dirname(first)), "media", m.group(1) + ".mp4")
    return vid if _FA_ORIG["exists"](vid) else None


def _fa_tables():
    """(play_calls, player_tracks): the ones in memory, else the ones the last full run exported to the data folder
    (CONFIRMED CHANGE: the archive / lean cell can run on its own in a fresh session)."""
    out = []
    for name, csv in (("play_calls", "uww_play_calls.csv"), ("player_tracks", "uww_player_tracks.csv")):
        t = globals().get(name)
        if not isinstance(t, pd.DataFrame) or t.empty:
            p_ = os.path.join(globals().get("APP_DATA_DIR") or OUTPUT_DIR, csv)
            try:
                t = pd.read_csv(p_, low_memory=False) if os.path.exists(p_) else pd.DataFrame()
            except Exception:
                t = pd.DataFrame()
            if not t.empty:
                print(f"  [frame archive] {name} not in memory -- read from {csv} (the last full run)", flush=True)
                globals()[name] = t
        out.append(t)
    return out


def _fl_ready(gdir):
    """(ready?, why not, the game's play-call rows) -- ready = every clip of the game is tracked."""
    base = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    rel = os.path.relpath(gdir, base).replace(os.sep, "/")
    pc, pt = _fa_tables()
    if not isinstance(pc, pd.DataFrame) or pc.empty or "track_files" not in pc.columns:
        return False, "play calls not loaded", None
    if not isinstance(pt, pd.DataFrame) or pt.empty or "clip_key" not in pt.columns:
        return False, "no player tracks loaded", None
    tf = pc["track_files"].astype(str)
    mine = pc[tf.str.startswith(rel + "/")]
    if mine.empty:
        return False, "none of its clips are in the play calls", None
    untracked = int((~mine["track_clip_key"].isin(set(pt["clip_key"]))).sum()) if "track_clip_key" in mine.columns else len(mine)
    if untracked:
        return False, f"{untracked} clip(s) not tracked yet", None
    return True, "", mine


def frame_lean_game(gdir, keep=None):
    """Lean mode for one tracked game. -> (clips, MB before, MB after)."""
    import shutil as _sh
    import tempfile as _tf
    ok, why, mine = _fl_ready(gdir)
    if not ok:
        return None, why
    if "_pr_clip" not in globals() or "_val_frame_pick" not in globals():
        # a fresh session: load just the functions (not the review itself) from those two sections
        import ast as _ast
        for fn in ("52_validation_pictures.py", "55c_play_review.py"):
            try:
                src_ = open(os.path.join(PARSER_LIB, fn), encoding="utf-8").read()
                for node in _ast.parse(src_).body:
                    if isinstance(node, (_ast.FunctionDef, _ast.Import, _ast.ImportFrom)):
                        exec(compile(_ast.Module([node], []), fn, "exec"), globals())
            except Exception as e:
                return None, f"couldn't load the play-video functions ({type(e).__name__}: {e})"
        globals().setdefault("_trk_json", json)
        globals().setdefault("PLAY_REVIEW_VIDEO", "mp4")
        globals().setdefault("PLAY_REVIEW_VIDEO_WIDTH", 560)
    keep = keep if keep is not None else _fa_keep_set()
    base = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    pt = player_tracks
    fps = float(globals().get("VISION_TRACK_FPS") or 4.0)
    media = os.path.join(gdir, "media")
    os.makedirs(media, exist_ok=True)
    recp = os.path.join(gdir, _FL_NAME)
    try:
        with open(recp, encoding="utf-8") as fh:
            rec = json.load(fh)
    except Exception:
        rec = {"clips": {}}
    before = after = 0
    n = 0
    two = int(globals().get("PLAY_REVIEW_PICTURES", 1)) >= 2
    closeups = bool(globals().get("FRAME_LEAN_KEEP_CLOSEUPS", False))
    tmp = _tf.mkdtemp(prefix="lean_")
    try:
        for _, r in mine.iterrows():
            files = [f for f in str(r["track_files"]).split(";") if f]
            if not files:
                continue
            m = re.match(r"^(.*)_t\d{3,}\.jpg$", os.path.basename(files[0]))
            if not m:
                continue
            clip = m.group(1)
            folder_rel = os.path.dirname(files[0])
            names = [os.path.basename(f) for f in files]
            paths = [os.path.join(base, f) for f in files]
            if clip in rec["clips"]:
                _k = set(rec["clips"][clip].get("kept", []))
                if not any(_FA_ORIG["exists"](p_) or _fa_lookup(p_) is not None
                           for nm, p_ in zip(names, paths) if nm not in _k):
                    continue                                   # done on an earlier run
            rows = pt[pt["clip_key"] == r["track_clip_key"]].to_dict("records")
            nfr = len(files)
            picks = {_val_frame_pick(rows, 0, max(0, nfr - 1))}
            if two:
                t_end = pd.to_numeric(r.get("track_finish_frame"), errors="coerce")
                end_hi = int(min(nfr - 1, t_end)) if pd.notna(t_end) else nfr - 1
                picks |= {_val_frame_pick(rows, 0, max(1, int(0.25 * nfr))),
                          _val_frame_pick(rows, int(max(0, end_hi - 2 * fps)), end_hi, prefer_late=True)}
            picks = {t for t in picks if t is not None and 0 <= t < nfr} or {0}
            if closeups and "_pr_best_instance" in globals():
                cache_ = {}
                for t0 in list(picks):
                    for rr in rows:
                        if rr.get("side") in ("offense", "defense"):
                            bi = _pr_best_instance(rows, rr["track"], t0, files, fps, cache_)
                            if bi is not None:
                                picks.add(int(bi[1]))
            # the play video, once (from the full frames, while they're still here)
            vid = os.path.join(media, clip + ".mp4")
            if not _FA_ORIG["exists"](vid):
                vision_frames_ensure(paths)                    # an archived clip: unpack it first
                made = _pr_clip(files, rows, None, os.path.join(tmp, clip))
                if made and made.endswith(".mp4"):
                    _sh.move(os.path.join(tmp, made), vid)
                    if os.path.exists(os.path.join(tmp, clip + "_poster.jpg")):
                        _sh.move(os.path.join(tmp, clip + "_poster.jpg"), os.path.join(media, clip + "_poster.jpg"))
                else:
                    print(f"  [lean] {clip}: play video not made -- its frames are kept", flush=True)
                    continue
            kept_names = {names[t] for t in picks}
            kept_names |= {nm for nm, p_ in zip(names, paths) if _fa_norm(p_) in keep}
            # the kept frames as plain JPEGs (unpacked if they were archived)
            vision_frames_ensure([p_ for nm, p_ in zip(names, paths) if nm in kept_names])
            for nm, p_ in zip(names, paths):
                if _FA_ORIG["exists"](p_):
                    sz = _FA_ORIG["getsize"](p_)
                    before += sz
                    if nm in kept_names:
                        after += sz
                    else:
                        os.remove(p_)
            rec["clips"][clip] = {"folder": folder_rel.split("/", 1)[-1], "frames": names, "kept": sorted(kept_names),
                                  "check_frames": sorted(int(t) for t in picks), "video": f"media/{clip}.mp4",
                                  "leaned": time.strftime("%Y-%m-%d %H:%M")}
            after += _FA_ORIG["getsize"](vid)
            n += 1
        # an archived clip's video and index entry go too (its kept frames are plain JPEGs now)
        for man in glob.glob(os.path.join(gdir, "track*", _FA_INDEX_NAME)):
            try:
                with open(man, encoding="utf-8") as fh:
                    ix = json.load(fh)
                folder = os.path.dirname(man)
                for c in [c for c in ix.get("clips", {}) if c in rec["clips"]]:
                    v = os.path.join(folder, ix["clips"][c]["video"])
                    if _FA_ORIG["exists"](v):
                        before += _FA_ORIG["getsize"](v)
                        os.remove(v)
                    ix["clips"].pop(c)
                with open(man, "w", encoding="utf-8") as fh:
                    json.dump(ix, fh)
            except Exception:
                pass
        rec["updated"] = time.strftime("%Y-%m-%d %H:%M")
        with open(recp, "w", encoding="utf-8") as fh:
            json.dump(rec, fh)
    finally:
        _sh.rmtree(tmp, ignore_errors=True)
    _fa_load_index()
    _fl_load_index()
    return (n, before / 1e6, after / 1e6), ""


def frame_lean_run():
    if not globals().get("FRAME_LEAN", True):
        print("Frame lean mode: off (FRAME_LEAN = False).")
        return
    keep = _fa_keep_set()
    dry = bool(globals().get("FRAME_ARCHIVE_DRY_RUN", True))
    tot_b = tot_a = 0.0
    for d in _fa_game_dirs():
        name = os.path.basename(d)
        if glob.glob(os.path.join(d, "track*", _FX_INDEX_NAME)):
            continue                                       # frames come from the game's Synergy export: nothing to slim down
        jpgs = glob.glob(os.path.join(d, "track*", "*.jpg"))
        archived = any(True for _ in glob.glob(os.path.join(d, "track*", "*.mp4")))
        if not jpgs and not archived:
            continue
        ok, why, mine = _fl_ready(d)
        if not ok:
            print(f"Frame lean mode: {name} -- not yet ({why})", flush=True)
            continue
        if dry:
            mb = sum(_FA_ORIG["getsize"](f) for f in jpgs) / 1e6
            print(f"Frame lean mode: {name} -- WOULD keep 1 check frame + a small play video per clip and delete the other "
                  f"tracking frames ({mb:,.0f} MB of pictures now). FRAME_ARCHIVE_DRY_RUN = False to do it.", flush=True)
            continue
        t0 = time.time()
        res, why = frame_lean_game(d, keep)
        if res is None:
            print(f"Frame lean mode: {name} -- skipped ({why})", flush=True)
            continue
        n, b, a = res
        if not n:
            continue                                           # already lean
        tot_b += b
        tot_a += a
        print(f"Frame lean mode: {name} -- {n} clip(s): {b:,.0f} MB -> {a:,.0f} MB ({time.time() - t0:.0f}s)", flush=True)
    if tot_b:
        print(f"Frame lean mode: freed {tot_b - tot_a:,.0f} MB ({tot_b:,.0f} MB -> {tot_a:,.0f} MB).", flush=True)


def frame_archive_run():
    games = globals().get("FRAME_ARCHIVE_GAMES", "finished")
    restore = list(globals().get("FRAME_RESTORE_GAMES") or [])
    base = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    for name in restore:
        g = os.path.join(base, name)
        if os.path.isdir(g):
            print(f"Frame archive: {name} -- unpacked {frame_restore_game(g):,} frame(s) back to JPEGs", flush=True)
    if not games:
        print("Frame archive: off (FRAME_ARCHIVE_GAMES = []).")
        return
    dirs = _fa_game_dirs()
    if isinstance(games, (list, tuple, set)):
        dirs = [d for d in dirs if os.path.basename(d) in set(games)]
    keep = _fa_keep_set()
    globals()["_fa_cur_run"] = None                     # the current run's games, worked out fresh each pass
    globals()["_fa_why_current"] = {}
    dry = bool(globals().get("FRAME_ARCHIVE_DRY_RUN", True))
    tot_b = tot_a = 0.0
    for d in dirs:
        name = os.path.basename(d)
        if name in restore:
            continue
        if glob.glob(os.path.join(d, "track*", _FX_INDEX_NAME)):
            # a game read from its Synergy export: JPEGs written from it (vision_frames_ensure) are re-made in a moment, so
            # they're removed here -- except coach-check and court-calibration frames
            _fx_i = globals().get("_fx_index") or {}
            made = [f for f in glob.glob(os.path.join(d, "track*", "*.jpg")) if _fa_norm(f) in _fx_i and _fa_norm(f) not in keep]
            if made and not dry:
                for f in made:
                    os.remove(f)
                print(f"Frame archive: {name} -- removed {len(made):,} JPEG(s) written from its Synergy export (re-made from "
                      f"the clip videos when needed)", flush=True)
            elif made:
                print(f"Frame archive: {name} -- WOULD remove {len(made):,} JPEG(s) written from its Synergy export", flush=True)
            continue
        if _FA_ORIG["exists"](os.path.join(d, _FL_NAME)):
            continue                                       # lean mode already keeps only a few frames of this game
        jpgs = [f for f in glob.glob(os.path.join(d, "track*", "*.jpg"))]
        packable = [f for f in jpgs if _fa_norm(f) not in keep]
        cur_set = _fa_settings()
        stale = 0
        for man in glob.glob(os.path.join(d, "track*", _FA_INDEX_NAME)):
            try:
                with open(man, encoding="utf-8") as fh:
                    stale += sum(1 for i in json.load(fh).get("clips", {}).values()
                                 if (i.get("crf"), i.get("pix", "yuv444p")) != (cur_set["crf"], cur_set["pix"]))
            except Exception:
                pass
        if not packable and not stale:
            continue
        if games == "finished":
            ok, why = _fa_finished(d)
            if not ok:
                cur_why = (globals().get("_fa_why_current") or {}).get(name)
                print(f"Frame archive: {name} -- kept as is ({why}" + (f"; part of this run: {cur_why}" if cur_why else "") + ")",
                      flush=True)
                continue
            if why:
                print(f"Frame archive: {name} -- {why}, counts as finished", flush=True)
        mb = sum(_FA_ORIG["getsize"](f) for f in jpgs) / 1e6
        if dry:
            print(f"Frame archive: {name} -- WOULD pack {len(packable):,} frame(s) ({mb:,.0f} MB of JPEGs)"
                  + (f" and re-pack {stale} clip(s) packed with older settings" if stale else "")
                  + ". FRAME_ARCHIVE_DRY_RUN = False to do it.", flush=True)
            continue
        t0 = time.time()
        n, b, a = frame_archive_game(d, keep)
        tot_b += b
        tot_a += a
        print(f"Frame archive: {name} -- packed {n} clip(s): {b:,.0f} MB -> {a:,.0f} MB ({time.time() - t0:.0f}s)", flush=True)
    if tot_b:
        print(f"Frame archive: freed {tot_b - tot_a:,.0f} MB ({tot_b:,.0f} MB -> {tot_a:,.0f} MB).", flush=True)


# ---- Every time this file runs: load the index and install the hooks -------------------------------------------------------
_fa_install_hooks()
_fx_load_index()
_fa_idx = _fa_load_index()
if _fa_idx:
    print(f"Frame archive: {len(_fa_idx):,} tracking frame(s) are packed in clip videos -- unpacked automatically when a "
          f"step reads them.", flush=True)
_fl_load_index()
if globals().get("FRAME_ARCHIVE_STEP") == "archive":
    frame_lean_run()
    frame_archive_run()
