# 46q_quality_test.py -- code for the TEST notebook quality_test_nb.ipynb (not part of the main parser run)
# Runs inside that notebook via run_section("46q_quality_test"); its settings are in the notebook cell.
#
# CONFIRMED CHANGE (requested): pick one game, capture its first QT_CLIPS clips once with the Synergy player on
# "Standard" and once on "High", and save everything to a separate test folder (QT_DIR) that can be deleted later.
# Nothing here touches _vision_frames, uww_clip_frames.csv, the training sets or any saved check.
#
# Uses the frame-capture functions from 46_frame_capture.py (_vision_open, _vision_set_quality, _vision_capture, ...).
# For each quality and clip it saves the tracking frames twice:
#   full/  -- at the stream's own size (whatever Synergy sends at that quality)
#   w1024/ -- shrunk to 1024 wide, exactly what the parser saves today (so the two qualities compare like for like)
# Then quality_test_summary.csv (one row per quality) and quality_test_clips.csv (one row per clip and quality).

import base64 as _qt_b64
import glob
import hashlib
import json
import os
import re
import shutil

import numpy as np
import pandas as pd

_QT_COLS = ["quality", "selected", "clip", "position", "description", "stream_w", "stream_h", "frames",
            "kb_full", "kb_1024", "sharp_full", "sharp_1024", "folder", "error"]


def _qt_find_game_url():
    """QT_GAME_URL if given, else the game named by QT_GAME in UWW's schedule (same name format as VISION_ONLY_GAME)."""
    if QT_GAME_URL:
        return QT_GAME_URL, QT_GAME or "game"
    globals()["VISION_ONLY_GAME"] = QT_GAME
    named = _vision_named_game()
    if named is None:
        raise ValueError("Set QT_GAME (e.g. '1_3_26 UW-Oshkosh Titans @ UW-Whitewater') or paste QT_GAME_URL.")
    ndate, words = named
    found, listed = [], []
    for sname in ("uww_team_schedule", "prev_games"):
        sched = globals().get(sname)
        if not isinstance(sched, pd.DataFrame) or sched.empty or "video_url" not in sched.columns:
            continue
        for _, g in sched[sched["video_url"].notna()].iterrows():
            gd = g.get("game_date")
            if gd is None or pd.isna(gd):
                try:
                    gd = parse_schedule_date(g["date"], uww_season_start_year)
                except Exception:
                    gd = None
            label = f"{pd.Timestamp(gd).date() if gd is not None else ''} {g.get('opponent', '')}".strip()
            listed.append(label)
            if gd is not None and abs((pd.Timestamp(gd) - ndate).days) <= 1 and any(w in label.lower() for w in words):
                found.append((abs((pd.Timestamp(gd) - ndate).days), label, g["video_url"]))
    if not found:
        raise ValueError(f"No clip page found for {QT_GAME!r}. Games with a clip page: " + "; ".join(listed[:40])
                         + " -- or open the game in Synergy and paste the address into QT_GAME_URL.")
    found.sort()
    return found[0][2], found[0][1]


def _qt_sharp(img):
    import cv2
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def _qt_capture(fastscout_page, url, label):
    """Runs on the Playwright worker thread. One browser; a FRESH context per quality so the player starts from its default."""
    import cv2
    pw = _fastscout_session["playwright"]
    browser = pw.chromium.launch(channel=VISION_BROWSER_CHANNEL, headless=VISION_HEADLESS,
                                 args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"])
    rows_out = []
    keep = (VISION_TRACK_WIDTH, VISION_TRACK_MAX_FRAMES)
    try:
        for quality in QT_QUALITIES:
            print(f"\n=== {quality} ===", flush=True)
            ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
            try:
                ctx.add_cookies(fastscout_page.context.cookies())
            except Exception:
                pass
            page = ctx.new_page()
            try:
                _vision_open(page, url)
            except Exception as e:
                print(f"  could not open the clip page ({type(e).__name__}: {e})", flush=True)
                ctx.close()
                continue
            rows = page.evaluate(_VIS_JS_ROWS)
            todo = [r for r in rows if not re.search(VISION_SKIP_DESCRIPTION, r["description"] or "")]
            if QT_GAME and not QT_GAME_URL:
                todo = [r for r in todo if _vision_row_in_named_game(r)]
            todo = todo[:QT_CLIPS]
            print(f"  {len(rows)} clips on the page; testing the first {len(todo)}", flush=True)
            globals()["_vision_size_shown"] = True        # this test prints the size per clip itself
            globals()["_vision_row_start"] = {}
            selected = None
            try:
                _vision_set_quality(page, quality)
                selected = bool(globals().get("_vision_quality_set"))
            except Exception as e:
                print(f"  [quality] not set ({type(e).__name__}: {e})", flush=True)
            # full stream size: no width cap while capturing (each frame is shrunk to 1024 afterwards, in Python)
            globals()["VISION_TRACK_WIDTH"] = 100000
            globals()["VISION_TRACK_MAX_FRAMES"] = int(QT_MAX_FRAMES_PER_CLIP)
            for n, r in enumerate(todo, 1):
                fp = hashlib.md5(str(r.get("description") or "").strip().encode("utf-8")).hexdigest()[:8]
                cdir = os.path.join(QT_DIR, quality, f"clip{n:02d}_{r.get('position')}_{fp}")
                rec = {"quality": quality, "selected": selected, "clip": n, "position": r.get("position"),
                       "description": r.get("description"), "folder": cdir}
                try:
                    frames, err = _vision_capture(page, r["index"], _vis_seconds(r["duration"]), mode="track")
                    size = page.evaluate(_VIS_JS_SIZE) or {}
                    rec.update(stream_w=size.get("w"), stream_h=size.get("h"), error=err)
                    kb_f, kb_s, sh_f, sh_s = [], [], [], []
                    for k, fb in enumerate(frames):
                        raw = _qt_b64.b64decode(fb)
                        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                        if img is None:
                            continue
                        for sub in ("full", "w1024"):
                            os.makedirs(os.path.join(cdir, sub), exist_ok=True)
                        pf = os.path.join(cdir, "full", f"t{k:03d}.jpg")
                        with open(pf, "wb") as fh:
                            fh.write(raw)
                        small = img
                        if img.shape[1] > 1024:
                            small = cv2.resize(img, (1024, round(img.shape[0] * 1024 / img.shape[1])), interpolation=cv2.INTER_AREA)
                        ps = os.path.join(cdir, "w1024", f"t{k:03d}.jpg")
                        cv2.imwrite(ps, small, [cv2.IMWRITE_JPEG_QUALITY, int(round(100 * float(VISION_TRACK_JPEG_QUALITY)))])
                        kb_f.append(os.path.getsize(pf) / 1024)
                        kb_s.append(os.path.getsize(ps) / 1024)
                        sh_f.append(_qt_sharp(img))
                        sh_s.append(_qt_sharp(small))
                    with open(os.path.join(cdir, "times.json"), "w") as fh:
                        json.dump(globals().get("_vision_last_times", []), fh)
                    rec.update(frames=len(kb_f), kb_full=round(float(np.mean(kb_f)), 1) if kb_f else None,
                               kb_1024=round(float(np.mean(kb_s)), 1) if kb_s else None,
                               sharp_full=round(float(np.mean(sh_f)), 1) if sh_f else None,
                               sharp_1024=round(float(np.mean(sh_s)), 1) if sh_s else None)
                    print(f"  clip {n}: stream {rec['stream_w']}x{rec['stream_h']}, {len(kb_f)} frames"
                          + (f" ({err})" if err else ""), flush=True)
                except Exception as e:
                    rec["error"] = f"{type(e).__name__}: {e}"[:300]
                    print(f"  clip {n}: failed -- {rec['error']}", flush=True)
                rows_out.append(rec)
            ctx.close()
    finally:
        globals()["VISION_TRACK_WIDTH"], globals()["VISION_TRACK_MAX_FRAMES"] = keep
        browser.close()
    return pd.DataFrame(rows_out, columns=_QT_COLS)


def _qt_summary(clips):
    if clips.empty:
        return clips
    g = clips.groupby("quality", sort=False)
    return pd.DataFrame({
        "setting picked": g["selected"].first(),
        "stream size": g.apply(lambda d: ", ".join(sorted({f"{int(w)}x{int(h)}" for w, h in zip(d["stream_w"], d["stream_h"])
                                                          if pd.notna(w) and pd.notna(h)})) or "?"),
        "clips": g["clip"].count(),
        "frames": g["frames"].sum(),
        "KB per frame (full)": g["kb_full"].mean().round(1),
        "KB per frame (1024)": g["kb_1024"].mean().round(1),
        "sharpness (full)": g["sharp_full"].mean().round(0),
        "sharpness (1024)": g["sharp_1024"].mean().round(0),
    }).reset_index()


def _qt_side_by_side(clips, out_dir):
    """For each clip: the middle frame at 1024 wide, Standard on top of High, plus a 2x zoom of the middle of the
    picture (where the players usually are) -- saved as compare_clipNN.jpg in QT_DIR."""
    import cv2
    paths = []
    qs = list(dict.fromkeys(clips["quality"]))
    if len(qs) < 2:
        return paths
    for n in sorted(clips["clip"].dropna().unique()):
        imgs = []
        for q in qs:
            row = clips[(clips["quality"] == q) & (clips["clip"] == n)]
            if row.empty:
                break
            files = sorted(glob.glob(os.path.join(row["folder"].iloc[0], "w1024", "*.jpg")))
            if not files:
                break
            im = cv2.imread(files[len(files) // 2])
            h, w = im.shape[:2]
            zoom = cv2.resize(im[int(h * 0.35):int(h * 0.65), int(w * 0.35):int(w * 0.65)], None, fx=2, fy=2,
                              interpolation=cv2.INTER_NEAREST)
            zoom = cv2.resize(zoom, (w, round(zoom.shape[0] * w / zoom.shape[1])))
            band = np.vstack([im, zoom])
            cv2.putText(band, q, (16, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 255, 255), 3)
            imgs.append(band)
        if len(imgs) == len(qs):
            wmax = max(i.shape[1] for i in imgs)
            imgs = [cv2.copyMakeBorder(i, 0, 8, 0, wmax - i.shape[1], cv2.BORDER_CONSTANT, value=(0, 0, 0)) for i in imgs]
            p = os.path.join(out_dir, f"compare_clip{int(n):02d}.jpg")
            cv2.imwrite(p, np.vstack(imgs), [cv2.IMWRITE_JPEG_QUALITY, 92])
            paths.append(p)
    return paths


# ---- Run --------------------------------------------------------------------------------------------------------
os.makedirs(QT_DIR, exist_ok=True)
_qt_url, _qt_label = _qt_find_game_url()
print(f"Quality test: {_qt_label}\n  {_qt_url}\n  first {QT_CLIPS} clips, qualities {QT_QUALITIES}, saved under {QT_DIR}")
qt_clips = run_in_fastscout_session(lambda p: _qt_capture(p, _qt_url, _qt_label))
qt_clips.to_csv(os.path.join(QT_DIR, "quality_test_clips.csv"), index=False)
qt_summary = _qt_summary(qt_clips)
qt_summary.to_csv(os.path.join(QT_DIR, "quality_test_summary.csv"), index=False)
print("\nSummary (sharpness = how much fine detail the picture holds; higher = crisper edges on numbers and lines):")
(_show if "_show" in globals() else print)(qt_summary)
qt_compare_files = _qt_side_by_side(qt_clips, QT_DIR)
print(f"\nSide-by-side pictures ({len(qt_compare_files)}): " + ("; ".join(qt_compare_files) if qt_compare_files else "none"))
