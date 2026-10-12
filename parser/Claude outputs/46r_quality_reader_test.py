# 46r_quality_reader_test.py -- code for the TEST notebook quality_test_nb.ipynb (not part of the main parser run)
# Runs inside that notebook via run_section("46r_quality_reader_test"), AFTER the capture cell (it reads its files).
#
# CONFIRMED CHANGE (requested: Standard vs High -- which gives better player tracking?). The sharpness score can't decide
# it (compression blocks raise it, and the two qualities had different clips), so this runs the parser's OWN pieces on
# the SAME clips of every version:
#   * the player detector -> how many players are found per frame
#   * the trained jersey-number reader (fixed chest crop) on every player not hidden behind someone -> how many SURE
#     reads (confidence >= 0.90, the cutoff tracking uses; 0.95 shown too)
# Versions: Standard (stream size), High (stream size, 1280 wide), High shrunk to 1024 (what the parser saves today).
# Only clips captured in EVERY quality count, and every QT_READER_EVERY-th frame, so it takes a few minutes on a CPU.

import glob
import os

import numpy as np
import pandas as pd


def _qtr_versions(clips):
    ok = clips[pd.to_numeric(clips["frames"], errors="coerce").fillna(0) > 0]
    both = set.intersection(*[set(ok[ok["quality"] == q]["clip"]) for q in ok["quality"].unique()]) if len(ok) else set()
    out = []
    for q in ok["quality"].unique():
        for sub in ("full", "w1024"):
            if sub == "w1024" and str(q).lower().startswith("s"):
                continue                       # Standard is already 1024 wide: its full and 1024 versions are the same
            for _, r in ok[(ok["quality"] == q) & ok["clip"].isin(both)].iterrows():
                files = sorted(glob.glob(os.path.join(r["folder"], sub, "*.jpg")))[::max(1, int(QT_READER_EVERY))]
                out.append((f"{q} {'(' + str(int(r['stream_w'])) + ' wide)' if sub == 'full' else '(shrunk to 1024)'}",
                            int(r["clip"]), files))
    return out, sorted(both)


def qt_reader_compare():
    import cv2
    from ultralytics import YOLO
    clips = pd.read_csv(os.path.join(QT_DIR, "quality_test_clips.csv"))
    versions, both = _qtr_versions(clips)
    if not versions:
        print("No clips captured in every quality -- run the capture cell first.")
        return pd.DataFrame()
    print(f"Reader test on clips {both} (captured in every quality), every {QT_READER_EVERY} frame(s)", flush=True)
    det = YOLO(QT_READER_DETECTOR)
    rows = []
    for label, clip, files in versions:
        n_frames = n_boxes = n_hidden = 0
        confs, nums = [], []
        for f in files:
            img = cv2.imread(f)
            if img is None:
                continue
            n_frames += 1
            # the detector sees each version at its own size (1280 frames are not shrunk back to 1024)
            res = det.predict(img, imgsz=int(32 * round(img.shape[1] / 32)), classes=[0], conf=0.35, verbose=False)[0]
            p = res.boxes.xyxy.cpu().numpy() if res.boxes is not None else np.zeros((0, 4))
            n_boxes += len(p)
            crops = []
            for j in range(len(p)):
                if _jr_hidden(p, j):
                    n_hidden += 1
                    continue
                if (p[j, 3] - p[j, 1]) < 0.06 * img.shape[0]:        # tiny (far end / crowd)
                    continue
                crops.append(_jr_chest(img, p[j], "fixed"))
            for (num, cf) in (jersey_recognizer_read([c for c in crops if c is not None], style="fixed") or []):
                confs.append(cf)
                nums.append(num)
        confs = np.array(confs) if confs else np.zeros(0)
        rows.append({"version": label, "clip": clip, "frames": n_frames, "players found": n_boxes,
                     "chests read": len(confs), "sure >= 0.90": int((confs >= 0.90).sum()),
                     "sure >= 0.95": int((confs >= 0.95).sum()), "_conf_sum": float(confs.sum())})
        print(f"  {label}, clip {clip}: {n_frames} frames, {n_boxes} players, {len(confs)} chests, "
              f"{int((confs >= 0.90).sum())} sure reads", flush=True)
    per_clip = pd.DataFrame(rows)
    g = per_clip.groupby("version", sort=False)
    summ = g[["frames", "players found", "chests read", "sure >= 0.90", "sure >= 0.95"]].sum()
    summ["players per frame"] = (summ["players found"] / summ["frames"].clip(lower=1)).round(2)
    summ["sure reads per 100 chests"] = (100 * summ["sure >= 0.90"] / summ["chests read"].clip(lower=1)).round(1)
    summ["avg confidence"] = (g["_conf_sum"].sum() / summ["chests read"].clip(lower=1)).round(3)
    summ = summ.reset_index()
    per_clip.drop(columns="_conf_sum").to_csv(os.path.join(QT_DIR, "quality_reader_by_clip.csv"), index=False)
    summ.to_csv(os.path.join(QT_DIR, "quality_reader_summary.csv"), index=False)
    return summ


qt_reader_summary = qt_reader_compare()
print("\nWhich version gives the tracking more to work with (same clips, same detector, same jersey reader):")
(_show if "_show" in globals() else print)(qt_reader_summary)
print("More 'sure reads per 100 chests' = more players the reader can name. The reader was trained on Standard 1024 crops,"
      " so this compares them with a reader that has only ever seen Standard -- retraining on High crops could move High's numbers.")
