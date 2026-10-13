# 55c_play_review.py -- code for the notebook section "Play review"
# Runs inside the notebook via run_section("55c_play_review"); its settings are in that notebook cell.

# --- Play review: the player checks and the Title review together, on the next 5 unreviewed plays per game ------------------------
# CONFIRMED CHANGE (requested: "combine the player-number review and the Title review into one file and do both at the
# same time; only 20 plays per game, a random set -- a different 20 when I run it again; a 'wrong team' option; and a
# gif of the play, the clip, or a link to Synergy").
#
# One review per game and run, in the Streamlit app (package: <data>/play_review/<game>/review.json + media; no review.html
# any more). For each of the 20 plays:
#   * an animated GIF of the play -- the tracking frames at real speed, every player's box and assigned number drawn on;
#   * a link to the game on Synergy with the clip's number and where it starts in the game video;
#   * the START and END pictures with a row per box: correct / really <player on his team> / really <player on the OTHER
#     team> / wrong team (don't know who) / not a player;
#   * the Title review: the coach's Title, the automatic Title (held-out for tagged plays) and right / wrong / can't tell
#     per field, with a box for the right answer.
# The app's Save commits the answers as <data>/play_review_saves/*.json (Titles and player checks are saved separately);
# the parser reads that folder next run (player checks -> certain names, "wrong team" moves the player to the other team;
# Title answers -> scored, and labels for the Tag model on untagged plays).
import os
import re
import shutil
import glob
import sys
import json
import random
import subprocess
import tempfile
import datetime as _pr_dt     # NOT "import datetime": the notebook's datetime is the class (section 01)
import html as _pr_html
import pandas as pd
import numpy as np
from PIL import Image


# ---- helpers moved here from the retired "Validation pictures" and "Auto-Title review" sections ------------------
# CONFIRMED CHANGE (requested: clean up -- the Play review replaced both pages). The Play review used these from
# those two sections; they live here now, unchanged, so both sections (cells and files) could be removed.

def _val_frame_pick(tr_rows, lo, hi, prefer_late=False):
    """The frame in [lo, hi] where the most players are visible (ties -> the earliest, or the latest)."""
    count = {}
    for r in tr_rows:
        if r.get("side") not in ("offense", "defense"):
            continue
        for p in _trk_json.loads(r["path"]):
            t = int(p[0])
            if lo <= t <= hi:
                count[t] = count.get(t, 0) + 1
    if not count:
        return None
    return max(count, key=lambda t: (count[t], t if prefer_late else -t))


def _val_font(size):
    from PIL import ImageFont
    for f in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _val_draw(img_path, boxes, header_lines, out_path, scale=1.6, grid=None):
    """Picture enlarged (scale), bigger font, labels that would overlap stacked upward with a line to their box.
    grid = (columns, rows): faint lines with letters across the top and numbers down the left, so a coach can name the
    square at the feet of a player who has NO box (the app's "Players with no box")."""
    from PIL import Image, ImageDraw
    im = Image.open(img_path).convert("RGB")
    W, H = im.size
    im = im.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
    fh, fl = _val_font(18), _val_font(17)
    head_h = 24 * len(header_lines) + 10
    canvas = Image.new("RGB", (im.size[0], im.size[1] + head_h), (20, 20, 20))
    canvas.paste(im, (0, head_h))
    d = ImageDraw.Draw(canvas)
    for n_, line in enumerate(header_lines):
        d.text((8, 5 + 24 * n_), line, fill=(255, 255, 255), font=fh)
    if grid:
        _gc, _gr = int(grid[0]), int(grid[1])
        _cw, _rh = im.size[0] / _gc, im.size[1] / _gr
        _gcol = (255, 255, 120)
        for c_ in range(1, _gc):
            for yy in range(head_h, canvas.size[1], 14):                # dotted, so it doesn't hide anyone
                d.line([(c_ * _cw, yy), (c_ * _cw, min(yy + 5, canvas.size[1]))], fill=_gcol, width=1)
        for r_ in range(1, _gr):
            for xx in range(0, canvas.size[0], 14):
                d.line([(xx, head_h + r_ * _rh), (min(xx + 5, canvas.size[0]), head_h + r_ * _rh)], fill=_gcol, width=1)
        _fg = _val_font(15)
        for c_ in range(_gc):
            for r_ in range(_gr):
                tag_ = f"{chr(65 + c_)}{r_ + 1}"
                d.rectangle([c_ * _cw + 2, head_h + r_ * _rh + 2, c_ * _cw + 30, head_h + r_ * _rh + 20], fill=(0, 0, 0))
                d.text((c_ * _cw + 4, head_h + r_ * _rh + 3), tag_, fill=_gcol, font=_fg)
    placed = []                                            # label rectangles already drawn
    for b in sorted(boxes, key=lambda b: b["box"][1]):     # top-most players first
        x1, y1, x2, y2 = [c * scale for c in b["box"]]
        y1 += head_h
        y2 += head_h
        col = {"offense": (255, 150, 0), "defense": (60, 170, 255)}.get(b["side"], (150, 150, 150))
        if b["guess"]:
            for yy in range(int(y1), int(y2), 10):
                d.line([(x1, yy), (x1, min(yy + 5, y2))], fill=col, width=3)
                d.line([(x2, yy), (x2, min(yy + 5, y2))], fill=col, width=3)
            for xx in range(int(x1), int(x2), 10):
                d.line([(xx, y1), (min(xx + 5, x2), y1)], fill=col, width=3)
                d.line([(xx, y2), (min(xx + 5, x2), y2)], fill=col, width=3)
        else:
            d.rectangle([x1, y1, x2, y2], outline=col, width=1 if not b["label"] else 4)
        tag = f"{b['id']}  {b['label']}" if b["label"] else b["id"]
        tw = int(d.textlength(tag, font=fl)) + 10
        th = 22
        lx, ly = x1, y1 - th - 2
        # move up until it no longer overlaps an earlier label
        for _ in range(12):
            if not any(lx < px2 and lx + tw > px1 and ly < py2 and ly + th > py1 for px1, py1, px2, py2 in placed):
                break
            ly -= th + 2
        ly = max(head_h, ly)
        placed.append((lx, ly, lx + tw, ly + th))
        if ly + th < y1 - 2:
            d.line([(lx + 6, ly + th), (x1 + 6, y1)], fill=col, width=2)
        d.rectangle([lx, ly, lx + tw, ly + th], fill=col if b["label"] else (90, 90, 90))
        d.text((lx + 5, ly + 2), tag, fill=(0, 0, 0) if b["label"] else (235, 235, 235), font=fl)
    canvas.save(out_path, quality=90)


_TR_FIELDS = [("situation", "Situation"), ("formation", "Formation"), ("play_call", "Play call"),
              ("primary_action", "Main action"), ("defense", "Defense"), ("press", "Press"),
              ("ball_screen_coverage", "Ball-screen coverage"), ("offball_coverage", "Off-ball coverage"),
              ("screener", "Screener"), ("screen_defender", "Screen defender")]


def _tr_val(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    s = str(v).strip()
    return None if s in ("", "None", "nan") else s


def _tr_same(a, b):
    norm = lambda x: re.sub(r"[^a-z0-9#]+", "", str(x).lower())
    return norm(a) == norm(b)


def _tr_auto(r, f, tagged):
    """The automatic answer for one field: (value, confidence, note)."""
    if tagged:
        v, c = _tr_val(r.get(f"heldout_{f}")), r.get(f"heldout_{f}_conf")
        if v is None and _tr_val(r.get(f"pred_{f}")) is not None:
            return None, None, "held-out answer not available until the Tag model retrains"
        return v, (float(c) if pd.notna(c) else None), ""
    v, c = _tr_val(r.get(f"pred_{f}")), r.get(f"pred_{f}_conf")
    return v, (float(c) if pd.notna(c) else None), ""


def _tr_title(r, tagged):
    """The automatic Title in the coaches' shorthand -- the Tag model's own builder, fed the (held-out) answers."""
    rr = dict(r)
    for f, _lab in _TR_FIELDS:
        v, c, _n = _tr_auto(r, f, tagged)
        rr[f"pred_{f}"], rr[f"pred_{f}_conf"] = v, (c if c is not None else np.nan)
    try:
        return _tm_suggest(rr) if "_tm_suggest" in globals() else None
    except Exception:
        return None


def _tr_film(key):
    """What tracking saw on the film for this clip: a sentence, or None."""
    scr = (globals().get("_ti_tables") or {}).get("uww_trk_screens")
    if not isinstance(scr, pd.DataFrame) or scr.empty or "clip_key" not in scr.columns:
        return None
    rows = scr[scr["clip_key"] == key]
    if rows.empty:
        return None
    s = rows.iloc[0]
    who = lambda x: x if isinstance(x, str) and x else "an unnamed player"
    txt = f"{s.get('screen_type') or 'Screen'}: {who(s.get('screener'))} screened for {who(s.get('screened'))}"
    d1, d2 = s.get("screened_defender"), s.get("screener_defender")
    if isinstance(d1, str) or isinstance(d2, str):
        txt += f"; defended by {who(d1)} (on the player screened) and {who(d2)} (on the screener)"
    est = s.get("coverage_tracking_estimate")
    if isinstance(est, str) and est:
        txt += f"; coverage from the players' movement: {est}"
    conf = s.get("confidence")
    if pd.notna(conf):
        txt += f" (screen confidence {float(conf):.0%})"
    return txt


def _pr_ck(k):
    return _pl_ckey_norm(k) if "_pl_ckey_norm" in globals() else str(k)


def _pr_reviewed_keys(part=None):
    """Clip keys already reviewed: part "players" = a player check saved, "titles" = a Title answer saved, None = either."""
    keys = set()
    if part in (None, "players"):
        try:
            for ch in coach_checks_all()[0]:
                keys.add(_pr_ck(ch.get("clip_key")))
        except Exception:
            pass
    if part in (None, "titles"):
        try:
            title_review_answers()
            keys |= {_pr_ck(ck) for (ck, _f) in (globals().get("_title_review_marks") or {})}
        except Exception:
            pass
    return keys


def _pr_box_crop(src, box, target_h=None):
    """Close-up of one player's head and chest (top ~65% of his box, padded) from the original frame, enlarged to
    PLAY_REVIEW_CROP_HEIGHT px tall -> a JPEG data URI (or None)."""
    import io
    import base64
    target_h = int(target_h or globals().get("PLAY_REVIEW_CROP_HEIGHT", 220))
    x1, y1, x2, y2 = [float(v) for v in box]
    w, h = x2 - x1, y2 - y1
    if w <= 2 or h <= 2:
        return None
    cx1, cx2 = x1 - 0.12 * w, x2 + 0.12 * w          # tighter sides: every pixel of the crop is the player (was 0.30)
    cy1, cy2 = y1 - 0.04 * h, y1 + 0.62 * h
    W, H = src.size
    cx1, cy1, cx2, cy2 = max(0, int(cx1)), max(0, int(cy1)), min(W, int(cx2) + 1), min(H, int(cy2) + 1)
    if cx2 - cx1 < 4 or cy2 - cy1 < 4:
        return None
    im = src.crop((cx1, cy1, cx2, cy2))
    sc = target_h / im.size[1]
    im = im.resize((max(1, int(im.size[0] * sc)), target_h), Image.BICUBIC if sc > 4 else Image.LANCZOS)
    try:                                                # a light sharpen so the edges of numbers read better when enlarged
        from PIL import ImageFilter
        im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=int(globals().get("PLAY_REVIEW_CROP_SHARPEN", 120)), threshold=2))
    except Exception:
        pass
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _pr_best_instance(rows, track, t0, files, fps, cache):
    """CONFIRMED CHANGE (requested: the close-ups are blurry when blown up). The pictures come from a 1024-px-wide video, so a
    player is only ~40 px wide in any one frame -- the pixels can't be recovered. What CAN be done: a player is the same track
    in every frame of the clip, so cut his close-up from the frame where he is SHARPEST, biggest (closest to the camera) and
    least hidden behind another player, not from the one frame chosen for the big picture. -> (box, t) or None."""
    try:
        import cv2
        import numpy as np
        from PIL import Image
        rr = next((r for r in rows if int(r["track"]) == int(track)), None)
        if rr is None:
            return None
        path = [q for q in _trk_json.loads(rr["path"]) if len(q) >= 6]
        if len(path) < 2:
            return None
        others = {}
        for r2 in rows:
            if int(r2["track"]) == int(track) or r2.get("side") not in ("offense", "defense"):
                continue
            for q in _trk_json.loads(r2["path"]):
                if len(q) >= 6:
                    others.setdefault(int(q[0]), []).append(q)
        hmax = max(float(q[3]) for q in path)
        # only frames within PLAY_REVIEW_CROP_WINDOW_S seconds of the big picture's frame: a track can jump from one player to
        # another (a lost-and-refound player), and a close-up cut from far away in the clip could then show a DIFFERENT man than
        # the box being checked. 0 = anywhere in the clip.
        _win = float(globals().get("PLAY_REVIEW_CROP_WINDOW_S", 3.0))
        cand = [q for q in path if float(q[3]) >= 0.6 * hmax and int(q[0]) < len(files)
                and (_win <= 0 or abs(int(q[0]) - int(t0)) <= _win * fps)]
        if len(cand) > 24:
            cand = cand[::max(1, len(cand) // 24)]
        best = None
        for q in cand:
            t = int(q[0])
            fp = os.path.join(VISION_FRAMES_DIR, files[t])
            if fp not in cache:
                cache[fp] = np.asarray(Image.open(fp).convert("RGB")) if os.path.exists(fp) else None
            fr = cache[fp]
            if fr is None:
                continue
            Hpx, Wpx = fr.shape[:2]
            hh = float(q[3]) * Hpx
            x, y = float(q[4]), float(q[5])
            bx = [x - 0.21 * hh, y - hh, x + 0.21 * hh, y]
            if bx[0] < 2 or bx[1] < 2 or bx[2] > Wpx - 2 or bx[3] > Hpx - 2:
                continue                                    # cut off by the edge of the picture
            ov = 0.0                                        # share of his box covered by another player's box
            for o in others.get(t, []):
                oh = float(o[3]) * Hpx
                ox, oy = float(o[4]), float(o[5])
                ix = max(0.0, min(bx[2], ox + 0.21 * oh) - max(bx[0], ox - 0.21 * oh))
                iy = max(0.0, min(bx[3], oy) - max(bx[1], oy - oh))
                ov = max(ov, ix * iy / max(1.0, (bx[2] - bx[0]) * (bx[3] - bx[1])))
            gy = cv2.cvtColor(fr[int(bx[1]):int(bx[1] + 0.62 * hh) + 1, int(bx[0]):int(bx[2]) + 1], cv2.COLOR_RGB2GRAY)
            if gy.shape[0] < 6 or gy.shape[1] < 4:
                continue
            gy = cv2.resize(gy, (48, 96), interpolation=cv2.INTER_AREA)       # same size for every candidate: fair sharpness
            score = float(cv2.Laplacian(gy, cv2.CV_64F).var()) * (hh / max(hmax, 1.0)) ** 0.5 * max(0.05, 1.0 - 2.5 * ov)
            if best is None or score > best[0]:
                best = (score, bx, t)
        return (best[1], best[2]) if best else None
    except Exception:
        return None


def _pr_boxes(rows, t, Hpx, numtxt):
    boxes = []
    for rr in sorted(rows, key=lambda x: (str(x.get("side")), str(x.get("name")))):
        p = next((p for p in _trk_json.loads(rr["path"]) if int(p[0]) == t and len(p) >= 6), None)
        if p is None or rr.get("side") not in ("offense", "defense"):
            continue
        hh = float(p[3]) * Hpx
        x, y = float(p[4]), float(p[5])
        named = isinstance(rr.get("name"), str)
        boxes.append({"id": chr(65 + len(boxes)) if len(boxes) < 26 else str(len(boxes)),
                      "track": int(rr["track"]), "side": rr["side"],
                      "box": [x - 0.21 * hh, y - hh, x + 0.21 * hh, y], "px": round(x, 1), "py": round(y, 1),
                      "name": rr.get("name") if named else None, "how": rr.get("name_how") if named else None,
                      "label": (numtxt(rr["name"]) + ((f"? {round(100 * float(rr['name_conf']))}%" if pd.notna(pd.to_numeric(rr.get("name_conf"), errors="coerce")) else "?")
                                                if rr.get("name_how") == "best guess" else "")) if named else "",
                      "conf": (float(rr["name_conf"]) if named and pd.notna(pd.to_numeric(rr.get("name_conf"), errors="coerce")) else None),
                      "guess": named and rr.get("name_how") == "best guess",
                      # the best guess NOT shown (under the cutoff) -- never displayed, saved with the check so it keeps being measured
                      "hidden_guess": (rr.get("guess_name") if not named and isinstance(rr.get("guess_name"), str) else None),
                      "hidden_guess_p": (float(rr["guess_p"]) if not named and pd.notna(pd.to_numeric(rr.get("guess_p"), errors="coerce")) else None)})
    return boxes


def _pr_frames(files, rows, numtxt, every=1):
    """The play's tracking frames, as filmed (PIL images) -- CONFIRMED CHANGE (requested): no boxes or labels on the
    video; the player checks happen on the still pictures below it."""
    from PIL import Image
    out = []
    for t in range(0, len(files), every)[:400]:
        p_ = os.path.join(VISION_FRAMES_DIR, files[t])
        if not os.path.exists(p_):
            continue
        im = Image.open(p_).convert("RGB")
        W, H = im.size
        sc = PLAY_REVIEW_VIDEO_WIDTH / float(W)
        out.append(im.resize((PLAY_REVIEW_VIDEO_WIDTH // 2 * 2, int(H * sc) // 2 * 2)))      # even sizes (video needs them)
    return out


def _pr_mp4_ok():
    """imageio + imageio-ffmpeg (a bundled ffmpeg) for small, browser-playable MP4s -- installed once if missing."""
    import importlib
    if importlib.util.find_spec("imageio_ffmpeg") is None or importlib.util.find_spec("imageio") is None:
        try:
            print("  [play review] installing imageio-ffmpeg (small videos of each play, one time)...", flush=True)
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "imageio", "imageio-ffmpeg"])
            importlib.invalidate_caches()
        except Exception as e:
            print(f"  [play review] couldn't install imageio-ffmpeg ({type(e).__name__}: {e}) -- using GIFs", flush=True)
            return False
    return importlib.util.find_spec("imageio_ffmpeg") is not None


def _pr_clip(files, rows, numtxt, out_base):
    """The play as a video (MP4, real speed, with play/pause) or an animated GIF -> file name, or None.
    CONFIRMED CHANGE: GIFs of a play were 3-7 MB each (~100 MB for 20 plays); an MP4 of the same frames is a small
    fraction of that and plays with a scrubber. GIF stays as the fallback (PLAY_REVIEW_VIDEO = "gif")."""
    fps = float(globals().get("VISION_TRACK_FPS") or 2.0)
    kind = PLAY_REVIEW_VIDEO
    # CONFIRMED CHANGE (lean mode): a game in lean mode keeps each clip's play video ready-made (<game>/media/<clip>.mp4)
    # instead of all its frames -- use it as is
    _pre = vision_clip_media(files) if "vision_clip_media" in globals() else None
    if _pre and kind == "mp4":
        shutil.copy2(_pre, out_base + ".mp4")
        _pp = _pre[:-4] + "_poster.jpg"
        if os.path.exists(_pp):
            shutil.copy2(_pp, out_base + "_poster.jpg")
        return os.path.basename(out_base + ".mp4")
    if kind == "mp4" and not globals().setdefault("_pr_mp4_ready", _pr_mp4_ok()):
        kind = "gif"
    if kind == "mp4":
        frames = _pr_frames(files, rows, numtxt, every=1)
        if not frames:
            return None
        import imageio.v2 as imageio
        path = out_base + ".mp4"
        # crf 30: well under 1 MB for a 45-second play -- for watching the play and the labels move (numbers are read
        # in the enlarged pictures below it)
        w = imageio.get_writer(path, fps=fps, codec="libx264", quality=None, macro_block_size=2, pixelformat="yuv420p",
                               ffmpeg_params=["-crf", "30", "-preset", "medium", "-movflags", "+faststart"])
        for im in frames:
            w.append_data(np.asarray(im))
        w.close()
        # the video's cover image (its first frame, clean) -- otherwise it shows as a black box until played
        frames[0].save(out_base + "_poster.jpg", "JPEG", quality=70)
        return os.path.basename(path)
    if kind == "gif":
        every = max(1, int(round(fps / 2.0)))                   # 2 frames a second, shown at real speed
        frames = _pr_frames(files, rows, numtxt, every=every)
        if not frames:
            return None
        from PIL import Image
        path = out_base + ".gif"
        pal = [im.convert("P", palette=Image.ADAPTIVE, colors=64) for im in frames]
        pal[0].save(path, save_all=True, append_images=pal[1:], duration=int(1000 * every / fps), loop=0, optimize=True)
        return os.path.basename(path)
    return None


def _pr_embed(rdir, name, kind):
    """A file in the run folder as a data: URI (inside the page). Pictures are re-saved 1300 px wide at JPEG quality
    75 -- about 60% of the size; jersey numbers and labels stay clearly readable."""
    import base64
    import io
    path = os.path.join(rdir, name)
    if kind == "image":
        from PIL import Image
        buf = io.BytesIO()
        im = Image.open(path).convert("RGB")
        if im.size[0] > 1300:                         # 1300 px wide: numbers and labels still clearly readable
            im = im.resize((1300, int(im.size[1] * 1300 / im.size[0])), Image.LANCZOS)
        im.save(buf, "JPEG", quality=75, optimize=True)
        data, mime = buf.getvalue(), "image/jpeg"
    else:
        with open(path, "rb") as fh:
            data = fh.read()
        mime = "video/mp4" if name.endswith(".mp4") else "image/gif"
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def _pr_app_dir():
    """The app's data folder. CONFIRMED BUG (fixed): APP_DATA_DIR is first set in a LATER section (cell ~174), so in a
    fresh session the Play review (cell ~126) failed to copy reviews to the app. OUTPUT_DIR is the same folder (../data)."""
    return globals().get("APP_DATA_DIR") or OUTPUT_DIR


def _export_play_review_to_app(rdir, slug, game, run, plays, vocab, kind="play_review"):
    """Copy this run's review into the app's data folder: _pr_app_dir()/<kind>/<slug>/ (replacing the last one).
    kind "play_review" = the Play review (Titles + player checks); "play_tag" = the Film Tagging queue (Titles only)."""
    from PIL import Image
    dest = os.path.join(_pr_app_dir(), kind, slug)
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    import base64
    import io

    def _media(value, name):
        """A separate file in the run folder, or one built into review.html (a data: URI) -> written to dest as name."""
        if not value:
            return None
        if str(value).startswith("data:"):
            head, b64 = str(value).split(",", 1)
            with open(os.path.join(dest, name), "wb") as fh:
                fh.write(base64.b64decode(b64))
            return name
        if os.path.exists(os.path.join(rdir, value)):
            shutil.copy2(os.path.join(rdir, value), os.path.join(dest, os.path.basename(value)))
            return os.path.basename(value)
        return None

    out = []
    for p in plays:
        q = json.loads(json.dumps(p, default=str))
        cn = int(q.get("clip_number") or 0)
        clip = q.get("clip") or q.get("gif")                  # older pages called it "gif"
        is_mp4 = str(clip or "").startswith("data:video") or str(clip or "").endswith(".mp4")
        fid = q.get("fid") or f"{cn:03d}"                      # file id: unique per play even when every clip number is 0
        q["clip"] = _media(clip, f"clip_{fid}.{'mp4' if is_mp4 else 'gif'}")
        q["clip_kind"] = "video" if is_mp4 else "image"
        q["poster"] = _media(q.get("poster"), f"clip_{fid}_poster.jpg")
        for pic in q.get("pictures", []):
            name = f"clip_{fid}_{'a_start' if pic.get('which') == 'start' else 'c_frame' if pic.get('which') == 'frame' else 'b_end'}.jpg"
            v = pic.get("image")
            try:
                if str(v or "").startswith("data:"):
                    im = Image.open(io.BytesIO(base64.b64decode(str(v).split(",", 1)[1]))).convert("RGB")
                elif v and os.path.exists(os.path.join(rdir, v)):
                    im = Image.open(os.path.join(rdir, v)).convert("RGB")
                else:
                    im = None
            except Exception:
                im = None
            if im is not None:
                # CONFIRMED CHANGE (requested: much clearer pictures for the player-number checks). The pictures were drawn
                # 1.6x (1638 px wide, quality 90) and then SHRUNK to 1100 px and re-saved at quality 72 for the app -- a second
                # round of compression that smeared the numbers. Now kept at their drawn size by default (width / quality in
                # the notebook cell: PLAY_REVIEW_PICTURE_WIDTH / PLAY_REVIEW_PICTURE_QUALITY).
                _maxw = int(globals().get("PLAY_REVIEW_PICTURE_WIDTH", 1640))
                if im.size[0] > _maxw:
                    im = im.resize((_maxw, int(im.size[1] * _maxw / im.size[0])), Image.LANCZOS)
                im.save(os.path.join(dest, name), "JPEG", quality=int(globals().get("PLAY_REVIEW_PICTURE_QUALITY", 92)),
                        optimize=True, subsampling=0)
                pic["image"] = name
            else:
                pic["image"] = None
        out.append(q)
    with open(os.path.join(dest, "review.json"), "w", encoding="utf-8") as fh:
        json.dump({"game": game, "slug": slug, "run": run, "plays": out, "vocab": vocab,
                   "built": _pr_dt.datetime.now().isoformat(timespec="seconds")}, fh, indent=1)
    size = sum(os.path.getsize(os.path.join(dest, f)) for f in os.listdir(dest)) / 1e6
    print(f"  [play review] copied to the app: {dest} ({size:.0f} MB) -- commit and push it with the data", flush=True)


def _pr_synergy(r):
    """(Synergy page link, clip position on that page) from the capture log."""
    cf = globals().get("clip_frames")
    if not isinstance(cf, pd.DataFrame) or cf.empty or "source_url" not in cf.columns:
        return None, None
    ff = str(r.get("frame_files") or "")
    hit = cf[cf.get("frame_files", pd.Series("", index=cf.index)).astype(str) == ff] if ff else cf.iloc[0:0]
    if hit.empty and "description" in cf.columns:
        hit = cf[cf["description"].astype(str).str.strip() == str(r.get("synergy_string") or "").strip()]
    if hit.empty:
        return None, None
    h = hit.iloc[0]
    return h.get("source_url"), h.get("position")


def play_review():
    pt = player_tracks if isinstance(globals().get("player_tracks"), pd.DataFrame) else pd.DataFrame()
    if pt.empty or "clip_key" not in pt.columns:
        print("Play review: no player tracks yet -- run Player tracking first.")
        return
    # CONFIRMED CHANGE (coach: "why only the Oshkosh game when there are frames for three games?"). The Play review needs
    # PLAYER TRACKING (tracking frames, boxes, assigned numbers); say which games were left out and why.
    _all = play_calls.copy()
    if PLAY_REVIEW_ONLY_GAME:
        _all = _all[_all["game_code"].astype(str).str.contains(PLAY_REVIEW_ONLY_GAME, regex=False)]
    ver = int(globals().get("VISION_CAPTURE_VERSION", 1))
    tracked_keys = set(pt["clip_key"])
    for (gd, gc), g in _all.groupby(["game_date", "game_code"], dropna=False):
        has_track = g["track_files"].notna().any() if "track_files" in g.columns else False
        if has_track and g["track_clip_key"].isin(tracked_keys).any():
            continue
        ff = g["frame_files"].dropna().astype(str) if "frame_files" in g.columns else pd.Series(dtype=str)
        if not has_track and ff.empty:
            why = "no frames captured for it"
        elif not has_track and ver >= 2 and not ff.str.contains(f"_v{ver}_", regex=False).any():
            why = ("only key frames from BEFORE the clip-start fix (they may show a different play) -- run Frame capture "
                   "for this game (VISION_ONLY_GAME) to recapture it with tracking frames")
        elif not has_track:
            why = "key frames but no tracking frames -- run Frame capture for this game with VISION_TRACK_FPS on"
        else:
            why = "tracking frames but no player tracks yet -- run Player tracking"
        print(f"Play review: {gd} {gc} left out -- {why}", flush=True)
    pc = play_calls[play_calls["track_files"].notna()].copy()
    if PLAY_REVIEW_ONLY_GAME:
        pc = pc[pc["game_code"].astype(str).str.contains(PLAY_REVIEW_ONLY_GAME, regex=False)]
    pc = pc[pc["track_clip_key"].isin(tracked_keys)]
    # CONFIRMED BUG (fixed; the Coe and Oshkosh reviews came out "0 MB" -- plays with no video and no pictures): their frame
    # folders were deleted to free space, so nothing can be drawn. A game whose tracking frames aren't on disk (or packed by
    # the frame archive / kept as lean-mode videos) is left out of the Play review until it's captured again.
    def _pr_frames_here(ff):
        f0 = next((f for f in str(ff).split(";") if f), None)
        if not f0:
            return False
        p0 = os.path.join(VISION_FRAMES_DIR, f0)
        return os.path.exists(p0) or bool(globals().get("vision_frame_leaned") and vision_frame_leaned(p0)) \
            or bool(globals().get("vision_clip_media") and vision_clip_media([f0]))
    _here = pc["track_files"].map(_pr_frames_here)
    for (gd, gc), g_ in pc[~_here].groupby(["game_date", "game_code"], dropna=False):
        if not _here[g_.index].any():
            print(f"Play review: {gd} {gc} left out -- its frames aren't on disk any more (folder deleted); recapture it "
                  f"(Frame capture, VISION_ONLY_GAME) to review it again", flush=True)
    pc = pc[_here]
    # CONFIRMED CHANGE (requested: the player checks move on once saved, while the Title checks stay on the same plays until
    # THEY are saved). PLAY_REVIEW_QUEUES = "separate": each part is its own queue -- the next PLAY_REVIEW_PLAYS_PER_GAME plays
    # in game order with no saved player check, and the next ones with no saved Title answer. One package holds both; each
    # play says which part(s) it's open for, and the app shows it only there. "together" = the old way (the same plays for
    # both, and a new batch only once BOTH parts are saved).
    _sep = str(globals().get("PLAY_REVIEW_QUEUES", "separate")).lower() != "together"
    _skip = PLAY_REVIEW_SKIP_REVIEWED
    done = _pr_reviewed_keys() if _skip else set()
    done_p = _pr_reviewed_keys("players") if _skip else set()
    done_t = _pr_reviewed_keys("titles") if _skip else set()
    # how the automatic Title did on everything reviewed so far
    marks = globals().get("_title_review_marks") or {}
    rep = {}
    for (_ck, f), a in marks.items():
        if a.get("verdict") in ("right", "wrong") and not a.get("prefilled"):
            rep.setdefault(f, [0, 0])
            rep[f][1] += 1
            rep[f][0] += int(a["verdict"] == "right")
    if rep:
        lab = dict(_TR_FIELDS) if "_TR_FIELDS" in globals() else {}
        print("Play review -- how often each field of the automatic Title was RIGHT on the plays reviewed so far: "
              + "; ".join(f"{lab.get(f, f)} {r_}/{n} ({100 * r_ / n:.0f}%)" for f, (r_, n) in rep.items()), flush=True)
    rng = random.Random(PLAY_REVIEW_SEED)
    stamp = _pr_dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    fps = float(globals().get("VISION_TRACK_FPS") or 2.0)
    min_c = float(globals().get("TAG_MODEL_MIN_CONFIDENCE", 0.6))
    if "_play_review_file_saves" in globals():
        _play_review_file_saves()                     # the saved reviews live in <data>/play_review_saves (one-time copy from the old folders)
    for (gd, gc), g in pc.groupby(["game_date", "game_code"], dropna=False):
        _slug_app = re.sub(r"[^A-Za-z0-9]+", "_", f"{gd}|{gc}").strip("_")
        _pkg = os.path.join(_pr_app_dir(), "play_review", _slug_app)
        # CONFIRMED CHANGE (requested: everything in the data folder; the Title and player-number checks are done in the
        # Streamlit app, not review.html pages). A game's open review is its package in <data>/play_review/<game>/. With
        # PLAY_REVIEW_QUEUES = "separate" it's rebuilt once EITHER part is saved (the saved part moves on to its next plays,
        # the other keeps its plays); "together" = only once BOTH are saved. Nothing saved = no new run
        # (PLAY_REVIEW_REQUIRE_SAVED = False skips that).
        if os.path.exists(os.path.join(_pkg, "review.json")):
            try:
                with open(os.path.join(_pkg, "review.json"), encoding="utf-8") as fh:
                    _pkg_doc = json.load(fh)
                _pkg_run = _pkg_doc.get("run")
                _open = set()
                for _pl_ in _pkg_doc.get("plays", []):
                    _open |= set(_pl_.get("parts") or ["titles", "players"])
                _saved = _run_parts_saved(_slug_app, _pkg_run)
                _done_now = (bool(_saved & _open) if _sep else {"titles", "players"} <= _saved)
                if _done_now:
                    shutil.rmtree(_pkg, ignore_errors=True)
                    _what = " and ".join({"titles": "Title checks", "players": "player checks"}[x] for x in sorted(_saved & _open))
                    print(f"Play review: {gd} {gc} -- {_what} of review run {_pkg_run} saved; a new batch is built"
                          + ("" if _open <= _saved else " (the part not saved yet keeps its plays)"), flush=True)
                elif globals().get("PLAY_REVIEW_REQUIRE_SAVED", True):
                    print(f"Play review: {gd} {gc} -- no new run: nothing in its open review (run {_pkg_run}) is saved yet "
                          f"(Title checks: Analytics > Film Tagging; player checks: Analytics > Player Number Tracking).", flush=True)
                    continue
            except Exception:
                pass
        g = g.assign(_key=[f"{r.get('game_date')}|{r.get('clip_number')}|{r.get('synergy_string')}" for _, r in g.iterrows()])
        _kn = g["_key"].map(_pr_ck)
        fresh = g[~_kn.isin(done)]
        # CONFIRMED CHANGE (requested: "the first 5 clips, then groups of 5 after that that haven't had a check run on them"):
        # PLAY_REVIEW_PICK = "next" takes the first PLAY_REVIEW_PLAYS_PER_GAME plays, in game order, that have no saved check yet;
        # "random" is the old behaviour (a random set).
        _mode = str(globals().get("PLAY_REVIEW_PICK", "next")).lower()
        if _mode == "random":
            pool = fresh if len(fresh) else g
            pick = pool.loc[rng.sample(list(pool.index), min(PLAY_REVIEW_PLAYS_PER_GAME, len(pool)))].sort_values("clip_number")
        elif _sep:
            _n = PLAY_REVIEW_PLAYS_PER_GAME
            _pp = g[~_kn.isin(done_p)].sort_values("clip_number", kind="stable").head(_n)
            # Title checks: only clips a coach already tagged (a Synergy Title) -- untagged clips are tagged in their own
            # Film Tagging batch (requested: tagging only on Analytics > Film Tagging, no duplicate plays)
            _tagged = g["decode_quality"].astype(str).ne("Untagged") if "decode_quality" in g.columns \
                else pd.Series(True, index=g.index)
            _pt = g[~_kn.isin(done_t) & _tagged].sort_values("clip_number", kind="stable").head(_n)
            if not len(_pp) and not len(_pt):
                print(f"Play review: {gd} {gc} -- every play already has its checks; nothing new to review", flush=True)
                continue
            pick = g.loc[sorted(set(_pp.index) | set(_pt.index), key=lambda i: list(g.index).index(i))]
            pick = pick.sort_values("clip_number", kind="stable")
        else:
            if not len(fresh):
                print(f"Play review: {gd} {gc} -- every play already has a check; nothing new to review", flush=True)
                continue
            pick = fresh.sort_values("clip_number", kind="stable").head(PLAY_REVIEW_PLAYS_PER_GAME)
        _parts_of = {}
        for _i in pick.index:
            if _sep and _mode != "random":
                _parts_of[_i] = [x for x, sub in (("titles", _pt), ("players", _pp)) if _i in sub.index]
            else:
                _parts_of[_i] = ["titles", "players"]
        slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{gd}|{gc}").strip("_")
        # scratch folder for this game's pictures / clips while they're built; the finished review goes to <data>/play_review
        rdir = tempfile.mkdtemp(prefix=f"play_review_{slug}_")
        # CONFIRMED CHANGE (requested: every clip has 10 players, but many pictures show fewer boxes -- coaches can now mark
        # players with NO box). The player-check picture gets a faint grid (PLAY_REVIEW_GRID = (columns, rows); None = off).
        _grid = globals().get("PLAY_REVIEW_GRID", (12, 8))
        gnums = _trk_numbers_for_game(gd, gc)
        numtxt = lambda n: f"#{gnums.get(str(n).lower(), '?')} {str(n).split()[-1]}"
        plays = []
        for _ri, r in pick.iterrows():
            _parts = _parts_of.get(_ri, ["titles", "players"])
            files = [f for f in str(r["track_files"]).split(";") if f]
            rows = pt[pt["clip_key"] == r["track_clip_key"]].to_dict("records")
            n = len(files)
            cn = int(r["clip_number"])
            # CONFIRMED BUG (fixed; the review showed the SAME picture for different plays): picture / clip files were named from
            # the clip number, and a game exported with every clip number = 0 (WWW@AC) wrote all 20 plays to clip_000_*.jpg, so
            # the last play's picture overwrote the others. Files now carry the play's position in the review as well.
            fid = f"{cn:03d}_{len(plays):02d}"
            # pictures: the start and the end of the play, most players visible
            t_end = pd.to_numeric(r.get("track_finish_frame"), errors="coerce")
            end_hi = int(min(n - 1, t_end)) if pd.notna(t_end) else n - 1
            # CONFIRMED CHANGE (requested: "1 frame for player number tracking per play"): ONE picture per play -- the frame of the
            # whole clip where the most players are visible (PLAY_REVIEW_PICTURES = 2 brings back the start + end pair).
            if int(globals().get("PLAY_REVIEW_PICTURES", 1)) >= 2:
                picks_ = [("start", _val_frame_pick(rows, 0, max(1, int(0.25 * n)))),
                          ("end", _val_frame_pick(rows, int(max(0, end_hi - 2 * fps)), end_hi, prefer_late=True))]
            else:
                picks_ = [("frame", _val_frame_pick(rows, 0, max(0, n - 1)))]
            clock = r.get("time_remaining_seconds")
            clock_txt = f"{r.get('period', '')} {int(clock // 60)}:{int(clock % 60):02d}" if pd.notna(clock) else "(no clock)"
            lu = lambda side: ", ".join(numtxt(nm) for nm in _trk_five(r.get(f"{side}_lineup"))) or "(lineup unknown)"
            pics = []
            if "players" not in _parts:
                picks_ = []                    # a Title-check-only play: no player pictures / close-ups to build
            for which, t in picks_:
                if t is None or t >= n or any(p_["t"] == t for p_ in pics):
                    continue
                img_path = os.path.join(VISION_FRAMES_DIR, files[t])
                if not os.path.exists(img_path):
                    continue
                from PIL import Image
                boxes = _pr_boxes(rows, t, Image.open(img_path).size[1], numtxt)
                header = [f"Clip {cn}  {clock_txt}  {str(r.get('synergy_string'))[:100]}",
                          (f"{'START' if which == 'start' else 'END'} of the play -- {t / fps:.1f} s into the clip" if which != "frame"
                           else f"Frame for the player check -- {t / fps:.1f} s into the clip, most players visible"),
                          f"OFFENSE (orange) {r.get('offense_team')}: {lu('offense')}",
                          f"DEFENSE (blue)  {r.get('defense_team')}: {lu('defense')}",
                          "Solid box = identified from evidence; DASHED box with ? = best guess; grey = not named"
                          + ("   |   A player with NO box? Pick the grid square at his feet in the app" if _grid else "")]
                fname = f"clip_{fid}_{'a_start' if which == 'start' else 'c_frame' if which == 'frame' else 'b_end'}.jpg"
                _val_draw(img_path, boxes, header, os.path.join(rdir, fname), grid=_grid)
                # where each box sits on the PICTURE, as fractions of its width / height (the frame is enlarged 1.6x under
                # a header) -- the app lets a coach click a box in the picture (requested)
                _fw, _fh = Image.open(img_path).size
                _hh = 24 * len(header) + 10
                for b in boxes:
                    x1, y1, x2, y2 = b["box"]
                    b["nbox"] = [round(x1 / _fw, 4), round((y1 * 1.6 + _hh) / (_fh * 1.6 + _hh), 4),
                                 round(x2 / _fw, 4), round((y2 * 1.6 + _hh) / (_fh * 1.6 + _hh), 4)]
                # CONFIRMED CHANGE (requested: much clearer pictures for the player-number checks). A zoomed close-up of every
                # box (head and chest, where the number is) cut from the ORIGINAL captured frame -- not the picture with
                # boxes drawn on it -- enlarged with Lanczos and shown beside the box's row in the app. Stored in the box
                # as a small JPEG data URI (box["crop"]).
                if globals().get("PLAY_REVIEW_CROPS", True):
                    try:
                        _src = Image.open(img_path).convert("RGB")
                        _fcache = {}
                        for b in boxes:
                            b["crop"] = _pr_box_crop(_src, b["box"])
                            if globals().get("PLAY_REVIEW_CROP_BEST_FRAME", True):
                                _bi = _pr_best_instance(rows, b["track"], t, files, fps, _fcache)
                                if _bi is not None and _bi[1] != t:
                                    _fp2 = os.path.join(VISION_FRAMES_DIR, files[_bi[1]])
                                    _c2 = _pr_box_crop(Image.fromarray(_fcache[_fp2]), _bi[0])
                                    if _c2:
                                        b["crop"], b["crop_s"] = _c2, round(_bi[1] / fps, 1)
                    except Exception as _ce:
                        print(f"  [play review] close-ups not made ({type(_ce).__name__}: {_ce})", flush=True)
                pics.append({"which": which, "image": fname, "frame_file": files[t], "t": int(t), "boxes": boxes,
                             "grid": list(_grid) if _grid else None, "W": int(_fw), "H": int(_fh)})
            clip_file = _pr_clip(files, rows, numtxt, os.path.join(rdir, f"clip_{fid}")) if PLAY_REVIEW_VIDEO else None
            # the Title review part (same logic as the Auto-Title review)
            tagged = any(_tr_val(r.get(f"coach_{f}")) is not None for f, _ in _TR_FIELDS)
            fields = []
            for f, label in _TR_FIELDS:
                cv = _tr_val(r.get(f"coach_{f}"))
                av, ac, note = _tr_auto(r, f, tagged)
                # CONFIRMED CHANGE (coaches tag in the app now): a clip with no Title shows EVERY field (except the
                # Synergy-named screener), so it can be tagged even where the automatic Title has no answer yet
                if cv is None and av is None and (tagged or f == "screener"):
                    continue
                sure = av is not None and ac is not None and ac >= min_c
                fields.append({"field": f, "label": label, "coach": cv, "auto": av, "conf": round(ac, 2) if ac is not None else None,
                               "sure": sure, "same": (_tr_same(cv, av) if cv is not None and sure else None), "note": note})
            url, pos = _pr_synergy(r)
            vs = pd.to_numeric(r.get("video_start_s"), errors="coerce")
            plays.append({"clip_key": r["_key"], "clip_number": cn, "clock": clock_txt, "parts": _parts,
                          # its play-by-play row (the app shows the review inside that row of the play-by-play)
                          "pbp_event_order": (float(r["pbp_event_order"]) if pd.notna(pd.to_numeric(r.get("pbp_event_order"), errors="coerce"))
                                              else None),
                          "synergy": str(r.get("synergy_string") or ""), "coach_title": _tr_val(r.get("play_title")),
                          "auto_title": _tr_title(r, tagged),
                          "film": _tr_film(r.get("track_clip_key")),
                          "validation": bool(r.get("tag_validation")) if pd.notna(r.get("tag_validation")) else False,
                          "clip": clip_file, "clip_kind": ("video" if str(clip_file).endswith(".mp4") else "image"),
                          "poster": (f"clip_{fid}_poster.jpg"
                                     if clip_file and os.path.exists(os.path.join(rdir, f"clip_{fid}_poster.jpg")) else None),
                          "fid": fid,
                          "synergy_url": url,
                          "synergy_pos": int(pos) if pd.notna(pos) else None,
                          "video_at": (f"{int(vs // 60)}:{int(vs % 60):02d}" if pd.notna(vs) else None),
                          "pictures": pics, "fields": fields,
                          "five": {"offense": _trk_five(r.get("offense_lineup")), "defense": _trk_five(r.get("defense_lineup"))},
                          # CONFIRMED CHANGE (requested): the "Your check" dropdown shows jersey numbers ("really #12 Marino"),
                          # so each name in the five carries its number label (same numtxt as the box labels)
                          "five_labels": {nm: f"{numtxt(nm).split(' ')[0]} {nm}" for side in ("offense", "defense")
                                          for nm in _trk_five(r.get(f"{side}_lineup"))}})
        # every answer already known for each field (coaches' Titles and the model's answers, all games) -- offered as
        # suggestions for a typed answer, so it matches an existing spelling (page and app)
        vocab = {}
        for f, _lab in _TR_FIELDS:
            vals = set()
            for c in (f"coach_{f}", f"pred_{f}"):
                if c in play_calls.columns:
                    vals |= {str(v) for v in play_calls[c].dropna() if str(v).strip() and str(v) != "nan"}
            vocab[f] = sorted(vals)
        # CONFIRMED CHANGE (requested: the play reviews inside the Streamlit app, saved to GitHub; no more review.html).
        # The open review goes to the app's data folder (_pr_app_dir()/play_review/<game>/): review.json + each play's
        # video, cover image and pictures (1100 px). Commit / push it with the rest of the data; the app saves each
        # coach's answers to data/play_review_saves, which the parser reads after a git pull. One package per game:
        # a new run replaces it, and it's removed once its run has a saved review.
        try:
            _export_play_review_to_app(rdir, slug, f"{gd}|{gc}", stamp, plays, vocab)
            shutil.rmtree(rdir, ignore_errors=True)
        except Exception as _ae:
            print(f"  [play review] not exported to the app: {type(_ae).__name__}: {_ae} (scratch files kept in {rdir})", flush=True)
        _nt = sum("titles" in p_.get("parts", []) for p_ in plays)
        _np = sum("players" in p_.get("parts", []) for p_ in plays)
        _rng = lambda part: (lambda cs: f"clips {min(cs)}-{max(cs)}" if cs else "none")(
            [p_["clip_number"] for p_ in plays if part in p_.get("parts", [])])
        print(f"Play review: {gd} {gc}: {_nt} Title check(s) ({_rng('titles')}) -- Analytics > Film Tagging; {_np} player check(s) "
              f"({_rng('players')}) -- Analytics > Player Number Tracking "
              f"({'next unreviewed, in game order' if _mode != 'random' else 'random'})", flush=True)


# ---- Film Tagging queue: the clips with no tag yet, in game order, Titles only -------------------------------------------
# CONFIRMED CHANGE (requested: coaches tag games in the app only, not in Synergy's Title field). The Play review only takes
# 5 tracked plays a game at a time (it's built for the player checks). Tagging a game needs more: every captured clip of
# every game (ours and the upcoming opponent's) that has no tag yet goes, PLAY_TAG_PER_GAME at a time in game order, into a
# Titles-only package in <data>/play_tag/<game>/ -- the play as a short video, the automatic Title and one column per
# field. The app shows it on Analytics > Film Tagging; what a coach saves there is the clip's tag (play-calls cell:
# _pl_apply_app_tags). A game gets its next batch once the open one is saved (PLAY_TAG_REQUIRE_SAVED).
def _tag_titles_saved(slug_game, run):
    for f in glob.glob(os.path.join(_review_saves_dir(), "*.json")):
        d = _review_doc(f)
        if d is None or str(d.get("run")) != str(run):
            continue
        if re.sub(r"[^A-Za-z0-9]+", "_", str(d.get("game"))).strip("_") != slug_game:
            continue
        if "titles" in _review_parts(d):
            return True
    return False


def tag_queue():
    pc = play_calls.copy() if isinstance(globals().get("play_calls"), pd.DataFrame) else pd.DataFrame()
    if pc.empty:
        print("Film Tagging: no play calls yet.")
        return
    if "side" in pc.columns:
        pc = pc[pc["side"].isin(["UWW", "Opponent"])]
    has = lambda c: pc[c].notna() if c in pc.columns else pd.Series(False, index=pc.index)
    pc = pc[has("track_files") | has("frame_files")]
    if PLAY_REVIEW_ONLY_GAME:
        pc = pc[pc["game_code"].astype(str).str.contains(PLAY_REVIEW_ONLY_GAME, regex=False)]
    if pc.empty:
        print("Film Tagging: no captured clips to tag.")
        return
    title_review_answers()
    answered = {_pl_ckey_norm(ck) for (ck, _f) in (globals().get("_title_review_marks") or {})}
    n_per = int(globals().get("PLAY_TAG_PER_GAME", 20))
    stamp = _pr_dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_tag"
    min_c = float(globals().get("TAG_MODEL_MIN_CONFIDENCE", 0.6))
    if "_play_review_file_saves" in globals():
        _play_review_file_saves()
    vocab = {}
    for f, _lab in _TR_FIELDS:
        vals = set()
        for c in (f"coach_{f}", f"pred_{f}"):
            if c in play_calls.columns:
                vals |= {str(v) for v in play_calls[c].dropna() if str(v).strip() and str(v) != "nan"}
        vocab[f] = sorted(vals)
    summary = []
    for (gd, gc), g in pc.groupby(["game_date", "game_code"], dropna=False):
        slug_game = re.sub(r"[^A-Za-z0-9]+", "_", f"{gd}|{gc}").strip("_")
        slug = "tag_" + slug_game
        pkg = os.path.join(_pr_app_dir(), "play_tag", slug)
        g = g.assign(_key=[_pl_ckey_norm(f"{r.get('game_date')}|{r.get('clip_number')}|{r.get('synergy_string')}")
                           for _, r in g.iterrows()])
        untagged = g["decode_quality"].eq("Untagged") if "decode_quality" in g.columns else pd.Series(True, index=g.index)
        todo = g[untagged & ~g["_key"].isin(answered)]
        n_tagged = int((~untagged).sum())
        summary.append(f"{gd} {gc}: {n_tagged} of {len(g)} clip(s) tagged, {len(todo)} to go")
        if os.path.exists(os.path.join(pkg, "review.json")):
            try:
                with open(os.path.join(pkg, "review.json"), encoding="utf-8") as fh:
                    old_run = json.load(fh).get("run")
                if _tag_titles_saved(slug_game, old_run):
                    shutil.rmtree(pkg, ignore_errors=True)
                elif globals().get("PLAY_TAG_REQUIRE_SAVED", True):
                    continue                                   # its open batch isn't saved yet
            except Exception:
                pass
        if todo.empty:
            shutil.rmtree(pkg, ignore_errors=True)
            continue
        pick = todo.assign(_cn=pd.to_numeric(todo["clip_number"], errors="coerce")).sort_values("_cn", kind="stable").head(n_per)
        rdir = tempfile.mkdtemp(prefix=f"play_tag_{slug_game}_")
        plays = []
        try:
            _gn = _trk_numbers_for_game(gd, gc) if "_trk_numbers_for_game" in globals() else {}
        except Exception:
            _gn = {}
        for _, r in pick.iterrows():
            files = [f for f in str(r.get("track_files") or "").split(";") if f] or \
                    [f for f in str(r.get("frame_files") or "").split(";") if f]
            cn = int(r["_cn"]) if pd.notna(r["_cn"]) else 0
            fid = f"{cn:03d}_{len(plays):02d}"
            clip_file = None
            if PLAY_REVIEW_VIDEO and files:
                try:
                    clip_file = _pr_clip(files, [], None, os.path.join(rdir, f"clip_{fid}"))
                except Exception as _ce:
                    print(f"  [film tagging] clip video not made ({type(_ce).__name__}: {_ce})", flush=True)
            fields = []
            for f, label in _TR_FIELDS:
                if f == "screener":
                    continue
                av, ac, note = _tr_auto(r, f, False)
                sure = av is not None and ac is not None and ac >= min_c
                fields.append({"field": f, "label": label, "coach": None, "auto": av,
                               "conf": round(ac, 2) if ac is not None else None, "sure": sure, "same": None, "note": note})
            clock = r.get("time_remaining_seconds")
            url, pos = _pr_synergy(r)
            plays.append({"clip_key": f"{r.get('game_date')}|{r.get('clip_number')}|{r.get('synergy_string')}",
                          "clip_number": cn,
                          "clock": (f"{r.get('period', '')} {int(clock // 60)}:{int(clock % 60):02d}" if pd.notna(clock) else "(no clock)"),
                          "synergy": str(r.get("synergy_string") or ""), "coach_title": None,
                          "auto_title": _tr_title(r, False), "film": _tr_film(r.get("track_clip_key")),
                          "offense": r.get("offense_team"), "defense": r.get("defense_team"), "player": r.get("player"),
                          "result": r.get("result"), "clip": clip_file,
                          "clip_kind": ("video" if str(clip_file).endswith(".mp4") else "image"),
                          "poster": (f"clip_{fid}_poster.jpg" if clip_file and os.path.exists(os.path.join(rdir, f"clip_{fid}_poster.jpg")) else None),
                          "fid": fid, "synergy_url": url, "synergy_pos": int(pos) if pd.notna(pos) else None,
                          "pictures": [], "fields": fields,
                          "five": {"offense": _trk_five(r.get("offense_lineup")), "defense": _trk_five(r.get("defense_lineup"))},
                          # requested: the Screener / Screen defender lists show each player's jersey number
                          "five_labels": {nm: (f"#{_gn[str(nm).lower()]} {nm}" if _gn.get(str(nm).lower()) else nm)
                                          for side_ in ("offense", "defense")
                                          for nm in _trk_five(r.get(f"{side_}_lineup"))}})
        try:
            _export_play_review_to_app(rdir, slug, f"{gd}|{gc}", stamp, plays, vocab, kind="play_tag")
            shutil.rmtree(rdir, ignore_errors=True)
            print(f"Film Tagging: {gd} {gc}: {len(plays)} clip(s) to tag (of {len(todo)} untagged) -- in the app: "
                  f"Analytics > Film Tagging", flush=True)
        except Exception as _ae:
            print(f"  [film tagging] not exported to the app: {type(_ae).__name__}: {_ae}", flush=True)
    if summary:
        print("Film Tagging -- tagging progress by game (Titles + app tags):\n  " + "\n  ".join(summary), flush=True)


def _pr_retire_redated():
    """CONFIRMED BUG (fixed with the Play calls date fix): the WashU game (3/7) had been filed one day early, as
    "2026-03-06 UWWhitewater@Wash(StLouis)", and its Play review / Film Tagging batch went to the app under that date.
    Now that it's dated right, a review or batch whose game is no longer among the play calls -- but the same game code
    is, a day away -- is the old copy: it's removed from the app's data folder so the app doesn't show it twice."""
    pc = globals().get("play_calls")
    if not isinstance(pc, pd.DataFrame) or pc.empty or not {"game_date", "game_code"} <= set(pc.columns):
        return
    have = set()
    by_code = {}
    for gd_, gc_ in pc[["game_date", "game_code"]].dropna().drop_duplicates().itertuples(index=False):
        try:
            d_ = pd.Timestamp(gd_).date()
        except Exception:
            continue
        have.add((d_, str(gc_)))
        by_code.setdefault(str(gc_), set()).add(d_)
    for kind in ("play_review", "play_tag"):
        base = os.path.join(_pr_app_dir(), kind)
        if not os.path.isdir(base):
            continue
        for sub in sorted(os.listdir(base)):
            rj = os.path.join(base, sub, "review.json")
            if not os.path.isfile(rj):
                continue
            try:
                with open(rj, encoding="utf-8") as fh:
                    game = str(json.load(fh).get("game") or "")
                gd_, gc_ = game.split("|", 1)
                d_ = pd.Timestamp(gd_).date()
            except Exception:
                continue
            if (d_, gc_) in have:
                continue
            if any(abs((x - d_).days) <= 1 for x in by_code.get(gc_, ())):
                shutil.rmtree(os.path.join(base, sub), ignore_errors=True)
                print(f"  [{'play review' if kind == 'play_review' else 'film tagging'}] removed the old copy of {gc_} "
                      f"filed under {d_} (the game is dated right now; a new one is made under the right date)", flush=True)


try:
    _pr_retire_redated()
except Exception as _e:
    print(f"  (old re-dated reviews not checked: {type(_e).__name__}: {_e})")

if RUN_PLAY_REVIEW:
    try:
        play_review()
    except Exception as _e:
        print(f"Play review skipped: {type(_e).__name__}: {_e}")
if globals().get("RUN_TAG_QUEUE", True):
    try:
        tag_queue()
    except Exception as _e:
        print(f"Film Tagging skipped: {type(_e).__name__}: {_e}")
