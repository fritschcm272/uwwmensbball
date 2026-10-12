# 46s_quality_paired.py -- code for the TEST notebook quality_test_nb.ipynb (not part of the main parser run)
# Runs via run_section("46s_quality_paired") after the reader test cell (needs the jersey reader's functions loaded).
#
# CONFIRMED CHANGE (requested follow-up to the reader test): High at 1280 found ~50% more people per frame, so its extra
# sure reads may be bench / crowd, not players on the floor. This compares the SAME PERSON in the SAME FRAME: every person
# the detector finds in the Standard frame is matched to the same person in the High frame (box positions scaled to the
# same size, overlap >= 0.5), and the reader reads both chests. Only those matched people count, so the extra people
# High finds don't inflate it.

import glob
import os

import numpy as np
import pandas as pd


def _qts_iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def _qts_detect(det, img):
    res = det.predict(img, imgsz=int(32 * round(img.shape[1] / 32)), classes=[0], conf=0.35, verbose=False)[0]
    return res.boxes.xyxy.cpu().numpy() if res.boxes is not None else np.zeros((0, 4))


def _qts_read(img, boxes, keep):
    crops = [_jr_chest(img, boxes[j], "fixed") for j in keep]
    out = jersey_recognizer_read([c if c is not None else np.zeros((0, 0, 3), np.uint8) for c in crops], style="fixed") or []
    return {j: r for j, r in zip(keep, out)}


def qt_paired_compare(other_sub="full"):
    """Standard (1024) vs High `other_sub` ("full" = 1280, "w1024" = shrunk) on the same people."""
    import cv2
    from ultralytics import YOLO
    clips = pd.read_csv(os.path.join(QT_DIR, "quality_test_clips.csv"))
    ok = clips[pd.to_numeric(clips["frames"], errors="coerce").fillna(0) > 0]
    std = ok[ok["quality"].str.lower().str.startswith("s")].set_index("clip")["folder"]
    hi = ok[ok["quality"].str.lower().str.startswith("h")].set_index("clip")["folder"]
    det = globals().get("_qts_det") or YOLO(QT_READER_DETECTOR)
    globals()["_qts_det"] = det
    tally = {"people matched": 0, "Standard sure": 0, "High sure": 0, "both sure, same number": 0,
             "both sure, DIFFERENT number": 0, "only Standard sure": 0, "only High sure": 0}
    for clip in sorted(set(std.index) & set(hi.index)):
        sf = sorted(glob.glob(os.path.join(std[clip], "full", "*.jpg")))[::max(1, int(QT_READER_EVERY))]
        for f in sf:
            g = os.path.join(hi[clip], other_sub, os.path.basename(f))
            a, b = cv2.imread(f), cv2.imread(g)
            if a is None or b is None:
                continue
            pa, pb = _qts_detect(det, a), _qts_detect(det, b)
            sc = a.shape[1] / b.shape[1]
            pairs, used = [], set()
            for i in range(len(pa)):
                if _jr_hidden(pa, i) or (pa[i, 3] - pa[i, 1]) < 0.06 * a.shape[0]:
                    continue
                best, bj = 0.5, None
                for j in range(len(pb)):
                    if j in used:
                        continue
                    o = _qts_iou(pa[i], pb[j] * sc)
                    if o >= best:
                        best, bj = o, j
                if bj is not None and not _jr_hidden(pb, bj):
                    used.add(bj)
                    pairs.append((i, bj))
            if not pairs:
                continue
            ra = _qts_read(a, pa, [i for i, _ in pairs])
            rb = _qts_read(b, pb, [j for _, j in pairs])
            for i, j in pairs:
                (na, ca), (nb, cb) = ra.get(i, ("", 0.0)), rb.get(j, ("", 0.0))
                sa, sb = ca >= 0.90, cb >= 0.90
                tally["people matched"] += 1
                tally["Standard sure"] += sa
                tally["High sure"] += sb
                if sa and sb:
                    tally["both sure, same number" if na == nb else "both sure, DIFFERENT number"] += 1
                elif sa:
                    tally["only Standard sure"] += 1
                elif sb:
                    tally["only High sure"] += 1
    return tally


qt_paired = {}
for _sub, _lab in (("full", "High at 1280"), ("w1024", "High shrunk to 1024")):
    print(f"Same people, Standard vs {_lab}...", flush=True)
    qt_paired[_lab] = qt_paired_compare(_sub)
qt_paired_table = pd.DataFrame(qt_paired)
qt_paired_table.index.name = "same person, same frame (confidence >= 0.90 = sure)"
qt_paired_table.to_csv(os.path.join(QT_DIR, "quality_paired.csv"))
(_show if "_show" in globals() else print)(qt_paired_table.reset_index())
print("Read it as: of the people both versions show, how many get a sure jersey read on Standard vs on High; 'only High sure'"
      " vs 'only Standard sure' is the real gain or loss, and 'DIFFERENT number' means one of the two sure reads is wrong.")
