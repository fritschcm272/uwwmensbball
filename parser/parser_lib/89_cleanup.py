# 89_cleanup.py -- code for the notebook section "Cleanup: free the disk space taken by things the parser no longer uses -------------------"
# Runs inside the notebook via run_section("89_cleanup"); its settings are in that notebook cell.

# --- Cleanup: free the disk space taken by things the parser no longer uses -------------------------------------------
# CONFIRMED CHANGE (requested: "what parts can be removed to speed up time and save disk space"). Leftovers from earlier
# versions that nothing reads anymore:
#   * old tracking-frame folders (track\ at 768 wide, track1024\ -- captured before the clip-start fix, so often the
#     wrong play) and the old-style key frames from before that fix (<pos>_<id>_<n>.jpg without "_v2_")
#   * detection / jersey-color / pose files from other detectors or models than the current ones (e.g. yolo11n)
#   * entries in the saved results that point at frames no longer on disk (court mapping, fingerprints, jersey readings),
#     and saved answers of readers no longer in the reader test
#   * TrOCR's downloaded model (~250 MB) when trocr isn't tested; old review zips in INPUT_DIR
# Frames your court calibration uses are ALWAYS kept. CLEANUP_DRY_RUN = True only LISTS what would go and how much space
# it frees -- set it to False to actually delete.
import os
import re
import glob
import shutil



def _cl_size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    tot = 0
    for root, _d, files in os.walk(path):
        for f in files:
            try:
                tot += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return tot


def _cl_mb(b):
    return f"{b / 1e6:,.0f} MB" if b >= 1e6 else f"{b / 1e3:,.0f} KB"


def cleanup(dry_run=True):
    vfd = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    tdir = globals().get("TRACK_DIR") or os.path.join(INPUT_DIR, "_tracking")
    # frames the court calibration uses: never deleted
    keep = set()
    for f in glob.glob(os.path.join(INPUT_DIR, "court_calibration", "court_calibration_*.json")):
        try:
            with open(f) as fh:
                keep |= {os.path.normpath(os.path.join(vfd, fr["file"])) for fr in json.load(fh).get("frames", [])}
        except Exception:
            pass
    cur_track = _vision_track_folder() if "_vision_track_folder" in globals() else None
    ver = int(globals().get("VISION_CAPTURE_VERSION", 1))
    plan = []                                       # (what, path, bytes)
    gone = set()                                    # frame files that will no longer exist
    for gdir in [d for d in glob.glob(os.path.join(vfd, "*")) if os.path.isdir(d)]:
        for sub in [d for d in glob.glob(os.path.join(gdir, "track*")) if os.path.isdir(d)]:
            if cur_track and os.path.basename(sub) != cur_track:
                files = [os.path.normpath(p) for p in glob.glob(os.path.join(sub, "*"))]
                if any(p in keep for p in files):   # calibration uses some: delete only the others
                    for p in files:
                        if p not in keep:
                            plan.append(("old tracking frame", p, os.path.getsize(p)))
                            gone.add(p)
                else:
                    plan.append((f"old tracking-frame folder ({len(files):,} files)", sub, _cl_size(sub)))
                    gone |= set(files)
        if ver >= 2:
            for p in glob.glob(os.path.join(gdir, "*.jpg")):
                if re.fullmatch(r"\d+_[0-9a-f]{8}_\d+\.jpg", os.path.basename(p)) and os.path.normpath(p) not in keep:
                    plan.append(("old key frame (before the clip-start fix)", p, os.path.getsize(p)))
                    gone.add(os.path.normpath(p))
    # detection / jersey-color / pose files from other detectors or models
    cur = set()
    if "_trk_det_cache_path" in globals():
        dp = _trk_det_cache_path()
        cur |= {os.path.normpath(dp), os.path.normpath(dp.replace(".pkl", "_jersey.pkl"))}
        cur.add(os.path.normpath(dp.replace("detections_" + re.sub(r"[^A-Za-z0-9]+", "_", TRACK_DETECTOR),
                                            "pose_" + re.sub(r"[^A-Za-z0-9]+", "_", TRACK_POSE_MODEL))))
    for p in glob.glob(os.path.join(tdir, "detections_*.pkl")) + glob.glob(os.path.join(tdir, "pose_*.pkl")):
        if cur and os.path.normpath(p) not in cur:
            plan.append(("old detection / pose file", p, os.path.getsize(p)))
    if not globals().get("TRACK_USE_APPEARANCE", True):
        for p in glob.glob(os.path.join(tdir, "fingerprints_*.pkl")):
            plan.append(("appearance fingerprints (appearance is switched off)", p, os.path.getsize(p)))
    # saved results that point at frames that won't exist
    def _exists(rel):
        full = os.path.normpath(os.path.join(vfd, rel))
        return full not in gone and os.path.exists(full)
    prune = []
    for name in ("court_homographies.pkl", "jersey_numbers.pkl") + tuple(
            os.path.basename(p) for p in glob.glob(os.path.join(tdir, "fingerprints_*.pkl"))
            if globals().get("TRACK_USE_APPEARANCE", True)):
        p = os.path.join(tdir, name)
        if os.path.exists(p):
            d = pd.read_pickle(p)
            drop = [k for k in d if not str(k).startswith("_") and not _exists(str(k).split("|")[0])]   # "_sig", "_sig_by_arena": bookkeeping
            if drop:
                prune.append((p, d, drop))
    rt = os.path.join(tdir, "jersey_reader_test.pkl")
    if os.path.exists(rt):
        d = pd.read_pickle(rt)
        engines = set(globals().get("JERSEY_READER_ENGINES", [])) | {"__trained_model__"}
        drop = [k for k in d if isinstance(k, tuple) and k[0] not in engines]
        if drop and engines != {"__trained_model__"}:
            prune.append((rt, d, drop))
    # TrOCR's model, old review zips
    if "trocr" not in globals().get("JERSEY_READER_ENGINES", ["trocr"]):
        hf = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub", "models--microsoft--trocr-small-printed")
        if os.path.exists(hf):
            plan.append(("TrOCR's downloaded model (trocr isn't tested anymore)", hf, _cl_size(hf)))
    # readers no longer tested: their downloaded models (reinstall happens automatically if one is put back)
    engines = set(globals().get("JERSEY_READER_ENGINES", ["easyocr", "paddle"]))
    home = os.path.expanduser("~")
    if not any(e.startswith("paddle") for e in engines):
        for p in (os.path.join(home, ".paddlex", "official_models"), os.path.join(home, ".paddleocr")):
            if os.path.exists(p):
                plan.append(("PaddleOCR's downloaded models (PaddleOCR isn't used anymore)", p, _cl_size(p)))
    if not any(e.startswith("easyocr") for e in engines):
        p = os.path.join(home, ".EasyOCR")
        if os.path.exists(p):
            plan.append(("EasyOCR's downloaded models (EasyOCR isn't used anymore)", p, _cl_size(p)))
    for p in glob.glob(os.path.join(INPUT_DIR, "tracking_review_first5*.zip")):
        plan.append(("old review zip", p, os.path.getsize(p)))

    total = sum(b for _w, _p, b in plan)
    print(f"Cleanup ({'DRY RUN -- nothing deleted' if dry_run else 'DELETING'}): {len(plan):,} item(s), {_cl_mb(total)}")
    by_what = {}
    for w, p, b in plan:
        by_what.setdefault(w, [0, 0, p])
        by_what[w][0] += 1
        by_what[w][1] += b
    for w, (n, b, ex) in sorted(by_what.items(), key=lambda x: -x[1][1]):
        print(f"  {w}: {n:,} ({_cl_mb(b)})  e.g. {ex}")
    for p, d, drop in prune:
        print(f"  {os.path.basename(p)}: {len(drop):,} of {len(d):,} saved entries point at frames or readers no longer used")
    if dry_run:
        print("  -> set CLEANUP_DRY_RUN = False and run this cell again to delete these.")
        return
    for _w, p, _b in plan:
        try:
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        except OSError as e:
            print(f"  couldn't delete {p}: {e}")
    for p, d, drop in prune:
        for k in drop:
            d.pop(k, None)
        pd.to_pickle(d, p)
    print(f"  done -- freed about {_cl_mb(total)}")


if RUN_CLEANUP:
    try:
        cleanup(dry_run=CLEANUP_DRY_RUN)
    except Exception as _e:
        print(f"Cleanup skipped: {type(_e).__name__}: {_e}")
