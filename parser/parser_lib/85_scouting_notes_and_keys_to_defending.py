# 85_scouting_notes_and_keys_to_defending.py -- code for the notebook section "Scouting notes and keys to defending, derived from the opponent's own box scores ---------"
# Runs inside the notebook via run_section("85_scouting_notes_and_keys_to_defending"); its settings are in that notebook cell.

# --- Scouting notes and keys to defending, derived from the opponent's own box scores ------------------------
# Writes uww_scouting_notes.csv: one row per SUBJECT per SOURCE, so the coach-written notes from the
# "_scout.html" report and the data-driven ones generated here sit side by side rather than one replacing
# the other. They answer the same question from different evidence and a coach should see both -- when they
# agree that is corroboration, and when they disagree that is the interesting part.
#
#   subject_type = "player"  one of their players
#   subject_type = "lineup"   one of their five-man units
#   source = "Coach"          lifted verbatim from the scouting report (uww_player_profiles / rosters)
#   source = "Data-Driven"    generated below from the reconstructed box scores
#
# Players and units carry the SAME four fields -- notes, keys, strengths, weaknesses -- so one renderer
# draws both and the two sections cannot drift into different shapes. That is why the lineup reads moved
# here from the brief: derived content belongs in the parser, and a read that exists in only one consumer
# is a read the app can never show.
#
# Notes DESCRIBE, keys PRESCRIBE. That split is deliberate: a note is what the numbers say about a player,
# a key is what to do about it on Wednesday. Each key traces back to a note rather than being a separate
# opinion, so a coach can see why the instruction is there.
#
# WHAT THIS WILL NOT DO. Every read is gated on volume, and the phrasing never claims more than the sample
# supports. A player who is 2-of-4 from three is not a shooter; saying he is gets someone run off the line
# for no reason and leaves the paint open. Where the numbers say nothing, the player gets no line rather
# than a filler sentence -- an empty entry is a real answer and reads as one.
#
# Stated against the opponent's OWN team, not a league average: there is no league baseline in this data,
# and inventing one would put a number on the page that nothing here can support. "Takes a quarter of their
# shots" is a claim these tables can actually make.

_PN_OUT = "uww_scouting_notes"

# Volume floors. Low on purpose -- this is a handful of games, not a season -- so they exclude noise
# rather than demanding a big sample.
_PN_MIN_FGA = 12      # field-goal attempts before efficiency or shot profile is worth a word
_PN_MIN_3PA = 6       # three-point attempts before a percentage means anything
_PN_MIN_FTA = 8       # free-throw attempts before a foul-shooting read is worth a word
_PN_MIN_PTS_SHARE = 0.18   # share of team scoring that makes someone a primary option
# CONFIRMED BUG (fixed here): Mekhi Doby played ONE of Aurora's four games and came out with "Inefficient",
# "Gets to the line (13.0 FTA/gm)" and "Let him be the one who shoots it" -- one night's box score presented
# as a scouting identity. A player now needs _PN_MIN_GAME_SHARE of the team's games on film before any
# PRESCRIPTIVE key is written for him; the descriptive notes stay, prefixed with how thin the sample is.
_PN_MIN_GAME_SHARE = 0.5
# Same problem for five-man units: "Their weakest group -- push tempo" off 5.0 minutes together. Below this
# many minutes a unit gets its minutes line and nothing else.
_PN_LU_MIN_MINUTES = 8.0
# Player-level reference to the decoded play-call tags (see the "Play calls" cell): a set needs this many
# tagged uses BY this player before it's worth naming -- low on purpose, same reasoning as the floors above.
_PN_MIN_PLAY_USES = 3

# ---- Driver and offensive-rebounding reads (requested; coaches' notes on Hillmer asked for both) --------
# DRIVER: from the play-by-play text -- a make or miss described as a layup/dunk/tip is "at the rim".
_PN_DRIVER_MIN_FGA = 10       # play-by-play attempts before a shot-location read means anything
_PN_DRIVER_RIM_SHARE = 45     # % of his attempts at the rim to call him a driver
# OFFENSIVE REBOUNDING, position-independent: his offensive rebounds per 40 minutes against the TEAM's
# per-player rate. The old read went only to the team leader, so a guard who crashes hard next to a big
# who crashes harder could never get it. Rate-based, it can't be won just by playing the most minutes.
_PN_OREB_VS_TEAM = 1.5        # his OREB per 40 at least this multiple of their per-player OREB per 40
_PN_OREB_MIN = 5              # ...on at least this many offensive rebounds
_PN_OREB_MIN_MINUTES = 40     # ...in at least this many minutes

_pn_rows = []
_pn_problems = []


def _pn_load(name):
    try:
        return pd.read_csv(os.path.join(APP_DATA_DIR, f"{name}.csv"))
    except Exception:
        return pd.DataFrame()


def _pn_text(value):
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in ("nan", "none") else text


_RIM_WORDS = ("layup", "lay-up", "dunk", "tip", "putback", "put back", "jam", "alley")


def player_shot_zones(pbp, team_value, opponent_label, side_label):
    """Per-player rim / other-2 / three split from the play-by-play text. Defined here (before the
    game-plan cell) so the roster's Driver read and the app's WHERE THEY SHOOT table use ONE calculation."""
    if pbp is None or pbp.empty or not {"event_type", "team", "player"}.issubset(pbp.columns):
        return []
    s = pbp[pbp["event_type"].astype(str).isin(["made_shot", "missed_shot"])
            & (pbp["team"].astype(str) == str(team_value))].copy()
    if s.empty:
        return []
    _txt = s["raw_text"].astype(str).str.lower() if "raw_text" in s.columns else pd.Series("", index=s.index)
    _three = s["shot_type"].astype(str) == "3" if "shot_type" in s.columns else pd.Series(False, index=s.index)
    s["_zone"] = "Other 2"
    s.loc[_txt.apply(lambda t: any(w in t for w in _RIM_WORDS)) & ~_three, "_zone"] = "Rim"
    s.loc[_three, "_zone"] = "Three"
    s["_made"] = s["event_type"].astype(str) == "made_shot"
    rows = []
    for _pl, _g in s.groupby(s["player"].astype(str)):
        if _pl.strip().upper() in ("", "TEAM", "NAN"):
            continue
        _n = len(_g)
        _row = {"opponent": opponent_label, "side": side_label, "player": _pl, "fga": _n}
        for _z, _key in (("Rim", "rim"), ("Other 2", "other2"), ("Three", "three")):
            _zg = _g[_g["_zone"] == _z]
            _row[f"{_key}_att"] = len(_zg)
            _row[f"{_key}_share"] = round(100 * len(_zg) / _n) if _n else None
            _row[f"{_key}_fg"] = round(100 * _zg["_made"].sum() / len(_zg), 1) if len(_zg) else None
        rows.append(_row)
    return rows


def _pn_player_reads(p, table, top_pts, top_oreb, top_ast, zone=None, team_oreb40=None):
    """(strengths, weaknesses) for one player as short phrases.

    Short labels a coach scans, as opposed to the notes above, which are full sentences that explain. Both
    are generated from the same totals so they can never contradict each other -- the split is how much
    room the reader has, not which numbers were used.
    """
    g = max(float(p["games"]), 1.0)
    fga, f3a, fta = float(p["FGA"]), float(p["FG3A"]), float(p["FTA"])
    strengths, weaknesses = [], []
    # Reads that WOULD have been made but for sample size (requested: say so instead of dropping the
    # player's note). Kept apart from strengths/weaknesses so a thin-sample observation never outranks a
    # real read -- the roster shows these only when a player has no real read at all.
    below = []

    if p["player"] == top_pts and float(p["PTS"]) > 0:
        strengths.append(f"Leading scorer ({float(p['PTS']) / g:.1f} ppg)")
    # Offensive glass, by rate against his own team (see _PN_OREB_VS_TEAM) -- replaces "team leader only".
    _oreb, _min = float(p["OREB"]), float(p.get("MIN") or 0)
    if _min > 0 and team_oreb40:
        _o40 = 40 * _oreb / _min
        _hits = _o40 >= _PN_OREB_VS_TEAM * team_oreb40
        if _hits and _oreb >= _PN_OREB_MIN and _min >= _PN_OREB_MIN_MINUTES:
            strengths.append(f"Crashes the offensive glass \u2014 {_o40:.1f} per 40 min, "
                             f"{_o40 / team_oreb40:.1f}x their average ({_oreb / g:.1f} a game)")
        elif _hits and _oreb > 0:
            below.append(f"{_o40:.1f} offensive rebounds per 40 ({_o40 / team_oreb40:.1f}x their average) \u2014 "
                         f"under the {_PN_OREB_MIN}-rebound / {_PN_OREB_MIN_MINUTES}-minute minimum for a "
                         "crashing read")
    # Driver: most of his shots come at the rim. From the play-by-play text (layups, dunks, tips).
    if zone:
        _zf, _rs, _rfg = int(zone.get("fga") or 0), zone.get("rim_share"), zone.get("rim_fg")
        if _rs is not None and _rs >= _PN_DRIVER_RIM_SHARE:
            _fg_txt = f", {_rfg:.0f}% there" if _rfg is not None else ""
            if _zf >= _PN_DRIVER_MIN_FGA:
                strengths.append(f"Driver \u2014 {_rs:.0f}% of his shots at the rim{_fg_txt}")
            elif _zf > 0:
                below.append(f"{_rs:.0f}% of his shots at the rim ({_zf} attempts) \u2014 under the "
                             f"{_PN_DRIVER_MIN_FGA}-attempt minimum for a driver read")
    if p["player"] == top_ast and float(p["AST"]) / g >= 2:
        strengths.append(f"Primary creator ({float(p['AST']) / g:.1f} apg)")
    if float(table["REB"].max()) > 0 and float(p["REB"]) == float(table["REB"].max()) and float(p["REB"]) / g >= 4:
        strengths.append(f"Leads them on the glass ({float(p['REB']) / g:.1f} rpg)")
    if float(table["STL"].max()) > 0 and float(p["STL"]) == float(table["STL"].max()) and float(p["STL"]) / g >= 1.2:
        strengths.append(f"Active hands ({float(p['STL']) / g:.1f} spg)")
    if float(table["BLK"].max()) > 0 and float(p["BLK"]) == float(table["BLK"].max()) and float(p["BLK"]) / g >= 0.8:
        strengths.append(f"Rim protection ({float(p['BLK']) / g:.1f} bpg)")

    if f3a > 0:
        pct = 100 * float(p["FG3M"]) / f3a
        if f3a >= _PN_MIN_3PA:
            if pct >= 35:
                strengths.append(f"Shooter \u2014 {pct:.0f}% on {int(f3a)} threes")
            elif pct <= 25:
                weaknesses.append(f"Cold from three \u2014 {pct:.0f}% on {int(f3a)}")
        elif pct >= 35 or pct <= 25:
            below.append(f"{pct:.0f}% from three ({int(p['FG3M'])}-{int(f3a)}) \u2014 under the "
                         f"{_PN_MIN_3PA}-attempt minimum for a shooting read")
    if fga > 0:
        pct = 100 * float(p["FGM"]) / fga
        if fga >= _PN_MIN_FGA:
            if pct >= 50:
                strengths.append(f"Efficient \u2014 {pct:.0f}% from the field")
            elif pct <= 35:
                weaknesses.append(f"Inefficient \u2014 {pct:.0f}% on {int(fga)} shots")
        elif pct >= 50 or pct <= 35:
            below.append(f"{pct:.0f}% from the field ({int(p['FGM'])}-{int(fga)}) \u2014 under the "
                         f"{_PN_MIN_FGA}-shot minimum for an efficiency read")
    if fta > 0:
        ft_pct = 100 * float(p["FTM"]) / fta
        if fta >= _PN_MIN_FTA:
            if fta / g >= 4:
                strengths.append(f"Gets to the line ({fta / g:.1f} FTA/gm)")
            if ft_pct <= 60:
                weaknesses.append(f"Poor at the line \u2014 {ft_pct:.0f}%")
        elif fta / g >= 4 or ft_pct <= 60:
            below.append(f"{ft_pct:.0f}% at the line ({int(p['FTM'])}-{int(fta)}) \u2014 under the "
                         f"{_PN_MIN_FTA}-attempt minimum for a free-throw read")
    if float(p["TO"]) / g >= 2.5 and float(p["TO"]) >= float(p["AST"]):
        weaknesses.append(f"Gives it away ({float(p['TO']) / g:.1f} TO vs {float(p['AST']) / g:.1f} AST)")
    if float(p["PF"]) / g >= 3.2:
        weaknesses.append(f"Foul-prone ({float(p['PF']) / g:.1f} pf/gm)")
    if not strengths and not weaknesses and not below:
        # Nothing crossed a threshold, even ignoring sample size: say that, with the numbers, rather than
        # leaving the note empty -- "no read" must not look the same as "notes failed to load".
        below.append(f"No stat met a read threshold \u2014 {float(p['PTS']) / g:.1f} ppg, "
                     f"{int(p['FGM'])}-{int(fga)} FG, {int(p['FG3M'])}-{int(f3a)} 3PT, "
                     f"{int(p['FTM'])}-{int(fta)} FT over {int(g)} game(s)")
    return strengths, weaknesses, below


try:
    _pn_short = upcoming_opponent_short
    _pn_box = _pn_load("uww_opponent_prior_games_box_score")
    # Loaded here, not inside Part B's branch below, so it's always defined -- Part C (five-man units)
    # reads it too, and needs a safe empty default on any path where Part B's box-score branch is skipped.
    _pn_calls_ok_df = pd.DataFrame()

    # ---- A. Coach-written notes, straight from the scouting report ------------------------------------
    # Not regenerated or reworded here. A coach's note is evidence in its own right and gets passed
    # through exactly as written.
    _pn_seen = set()
    for _tbl in ("uww_player_profiles", "uww_opponent_rosters"):
        _t = _pn_load(_tbl)
        if _t.empty or not {"opponent", "name"}.issubset(_t.columns) or not _pn_short:
            continue
        for _, _p in _t[_t["opponent"].astype(str) == str(_pn_short)].iterrows():
            _nm = _pn_text(_p.get("name"))
            _notes = _pn_text(_p.get("player_notes"))
            _keys = _pn_text(_p.get("keys_to_defending"))
            if not _nm or (not _notes and not _keys) or _nm in _pn_seen:
                continue
            _pn_seen.add(_nm)
            _pn_rows.append({"opponent": _pn_short, "subject_type": "player", "name": _nm,
                             "source": "Coach", "notes": _notes, "keys_to_defending": _keys,
                             "strengths": "", "weaknesses": ""})

    # ---- B. Data-driven notes and keys ----------------------------------------------------------------
    if _pn_box.empty or "team" not in _pn_box.columns or not _pn_short:
        _pn_problems.append("no prior-game box scores for the upcoming opponent -- data-driven notes skipped")
    else:
        _pn_own = _pn_box[(_pn_box["team"].astype(str) == str(_pn_short))
                          & (_pn_box["player"].astype(str) != "TEAM")]
        # Per-player read of the decoded play-call tags (play_call/primary_action/play_location), joined onto
        # the opponent's clips in the "Play calls" cell. Loaded once, filtered per player inside the loop below.
        _pn_calls_all = _pn_load("uww_play_calls")
        _pn_calls_ok = (not _pn_calls_all.empty
                        and {"side", "scouted_opponent", "offense_team", "player", "play_call",
                             "decode_quality", "points"}.issubset(_pn_calls_all.columns))
        if _pn_calls_ok:
            _pn_calls_ok_df = _pn_calls_all[
                (_pn_calls_all["side"] == "Opponent")
                & (_pn_calls_all["scouted_opponent"].astype(str) == str(_pn_short))
                & (_pn_calls_all["offense_team"].astype(str) == str(_pn_short))
                & (_pn_calls_all["decode_quality"] != "Needs review")
            ]
        else:
            _pn_calls_ok_df = pd.DataFrame()
            _pn_problems.append("no uww_play_calls.csv (or missing columns) -- player play-call references skipped")
        if _pn_own.empty:
            _pn_problems.append(f"no box-score rows for {_pn_short} in their prior games")
        else:
            _pn_cols = ("PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA",
                        "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "MIN")
            _pn_tot = _pn_own.groupby("player").apply(
                lambda g: pd.Series({c: pd.to_numeric(g[c], errors="coerce").sum()
                                     if c in g.columns else 0 for c in _pn_cols}
                                    | {"games": g["game_date"].nunique()
                                       if "game_date" in g.columns else len(g)})
            ).reset_index()

            _pn_team_pts = float(_pn_tot["PTS"].sum()) or 1.0
            _pn_team_fga = float(_pn_tot["FGA"].sum()) or 1.0
            _pn_top_oreb = _pn_tot.loc[_pn_tot["OREB"].idxmax()]["player"] if _pn_tot["OREB"].max() > 0 else None
            _pn_top_ast = _pn_tot.loc[_pn_tot["AST"].idxmax()]["player"] if _pn_tot["AST"].max() > 0 else None
            _pn_top_pts = _pn_tot.loc[_pn_tot["PTS"].idxmax()]["player"] if _pn_tot["PTS"].max() > 0 else None

            _pn_team_games = (int(_pn_own["game_date"].nunique()) if "game_date" in _pn_own.columns
                              else int(_pn_tot["games"].max()))
            # Their per-player offensive-rebound rate (per 40 minutes) -- the yardstick for "crashes".
            _pn_team_min = float(_pn_tot["MIN"].sum())
            _pn_team_oreb40 = (40 * float(_pn_tot["OREB"].sum()) / _pn_team_min) if _pn_team_min > 0 else None
            if _pn_team_oreb40 is None:
                _pn_problems.append("box score has no minutes -- the offensive-rebounding read was skipped")
            # Where each player shoots from, for the Driver read (same function the app's table uses).
            _pn_zones = {str(r["player"]).strip().lower(): r for r in player_shot_zones(
                _pn_load("uww_opponent_prior_games_pbp"), _pn_short, _pn_short, "Opponent")}
            if not _pn_zones:
                _pn_problems.append("no play-by-play shot text for their players -- the Driver read was skipped")
            for _, _p in _pn_tot.iterrows():
                _nm = str(_p["player"])
                _g = max(float(_p["games"]), 1.0)
                _thin = _pn_team_games > 1 and _g < _PN_MIN_GAME_SHARE * _pn_team_games
                _fga, _f3a, _fta = float(_p["FGA"]), float(_p["FG3A"]), float(_p["FTA"])
                _notes, _keys = [], []

                _pts_share = float(_p["PTS"]) / _pn_team_pts
                _fga_share = _fga / _pn_team_fga
                # True shooting puts threes and free throws on the same scale as twos, which raw FG%
                # cannot -- a 36% three-point shooter and a 50% finisher are equally efficient and FG%
                # would call one of them bad.
                _ts_den = 2 * (_fga + 0.44 * _fta)
                _ts = (100 * float(_p["PTS"]) / _ts_den) if _ts_den > 0 else None

                # --- usage ---
                # CONFIRMED BUG (fixed here): both the SINGLE team-leading scorer AND anyone else clearing
                # 18% of team scoring got the identical "Top priority ... make a second option beat you"
                # note -- wording that only makes sense for exactly one player. On a team with a flat
                # scoring distribution (no one dominant scorer), three or more players can each individually
                # clear 18%, and all three showed up with the same "you are the lone threat" framing, which
                # is self-contradictory read together. Only the actual top scorer keeps that wording now;
                # anyone else who separately clears the bar gets a note that doesn't claim uniqueness.
                if _nm == _pn_top_pts:
                    _notes.append(f"Primary option: {float(_p['PTS']) / _g:.1f} ppg, "
                                  f"{100 * _pts_share:.0f}% of their scoring on "
                                  f"{100 * _fga_share:.0f}% of their shots.")
                    _keys.append("Top priority \u2014 no easy catches, and make a second option beat you.")
                elif _pts_share >= _PN_MIN_PTS_SHARE:
                    _notes.append(f"Also a high-usage scorer: {float(_p['PTS']) / _g:.1f} ppg, "
                                  f"{100 * _pts_share:.0f}% of their scoring on "
                                  f"{100 * _fga_share:.0f}% of their shots.")
                    _keys.append("Heavily used too \u2014 not the lone scorer, but don't lose him helping "
                                 "off to load up on someone else.")

                # --- shot profile ---
                if _fga >= _PN_MIN_FGA:
                    _three_rate = _f3a / _fga if _fga else 0
                    _three_pct = (100 * float(_p["FG3M"]) / _f3a) if _f3a > 0 else None
                    if _three_rate >= 0.45 and _f3a >= _PN_MIN_3PA:
                        _notes.append(f"Perimeter-first: {100 * _three_rate:.0f}% of his attempts are "
                                      f"threes ({int(_p['FG3M'])}-of-{int(_f3a)}, {_three_pct:.0f}%).")
                        if _three_pct is not None and _three_pct >= 35:
                            _keys.append("Run him off the line \u2014 close out short and make him put it "
                                         "on the floor.")
                        elif _three_pct is not None and _three_pct <= 28:
                            _keys.append("Live with the three \u2014 go under screens and help off him "
                                         "into the paint.")
                    elif _three_rate <= 0.15:
                        _notes.append(f"Interior player: only {100 * _three_rate:.0f}% of his attempts "
                                      f"come from three.")
                        _keys.append("Nothing easy at the rim \u2014 wall up early rather than reaching, "
                                     "and make him finish over a body.")

                    if _ts is not None:
                        if _ts >= 57:
                            _notes.append(f"Efficient: {_ts:.1f}% true shooting on {int(_fga)} attempts.")
                        elif _ts <= 45:
                            _notes.append(f"Inefficient: {_ts:.1f}% true shooting on {int(_fga)} attempts.")
                            _keys.append("Let him be the one who shoots it \u2014 volume without "
                                         "efficiency is a result we will take.")

                # --- free throws ---
                if _fta >= _PN_MIN_FTA:
                    _ft_rate = _fta / _fga if _fga else 0
                    _ft_pct = 100 * float(_p["FTM"]) / _fta
                    if _ft_rate >= 0.40:
                        _notes.append(f"Gets to the line: {_fta / _g:.1f} attempts a game "
                                      f"({_ft_rate:.2f} per field-goal attempt).")
                        _keys.append("Guard him without fouling \u2014 hands up, no bail-outs.")
                    if _ft_pct <= 60:
                        _notes.append(f"{_ft_pct:.0f}% from the line on {int(_fta)} attempts.")
                        _keys.append("If he has to be fouled late, he is the one to foul.")

                # --- glass, playmaking, giveaways, fouls ---
                # Same rate rule as the "Crashes the offensive glass" read, so the note, the key and the read
                # always agree -- no longer only the team's leader.
                _pmin = float(_p.get("MIN") or 0)
                if (_pn_team_oreb40 and _pmin >= _PN_OREB_MIN_MINUTES and float(_p["OREB"]) >= _PN_OREB_MIN
                        and 40 * float(_p["OREB"]) / _pmin >= _PN_OREB_VS_TEAM * _pn_team_oreb40):
                    _notes.append(f"Their offensive glass: {40 * float(_p['OREB']) / _pmin:.1f} offensive rebounds "
                                  f"per 40 minutes, {40 * float(_p['OREB']) / _pmin / _pn_team_oreb40:.1f}x their "
                                  f"per-player rate.")
                    _keys.append("Put a body on him every shot \u2014 he is where their second chances "
                                 "come from.")

                _ast, _to = float(_p["AST"]), float(_p["TO"])
                if _nm == _pn_top_ast and _ast / _g >= 2:
                    _notes.append(f"Initiates for them: {_ast / _g:.1f} assists a game, "
                                  f"{_ast / _to:.1f} per turnover." if _to > 0 else
                                  f"Initiates for them: {_ast / _g:.1f} assists a game.")
                    _keys.append("Get it out of his hands \u2014 deny the first pass and make someone "
                                 "else start the offense.")
                if _to / _g >= 2.5 and _to >= _ast:
                    _notes.append(f"Loose with it: {_to / _g:.1f} turnovers a game against "
                                  f"{_ast / _g:.1f} assists.")
                    _keys.append("Pressure him full-court and trap him off the catch.")

                _pf = float(_p["PF"])
                if _pf / _g >= 3.2:
                    _notes.append(f"Fouls: {_pf / _g:.1f} a game.")
                    _keys.append("Attack him early \u2014 two quick ones changes how he guards.")

                # --- his own tagged play calls (uww_plays.csv / opponent_plays.csv, decoded) ---------------
                if not _pn_calls_ok_df.empty:
                    _my_clips = _pn_calls_ok_df[_pn_calls_ok_df["player"].astype(str) == _nm]
                    if not _my_clips.empty:
                        _named = _my_clips[~_my_clips["play_call"].astype(str).str.contains("unspecified", na=False)
                                           & _my_clips["play_call"].notna()]
                        _call_counts = _named["play_call"].value_counts()
                        _top_calls = _call_counts[_call_counts >= _PN_MIN_PLAY_USES]
                        if not _top_calls.empty:
                            _pts = pd.to_numeric(_my_clips["points"], errors="coerce")
                            _known = int(_pts.notna().sum())
                            _ppp = (_pts.sum() / _known) if _known else None
                            _call_txt = ", ".join(f"{n} ({int(c)}x)" for n, c in _top_calls.head(3).items())
                            _notes.append(
                                f"Tagged film: featured in {_call_txt} out of {len(_my_clips)} tagged "
                                f"possession(s)" + (f" \u2014 {_ppp:.2f} PPP." if _ppp is not None else "."))
                            _top_set = _top_calls.index[0]
                            _set_clips = _my_clips[_my_clips["play_call"] == _top_set]
                            _loc = _set_clips["play_location"].dropna()
                            _act = _set_clips["primary_action"].dropna()
                            _where = (f" to the {_loc.mode().iloc[0].lower()}"
                                      if not _loc.empty and not _loc.mode().empty else "")
                            _how = (f" off {_act.mode().iloc[0]}"
                                    if not _act.empty and not _act.mode().empty
                                    and _act.mode().iloc[0] not in _top_set else "")
                            _keys.append(f"Know {_top_set}{_how}{_where} \u2014 his most-tagged set on film "
                                         f"({int(_top_calls.iloc[0])}x).")

                _strengths, _weaknesses, _below = _pn_player_reads(
                    _p, _pn_tot, _pn_top_pts, _pn_top_oreb, _pn_top_ast,
                    zone=_pn_zones.get(_nm.strip().lower()), team_oreb40=_pn_team_oreb40)
                if _thin:
                    # Describe, don't prescribe: a key is an instruction a player will act on Wednesday.
                    if _notes or _strengths or _weaknesses:
                        _notes.insert(0, f"Only {int(_g)} of {_pn_team_games} games on film \u2014 provisional.")
                    _keys = []
                if _notes or _keys or _strengths or _weaknesses or _below:
                    _pn_rows.append({
                        "opponent": _pn_short, "subject_type": "player", "name": _nm,
                        "source": "Data-Driven",
                        "notes": " ".join(_notes),
                        # Pipe-joined so a renderer can show each as its own line; kept in one field so
                        # the table stays one row per subject per source.
                        "keys_to_defending": " | ".join(_keys),
                        "strengths": " | ".join(_strengths),
                        "weaknesses": " | ".join(_weaknesses),
                        "below_minimum": " | ".join(_below),
                    })

    # ---- C. Five-man units, same four fields as the players ------------------------------------------
    # Measured against the opponent's OWN lineup averages and stated as rates -- per 40 minutes or a
    # percentage. Raw totals would rank the units by playing time a second time, so the heaviest-used
    # unit would come out "best at everything" by construction.
    _pn_lu = _pn_load("uww_opp_lineup_season_box")
    if not _pn_lu.empty and "lineup" in _pn_lu.columns and "MIN" in _pn_lu.columns:
        _lu_min = pd.to_numeric(_pn_lu["MIN"], errors="coerce").fillna(0)
        _lu_total_min = float(_lu_min.sum())
        if _lu_total_min > 0:
            def _lu_num(col):
                return (pd.to_numeric(_pn_lu[col], errors="coerce").fillna(0)
                        if col in _pn_lu.columns else pd.Series(0.0, index=_pn_lu.index))

            def _lu_team_rate(col):
                return float(_lu_num(col).sum()) / _lu_total_min * 40

            _lu_team_fg = (100 * _lu_num("FGM").sum() / _lu_num("FGA").sum()
                           if _lu_num("FGA").sum() > 0 else None)
            _lu_team_3p = (100 * _lu_num("FG3M").sum() / _lu_num("FG3A").sum()
                           if _lu_num("FG3A").sum() > 0 else None)
            _lu_team_to40, _lu_team_reb40 = _lu_team_rate("TO"), _lu_team_rate("REB")
            _lu_team_ast40 = _lu_team_rate("AST")
            _lu_busiest = _pn_lu.loc[_lu_min.idxmax(), "lineup"]

            for _i, _u in _pn_lu.iterrows():
                _key = str(_u["lineup"])
                _mins = float(_lu_min.loc[_i])
                if _mins <= 0:
                    continue
                _notes, _keys, _str, _weak = [], [], [], []

                def _val(col):
                    return float(pd.to_numeric(pd.Series([_u.get(col, 0)]), errors="coerce").fillna(0).iloc[0])

                _gp = _val("GP")
                _notes.append(f"{_mins:.1f} minutes together"
                              + (f" over {int(_gp)} game(s)" if _gp else "")
                              + (" \u2014 their most-used unit." if _key == str(_lu_busiest) else "."))
                if _mins < _PN_LU_MIN_MINUTES:
                    _notes.append(f"Under {_PN_LU_MIN_MINUTES:.0f} minutes together \u2014 too few possessions "
                                  f"to read.")
                    _pn_rows.append({"opponent": _pn_short, "subject_type": "lineup", "name": _key,
                                     "source": "Data-Driven", "notes": " ".join(_notes),
                                     "keys_to_defending": "", "strengths": "", "weaknesses": ""})
                    continue

                _margin = _val("+/-")
                _per40 = _margin / _mins * 40
                if abs(_per40) >= 5:
                    _notes.append(f"Net {_per40:+.0f} per 40 minutes on the floor "
                                  f"({_margin:+.0f} in {_mins:.1f}).")
                    if _per40 > 0:
                        _str.append(f"{_per40:+.0f} per 40 on the floor")
                        _keys.append("Their best group \u2014 make sure our own best five is out there "
                                     "with them.")
                    else:
                        _weak.append(f"{_per40:+.0f} per 40 on the floor")
                        _keys.append("Their weakest group \u2014 push tempo and hunt shots while it is "
                                     "on the floor.")

                _fg, _fga = _u.get("FG%"), _val("FGA")
                if pd.notna(_fg) and _lu_team_fg and _fga >= _PN_MIN_FGA:
                    _fg = float(_fg)
                    if _fg - _lu_team_fg >= 4:
                        _str.append(f"Shoots it better than their norm ({_fg:.1f}% vs {_lu_team_fg:.1f}%)")
                    elif _lu_team_fg - _fg >= 4:
                        _weak.append(f"Cold unit ({_fg:.1f}% vs {_lu_team_fg:.1f}%)")

                _tp, _tpa = _u.get("3P%"), _val("FG3A")
                if pd.notna(_tp) and _lu_team_3p and _tpa >= _PN_MIN_3PA:
                    _tp = float(_tp)
                    if _tp - _lu_team_3p >= 5:
                        _str.append(f"Hits threes ({_tp:.1f}% on {int(_tpa)})")
                        _notes.append(f"Shoots {_tp:.1f}% from three on {int(_tpa)} attempts with this "
                                      f"group on the floor.")
                        _keys.append("Stay attached on the perimeter \u2014 no help off this group's "
                                     "shooters.")
                    elif _lu_team_3p - _tp >= 5:
                        _weak.append(f"Won't make threes ({_tp:.1f}% on {int(_tpa)})")
                        _keys.append("Pack the paint against this group and live with the three.")

                for _col, _team_value, _good, _bad, _higher, _key_good, _key_bad in (
                    ("REB", _lu_team_reb40, "Rebounds well", "Gets beaten on the glass", True,
                     None, "Crash the offensive glass while this unit is in."),
                    ("AST", _lu_team_ast40, "Moves the ball", "Stagnant \u2014 few assists", True,
                     None, "Switch and make this group create off the dribble."),
                    ("TO", _lu_team_to40, "Takes care of it", "Turnover-prone", False,
                     None, "Pressure this unit \u2014 they give it away."),
                ):
                    if _team_value is None:
                        continue
                    _rate = _val(_col) / _mins * 40
                    _gap = _rate - _team_value
                    if abs(_gap) < max(1.5, 0.15 * _team_value):
                        continue
                    _better = (_gap > 0) if _higher else (_gap < 0)
                    _phrase = f"{_good if _better else _bad} ({_rate:.1f} vs {_team_value:.1f} per 40)"
                    (_str if _better else _weak).append(_phrase)
                    _instruction = _key_good if _better else _key_bad
                    if _instruction:
                        _keys.append(_instruction)

                # --- this group's own tagged play calls (uww_plays.csv / opponent_plays.csv, decoded) -----
                # There's no lineup tag on a clip itself -- a clip names the possession's ball-handler or
                # finisher, not all five players on the floor -- so this pools every clip whose tagged player
                # is a MEMBER of this group, rather than claiming the five were confirmed on the floor
                # together for each one. Said explicitly in the note so it isn't read as more than it is.
                if _pn_calls_ok_df is not None and not _pn_calls_ok_df.empty:
                    _lu_members = [p.strip() for p in _key.split(",") if p.strip()]
                    _lu_clips = _pn_calls_ok_df[_pn_calls_ok_df["player"].astype(str).isin(_lu_members)]
                    if not _lu_clips.empty:
                        _lu_named = _lu_clips[~_lu_clips["play_call"].astype(str).str.contains("unspecified", na=False)
                                              & _lu_clips["play_call"].notna()]
                        _lu_call_counts = _lu_named["play_call"].value_counts()
                        _lu_top_calls = _lu_call_counts[_lu_call_counts >= _PN_MIN_PLAY_USES]
                        if not _lu_top_calls.empty:
                            _lu_pts = pd.to_numeric(_lu_clips["points"], errors="coerce")
                            _lu_known = int(_lu_pts.notna().sum())
                            _lu_ppp = (_lu_pts.sum() / _lu_known) if _lu_known else None
                            _lu_call_txt = ", ".join(f"{n} ({int(c)}x)" for n, c in _lu_top_calls.head(3).items())
                            _notes.append(
                                f"Tagged film across this group's players: {_lu_call_txt} out of "
                                f"{len(_lu_clips)} tagged possession(s)"
                                + (f" \u2014 {_lu_ppp:.2f} PPP." if _lu_ppp is not None else ".")
                                + " (each clip's tagged player is a member of this group -- not confirmed "
                                  "as all five on the floor together for every one.)")
                            _lu_top_set = _lu_top_calls.index[0]
                            _lu_set_clips = _lu_clips[_lu_clips["play_call"] == _lu_top_set]
                            _lu_loc = _lu_set_clips["play_location"].dropna()
                            _lu_act = _lu_set_clips["primary_action"].dropna()
                            _lu_where = (f" to the {_lu_loc.mode().iloc[0].lower()}"
                                        if not _lu_loc.empty and not _lu_loc.mode().empty else "")
                            _lu_how = (f" off {_lu_act.mode().iloc[0]}"
                                      if not _lu_act.empty and not _lu_act.mode().empty
                                      and _lu_act.mode().iloc[0] not in _lu_top_set else "")
                            _keys.append(f"Know {_lu_top_set}{_lu_how}{_lu_where} \u2014 this group's "
                                        f"most-tagged set on film ({int(_lu_top_calls.iloc[0])}x).")

                if _notes or _keys or _str or _weak:
                    _pn_rows.append({
                        "opponent": _pn_short, "subject_type": "lineup", "name": _key,
                        "source": "Data-Driven",
                        "notes": " ".join(_notes),
                        "keys_to_defending": " | ".join(_keys),
                        "strengths": " | ".join(_str),
                        "weaknesses": " | ".join(_weak),
                    })

except Exception as _e:
    _pn_problems.append(str(_e))

scouting_notes = pd.DataFrame(_pn_rows)
if scouting_notes.empty:
    scouting_notes = pd.DataFrame(columns=["opponent", "subject_type", "name", "source", "notes",
                                           "keys_to_defending", "strengths", "weaknesses"])
scouting_notes.to_csv(os.path.join(APP_DATA_DIR, f"{_PN_OUT}.csv"), index=False)

print(f"Wrote {_PN_OUT}.csv -- {len(scouting_notes)} row(s) for "
      f"{upcoming_opponent_short or 'no opponent'}"
      + (f": {scouting_notes.groupby(['subject_type', 'source']).size().to_dict()}"
         if not scouting_notes.empty else ""))
if _pn_problems:
    print("  Notes:")
    for _p in _pn_problems:
        print(f"    - {_p}")
