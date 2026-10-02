# 55_court_insights.py -- code for the notebook section "Court insights: everything that needs real court positions -------------------------------"
# Runs inside the notebook via run_section("55_court_insights"); its settings are in that notebook cell.

# --- Court insights: everything that needs real court positions ------------------------------------------------
# CONFIRMED CHANGE (requested: add the court-mapped information to the brief and the app). Built from the
# court-mapped tracks (court mapping cell) + the tracking-insight tables. Half-court coordinates throughout:
# hx = feet from the attacked baseline, hy = feet from the offense's LEFT sideline (basket at hx 5.25, hy 25).
# Tables (all exported for the app; the brief and app only render them):
#   uww_court_shots        every tracked shot: shooter, spot on the floor, zone (rim / paint / mid-range /
#                          corner 3 / above-break 3), result. Also the mapping's own check: does the zone agree
#                          with Synergy's 2 or 3?
#   uww_court_shot_zones   attempts / makes / FG% / points per shot by team, player and zone
#   uww_court_heat         where each player spends his time on offense and defense (5-ft squares)
#   uww_court_screens      where every tracked screen happened (zone + spot) with its coverage and points
#   uww_court_screen_zones screens by team, zone and coverage
#   uww_court_help         per defender: true feet off his man, % of weak-side time spent in the paint
#   uww_court_zone_press   zone alignments read from the court (e.g. 2-3, 1-3-1) and where traps happen
#   uww_court_spacing      UWW offense by lineup: both corners filled %, paint crowded %, true spacing
#   uww_court_diagrams     one FastDraw-style diagram per tracked possession (numbered players, their paths,
#                          dribbles, passes, screens) -- the app draws them; the future FastDraw export uses them
#   uww_court_report       mapping quality per game (from the court mapping cell) + the 2-vs-3 shot check

_CZ_BASKET = (5.25, 25.0)
_cz_tables = {n: pd.DataFrame() for n in (
    "uww_court_shots", "uww_court_shot_zones", "uww_court_heat", "uww_court_screens", "uww_court_screen_zones",
    "uww_court_help", "uww_court_zone_press", "uww_court_spacing", "uww_court_diagrams", "uww_court_report")}


def _cz_in_paint(hx, hy):
    return hx <= 19 and 19 <= hy <= 31


def _cz_shot_zone(hx, hy):
    d = float(np.hypot(hx - _CZ_BASKET[0], hy - _CZ_BASKET[1]))
    if d <= 6:
        return "Rim"
    if abs(hy - 25) >= _CM_CORNER and hx <= 9.83:
        return "Corner 3"
    if hx > 9.83 and d >= _CM_ARC:
        return "Above-break 3"
    return "Paint" if _cz_in_paint(hx, hy) else "Mid-range"


def _cz_floor_zone(hx, hy):
    """A coach's name for a spot (offense's left/right)."""
    if hx > 47:
        return "Backcourt"
    side = "Left" if hy < 25 else "Right"
    if _cz_in_paint(hx, hy):
        return "Paint / post"
    if abs(hy - 25) >= 18 and hx <= 12:
        return f"{side} corner"
    if hx <= 12:
        return f"{side} baseline"
    if hx <= 22 and abs(hy - 25) <= 11:
        return f"{side} elbow"
    if abs(hy - 25) <= 8:
        return "Top of key"
    return f"{side} wing" if hx <= 38 else "Mid-court"


def _cz_clips():
    """_ti_load_clips + each track's court spot per frame."""
    clips = _ti_load_clips(play_calls, player_tracks)
    court = {}
    for _, t in player_tracks.iterrows():
        if isinstance(t.get("court_path"), str):
            court[(t["clip_key"], int(t["track"]))] = {int(p[0]): (float(p[1]), float(p[2])) for p in _trk_json.loads(t["court_path"])}
    for key, c in clips.items():
        for k, v in c["tr"].items():
            v["court"] = court.get((key, k), {})
        c["mapped"] = any(v["court"] for v in c["tr"].values())
    return {k: c for k, c in clips.items() if c["mapped"]}


def _cz_near(pts, t, span=2):
    """Court spot at frame t, or the nearest frame within `span`."""
    for d in range(span + 1):
        for tt in (t - d, t + d):
            if tt in pts:
                return pts[tt]
    return None


def _cz_shots(clips):
    """Every tracked shot: where the shooter stood when the play finished -- checked against the play-by-play.
    CONFIRMED BUG (fixed; coach: "Where they shoot (tracked shots)" looked wrong -- dots near half court). The shooter
    was "whoever last had the ball" at the LAST moment he had it, but Synergy clips run on after the shot (the
    rebound, the other team bringing it up), so that was often after the shot, or someone else. Now: the shooter
    Synergy names, at the play's finish frame (ball-holder only as a fallback, and never after the finish). And every
    spot is checked against the shot itself: a 3 must be outside the arc, a 2 inside it, a shot "at/to the basket"
    near the rim, nothing past 30 ft -- a spot that disagrees is kept in the table (location_ok = False, with why)
    but never plotted or counted in the zones."""
    rows = []
    for key, c in clips.items():
        r = c["row"]
        m = re.search(r"\b(Make|Miss)\w*\s+([23])\s*Pts", str(r.get("result") or ""), re.I)
        if not m:
            continue
        off = [k for k in _ti_side(c, "offense")]
        name = r.get("player") if isinstance(r.get("player"), str) else None
        t_fin = pd.to_numeric(r.get("track_finish_frame"), errors="coerce")
        shooter = t_shot = None
        how = None
        if name:
            shooter = next((k for k in off if c["tr"][k]["name"] == name), None)
            if shooter is not None and c["tr"][shooter]["court"]:
                ts = sorted(c["tr"][shooter]["court"])
                t_shot = min(ts, key=lambda t: abs(t - t_fin)) if pd.notna(t_fin) else None
                how = "named shooter at the finish"
        if t_shot is None:
            hold = [(t, k) for t, k in sorted(c["holder"].items()) if k in off and (pd.isna(t_fin) or t <= t_fin)]
            if hold:
                t_shot, shooter = hold[-1]
                how = "last ball holder before the finish"
        if shooter is None or t_shot is None:
            continue
        spot = _cz_near(c["tr"][shooter]["court"], t_shot)
        if spot is None:
            continue
        hx, hy = spot
        zone = _cz_shot_zone(hx, hy)
        d = float(np.hypot(hx - _CZ_BASKET[0], hy - _CZ_BASKET[1]))
        val = int(m.group(2))
        at_rim = bool(re.search(r"\b(At|To) Basket\b|Basket >|> Basket|Put Back|Dunk|Layup", str(r.get("synergy_string") or r.get("result") or ""), re.I))
        why_bad = (f"{d:.0f} ft from the basket -- past 30 ft" if d > 30 else
                   f"a 3 plotted inside the arc ({d:.0f} ft)" if val == 3 and d < _CM_ARC - 2.5 else
                   f"a 2 plotted outside the arc ({d:.0f} ft)" if val == 2 and d > _CM_ARC + 1.5 else
                   f"a shot at the basket plotted {d:.0f} ft out" if at_rim and val == 2 and d > 9 else None)
        rows.append({"clip_key": key, "game_date": r.get("game_date"), "offense_team": r.get("offense_team"),
                     "defense_team": r.get("defense_team"), "shooter": name or _ti_label(c, shooter),
                     "hx": round(hx, 1), "hy": round(hy, 1), "feet_from_basket": round(d, 1), "zone": zone,
                     "floor_zone": _cz_floor_zone(hx, hy), "made": m.group(1).lower() == "make", "value": val,
                     "points": _ti_points(r), "located_by": how, "location_ok": why_bad is None,
                     "location_problem": why_bad,
                     "zone_agrees_with_result": (zone.endswith("3")) == (val == 3)})
    shots = pd.DataFrame(rows)
    zones = pd.DataFrame()
    if not shots.empty:
        good = shots[shots["location_ok"]]
        print(f"  [court] tracked shots: {len(good)} placed, {len(shots) - len(good)} set aside (spot didn't match "
              f"the shot in the play-by-play)", flush=True)
        if not good.empty:
            both = pd.concat([good, good.assign(shooter="TEAM")])
            zones = (both.groupby(["offense_team", "shooter", "zone"])
                     .agg(attempts=("clip_key", "count"), makes=("made", "sum"), points=("points", "sum")).reset_index())
            zones["fg_pct"] = (100 * zones["makes"] / zones["attempts"]).round()
            zones["pts_per_shot"] = (zones["points"] / zones["attempts"]).round(2)
    return shots, zones


def _cz_heat(clips):
    cells = {}
    for key, c in clips.items():
        r = c["row"]
        for k, v in c["tr"].items():
            if v["side"] not in ("offense", "defense"):
                continue
            team = r.get("offense_team") if v["side"] == "offense" else r.get("defense_team")
            for hx, hy in v["court"].values():
                if not (0 <= hx <= 47 and 0 <= hy <= 50):
                    continue
                gx, gy = int(min(hy // 5, 9)), int(min(hx // 5, 9))
                for who in ([v["name"]] if v["name"] else []) + ["TEAM"]:
                    kk = (team, who, v["side"], gx, gy)
                    cells[kk] = cells.get(kk, 0) + 1
    return pd.DataFrame([{"team": a, "player": b, "side": s, "cell_hy": gx * 5, "cell_hx": gy * 5, "frames": n}
                         for (a, b, s, gx, gy), n in cells.items()])


def _cz_screens(clips):
    scr = _ti_tables.get("uww_trk_screens", pd.DataFrame())
    cov = scr.set_index("clip_key") if not scr.empty else pd.DataFrame()
    rows = []
    for key, c in clips.items():
        s = c["screen"]
        if not s or s.get("screener") is None or s["screener"] not in c["tr"]:
            continue
        spot = _cz_near(c["tr"][s["screener"]]["court"], s["t"])
        if spot is None:
            continue
        r = c["row"]
        x = cov.loc[key] if key in cov.index else {}
        rows.append({"clip_key": key, "offense_team": r.get("offense_team"), "defense_team": r.get("defense_team"),
                     "screen_type": s.get("type"), "hx": round(spot[0], 1), "hy": round(spot[1], 1),
                     "zone": _cz_floor_zone(*spot), "screener": x.get("screener") if len(x) else None,
                     "coverage": x.get("coverage") if len(x) else None,
                     "coverage_source": x.get("coverage_source") if len(x) else None, "points": _ti_points(r)})
    s = pd.DataFrame(rows)
    z = pd.DataFrame()
    if not s.empty:
        z = (s.groupby(["offense_team", "defense_team", "screen_type", "zone", "coverage"], dropna=False)
             .agg(screens=("clip_key", "count"), ppp=("points", "mean")).reset_index())
        z["ppp"] = z["ppp"].round(2)
    return s, z


def _cz_help(clips):
    rows = []
    for key, c in clips.items():
        r = c["row"]
        for d in _ti_side(c, "defense"):
            dc = c["tr"][d]["court"]
            for t, (hx, hy) in dc.items():
                h = c["holder"].get(t)
                best, bd = None, np.inf
                for o in _ti_side(c, "offense"):
                    q = c["tr"][o]["court"].get(t)
                    if q is not None:
                        dd = float(np.hypot(q[0] - hx, q[1] - hy))
                        if dd < bd:
                            best, bd = o, dd
                if best is None or h is None or h not in c["tr"] or t not in c["tr"][h]["court"]:
                    continue
                hq, mq = c["tr"][h]["court"][t], c["tr"][best]["court"][t]
                weak = best != h and float(np.hypot(mq[0] - hq[0], mq[1] - hq[1])) >= TI_WEAK_SIDE_FT
                rows.append({"defense_team": r.get("defense_team"), "defender": _ti_label(c, d), "clip_key": key,
                             "weak": weak, "on_ball": best == h, "ft_off_man": bd, "in_paint": _cz_in_paint(hx, hy)})
    h = pd.DataFrame(rows)
    if h.empty:
        return h
    g = h.groupby(["defense_team", "defender"])
    out = g.agg(clips=("clip_key", "nunique"), frames=("clip_key", "count")).reset_index()
    ws = h[h["weak"]].groupby(["defense_team", "defender"]).agg(
        weak_side_ft_off_man=("ft_off_man", "mean"), weak_side_in_paint_pct=("in_paint", "mean"), weak_frames=("in_paint", "size"))
    ob = h[h["on_ball"]].groupby(["defense_team", "defender"]).agg(on_ball_ft=("ft_off_man", "mean"))
    out = out.join(ws, on=["defense_team", "defender"]).join(ob, on=["defense_team", "defender"])
    out["weak_side_in_paint_pct"] = (100 * out["weak_side_in_paint_pct"]).round()
    for col in ("weak_side_ft_off_man", "on_ball_ft"):
        out[col] = out[col].round(1)
    return out.sort_values(["defense_team", "weak_side_in_paint_pct"], ascending=[True, False])


def _cz_zone_press(clips):
    zp = _ti_tables.get("uww_trk_zone_press", pd.DataFrame())
    rows = []
    for _, z in (zp.iterrows() if not zp.empty else []):
        c = clips.get(z["clip_key"])
        if c is None:
            continue
        rec = {"clip_key": z["clip_key"], "defense_team": z["defense_team"], "offense_team": z["offense_team"],
               "zone": bool(z["zone"]), "press": bool(z["press"]), "points": z["points"]}
        if z["zone"]:
            # the defense's alignment at its stillest moment, read in court bands: top (hx > 20), middle, back (hx < 12)
            t = _ti_set_frame(c, side="defense")
            spots = [_cz_near(c["tr"][d]["court"], t) for d in _ti_side(c, "defense")] if t is not None else []
            spots = [s for s in spots if s is not None and s[0] <= 47]
            if len(spots) >= 4:
                top = sum(1 for s in spots if s[0] > 20)
                mid = sum(1 for s in spots if 12 <= s[0] <= 20)
                back = sum(1 for s in spots if s[0] < 12)
                rec["alignment"] = "-".join(str(n) for n in (top, mid, back) if n) if mid else f"{top}-{back}"
                rec["court_layout"] = _trk_json.dumps([(round(s[1], 1), round(s[0], 1)) for s in spots])
        if z["press"]:
            spots = []
            for t, h in c["holder"].items():
                if h not in c["tr"] or c["tr"][h]["side"] != "offense" or t not in c["tr"][h]["court"]:
                    continue
                hq = c["tr"][h]["court"][t]
                close = [d for d in _ti_side(c, "defense") if t in c["tr"][d]["court"]
                         and np.hypot(*(np.array(c["tr"][d]["court"][t]) - hq)) <= TI_TRAP_FT]
                if len(close) >= 2:
                    spots.append(hq)
            if spots:
                hx, hy = spots[0]
                rec["trap_spot"] = ("backcourt" if hx > 47 else "frontcourt") + ", " + (
                    "left sideline" if hy < 12 else "right sideline" if hy > 38 else "middle")
                rec["trap_hx"], rec["trap_hy"] = round(hx, 1), round(hy, 1)
        rows.append(rec)
    return pd.DataFrame(rows)


def _cz_spacing(clips):
    rows = []
    for key, c in clips.items():
        r = c["row"]
        if str(r.get("side")) != "UWW" or str(r.get("possession_side")) != "Offense":
            continue
        frames = corners = crowd = 0
        nn = []
        for t in range(c["n"]):
            pts = [(k, c["tr"][k]["court"][t]) for k in _ti_side(c, "offense") if t in c["tr"][k]["court"]]
            pts = [(k, p) for k, p in pts if p[0] <= 47]
            if len(pts) < 4:
                continue
            frames += 1
            zones = [_cz_floor_zone(*p) for _, p in pts]
            corners += int("Left corner" in zones and "Right corner" in zones)
            h = c["holder"].get(t)
            hp = c["tr"][h]["court"].get(t) if h in c["tr"] else None
            in_paint = sum(1 for _, p in pts if _cz_in_paint(*p))
            crowd += int(in_paint >= 2 and (hp is None or not _cz_in_paint(*hp)))
            P = np.array([p for _, p in pts])
            d = np.sqrt(((P[:, None] - P[None]) ** 2).sum(-1))
            np.fill_diagonal(d, np.inf)
            nn.append(float(d.min(1).mean()))
        if frames:
            rows.append({"clip_key": key, "lineup": r.get("offense_lineup"), "both_corners": corners / frames,
                         "paint_crowded": crowd / frames, "spacing_ft": float(np.mean(nn)), "points": _ti_points(r)})
    sp = pd.DataFrame(rows)
    if sp.empty:
        return sp
    out = (sp.groupby("lineup", dropna=False).agg(possessions=("clip_key", "count"), both_corners_pct=("both_corners", "mean"),
                                                  paint_crowded_pct=("paint_crowded", "mean"), spacing_ft=("spacing_ft", "mean"),
                                                  ppp=("points", "mean")).reset_index())
    for col in ("both_corners_pct", "paint_crowded_pct"):
        out[col] = (100 * out[col]).round()
    out["spacing_ft"] = out["spacing_ft"].round(1)
    out["ppp"] = out["ppp"].round(2)
    return out.sort_values("possessions", ascending=False)


def _cz_diagrams(clips):
    """One FastDraw-style diagram per possession: offense numbered 1-5 (1 = first ball handler, then by distance
    from the basket: farthest = guards, closest = 5), each player's path, dribbles, passes and the screen."""
    rows = []
    for key, c in clips.items():
        r = c["row"]
        off = [k for k in _ti_side(c, "offense") if len(c["tr"][k]["court"]) >= 2]
        dfn = [k for k in _ti_side(c, "defense") if len(c["tr"][k]["court"]) >= 2]
        if len(off) < 3:
            continue
        first_holder = next((k for t, k in sorted(c["holder"].items()) if k in off), None)
        dist = {k: float(np.mean([np.hypot(hx - _CZ_BASKET[0], hy - _CZ_BASKET[1]) for hx, hy in c["tr"][k]["court"].values()])) for k in off}
        order = ([first_holder] if first_holder is not None else []) + sorted([k for k in off if k != first_holder], key=lambda k: -dist[k])
        num = {k: i + 1 for i, k in enumerate(order[:5])}
        players = []
        for k in off + dfn:
            pts = sorted(c["tr"][k]["court"].items())
            step = max(1, len(pts) // 12)
            players.append({"id": k, "num": num.get(k), "side": c["tr"][k]["side"], "name": c["tr"][k]["name"],
                            "path": [[t, round(hx, 1), round(hy, 1)] for t, (hx, hy) in pts[::step] + ([pts[-1]] if pts[-1] not in pts[::step] else [])]})
        # dribbles = frames the same offensive player keeps the ball; passes = the ball changing hands
        seq = [(t, k) for t, k in sorted(c["holder"].items()) if k in num]
        passes = [{"from": num[a], "to": num[b], "t": t2} for (t1, a), (t2, b) in zip(seq, seq[1:]) if a != b]
        dribbles = []
        for k in set(k for _, k in seq):
            ts = [t for t, kk in seq if kk == k]
            if len(ts) >= 2:
                dribbles.append({"num": num[k], "from_t": ts[0], "to_t": ts[-1]})
        screen = None
        s = c["screen"]
        if s and s.get("screener") in c["tr"]:
            sp = _cz_near(c["tr"][s["screener"]]["court"], s["t"])
            if sp:
                screen = {"num": num.get(s["screener"]), "t": s["t"], "hx": round(sp[0], 1), "hy": round(sp[1], 1),
                          "type": s.get("type"),
                          "for": num.get(s.get("screened")) if s.get("screened") is not None else None}
        rows.append({"clip_key": key, "game_date": r.get("game_date"), "offense_team": r.get("offense_team"),
                     "defense_team": r.get("defense_team"), "play_title": r.get("play_title"),
                     "synergy_string": r.get("synergy_string"), "result": r.get("result"),
                     "diagram": _trk_json.dumps({"players": players, "passes": passes, "dribbles": dribbles, "screen": screen})})
    return pd.DataFrame(rows)


if isinstance(globals().get("player_tracks"), pd.DataFrame) and "court_path" in player_tracks.columns \
        and player_tracks["court_path"].notna().any():
    try:
        _cz_c = _cz_clips()
        _shots, _zones = _cz_shots(_cz_c)
        _scr, _scr_z = _cz_screens(_cz_c)
        _cz_tables.update({"uww_court_shots": _shots, "uww_court_shot_zones": _zones, "uww_court_heat": _cz_heat(_cz_c),
                           "uww_court_screens": _scr, "uww_court_screen_zones": _scr_z, "uww_court_help": _cz_help(_cz_c),
                           "uww_court_zone_press": _cz_zone_press(_cz_c), "uww_court_spacing": _cz_spacing(_cz_c),
                           "uww_court_diagrams": _cz_diagrams(_cz_c)})
        # the same, game by game ("<name>_by_game", with game_date / game_code) for the app's per-game Film Tracking;
        # per-play tables (shots, screens, diagrams) already carry their game
        import contextlib as _ctx
        import io as _io
        _cz_games = {}
        for _k, _c in _cz_c.items():
            _cz_games.setdefault((str(_c["row"].get("game_date")), str(_c["row"].get("game_code"))), {})[_k] = _c
        _cby = {n: [] for n in ("uww_court_shot_zones", "uww_court_heat", "uww_court_screen_zones", "uww_court_help",
                                "uww_court_zone_press", "uww_court_spacing")}
        for (_gd, _gc), _sub in _cz_games.items():
            try:
                with _ctx.redirect_stdout(_io.StringIO()):
                    _gsh, _gz = _cz_shots(_sub)
                    _gs, _gsz = _cz_screens(_sub)
                    _parts = {"uww_court_shot_zones": _gz, "uww_court_heat": _cz_heat(_sub), "uww_court_screen_zones": _gsz,
                              "uww_court_help": _cz_help(_sub), "uww_court_zone_press": _cz_zone_press(_sub),
                              "uww_court_spacing": _cz_spacing(_sub)}
                for _n, _t in _parts.items():
                    if isinstance(_t, pd.DataFrame) and not _t.empty:
                        _cby[_n].append(_t.assign(game_date=_gd, game_code=_gc))
            except Exception as _ge:
                print(f"  [court] per-game tables skipped for {_gd} {_gc}: {type(_ge).__name__}: {_ge}")
        for _n, _lst in _cby.items():
            _cz_tables[_n + "_by_game"] = pd.concat(_lst, ignore_index=True) if _lst else pd.DataFrame()
        _rep = court_report.copy()
        if not _shots.empty and not _rep.empty:
            _rep["shots_zone_agrees_with_2_or_3_pct"] = round(100 * _shots["zone_agrees_with_result"].mean())
            _rep["shots_checked"] = len(_shots)
        _cz_tables["uww_court_report"] = _rep
        print(f"Court insights: {len(_cz_c)} possession(s) on the court -- " + ", ".join(
            f"{k.replace('uww_court_', '')} {len(v)}" for k, v in _cz_tables.items()))
        if not _shots.empty:
            print(f"  Check: {round(100 * _shots['zone_agrees_with_result'].mean())}% "
                  f"of {len(_shots)} tracked shots land on the right side of the 3-pt line for what Synergy called them "
                  f"(low = the court mapping or the shooter pick needs work).")
    except Exception as _e:
        print("  " + "!" * 100)
        print(f"  COURT INSIGHTS NOT BUILT: {type(_e).__name__}: {_e}")
        print("  " + "!" * 100)
else:
    _cz_tables["uww_court_report"] = court_report if isinstance(globals().get("court_report"), pd.DataFrame) else pd.DataFrame()
    print("Court insights: nothing on the court yet (court mapping needs a calibration -- see the court mapping cell).")
