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
import os
import json
import time as _rc_time

for _k, _v in (("RUN_REID_CHECK_TEST", True), ("REID_MODELS", ["osnet", "dinov2"]), ("REID_OSNET_WEIGHTS", "osnet_x0_25_msmt17.pt"),
               ("REID_MIN_PRECISION", 0.8), ("REID_MIN_COVERAGE", 0.15), ("REID_MIN_QUESTIONS", 40)):
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
            ims.append(((np.asarray(Image.fromarray(np.ascontiguousarray(c)).resize((112, 224)), np.float32) / 255 - mean) / std)
                       .transpose(2, 0, 1))
        with torch.no_grad():
            h = model(pixel_values=torch.from_numpy(np.stack(ims))).last_hidden_state
            v = torch.cat([h[:, 0], h[:, 1:].mean(1)], 1).float().numpy()
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-8)
    globals()["_rc_dino_m"] = f
    return f


def reid_fingerprints(items, base, model="osnet"):
    """items: [(frame file, box)] -> [fingerprint or None]; cached on disk by model + frame + box; each picture read once."""
    import cv2
    cache = globals().get("_rc_cache_d")
    if cache is None:
        try:
            cache = pd.read_pickle(_RC_CACHE_PATH) if os.path.exists(_RC_CACHE_PATH) else {}
        except Exception:
            cache = {}
        globals()["_rc_cache_d"] = cache
    fn = _rc_osnet() if model == "osnet" else _rc_dinov2()
    keys = [f"{model}|{f}|{int(b[0])}|{int(b[1])}|{int(b[2])}|{int(b[3])}" for f, b in items]
    todo = {}
    for n, (k, (f, b)) in enumerate(zip(keys, items)):
        if k not in cache:
            todo.setdefault(f, []).append((n, b))
    done_new = 0
    for f, lst in todo.items():
        img = cv2.imread(os.path.join(base, f))
        if img is None:
            continue
        boxes = [[max(0, float(b[0])), max(0, float(b[1])), min(img.shape[1] - 1, float(b[2])), min(img.shape[0] - 1, float(b[3]))]
                 for _n, b in lst]
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
            pd.to_pickle(cache, _RC_CACHE_PATH)
    if todo:
        pd.to_pickle(cache, _RC_CACHE_PATH)
    return [cache.get(k) for k in keys]


def reid_match(q, gallery, candidates):
    """q: fingerprint; gallery: {name: [fingerprints]}; -> (best name, margin, scores) among candidates with references.
    A player's score = the mean of his 3 most similar reference pictures."""
    sc = {}
    for n in candidates:
        g = gallery.get(n)
        if not g:
            continue
        sims = np.sort(np.asarray([float(np.dot(q.astype(np.float32), v.astype(np.float32))) for v in g]))[::-1]
        sc[n] = float(np.mean(sims[:3]))
    if not sc:
        return None, 0.0, sc
    ranked = sorted(sc.items(), key=lambda kv: -kv[1])
    return ranked[0][0], (ranked[0][1] - ranked[1][1]) if len(ranked) > 1 else ranked[0][1], sc


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
                     "team": _fl.get(f"team_{ch.get('side')}")})
    n_ref = sum(r["half"] == "train" for r in rows)
    print(f"Re-ID check: {len(rows)} checked box(es) with a known player -- {n_ref} reference picture(s), "
          f"{len(rows) - n_ref} question(s)", flush=True)
    results = {}
    for model in REID_MODELS:
        t0 = _rc_time.time()
        try:
            fp = reid_fingerprints([(r["frame_file"], r["box"]) for r in rows], base, model)
        except Exception as e:
            print(f"  {model:7}: not tested ({type(e).__name__}: {e})", flush=True)
            continue
        out = []
        for g in sorted({r["game"] for r in rows}):
            ref = [(r, v) for r, v in zip(rows, fp) if r["game"] == g and r["half"] == "train" and v is not None]
            gallery = {}
            for r, v in ref:
                gallery.setdefault(r["true_name"], []).append(v)
            for r, v in zip(rows, fp):
                if r["game"] != g or r["half"] != "test" or v is None:
                    continue
                # candidates: the five on the floor for his team (else every player of that side seen in the references)
                cand = r["five"] or sorted({rr["true_name"] for rr, _v in ref
                                            if (rr["team"] == r["team"] if r["team"] is not None else rr["side"] == r["side"])})
                pick, margin, _sc = reid_match(v, gallery, cand)
                out.append({"model": model, "game": g, "clip_key": r["clip_key"], "frame_file": r["frame_file"], "side": r["side"],
                            "true_name": r["true_name"], "picked": pick, "right": pick == r["true_name"],
                            "margin": round(margin, 4), "true_has_references": r["true_name"] in gallery,
                            "candidates": len(cand)})
        if not out:
            print(f"  {model:7}: no questions could be answered", flush=True)
            continue
        df = pd.DataFrame(out)
        acc = float(df["right"].mean())
        best = None
        for m in sorted(set(df["margin"].round(3)), reverse=True):
            sel = df["margin"] >= m - 1e-9
            if sel.sum() >= 10 and df.loc[sel, "right"].mean() >= REID_MIN_PRECISION:
                best = (float(m), float(df.loc[sel, "right"].mean()), float(sel.mean()), int(sel.sum()))
        passed = bool(best and best[2] >= REID_MIN_COVERAGE and len(df) >= REID_MIN_QUESTIONS)
        results[model] = {"questions": len(df), "right_overall": round(acc, 3),
                          "chance": round(float(np.mean([1 / max(c, 1) for c in df["candidates"]])), 3),
                          "true_player_has_references": round(float(df["true_has_references"].mean()), 3),
                          "margin_cutoff": round(best[0], 4) if best else None, "precision": round(best[1], 3) if best else None,
                          "coverage": round(best[2], 3) if best else None, "named": best[3] if best else 0, "passed": passed,
                          "seconds": round(_rc_time.time() - t0)}
        results[model]["_df"] = df
        r_ = results[model]
        print(f"  {model:7}: {len(df)} questions -- right {acc:.0%} overall (guessing at random among the candidates: {r_['chance']:.0%}); "
              + (f"at margin >= {best[0]:.3f} right {best[1]:.0%} on {best[3]} box(es) ({best[2]:.0%} of them)"
                 if best else f"no margin reached {REID_MIN_PRECISION:.0%} right") + ("  -> PASSED" if passed else "  -> not passed"),
              flush=True)
    if not results:
        return None
    passing = [m for m, r in results.items() if r["passed"]]
    chosen = max(passing, key=lambda m: results[m]["coverage"]) if passing else None
    summary = {"models": {m: {k: v for k, v in r.items() if k != "_df"} for m, r in results.items()}, "chosen": chosen,
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
