# 48_jersey_number_recognizer.py -- code for the notebook section "Jersey-number recognizer: a small image model trained on YOUR film -----------------------"
# Runs inside the notebook via run_section("48_jersey_number_recognizer"); its settings are in that notebook cell.

# --- Jersey-number recognizer: a small image model trained on YOUR film ---------------------------------------------
# CONFIRMED CHANGE (requested after the Roboflow basketball article: build a jersey-number recognizer trained on labeled
# crops -- there, off-the-shelf reading got 56% of numbers and a small model trained on 3,600 labeled crops got 93% -- and
# "give me a parameter to add more frames to the training set later and train it again").
#
# A ResNet-18 (a small, standard image model) looks at a player's chest crop and says which number it is. It learns from
# a TRAINING SET that grows every run, kept in INPUT_DIR/jersey_training/<source>/<number>/*.jpg:
#   reads/   players PaddleOCR named by jersey number (confident reads): several chest crops from each track, INCLUDING
#            frames where PaddleOCR could NOT read the number -- exactly what this model has to learn
#   coach/   your checks (true numbers). By default these are the TEST set, not trained on, so the reader test's
#            "on YOUR checked players" score for the "trained" reader is honest (JERSEY_TRAIN_USE_COACH = True adds them)
#   extra/   anything in JERSEY_TRAIN_EXTRA_DIRS: folders of <number>/ images, or Roboflow JSONL exports -- e.g. Roboflow's
#            NBA "basketball-jersey-numbers-ocr" set (3,615 crops, CC BY 4.0), downloaded here if you give an API key
# It is then one more reader ("trained") in the Jersey-number reader test, scored on your checked players like the rest,
# and used by tracking only if it wins there. It reads a crop in a few milliseconds, so tracking can read more per player.
#
# Settings for later: JERSEY_TRAIN_ADD_FRAMES adds this run's labeled crops; JERSEY_TRAIN_EXTRA_DIRS adds more data;
# JERSEY_TRAIN_NOW = "auto" retrains whenever the training set changed (True = retrain now, False = keep the saved model).
import os
import re
import sys
import time
import glob
import json
import hashlib
import subprocess
import numpy as np
import pandas as pd



def _jr_chest(img, box):
    """The chest region the recognizer sees (same region the PaddleOCR color reader gets, before enlarging)."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    c = img[max(int(y1 + 0.10 * h), 0):max(int(y1 + 0.62 * h), int(y1 + 0.10 * h) + 1),
            max(int(x1 - 0.05 * w), 0):max(int(x2 + 0.05 * w), int(x1) + 1)]
    return c if c.size else None


def _jr_det_cache():
    dets = sorted([d for d in glob.glob(os.path.join(INPUT_DIR, "_tracking", "detections_*tiles*.pkl")) if "jersey" not in d],
                  key=os.path.getmtime)
    return pd.read_pickle(dets[-1]) if dets else {}


def _jr_box_at(det, frame, px, py):
    d = det.get(frame)
    if d is None or not len(d["p"]):
        return None
    p = d["p"]
    j = int(np.argmin(np.hypot((p[:, 0] + p[:, 2]) / 2 - px, p[:, 3] - py)))
    if np.hypot((p[j, 0] + p[j, 2]) / 2 - px, p[j, 3] - py) > 25:
        return None
    if _jr_hidden(p, j):
        return None                  # partly hidden behind someone in front: the chest crop may show the other person
    return [float(v) for v in p[j, :4]]


def _jr_hidden(p, j):
    """CONFIRMED CHANGE (requested; clip 1 t048: Luke Bara's box was 42% covered by the box of a coach standing IN FRONT of him,
    so Bara's chest crop showed part of the coach). True when a box whose feet are lower on the picture (closer to the camera)
    covers more than JERSEY_MAX_HIDDEN of box j. Such a box never becomes a training or test crop (on the saved checks this
    skips about 15% of the checked boxes)."""
    try:
        lim = float(globals().get("JERSEY_MAX_HIDDEN", 0.3))
        if lim <= 0:
            return False
        a = p[j]
        area = max(float(a[2] - a[0]) * float(a[3] - a[1]), 1e-6)
        for k in range(len(p)):
            if k == j or float(p[k, 3]) <= float(a[3]):
                continue                               # only someone in FRONT (feet lower) can hide him
            ix = max(0.0, min(float(a[2]), float(p[k, 2])) - max(float(a[0]), float(p[k, 0])))
            iy = max(0.0, min(float(a[3]), float(p[k, 3])) - max(float(a[1]), float(p[k, 1])))
            if ix * iy / area > lim:
                return True
        return False
    except Exception:
        return False


def _jr_save(img, box, path):
    import cv2
    if os.path.exists(path):
        return False
    c = _jr_chest(img, box)
    if c is None or min(c.shape[:2]) < 8:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cv2.imwrite(path, c)
    return True


def _jr_name(frame, box):
    return re.sub(r"[^A-Za-z0-9]+", "_", frame)[-60:] + f"_{int(box[0])}_{int(box[1])}.jpg"


def jersey_collect():
    """Add this run's labeled crops to the training set. -> counts per source."""
    import cv2
    added = {"reads": 0, "coach": 0, "extra": 0}
    det = _jr_det_cache()
    vfd = globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames")
    imgs = {}

    def _img(f):
        if f not in imgs:
            if len(imgs) > 200:
                imgs.clear()
            imgs[f] = cv2.imread(os.path.join(vfd, f), cv2.IMREAD_COLOR)
        return imgs[f]

    # coach checks: the true number at the checked frame
    coach_spots = set()
    _nums_by_game = {}
    for ch in coach_checks_all()[0]:                  # every checks file, merged -- the latest check of a box wins
        gd, gc = str(ch.get("game") or "|").split("|", 1)
        if (gd, gc) not in _nums_by_game:
            _nums_by_game[(gd, gc)] = _trk_numbers_for_game(gd, gc)
        num = _nums_by_game[(gd, gc)].get(str(ch.get("true_name") or "").lower())
        box = _jr_box_at(det, ch.get("frame_file"), ch.get("px", -1e9), ch.get("py", -1e9))
        if box is None:
            continue
        fname = _jr_name(ch["frame_file"], box)
        coach_spots.add((ch["frame_file"], int(box[0]), int(box[1])))
        # a box re-checked as someone else (or "not a player"): its crop must not stay under the old number
        for old_ in glob.glob(os.path.join(JERSEY_TRAIN_DIR, "coach", "*", fname)):
            if os.path.basename(os.path.dirname(old_)) != num:
                os.remove(old_)
        if not num:
            continue
        im = _img(ch["frame_file"])
        if im is not None and _jr_save(im, box, os.path.join(JERSEY_TRAIN_DIR, "coach", num, fname)):
            added["coach"] += 1
    # players named by jersey number in the last tracking run: crops from across each track
    pt = globals().get("player_tracks")
    if not isinstance(pt, pd.DataFrame) or pt.empty:
        p_ = os.path.join(OUTPUT_DIR, "uww_player_tracks.csv")
        pt = pd.read_csv(p_) if os.path.exists(p_) else pd.DataFrame()
    pcs = globals().get("play_calls", pd.DataFrame())
    # every saved jersey reading, by spot on the picture: (frame, x1, y1) -> [(key, [(text, conf)])]
    _reads_by_spot = {}
    _jp = os.path.join(INPUT_DIR, "_tracking", "jersey_numbers.pkl")
    if os.path.exists(_jp):
        for key_, v in pd.read_pickle(_jp).items():
            parts = str(key_).split("|")
            # its OWN readings never become its training labels (it would learn its own mistakes) unless asked
            if len(parts) >= 6 and parts[5].startswith("trained") and not JERSEY_TRAIN_FROM_OWN_READS:
                continue
            if len(parts) >= 6 and v:
                _reads_by_spot.setdefault((parts[0], int(parts[1]), int(parts[2])), []).append((key_, v))
    # CONFIRMED BUG (fixed): this used play_calls' "track_clip_key", a column Player tracking creates -- but this cell
    # runs BEFORE Player tracking, so the column didn't exist yet and every jersey-number track was skipped ("added 0").
    # The clip key is rebuilt here the same way tracking builds it (game date | clip number | Synergy description).
    _n_jt = _n_jt_read = 0
    if pt.empty or "name_how" not in pt.columns:
        print("  [recognizer] no player tracks with name sources from an earlier run yet (run Player tracking once)", flush=True)
    elif not pcs.empty and "track_files" in pcs.columns:
        _pc = pcs[pcs["track_files"].notna()].copy()
        _pc["_key"] = [f"{r.get('game_date')}|{r.get('clip_number')}|{r.get('synergy_string')}" for _, r in _pc.iterrows()]
        meta = _pc.drop_duplicates("_key").set_index("_key")
        for _, t in pt[pt["name_how"] == "jersey number"].iterrows():
            if t["clip_key"] not in meta.index:
                continue
            r = meta.loc[t["clip_key"]]
            num = _trk_numbers_for_game(str(r["game_date"]), str(r["game_code"])).get(str(t["name"]).lower())
            files = [f for f in str(r.get("track_files") or "").split(";") if f]
            if not num or not files:
                continue
            _n_jt += 1
            path = [p for p in json.loads(t["path"]) if len(p) >= 6 and int(p[0]) < len(files)]
            boxes = {int(p[0]): _jr_box_at(det, files[int(p[0])], p[4], p[5]) for p in path}
            # the frames where this number was actually READ on this track (a confident read)
            read_t = [tt for tt, b in boxes.items() if b is not None and any(
                txt == num and cf >= 0.5 for key_, v in _reads_by_spot.get((files[tt], int(b[0]), int(b[1])), []) for txt, cf in v)]
            if not read_t:
                continue
            _n_jt_read += 1
            fps_ = float(globals().get("VISION_TRACK_FPS") or 2.0)
            near = [tt for tt in sorted(boxes) if boxes[tt] is not None
                    and min(abs(tt - r_) for r_ in read_t) <= JERSEY_TRAIN_NEAR_READ_S * fps_]
            for tt in [near[int(k)] for k in np.linspace(0, len(near) - 1, min(JERSEY_TRAIN_CROPS_PER_TRACK, len(near)))]:
                f, box = files[tt], boxes[tt]
                if (f, int(box[0]), int(box[1])) in coach_spots:     # never train on a test crop
                    continue
                im = _img(f)
                c = _jr_chest(im, box) if im is not None else None
                if c is None or cv2.Laplacian(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() < JERSEY_TRAIN_MIN_SHARPNESS:
                    continue
                if _jr_save(im, box, os.path.join(JERSEY_TRAIN_DIR, "reads", num, _jr_name(f, box))):
                    added["reads"] += 1
    added["_tracks"] = (_n_jt, _n_jt_read)
    return added


def jersey_import_extra():
    """Extra labeled data: folders of <number>/ images, or JSONL exports ({"image": ..., "suffix": "23"}) -> extra/."""
    import shutil
    import cv2
    n = 0
    dirs = list(JERSEY_TRAIN_EXTRA_DIRS)
    if JERSEY_TRAIN_ROBOFLOW_API_KEY:
        rf_dir = os.path.join(JERSEY_TRAIN_DIR, "_roboflow_nba")
        if not os.path.exists(rf_dir):
            try:
                import importlib
                if importlib.util.find_spec("roboflow") is None:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "roboflow"])
                from roboflow import Roboflow
                print("  [recognizer] downloading Roboflow's NBA jersey-number set (CC BY 4.0), once...", flush=True)
                proj = Roboflow(api_key=JERSEY_TRAIN_ROBOFLOW_API_KEY).workspace("roboflow-jvuqo").project(
                    "basketball-jersey-numbers-ocr")
                proj.version(JERSEY_TRAIN_ROBOFLOW_VERSION).download("jsonl", location=rf_dir)
            except Exception as e:
                print(f"  [recognizer] Roboflow download didn't work ({type(e).__name__}: {e}). You can download it from "
                      f"universe.roboflow.com/roboflow-jvuqo/basketball-jersey-numbers-ocr (format: JSONL), unzip it, "
                      f"and put that folder in JERSEY_TRAIN_EXTRA_DIRS.", flush=True)
        if os.path.exists(rf_dir):
            dirs.append(rf_dir)
    for d in dirs:
        tag = re.sub(r"[^A-Za-z0-9]+", "_", os.path.basename(os.path.normpath(d)))[:30]
        # JSONL exports
        for jl in glob.glob(os.path.join(d, "**", "*.jsonl"), recursive=True):
            with open(jl, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    num = re.sub(r"\D", "", str(rec.get("suffix") or rec.get("text") or rec.get("label") or ""))
                    src = os.path.join(os.path.dirname(jl), str(rec.get("image") or ""))
                    if not num or len(num) > 2 or not os.path.exists(src):
                        continue
                    dst = os.path.join(JERSEY_TRAIN_DIR, "extra", num, f"{tag}_{os.path.basename(src)}")
                    if not os.path.exists(dst):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src, dst)
                        n += 1
        # <number>/ image folders (skipped when the folder IS the training set's own extra/ folder, e.g. JERSEY_TRAIN_EXTRA_DIRS
        # pointing at inputs/jersey_training/extra: its number folders are already the result of the import -- copying them
        # into themselves would add every image again, with a longer name, on every run)
        _in_place = os.path.abspath(d).startswith(os.path.abspath(os.path.join(JERSEY_TRAIN_DIR, "extra")))
        for sub in ([] if _in_place else glob.glob(os.path.join(d, "*"))):
            num = os.path.basename(sub)
            if not (os.path.isdir(sub) and re.fullmatch(r"\d{1,2}", num)):
                continue
            for src in glob.glob(os.path.join(sub, "*")):
                if src.lower().endswith((".jpg", ".jpeg", ".png")):
                    dst = os.path.join(JERSEY_TRAIN_DIR, "extra", num, f"{tag}_{os.path.basename(src)}")
                    if not os.path.exists(dst):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src, dst)
                        n += 1
    return n


def _jr_play_key(fname):
    """The PLAY a crop came from: its file name without the frame number and box position. CONFIRMED CHANGE (requested: the
    test half must not share plays with the training half). The same player a fraction of a second apart in the same play
    used to land in both halves, which flatters the score; now a whole play is on one side."""
    return re.sub(r"_(?:t)?\d+_jpg_\d+_\d+\.jpg$", "", os.path.basename(fname))


def _jr_coach_half(fname):
    """Which half of the coach checks a crop belongs to -- 'train' or 'test' -- fixed by its PLAY (JERSEY_TRAIN_SPLIT_BY =
    "play"; "crop" = the old split by file name), so a crop never switches halves between runs."""
    key = _jr_play_key(fname) if str(globals().get("JERSEY_TRAIN_SPLIT_BY", "play")).lower() == "play" else os.path.basename(fname)
    return "train" if int(hashlib.md5(key.encode()).hexdigest(), 16) % 2 == 0 else "test"


def _jr_train_sources():
    return ["reads", "extra"] + (["coach"] if JERSEY_TRAIN_USE_COACH else [])


def _jr_samples(sources):
    out = []
    for s in sources:
        for f in glob.glob(os.path.join(JERSEY_TRAIN_DIR, s, "*", "*")):
            if not f.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            # only <number>/ folders are labels: a Roboflow download unzipped in place has train/, valid/ and test/ folders beside
            # the number folders, and their images (labels are in annotations.jsonl) must never be read as a class called "train"
            if not re.fullmatch(r"\d{1,2}", os.path.basename(os.path.dirname(f))):
                continue
            # CONFIRMED CHANGE (requested: trained recognizer only -- EasyOCR / PaddleOCR removed, so the coach checks
            # are its main training data). JERSEY_TRAIN_USE_COACH = "half": half the checked players train it, the other
            # half stay the reader test's answer key (fixed per crop).
            if s == "coach" and JERSEY_TRAIN_USE_COACH == "half" and _jr_coach_half(f) != "train":
                continue
            out.append((f, os.path.basename(os.path.dirname(f))))
    return sorted(out)


def jersey_train():
    """Train the recognizer on the training set (CPU; a few to ~20 minutes depending on how much data)."""
    import torch
    import torchvision
    from torchvision import transforms
    from PIL import Image
    train_src = _jr_train_sources()
    samples = _jr_samples(train_src)
    classes = sorted({lab for _, lab in samples}, key=lambda x: (len(x), x))
    idx = {c: i for i, c in enumerate(classes)}
    rs = np.random.RandomState(0)
    order = rs.permutation(len(samples))
    n_val = max(1, int(0.15 * len(samples)))
    val = [samples[i] for i in order[:n_val]]
    tr = [samples[i] for i in order[n_val:]]
    norm = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    t_train = transforms.Compose([transforms.RandomResizedCrop(128, scale=(0.7, 1.0), ratio=(0.6, 1.4)),
                                  transforms.ColorJitter(0.3, 0.3, 0.3, 0.05), transforms.RandomRotation(8),
                                  transforms.RandomGrayscale(0.1), transforms.ToTensor(), norm])   # never flipped: 2 != S
    t_eval = transforms.Compose([transforms.Resize((128, 128)), transforms.ToTensor(), norm])

    class _DS(torch.utils.data.Dataset):
        def __init__(self, items, tf):
            self.items, self.tf = items, tf
        def __len__(self):
            return len(self.items)
        def __getitem__(self, k):
            f, lab = self.items[k]
            return self.tf(Image.open(f).convert("RGB")), idx[lab]

    try:
        net = torchvision.models.resnet18(weights=torchvision.models.ResNet18_Weights.IMAGENET1K_V1)
    except Exception:
        net = torchvision.models.resnet18(pretrained=True)
    net.fc = torch.nn.Linear(net.fc.in_features, len(classes))
    # CONFIRMED CHANGE (requested; the 45% test showed 32 and 15 as the answer to many other numbers): the model leaned toward
    # the numbers most common in the training pictures. Each draw is now weighted so every NUMBER counts about equally
    # (JERSEY_TRAIN_BALANCE: 1 = fully equal, 0 = off, 0.75 = mostly), and a crop from your own checks counts
    # JERSEY_TRAIN_COACH_WEIGHT times as much as a generic one (they are the only crops from your gym and camera).
    _bal = float(globals().get("JERSEY_TRAIN_BALANCE", 0.75))
    _cw = float(globals().get("JERSEY_TRAIN_COACH_WEIGHT", 3.0))
    _cnt_c = {}
    for _f, _l in tr:
        _cnt_c[_l] = _cnt_c.get(_l, 0) + 1
    _w = [(1.0 / (_cnt_c[_l] ** _bal)) * (_cw if (os.sep + "coach" + os.sep) in _f else 1.0) for _f, _l in tr]
    _sampler = torch.utils.data.WeightedRandomSampler(_w, num_samples=len(tr), replacement=True,
                                                      generator=torch.Generator().manual_seed(0))
    dl = torch.utils.data.DataLoader(_DS(tr, t_train), batch_size=32, sampler=_sampler, num_workers=0)
    dv = torch.utils.data.DataLoader(_DS(val, t_eval), batch_size=64, shuffle=False, num_workers=0)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, JERSEY_TRAIN_EPOCHS))
    loss_fn = torch.nn.CrossEntropyLoss(label_smoothing=0.05)
    print(f"  [recognizer] training on {len(tr):,} crops ({len(classes)} numbers), checking on {len(val):,}...", flush=True)
    t0 = time.time()
    best = (-1.0, None)
    for ep in range(JERSEY_TRAIN_EPOCHS):
        net.train()
        for xb, yb in dl:
            opt.zero_grad()
            loss_fn(net(xb), yb).backward()
            opt.step()
        sched.step()
        net.eval()
        right = tot = 0
        with torch.no_grad():
            for xb, yb in dv:
                right += int((net(xb).argmax(1) == yb).sum())
                tot += len(yb)
        acc = right / max(tot, 1)
        if acc >= best[0]:
            best = (acc, {k: v.clone() for k, v in net.state_dict().items()})
        print(f"  [recognizer]   round {ep + 1}/{JERSEY_TRAIN_EPOCHS}: {acc:.0%} of held-back crops right "
              f"({(time.time() - t0) / 60:.1f} min so far)", flush=True)
    net.load_state_dict(best[1])
    torch.save({"state_dict": net.state_dict(), "classes": classes, "n_train": len(tr), "val_acc": best[0],
                "sources": {s: sum(1 for f, _ in samples if os.sep + s + os.sep in f) for s in train_src},
                "signature": _jr_signature(), "n_samples": len(samples),
                "settings": _jr_settings_str(), "trained_at": pd.Timestamp.now().isoformat(timespec="seconds")},
               JERSEY_MODEL_PATH)
    print(f"  [recognizer] saved -> {JERSEY_MODEL_PATH} (best: {best[0]:.0%} of held-back crops right)", flush=True)


def _jr_settings_str():
    return repr((JERSEY_TRAIN_EPOCHS, str(JERSEY_TRAIN_USE_COACH), str(globals().get("JERSEY_TRAIN_SPLIT_BY", "play")),
                 float(globals().get("JERSEY_TRAIN_BALANCE", 0.75)), float(globals().get("JERSEY_TRAIN_COACH_WEIGHT", 3.0))))


def _jr_signature():
    files = [os.path.relpath(f, JERSEY_TRAIN_DIR) for f, _ in _jr_samples(_jr_train_sources())]
    return hashlib.md5((repr(files) + repr((JERSEY_TRAIN_EPOCHS, JERSEY_TRAIN_USE_COACH, globals().get("JERSEY_TRAIN_SPLIT_BY", "play"), globals().get("JERSEY_TRAIN_BALANCE", 0.75), globals().get("JERSEY_TRAIN_COACH_WEIGHT", 3.0)))).encode()).hexdigest()


def jersey_recognizer_read(crops_bgr):
    """Color chest crops -> [(number, probability)] with the saved recognizer (None if there is no model)."""
    import torch
    import torchvision
    from torchvision import transforms
    from PIL import Image
    m = globals().get("_jr_model")
    if m is None:
        if not os.path.exists(JERSEY_MODEL_PATH):
            return None
        ck = torch.load(JERSEY_MODEL_PATH, map_location="cpu")
        net = torchvision.models.resnet18(weights=None)
        net.fc = torch.nn.Linear(net.fc.in_features, len(ck["classes"]))
        net.load_state_dict(ck["state_dict"])
        net.eval()
        tf = transforms.Compose([transforms.Resize((128, 128)), transforms.ToTensor(),
                                 transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
        m = globals()["_jr_model"] = (net, ck["classes"], tf)
    net, classes, tf = m
    out = []
    with torch.no_grad():
        for c in crops_bgr:
            if c is None or c.size == 0:
                out.append(("", 0.0))
                continue
            x = tf(Image.fromarray(c[:, :, ::-1].copy())).unsqueeze(0)
            pr = torch.softmax(net(x), 1)[0]
            j = int(pr.argmax())
            out.append((classes[j], float(pr[j])))
    return out


def _jr_inputs_fingerprint():
    """Everything this cell reads -> one fingerprint. CONFIRMED CHANGE (requested: "this should only run if there is
    new information compared to the last run"). New training data can only come from: coach checks (Play review /
    validation files, in INPUT_DIR or Downloads), extra-data folders, Roboflow's set, crops added or deleted by hand in
    the training folder, or changed settings -- not from tracking runs (the recognizer never learns from its own
    readings, and the other readers are off; if they're switched back on, their readings count too)."""
    parts = []
    # CONFIRMED CHANGE (requested: everything in the data folder): coach checks are the saved reviews in
    # <data>/play_review_saves (any .json there is a review, whatever its name)
    for f in glob.glob(os.path.join(_play_review_file_saves(), "*.json")):
        parts.append((os.path.basename(f), os.path.getsize(f), int(os.path.getmtime(f))))
    def _dir_state(d):
        n, latest = 0, 0
        for root, _ds, fs in os.walk(d):
            for f in fs:
                n += 1
                latest = max(latest, int(os.path.getmtime(os.path.join(root, f))))
        return (n, latest)
    parts += [("extra", d, _dir_state(d)) for d in JERSEY_TRAIN_EXTRA_DIRS if os.path.isdir(d)]
    parts.append(("roboflow", bool(JERSEY_TRAIN_ROBOFLOW_API_KEY),
                  os.path.isdir(os.path.join(JERSEY_TRAIN_DIR, "_roboflow_nba"))))
    parts.append(("training_folder",) + _dir_state(JERSEY_TRAIN_DIR))
    if JERSEY_TRAIN_FROM_OWN_READS or any(e != "trained" for e in globals().get("JERSEY_READER_ENGINES", ["trained"])):
        for f in (os.path.join(INPUT_DIR, "_tracking", "jersey_numbers.pkl"), os.path.join(OUTPUT_DIR, "uww_player_tracks.csv")):
            parts.append((os.path.basename(f), int(os.path.getmtime(f)) if os.path.exists(f) else 0))
    parts.append(("model", int(os.path.getmtime(JERSEY_MODEL_PATH)) if os.path.exists(JERSEY_MODEL_PATH) else 0))
    parts.append(("settings", JERSEY_TRAIN_ADD_FRAMES, JERSEY_TRAIN_CROPS_PER_TRACK, JERSEY_TRAIN_NEAR_READ_S,
                  JERSEY_TRAIN_MIN_SHARPNESS, str(JERSEY_TRAIN_USE_COACH), JERSEY_TRAIN_FROM_OWN_READS, JERSEY_TRAIN_EPOCHS,
                  JERSEY_TRAIN_MIN_IMAGES, str(globals().get("JERSEY_TRAIN_SPLIT_BY", "play")),
                  float(globals().get("JERSEY_TRAIN_BALANCE", 0.75)), float(globals().get("JERSEY_TRAIN_COACH_WEIGHT", 3.0))))
    return hashlib.md5(repr(sorted(map(repr, parts))).encode()).hexdigest()


_JR_LAST_INPUTS = os.path.join(JERSEY_TRAIN_DIR, "_last_inputs.json")

if RUN_JERSEY_RECOGNIZER:
    try:
        os.makedirs(JERSEY_TRAIN_DIR, exist_ok=True)
        _jr_fp = _jr_inputs_fingerprint()
        _jr_last = None
        if os.path.exists(_JR_LAST_INPUTS):
            try:
                with open(_JR_LAST_INPUTS) as _fh:
                    _jr_last = json.load(_fh).get("fingerprint")
            except Exception:
                _jr_last = None
        if JERSEY_TRAIN_NOW is not True and _jr_last == _jr_fp and os.path.exists(JERSEY_MODEL_PATH):
            print("Jersey-number recognizer: nothing new since the last run (no new checks, extra data or settings) "
                  "-- skipped. JERSEY_TRAIN_NOW = True forces a run.", flush=True)
            raise StopIteration
        if JERSEY_TRAIN_ADD_FRAMES:
            _added = jersey_collect()
            _added["extra"] = jersey_import_extra()
            print(f"Jersey-number recognizer: added {_added['reads']} crop(s) from players named by jersey number "
                  f"({_added['_tracks'][0]} such track(s) in the last run, {_added['_tracks'][1]} with a confirmed reading to "
                  f"take crops around), {_added['coach']} from coach checks, {_added['extra']} from extra data", flush=True)
        _cnt = {s: len(_jr_samples([s])) for s in ("reads", "coach", "extra")}
        _cn = len(glob.glob(os.path.join(JERSEY_TRAIN_DIR, "coach", "*", "*")))
        _how = ("half trained on, half kept as the TEST set" if JERSEY_TRAIN_USE_COACH == "half"
                else "trained on" if JERSEY_TRAIN_USE_COACH else "kept as the TEST set")
        print(f"  training set: {_cnt['reads']:,} from jersey-number tracks, {_cnt['extra']:,} extra, {_cn:,} coach "
              f"checks ({_how})  -- {JERSEY_TRAIN_DIR}", flush=True)
        _n_coach_train = len(_jr_samples(["coach"])) if JERSEY_TRAIN_USE_COACH else 0
        _n_train = _cnt["reads"] + _cnt["extra"] + _n_coach_train
        _saved_sig, _saved_n, _saved_set = None, None, None
        if os.path.exists(JERSEY_MODEL_PATH):
            try:
                import torch
                _ck_ = torch.load(JERSEY_MODEL_PATH, map_location="cpu")
                _saved_sig, _saved_set = _ck_.get("signature"), _ck_.get("settings")
                _saved_n = _ck_.get("n_samples") or _ck_.get("n_train")
            except Exception:
                _saved_sig = None
        # CONFIRMED CHANGE (requested: "is it really necessary to retrain every time I add pictures from the player checks?").
        # "auto" now retrains only when the training set has GROWN enough since the saved model: at least JERSEY_TRAIN_MIN_NEW
        # new crops or JERSEY_TRAIN_MIN_GROWTH (a share, 0.15 = 15%) more than it was trained on -- or when the epochs / coach
        # setting changed, or there is no model yet. JERSEY_TRAIN_MIN_NEW = 0 retrains on any change (the old behaviour).
        _want = JERSEY_TRAIN_NOW is True
        if not _want and JERSEY_TRAIN_NOW == "auto" and _saved_sig != _jr_signature():
            _now_n = len(_jr_samples(_jr_train_sources()))
            _min_new = int(globals().get("JERSEY_TRAIN_MIN_NEW", 150))
            _min_gr = float(globals().get("JERSEY_TRAIN_MIN_GROWTH", 0.15))
            _new_n = (_now_n - int(_saved_n)) if _saved_n else None
            if (not os.path.exists(JERSEY_MODEL_PATH) or _saved_n is None or _saved_set != _jr_settings_str()
                    or _min_new <= 0 or abs(_new_n) >= _min_new or abs(_new_n) >= _min_gr * max(int(_saved_n), 1)):
                _want = True
            else:
                print(f"  training set changed by {_new_n:+,} crop(s) since the saved model ({int(_saved_n):,} then, {_now_n:,} now) -- "
                      f"under the retrain bar of {_min_new} crops or {_min_gr:.0%}, so the saved recognizer is kept "
                      f"(JERSEY_TRAIN_NOW = True forces a retrain).", flush=True)
        if _want and _n_train < JERSEY_TRAIN_MIN_IMAGES:
            print(f"  not trained yet: {_n_train} training crop(s), needs {JERSEY_TRAIN_MIN_IMAGES} (check more players, "
                  f"run tracking with jersey numbers on, or add extra data)", flush=True)
        elif _want:
            globals().pop("_jr_model", None)
            jersey_train()
        elif os.path.exists(JERSEY_MODEL_PATH):
            print("  saved recognizer is up to date with the training set -- not retrained", flush=True)
        # remember what this run saw (after training: the model file is part of it)
        with open(_JR_LAST_INPUTS, "w") as _fh:
            json.dump({"fingerprint": _jr_inputs_fingerprint(), "saved": pd.Timestamp.now().isoformat(timespec="seconds")}, _fh)
    except StopIteration:
        pass
    except Exception as _e:
        print(f"Jersey-number recognizer skipped: {type(_e).__name__}: {_e}")
