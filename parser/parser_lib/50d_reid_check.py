# 50d_reid_check.py -- code for the notebook section "Re-ID check: does this look like the same player I already checked?"
# Runs inside the notebook via run_section("50d_reid_check"); its settings are in that notebook cell.
#
# CONFIRMED CHANGE (requested: "add that and make sure to add documentation so I can show you results"; idea from
# github.com/aviasoletechnologies/football-event-detection, which re-identifies players with OSNet). A re-identification
# ("re-ID") model turns a picture of a person into a fingerprint; two pictures of the SAME person get close fingerprints even
# in the same uniform (build, hair, shoes, sleeves, skin). Your player checks are labeled pictures of each player in each game,
# so they can be the reference pictures, and an unnamed track that clearly looks like one of the five on the floor gets his name.
#
# TEST FIRST (this cell). Within each game, your checked boxes are split in two by PLAY (the same split the jersey recognizer
# uses): one half are the REFERENCE pictures, the other half are the QUESTIONS. For every question box the model picks, among
# the five on the floor for that box's team, the player whose reference pictures look most like it. "Margin" = how much better
# the best player matched than the second best. The test finds the smallest margin at which its picks are right at least
# REID_MIN_PRECISION of the time and how many boxes that covers. Two models are compared:
#   osnet   -- OSNet, trained for person re-ID (needs the `boxmot` package; downloads ~1-10 MB of weights once)
#   dinov2  -- the general image model the tracker's "appearance" step already uses (facebook/dinov2-small)
# Results: printed, plus _tracking/reid_check_test.json (summary) and _tracking/reid_check_results.csv (every question box).
# Player tracking uses it only if the test PASSED (TRACK_REID_NAMES = "auto"). See parser_lib/README.md, "Tests to send back".
#
# CONFIRMED CHANGE (requested: "make those changes to the check and to tracking"; the first test was right 30% of the time,
# random 20%, all margins 0.01-0.08). Three changes, the same in this test and in Player tracking:
#   1. CROP (REID_CROPS): "upper" = head and jersey (the top ~2/3 of the box, as in the close-ups) -- the legs, the floor and
#      whoever stands behind him are mostly background that makes teammates look alike; "full" = the whole box (as before).
#      Both are tested; the better one is used.
#   2. SEVERAL PICTURES PER PLAYER (REID_TRACK_CROPS): a checked box is followed along its track in the last tracking run and
#      up to 3 of its biggest boxes in that clip are averaged into one fingerprint (one picture alone is often blurred,
#      turned away or half hidden).
#   3. FIVE BOXES, FIVE NAMES (REID_MATCH): a player is compared with the AVERAGE of his reference pictures ("prototype"; "top3"
#      = the old mean of his 3 closest), and the boxes of one team in one frame are named together -- the surest box first, and
#      a name already given to a box in that frame can't be given again (the test picked Yogi Oliff twice in clips 21 and 44).
import os
import json
import time as _rc_time

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



for _k, _v in (("RUN_REID_CHECK_TEST", True), ("REID_MODELS", ["osnet", "dinov2"]), ("REID_OSNET_WEIGHTS", "osnet_x0_25_msmt17.pt"),
               ("REID_MIN_PRECISION", 0.8), ("REID_MIN_COVERAGE", 0.15), ("REID_MIN_QUESTIONS", 40),
               ("REID_CROPS", ["upper", "full"]), ("REID_MATCH", "prototype"), ("REID_TRACK_CROPS", 3)):
    globals().setdefault(_k, _v)
if "TRACK_DIR" not in globals() and "INPUT_DIR" in globals():
    TRACK_DIR = os.path.join(INPUT_DIR, "_tracking")
REID_TEST_PATH = os.path.join(TRACK_DIR, "reid_check_test.json")
_RC_CACHE_PATH = os.path.join(TRACK_DIR, "reid_fingerprints.pkl")


def _rc_osnet():
    """OSNet through boxmot (several boxmot versions keep it in different places). -> callable(img_bgr, boxes) -> (N, d)."""
    m = globals().get("_rc_osnet_m")
    if m is not None:
        return m
    from pathlib import Path
    Backend = None
    for mod in ("boxmot.reid.core.auto_backend", "boxmot.appearance.reid.auto_backend", "boxmot.appearance.reid_auto_backend"):
        try:
            Backend = __import__(mod, fromlist=["ReidAutoBackend"]).ReidAutoBackend
            break
        except Exception:
            continue
    if Backend is None:
        import importlib
        if importlib.util.find_spec("boxmot") is None:
            raise ImportError("boxmot is not installed -- run  %pip install boxmot  in a cell, restart the kernel, run again "
                              "(or set REID_MODELS = [\"dinov2\"] to test only the model you already have)")
        raise ImportError("boxmot is installed but its re-ID part wasn't found (unexpected boxmot version)")
    import torch
    be = Backend(weights=Path(REID_OSNET_WEIGHTS), device=torch.device("cpu"), half=False)
    model = getattr(be, "model", be)

    def f(img_bgr, boxes):
        feats = model.get_features(np.asarray(boxes, np.float32), img_bgr)
        feats = feats.cpu().numpy() if hasattr(feats, "cpu") else np.asarray(feats)
        return feats / (np.linalg.norm(feats, axis=1, keepdims=True) + 1e-8)
    globals()["_rc_osnet_m"] = f
    return f


def _rc_dinov2():
    m = globals().get("_rc_dino_m")
    if m is not None:
        return m
    import torch
    from transformers import AutoModel
    from PIL import Image
    name = globals().get("TRACK_EMBED_MODEL", "facebook/dinov2-small")
    model = AutoModel.from_pretrained(name).eval()
    mean, std = np.array([0.485, 0.456, 0.406], np.float32), np.array([0.229, 0.224, 0.225], np.float32)

    def f(img_bgr, boxes):
        ims = []
        for b in boxes:
            x1, y1, x2, y2 = [int(v) for v in b[:4]]
            c = img_bgr[max(y1, 0):max(y2, y1 + 1), max(x1, 0):max(x2, x1 + 1)][:, :, ::-1]
            # the whole box is tall (1:2); a head-and-jersey crop is closer to 4:5 -- both sides multiples of the model's 14 px
            _sz = (112, 224) if (y2 - y1) > 1.6 * max(x2 - x1, 1) else (112, 140)
            ims.append(((np.asarray(Image.fromarray(np.ascontiguousarray(c)).resize(_sz), np.float32) / 255 - mean) / std)
                       .transpose(2, 0, 1))
        out_ = [None] * len(ims)
        for shp in {im_.shape for im_ in ims}:
            idx = [n_ for n_, im_ in enumerate(ims) if im_.shape == shp]
            with torch.no_grad():
                h = model(pixel_values=torch.from_numpy(np.stack([ims[n_] for n_ in idx]))).last_hidden_state
                v = torch.cat([h[:, 0], h[:, 1:].mean(1)], 1).float().numpy()
            for n_, vv in zip(idx, v):
                out_[n_] = vv
        v = np.stack(out_)
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-8)
    globals()["_rc_dino_m"] = f
    return f


def _rc_crop_box(b, crop="full"):
    """The part of a player's box that is fingerprinted: "upper" = head and jersey (the close-up's crop), "full" = all of it."""
    x1, y1, x2, y2 = [float(v) for v in b[:4]]
    if crop != "upper":
        return [x1, y1, x2, y2]
    w, h = x2 - x1, y2 - y1
    return [x1 - 0.12 * w, y1 - 0.04 * h, x2 + 0.12 * w, y1 + 0.62 * h]


def reid_fingerprints(items, base, model="osnet", crop="full"):
    """items: [(frame file, box)] -> [fingerprint or None]; cached on disk by model + crop + frame + box; each picture read
    once. crop = "full" (the whole box) or "upper" (head and jersey)."""
    import cv2
    cache = globals().get("_rc_cache_d")
    if cache is None:
        try:
            cache = _safe_read_pickle(_RC_CACHE_PATH) if os.path.exists(_RC_CACHE_PATH) else {}
        except Exception:
            cache = {}
        globals()["_rc_cache_d"] = cache
    fn = _rc_osnet() if model == "osnet" else _rc_dinov2()
    keys = [f"{model}{'' if crop == 'full' else '@' + crop}|{f}|{int(b[0])}|{int(b[1])}|{int(b[2])}|{int(b[3])}" for f, b in items]
    todo = {}
    for n, (k, (f, b)) in enumerate(zip(keys, items)):
        if k not in cache:
            todo.setdefault(f, []).append((n, b))
    done_new = 0
    for f, lst in todo.items():
        img = cv2.imread(os.path.join(base, f))
        if img is None:
            continue
        boxes = [[max(0, float(c_[0])), max(0, float(c_[1])), min(img.shape[1] - 1, float(c_[2])), min(img.shape[0] - 1, float(c_[3]))]
                 for _n, b in lst for c_ in [_rc_crop_box(b, crop)]]
        ok = [k for k, b in enumerate(boxes) if b[2] - b[0] >= 6 and b[3] - b[1] >= 12]
        if not ok:
            continue
        try:
            feats = fn(img, [boxes[k] for k in ok])
        except Exception as e:
            if "not installed" in str(e) or "wasn't found" in str(e):
                raise
            continue
        for k, v in zip(ok, feats):
            cache[keys[lst[k][0]]] = np.asarray(v, np.float16)
        done_new += len(ok)
        if done_new and done_new % 2000 < len(ok):
            _safe_to_pickle(cache, _RC_CACHE_PATH)
    if todo:
        _safe_to_pickle(cache, _RC_CACHE_PATH)
    return [cache.get(k) for k in keys]


def reid_match(q, gallery, candidates):
    """q: fingerprint; gallery: {name: [fingerprints]}; -> (best name, margin, scores) among candidates with references.
    REID_MATCH = "prototype": a player's score = how close q is to the AVERAGE of his reference pictures (steadier with few
    pictures); "top3": the mean of his 3 most similar reference pictures (the first version)."""
    sc = {}
    q = np.asarray(q, np.float32)
    q = q / (np.linalg.norm(q) + 1e-8)
    for n in candidates:
        g = gallery.get(n)
        if not g:
            continue
        G = np.asarray([np.asarray(v, np.float32) for v in g])
        if str(globals().get("REID_MATCH", "prototype")) == "top3":
            sims = np.sort(G @ q)[::-1]
            sc[n] = float(np.mean(sims[:3]))
        else:
            pr = G.mean(0)
            sc[n] = float(np.dot(q, pr / (np.linalg.norm(pr) + 1e-8)))
    if not sc:
        return None, 0.0, sc
    ranked = sorted(sc.items(), key=lambda kv: -kv[1])
    return ranked[0][0], (ranked[0][1] - ranked[1][1]) if len(ranked) > 1 else ranked[0][1], sc


def reid_assign(entries):
    """Name several boxes / tracks together. entries: {id: (scores {name: score}, ids it can't share a name with)}.
    The surest one (biggest lead of its best name over its second) is named first; each next one gets its best name that no
    conflicting one already has. -> {id: (name, margin)}: margin = how far that name beats the next name still open to it."""
    def lead(sc):
        v = sorted(sc.values(), reverse=True)
        return (v[0] - v[1]) if len(v) > 1 else (v[0] if v else 0.0)
    out = {}
    for i_ in sorted(entries, key=lambda i_: -lead(entries[i_][0])):
        sc, conflicts = entries[i_]
        taken = {out[c][0] for c in conflicts if c in out}
        open_ = sorted(((v, n) for n, v in sc.items() if n not in taken), reverse=True)
        if not open_:
            continue
        if len(open_) > 1:
            m = open_[0][0] - open_[1][0]
        else:                                     # the last name open: trusted only if it was his best name anyway
            m = lead(sc) if open_[0][1] == max(sc, key=sc.get) else 0.0
        out[i_] = (open_[0][1], float(m))
    return out


def _rc_track_items(ch, tracks_by_clip, files_by_clip, det, n):
    """Up to n (frame file, box) pictures of the checked player: his box in the checked frame plus his biggest boxes elsewhere in
    the clip, followed along the matching track of the last tracking run (requested: several pictures per player)."""
    rows = tracks_by_clip.get(ch.get("clip_key")) or []
    files = files_by_clip.get(ch.get("clip_key")) or []
    t0 = int(pd.to_numeric(ch.get("t"), errors="coerce")) if pd.notna(pd.to_numeric(ch.get("t"), errors="coerce")) else None
    if t0 is None or not rows or not files:
        return []
    best = None
    for path in rows:
        for e in path:
            if int(e[0]) == t0 and len(e) >= 6:
                d_ = float(np.hypot(float(e[4]) - float(ch["px"]), float(e[5]) - float(ch["py"])))
                if d_ <= 25 and (best is None or d_ < best[0]):
                    best = (d_, path)
    if best is None:
        return []
    picks, used = [], []
    for e in sorted(best[1], key=lambda e: -float(e[3])):
        t = int(e[0])
        if t == t0 or t >= len(files) or any(abs(t - u) < 2 for u in used + [t0]):
            continue
        d = det.get(files[t])
        if d is None or not len(d["p"]):
            continue
        p = d["p"]
        j = int(np.argmin(np.hypot((p[:, 0] + p[:, 2]) / 2 - float(e[4]), p[:, 3] - float(e[5]))))
        if np.hypot((p[j, 0] + p[j, 2]) / 2 - float(e[4]), p[j, 3] - float(e[5])) > 25:
            continue
        if "_jr_hidden" in globals() and _jr_hidden(p, j):
            continue
        picks.append((files[t], p[j, :4]))
        used.append(t)
        if len(picks) >= n - 1:
            break
    return picks


def _rc_five_lookup():
    """clip key -> {"offense": [five], "defense": [five]} from play_calls (empty when the lineup isn't known)."""
    out = {}
    pcs = globals().get("play_calls")
    if not isinstance(pcs, pd.DataFrame) or pcs.empty:
        return out
    for _, r in pcs.iterrows():
        key = f"{r.get('game_date')}|{r.get('clip_number')}|{r.get('synergy_string')}"
        five = lambda v: [p.strip() for p in v.split(",") if p.strip()] if isinstance(v, str) else []
        out[key] = {"offense": five(r.get("offense_lineup")), "defense": five(r.get("defense_lineup")),
                    "team_offense": r.get("offense_team"), "team_defense": r.get("defense_team")}
    return out


def reid_check_test():
    base = VISION_FRAMES_DIR if "VISION_FRAMES_DIR" in globals() else os.path.join(INPUT_DIR, "_vision_frames")
    checks = coach_checks_all()[0] if "coach_checks_all" in globals() else []
    det = _jr_det_cache() if "_jr_det_cache" in globals() else {}
    if not checks or not det:
        print("Re-ID check: needs the saved player checks and the saved detections.", flush=True)
        return None
    fives = _rc_five_lookup()
    # the last tracking run's tracks (this cell runs before Player tracking: in a fresh run they come from the saved table)
    _pt = globals().get("player_tracks")
    if not isinstance(_pt, pd.DataFrame) or _pt.empty:
        _ptp = os.path.join(globals().get("APP_DATA_DIR") or globals().get("OUTPUT_DIR") or ".", "uww_player_tracks.csv")
        _pt = pd.read_csv(_ptp, usecols=["clip_key", "path"], low_memory=False) if os.path.exists(_ptp) else pd.DataFrame()
    tracks_by_clip = {}
    for ck_, pth_ in zip(_pt.get("clip_key", []), _pt.get("path", [])):
        try:
            tracks_by_clip.setdefault(str(ck_), []).append(json.loads(pth_))
        except Exception:
            continue
    files_by_clip = {}
    _pcs = globals().get("play_calls")
    if isinstance(_pcs, pd.DataFrame) and "track_files" in _pcs.columns:
        for _, r_ in _pcs.iterrows():
            if isinstance(r_.get("track_files"), str):
                files_by_clip[f"{r_.get('game_date')}|{r_.get('clip_number')}|{r_.get('synergy_string')}"] = \
                    [f for f in r_["track_files"].split(";") if f]
    n_more = int(globals().get("REID_TRACK_CROPS", 3))
    rows = []
    for ch in checks:
        if ch.get("verdict") not in ("correct", "wrong") or not ch.get("true_name"):
            continue
        d = det.get(ch.get("frame_file"))
        if d is None or not len(d["p"]):
            continue
        p = d["p"]
        j = int(np.argmin(np.hypot((p[:, 0] + p[:, 2]) / 2 - ch["px"], p[:, 3] - ch["py"])))
        if np.hypot((p[j, 0] + p[j, 2]) / 2 - ch["px"], p[j, 3] - ch["py"]) > 25:
            continue
        if "_jr_hidden" in globals() and _jr_hidden(p, j):
            continue                                  # half hidden behind someone: not a fair picture of him
        box = p[j, :4]
        fname = _jr_name(ch["frame_file"], box) if "_jr_name" in globals() else ch["frame_file"]
        half = _jr_coach_half(fname) if "_jr_coach_half" in globals() else ("train" if hash(ch["clip_key"]) % 2 else "test")
        _fl = fives.get(ch.get("clip_key"), {}) or {}
        rows.append({"game": ch.get("game"), "clip_key": ch.get("clip_key"), "side": ch.get("side"), "frame_file": ch["frame_file"],
                     "box": box, "true_name": ch["true_name"], "half": half, "five": _fl.get(ch.get("side"), []),
                     "team": _fl.get(f"team_{ch.get('side')}"),
                     "more": _rc_track_items(ch, tracks_by_clip, files_by_clip, det, n_more) if n_more > 1 else []})
    n_ref = sum(r["half"] == "train" for r in rows)
    _n_more = sum(1 for r in rows if r["more"])
    print(f"Re-ID check: {len(rows)} checked box(es) with a known player -- {n_ref} reference picture(s), "
          f"{len(rows) - n_ref} question(s); {_n_more} followed along their track for up to {n_more} pictures each", flush=True)
    results = {}
    _crops = [c for c in (REID_CROPS if isinstance(REID_CROPS, (list, tuple)) else [REID_CROPS]) if c in ("upper", "full")] or ["full"]
    for model, crop in [(m_, c_) for m_ in REID_MODELS for c_ in _crops]:
        t0 = _rc_time.time()
        combo = f"{model} {crop}"
        try:
            items, owner = [], []
            for n_, r in enumerate(rows):
                for f_, b_ in [(r["frame_file"], r["box"])] + list(r["more"]):
                    items.append((f_, b_))
                    owner.append(n_)
            raw = reid_fingerprints(items, base, model, crop)
        except Exception as e:
            print(f"  {combo:13}: not tested ({type(e).__name__}: {e})", flush=True)
            if "not installed" in str(e) or "wasn't found" in str(e):
                continue
            continue
        _acc = {}
        for n_, v_ in zip(owner, raw):
            if v_ is not None:
                _acc.setdefault(n_, []).append(np.asarray(v_, np.float32) / (np.linalg.norm(np.asarray(v_, np.float32)) + 1e-8))
        fp = [(lambda m_: m_ / (np.linalg.norm(m_) + 1e-8))(np.mean(_acc[n_], 0)) if n_ in _acc else None for n_ in range(len(rows))]
        out = []
        for g in sorted({r["game"] for r in rows}):
            ref = [(r, v) for r, v in zip(rows, fp) if r["game"] == g and r["half"] == "train" and v is not None]
            gallery = {}
            for r, v in ref:
                gallery.setdefault(r["true_name"], []).append(v)
            qs = []
            for n_, (r, v) in enumerate(zip(rows, fp)):
                if r["game"] != g or r["half"] != "test" or v is None:
                    continue
                # candidates: the five on the floor for his team (else every player of that side seen in the references)
                cand = r["five"] or sorted({rr["true_name"] for rr, _v in ref
                                            if (rr["team"] == r["team"] if r["team"] is not None else rr["side"] == r["side"])})
                _p, _m, sc = reid_match(v, gallery, cand)
                qs.append((n_, r, cand, sc))
            # boxes of one team in one frame are named together: no name twice in a frame
            ent = {n_: (sc, {m_ for m_, rr, _c, _s in qs if m_ != n_ and rr["frame_file"] == r["frame_file"]
                             and rr["side"] == r["side"]}) for n_, r, cand, sc in qs}
            got = reid_assign(ent)
            for n_, r, cand, sc in qs:
                pick, margin = got.get(n_, (None, 0.0))
                out.append({"model": model, "crop": crop, "game": g, "clip_key": r["clip_key"], "frame_file": r["frame_file"],
                            "side": r["side"], "true_name": r["true_name"], "picked": pick, "right": pick == r["true_name"],
                            "margin": round(margin, 4), "true_has_references": r["true_name"] in gallery,
                            "candidates": len(cand), "pictures": 1 + len(r["more"])})
        if not out:
            print(f"  {combo:13}: no questions could be answered", flush=True)
            continue
        df = pd.DataFrame(out)
        acc = float(df["right"].mean())
        best = None
        for m in sorted(set(df["margin"].round(3)), reverse=True):
            sel = df["margin"] >= m - 1e-9
            if sel.sum() >= 10 and df.loc[sel, "right"].mean() >= REID_MIN_PRECISION:
                best = (float(m), float(df.loc[sel, "right"].mean()), float(sel.mean()), int(sel.sum()))
        passed = bool(best and best[2] >= REID_MIN_COVERAGE and len(df) >= REID_MIN_QUESTIONS)
        results[combo] = {"model": model, "crop": crop, "questions": len(df), "right_overall": round(acc, 3),
                          "chance": round(float(np.mean([1 / max(c, 1) for c in df["candidates"]])), 3),
                          "true_player_has_references": round(float(df["true_has_references"].mean()), 3),
                          "margin_cutoff": round(best[0], 4) if best else None, "precision": round(best[1], 3) if best else None,
                          "coverage": round(best[2], 3) if best else None, "named": best[3] if best else 0, "passed": passed,
                          "seconds": round(_rc_time.time() - t0)}
        results[combo]["_df"] = df
        r_ = results[combo]
        print(f"  {combo:13}: {len(df)} questions -- right {acc:.0%} overall (guessing at random among the candidates: {r_['chance']:.0%}); "
              + (f"at margin >= {best[0]:.3f} right {best[1]:.0%} on {best[3]} box(es) ({best[2]:.0%} of them)"
                 if best else f"no margin reached {REID_MIN_PRECISION:.0%} right") + ("  -> PASSED" if passed else "  -> not passed"),
              flush=True)
    if not results:
        return None
    passing = [m for m, r in results.items() if r["passed"]]
    chosen = max(passing, key=lambda m: results[m]["coverage"]) if passing else None
    summary = {"models": {m: {k: v for k, v in r.items() if k != "_df"} for m, r in results.items()}, "chosen": chosen,
               "match": str(globals().get("REID_MATCH", "prototype")),
               "passed": bool(chosen), "min_precision": REID_MIN_PRECISION, "min_coverage": REID_MIN_COVERAGE,
               "reference_pictures": n_ref, "tested": pd.Timestamp.now().isoformat(timespec="seconds")}
    try:
        with open(REID_TEST_PATH, "w") as fh:
            json.dump(summary, fh, indent=1)
        pd.concat([r["_df"] for r in results.values()]).to_csv(os.path.join(TRACK_DIR, "reid_check_results.csv"), index=False)
    except Exception as e:
        print(f"  (not saved: {type(e).__name__}: {e})", flush=True)
    print(("  CHOSEN: " + chosen + " -- Player tracking will name unnamed tracks that clearly match your checked players "
           "(TRACK_REID_NAMES = \"auto\").") if chosen else
          "  NOT PASSED: Player tracking will not use re-ID names. Send me reid_check_test.json and reid_check_results.csv.",
          flush=True)
    print(f"  saved: {REID_TEST_PATH} and reid_check_results.csv", flush=True)
    return summary


if RUN_REID_CHECK_TEST:
    try:
        reid_check_result = reid_check_test()
    except Exception as _e:
        print(f"Re-ID check skipped: {type(_e).__name__}: {_e}", flush=True)
