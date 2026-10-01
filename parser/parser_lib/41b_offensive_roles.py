# 41b_offensive_roles.py -- code for the notebook section "Offensive roles"
# Runs inside the notebook via run_section("41b_offensive_roles"); its settings are in that notebook cell.

# --- Offensive roles: every player (UWW and opponents) in one of BBall Index's 12 offensive roles ----------------------
# CONFIRMED CHANGE (requested: "every player, UWW and opponents, bucketed into one offensive role based on
# https://www.bball-index.com/offensive-archetypes/").
# The 12 roles -- guards/wings: Primary Ball Handler, Secondary Ball Handler, Shot Creator, Slasher, Athletic Finisher,
# Off Screen Shooter, Movement Shooter, Stationary Shooter; bigs: Versatile Big, Post Scorer, Stretch Big, Roll & Cut Big.
# BBall Index assigns them from play-type shares (PnR ball handler, isolation, spot-up, off screen, handoff, cut,
# putback, post-up, roll man), 3PA rate, drives and how often a player initiates. Their exact cut-offs aren't
# published (and are NBA-scale), so this follows their definitions with Division III cut-offs set below.
#
# Per player, over every game with a play-by-play file, shares of his SCORING POSSESSIONS (shots, turnovers, fouled
# trips):
#   * Synergy play types -- from the video descriptions matched onto the play-by-play ("... > 32 Luke Bara > Spot-Up >
#     Drives Left > To Basket > Foul": his own part of the play), wherever they exist;
#   * the play-by-play itself, always: 3PA rate (2s vs 3s), driving layups, hooks / turnarounds (post), putbacks (a shot
#     right after his own offensive rebound), assists (initiating).
# Every player gets a role: "low sample" when there are few possessions, "position only" (from the roster) when there
# is no play data at all. -> player_profiles["offensive_role"] and the table offensive_roles (uww_offensive_roles.csv).
import re
import numpy as np
import pandas as pd

_OR_TYPES = {"p&r ball handler": "prbh", "pick and roll ball handler": "prbh", "isolation": "iso", "iso": "iso",
             "spot-up": "spot", "spot up": "spot", "off screen": "offscreen", "hand off": "handoff", "handoff": "handoff",
             "cut": "cut", "transition": "trans", "post-up": "post", "post up": "post", "p&r roll man": "roll",
             "pick and roll roll man": "roll", "offensive rebound": "putback", "put back": "putback", "putback": "putback"}


def _or_norm(n):
    return re.sub(r"[^a-z]", "", str(n or "").lower())


def _or_chain(desc, player):
    """The player's own part of a Synergy description -> list of segments after his name (to the next player)."""
    if not isinstance(desc, str) or not isinstance(player, str):
        return None
    segs = [s.strip() for s in desc.split(">")]
    me = _or_norm(player)
    idx = None
    for i, s in enumerate(segs):
        m = re.match(r"^\d{1,2}\s+(.+)$", s)
        if m and _or_norm(m.group(1)) == me:
            idx = i
    if idx is None:
        return None
    out = []
    for s in segs[idx + 1:]:
        if re.match(r"^\d{1,2}\s+[A-Za-z]", s):
            break
        out.append(s)
    return out


def _or_player_events():
    """Every scoring possession by every player: shots, turnovers, first free throw of a trip -> one row each."""
    frames = []
    for nm in ("pbp_events", "pbp_events_upcoming"):
        ev = globals().get(nm)
        if isinstance(ev, pd.DataFrame) and not ev.empty and {"event_type", "player", "team"} <= set(ev.columns):
            e = ev.copy()
            e["_src"] = nm
            frames.append(e)
    if not frames:
        return pd.DataFrame()
    ev = pd.concat(frames, ignore_index=True)
    keys = [c for c in ("opponent", "game_date") if c in ev.columns]
    ev = ev.drop_duplicates(subset=[c for c in keys + ["period", "event_order", "event_type", "player"] if c in ev.columns])
    ev = ev.sort_values(keys + [c for c in ("event_order",) if c in ev.columns])
    rows = []
    prev = {}
    for _, e in ev.iterrows():
        et, pl, tm = e["event_type"], e.get("player"), e.get("team")
        gkey = tuple(e.get(k) for k in keys) + (e.get("period"),)
        clock = e.get("time_remaining_seconds")
        if et in ("rebound_offensive",) and isinstance(pl, str):
            prev[(gkey, pl)] = clock
        if not isinstance(pl, str) or not isinstance(tm, str):
            continue
        is_shot = et in ("made_shot", "missed_shot")
        is_ft1 = et in ("free_throw_made", "free_throw_missed") and (pd.isna(e.get("ft_num")) or e.get("ft_num") == 1)
        if not (is_shot or et == "turnover" or is_ft1):
            continue
        desc = str(e.get("shot_desc") or "")
        pb_clock = prev.get((gkey, pl))
        rows.append({"team": tm, "player": pl, "kind": "shot" if is_shot else ("to" if et == "turnover" else "ft"),
                     "three": is_shot and str(e.get("shot_type")) == "3",
                     "driving": is_shot and "driving" in desc.lower(),
                     "post_shot": is_shot and any(w in desc.lower() for w in ("hook", "turnaround", "post")),
                     "rim": is_shot and any(w in desc.lower() for w in ("layup", "dunk", "tip")),
                     "putback": is_shot and pb_clock is not None and pd.notna(clock) and pd.notna(pb_clock)
                                and 0 <= float(pb_clock) - float(clock) <= 3,
                     "chain": _or_chain(e.get("video_description"), pl)})
    return pd.DataFrame(rows)


def _or_assists():
    out = {}
    for nm in ("pbp_events", "pbp_events_upcoming"):
        ev = globals().get(nm)
        if isinstance(ev, pd.DataFrame) and not ev.empty and "event_type" in ev.columns:
            a = ev[ev["event_type"] == "assist"].groupby(["team", "player"]).size()
            for k, v in a.items():
                out[k] = out.get(k, 0) + int(v)
    return out


def _or_features(g, n_ast):
    """One player's rows -> the numbers the roles are decided from."""
    poss = len(g)
    shots = g[g["kind"] == "shot"]
    fga = max(len(shots), 1)
    f = {"poss": poss, "fga": len(shots), "three_rate": shots["three"].mean() if len(shots) else 0.0,
         "assists": n_ast, "ast_per_poss": n_ast / max(poss, 1)}
    vid = g[g["chain"].map(lambda c: isinstance(c, list) and len(c) > 0)]
    f["poss_video"] = len(vid)
    types = {k: 0 for k in set(_OR_TYPES.values())}
    drives = trans_bh = drib3 = three_v = 0
    for _, r in vid.iterrows():
        c = [s.lower() for s in r["chain"]]
        t = _OR_TYPES.get(c[0])
        if t == "roll" and any("pop" in s_ for s_ in c[1:3]):
            t = "spot"                            # pick-and-POP: the screener spots up for a shot -- not a roll to the rim
        if t:
            types[t] += 1
        if t == "trans" and len(c) > 1 and "ball" in c[1]:
            trans_bh += 1
        if any(s.startswith("drive") or s == "to basket" for s in c) and t in ("prbh", "iso", "spot", "trans", "handoff"):
            drives += 1
        if r["three"]:
            three_v += 1
            if t in ("trans", "handoff", "offscreen") or any("dribble jumper" in s and "no dribble" not in s for s in c):
                drib3 += 1
    nv = max(len(vid), 1)
    if len(vid) >= ROLE_MIN_VIDEO_POSS:
        f.update({k: v / nv for k, v in types.items()})
        f["trans_bh"] = trans_bh / nv
        f["drive"] = drives / nv
        f["onball"] = (types["prbh"] + types["iso"] + trans_bh) / nv
        f["moving3"] = drib3 / max(three_v, 1)
        f["source"] = "Synergy play types"
    else:                                         # play-by-play only: close stand-ins
        f.update({k: 0.0 for k in types})
        f["post"] = shots["post_shot"].sum() / fga
        f["putback"] = shots["putback"].sum() / fga
        f["cut"] = max(0.0, (shots["rim"] & ~shots["driving"] & ~shots["putback"]).sum() / fga * 0.5)
        f["drive"] = shots["driving"].sum() / fga
        f["trans_bh"] = 0.0
        # assists mark a ball handler -- only with enough of them to mean something
        f["onball"] = (min(1.0, f["ast_per_poss"] / max(ROLE_ASSIST_BALLHANDLER, 1e-6) * ROLE_ONBALL_MIN)
                       if n_ast >= 3 and poss >= 10 else 0.0)
        f["moving3"] = 0.0
        f["source"] = "play-by-play only"
    f["big_share"] = f["post"] + f["roll"] + f["putback"] + f["cut"]
    return f


def _or_decide(f, pos, height_in, team_onball_share):
    """Features -> (role, why)."""
    pos = str(pos or "").upper()
    listed_guard = "G" in pos
    if listed_guard:
        # a listed guard (G, G/F) is a big only if clearly one: mostly big-man plays and tall
        big = f["big_share"] >= ROLE_GUARD_BIG_SHARE and (height_in or 0) >= ROLE_GUARD_BIG_HEIGHT_IN
    else:
        big = (f["big_share"] >= ROLE_BIG_SHARE or "C" in pos.replace("CENTER", "C")
               or ("F" in pos and (height_in or 0) >= ROLE_BIG_HEIGHT_IN and f["big_share"] >= ROLE_BIG_SHARE_TALL))
    tr = f["three_rate"]
    if big:
        post, shoots = f["post"] >= ROLE_POST_SHARE, tr >= ROLE_BIG_3PA_RATE
        role = ("Versatile Big" if post and shoots else "Post Scorer" if post else "Stretch Big" if shoots else "Roll & Cut Big")
    elif f["iso"] >= ROLE_ISO_SHARE:
        role = "Shot Creator"
    elif f["onball"] >= ROLE_ONBALL_MIN:
        role = "Primary Ball Handler" if team_onball_share >= ROLE_PRIMARY_TEAM_SHARE else "Secondary Ball Handler"
    elif f["drive"] >= ROLE_DRIVE_SHARE and tr < ROLE_SHOOTER_3PA_RATE:
        role = "Slasher"
    elif (f["cut"] + f["putback"] + (f["trans"] - f["trans_bh"])) >= ROLE_FINISHER_SHARE and tr < ROLE_FINISHER_MAX_3PA:
        role = "Athletic Finisher"
    elif f["offscreen"] + f["handoff"] >= ROLE_OFFSCREEN_SHARE:
        role = "Off Screen Shooter"
    elif tr >= ROLE_SHOOTER_3PA_RATE:
        role = "Movement Shooter" if f["moving3"] >= ROLE_MOVING_SHARE else "Stationary Shooter"
    else:                                         # nothing stands out: the biggest part of his game decides
        cand = {"Slasher": f["drive"], "Athletic Finisher": f["cut"] + f["putback"],
                "Secondary Ball Handler": f["onball"], "Stationary Shooter": tr * 0.8 + f["spot"] * 0.5}
        role = max(cand, key=cand.get)
    pct = lambda x: f"{100 * x:.0f}%"
    why = (f"{'big' if big else 'guard/wing'}; PnR {pct(f['prbh'])} · ISO {pct(f['iso'])} · spot-up {pct(f['spot'])} · "
           f"off screen/handoff {pct(f['offscreen'] + f['handoff'])} · cut/putback {pct(f['cut'] + f['putback'])} · "
           f"post {pct(f['post'])} · roll {pct(f['roll'])} · drives {pct(f['drive'])} · 3PA rate {pct(tr)} · "
           f"{f['poss']} poss ({f['source']})")
    return role, why


def offensive_roles():
    pe = _or_player_events()
    ast = _or_assists()
    # roster facts (position, height) for every player we can find
    ros = []
    for nm, team_col in (("live_rosters", "team"), ("player_profiles", "opponent"), ("all_rosters", "opponent")):
        t = globals().get(nm)
        if isinstance(t, pd.DataFrame) and not t.empty and "name" in t.columns:
            ros.append(pd.DataFrame({"team": t.get(team_col), "name": t["name"], "position": t.get("position"),
                                     "height": t.get("height")}))
    ros = pd.concat(ros, ignore_index=True).dropna(subset=["name"]) if ros else pd.DataFrame(columns=["team", "name", "position", "height"])
    ros["_n"] = ros["name"].map(_or_norm)
    ros = ros.drop_duplicates("_n")
    hi = globals().get("parse_height_inches") or (lambda h: None)
    info = {r["_n"]: (r["position"], hi(r["height"]) if pd.notna(r["height"]) else None, r["team"]) for _, r in ros.iterrows()}
    rows = []
    if not pe.empty:
        feats = {}
        for (tm, pl), g in pe.groupby(["team", "player"]):
            feats[(tm, pl)] = _or_features(g, ast.get((tm, pl), 0))
        # share of each team's on-ball possessions (initiator estimate for Primary vs Secondary)
        team_onball = {}
        for (tm, pl), f in feats.items():
            team_onball[tm] = team_onball.get(tm, 0.0) + f["onball"] * f["poss"]
        for (tm, pl), f in feats.items():
            pos, h, _t = info.get(_or_norm(pl), (None, None, None))
            share = f["onball"] * f["poss"] / max(team_onball.get(tm, 0.0), 1e-6)
            role, why = _or_decide(f, pos, h, share)
            basis = f["source"] + ("" if f["poss"] >= ROLE_MIN_POSS else " (low sample)")
            rows.append({"team": tm, "player": pl, "offensive_role": role, "role_basis": basis, "why": why,
                         "position": pos, "height_in": h, "possessions": f["poss"], "video_possessions": f["poss_video"],
                         **{k: round(float(f[k]), 3) for k in ("three_rate", "prbh", "iso", "spot", "offscreen", "handoff",
                                                               "cut", "trans", "post", "roll", "putback", "drive",
                                                               "onball", "moving3", "ast_per_poss")},
                         "team_onball_share": round(share, 3)})
    seen = {_or_norm(r["player"]) for r in rows}
    fallback = {"GUARD": "Secondary Ball Handler", "WING": "Stationary Shooter", "FORWARD/POST": "Roll & Cut Big"}
    norm_pos = globals().get("normalize_position") or (lambda p: "Unknown")
    for n_, (pos, h, tm) in info.items():
        if n_ in seen:
            continue
        name = ros.loc[ros["_n"] == n_, "name"].iloc[0]
        grp = str(norm_pos(pos)).upper()
        rows.append({"team": tm, "player": name, "offensive_role": fallback.get(grp, "Stationary Shooter"),
                     "role_basis": "position only", "why": f"no play data -- from the roster position ({pos or 'unknown'})",
                     "position": pos, "height_in": h, "possessions": 0, "video_possessions": 0})
    out = pd.DataFrame(rows).sort_values(["team", "possessions"], ascending=[True, False]).reset_index(drop=True)
    return out


def offensive_role_for(name, team=None):
    """(offensive role, basis) for one player, from offensive_roles_table -- the ONE source every roster table uses
    (player profiles, opponent rosters, personnel tiers, the brief). A same-named player on another team never wins
    over a match on the player's own team."""
    t = globals().get("offensive_roles_table")
    if not isinstance(t, pd.DataFrame) or t.empty:
        return None, None
    rows = t[t["player"].map(_or_norm) == _or_norm(name)]
    if rows.empty:
        return None, None
    if team is not None and len(rows) > 1:
        tq = _or_norm(team)
        own = rows[rows["team"].map(lambda x: bool(tq) and (tq in _or_norm(x) or _or_norm(x) in tq))]
        if not own.empty:
            rows = own
    r = rows.sort_values("possessions", ascending=False).iloc[0]
    return r["offensive_role"], r["role_basis"]


def _or_attach(df, name_col="name", team_col=None):
    """Add offensive_role / offensive_role_basis to a roster-style table (in place)."""
    if not isinstance(df, pd.DataFrame) or df.empty or name_col not in df.columns:
        return
    pairs = [offensive_role_for(r[name_col], r[team_col] if team_col and team_col in df.columns else None)
             for _, r in df.iterrows()]
    df["offensive_role"] = [p[0] for p in pairs]
    df["offensive_role_basis"] = [p[1] for p in pairs]


if RUN_OFFENSIVE_ROLES:
    try:
        offensive_roles_table = offensive_roles()
        # CONFIRMED CHANGE (requested: "add these offensive roles to the Roster tables"). Every roster-style table gets
        # the same two columns from offensive_role_for() -- one source, so no two tables can disagree on a player's role:
        # player profiles and opponent rosters here; personnel tiers where they're built (Game plan section).
        _or_attach(globals().get("player_profiles"), "name", "opponent")
        _or_attach(globals().get("all_rosters"), "name", "opponent")      # exported as uww_opponent_rosters
        _or_attach(globals().get("live_rosters"), "name", "team")
        _t = offensive_roles_table
        print(f"Offensive roles: {len(_t)} player(s) -- {int(_t['role_basis'].str.startswith('Synergy').sum())} from Synergy "
              f"play types, {int(_t['role_basis'].str.startswith('play-by-play').sum())} from the play-by-play only, "
              f"{int((_t['role_basis'] == 'position only').sum())} from roster position only "
              f"({int(_t['role_basis'].str.contains('low sample').sum())} marked low sample)")
        print("  roles: " + "; ".join(f"{k} {v}" for k, v in _t["offensive_role"].value_counts().items()))
        for _tm, _g in _t[_t["possessions"] > 0].groupby("team"):
            print(f"  {_tm}: " + "; ".join(f"{r.player} = {r.offensive_role}" for r in _g.head(9).itertuples()))
    except Exception as _e:
        offensive_roles_table = pd.DataFrame()
        print(f"Offensive roles skipped: {type(_e).__name__}: {_e}")
