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
# A game is "finished" when: every clip with tracking frames has been tracked (player tracks exist for it), it has no open
# Play review or Film Tagging batch in the app data folder, and none of its clips is still Untagged. FRAME_ARCHIVE_GAMES:
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


# ---- Hooks: archived frames look present, and are unpacked the moment something reads one ------------------------------
def _fa_install_hooks():
    import cv2
    from PIL import Image as _PILImage
    if globals().get("_FA_ORIG") is None or not getattr(cv2.imread, "_fa_hook", False):
        globals()["_FA_ORIG"] = {"imread": cv2.imread, "imwrite": cv2.imwrite, "pil_open": _PILImage.open,
                                 "exists": os.path.exists, "getsize": os.path.getsize, "isfile": os.path.isfile}
    O = globals()["_FA_ORIG"]

    def _restore_for(p):
        hit = _fa_lookup(p)
        if hit is not None and not O["exists"](p):
            try:
                _fa_restore_clip(hit[0], hit[2], hit[3])
            except Exception as e:
                print(f"  [frame archive] couldn't unpack {os.path.basename(hit[0])}: {type(e).__name__}: {e}", flush=True)

    def imread(filename, *a, **k):
        if isinstance(filename, (str, os.PathLike)):
            _restore_for(filename)
        return O["imread"](filename, *a, **k)

    def pil_open(fp, *a, **k):
        if isinstance(fp, (str, os.PathLike)):
            _restore_for(fp)
        return O["pil_open"](fp, *a, **k)

    def exists(p):
        r = O["exists"](p)
        return r or (isinstance(p, (str, os.PathLike)) and _fa_lookup(p) is not None)

    def isfile(p):
        r = O["isfile"](p)
        return r or (isinstance(p, (str, os.PathLike)) and _fa_lookup(p) is not None)

    def getsize(p):
        if isinstance(p, (str, os.PathLike)) and not O["exists"](p) and _fa_lookup(p) is not None:
            return 1                                       # archived: present, just packed in its clip video
        return O["getsize"](p)

    for f in (imread, pil_open, exists, isfile, getsize):
        f._fa_hook = True
    cv2.imread = imread
    _PILImage.open = pil_open
    os.path.exists = exists
    os.path.isfile = isfile
    os.path.getsize = getsize


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


def _fa_finished(gdir):
    """(finished?, why not) for one game folder under _vision_frames."""
    base = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    rel = os.path.relpath(gdir, base).replace(os.sep, "/")
    pc = globals().get("play_calls")
    if not isinstance(pc, pd.DataFrame) or pc.empty or "track_files" not in pc.columns:
        return False, "play calls not loaded (run the notebook through the Play review first)"
    tf = pc["track_files"].astype(str)
    mine = pc[tf.str.startswith(rel + "/") | tf.str.contains(";" + re.escape(rel) + "/", regex=True)]
    if mine.empty:
        return False, "none of its clips are in the play calls"
    pt = globals().get("player_tracks")
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
def frame_archive_game(gdir, keep=None):
    """Pack every clip of every tracking-frame folder of one game into a video; delete the JPEGs not in `keep`.
    -> (clips packed, MB before, MB after)."""
    import cv2
    import imageio.v2 as imageio
    keep = keep if keep is not None else _fa_keep_set()
    fps = float(globals().get("VISION_TRACK_FPS") or 4.0)
    crf = str(int(globals().get("FRAME_ARCHIVE_CRF", 14)))
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
        by_clip = {}
        for f in sorted(glob.glob(os.path.join(folder, "*.jpg"))):
            m = re.match(r"^(.*)_t(\d{3,})\.jpg$", os.path.basename(f))
            if m:
                by_clip.setdefault(m.group(1), []).append((int(m.group(2)), f))
        for clip, items in by_clip.items():
            items.sort()
            names = [os.path.basename(f) for _t, f in items]
            info = index["clips"].get(clip)
            vid = os.path.join(folder, f"{clip}.mp4")
            if not (info and os.path.exists(vid) and info.get("frames") == names):
                first = cv2.imread(items[0][1])
                if first is None:
                    continue
                h, w = first.shape[:2]
                wr = imageio.get_writer(vid, fps=fps, codec="libx264", quality=None, macro_block_size=1,
                                        pixelformat="yuv444p", ffmpeg_params=["-crf", crf, "-preset", "slow"])
                ok = True
                try:
                    for _t, f in items:
                        im = cv2.imread(f)
                        if im is None or im.shape[:2] != (h, w):
                            ok = False
                            break
                        wr.append_data(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
                finally:
                    wr.close()
                # check: the video has every frame before anything is deleted
                try:
                    rd = imageio.get_reader(vid)
                    n_read = sum(1 for _ in rd)
                    rd.close()
                except Exception:
                    n_read = -1
                if not ok or n_read != len(items):
                    _FA_ORIG["exists"](vid) and os.remove(vid)
                    print(f"  [frame archive] {os.path.basename(folder)}/{clip}: not packed (frames {len(items)}, video "
                          f"{n_read}) -- its JPEGs are kept", flush=True)
                    continue
                index["clips"][clip] = {"video": os.path.basename(vid), "frames": names, "w": w, "h": h,
                                        "crf": int(crf), "packed": time.strftime("%Y-%m-%d %H:%M")}
                with open(man, "w", encoding="utf-8") as fh:
                    json.dump(index, fh)
            n_clips += 1
            for _t, f in items:
                sz = _FA_ORIG["getsize"](f)
                before += sz
                if _fa_norm(f) in keep:
                    after += sz
                else:
                    os.remove(f)
            after += _FA_ORIG["getsize"](vid)
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
    dry = bool(globals().get("FRAME_ARCHIVE_DRY_RUN", True))
    tot_b = tot_a = 0.0
    for d in dirs:
        name = os.path.basename(d)
        if name in restore:
            continue
        jpgs = [f for f in glob.glob(os.path.join(d, "track*", "*.jpg"))]
        packable = [f for f in jpgs if _fa_norm(f) not in keep]
        if not packable:
            continue
        if games == "finished":
            ok, why = _fa_finished(d)
            if not ok:
                print(f"Frame archive: {name} -- kept as is ({why})", flush=True)
                continue
        mb = sum(_FA_ORIG["getsize"](f) for f in jpgs) / 1e6
        if dry:
            print(f"Frame archive: {name} -- WOULD pack {len(packable):,} frame(s) ({mb:,.0f} MB of JPEGs; ~{mb / 12:,.0f} MB "
                  f"after). FRAME_ARCHIVE_DRY_RUN = False to do it.", flush=True)
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
_fa_idx = _fa_load_index()
if _fa_idx:
    print(f"Frame archive: {len(_fa_idx):,} tracking frame(s) are packed in clip videos -- unpacked automatically when a "
          f"step reads them.", flush=True)
if globals().get("FRAME_ARCHIVE_STEP") == "archive":
    frame_archive_run()
