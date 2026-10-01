import re
# 54_tracking_insights.py -- code for the notebook section "Tracking insights: every scouting table built from the player tracking -------------------"
# Runs inside the notebook via run_section("54_tracking_insights"); its settings are in that notebook cell.

# --- Tracking insights: every scouting table built from the player tracking -----------------------------------
# CONFIRMED CHANGE (requested: "build every single one of these out so I can see them with the real Oshkosh
# data, even though it's a small sample"). Everything is computed HERE; the brief and the app only render these
# tables. All of it comes from the player-tracking cell (names, positions, ball, screens) plus the coaches' tags
# and the play-by-play; every table carries its counts so a small sample reads as one.
#
# Distances: the tracking positions are in PICTURE units, not court units -- there's no court mapping yet (that
# needs the court lines found in every frame). Distances between two players in the SAME frame are turned into
# approximate feet using the players' own height in the picture (one player-height ~ TI_FEET_PER_PLAYER feet,
# depth squashed by the sideline camera angle ~ TI_DEPTH_SQUASH). Good to a few feet; every feet column is
# labeled "approx". Nothing here uses court locations (corners, the lane, the basket) -- those need the mapping.
#
# Tables (all exported for the app):
#   uww_trk_matchups            who guards whom (named defender -> named offensive player), possessions, PPP
#   uww_trk_help                per defender: how far he plays off his man with the ball on the other side
#   uww_trk_screens             one row per tracked screen: who screened, for whom, both defenders, coverage
#                               (coach tag when there is one, else the tracking estimate), points
#   uww_trk_screen_coverage     per defender: coverage mix on the screens he defended, by role
#   uww_trk_screen_pairs        who screens for whom + what the screener did after (roll / pop / slip)
#   uww_trk_sets                recurring offensive alignments found by grouping the set moment of every clip
#   uww_trk_set_clips           which clip belongs to which alignment
#   uww_trk_inbounds            BLOB / SLOB alignments (line, box, stack, spread) with their layouts
#   uww_trk_zone_press          zone layouts and press traps (count, when in the possession)
#   uww_trk_coverage_execution  UWW's defense: planned coverage (staff_inputs/uww_coverage_plan.csv) vs actual
#   uww_trk_spacing             UWW's offense spacing by lineup (approx feet), with PPP
#   uww_trk_roles               one row per player per role per clip -- the app's "search by player"
#   uww_trk_clips               one row per tracked clip -- the app's possession replay list

                            # upcoming opponent, or the most-tracked opponent when they have no tracked film yet)

_ti_tables = {}


def _ti_ft(a, b):
    """Approximate feet between two points (x, y, box height) in the same frame."""
    unit = (a[2] + b[2]) / 2 or 0.1
    return float(np.hypot(a[0] - b[0], (a[1] - b[1]) * TI_DEPTH_SQUASH) / unit * TI_FEET_PER_PLAYER)


def _ti_load_clips(pc, tracks):
    """clip_key -> {"row": clip row, "tr": {track: {"side", "name", "pts": {t: (x, y, h)}}}, "holder": {t: k},
    "screen": {...} or None, "n": frames}"""
    out = {}
    if tracks.empty or "track_clip_key" not in pc.columns:
        return out
    rows = pc[pc["track_clip_key"].notna()]
    by_clip = {k: g for k, g in tracks.groupby("clip_key")}
    for i, r in rows.iterrows():
        g = by_clip.get(r["track_clip_key"])
        if g is None:
            continue
        tr = {}
        for _, t in g.iterrows():
            pts = {int(p[0]): (float(p[1]), float(p[2]), float(p[3]) if len(p) > 3 else 0.1)
                   for p in _trk_json.loads(t["path"])}
            tr[int(t["track"])] = {"side": t["side"], "name": t["name"] if isinstance(t["name"], str) else None,
                                   "pts": pts}
        holder = {int(k): int(v) for k, v in _trk_json.loads(r["track_holders"]).items()} if isinstance(r.get("track_holders"), str) else {}
        screen = _trk_json.loads(r["track_screen_ids"]) if isinstance(r.get("track_screen_ids"), str) else None
        n = int(r["track_frames"]) if pd.notna(r.get("track_frames")) else (max((max(v["pts"]) for v in tr.values() if v["pts"]), default=0) + 1)
        # tracking frames per second (for rules written in half-second steps; the clip table also carries it)
        fps = float(globals().get("VISION_TRACK_FPS") or 2.0)
        out[r["track_clip_key"]] = {"row": r, "tr": tr, "holder": holder, "screen": screen, "n": n, "idx": i, "fps": fps}
    return out


def _ti_side(c, side):
    return [k for k, v in c["tr"].items() if v["side"] == side]


def _ti_label(c, k):
    """Name if tracking named him, else a stand-in that says he's unnamed."""
    if k is None or k not in c["tr"]:
        return None
    return c["tr"][k]["name"] or f"unnamed {c['tr'][k]['side'] or ''}".strip()


def _ti_man_by_frame(c, d):
    """frame -> the offensive track defender d is closest to (his man at that moment)."""
    out = {}
    off = _ti_side(c, "offense")
    for t, p in c["tr"][d]["pts"].items():
        best, bd = None, np.inf
        for o in off:
            q = c["tr"][o]["pts"].get(t)
            if q is not None:
                dd = _ti_ft(p, q)
                if dd < bd:
                    best, bd = o, dd
        if best is not None:
            out[t] = (best, bd)
    return out


def _ti_points(r):
    v = pd.to_numeric(r.get("points"), errors="coerce")
    return float(v) if pd.notna(v) else np.nan


def _ti_teams(r):
    return str(r.get("offense_team")), str(r.get("defense_team"))


def _ti_matchups_and_help(clips):
    mrows, hrows, roles = [], [], []
    for key, c in clips.items():
        r = c["row"]
        off_t, def_t = _ti_teams(r)
        for d in _ti_side(c, "defense"):
            mans = _ti_man_by_frame(c, d)
            if len(mans) < 3:
                continue
            counts = pd.Series([m for m, _ in mans.values()]).value_counts()
            man, share = counts.index[0], counts.iloc[0] / len(mans)
            dname, mname = _ti_label(c, d), _ti_label(c, man)
            if share >= 0.4:
                mrows.append({"clip_key": key, "game_date": r.get("game_date"), "defense_team": def_t,
                              "offense_team": off_t, "defender": dname, "guards": mname, "share_of_frames": round(share, 2),
                              "points": _ti_points(r)})
                roles.append((key, dname, "guarding", mname))
            # help: distance from his man, split by where the ball is
            for t, (m, dist) in mans.items():
                h = c["holder"].get(t)
                if h is None or h not in c["tr"] or t not in c["tr"][h]["pts"] or t not in c["tr"][m]["pts"]:
                    continue
                if m == h:
                    zone = "on ball"
                else:
                    zone = "weak side" if _ti_ft(c["tr"][m]["pts"][t], c["tr"][h]["pts"][t]) >= TI_WEAK_SIDE_FT else "ball side"
                hrows.append({"defense_team": def_t, "defender": dname, "where": zone, "feet_off_man": dist, "clip_key": key})
    matchups = pd.DataFrame(mrows)
    # the per-play rows too (with clip_key), before they're summarised -- the defensive roles credit only defenders
    # whose name on THAT play came from evidence, which the summary can no longer tell
    _ti_tables["uww_trk_matchups_raw"] = matchups.copy()
    _ti_tables["uww_trk_help_raw"] = pd.DataFrame(hrows)
    if not matchups.empty:
        g = matchups.groupby(["defense_team", "defender", "offense_team", "guards"], dropna=False)
        matchups = g.agg(possessions=("clip_key", "nunique"), ppp=("points", "mean")).reset_index()
        _tot = matchups.groupby(["defense_team", "defender"], dropna=False)["possessions"].transform("sum")
        matchups["share_of_his_possessions"] = (100 * matchups["possessions"] / _tot).round()
        matchups["ppp"] = matchups["ppp"].round(2)
        matchups = matchups.sort_values(["defense_team", "defender", "possessions"], ascending=[True, True, False])
    help_ = pd.DataFrame(hrows)
    if not help_.empty:
        piv = help_.pivot_table(index=["defense_team", "defender"], columns="where", values="feet_off_man",
                                aggfunc="mean").round(1)
        frames = help_.pivot_table(index=["defense_team", "defender"], columns="where", values="feet_off_man",
                                   aggfunc="size")
        clips_n = help_.groupby(["defense_team", "defender"])["clip_key"].nunique()
        help_ = piv.add_prefix("approx_ft_off_man_").join(frames.add_prefix("frames_")).reset_index()
        help_["clips"] = help_.apply(lambda x: int(clips_n.get((x["defense_team"], x["defender"]), 0)), axis=1)
        w = help_.get("approx_ft_off_man_weak side")
        help_["tendency"] = (w.map(lambda v: "helps / sags off" if pd.notna(v) and v >= 12 else
                                   ("stays attached" if pd.notna(v) and v <= 7 else ("in between" if pd.notna(v) else "")))
                             if w is not None else "")
    return matchups, help_, roles


def _ti_coverage_estimate(c, s):
    """Tracking's own read of how the screen was defended, from where the defenders went after it."""
    t = s["t"]
    sc, bh, bd, sd = s.get("screener"), s.get("screened"), s.get("screened_defender"), s.get("screener_defender")
    P = lambda k, tt: c["tr"][k]["pts"].get(tt) if k is not None and k in c["tr"] else None
    st = max(1, int(round(c.get("fps", 2.0) / 2.0)))       # half-second steps at any tracking rate
    after = [tt for tt in (t + st, t + 2 * st) if P(bh, tt) is not None]
    if not after:
        return "unclear"
    ta = after[-1]
    if s.get("type") == "Ball screen":
        if sd is not None and bd is not None and P(sd, ta) and P(bd, ta) and P(sc, ta):
            if _ti_ft(P(sd, ta), P(bh, ta)) < _ti_ft(P(bd, ta), P(bh, ta)) and _ti_ft(P(bd, ta), P(sc, ta)) < 6:
                return "switch"
        if sd is not None and P(sd, after[0]):
            d1 = _ti_ft(P(sd, after[0]), P(bh, after[0]))
            if d1 <= 5:
                return "blitz / trap" if bd is not None and P(bd, after[0]) and _ti_ft(P(bd, after[0]), P(bh, after[0])) <= 5 else "up (hedge / show)"
            if d1 >= 10:
                return "back (drop)"
        return "unclear"
    # off-ball screen: did the screened player's defender stay attached through it?
    if bd is not None and P(bd, ta):
        return "stayed attached (lock / trail)" if _ti_ft(P(bd, ta), P(bh, ta)) <= 4 else "separated (under / behind)"
    return "unclear"


_TI_ACTION_WORDS = [("roll", r"\broll", r"\bRolls?\b"), ("pop", r"\bpop", r"\bPops?\b|\bPick and Pops?\b"),
                    ("slip", r"\bslip", r"\bSlips?\b")]


def _ti_screener_action(r):
    tag = str(r.get("play_details") or "").lower()
    syn = str(r.get("synergy_string") or "")
    for name, tag_pat, syn_pat in _TI_ACTION_WORDS:
        if re.search(tag_pat, tag) or re.search(syn_pat, syn):
            return name
    return None


def _ti_screens(clips):
    rows, roles = [], []
    for key, c in clips.items():
        s = c["screen"]
        if not s:
            continue
        r = c["row"]
        off_t, def_t = _ti_teams(r)
        tag_cov = None
        cd = str(r.get("coverage_detail") or "")
        want = "Ball Screen" if s.get("type") == "Ball screen" else None
        for piece in cd.split(" | "):
            m = re.match(r"\s*([^:]+):\s*([^(]+)", piece)
            if m and ((want and m.group(1).strip() in ("Ball Screen", "DHO", "Get", "Double Drag")) or
                      (not want and m.group(1).strip() not in ("Ball Screen", "DHO", "Get", "Double Drag"))):
                tag_cov = m.group(2).strip()
                break
        est = _ti_coverage_estimate(c, s)
        row = {"clip_key": key, "game_date": r.get("game_date"), "offense_team": off_t, "defense_team": def_t,
               "screen_type": s.get("type"), "screener": _ti_label(c, s.get("screener")),
               "screened": _ti_label(c, s.get("screened")),
               "screened_defender": _ti_label(c, s.get("screened_defender")),
               "screener_defender": _ti_label(c, s.get("screener_defender")),
               "coverage": tag_cov or est, "coverage_source": "coach tag" if tag_cov else "tracking estimate",
               "coverage_tracking_estimate": est, "screener_action": _ti_screener_action(r),
               "points": _ti_points(r), "play_title": r.get("play_title"), "synergy_string": r.get("synergy_string"),
               "confidence": r.get("track_screen_conf")}
        rows.append(row)
        for role, col in (("screener", "screener"), ("screened for", "screened"),
                          ("defended the screened player", "screened_defender"),
                          ("defended the screener", "screener_defender")):
            if row[col]:
                partner = row["screened"] if role == "screener" else row["screener"] if role == "screened for" else \
                    row["screened"] if role == "defended the screened player" else row["screener"]
                roles.append((key, row[col], role, partner))
    screens = pd.DataFrame(rows)
    cov = pairs = pd.DataFrame()
    if not screens.empty:
        long = pd.concat([
            screens.assign(defender=screens["screened_defender"], role="guarding the player screened"),
            screens.assign(defender=screens["screener_defender"], role="guarding the screener")])
        long = long[long["defender"].notna()]
        if not long.empty:
            cov = (long.groupby(["defense_team", "defender", "role", "screen_type", "coverage", "coverage_source"],
                                dropna=False)
                   .agg(times=("clip_key", "count"), ppp=("points", "mean")).reset_index())
            _tot = cov.groupby(["defense_team", "defender", "role", "screen_type"], dropna=False)["times"].transform("sum")
            cov["share_pct"] = (100 * cov["times"] / _tot).round()
            cov["ppp"] = cov["ppp"].round(2)
            cov = cov.sort_values(["defense_team", "defender", "role", "times"], ascending=[True, True, True, False])
        pairs = (screens.groupby(["offense_team", "screener", "screened", "screen_type"], dropna=False)
                 .agg(times=("clip_key", "count"), ppp=("points", "mean"),
                      rolls=("screener_action", lambda a: int((a == "roll").sum())),
                      pops=("screener_action", lambda a: int((a == "pop").sum())),
                      slips=("screener_action", lambda a: int((a == "slip").sum()))).reset_index())
        pairs["ppp"] = pairs["ppp"].round(2)
        pairs = pairs.sort_values(["offense_team", "times"], ascending=[True, False])
    return screens, cov, pairs, roles


def _ti_set_frame(c, side="offense", lo=0.15, hi=0.6):
    """The stillest moment of the offense in the early-middle of the clip = when the set is in place."""
    ks = _ti_side(c, side)
    best, bt = np.inf, None
    for t in range(max(1, int(lo * c["n"])), max(2, int(hi * c["n"]))):
        moves, present = [], 0
        for k in ks:
            p, q = c["tr"][k]["pts"].get(t), c["tr"][k]["pts"].get(t - max(1, int(round(c.get("fps", 2.0) / 2.0))))
            if p is not None:
                present += 1
            if p is not None and q is not None:
                moves.append(_ti_ft(p, q))
        if present >= TI_MIN_SET_PLAYERS and moves and np.mean(moves) < best:
            best, bt = float(np.mean(moves)), t
    return bt


def _ti_layout(c, t, side="offense"):
    """[(x_ft, depth_ft, name)] relative to the group's center, at frame t."""
    pts = [(c["tr"][k]["pts"][t], _ti_label(c, k)) for k in _ti_side(c, side) if t in c["tr"][k]["pts"]]
    if len(pts) < TI_MIN_SET_PLAYERS:
        return None
    unit = float(np.median([p[2] for p, _ in pts])) or 0.1
    cx, cy = np.mean([p[0] for p, _ in pts]), np.mean([p[1] for p, _ in pts])
    return [(round((p[0] - cx) / unit * TI_FEET_PER_PLAYER, 1), round((p[1] - cy) * TI_DEPTH_SQUASH / unit * TI_FEET_PER_PLAYER, 1), n)
            for p, n in pts]


def _ti_descriptor(layout):
    """Order-free description of an alignment: where the players stand on a coarse grid around their center."""
    H = np.zeros((3, 5))
    for x, y, _ in layout:
        xi = int(np.clip((x + 30) / 12, 0, 4))
        yi = int(np.clip((y + 12) / 8, 0, 2))
        H[yi, xi] += 1
    xs = sorted(x for x, _, _ in layout)
    spread = [np.std([x for x, _, _ in layout]) / 10, np.std([y for _, y, _ in layout]) / 10]
    return np.concatenate([H.ravel() / max(len(layout), 1), spread, [len(layout) / 5]])


def _ti_sets(clips):
    recs = []
    for key, c in clips.items():
        r = c["row"]
        sit = str(r.get("play_situation") or "")
        if sit.startswith(("BLOB", "SLOB")) or sit == "Transition":
            continue
        t = _ti_set_frame(c)
        if t is None:
            continue
        lay = _ti_layout(c, t)
        if lay:
            recs.append({"clip_key": key, "offense_team": _ti_teams(r)[0], "layout": lay, "desc": _ti_descriptor(lay),
                         "play_call": r.get("play_call"), "situation": sit, "points": _ti_points(r),
                         "title": r.get("play_title")})
    set_rows, clip_rows = [], []
    from sklearn.cluster import KMeans
    for team in sorted({x["offense_team"] for x in recs}):
        R = [x for x in recs if x["offense_team"] == team]
        if len(R) < 6:
            continue
        X = np.stack([x["desc"] for x in R])
        k = int(min(8, max(2, len(R) // 6)))
        km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
        for cl in range(k):
            members = [R[j] for j in range(len(R)) if km.labels_[j] == cl]
            if len(members) < 3:
                continue
            center = km.cluster_centers_[cl]
            rep = min(members, key=lambda x: float(np.linalg.norm(x["desc"] - center)))
            calls = pd.Series([m["play_call"] for m in members if isinstance(m["play_call"], str)]).value_counts()
            sits = pd.Series([m["situation"] for m in members]).value_counts()
            pts = [m["points"] for m in members if pd.notna(m["points"])]
            set_rows.append({"offense_team": team, "set_id": f"{team[:12]} set {cl + 1}", "clips": len(members),
                             "most_common_call": calls.index[0] if len(calls) else None,
                             "call_share_pct": round(100 * calls.iloc[0] / len(members)) if len(calls) else None,
                             "situations": ", ".join(f"{s} {n}" for s, n in sits.items()),
                             "ppp": round(float(np.mean(pts)), 2) if pts else None,
                             "layout": _trk_json.dumps(rep["layout"]), "example_clip": rep["clip_key"],
                             "example_titles": " | ".join(str(m["title"]) for m in members[:3])})
            for m in members:
                clip_rows.append({"clip_key": m["clip_key"], "offense_team": team, "set_id": f"{team[:12]} set {cl + 1}"})
    sets = pd.DataFrame(set_rows)
    if not sets.empty:
        sets = sets.sort_values(["offense_team", "clips"], ascending=[True, False])
    return sets, pd.DataFrame(clip_rows)


def _ti_result_type(result):
    """Synergy's result -> made 2 / made 3 / missed 2 / missed 3 / turnover / fouled / other (replay filter)."""
    t = str(result or "")
    m = re.search(r"\b(Make|Miss)\w*\s+([23])\s*Pts", t, re.I)
    if m:
        return f"{'made' if m.group(1).lower() == 'make' else 'missed'} {m.group(2)}"
    if re.search(r"turnover", t, re.I):
        return "turnover"
    if re.search(r"foul|free throw", t, re.I):
        return "fouled"
    return "other" if t else None


def _ti_shot_clock_bucket(used):
    """Seconds used on the shot clock -> early (0-9) / organized (10-19) / late (20+) (replay filter)."""
    v = pd.to_numeric(used, errors="coerce")
    if pd.isna(v):
        return None
    return "early (0-9 s)" if v < 10 else "organized (10-19 s)" if v < 20 else "late (20+ s)"


def _ti_shape(layout):
    P = np.array([[x, y] for x, y, _ in layout])
    if len(P) < 3:
        return "unclear"
    d = np.sqrt(((P[:, None] - P[None]) ** 2).sum(-1))
    if np.median(d[np.triu_indices(len(P), 1)]) < 6:
        return "stack (bunched)"
    ev = np.linalg.eigvalsh(np.cov(P.T))
    if ev[-1] > 0 and ev[0] / ev[-1] < 0.08:
        return "line"
    if len(P) >= 4 and ev[0] / ev[-1] > 0.3 and np.median(d[np.triu_indices(len(P), 1)]) < 16:
        return "box"
    return "spread"


def _ti_inbounds(clips):
    rows = []
    for key, c in clips.items():
        r = c["row"]
        sit = str(r.get("play_situation") or "")
        if not sit.startswith(("BLOB", "SLOB")):
            psit = r.get("pred_situation")
            if not (isinstance(psit, str) and psit in ("BLOB", "SLOB") and (r.get("pred_situation_conf") or 0) >= 0.6):
                continue
            sit = psit + " (predicted)"
        # first moment with enough of the offense in the picture
        t = next((tt for tt in range(0, max(1, c["n"] // 2)) if _ti_layout(c, tt)), None)
        if t is None:
            continue
        lay = _ti_layout(c, t)
        rows.append({"clip_key": key, "offense_team": _ti_teams(r)[0], "situation": sit, "alignment": _ti_shape(lay),
                     "layout": _trk_json.dumps(lay), "points": _ti_points(r), "play_title": r.get("play_title")})
    return pd.DataFrame(rows)


def _ti_zone_press(clips):
    rows = []
    for key, c in clips.items():
        r = c["row"]
        dt = str(r.get("defense_type") or "")
        is_zone = "Zone" in dt or (str(r.get("pred_defense") or "").find("Zone") >= 0 and (r.get("pred_defense_conf") or 0) >= 0.6)
        press = str(r.get("defense_press")).lower() == "true" or (
            isinstance(r.get("pred_press"), str) and r.get("pred_press") not in ("None", "") and (r.get("pred_press_conf") or 0) >= 0.6)
        if not (is_zone or press):
            continue
        rec = {"clip_key": key, "defense_team": _ti_teams(r)[1], "offense_team": _ti_teams(r)[0],
               "zone": bool(is_zone), "press": bool(press), "press_type": r.get("defense_press_formation") or r.get("pred_press"),
               "points": _ti_points(r)}
        if is_zone:
            t = _ti_set_frame(c, side="defense")
            lay = _ti_layout(c, t, side="defense") if t is not None else None
            rec["zone_layout"] = _trk_json.dumps(lay) if lay else None
            if lay:
                xs, ys = [x for x, _, _ in lay], [y for _, y, _ in lay]
                rec["zone_width_ft_approx"], rec["zone_depth_ft_approx"] = round(max(xs) - min(xs), 1), round(max(ys) - min(ys), 1)
        if press:
            traps = []
            for t, h in c["holder"].items():
                if h not in c["tr"] or c["tr"][h]["side"] != "offense" or t not in c["tr"][h]["pts"]:
                    continue
                close = [d for d in _ti_side(c, "defense") if t in c["tr"][d]["pts"]
                         and _ti_ft(c["tr"][d]["pts"][t], c["tr"][h]["pts"][t]) <= TI_TRAP_FT]
                if len(close) >= 2:
                    traps.append(t)
            fps = VISION_TRACK_FPS if "VISION_TRACK_FPS" in globals() and VISION_TRACK_FPS else 2
            rec["trap_frames"] = len(traps)
            rec["first_trap_seconds_into_clip"] = round(min(traps) / fps, 1) if traps else None
        rows.append(rec)
    return pd.DataFrame(rows)


def _ti_spacing(clips):
    rows = []
    for key, c in clips.items():
        r = c["row"]
        if str(r.get("side")) != "UWW" or str(r.get("possession_side")) != "Offense":
            continue
        nn, width, crowded, frames = [], [], 0, 0
        scr_t = c["screen"]["t"] if c["screen"] else None
        scr_pair = {c["screen"].get("screener"), c["screen"].get("screened")} if c["screen"] else set()
        for t in range(c["n"]):
            pts = [(k, c["tr"][k]["pts"][t]) for k in _ti_side(c, "offense") if t in c["tr"][k]["pts"]]
            if len(pts) < 4:
                continue
            frames += 1
            ds = []
            crowd = False
            for a in range(len(pts)):
                others = [_ti_ft(pts[a][1], pts[b][1]) for b in range(len(pts)) if b != a]
                ds.append(min(others))
                for b in range(a + 1, len(pts)):
                    if _ti_ft(pts[a][1], pts[b][1]) < TI_CROWD_FT and not (
                            scr_t is not None and abs(t - scr_t) <= 1 and {pts[a][0], pts[b][0]} == scr_pair):
                        crowd = True
            nn.append(np.mean(ds))
            unit = float(np.median([p[2] for _, p in pts])) or 0.1
            xs = [p[0] for _, p in pts]
            width.append((max(xs) - min(xs)) / unit * TI_FEET_PER_PLAYER)
            crowded += int(crowd)
        if frames:
            rows.append({"clip_key": key, "lineup": r.get("offense_lineup"), "frames": frames,
                         "spacing_ft_approx": float(np.mean(nn)), "width_ft_approx": float(np.mean(width)),
                         "crowded_share": crowded / frames, "points": _ti_points(r)})
    sp = pd.DataFrame(rows)
    if sp.empty:
        return sp, sp
    by = (sp.groupby("lineup", dropna=False)
          .agg(possessions=("clip_key", "count"), spacing_ft_approx=("spacing_ft_approx", "mean"),
               width_ft_approx=("width_ft_approx", "mean"), crowded_pct=("crowded_share", "mean"),
               ppp=("points", "mean")).reset_index())
    by["crowded_pct"] = (100 * by["crowded_pct"]).round()
    for c in ("spacing_ft_approx", "width_ft_approx"):
        by[c] = by[c].round(1)
    by["ppp"] = by["ppp"].round(2)
    return by.sort_values("possessions", ascending=False), sp


def _ti_coverage_execution(screens):
    """UWW's defense: what we planned (staff_inputs/uww_coverage_plan.csv) vs what we did."""
    plan_path = os.path.join(INPUT_DIR, "staff_inputs", "uww_coverage_plan.csv")
    tmpl_dir = os.path.join(globals().get("OUTPUT_DIR", INPUT_DIR), "staff_input_templates")
    try:
        os.makedirs(tmpl_dir, exist_ok=True)
        tmpl = os.path.join(tmpl_dir, "uww_coverage_plan.csv")
        if not os.path.exists(tmpl):
            pd.DataFrame([{"opponent": "UW-Oshkosh", "screen_type": "Ball screen", "defender": "",
                           "planned_coverage": "Drop"}]).to_csv(tmpl, index=False)
    except Exception:
        pass
    if screens.empty:
        return pd.DataFrame()
    ours = screens[screens["defense_team"].map(lambda t: bool(_pl_team_label(str(t), {_PL_UWW})))].copy()
    if ours.empty:
        return pd.DataFrame()
    plan = pd.read_csv(plan_path) if os.path.exists(plan_path) else pd.DataFrame(
        columns=["opponent", "screen_type", "defender", "planned_coverage"])
    fam = lambda s: re.sub(r"[^a-z]", "", str(s).lower())

    def planned(row):
        for _, p in plan.iterrows():
            if p["opponent"] and _pl_team_label(str(row["offense_team"]), {str(p["opponent"])}) is None:
                continue
            if isinstance(p.get("screen_type"), str) and p["screen_type"] not in ("", "Any") and p["screen_type"] != row["screen_type"]:
                continue
            if isinstance(p.get("defender"), str) and p["defender"].strip() and p["defender"].strip() not in (
                    row["screener_defender"], row["screened_defender"]):
                continue
            return p["planned_coverage"]
        return None
    ours["planned_coverage"] = ours.apply(planned, axis=1)
    ours["followed_plan"] = ours.apply(
        lambda x: None if not isinstance(x["planned_coverage"], str) else
        (fam(x["planned_coverage"]) in fam(x["coverage"]) or fam(x["coverage"]) in fam(x["planned_coverage"])), axis=1)
    long = pd.concat([ours.assign(defender=ours["screener_defender"], role="guarding the screener"),
                      ours.assign(defender=ours["screened_defender"], role="guarding the player screened")])
    long = long[long["defender"].notna()]
    if long.empty:
        return pd.DataFrame()
    out = (long.groupby(["offense_team", "defender", "role", "screen_type", "coverage", "coverage_source"], dropna=False)
           .agg(times=("clip_key", "count"), planned=("planned_coverage", lambda s: s.dropna().iloc[0] if s.notna().any() else None),
                followed_pct=("followed_plan", lambda s: round(100 * s.dropna().astype(bool).mean()) if s.notna().any() else None),
                ppp=("points", "mean")).reset_index())
    out["ppp"] = out["ppp"].round(2)
    out["plan_file"] = "found" if os.path.exists(plan_path) else "none yet -- staff_inputs/uww_coverage_plan.csv"
    return out.sort_values(["offense_team", "times"], ascending=[True, False])


# ---- Run --------------------------------------------------------------------------------------------------
for _n in ("uww_trk_matchups", "uww_trk_help", "uww_trk_screens", "uww_trk_screen_coverage", "uww_trk_screen_pairs",
           "uww_trk_sets", "uww_trk_set_clips", "uww_trk_inbounds", "uww_trk_zone_press",
           "uww_trk_coverage_execution", "uww_trk_spacing", "uww_trk_roles", "uww_trk_clips"):
    _ti_tables[_n] = pd.DataFrame()
if isinstance(globals().get("player_tracks"), pd.DataFrame) and not player_tracks.empty:
    try:
        _ti_clips = _ti_load_clips(play_calls, player_tracks)
        _m, _h, _roles1 = _ti_matchups_and_help(_ti_clips)
        _scr, _cov, _pairs, _roles2 = _ti_screens(_ti_clips)
        _sets, _set_clips = _ti_sets(_ti_clips)
        _sp_by, _sp_clip = _ti_spacing(_ti_clips)
        _ti_tables.update({
            "uww_trk_matchups": _m, "uww_trk_help": _h, "uww_trk_screens": _scr, "uww_trk_screen_coverage": _cov,
            "uww_trk_screen_pairs": _pairs, "uww_trk_sets": _sets, "uww_trk_set_clips": _set_clips,
            "uww_trk_inbounds": _ti_inbounds(_ti_clips), "uww_trk_zone_press": _ti_zone_press(_ti_clips),
            "uww_trk_coverage_execution": _ti_coverage_execution(_scr), "uww_trk_spacing": _sp_by})
        _role_rows = []
        for _key, _who, _role, _partner in _roles1 + _roles2:
            _c = _ti_clips[_key]["row"]
            _role_rows.append({"clip_key": _key, "game_date": _c.get("game_date"), "offense_team": _c.get("offense_team"),
                               "defense_team": _c.get("defense_team"), "player": _who, "role": _role, "with": _partner,
                               "result": _c.get("result"), "points": _c.get("points"), "play_title": _c.get("play_title"),
                               "synergy_string": _c.get("synergy_string")})
        for _key, _c in _ti_clips.items():
            _r = _c["row"]
            _h0 = _r.get("player")
            if isinstance(_h0, str):
                _role_rows.append({"clip_key": _key, "game_date": _r.get("game_date"), "offense_team": _r.get("offense_team"),
                                   "defense_team": _r.get("defense_team"), "player": _h0, "role": "finished the play (Synergy)",
                                   "with": None, "result": _r.get("result"), "points": _r.get("points"),
                                   "play_title": _r.get("play_title"), "synergy_string": _r.get("synergy_string")})
        _ti_tables["uww_trk_roles"] = pd.DataFrame(_role_rows)
        _ti_tables["uww_trk_clips"] = pd.DataFrame([{
            "clip_key": _k, "game_date": _c["row"].get("game_date"), "clip_number": _c["row"].get("clip_number"),
            "offense_team": _c["row"].get("offense_team"), "defense_team": _c["row"].get("defense_team"),
            "play_title": _c["row"].get("play_title"), "suggested_title": _c["row"].get("suggested_title"),
            "synergy_string": _c["row"].get("synergy_string"), "result": _c["row"].get("result"),
            "points": _c["row"].get("points"), "frames": _c["n"],
            "fps": VISION_TRACK_FPS if "VISION_TRACK_FPS" in globals() and VISION_TRACK_FPS else 2,
            "holders": _c["row"].get("track_holders"), "screen": _c["row"].get("track_screen_ids"),
            "screen_type": _c["row"].get("track_screen_type"), "set_id": None,
            # CONFIRMED CHANGE (requested: filters on the Possession Replay for each game and different types of data).
            # Everything the replay can be filtered by, worked out here so the app only filters.
            "game_code": _c["row"].get("game_code"), "period": _c["row"].get("period"),
            "time_remaining_seconds": _c["row"].get("time_remaining_seconds"), "player": _c["row"].get("player"),
            "situation": _c["row"].get("play_situation"), "formation": _c["row"].get("play_formation"),
            "play_call": _c["row"].get("play_set"), "primary_action": _c["row"].get("primary_action"),
            "defense": _c["row"].get("defense_formation"),
            "press": bool(_c["row"].get("defense_press")) if pd.notna(_c["row"].get("defense_press")) else None,
            "coverage": _c["row"].get("coverage_detail"),
            "result_type": _ti_result_type(_c["row"].get("result")),
            "shot_clock": _ti_shot_clock_bucket(_c["row"].get("shot_clock_used"))} for _k, _c in _ti_clips.items()])
        if not _set_clips.empty:
            _ti_tables["uww_trk_clips"] = _ti_tables["uww_trk_clips"].drop(columns="set_id").merge(
                _set_clips[["clip_key", "set_id"]], on="clip_key", how="left")
        print("Tracking insights: " + ", ".join(f"{k.replace('uww_trk_', '')} {len(v)}" for k, v in _ti_tables.items()))
    except Exception as _e:
        print("  " + "!" * 100)
        print(f"  TRACKING INSIGHTS NOT BUILT: {type(_e).__name__}: {_e}")
        print("  " + "!" * 100)
else:
    print("Tracking insights: no player tracks yet (run frame capture with VISION_TRACK_FPS > 0, then player tracking).")
