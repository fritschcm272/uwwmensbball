# 50b_detector_compare.py -- code for the notebook section "Detector compare: old vs new player detector on a small sample".
# Runs inside the notebook via run_section("50b_detector_compare"); its settings are in that notebook cell.
#
# CONFIRMED CHANGE (requested: "if I stop it now, can I see how well the new model works?"). Player tracking detects every frame
# of every clip before it can name anyone (tens of thousands of frames -- hours on a CPU). This section tests the detectors on a
# SMALL sample instead: COMPARE_FRAMES pictures spread across the tracked clips, each run through the OLD detector setup and
# the NEW one (the current TRACK_DETECTOR / TRACK_DETECT_SIZE). For every picture it counts the people found on the court and
# draws both sets of boxes side by side (old = blue, new = orange). Nothing is saved to the tracking caches.
#
# Works on its own -- no need to run (or interrupt) the Player tracking cell: it borrows that section's detector functions
# straight from its file. It also REUSES detections already saved by earlier runs (the new detector's frames done so far, and the
# old detector's saved frames), so only frames nobody has detected yet are run.
import ast as _dc_ast
import time as _dc_time

# Settings of the Player tracking cell, with the notebook's current values as defaults -- so this cell works in a fresh kernel too
# (the Player tracking settings cell doesn't have to have been run).
for _k, _v in (("TRACK_DETECTOR", "yolo11m.pt"), ("TRACK_DETECT_SIZE", 1024), ("TRACK_DETECT_TILES", 3),
               ("TRACK_DETECT_UPSCALE", 2.0), ("TRACK_PERSON_CONF", 0.18)):
    globals().setdefault(_k, _v)
if "TRACK_DIR" not in globals() and "INPUT_DIR" in globals():
    TRACK_DIR = os.path.join(INPUT_DIR, "_tracking")

if "_trk_tiled_predict" not in globals():
    _dc_src = open(os.path.join(PARSER_LIB, "50_player_tracking.py"), encoding="utf-8").read()
    _dc_need = {"_trk_tiled_predict", "_trk_court_band", "_trk_iou", "_trk_court_H_lookup", "_trk_det_cache_path"}
    for _nd in _dc_ast.parse(_dc_src).body:
        if isinstance(_nd, _dc_ast.FunctionDef) and _nd.name in _dc_need:
            exec(compile(_dc_ast.Module([_nd], []), "50_player_tracking.py", "exec"), globals())

if "_trk_tiled_predict" not in globals():
    print("Detector compare: could not load the detector functions from 50_player_tracking.py.")
else:
    import cv2 as _dc_cv2
    from PIL import Image as _dc_Image, ImageDraw as _dc_Draw

    _dc_n = int(globals().get("COMPARE_FRAMES", 20))
    _dc_old = globals().get("COMPARE_OLD", ("yolo11s.pt", 768))
    _dc_new = globals().get("COMPARE_NEW", (TRACK_DETECTOR, TRACK_DETECT_SIZE))
    _dc_base = VISION_FRAMES_DIR if "VISION_FRAMES_DIR" in globals() else os.path.join(INPUT_DIR, "_vision_frames")
    _dc_pc = globals().get("play_calls")
    if not isinstance(_dc_pc, pd.DataFrame) or "track_files" not in _dc_pc.columns or _dc_pc["track_files"].isna().all():
        print("Detector compare: no clips with tracking frames in play_calls yet -- run Play calls (47) first.")
    else:
        _dc_rows = _dc_pc[_dc_pc["track_files"].notna()]
        _dc_pick = np.linspace(0, len(_dc_rows) - 1, min(_dc_n, len(_dc_rows))).round().astype(int)
        _dc_files = []
        for _i in _dc_pick:
            _fl = [f for f in str(_dc_rows.iloc[int(_i)]["track_files"]).split(";") if f]
            if _fl and os.path.exists(os.path.join(_dc_base, _fl[len(_fl) // 2])):
                _dc_files.append(_fl[len(_fl) // 2])
        _dc_files = list(dict.fromkeys(_dc_files))
        print(f"Detector compare: {len(_dc_files)} frame(s) spread across {len(_dc_rows)} tracked clips; "
              f"OLD = {_dc_old[0]} at {_dc_old[1]}, NEW = {_dc_new[0]} at {_dc_new[1]} "
              f"({TRACK_DETECT_TILES} tiles, upscale {TRACK_DETECT_UPSCALE:g} for both).", flush=True)
        _dc_H = _trk_court_H_lookup(_dc_base)
        _dc_out = os.path.join(TRACK_DIR, "detector_compare")
        os.makedirs(_dc_out, exist_ok=True)

        def _dc_run(cfg):
            """-> (boxes per frame as [(box, conf, class, None)], seconds per NEWLY detected frame, frames reused from the cache)"""
            saved = (globals().get("TRACK_DETECTOR"), globals().get("TRACK_DETECT_SIZE"))
            globals()["TRACK_DETECTOR"], globals()["TRACK_DETECT_SIZE"] = cfg
            try:
                cpath = _trk_det_cache_path()
                cache = pd.read_pickle(cpath) if os.path.exists(cpath) else {}
                out, todo_ = {}, []
                for f in _dc_files:
                    d_ = cache.get(f)
                    if d_ is not None:
                        out[f] = [(np.asarray(r[:4], float), float(r[4]), 0, None) for r in d_["p"] if float(r[4]) >= TRACK_PERSON_CONF]
                    else:
                        todo_.append(f)
                secs = 0.0
                if todo_:
                    from ultralytics import YOLO
                    model = YOLO(cfg[0])
                    t0 = _dc_time.time()
                    res = _trk_tiled_predict(model, [os.path.join(_dc_base, f) for f in todo_], _dc_H, [0], TRACK_PERSON_CONF)
                    secs = (_dc_time.time() - t0) / len(todo_)
                    out.update(dict(zip(todo_, res)))
                return [out[f] for f in _dc_files], secs, len(_dc_files) - len(todo_)
            finally:
                globals()["TRACK_DETECTOR"], globals()["TRACK_DETECT_SIZE"] = saved

        _dc_noH = set()

        def _dc_on_court(f, box):
            H = _dc_H(os.path.join(_dc_base, f))
            if H is None:
                _dc_noH.add(f)
                return False      # no court mapping for this picture: the real step can't place anyone either, so don't count
            v = np.asarray(H, np.float64) @ np.array([(box[0] + box[2]) / 2, box[3], 1.0])
            if abs(v[2]) < 1e-9:
                return False
            X, Y = v[0] / v[2], v[1] / v[2]
            # Same rules as the real tracking step (_trk_players): feet inside the court plus TRACK_COURT_MARGIN_FT
            # (and only TRACK_NEAR_MARGIN_FT on the camera side), a player-sized box, and no wide "seated" boxes along
            # the edges -- so bench players, coaches and the scorer's table are not counted.
            m = float(globals().get("TRACK_COURT_MARGIN_FT", 2.0))
            mn = float(globals().get("TRACK_NEAR_MARGIN_FT", 0.5))
            ez = float(globals().get("TRACK_EDGE_ZONE_FT", 3.0))
            fm = float(globals().get("TRACK_FAR_MARGIN_FT", -1.5))
            if not (-m < X < 94 + m and -mn < Y < 50 + fm):
                return False
            w_ = max(box[2] - box[0], 1e-6)
            h_ = max(box[3] - box[1], 1e-6)
            near_edge = X < ez or X > 94 - ez or Y < ez or Y > 50 - ez
            if near_edge and not (w_ / h_ < 0.8):
                return False
            return True

        print("  running the OLD detector...", flush=True)
        _dc_r_old, _dc_s_old, _dc_ro = _dc_run(_dc_old)
        print(f"    {_dc_ro} of {len(_dc_files)} frame(s) were already detected in the old detector's saved results")
        print("  running the NEW detector...", flush=True)
        _dc_r_new, _dc_s_new, _dc_rn = _dc_run(_dc_new)
        print(f"    {_dc_rn} of {len(_dc_files)} frame(s) were already detected in the new detector's saved results")
        rows_ = []
        for f, ro, rn in zip(_dc_files, _dc_r_old, _dc_r_new):
            bo = [b for (b, c, k, _kp) in ro if k == 0 and _dc_on_court(f, b)]
            bn = [b for (b, c, k, _kp) in rn if k == 0 and _dc_on_court(f, b)]
            rows_.append({"frame": f, "old_on_court": len(bo), "new_on_court": len(bn),
                          "old_all": sum(1 for x in ro if x[2] == 0), "new_all": sum(1 for x in rn if x[2] == 0)})
            img = _dc_Image.open(os.path.join(_dc_base, f)).convert("RGB")
            pair = []
            for boxes, col, tag in ((bo, (30, 144, 255), f"OLD {_dc_old[0]}: {len(bo)} on court"),
                                    (bn, (255, 140, 0), f"NEW {_dc_new[0]}: {len(bn)} on court")):
                im = img.copy()
                d = _dc_Draw.Draw(im)
                for b in boxes:
                    d.rectangle([float(x) for x in b], outline=col, width=3)
                    _H_ = _dc_H(os.path.join(_dc_base, f))
                    if _H_ is not None:
                        _v = np.asarray(_H_, np.float64) @ np.array([(b[0] + b[2]) / 2, b[3], 1.0])
                        d.text((float(b[0]), float(b[3]) + 2), f"{_v[0]/_v[2]:.0f},{_v[1]/_v[2]:.0f}", fill=col)
                d.rectangle([0, 0, im.width, 22], fill=(0, 0, 0))
                d.text((6, 5), tag, fill=(255, 255, 255))
                pair.append(im)
            sheet = _dc_Image.new("RGB", (pair[0].width * 2, pair[0].height))
            sheet.paste(pair[0], (0, 0))
            sheet.paste(pair[1], (pair[0].width, 0))
            sheet.save(os.path.join(_dc_out, f"compare_{len(rows_):02d}.jpg"), quality=88)
        if _dc_noH:
            print(f"  NOTE: {len(_dc_noH)} of {len(_dc_files)} picture(s) have no court mapping (homography), so nobody was counted in them; "
                  f"that is why a count can look low. Those pictures: {sorted(_dc_noH)[:5]}")
        res_df = pd.DataFrame(rows_)
        res_df.to_csv(os.path.join(_dc_out, "detector_compare.csv"), index=False)
        print(f"\nPeople found ON THE COURT per frame (10 players + 3 referees is the ideal ~13):")
        print(f"  OLD {_dc_old[0]}: average {res_df['old_on_court'].mean():.1f}   |   NEW {_dc_new[0]}: average {res_df['new_on_court'].mean():.1f}")
        print(f"  NEW found more in {int((res_df['new_on_court'] > res_df['old_on_court']).sum())} frame(s), fewer in "
              f"{int((res_df['new_on_court'] < res_df['old_on_court']).sum())}, the same in {int((res_df['new_on_court'] == res_df['old_on_court']).sum())}.")
        if _dc_s_old and _dc_s_new:
            print(f"  Speed on this computer: OLD {_dc_s_old:.1f} s per frame, NEW {_dc_s_new:.1f} s per frame "
                  f"-> 45,000 frames would take about {45000 * _dc_s_new / 3600:.0f} h (new) vs {45000 * _dc_s_old / 3600:.0f} h (old).")
        print(f"  Side-by-side pictures (old left, new right): {_dc_out}")
