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

for _k, _v in (("OUTFIT_MODEL", "patrickjohncyh/fashion-clip"), ("OUTFIT_MIN_PRECISION", 0.9), ("OUTFIT_MIN_RECALL", 0.25),
               ("OUTFIT_MIN_NONPLAYERS", 20), ("RUN_OUTFIT_CHECK_TEST", True)):
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
        tf = model.get_text_features(**t)
        tf = tf / tf.norm(dim=-1, keepdim=True)
    globals()["_oc_loaded"] = (model, proc, tf)
    return globals()["_oc_loaded"]


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
    scale = float(model.logit_scale.exp())
    for s in range(0, len(idx), batch):
        part = idx[s:s + batch]
        ims = [Image.fromarray(crops_bgr[k][:, :, ::-1].copy()) for k in part]
        with torch.no_grad():
            px = proc(images=ims, return_tensors="pt")
            f = model.get_image_features(**px)
            f = f / f.norm(dim=-1, keepdim=True)
            pr = (scale * f @ tf.T).softmax(dim=-1)
        for k, row in zip(part, pr):
            out[k] = float(row[n_pl:].sum())
    return out


def _oc_cache():
    c = globals().get("_oc_cache_d")
    if c is None:
        try:
            c = pd.read_pickle(_OC_CACHE_PATH) if os.path.exists(_OC_CACHE_PATH) else {}
            if c.get("_words") != (OUTFIT_MODEL, tuple(OUTFIT_PLAYER_WORDS), tuple(OUTFIT_OTHER_WORDS)):
                c = {}
        except Exception:
            c = {}
        c["_words"] = (OUTFIT_MODEL, tuple(OUTFIT_PLAYER_WORDS), tuple(OUTFIT_OTHER_WORDS))
        globals()["_oc_cache_d"] = c
    return c


def _oc_save_cache():
    try:
        pd.to_pickle(globals().get("_oc_cache_d", {}), _OC_CACHE_PATH)
    except Exception:
        pass


def outfit_scores_for(items, base):
    """items: [(frame file, box)] -> [score or None]. Scores are cached on disk by frame + box, so reruns are fast; each
    picture is read once."""
    import cv2
    cache = _oc_cache()
    keys = [f"{f}|{int(b[0])}|{int(b[1])}|{int(b[2])}|{int(b[3])}" for f, b in items]
    todo = {}
    for n, (k, (f, b)) in enumerate(zip(keys, items)):
        if k not in cache:
            todo.setdefault(f, []).append((n, b))
    if todo:
        crops, where = [], []
        for f, lst in todo.items():
            img = cv2.imread(os.path.join(base, f))
            for n, b in lst:
                crops.append(_oc_crop(img, b) if img is not None else None)
                where.append(n)
            if len(crops) >= 256:
                for n, s_ in zip(where, _oc_scores(crops)):
                    cache[keys[n]] = s_
                crops, where = [], []
        if crops:
            for n, s_ in zip(where, _oc_scores(crops)):
                cache[keys[n]] = s_
        _oc_save_cache()
    return [cache.get(k) for k in keys]


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
                     "assigned": ch.get("assigned"), "true_name": ch.get("true_name")})
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
        if prec >= OUTFIT_MIN_PRECISION:
            best = (t, prec, rec, lost, int(flag.sum()))          # keep going: the lowest score that still meets the bar
    passed = bool(best and best[2] >= OUTFIT_MIN_RECALL and n_np >= OUTFIT_MIN_NONPLAYERS)
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
    print(f"  how well the score tells them apart (AUC; 0.5 = coin flip, 1.0 = perfect): {auc:.2f}", flush=True)
    show = [r for r in table if r[2] >= 0.5][-8:] or table[:8]
    print("  score cutoff | boxes flagged | really not players | non-players caught | real players lost", flush=True)
    for t, nf, prec, rec, lost in show:
        print(f"     {t:5.3f}     |   {nf:5d}       |      {prec:5.0%}        |      {rec:5.0%}         |   {lost}", flush=True)
    if passed:
        print(f"  PASSED: at a score of {best[0]:.2f}+ flagged boxes were really not players {best[1]:.0%} of the time, catching "
              f"{best[2]:.0%} of the non-players (costing {best[3]} real player box(es)). Player tracking will use it "
              f"(TRACK_OUTFIT_CHECK = \"auto\").", flush=True)
    else:
        why = ("no cutoff reached " + f"{OUTFIT_MIN_PRECISION:.0%} right" if not best else
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
