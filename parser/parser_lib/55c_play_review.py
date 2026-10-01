# 55c_play_review.py -- code for the notebook section "Play review"
# Runs inside the notebook via run_section("55c_play_review"); its settings are in that notebook cell.

# --- Play review: the player checks and the Title review together, on 20 random plays per game ------------------------
# CONFIRMED CHANGE (requested: "combine the player-number review and the Title review into one file and do both at the
# same time; only 20 plays per game, a random set -- a different 20 when I run it again; a 'wrong team' option; and a
# gif of the play, the clip, or a link to Synergy").
#
# One page per game and run: INPUT_DIR/play_review/<game>/run_<date_time>/review.html. For each of the 20 plays:
#   * an animated GIF of the play -- the tracking frames at real speed, every player's box and assigned number drawn on;
#   * a link to the game on Synergy with the clip's number and where it starts in the game video;
#   * the START and END pictures with a row per box: correct / really <player on his team> / really <player on the OTHER
#     team> / wrong team (don't know who) / not a player;
#   * the Title review: the coach's Title, the automatic Title (held-out for tagged plays) and right / wrong / can't tell
#     per field, with a box for the right answer.
# ONE "Save" downloads play_review_<game>_<run>.json holding both the player checks and the Title answers; the parser
# picks it up from Downloads next run (player checks -> certain names, "wrong team" moves the player to the other team;
# Title answers -> scored, and labels for the Tag model on untagged plays).
import os
import re
import glob
import sys
import json
import random
import subprocess
import datetime as _pr_dt     # NOT "import datetime": the notebook's datetime is the class (section 01)
import html as _pr_html
import pandas as pd
import numpy as np


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


def _val_draw(img_path, boxes, header_lines, out_path, scale=1.6):
    """Picture enlarged (scale), bigger font, labels that would overlap stacked upward with a line to their box."""
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


def _pr_reviewed_keys():
    """Clip keys already reviewed (any player check or Title answer saved)."""
    keys = set()
    try:
        for ch in coach_checks_all()[0]:
            keys.add(ch.get("clip_key"))
    except Exception:
        pass
    try:
        title_review_answers()
        keys |= {ck for (ck, _f) in (globals().get("_title_review_marks") or {})}
    except Exception:
        pass
    return keys


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
                      "label": (numtxt(rr["name"]) + ("?" if rr.get("name_how") == "best guess" else "")) if named else "",
                      "guess": named and rr.get("name_how") == "best guess"})
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
    done = _pr_reviewed_keys() if PLAY_REVIEW_SKIP_REVIEWED else set()
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
        _play_review_file_saves()                     # saved reviews into their run folders first
    for (gd, gc), g in pc.groupby(["game_date", "game_code"], dropna=False):
        # CONFIRMED CHANGE (requested): a new run for a game only when EVERY earlier run folder of that game has its
        # saved review (.json) in it -- otherwise reviews pile up unfinished. PLAY_REVIEW_REQUIRE_SAVED = False skips this.
        _slug_chk = re.sub(r"[^A-Za-z0-9]+", "_", f"{gd}|{gc}").strip("_")
        _open = [d for d in sorted(glob.glob(os.path.join(INPUT_DIR, "play_review", _slug_chk, "run_*")))
                 if os.path.isdir(d) and not any(_review_doc(f) is not None
                                                 for f in glob.glob(os.path.join(d, "*.json")))]   # any name
        if _open and globals().get("PLAY_REVIEW_REQUIRE_SAVED", True):
            print(f"Play review: {gd} {gc} -- no new run: {len(_open)} earlier run(s) not saved yet: "
                  + "; ".join(os.path.join(d, "review.html") for d in _open)
                  + ". Open it, review, press Save (the file is picked up from Downloads), or delete that run folder "
                    "if you're not doing it.", flush=True)
            continue
        g = g.assign(_key=[f"{r.get('game_date')}|{r.get('clip_number')}|{r.get('synergy_string')}" for _, r in g.iterrows()])
        fresh = g[~g["_key"].isin(done)]
        pool = fresh if len(fresh) else g
        pick = pool.loc[rng.sample(list(pool.index), min(PLAY_REVIEW_PLAYS_PER_GAME, len(pool)))].sort_values("clip_number")
        slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{gd}|{gc}").strip("_")
        rdir = os.path.join(INPUT_DIR, "play_review", slug, f"run_{stamp}")
        os.makedirs(rdir, exist_ok=True)
        gnums = _trk_numbers_for_game(gd, gc)
        numtxt = lambda n: f"#{gnums.get(str(n).lower(), '?')} {str(n).split()[-1]}"
        plays = []
        for _, r in pick.iterrows():
            files = [f for f in str(r["track_files"]).split(";") if f]
            rows = pt[pt["clip_key"] == r["track_clip_key"]].to_dict("records")
            n = len(files)
            cn = int(r["clip_number"])
            # pictures: the start and the end of the play, most players visible
            t_end = pd.to_numeric(r.get("track_finish_frame"), errors="coerce")
            end_hi = int(min(n - 1, t_end)) if pd.notna(t_end) else n - 1
            picks_ = [("start", _val_frame_pick(rows, 0, max(1, int(0.25 * n)))),
                      ("end", _val_frame_pick(rows, int(max(0, end_hi - 2 * fps)), end_hi, prefer_late=True))]
            clock = r.get("time_remaining_seconds")
            clock_txt = f"{r.get('period', '')} {int(clock // 60)}:{int(clock % 60):02d}" if pd.notna(clock) else "(no clock)"
            lu = lambda side: ", ".join(numtxt(nm) for nm in _trk_five(r.get(f"{side}_lineup"))) or "(lineup unknown)"
            pics = []
            for which, t in picks_:
                if t is None or t >= n or any(p_["t"] == t for p_ in pics):
                    continue
                img_path = os.path.join(VISION_FRAMES_DIR, files[t])
                if not os.path.exists(img_path):
                    continue
                from PIL import Image
                boxes = _pr_boxes(rows, t, Image.open(img_path).size[1], numtxt)
                header = [f"Clip {cn}  {clock_txt}  {str(r.get('synergy_string'))[:100]}",
                          f"{'START' if which == 'start' else 'END'} of the play -- {t / fps:.1f} s into the clip",
                          f"OFFENSE (orange) {r.get('offense_team')}: {lu('offense')}",
                          f"DEFENSE (blue)  {r.get('defense_team')}: {lu('defense')}",
                          "Solid box = identified from evidence; DASHED box with ? = best guess; grey = not named"]
                fname = f"clip_{cn:03d}_{'a_start' if which == 'start' else 'b_end'}.jpg"
                _val_draw(img_path, boxes, header, os.path.join(rdir, fname))
                pics.append({"which": which, "image": fname, "frame_file": files[t], "t": int(t), "boxes": boxes})
            clip_file = _pr_clip(files, rows, numtxt, os.path.join(rdir, f"clip_{cn:03d}")) if PLAY_REVIEW_VIDEO else None
            # the Title review part (same logic as the Auto-Title review)
            tagged = any(_tr_val(r.get(f"coach_{f}")) is not None for f, _ in _TR_FIELDS)
            fields = []
            for f, label in _TR_FIELDS:
                cv = _tr_val(r.get(f"coach_{f}"))
                av, ac, note = _tr_auto(r, f, tagged)
                if cv is None and av is None:
                    continue
                sure = av is not None and ac is not None and ac >= min_c
                fields.append({"field": f, "label": label, "coach": cv, "auto": av, "conf": round(ac, 2) if ac is not None else None,
                               "sure": sure, "same": (_tr_same(cv, av) if cv is not None and sure else None), "note": note})
            url, pos = _pr_synergy(r)
            vs = pd.to_numeric(r.get("video_start_s"), errors="coerce")
            plays.append({"clip_key": r["_key"], "clip_number": cn, "clock": clock_txt,
                          "synergy": str(r.get("synergy_string") or ""), "coach_title": _tr_val(r.get("play_title")),
                          "auto_title": _tr_title(r, tagged),
                          "film": _tr_film(r.get("track_clip_key")),
                          "validation": bool(r.get("tag_validation")) if pd.notna(r.get("tag_validation")) else False,
                          "clip": clip_file, "clip_kind": ("video" if str(clip_file).endswith(".mp4") else "image"),
                          "poster": (f"clip_{cn:03d}_poster.jpg"
                                     if clip_file and os.path.exists(os.path.join(rdir, f"clip_{cn:03d}_poster.jpg")) else None),
                          "synergy_url": url,
                          "synergy_pos": int(pos) if pd.notna(pos) else None,
                          "video_at": (f"{int(vs // 60)}:{int(vs % 60):02d}" if pd.notna(vs) else None),
                          "pictures": pics, "fields": fields,
                          "five": {"offense": _trk_five(r.get("offense_lineup")), "defense": _trk_five(r.get("defense_lineup"))}})
        # CONFIRMED CHANGE (requested: "embed the plays right into the html"). Every play's video and pictures go INSIDE
        # review.html, so the page is one self-contained file (open it anywhere, share it on its own). About 1 MB per play.
        if PLAY_REVIEW_EMBED:
            used = []
            for p in plays:
                if p["clip"]:
                    used.append(p["clip"])
                    p["clip"] = _pr_embed(rdir, p["clip"], "clip")
                for pic in p["pictures"]:
                    used.append(pic["image"])
                    pic["image"] = _pr_embed(rdir, pic["image"], "image")
                if p.get("poster"):
                    used.append(p["poster"])
                    p["poster"] = _pr_embed(rdir, p["poster"], "image")
            if not PLAY_REVIEW_KEEP_FILES:
                for f in used:
                    try:
                        os.remove(os.path.join(rdir, f))
                    except OSError:
                        pass
        # every answer already known for each field (coaches' Titles and the model's answers, all games) -- offered as
        # suggestions in the "right answer" box so a typed answer matches an existing spelling
        vocab = {}
        for f, _lab in _TR_FIELDS:
            vals = set()
            for c in (f"coach_{f}", f"pred_{f}"):
                if c in play_calls.columns:
                    vals |= {str(v) for v in play_calls[c].dropna() if str(v).strip() and str(v) != "nan"}
            vocab[f] = sorted(vals)
        page = os.path.join(rdir, "review.html")
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(_PR_PAGE.replace("__DATA__", json.dumps({"game": f"{gd}|{gc}", "slug": slug, "run": stamp,
                                                             "plays": plays, "vocab": vocab}, default=str))
                     .replace("__TITLE__", _pr_html.escape(f"{gd} {gc}")))
        print(f"Play review: {gd} {gc}: {len(plays)} random play(s) ({len(g) - len(fresh)} already reviewed, left out) "
              f"-- open {page} ({os.path.getsize(page) / 1e6:.0f} MB{', everything inside it' if PLAY_REVIEW_EMBED else ''})",
              flush=True)


_PR_PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Play review -- __TITLE__</title>
<style>body{font-family:Arial,sans-serif;margin:14px;background:#f4f4f4}.play{background:#fff;margin:16px 0;padding:10px;
border:1px solid #ccc}img{max-width:100%;border:1px solid #999}table{border-collapse:collapse;font-size:13px;margin-top:6px}
td,th{border:1px solid #ddd;padding:3px 6px;vertical-align:top}.off{color:#c66a00;font-weight:bold}.def{color:#1e7fc8;font-weight:bold}
.t{font-family:Consolas,monospace;font-size:14px}.ok{background:#e3f4e3}.no{background:#fbe3e3}.uns{color:#888}
#bar{position:sticky;top:0;background:#4E2A84;color:#fff;padding:8px;z-index:5}button{padding:6px 12px}
.film{background:#eef3fb;padding:4px 6px;margin-top:4px;font-size:13px}h4{margin:12px 0 2px 0}
.nav a{margin-right:8px}
.mini{font-size:12px;color:#555;margin-top:4px}
.pair{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;margin:8px 0}
.pair>.media{flex:0 0 auto;max-width:560px;width:100%}
.pair>.side{flex:1 1 380px;min-width:320px}
.pic{width:560px;max-width:100%;cursor:zoom-in}
.pic.big{width:1300px;max-width:none;cursor:zoom-out}</style></head><body>
<div id="bar">Play review -- __TITLE__ &nbsp; <button id="save">Save my review</button> <span id="cnt"></span></div>
<p>20 random plays. For each: watch the video (or open it on Synergy) and check the automatic Title beside it, then
check the players in the pictures below (click a picture to enlarge it). Title rows where the coach's value and the
automatic value differ start as <b>wrong</b> with the coach's value filled in -- change any where the coach's tag was the
miss. You don't have to finish -- save any time; everything you marked counts.</p>
<div class="nav" id="nav"></div><div id="plays"></div>
<script>
const D = __DATA__; const marks = {}, fixes = {}; const prefilled = new Set();
const norm = x => String(x).toLowerCase().replace(/[^a-z0-9#]+/g, '');   // same comparison as the red / green shading
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
document.getElementById('nav').innerHTML = 'Plays: ' + D.plays.map((p, i) => `<a href="#p${i}">#${p.clip_number}</a>`).join('');
const root = document.getElementById('plays');
// suggestions for the "right answer" boxes: every answer already known for that field
document.body.insertAdjacentHTML('beforeend', Object.entries(D.vocab || {}).map(([f, vals]) =>
  `<datalist id="dl_${esc(f)}">` + vals.map(v => `<option value="${esc(v)}">`).join('') + '</datalist>').join(''));
D.plays.forEach((p, pi) => {
  let h = `<div class="play" id="p${pi}"${p.validation ? ' style="border:3px solid #4E2A84"' : ''}><h3>Clip ${p.clip_number} &nbsp; <small>${esc(p.clock)} &nbsp; ${esc(p.synergy)}</small>` +
          (p.validation ? ' <span style="background:#4E2A84;color:#fff;padding:2px 6px;font-size:12px">VALIDATION PLAY</span>' : '') + '</h3>';
  // top: the video on the left, the Title check on the right
  h += '<div class="pair"><div class="media">';
  if (p.clip && p.clip_kind === 'video') h += `<video src="${esc(p.clip)}"${p.poster ? ` poster="${esc(p.poster)}"` : ''} controls loop muted playsinline preload="metadata" style="width:100%"></video>`;
  else if (p.clip) h += `<img src="${esc(p.clip)}" style="width:100%">`;
  if (p.synergy_url) h += `<div class="mini"><a href="${esc(p.synergy_url)}" target="_blank">Open the game on Synergy</a> -- clip #${p.clip_number}` +
                          (p.synergy_pos ? ` (row ${p.synergy_pos} of the clip list)` : '') + (p.video_at ? `, starts ${esc(p.video_at)} into the game video` : '') + '</div>';
  h += '</div><div class="side"><h4 style="margin-top:0">Title</h4>' +
       `<table><tr><td><b>Coach's Title</b></td><td class="t">${p.coach_title ? esc(p.coach_title) : '<i>not tagged</i>'}</td></tr>` +
       `<tr><td><b>Automatic Title</b></td><td class="t">${p.auto_title ? esc(p.auto_title) : '<i>nothing confident enough yet</i>'}</td></tr></table>`;
  if (p.film) h += `<div class="film"><b>Seen on the film:</b> ${esc(p.film)}</div>`;
  if (p.fields.length) {
    h += '<table><tr><th>Field</th><th>Coach</th><th>Automatic</th><th>Your answer</th></tr>';
    p.fields.forEach((f, fi) => {
      const cls = f.same === true ? 'ok' : (f.same === false ? 'no' : '');
      const auto = f.auto == null ? `<i class="uns">${esc(f.note || 'no answer')}</i>` :
                   (f.sure ? `${esc(f.auto)} <small>(${Math.round(100*f.conf)}%)</small>` : `<span class="uns">unsure: ${esc(f.auto)} (${Math.round(100*(f.conf||0))}%)</span>`);
      // CONFIRMED CHANGE (requested): when the coach's value and the automatic value differ, the row starts as
      // "wrong" with the coach's value filled in. Left untouched it's saved with prefilled: true (the accuracy figures
      // skip those -- the "coach Titles" comparison already counts them); changed or re-picked, it's a real review.
      const k = `ti_${pi}_${fi}`;
      const pre = f.coach != null && f.auto != null && norm(f.coach) !== norm(f.auto);
      if (pre) { marks[k] = 'wrong'; fixes[k] = f.coach; prefilled.add(k); }
      h += `<tr class="${cls}"><td>${esc(f.label)}</td><td>${f.coach == null ? '' : esc(f.coach)}</td><td>${auto}</td>` +
           `<td><select data-k="${k}"><option value="">--</option><option value="right">right</option>` +
           `<option value="wrong"${pre ? ' selected' : ''}>wrong</option><option value="cant">can't tell</option></select> ` +
           `<input size="16" placeholder="right answer" list="dl_${esc(f.field)}" data-k="${k}"${pre ? ` value="${esc(f.coach)}"` : ''}></td></tr>`;
    });
    h += '</table>';
  }
  h += '</div></div>';
  // below: each still picture on the left, its player checks on the right (click a picture to enlarge it)
  p.pictures.forEach((pic, ki) => {
    h += `<div class="pair"><div class="media"><b>${pic.which === 'start' ? 'START of the play' : 'END of the play'}</b><br>` +
         `<img class="pic" src="${esc(pic.image)}" onclick="this.classList.toggle('big')" title="click to enlarge / shrink"></div>` +
         '<div class="side"><h4 style="margin-top:0">Players</h4><table><tr><th>Box</th><th>Side</th><th>Assigned</th><th>Your check</th></tr>';
    pic.boxes.forEach((b, bi) => {
      const mine = (p.five[b.side] || []), other = (p.five[b.side === 'offense' ? 'defense' : 'offense'] || []);
      const opts = ['<option value="">-- not checked --</option>', '<option value="correct">correct</option>']
        .concat(mine.filter(n => n !== b.name).map(n => `<option value="same:${esc(n)}">really ${esc(n)}</option>`))
        .concat(other.map(n => `<option value="other:${esc(n)}">really ${esc(n)} (other team)</option>`))
        .concat(['<option value="__wrong_team__">wrong team (don\'t know who)</option>', '<option value="__not_a_player__">not a player</option>']);
      h += `<tr><td>${b.id}</td><td class="${b.side === 'offense' ? 'off' : 'def'}">${b.side}</td>` +
           `<td>${b.label ? esc(b.label) + ' <small>(' + esc(b.how || '') + ')</small>' : '<i>not named</i>'}</td>` +
           `<td><select data-k="pl_${pi}_${ki}_${bi}">${opts.join('')}</select></td></tr>`;
    });
    h += '</table></div></div>';
  });
  root.insertAdjacentHTML('beforeend', h + '</div>');
});
const upd = () => document.getElementById('cnt').textContent = Object.keys(marks).length + ' answer(s) marked';
document.querySelectorAll('select').forEach(s => s.onchange = () => { prefilled.delete(s.dataset.k); if (s.value) marks[s.dataset.k] = s.value; else delete marks[s.dataset.k]; upd(); });
document.querySelectorAll('input').forEach(i => i.oninput = () => { prefilled.delete(i.dataset.k); fixes[i.dataset.k] = i.value; });
upd();
document.getElementById('save').onclick = () => {
  const out = {game: D.game, run: D.run, saved: new Date().toISOString(), checks: [], answers: []};
  for (const [k, v] of Object.entries(marks)) {
    const parts = k.split('_');
    if (parts[0] === 'pl') {
      const [pi, ki, bi] = parts.slice(1).map(Number); const p = D.plays[pi], pic = p.pictures[ki], b = pic.boxes[bi];
      let verdict, name = null;
      if (v === 'correct') { verdict = 'correct'; name = b.name; }
      else if (v === '__not_a_player__') verdict = 'not a player';
      else if (v === '__wrong_team__') verdict = 'wrong team';
      else if (v.startsWith('same:')) { verdict = 'wrong'; name = v.slice(5); }
      else if (v.startsWith('other:')) { verdict = 'wrong team'; name = v.slice(6); }
      out.checks.push({clip_key: p.clip_key, clip_number: p.clip_number, frame_file: pic.frame_file, t: pic.t, px: b.px, py: b.py,
                       side: b.side, assigned: b.name, assigned_how: b.how, verdict: verdict, true_name: name});
    } else {
      const [pi, fi] = parts.slice(1).map(Number); const p = D.plays[pi], f = p.fields[fi];
      out.answers.push({clip_key: p.clip_key, clip_number: p.clip_number, field: f.field, coach: f.coach, auto: f.auto,
                        auto_conf: f.conf, verdict: v === 'cant' ? "can't tell" : v, correct: fixes[k] || null,
                        prefilled: prefilled.has(k)});
    }
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {type: 'application/json'}));
  a.download = 'play_review_' + D.slug + '_' + D.run + '.json'; a.click();
};
</script></body></html>"""

if RUN_PLAY_REVIEW:
    try:
        play_review()
    except Exception as _e:
        print(f"Play review skipped: {type(_e).__name__}: {_e}")
