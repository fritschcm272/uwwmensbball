# 48_jersey_number_recognizer.py -- code for the notebook section "Jersey-number recognizer: a small image model trained on YOUR film -----------------------"
# Runs inside the notebook via run_section("48_jersey_number_recognizer"); its settings are in that notebook cell.

# --- Jersey-number recognizer: a small image model trained on YOUR film ---------------------------------------------
# CONFIRMED CHANGE (requested after the Roboflow basketball article: build a jersey-number recognizer trained on labeled
# crops -- there, off-the-shelf reading got 56% of numbers and a small model trained on 3,600 labeled crops got 93% -- and
# "give me a parameter to add more frames to the training set later and train it again").
#
# A ResNet-18 (a small, standard image model) looks at a player's chest crop and says which number it is. It learns from
# a TRAINING SET that grows every run, kept in INPUT_DIR/jersey_training/<source>/<number>/*.jpg:
#   reads/   players PaddleOCR named by jersey number (confident reads): several chest crops from each track, INCLUDING
#            frames where PaddleOCR could NOT read the number -- exactly what this model has to learn
#   coach/   your checks (true numbers). By default these are the TEST set, not trained on, so the reader test's
#            "on YOUR checked players" score for the "trained" reader is honest (JERSEY_TRAIN_USE_COACH = True adds them)
#   extra/   anything in JERSEY_TRAIN_EXTRA_DIRS: folders of <number>/ images, or Roboflow JSONL exports -- e.g. Roboflow's
#            NBA "basketball-jersey-numbers-ocr" set (3,615 crops, CC BY 4.0), downloaded here if you give an API key
# It is then one more reader ("trained") in the Jersey-number reader test, scored on your checked players like the rest,
# and used by tracking only if it wins there. It reads a crop in a few milliseconds, so tracking can read more per player.
#
# Settings for later: JERSEY_TRAIN_ADD_FRAMES adds this run's labeled crops; JERSEY_TRAIN_EXTRA_DIRS adds more data;
# JERSEY_TRAIN_NOW = "auto" retrains whenever the training set changed (True = retrain now, False = keep the saved model).
import os
import re
import sys
import time
import glob
import json
import hashlib
import subprocess
import numpy as np
import pandas as pd

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





# CONFIRMED CHANGE (requested: "do #1" -- from the TrackID3x3 jersey-number pipeline). The recognizer's crop can be cut from
# the player's BODY instead of a fixed slice of his box: a small pose model finds his shoulders and hips, and the crop runs from
# just above the shoulders to the hips, a little wider than the shoulders. A fixed slice (10-62% of the box height) misses the
# number when a player leans, turns, has his arms up or is partly hidden. JERSEY_CROP_STYLE: "fixed" (the old crop), "pose", or
# "compare" (train BOTH and let the Jersey-number reader test pick the better on your checked players: "trained" vs
# "trained_pose"). Each style has its own training crops (reads/ + coach/ vs reads_pose/ + coach_pose/; extra/ is shared --
# those are ready-made crops) and its own model file (jersey_recognizer.pt / jersey_recognizer_pose.pt).
# CONFIRMED CHANGE (requested: "There is not a lot of description that gets printed when 48_jersey_number_recognizer is
# running"). Every step now says what it's doing, with the time since the cell started; the slow loops (crops from the coach
# checks, from jersey-number tracks, the extra data) print a count with time so far / time left; the cell ends with where
# the time went.
import time as _jr_time
_jr_t_cell = _jr_time.time()
_jr_steps = []
_jr_step_open = None


def _jr_say(msg):
    print(f"  [recognizer {(_jr_time.time() - _jr_t_cell) / 60:.1f} min] {msg}", flush=True)


def _jr_step(name):
    """Close the running step (its time is kept for the summary) and start this one."""
    global _jr_step_open
    now = _jr_time.time()
    if _jr_step_open is not None:
        _jr_steps.append((_jr_step_open[0], now - _jr_step_open[1]))
    _jr_step_open = (name, now) if name else None
    if name:
        _jr_say(name + "...")


def _jr_progress(label, done, total, t0, state, extra=""):
    now = _jr_time.time()
    if done < total and now - state.get("last", t0) < 20:
        return
    state["last"] = now
    el = (now - t0) / 60.0
    left = el / done * (total - done) if done else None
    print(f"    {label}: {done:,} / {total:,} ({100 * done // max(total, 1)}%) -- {el:.1f} min so far"
          + (f", ~{left:.1f} min left" if left is not None and done < total else "") + (f" -- {extra}" if extra else ""),
          flush=True)


def _jr_style():
    return globals().get("_JR_STYLE", "fixed")


def _jr_dir(src):
    """Training-set folder for a source in the current crop style."""
    return src + "_pose" if _jr_style() == "pose" and src in ("reads", "coach") else src


def _jr_path_for(style):
    base = globals().get("_JR_BASE_MODEL_PATH") or JERSEY_MODEL_PATH
    return base[:-3] + "_pose.pt" if style == "pose" and base.endswith(".pt") else base


def _jr_fixed_box(box):
    x1, y1, x2, y2 = [float(v) for v in box[:4]]
    w, h = x2 - x1, y2 - y1
    return (x1 - 0.05 * w, y1 + 0.10 * h, x2 + 0.05 * w, y1 + 0.62 * h)


def _jr_torso_box(img, box):
    """Shoulders-to-hips box from a pose model run on the person's own crop (None = pose not found: use the fixed crop)."""
    x1, y1, x2, y2 = [float(v) for v in box[:4]]
    w, h = x2 - x1, y2 - y1
    if h < 20:
        return None
    X1, Y1 = max(int(x1 - 0.15 * w), 0), max(int(y1 - 0.05 * h), 0)
    X2, Y2 = min(int(x2 + 0.15 * w), img.shape[1]), min(int(y2 + 0.02 * h), img.shape[0])
    person = img[Y1:Y2, X1:X2]
    if person.size == 0:
        return None
    key = (img.shape[0], img.shape[1], int(x1), int(y1), int(x2), int(y2), int(person.mean() * 1000))
    cache = globals().setdefault("_jr_torso_cache", _jr_torso_load())
    if key in cache:
        return cache[key]
    out = None
    try:
        m = globals().get("_jr_pose_m")
        if m is None:
            from ultralytics import YOLO
            if "vision_hooks_ensure" in globals():
                vision_hooks_ensure()          # ultralytics replaces cv2.imread on Windows
            m = globals()["_jr_pose_m"] = YOLO(globals().get("TRACK_POSE_MODEL", "yolo11n-pose.pt"))
        r = m.predict(person, imgsz=256, conf=0.2, verbose=False)[0]
        if r.keypoints is not None and len(r.keypoints.data):
            bx = r.boxes.xyxy.cpu().numpy()
            cx, cy = person.shape[1] / 2, person.shape[0] / 2
            # the person the box is about: biggest, centered
            k = int(np.argmax([(b[2] - b[0]) * (b[3] - b[1]) - 2.0 * abs((b[0] + b[2]) / 2 - cx) * (b[3] - b[1]) for b in bx]))
            kp = r.keypoints.data[k].cpu().numpy()
            sh = [kp[i] for i in (5, 6) if kp[i][2] > 0.3]
            hp = [kp[i] for i in (11, 12) if kp[i][2] > 0.3]
            if len(sh) == 2:
                sx1, sx2 = sorted([float(sh[0][0]), float(sh[1][0])])
                sy = float(np.mean([q[1] for q in sh]))
                hy = float(np.mean([q[1] for q in hp])) if hp else sy + 0.30 * h
                tw = max(sx2 - sx1, 0.25 * w)
                th = hy - sy
                if th > 0.12 * h:
                    out = (X1 + sx1 - 0.25 * tw, Y1 + sy - 0.12 * th, X1 + sx2 + 0.25 * tw, Y1 + hy + 0.02 * th)
    except Exception:
        out = None
    cache[key] = out
    globals()["_jr_torso_new"] = globals().get("_jr_torso_new", 0) + 1
    if globals()["_jr_torso_new"] % 300 == 0:
        _jr_torso_save()
    return out


def _jr_torso_load():
    try:
        p_ = os.path.join(INPUT_DIR, "_tracking", "jersey_torso_boxes.pkl")
        return _safe_read_pickle(p_) if os.path.exists(p_) else {}
    except Exception:
        return {}


def _jr_torso_save():
    try:
        os.makedirs(os.path.join(INPUT_DIR, "_tracking"), exist_ok=True)
        _safe_to_pickle(globals().get("_jr_torso_cache", {}), os.path.join(INPUT_DIR, "_tracking", "jersey_torso_boxes.pkl"))
    except Exception:
        pass


def _jr_crop_box(img, box, style=None):
    """The region the recognizer sees, in the given (or current) crop style."""
    style = style or _jr_style()
    if style == "pose":
        tb = _jr_torso_box(img, box)
        if tb is not None:
            return tb
    return _jr_fixed_box(box)


def _jr_chest(img, box, style=None):
    """The chest region the recognizer sees (fixed slice of the box, or shoulders-to-hips with JERSEY_CROP_STYLE = "pose")."""
    a, b, c_, d = _jr_crop_box(img, box, style)
    c = img[max(int(b), 0):max(int(d), int(b) + 1), max(int(a), 0):max(int(c_), int(a) + 1)]
    return c if c.size else None


def _jr_det_cache():
    dets = sorted([d for d in glob.glob(os.path.join(INPUT_DIR, "_tracking", "detections_*tiles*.pkl")) if "jersey" not in d],
                  key=os.path.getmtime)
    return _safe_read_latest(dets) if dets else {}


def _jr_box_at(det, frame, px, py):
    d = det.get(frame)
    if d is None or not len(d["p"]):
        return None
    p = d["p"]
    j = int(np.argmin(np.hypot((p[:, 0] + p[:, 2]) / 2 - px, p[:, 3] - py)))
    if np.hypot((p[j, 0] + p[j, 2]) / 2 - px, p[j, 3] - py) > 25:
        return None
    if _jr_hidden(p, j):
        return None                  # partly hidden behind someone in front: the chest crop may show the other person
    return [float(v) for v in p[j, :4]]


def _jr_hidden(p, j):
    """CONFIRMED CHANGE (requested; clip 1 t048: Luke Bara's box was 42% covered by the box of a coach standing IN FRONT of him,
    so Bara's chest crop showed part of the coach). True when a box whose feet are lower on the picture (closer to the camera)
    covers more than JERSEY_MAX_HIDDEN of box j. Such a box never becomes a training or test crop (on the saved checks this
    skips about 15% of the checked boxes)."""
    try:
        lim = float(globals().get("JERSEY_MAX_HIDDEN", 0.3))
        if lim <= 0:
            return False
        a = p[j]
        area = max(float(a[2] - a[0]) * float(a[3] - a[1]), 1e-6)
        for k in range(len(p)):
            if k == j or float(p[k, 3]) <= float(a[3]):
                continue                               # only someone in FRONT (feet lower) can hide him
            ix = max(0.0, min(float(a[2]), float(p[k, 2])) - max(float(a[0]), float(p[k, 0])))
            iy = max(0.0, min(float(a[3]), float(p[k, 3])) - max(float(a[1]), float(p[k, 1])))
            if ix * iy / area > lim:
                return True
        return False
    except Exception:
        return False


def _jr_save(img, box, path):
    import cv2
    if os.path.exists(path):
        return False
    c = _jr_chest(img, box)
    if c is None or min(c.shape[:2]) < 8:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cv2.imwrite(path, c)
    return True


def _jr_name(frame, box):
    return re.sub(r"[^A-Za-z0-9]+", "_", frame)[-60:] + f"_{int(box[0])}_{int(box[1])}.jpg"


def jersey_collect():
    """Add this run's labeled crops to the training set. -> counts per source."""
    import cv2
    added = {"reads": 0, "coach": 0, "extra": 0}
    _jr_say("loading the saved player detections (to find each checked box)...")
    _td = _jr_time.time()
    det = _jr_det_cache()
    _jr_say(f"  {len(det):,} frame(s) of saved detections loaded ({_jr_time.time() - _td:.0f} s)")
    vfd = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    imgs = {}

    def _img(f):
        if f not in imgs:
            if len(imgs) > 200:
                imgs.clear()
            imgs[f] = cv2.imread(os.path.join(vfd, f), cv2.IMREAD_COLOR)
        return imgs[f]

    # coach checks: the true number at the checked frame
    coach_spots = set()
    _nums_by_game = {}
    _checks = coach_checks_all()[0]                   # every checks file, merged -- the latest check of a box wins
    _jr_say(f"cutting training crops from {len(_checks):,} coach check(s) (a crop already in the training set is skipped)...")
    _t0, _st, _cc = _jr_time.time(), {}, {"had": 0, "no_box": 0, "no_num": 0, "no_pic": 0}
    for _ci, ch in enumerate(_checks):
        _jr_progress("coach checks", _ci, len(_checks), _t0, _st,
                     f"{added['coach']} new crop(s), {_cc['had']} already had")
        gd, gc = str(ch.get("game") or "|").split("|", 1)
        if (gd, gc) not in _nums_by_game:
            _nums_by_game[(gd, gc)] = _trk_numbers_for_game(gd, gc)
        num = _nums_by_game[(gd, gc)].get(str(ch.get("true_name") or "").lower())
        # CONFIRMED CHANGE (requested: the reader kept reading a referee's striped shirt as #10). A box the coach marked "not a
        # player" (referee, coach, fan) is now a training example of a shirt with NO number -- class "nn" -- so the reader
        # learns to answer "no number" there instead of the nearest number (JERSEY_TRAIN_NO_NUMBER = False turns it off).
        if ch.get("verdict") == "not a player" and globals().get("JERSEY_TRAIN_NO_NUMBER", True):
            # CONFIRMED CHANGE (requested: kinds of non-player). A BENCH player / coach / staff box is not taught as "no number":
            # bench players often wear the team uniform with a perfectly readable number. Referees, crowd and plain "not a
            # player" still are.
            num = None if ch.get("not_player_kind") == "bench" else "nn"
        box = _jr_box_at(det, ch.get("frame_file"), ch.get("px", -1e9), ch.get("py", -1e9))
        if box is None:
            _cc["no_box"] += 1
            continue
        fname = _jr_name(ch["frame_file"], box)
        coach_spots.add((ch["frame_file"], int(box[0]), int(box[1])))
        # a box re-checked as someone else (or "not a player"): its crop must not stay under the old number
        for old_ in glob.glob(os.path.join(JERSEY_TRAIN_DIR, _jr_dir("coach"), "*", fname)):
            if os.path.basename(os.path.dirname(old_)) != num:
                os.remove(old_)
        if not num:
            _cc["no_num"] += 1
            continue
        _dst = os.path.join(JERSEY_TRAIN_DIR, _jr_dir("coach"), num, fname)
        # (speed) the crop is already in the training set: don't read (decode) the frame at all
        if (globals().get("_FA_ORIG") or {}).get("exists", os.path.exists)(_dst):
            _cc["had"] += 1
            continue
        im = _img(ch["frame_file"])
        if im is None:
            _cc["no_pic"] += 1
        elif _jr_save(im, box, _dst):
            added["coach"] += 1
    _jr_progress("coach checks", len(_checks), len(_checks), _t0, _st,
                 f"{added['coach']} new crop(s), {_cc['had']} already had, {_cc['no_box']} with no box found there "
                 f"(partly hidden / not in the saved detections), {_cc['no_num']} without a jersey number to learn"
                 + (f", {_cc['no_pic']} whose frame isn't on disk" if _cc["no_pic"] else ""))
    # players named by jersey number in the last tracking run: crops from across each track
    pt = globals().get("player_tracks")
    if not isinstance(pt, pd.DataFrame) or pt.empty:
        p_ = os.path.join(OUTPUT_DIR, "uww_player_tracks.csv")
        pt = pd.read_csv(p_) if os.path.exists(p_) else pd.DataFrame()
    pcs = globals().get("play_calls", pd.DataFrame())
    # every saved jersey reading, by spot on the picture: (frame, x1, y1) -> [(key, [(text, conf)])]
    _reads_by_spot = {}
    _jp = os.path.join(INPUT_DIR, "_tracking", "jersey_numbers.pkl")
    if os.path.exists(_jp):
        for key_, v in _safe_read_pickle(_jp).items():
            parts = str(key_).split("|")
            # its OWN readings never become its training labels (it would learn its own mistakes) unless asked
            if len(parts) >= 6 and parts[5].startswith("trained") and not JERSEY_TRAIN_FROM_OWN_READS:
                continue
            if len(parts) >= 6 and v:
                _reads_by_spot.setdefault((parts[0], int(parts[1]), int(parts[2])), []).append((key_, v))
    # CONFIRMED BUG (fixed): this used play_calls' "track_clip_key", a column Player tracking creates -- but this cell
    # runs BEFORE Player tracking, so the column didn't exist yet and every jersey-number track was skipped ("added 0").
    # The clip key is rebuilt here the same way tracking builds it (game date | clip number | Synergy description).
    _n_jt = _n_jt_read = 0
    if pt.empty or "name_how" not in pt.columns:
        print("  [recognizer] no player tracks with name sources from an earlier run yet (run Player tracking once)", flush=True)
    elif not pcs.empty and "track_files" in pcs.columns:
        _pc = pcs[pcs["track_files"].notna()].copy()
        _pc["_key"] = [f"{r.get('game_date')}|{r.get('clip_number')}|{r.get('synergy_string')}" for _, r in _pc.iterrows()]
        meta = _pc.drop_duplicates("_key").set_index("_key")
        _jt = pt[pt["name_how"] == "jersey number"]
        _jr_say(f"cutting training crops from {len(_jt):,} player track(s) named by jersey number in the last tracking run...")
        _t0, _st = _jr_time.time(), {}
        for _ti, (_, t) in enumerate(_jt.iterrows()):
            _jr_progress("number tracks", _ti, len(_jt), _t0, _st, f"{added['reads']} new crop(s)")
            if t["clip_key"] not in meta.index:
                continue
            r = meta.loc[t["clip_key"]]
            num = _trk_numbers_for_game(str(r["game_date"]), str(r["game_code"])).get(str(t["name"]).lower())
            files = [f for f in str(r.get("track_files") or "").split(";") if f]
            if not num or not files:
                continue
            _n_jt += 1
            path = [p for p in json.loads(t["path"]) if len(p) >= 6 and int(p[0]) < len(files)]
            boxes = {int(p[0]): _jr_box_at(det, files[int(p[0])], p[4], p[5]) for p in path}
            # the frames where this number was actually READ on this track (a confident read)
            read_t = [tt for tt, b in boxes.items() if b is not None and any(
                txt == num and cf >= 0.5 for key_, v in _reads_by_spot.get((files[tt], int(b[0]), int(b[1])), []) for txt, cf in v)]
            if not read_t:
                continue
            _n_jt_read += 1
            fps_ = float(globals().get("VISION_TRACK_FPS") or 2.0)
            near = [tt for tt in sorted(boxes) if boxes[tt] is not None
                    and min(abs(tt - r_) for r_ in read_t) <= JERSEY_TRAIN_NEAR_READ_S * fps_]
            for tt in [near[int(k)] for k in np.linspace(0, len(near) - 1, min(JERSEY_TRAIN_CROPS_PER_TRACK, len(near)))]:
                f, box = files[tt], boxes[tt]
                if (f, int(box[0]), int(box[1])) in coach_spots:     # never train on a test crop
                    continue
                # (frame archive) a crop already in the training set needs no picture (an archived clip stays packed)
                if os.path.exists(os.path.join(JERSEY_TRAIN_DIR, _jr_dir("reads"), num, _jr_name(f, box))):
                    continue
                im = _img(f)
                c = _jr_chest(im, box) if im is not None else None
                if c is None or cv2.Laplacian(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() < JERSEY_TRAIN_MIN_SHARPNESS:
                    continue
                if _jr_save(im, box, os.path.join(JERSEY_TRAIN_DIR, _jr_dir("reads"), num, _jr_name(f, box))):
                    added["reads"] += 1
    added["_tracks"] = (_n_jt, _n_jt_read)
    return added


def jersey_import_extra():
    """Extra labeled data: folders of <number>/ images, or JSONL exports ({"image": ..., "suffix": "23"}) -> extra/."""
    import shutil
    import cv2
    n = 0
    dirs = list(JERSEY_TRAIN_EXTRA_DIRS)
    if JERSEY_TRAIN_ROBOFLOW_API_KEY:
        rf_dir = os.path.join(JERSEY_TRAIN_DIR, "_roboflow_nba")
        if not os.path.exists(rf_dir):
            try:
                import importlib
                if importlib.util.find_spec("roboflow") is None:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "roboflow"])
                from roboflow import Roboflow
                print("  [recognizer] downloading Roboflow's NBA jersey-number set (CC BY 4.0), once...", flush=True)
                proj = Roboflow(api_key=JERSEY_TRAIN_ROBOFLOW_API_KEY).workspace("roboflow-jvuqo").project(
                    "basketball-jersey-numbers-ocr")
                proj.version(JERSEY_TRAIN_ROBOFLOW_VERSION).download("jsonl", location=rf_dir)
            except Exception as e:
                print(f"  [recognizer] Roboflow download didn't work ({type(e).__name__}: {e}). You can download it from "
                      f"universe.roboflow.com/roboflow-jvuqo/basketball-jersey-numbers-ocr (format: JSONL), unzip it, "
                      f"and put that folder in JERSEY_TRAIN_EXTRA_DIRS.", flush=True)
        if os.path.exists(rf_dir):
            dirs.append(rf_dir)
    _jr_say(f"checking the extra labeled data for new crops ({len(dirs)} folder(s): "
            + ", ".join(os.path.basename(os.path.normpath(d)) for d in dirs) + ")...")
    for d in dirs:
        tag = re.sub(r"[^A-Za-z0-9]+", "_", os.path.basename(os.path.normpath(d)))[:30]
        # JSONL exports
        for jl in glob.glob(os.path.join(d, "**", "*.jsonl"), recursive=True):
            with open(jl, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    num = re.sub(r"\D", "", str(rec.get("suffix") or rec.get("text") or rec.get("label") or ""))
                    src = os.path.join(os.path.dirname(jl), str(rec.get("image") or ""))
                    if not num or len(num) > 2 or not os.path.exists(src):
                        continue
                    dst = os.path.join(JERSEY_TRAIN_DIR, "extra", num, f"{tag}_{os.path.basename(src)}")
                    if not os.path.exists(dst):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src, dst)
                        n += 1
        # <number>/ image folders (skipped when the folder IS the training set's own extra/ folder, e.g. JERSEY_TRAIN_EXTRA_DIRS
        # pointing at inputs/jersey_training/extra: its number folders are already the result of the import -- copying them
        # into themselves would add every image again, with a longer name, on every run)
        _in_place = os.path.abspath(d).startswith(os.path.abspath(os.path.join(JERSEY_TRAIN_DIR, "extra")))
        for sub in ([] if _in_place else glob.glob(os.path.join(d, "*"))):
            num = os.path.basename(sub)
            if not (os.path.isdir(sub) and re.fullmatch(r"\d{1,2}", num)):
                continue
            for src in glob.glob(os.path.join(sub, "*")):
                if src.lower().endswith((".jpg", ".jpeg", ".png")):
                    dst = os.path.join(JERSEY_TRAIN_DIR, "extra", num, f"{tag}_{os.path.basename(src)}")
                    if not os.path.exists(dst):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src, dst)
                        n += 1
    return n


def _jr_play_key(fname):
    """The PLAY a crop came from: its file name without the frame number and box position. CONFIRMED CHANGE (requested: the
    test half must not share plays with the training half). The same player a fraction of a second apart in the same play
    used to land in both halves, which flatters the score; now a whole play is on one side."""
    return re.sub(r"_(?:t)?\d+_jpg_\d+_\d+\.jpg$", "", os.path.basename(fname))


def _jr_coach_half(fname):
    """Which half of the coach checks a crop belongs to -- 'train' or 'test' -- fixed by its PLAY (JERSEY_TRAIN_SPLIT_BY =
    "play"; "crop" = the old split by file name), so a crop never switches halves between runs."""
    key = _jr_play_key(fname) if str(globals().get("JERSEY_TRAIN_SPLIT_BY", "play")).lower() == "play" else os.path.basename(fname)
    return "train" if int(hashlib.md5(key.encode()).hexdigest(), 16) % 2 == 0 else "test"


def _jr_train_sources():
    return ["reads", "extra"] + (["coach"] if JERSEY_TRAIN_USE_COACH else [])


def _jr_samples(sources):
    out = []
    for s in sources:
        for f in glob.glob(os.path.join(JERSEY_TRAIN_DIR, _jr_dir(s), "*", "*")):
            if not f.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            # only <number>/ folders are labels: a Roboflow download unzipped in place has train/, valid/ and test/ folders beside
            # the number folders, and their images (labels are in annotations.jsonl) must never be read as a class called "train"
            if not re.fullmatch(r"\d{1,2}|nn", os.path.basename(os.path.dirname(f))):
                continue
            # CONFIRMED CHANGE (requested: trained recognizer only -- EasyOCR / PaddleOCR removed, so the coach checks
            # are its main training data). JERSEY_TRAIN_USE_COACH = "half": half the checked players train it, the other
            # half stay the reader test's answer key (fixed per crop).
            if s == "coach" and JERSEY_TRAIN_USE_COACH == "half" and _jr_coach_half(f) != "train":
                continue
            out.append((f, os.path.basename(os.path.dirname(f))))
    return sorted(out)


def jersey_train():
    """Train the recognizer on the training set (CPU; a few to ~20 minutes depending on how much data)."""
    import torch
    import torchvision
    from torchvision import transforms
    from PIL import Image
    train_src = _jr_train_sources()
    samples = _jr_samples(train_src)
    classes = sorted({lab for _, lab in samples}, key=lambda x: (len(x), x))
    idx = {c: i for i, c in enumerate(classes)}
    # CONFIRMED CHANGE (requested: compare fixed vs pose fairly). The held-back 15% is now picked by PLAY for crops from our
    # own film (jersey-number tracks and coach checks), so crops of the same player a moment apart are never on both sides
    # (that flattered the round-by-round %). Extra (ready-made) crops are still picked at random.
    def _src_of(f):
        for s in ("coach", "reads"):
            if os.sep + _jr_dir(s) + os.sep in f:
                return s
        return "extra"

    def _is_val(f):
        key = os.path.basename(f) if _src_of(f) == "extra" else _jr_play_key(f)
        return int(hashlib.md5(("val|" + key).encode()).hexdigest(), 16) % 100 < 15

    val = [s_ for s_ in samples if _is_val(s_[0])] or samples[:1]
    tr = [s_ for s_ in samples if not _is_val(s_[0])]
    _val_src = [_src_of(f) for f, _ in val]
    norm = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    t_train = transforms.Compose([transforms.RandomResizedCrop(128, scale=(0.7, 1.0), ratio=(0.6, 1.4)),
                                  transforms.ColorJitter(0.3, 0.3, 0.3, 0.05), transforms.RandomRotation(8),
                                  transforms.RandomGrayscale(0.1), transforms.ToTensor(), norm])   # never flipped: 2 != S
    t_eval = transforms.Compose([transforms.Resize((128, 128)), transforms.ToTensor(), norm])

    class _DS(torch.utils.data.Dataset):
        def __init__(self, items, tf):
            self.items, self.tf = items, tf
        def __len__(self):
            return len(self.items)
        def __getitem__(self, k):
            f, lab = self.items[k]
            return self.tf(Image.open(f).convert("RGB")), idx[lab]

    try:
        net = torchvision.models.resnet18(weights=torchvision.models.ResNet18_Weights.IMAGENET1K_V1)
    except Exception:
        net = torchvision.models.resnet18(pretrained=True)
    net.fc = torch.nn.Linear(net.fc.in_features, len(classes))
    # CONFIRMED CHANGE (requested; the 45% test showed 32 and 15 as the answer to many other numbers): the model leaned toward
    # the numbers most common in the training pictures. Each draw is now weighted so every NUMBER counts about equally
    # (JERSEY_TRAIN_BALANCE: 1 = fully equal, 0 = off, 0.75 = mostly), and a crop from your own checks counts
    # JERSEY_TRAIN_COACH_WEIGHT times as much as a generic one (they are the only crops from your gym and camera).
    _bal = float(globals().get("JERSEY_TRAIN_BALANCE", 0.75))
    _cw = float(globals().get("JERSEY_TRAIN_COACH_WEIGHT", 3.0))
    _cnt_c = {}
    for _f, _l in tr:
        _cnt_c[_l] = _cnt_c.get(_l, 0) + 1
    _w = [(1.0 / (_cnt_c[_l] ** _bal)) * (_cw if (os.sep + _jr_dir("coach") + os.sep) in _f else 1.0) for _f, _l in tr]
    _sampler = torch.utils.data.WeightedRandomSampler(_w, num_samples=len(tr), replacement=True,
                                                      generator=torch.Generator().manual_seed(0))
    dl = torch.utils.data.DataLoader(_DS(tr, t_train), batch_size=32, sampler=_sampler, num_workers=0)
    dv = torch.utils.data.DataLoader(_DS(val, t_eval), batch_size=64, shuffle=False, num_workers=0)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, JERSEY_TRAIN_EPOCHS))
    loss_fn = torch.nn.CrossEntropyLoss(label_smoothing=0.05)
    print(f"  [recognizer] training on {len(tr):,} crops ({len(classes)} numbers), checking on {len(val):,}...", flush=True)
    t0 = time.time()
    best = (-1.0, None, 0.0)
    for ep in range(JERSEY_TRAIN_EPOCHS):
        net.train()
        for xb, yb in dl:
            opt.zero_grad()
            loss_fn(net(xb), yb).backward()
            opt.step()
        sched.step()
        net.eval()
        hits = []
        with torch.no_grad():
            for xb, yb in dv:
                hits += (net(xb).argmax(1) == yb).tolist()
        _by = {}
        for h_, s_ in zip(hits, _val_src):
            _by.setdefault(s_, []).append(h_)
        acc = sum(hits) / max(len(hits), 1)
        # "our film" = jersey-number tracks + coach checks: the crops that look like what the reader sees in our games.
        # The model kept is the best round on OUR FILM when there are enough of those crops (else on everything).
        _own = _by.get("reads", []) + _by.get("coach", [])
        score = (sum(_own) / len(_own)) if len(_own) >= 50 else acc
        if score >= best[0]:
            best = (score, {k: v.clone() for k, v in net.state_dict().items()}, acc, len(_own) >= 50,
                    (sum(_own) / len(_own)) if _own else None)
        _parts = ", ".join(f"{n_} {sum(_by[k_]) / len(_by[k_]):.0%} of {len(_by[k_])}"
                           for k_, n_ in (("reads", "number tracks"), ("coach", "coach checks"), ("extra", "extra")) if _by.get(k_))
        print(f"  [recognizer]   round {ep + 1}/{JERSEY_TRAIN_EPOCHS}: {acc:.0%} of held-back crops right ({_parts}) "
              f"({(time.time() - t0) / 60:.1f} min so far)", flush=True)
    net.load_state_dict(best[1])
    torch.save({"state_dict": net.state_dict(), "classes": classes, "n_train": len(tr), "val_acc": best[0],
                "sources": {s: sum(1 for f, _ in samples if os.sep + _jr_dir(s) + os.sep in f) for s in train_src},
                "crop_style": _jr_style(),
                "signature": _jr_signature(), "n_samples": len(samples),
                "settings": _jr_settings_str(), "trained_at": pd.Timestamp.now().isoformat(timespec="seconds")},
               JERSEY_MODEL_PATH + ".tmp")
    for _try in range(8):                                         # swapped in only once fully written (full-disk safe);
        try:                                                      # retried while OneDrive / antivirus holds the file
            os.replace(JERSEY_MODEL_PATH + ".tmp", JERSEY_MODEL_PATH)
            break
        except PermissionError:
            time.sleep(0.25 * (_try + 1))
    else:
        import shutil
        shutil.copyfile(JERSEY_MODEL_PATH + ".tmp", JERSEY_MODEL_PATH)
        os.remove(JERSEY_MODEL_PATH + ".tmp")
    # CONFIRMED BUG (fixed; the pose recognizer reported "87% right on our own film" while every round showed ~30% on the
    # coach checks): with fewer than 50 of our own crops held back, the round is chosen on ALL held-back crops, and that
    # score was printed as "our own film". It now says which it was.
    if len(best) > 3 and not best[3]:
        print(f"  [recognizer] saved -> {JERSEY_MODEL_PATH} (kept round: {best[2]:.0%} on all held-back crops; our own film "
              f"{(best[4] or 0):.0%} -- too few of our own crops held back (under 50) to choose the round by)", flush=True)
    else:
        print(f"  [recognizer] saved -> {JERSEY_MODEL_PATH} (kept round: {best[0]:.0%} right on our own film, "
              f"{best[2]:.0%} on all held-back crops)", flush=True)


def _jr_settings_str():
    return repr((JERSEY_TRAIN_EPOCHS, str(JERSEY_TRAIN_USE_COACH), str(globals().get("JERSEY_TRAIN_SPLIT_BY", "play")),
                 float(globals().get("JERSEY_TRAIN_BALANCE", 0.75)), float(globals().get("JERSEY_TRAIN_COACH_WEIGHT", 3.0))))


def _jr_signature():
    files = [os.path.relpath(f, JERSEY_TRAIN_DIR) for f, _ in _jr_samples(_jr_train_sources())]
    return hashlib.md5((repr(files) + repr((JERSEY_TRAIN_EPOCHS, JERSEY_TRAIN_USE_COACH, globals().get("JERSEY_TRAIN_SPLIT_BY", "play"), globals().get("JERSEY_TRAIN_BALANCE", 0.75), globals().get("JERSEY_TRAIN_COACH_WEIGHT", 3.0)))).encode()).hexdigest()


def jersey_recognizer_read(crops_bgr, style="fixed"):
    """Color chest crops -> [(number, probability)] with the saved recognizer for that crop style (None if there is no model)."""
    import torch
    import torchvision
    from torchvision import transforms
    from PIL import Image
    _mk = "_jr_model" if style != "pose" else "_jr_model_pose"
    m = globals().get(_mk)
    if m is None:
        _mp = _jr_path_for(style)
        if not os.path.exists(_mp):
            return None
        try:
            ck = torch.load(_mp, map_location="cpu")
        except Exception as _le:                       # an empty / cut-short model file (a full disk mid-save)
            try:
                os.replace(_mp, _mp + ".broken")
            except Exception:
                pass
            print(f"  [jersey] saved model {os.path.basename(_mp)} was damaged ({type(_le).__name__}) -- set aside as "
                  f".broken; numbers aren't read until the recognizer is trained again (Jersey-number recognizer cell)",
                  flush=True)
            return None
        net = torchvision.models.resnet18(weights=None)
        net.fc = torch.nn.Linear(net.fc.in_features, len(ck["classes"]))
        net.load_state_dict(ck["state_dict"])
        net.eval()
        tf = transforms.Compose([transforms.Resize((128, 128)), transforms.ToTensor(),
                                 transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
        m = globals()[_mk] = (net, ck["classes"], tf)
    net, classes, tf = m
    out = []
    with torch.no_grad():
        for c in crops_bgr:
            if c is None or c.size == 0:
                out.append(("", 0.0))
                continue
            x = tf(Image.fromarray(c[:, :, ::-1].copy())).unsqueeze(0)
            pr = torch.softmax(net(x), 1)[0]
            j = int(pr.argmax())
            out.append((classes[j], float(pr[j])))
    return out


def _jr_inputs_fingerprint():
    """Everything this cell reads -> one fingerprint. CONFIRMED CHANGE (requested: "this should only run if there is
    new information compared to the last run"). New training data can only come from: coach checks (Play review /
    validation files, in INPUT_DIR or Downloads), extra-data folders, Roboflow's set, crops added or deleted by hand in
    the training folder, or changed settings -- not from tracking runs (the recognizer never learns from its own
    readings, and the other readers are off; if they're switched back on, their readings count too)."""
    parts = []
    # CONFIRMED CHANGE (requested: everything in the data folder): coach checks are the saved reviews in
    # <data>/play_review_saves (any .json there is a review, whatever its name)
    for f in glob.glob(os.path.join(_play_review_file_saves(), "*.json")):
        parts.append((os.path.basename(f), os.path.getsize(f), int(os.path.getmtime(f))))
    def _dir_state(d):
        n, latest = 0, 0
        for root, _ds, fs in os.walk(d):
            for f in fs:
                n += 1
                latest = max(latest, int(os.path.getmtime(os.path.join(root, f))))
        return (n, latest)
    parts += [("extra", d, _dir_state(d)) for d in JERSEY_TRAIN_EXTRA_DIRS if os.path.isdir(d)]
    parts.append(("roboflow", bool(JERSEY_TRAIN_ROBOFLOW_API_KEY),
                  os.path.isdir(os.path.join(JERSEY_TRAIN_DIR, "_roboflow_nba"))))
    parts.append(("training_folder",) + _dir_state(JERSEY_TRAIN_DIR))
    if JERSEY_TRAIN_FROM_OWN_READS or any(e != "trained" for e in globals().get("JERSEY_READER_ENGINES", ["trained"])):
        for f in (os.path.join(INPUT_DIR, "_tracking", "jersey_numbers.pkl"), os.path.join(OUTPUT_DIR, "uww_player_tracks.csv")):
            parts.append((os.path.basename(f), int(os.path.getmtime(f)) if os.path.exists(f) else 0))
    parts.append(("model", int(os.path.getmtime(JERSEY_MODEL_PATH)) if os.path.exists(JERSEY_MODEL_PATH) else 0))
    parts.append(("settings", JERSEY_TRAIN_ADD_FRAMES, JERSEY_TRAIN_CROPS_PER_TRACK, JERSEY_TRAIN_NEAR_READ_S,
                  JERSEY_TRAIN_MIN_SHARPNESS, str(JERSEY_TRAIN_USE_COACH), JERSEY_TRAIN_FROM_OWN_READS, JERSEY_TRAIN_EPOCHS,
                  JERSEY_TRAIN_MIN_IMAGES, str(globals().get("JERSEY_TRAIN_SPLIT_BY", "play")),
                  float(globals().get("JERSEY_TRAIN_BALANCE", 0.75)), float(globals().get("JERSEY_TRAIN_COACH_WEIGHT", 3.0))))
    return hashlib.md5(repr(sorted(map(repr, parts))).encode()).hexdigest()


_JR_BASE_MODEL_PATH = globals().get("_JR_BASE_MODEL_PATH") or JERSEY_MODEL_PATH
_jr_cs = str(globals().get("JERSEY_CROP_STYLE", "fixed")).lower()
_jr_styles = ["fixed", "pose"] if _jr_cs == "compare" else (["pose"] if _jr_cs == "pose" else ["fixed"])

if RUN_JERSEY_RECOGNIZER:
    _jr_t_cell = _jr_time.time()
    _jr_steps.clear()
    for _JR_STYLE in _jr_styles:
        JERSEY_MODEL_PATH = _jr_path_for(_JR_STYLE)
        _JR_LAST_INPUTS = os.path.join(JERSEY_TRAIN_DIR, "_last_inputs.json" if _JR_STYLE == "fixed" else "_last_inputs_pose.json")
        if len(_jr_styles) > 1:
            print(f"--- jersey crop style: {_JR_STYLE} ---", flush=True)
        try:
            os.makedirs(JERSEY_TRAIN_DIR, exist_ok=True)
            _jr_step("checking whether anything changed since the last run (coach checks, extra data, the training folder, "
                     "settings)")
            _jr_fp = _jr_inputs_fingerprint()
            _jr_last = None
            if os.path.exists(_JR_LAST_INPUTS):
                try:
                    with open(_JR_LAST_INPUTS) as _fh:
                        _jr_last = json.load(_fh).get("fingerprint")
                except Exception:
                    _jr_last = None
            if JERSEY_TRAIN_NOW is not True and _jr_last == _jr_fp and os.path.exists(JERSEY_MODEL_PATH):
                print("Jersey-number recognizer: nothing new since the last run (no new checks, extra data or settings) "
                      "-- skipped. JERSEY_TRAIN_NOW = True forces a run.", flush=True)
                raise StopIteration
            if JERSEY_TRAIN_ADD_FRAMES:
                _jr_step("adding new training crops")
                _added = jersey_collect()
                _jr_step("adding the extra labeled data")
                _added["extra"] = jersey_import_extra()
                print(f"Jersey-number recognizer: added {_added['reads']} crop(s) from players named by jersey number "
                      f"({_added['_tracks'][0]} such track(s) in the last run, {_added['_tracks'][1]} with a confirmed reading to "
                      f"take crops around), {_added['coach']} from coach checks, {_added['extra']} from extra data", flush=True)
            _jr_step("counting the training set")
            _cnt = {s: len(_jr_samples([s])) for s in ("reads", "coach", "extra")}
            _cn = len(glob.glob(os.path.join(JERSEY_TRAIN_DIR, _jr_dir("coach"), "*", "*")))
            _how = ("half trained on, half kept as the TEST set" if JERSEY_TRAIN_USE_COACH == "half"
                    else "trained on" if JERSEY_TRAIN_USE_COACH else "kept as the TEST set")
            print(f"  [{_jr_style()} crop] training set: {_cnt['reads']:,} from jersey-number tracks, {_cnt['extra']:,} extra, {_cn:,} coach "
                  f"checks ({_how})  -- {JERSEY_TRAIN_DIR}", flush=True)
            _n_coach_train = len(_jr_samples(["coach"])) if JERSEY_TRAIN_USE_COACH else 0
            _n_train = _cnt["reads"] + _cnt["extra"] + _n_coach_train
            _saved_sig, _saved_n, _saved_set = None, None, None
            _saved_classes = set()
            _jr_step("comparing the training set with the saved recognizer (retrain or keep it?)")
            if os.path.exists(JERSEY_MODEL_PATH):
                try:
                    import torch
                    _ck_ = torch.load(JERSEY_MODEL_PATH, map_location="cpu")
                    _saved_sig, _saved_set = _ck_.get("signature"), _ck_.get("settings")
                    _saved_n = _ck_.get("n_samples") or _ck_.get("n_train")
                    _saved_classes = set(_ck_.get("classes") or [])
                except Exception:
                    _saved_sig = None
            # CONFIRMED CHANGE (requested: "is it really necessary to retrain every time I add pictures from the player checks?").
            # "auto" now retrains only when the training set has GROWN enough since the saved model: at least JERSEY_TRAIN_MIN_NEW
            # new crops or JERSEY_TRAIN_MIN_GROWTH (a share, 0.15 = 15%) more than it was trained on -- or when the epochs / coach
            # setting changed, or there is no model yet. JERSEY_TRAIN_MIN_NEW = 0 retrains on any change (the old behaviour).
            _want = JERSEY_TRAIN_NOW is True
            # CONFIRMED CHANGE (the new "no number" examples sat unused under the retrain bar): an answer the saved model doesn't
            # know yet -- a new jersey number, or "nn" (no number) -- always retrains it, however few crops were added.
            if not _want and JERSEY_TRAIN_NOW == "auto" and os.path.exists(JERSEY_MODEL_PATH) and _saved_sig is not None:
                _new_cls = {lab for _f, lab in _jr_samples(_jr_train_sources())} - _saved_classes
                if _new_cls:
                    _want = True
                    print(f"  the training set has answer(s) the saved recognizer doesn't know: {', '.join(sorted(_new_cls))} "
                          f"(\"nn\" = no number) -- retraining", flush=True)
            if not _want and JERSEY_TRAIN_NOW == "auto" and _saved_sig != _jr_signature():
                _now_n = len(_jr_samples(_jr_train_sources()))
                _min_new = int(globals().get("JERSEY_TRAIN_MIN_NEW", 150))
                _min_gr = float(globals().get("JERSEY_TRAIN_MIN_GROWTH", 0.15))
                _new_n = (_now_n - int(_saved_n)) if _saved_n else None
                if (not os.path.exists(JERSEY_MODEL_PATH) or _saved_n is None or _saved_set != _jr_settings_str()
                        or _min_new <= 0 or abs(_new_n) >= _min_new or abs(_new_n) >= _min_gr * max(int(_saved_n), 1)):
                    _want = True
                else:
                    print(f"  training set changed by {_new_n:+,} crop(s) since the saved model ({int(_saved_n):,} then, {_now_n:,} now) -- "
                          f"under the retrain bar of {_min_new} crops or {_min_gr:.0%}, so the saved recognizer is kept "
                          f"(JERSEY_TRAIN_NOW = True forces a retrain).", flush=True)
            if _want and _n_train < JERSEY_TRAIN_MIN_IMAGES:
                print(f"  not trained yet: {_n_train} training crop(s), needs {JERSEY_TRAIN_MIN_IMAGES} (check more players, "
                      f"run tracking with jersey numbers on, or add extra data)", flush=True)
            elif _want:
                globals().pop("_jr_model" if _jr_style() != "pose" else "_jr_model_pose", None)
                _jr_step(f"retraining the recognizer ({JERSEY_TRAIN_EPOCHS} rounds)")
                jersey_train()
            elif os.path.exists(JERSEY_MODEL_PATH):
                print("  saved recognizer is up to date with the training set -- not retrained", flush=True)
            # remember what this run saw (after training: the model file is part of it)
            with open(_JR_LAST_INPUTS, "w") as _fh:
                json.dump({"fingerprint": _jr_inputs_fingerprint(), "saved": pd.Timestamp.now().isoformat(timespec="seconds")}, _fh)
        except StopIteration:
            pass
        except Exception as _e:
            print(f"Jersey-number recognizer skipped: {type(_e).__name__}: {_e}")
    _jr_step(None)
    _jr_tot = _jr_time.time() - _jr_t_cell
    if _jr_tot >= 30:
        print(f"  Jersey-number recognizer -- where the time went ({_jr_tot / 60:.1f} min in all): "
              + "; ".join(f"{n} {sec / 60:.1f} min" for n, sec in sorted(_jr_steps, key=lambda x: -x[1]) if sec >= 5),
              flush=True)
    _JR_STYLE = "fixed"
    JERSEY_MODEL_PATH = _JR_BASE_MODEL_PATH
    _jr_torso_save()

