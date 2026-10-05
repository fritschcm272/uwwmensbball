# 50_player_tracking.py -- code for the notebook section "Player tracking: follow every player through the clip, put names on them, find the screen "
# Runs inside the notebook via run_section("50_player_tracking"); its settings are in that notebook cell.

# --- Player tracking: follow every player through the clip, put names on them, find the screen ----------------
# CONFIRMED CHANGE (requested: connect the detector's boxes to the five names on the floor, and find who set
# the screen and who defended it). A first version, built to be MEASURED -- every run reports how often it
# gets names right, so it's clear how far to trust it.
#   1. Detect   every person and the ball in each clip's tracking frames (VISION_TRACK_FPS per second, from the
#               frame-capture cell). YOLO; cached per frame file, so each frame is detected once ever.
#   2. Track    link each player's box from one frame to the next into a track, allowing for the camera
#               panning (the whole picture's shift is measured first, then players are matched after it).
#   3. Teams    jersey colors across the whole GAME are grouped into 3 (two teams + referees, the smallest).
#               Which color is which team is learned from the anchors below -- no uniform rules assumed.
#   4. Anchors  Synergy names the player who ends the possession (the shooter / ball handler / turnover). In
#               the last part of the clip, the track nearest the ball most often IS that player. That gives a
#               few named tracks per game for free.
#   5. Names    every track gets an appearance fingerprint (the pretrained image model on crops of the
#               player). Each named player's fingerprints form his profile; every other track is matched to
#               the closest profile AMONG THE FIVE ON THE FLOOR FOR HIS TEAM (lineups from the play-by-play),
#               never giving two tracks on the floor at the same time the same name.
#   6. Screens  a screen = an offensive player nearly standing still, touching a defender who had been
#               guarding a DIFFERENT offensive player, while that player passes close by. It reports the
#               screener, the player screened for (ball screen when he has the ball), that player's defender,
#               and the screener's own defender.
# Honest limits: every teammate wears the same uniform, so naming depends on small differences (build,
# skin, hair, shoes, sleeves) and the named examples Synergy provides; ball detection on game film is patchy;
# screens that happen between tracking frames are missed. The report at the end measures each part.
# Outputs: track_* columns on play_calls (the tag model can learn from them) and uww_player_tracks.csv (one row
# per track, for the app later). Check images with names drawn on them: _tracking/checks/.

# CONFIRMED CHANGE (requested: "switch to yolo11s"). The small model (yolo11n) boxed some players only part of the
# time -- overlapping, far away, partly out of the picture -- so review pictures showed 3-5 players per team instead of
# 5. yolo11s finds more of them; detection takes ~2-3x as long (once per frame -- saved). New detections mean new
# boxes, so jersey colors, fingerprints and jersey reads are redone for those frames too (all saved as before).
# CONFIRMED CHANGE (first real run: "0 named by Synergy + ball, teams told apart by color: no" -- the generic
# detector rarely finds a small, blurry basketball on game film, and every later step waited on it). Two
# routes that don't need the ball:
#   * teams: NCAA home teams wear the LIGHT jersey, so the lighter jersey-color group is the home team
#     (TRACK_TEAM_COLORS overrides it, e.g. {"UW-Oshkosh": "light"} for a game where the home team wore dark)
#   * names: on shot clips, the offensive player with his ARMS UP at the end is the shooter (a pose model finds
#     arms), and Synergy names the shooter -- that's the anchor.
# CONFIRMED CHANGE (review of the first 5 Oshkosh possessions: fans in the front rows, the scorer's table and
# seated bench players were being detected and even tracked as players -- one bench player was tracked as a
# defender -- which broke tracks into pieces, muddied the jersey-color groups and left 3 anchors all game). With
# the gym calibrated, every detection is put on the court first:
#   * anyone standing more than TRACK_COURT_MARGIN_FT outside the court lines is dropped
#   * players are linked frame to frame by real distance in feet (a player covers at most TRACK_MAX_SPEED_FTS
#     feet per second), which the camera's pan and perspective can't fool
#   * a track survives TRACK_KEEP_ALIVE missed frames (a player hidden behind another for a moment)
#   * a new anchor that needs neither ball nor pose: on a finish at the rim ("Basket", "Layup", "Putback", ...),
#     the offensive player closest to the basket at the end is the Synergy-named finisher.
# Uses the court mapping saved by the Court mapping cell (_tracking/court_homographies.pkl). On a game's very
# first run that file doesn't cover it yet -- rerun from this cell after Court mapping and it will.
# CONFIRMED CHANGE (first review on correctly captured frames: both finish-at-the-rim anchors named the wrong player --
# Richie Warren's cut (#24) landed on #21, Luke Bara's drive (#32) on #15 -- with clean, single-player tracks, so the
# RULE is wrong, not the tracking; it also explains the anchors disagreeing with jersey numbers 0 of 4 before). Off
# until it can be made reliable; jersey numbers, Synergy's ball-based anchors and the possession links still name.
# Detecting small, far-away players (review: only ~6 of the 10 players + 3 refs were found per frame). With the
# gym calibrated, each frame is cropped to the COURT STRIP (plus room above for heads), enlarged
# TRACK_DETECT_UPSCALE times and split into TRACK_DETECT_TILES overlapping pieces, so a far player the detector
# saw as 40 pixels tall is now ~80-100. Detections from the pieces are mapped back and duplicates merged.
# Costs ~TRACK_DETECT_TILES detector runs per frame (~15-25 min for a game with the small model, once --
# saved like before). 1 and 1.0 = the old whole-frame detection.
# CONFIRMED CHANGE (third review of the first 5 Oshkosh possessions: tracks jumped between players and even
# between teams -- the "Richie Warren" track was #21, a referee was tracked as offense -- and naming by
# appearance was no better than chance, 11 of 67). Two changes:
#   * Everyone is sorted into THREE groups BEFORE tracks are built -- team A, team B, and everyone else
#     (referees, coaches, fans at the sideline) -- by jersey AND shorts color (referees: black pants under a
#     grey striped shirt; UWW: white on white; Oshkosh: black and gold). A track can never cross groups.
#   * Players are named by the NUMBER ON THE JERSEY (read with EasyOCR from the chest of each tracked player;
#     one-time install + ~100 MB model download), limited to the numbers of the five on the floor for that
#     team (rosters + Synergy's "24 Richie Warren"). Appearance matching only fills in what numbers can't.
# CONFIRMED CHANGE (first review with jersey numbers on correctly captured frames: the reader answered only 38 of 492
# crops -- the 3 TALLEST boxes per player are often a player turned sideways). Crops that got confident answers were
# clearly WIDER for their height (0.51 vs 0.40: shoulders square to the camera, number showing); the widest quarter
# got confident answers 3-4x as often. So each player's crops are his widest boxes that are still near full height,
# at least half a second apart; tracks shorter than TRACK_OCR_MIN_TRACK_S aren't read (elimination and the
# possession links name those).
# CONFIRMED CHANGE (fourth review: of 12 tracks named by jersey number in the first 5 possessions ~4 were right).
#   * Seated people: at the same spot in the picture a seated bench player is much shorter than a standing one
#     (Oshkosh's #23 on the bench measured 0.65 of the standing height there; players on the floor 0.9-1.2;
#     seated fans and bench 0.43-0.59, crouching or partly hidden players 0.66-0.73).
#     Anyone under TRACK_MIN_STANDING of the standing height for that picture row is set aside.
#   * The number vote now counts EVERY confident read: the winning number must be the majority of all of them
#     (a track read "22" again and again was being named #4 off one stray "4"), and a single-digit number needs
#     TRACK_SINGLE_DIGIT_VOTES reads (blurry chests read as "0" constantly).
#   * Appearance-only names are switched off automatically while the appearance name check is below
#     TRACK_APPEARANCE_MIN_CHECK -- a blank is better than a wrong name in the brief.
# CONFIRMED CHANGE (coach: "not all 5 players even have a box around them"). Per frame the detector finds ~13 people on
# the court -- the 10 players and 3 referees -- but only ~6-7 players survived: the "seated person" and "wide box"
# checks (meant for fans and the bench along the sidelines) threw out real players crouched on defense, arms out,
# bent for a rebound. Both checks now apply only within TRACK_EDGE_ZONE_FT of a sideline or baseline, where people
# actually sit; out on the floor nobody is seated, so everyone standing there is kept.
# CONFIRMED CHANGE (requested: "there should never be an unnamed offense or unnamed defense -- make a best guess at each
# of the 5 players based on who we know is in the lineup"). After every trusted name is placed, the rest of each team's
# five are shared out among its remaining tracks using whatever weak clues exist (which known player he looks most
# like, partial jersey reads, names carried from linked possessions) -- and with no clue at all, still a name from the
# lineup. Never the same name on two tracks at once, never more than five at once (extras at the same moment are not
# players). Every such name is MARKED: name_how = "best guess", name_conf = TRACK_BEST_GUESS_CONF.
# CONFIRMED CHANGE (requested: validate the 10 players on the court from one picture per clip). Coach checks saved from
# track_validation/<game>/review.html (track_validation_*.json, picked up from Downloads) are CERTAIN names: they
# outrank every other source, teach each player's look, and "not a player" removes a box from naming. Each run also
# prints how often each naming method was right on the boxes a coach checked.
# CONFIRMED CHANGE (coach: "there are still unnamed offense and defensive players" in the scouting tables). The best
# guess treated every track of a team alike, so at a moment with 6+ tracks for a team -- a referee, a coach, a fan in a
# white shirt by the sideline sorted in by color -- it could hand a name to the sideline figure and leave a real player
# unnamed (review of 22 unnamed tracks: nearly all real players). Each track now gets a PLAYER-LIKENESS: out on the floor
# (not along a sideline / baseline), tracked through much of the play, moving. The most player-like tracks get the
# names; any track still unnamed after that can't be a 6th player on the floor, so it's set aside as NOT A PLAYER (like
# referees) and never appears as "unnamed offense / defense" in the tables.
# CONFIRMED CHANGE (requested: "you already know which 5 players from each team are on the court and their numbers
# -- make sure all 10 are matched up with that"). Names are now solved as ONE MATCHING per team per clip: the
# five names on the floor are shared out among that team's tracks, each player at most once at any moment,
# using every clue together:
#   * jersey readings scored against ONLY those five numbers -- an exact read counts most, and a partial read
#     still points the right way when only one of the five fits it (UWW's 21/15/11/32/24: a "4" can only be
#     #24, a "5" only #15), so even the reader's misreads carry information
#   * the Synergy-named anchor (weaker: anchors and numbers agreed only 4 of 18 times)
#   * elimination: when four of a team's five on the floor are identified at a moment, the one track left
#     is the fifth player -- no reading needed
# Players with no clue at all stay blank rather than being guessed (a guess among five is right 1 time in 5).
# CONFIRMED CHANGE (requested: "go forward and backwards in the Synergy details"). Every tracking frame now has its
# time in the full-game video, and back-to-back clips overlap (review: two Oshkosh-game clips shared 14 seconds;
# 27 track pairs lined up, most under 1 ft apart). Where two clips show the same moment, a team's tracks that stand
# in the same court spot are the same player, so they're LINKED; a player's linked tracks can run across many
# possessions, and a name found in any of them counts as evidence in all of them.
# CONFIRMED CHANGE (requested: use the play-by-play's named events). Rebounds, steals, blocks and fouls name a player
# at a known game-clock moment -- the only source that names DEFENDERS. Each clip has its own game clock, and its
# frames have game-video times, so an event lands on a frame: the clip's finish frame, shifted by how far the clock
# ran between them. There, the named player is:
#   rebound -> that team's player nearest the basket being attacked
#   steal   -> that team's player nearest the player who turned it over (once he's identified)
#   block   -> that team's player nearest the shooter;   foul -> that team's player nearest the player fouled
# accepted only if he is in that team's five on the floor and clearly the nearest (TRACK_PBP_MARGIN_FT).
# CONFIRMED CHANGE (review of the first full run with events: where an event pointed at an already-known player it
# was wrong 3 of 3 times, and a foul named "Brandon Beck (#0)" landed on a track showing #12 and #5). Until the event
# names are verified, they run in REVIEW mode: found and saved (uww_trk_event_candidates.csv, and crops of every one in
# the review zip) but NOT used to name anyone. True = use them; False = skip them.
# CONFIRMED CHANGE (coach: "there has to be some way to find the exact place one play ends and the next play starts").
# The clips are one continuous stretch of game video: each play's clip starts 0.2-0.4 s BEFORE the previous one ends.
# Linking used to need 1+ s of overlap and 3 shared moments, so back-to-back plays (one shared moment) were never
# linked. At every play boundary the players at the end of one play are now matched, spot for spot, with the players
# at the start of the next -- names carry across in both directions, play after play, until a substitution.

import json as _trk_json
import time
import glob
import shutil
# CONFIRMED BUG (fixed): numpy was first imported in the tag model cell, which runs AFTER this one
# ("PLAYER TRACKING NOT RUN: NameError: name 'np' is not defined"). Every cell that uses np imports it itself.
import numpy as np


def _trk_progress(label, done, total, t0, every=None):
    """One progress line with elapsed time and an estimate of what's left (requested: "make sure it is actually
    continuing to work"). About 10 lines per slow step; quick steps only print their finishing line."""
    every = every or max(1, total // 10)
    el = time.time() - t0
    # quick steps stay quiet: a line only once a step has run 5+ seconds, and always the finishing line
    if done == total and el >= 1 or (done % every == 0 and el >= 5):
        left = el / max(done, 1) * (total - done)
        print(f"  [tracking]   {label}: {done:,} / {total:,} ({100 * done // max(total, 1)}%) -- "
              f"{el / 60:.1f} min so far, ~{left / 60:.1f} min left", flush=True)


def _trk_yolo():
    import importlib
    if importlib.util.find_spec("ultralytics") is None:
        print("  [tracking] installing ultralytics (one time; it may also update torch)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "ultralytics"])
        raise RuntimeError("ultralytics was installed. RESTART THE KERNEL (Kernel > Restart) and run the parser "
                           "again -- torch may have been updated and the old one is still loaded.")
    from ultralytics import YOLO
    m = globals().get("_trk_yolo_model")
    if m is None or m[0] != TRACK_DETECTOR:
        print(f"  [tracking] loading detector {TRACK_DETECTOR} (downloads once)...")
        m = globals()["_trk_yolo_model"] = (TRACK_DETECTOR, YOLO(TRACK_DETECTOR))
    return m[1]


def _trk_det_cache_path():
    tiled = TRACK_DETECT_TILES > 1 or TRACK_DETECT_UPSCALE != 1.0
    return os.path.join(TRACK_DIR, f"detections_{re.sub(r'[^A-Za-z0-9]+', '_', TRACK_DETECTOR)}_{TRACK_DETECT_SIZE}"
                        + (f"_tiles{TRACK_DETECT_TILES}x{TRACK_DETECT_UPSCALE:g}" if tiled else "") + ".pkl")


def _trk_court_band(H, W, Hpx):
    """(y0, y1) rows of the picture that hold the court (feet) plus head room; None = use the whole frame."""
    if H is None:
        return None
    try:
        Hi = np.linalg.inv(np.asarray(H, np.float64))
    except Exception:
        return None
    # A homography is only defined up to scale, so "in front of the camera" is the SAME SIGN of w as a spot
    # known to be in the picture (its lower middle), not w > 0.
    c = np.asarray(H, np.float64) @ np.array([W / 2, 0.8 * Hpx, 1.0])
    front = np.sign((Hi @ (c / c[2]))[2]) or 1.0
    ys = []
    for X in np.linspace(-12, 106, 25):             # CONFIRMED CHANGE: room behind the baselines too (an inbounder stands out there)
        for Y in (-3, 25, 53):
            v = Hi @ np.array([X, Y, 1.0])
            if np.sign(v[2]) != front or abs(v[2]) < 1e-9:
                continue
            u, w = v[0] / v[2], v[1] / v[2]
            if -0.5 * W <= u <= 1.5 * W:
                ys.append(w)
    if len(ys) < 3:
        return None
    y1 = int(min(Hpx, max(ys) + 4))
    y0 = int(max(0, min(ys) - 0.22 * Hpx))          # room above the far sideline for a standing player
    return (y0, y1) if y1 - y0 > 0.2 * Hpx else None


def _trk_tiled_predict(model, paths, H_of, classes, conf, keypoints=False):
    """Run `model` on the enlarged court strip of each picture in overlapping tiles; boxes (and keypoints)
    mapped back to the original picture, duplicates across tiles merged. Returns one list per picture of
    (box xyxy, conf, class, keypoints or None)."""
    import cv2
    U, T = float(TRACK_DETECT_UPSCALE), int(TRACK_DETECT_TILES)
    out_all = []
    for p in paths:
        img = cv2.imread(p)
        Hpx, W = img.shape[:2]
        band = _trk_court_band(H_of(p), W, Hpx) if (T > 1 or U != 1.0) else None
        y0, y1 = band if band else (0, Hpx)
        strip = img[y0:y1]
        if U != 1.0:
            strip = cv2.resize(strip, (int(W * U), int((y1 - y0) * U)), interpolation=cv2.INTER_CUBIC)
        SW = strip.shape[1]
        tw = int(np.ceil(SW / T * 1.15)) if T > 1 else SW
        starts = [int(round(k * (SW - tw) / max(T - 1, 1))) for k in range(T)] if T > 1 else [0]
        tiles = [strip[:, s0:s0 + tw] for s0 in starts]
        res = model.predict(tiles, classes=classes, conf=conf, imgsz=TRACK_DETECT_SIZE, verbose=False)
        found = []
        for s0, r in zip(starts, res):
            bx = r.boxes.xyxy.cpu().numpy() if r.boxes is not None else np.zeros((0, 4))
            cf = r.boxes.conf.cpu().numpy() if r.boxes is not None else np.zeros(0)
            cl = r.boxes.cls.cpu().numpy() if r.boxes is not None else np.zeros(0)
            kp = r.keypoints.data.cpu().numpy() if keypoints and getattr(r, "keypoints", None) is not None else None
            for n_, (b, c, k) in enumerate(zip(bx, cf, cl)):
                # a box cut by an inner tile edge is left to the neighbouring tile, which sees it whole
                if (b[0] <= 2 and s0 > 0) or (b[2] >= tw - 2 and s0 + tw < SW):
                    continue
                box = np.array([(b[0] + s0) / U, b[1] / U + y0, (b[2] + s0) / U, b[3] / U + y0])
                kk = None
                if kp is not None and n_ < len(kp):
                    kk = kp[n_].copy()
                    kk[:, 0] = (kk[:, 0] + s0) / U
                    kk[:, 1] = kk[:, 1] / U + y0
                found.append((box, float(c), int(k), kk))
        # merge duplicates from the overlaps (same class, heavy overlap -> keep the more confident)
        found.sort(key=lambda x: -x[1])
        kept = []
        for f in found:
            if all(f[2] != g[2] or _trk_iou(f[0], g[0]) < 0.5 for g in kept):
                kept.append(f)
        out_all.append(kept)
    return out_all


def _trk_iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / max((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter, 1e-6)


def _trk_court_H_lookup(base):
    cp = os.path.join(TRACK_DIR, "court_homographies.pkl")
    cache = {k: v for k, v in pd.read_pickle(cp).items() if not str(k).startswith("_")} if os.path.exists(cp) else {}
    return lambda p: cache.get(os.path.relpath(p, base).replace(os.sep, "/"))


def _trk_detect(rels, base):
    """rel path -> {"p": [x1,y1,x2,y2,conf,r,g,b] people, "b": [cx,cy,conf] balls, "W", "H"}; cached."""
    os.makedirs(TRACK_DIR, exist_ok=True)
    cpath = _trk_det_cache_path()
    cache = pd.read_pickle(cpath) if os.path.exists(cpath) else {}
    todo = [r for r in dict.fromkeys(rels) if r not in cache and os.path.exists(os.path.join(base, r))]
    if todo:
        from PIL import Image
        model = _trk_yolo()
        H_of = _trk_court_H_lookup(base)
        n_band = sum(1 for r in todo if H_of(os.path.join(base, r)) is not None)
        print(f"  [tracking] finding players and the ball in {len(todo)} new frame(s) "
              f"({TRACK_DETECT_TILES} enlarged court-strip tiles per frame; court strip known for {n_band:,})...", flush=True)
        _t0 = time.time()
        for i in range(0, len(todo), 8):
            chunk = todo[i:i + 8]
            res = _trk_tiled_predict(model, [os.path.join(base, r) for r in chunk], H_of, [0, 32],
                                     min(TRACK_PERSON_CONF, TRACK_BALL_CONF))
            for r, found in zip(chunk, res):
                img = np.asarray(Image.open(os.path.join(base, r)).convert("RGB"))
                H, W = img.shape[:2]
                people, balls = [], []
                for (x1, y1, x2, y2), cf, cl, _k in found:
                    if cl == 32 and cf >= TRACK_BALL_CONF:
                        balls.append([(x1 + x2) / 2, (y1 + y2) / 2, cf])
                    elif cl == 0 and cf >= TRACK_PERSON_CONF:
                        w, h = x2 - x1, y2 - y1
                        patch = img[max(int(y1 + 0.2 * h), 0):max(int(y1 + 0.45 * h), int(y1 + 0.2 * h) + 1),
                                    max(int(x1 + 0.3 * w), 0):max(int(x2 - 0.3 * w), int(x1 + 0.3 * w) + 1)]
                        rgb = patch.reshape(-1, 3).mean(0) if patch.size else np.array([np.nan] * 3)
                        # color strength and "stripes" of the chest: referees' black-and-white stripes are
                        # colorless with strong light/dark variation; jerseys aren't (review: gold-and-black
                        # Oshkosh jerseys under the lights were being grouped with the referees)
                        if patch.size:
                            pf = patch.reshape(-1, 3).astype(np.float32)
                            sat = float(np.mean(pf.max(1) - pf.min(1)))
                            stripes = float(np.std(pf.mean(1)))
                        else:
                            sat = stripes = np.nan
                        people.append([x1, y1, x2, y2, cf, *rgb, sat, stripes])
                cache[r] = {"p": np.array(people, dtype=np.float32).reshape(-1, 10),
                            "b": np.array(balls, dtype=np.float32).reshape(-1, 3), "W": W, "H": H}
            if (i // 8) % 40 == 39:
                pd.to_pickle(cache, cpath)
            _trk_progress("frames checked for players", min(i + 8, len(todo)), len(todo), _t0,
                          every=max(8, (len(todo) // 20) // 8 * 8))
        pd.to_pickle(cache, cpath)
    return cache


def _trk_jersey_feats(rels, det, base):
    """rel -> array (one row per detection in det[rel]["p"]): chest lightness, chest warmth (red - blue),
    shorts lightness, shorts warmth, chest light/dark variation. Read from the frames once and saved."""
    cp = _trk_det_cache_path().replace(".pkl", "_jersey.pkl")
    cache = pd.read_pickle(cp) if os.path.exists(cp) else {}
    todo = [r for r in dict.fromkeys(rels) if r not in cache and det.get(r) is not None]
    if todo:
        from PIL import Image
        print(f"  [tracking]   reading jersey and shorts colors in {len(todo):,} frame(s)...", flush=True)
        _t0 = time.time()
        for n, r in enumerate(todo, 1):
            _trk_progress("frames read for jersey colors", n, len(todo), _t0)
            p = det[r]["p"]
            if not len(p):
                cache[r] = np.zeros((0, 5), np.float32)
                continue
            img = np.asarray(Image.open(os.path.join(base, r)).convert("RGB")).astype(np.float32)
            rows = []
            for x1, y1, x2, y2 in p[:, :4]:
                w, h = x2 - x1, y2 - y1
                def _patch(a, b):
                    return img[max(int(y1 + a * h), 0):max(int(y1 + b * h), int(y1 + a * h) + 1),
                               max(int(x1 + 0.3 * w), 0):max(int(x2 - 0.3 * w), int(x1 + 0.3 * w) + 1)].reshape(-1, 3)
                t_, s_ = _patch(0.2, 0.45), _patch(0.5, 0.68)
                if not len(t_) or not len(s_):
                    rows.append([np.nan] * 5)
                    continue
                tm, sm = t_.mean(0), s_.mean(0)
                rows.append([tm.mean(), tm[0] - tm[2], sm.mean(), sm[0] - sm[2], float(np.std(t_.mean(1)))])
            cache[r] = np.array(rows, np.float32)
        pd.to_pickle(cache, cp)
    return cache


def _trk_group_feat(rows):
    """What sorts people into team A / team B / everyone else: chest and shorts lightness and warmth."""
    return np.column_stack([rows[:, 14], rows[:, 15] * 2, rows[:, 16], rows[:, 17] * 2, rows[:, 18]])


def _trk_read_numbers(clips, todo, base, engine):
    """(clip, track) -> list of (digits read, confidence) from the chest of the track's tallest boxes, with the
    reader chosen by the Jersey-number reader test. Every read is saved, so each crop is read once per reader."""
    import cv2
    cp = os.path.join(TRACK_DIR, "jersey_numbers.pkl")
    cache = pd.read_pickle(cp) if os.path.exists(cp) else {}
    jobs = []
    for i in todo:
        clip = clips[i]
        for k, tr in enumerate(clip["tracks"]):
            if clip["side"].get(k) not in ("offense", "defense"):
                continue
            n_crops = (TRACK_OCR_CROPS_TRAINED if engine == "trained" else TRACK_OCR_CROPS_PADDLE if str(engine).startswith("paddle")
                       else TRACK_OCR_CROPS_FIND if str(engine).endswith(("_find", "_local", "_rec")) else TRACK_OCR_CROPS)
            fps_ = float(clip.get("fps", 2.0))
            if len(tr) < TRACK_OCR_MIN_TRACK_S * fps_:
                continue
            hts = {tj: clip["frames"][tj[0]][tj[1]][9] - clip["frames"][tj[0]][tj[1]][7] for tj in tr}
            hmax = max(hts.values())
            # widest for its height (facing the camera) among the boxes near his full height, spread out in time
            cand = sorted((tj for tj in tr if hts[tj] >= 0.8 * hmax),
                          key=lambda tj: -((clip["frames"][tj[0]][tj[1]][8] - clip["frames"][tj[0]][tj[1]][6]) / max(hts[tj], 1e-6)))
            gap = max(1, int(round(fps_ / 2)))
            tallest = []
            for tj in cand:
                if all(abs(tj[0] - o[0]) >= gap for o in tallest):
                    tallest.append(tj)
                if len(tallest) >= n_crops:
                    break
            # dark digits on a light jersey are read as-is; light digits on a dark jersey inverted
            light = np.nanmean([clip["frames"][tt][jj][14] for tt, jj in tr]) > 130
            for t, j in tallest:
                x1, y1, x2, y2 = [float(v) for v in clip["frames"][t][j][6:10]]
                jobs.append(((i, k), f"{clip['files'][t]}|{int(x1)}|{int(y1)}|{int(x2)}|{int(y2)}|{engine}2",
                             clip["files"][t], (x1, y1, x2, y2), "as_is" if light else "invert"))
    new = [jb for jb in jobs if jb[1] not in cache]
    if new:
        print(f"  [tracking]   reading jersey numbers ({engine}) on {len(new):,} chest crop(s) "
              f"({len(jobs) - len(new):,} read in earlier runs)...", flush=True)
        _t0 = time.time()
        imgs = {}
        for s0 in range(0, len(new), 100):
            chunk = new[s0:s0 + 100]
            crops = []
            for _o, _key, rel, box, _pol in chunk:
                if rel not in imgs:
                    if len(imgs) > 300:
                        imgs.clear()
                    imgs[rel] = cv2.imread(os.path.join(base, rel),
                                           cv2.IMREAD_COLOR if _jn_needs_color(engine) else cv2.IMREAD_GRAYSCALE)
                crops.append(_jn_prep_for(engine)(imgs[rel], box) if imgs[rel] is not None else None)
            for (_o, key, _rel, _box, _pol), (txt, cf) in zip(chunk, _jn_read(engine, crops, [jb[4] for jb in chunk])):
                cache[key] = [(txt, cf)] if txt else []
            pd.to_pickle(cache, cp)
            _trk_progress("chest crops read", min(s0 + 100, len(new)), len(new), _t0, every=max(100, (len(new) // 10) // 100 * 100))
    out = {}
    for owner, key, _rel, _box, _pol in jobs:
        out.setdefault(owner, []).extend(cache.get(key, []))
    return out


def _trk_read_scores(rd, five_nums):
    """Evidence for each of the five names from one track's jersey readings. five_nums: {name: "24"}."""
    sc = {n: 0.0 for n in five_nums}
    for txt, cf in rd:
        if not txt or cf < TRACK_MIN_READ_CONF:
            continue
        exact = [n for n, num in five_nums.items() if num == txt]
        # a single digit that is also PART of another number on the floor ("0" vs #10, "2" vs #21/#23/#32) is only a
        # shared hint: split between everyone it could be, like a partial read
        if exact and len(txt) == 1 and any(len(num) == 2 and txt in num for num in five_nums.values()):
            exact = []
        if exact:
            w = TRACK_EXACT_READ_WEIGHT * (0.5 if len(txt) == 1 else 1.0)
            for n in exact:
                sc[n] += w * cf / len(exact)
            continue
        part = [n for n, num in five_nums.items() if txt in num or (num in txt and len(num) > 1)]
        for n in part:
            sc[n] += TRACK_PARTIAL_READ_WEIGHT * cf / len(part)
    return sc


def _trk_solve_team(tracks, ks, score):
    """One matching for one team in one clip. ks: that team's track ids; score[k][name] = evidence. Every track
    gets at most one name, and two tracks seen at the same moment never share a name. Maximizes the total
    evidence (scipy's integer solver; a careful greedy pass if that isn't available). -> {k: name}"""
    names = sorted({n for k in ks for n in score[k]})
    if not ks or not names:
        return {}
    frames_of = {k: {t for t, _ in tracks[k]} for k in ks}
    pairs = [(a, b) for x, a in enumerate(ks) for b in ks[x + 1:] if frames_of[a] & frames_of[b]]
    try:
        from scipy.optimize import milp, LinearConstraint, Bounds
        idx = {(k, n): v for v, (k, n) in enumerate((k, n) for k in ks for n in names)}
        nv = len(idx)
        c = np.array([-score[k][n] + 1e-3 for (k, n) in idx])     # the tiny cost: no evidence -> stay blank
        rows, ub = [], []
        for k in ks:                                              # at most one name per track
            r = np.zeros(nv)
            for n in names:
                r[idx[(k, n)]] = 1
            rows.append(r)
            ub.append(1)
        for a, b in pairs:                                        # never the same name at the same moment
            for n in names:
                r = np.zeros(nv)
                r[idx[(a, n)]] = r[idx[(b, n)]] = 1
                rows.append(r)
                ub.append(1)
        res = milp(c, constraints=LinearConstraint(np.array(rows), -np.inf, np.array(ub)),
                   integrality=np.ones(nv), bounds=Bounds(0, 1))
        if res.x is not None:
            return {k: n for (k, n), v in idx.items() if res.x[v] > 0.5 and score[k][n] > 0}
    except Exception:
        pass
    out, used = {}, {}
    for s_, k, n in sorted(((score[k][n], k, n) for k in ks for n in names if score[k][n] > 0), reverse=True):
        if k in out or any(frames_of[k] & frames_of[o] for o in used.get(n, [])):
            continue
        out[k] = n
        used.setdefault(n, []).append(k)
    return out


def _trk_eliminate(tracks, ks, five, named):
    """Lineup elimination: at any moment where four of the five are placed on tracks and one track of that team is
    still blank, that track is the fifth player (if he isn't on another track at any moment it covers)."""
    frames_of = {k: {t for t, _ in tracks[k]} for k in ks}
    added = {}
    changed = True
    while changed:
        changed = False
        allt = sorted({t for k in ks for t in frames_of[k]})
        for t in allt:
            here = [k for k in ks if t in frames_of[k]]
            named_here = {named.get(k) or added.get(k) for k in here} - {None}
            blank = [k for k in here if not (named.get(k) or added.get(k))]
            left = [n for n in five if n not in named_here]
            if len(blank) == 1 and len(left) == 1 and len(named_here) == len(five) - 1:
                k, n = blank[0], left[0]
                clash = any((named.get(o) == n or added.get(o) == n) and frames_of[o] & frames_of[k] for o in ks if o != k)
                if not clash:
                    added[k] = n
                    changed = True
    return added


def _trk_fill_lineups(pc):
    """Clips with no game clock can't be matched to the play-by-play, so they had NO five on the floor and nobody in
    them could be named (e.g. clip 2, a Synergy "Non Possession" foul). Every clip has a spot in the game video, though:
    if the clips just before and after it show the same five for a team, nobody subbed in between -- that's its five.
    Fills offense_lineup / defense_lineup in place; lineup_source says where each came from."""
    if "lineup_source" not in pc.columns:
        pc["lineup_source"] = None
    for c in ("offense_lineup", "defense_lineup", "video_start_s"):
        if c not in pc.columns:
            return 0
    has = lambda v: isinstance(v, str) and v.strip() != ""
    pc.loc[pc["offense_lineup"].map(has) & pc["lineup_source"].isna(), "lineup_source"] = "play-by-play"
    n_filled = 0
    vs = pd.to_numeric(pc["video_start_s"], errors="coerce")
    for (gd, gc), g in pc[vs.notna()].groupby(["game_date", "game_code"], dropna=False):
        g = g.assign(_v=vs[g.index]).sort_values("_v")
        order = list(g.index)
        def five_of(i, team):
            for side in ("offense", "defense"):
                if str(pc.at[i, f"{side}_team"]) == str(team) and has(pc.at[i, f"{side}_lineup"]) \
                        and pc.at[i, "lineup_source"] == "play-by-play":
                    return pc.at[i, f"{side}_lineup"]
            return None
        for x, i in enumerate(order):
            for side in ("offense", "defense"):
                team = pc.at[i, f"{side}_team"]
                if has(pc.at[i, f"{side}_lineup"]) or not isinstance(team, str):
                    continue
                prev = next((five_of(j, team) for j in reversed(order[:x]) if five_of(j, team)), None)
                nxt = next((five_of(j, team) for j in order[x + 1:] if five_of(j, team)), None)
                same = lambda a, b: a and b and sorted(p.strip() for p in a.split(",")) == sorted(p.strip() for p in b.split(","))
                pick = prev if (prev and nxt and same(prev, nxt)) else (prev or nxt if not (prev and nxt) else None)
                if pick:
                    pc.at[i, f"{side}_lineup"] = pick
                    pc.at[i, "lineup_source"] = "clips before/after (no clock)"
                    n_filled += 1
    return n_filled


def _trk_coach_checks():
    """Every coach check saved from the validation pages -- all files merged, the latest check of a box wins
    (coach_checks_all, in the Play calls section)."""
    return coach_checks_all()[0]


def _trk_player_likeness(clip, k):
    """0..1: how much a track behaves like a player on the floor -- out on the court (not along a sideline or baseline,
    where coaches, the bench and fans are), tracked through much of the play, and moving."""
    tr = clip["tracks"][k]
    pts = [clip["frames"][t][j][10:12] for t, j in tr]
    pts = [(float(x), float(y)) for x, y in pts if np.isfinite(x) and np.isfinite(y)]
    n = max(len(clip["frames"]), 1)
    length = min(1.0, len(tr) / max(0.5 * n, 1))
    if not pts:
        return 0.3 * length
    inside = float(np.mean([3 <= x <= 91 and 3 <= y <= 47 for x, y in pts]))
    steps = [np.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
    moving = float(np.mean([s_ > 0.4 for s_ in steps])) if steps else 0.0
    return 0.5 * inside + 0.3 * length + 0.2 * moving


def _trk_synergy_names(ss):
    """Every player a Synergy description names, in order ("24 Richie Warren > ... > 32 Luke Bara" -> both)."""
    out = []
    for _j, n in re.findall(r"(?:^|>)\s*(\d{1,2})\s+([A-Za-z][^>]*?)\s*(?=>|$)", str(ss or "")):
        n = n.strip()
        if n and n not in out:
            out.append(n)
    return out


def _trk_pbp_anchors(clips, todo, pc, known, fps):
    """Play-by-play named events -> [(clip, track, name, event type)]. `known`: {(clip, name): track} already
    identified (Synergy anchors, jersey numbers) -- the reference for steals, blocks and fouls."""
    out = []
    for i in todo:
        clip, r = clips[i], pc.loc[i]
        c_clip, per = pd.to_numeric(r.get("time_remaining_seconds"), errors="coerce"), r.get("period")
        if pd.isna(c_clip) or clip.get("t_finish") is None or not isinstance(per, str):
            continue
        ev = globals().get("pbp_events") if str(r.get("side")) == "UWW" else globals().get("pbp_events_upcoming")
        if not isinstance(ev, pd.DataFrame) or ev.empty or "event_type" not in ev.columns:
            continue
        m = (ev["game_date"].astype(str) == str(r.get("game_date"))) & (ev["period"].astype(str) == per) \
            & pd.to_numeric(ev["time_remaining_seconds"], errors="coerce").between(c_clip - TRACK_PBP_WINDOW_S,
                                                                                 c_clip + TRACK_PBP_WINDOW_S)
        evs = ev[m & ev["player"].notna()]
        if evs.empty:
            continue
        n = len(clip["frames"])
        team_name = {"offense": str(r.get("offense_team")), "defense": str(r.get("defense_team"))}
        five_of = {str(r.get("offense_team")): _trk_five(r.get("offense_lineup")),
                   str(r.get("defense_team")): _trk_five(r.get("defense_lineup"))}
        pos = {}
        for k, tr in enumerate(clip["tracks"]):
            for t, j in tr:
                X, Y = clip["frames"][t][j][10:12]
                if np.isfinite(X) and np.isfinite(Y):
                    pos.setdefault(k, {})[t] = (float(X), float(Y))

        def _at(k, f):
            for d in (0, -1, 1, -2, 2):
                if f + d in pos.get(k, {}):
                    return pos[k][f + d]
            return None

        for _, e in evs.iterrows():
            et, P, T = str(e["event_type"]), str(e["player"]).strip(), str(e.get("team"))
            if et not in ("rebound_offensive", "rebound_defensive", "steal", "block", "foul"):
                continue
            _norm = lambda x: re.sub(r"[^a-z]", "", str(x).lower())
            side = next((sd for sd, nm in team_name.items()
                         if _norm(T) and (_norm(T) == _norm(nm) or _norm(T) in _norm(nm) or _norm(nm) in _norm(T))), None)
            if side is None or (five_of.get(team_name[side]) and P not in five_of[team_name[side]]):
                continue
            fe = int(round(clip["t_finish"] + (c_clip - float(e["time_remaining_seconds"])) * fps))
            # the finish frame is an estimate (review: a steal happened 3 frames before it), so look across a short
            # window -- before and just after it for steals / blocks / fouls, after it for rebounds -- and keep the
            # frame where one player is most clearly the nearest
            win = range(fe, fe + int(2.0 * fps) + 1) if et.startswith("rebound") else range(fe - int(2.0 * fps), fe + int(1.0 * fps) + 1)
            best = None
            other_side = "defense" if side == "offense" else "offense"
            if not et.startswith("rebound"):
                same_t = evs[pd.to_numeric(evs["time_remaining_seconds"], errors="coerce") == float(e["time_remaining_seconds"])]
                want = {"steal": ("turnover",), "block": ("missed_shot",), "foul": ("free_throw_made", "free_throw_missed",
                                                                                     "made_shot", "missed_shot", "turnover")}[et]
                others = [str(x) for x in same_t.loc[same_t["event_type"].isin(want), "player"].dropna()]
                if et == "foul" and isinstance(r.get("player"), str):
                    others.append(r.get("player").strip())
                ref_k = next((known.get((i, o)) for o in others if known.get((i, o)) is not None
                              and clip["side"].get(known.get((i, o))) == other_side), None)
                if ref_k is None:
                    continue
            elif clip.get("basket") is None:
                continue
            for f in win:
                if not 0 <= f < n:
                    continue
                if et.startswith("rebound"):
                    ref, lim = clip["basket"], TRACK_PBP_REBOUND_FT
                else:
                    ref, lim = pos.get(ref_k, {}).get(f), TRACK_PBP_NEAR_FT
                    if ref is None:
                        continue
                cands = [(k, pos[k][f]) for k in pos if clip["side"].get(k) == side and f in pos[k]]
                if not cands:
                    continue
                dist = sorted((float(np.hypot(p[0] - ref[0], p[1] - ref[1])), k) for k, p in cands)
                margin = (dist[1][0] - dist[0][0]) if len(dist) > 1 else 99.0
                kp = pos[dist[0][1]][f]
                crowd = any(float(np.hypot(p[0] - kp[0], p[1] - kp[1])) < TRACK_PBP_CROWD_FT for k, p in cands if k != dist[0][1])
                if dist[0][0] <= lim and margin >= TRACK_PBP_MARGIN_FT and not crowd and (best is None or margin > best[0]):
                    best = (margin, dist[0][1])
            if best is not None:
                out.append((i, best[1], P, et))
    return out


def _trk_link_possessions(clips, todo, pc, game_of):
    """Link a team's tracks across clips that show the same moments of the game. -> {(clip, track): group id},
    plus (links made, clip pairs overlapping)."""
    from scipy.optimize import linear_sum_assignment
    times = {}
    for i in todo:
        tt = [float(x) for x in str(pc.at[i, "track_times"] if "track_times" in pc.columns else "").split(";") if x and x != "nan"]
        if len(tt) == len(clips[i]["frames"]) and tt:
            times[i] = np.array(tt)
    pos = {}
    for i in times:
        d = {}
        for k, tr in enumerate(clips[i]["tracks"]):
            tm = clips[i].get("team", {}).get(k)
            if tm not in ("A", "B"):
                continue
            for t, j in tr:
                X, Y = clips[i]["frames"][t][j][10:12]
                if np.isfinite(X) and np.isfinite(Y):
                    d.setdefault(t, []).append((k, float(X), float(Y), tm))
        pos[i] = d
    ids = sorted(times, key=lambda i: times[i][0])
    cands, n_pairs = [], 0
    n_bound = [0]
    for x, a in enumerate(ids):
        for b in ids[x + 1:]:
            if game_of[a] != game_of[b]:
                continue
            if times[b][0] > times[a][-1]:
                break                                            # sorted by start: nothing later overlaps a
            overlap = min(times[a][-1], times[b][-1]) - max(times[a][0], times[b][0])
            if overlap < -TRACK_LINK_BOUNDARY_S:
                continue
            boundary = overlap < 1.0                    # back-to-back plays: they meet at one moment
            n_pairs += 1
            n_bound[0] += int(boundary)
            co = {}
            max_dt = TRACK_LINK_BOUNDARY_S if boundary else TRACK_LINK_MAX_DT
            for fa, t_a in enumerate(times[a]):
                fb = int(np.argmin(np.abs(times[b] - t_a)))
                if abs(times[b][fb] - t_a) > max_dt:
                    continue
                for team in ("A", "B"):
                    pa = [p for p in pos[a].get(fa, []) if p[3] == team]
                    pb = [p for p in pos[b].get(fb, []) if p[3] == team]
                    if not pa or not pb:
                        continue
                    D = np.array([[np.hypot(p[1] - q[1], p[2] - q[2]) for q in pb] for p in pa])
                    r, c = linear_sum_assignment(D)
                    for u, v in zip(r, c):
                        if D[u, v] < TRACK_LINK_FT:
                            co.setdefault((pa[u][0], pb[v][0]), []).append(D[u, v])
            for (ka, kb), ds in co.items():
                if (len(ds) >= TRACK_LINK_MIN_MOMENTS and np.median(ds) <= TRACK_LINK_FT * 0.67) or \
                        (boundary and np.median(ds) <= TRACK_LINK_BOUNDARY_FT):
                    cands.append((len(ds), -float(np.median(ds)), (a, ka), (b, kb)))
    # join strongest links first; a group may never hold two tracks of the same clip that are seen at the same moment
    parent, members = {}, {}
    def find(u):
        while parent.get(u, u) != u:
            u = parent[u]
        return u
    def frames_of(node):
        i, k = node
        return {float(times[i][t]) for t, _ in clips[i]["tracks"][k]}
    n_links = 0
    for _n, _d, u, v in sorted(cands, reverse=True):
        ru, rv = find(u), find(v)
        if ru == rv:
            continue
        mu, mv = members.get(ru, [ru]), members.get(rv, [rv])
        clash = any(p[0] == q[0] and p[1] != q[1] and (frames_of(p) & frames_of(q)) for p in mu for q in mv)
        if clash:
            continue
        parent[rv] = ru
        members[ru] = mu + mv
        members.pop(rv, None)
        n_links += 1
    group = {}
    for root, ms in members.items():
        for m in ms:
            group[m] = root
    globals()["_trk_n_boundaries"] = n_bound[0]
    return group, n_links, n_pairs


def _trk_players(d, H=None, feats=None, opening=False):
    """Kept player boxes for one frame -> rows [x, y, h, r, g, b, x1, y1, x2, y2, X, Y, sat, stripes, chest L,
    chest warmth, shorts L, shorts warmth, chest variation, group] with x, y the feet point
    measured in picture-HEIGHT units (so left-right and up-down distances are comparable), h the box height,
    and X, Y the feet on the court in feet (NaN when this frame has no court mapping). With a court mapping,
    anyone standing off the court (fans, bench, the scorer's table) is dropped."""
    if d is None or len(d["p"]) == 0:
        return np.zeros((0, 20), dtype=np.float32)
    p, W, Hpx = d["p"], d["W"], d["H"]
    p = p[np.isfinite(p[:, 5])]
    h = (p[:, 3] - p[:, 1]) / Hpx
    fy = p[:, 3] / Hpx
    fx = (p[:, 0] + p[:, 2]) / 2 / W
    # Review of the first 5 Oshkosh possessions: the front row of fans (heads and hoodies cut off by the bottom of
    # the picture) was being kept as "players". Anyone whose feet run off the bottom edge can't be put on the
    # court, and a player's box is tall and narrow -- wide, squat boxes are seated people.
    wid = (p[:, 2] - p[:, 0]) / np.maximum(p[:, 3] - p[:, 1], 1e-6)
    keep = (h > 0.03) & (h < 0.45) & (fy > 0.15) & (fy < 0.975) & (fx > 0.005) & (fx < 0.995)
    X = np.full(len(p), np.nan)
    Y = np.full(len(p), np.nan)
    if H is not None and len(p):
        Hm = np.asarray(H, np.float64)
        v = Hm @ np.vstack([(p[:, 0] + p[:, 2]) / 2, p[:, 3], np.ones(len(p))])
        X, Y = v[0] / v[2], v[1] / v[2]
        m = TRACK_COURT_MARGIN_FT
        court_ok = (X > -m) & (X < 94 + m) & (Y > -TRACK_NEAR_MARGIN_FT) & (Y < 50 + m)
        # CONFIRMED CHANGE (coach: "the model normally misses the player throwing the ball in on BLOB plays"). The inbounder
        # stands BEHIND the baseline -- farther out than TRACK_COURT_MARGIN_FT -- so he was dropped with the fans and the
        # bench. In a clip's opening seconds (TRACK_INBOUND_OPEN_S) a standing person up to TRACK_INBOUND_MARGIN_FT behind
        # either baseline, within TRACK_INBOUND_Y_FT across the court, is kept (0 = off). Referees and anyone else back
        # there fall into the third color group ("everyone else"); the seated / wide-box checks below still apply.
        _im = float(globals().get("TRACK_INBOUND_MARGIN_FT", 10.0))
        if opening and _im > 0:
            _y0, _y1 = globals().get("TRACK_INBOUND_Y_FT", (8.0, 42.0))
            court_ok |= (((X <= -m) & (X > -_im)) | ((X >= 94 + m) & (X < 94 + _im))) & (Y >= _y0) & (Y <= _y1)
        keep &= court_ok
        edge = (X < TRACK_EDGE_ZONE_FT) | (X > 94 - TRACK_EDGE_ZONE_FT) | (Y < TRACK_EDGE_ZONE_FT) | (Y > 50 - TRACK_EDGE_ZONE_FT)
        keep &= ~edge | (wid < 0.8)          # wide boxes: seated people -- only along the edges
    else:
        keep &= wid < 0.8                     # no court position: the old rule everywhere
    rgb = p[:, 5:8]
    sat = p[:, 8] if p.shape[1] > 8 else rgb.max(1) - rgb.min(1)
    stripes = p[:, 9] if p.shape[1] > 9 else np.zeros(len(p))
    jf = feats if feats is not None and len(feats) == len(p) else np.full((len(p), 5), np.nan, np.float32)
    grp = np.full(len(p), -1.0)                    # filled in by the team grouping (0 = A, 1 = B, 2 = everyone else)
    return np.column_stack([fx[keep] * W / Hpx, fy[keep], h[keep], rgb[keep], p[keep][:, 0:4],
                            X[keep], Y[keep], sat[keep], stripes[keep], jf[keep], grp[keep]]).astype(np.float32)


def _trk_finish(frames):
    """(basket, finish frame, window) for one clip, from the court positions of everyone on the floor.
    Synergy clips run on after the play ends (review: in possession 3 the basket comes at frame 14 and by
    frame 17 everyone is running the other way), so "the end of the clip" is the wrong moment. The attacked
    basket = the end the players are at during the first 70% of the clip; the finish = the frame they're
    deepest toward it; the window = the stretch leading up to it (where the shooter / finisher is read).
    Without court positions: the old rule, the last 40% of the clip."""
    n = len(frames)
    xs = np.array([np.nanmedian(f[:, 10]) if len(f) and f.shape[1] >= 12 and np.isfinite(f[:, 10]).any() else np.nan
                   for f in frames])
    first = xs[: max(2, int(0.7 * n))]
    if not np.isfinite(first).any():
        return None, n - 1, list(range(int(0.6 * n), n))
    bx = 5.25 if np.nanmedian(first) < 47 else 88.75
    lo, hi = int(0.2 * n), max(int(0.9 * n), int(0.2 * n) + 1)
    depth = np.abs(xs - bx)
    cand = [t for t in range(lo, min(hi, n)) if np.isfinite(depth[t])]
    t_fin = min(cand, key=lambda t: depth[t]) if cand else n - 1
    w0 = max(0, t_fin - max(2, int(0.25 * n)))
    return (bx, 25.0), t_fin, list(range(w0, min(n, t_fin + 2)))


def _trk_color_feat(rows):
    """Jersey description used to split the teams: lightness, color direction, color strength, stripes."""
    rows = np.asarray(rows, np.float32).reshape(-1, rows.shape[-1] if hasattr(rows, "shape") else 14)
    rgb = rows[:, 3:6]
    L = rgb.mean(1)
    chroma = rgb - L[:, None]
    sat = rows[:, 12] if rows.shape[1] > 12 else rgb.max(1) - rgb.min(1)
    stripes = rows[:, 13] if rows.shape[1] > 13 else np.zeros(len(rows))
    sat = np.where(np.isfinite(sat), sat, rgb.max(1) - rgb.min(1))
    stripes = np.where(np.isfinite(stripes), stripes, 0.0)
    return np.column_stack([L, chroma[:, 0] * 2, chroma[:, 1] * 2, chroma[:, 2] * 2, sat, stripes * 1.5])


def _trk_link(frames, fps_=2.0):
    """frames: list of player arrays. -> (tracks, shifts): tracks = list of lists of (t, i); shifts[t] = the
    camera's estimated move from frame t-1 to t (x, y), applied before matching players."""
    from scipy.optimize import linear_sum_assignment
    tracks, active = [], []          # active: indexes into tracks
    shifts = [np.zeros(2)]
    for t, P in enumerate(frames):
        if t == 0 or not active:
            for i in range(len(P)):
                tracks.append([(t, i)])
            active = list(range(len(tracks)))
            if t:
                shifts.append(np.zeros(2))
            continue
        last = [tracks[k][-1] for k in active]
        prev_pts = np.array([frames[lt][li][:2] for lt, li in last]) if last else np.zeros((0, 2))
        prev_col = np.array([frames[lt][li][3:6] for lt, li in last]) if last else np.zeros((0, 3))
        unit = float(np.median(P[:, 2])) if len(P) else 0.1
        shift = np.zeros(2)
        if len(P) and len(prev_pts):
            # Camera move: median offset between each previous player and the nearest same-colored one now.
            d = np.linalg.norm(prev_pts[:, None, :] - P[None, :, :2], axis=2)
            cd = np.linalg.norm(prev_col[:, None, :] - P[None, :, 3:6], axis=2)
            d_ok = np.where(cd < 60, d, np.inf)
            j = d_ok.argmin(1)
            good = np.isfinite(d_ok[np.arange(len(j)), j]) & (d_ok[np.arange(len(j)), j] < 5 * unit)
            if good.sum() >= 3:
                shift = np.median(P[j[good], :2] - prev_pts[good], axis=0)
        shifts.append(shift)
        if len(P) == 0:
            continue
        pred = prev_pts + shift
        dist = np.linalg.norm(pred[:, None, :] - P[None, :, :2], axis=2) / unit
        cdist = np.linalg.norm(prev_col[:, None, :] - P[None, :, 3:6], axis=2) / 60.0
        # On the court (both ends mapped): real feet, allowing TRACK_MAX_SPEED_FTS per second for every frame
        # since the track was last seen. Otherwise: picture distance after the camera's pan, as before.
        prev_court = np.array([frames[lt][li][10:12] if frames[lt].shape[1] >= 12 else [np.nan, np.nan] for lt, li in last])
        gaps = np.array([t - lt for lt, _ in last], dtype=float)
        court_ok = np.isfinite(prev_court).all(1)[:, None] & (np.isfinite(P[:, 10:12]).all(1)[None, :] if P.shape[1] >= 12 else False)
        if np.any(court_ok):
            dft = np.linalg.norm(prev_court[:, None, :] - P[None, :, 10:12], axis=2)
            reach = (TRACK_MAX_SPEED_FTS / max(fps_, 0.5)) * gaps[:, None]
            dist = np.where(court_ok, dft / np.maximum(reach, 1e-3) * 2.0, dist)   # 2.0 = the old gate, in the same scale
        cost = dist + 0.5 * cdist
        gate = (dist < 2.0) & (cdist < 1.4)
        # never across groups: team A, team B and everyone else stay apart (review: a track ran from a UWW player
        # to an Oshkosh player to a seated bench player)
        if P.shape[1] >= 20:
            prev_grp = np.array([frames[lt][li][19] for lt, li in last])
            known = (prev_grp[:, None] >= 0) & (P[None, :, 19] >= 0)
            gate &= ~known | (prev_grp[:, None] == P[None, :, 19])
        cost = np.where(gate, cost, 1e6)
        ri, ci = linear_sum_assignment(cost)
        used = set()
        new_active = []
        for a, b in zip(ri, ci):
            if cost[a, b] < 1e6:
                tracks[active[a]].append((t, b))
                used.add(b)
                new_active.append(active[a])
        # a track missed for a frame or two stays alive (TRACK_KEEP_ALIVE)
        for a, k in enumerate(active):
            if k not in new_active and tracks[k][-1][0] >= t - max(1, int(round(TRACK_KEEP_ALIVE_S * fps_))):
                new_active.append(k)
        for b in range(len(P)):
            if b not in used:
                tracks.append([(t, b)])
                new_active.append(len(tracks) - 1)
        active = new_active
    return [tr for tr in tracks if len(tr) >= TRACK_MIN_FRAMES], shifts


def _trk_holders(clip, allowed=None):
    """frame -> track holding the ball: the (allowed) player whose body is closest to the ball, within 0.8 of
    a player-height. `allowed` = only these tracks (the offense, once the teams are known) -- the defender
    guarding the ball is often just as close."""
    out = {}
    where = {}
    for k, tr in enumerate(clip["tracks"]):
        if allowed is not None and k not in allowed:
            continue
        for t, j in tr:
            where.setdefault(t, []).append((k, j))
    for t, (bx, by) in clip["ball"].items():
        best, bd = None, np.inf
        for k, j in where.get(t, []):
            row = clip["frames"][t][j]
            x1, y1, x2, y2 = row[6:10]                      # pixels
            H = y2 / max(float(row[1]), 1e-6)               # picture height in pixels (row[1] = feet y / height)
            cx, cy = (x1 + x2) / 2 / H, (y1 + y2) / 2 / H   # body center, in picture-height units like the ball
            dd = np.hypot(cx - bx, cy - by) / max(float(row[2]), 1e-3)
            if dd < bd:
                best, bd = k, dd
        if best is not None and bd < 0.8:
            out[t] = best
    return out


def _trk_embed(crops):
    """PIL crops -> L2-normalized fingerprints (pretrained image model; whole summary + patch average)."""
    import torch
    from transformers import AutoModel
    enc = globals().get("_trk_encoder")
    if enc is None or enc[0] != TRACK_EMBED_MODEL:
        enc = globals()["_trk_encoder"] = (TRACK_EMBED_MODEL, AutoModel.from_pretrained(TRACK_EMBED_MODEL).eval())
    model = enc[1]
    mean, std = np.array([0.485, 0.456, 0.406], np.float32), np.array([0.229, 0.224, 0.225], np.float32)
    out = []
    _t0 = time.time()
    with torch.no_grad():
        for i in range(0, len(crops), 64):
            if i:
                _trk_progress("player crops fingerprinted", i, len(crops), _t0, every=max(64, (len(crops) // 20) // 64 * 64))
            arr = np.stack([((np.asarray(c.convert("RGB").resize((112, 224)), np.float32) / 255 - mean) / std)
                            .transpose(2, 0, 1) for c in crops[i:i + 64]])
            res = model(pixel_values=torch.from_numpy(arr))
            h = res.last_hidden_state
            v = torch.cat([h[:, 0], h[:, 1:].mean(1)], 1).float().numpy()
            out.extend(v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-8))
    if crops:
        _trk_progress("player crops fingerprinted", len(crops), len(crops), _t0)
    return out


def _trk_dist(a, b):
    return float(np.linalg.norm(np.asarray(a[:2]) - np.asarray(b[:2])))


def _trk_pose(rels, base):
    """rel path -> list of (box xyxy, keypoints [17 x (x, y, conf)]); cached like the detections."""
    cpath = _trk_det_cache_path().replace("detections_" + re.sub(r"[^A-Za-z0-9]+", "_", TRACK_DETECTOR),
                                          "pose_" + re.sub(r"[^A-Za-z0-9]+", "_", TRACK_POSE_MODEL))
    cache = pd.read_pickle(cpath) if os.path.exists(cpath) else {}
    todo = [r for r in dict.fromkeys(rels) if r not in cache and os.path.exists(os.path.join(base, r))]
    if todo:
        from ultralytics import YOLO
        m = globals().get("_trk_pose_model")
        if m is None or m[0] != TRACK_POSE_MODEL:
            print(f"  [tracking] loading pose model {TRACK_POSE_MODEL} (downloads once)...")
            m = globals()["_trk_pose_model"] = (TRACK_POSE_MODEL, YOLO(TRACK_POSE_MODEL))
        print(f"  [tracking] reading arm positions in {len(todo)} end-of-clip frame(s)...", flush=True)
        _t0 = time.time()
        H_of = _trk_court_H_lookup(base)
        for i in range(0, len(todo), 8):
            chunk = todo[i:i + 8]
            _trk_progress("end-of-clip frames read", min(i + 8, len(todo)), len(todo), _t0,
                          every=max(8, (len(todo) // 20) // 8 * 8))
            res = _trk_tiled_predict(m[1], [os.path.join(base, x) for x in chunk], H_of, None, TRACK_PERSON_CONF,
                                     keypoints=True)
            for r, found in zip(chunk, res):
                cache[r] = [(box, kk) for box, _c, _cl, kk in found if kk is not None]
        os.makedirs(TRACK_DIR, exist_ok=True)
        pd.to_pickle(cache, cpath)
    return cache


def _trk_arms_up(box, poses):
    """How far above the shoulders the higher wrist is, in box-heights (the pose matched to `box` by overlap)."""
    x1, y1, x2, y2 = box
    best, biou = None, 0.0
    for pb, kp in poses:
        ix = max(0, min(x2, pb[2]) - max(x1, pb[0]))
        iy = max(0, min(y2, pb[3]) - max(y1, pb[1]))
        inter = ix * iy
        iou = inter / max((x2 - x1) * (y2 - y1) + (pb[2] - pb[0]) * (pb[3] - pb[1]) - inter, 1e-6)
        if iou > biou:
            best, biou = kp, iou
    if best is None or biou < 0.4:
        return None
    sh = [best[i][1] for i in (5, 6) if best[i][2] > 0.3]
    wr = [best[i][1] for i in (9, 10) if best[i][2] > 0.3]
    if not sh or not wr:
        return None
    return (min(sh) - min(wr)) / max(y2 - y1, 1e-6)


def _trk_find_screen(clip):
    """Best screen in the clip from the tracks' positions. Returns a dict or None."""
    frames, tracks, side, shifts, holder = clip["frames"], clip["tracks"], clip["side"], clip["shifts"], clip["holder"]
    pos = {}   # track -> {t: (x, y) with the camera's accumulated move removed}
    cum = np.cumsum(np.array(shifts), axis=0)
    for k, tr in enumerate(tracks):
        pos[k] = {t: frames[t][i][:2] - cum[t] for t, i in tr}
    units = [float(np.median(f[:, 2])) if len(f) else np.nan for f in frames]
    off = [k for k in range(len(tracks)) if side.get(k) == "offense"]
    dfn = [k for k in range(len(tracks)) if side.get(k) == "defense"]
    best = None
    # half-second steps, so "standing still" / "moving" mean the same thing at any tracking rate (tuned at 2 a second)
    st = max(1, int(round(float(clip.get("fps", 2.0)) / 2.0)))
    # only up to the finish (clips run on after the play; a "screen" in the next possession isn't this play's)
    t_end = min(len(frames) - 1, int(clip.get("t_finish", len(frames))) + 2)
    for t in range(1, t_end):
        u = units[t]
        if not np.isfinite(u):
            continue
        for s in off:
            # the screener doesn't have the ball around this moment
            if t not in pos[s] or any(holder.get(tt) == s for tt in range(t - 2 * st, t + 3 * st)):
                continue
            sp = [pos[s][tt] for tt in (t - st, t + st) if tt in pos[s]]
            speed = (max(_trk_dist(pos[s][t], q) for q in sp) / u) if sp else 9
            if speed > 0.6:                                    # a screener is (nearly) set
                continue
            for d in dfn:
                if t not in pos[d]:
                    continue
                gap = _trk_dist(pos[s][t], pos[d][t]) / u
                if gap > 0.9:                                  # screener and defender in contact
                    continue
                # Whom was this defender guarding just before? The offensive player he stayed closest to.
                man, man_d = None, np.inf
                for c in off:
                    if c == s:
                        continue
                    ds = [_trk_dist(pos[d][tt], pos[c][tt]) / units[tt] for tt in range(max(0, t - 3 * st), t)
                          if tt in pos[d] and tt in pos[c] and np.isfinite(units[tt])]
                    if ds and np.mean(ds) < man_d:
                        man, man_d = c, float(np.mean(ds))
                if man is None or man_d > 1.5 or t not in pos[man]:
                    continue
                if _trk_dist(pos[man][t], pos[s][t]) / u > 2.0:   # the screened player comes by the screen
                    continue
                # ...and is the one MOVING (coming off it), unless he has the ball (a ball screen can be waited on)
                msp = [pos[man][tt] for tt in (t - st, t + st) if tt in pos[man]]
                man_speed = (max(_trk_dist(pos[man][t], q) for q in msp) / u) if msp else 0
                if man_speed <= speed and holder.get(t) != man:
                    continue
                score = (0.9 - gap) + (1.0 if holder.get(t) == man else 0.0) + (1.5 - man_d) / 1.5
                if best is None or score > best["score"]:
                    # The screener's own defender: the other defender closest to him just before.
                    sd, sd_d = None, np.inf
                    for d2 in dfn:
                        if d2 == d:
                            continue
                        ds = [_trk_dist(pos[d2][tt], pos[s][tt]) / units[tt] for tt in range(max(0, t - 3 * st), t + 1)
                              if tt in pos[d2] and tt in pos[s] and np.isfinite(units[tt])]
                        if ds and np.mean(ds) < sd_d:
                            sd, sd_d = d2, float(np.mean(ds))
                    best = {"t": t, "screener": s, "screened": man, "screened_defender": d,
                            "screener_defender": sd if sd_d < 2.5 else None,
                            "type": "Ball screen" if holder.get(t) == man else "Off-ball screen", "score": score}
    return best


def _trk_five(v):
    return [p.strip() for p in v.split(",") if p.strip()] if isinstance(v, str) else []


def _trk_clip_key(r):
    return f"{r.get('game_date')}|{r.get('clip_number')}|{r.get('synergy_string')}"


def player_tracking(pc):
    """Runs everything on the clips in pc that have tracking frames. Returns (per-clip columns, tracks table,
    report rows)."""
    from PIL import Image
    base = VISION_FRAMES_DIR if "VISION_FRAMES_DIR" in globals() else os.path.join(INPUT_DIR, "_vision_frames")
    tf = pc.get("track_files", pd.Series(index=pc.index, dtype=object)).map(lambda v: v if isinstance(v, str) else "")
    lists = tf.map(lambda s: [x for x in s.split(";") if x])
    todo = [i for i in pc.index if len(lists[i]) >= 4]
    if not todo:
        return None, pd.DataFrame(), []
    print(f"  [tracking] step 1: player and ball detections for {len(todo)} clip(s) "
          f"({sum(len(lists[i]) for i in todo):,} frames; saved ones are reused)...", flush=True)
    det = _trk_detect([f for i in todo for f in lists[i]], base)
    court_H = {}
    if TRACK_USE_COURT:
        _cp = os.path.join(TRACK_DIR, "court_homographies.pkl")
        if os.path.exists(_cp):
            court_H = {k: v for k, v in pd.read_pickle(_cp).items() if not str(k).startswith("_") and v is not None}
        n_cf = sum(1 for i in todo for f in lists[i] if f in court_H)
        globals()["_trk_court_frames_used"] = n_cf
        n_all_f = sum(len(lists[i]) for i in todo)
        print(f"  [tracking]   court mapping available for {n_cf:,} of {n_all_f:,} frame(s)"
              + ("" if n_cf else " -- run the Court mapping cell, then rerun from this cell to use it"), flush=True)
    _fps = VISION_TRACK_FPS if "VISION_TRACK_FPS" in globals() and VISION_TRACK_FPS else 2.0

    # --- per clip: players; then team groups for the whole game; then tracks ---
    print(f"  [tracking] step 2: finding the players in {len(todo)} clip(s) and sorting them into teams...", flush=True)
    jfeat = _trk_jersey_feats([f for i in todo for f in lists[i]], det, base)
    _n_open = int(round(float(globals().get("TRACK_INBOUND_OPEN_S", 2.0)) * float(globals().get("VISION_TRACK_FPS") or 2.0)))
    frames_of = {i: [_trk_players(det.get(f), court_H.get(f), jfeat.get(f), opening=(t_ < _n_open))
                     for t_, f in enumerate(lists[i])] for i in todo}
    # seated / partly hidden people: shorter than a standing player at the same picture row
    _n_seated = 0
    for g_ in set(f"{pc.at[i, 'game_date']}|{pc.at[i, 'game_code']}" for i in todo):
        ids_ = [i for i in todo if f"{pc.at[i, 'game_date']}|{pc.at[i, 'game_code']}" == g_]
        rows_ = [f for i in ids_ for f in frames_of[i] if len(f)]
        if not rows_:
            continue
        allr = np.vstack(rows_)
        y2, hpx = allr[:, 9], allr[:, 9] - allr[:, 7]
        edges = np.linspace(y2.min(), y2.max(), 13)
        pts = [(0.5 * (a + b), np.percentile(hpx[(y2 >= a) & (y2 < b)], 70)) for a, b in zip(edges[:-1], edges[1:])
               if ((y2 >= a) & (y2 < b)).sum() > 20]
        if len(pts) < 3:
            continue
        coef = np.polyfit([p[0] for p in pts], [p[1] for p in pts], 1)
        for i in ids_:
            for t_, f in enumerate(frames_of[i]):
                if len(f):
                    keep_ = (f[:, 9] - f[:, 7]) >= TRACK_MIN_STANDING * np.polyval(coef, f[:, 9])
                    X_, Y_ = f[:, 10], f[:, 11]
                    inside = np.isfinite(X_) & (X_ >= TRACK_EDGE_ZONE_FT) & (X_ <= 94 - TRACK_EDGE_ZONE_FT) \
                        & (Y_ >= TRACK_EDGE_ZONE_FT) & (Y_ <= 50 - TRACK_EDGE_ZONE_FT)
                    keep_ |= inside                   # out on the floor nobody is seated
                    _n_seated += int((~keep_).sum())
                    frames_of[i][t_] = f[keep_]
    print(f"  [tracking]   set aside {_n_seated:,} seated or partly hidden people (shorter than a standing player there)", flush=True)
    from sklearn.cluster import KMeans
    game_of = {i: f"{pc.at[i, 'game_date']}|{pc.at[i, 'game_code']}" for i in todo}
    team_color = {}
    for g in set(game_of.values()):
        ids = [i for i in todo if game_of[i] == g]
        rows_ = [f[np.isfinite(f[:, 14:19]).all(1)] for i in ids for f in frames_of[i] if len(f)]
        allr = np.vstack(rows_) if rows_ else np.zeros((0, 20))
        if len(allr) < 30:
            continue
        km = KMeans(n_clusters=3, n_init=10, random_state=0).fit(_trk_group_feat(allr))
        c_ = km.cluster_centers_
        # everyone-else = light shirt over dark pants, not warm (referees' black pants, coaches, fans)
        other = int(np.argmax((c_[:, 0] - c_[:, 2]) - np.abs(c_[:, 1] / 2)))
        teams_ = [c for c in range(3) if c != other]
        lab = {teams_[0]: "A", teams_[1]: "B", other: "ref"}
        code = {teams_[0]: 0.0, teams_[1]: 1.0, other: 2.0}
        team_color[g] = (km, lab)
        # CONFIRMED CHANGE (coach: not all 5 players had a box). Frame by frame, some players were sorted into the WRONG
        # team (e.g. a gold-and-black Oshkosh player labelled with the white UWW group when his chest patch caught bright
        # floor) -- he was then missing from his own team, and his track split in two ("never across teams"). A
        # detection whose colors are about as close to the other team as to its own is now UNSURE (-1): it links
        # freely, and each track's team is decided by the majority of its frames.
        for i in ids:
            for f in frames_of[i]:
                ok = np.isfinite(f[:, 14:19]).all(1) if len(f) else np.zeros(0, bool)
                if ok.any():
                    F_ = _trk_group_feat(f[ok])
                    dd = np.linalg.norm(F_[:, None, :] - km.cluster_centers_[None, :, :], axis=2)
                    lab_ = dd.argmin(1)
                    srt = np.sort(dd, 1)
                    unsure = srt[:, 0] > TRACK_TEAM_SURE_RATIO * srt[:, 1]
                    vals = np.array([code[int(x)] for x in lab_], float)
                    vals[unsure & (vals != 2.0)] = -1.0      # unsure between the two TEAMS -> no team this frame
                    f[ok, 19] = vals
    print(f"  [tracking] step 3: following players through {len(todo)} clip(s) (never across teams)...", flush=True)
    clips = {}
    _t0 = time.time()
    for _n_clip, i in enumerate(todo, 1):
        _trk_progress("clips tracked", _n_clip, len(todo), _t0)
        frames = frames_of[i]
        tracks, shifts = _trk_link(frames, _fps)
        ball = {}
        for t, f in enumerate(lists[i]):
            d = det.get(f)
            if d is None or not len(d["b"]):
                continue
            bx, by, _c = d["b"][d["b"][:, 2].argmax()]
            ball[t] = (bx / d["H"], by / d["H"])
        clip = {"frames": frames, "tracks": tracks, "shifts": shifts, "ball": ball, "files": lists[i], "fps": _fps}
        clip["basket"], clip["t_finish"], clip["window"] = _trk_finish(frames)
        clip["holder"] = _trk_holders(clip)
        g = game_of[i]
        if g in team_color:
            lab = {0.0: "A", 1.0: "B", 2.0: "ref"}
            clip["team"] = {}
            for k, tr in enumerate(tracks):
                labs = [lab.get(float(frames[t][j][19])) for t, j in tr]
                labs = [x for x in labs if x] or ["ref"]          # unsure frames don't vote
                clip["team"][k] = max(set(labs), key=labs.count)
        clips[i] = clip

    _n_det = sum(len(det[f]["p"]) for i in todo for f in lists[i] if det.get(f) is not None)
    _n_keep = sum(len(f) for i in todo for f in clips[i]["frames"])
    _n_players = sum(1 for i in todo for f in clips[i]["frames"] for r_ in f if r_[19] in (0.0, 1.0))
    print(f"  [tracking]   kept {_n_keep:,} of {_n_det:,} people detected ({_n_players / max(sum(len(lists[i]) for i in todo), 1):.1f} "
          f"players per frame after setting aside referees/coaches/fans); "
          f"{sum(len(clips[i]['tracks']) for i in todo):,} tracks, "
          f"{sum(len(clips[i]['tracks']) for i in todo) / max(len(todo), 1):.1f} per clip (10 players + 3 refs is ideal)", flush=True)

    # --- anchors: the Synergy-named player = the track with the ball late in the clip ---
    print("  [tracking] step 4: finding the Synergy-named player in each clip (ball, then shooting pose)...", flush=True)
    votes = {}   # (game, team name) -> Counter of color label
    for i in todo:
        clip = clips[i]
        n = len(clip["frames"])
        late = [clip["holder"][t] for t in clip["holder"] if t in clip["window"]]
        clip["anchor"] = None
        if late:
            k = max(set(late), key=late.count)
            name = pc.at[i, "player"].strip() if isinstance(pc.at[i, "player"], str) else ""
            five = _trk_five(pc.at[i, "offense_lineup"])
            if late.count(k) >= 2 and name and (not five or name in five) and clip.get("team", {}).get(k) in ("A", "B"):
                clip["anchor"] = (k, name)
                key = (game_of[i], str(pc.at[i, "offense_team"]))
                votes.setdefault(key, {}).setdefault(clip["team"][k], 0)
                votes[key][clip["team"][k]] += 1
    color_of_team = {}
    for (g, team), v in votes.items():
        color_of_team[(g, team)] = max(v, key=v.get)
    color_source = {g: "anchors (ball)" for g, _ in color_of_team}
    # CONFIRMED BUG (fixed): the ball-based votes decided which jersey color is which team whenever any existed,
    # and on the full Oshkosh game (ball seen in 110 clips) they got it backwards -- most tracks landed on the
    # wrong team. The override (TRACK_TEAM_COLORS) and the home-wears-light rule now come FIRST; the ball votes
    # only decide when neither applies, and a disagreement is printed. (Review of the first 5 possessions: with
    # the home rule, 90 of 91 player tracks were on the right team.)
    ball_votes = dict(color_of_team)
    for g, (km_, lab) in team_color.items():
        teams = sorted({str(pc.at[i, c]) for i in todo if game_of[i] == g for c in ("offense_team", "defense_team")})
        if len(teams) != 2:
            continue
        idx = {v: k for k, v in lab.items()}
        bright = {x: float(km_.cluster_centers_[idx[x]][0]) * 3 for x in ("A", "B")}   # feature 0 = lightness
        light, dark = (("A", "B") if bright["A"] >= bright["B"] else ("B", "A"))
        light_team = None
        for t in teams:   # manual override first
            for key_, val in TRACK_TEAM_COLORS.items():
                if str(key_).lower() in t.lower():
                    light_team = t if val == "light" else next(x for x in teams if x != t)
        src = "override (TRACK_TEAM_COLORS)"
        if light_team is None and TRACK_HOME_WEARS_LIGHT:
            code = str(next((pc.at[i, "game_code"] for i in todo if game_of[i] == g), ""))
            uww = next((t for t in teams if "whitewater" in t.lower()), None)
            if uww and "@" in code:
                home_is_uww = code.split("@")[-1].strip().upper() == TRACK_UWW_GAME_CODE.upper()
                light_team = uww if home_is_uww else next(t for t in teams if t != uww)
                src = f"home team wears light ({light_team})"
        if light_team:
            dark_team = next(t for t in teams if t != light_team)
            if ball_votes.get((g, light_team)) not in (None, light) or ball_votes.get((g, dark_team)) not in (None, dark):
                print(f"  [tracking]   note: the ball-based guess disagreed with '{src}' for {g} -- using {src}", flush=True)
            color_of_team[(g, light_team)], color_of_team[(g, dark_team)] = light, dark
            gap = abs(bright["A"] - bright["B"])
            color_source[g] = src + ("" if gap > 60 else " -- jerseys look similar in brightness, check the images")
    for i in todo:
        clip, g = clips[i], game_of[i]
        oc = color_of_team.get((g, str(pc.at[i, "offense_team"])))
        dc = color_of_team.get((g, str(pc.at[i, "defense_team"])))
        if oc is None and dc in ("A", "B"):
            oc = "B" if dc == "A" else "A"
        clip["side"] = {k: ("offense" if lab == oc else "defense") if lab in ("A", "B") and oc else None
                        for k, lab in clip.get("team", {}).items()}

    # Now that the offense is known: the ball holder is looked for among the OFFENSE only, and each clip's
    # anchor is re-picked from that -- a defender hugging the ball can't become the named player.
    for i in todo:
        clip = clips[i]
        offk = {k for k, sd in clip["side"].items() if sd == "offense"}
        if not offk:
            clip["anchor"] = None
            continue
        clip["holder"] = _trk_holders(clip, allowed=offk)
        n = len(clip["frames"])
        late = [clip["holder"][t] for t in clip["holder"] if t in clip["window"]]
        name = pc.at[i, "player"].strip() if isinstance(pc.at[i, "player"], str) else ""
        five = _trk_five(pc.at[i, "offense_lineup"])
        clip["anchor"] = None
        if late and name and (not five or name in five):
            k = max(set(late), key=late.count)
            if late.count(k) >= 2:
                clip["anchor"] = (k, name)

    # Finish at the rim, no anchor yet -> the offensive player closest to the attacked basket at the end.
    anchors_rim = 0
    for i in (todo if TRACK_USE_RIM_ANCHORS else []):
        clip = clips[i]
        if clip["anchor"] is not None:
            continue
        syn, res = str(pc.at[i, "synergy_string"] or ""), str(pc.at[i, "result"] or "")
        if not (re.search(r"Basket|Layup|At Rim|Putback|Dunk|Tip", syn, re.I) or re.search(r"\b(Make|Miss)\w*\s+2\s*Pts", res, re.I)):
            continue
        name = pc.at[i, "player"].strip() if isinstance(pc.at[i, "player"], str) else ""
        five = _trk_five(pc.at[i, "offense_lineup"])
        if not name or (five and name not in five):
            continue
        basket = clip["basket"]
        if basket is None:
            continue
        near = {}
        for k, tr in enumerate(clip["tracks"]):
            if clip["side"].get(k) != "offense":
                continue
            for t, j in tr:
                if t not in clip["window"]:
                    continue
                X, Y = clip["frames"][t][j][10:12]
                if np.isfinite(X) and np.hypot(X - basket[0], Y - basket[1]) <= TRACK_RIM_ANCHOR_FT:
                    near[k] = near.get(k, 0) + 1
        if near:
            k = max(near, key=near.get)
            clip["anchor"] = (k, name)
            clip["anchor_by"] = "rim"
            anchors_rim += 1
    print(f"  [tracking]   anchors from a finish at the rim: {anchors_rim}"
          + ("" if TRACK_USE_RIM_ANCHORS else " (switched off -- TRACK_USE_RIM_ANCHORS)"), flush=True)

    # No ball-based anchor on a shot clip -> the offensive player with his arms up at the end is the shooter.
    anchors_pose = 0
    if TRACK_USE_POSE_ANCHORS:
        shot_clips = [i for i in todo if clips[i]["anchor"] is None
                      and re.search(r"\b(Make|Miss)\w*\s+[23]\s*Pts", str(pc.at[i, "result"] or ""), re.I)
                      and any(sd == "offense" for sd in clips[i]["side"].values())]
        late_files = {i: [clips[i]["files"][t] for t in clips[i]["window"]] for i in shot_clips}
        poses = _trk_pose([f for fl in late_files.values() for f in fl], base) if shot_clips else {}
        for i in shot_clips:
            clip = clips[i]
            name = pc.at[i, "player"].strip() if isinstance(pc.at[i, "player"], str) else ""
            five = _trk_five(pc.at[i, "offense_lineup"])
            if not name or (five and name not in five):
                continue
            score = {}
            for k, tr in enumerate(clip["tracks"]):
                if clip["side"].get(k) != "offense":
                    continue
                for t, j in tr:
                    if t not in clip["window"]:
                        continue
                    a = _trk_arms_up(clip["frames"][t][j][6:10], poses.get(clip["files"][t], []))
                    if a is not None:
                        score[k] = max(score.get(k, -9), a)
            ranked = sorted(score.items(), key=lambda x: -x[1])
            if ranked and ranked[0][1] >= 0.15 and (len(ranked) == 1 or ranked[0][1] - ranked[1][1] >= 0.08):
                clip["anchor"] = (ranked[0][0], name)
                clip["anchor_by"] = "pose"
                anchors_pose += 1

    # No ball seen but Synergy says who had it: on "P&R Ball Handler" / "Isolation" / "Hand Off" / "Post-Up"
    # clips the named player IS the ball handler, so his (anchored) track holds the ball -- that's what lets a
    # screen be recognized as a BALL screen without seeing the ball.
    # CONFIRMED BUG (fixed): when Synergy names TWO players ("24 Richie Warren > P&R Ball Handler > ... > 32 Luke Bara
    # > ..."), the anchor is the LAST one (Bara, who finished), but the ball handler is the FIRST (Warren) -- so this
    # rule only applies when the description names one player.
    for i in todo:
        clip = clips[i]
        if clip["holder"] or not clip["anchor"]:
            continue
        ss_ = str(pc.at[i, "synergy_string"] or "")
        if len(_trk_synergy_names(ss_)) == 1 and re.search(r"P&R Ball Handler|Isolation|\bISO\b|Hand Off|Post-Up", ss_):
            k = clip["anchor"][0]
            clip["holder"] = {t: k for t, _ in clip["tracks"][k]}
            clip["holder_from"] = "synergy"

    # EVERY player Synergy names (requested: "we know who was part of those plays"). Beyond the last-named finisher
    # (the anchor), the FIRST-named player had the ball early: the offensive player seen holding it most in the first
    # part of the clip is him -- a second anchor, often a different player.
    n_first = 0
    for i in todo:
        clip = clips[i]
        names_ = _trk_synergy_names(pc.at[i, "synergy_string"])
        clip["anchor_first"] = None
        if len(names_) < 2 or names_[0] == names_[-1]:
            continue
        five = _trk_five(pc.at[i, "offense_lineup"])
        if five and names_[0] not in five:
            continue
        offk = {k for k, sd in clip["side"].items() if sd == "offense"}
        early = [k for t, k in clip["holder"].items() if k in offk and t <= max(2, int(0.35 * len(clip["frames"])))]
        if not early:
            continue
        k = max(set(early), key=early.count)
        if early.count(k) >= 2 and not (clip["anchor"] and clip["anchor"][0] == k):
            clip["anchor_first"] = (k, names_[0])
            n_first += 1
    print(f"  [tracking]   anchors from the FIRST player Synergy names (the early ball handler): {n_first}", flush=True)

    # --- coach checks -> the tracks they point at (same frame, same spot on the picture) ---
    coach, coach_flip = {}, set()
    if TRACK_USE_COACH_CHECKS:
        checks = _trk_coach_checks()
        if checks:
            key_to_i = {_trk_clip_key(pc.loc[i]): i for i in todo}
            rep = {}
            for ch in checks:
                how = ch.get("assigned_how") or "not named"
                if ch.get("assigned") is not None or ch.get("verdict") == "not a player":
                    rep.setdefault(how, [0, 0])
                    rep[how][1] += 1
                    rep[how][0] += int(ch.get("verdict") == "correct")
                i = key_to_i.get(ch.get("clip_key"))
                if i is None:
                    continue
                t = int(ch.get("t", -1))
                if not 0 <= t < len(clips[i]["frames"]):
                    continue
                best = None
                for k, tr in enumerate(clips[i]["tracks"]):
                    for tt, j in tr:
                        if tt == t:
                            row = clips[i]["frames"][t][j]
                            dpx = float(np.hypot((row[6] + row[8]) / 2 - ch["px"], row[9] - ch["py"]))
                            if dpx < 25 and (best is None or dpx < best[0]):
                                best = (dpx, k)
                if best is not None:
                    if ch.get("verdict") == "wrong team":
                        # CONFIRMED CHANGE (requested: a "wrong team" option in the player review): the box is a player
                        # of the OTHER team -- move the track there; if the coach picked who it is, that's certain too
                        coach_flip.add((i, best[1]))
                        if ch.get("true_name"):
                            coach[(i, best[1])] = ch["true_name"]
                        continue
                    coach[(i, best[1])] = ch.get("true_name") if ch.get("verdict") != "not a player" else None
            print(f"  [tracking]   coach checks: {len(checks)} saved, {len(set(coach) | coach_flip)} matched to this run's tracks. How often each "
                  f"naming method was RIGHT on the boxes checked: " + "; ".join(
                      f"{h} {r}/{n} ({100 * r / max(n, 1):.0f}%)" for h, (r, n) in sorted(rep.items(), key=lambda x: -x[1][1])),
                  flush=True)
            for (i, k), n in coach.items():
                if n is None:
                    clips[i]["side"][k] = None                    # coach: not a player -> never named
            _other_team = {"A": "B", "B": "A"}
            for (i, k) in coach_flip:
                sd = clips[i]["side"].get(k)
                if sd in ("offense", "defense"):
                    clips[i]["side"][k] = "defense" if sd == "offense" else "offense"
                if clips[i].get("team", {}).get(k) in _other_team:
                    clips[i]["team"][k] = _other_team[clips[i]["team"][k]]
            if coach_flip:
                print(f"  [tracking]   coach checks: {len(coach_flip)} player(s) moved to the other team (\"wrong team\")",
                      flush=True)

    # --- fingerprints for every track on a known side ---
    # CONFIRMED CHANGE (requested: the run sat on "fingerprinting 16858 player crop(s)" with no sign of life).
    # Progress is printed, and every crop's fingerprint is SAVED (_tracking/fingerprints_<model>.pkl, keyed by
    # frame + box), so a rerun only fingerprints crops it hasn't seen before.
    n_anch = sum(1 for i in todo if clips[i]["anchor"])
    print(f"  [tracking]   named anchors so far: {n_anch} of {len(todo)} clip(s) "
          f"({sum(1 for i in todo if clips[i].get('anchor_by') == 'pose' and clips[i]['anchor'])} by shooting pose)", flush=True)
    if not TRACK_USE_APPEARANCE:
        print("  [tracking] step 5: appearance fingerprints skipped (TRACK_USE_APPEARANCE = False)", flush=True)
        fp = {}
    else:
        print("  [tracking] step 5: cutting out each player for his appearance fingerprint...", flush=True)
        fp_path = os.path.join(TRACK_DIR, f"fingerprints_{re.sub(r'[^A-Za-z0-9]+', '_', TRACK_EMBED_MODEL)}.pkl")
        fp_cache = pd.read_pickle(fp_path) if os.path.exists(fp_path) else {}
        crops, owners, keys = [], [], []
        fps = {}
        img_cache = {}
        _t0 = time.time()
        for _n_clip, i in enumerate(todo, 1):
            _trk_progress("clips cut into player crops", _n_clip, len(todo), _t0)
            clip = clips[i]
            for k, tr in enumerate(clip["tracks"]):
                if not clip["side"].get(k):
                    continue
                pick = [tr[int(x)] for x in np.linspace(0, len(tr) - 1, min(TRACK_EMBED_CROPS, len(tr)))]
                for t, j in pick:
                    f = clip["files"][t]
                    if f not in img_cache:
                        if len(img_cache) > 200:
                            img_cache.clear()
                        img_cache[f] = Image.open(os.path.join(base, f)).convert("RGB")
                    x1, y1, x2, y2 = clip["frames"][t][j][6:10]
                    ck = f"{f}|{int(x1)}|{int(y1)}|{int(x2)}|{int(y2)}"
                    if ck in fp_cache:
                        fps.setdefault((i, k), []).append(fp_cache[ck])
                        continue
                    crops.append(img_cache[f].crop((int(x1), int(y1), int(x2), int(y2))))
                    owners.append((i, k))
                    keys.append(ck)
        n_reused = sum(len(v) for v in fps.values())
        if crops:
            print(f"  [tracking] fingerprinting {len(crops):,} new player crop(s) ({n_reused:,} reused from earlier runs) -- "
                  f"the slowest step on a laptop, progress below...", flush=True)
            for o, ck, v in zip(owners, keys, _trk_embed(crops)):
                fps.setdefault(o, []).append(v)
                fp_cache[ck] = np.asarray(v, dtype=np.float16)
            os.makedirs(TRACK_DIR, exist_ok=True)
            pd.to_pickle(fp_cache, fp_path)
        else:
            print(f"  [tracking]   all {n_reused:,} fingerprints reused from earlier runs", flush=True)
        fp = {o: (np.mean(v, 0) / (np.linalg.norm(np.mean(v, 0)) + 1e-8)) for o, v in fps.items()}

    # --- names: closest profile among the five on the floor, no duplicate names at the same moment ---
    _tau_box = {"v": None}   # similarity below which a track looks like none of the known players (set per game)

    def assign(game_ids, protos, exclude_clip=None):
        names = {}
        for i in game_ids:
            clip = clips[i]
            for sd, col in (("offense", "offense_lineup"), ("defense", "defense_lineup")):
                five = _trk_five(pc.at[i, col])
                ks = [k for k in range(len(clip["tracks"])) if clip["side"].get(k) == sd
                      and ((i, k) in fp or (i, k) in number_names)]
                if not five or not ks:
                    continue
                cand = []
                for k in ks:
                    if (i, k) in number_names:            # the number on his jersey beats everything else
                        cand.append((10.0, k, number_names[(i, k)][0], number_names[(i, k)][1]))
                        continue
                    if clip["anchor"] and clip["anchor"][0] == k and i != exclude_clip:
                        cand.append((9.0, k, clip["anchor"][1], 1.0))
                        continue
                    af = clip.get("anchor_first")
                    if af and af[0] == k and i != exclude_clip:
                        cand.append((9.0, k, af[1], 1.0))
                        continue
                    if (i, k) not in fp:
                        continue
                    sims = np.array([float(fp[(i, k)] @ protos[n]) if n in protos else np.nan for n in five])
                    if np.all(np.isnan(sims)):
                        continue
                    # elimination by appearance: he looks like none of the known players on the floor, and exactly one
                    # of the five has no known look yet -> it's him
                    unknown = [n for n in five if n not in protos]
                    if _tau_box["v"] is not None and len(unknown) == 1 and np.nanmax(sims) < _tau_box["v"]:
                        cand.append((0.6, k, unknown[0], 0.6))
                        continue
                    z = np.nan_to_num((sims - np.nanmean(sims)) / (np.nanstd(sims) + 1e-6), nan=-1.0)
                    p = np.exp(3 * z) / np.exp(3 * z).sum()
                    order = np.argsort(-p)
                    for rank, o in enumerate(order[:2]):
                        cand.append((float(p[o]) - rank * 1e-3, k, five[o], float(p[o])))
                taken = {}   # name -> list of frame sets already using it
                for score, k, n, conf in sorted(cand, reverse=True):
                    if (i, k) in names or conf < TRACK_NAME_MIN_CONF:
                        continue
                    tset = {t for t, _ in clip["tracks"][k]}
                    if any(tset & other for other in taken.get(n, [])):
                        continue
                    names[(i, k)] = (n, conf)
                    taken.setdefault(n, []).append(tset)
        return names

    # jersey numbers come from each clip's OWN game (see _trk_numbers_for_game)
    _game_nums, _num_conflicts = {}, []
    def _numfor(i, n):
        gk = (str(pc.at[i, "game_date"]), str(pc.at[i, "game_code"]))
        if gk not in _game_nums:
            _game_nums[gk] = _trk_numbers_for_game(*gk, report=_num_conflicts)
        return _game_nums[gk].get(str(n).strip().lower())

    # --- jersey numbers -> names (limited to the five on the floor for that team) ---
    number_names, n_read_tracks = {}, 0
    # CONFIRMED BUG (fixed): with no reader chosen by the reader test (e.g. the trained recognizer not trained yet)
    # this fell back to EasyOCR -- loading it, reading every chest, and (with no test score to check) using its numbers.
    # No reliable reader now means no jersey reading this run.
    _engine = globals().get("JERSEY_READER_BEST") if TRACK_OCR_ENGINE == "auto" else TRACK_OCR_ENGINE
    if TRACK_READ_NUMBERS and not _engine:
        print("  [tracking] step 5b: jersey numbers NOT read -- no reader passed the Jersey-number reader test yet "
              "(train the recognizer: more checks, Roboflow's set, JERSEY_TRAIN_EXTRA_DIRS)", flush=True)
    _prec = (globals().get("JERSEY_READER_PRECISION") or {}).get(_engine)
    _nans = (globals().get("JERSEY_READER_ANSWERS") or {}).get(_engine, 0)
    _acc = (globals().get("JERSEY_READER_ACCURACY") or {}).get(_engine)
    if not _engine:
        _use_numbers = False
    elif _prec is not None:
        _use_numbers = TRACK_READ_NUMBERS and _prec >= TRACK_READER_MIN_PRECISION and _nans >= 6
    else:
        _use_numbers = TRACK_READ_NUMBERS and (_acc is None or _acc >= TRACK_READER_MIN_ACCURACY)
    _min_conf = (globals().get("JERSEY_READER_CONF") or {}).get(_engine, TRACK_OCR_MIN_CONF)
    if TRACK_READ_NUMBERS and not _use_numbers and _engine:
        print(f"  [tracking] step 5b: jersey numbers NOT used -- the best reader ({_engine}) is right "
              f"{(_prec if _prec is not None else _acc or 0):.0%} of the time it answers ({_nans} answers), below "
              f"{TRACK_READER_MIN_PRECISION:.0%}. Players are named only where Synergy names them.", flush=True)
    elif TRACK_READ_NUMBERS and _acc is None:
        print(f"  [tracking]   (the Jersey-number reader test didn't run, so {_engine} is used untested)", flush=True)
    if _use_numbers:
        print(f"  [tracking] step 5b: reading jersey numbers with {_engine}"
              + (f" (right {_prec:.0%} of the time it answers on the answer key; using reads at confidence >= "
                 f"{_min_conf:.1f})" if _prec is not None else (f" (scored {_acc:.0%} on the answer key)" if _acc is not None else ""))
              + "...", flush=True)
        try:
            if _engine == "combined":
                # every member reader, each at its own confidence level; the vote below needs their reads to agree
                reads = {}
                for _me, _mc in globals().get("JERSEY_READER_COMBINED_MEMBERS", []):
                    for o, rd in _trk_read_numbers(clips, todo, base, _me).items():
                        reads.setdefault(o, []).extend((tx, cf) for tx, cf in rd if cf >= _mc)
            else:
                reads = _trk_read_numbers(clips, todo, base, _engine)
                # only reads at or above the confidence where the reader tested >= 85% right
                reads = {o: [(tx, cf) for tx, cf in rd if cf >= _min_conf] for o, rd in reads.items()}
            num_of = {}                                   # player name (lower case) -> jersey number
            book = _pl_jersey_book() if "_pl_jersey_book" in globals() else {}
            for team_book in book.values():
                for j_, n_ in team_book.items():
                    num_of.setdefault(str(n_).strip().lower(), str(j_).strip())
            for ss in pc["synergy_string"].dropna().astype(str):   # Synergy's "24 Richie Warren > ..." wins
                for j_, n_ in re.findall(r"(?:^|>)\s*(\d{1,2})\s+([A-Za-z][^>]*?)\s*(?=>|$)", ss):
                    num_of[n_.strip().lower()] = j_
            for (i, k), rd in reads.items():
                sd = clips[i]["side"].get(k)
                five = _trk_five(pc.at[i, "offense_lineup" if sd == "offense" else "defense_lineup"])
                cand = {_numfor(i, n): n for n in five if _numfor(i, n)}
                if rd:
                    n_read_tracks += 1
                sure = [(txt, cf) for txt, cf in rd if cf >= TRACK_OCR_MIN_CONF]
                # CONFIRMED BUG (fixed; review of the 1024 run): the reader sometimes catches ONE digit of a two-digit
                # number -- "0" off a clear 10 (at 0.95), "2" off 23 -- and that digit was someone else's number (#0 Beck,
                # #2 LaChapell). A single-digit read is AMBIGUOUS when another number on the floor for that team contains
                # it; it never names a track by itself (the lineup matching still weighs it as a shared hint).
                _two = [num for num in cand if len(num) == 2]
                sure = [(txt, cf) for txt, cf in sure if not (len(txt) == 1 and any(txt in num for num in _two))]
                if not sure:
                    continue
                allv = {}
                for txt, cf in sure:
                    allv.setdefault(txt, []).append(cf)
                top, cfs = max(allv.items(), key=lambda kv: (len(kv[1]), max(kv[1])))
                need = TRACK_SINGLE_DIGIT_VOTES if len(top) == 1 else TRACK_NUMBER_MIN_VOTES
                if _prec is not None and _prec >= TRACK_READER_MIN_PRECISION and len(allv) == 1:
                    need = 1        # a reader that is rarely wrong when it answers, and nothing disagrees
                # the winner must be one of the five on the floor, the MAJORITY of every confident read, and have
                # enough agreeing reads (more for single digits)
                if top in cand and len(cfs) >= need and len(cfs) > len(sure) / 2:
                    number_names[(i, k)] = (cand[top], round(min(0.95, 0.6 + 0.1 * len(cfs)), 2))
            # CONFIRMED BUG (fixed; found by the best-guess check): two tracks seen at the SAME moment both read "21" --
            # two different players 20+ ft apart -- and both were named #21. One player can't be on two tracks at once:
            # keep the one with more agreeing reads (then the longer one); the other goes back to the lineup matching.
            _dropped = 0
            for i in {i for (i, _k) in number_names}:
                by_name = {}
                for (ii, k), (n, cf) in number_names.items():
                    if ii == i:
                        by_name.setdefault(n, []).append((cf, len(clips[i]["tracks"][k]), k))
                for n, lst in by_name.items():
                    kept = []
                    for cf, ln, k in sorted(lst, reverse=True):
                        fk = {t for t, _ in clips[i]["tracks"][k]}
                        if any(fk & {t for t, _ in clips[i]["tracks"][o]} for o in kept):
                            number_names.pop((i, k), None)
                            _dropped += 1
                        else:
                            kept.append(k)
            print(f"  [tracking]   a jersey number was read on {n_read_tracks:,} track(s); "
                  f"{len(number_names):,} named by number"
                  + (f" ({_dropped} dropped: the same number read on two players at the same moment)" if _dropped else ""),
                  flush=True)
        except Exception as _e:
            print(f"  [tracking]   jersey numbers not read this run ({type(_e).__name__}: {_e})", flush=True)

    # coach-checked names are certain: they replace any number name on that track, and no other track of that clip
    # may carry the same name at the same moment
    for (i, k), n in coach.items():
        if not n:
            continue
        fk = {t for t, _ in clips[i]["tracks"][k]}
        for (ii, kk) in [key for key, v in number_names.items() if key[0] == i and v[0] == n and key[1] != k]:
            if fk & {t for t, _ in clips[i]["tracks"][kk]}:
                number_names.pop((ii, kk), None)
        number_names[(i, k)] = (n, 0.99)

    # --- play-by-play named events (rebounds, steals, blocks, fouls): anchors for offense AND defense ---
    for i in todo:
        clips[i]["anchors_pbp"] = []
    globals()["trk_event_candidates"] = pd.DataFrame()
    if TRACK_USE_PBP_EVENTS:
        try:
            known = {}
            for i in todo:
                for a in (clips[i]["anchor"], clips[i].get("anchor_first")):
                    if a:
                        known[(i, a[1])] = a[0]
            for (i, k), (n, _c) in number_names.items():
                known.setdefault((i, n), k)
            pa = _trk_pbp_anchors(clips, todo, pc, known, _fps)
            agree = disagree = 0
            _cands_rows = []
            _rd_all = locals().get("reads", {}) or {}
            _nums = locals().get("num_of", {}) or {}
            for i, k, n, et in pa:
                # the track's own jersey readings clearly show a DIFFERENT two-digit number -> not him
                _mine = _numfor(i, n)
                if any(len(tx) == 2 and cf >= 0.5 and tx != _mine for tx, cf in _rd_all.get((i, k), [])):
                    disagree += 1
                    continue
                prior = [nm for (ii, nm), kk in known.items() if ii == i and kk == k]
                if prior:
                    agree += int(n in prior)
                    disagree += int(n not in prior)
                    if n not in prior:
                        continue                                  # conflicts with a name we already trust: skip it
                _cands_rows.append({"clip_key": pc.at[i, "track_clip_key"], "clip_number": pc.at[i, "clip_number"],
                                    "track": int(k), "name": n, "event": et, "game_date": pc.at[i, "game_date"]})
                if TRACK_USE_PBP_EVENTS != "review":
                    clips[i]["anchors_pbp"].append((k, n, et))
            globals()["trk_event_candidates"] = pd.DataFrame(_cands_rows)
            by_type = pd.Series([et for *_x, et in pa]).value_counts().to_dict() if pa else {}
            _types = ", ".join(str(k).replace("_", " ") + " " + str(v) for k, v in by_type.items()) or "none"
            _n_pbp = len(_cands_rows)
            print(f"  [tracking] step 5d: play-by-play events point at {_n_pbp:,} player(s) ({_types}); where the player "
                  f"was already known they agreed {agree} of {agree + disagree} time(s)"
                  + (" -- REVIEW mode: saved for checking, not used for names" if TRACK_USE_PBP_EVENTS == "review" else ""),
                  flush=True)
        except Exception as _e:
            print(f"  [tracking]   play-by-play events not used this run ({type(_e).__name__}: {_e})", flush=True)

    # --- link possessions: the same player across overlapping clips; names travel along the links ---
    link_names = {}
    if TRACK_LINK_POSSESSIONS:
        print("  [tracking] step 5a: linking possessions that show the same moments of the game...", flush=True)
        try:
            group, n_links, n_pairs = _trk_link_possessions(clips, todo, pc, game_of)
            by_group = {}
            for node, gid in group.items():
                by_group.setdefault(gid, []).append(node)
            # what each linked player is called anywhere. CONFIRMED CHANGE (requested, from the player-check results: names
            # carried along linked possessions were right 0 of 5 times, and one wrong name spreads across every clip in the
            # link). With TRACK_LINK_EVIDENCE = "numbers+coach" (the default) ONLY a jersey number or a coach check starts a
            # carried name -- Synergy / rim / pose / play-by-play anchors no longer do. "all" = the old behavior.
            _link_all = str(globals().get("TRACK_LINK_EVIDENCE", "numbers+coach")).lower() == "all"
            for gid, nodes in by_group.items():
                votes = {}
                for (i, k) in nodes:
                    if _link_all:
                        for a in (clips[i]["anchor"], clips[i].get("anchor_first")):
                            if a and a[0] == k:
                                votes[a[1]] = votes.get(a[1], 0) + 1
                        for kk, nn, _et in clips[i].get("anchors_pbp", []):
                            if kk == k:
                                votes[nn] = votes.get(nn, 0) + 1
                    if (i, k) in number_names:
                        votes[number_names[(i, k)][0]] = votes.get(number_names[(i, k)][0], 0) + 1
                    if coach.get((i, k)):                           # a name the coaches checked is certain: it counts double
                        votes[coach[(i, k)]] = votes.get(coach[(i, k)], 0) + 2
                if not votes:
                    continue
                name, sup = max(votes.items(), key=lambda kv: kv[1])
                if sup <= sum(votes.values()) / 2:
                    continue                                     # the evidence disagrees -- don't carry it
                # CONFIRMED BUG (fixed; coach: "the same player is assigned to multiple boxes"). A linked group can merge
                # two DIFFERENT players, so two tracks of one group can be on the floor at the same moment in a clip (e.g.
                # "#24 Warren" on one box by jersey number and on another as "linked possession"). In such a clip only a
                # track with its OWN evidence for the name keeps it; the others get no carried name.
                _by_clip = {}
                for (i, k) in nodes:
                    _by_clip.setdefault(i, []).append(k)
                for i, ks_ in _by_clip.items():
                    fr_ = {k: {t_ for t_, _ in clips[i]["tracks"][k]} for k in ks_}
                    for k in ks_:
                        clash = any(k2 != k and fr_[k] & fr_[k2] for k2 in ks_)
                        own = ((i, k) in number_names and number_names[(i, k)][0] == name) or coach.get((i, k)) == name
                        if _link_all and not own:
                            own = any(a and a[0] == k and a[1] == name for a in (clips[i]["anchor"], clips[i].get("anchor_first"))) \
                                or any(kk == k and nn == name for kk, nn, _et in clips[i].get("anchors_pbp", []))
                        if clash and not own:
                            continue
                        link_names[(i, k)] = (name, sup)
            n_carried = sum(1 for (i, k) in link_names if not (clips[i]["anchor"] and clips[i]["anchor"][0] == k))
            print(f"  [tracking]   {n_pairs:,} pairs of clips meet or overlap in the game video "
                  f"({globals().get('_trk_n_boundaries', 0):,} back-to-back play boundaries); {n_links:,} track links made; "
                  f"{len(by_group):,} linked players; a name reached {n_carried:,} more track(s) through the links", flush=True)
        except Exception as _e:
            print(f"  [tracking]   possessions not linked this run ({type(_e).__name__}: {_e})", flush=True)

    _reads_all = locals().get("reads", {}) or {}
    _num_of_all = locals().get("num_of", {}) or {}
    solved, solve_how = {}, {}
    if TRACK_SOLVE_LINEUPS:
        print("  [tracking] step 5c: matching each team's tracks to its five on the floor (numbers, partial numbers, "
              "anchors, then elimination)...", flush=True)
        _reads = locals().get("reads", {}) or {}
        _num_of = locals().get("num_of", {}) or {}
        def _team_solve(i, sd, use_anchor=True):
            clip = clips[i]
            five = _trk_five(pc.at[i, "offense_lineup" if sd == "offense" else "defense_lineup"])
            five_nums = {n: _numfor(i, n) for n in five if _numfor(i, n)}
            ks = [k for k in range(len(clip["tracks"])) if clip["side"].get(k) == sd]
            if not five or not ks:
                return {}, {}, {}
            score = {k: _trk_read_scores(_reads.get((i, k), []), five_nums) for k in ks}
            for k in ks:
                for n in five:
                    score[k].setdefault(n, 0.0)
            if use_anchor and clip["anchor"] and clip["anchor"][0] in score and clip["anchor"][1] in score[clip["anchor"][0]]:
                score[clip["anchor"][0]][clip["anchor"][1]] += TRACK_ANCHOR_WEIGHT
            af = clip.get("anchor_first")
            if use_anchor and af and af[0] in score and af[1] in score[af[0]]:
                score[af[0]][af[1]] += TRACK_ANCHOR_WEIGHT
            for kk, nn, _et in clip.get("anchors_pbp", []):          # rebound / steal / block / foul
                if kk in score and nn in score[kk]:
                    score[kk][nn] += TRACK_PBP_WEIGHT
            for k in ks:                                          # a name carried from a linked possession
                ln = link_names.get((i, k))
                if ln and ln[0] in score[k] and not (not use_anchor and clip["anchor"] and clip["anchor"][0] == k):
                    score[k][ln[0]] += TRACK_LINK_WEIGHT * min(ln[1], 3)
            got = _trk_solve_team(clip["tracks"], ks, score)
            # weak or tied evidence doesn't name anyone by itself (elimination below can still place him)
            def _clear(k, n):
                ss_ = sorted(score[k].values(), reverse=True)
                second = ss_[1] if len(ss_) > 1 else 0.0
                return score[k][n] >= TRACK_MIN_NAME_EVIDENCE and score[k][n] - (second if ss_[0] == score[k][n] else ss_[0]) >= TRACK_MIN_NAME_MARGIN
            got = {k: n for k, n in got.items() if _clear(k, n)}
            elim = _trk_eliminate(clip["tracks"], ks, five, got)
            return got, elim, score
        n_ev = n_el = 0
        for i in todo:
            for sd in ("offense", "defense"):
                got, elim, score = _team_solve(i, sd)
                for k, n in got.items():
                    tot = sum(score[k].values()) or 1.0
                    solved[(i, k)] = (n, round(float(min(0.95, max(0.4, score[k][n] / tot))), 2))
                    solve_how[(i, k)] = "evidence"
                    n_ev += 1
                for k, n in elim.items():
                    solved[(i, k)] = (n, 0.6)
                    solve_how[(i, k)] = "elimination"
                    n_el += 1
        # honest check: on clips with a Synergy anchor, solve WITHOUT the anchor and see if the anchor's track
        # still gets the anchor's name (both are imperfect -- this measures how often they agree)
        lc = []
        for i in todo:
            a = clips[i]["anchor"]
            if a:
                got, elim, _s = _team_solve(i, "offense", use_anchor=False)
                n_ = got.get(a[0]) or elim.get(a[0])
                if n_:
                    lc.append(n_ == a[1])
        lineup_check = f"{sum(lc)}/{len(lc)}" if lc else "--"
        print(f"  [tracking]   named {n_ev:,} track(s) from evidence ("
              + ("jersey numbers and Synergy anchors" if _use_numbers else "Synergy anchors only -- numbers are off")
              + f") and {n_el:,} more by elimination; "
              f"agreement with Synergy anchors (anchor hidden): {lineup_check}", flush=True)
    else:
        lineup_check = "--"

    if _num_conflicts:
        print("  [tracking]   jersey-number conflicts between sources (this game's number is used): "
              + "; ".join(sorted(set(_num_conflicts))[:8]), flush=True)
    print("  [tracking] step 6: matching every player to the five on the floor...", flush=True)
    report, names_all = [], {}
    _looks_by_game = {}
    for g in sorted(set(game_of.values())):
        ids = [i for i in todo if game_of[i] == g]
        anchors = [(i, clips[i]["anchor"]) for i in ids if clips[i]["anchor"] and (i, clips[i]["anchor"][0]) in fp]
        # CONFIRMED CHANGE (requested: use who is on the court across clips, not just within one). Every track of a team is
        # one of its five on the floor, so each player's LOOK, learned from the tracks we can name for sure, names his
        # other tracks in every clip he plays in. Learned only from TRUSTED names -- jersey numbers, Synergy's ball-based
        # anchors (and verified play-by-play events) -- never from the finish-at-the-rim guesses that taught it wrong
        # faces before.
        seeds = [(i, k, n) for i, (k, n) in anchors]
        seeds += [(i, clips[i]["anchor_first"][0], clips[i]["anchor_first"][1]) for i in ids
                  if clips[i].get("anchor_first") and (i, clips[i]["anchor_first"][0]) in fp]
        seeds += [(i, k, n) for (i, k), (n, _c) in number_names.items() if game_of.get(i) == g and (i, k) in fp]
        seeds += [(i, k, n) for i in ids for k, n, _et in clips[i].get("anchors_pbp", []) if (i, k) in fp]
        seeds = list(dict.fromkeys(seeds))
        protos_raw = {}
        for i, k, n in seeds:
            protos_raw.setdefault(n, []).append((i, fp[(i, k)]))
        norm = lambda vs: (np.mean(vs, 0) / (np.linalg.norm(np.mean(vs, 0)) + 1e-8))
        protos = {n: norm([v for _, v in vs]) for n, vs in protos_raw.items()}
        # how alike the same player looks vs two teammates, from the seeds -> the "looks like none of them" line
        _same, _other = [], []
        for i, k, n in seeds:
            sd = clips[i]["side"].get(k)
            five = _trk_five(pc.at[i, "offense_lineup" if sd == "offense" else "defense_lineup"])
            others = [v for j, v in protos_raw[n] if not (j == i)]
            if others:
                _same.append(float(fp[(i, k)] @ norm(others)))
            _other += [float(fp[(i, k)] @ protos[m]) for m in five if m != n and m in protos]
        _tau_box["v"] = (float(np.median(_same)) + float(np.median(_other))) / 2 if len(_same) >= 6 and len(_other) >= 6 else None
        names = assign(ids, protos)
        # second pass: confident names join the profiles (more views of each player), then reassign
        grow = {}
        for (i, k), (n, c) in names.items():
            if c >= 0.7 and (i, k) in fp:                 # named by number/coach with appearance off: no look to add
                grow.setdefault(n, []).append(fp[(i, k)])
        protos2 = {n: norm([v for _, v in protos_raw.get(n, [])] + grow.get(n, [])) for n in set(protos_raw) | set(grow)}
        _looks_by_game[g] = protos2
        names = assign(ids, protos2)
        print(f"  [tracking]   {g}: {sum(1 for (i, _k) in names if i in ids):,} track(s) named; checking appearance "
              f"against {len(seeds)} trusted name(s)...", flush=True)
        # Honest check: hide each trusted name (and everything its clip taught), let appearance name that track, compare.
        hits = tries = 0
        for i, k, n in seeds:
            pr = {m: norm([v for j, v in vs if j != i]) for m, vs in protos_raw.items() if any(j != i for j, _ in vs)}
            sd = clips[i]["side"].get(k)
            five = _trk_five(pc.at[i, "offense_lineup" if sd == "offense" else "defense_lineup"])
            sims = {m: float(fp[(i, k)] @ pr[m]) for m in five if m in pr}
            if not sims:
                continue
            best = max(sims, key=sims.get)
            unknown = [m for m in five if m not in pr]
            if _tau_box["v"] is not None and len(unknown) == 1 and sims[best] < _tau_box["v"]:
                best = unknown[0]
            tries += 1
            hits += int(best == n)
        # appearance names only when the check had enough trusted names to test against AND passed
        appearance_on = tries >= TRACK_APPEARANCE_MIN_TRIES and hits / tries >= TRACK_APPEARANCE_MIN_CHECK
        if appearance_on:
            print(f"  [tracking]   appearance name check {hits}/{tries} ({hits / tries:.0%}) passes -- appearance names are used",
                  flush=True)
        if not appearance_on:
            keep_names = {(i, k): v for (i, k), v in names.items()
                          if (i, k) in number_names or (clips[i]["anchor"] and clips[i]["anchor"][0] == k)}
            print(f"  [tracking]   appearance name check {hits}/{tries}"
                  + (f" is below {TRACK_APPEARANCE_MIN_CHECK:.0%}" if tries >= TRACK_APPEARANCE_MIN_TRIES
                     else f" -- too few trusted names to check it (needs {TRACK_APPEARANCE_MIN_TRIES})")
                  + ": appearance-only "
                  f"names are left blank ({len(names) - len(keep_names):,} dropped); keeping {len(keep_names):,} "
                  f"named by jersey number or Synergy", flush=True)
            names = keep_names
        # the lineup matching wins wherever it named a track
        for (i, k), v in solved.items():
            if game_of.get(i) == g:
                names[(i, k)] = v
        names_all.update(names)
        # Number check: where a Synergy-based anchor's track ALSO has its jersey number read, do they agree?
        # (low = the anchors themselves are picking the wrong player)
        nc = [(n == number_names[(i, k)][0]) for i, (k, n) in anchors if (i, k) in number_names]
        n_tracks = sum(len(clips[i]["tracks"]) for i in ids)
        n_named = sum(1 for (i, k) in names if i in ids)
        # Where the chain can break, counted (requested after the first real run named nobody).
        with_lineup = [i for i in ids if _trk_five(pc.at[i, "offense_lineup"])]
        in_lineup = sum(1 for i in with_lineup if isinstance(pc.at[i, "player"], str)
                        and pc.at[i, "player"].strip() in _trk_five(pc.at[i, "offense_lineup"]))
        report.append({"game": g, "clips": len(ids), "tracks": n_tracks, "anchors": len(anchors),
                       "anchors_by_pose": sum(1 for i in ids if clips[i].get("anchor_by") == "pose" and clips[i]["anchor"]),
                       "anchors_by_rim": sum(1 for i in ids if clips[i].get("anchor_by") == "rim" and clips[i]["anchor"]),
                       "teams_by_color": color_source.get(g, "no -- no anchors and no home/away rule for this game"),
                       "clips_ball_seen": sum(1 for i in ids if clips[i]["ball"]),
                       "clips_with_lineups": len(with_lineup), "synergy_player_in_lineup": in_lineup,
                       "tracks_named": n_named, "anchor_name_check": f"{hits}/{tries}" if tries else "--",
                       "tracks_named_by_number": sum(1 for (i, k) in number_names if game_of.get(i) == g),
                       "tracks_number_read": n_read_tracks,
                       "anchor_vs_number_check": f"{sum(nc)}/{len(nc)}" if nc else "--",
                       "tracks_named_by_evidence": sum(1 for (i, k), h in solve_how.items() if h == "evidence" and game_of.get(i) == g),
                       "tracks_named_by_elimination": sum(1 for (i, k), h in solve_how.items() if h == "elimination" and game_of.get(i) == g),
                       "lineup_vs_anchor_check": lineup_check,
                       "numbers_used": bool(_use_numbers)})

    # --- one name per player at any moment ---------------------------------------------------------------------------
    # CONFIRMED BUG (fixed; coach: "we're still getting the same player assigned to multiple boxes" -- #24 Warren on two
    # defenders in one picture, one by jersey number, one as "linked possession"). The names come from several sources
    # (jersey reads, anchors, the lineup solver, appearance, links) that were each unique on their own but never checked
    # against EACH OTHER. Now, in every clip, two tracks that are on the floor at the same moment can't share a name: the
    # one with the stronger evidence keeps it (coach check > jersey number > Synergy anchor > play-by-play event > lineup
    # evidence > elimination > appearance > carried from a linked possession), the other is left unnamed here and the
    # best guess below can give it one of the names still free.
    def _name_rank(i, k, n, c):
        if coach.get((i, k)) == n:
            r = 100
        elif (i, k) in number_names and number_names[(i, k)][0] == n:
            r = 90
        elif any(a and a[0] == k and a[1] == n for a in (clips[i]["anchor"], clips[i].get("anchor_first"))):
            r = 80
        elif any(kk == k and nn == n for kk, nn, _e in clips[i].get("anchors_pbp", [])):
            r = 70
        elif solve_how.get((i, k)) == "evidence":
            r = 60
        elif solve_how.get((i, k)) == "elimination":
            r = 50
        elif link_names.get((i, k), (None,))[0] == n:
            r = 30
        else:
            r = 40
        return r + float(c or 0.0)
    n_dup = 0
    for i in todo:
        clip = clips[i]
        by_name = {}
        for k in range(len(clip["tracks"])):
            v = names_all.get((i, k))
            if v and v[0]:
                by_name.setdefault(v[0], []).append(k)
        for n, ks_ in by_name.items():
            if len(ks_) < 2:
                continue
            fr_ = {k: {t_ for t_, _ in clip["tracks"][k]} for k in ks_}
            kept = []
            for k in sorted(ks_, key=lambda k: (_name_rank(i, k, n, names_all[(i, k)][1]), len(fr_[k])), reverse=True):
                if any(fr_[k] & fr_[k2] for k2 in kept):
                    names_all.pop((i, k), None)
                    n_dup += 1
                else:
                    kept.append(k)
    print(f"  [tracking]   {n_dup:,} track(s) lost a name they shared with another track on the floor at the same moment "
          f"(the track with the stronger evidence keeps it)", flush=True)

    # --- best guess: every one of the five on the floor gets a track (the lineup is known; clues pick who is who) ---
    guessed = set()
    if TRACK_BEST_GUESS:
        for i in todo:
            clip = clips[i]
            g = game_of.get(i)
            looks = _looks_by_game.get(g, {})
            for sd in ("offense", "defense"):
                five = _trk_five(pc.at[i, f"{sd}_lineup"])
                ks = [k for k in range(len(clip["tracks"])) if clip["side"].get(k) == sd]
                if not five or not ks:
                    continue
                named = {k: names_all[(i, k)][0] for k in ks if (i, k) in names_all}
                free = [k for k in ks if k not in named]
                if not free:
                    continue
                frames_of = {k: {t for t, _ in clip["tracks"][k]} for k in ks}
                five_nums = {n: _numfor(i, n) for n in five if _numfor(i, n)}
                like = {k: _trk_player_likeness(clip, k) for k in free}
                score = {}
                for k in free:
                    rd = _trk_read_scores(_reads_all.get((i, k), []), five_nums) if five_nums else {}
                    score[k] = {}
                    for n in five:
                        # a name already on a track seen at the same moment is taken for this one
                        if any(nm_ == n and frames_of[k] & frames_of[kk] for kk, nm_ in named.items()):
                            score[k][n] = -1e6                          # taken at the same moment: never chosen
                            continue
                        sc = 1.0                                        # every lineup name is possible
                        if (i, k) in fp and n in looks:                # looks like him (0..0.5)
                            sc += 0.25 * (1.0 + float(fp[(i, k)] @ looks[n]))
                        sc += rd.get(n, 0.0)                            # partial / uncertain jersey reads
                        ln = link_names.get((i, k))
                        if ln and ln[0] == n:                           # carried from a linked possession
                            sc += 0.5
                        sc += TRACK_LIKENESS_WEIGHT * like[k]           # a player-like track before a sideline figure
                        # weighted by how LONG the track is: the goal is to name as much of the play as possible
                        # (review: five short fragments each took a name, so a player tracked through the whole clip
                        # overlapped all five somewhere and got none)
                        score[k][n] = sc * len(clip["tracks"][k])
                got = _trk_solve_team(clip["tracks"], free, score)
                for k, n in got.items():
                    names_all[(i, k)] = (n, TRACK_BEST_GUESS_CONF)
                    guessed.add((i, k))
        print(f"  [tracking] step 6b: best guesses from the lineup for {len(guessed):,} more track(s) "
              f"(marked \"best guess\" -- confidence {TRACK_BEST_GUESS_CONF})", flush=True)
        # every track still without a name, in a clip whose five are known, can't be a 6th player: not a player
        n_set_aside = 0
        for i in todo:
            clip = clips[i]
            for sd in ("offense", "defense"):
                if not _trk_five(pc.at[i, f"{sd}_lineup"]):
                    continue
                for k in range(len(clip["tracks"])):
                    if clip["side"].get(k) == sd and (i, k) not in names_all:
                        clip["side"][k] = None
                        n_set_aside += 1
        print(f"  [tracking]   {n_set_aside:,} track(s) beyond the five on the floor set aside as not players "
              f"(referees, coaches, sideline) -- no unnamed players remain where the lineup is known", flush=True)

    # --- screens + per-clip columns ---
    out = pd.DataFrame(index=pc.index, columns=_TRACK_COLS, dtype=object)
    rows = []
    print(f"  [tracking] step 7: looking for the screen in {len(todo)} clip(s)...", flush=True)
    _t0 = time.time()
    def _how(i, k, n):
        """How a track's name was found (for the per-player table and every track row)."""
        if n is None:
            return None
        if coach.get((i, k)) == n and n is not None:
            return "coach checked"
        if (i, k) in guessed:
            return "best guess"
        if (i, k) in number_names and number_names[(i, k)][0] == n:
            return "jersey number"
        a, af = clips[i]["anchor"], clips[i].get("anchor_first")
        if (a and a[0] == k and a[1] == n) or (af and af[0] == k and af[1] == n):
            return "Synergy"
        if any(kk == k and nn == n for kk, nn, _e in clips[i].get("anchors_pbp", [])):
            return "play-by-play event"
        if solve_how.get((i, k)) == "elimination":
            return "elimination"
        if link_names.get((i, k), (None,))[0] == n:
            return "linked possession"
        if (i, k) in solved:
            return "lineup matching"
        return "appearance"

    for _n_clip, i in enumerate(todo, 1):
        _trk_progress("clips searched for a screen", _n_clip, len(todo), _t0)
        clip = clips[i]
        nm = lambda k: names_all.get((i, k), (None, 0.0)) if k is not None else (None, 0.0)
        out.at[i, "track_players"] = len(clip["tracks"])
        out.at[i, "track_named"] = sum(1 for k in range(len(clip["tracks"])) if (i, k) in names_all)
        out.at[i, "track_ball_frames"] = len(clip["holder"])
        out.at[i, "track_clip_key"] = _trk_clip_key(pc.loc[i])
        out.at[i, "track_frames"] = len(clip["files"])
        out.at[i, "track_finish_frame"] = clip["t_finish"]
        out.at[i, "track_holders"] = _trk_json.dumps({int(t): int(k) for t, k in clip["holder"].items()})
        scr = _trk_find_screen(clip)
        if scr:
            parts = {r: nm(scr[r]) for r in ("screener", "screened", "screened_defender", "screener_defender")}
            out.at[i, "track_screen_type"] = scr["type"]
            for r, (n, c) in parts.items():
                out.at[i, f"track_{r}"] = n
            confs = [c for n, c in parts.values() if n]
            out.at[i, "track_screen_conf"] = round(min(1.0, scr["score"] / 3.0) * (float(np.mean(confs)) if confs else 0.0), 2)
            out.at[i, "track_screen_frame"] = clip["files"][scr["t"]]
            out.at[i, "track_screen_ids"] = _trk_json.dumps({r: (int(scr[r]) if scr[r] is not None else None)
                                                             for r in ("screener", "screened", "screened_defender",
                                                                       "screener_defender")}
                                                            | {"t": int(scr["t"]), "type": scr["type"]})
            clip["screen"] = scr
        for k, tr in enumerate(clip["tracks"]):
            n, c = nm(k)
            cum = np.cumsum(np.array(clip["shifts"]), axis=0)
            rows.append({"clip_key": _trk_clip_key(pc.loc[i]), "game_date": pc.at[i, "game_date"],
                         "clip_number": pc.at[i, "clip_number"], "track": k, "side": clip["side"].get(k),
                         "name": n, "name_conf": round(c, 2) if n else None, "name_how": _how(i, k, n),
                         "anchored": bool(clip["anchor"] and clip["anchor"][0] == k), "frames": len(tr),
                         # [frame, x, y, box height]: x/y are the feet in picture-height units with the camera's
                         # pan removed; box height lets the insights cell turn distances into approximate feet.
                         # [frame, x, y, box height, feet px, feet py]: x/y are the feet in picture-height units with
                         # the camera's pan removed; px/py the same point in the frame's pixels (court mapping).
                         "path": _trk_json.dumps([[t, round(float(clip["frames"][t][j][0] - cum[t][0]), 3),
                                                   round(float(clip["frames"][t][j][1] - cum[t][1]), 3),
                                                   round(float(clip["frames"][t][j][2]), 3),
                                                   # raw feet point in the frame's own pixels, for court mapping
                                                   round(float((clip["frames"][t][j][6] + clip["frames"][t][j][8]) / 2), 1),
                                                   round(float(clip["frames"][t][j][9]), 1)] for t, j in tr])})
    print("  [tracking] step 8: drawing the check images...", flush=True)
    # --- the five on the floor, player by player: which track is him, how we know -- or "not located" ---
    slots = []
    for i in todo:
        for sd in ("offense", "defense"):
            five = _trk_five(pc.at[i, f"{sd}_lineup"])
            team = pc.at[i, f"{sd}_team"]
            for p in five:
                ks = [k for k in range(len(clips[i]["tracks"])) if clips[i]["side"].get(k) == sd
                      and names_all.get((i, k), (None,))[0] == p]
                slots.append({"clip_key": _trk_clip_key(pc.loc[i]), "clip_number": pc.at[i, "clip_number"],
                              "game_date": pc.at[i, "game_date"], "team": team, "side": sd, "player": p,
                              "lineup_source": pc.at[i, "lineup_source"] if "lineup_source" in pc.columns else None,
                              "located": bool(ks), "tracks": ";".join(str(k) for k in ks),
                              "seconds_seen": round(sum(len(clips[i]["tracks"][k]) for k in ks) / max(_fps, 0.5), 1),
                              "how": ";".join(sorted({_how(i, k, p) for k in ks})) if ks else "not located",
                              "confidence": round(max(names_all[(i, k)][1] for k in ks), 2) if ks else None})
    globals()["trk_lineup_slots"] = pd.DataFrame(slots)
    if slots:
        _sl = globals()["trk_lineup_slots"]
        # identified = at least one of his tracks was named from evidence (not only by best guess)
        _ident = _sl["how"].map(lambda h: any(x not in ("best guess", "not located") for x in str(h).split(";")))
        print(f"  [tracking]   of the five on the floor: {int(_ident.sum()):,} of {len(_sl):,} player-clips identified from "
              f"evidence, {int((_sl['located'] & ~_ident).sum()):,} named by best guess only, "
              f"{int((~_sl['located']).sum()):,} not on film (no track left for them)", flush=True)
        print(f"  [tracking]   players on the floor located on the film: {int(_sl['located'].sum()):,} of {len(_sl):,} "
              f"({100 * _sl['located'].mean():.0f}%) -- by " + ", ".join(
                  f"{h} {n}" for h, n in _sl.loc[_sl["located"], "how"].str.split(";").explode().value_counts().items()),
              flush=True)

    _trk_draw_checks(pc, clips, names_all, base, todo)
    return out, pd.DataFrame(rows), report


def _trk_draw_checks(pc, clips, names_all, base, todo):
    if not TRACK_CHECKS:
        return
    from PIL import Image, ImageDraw
    cdir = os.path.join(TRACK_DIR, "checks")
    os.makedirs(cdir, exist_ok=True)
    shown = [i for i in todo if clips[i].get("screen")][:TRACK_CHECKS] or todo[:TRACK_CHECKS]
    col = {"offense": (255, 215, 0), "defense": (0, 200, 255), None: (150, 150, 150)}
    for i in shown:
        clip = clips[i]
        n = len(clip["files"])
        ts = sorted(set([0, n // 3, 2 * n // 3, n - 1] + ([clip["screen"]["t"]] if clip.get("screen") else [])))[:5]
        tiles = []
        for t in ts:
            im = Image.open(os.path.join(base, clip["files"][t])).convert("RGB")
            dr = ImageDraw.Draw(im)
            for k, tr in enumerate(clip["tracks"]):
                j = dict(tr).get(t)
                if j is None:
                    continue
                x1, y1, x2, y2 = clip["frames"][t][j][6:10]
                sd = clip["side"].get(k)
                label = names_all.get((i, k), (f"#{k}", 0))[0]
                scr = clip.get("screen")
                if scr and scr["t"] == t and k == scr["screener"]:
                    label = "SCREEN " + label
                dr.rectangle([x1, y1, x2, y2], outline=col.get(sd, (150, 150, 150)), width=2)
                dr.text((x1, max(0, y1 - 11)), label, fill=col.get(sd, (150, 150, 150)))
            if clip["holder"].get(t) is not None:
                dr.text((6, 6), "ball: track #" + str(clip["holder"][t]), fill=(255, 80, 80))
            tiles.append(im)
        W = sum(im.width for im in tiles)
        strip = Image.new("RGB", (W, max(im.height for im in tiles) + 16), (0, 0, 0))
        x = 0
        for im in tiles:
            strip.paste(im, (x, 16))
            x += im.width
        ImageDraw.Draw(strip).text((4, 2), str(pc.at[i, "synergy_string"])[:160], fill=(255, 255, 255))
        strip.save(os.path.join(cdir, f"{pc.at[i, 'game_date']}_{pc.at[i, 'clip_number']}.jpg"))


# ---- Run --------------------------------------------------------------------------------------------------
_TRACK_COLS = ["track_players", "track_named", "track_ball_frames", "track_screen_type", "track_screener",
               "track_screened", "track_screened_defender", "track_screener_defender", "track_screen_conf",
               "track_screen_frame", "track_clip_key", "track_frames", "track_holders", "track_screen_ids",
               "track_finish_frame"]
for _c in _TRACK_COLS:
    if _c not in play_calls.columns:
        play_calls[_c] = None
# CONFIRMED CHANGE (first run at 1024 wide: tracking ran BEFORE the new frames were placed on the court -- "court
# mapping available for 0 of 7,595 frames" -- so it had no court filter, and fans got in). The tracking run is a
# function now, so the Court mapping cell can rerun it with the court as soon as the court exists (every new game's
# first run). Detections, colors, fingerprints etc. are saved, so the rerun takes minutes.
def _trk_run_all():
    global play_calls, player_tracks, tracking_report
    player_tracks = pd.DataFrame()
    tracking_report = pd.DataFrame()
    # CONFIRMED CHANGE (requested: naming "starts" with the 5 players known to be on the court): first make sure every
    # clip HAS its five -- including clips with no game clock, filled from the clips around them.
    _nf = _trk_fill_lineups(play_calls)
    if _nf:
        print(f"  [tracking] filled {_nf} team lineup(s) for clips with no game clock, from the clips just before and "
              f"after them (same five on both sides = nobody subbed)", flush=True)
    for _c in _TRACK_COLS:
        if _c not in play_calls.columns:
            play_calls[_c] = None
    if RUN_PLAYER_TRACKING and not play_calls.empty:
        try:
            _trk_cols, player_tracks, _trk_rep = player_tracking(play_calls)
            if _trk_cols is None:
                print("Player tracking: no clips have tracking frames yet -- run frame capture with VISION_TRACK_FPS > 0.")
            else:
                for _c in _TRACK_COLS:
                    play_calls[_c] = _trk_cols[_c]
                tracking_report = pd.DataFrame(_trk_rep)
                print("Player tracking:")
                for _r in _trk_rep:
                    print(f"  {_r['game']}: {_r['clips']} clips, {_r['tracks']} tracks. Ball seen in {_r['clips_ball_seen']} clip(s). "
                          f"Teams by jersey color: {_r['teams_by_color']}. Lineups on {_r['clips_with_lineups']} clip(s), Synergy's "
                          f"player found in that lineup on {_r['synergy_player_in_lineup']}. Named anchors: {_r['anchors']} "
                          f"({_r['anchors_by_pose']} by shooting pose, {_r.get('anchors_by_rim', 0)} by finish at the rim). "
                          f"{_r['tracks_named']} tracks named ({_r.get('tracks_named_by_evidence', 0)} by lineup matching on "
                          + ("jersey numbers + Synergy" if _r.get("numbers_used") else "Synergy only -- jersey numbers off")
                          + f", {_r.get('tracks_named_by_elimination', 0)} by elimination). "
                          f"Name check (appearance): {_r['anchor_name_check']} right. Synergy anchor vs jersey number: "
                          f"{_r.get('anchor_vs_number_check', '--')} agree.")
                # The check images also go to the app's data folder (Tracking Quality section in the app).
                try:
                    _app_dir = globals().get("OUTPUT_DIR")
                    if _app_dir:
                        _dst = os.path.join(_app_dir, "tracking_checks")
                        os.makedirs(_dst, exist_ok=True)
                        for _f in os.listdir(os.path.join(TRACK_DIR, "checks")):
                            shutil.copy2(os.path.join(TRACK_DIR, "checks", _f), os.path.join(_dst, _f))
                except Exception as _e:
                    print(f"  (couldn't copy check images to the app folder: {_e})")
                _n_scr = int(play_calls["track_screen_type"].notna().sum())
                print(f"  Screens found: {_n_scr} clip(s). Check images: {os.path.join(TRACK_DIR, 'checks')}")
                # Against the coaches' own defender tags ("12drop" -> #12, named from the roster), where both exist.
                _tag_def = play_calls.get("coverage_defenders", pd.Series(dtype=object)).map(
                    lambda v: re.search(r"def #\d{1,2} ([^)|]+?)\)", v).group(1).strip()
                    if isinstance(v, str) and re.search(r"def #\d{1,2} ([^)|]+?)\)", v) else None)
                _both = _tag_def.notna() & play_calls["track_screen_type"].notna()
                if _both.any():
                    _hit = sum(_tag_def[i] in (play_calls.at[i, "track_screened_defender"], play_calls.at[i, "track_screener_defender"])
                               for i in _both[_both].index)
                    print(f"  Coach-tagged screen defender found among the tracked defenders: {_hit}/{int(_both.sum())}")
        except Exception as _e:
            print("  " + "!" * 100)
            print(f"  PLAYER TRACKING NOT RUN: {type(_e).__name__}: {_e}")
            print("  " + "!" * 100)



player_tracks = pd.DataFrame()
tracking_report = pd.DataFrame()
_trk_court_frames_used = None
_trk_run_all()
