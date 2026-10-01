# 51_court_mapping.py -- code for the notebook section "Court mapping: every tracked player's position ON THE COURT, in feet ---------------------"
# Runs inside the notebook via run_section("51_court_mapping"); its settings are in that notebook cell.

# --- Court mapping: every tracked player's position ON THE COURT, in feet ----------------------------------------
# CONFIRMED CHANGE (requested: "start working on the court mapping, and add any newly created info into the
# scouting brief and application"). The tracking positions were in the camera's picture; this turns them into
# real court coordinates (94 x 50 ft), so corners, the lane, the arc and true distances mean something.
#
# How (the standard broadcast-sports approach, built to need as little clicking as possible):
#   1. CALIBRATE ONCE PER GYM. For a game with no calibration yet, this cell writes a small web page,
#      court_calibration/calibrate_<game>.html. Open it in any browser: for a few frames, click a court
#      landmark on the diagram (e.g. "left lane, baseline corner, near side"), then click the same spot in the
#      picture -- 4 or more landmarks per frame, ideally one frame of EACH basket. "Save" downloads
#      court_calibration_<game>.json; the parser picks it up from your Downloads folder (or court_calibration/).
#      The camera sits in the same spot every home game, so ONE calibration covers every game in that gym.
#   2. MAP EVERY FRAME AUTOMATICALLY. Each tracking frame is matched to the calibrated frames on the floor's
#      own fixed features (court lines, logos, lettering -- players are masked out because they move), which
#      gives how the camera has panned/zoomed since; combined with the calibration that places every pixel on
#      the court. A frame that can't be matched directly is chained through the frame before it in the clip.
#   3. CHECK IT. Every run reports: frames mapped, the calibration's own error in feet, how many mapped players
#      land inside the court, and (in the court-insights cell) whether shots Synergy calls 3s land outside the
#      arc -- an independent check that the mapping is right.
# Court coordinates: x = 0..94 along the court (x = 0 is the basket on the LEFT of the camera picture),
# y = 0..50 across it (y = 0 is the sideline NEAR the camera). For half-court diagrams every possession is
# turned so the offense attacks the same basket: hx = feet from the attacked baseline (0..47), hy = feet from
# the offense's LEFT sideline (0..50) -- the FastDraw view, basket at the top.
# Outputs: court_path / court_raw_path on uww_player_tracks, court_attack + court_mapped_frames on play_calls,
# uww_court_report.csv. Dimensions are NCAA men's (3-pt line 22'1.75", corner 21'8", basket 5'3" in).

import numpy as np
import shutil
import time
import json as _trk_json


_CM_BASKET_X, _CM_ARC, _CM_CORNER = 5.25, 22.146, 21.667
# Landmarks (x, y) in court feet -- left end; the right end mirrors x -> 94 - x. "near" = the camera's sideline.
_CM_LEFT = {
    "baseline x near sideline": (0, 0), "baseline x far sideline": (0, 50),
    "lane, baseline corner, near": (0, 19), "lane, baseline corner, far": (0, 31),
    "lane, free-throw corner, near": (19, 19), "lane, free-throw corner, far": (19, 31),
    "free-throw line, middle": (19, 25), "free-throw circle, top": (25, 25),
    "corner 3 at baseline, near": (0, 25 - _CM_CORNER), "corner 3 at baseline, far": (0, 25 + _CM_CORNER),
    "3-pt arc, top of key": (_CM_BASKET_X + _CM_ARC, 25),
}
COURT_LANDMARKS = {**{f"LEFT {k}": v for k, v in _CM_LEFT.items()},
                   **{f"RIGHT {k}": (94 - v[0], v[1]) for k, v in _CM_LEFT.items()},
                   "mid-court x near sideline": (47, 0), "mid-court x far sideline": (47, 50),
                   "center circle, near": (47, 19), "center circle, far": (47, 31), "center circle, middle": (47, 25)}
court_report = pd.DataFrame()
court_frames = {}


def _cm_progress(label, done, total, t0, every=None):
    """Progress line for the slow court-mapping steps (requested: "it's been running a long time and I don't
    know what is happening"). ~10 lines per slow step; quick steps print only their finishing line."""
    every = every or max(1, total // 10)
    el = time.time() - t0
    if done == total and el >= 1 or (done % every == 0 and el >= 5):
        left = el / max(done, 1) * (total - done)
        print(f"  [court]   {label}: {done:,} / {total:,} ({100 * done // max(total, 1)}%) -- "
              f"{el / 60:.1f} min so far, ~{left / 60:.1f} min left", flush=True)


def _cm_slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", str(s)).strip("_")


def _cm_arena(game_code):
    g = str(game_code or "")
    return g.split("@")[-1].strip() if "@" in g else g


def _cm_calibration_files():
    os.makedirs(COURT_CAL_DIR, exist_ok=True)
    if COURT_SEARCH_DOWNLOADS:
        dl = os.path.join(os.path.expanduser("~"), "Downloads")
        for f in glob.glob(os.path.join(dl, "court_calibration_*.json")):
            dst = os.path.join(COURT_CAL_DIR, os.path.basename(f))
            if not os.path.exists(dst) or os.path.getmtime(f) > os.path.getmtime(dst):
                shutil.copy2(f, dst)
    out = []
    for f in sorted(glob.glob(os.path.join(COURT_CAL_DIR, "court_calibration_*.json"))):
        try:
            with open(f) as fh:
                out.append(_trk_json.load(fh))
        except Exception as e:
            print(f"  [court] couldn't read {os.path.basename(f)}: {e}")
    return out


def _cm_write_tool(game_key, arena, frames, base):
    """The click-to-calibrate page for one game: its frames, a court diagram with every landmark."""
    import base64
    imgs = []
    for rel in frames:
        with open(os.path.join(base, rel), "rb") as fh:
            imgs.append({"file": rel, "src": "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode("ascii")})
    payload = _trk_json.dumps({"game": game_key, "arena": arena, "frames": imgs,
                               "landmarks": {k: list(v) for k, v in COURT_LANDMARKS.items()}})
    page = _CM_TOOL_HTML.replace("__PAYLOAD__", payload).replace("__SLUG__", _cm_slug(game_key))
    path = os.path.join(COURT_CAL_DIR, f"calibrate_{_cm_slug(game_key)}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return path


_CM_TOOL_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>Court calibration</title>
<style>body{font-family:Arial,sans-serif;margin:12px;background:#fafafa}#wrap{display:flex;gap:14px;flex-wrap:wrap}
canvas{border:1px solid #999;cursor:crosshair;max-width:100%}.lm{cursor:pointer}.sel{fill:#d62728!important}
button{margin:2px;padding:5px 10px}#pts div{font-size:12px}.hint{color:#555;font-size:13px;max-width:900px}</style></head><body>
<h3>Court calibration -- <span id="gm"></span></h3>
<p class="hint">1) Click a landmark dot on the court diagram (it turns red). 2) Click that exact spot in the picture.
Do this for <b>4 or more</b> landmarks per frame, spread out (not all on one line). Calibrate at least one frame at
<b>each basket</b>; skip frames where you can't see 4 landmarks. Then press <b>Save calibration</b> and run the parser again
(it finds the file in your Downloads folder). "Near" = the sideline closest to the camera.</p>
<div id="wrap"><div><canvas id="cv"></canvas><div>
<button id="prev">&larr; Prev frame</button><span id="fi"></span><button id="next">Next frame &rarr;</button>
<button id="save" style="background:#4E2A84;color:#fff">Save calibration</button></div></div>
<div><svg id="court" width="470" height="250" style="background:#e8d3a9;border:1px solid #999"></svg>
<div id="sel" style="margin:6px 0;font-weight:bold"></div><div id="pts"></div></div></div>
<script>
const P = __PAYLOAD__;
document.getElementById('gm').textContent = P.game;
const S = 5, cv = document.getElementById('cv'), ctx = cv.getContext('2d');
const court = document.getElementById('court');
let fi = 0, sel = null; const img = new Image();
P.frames.forEach(f => f.points = []);
function drawCourt(){
  const L = (x1,y1,x2,y2) => `<line x1="${x1*S}" y1="${250-y1*S}" x2="${x2*S}" y2="${250-y2*S}" stroke="#fff" stroke-width="2"/>`;
  let s = L(0,0,94,0)+L(0,50,94,50)+L(0,0,0,50)+L(94,0,94,50)+L(47,0,47,50)
        + L(0,19,19,19)+L(0,31,19,31)+L(19,19,19,31)+L(94,19,75,19)+L(94,31,75,31)+L(75,19,75,31);
  s += `<circle cx="${47*S}" cy="${250-25*S}" r="${6*S}" fill="none" stroke="#fff" stroke-width="2"/>`;
  for (const [nm,[x,y]] of Object.entries(P.landmarks)) {
    s += `<circle class="lm" data-n="${nm}" cx="${x*S}" cy="${250-y*S}" r="6" fill="#1f77b4"><title>${nm}</title></circle>`;
  }
  court.innerHTML = s;
  court.querySelectorAll('.lm').forEach(c => c.onclick = () => { sel = c.dataset.n;
    court.querySelectorAll('.lm').forEach(d => d.classList.remove('sel')); c.classList.add('sel');
    document.getElementById('sel').textContent = 'Now click in the picture: ' + sel; });
}
function load(){ img.onload = () => { cv.width = img.naturalWidth; cv.height = img.naturalHeight; draw(); }; img.src = P.frames[fi].src;
  document.getElementById('fi').textContent = ` frame ${fi+1} / ${P.frames.length} `; }
function draw(){ ctx.drawImage(img,0,0); ctx.font='bold 13px Arial';
  P.frames[fi].points.forEach(p => { ctx.fillStyle='#d62728'; ctx.beginPath(); ctx.arc(p.px,p.py,5,0,6.3); ctx.fill();
    ctx.fillStyle='#ff0'; ctx.fillText(p.landmark.replace('lane, ','').slice(0,34), p.px+7, p.py-7); });
  document.getElementById('pts').innerHTML = P.frames.map((f,i) => `<div>Frame ${i+1}: ${f.points.length} point(s)${f.points.length>=4?' ✔':''}</div>`).join('')
    + P.frames[fi].points.map((p,j) => `<div>${p.landmark} <a href="#" onclick="del(${j});return false">remove</a></div>`).join(''); }
function del(j){ P.frames[fi].points.splice(j,1); draw(); }
cv.onclick = e => { if(!sel){ alert('Click a landmark on the court diagram first.'); return; }
  const r = cv.getBoundingClientRect(), sx = cv.width / r.width, sy = cv.height / r.height;
  const pts = P.frames[fi].points.filter(p => p.landmark !== sel);
  pts.push({landmark: sel, px: Math.round((e.clientX-r.left)*sx*10)/10, py: Math.round((e.clientY-r.top)*sy*10)/10});
  P.frames[fi].points = pts; draw(); };
document.getElementById('prev').onclick = () => { fi = (fi + P.frames.length - 1) % P.frames.length; load(); };
document.getElementById('next').onclick = () => { fi = (fi + 1) % P.frames.length; load(); };
document.getElementById('save').onclick = () => {
  const out = {game: P.game, arena: P.arena, frames: P.frames.filter(f => f.points.length >= 4).map(f => ({file: f.file, points: f.points}))};
  if (!out.frames.length) { alert('No frame has 4+ points yet.'); return; }
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:'application/json'}));
  a.download = 'court_calibration___SLUG__.json'; a.click(); };
drawCourt(); load();
</script></body></html>"""


def _cm_detection_boxes(rel):
    det = globals().get("_cm_det_cache")
    if det is None:
        # the newest detections file (tiled or not) -- only used to mask players out of the floor features
        cands = sorted(glob.glob(os.path.join(TRACK_DIR, "detections_*.pkl")), key=os.path.getmtime)
        p = _trk_det_cache_path() if os.path.exists(_trk_det_cache_path()) else (cands[-1] if cands else "")
        det = globals()["_cm_det_cache"] = pd.read_pickle(p) if p and os.path.exists(p) else {}
    d = det.get(rel)
    return d["p"][:, :4] if d is not None and len(d["p"]) else np.zeros((0, 4))


def _cm_features(rel, base):
    """ORB features on the FLOOR only: the top of the picture (crowd, scoreboard) and every person are masked."""
    import cv2
    img = cv2.imread(os.path.join(base, rel), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None, None, None
    h, w = img.shape
    mask = np.full((h, w), 255, np.uint8)
    mask[: int(0.12 * h)] = 0
    for x1, y1, x2, y2 in _cm_detection_boxes(rel):
        mask[max(int(y1) - 6, 0):int(y2) + 6, max(int(x1) - 6, 0):int(x2) + 6] = 0
    orb = cv2.ORB_create(COURT_ORB_FEATURES)
    kp, des = orb.detectAndCompute(img, mask)
    return img.shape, np.float32([k.pt for k in kp]) if kp else np.zeros((0, 2), np.float32), des


def _cm_match(fa, fb):
    """Homography taking picture A to picture B from their floor features, and how many features agreed."""
    import cv2
    (_, pa, da), (_, pb, db) = fa, fb
    if da is None or db is None or len(pa) < 12 or len(pb) < 12:
        return None, 0
    knn = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [m for m, *n in knn if n and m.distance < 0.75 * n[0].distance]
    if len(good) < 12:
        return None, 0
    H, inl = cv2.findHomography(pa[[m.queryIdx for m in good]], pb[[m.trainIdx for m in good]], cv2.RANSAC, 4.0)
    return (H, int(inl.sum())) if H is not None else (None, 0)


def _cm_apply(H, pts):
    import cv2
    if H is None or not len(pts):
        return np.zeros((0, 2))
    return cv2.perspectiveTransform(np.float32(pts).reshape(-1, 1, 2), np.asarray(H, np.float64)).reshape(-1, 2)


def _cm_plausible(H, rel):
    feet = [((x1 + x2) / 2, y2) for x1, y1, x2, y2 in _cm_detection_boxes(rel)]
    if len(feet) < 3:
        return True
    m = _cm_apply(H, feet)
    inside = ((m[:, 0] > -6) & (m[:, 0] < 100) & (m[:, 1] > -6) & (m[:, 1] < 56)).mean()
    return inside >= COURT_MIN_IN_BOUNDS


def court_mapping(pc, tracks):
    import cv2
    base = VISION_FRAMES_DIR
    rows = pc[pc["track_files"].map(lambda v: isinstance(v, str) and v != "")]
    if rows.empty:
        return tracks, pc, pd.DataFrame(), {}
    print(f"  [court] step 1: reading calibration files from {COURT_CAL_DIR}"
          + (" and your Downloads folder" if COURT_SEARCH_DOWNLOADS else "") + "...", flush=True)
    cals = _cm_calibration_files()
    print(f"  [court]   found {len(cals)} calibration file(s): "
          + (", ".join(f"{c.get('game')} ({len(c.get('frames', []))} frame(s))" for c in cals) or "none"), flush=True)
    # reference frames per ARENA (one calibration serves every game in that gym)
    refs_by_arena = {}
    for cal in cals:
        for fr in cal.get("frames", []):
            pts = [(p["px"], p["py"]) for p in fr["points"] if p["landmark"] in COURT_LANDMARKS]
            dst = [COURT_LANDMARKS[p["landmark"]] for p in fr["points"] if p["landmark"] in COURT_LANDMARKS]
            if len(pts) < 4:
                continue
            if not os.path.exists(os.path.join(base, fr["file"])):
                globals().setdefault("_cm_missing_frames", []).append(fr["file"])
                continue
            H, _ = cv2.findHomography(np.float32(pts), np.float32(dst), cv2.RANSAC if len(pts) > 4 else 0, 1.5)
            if H is None:
                continue
            err = float(np.mean(np.linalg.norm(_cm_apply(H, pts) - np.float32(dst), axis=1)))
            refs_by_arena.setdefault(str(cal.get("arena")), []).append(
                {"file": fr["file"], "H": H, "err": err, "feat": _cm_features(fr["file"], base)})
    _miss = globals().pop("_cm_missing_frames", [])
    if _miss:
        print(f"  [court]   {len(_miss)} calibrated frame(s) are no longer on disk (e.g. {_miss[0]}) -- that calibration "
              f"can't be used; if a gym has none left, a new calibration page is written below", flush=True)
    for a, rs in refs_by_arena.items():
        print(f"  [court]   gym '{a}': {len(rs)} usable calibrated frame(s), average click error "
              f"{np.mean([r['err'] for r in rs]):.2f} ft", flush=True)
    sig = _cm_slug(_trk_json.dumps(sorted((a, r["file"], round(r["err"], 3)) for a, rs in refs_by_arena.items() for r in rs)))[:120]
    cache_path = os.path.join(TRACK_DIR, "court_homographies.pkl")
    cache = pd.read_pickle(cache_path) if os.path.exists(cache_path) else {}
    # CONFIRMED BUG (fixed; coach: "only the Coe game needed a calibration -- why is it re-placing the Oshkosh @
    # Whitewater frames?"). One fingerprint covered EVERY gym's calibration, so adding Coe's threw away all saved
    # frames, including Whitewater's 16,500 whose calibration hadn't changed. Now each gym has its own fingerprint:
    # when a gym's calibration changes, only the games played in that gym are placed again.
    sig_by_arena = {a: _cm_slug(_trk_json.dumps(sorted((r["file"], round(r["err"], 3)) for r in rs)))[:120]
                    for a, rs in refs_by_arena.items()}
    old_by = cache.get("_sig_by_arena")
    if old_by is None:
        # saved before per-gym fingerprints: trust it only if the combined fingerprint still matches
        if cache.get("_sig") != sig:
            if len([k for k in cache if not str(k).startswith("_")]):
                print("  [court]   calibration changed since the last run -- every frame will be mapped again "
                      "(one time: saved results from now on are kept gym by gym)", flush=True)
            cache = {}
    else:
        _changed = sorted({a for a in sig_by_arena if old_by.get(a) != sig_by_arena[a]}
                          | {a for a in old_by if a not in sig_by_arena})
        if _changed:
            _games = rows[rows["game_code"].map(_cm_arena).isin(_changed)]
            _drop = {f for v in _games["track_files"].dropna() for f in str(v).split(";") if f}
            _n = sum(1 for f in _drop if f in cache)
            for f in _drop:
                cache.pop(f, None)
            print(f"  [court]   calibration changed for gym(s) {', '.join(repr(a) for a in _changed)} -- only "
                  f"{_games.groupby(['game_date', 'game_code']).ngroups} game(s) there are placed again "
                  f"({_n:,} saved frame(s) dropped); every other gym keeps its saved frames", flush=True)
    cache["_sig"], cache["_sig_by_arena"] = sig, sig_by_arena
    report, attack = [], {}
    last_ref = {}
    for (gd, gc), g in rows.groupby(["game_date", "game_code"], dropna=False):
        game_key, arena = f"{gd}|{gc}", _cm_arena(gc)
        refs = refs_by_arena.get(arena, [])
        clips = [(r["track_clip_key"], [f for f in r["track_files"].split(";") if f]) for _, r in g.iterrows()]
        if not refs:
            # no calibration for this gym yet -> write the click-to-calibrate page for this game
            pool = [fl[len(fl) // 2] for _, fl in clips if fl]
            pick = [pool[int(i)] for i in np.linspace(0, len(pool) - 1, min(COURT_REF_FRAMES, len(pool)))] if pool else []
            print(f"  [court] {game_key}: gym '{arena}' has no calibration yet -- writing the calibration page...", flush=True)
            tool = _cm_write_tool(game_key, arena, pick, base) if pick else None
            report.append({"game": game_key, "arena": arena, "calibrated": False, "frames": sum(len(fl) for _, fl in clips),
                           "mapped_pct": 0, "calibration_error_ft": None, "calibration_page": tool})
            continue
        n_all = n_map = n_chain = n_new = 0
        total = sum(len(fl) for _, fl in clips)
        n_cached = sum(1 for _, fl in clips for rel in fl if rel in cache)
        print(f"  [court] step 2: {game_key}: placing {total:,} frame(s) on the court ({n_cached:,} already done in an "
              f"earlier run, {total - n_cached:,} to match against {len(refs)} calibrated frame(s))...", flush=True)
        _t0 = time.time()
        for _, fl in clips:
            prev_rel, prev_feat = None, None
            for rel in fl:
                n_all += 1
                if rel not in cache:
                    n_new += 1
                    _cm_progress(f"frames matched ({n_map:,} on the court so far)", n_new, total - n_cached, _t0)
                    if n_new % 300 == 0:
                        pd.to_pickle(cache, cache_path)   # save progress: an interrupted run keeps its work
                if rel in cache:
                    if cache[rel] is not None:
                        n_map += 1
                    prev_rel = rel if cache[rel] is not None else prev_rel
                    prev_feat = None
                    continue
                feat = _cm_features(rel, base)
                best = (None, 0)
                # Speed: try the calibrated frame that matched the last frame first; a strong match there
                # (3x the minimum) is good enough, so the other calibrated frames are skipped.
                for ref in sorted(refs, key=lambda r_: r_ is not last_ref.get(game_key)):
                    Hfr, n = _cm_match(feat, ref["feat"])
                    if Hfr is not None and n > best[1]:
                        best = (ref["H"] @ Hfr, n)
                        best_ref = ref
                    if best[1] >= 3 * COURT_MIN_INLIERS:
                        break
                if best[1]:
                    last_ref[game_key] = best_ref
                H = best[0] if best[1] >= COURT_MIN_INLIERS and _cm_plausible(best[0], rel) else None
                if H is None and prev_rel is not None and cache.get(prev_rel) is not None:
                    pf = prev_feat or _cm_features(prev_rel, base)
                    Hfp, n = _cm_match(feat, pf)
                    if Hfp is not None and n >= COURT_MIN_INLIERS:
                        Hc = np.asarray(cache[prev_rel]) @ Hfp
                        if _cm_plausible(Hc, rel):
                            H = Hc
                            n_chain += 1
                cache[rel] = H.tolist() if H is not None else None
                if H is not None:
                    n_map += 1
                    prev_rel, prev_feat = rel, feat
        print(f"  [court]   {game_key}: {n_map:,} of {n_all:,} frame(s) on the court "
              f"({round(100 * n_map / max(n_all, 1))}%, {n_chain:,} of them via the frame before)", flush=True)
        errs = [r["err"] for r in refs]
        report.append({"game": game_key, "arena": arena, "calibrated": True, "frames": n_all,
                       "mapped_pct": round(100 * n_map / max(n_all, 1)), "mapped_by_chaining": n_chain,
                       "calibration_frames": len(refs), "calibration_error_ft": round(float(np.mean(errs)), 2),
                       "calibration_page": None})
    pd.to_pickle(cache, cache_path)

    # ---- every track point onto the court, then turned so the offense attacks the same basket ----
    files_of = {r["track_clip_key"]: [f for f in r["track_files"].split(";") if f] for _, r in rows.iterrows()}
    raw_paths, inb, tot = {}, 0, 0
    print(f"  [court] step 3: moving {len(tracks):,} player track(s) onto the court...", flush=True)
    _t0 = time.time()
    for _n, (idx, t) in enumerate(tracks.iterrows(), 1):
        _cm_progress("tracks placed", _n, len(tracks), _t0)
        fl = files_of.get(t["clip_key"], [])
        out = []
        for p in _trk_json.loads(t["path"]):
            if len(p) < 6 or int(p[0]) >= len(fl):
                continue
            H = cache.get(fl[int(p[0])])
            if H is None:
                continue
            Hm = np.asarray(H, np.float64)
            v = Hm @ np.array([p[4], p[5], 1.0])
            X, Y = v[0] / v[2], v[1] / v[2]
            out.append([int(p[0]), round(float(X), 2), round(float(Y), 2)])
            tot += 1
            inb += int(-3 < X < 97 and -3 < Y < 53)
        raw_paths[idx] = out
    tracks = tracks.copy()
    tracks["court_raw_path"] = [(_trk_json.dumps(raw_paths[i]) if raw_paths.get(i) else None) for i in tracks.index]
    # attack direction per clip: the end the players are at during the first 70% of the clip (review: clips run on
    # after the play, often with everyone heading the other way, so the END of the clip was the wrong half)
    for key, g in tracks.groupby("clip_key"):
        pts = [p for i in g.index for p in (raw_paths.get(i) or []) if p]
        if not pts:
            attack[key] = None
            continue
        n_fr = max(p[0] for p in pts) + 1
        xs = [p[1] for p in pts if p[0] < max(2, int(0.7 * n_fr))]
        attack[key] = ("right" if np.median(xs) > 47 else "left") if xs else None

    def _half(i):
        pts = raw_paths.get(i)
        a = attack.get(tracks.at[i, "clip_key"])
        if not pts or a is None:
            return None
        return _trk_json.dumps([[t, round(94 - X if a == "right" else X, 2), round(50 - Y if a == "right" else Y, 2)]
                                for t, X, Y in pts])
    print("  [court] step 4: turning every possession so the offense attacks the same basket...", flush=True)
    tracks["court_path"] = [_half(i) for i in tracks.index]
    pc = pc.copy()
    pc["court_attack"] = pc["track_clip_key"].map(attack)
    pc["court_mapped_frames"] = pc["track_files"].map(
        lambda v: sum(1 for f in v.split(";") if f and cache.get(f) is not None) if isinstance(v, str) else None)
    rep = pd.DataFrame(report)
    if not rep.empty:
        rep["players_on_court_pct"] = round(100 * inb / tot) if tot else None
    return tracks, pc, rep, cache


_cm_ran_now = False                           # the calibration stop only trusts a report made by THIS run
if RUN_COURT_MAPPING and isinstance(globals().get("player_tracks"), pd.DataFrame) and not player_tracks.empty:
    try:
        import cv2  # comes with ultralytics
        player_tracks, play_calls, court_report, court_frames = court_mapping(play_calls, player_tracks)
        _cm_ran_now = True
        # Tracking ran before these frames were on the court (a new game's first run): rerun it WITH the court
        # (off-court people dropped, players linked in feet, rim anchors), then place the new tracks on the court.
        if globals().get("_trk_court_frames_used") == 0 and any(v is not None for k, v in court_frames.items() if not str(k).startswith("_")) \
                and "_trk_run_all" in globals():
            print("  [court] tracking ran before the court mapping existed -- rerunning Player tracking with it now "
                  "(saved detections/colors/fingerprints are reused)...", flush=True)
            _trk_run_all()
            if isinstance(player_tracks, pd.DataFrame) and not player_tracks.empty:
                player_tracks, play_calls, court_report, court_frames = court_mapping(play_calls, player_tracks)
        for _r in court_report.to_dict("records"):
            if not _r["calibrated"]:
                print(f"  {_r['game']}: NOT CALIBRATED for gym '{_r['arena']}' -- open {_r['calibration_page']} in a browser, "
                      f"click 4+ landmarks on a few frames (one at each basket), press Save, rerun.")
            else:
                print(f"  {_r['game']}: {_r['mapped_pct']}% of {_r['frames']} frames on the court "
                      f"({_r.get('mapped_by_chaining', 0)} via the frame before); calibration error "
                      f"{_r['calibration_error_ft']} ft over {_r['calibration_frames']} frame(s); "
                      f"{_r.get('players_on_court_pct')}% of mapped players land on the court.")
    except Exception as _e:
        print("  " + "!" * 100)
        print(f"  COURT MAPPING NOT RUN: {type(_e).__name__}: {_e}")
        print("  " + "!" * 100)


class CourtCalibrationNeeded(Exception):
    """Raised to STOP the notebook when a gym needs its one-time court calibration."""


# CONFIRMED CHANGE (requested: "parser_nb should stop when a court configuration needs to be done"). The calibration
# page was written and the run carried on for hours without that game on the court, with a one-line note that was easy
# to miss. Now the notebook stops here (an error halts "Run All"), opens the page, and says exactly what to do.
# Raised OUTSIDE the section's try/except above so it can't be swallowed. COURT_STOP_FOR_CALIBRATION = False carries on.
_cm_need = []
if _cm_ran_now and isinstance(globals().get("court_report"), pd.DataFrame) and not court_report.empty \
        and "calibrated" in court_report.columns:
    _cm_need = [r for r in court_report.to_dict("records") if not r.get("calibrated") and r.get("calibration_page")]
if _cm_need and globals().get("COURT_STOP_FOR_CALIBRATION", True):
    if globals().get("COURT_OPEN_CALIBRATION_PAGE", True):
        import webbrowser
        for _r in _cm_need:
            try:
                webbrowser.open("file:///" + os.path.abspath(_r["calibration_page"]).replace("\\", "/"))
            except Exception:
                pass
    _lines = "\n".join(f"    - {_r['game']} (gym '{_r['arena']}'): {_r['calibration_page']}" for _r in _cm_need)
    print("  " + "=" * 100)
    print(f"  STOPPED: {len(_cm_need)} game(s) need a one-time court calibration before the rest of the notebook runs:")
    print(_lines)
    print("  What to do:")
    print(("    1. The page" + ("s are" if len(_cm_need) > 1 else " is") + " open in your browser (or open the file above).")
          if globals().get("COURT_OPEN_CALIBRATION_PAGE", True) else "    1. Open the page above in a browser.")
    print("    2. On a few frames, click 4+ court landmarks (include one near each basket), then press Save.")
    print("    3. Rerun this Court mapping cell, then continue with the cells below (Run > Run Selected Cell and All Below).")
    print("  (To finish this run without that game on the court instead, set COURT_STOP_FOR_CALIBRATION = False.)")
    print("  " + "=" * 100, flush=True)
    raise CourtCalibrationNeeded(f"{len(_cm_need)} game(s) need court calibration -- see the steps printed above")

for _c in ("court_attack", "court_mapped_frames"):
    if _c not in play_calls.columns:
        play_calls[_c] = None
if isinstance(globals().get("player_tracks"), pd.DataFrame) and not player_tracks.empty:
    for _c in ("court_raw_path", "court_path"):
        if _c not in player_tracks.columns:
            player_tracks[_c] = None
