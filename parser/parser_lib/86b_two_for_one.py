# 86b_two_for_one.py -- code for the notebook section "Two-for-one: end-of-half possessions, and how to use them against the upcoming opponent"
# Runs inside the notebook via run_section("86b_two_for_one"); its settings are in that notebook cell.

# --- Two-for-one: end-of-half possessions --------------------------------------------------------------------
# CONFIRMED CHANGE (requested): the Previous Games play-by-play gets a Situation filter that includes "Two for
# one", and the Game Plan tab / scouting brief get a section on using the 2-for-1 against the upcoming opponent.
#
# What a 2-for-1 is (NCAA men's rules, which Division III plays: 30-second shot clock, 20 after an offensive
# rebound, two 20-minute halves): a team that gets the ball with a little more than one shot clock left in a
# half can shoot EARLY on purpose. The other team then has to shoot before the half ends, and the first team gets
# the ball back for the last shot -- two possessions to one. Take the full shot clock instead and the other team
# gets the last shot.
#
# Built from every game's play-by-play (ours, and the upcoming opponent's games before they play us), not just
# tagged clips, so the sample is every half on file. There is no possession column in the play-by-play, so
# possessions are rebuilt here the same way the shot-clock estimate in the play-calls cell does it: a possession
# changes on a made basket (after any and-one free throw), a turnover, a defensive rebound, or the last free
# throw of a trip; an offensive rebound keeps it. Each possession starts when the previous one ended.
#
# Settings (notebook cell):
#   TWO_FOR_ONE_WINDOW = (35, 60)  the chance: a possession that STARTS with this many seconds left (low, high)
#                                  in a half or overtime. The FIRST such possession of the half is the chance.
#   TWO_FOR_ONE_SHOOT_BY = 33      "went for it" = the first shot, free-throw trip or turnover came with at least
#                                  this many seconds left (the other team's 30 then runs out before the half does)
#   TWO_FOR_ONE_MIN_USES = 2       a play call / play type needs this many end-of-half possessions to be listed
#   TWO_FOR_ONE_END_OF_GAME = "trailing"   the end of the 1st half always counts. The end of the 2nd half / OT
#                                  counts only for a team that is behind by 1-TWO_FOR_ONE_MAX_DEFICIT (12) -- ahead
#                                  or tied, a team holds for the last shot, which isn't a 2-for-1. "always"/"never".
#
# Writes (all real data, never sample):
#   uww_pbp_situations          one row per play-by-play event of OUR games: its possession's situation (coach tag,
#                               else Synergy's play type -> Half court / Transition) and its 2-for-1 role if any.
#                               The Previous Games Situation filter reads this.
#   uww_two_for_one_possessions every possession of every 2-for-1 sequence, ours and the upcoming opponent's games
#   uww_two_for_one_plan        the headline reads for the upcoming opponent (Game Plan tab + brief)
#   uww_two_for_one_calls       what worked: play calls (tagged) and Synergy play types, quick shot vs last shot
#   uww_two_for_one_attack      who to attack: their players on the floor at the end of halves, foul rate, role
TWO_FOR_ONE_WINDOW = tuple(globals().get("TWO_FOR_ONE_WINDOW", (35, 60)))
TWO_FOR_ONE_SHOOT_BY = float(globals().get("TWO_FOR_ONE_SHOOT_BY", 33))
TWO_FOR_ONE_MIN_USES = int(globals().get("TWO_FOR_ONE_MIN_USES", 2))
_TF_HEADLINE_USES = max(3, TWO_FOR_ONE_MIN_USES)   # a "best call" headline needs at least this many
TWO_FOR_ONE_END_OF_GAME = globals().get("TWO_FOR_ONE_END_OF_GAME", "trailing")
TWO_FOR_ONE_MAX_DEFICIT = float(globals().get("TWO_FOR_ONE_MAX_DEFICIT", 12))
_TF_UWW = "UW-Whitewater"
_TF_SHORT = globals().get("upcoming_opponent_short")
_TF_POSS = (str(_TF_SHORT) + ("'" if str(_TF_SHORT).endswith("s") else "'s")) if _TF_SHORT else ""   # "Raiders'"
_TF_KEYS = list(globals().get("GAME_KEYS", ["opponent", "game_date"]))
_TF_BONUS, _TF_DOUBLE_BONUS = 7, 10       # NCAA men's: 1-and-1 on the 7th team foul of a half, two shots on the 10th

_TF_SHOT = {"made_shot", "missed_shot"}
_TF_FT = {"free_throw_made", "free_throw_missed"}
_TF_OWNER = {"made_shot", "missed_shot", "free_throw_made", "free_throw_missed", "turnover", "assist",
             "rebound_offensive", "team_deadball_rebound_offensive"}
_TF_DEF_REB = {"rebound_defensive", "team_deadball_rebound_defensive"}
# Synergy play types: which situation a possession started in when the coaches didn't tag one
_TF_HALF_COURT_TYPES = {"P&R Ball Handler", "P&R Roll Man", "Spot-Up", "Post-Up", "ISO", "Off Screen", "Cut",
                        "Hand Off", "Offensive Rebound"}
_TF_NOT_A_TYPE = {"Non Possession", "No Play Type", ""}


def _tf_load(name):
    try:
        return pd.read_csv(os.path.join(APP_DATA_DIR, f"{name}.csv"), low_memory=False)
    except Exception:
        return pd.DataFrame()


def _tf_is_uww(team):
    return "whitewater" in str(team).lower()


def _tf_ft_parts(row):
    n, t = row.get("ft_num"), row.get("ft_total")
    if pd.notna(n) and pd.notna(t):
        return int(n), int(t)
    m = re.search(r"\((\d+) of (\d+)\)", str(row.get("raw_text") or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (1, 1)


def _tf_play_type(desc):
    parts = [p.strip() for p in str(desc).split(">")] if isinstance(desc, str) else []
    return parts[1] if len(parts) > 1 else ""


def _tf_clock(sec):
    if sec is None or pd.isna(sec):
        return ""
    sec = int(round(float(sec)))
    return f"{sec // 60}:{sec % 60:02d}"


def tf_possessions(events, lineup_cols=()):
    """Rebuild possessions from play-by-play. Returns (possessions DataFrame, {event index -> possession id}).

    One row per possession: game keys, period, team, start / first_action / end clock (seconds left), points,
    result, finisher, Synergy play type, coach-tagged play call / situation, and the lineups on the first event.
    """
    rows, owner_of = [], {}
    if events is None or events.empty or not {"event_type", "team", "period", "event_order"} <= set(events.columns):
        return pd.DataFrame(), owner_of
    ev = events[events["period"].notna() & events["event_type"].notna()].copy()
    ev["time_remaining_seconds"] = pd.to_numeric(ev.get("time_remaining_seconds"), errors="coerce")
    ev = ev[ev["time_remaining_seconds"].notna()]
    _periods = []
    for gkeys, gg in ev.groupby(_TF_KEYS, dropna=False, sort=False):
        score = {}                                    # running score, carried across periods
        gkeys = gkeys if isinstance(gkeys, tuple) else (gkeys,)
        for period, grp in gg.sort_values("event_order").groupby("period", sort=False):
            _periods.append((gkeys + (period,), grp, score))
    for keys, grp, score in _periods:
        period = keys[-1]
        start_clock = 300.0 if "OT" in str(period).upper() else 1200.0
        cur, last_end, pending, fouls, fouls_at_end = None, start_clock, [], {}, {}
        for idx, r in grp.iterrows():
            et, team, clock = r["event_type"], r.get("team"), float(r["time_remaining_seconds"])
            if et == "foul" and isinstance(team, str) and "technical" not in str(r.get("raw_text")).lower():
                fouls[team] = fouls.get(team, 0) + 1
            owner = team if (et in _TF_OWNER or et in _TF_DEF_REB) and isinstance(team, str) else None
            if owner is not None:
                new = cur is None or cur["ended"] or cur["team"] != owner
                if (cur is not None and cur["ended"] and cur["team"] == owner and clock == cur["end"]
                        and (et in _TF_FT or et == "assist" or et.startswith("team_deadball"))):
                    new = False                       # and-one free throw / the assist on the basket: same trip
                    if et in _TF_FT:
                        cur["ended"] = False
                if new:
                    if cur is not None and not cur["ended"]:
                        cur.update(ended=True, end=clock, end_kind=cur.get("end_kind") or "miss")
                    start = clock if et in _TF_DEF_REB else last_end
                    fb = dict(fouls) if et in _TF_DEF_REB else dict(fouls_at_end)   # team fouls when it started
                    cur = {"pid": len(rows), "keys": keys, "period": period, "team": owner, "start": start,
                           "first_action": None, "end": None, "end_kind": None, "ended": False, "points": 0,
                           "fga": 0, "fg3a": 0, "fta": 0, "to": 0, "oreb": 0, "finisher": None, "first_shooter": None,
                           "types": [], "play_call": None, "play_situation": None, "events": [],
                           "first_idx": idx, "fouls_before": fb, "score_before": dict(score)}
                    for c in lineup_cols:
                        cur[c] = r.get(c)
                    rows.append(cur)
                    for p in pending:
                        owner_of[p] = cur["pid"]
                    pending = []
            if cur is None or (cur["ended"] and owner is None and clock < cur["end"]):
                pending.append(idx)               # nobody has the ball on record yet -- goes to the next possession
                continue
            owner_of[idx] = cur["pid"]
            cur["events"].append(idx)
            t = _tf_play_type(r.get("video_description"))
            if t and t not in _TF_NOT_A_TYPE:
                cur["types"].append(t)
            for c in ("play_call", "play_situation"):
                if cur[c] is None and isinstance(r.get(c), str) and r.get(c).strip():
                    cur[c] = r.get(c).strip()
            if owner is None or owner != cur["team"]:
                continue
            if et in _TF_SHOT or et in _TF_FT or et == "turnover":
                if cur["first_action"] is None:
                    cur["first_action"] = clock
                    cur["first_shooter"] = r.get("player")
                cur["finisher"] = r.get("player")
            if et in _TF_SHOT:
                cur["fga"] += 1
                pts = int(pd.to_numeric(r.get("shot_type"), errors="coerce")) if pd.notna(
                    pd.to_numeric(r.get("shot_type"), errors="coerce")) else 2
                cur["fg3a"] += int(pts == 3)
                if et == "made_shot":
                    cur["points"] += pts
                    score[owner] = score.get(owner, 0) + pts
                    cur.update(ended=True, end=clock, end_kind=f"Make {pts}")
                    last_end, fouls_at_end = clock, dict(fouls)
            elif et in _TF_FT:
                cur["fta"] += 1
                n, tot = _tf_ft_parts(r)
                if et == "free_throw_made":
                    cur["points"] += 1
                    score[owner] = score.get(owner, 0) + 1
                if n >= tot:
                    if et == "free_throw_made":
                        cur.update(ended=True, end=clock,
                                   end_kind=("And-1" if str(cur.get("end_kind") or "").startswith("Make")
                                             else "Free throws"))
                        last_end, fouls_at_end = clock, dict(fouls)
                    elif not str(cur.get("end_kind") or "").startswith("Make"):
                        cur["end_kind"] = "Free throws"   # missed last free throw: the rebound decides
            elif et == "turnover":
                cur["to"] += 1
                cur.update(ended=True, end=clock, end_kind="Turnover")
                last_end, fouls_at_end = clock, dict(fouls)
            elif et == "rebound_offensive":
                cur["oreb"] += 1
        if cur is not None and not cur["ended"]:
            cur.update(ended=True, end=0.0, end_kind=cur.get("end_kind") or "Clock ran out")
    out = []
    for p in rows:
        k = p["keys"]
        rec = {c: k[i] for i, c in enumerate(_TF_KEYS)}
        result = p["end_kind"] or ""
        if result == "miss":
            result = "Miss"
        rec.update(pid=p["pid"], period=p["period"], team=p["team"], start_s=p["start"],
                   first_action_s=p["first_action"], end_s=p["end"], points=p["points"], result=result,
                   fga=p["fga"], fg3a=p["fg3a"], fta=p["fta"], turnovers=p["to"], oreb=p["oreb"],
                   finisher=p["finisher"], first_shooter=p["first_shooter"],
                   play_type=(p["types"][0] if p["types"] else None),
                   all_types=" / ".join(dict.fromkeys(p["types"])) or None,
                   play_call=p["play_call"], play_situation=p["play_situation"],
                   n_events=len(p["events"]), first_event_index=p["first_idx"],
                   fouls_before=p["fouls_before"],
                   margin_before=(p["score_before"].get(p["team"], 0)
                                  - max([v for t_, v in p["score_before"].items() if t_ != p["team"]] or [0])))
        for c in lineup_cols:
            rec[c] = p.get(c)
        out.append(rec)
    return pd.DataFrame(out), owner_of


def _tf_situation(p):
    """A possession's situation: the coaches' tag when there is one, else Synergy's play type on its first
    clip -- Transition, or Half court for every half-court play type. None when neither says."""
    if isinstance(p.get("play_situation"), str) and p["play_situation"].strip():
        s = p["play_situation"].strip()
        return {"half court": "Half court", "transition": "Transition", "offensive rebound": "Offensive rebound"
                }.get(s.lower(), s), "coach tag"
    t = p.get("play_type")
    if t == "Transition":
        return "Transition", "Synergy play type"
    if t in _TF_HALF_COURT_TYPES:
        return "Half court", "Synergy play type"
    return None, None


def _tf_end_of_game_counts(margin):
    """End of the 2nd half / overtime is only a 2-for-1 chance for a team that needs possessions: trailing, and
    not by so much the game is over. Leading or tied, a team holds for the last shot instead -- see
    TWO_FOR_ONE_END_OF_GAME."""
    mode = str(TWO_FOR_ONE_END_OF_GAME).lower()
    if mode == "always":
        return True
    if mode == "never" or margin is None or pd.isna(margin):
        return False
    return -TWO_FOR_ONE_MAX_DEFICIT <= float(margin) < 0


def tf_sequences(poss):
    """Find each half's 2-for-1 sequence. Adds seq_* columns to the possessions that are part of one."""
    if poss.empty:
        return poss.assign(seq_id=pd.Series(dtype=object))
    poss = poss.copy()
    for c in ("seq_id", "seq_owner", "seq_role", "seq_went", "seq_got", "seq_owner_pts", "seq_other_pts",
              "seq_owner_poss", "seq_other_poss"):
        poss[c] = None
    lo, hi = min(TWO_FOR_ONE_WINDOW), max(TWO_FOR_ONE_WINDOW)
    for keys, g in poss.groupby(_TF_KEYS + ["period"], dropna=False, sort=False):
        # a "possession" that starts with 0 seconds left (a rebound at the horn) isn't one
        g = g[pd.to_numeric(g["start_s"], errors="coerce") >= 1].sort_values("pid")
        chance = g[(g["start_s"] >= lo) & (g["start_s"] <= hi)]
        if chance.empty:
            continue
        first = chance.index[0]
        seq = g.loc[first:]
        owner = seq.iloc[0]["team"]
        margin = seq.iloc[0].get("margin_before")
        if str(keys[-1]).upper() != "H1" and not _tf_end_of_game_counts(margin):
            continue                      # end of the game, and the team with the ball isn't chasing it
        mine = seq["team"] == owner
        fa = seq.iloc[0]["first_action_s"]
        went = bool(pd.notna(fa) and float(fa) >= TWO_FOR_ONE_SHOOT_BY)
        # got it = a second possession of our own that was a real shot (3+ seconds), and more trips than them
        real = mine & ((seq.index == seq.index[0]) | (pd.to_numeric(seq["start_s"], errors="coerce") >= 3))
        got = bool(real.sum() >= 2 and real.sum() > (~mine).sum())
        sid = "|".join(str(k) for k in keys)
        last = seq.index[-1]
        for i, (ix, r) in enumerate(seq.iterrows()):
            if i == 0:
                role = "2-for-1 chance"
            elif ix == last:
                role = "Last shot"
            elif r["team"] == owner:
                role = "Second shot"
            else:
                role = "Answer"
            poss.loc[ix, ["seq_id", "seq_owner", "seq_role", "seq_went", "seq_got"]] = [sid, owner, role, went, got]
        poss.loc[seq.index, "seq_owner_pts"] = int(seq.loc[mine, "points"].sum())
        poss.loc[seq.index, "seq_other_pts"] = int(seq.loc[~mine, "points"].sum())
        poss.loc[seq.index, "seq_owner_poss"] = int(mine.sum())
        poss.loc[seq.index, "seq_other_poss"] = int((~mine).sum())
    return poss


# ---- build: our games, and the upcoming opponent's games ---------------------------------------------------
_tf_uww_ev = globals().get("pbp_events")
if not isinstance(_tf_uww_ev, pd.DataFrame) or _tf_uww_ev.empty:
    _tf_uww_ev = _tf_load("uww_pbp_events")
_tf_opp_ev = globals().get("pbp_events_upcoming")
if not isinstance(_tf_opp_ev, pd.DataFrame) or _tf_opp_ev.empty:
    _tf_opp_ev = _tf_load("uww_opponent_prior_games_pbp")

# own copies with a clean index: event index -> possession needs one row per label
_tf_uww_ev = _tf_uww_ev.reset_index(drop=True)
_tf_opp_ev = _tf_opp_ev.reset_index(drop=True)
_tf_uww_poss, _tf_uww_owner = tf_possessions(_tf_uww_ev, [c for c in ("uww_lineup", "opp_lineup")
                                                          if c in _tf_uww_ev.columns])
_tf_opp_poss, _tf_opp_owner = tf_possessions(_tf_opp_ev, [c for c in ("self_lineup", "their_lineup")
                                                          if c in _tf_opp_ev.columns])
_tf_uww_poss = tf_sequences(_tf_uww_poss)
_tf_opp_poss = tf_sequences(_tf_opp_poss)
for _df in (_tf_uww_poss, _tf_opp_poss):
    if not _df.empty:
        _sit = _df.apply(_tf_situation, axis=1)
        _df["situation"] = [s[0] for s in _sit]
        _df["situation_source"] = [s[1] for s in _sit]

# ---- per-event table for the Previous Games Situation filter (our games) ------------------------------------
_tf_ev_rows = []
if not _tf_uww_poss.empty:
    _tf_by_pid = _tf_uww_poss.set_index("pid")
    for _ix, _pid in _tf_uww_owner.items():
        _p = _tf_by_pid.loc[_pid]
        _r = _tf_uww_ev.loc[_ix]
        _role = _p.get("seq_role")
        _tf_ev_rows.append({
            **{c: _r.get(c) for c in _TF_KEYS}, "event_order": _r.get("event_order"),
            "possession_team": _p["team"], "situation": _p.get("situation"),
            "situation_source": _p.get("situation_source"),
            "two_for_one": (f"{_role} -- {'UWW' if _tf_is_uww(_p['team']) else 'them'}"
                            if isinstance(_role, str) else None),
            "two_for_one_team": _p.get("seq_owner") if isinstance(_role, str) else None,
            "two_for_one_got": _p.get("seq_got") if isinstance(_role, str) else None,
            "possession_start": _tf_clock(_p["start_s"]),
        })
pbp_situations = pd.DataFrame(_tf_ev_rows)
pbp_situations.to_csv(os.path.join(APP_DATA_DIR, "uww_pbp_situations.csv"), index=False)

# ---- every 2-for-1 possession, both sides --------------------------------------------------------------------
_tf_cols = ["side", "scouted_opponent"] + _TF_KEYS + [
    "period", "seq_id", "seq_owner", "seq_role", "team", "start", "first_action", "end", "points", "result",
    "first_shooter", "finisher", "play_type", "all_types", "play_call", "situation", "fga", "fg3a", "fta",
    "turnovers", "oreb", "defense_team_fouls", "seq_went", "seq_got", "seq_owner_pts", "seq_other_pts",
    "offense_lineup", "defense_lineup"]


def _tf_export(poss, side, events):
    if poss.empty or "seq_id" not in poss.columns:
        return pd.DataFrame(columns=_tf_cols)
    s = poss[poss["seq_id"].notna()].copy()
    if s.empty:
        return pd.DataFrame(columns=_tf_cols)
    s["side"] = side
    s["scouted_opponent"] = _TF_SHORT
    s["start"] = s["start_s"].map(_tf_clock)
    s["first_action"] = s["first_action_s"].map(_tf_clock)
    s["end"] = s["end_s"].map(_tf_clock)

    def _other(r):
        # the defending team in this game: whichever team in the game isn't on offense
        teams = events.loc[(events[_TF_KEYS[0]] == r[_TF_KEYS[0]]) & (events[_TF_KEYS[1]] == r[_TF_KEYS[1]]),
                           "team"].dropna().unique()
        others = [t for t in teams if t != r["team"]]
        return others[0] if others else None
    s["defense_team"] = s.apply(_other, axis=1)
    s["defense_team_fouls"] = s.apply(lambda r: (r["fouls_before"] or {}).get(r["defense_team"], 0)
                                      if isinstance(r["fouls_before"], dict) else 0, axis=1)
    if side == "UWW":
        s["offense_lineup"] = s.apply(lambda r: r.get("uww_lineup") if _tf_is_uww(r["team"]) else r.get("opp_lineup"),
                                      axis=1)
        s["defense_lineup"] = s.apply(lambda r: r.get("opp_lineup") if _tf_is_uww(r["team"]) else r.get("uww_lineup"),
                                      axis=1)
    else:
        s["offense_lineup"] = s.apply(lambda r: r.get("self_lineup") if r["team"] == _TF_SHORT else r.get("their_lineup"),
                                      axis=1)
        s["defense_lineup"] = s.apply(lambda r: r.get("their_lineup") if r["team"] == _TF_SHORT else r.get("self_lineup"),
                                      axis=1)
    for c in _tf_cols:
        if c not in s.columns:
            s[c] = None
    return s[_tf_cols + ["start_s", "first_action_s", "end_s"]]


two_for_one_possessions = pd.concat([_tf_export(_tf_uww_poss, "UWW", _tf_uww_ev),
                                     _tf_export(_tf_opp_poss, "Opponent", _tf_opp_ev)], ignore_index=True)
two_for_one_possessions.to_csv(os.path.join(APP_DATA_DIR, "uww_two_for_one_possessions.csv"), index=False)


# ---- the reads for the upcoming opponent -------------------------------------------------------------------
def _tf_chances(p, owner_pred):
    """One row per 2-for-1 chance (the first possession of each sequence) whose owner passes owner_pred."""
    if p.empty:
        return p
    c = p[(p["seq_role"] == "2-for-1 chance") & p["seq_owner"].map(owner_pred)]
    return c


def _tf_rate(n, d):
    return f"{n} of {d}" + (f" ({round(100 * n / d)}%)" if d else "")


def _tf_net(c):
    return (pd.to_numeric(c["seq_owner_pts"], errors="coerce") - pd.to_numeric(c["seq_other_pts"], errors="coerce"))


def _tf_ppp(df):
    n = len(df)
    return round(float(pd.to_numeric(df["points"], errors="coerce").fillna(0).sum()) / n, 2) if n else None


_tfp = two_for_one_possessions
_tf_u = _tfp[_tfp["side"] == "UWW"]
_tf_o = _tfp[_tfp["side"] == "Opponent"]
_tf_plan, _tf_calls, _tf_attack = [], [], []


def _tf_plan_row(part, headline, detail, n):
    _tf_plan.append([_TF_SHORT, part, len(_tf_plan) + 1, headline, detail, int(n)])


# 1. Do we go for it, and does it pay? (our games)
_c_us = _tf_chances(_tf_u, _tf_is_uww)
if len(_c_us):
    _went = _c_us["seq_went"].astype(bool)
    _got = _c_us["seq_got"].astype(bool)
    _net = _tf_net(_c_us)
    _w_net = _net[_went].mean() if _went.any() else None
    _n_net = _net[~_went].mean() if (~_went).any() else None
    _tf_plan_row(
        "Our 2-for-1 chances",
        f"Get a shot up by 0:{int(TWO_FOR_ONE_SHOOT_BY):02d}: we went for it in {_tf_rate(int(_went.sum()), len(_c_us))} "
        f"of our chances, and got two shots to one in {int((_got & _went).sum())} of those",
        "Net points per chance (our points minus theirs from that possession to the horn): "
        + (f"{_w_net:+.2f} when we went for it" if _w_net is not None else "never went for it")
        + (f", {_n_net:+.2f} when we didn't" if _n_net is not None else "") + ".", len(_c_us))

# 2. Their late-half defense: what other teams did with a 2-for-1 chance against them
if _TF_SHORT:
    _c_vs = _tf_chances(_tf_o, lambda t: t != _TF_SHORT)
    _seq_vs = _tf_o[_tf_o["seq_id"].isin(_c_vs["seq_id"])] if len(_c_vs) else _tf_o.iloc[0:0]
    _vs_off = _seq_vs[_seq_vs["team"] != _TF_SHORT]
    if len(_c_vs):
        _went = _c_vs["seq_went"].astype(bool)
        _got = _c_vs["seq_got"].astype(bool)
        _all_def = _tf_opp_poss[_tf_opp_poss["team"] != _TF_SHORT] if not _tf_opp_poss.empty else pd.DataFrame()
        _base = _tf_ppp(_all_def) if len(_all_def) else None
        _spot = _tf_ppp(_tf_u) if len(_tf_u) else None      # every team, same spot, in our games
        _tf_plan_row(
            "Their late-half defense",
            f"Teams with a 2-for-1 chance against {_TF_SHORT} scored {_tf_ppp(_vs_off):.2f} points per possession "
            f"from there to the horn"
            + (f" (their defense all game: {_base:.2f}; every team in this spot in our games: {_spot:.2f})"
               if _base is not None and _spot is not None else ""),
            f"{_tf_rate(int(_went.sum()), len(_c_vs))} went for it; {int(_got.sum())} got two shots to one. "
            f"Turnovers on {int((pd.to_numeric(_vs_off['turnovers'], errors='coerce') > 0).sum())} of "
            f"{len(_vs_off)} of those possessions.", len(_vs_off))
        # bonus: how many fouls they carry into the last minute
        _f = pd.to_numeric(_c_vs["defense_team_fouls"], errors="coerce").dropna()
        _all_halves = _tf_opp_poss.copy() if not _tf_opp_poss.empty else pd.DataFrame()
        if len(_f):
            _b, _bb = int((_f >= _TF_BONUS).sum()), int((_f >= _TF_DOUBLE_BONUS).sum())
            _tf_plan_row(
                "Their late-half defense",
                ("Attack the rim -- " if _b >= max(1, len(_f) / 2) else "")
                + f"{_TF_SHORT} carried {_f.mean():.1f} team fouls into the 2-for-1 window on average: in the bonus "
                f"{_tf_rate(_b, len(_f))}, double bonus {_tf_rate(_bb, len(_f))}",
                f"NCAA men's: one-and-one on the {_TF_BONUS}th team foul of a half, two shots on the "
                f"{_TF_DOUBLE_BONUS}th (2nd-half fouls carry into overtime). Counted at the start of the 2-for-1 "
                f"possession.", len(_f))
    # 3. Their own 2-for-1 offense
    _c_them = _tf_chances(_tf_o, lambda t: t == _TF_SHORT)
    if len(_c_them):
        _went = _c_them["seq_went"].astype(bool)
        _got = _c_them["seq_got"].astype(bool)
        _seq_t = _tf_o[_tf_o["seq_id"].isin(_c_them["seq_id"])]
        _quick = _seq_t[(_seq_t["seq_role"] == "2-for-1 chance")]
        _shooters = _quick["first_shooter"].dropna().value_counts()
        _last_t = _tf_o[(_tf_o["seq_role"] == "Last shot") & (_tf_o["team"] == _TF_SHORT)]
        _last_sh = _last_t["finisher"].dropna().value_counts()
        _tf_plan_row(
            "When they have the chance",
            f"{_TF_SHORT} went for the 2-for-1 in {_tf_rate(int(_went.sum()), len(_c_them))} of their chances "
            f"and got two shots to one in {int(_got.sum())}"
            + (f" -- the quick shot most often goes to {_shooters.index[0]} ({int(_shooters.iloc[0])}x)"
               if len(_shooters) and _shooters.iloc[0] >= TWO_FOR_ONE_MIN_USES else ""),
            f"Net {_tf_net(_c_them).mean():+.2f} points per chance for them. "
            + (f"Their last shot of a half: {', '.join(f'{n} ({int(c)}x)' for n, c in _last_sh.head(3).items())}."
               if len(_last_sh) else ""), len(_c_them))

# 4. What worked: play calls (tagged) and Synergy play types
_TF_MOMENTS = {"2-for-1 chance": "Quick shot (2-for-1 chance)", "Second shot": "Last shot", "Last shot": "Last shot",
               "Answer": "Answering a 2-for-1"}


def _tf_calls_for(df, who):
    if df.empty:
        return
    d = df.assign(moment=df["seq_role"].map(_TF_MOMENTS))
    for kind, col in (("Play call", "play_call"), ("Synergy play type", "play_type")):
        dd = d[d[col].notna() & (d[col].astype(str).str.strip() != "")]
        for (moment, name), g in dd.groupby(["moment", col]):
            if len(g) < TWO_FOR_ONE_MIN_USES:
                continue
            pts = pd.to_numeric(g["points"], errors="coerce").fillna(0)
            top = g["finisher"].dropna().value_counts()
            _tf_calls.append([_TF_SHORT, who, moment, kind, name, len(g), int(pts.sum()), round(float(pts.mean()), 2),
                              int((pts > 0).sum()), (top.index[0] if len(top) else None),
                              f"{int((pd.to_numeric(g['turnovers'], errors='coerce') > 0).sum())} turnover(s)"])


_tf_calls_for(_tf_u[_tf_u["team"].map(_tf_is_uww)], "UWW offense")
if _TF_SHORT:
    _tf_calls_for(_tf_o[_tf_o["team"] == _TF_SHORT], f"{_TF_SHORT} offense")
    _tf_calls_for(_tf_o[_tf_o["team"] != _TF_SHORT], f"Against {_TF_POSS} defense")

two_for_one_calls = pd.DataFrame(_tf_calls, columns=[
    "opponent", "who", "moment", "kind", "name", "uses", "points", "ppp", "scored", "top_player", "note"])
if not two_for_one_calls.empty:
    two_for_one_calls = two_for_one_calls.sort_values(["who", "moment", "ppp", "uses"],
                                                      ascending=[True, True, False, False])

# best lines from the calls table, into the plan
for _who, _part in (("UWW offense", "What to run"), (f"Against {_TF_POSS} defense", "What beat them late")):
    _cc = two_for_one_calls[two_for_one_calls["who"] == _who] if not two_for_one_calls.empty else pd.DataFrame()
    for _moment in ("Quick shot (2-for-1 chance)", "Last shot"):
        _m = _cc[(_cc["moment"] == _moment) & (_cc["uses"] >= _TF_HEADLINE_USES)] if len(_cc) else _cc
        if len(_m):
            _best = _m.sort_values(["ppp", "uses"], ascending=False).iloc[0]
            _good = float(_best["ppp"]) >= 1.0
            _tf_plan_row(_part, (f"{_moment}: {_best['name']} -- {_best['ppp']:.2f} PPP on {int(_best['uses'])} "
                                 f"possession(s) ({_best['kind'].lower()})") if _good else
                         (f"{_moment}: nothing has scored well yet -- best is {_best['name']} at "
                          f"{_best['ppp']:.2f} PPP on {int(_best['uses'])} ({_best['kind'].lower()})"),
                         f"Scored on {int(_best['scored'])} of {int(_best['uses'])}"
                         + (f", most often finished by {_best['top_player']}" if isinstance(_best['top_player'], str) else "")
                         + ". Full list in the 2-for-1 table.", int(_best["uses"]))

# 5. Who to attack: their players on the floor at the end of halves, by foul rate and defensive role
if _TF_SHORT:
    _box = _tf_load("uww_opponent_prior_games_box_score")
    _roles = _tf_load("uww_defensive_roles")
    _late_def = _tf_opp_poss[(_tf_opp_poss["team"] != _TF_SHORT) & (_tf_opp_poss["start_s"] <= max(TWO_FOR_ONE_WINDOW))
                             ] if not _tf_opp_poss.empty else pd.DataFrame()
    _share = {}
    if len(_late_def) and "self_lineup" in _late_def.columns and _late_def["self_lineup"].notna().any():
        for _lu in _late_def["self_lineup"].dropna():
            for _n in str(_lu).split(","):
                _share[_n.strip()] = _share.get(_n.strip(), 0) + 1
        _share_basis = f"on the floor for that share of their {len(_late_def)} end-of-half defensive possessions"
        _den = len(_late_def)
    else:
        _share_basis = "share of minutes (no per-possession lineups on this run)"
        _den = None
    # fouls they committed while defending a 2-for-1 sequence (not end-of-game fouling on purpose -- those
    # sequences aren't counted, see TWO_FOR_ONE_END_OF_GAME)
    _late_fouls = {}
    if not _tf_opp_ev.empty and not _tf_opp_poss.empty:
        _seq_def = set(_tf_opp_poss.loc[_tf_opp_poss["seq_id"].notna() & (_tf_opp_poss["team"] != _TF_SHORT), "pid"])
        for _ix, _pid in _tf_opp_owner.items():
            if _pid in _seq_def:
                _e = _tf_opp_ev.loc[_ix]
                if _e.get("event_type") == "foul" and _e.get("team") == _TF_SHORT and isinstance(_e.get("player"), str):
                    _late_fouls[_e["player"]] = _late_fouls.get(_e["player"], 0) + 1
    if not _box.empty and {"team", "player", "PF", "MIN"} <= set(_box.columns):
        _b = _box[_box["team"].astype(str) == str(_TF_SHORT)].copy()
        for c in ("PF", "MIN"):
            _b[c] = pd.to_numeric(_b[c], errors="coerce").fillna(0)
        _agg = _b.groupby("player").agg(PF=("PF", "sum"), MIN=("MIN", "sum"), games=("game_date", "nunique"))
        _tot_min = float(_agg["MIN"].sum()) or 1.0
        _role_of = {}
        if not _roles.empty and {"team", "player", "defensive_role"} <= set(_roles.columns):
            _r = _roles[_roles["team"].astype(str) == str(_TF_SHORT)]
            _role_of = {str(p).strip().lower(): (r, w) for p, r, w in zip(_r["player"], _r["defensive_role"],
                                                                          _r.get("why", pd.Series(index=_r.index)))}
        _weak_roles = {"Low Activity"}
        _strong_roles = {"Point of Attack", "Wing Stopper", "Anchor Big"}
        _cands = []
        for _p, r in _agg.iterrows():
            if r["MIN"] < 40:
                continue                     # a couple of garbage-time stints isn't a late-half defender
            _sh = (_share.get(_p, 0) / _den) if _den else (r["MIN"] / (_tot_min / 5))
            if _sh < 0.25:
                continue                     # rarely on the floor when a half is ending
            _f40 = 40 * r["PF"] / r["MIN"] if r["MIN"] else 0
            _role, _why = _role_of.get(str(_p).strip().lower(), (None, None))
            # foul-prone + weak defensive role, weighted by how often he's out there late
            _score = (_f40 + (1.5 if _role in _weak_roles else 0) - (1.0 if _role in _strong_roles else 0)) \
                * min(1.0, _sh / 0.6) + 0.5 * _late_fouls.get(_p, 0)
            _cands.append([_p, _sh, _f40, _late_fouls.get(_p, 0), _role, _score])
        _cands.sort(key=lambda x: -x[5])
        for i, (_p, _sh, _f40, _lfc, _role, _score) in enumerate(_cands):
            _verdict = "Attack" if i < 3 else ("Avoid" if _role in _strong_roles and i >= len(_cands) - 2 else "")
            _why_txt = f"{_f40:.1f} fouls per 40 min"
            if _lfc:
                _why_txt += f", {_lfc} foul(s) defending 2-for-1 possessions"
            if _role:
                _why_txt += f"; defensive role {_role}"
            _tf_attack.append([_TF_SHORT, _p, _verdict, round(100 * min(_sh, 1.0)), round(_f40, 1), int(_lfc),
                               _role, _why_txt, _share_basis])
        if _cands:
            _top = [c for c in _cands[:3]]
            _tf_plan_row("Who to attack",
                         "Attack " + ", ".join(f"{c[0]} ({c[2]:.1f} fouls/40" + (f", {c[3]} in 2-for-1 spots" if c[3] else "")
                                               + ")" for c in _top)
                         + " -- on the floor late in halves and the most foul-prone",
                         "Drive at them for the quick 2-for-1 shot: a foul late in the half is free throws "
                         "(they're often in the bonus) and a third foul on a starter changes their second half. "
                         f"Basis: {_share_basis}; foul rate from their box scores; role from the defensive-roles "
                         "table.", len(_late_def) if len(_late_def) else len(_cands))

two_for_one_plan = pd.DataFrame(_tf_plan, columns=["opponent", "part", "order", "headline", "detail", "sample_n"])
two_for_one_attack = pd.DataFrame(_tf_attack, columns=["opponent", "player", "verdict", "late_share_pct",
                                                       "fouls_per_40", "late_fouls", "defensive_role", "why", "basis"])
for _name, _df in (("uww_two_for_one_plan", two_for_one_plan), ("uww_two_for_one_calls", two_for_one_calls),
                   ("uww_two_for_one_attack", two_for_one_attack)):
    _df.to_csv(os.path.join(APP_DATA_DIR, f"{_name}.csv"), index=False)

# ---- what the run found ---------------------------------------------------------------------------------------
_tf_nu = int((_tf_u["seq_role"] == "2-for-1 chance").sum()) if len(_tf_u) else 0
_tf_no = int((_tf_o["seq_role"] == "2-for-1 chance").sum()) if len(_tf_o) else 0
print(f"Two-for-one: possessions rebuilt -- our games {len(_tf_uww_poss):,}, {_TF_SHORT}'s games {len(_tf_opp_poss):,}. "
      f"2-for-1 chances (a possession starting with {min(TWO_FOR_ONE_WINDOW)}-{max(TWO_FOR_ONE_WINDOW)} sec left): "
      f"{_tf_nu} in our games, {_tf_no} in theirs.")
if len(pbp_situations):
    _sv = pbp_situations.drop_duplicates(_TF_KEYS + ["event_order"])
    print("  Situation on our play-by-play rows: "
          + ", ".join(f"{k} {v:,}" for k, v in _sv["situation"].fillna("unknown").value_counts().items())
          + f"  (coach tag on {int((_sv['situation_source'] == 'coach tag').sum()):,})")
for _, _r in two_for_one_plan.iterrows():
    print(f"  [{_r['part']}] {_r['headline']}")
if two_for_one_plan.empty:
    print("  No 2-for-1 reads for the upcoming opponent -- no end-of-half possessions found in their games.")
