import re
# 53_tag_model.py -- code for the notebook section "Tag model: learns the coaches' Titles, retrained every run -------------------------------"
# Runs inside the notebook via run_section("53_tag_model"); its settings are in that notebook cell.

# --- Tag model: learns the coaches' Titles, retrained every run ---------------------------------------------
# CONFIRMED CHANGE (requested): replaces the Ollama vision model. The coaches' tagged Titles ARE the training
# data: every clip whose Title decodes (play-calls cell above -- UWW games, opponent games and other teams'
# games from the one plays file) is an answer key, and a small classifier per
# field learns from them. It retrains from scratch on EVERY tagged clip each time the parser runs
# (TAG_MODEL_RETRAIN), so more tagging = a better model with no other change.
#
# What each clip gives the model (all of it already in play_calls):
#   * Synergy description -- each "> step" is a feature ("P&R Ball Handler", "Go Away from Pick", "Flare")
#   * context -- offense/defense team, possession side, player, half, clock, shot clock, result
#   * the 5 frames from the frame-capture cell (requested: keep using all 5). Each frame is turned into a list
#     of numbers by a pretrained image model (TAG_MODEL_FRAME_ENCODER, downloaded once, never retrained --
#     only the small classifier on top learns). The 5 are kept IN ORDER (start -> end of the clip), so the
#     model can learn e.g. "press shows in frame 1, the set shows in frame 2", then squeezed to
#     TAG_MODEL_FRAME_PCA numbers so a few hundred clips aren't swamped by thousands of image numbers.
# What it predicts (TAG_MODEL_TARGETS -- add a line to teach it a new field): formation, play call, defense,
# press, situation, primary action, ball-screen coverage, off-ball-screen coverage. Jersey numbers are not
# attempted (too small in a wide game camera).
#
# Every prediction carries a confidence; only predictions at or above TAG_MODEL_MIN_CONFIDENCE go into the
# Suggested Title, the rest stay blank for the coaches. The coach's Title is never changed.
#
# Honest scoring: accuracy is measured on clips the model did NOT train on. With 2+ tagged games that means
# whole games held out (the real test: a game it has never seen); with 1 game it falls back to 5-way splits
# inside that game and says so -- those numbers run high. Each field is scored against "always guess the most
# common answer", because a model that can't beat that isn't learning anything.
# Outputs: pred_<field> / pred_<field>_conf / suggested_title on play_calls (-> uww_play_calls.csv),
# uww_tag_model_report.csv (this run), and _tag_model/history.csv (every retrain, to watch it improve).

import numpy as np


# field -> column holding the coach's answer. Columns starting "label_" are built below from the decoded Title.
TAG_MODEL_TARGETS = {
    "formation": "play_formation",
    "play_call": "play_set",
    "defense": "defense_formation",
    "press": "label_press",
    "situation": "label_situation",
    "primary_action": "primary_action",
    "ball_screen_coverage": "label_ball_screen_coverage",
    "offball_coverage": "label_offball_coverage",
    # NEW (requested): WHO. The screener comes from Synergy's own naming (its roll-man / pick-and-pop clips name
    # the screener); the screen defender from the coaches' tag jersey ("5tl" = #5, named from the roster).
    # Both are limited to the five actually on the floor for that team (TAG_MODEL_LINEUP_LIMITED).
    "screener": "label_screener",
    "screen_defender": "label_screen_defender",
}


def _tm_ensure(pkgs):
    import importlib
    missing = [p for p, mod in pkgs if importlib.util.find_spec(mod) is None]
    if missing:
        if not TAG_MODEL_AUTO_INSTALL:
            raise ModuleNotFoundError(f"missing: {missing} (pip install {' '.join(missing)})")
        print(f"  [tag model] installing {', '.join(missing)} (one time)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *missing])


# ---- Labels: the coach's answer for each field, from the decoded Title ----------------------------------------
def _tm_labels(pc):
    lab = pd.DataFrame(index=pc.index)
    title = pc["play_title"].fillna("").astype(str).str.strip()
    # A clip counts as coach-tagged if its Title decoded into the tag format at all -- not blank, not a bare player
    # name (the Eau Claire clips' Titles were just names), not flagged "Needs review" by the tagger.
    is_name = title.str.lower() == pc["player"].fillna("").astype(str).str.strip().str.lower()
    lab["tagged"] = (title != "") & pc["tag_format"].notna() & ~is_name & (pc["decode_quality"] != "Needs review")
    def_tagged = pc["defense_formation"].notna() | pc["defense_press"].astype(str).str.lower().eq("true")
    press_type = pc["defense_press_formation"].where(pc["defense_press_formation"].notna(),
                                                     pc["defense_press"].map(lambda x: "Press" if str(x).lower() == "true" else "None"))
    lab["label_press"] = press_type.where(def_tagged)
    # Situation: what the coach typed; a clip tagged without one is half court. (Synergy/timeout inference is
    # context, not an answer.)
    lab["label_situation"] = pc["play_situation"].where(pc["situation_source"].eq("Tag"), "Half court")
    cov = pc["coverage_detail"].fillna("").astype(str)
    first = lambda pat: cov.str.extract(pat, expand=False).str.strip()
    lab["label_ball_screen_coverage"] = first(r"(?:^|\| )(?:Ball Screen|DHO|Get|Double Drag):\s*([^(|]+)")
    lab["label_offball_coverage"] = first(r"(?:^|\| )(?:Down Screen|Off-ball screen|Flare|Stagger|Up Screen|"
                                          r"Pin Down|Back Screen|Cross Screen|UCLA|Screen the Screener|"
                                          r"Double/Stagger Screen|Screen):\s*([^(|]+)")
    # Screener: on Synergy's "P&R Roll Man" / "Pick and Pops" clips the first player named IS the screener. This
    # label comes from Synergy, not a coach, so it doesn't need the clip to be coach-tagged.
    ss = pc["synergy_string"].map(lambda v: v if isinstance(v, str) else "")
    roll = ss.str.contains(r">\s*(?:P&R Roll Man|Pick and Pops?)\s*(?:>|$)", regex=True)
    lab["label_screener"] = ss.str.extract(r"^\s*\d+\s+([^>]+?)\s*>", expand=False).str.strip().where(roll)
    # Screen defender: the first coverage in the tag that carries a jersey, named from the roster when possible.
    cd = pc.get("coverage_defenders", pd.Series(index=pc.index, dtype=object)).map(lambda v: v if isinstance(v, str) else "")
    named = cd.str.extract(r"def #\d{1,2} ([^)|]+?)\)", expand=False).str.strip()
    num = cov.str.extract(r"def #(\d{1,2})", expand=False)
    lab["label_screen_defender"] = named.where(named.notna() & named.ne(""), "#" + num).where(named.notna() | num.notna())
    for col in set(TAG_MODEL_TARGETS.values()):
        if not col.startswith("label_"):
            lab[col] = pc[col] if col in pc.columns else None
    for col in lab.columns:
        if col == "tagged":
            continue
        need_tag = col != "label_screener"   # Synergy-named, valid on any clip
        good = lab[col].notna() & lab[col].map(lambda v: str(v).strip() != "" if v is not None else False)
        lab[col] = lab[col].where(good & (lab["tagged"] if need_tag else True))
    return lab


# ---- Which game each clip is from, and matching a game by its file-style name -------------------------------
def _tm_game_key(pc):
    teams = pc.apply(lambda r: " v ".join(sorted([str(r.get("offense_team")), str(r.get("defense_team"))])), axis=1)
    return pd.to_datetime(pc["game_date"], errors="coerce").dt.date.map(str) + " | " + teams


def _tm_game_matches(name, keys):
    """'1_3_26 UW-Oshkosh Titans @ UW-Whitewater' -> which game keys it means (date within a day + team word)."""
    m = re.match(r"^\s*(\d{1,2})_(\d{1,2})_(\d{2,4})\s+(.*)$", str(name))
    if not m:
        raise ValueError(f"Game names should look like '1_3_26 UW-Oshkosh Titans @ UW-Whitewater', got {name!r}")
    d = pd.Timestamp(int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0), int(m.group(1)), int(m.group(2)))
    words = {w for w in re.split(r"[\s@\-]+", m.group(4).lower()) if len(w) > 2 and w not in {"uww", "whitewater", "warhawks", "the"}}
    out = set()
    for k in set(keys):
        kd = pd.to_datetime(k.split(" | ")[0], errors="coerce")
        if pd.notna(kd) and abs((kd - d).days) <= 1 and any(w in k.lower() for w in words):
            out.add(k)
    return out


# ---- Frame features ----------------------------------------------------------------------------------------
def _tm_encode_images(paths):
    """Pretrained image model -> one vector per image. Downloaded once; never retrained."""
    _tm_ensure([("torch", "torch"), ("transformers", "transformers"), ("pillow", "PIL")])  # no torchvision needed
    # CONFIRMED BUG (fixed): the install check only looked for transformers, not its VERSION. The user's Anaconda
    # had an old one without AutoImageProcessor ("cannot import name 'AutoImageProcessor'"), and DINOv2 needs
    # an even newer one. Too old -> upgrade it, then stop: the old version is already loaded in the running
    # kernel, so it only takes effect after a kernel restart.
    import transformers
    _v = tuple(int(x) for x in re.findall(r"\d+", transformers.__version__)[:2])
    if _v < TAG_MODEL_MIN_TRANSFORMERS:
        _need = ".".join(map(str, TAG_MODEL_MIN_TRANSFORMERS))
        if TAG_MODEL_AUTO_INSTALL:
            print(f"  [tag model] transformers {transformers.__version__} is too old (needs {_need}+) -- upgrading...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-U", f"transformers>={_need}",
                                   "torch", "pillow"])
            raise RuntimeError(f"transformers was upgraded from {transformers.__version__}. RESTART THE KERNEL "
                               f"(Kernel > Restart) and run the parser again -- the old version stays loaded until then.")
        raise RuntimeError(f"transformers {transformers.__version__} is too old (needs {_need}+). Run "
                           f"`%pip install -U transformers torch pillow`, restart the kernel, and rerun.")
    import torch
    from PIL import Image
    from transformers import AutoModel
    enc = globals().get("_tm_encoder")
    if enc is None or enc[0] != TAG_MODEL_FRAME_ENCODER:
        print(f"  [tag model] loading image model {TAG_MODEL_FRAME_ENCODER} (downloads once)...")
        model = AutoModel.from_pretrained(TAG_MODEL_FRAME_ENCODER).eval()
        enc = globals()["_tm_encoder"] = (TAG_MODEL_FRAME_ENCODER, model)
    _, model = enc
    out = []
    with torch.no_grad():
        for i in range(0, len(paths), 16):
            batch = torch.from_numpy(np.stack([_tm_prep_image(Image.open(p)) for p in paths[i:i + 16]]))
            res = model(pixel_values=batch)
            h = res.last_hidden_state                      # [clip, 1 + patches, dims]
            cls = res.pooler_output if getattr(res, "pooler_output", None) is not None else h[:, 0]
            # The whole-image summary (CLS) PLUS the average over every 14x14 patch -- the patch average keeps
            # more of WHERE things are on the floor, which is what formation and man vs zone depend on.
            out.extend(torch.cat([cls, h[:, 1:].mean(1)], dim=1).float().numpy())
    return out


# CONFIRMED BUG (fixed): transformers' AutoImageProcessor now needs the separate torchvision library
# ("AutoImageProcessor requires the Torchvision library") -- another install that has to match torch exactly.
# The frames are prepared here instead with Pillow + numpy, which also fixes a real problem: the standard
# DINOv2 preparation center-crops to a 224x224 square, which on a wide game camera throws away both sides of
# the floor. Here the WHOLE frame is resized to TAG_MODEL_FRAME_SIZE (height x width, multiples of 14 -- the
# model's patch size), keeping the full width of the court.
_TM_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_TM_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _tm_prep_image(img):
    from PIL import Image
    h, w = TAG_MODEL_FRAME_SIZE
    a = np.asarray(img.convert("RGB").resize((w, h), Image.BICUBIC), dtype=np.float32) / 255.0
    return ((a - _TM_MEAN) / _TM_STD).transpose(2, 0, 1).astype(np.float32)   # channels first


_tm_frame_diag = {}


def _tm_frame_matrix(pc):
    """One row per clip: its 5 frame vectors in order, joined, squeezed with PCA. Frame vectors are cached per
    file in _tag_model/, so each image is encoded once ever. Clips without frames get zeros + has_frames=0."""
    n = VISION_FRAMES_PER_CLIP if "VISION_FRAMES_PER_CLIP" in globals() else 5
    files = pc.get("frame_files", pd.Series(index=pc.index, dtype=object))
    files = files.map(lambda v: v if isinstance(v, str) else "")
    lists = files.map(lambda s: [x for x in s.split(";") if x])
    ok = lists.map(len).eq(n)
    base = VISION_FRAMES_DIR if "VISION_FRAMES_DIR" in globals() else os.path.join(INPUT_DIR, "_vision_frames")
    # Where frames drop out, stage by stage, so "frames for 0 clip(s)" always comes with the reason (requested).
    _tm_frame_diag.update(joined=int(lists.map(len).gt(0).sum()), complete=int(ok.sum()),
                          on_disk=int((ok & lists.map(lambda fl: all(os.path.exists(os.path.join(base, f)) for f in fl))).sum()),
                          folder=base)
    if not ok.any():
        return None
    cache_path = os.path.join(TAG_MODEL_DIR, f"frame_vectors_{re.sub(r'[^A-Za-z0-9]+', '_', TAG_MODEL_FRAME_ENCODER)}"
                                            f"_{TAG_MODEL_FRAME_SIZE[0]}x{TAG_MODEL_FRAME_SIZE[1]}_clsmean.pkl")
    cache = pd.read_pickle(cache_path) if os.path.exists(cache_path) else {}
    todo = sorted({f for fl in lists[ok] for f in fl if f not in cache and os.path.exists(os.path.join(base, f))})
    if todo:
        print(f"  [tag model] encoding {len(todo)} new frame(s)...")
        for f, v in zip(todo, _tm_encode_images([os.path.join(base, f) for f in todo])):
            cache[f] = np.asarray(v, dtype=np.float16)
        os.makedirs(TAG_MODEL_DIR, exist_ok=True)
        pd.to_pickle(cache, cache_path)
    ok = ok & lists.map(lambda fl: all(f in cache for f in fl))
    _tm_frame_diag["encoded"] = int(ok.sum())
    if ok.sum() < 3:
        return None
    raw = np.stack([np.concatenate([cache[f].astype(np.float32) for f in fl]) for fl in lists[ok]])
    from sklearn.decomposition import PCA
    k = int(min(TAG_MODEL_FRAME_PCA, raw.shape[0] - 1, raw.shape[1]))
    comp = PCA(n_components=k, random_state=0).fit_transform(raw)
    fm = pd.DataFrame(0.0, index=pc.index, columns=[f"frame_pc{i}" for i in range(k)])
    fm.loc[ok[ok].index] = comp
    fm["has_frames"] = ok.astype(float)
    return fm


# ---- Player positions (requested: "turn each frame into player positions") ---------------------------------
# A person detector (YOLO, via the `ultralytics` package; ~6 MB of weights downloaded once) finds every person
# in each saved frame. Detections are cached per frame file in _tag_model/, so each frame is detected once ever.
# Then, per clip:
#   * keep likely PLAYERS: boxes of a player-like size standing in the court band of the picture (drops most
#     fans in the stands and people cut off at the edges)
#   * split them into TEAMS by jersey color: the torso color of every kept box in the clip's 5 frames is
#     grouped into 3 color groups, and the smallest group (usually the referees) is dropped
#   * describe each frame with numbers the model can learn from: how many players, how spread out they are
#     (left-right and up-down in the picture), where on the floor they stand (a 4x2 grid of the picture), how
#     tight each team is to the other (tight = man-to-man denial, loose = zone or sagging), and how many
#     same-team pairs are touching (screens, stacks) vs opposite-team pairs (guarding, bumping)
# Positions are in PICTURE coordinates, not court feet: the camera pans and zooms, and turning the picture
# into a court diagram needs the court lines found in every frame -- a later step if this proves useful.
# Which team is on offense isn't read from the colors; the features are built so they don't need to know.
_TM_POS_PER_FRAME = ["n_players", "n_team_big", "n_team_small", "spread_x", "spread_y", "width", "height",
                     *[f"grid_{r}{c}" for r in range(2) for c in range(4)],
                     "tight_min", "tight_max", "close_cross", "close_same", "team_spread_big", "team_spread_small"]
_tm_pos_diag = {}


def _tm_detect(paths):
    """{path: array of [x1, y1, x2, y2, conf, r, g, b]} for every person found (torso color in r, g, b)."""
    import importlib
    if importlib.util.find_spec("ultralytics") is None:
        if not TAG_MODEL_AUTO_INSTALL:
            raise ModuleNotFoundError("ultralytics is missing: run `%pip install ultralytics`, restart the kernel")
        print("  [positions] installing ultralytics (one time; it may also update torch)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "ultralytics"])
        raise RuntimeError("ultralytics was installed. RESTART THE KERNEL (Kernel > Restart) and run the parser "
                           "again -- torch may have been updated and the old one is still loaded.")
    from ultralytics import YOLO
    from PIL import Image
    det = globals().get("_tm_detector")
    if det is None or det[0] != TAG_MODEL_DETECTOR:
        print(f"  [positions] loading detector {TAG_MODEL_DETECTOR} (downloads once)...")
        det = globals()["_tm_detector"] = (TAG_MODEL_DETECTOR, YOLO(TAG_MODEL_DETECTOR))
    model = det[1]
    out = {}
    for i in range(0, len(paths), 8):
        chunk = paths[i:i + 8]
        results = model.predict(chunk, classes=[0], conf=TAG_MODEL_DETECT_CONF, imgsz=TAG_MODEL_DETECT_SIZE,
                                verbose=False)
        for p, r in zip(chunk, results):
            img = np.asarray(Image.open(p).convert("RGB"))
            rows = []
            for (x1, y1, x2, y2), cf in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()):
                w, h = x2 - x1, y2 - y1
                tx1, tx2 = int(x1 + 0.3 * w), int(x2 - 0.3 * w)
                ty1, ty2 = int(y1 + 0.2 * h), int(y1 + 0.45 * h)       # chest: jersey color, not skin or floor
                patch = img[max(ty1, 0):max(ty2, ty1 + 1), max(tx1, 0):max(tx2, tx1 + 1)]
                rgb = patch.reshape(-1, 3).mean(0) if patch.size else np.array([np.nan] * 3)
                rows.append([x1, y1, x2, y2, cf, *rgb])
            out[p] = np.array(rows, dtype=np.float32).reshape(-1, 8)
    return out


def _tm_frame_positions(boxes, W, H):
    """Kept player boxes for one frame: size + court-band filter. -> array rows [fx, fy, h, r, g, b] normalized."""
    if boxes is None or len(boxes) == 0:
        return np.zeros((0, 6), dtype=np.float32)
    b = boxes[np.isfinite(boxes[:, 5])]
    h = (b[:, 3] - b[:, 1]) / H
    fy = b[:, 3] / H                      # feet
    fx = ((b[:, 0] + b[:, 2]) / 2) / W
    keep = (h > 0.05) & (h < 0.45) & (fy > 0.25) & (fy < 0.98) & (fx > 0.01) & (fx < 0.99)
    return np.column_stack([fx[keep], fy[keep], h[keep], b[keep][:, 5:8]]).astype(np.float32)


def _tm_clip_position_features(frames_pos):
    """frames_pos: list (one per frame, in clip order) of arrays from _tm_frame_positions."""
    allc = np.vstack([f[:, 3:6] for f in frames_pos if len(f)]) if any(len(f) for f in frames_pos) else np.zeros((0, 3))
    team_of = None
    if len(allc) >= 9:
        from sklearn.cluster import KMeans
        km = KMeans(n_clusters=3, n_init=5, random_state=0).fit(allc)
        sizes = np.bincount(km.labels_, minlength=3)
        big, mid, small = np.argsort(-sizes)
        team_of = {big: 0, mid: 1, small: -1}     # -1 = referees / other, dropped
    feats = []
    for f in frames_pos:
        v = dict.fromkeys(_TM_POS_PER_FRAME, np.nan)
        if len(f) and team_of is not None:
            lab = np.array([team_of[l] for l in km.predict(f[:, 3:6])])
            f, lab = f[lab >= 0], lab[lab >= 0]
        else:
            lab = np.zeros(len(f), dtype=int)
        if len(f):
            xs, ys, hs = f[:, 0], f[:, 1], f[:, 2]
            unit = float(np.median(hs)) or 0.1      # one player-height, in picture units
            counts = sorted([(lab == 0).sum(), (lab == 1).sum()], reverse=True)
            v.update(n_players=len(f), n_team_big=counts[0], n_team_small=counts[1],
                     spread_x=float(xs.std()), spread_y=float(ys.std()),
                     width=float(xs.max() - xs.min()), height=float(ys.max() - ys.min()))
            gx = np.clip((xs * 4).astype(int), 0, 3)
            gy = np.clip(((ys - 0.25) / 0.73 * 2).astype(int), 0, 1)
            for r in range(2):
                for c in range(4):
                    v[f"grid_{r}{c}"] = float(((gy == r) & (gx == c)).sum()) / len(f)
            pts = np.column_stack([xs, ys * 1.5])   # the camera looks down at an angle: depth is compressed
            d = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)) / unit
            np.fill_diagonal(d, np.inf)
            same = lab[:, None] == lab[None, :]
            tight = [np.mean([d[i][~same[i]].min() for i in np.where(lab == t)[0] if (~same[i]).any()] or [np.nan])
                     for t in (0, 1)]
            v.update(tight_min=float(np.nanmin(tight)) if not np.all(np.isnan(tight)) else np.nan,
                     tight_max=float(np.nanmax(tight)) if not np.all(np.isnan(tight)) else np.nan,
                     close_cross=float(np.triu((d < 1.0) & ~same, 1).sum()),
                     close_same=float(np.triu((d < 1.0) & same, 1).sum()))
            spreads = sorted([float(xs[lab == t].std()) if (lab == t).sum() > 1 else 0.0 for t in (0, 1)], reverse=True)
            v.update(team_spread_big=spreads[0], team_spread_small=spreads[1])
        feats.append(v)
    return feats


def _tm_position_matrix(pc):
    """One row per clip: the per-frame position numbers for all its frames, in order. Clips without frames or
    detections get zeros + has_positions = 0."""
    n = VISION_FRAMES_PER_CLIP if "VISION_FRAMES_PER_CLIP" in globals() else 5
    base = VISION_FRAMES_DIR if "VISION_FRAMES_DIR" in globals() else os.path.join(INPUT_DIR, "_vision_frames")
    files = pc.get("frame_files", pd.Series(index=pc.index, dtype=object)).map(lambda v: v if isinstance(v, str) else "")
    lists = files.map(lambda s: [x for x in s.split(";") if x])
    ok = lists.map(len).eq(n) & lists.map(lambda fl: all(os.path.exists(os.path.join(base, f)) for f in fl))
    _tm_pos_diag.update(clips_with_frames=int(ok.sum()))
    if ok.sum() < 3:
        return None
    cache_path = os.path.join(TAG_MODEL_DIR, f"player_boxes_{re.sub(r'[^A-Za-z0-9]+', '_', TAG_MODEL_DETECTOR)}"
                                            f"_{TAG_MODEL_DETECT_SIZE}_{TAG_MODEL_DETECT_CONF}.pkl")
    cache = pd.read_pickle(cache_path) if os.path.exists(cache_path) else {}
    todo = sorted({f for fl in lists[ok] for f in fl if f not in cache})
    if todo:
        print(f"  [positions] finding players in {len(todo)} new frame(s)...")
        found = _tm_detect([os.path.join(base, f) for f in todo])
        for f in todo:
            cache[f] = found.get(os.path.join(base, f), np.zeros((0, 8), dtype=np.float32))
        os.makedirs(TAG_MODEL_DIR, exist_ok=True)
        pd.to_pickle(cache, cache_path)
    from PIL import Image
    cols = [f"pos_f{k + 1}_{name}" for k in range(n) for name in _TM_POS_PER_FRAME]
    pm = pd.DataFrame(np.nan, index=pc.index, columns=cols)
    size_cache = {}
    n_players = []
    for i in ok[ok].index:
        fl = lists[i]
        if fl[0] not in size_cache:
            with Image.open(os.path.join(base, fl[0])) as im:
                size_cache[fl[0]] = im.size
        W, H = size_cache[fl[0]]
        fpos = [_tm_frame_positions(cache.get(f), W, H) for f in fl]
        feats = _tm_clip_position_features(fpos)
        pm.loc[i, cols] = [feats[k][name] for k in range(n) for name in _TM_POS_PER_FRAME]
        n_players.append(np.nanmean([ft["n_players"] for ft in feats]))
    pm["has_positions"] = ok.astype(float)
    _tm_pos_diag.update(clips_with_positions=int(ok.sum()),
                        avg_players=round(float(np.nanmean(n_players)), 1) if n_players else None)
    _tm_position_checks(pc, lists, ok, cache, base)
    return pm


def _tm_position_checks(pc, lists, ok, cache, base):
    """Draw the kept boxes on a few clips' frames (colored by team) so a person can check the detector."""
    if not TAG_MODEL_POSITION_CHECKS:
        return
    from PIL import Image, ImageDraw
    out_dir = os.path.join(TAG_MODEL_DIR, "position_checks")
    os.makedirs(out_dir, exist_ok=True)
    for i in list(ok[ok].index)[:TAG_MODEL_POSITION_CHECKS]:
        f = lists[i][len(lists[i]) // 2]                 # the middle frame
        dst = os.path.join(out_dir, re.sub(r"[^\w@.-]+", "_", f))
        if os.path.exists(dst):
            continue
        with Image.open(os.path.join(base, f)) as im:
            im = im.convert("RGB")
            W, H = im.size
            draw = ImageDraw.Draw(im)
            for x1, y1, x2, y2, cf, r, g, b in cache.get(f, []):
                h, fy, fx = (y2 - y1) / H, y2 / H, (x1 + x2) / 2 / W
                kept = 0.05 < h < 0.45 and 0.25 < fy < 0.98 and 0.01 < fx < 0.99
                col = (int(r), int(g), int(b)) if kept else (128, 128, 128)
                draw.rectangle([x1, y1, x2, y2], outline=col, width=3 if kept else 1)
            draw.text((8, 8), str(pc.loc[i].get("synergy_string", ""))[:120], fill=(255, 255, 0))
            im.save(dst)


# ---- Features + model -------------------------------------------------------------------------------------
_TM_CATS = ["side", "possession_side", "offense_team", "defense_team", "player", "period", "synergy_play_type",
            "result", "shot_clock_situation",
            # NEW: what the player-tracking cell saw (screen type and who, by name) -- the model learns how far
            # to trust it for each field; blank when a clip has no tracking frames.
            "track_screen_type", "track_screener", "track_screened_defender", "track_screener_defender"]
_TM_NUMS = ["time_remaining_seconds", "shot_clock_used"]


def _tm_features(pc, frames, positions=None):
    X = pd.DataFrame(index=pc.index)
    # Synergy steps, minus the "<jersey> <name>" steps (the player is its own feature).
    X["steps"] = pc["synergy_string"].fillna("").astype(str).map(
        lambda s: "|".join(x.strip().lower() for x in s.split(">") if x.strip() and not re.match(r"^\d+\s", x.strip())))
    # Who's on the floor: every player in the offense's five and the defense's five is its own yes/no input
    # (requested), so the model can learn things like "when these two are in, it's Horns" or "#12 guards
    # their 5-man".
    def _five(v, tag):
        return [f"{tag}:{p.strip()}" for p in v.split(",") if p.strip()] if isinstance(v, str) else []
    off5 = pc.get("offense_lineup", pd.Series(index=pc.index, dtype=object))
    def5 = pc.get("defense_lineup", pd.Series(index=pc.index, dtype=object))
    X["lineups"] = [ "|".join(_five(o, "off") + _five(d, "def")) for o, d in zip(off5, def5)]
    for c in _TM_CATS:
        X[c] = pc[c].astype(str) if c in pc.columns else "nan"
    for c in _TM_NUMS:
        X[c] = pd.to_numeric(pc[c], errors="coerce") if c in pc.columns else np.nan
    if frames is not None:
        X = X.join(frames)
    if positions is not None:
        X = X.join(positions)
    return X


def _tm_split_steps(s):
    # A named function, not a lambda, so the saved model can be written to disk and loaded back.
    return [t for t in s.split("|") if t]


def _tm_pipeline(X):
    from sklearn.compose import ColumnTransformer
    from sklearn.feature_extraction.text import CountVectorizer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline, make_pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    frame_cols = [c for c in X.columns if c.startswith("frame_pc") or c == "has_frames"]
    pos_cols = [c for c in X.columns if c.startswith("pos_f") or c == "has_positions"]
    ct = ColumnTransformer([
        ("steps", CountVectorizer(tokenizer=_tm_split_steps, lowercase=False,
                                  token_pattern=None, binary=True), "steps"),
        ("cats", OneHotEncoder(handle_unknown="ignore"), _TM_CATS),
    ] + ([("lineups", CountVectorizer(tokenizer=_tm_split_steps, lowercase=False, token_pattern=None, binary=True),
           "lineups")] if "lineups" in X.columns and X["lineups"].str.len().gt(0).any() else []) + [
        ("nums", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), _TM_NUMS),
    ] + ([("frames", StandardScaler(), frame_cols)] if frame_cols else [])
      + ([("positions", make_pipeline(SimpleImputer(strategy="constant", fill_value=0.0), StandardScaler()),
           pos_cols)] if pos_cols else []))
    return Pipeline([("features", ct), ("clf", LogisticRegression(C=TAG_MODEL_C, max_iter=3000))])


def _tm_limit(proba, classes, lineups):
    """Zero out every answer that isn't one of the five on the floor for that clip, then renormalize. A clip
    with no known lineup (or none of the five ever seen as an answer) keeps its unlimited prediction."""
    if lineups is None:
        return proba
    proba = proba.copy()
    for r, lu in enumerate(lineups):
        if not isinstance(lu, str) or not lu.strip():
            continue
        five = {p.strip() for p in lu.split(",")}
        mask = np.array([c in five for c in classes])
        if mask.any() and proba[r, mask].sum() > 0:
            proba[r, ~mask] = 0.0
            proba[r] /= proba[r].sum()
    return proba


def _tm_score(X, y, groups, holdout_mask, limit=None):
    """Predictions for clips the model did NOT train on -> (predicted, confidence, how it was scored)."""
    pred = pd.Series(index=y.index, dtype=object)
    conf = pd.Series(index=y.index, dtype=float)
    if holdout_mask is not None and holdout_mask.any():
        folds = [(~holdout_mask, holdout_mask)]
        how = "held-out game(s)"
    elif groups[y.notna()].nunique() >= 2:
        # Only games that have tagged clips of this field count -- untagged games can't be scored.
        g = groups[y.notna()].unique()
        folds = [(groups != gi, groups == gi) for gi in g]
        how = f"each of {len(g)} tagged games held out in turn"
    else:
        rng = np.random.RandomState(0)
        fold_id = pd.Series(rng.randint(0, 5, len(y)), index=y.index)
        folds = [(fold_id != f, fold_id == f) for f in range(5)]
        how = "ONE game only: 5 splits inside it (optimistic -- tag another game for a real test)"
    for tr, te in folds:
        tr, te = tr & y.notna(), te & y.notna()
        if te.sum() == 0 or y[tr].nunique() < 2:
            continue
        m = _tm_pipeline(X).fit(X[tr], y[tr])
        proba = _tm_limit(m.predict_proba(X[te]), m.classes_, None if limit is None else limit[te].tolist())
        pred[te] = m.classes_[proba.argmax(1)]
        conf[te] = proba.max(1)
    return pred, conf, how


# ---- Run --------------------------------------------------------------------------------------------------
# Training data = every clip the play-calls cell decoded: UWW games, the upcoming opponent's games, AND other
# teams' games from the one plays file (play_calls_other) -- a tagged clip teaches the model the same thing
# whichever game it's from. Predictions are written back onto play_calls only (the scouting table).
# CONFIRMED CHANGE (requested after the first 7-game run, where play call scored 27% vs 54% for "always guess
# the most common"): each field now tries a few model flexibilities (TAG_MODEL_C_OPTIONS) with the same
# game-held-out scoring and keeps the best; and if even the best can't beat always guessing the most common
# answer, the field predicts that answer instead (and says so), so a model that isn't learning yet can never
# make the Suggested Titles worse than a plain guess.

tag_model_report = pd.DataFrame(columns=["field", "label_column", "tagged_clips", "answers_learned", "scored_how",
                                         "clips_scored", "accuracy_pct", "baseline_pct", "using", "features", "model_c",
                                         "confident_pct", "confident_accuracy_pct", "not_learned_yet", "trained_at"])
_tm_other = globals().get("play_calls_other")
_tm_src = (pd.concat([play_calls, _tm_other], ignore_index=True)
           if isinstance(_tm_other, pd.DataFrame) and not _tm_other.empty else play_calls.copy())
_tm_n_pc = len(play_calls)   # rows [0, _tm_n_pc) of _tm_src are play_calls, in order
if RUN_TAG_MODEL and not _tm_src.empty:
    _tm_ensure([("scikit-learn", "sklearn"), ("joblib", "joblib")])
    import joblib
    os.makedirs(TAG_MODEL_DIR, exist_ok=True)
    _tm_lab = _tm_labels(_tm_src)
    # CONFIRMED CHANGE (requested: an automatic Title from the film, with a review like the player checks). Answers
    # confirmed or corrected in the Auto-Title review (title_review_*.json) are labels for clips the coaches never
    # tagged -- reviewing an automatic Title teaches the model like tagging does. A coach's Title always wins.
    # the coaches' own answers, before any review answer -- the "Coach" column and the coach-Title comparisons use these
    _tm_lab_coach = _tm_lab.copy()
    # CONFIRMED CHANGE (requested): review answers (Play review "Your answer") are training labels -- they fill fields
    # the coach's Title left empty AND, with TAG_MODEL_REVIEW_OVERRIDES_TITLE, override the coach's Title when they
    # disagree. Untouched prefilled rows never override (they only repeat the coach's value, and a later re-tag must win
    # over them). A typed answer that matches a known answer apart from capitals / spaces / punctuation is stored in
    # the known spelling ("2-3 zone" -> "2-3 Zone"); anything new is kept as typed and listed below.
    _tm_n_review = _tm_n_override = 0
    _tm_new_answers = []
    _tm_norm = lambda x: re.sub(r"[^a-z0-9#]+", "", str(x).lower())
    _answers = title_review_answers() if "title_review_answers" in globals() else {}
    _marks_ = globals().get("_title_review_marks") or {}
    _key_of = [f"{play_calls.iloc[i].get('game_date')}|{play_calls.iloc[i].get('clip_number')}|"
               f"{play_calls.iloc[i].get('synergy_string')}" for i in range(_tm_n_pc)]
    _rows_of = {}
    for i, k in enumerate(_key_of):
        _rows_of.setdefault(k, []).append(i)
    for (_ck, _fld), _val in _answers.items():
        _col = TAG_MODEL_TARGETS.get(_fld)
        if not _col or _col not in _tm_lab.columns or _val in (None, ""):
            continue
        # the known spelling of this answer, if there is one
        _known = {}
        for v in list(_tm_lab_coach[_col].dropna().astype(str)) + list(play_calls.get(f"pred_{_fld}", pd.Series(dtype=object)).dropna().astype(str)):
            _known.setdefault(_tm_norm(v), v)
        _canon = _known.get(_tm_norm(_val))
        if _canon is None:
            _tm_new_answers.append(f"{_fld}: '{_val}'")
            _canon = str(_val)
        _pre = bool((_marks_.get((_ck, _fld)) or {}).get("prefilled"))
        for i in _rows_of.get(_ck, []):
            _cur = _tm_lab.iloc[i][_col]
            _empty = pd.isna(_cur) or _cur in (None, "")
            if _empty:
                _tm_lab.iat[i, _tm_lab.columns.get_loc(_col)] = _canon
                _tm_n_review += 1
            elif (globals().get("TAG_MODEL_REVIEW_OVERRIDES_TITLE", True) and not _pre
                  and _tm_norm(_cur) != _tm_norm(_canon)):
                _tm_lab.iat[i, _tm_lab.columns.get_loc(_col)] = _canon
                _tm_n_override += 1
    if _tm_n_review or _tm_n_override:
        print(f"  [tag model] review answers: {_tm_n_review} added as labels where the coach's Title had none"
              + (f", {_tm_n_override} overriding the coach's Title (TAG_MODEL_REVIEW_OVERRIDES_TITLE)" if _tm_n_override else ""),
              flush=True)
    if _tm_new_answers:
        print(f"  [tag model] new answers typed in reviews (not seen before -- check for typos): "
              + "; ".join(sorted(set(_tm_new_answers))[:12]), flush=True)
    _tm_groups = _tm_game_key(_tm_src)
    _tm_frames = None
    _tm_frame_diag.clear()
    _tm_frame_err = None
    if TAG_MODEL_USE_FRAMES:
        try:
            _tm_frames = _tm_frame_matrix(_tm_src)
        except Exception as _e:
            _tm_frame_err = f"{type(_e).__name__}: {_e}"
        # CONFIRMED CHANGE (requested: frame capture reported 196 of 196 clips with frames, but the model said
        # "frames for 0 clip(s)" with no reason). Every run now prints how many clips survive each step, and any
        # failure is spelled out instead of a one-line note that scrolls past.
        _cf = globals().get("clip_frames")
        _n_cap = (int(pd.to_numeric(_cf.get("frames_captured"), errors="coerce").fillna(0).ge(
            globals().get("VISION_FRAMES_PER_CLIP", 5)).sum()) if isinstance(_cf, pd.DataFrame) and not _cf.empty else 0)
        _d = _tm_frame_diag
        print(f"  Frames: {_n_cap} clip(s) captured (uww_clip_frames.csv) -> {_d.get('joined', 0)} matched to a clip in "
              f"uww_plays.csv -> {_d.get('complete', 0)} with all {globals().get('VISION_FRAMES_PER_CLIP', 5)} frames -> "
              f"{_d.get('on_disk', 0)} found on disk -> {_d.get('encoded', 0)} turned into numbers")
        if _tm_frame_err:
            print("  " + "!" * 100)
            print(f"  FRAMES NOT USED THIS RUN -- the image model failed: {_tm_frame_err}")
            if "RESTART THE KERNEL" not in _tm_frame_err:  # the upgrade message already says exactly what to do
                print("  Usual causes: torch/transformers didn't install into this Jupyter kernel (run "
                      "`%pip install -U torch transformers pillow` in a cell, then restart the kernel), or the one-time "
                      f"download of {TAG_MODEL_FRAME_ENCODER} from huggingface.co was blocked.")
            print("  " + "!" * 100)
        elif _n_cap and not _d.get("joined"):
            print("  FRAMES NOT USED: none of the captured clips matched a clip in uww_plays.csv. The match is Synergy "
                  "description + player + date (within a day) -- check the export has this game's 'Synergy String'.")
        elif _d.get("complete") and not _d.get("on_disk"):
            print(f"  FRAMES NOT USED: the frame files aren't in {_d.get('folder')} -- was the _vision_frames folder "
                  f"moved, or INPUT_DIR changed since capture?")
    print(f"Tag model: {int(_tm_lab['tagged'].sum())} coach-tagged clip(s) across {_tm_groups[_tm_lab['tagged']].nunique()} "
          f"game(s) ({int(_tm_lab['tagged'].iloc[_tm_n_pc:].sum())} from other teams' games); "
          f"frames for {int(_tm_frames['has_frames'].sum()) if _tm_frames is not None else 0} clip(s).")
    _tm_positions = None
    if TAG_MODEL_USE_POSITIONS:
        _tm_pos_diag.clear()
        try:
            _tm_positions = _tm_position_matrix(_tm_src)
            if _tm_positions is not None:
                print(f"  Positions: players found in {_tm_pos_diag.get('clips_with_positions', 0)} clip(s), "
                      f"~{_tm_pos_diag.get('avg_players')} player(s) per frame on average (10 on the floor + refs = "
                      f"best case). Check the boxes: {os.path.join(TAG_MODEL_DIR, 'position_checks')}")
            else:
                print("  Positions: not used -- no clips with all their frames on disk.")
        except Exception as _e:
            print("  " + "!" * 100)
            print(f"  POSITIONS NOT USED THIS RUN: {type(_e).__name__}: {_e}")
            print("  " + "!" * 100)
    _tm_X = _tm_features(_tm_src, _tm_frames, _tm_positions)
    _tm_ctx_cols = [c for c in _tm_X.columns if not (c.startswith(("frame_pc", "pos_f")) or c in ("has_frames", "has_positions"))]
    _tm_frame_cols = [c for c in _tm_X.columns if c.startswith("frame_pc") or c == "has_frames"]
    _tm_pos_cols = [c for c in _tm_X.columns if c.startswith("pos_f") or c == "has_positions"]
    _tm_sets = {"context": _tm_ctx_cols}
    if _tm_frame_cols:
        _tm_sets["context+frames"] = _tm_ctx_cols + _tm_frame_cols
    if _tm_pos_cols:
        _tm_sets["context+positions"] = _tm_ctx_cols + _tm_pos_cols
    if _tm_frame_cols and _tm_pos_cols:
        _tm_sets["context+frames+positions"] = _tm_ctx_cols + _tm_frame_cols + _tm_pos_cols
    _tm_hold = pd.Series(False, index=_tm_src.index)
    for _g in TAG_MODEL_HOLDOUT_GAMES:
        _tm_hold |= _tm_groups.isin(_tm_game_matches(_g, _tm_groups))
    _tm_excl = pd.Series(False, index=_tm_src.index)
    for _g in TAG_MODEL_EXCLUDE_GAMES:
        _tm_excl |= _tm_groups.isin(_tm_game_matches(_g, _tm_groups))
    # CONFIRMED CHANGE (requested: "leave 20 plays out of the training set so they can be used for data validation").
    # TAG_MODEL_VALIDATION_PLAYS coach-tagged plays are NEVER trained on (nor used to choose the model's settings), so
    # their automatic Titles come from a model that has never seen them -- the coaches compare them in the Auto-Title
    # review. Picked from plays whose Title decodes cleanly, spread evenly through each game, and SAVED
    # (_tag_model/validation_plays.csv) so the same plays stay out every run; one that drops out is replaced.
    _tm_keys = pd.Series([f"{r.get('game_date')}|{r.get('clip_number')}|{r.get('synergy_string')}"
                          for _, r in _tm_src.iterrows()], index=_tm_src.index)
    _tm_valid = pd.Series(False, index=_tm_src.index)
    _tm_valid_keys = []
    if TAG_MODEL_VALIDATION_PLAYS:
        _vpath = os.path.join(TAG_MODEL_DIR, "validation_plays.csv")
        _vsaved = pd.read_csv(_vpath)["clip_key"].astype(str).tolist() if os.path.exists(_vpath) else []
        _pool = (_tm_lab["tagged"] & (pd.Series(range(len(_tm_src)), index=_tm_src.index) < _tm_n_pc) & ~_tm_excl & ~_tm_hold
                 & _tm_src.get("decode_quality", pd.Series("", index=_tm_src.index)).eq("Clean"))
        _pool_keys = set(_tm_keys[_pool])
        _tm_valid_keys = [k for k in dict.fromkeys(_vsaved) if k in _pool_keys][:TAG_MODEL_VALIDATION_PLAYS]
        _need = TAG_MODEL_VALIDATION_PLAYS - len(_tm_valid_keys)
        if _need > 0:
            _cand = _tm_src[_pool & ~_tm_keys.isin(_tm_valid_keys)].assign(_k=_tm_keys, _g=_tm_groups)
            _cand = _cand.sort_values(["_g", "clip_number"])
            if len(_cand):
                _pick = np.unique(np.linspace(0, len(_cand) - 1, min(_need, len(_cand))).round().astype(int))
                _tm_valid_keys += _cand["_k"].iloc[_pick].tolist()
        pd.DataFrame({"clip_key": _tm_valid_keys}).to_csv(_vpath, index=False)
        _tm_valid = _tm_keys.isin(_tm_valid_keys)
        print(f"  [tag model] {int(_tm_valid.sum())} coach-tagged play(s) kept OUT of training for validation "
              f"(TAG_MODEL_VALIDATION_PLAYS; list in {_vpath})", flush=True)
    if TAG_MODEL_HOLDOUT_GAMES and not _tm_hold.any():
        print(f"  [tag model] no clips matched TAG_MODEL_HOLDOUT_GAMES {TAG_MODEL_HOLDOUT_GAMES}")
    _tm_now = pd.Timestamp.now().isoformat(timespec="seconds")
    _tm_rows = []
    # CONFIRMED CHANGE (requested: speed up reruns). A fingerprint of everything a field's model is built from
    # (every input, every label, the settings); with TAG_MODEL_RETRAIN = "auto", a field whose fingerprint
    # matches its saved model is reused instead of re-scored and retrained (the slowest part of this cell).
    import hashlib as _tm_hash
    _tm_sig_base = _tm_hash.md5(
        pd.util.hash_pandas_object(_tm_X.astype(str), index=True).values.tobytes()
        + pd.util.hash_pandas_object(_tm_lab.astype(str), index=True).values.tobytes()
        + repr((TAG_MODEL_C_OPTIONS, TAG_MODEL_MIN_CLASS_EXAMPLES, TAG_MODEL_MIN_TRAIN_ROWS, TAG_MODEL_MIN_CONFIDENCE,
                TAG_MODEL_HOLDOUT_GAMES, TAG_MODEL_EXCLUDE_GAMES, TAG_MODEL_TARGETS, TAG_MODEL_LINEUP_LIMITED,
                sorted(_tm_valid_keys))).encode()
    ).hexdigest()
    _tm_any_retrained = False
    for _field, _col in TAG_MODEL_TARGETS.items():
        _y = _tm_lab[_col].where(~_tm_excl & ~_tm_valid).astype(object) if _col in _tm_lab.columns else pd.Series(dtype=object)
        _path = os.path.join(TAG_MODEL_DIR, f"{_field}.joblib")
        _counts = _y.value_counts()
        _rare = _counts[_counts < TAG_MODEL_MIN_CLASS_EXAMPLES]
        _y_fit = _y.where(~_y.isin(_rare.index))
        _row = {"field": _field, "label_column": _col, "tagged_clips": int(_y.notna().sum()),
                "answers_learned": int(_y_fit.dropna().nunique()), "trained_at": _tm_now,
                "not_learned_yet": " | ".join(f"{k} ({v})" for k, v in _rare.items())}
        _model, _only, _share = None, None, None
        _oof = None
        _train = _y_fit.notna() & ~_tm_hold   # held-out games are never trained on
        _sig = _tm_sig_base + _field
        _retrain = bool(TAG_MODEL_RETRAIN)
        _saved = None
        if TAG_MODEL_RETRAIN == "auto" and os.path.exists(_path):
            try:
                _saved = joblib.load(_path)
            except Exception:
                _saved = None
            _retrain = not (_saved and _saved.get("sig") == _sig)
        if not _retrain and TAG_MODEL_RETRAIN == "auto" and _saved:
            # unchanged since the saved model: reuse it AND its scores
            _model, _only, _share = _saved["model"], _saved.get("only"), _saved.get("share")
            if _saved.get("oof") and len(_saved["oof"][0]) == len(_tm_src):
                _oof = (pd.Series(_saved["oof"][0], index=_tm_src.index, dtype=object),
                        pd.Series(_saved["oof"][1], index=_tm_src.index, dtype=float))
            _row.update(_saved.get("report_row") or {})
            _row["scored_how"] = f"{_row.get('scored_how', '')} (unchanged data -- reused model from {_saved['trained_at']})"
        elif _retrain and _y_fit.dropna().nunique() == 1 and _y_fit.notna().sum() >= TAG_MODEL_MIN_TRAIN_ROWS:
            # Every tagged clip has the same answer (e.g. all man-to-man so far): nothing to learn yet, so predict
            # that answer, with confidence = its share of ALL tagged answers (rare ones included).
            _only = _y_fit.dropna().iloc[0]
            _share = round(float((_y == _only).sum() / _y.notna().sum()), 2)
            _row.update(scored_how=f"only one answer tagged so far ({_only}): predicted for every clip at {_share:.0%}",
                        using="only answer")
            _tm_any_retrained = True
            joblib.dump({"model": None, "only": _only, "share": _share, "columns": [], "all_columns": list(_tm_X.columns),
                         "sig": _sig, "report_row": {k: v for k, v in _row.items() if k != "trained_at"},
                         "trained_at": _tm_now}, _path)
        elif _retrain:
            _tm_any_retrained = True
            if _y_fit.notna().sum() < TAG_MODEL_MIN_TRAIN_ROWS or _y_fit.dropna().nunique() < 2:
                _row["scored_how"] = (f"not trained: needs {TAG_MODEL_MIN_TRAIN_ROWS}+ tagged clips over 2+ answers "
                                      f"(has {int(_y_fit.notna().sum())} over {_y_fit.dropna().nunique()})")
            else:
                _hold_arg = _tm_hold if TAG_MODEL_HOLDOUT_GAMES else None
                _lim_col = TAG_MODEL_LINEUP_LIMITED.get(_field)
                _lim = _tm_src[_lim_col] if _lim_col and _lim_col in _tm_src.columns else None
                # Which inputs help THIS field (requested: "does positions/frames help?"): score each combination
                # on held-out clips and keep the best -- so noisy image numbers can't drag a field down, and the
                # report says per field what actually helped.
                _best = None
                for _set_name, _set_cols in _tm_sets.items():
                    TAG_MODEL_C = 0.2
                    _p, _c, _how = _tm_score(_tm_X[_set_cols], _y_fit, _tm_groups, _hold_arg, _lim)
                    _s = _p.notna() & _y_fit.notna()
                    _acc = (_p[_s] == _y_fit[_s]).mean() if _s.any() else -1
                    if _best is None or _acc > _best[0] + 0.005:   # a tie keeps the simpler set
                        _best = (_acc, 0.2, _p, _c, _how, _s, _set_name)
                _set_name = _best[6]
                _Xs = _tm_X[_tm_sets[_set_name]]
                for _cval in TAG_MODEL_C_OPTIONS:
                    if _cval == 0.2:
                        continue
                    TAG_MODEL_C = _cval
                    _p, _c, _how = _tm_score(_Xs, _y_fit, _tm_groups, _hold_arg, _lim)
                    _s = _p.notna() & _y_fit.notna()
                    _acc = (_p[_s] == _y_fit[_s]).mean() if _s.any() else -1
                    if _acc > _best[0]:
                        _best = (_acc, _cval, _p, _c, _how, _s, _set_name)
                _acc, _cval, _p, _c, _how, _s, _set_name = _best
                _oof = (_p, _c)                      # each clip predicted WITHOUT learning from its own Title
                TAG_MODEL_C = _cval
                _row["features"] = _set_name
                # Baseline: always guess the most common answer IN THE TRAINING clips, scored on the same clips.
                _most = _y_fit[_train].value_counts().index[0]
                _base = _y_fit[_s].eq(_most).mean() if _s.any() else None
                _conf = _s & (_c >= TAG_MODEL_MIN_CONFIDENCE)
                _row.update(scored_how=_how, clips_scored=int(_s.sum()), model_c=_cval,
                            accuracy_pct=round(100 * _acc) if _s.any() else None,
                            baseline_pct=round(100 * _base) if _base is not None else None,
                            confident_pct=round(100 * _conf.sum() / _s.sum()) if _s.any() else None,
                            confident_accuracy_pct=round(100 * (_p[_conf] == _y_fit[_conf]).mean()) if _conf.any() else None)
                if _base is not None and _acc <= _base:
                    # Not learning yet: predict the most common answer, at its share of the training clips.
                    _only = _most
                    _share = round(float(_y_fit[_train].eq(_most).mean()), 2)
                    _oof = None
                    _row["using"] = f"most common answer ({_most}) -- model not better yet"
                else:
                    _model = _tm_pipeline(_Xs).fit(_Xs[_train], _y_fit[_train])
                    _row["using"] = "model"
                joblib.dump({"model": _model, "only": _only, "share": _share, "columns": list(_Xs.columns),
                             "all_columns": list(_tm_X.columns), "sig": _sig,
                             "oof": ([None if pd.isna(v) else v for v in _oof[0].tolist()], _oof[1].tolist()) if _oof else None,
                             "report_row": {k: v for k, v in _row.items() if k != "trained_at"},
                             "trained_at": _tm_now,
                             "frame_encoder": TAG_MODEL_FRAME_ENCODER if _tm_frames is not None else None}, _path)
        elif os.path.exists(_path):
            _saved = _saved or joblib.load(_path)
            if _saved.get("all_columns", _saved["columns"]) == list(_tm_X.columns):
                _model, _only, _share = _saved["model"], _saved.get("only"), _saved.get("share")
                _row.update(scored_how=f"reused model trained {_saved['trained_at']}", trained_at=_saved["trained_at"],
                            using="model" if _model is not None else f"most common answer ({_only})")
            else:
                _row["scored_how"] = "saved model doesn't match this run's features (frames on/off?) -- retrain"
        _tm_rows.append(_row)
        _pred = pd.Series(None, index=_tm_src.index, dtype=object)
        _pconf = pd.Series(np.nan, index=_tm_src.index)
        if _only is not None:
            _pred[:] = _only
            _pconf[:] = _share
        elif _model is not None:
            _cols_used = _saved["columns"] if not _retrain else list(_Xs.columns)
            _lim_col = TAG_MODEL_LINEUP_LIMITED.get(_field)
            _proba = _tm_limit(_model.predict_proba(_tm_X[_cols_used]), _model.classes_,
                               _tm_src[_lim_col].tolist() if _lim_col and _lim_col in _tm_src.columns else None)
            _pred[:] = _model.classes_[_proba.argmax(1)]
            _pconf[:] = _proba.max(1).round(2)
        play_calls[f"pred_{_field}"] = _pred.iloc[:_tm_n_pc].to_numpy()
        play_calls[f"pred_{_field}_conf"] = _pconf.iloc[:_tm_n_pc].to_numpy()
        # held-out: what the model predicts for a tagged clip WITHOUT learning from its Title (the honest comparison
        # for the Auto-Title review); a constant answer is the same with or without the clip
        if _oof is not None:
            play_calls[f"heldout_{_field}"] = pd.Series(_oof[0]).iloc[:_tm_n_pc].to_numpy()
            play_calls[f"heldout_{_field}_conf"] = pd.Series(_oof[1]).iloc[:_tm_n_pc].to_numpy()
        elif _only is not None:
            play_calls[f"heldout_{_field}"] = play_calls[f"pred_{_field}"]
            play_calls[f"heldout_{_field}_conf"] = play_calls[f"pred_{_field}_conf"]
        else:
            # a model saved before held-out predictions were kept: unknown until its next retrain (never the
            # in-memory prediction -- it learned from this clip's Title, which would flatter the review)
            play_calls[f"heldout_{_field}"] = None
            play_calls[f"heldout_{_field}_conf"] = np.nan
        # the coach's own answer for this field (from the decoded Title), for the review
        # what the COACH tagged (before review answers) -- shown as "Coach" and used for the coach-Title comparisons
        play_calls[f"coach_{_field}"] = _tm_lab_coach[_col].iloc[:_tm_n_pc].to_numpy() if _col in _tm_lab_coach.columns else None
        # validation plays were never trained on: the final model's answer IS their held-out answer
        _vm = _tm_valid.iloc[:_tm_n_pc].to_numpy()
        if _vm.any():
            play_calls[f"heldout_{_field}"] = play_calls[f"heldout_{_field}"].astype(object)
            play_calls.loc[_vm, f"heldout_{_field}"] = play_calls.loc[_vm, f"pred_{_field}"]
            play_calls.loc[_vm, f"heldout_{_field}_conf"] = play_calls.loc[_vm, f"pred_{_field}_conf"]
    play_calls["tag_validation"] = _tm_valid.iloc[:_tm_n_pc].to_numpy()
    # the honest score: the validation plays, which no model ever trained on
    _vrows = []
    if _tm_valid.any():
        _vpc = play_calls[play_calls["tag_validation"]]
        for _field in TAG_MODEL_TARGETS:
            _c_, _p_, _cf = _vpc.get(f"coach_{_field}"), _vpc.get(f"pred_{_field}"), _vpc.get(f"pred_{_field}_conf")
            if _c_ is None or _p_ is None:
                continue
            _has = _c_.notna() & _c_.astype(str).str.strip().ne("")
            if not _has.any():
                continue
            _ok = (_p_[_has].astype(str).str.lower() == _c_[_has].astype(str).str.lower())
            _sure = _cf[_has].fillna(0) >= TAG_MODEL_MIN_CONFIDENCE
            _vrows.append({"field": _field, "validation_plays": int(_has.sum()), "right": int(_ok.sum()),
                           "accuracy_pct": round(100 * _ok.mean()), "confident": int(_sure.sum()),
                           "confident_right_pct": round(100 * _ok[_sure].mean()) if _sure.any() else None})
        print(f"  [tag model] on the {int(_tm_valid.sum())} validation plays (never trained on): "
              + "; ".join(f"{r['field']} {r['right']}/{r['validation_plays']}"
                          + (f" (confident: {r['confident_right_pct']}% of {r['confident']})" if r['confident'] else "")
                          for r in _vrows), flush=True)
    tag_model_validation = pd.DataFrame(_vrows)
    tag_model_report = pd.DataFrame(_tm_rows, columns=tag_model_report.columns)
    if _tm_any_retrained:
        _hist = os.path.join(TAG_MODEL_DIR, "history.csv")
        _hist_old = pd.read_csv(_hist) if os.path.exists(_hist) else pd.DataFrame()
        pd.concat([_hist_old, tag_model_report], ignore_index=True).to_csv(_hist, index=False)
    for _r in tag_model_report.itertuples():
        if pd.notna(_r.accuracy_pct):
            _f = lambda v: "--" if v is None or pd.isna(v) else f"{v:.0f}"
            print(f"  {_r.field:22} {_f(_r.accuracy_pct):>3}% right (always-most-common: {_f(_r.baseline_pct)}%)  "
                  f"n={int(_r.clips_scored)}  | confident on {_f(_r.confident_pct)}%, {_f(_r.confident_accuracy_pct)}% right"
                  + (f"  [{_r.features}]" if _r.using == "model" else f"  -> using {_r.using}")
                  + ("  (unchanged -- reused)" if "unchanged data" in str(_r.scored_how) else ""))
        else:
            print(f"  {_r.field:22} {_r.scored_how}")
    _scored = tag_model_report.loc[tag_model_report["accuracy_pct"].notna(), "scored_how"]
    if len(_scored):
        print(f"  Scored on: {str(_scored.iloc[0]).split(' (unchanged data')[0]}")


# ---- Suggested Title, in the coaches' format, from confident predictions only ---------------------------------
_TM_SYNERGY_DETAILS = [
    (r"\bP&R Ball Handler\b|\bP&R Roll Man\b|\bPick and Pops?\b", "bs"), (r"\bGo Away from Pick\b", "reject"),
    (r"\bSlips?\b", "slip"), (r"\bPick and Pops?\b", "pop"), (r"\bHand Off\b", "dho"),
    (r"\bOff Screen\b(?!.*\bFlare\b)", "ds"), (r"\bFlare\b", "flare"), (r"\bCut\b", "cut"),
    (r"\bPost-Up\b", "post"), (r"\bISO\b", "iso"),
]


def _tm_code(name, table):
    """Decoded name -> the shorthand coaches type ('Top Lock' -> 'tl'), from the decoder's own tables."""
    for code, (full, _conf) in table.items():
        if full == name:
            return code
    return str(name).lower()


def _tm_jersey_of(name):
    """Roster/Synergy jersey number for a player name (from the play-calls cell's jersey book), or None."""
    book = globals().get("_tm_book")
    if book is None:
        book = globals()["_tm_book"] = (_pl_jersey_book() if "_pl_jersey_book" in globals() else {})
    for team_book in book.values():
        for j, n in team_book.items():
            if str(n).strip().lower() == str(name).strip().lower():
                return j
    return None


def _tm_suggest(r):
    def ok(f):
        v, c = r.get(f"pred_{f}"), r.get(f"pred_{f}_conf")
        return v if v is not None and not (isinstance(v, float) and pd.isna(v)) and pd.notna(c) and c >= TAG_MODEL_MIN_CONFIDENCE else None
    sit = ok("situation")
    if sit == "Transition":
        return "tran"
    details = [t for p, t in _TM_SYNERGY_DETAILS if re.search(p, str(r.get("synergy_string") or ""))]
    form = ok("formation")
    call = ok("play_call")
    head = "-".join(x for x in [
        sit.lower() if sit in ("BLOB", "SLOB") else None,
        str(form).lower() if form else None,
        call if call and call != "Motion" else None] if x)
    offense = f"{head}({','.join(dict.fromkeys(details))})" if details else head
    press = ok("press")
    press_code = ""
    if press and press != "None":
        m = re.match(r"^([\d-]+) Press$", press)
        press_code = (m.group(1).replace("-", "") if m else {"Run & Jump": "rj"}.get(press, "press")) + " - "
    dform = ok("defense")
    dcode = {"Man-to-Man": "m2m"}.get(dform, str(dform).lower() if dform else "")
    covs = [c for c in (ok("offball_coverage"), ok("ball_screen_coverage")) if c]
    cov_codes = [_tm_code(c, {**_PT_OFFBALL_COVERAGE, **_PT_BALL_COVERAGE, **_PT_EITHER_COVERAGE}) for c in covs]
    # One coverage predicted AND a confident screen defender -> put his jersey on it, the way coaches tag ("12drop").
    who = ok("screen_defender")
    if who and len(cov_codes) == 1:
        jersey = who[1:] if str(who).startswith("#") else _tm_jersey_of(who)
        if jersey:
            cov_codes = [f"{jersey}{cov_codes[0]}"]
    if press_code and not dcode:
        press_code = press_code[:-3]  # "rj" alone, not "rj - "
    defense = f"{press_code}{dcode}" + (f" ({','.join(cov_codes)})" if cov_codes else "")
    title = f"{offense}: {defense}".strip()
    return None if title.strip(" :") == "" else title


if RUN_TAG_MODEL and not play_calls.empty and any(c.startswith("pred_") for c in play_calls.columns):
    _tm_book = None   # rebuilt from this run's rosters
    play_calls["suggested_title"] = play_calls.apply(_tm_suggest, axis=1)
    _n_untagged = int((play_calls["suggested_title"].notna() & ~_tm_lab["tagged"].iloc[:_tm_n_pc].to_numpy()).sum())
    print(f"  Suggested Titles: {int(play_calls['suggested_title'].notna().sum())} clip(s), "
          f"{_n_untagged} of them not tagged by a coach yet.")
