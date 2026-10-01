# 55d_defensive_roles.py -- code for the notebook section "Defensive roles"
# Runs inside the notebook via run_section("55d_defensive_roles"); its settings are in that notebook cell.

# --- Defensive roles: every player (UWW and opponents) in one of BBall Index's 7 defensive roles -----------------------
# CONFIRMED CHANGE (requested: "similar to the offensive role types, create the defensive role types" --
# https://www.bball-index.com/defensive-roles/). The 7 roles: Point of Attack, Wing Stopper, Chaser, Helper, Low
# Activity, Mobile Big, Anchor Big. BBall Index assigns them from MATCHUP data (who each player guards, by position and
# by the 12 offensive roles) plus rim time, screen involvement and help; their cut-offs aren't published (and are
# NBA-scale), so this follows their definitions with Division III cut-offs set in the notebook cell.
#
# Per player, every defensive action we can credit to him BY NAME:
#   * coaches' coverage tags with the defender's jersey number ("12drop", "5tl") -- mapped to a name with that game's
#     own numbers, preferring the five on the floor;
#   * film tracking -- matchups, screen defenders, weak-side help -- ONLY where his name on that play came from evidence
#     (coach checks, jersey numbers, lineups, linked plays), never from a best guess;
#   * the play-by-play: blocks, steals, defensive rebounds per game.
# Every player gets a role: "low sample" with few credited actions, "play-by-play only", or "position only".
import re
import numpy as np
import pandas as pd

_DR_MOBILE = {"switch", "hedge", "soft hedge", "show", "show & get back", "blitz", "ice", "switch 2nd",
              "stay, then switch 2nd", "jam", "weak"}
_DR_ANCHOR = {"drop", "under", "sag"}
_DR_ONBALL_COV = {"over", "under", "stay (reject)", "fight", "ice", "switch", "show", "hedge", "soft hedge", "blitz",
                  "show & get back", "drop", "stay, then switch 2nd"}
_DR_CHASE_COV = {"top lock", "trail", "chase", "front", "bump", "cheat", "through", "deny"}
_DR_BALL_SCREENS = ("ball screen", "high ball screen", "double ball screen", "ricky", "zoom", "dho", "get", "double drag")
_DR_ONBALL_OFF_ROLES = {"Primary Ball Handler", "Secondary Ball Handler", "Shot Creator", "Slasher"}
_DR_CHASE_OFF_ROLES = {"Off Screen Shooter", "Movement Shooter", "Stationary Shooter", "Athletic Finisher"}
_DR_BIG_OFF_ROLES = {"Versatile Big", "Post Scorer", "Stretch Big", "Roll & Cut Big"}


def _dr_norm(n):
    return re.sub(r"[^a-z]", "", str(n or "").lower())


def _dr_tag_actions():
    """Coaches' coverage tags with a defender number -> [(team, player, screen kind, coverage)]."""
    pc = globals().get("play_calls")
    out = []
    if not isinstance(pc, pd.DataFrame) or pc.empty or "coverage_detail" not in pc.columns:
        return out
    for _, r in pc[pc["coverage_detail"].astype(str).str.contains("def #", na=False)].iterrows():
        team = r.get("defense_team")
        nums = _trk_numbers_for_game(str(r.get("game_date")), str(r.get("game_code"))) if "_trk_numbers_for_game" in globals() else {}
        five = [x.strip() for x in str(r.get("defense_lineup") or "").split(",") if x.strip()]
        by_num = {}
        for n_, j_ in nums.items():
            by_num.setdefault(str(j_), []).append(n_)
        for part in str(r["coverage_detail"]).split("|"):
            m = re.match(r"\s*([^:]+):\s*(.+?)\s*\(def #(\d{1,2})\)", part)
            if not m:
                continue
            screen, cov, num = m.group(1).strip().lower(), m.group(2).strip().lower(), m.group(3)
            cands = by_num.get(num, [])
            on_floor = [c for c in cands if any(_dr_norm(c) == _dr_norm(f) for f in five)]
            pick = (on_floor or cands)
            if not pick:
                continue
            name = next((f for f in five if _dr_norm(f) == _dr_norm(pick[0])), pick[0].title())
            out.append((team, name, "ball" if screen.startswith(_DR_BALL_SCREENS) else "offball", cov))
    return out


def _dr_evidence_names():
    """(clip_key, player) pairs named from evidence (not a best guess) in the last tracking run."""
    pt = globals().get("player_tracks")
    if not isinstance(pt, pd.DataFrame) or pt.empty or "name_how" not in pt.columns:
        return set()
    ev = pt[pt["name"].notna() & (pt["name_how"] != "best guess")]
    return {(k, _dr_norm(n)) for k, n in zip(ev["clip_key"], ev["name"])}


def _dr_film_actions(evidence):
    """Film tracking, evidence-named defenders only -> dict per (team, player) of matchup / screen / help counts."""
    tabs = globals().get("_ti_tables") or {}
    off_role = {}
    ort = globals().get("offensive_roles_table")
    if isinstance(ort, pd.DataFrame) and not ort.empty:
        off_role = {_dr_norm(p): r for p, r in zip(ort["player"], ort["offensive_role"])}
    acts = {}
    def bump(team, player, key, n=1):
        d = acts.setdefault((team, player), {})
        d[key] = d.get(key, 0) + n
    mu = tabs.get("uww_trk_matchups_raw")             # per play only -- the summary can't be checked for evidence
    if isinstance(mu, pd.DataFrame) and not mu.empty and {"defender", "guards", "clip_key"} <= set(mu.columns):
        for _, r in mu.iterrows():
            if (r["clip_key"], _dr_norm(r["defender"])) not in evidence:
                continue
            w = float(r.get("share_of_frames", 1) or 1)
            role = off_role.get(_dr_norm(r["guards"]))
            bump(r["defense_team"], r["defender"], "matchups", w)
            if role in _DR_ONBALL_OFF_ROLES:
                bump(r["defense_team"], r["defender"], "vs_onball", w)
                if role == "Shot Creator":
                    bump(r["defense_team"], r["defender"], "vs_creator", w)
            elif role in _DR_CHASE_OFF_ROLES:
                bump(r["defense_team"], r["defender"], "vs_offball", w)
            elif role in _DR_BIG_OFF_ROLES:
                bump(r["defense_team"], r["defender"], "vs_big", w)
    scr = tabs.get("uww_trk_screens")
    if isinstance(scr, pd.DataFrame) and not scr.empty:
        for _, r in scr.iterrows():
            ball = "ball" in str(r.get("screen_type", "")).lower() and "off" not in str(r.get("screen_type", "")).lower()
            for col, role_ in (("screened_defender", "on_ball" if ball else "chase"), ("screener_defender", "screener")):
                p = r.get(col)
                if isinstance(p, str) and (r.get("clip_key"), _dr_norm(p)) in evidence:
                    bump(r.get("defense_team"), p, role_)
                    est = str(r.get("coverage_tracking_estimate") or "").lower()
                    if role_ == "screener" and est:
                        bump(r.get("defense_team"), p, "mobile" if any(w in est for w in ("switch", "hedge", "show", "blitz")) else
                             ("anchor" if "drop" in est else "screener_other"))
    hp = tabs.get("uww_trk_help_raw")
    if isinstance(hp, pd.DataFrame) and not hp.empty and "defender" in hp.columns:
        for _, r in hp.iterrows():
            if (r.get("clip_key"), _dr_norm(r["defender"])) in evidence:
                bump(r.get("defense_team"), r["defender"], "help")
    return acts


def _dr_pbp_rates():
    """Blocks / steals / defensive rebounds per game, every player in every game with a play-by-play file."""
    frames = [globals().get(n) for n in ("pbp_events", "pbp_events_upcoming")]
    ev = pd.concat([f for f in frames if isinstance(f, pd.DataFrame) and not f.empty
                    and {"event_type", "player", "team"} <= set(f.columns)], ignore_index=True) if any(
        isinstance(f, pd.DataFrame) and not f.empty for f in frames) else pd.DataFrame()
    if ev.empty:
        return {}
    gk = [c for c in ("opponent", "game_date") if c in ev.columns]
    ev = ev.dropna(subset=["player"])
    games = ev.groupby(["team", "player"])[gk].apply(lambda d: len(d.drop_duplicates())) if gk else ev.groupby(["team", "player"]).size()
    out = {}
    for (tm, pl), g in ev.groupby(["team", "player"]):
        n = max(int(games.get((tm, pl), 1)), 1)
        out[(tm, pl)] = {"games": n, "blk": (g["event_type"] == "block").sum() / n, "stl": (g["event_type"] == "steal").sum() / n,
                         "dreb": (g["event_type"] == "rebound_defensive").sum() / n}
    return out


def defensive_roles():
    tag = _dr_tag_actions()
    film = _dr_film_actions(_dr_evidence_names()) if DROLE_USE_TRACKING else {}
    pbp = _dr_pbp_rates()
    # roster facts, offensive roles (big or not), the same way as the offensive roles
    ros = {}
    for nm, tc in (("live_rosters", "team"), ("player_profiles", "opponent"), ("all_rosters", "opponent")):
        t = globals().get(nm)
        if isinstance(t, pd.DataFrame) and not t.empty and "name" in t.columns:
            for _, r in t.iterrows():
                ros.setdefault(_dr_norm(r["name"]), (r.get(tc), r.get("position"), r.get("height"), r["name"]))
    hi = globals().get("parse_height_inches") or (lambda h: None)
    ort = globals().get("offensive_roles_table")
    off = {_dr_norm(p): r for p, r in zip(ort["player"], ort["offensive_role"])} if isinstance(ort, pd.DataFrame) and not ort.empty else {}
    # everyone we know about
    people = {}
    for tm, pl, _k, _c in tag:
        people.setdefault(_dr_norm(pl), (tm, pl))
    for (tm, pl) in list(film) + list(pbp):
        people.setdefault(_dr_norm(pl), (tm, pl))
    for k, (tm, _pos, _h, name) in ros.items():
        people.setdefault(k, (tm, name))
    rows = []
    for k, (tm, pl) in people.items():
        _rt, pos, ht, _n = ros.get(k, (None, None, None, None))
        pos = str(pos or "").upper()
        h_in = hi(ht) if ht is not None and not (isinstance(ht, float) and np.isnan(ht)) else None
        orole = off.get(k)
        t_ = [(kind, cov) for (tm2, pl2, kind, cov) in tag if _dr_norm(pl2) == k]
        f_ = {}
        for (tm2, pl2), d in film.items():
            if _dr_norm(pl2) == k:
                for kk, vv in d.items():
                    f_[kk] = f_.get(kk, 0) + vv
        p_ = next((v for (tm2, pl2), v in pbp.items() if _dr_norm(pl2) == k), None)
        big = (orole in _DR_BIG_OFF_ROLES or "C" in pos.replace("CENTER", "C")
               or ("F" in pos and "G" not in pos and (h_in or 0) >= DROLE_BIG_HEIGHT_IN))
        wing = (not big) and ("F" in pos or (h_in or 0) >= DROLE_WING_HEIGHT_IN)
        mobile = sum(1 for kind, cov in t_ if kind == "ball" and cov in _DR_MOBILE) + f_.get("mobile", 0)
        anchor = sum(1 for kind, cov in t_ if kind == "ball" and cov in _DR_ANCHOR) + f_.get("anchor", 0)
        onball = (sum(1 for kind, cov in t_ if kind == "ball" and cov in _DR_ONBALL_COV) + f_.get("on_ball", 0)
                  + f_.get("vs_onball", 0) * DROLE_MATCHUP_WEIGHT)
        chase = (sum(1 for kind, cov in t_ if kind == "offball" or cov in _DR_CHASE_COV) + f_.get("chase", 0)
                 + f_.get("vs_offball", 0) * DROLE_MATCHUP_WEIGHT)
        creator = f_.get("vs_creator", 0)
        help_ = f_.get("help", 0)
        games = (p_ or {}).get("games", 0)
        stocks = ((p_ or {}).get("stl", 0) + (p_ or {}).get("blk", 0)) if p_ else None
        blk = (p_ or {}).get("blk", 0) if p_ else None
        n_actions = len(t_) + sum(v for kk, v in f_.items() if kk not in ("matchups",))
        if big:
            if mobile + anchor >= DROLE_MIN_COVERAGES:
                role = "Mobile Big" if mobile > anchor else "Anchor Big"
            elif blk is not None and blk >= DROLE_ANCHOR_BLOCKS_PER_GAME:
                role = "Anchor Big"
            else:
                role = "Anchor Big" if "C" in pos else "Mobile Big"
        elif onball >= DROLE_MIN_ACTIONS and onball >= chase * DROLE_ONBALL_OVER_CHASE:
            role = "Wing Stopper" if (wing or creator >= max(1.0, 0.3 * onball)) else "Point of Attack"
        elif chase >= DROLE_MIN_ACTIONS and chase >= onball:
            role = "Chaser"
        elif (help_ >= DROLE_MIN_ACTIONS) or (stocks is not None and stocks >= DROLE_HELPER_STOCKS_PER_GAME):
            role = "Helper"
        elif stocks is not None and stocks < DROLE_LOW_STOCKS_PER_GAME and n_actions < DROLE_MIN_ACTIONS:
            role = "Low Activity"
        elif onball + chase > 0:                      # some credited actions, too few to be sure: they still decide
            role = ("Chaser" if chase > onball else ("Wing Stopper" if wing else "Point of Attack"))
        else:                                         # nothing stands out: his size decides
            role = "Wing Stopper" if wing else "Point of Attack"
        if n_actions >= DROLE_MIN_ACTIONS:
            basis = "coach tags" + (" + film" if f_ else "") if t_ else "film tracking"
        elif n_actions > 0:
            basis = ("coach tags" if t_ else "film tracking") + " (low sample)"
        elif p_:
            basis = "play-by-play only"
        else:
            basis = "position only"
        why = (f"{'big' if big else 'wing' if wing else 'guard'}; on-ball {onball:.0f} · chasing {chase:.0f} · help {help_:.0f}"
               f" · switch/hedge {mobile} · drop {anchor}"
               + (f" · {stocks:.1f} steals+blocks a game ({games} games)" if stocks is not None else "")
               + (f" · offensive role {orole}" if orole else ""))
        rows.append({"team": tm, "player": pl, "defensive_role": role, "role_basis": basis, "why": why,
                     "position": pos or None, "height_in": h_in, "credited_actions": n_actions,
                     "on_ball": round(onball, 1), "chasing": round(chase, 1), "help": help_, "mobile_coverages": mobile,
                     "drop_coverages": anchor, "steals_blocks_per_game": round(stocks, 2) if stocks is not None else None,
                     "games": games})
    return pd.DataFrame(rows).sort_values(["team", "credited_actions"], ascending=[True, False]).reset_index(drop=True)


def defensive_role_for(name, team=None):
    """(defensive role, basis) for one player -- the ONE source every roster table uses."""
    t = globals().get("defensive_roles_table")
    if not isinstance(t, pd.DataFrame) or t.empty:
        return None, None
    rows = t[t["player"].map(_dr_norm) == _dr_norm(name)]
    if rows.empty:
        return None, None
    if team is not None and len(rows) > 1:
        tq = _dr_norm(team)
        own = rows[rows["team"].map(lambda x: bool(tq) and (tq in _dr_norm(x) or _dr_norm(x) in tq))]
        if not own.empty:
            rows = own
    r = rows.sort_values("credited_actions", ascending=False).iloc[0]
    return r["defensive_role"], r["role_basis"]


def _dr_attach(df, name_col="name", team_col=None):
    if not isinstance(df, pd.DataFrame) or df.empty or name_col not in df.columns:
        return
    pairs = [defensive_role_for(r[name_col], r[team_col] if team_col and team_col in df.columns else None)
             for _, r in df.iterrows()]
    df["defensive_role"] = [p[0] for p in pairs]
    df["defensive_role_basis"] = [p[1] for p in pairs]


if RUN_DEFENSIVE_ROLES:
    try:
        defensive_roles_table = defensive_roles()
        _dr_attach(globals().get("player_profiles"), "name", "opponent")
        _dr_attach(globals().get("all_rosters"), "name", "opponent")
        _dr_attach(globals().get("live_rosters"), "name", "team")
        _t = defensive_roles_table
        print(f"Defensive roles: {len(_t)} player(s) -- " + ", ".join(
            f"{v} from {k}" for k, v in _t["role_basis"].str.replace(r" \(low sample\)", "", regex=True).value_counts().items())
              + f" ({int(_t['role_basis'].str.contains('low sample').sum())} marked low sample)")
        print("  roles: " + "; ".join(f"{k} {v}" for k, v in _t["defensive_role"].value_counts().items()))
    except Exception as _e:
        defensive_roles_table = pd.DataFrame()
        print(f"Defensive roles skipped: {type(_e).__name__}: {_e}")
