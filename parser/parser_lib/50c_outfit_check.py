# 50c_outfit_check.py -- code for the notebook section "Outfit check: is this person a player, a referee, a coach or bench?"
# Runs inside the notebook via run_section("50c_outfit_check"); its settings are in that notebook cell.
#
# CONFIRMED CHANGE (requested: "do #1 -- and if it performs well, add it"; idea from github.com/HanaFEKI/AI_BasketBall_Analysis_v1,
# which sorts players by their clothes with Fashion-CLIP). 87 of the 658 checked boxes were NOT players (referees, coaches,
# the bench, fans), and most were given a name. Fashion-CLIP is an image model that scores a picture against plain words --
# no training: each person is scored against "a basketball player in a jersey" vs "a referee in a striped shirt", "a man in a
# suit", "a person in a hoodie"... The share that goes to the non-player words is his "not a player" score.
#
# TEST FIRST (this cell): every box a coach checked is scored; the coach's answer ("not a player" or a real player) is the
# truth. It finds the lowest score at which flagged boxes are really non-players at least OUTFIT_MIN_PRECISION of the time,
# and how many of the non-players that catches. The result is saved (_tracking/outfit_check_test.json) with every box's score
# (_tracking/outfit_check_scores.csv). The Player tracking cell uses it only when the test PASSED (TRACK_OUTFIT_CHECK = "auto").
import os
import json
import time as _oc_time

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



for _k, _v in (("OUTFIT_MODEL", "patrickjohncyh/fashion-clip"), ("OUTFIT_MIN_PRECISION", 0.9), ("OUTFIT_MIN_RECALL", 0.25),
               ("OUTFIT_MIN_NONPLAYERS", 20), ("RUN_OUTFIT_CHECK_TEST", True),
               ("OUTFIT_MAX_PLAYERS_LOST", 0.05), ("OUTFIT_MIN_PLAYERS", 20)):
    globals().setdefault(_k, _v)
if "TRACK_DIR" not in globals() and "INPUT_DIR" in globals():
    TRACK_DIR = os.path.join(INPUT_DIR, "_tracking")

# the words each person is scored against (first group = a player on the floor, second = everyone else)
OUTFIT_PLAYER_WORDS = globals().get("OUTFIT_PLAYER_WORDS") or [
    "a basketball player wearing a sleeveless jersey and shorts",
    "an athlete in a basketball uniform",
]
OUTFIT_OTHER_WORDS = globals().get("OUTFIT_OTHER_WORDS") or [
    "a referee wearing a black and white striped shirt",
    "a man wearing a suit jacket and dress pants",
    "a person wearing a polo shirt and slacks",
    "a person wearing a hoodie or sweatshirt",
    "a person wearing a long-sleeve warm-up shirt",
    "a spectator sitting in the stands",
]
OUTFIT_TEST_PATH = os.path.join(TRACK_DIR, "outfit_check_test.json")
_OC_CACHE_PATH = os.path.join(TRACK_DIR, "outfit_scores_cache.pkl")


def _oc_model():
    """(model, processor) -- loaded once. Installs `transformers` if it's missing (then asks for a kernel restart)."""
    m = globals().get("_oc_loaded")
    if m is not None:
        return m
    try:
        import torch
        from transformers import CLIPModel, CLIPProcessor
    except ImportError:
        import subprocess
        import sys
        print("  [outfit] installing transformers (one time)...", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "transformers"], check=False)
        raise RuntimeError("transformers was installed. RESTART THE KERNEL (Kernel > Restart) and run the parser again.")
    print(f"  [outfit] loading {OUTFIT_MODEL} (downloads ~600 MB the first time)...", flush=True)
    model = CLIPModel.from_pretrained(OUTFIT_MODEL).eval()
    proc = CLIPProcessor.from_pretrained(OUTFIT_MODEL)
    with torch.no_grad():
        t = proc(text=OUTFIT_PLAYER_WORDS + OUTFIT_OTHER_WORDS, return_tensors="pt", padding=True)
        tf = _oc_text_feats(model, t)
        tf = tf / tf.norm(dim=-1, keepdim=True)
    globals()["_oc_loaded"] = (model, proc, tf)
    return globals()["_oc_loaded"]


# CONFIRMED BUG (fixed; "AttributeError: 'BaseModelOutputWithPooling' object has no attribute 'norm'"): newer transformers
# versions return a results object from get_image_features / get_text_features instead of the feature numbers. The
# features are now worked out the same way those functions always did it -- the model's pooled output passed through its
# projection layer -- which gives the same numbers on every transformers version.
def _oc_pooled(out):
    return out.pooler_output if hasattr(out, "pooler_output") else out[1]


def _oc_text_feats(model, t):
    out = model.text_model(input_ids=t["input_ids"], attention_mask=t.get("attention_mask"))
    return model.text_projection(_oc_pooled(out))


def _oc_image_feats(model, px):
    out = model.vision_model(pixel_values=px["pixel_values"])
    return model.visual_projection(_oc_pooled(out))


def _oc_crop(img, box):
    """The whole person (clothes from shoulders to shoes), a little wider than the box."""
    x1, y1, x2, y2 = [float(v) for v in box[:4]]
    w = x2 - x1
    c = img[max(int(y1), 0):max(int(y2), int(y1) + 1), max(int(x1 - 0.08 * w), 0):max(int(x2 + 0.08 * w), int(x1) + 1)]
    return c if c.size and min(c.shape[:2]) >= 12 else None


def _oc_scores(crops_bgr, batch=32):
    """BGR crops -> the share of each crop's probability that goes to the NON-player words (0..1; None for a missing crop)."""
    import torch
    from PIL import Image
    model, proc, tf = _oc_model()
    out = [None] * len(crops_bgr)
    idx = [k for k, c in enumerate(crops_bgr) if c is not None]
    n_pl = len(OUTFIT_PLAYER_WORDS)
    scale = float(model.logit_scale.detach().exp())
    for s in range(0, len(idx), batch):
        part = idx[s:s + batch]
        ims = [Image.fromarray(crops_bgr[k][:, :, ::-1].copy()) for k in part]
        with torch.no_grad():
            px = proc(images=ims, return_tensors="pt")
            f = _oc_image_feats(model, px)
            f = f / f.norm(dim=-1, keepdim=True)
            pr = (scale * f @ tf.T).softmax(dim=-1)
        for k, row in zip(part, pr):
            out[k] = float(row[n_pl:].sum())
    return out


def _oc_cache():
    c = globals().get("_oc_cache_d")
    if c is None:
        try:
            c = _safe_read_pickle(_OC_CACHE_PATH) if os.path.exists(_OC_CACHE_PATH) else {}
            if c.get("_words") != (OUTFIT_MODEL, tuple(OUTFIT_PLAYER_WORDS), tuple(OUTFIT_OTHER_WORDS)):
                c = {}
        except Exception:
            c = {}
        c["_words"] = (OUTFIT_MODEL, tuple(OUTFIT_PLAYER_WORDS), tuple(OUTFIT_OTHER_WORDS))
        globals()["_oc_cache_d"] = c
    return c


def _oc_save_cache():
    try:
        _safe_to_pickle(globals().get("_oc_cache_d", {}), _OC_CACHE_PATH)
    except Exception:
        pass


def outfit_scores_for(items, base):
    """items: [(frame file, box)] -> [score or None]. Scores are cached on disk by frame + box, so reruns are fast; each
    picture is read once.
    CONFIRMED CHANGE (requested: "These take a very long time to run, can you add some description print outs so I know what
    is happening" -- 67,302 pictures with nothing printed after the model loaded). It now says how many pictures are saved
    from earlier runs vs new, then prints a count every 20 s (frames read, pictures scored, time so far / time left), and
    saves the scores every 5 minutes so a stopped run keeps what it did."""
    import cv2
    cache = _oc_cache()
    keys = [f"{f}|{int(b[0])}|{int(b[1])}|{int(b[2])}|{int(b[3])}" for f, b in items]
    todo = {}
    for n, (k, (f, b)) in enumerate(zip(keys, items)):
        if k not in cache:
            todo.setdefault(f, []).append((n, b))
    n_new = sum(len(v) for v in todo.values())
    print(f"    [outfit] {len(keys) - n_new:,} of {len(keys):,} picture(s) already scored in earlier runs (reused); "
          f"{n_new:,} new to score, from {len(todo):,} frame(s)" + (" -- nothing to do" if not n_new else ""), flush=True)
    if todo:
        t0 = last = last_save = _oc_time.time()
        done = n_frames = 0
        crops, where = [], []

        def _say(final=False):
            el = (_oc_time.time() - t0) / 60.0
            left = el / done * (n_new - done) if done else None
            print(f"    [outfit] pictures scored: {done:,} / {n_new:,} ({100 * done // max(n_new, 1)}%), {n_frames:,} of "
                  f"{len(todo):,} frame(s) read -- {el:.1f} min so far"
                  + (f", ~{left:.1f} min left" if left is not None and not final else ""), flush=True)

        def _score_batch():
            nonlocal done, last, last_save, crops, where
            for n, s_ in zip(where, _oc_scores(crops)):
                cache[keys[n]] = s_
            done += len(where)
            crops, where = [], []
            now = _oc_time.time()
            if now - last >= 20:
                last = now
                _say()
            if now - last_save >= 300:                    # every 5 minutes: a stopped run keeps its scores
                last_save = now
                _oc_save_cache()

        for f, lst in todo.items():
            img = cv2.imread(os.path.join(base, f))
            n_frames += 1
            for n, b in lst:
                crops.append(_oc_crop(img, b) if img is not None else None)
                where.append(n)
            if len(crops) >= 256:
                _score_batch()
        if crops:
            _score_batch()
        _say(final=True)
        # CONFIRMED BUG (fixed): a box whose picture wasn't on disk was cached as "no score" for good, so it stayed unscored
        # even after the picture came back. Only real scores are kept.
        _miss = [k for k in keys if k in cache and cache[k] is None]
        for k in _miss:
            del cache[k]
        if _miss:
            print(f"    [outfit] {len(_miss):,} picture(s) couldn't be scored (frame not on disk) -- tried again next run",
                  flush=True)
        _oc_save_cache()
    return [cache.get(k) for k in keys]


# Frames packed by the frame archive are read through its file hooks -- loaded here too, so archived games' pictures count
# even when this cell runs on its own in a fresh session.
if "vision_frame_archived" not in globals() and "PARSER_LIB" in globals() \
        and os.path.exists(os.path.join(PARSER_LIB, "46a_frame_archive.py")):
    FRAME_ARCHIVE_STEP = "hooks"
    run_section("46a_frame_archive")


def outfit_check_test():
    """Score every coach-checked box; the coach's answer is the truth. -> result dict (also saved to OUTFIT_TEST_PATH)."""
    base = VISION_FRAMES_DIR if "VISION_FRAMES_DIR" in globals() else os.path.join(INPUT_DIR, "_vision_frames")
    checks = coach_checks_all()[0] if "coach_checks_all" in globals() else []
    det = _jr_det_cache() if "_jr_det_cache" in globals() else {}
    if not checks or not det:
        print("Outfit check test: needs the saved player checks and the saved detections (run Play calls and Player tracking "
              "first).", flush=True)
        return None
    items, truth, rows = [], [], []
    for ch in checks:
        vd = ch.get("verdict")
        if vd == "not a player":
            y = 1
        elif vd in ("wrong", "wrong team") or (vd == "correct" and ch.get("assigned")):
            y = 0                                     # a real player (named right, or the coach said who he really is)
        else:
            continue                                  # "correct" on an unnamed box is ambiguous -- left out
        d = det.get(ch.get("frame_file"))
        if d is None or not len(d["p"]):
            continue
        p = d["p"]
        j = int(np.argmin(np.hypot((p[:, 0] + p[:, 2]) / 2 - ch["px"], p[:, 3] - ch["py"])))
        if np.hypot((p[j, 0] + p[j, 2]) / 2 - ch["px"], p[j, 3] - ch["py"]) > 25:
            continue
        items.append((ch["frame_file"], p[j, :4]))
        truth.append(y)
        rows.append({"frame_file": ch["frame_file"], "px": ch["px"], "py": ch["py"], "verdict": vd,
                     "assigned": ch.get("assigned"), "true_name": ch.get("true_name"),
                     "kind": (ch.get("not_player_kind") or "not a player (kind not given)") if vd == "not a player" else "player"})
    n_np = sum(truth)
    print(f"Outfit check test: {len(items)} checked box(es) found in the saved detections -- {n_np} not a player, "
          f"{len(items) - n_np} real players", flush=True)
    if n_np < 5 or len(items) - n_np < 5:
        print("  too few of one kind to test", flush=True)
        return None
    t0 = _oc_time.time()
    sc = outfit_scores_for(items, base)
    ok = [k for k, s_ in enumerate(sc) if s_ is not None]
    s = np.array([sc[k] for k in ok], float)
    y = np.array([truth[k] for k in ok], int)
    print(f"  scored {len(ok)} box(es) in {_oc_time.time() - t0:.0f} s", flush=True)
    # CONFIRMED BUG (fixed; "scored 0 box(es)" then "TypeError: unsupported format string passed to NoneType"): when the
    # checked boxes' pictures aren't on disk (game folders deleted to free space), nothing can be scored -- say so and which
    # games, instead of failing on an empty result.
    _miss = [items[k][0] for k in range(len(items)) if sc[k] is None]
    if _miss:
        _lean = globals().get("vision_frame_leaned")
        _why = ["thinned by lean mode" if (_lean and _lean(os.path.join(base, f))) else "not on disk" for f in _miss]
        _by_game = pd.DataFrame({"g": [str(f).replace("\\", "/").split("/")[0] for f in _miss], "w": _why}).value_counts()
        print(f"  {len(_miss)} checked box(es) have no picture, by game folder: "
              + ", ".join(f"{g} {n} ({w})" for (g, w), n in _by_game.items()), flush=True)
    if int(y.sum()) < 5 or int((y == 0).sum()) < 5:
        print(f"  NOT TESTED: only {int(y.sum())} not-a-player and {int((y == 0).sum())} real-player box(es) could be scored "
              f"(needs 5+ of each). The pictures of the checked boxes are missing -- they come back when those games are "
              f"captured again; until then Player tracking does not use the outfit check (TRACK_OUTFIT_CHECK = \"auto\").",
              flush=True)
        return None
    # how well the score separates the two (AUC: 0.5 = no better than chance, 1.0 = perfect)
    pos, neg = s[y == 1], s[y == 0]
    auc = float(np.mean([(p_ > neg).mean() + 0.5 * (p_ == neg).mean() for p_ in pos])) if len(pos) and len(neg) else None
    best = None
    table = []
    for t in sorted(set(np.round(s, 3)), reverse=True):
        flag = s >= t
        if flag.sum() < 5:
            continue
        prec = float(y[flag].mean())
        rec = float(y[flag].sum() / max(y.sum(), 1))
        lost = int(((y == 0) & flag).sum())
        table.append((t, int(flag.sum()), prec, rec, lost))
        # CONFIRMED BUG (fixed; the check passed at a cutoff of 0.03 that set aside 8 of the 24 checked REAL players, then
        # tracking set aside 3,145 tracks -- most of one team): a cutoff must be right often enough AND cost at most
        # OUTFIT_MAX_PLAYERS_LOST (5%) of the real players. With mostly "not a player" checks, "right 90% of the time" alone
        # is met by flagging nearly everyone.
        if prec >= OUTFIT_MIN_PRECISION and lost <= OUTFIT_MAX_PLAYERS_LOST * max(1, int((y == 0).sum())):
            best = (t, prec, rec, lost, int(flag.sum()))          # keep going: the lowest score that still meets the bar
    n_pl = int((y == 0).sum())
    passed = bool(best and best[2] >= OUTFIT_MIN_RECALL and n_np >= OUTFIT_MIN_NONPLAYERS and n_pl >= OUTFIT_MIN_PLAYERS)
    res = {"model": OUTFIT_MODEL, "player_words": OUTFIT_PLAYER_WORDS, "other_words": OUTFIT_OTHER_WORDS,
           "boxes": len(ok), "not_players": int(y.sum()), "auc": round(auc, 3) if auc is not None else None,
           "threshold": (round(best[0], 3) if best else None), "precision": (round(best[1], 3) if best else None),
           "recall": (round(best[2], 3) if best else None), "players_lost": (best[3] if best else None),
           "passed": passed, "tested": pd.Timestamp.now().isoformat(timespec="seconds")}
    try:
        with open(OUTFIT_TEST_PATH, "w") as fh:
            json.dump(res, fh, indent=1)
        pd.DataFrame([dict(r, score=sc[k], not_a_player=truth[k]) for k, r in enumerate(rows)]).sort_values(
            "score", ascending=False).to_csv(os.path.join(TRACK_DIR, "outfit_check_scores.csv"), index=False)
    except Exception as _e:
        print(f"  (not saved: {type(_e).__name__}: {_e})", flush=True)
    if auc is not None:
        print(f"  how well the score tells them apart (AUC; 0.5 = coin flip, 1.0 = perfect): {auc:.2f}", flush=True)
    show = [r for r in table if r[2] >= 0.5][-8:] or table[:8]
    print("  score cutoff | boxes flagged | really not players | non-players caught | real players lost", flush=True)
    for t, nf, prec, rec, lost in show:
        print(f"     {t:5.3f}     |   {nf:5d}       |      {prec:5.0%}        |      {rec:5.0%}         |   {lost}", flush=True)
    # requested: how well each KIND of non-player is caught at the cutoff (referees and fans by their clothes; a bench player in
    # uniform looks like a player -- the court filter has to catch him, not this check)
    if best:
        _kinds = {}
        for k_ in ok:
            _kd = rows[k_]["kind"]
            _kinds.setdefault(_kd, [0, 0])
            _kinds[_kd][1] += 1
            _kinds[_kd][0] += int(sc[k_] >= best[0])
        print("  flagged at that cutoff, by kind: " + "; ".join(
            f"{kd} {a}/{n}" for kd, (a, n) in sorted(_kinds.items(), key=lambda kv: (kv[0] == "player", kv[0]))), flush=True)
    if passed:
        print(f"  PASSED: at a score of {best[0]:.2f}+ flagged boxes were really not players {best[1]:.0%} of the time, catching "
              f"{best[2]:.0%} of the non-players (costing {best[3]} real player box(es)). Player tracking will use it "
              f"(TRACK_OUTFIT_CHECK = \"auto\").", flush=True)
    else:
        why = (f"only {n_pl} checked real players (needs {OUTFIT_MIN_PLAYERS}) -- name more players in the checks"
               if best and n_pl < OUTFIT_MIN_PLAYERS else
               "no cutoff reached " + f"{OUTFIT_MIN_PRECISION:.0%} right while losing at most "
               f"{OUTFIT_MAX_PLAYERS_LOST:.0%} of the real players" if not best else
               f"it catches only {best[2]:.0%} of the non-players at {OUTFIT_MIN_PRECISION:.0%} right (needs "
               f"{OUTFIT_MIN_RECALL:.0%})" if best[2] < OUTFIT_MIN_RECALL else
               f"only {n_np} checked non-players (needs {OUTFIT_MIN_NONPLAYERS})")
        print(f"  NOT PASSED: {why}. Player tracking will NOT use the outfit check (TRACK_OUTFIT_CHECK = \"auto\"). "
              f"Every box's score is in outfit_check_scores.csv.", flush=True)
    return res


if RUN_OUTFIT_CHECK_TEST:
    try:
        outfit_check_result = outfit_check_test()
    except Exception as _e:
        if "RESTART THE KERNEL" in str(_e):
            raise
        print(f"Outfit check test skipped: {type(_e).__name__}: {_e}", flush=True)
