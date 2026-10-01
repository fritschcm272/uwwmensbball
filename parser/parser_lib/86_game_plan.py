# 86_game_plan.py -- code for the notebook section "Game-plan and practice-plan tables, with SAMPLE placeholders for what the files don't carr"
# Runs inside the notebook via run_section("86_game_plan"); its settings are in that notebook cell.

# --- Game-plan and practice-plan tables, with SAMPLE placeholders for what the files don't carry yet --------
# The brief answers "who are they, statistically". A staff building Monday's practice also needs HOW they play
# (sets, special situations, defensive scheme), physical details (height, hand), availability, matchups, a
# scout-team plan and a practice calendar. None of that is in play-by-play or video-tagging exports.
#
# This cell writes one CSV per section so the app and the brief render the same thing. Every row carries
# `is_sample`:
#   is_sample = False   real -- derived from the exported tables, or typed in by the staff (see below)
#   is_sample = True    PLACEHOLDER generated here so the layout can be reviewed. Renderers MUST show these
#                       inside a red "SAMPLE DATA" box. They are shaped like the real thing (real player names,
#                       plausible values) precisely so nobody mistakes a blank for "nothing to scout" -- which
#                       is also why they must never be shown unmarked.
#
# REPLACING SAMPLES WITH REAL INPUT. Drop a CSV into INPUT_DIR/staff_inputs/ with the same name and columns as
# the template this cell writes to OUTPUT_DIR/staff_input_templates/ (minus is_sample). Rows whose `opponent`
# matches the upcoming opponent replace the sample rows for that section entirely. Nothing is blended: a
# section is either all staff input or all sample, so a red box never hides one real row among fake ones.
#
# REAL-DATA sections written here (never sample):
#   uww_late_game_foul_list   who to foul / not foul, from their own FT shooting with an attempt floor
#   uww_sample_size_warnings  every number in the brief that rests on a thin sample, in one place
#   uww_practice_plan         the EMPHASIS items are pulled from uww_ktv_keys and uww_coaching_flags (real);
#                             the calendar and minutes are sample until a staff calendar is supplied, and the
#                             row-level `schedule_is_sample` says so.
import hashlib as _gp_hash

_GP_STAFF_DIR = os.path.join(INPUT_DIR, "staff_inputs")
_GP_TEMPLATE_DIR = os.path.join(OUTPUT_DIR, "staff_input_templates")
_GP_UWW = "UW-Whitewater"
_GP_FOUL_MIN_FTA = 8          # FT attempts before a player goes on either foul list
_GP_THIN_GAME_SHARE = 0.5     # same floor as the scouting-notes cell
_GP_THIN_LINEUP_MIN = 8.0     # same floor as the scouting-notes / KTV cells
_gp_short = upcoming_opponent_short
_gp_problems = []


def _gp_load(name):
    try:
        return pd.read_csv(os.path.join(APP_DATA_DIR, f"{name}.csv"))
    except Exception:
        return pd.DataFrame()


def _gp_pick(seed, options):
    """Deterministic 'random' choice, so a sample doesn't change every run and look like new data."""
    h = int(_gp_hash.md5(str(seed).encode()).hexdigest(), 16)
    return options[h % len(options)]


def _gp_last(name):
    parts = str(name).split()
    return parts[-1] if parts else str(name)


def _gp_staff_rows(section, columns):
    """Staff-typed rows for this opponent, or None. A file that exists but has no rows for this opponent is
    treated as absent -- a staff sheet for last week's opponent must not suppress this week's sample."""
    path = os.path.join(_GP_STAFF_DIR, f"{section}.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
    except Exception as e:
        _gp_problems.append(f"{section}: could not read staff input ({e}) -- using sample")
        return None
    if "opponent" in df.columns and _gp_short:
        df = df[df["opponent"].astype(str).str.strip() == str(_gp_short)]
    if df.empty:
        return None
    for c in columns:
        if c not in df.columns:
            df[c] = None
    df = df[columns].copy()
    df["is_sample"] = False
    return df


def _gp_write(section, columns, sample_rows, real_rows=None):
    """Staff input if present, else rows derived from real data (real_rows), else the sample rows. Also writes
    an empty template the staff can fill. Staff input wins over derived data: it's the staff's call."""
    os.makedirs(_GP_TEMPLATE_DIR, exist_ok=True)
    pd.DataFrame(columns=columns).to_csv(os.path.join(_GP_TEMPLATE_DIR, f"{section}.csv"), index=False)
    staff = _gp_staff_rows(section, columns)
    if staff is not None:
        out = staff
    elif real_rows:
        out = pd.DataFrame(real_rows, columns=columns)
        out["is_sample"] = False
    else:
        out = pd.DataFrame(sample_rows, columns=columns)
        out["is_sample"] = True
    out.to_csv(os.path.join(APP_DATA_DIR, f"uww_{section}.csv"), index=False)
    return out


# ---- per-player season lines, both sides --------------------------------------------------------------
def _gp_player_lines(box, team_value, invert=False):
    if box.empty or "team" not in box.columns:
        return pd.DataFrame()
    mask = box["team"].astype(str) == str(team_value)
    rows = box[~mask if invert else mask]
    rows = rows[rows["player"].astype(str) != "TEAM"]
    if rows.empty:
        return pd.DataFrame()
    cols = [c for c in ("PTS", "MIN", "FGA", "FG3M", "FG3A", "FTM", "FTA", "REB", "OREB", "AST", "BLK", "TO")
            if c in rows.columns]
    work = rows.copy()
    for c in cols:
        work[c] = pd.to_numeric(work[c], errors="coerce").fillna(0)
    agg = work.groupby("player")[cols].sum()
    agg["games"] = work.groupby("player")["game_date"].nunique() if "game_date" in work.columns else 1
    agg = agg.reset_index()
    # Minutes when we have them, points otherwise -- "who plays most" is the question for matchups.
    order = "MIN" if "MIN" in agg.columns and agg["MIN"].sum() > 0 else "PTS"
    return agg.sort_values(order, ascending=False).reset_index(drop=True)


_gp_prior = _gp_load("uww_opponent_prior_games_box_score")
_gp_box = _gp_load("uww_pbp_box_score")
_gp_opp = _gp_player_lines(_gp_prior, _gp_short)
_gp_us = _gp_player_lines(_gp_box, _GP_UWW)
_gp_team_games = (int(_gp_prior[_gp_prior["team"].astype(str) == str(_gp_short)]["game_date"].nunique())
                  if not _gp_prior.empty and "game_date" in _gp_prior.columns else 0)

# Role guesses used ONLY to make sample rows plausible (who a set is "for"). Not exported as facts.
_gp_shooter = _gp_big = _gp_driver = _gp_handler = None
if not _gp_opp.empty:
    _regular = _gp_opp[_gp_opp["games"] >= max(1, _GP_THIN_GAME_SHARE * max(_gp_team_games, 1))]
    _pool = _regular if not _regular.empty else _gp_opp
    _sh = _pool[_pool["FG3A"] >= 6].assign(_p=lambda d: d["FG3M"] / d["FG3A"])
    _gp_shooter = _sh.sort_values("_p", ascending=False)["player"].iloc[0] if not _sh.empty else _pool["player"].iloc[0]
    _gp_big = _pool.sort_values(["REB", "BLK"], ascending=False)["player"].iloc[0]
    _gp_driver = _pool.sort_values("FTA", ascending=False)["player"].iloc[0]
    _gp_handler = _pool.sort_values("AST", ascending=False)["player"].iloc[0]


# ======================================================================================================
# REAL: late-game foul list
# ======================================================================================================
# CONFIRMED BUG (fixed here): the attempt floor was applied to BOTH calls, so a player shooting 6-for-6 was
# left off the list entirely -- a blank cell, when the obvious read is "don't put him on the line". The two
# calls carry different risk, so they no longer share a threshold:
#   FOUL him       -- a deliberate act on our part, so it needs real evidence he is bad: _GP_FOUL_MIN_FTA
#                     attempts AND a shrunk estimate at or under _GP_FOUL_BAD_PCT.
#   DO NOT FOUL    -- avoiding a shooter costs us nothing if we're wrong, so a small but clean sample is
#                     enough: _GP_FOUL_MIN_FTA attempts at _GP_FOUL_GOOD_PCT or better, OR as few as
#                     _GP_FOUL_SMALL_FTA attempts when he hasn't missed much (_GP_FOUL_SMALL_PCT or better).
# Rates are shrunk toward a D3 baseline before the call is made, so 6-for-6 doesn't read as a true 100%
# shooter while still landing on the right side of the line; the raw makes-attempts pair is what's displayed.
_GP_FOUL_BAD_PCT = 62
_GP_FOUL_GOOD_PCT = 75
_GP_FOUL_SMALL_FTA = 4
_GP_FOUL_SMALL_PCT = 85
_GP_FOUL_SHRINK_N = 6      # prior weight, in attempts
_GP_FOUL_PRIOR_PCT = 70.0  # roughly the D3 men's free-throw average

_foul_rows = []
if not _gp_opp.empty and "FTA" in _gp_opp.columns:
    _ft = _gp_opp[_gp_opp["FTA"] >= min(_GP_FOUL_MIN_FTA, _GP_FOUL_SMALL_FTA)].copy()
    _ft["ft_pct"] = (100 * _ft["FTM"] / _ft["FTA"]).round(1)
    _ft["ft_pct_adj"] = ((100 * _ft["FTM"] + _GP_FOUL_PRIOR_PCT * _GP_FOUL_SHRINK_N)
                         / (_ft["FTA"] + _GP_FOUL_SHRINK_N)).round(1)
    for _, r in _ft.sort_values("ft_pct_adj").iterrows():
        _enough_to_foul = r["FTA"] >= _GP_FOUL_MIN_FTA
        _clean_small = r["FTA"] >= _GP_FOUL_SMALL_FTA and r["ft_pct"] >= _GP_FOUL_SMALL_PCT
        if _enough_to_foul and r["ft_pct_adj"] <= _GP_FOUL_BAD_PCT:
            _call = "Foul"
        elif (_enough_to_foul and r["ft_pct_adj"] >= _GP_FOUL_GOOD_PCT) or _clean_small:
            _call = "Do not foul"
        elif _enough_to_foul:
            _call = "Neutral"
        else:
            continue  # too few attempts to say anything either way
        _thin_ft = _gp_team_games > 1 and r["games"] < _GP_THIN_GAME_SHARE * _gp_team_games
        _note = f"Only {int(r['games'])} of {_gp_team_games} games on film" if _thin_ft else ""
        if _clean_small and r["FTA"] < _GP_FOUL_MIN_FTA:
            _note = (f"{int(r['FTM'])}-for-{int(r['FTA'])} -- small sample, but no reason to put him on the "
                     f"line" + (f"; {_note.lower()}" if _note else ""))
        _foul_rows.append({"opponent": _gp_short, "player": r["player"], "call": _call,
                           "ft_pct": r["ft_pct"], "ft_pct_adj": r["ft_pct_adj"],
                           "ftm": int(r["FTM"]), "fta": int(r["FTA"]),
                           "games": int(r["games"]), "note": _note})
late_game_foul_list = pd.DataFrame(_foul_rows, columns=["opponent", "player", "call", "ft_pct", "ft_pct_adj",
                                                        "ftm", "fta", "games", "note"])
late_game_foul_list["is_sample"] = False
late_game_foul_list.to_csv(os.path.join(APP_DATA_DIR, "uww_late_game_foul_list.csv"), index=False)


# ======================================================================================================
# REAL: sample-size warnings -- one place a coach can see what NOT to lean on
# ======================================================================================================
_warn = []
if not _gp_opp.empty and _gp_team_games > 1:
    for _, r in _gp_opp.iterrows():
        if r["games"] < _GP_THIN_GAME_SHARE * _gp_team_games and r["PTS"] / max(r["games"], 1) >= 8:
            _warn.append({"area": "Opponent player", "subject": r["player"],
                          "detail": f"{r['PTS'] / r['games']:.1f} ppg comes from {int(r['games'])} of "
                                    f"{_gp_team_games} games on film -- confirm his status and role."})
_lu = _gp_load("uww_opp_lineup_season_box")
if not _lu.empty and "MIN" in _lu.columns:
    _n_thin = int((pd.to_numeric(_lu["MIN"], errors="coerce") < _GP_THIN_LINEUP_MIN).sum())
    if _n_thin:
        _warn.append({"area": "Opponent lineups", "subject": f"{_n_thin} of {len(_lu)} units",
                      "detail": f"under {_GP_THIN_LINEUP_MIN:.0f} minutes together -- no reads or keys "
                                f"are drawn from them."})
_sm = _gp_load("uww_style_matchups")
if not _sm.empty and "confidence" in _sm.columns and "opponent" in _sm.columns:
    _sm = _sm[_sm["opponent"].astype(str) == str(_gp_short)]
    for _dir, _label in (("like_them", "Teams like them we've played"), ("like_us", "Teams like us")):
        _c = pd.to_numeric(_sm[_sm["direction"] == _dir]["confidence"], errors="coerce")
        if _c.notna().any() and _c.max() < 0.35:
            _warn.append({"area": "Style matchups", "subject": _label,
                          "detail": f"best match confidence is {100 * _c.max():.0f}% -- context, not evidence."})
_fl = _gp_load("uww_coaching_flags")
if not _fl.empty and "confidence" in _fl.columns:
    _low = _fl[_fl["confidence"].astype(str).str.lower().str.startswith("low")]
    if not _low.empty:
        _warn.append({"area": "Our player flags", "subject": f"{len(_low)} flag(s)",
                      "detail": "rest on fewer than 10 attempts -- use for film review, not rotation calls."})
if _gp_team_games and _gp_team_games < 6:
    _warn.append({"area": "Whole brief", "subject": f"{_gp_team_games} opponent games on film",
                  "detail": "every opponent rate here is early-season -- expect several to move by January."})
sample_size_warnings = pd.DataFrame(_warn, columns=["area", "subject", "detail"])
sample_size_warnings.insert(0, "opponent", _gp_short)
sample_size_warnings["is_sample"] = False
sample_size_warnings.to_csv(os.path.join(APP_DATA_DIR, "uww_sample_size_warnings.csv"), index=False)


# ======================================================================================================
# SAMPLE (until staff input exists): how they play
# ======================================================================================================
_S = lambda n: n if n else "their best player"  # noqa: E731

# ---- REAL sets from opponent_plays.csv, when the play-call cell produced them ----------------------------
# Situation, set, who finishes it, its main action and where, how often, how well it worked, and the game
# codes to pull film from. "our_call" is a GENERATED suggestion keyed on the primary action -- the brief labels
# that column "Suggested coverage" so nobody reads it as the staff's scheme.
_GP_COVERAGE_BY_ACTION = {
    "DHO": "Get into the handoff; force it away from the middle",
    "Ball Screen": "Pick one ball-screen coverage and stay in it; no middle",
    "Down Screen": "Lock and trail; bump the cutter off the screen",
    "Stagger": "Trail the first screen, top-lock the second",
    "Screen the Screener": "Talk it early; switch the second screen if we must",
    "Flare": "Top-lock the flare; screener's man shows",
    "Curl": "Trail tight and have the big wall the curl",
    "Pat Miller": "Walk through it Monday -- their signature action",
    "Grenade": "Get into the handoff before it becomes a pick-and-roll",
    "Hammer": "Weak-side corner defender stays home; no help from the corner",
    "Zoom": "Chase over the pin-down and jump the handoff",
    "Twirl": "Trail the twirl cut; big stays connected",
    "IVO": "Deny the Iverson cut across the elbows",
    "Scissors": "Communicate the split; no switching into mismatches",
    "Breddy": "Walk through the inbounds alignment and assignments",
    "Lob": "Help side sits on the rim; inbounder's man turns and faces",
    "Post Touch": "Three-quarter front; dig from the passer",
    "ISO": "Gap help, make him score over a crowd",
    "Double Drag": "Talk both screens; tag the roller",
}
_gp_pcs = _gp_load("uww_play_call_summary")
_gp_pc = _gp_load("uww_play_calls")

# ---- Minimum tagged possessions before a split is reported as real rather than left as sample ----------
# One place for every floor in this cell. These used to be defined inline next to each table, which meant
# four related tables quietly disagreed about how thin a sample is too thin to read. Raise them together
# once there's more film; a row below its floor falls back to sample data rather than reporting a
# confident-looking percentage off two or three clips.
MIN_USES = {
    "defense_by_situation": 4,   # situation x defense cross-tab: possessions in ONE situation
    "shot_clock": 4,             # possessions in one shot-clock bucket
    "ball_screen_coverage": 3,   # possessions against one named coverage
    "personnel_grouping": 4,     # possessions with one personnel type on the floor
    "game_situation": 4,         # possessions in one game-situation bucket
}
_DEF_MIN_USES = MIN_USES["defense_by_situation"]
_SC_MIN_USES = MIN_USES["shot_clock"]
_BSC_MIN_USES = MIN_USES["ball_screen_coverage"]
_PG_MIN_USES = MIN_USES["personnel_grouping"]
_GS_MIN_USES = MIN_USES["game_situation"]

_sets_real = []
_film_real = []
if not _gp_pcs.empty and {"side", "level", "name"}.issubset(_gp_pcs.columns):
    _opp_calls = _gp_pcs[(_gp_pcs["side"] == "Opponent") & (_gp_pcs["level"] == "Play call")
                         & (_gp_pcs["scouted_opponent"].astype(str) == str(_gp_short))]
    _opp_calls = _opp_calls[~_opp_calls["name"].astype(str).str.contains("unspecified", na=False)]
    _opp_calls = _opp_calls.sort_values(["uses", "ppp"], ascending=[False, False])
    # Half-court sets first, then inbounds/ATO, so the table reads the way a walkthrough runs.
    _half = _opp_calls[_opp_calls["situation"].astype(str) == "Half court"].head(8)
    _oob = _opp_calls[_opp_calls["situation"].astype(str) != "Half court"].head(6)
    for _, r in pd.concat([_half, _oob]).iterrows():
        if int(r["uses"]) < 2:
            continue
        _ppp = f", {r['ppp']:.2f} PPP" if pd.notna(r.get("ppp")) else ""
        _where = f" -- {r['top_location']}" if isinstance(r.get("top_location"), str) and r["top_location"] else ""
        _sets_real.append([
            _gp_short, r["situation"], r["name"], r.get("top_player"),
            (str(r.get("top_action") or "") + _where).strip(" -") or "--",
            f"{int(r['uses'])} uses in {int(r['games'])} games{_ppp}",
            _GP_COVERAGE_BY_ACTION.get(str(r.get("top_action")), ""),
            str(r.get("game_codes") or ""),
        ])
    for _, r in pd.concat([_half.head(4), _oob.head(2)]).iterrows():
        _film_real.append([_gp_short, f"{r['name']} ({r['situation']})", int(r["uses"]),
                           "Whole team" if r["situation"] != "Half court" else "Whole team -- scout team runs it"])

_sets_cols = ["opponent", "situation", "set_name", "primary_player", "action", "frequency", "our_call", "film_ref"]
_sets_sample = [
    [_gp_short, "Half court", "5-Out Motion", _S(_gp_driver), "Drive-and-kick off a dribble handoff at the top",
     "Base offense (~40%)", "Gap help, no middle drives, close out short", "Gm 2, 1st half"],
    [_gp_short, "Half court", "Horns Flare", _S(_gp_shooter), "Elbow ball screen, weak-side flare for the shooter",
     "3-4x a half", "Top-lock the flare; switch 4-5 on the elbow screen", "Gm 1, 2nd half"],
    [_gp_short, "Half court", "Post Split", _S(_gp_big), "Entry to the block, split cut above it",
     "2-3x a half", "Three-quarter front; dig from the passer", "Gm 3, 1st half"],
    [_gp_short, "Half court", "Spain PnR", _S(_gp_handler), "Ball screen with a back-screen on the roller's man",
     "Late clock", "Ice the ball screen; talk the back-screen early", "Gm 4, 2nd half"],
    [_gp_short, "BLOB", "Box Up", _S(_gp_shooter), "Stagger to the corner, big seals the rim",
     "Most BLOBs", "Switch everything on the box; bump the sealer", "Gm 2"],
    [_gp_short, "SLOB", "Stack Lob", _S(_gp_big), "Stack at the elbow, back-screen lob to the rim",
     "Under 5:00", "Help side sits on the rim; no top-side denial", "Gm 1"],
    [_gp_short, "ATO", "Elevator", _S(_gp_shooter), "Elevator doors at the top of the key for a catch-and-shoot",
     "Out of timeouts", "Chase over the top; the screener's man sits in the doors", "Gm 3"],
    [_gp_short, "Press break", "4-Across", _S(_gp_handler), "Four across the free-throw line, inbounder runs baseline",
     "vs full-court pressure", "Deny the first pass to the handler; trap the catch", "Gm 4"],
    [_gp_short, "End of game", "Iso-High Ball Screen", _S(_gp_driver), "Clear-out, late high ball screen with 8 on the clock",
     "Last possession", "Show and recover; no fouling on the drive", "Gm 2"],
]
opp_sets = _gp_write("opp_sets", _sets_cols, _sets_sample, real_rows=_sets_real)

_def_cols = ["opponent", "item", "what_they_do", "how_we_attack"]
_def_sample = [
    [_gp_short, "Base defense", "Man-to-man about 80% of possessions; 2-3 zone out of timeouts",
     "Have a zone offense called from the bench on every dead ball"],
    [_gp_short, "Ball-screen coverage", "Hard hedge and recover", "Short roll to the free-throw line; slip early"],
    [_gp_short, "Handoffs", "Switch", "Keep the ball and attack the slower defender; re-screen"],
    [_gp_short, "Post defense", "Play behind, dig from the passer", "Swing it after the dig; shooter relocates"],
    [_gp_short, "Help rules", "Strong-side low man helps on drives", "Corner stays filled; baseline drift"],
    [_gp_short, "Pressure", "1-2-1-1 after made free throws, late halves", "Middle flash, ball reversal, attack 4-on-3"],
]
# ---- REAL: what their defense actually shows, from clips where THEY were the defense --------------
# This table had no real_rows wiring at all -- it was sample-only regardless of what was tagged, which is
# why it stayed empty even after Aurora's defense was tagged. The scheme text (how_we_attack) is still a
# coaching judgement and stays staff-input, but WHAT they do is now read off the film.
# Source is defense_PLAYED on opponent-side clips: possessions where the other team had the ball and this
# opponent was defending. defense_faced would be the other team's scheme under this opponent's name.
_def_real = []
_OPPD_MIN = 5
if not _gp_pc.empty and "defense_played" in _gp_pc.columns:
    _od = _gp_pc[(_gp_pc["side"] == "Opponent")
                 & (_gp_pc["scouted_opponent"].astype(str) == str(_gp_short))
                 & (_gp_pc["decode_quality"] != "Needs review")
                 & _gp_pc["defense_played"].notna()]
    if len(_od) >= _OPPD_MIN:
        _base = _od["defense_played"].astype(str).value_counts()
        _pct = round(100 * int(_base.iloc[0]) / int(_base.sum()))
        _second = (f"; also {_base.index[1]} ({round(100 * int(_base.iloc[1]) / int(_base.sum()))}%)"
                   if len(_base) > 1 else "")
        _def_real.append([_gp_short, "Base defense",
                          f"{_base.index[0]} on {_pct}% of {int(_base.sum())} tagged possessions{_second}",
                          ""])
        if "coverage_played" in _od.columns:
            _cv = _od[_od["coverage_played"].notna() & ~_od["coverage_played"].astype(str).str.strip().str.lower().isin(["", "nan", "none"])]["coverage_played"] \
                .astype(str).value_counts()
            if len(_cv):
                _def_real.append([_gp_short, "Ball-screen coverage",
                                  ", ".join(f"{n} ({int(c)}x)" for n, c in _cv.head(3).items()), ""])
        if "press_played" in _od.columns and int(_od["press_played"].sum()):
            _pf = _od[_od["press_played"].astype(bool)]
            _forms = (_pf["press_formation_played"].dropna().astype(str).value_counts()
                      if "press_formation_played" in _pf.columns else pd.Series(dtype=int))
            _def_real.append([_gp_short, "Pressure",
                              f"Pressed on {len(_pf)} of {len(_od)} tagged possessions"
                              + (f" -- {', '.join(_forms.index[:2])}" if len(_forms) else ""), ""])
opp_defense = _gp_write("opp_defense", _def_cols, _def_sample, real_rows=_def_real)

# Diagnostic: say exactly why this table is or isn't real, since "tagged but still empty" has bitten here.
if _gp_pc.empty:
    print("  opp_defense: uww_play_calls is empty -- staying sample.")
elif "defense_played" not in _gp_pc.columns:
    print("  opp_defense: no defense_played column -- re-run from the play-calls cell so possession_side "
          "and the faced/played split get built. Staying sample.")
elif not _def_real:
    _oc = _gp_pc[(_gp_pc["side"] == "Opponent") & (_gp_pc["scouted_opponent"].astype(str) == str(_gp_short))]
    _n_faced = int(_oc["defense_faced"].notna().sum()) if "defense_faced" in _oc.columns else 0
    _n_played = int(_oc["defense_played"].notna().sum()) if "defense_played" in _oc.columns else 0
    print(f"  opp_defense: {_n_played} clip(s) tagged with a defense {_gp_short} PLAYED "
          f"(need {_OPPD_MIN}+), and {_n_faced} tagged with a defense they FACED -- staying sample.")
    if _n_played == 0 and _n_faced > 0:
        print("    ^ Every defense tag in opponent_plays.csv landed on an OFFENSIVE possession "
              f"(Team = {_gp_short}). If those clips are meant to be {_gp_short}'s own defense, the Team "
              "column is naming the team being scouted rather than the team with the ball -- see the "
              "possession_side note in the play-calls cell.")
else:
    print(f"  opp_defense: real data for {len(_def_real)} item(s).")

_pers_cols = ["opponent", "player", "jersey", "position", "height", "hand", "class_year", "status",
              "games_on_film", "photo_url"]
_pers_sample = []
_used_numbers = set()
for _i, r in _gp_opp.head(10).iterrows():
    _num_options = [n for n in list(range(0, 35)) if n not in _used_numbers]
    _jersey = _gp_pick(r["player"] + "#", _num_options)
    _used_numbers.add(_jersey)
    _three_share = (r["FG3A"] / r["FGA"]) if r.get("FGA") else 0
    if r["player"] == _gp_big or (r["REB"] / max(r["games"], 1) >= 6 and _three_share < 0.15):
        _pos, _hts = "F/C", ["6-7", "6-8", "6-9"]
    elif _three_share >= 0.4 or r["AST"] / max(r["games"], 1) >= 2:
        _pos, _hts = "G", ["5-11", "6-1", "6-2", "6-3"]
    else:
        _pos, _hts = "W", ["6-4", "6-5", "6-6"]
    _thin = _gp_team_games > 1 and r["games"] < _GP_THIN_GAME_SHARE * _gp_team_games
    _pers_sample.append([
        _gp_short, r["player"], str(_jersey), _pos,
        _gp_pick(r["player"] + "h", _hts), _gp_pick(r["player"] + "L", ["R", "R", "R", "R", "L"]),
        _gp_pick(r["player"] + "c", ["Fr.", "So.", "Jr.", "Sr."]),
        "Confirm -- limited film" if _thin else "Available",
        # games_on_film is REAL even inside a sample section; the brief labels the column as such.
        f"{int(r['games'])} of {_gp_team_games}" if _gp_team_games else str(int(r["games"])),
        None,  # no photo without a real roster scrape
    ])

# ---- REAL personnel details from the live FastScout roster scrape (see the "Roster pages" cell), when it
# found this opponent. jersey/position/height/class_year/photo are real; hand and status are left BLANK
# rather than guessed -- the roster page doesn't carry either, and this table is either fully real or fully
# sample (never a mix), so a blank here is honest about what the source actually has.
#
# CONFIRMED BUG (fixed here): the roster page lists everyone on the roster, including players who haven't
# recorded a single minute in a game we have box-score data for -- a live run surfaced one by name ("Wifi
# Chin") with an incorrect photo. Photo-to-player pairing is done by POSITION on the page (see the roster
# cell's own docstring on this risk), and a zero-minute/inactive player is exactly the case most likely to
# sit in a different part of the page (a "not active" group) where that positional pairing breaks -- so
# these players are pulled OUT of the table entirely (no photo shown, no chance of a wrong one) and named in
# one summary line underneath instead, rather than risk a bad photo standing next to a real name.
#
# CONFIRMED BUG (fixed here): the roster page renders names ALL CAPS ("DEVON RICHARDSON"), while the box
# score has them title-cased ("Devon Richardson"). Matching on the exact string meant NOBODY matched -- the
# entire roster, active players included, landed in the "no minutes" line. Match on a case/whitespace-
# normalized key instead, and prefer the box score's own casing for display since it's already correct;
# _pers_titlecase is a fallback only for a player the box score has never seen at all.
_PERS_NAME_FIX = {"II": "II", "III": "III", "IV": "IV", "JR": "Jr.", "SR": "Sr."}


def _pers_norm(name):
    return re.sub(r"\s+", " ", str(name)).strip().lower()


def _pers_titlecase(name):
    """ALL CAPS -> Title Case for a player with no box-score entry to borrow proper casing from. Simple
    word-by-word title-casing -- doesn't special-case McEwen-style names, so double-check those by eye."""
    out = []
    for word in str(name).strip().split():
        key = word.rstrip(".").upper()
        out.append(_PERS_NAME_FIX[key] if key in _PERS_NAME_FIX else (word[:1].upper() + word[1:].lower()))
    return " ".join(out)


_live_ros = _gp_load("uww_live_rosters")
_pers_real = []
_pers_no_minutes = []
if not _live_ros.empty and "team" in _live_ros.columns:
    _my_ros = _live_ros[_live_ros["team"].astype(str) == str(_gp_short)]
    if not _my_ros.empty:
        _has_min_col = "MIN" in _gp_opp.columns
        _min_by_norm = ({_pers_norm(p): m for p, m in _gp_opp.set_index("player")["MIN"].items()}
                        if _has_min_col else {})
        _games_by_norm = {_pers_norm(r["player"]): (int(r["games"]), _gp_team_games, r["player"])
                          for _, r in _gp_opp.iterrows()}
        for _, r in _my_ros.iterrows():
            _key = _pers_norm(r["name"])
            _mins = _min_by_norm.get(_key)
            _played = (_mins is not None and _mins > 0) if _has_min_col else (_key in _games_by_norm)
            _gof = _games_by_norm.get(_key)
            _display_name = _gof[2] if _gof else _pers_titlecase(r["name"])
            if not _played:
                _pers_no_minutes.append(_display_name)
                continue
            _pers_real.append([
                _gp_short, _display_name, r.get("jersey_number"), r.get("position"), r.get("height"), "",
                r.get("class_year"), "",
                f"{_gof[0]} of {_gof[1]}" if _gof and _gof[1] else "",
                r.get("photo_url"),
            ])

opp_personnel = _gp_write("opp_personnel", _pers_cols, _pers_sample, real_rows=_pers_real)

# One real row per opponent, always (never sample-gated): the names pulled out of the table above. Rendered
# as a single summary sentence under Personnel Details rather than full rows -- a player is worth naming so
# the staff knows he's on the roster, but a blank/guessed row for him would overstate what's actually known.
roster_no_minutes = pd.DataFrame(
    [{"opponent": _gp_short, "names": ", ".join(_pers_no_minutes), "count": len(_pers_no_minutes)}]
    if _pers_no_minutes else [], columns=["opponent", "names", "count"])
roster_no_minutes.to_csv(os.path.join(APP_DATA_DIR, "uww_roster_no_minutes.csv"), index=False)

_zone_cols = ["opponent", "player", "rim", "paint_non_rim", "midrange", "corner_3", "above_break_3"]
_zone_sample = []
for _, r in _gp_opp.head(5).iterrows():
    _t = round(100 * r["FG3A"] / r["FGA"]) if r.get("FGA") else 0  # three share is REAL
    _c3 = round(_t * _gp_pick(r["player"] + "z", [0.3, 0.4, 0.5]))
    _two = 100 - _t
    _rim = round(_two * _gp_pick(r["player"] + "r", [0.45, 0.55, 0.65]))
    _mid = round((_two - _rim) * 0.5)
    _zone_sample.append([_gp_short, r["player"], _rim, _two - _rim - _mid, _mid, _c3, _t - _c3])
opp_shot_zones = _gp_write("opp_shot_zones", _zone_cols, _zone_sample)

# ---- REAL per-player shot profile, from the play-by-play ----------------------------------------------
# The zone table above is a placeholder: only its three-point share is real, and rim / paint / mid / corner
# are a pseudo-random split. The play-by-play CAN say something real about location, though -- the text of
# every make and miss says whether a two was a layup/dunk/tip or a jumper. So each player gets an honest
# three-way split: AT THE RIM, OTHER TWOS (jumpers, hooks, floaters), and THREES, with FG% in each. Coarser
# than five zones, but every number is real. Feeds the roster's per-player shot line in the brief.
# player_shot_zones() is defined in the scouting-notes cell -- ONE calculation shared by the roster's Driver
# read and this table, so a player called a driver in the brief always matches his row in the app.
_prof_rows = (player_shot_zones(_gp_load("uww_opponent_prior_games_pbp"), _gp_short, _gp_short, "Opponent")
              + player_shot_zones(_gp_load("uww_pbp_events"), "UW-Whitewater", _gp_short, "UWW"))
player_shot_profile = pd.DataFrame(_prof_rows, columns=[
    "opponent", "side", "player", "fga", "rim_att", "rim_share", "rim_fg", "other2_att", "other2_share",
    "other2_fg", "three_att", "three_share", "three_fg"])
player_shot_profile.to_csv(os.path.join(APP_DATA_DIR, "uww_player_shot_profile.csv"), index=False)
print(f"  player_shot_profile: {int((player_shot_profile['side'] == 'Opponent').sum())} of theirs, "
      f"{int((player_shot_profile['side'] == 'UWW').sum())} of ours (rim / other 2 / three, from play-by-play).")

_tend_cols = ["opponent", "item", "detail"]
_tend_sample = [
    [_gp_short, "Transition", "Push after misses about half the time; walk it up after makes"],
    [_gp_short, "Offensive glass", f"Send 2-3 to the glass; {_S(_gp_big)} crashes every shot"],
    [_gp_short, "Timeouts", "Head coach calls the first one early if down 6+; saves two for the last 4:00"],
    [_gp_short, "End of half", "Hold for one; iso the best scorer at the top with 8 seconds left"],
    [_gp_short, "Officials", "Crew not yet assigned -- check the conference site Tuesday"],
]
opp_tendencies = _gp_write("opp_tendencies", _tend_cols, _tend_sample)

# ======================================================================================================
# SAMPLE (until staff input exists): our side
# ======================================================================================================
_match_cols = ["opponent", "their_player", "our_defender", "backup", "note"]
_match_sample = []
_us_starters = list(_gp_us["player"].head(5)) if not _gp_us.empty else []
_top_threat = None
if not _gp_opp.empty:
    _reg = _gp_opp[_gp_opp["games"] >= _GP_THIN_GAME_SHARE * max(_gp_team_games, 1)]
    _top_threat = (_reg if not _reg.empty else _gp_opp).sort_values("PTS", ascending=False)["player"].iloc[0]
_us_bench = list(_gp_us["player"].iloc[5:10]) if len(_gp_us) > 5 else []


# ======================================================================================================
# SAMPLE ONLY (no path to real data from current tagging): sections that show what richer film tagging
# would unlock. Each needs a field the tagging tool doesn't capture today -- see the note on each table.
# DEFENSE TYPE BY SITUATION and BALL SCREEN COVERAGE used to live in this block too, but the coaches'
# updated Title logic (see decode_defense_tag in the play-calls cell) now tags exactly this, so both moved
# below to the real-data section with everything else derived from uww_play_calls / uww_play_call_summary.
# ======================================================================================================
_def_type_cols = ["opponent", "situation", "primary_defense", "freq_pct", "secondary_defense", "note"]
_def_type_sample = [
    [_gp_short, "Half court", "Man-to-man", 78, "2-3 zone (after a timeout or a long defensive stretch)",
     f"Switches 1-4, doesn't switch {_S(_gp_big)}'s matchup"],
    [_gp_short, "BLOB", "Man-to-man", 60, "Box-and-1 on our best shooter", "Denies the first pass hard"],
    [_gp_short, "SLOB", "Man-to-man", 85, "", "Same coverage as half court, no separate call seen"],
    [_gp_short, "After a made basket (press)", "1-2-1-1 full-court", 30, "Man-to-man (no press)",
     "Presses more in the 4th when trailing"],
]

# ---- REAL defense-by-situation, cross-tabbed straight from the per-clip table (uww_play_calls) rather
# than uww_play_call_summary -- that table only aggregates one column at a time, and this needs TWO
# (situation x defense_type together). A situation needs at least _DEF_MIN_USES tagged possessions with a
# defense_type before it's shown; below that it stays sample rather than reporting a "100%" read on 2 clips.
_def_type_real = []
# defense_PLAYED, not defense_type: this table is what the opponent's own defense runs. The raw
# defense_type on an opponent-side clip is what their OFFENSE faced -- i.e. the other team's defense --
# so reading it here reported the wrong team's scheme under this opponent's name.
if not _gp_pc.empty and {"side", "scouted_opponent", "play_situation", "defense_played", "decode_quality"}.issubset(_gp_pc.columns):
    _dpc = _gp_pc[(_gp_pc["side"] == "Opponent") & (_gp_pc["scouted_opponent"].astype(str) == str(_gp_short))
                  & _gp_pc["defense_played"].notna() & (_gp_pc["decode_quality"] != "Needs review")]
    for _situ, _grp in (_dpc.groupby("play_situation") if not _dpc.empty else []):
        _counts = _grp["defense_played"].value_counts()
        if _counts.empty or int(_counts.sum()) < _DEF_MIN_USES:
            continue
        _freq = round(100 * int(_counts.iloc[0]) / int(_counts.sum()))
        _secondary = _counts.index[1] if len(_counts) > 1 else ""
        _press_n = int(_grp["press_played"].sum()) if "press_played" in _grp.columns else 0
        _note = f"{int(_counts.sum())} tagged possession{'s' if _counts.sum() != 1 else ''}"
        if _press_n:
            _note += f"; press seen on {_press_n}"
        _def_type_real.append([_gp_short, _situ, _counts.index[0], _freq, _secondary, _note])
if _gp_pc.empty:
    print("  defense_by_situation: uww_play_calls is empty -- staying sample.")
elif "defense_played" not in _gp_pc.columns:
    print("  defense_by_situation: uww_play_calls has no defense_type column -- the notebook needs a full "
          "re-run from the play-calls cell so the new Title tagging gets decoded. Staying sample.")
elif not _def_type_real:
    _opp_def_n = int(((_gp_pc["side"] == "Opponent") & (_gp_pc["scouted_opponent"].astype(str) == str(_gp_short))
                      & _gp_pc["defense_played"].notna()).sum())
    print(f"  defense_by_situation: {_opp_def_n} opponent clip(s) with a defense tag for {_gp_short}, none of "
          f"which reached {_DEF_MIN_USES}+ in any one situation -- staying sample. (0 clips usually means "
          f"opponent_plays.csv hasn't been re-tagged with the new Title format yet.)")
else:
    print(f"  defense_by_situation: real data for {len(_def_type_real)} situation(s).")
defense_by_situation = _gp_write("defense_by_situation", _def_type_cols, _def_type_sample, real_rows=_def_type_real)

_clock_cols = ["opponent", "clock_situation", "freq_pct", "ppp", "fg_pct", "note"]
_clock_sample = [
    [_gp_short, "Early clock (0-9 sec used)", 22, 1.18, 54, "Mostly transition and early ball screens"],
    [_gp_short, "Organized offense (10-19 sec used)", 55, 0.94, 41, f"Their half-court sets, {_S(_gp_shooter)} runs off screens here"],
    [_gp_short, "Late clock (20+ sec used)", 23, 0.71, 33, f"{_S(_gp_driver)} isolation when the set breaks down"],
]

# ---- REAL shot-clock tendencies, estimated from the game clock using NCAA men's shot-clock rules and
# cross-referenced against each matched clip's decoded play call (see the "Play calls" cell -- shot_clock_
# situation, level="Shot clock" in uww_play_call_summary). Only matched clips carry an estimate.
_clock_real = []
if not _gp_pcs.empty and {"side", "level", "name", "uses"}.issubset(_gp_pcs.columns):
    _sc_rows_df = _gp_pcs[(_gp_pcs["side"] == "Opponent") & (_gp_pcs["level"] == "Shot clock")
                          & (_gp_pcs["scouted_opponent"].astype(str) == str(_gp_short))]
    _sc_order = ["Early clock (0-9 sec used)", "Organized offense (10-19 sec used)", "Late clock (20+ sec used)"]
    _sc_total_uses = _sc_rows_df["uses"].sum()
    for _bucket in _sc_order:
        _row = _sc_rows_df[_sc_rows_df["name"] == _bucket]
        if _row.empty or int(_row.iloc[0]["uses"]) < _SC_MIN_USES:
            continue
        _r = _row.iloc[0]
        _freq = round(100 * _r["uses"] / _sc_total_uses) if _sc_total_uses else None
        _note = f"{int(_r['uses'])} tagged possessions"
        if isinstance(_r.get("top_action"), str):
            _note += f" -- most often {_r['top_action']}"
        if isinstance(_r.get("top_player"), str):
            _note += f" ({_r['top_player']})"
        _clock_real.append([_gp_short, _bucket, _freq, _r.get("ppp"), _r.get("fg_pct"), _note])

shot_clock_tendencies = _gp_write("shot_clock_tendencies", _clock_cols, _clock_sample, real_rows=_clock_real)

_matchup_hist_cols = ["opponent", "their_player", "defended_by", "possessions", "ppp_allowed", "note"]
_matchup_hist_sample = [
    [_gp_short, _S(_gp_driver), (_us_starters[0] if _us_starters else ""), 18, 0.83, "Best matchup on file -- length bothers his first step"],
    [_gp_short, _S(_gp_driver), (_us_starters[1] if len(_us_starters) > 1 else ""), 9, 1.22, "Got switched onto him twice in the 4th and gave up 6 straight"],
    [_gp_short, _S(_gp_shooter), (_us_starters[2] if len(_us_starters) > 2 else ""), 14, 0.71, "Chases well over screens"],
    [_gp_short, _S(_gp_big), (_us_starters[4] if len(_us_starters) > 4 else ""), 21, 0.95, "Gives up deep position early in the shot clock"],
]
matchup_history = _gp_write("matchup_history", _matchup_hist_cols, _matchup_hist_sample)

_counters_cols = ["opponent", "set", "when_we_take_it_away", "their_counter", "our_adjustment"]
_counters_sample = [
    [_gp_short, "4-1 Ball Screen", "We show hard and force it left", "Reject and drive right instead",
     "Have the weak-side big ready to step up, not just the on-ball defender"],
    [_gp_short, "Hi-Lo DHO", "We deny the handoff", f"{_S(_gp_big)} seals and posts instead",
     "Front early rather than three-quarter once the handoff is denied"],
    [_gp_short, "BLOB Box Curl", "We switch the curl", "They throw the skip pass to the opposite corner",
     "Tag the low man to the corner on the switch"],
]
play_counters = _gp_write("play_counters", _counters_cols, _counters_sample)

_bsc_cols = ["opponent", "coverage", "freq_pct", "ppp", "fg_pct", "note"]
_bsc_sample = [
    [_gp_short, "Drop", 45, 0.87, 39, f"Big sags to the paint -- {_S(_gp_shooter)} pulls up off it"],
    [_gp_short, "Hard hedge", 25, 1.05, 47, "Big shows well but recovers late -- short roll is open behind it"],
    [_gp_short, "Switch", 15, 0.95, 43, f"Switches 1 through 4, not onto {_S(_gp_big)}"],
    [_gp_short, "Ice (side ball screens)", 10, 0.62, 31, "Forces it baseline; help comes from the nail"],
    [_gp_short, "Blitz", 5, 1.30, 50, f"Live-ball turnover risk if {_S(_gp_handler)} splits it"],
]

# ---- REAL ball-screen coverage, from uww_play_call_summary's "Ball screen coverage" level (level built
# in the play-calls cell from decode_defense_tag's defense_coverage field: Switch / Hedge / Soft Hedge /
# Ice / Drop / Deny / Jam -- a clip tagged with more than one, e.g. "Drop+Press", counts under its own
# combined bucket rather than being split). Same shape and threshold pattern as shot_clock_tendencies above.
_bsc_real = []
_bsc_rows_df = pd.DataFrame()
_bsc_cols_ok = not _gp_pcs.empty and {"side", "level", "name", "uses"}.issubset(_gp_pcs.columns)
if _bsc_cols_ok:
    # DEFENSIVE rows: this is the coverage they played, which only exists on possessions where they were
    # defending. play_call_summary now stamps possession_side for exactly this reason.
    _bsc_rows_df = _gp_pcs[(_gp_pcs["side"] == "Opponent") & (_gp_pcs["level"] == "Ball screen coverage played")
                           & (_gp_pcs["scouted_opponent"].astype(str) == str(_gp_short))]
    if "possession_side" in _bsc_rows_df.columns:
        _bsc_rows_df = _bsc_rows_df[_bsc_rows_df["possession_side"].astype(str) == "Defense"]
    _bsc_total_uses = _bsc_rows_df["uses"].sum()
    for _, _r in _bsc_rows_df.sort_values("uses", ascending=False).iterrows():
        if int(_r["uses"]) < _BSC_MIN_USES:
            continue
        _freq = round(100 * _r["uses"] / _bsc_total_uses) if _bsc_total_uses else None
        _note = f"{int(_r['uses'])} tagged possession{'s' if _r['uses'] != 1 else ''}"
        if isinstance(_r.get("top_player"), str):
            _note += f" -- most often against {_r['top_player']}"
        _bsc_real.append([_gp_short, _r["name"], _freq, _r.get("ppp"), _r.get("fg_pct"), _note])
if _gp_pcs.empty:
    print("  ball_screen_coverage: uww_play_call_summary is empty -- staying sample.")
elif not _bsc_cols_ok or "Ball screen coverage played" not in set(_gp_pcs.get("level", [])):
    print("  ball_screen_coverage: no \"Ball screen coverage\" level in uww_play_call_summary -- the notebook "
          "needs a full re-run from the play-calls cell so the new Title tagging gets decoded. Staying sample.")
elif not _bsc_real:
    print(f"  ball_screen_coverage: {int(_bsc_rows_df['uses'].sum()) if not _bsc_rows_df.empty else 0} tagged "
          f"clip(s) with a coverage call for {_gp_short}, none of which reached {_BSC_MIN_USES}+ on any one "
          f"coverage -- staying sample. (0 clips usually means opponent_plays.csv hasn't been re-tagged with "
          f"the new Title format yet.)")
else:
    print(f"  ball_screen_coverage: real data for {len(_bsc_real)} coverage type(s).")
# CONFIRMED CHANGE (requested): the structured tags pair every coverage with the screen it answered, so
# BALL SCREEN COVERAGE now reads ball screens only from uww_screen_coverage_summary. The older source above
# (defense_coverage on the clip) mixes in off-ball calls like Top Lock since the new tags, so it is only the
# fallback when no structured coverage exists for this opponent yet.
_scv_sum = globals().get("screen_coverage_summary", pd.DataFrame())
if isinstance(_scv_sum, pd.DataFrame) and not _scv_sum.empty:
    _scv_bs = _scv_sum[(_scv_sum["level"] == "Screen x coverage") & (_scv_sum["perspective"] == "Opponent defense")
                       & (_scv_sum["screen_family"] == "Ball screen")
                       & (_scv_sum["scouted_opponent"].astype(str) == str(_gp_short))]
    if not _scv_bs.empty:
        _scv_tot = _scv_bs["uses"].sum()
        _bsc_real = []
        for _cov, _g in _scv_bs.groupby("coverage"):
            _u = int(_g["uses"].sum())
            _known = _g["poss_with_points"].sum()
            _ppp = round((_g["ppp"].fillna(0) * _g["poss_with_points"]).sum() / _known, 2) if _known else None
            _fga = _g["fga"].sum()
            _fg = round((_g["fg_pct"].fillna(0) * _g["fga"]).sum() / _fga, 1) if _fga else None
            _who = _g.sort_values("uses", ascending=False)["top_defender"].dropna()
            _note = (f"{_u} tagged ball screen{'s' if _u != 1 else ''}"
                     + (f" -- most often by {_who.iloc[0]}" if len(_who) else "")
                     + (" (thin sample)" if _scv_tot < SCREEN_COVERAGE_RULES["thin_screens"] else ""))
            _bsc_real.append([_gp_short, _cov, round(100 * _u / _scv_tot) if _scv_tot else None, _ppp, _fg, _note])
        _bsc_real.sort(key=lambda r: -(r[2] or 0))
        print(f"  ball_screen_coverage: real data from structured tags -- {int(_scv_tot)} ball screen(s).")
ball_screen_coverage = _gp_write("ball_screen_coverage", _bsc_cols, _bsc_sample, real_rows=_bsc_real)

# ---- Tempo & transition (REAL, from the play-by-play -- needs no play tagging at all) ------------------
# Pre-film question the brief never answered: how fast do they want to play, and how much of their offense
# comes before the defense is set. Possessions are the standard estimate (FGA - OREB + TO + 0.475*FTA),
# averaged per game; transition share comes from the shot-clock estimate already on the tagged clips.
_tempo_cols = ["opponent", "metric", "value", "note"]
_tempo_sample = [
    [_gp_short, "Possessions per game", 71.4, "Sample -- needs their prior-game box scores"],
    [_gp_short, "Points per possession", 1.07, "Sample"],
    [_gp_short, "Early-offense share", 38, "Sample -- % of tagged possessions shooting inside 10 seconds"],
]
_tempo_real = []

def _team_game_totals(box, team):
    """One row per game: the team's summed box score, INCLUDING the synthetic TEAM row.

    CONFIRMED BUG (fixed here): the earlier version used the TEAM row ALONE whenever one existed. That row
    is synthetic -- it only carries bare team-level turnovers (see the pbp box score cell), with FGA, FTA,
    OREB and PTS all zero -- so possessions came out as a couple of turnovers a game and PPP as roughly
    zero. The TEAM row has to be ADDED to the player rows, never used instead of them.
    """
    if box.empty or "team" not in box.columns:
        return pd.DataFrame()
    own = box[box["team"].astype(str) == str(team)]
    if own.empty:
        return own
    cols = [c for c in ("FGA", "OREB", "TO", "FTA", "PTS") if c in own.columns]
    key = "game_date" if "game_date" in own.columns else None
    if not key:
        return pd.DataFrame()
    g = own.groupby(key, dropna=True)[cols].sum(numeric_only=True).reset_index()
    for c in ("FGA", "OREB", "TO", "FTA", "PTS"):
        if c not in g.columns:
            g[c] = pd.NA
    return g

def _possessions(g):
    """Standard estimate. Returns None rather than a wrong number when a required column is missing --
    a possession estimate without OREB overstates pace by the offensive-rebound count every game."""
    if g.empty or g[["FGA", "TO", "FTA", "OREB"]].isna().all().any():
        return None
    return (pd.to_numeric(g["FGA"], errors="coerce").fillna(0)
            - pd.to_numeric(g["OREB"], errors="coerce").fillna(0)
            + pd.to_numeric(g["TO"], errors="coerce").fillna(0)
            + 0.475 * pd.to_numeric(g["FTA"], errors="coerce").fillna(0))

_tb = _team_game_totals(_gp_load("uww_opponent_prior_games_box_score"), _gp_short)
_poss = _possessions(_tb)
if _poss is not None and _poss.sum() > 0:
    _n_games = len(_tb)
    _pts = pd.to_numeric(_tb["PTS"], errors="coerce").fillna(0)
    _tempo_real.append([_gp_short, "Possessions per game", round(float(_poss.mean()), 1),
                        f"Estimated over {_n_games} game(s): FGA - OREB + TO + 0.475*FTA"])
    _tempo_real.append([_gp_short, "Points per possession", round(float(_pts.sum() / _poss.sum()), 2),
                        f"Their scoring over {_n_games} game(s) of film"])
    # Our own pace from our own box, so the number has something to be compared against.
    _ub = _team_game_totals(_gp_load("uww_pbp_box_score"), "UW-Whitewater")
    _up = _possessions(_ub)
    if _up is not None and _up.sum() > 0:
        _tempo_real.append(["UW-Whitewater", "Possessions per game", round(float(_up.mean()), 1),
                            f"Our own pace over {len(_ub)} game(s)"])
    # Sanity bounds: college men's pace lives roughly 60-85. Anything outside is a data problem, not a
    # fast team, so say so on the run rather than let it reach the app looking plausible.
    if not (55 <= float(_poss.mean()) <= 90):
        print(f"  tempo_profile: {_gp_short} computed at {float(_poss.mean()):.1f} possessions/game -- outside "
              "the plausible range; check the prior-games box score before trusting it.")
elif not _tb.empty:
    print("  tempo_profile: box score is missing a column the possession estimate needs (FGA, OREB, TO or "
          "FTA) -- left as sample rather than reporting an inflated pace.")

# possession_side is a column in normal runs; guard with a Series default so a missing column can never
# turn into DataFrame.get() returning the bare string "Offense" (which has no .astype).
_ps = _gp_pc["possession_side"] if "possession_side" in _gp_pc.columns else pd.Series("Offense", index=_gp_pc.index)
if not _gp_pc.empty and "shot_clock_situation" in _gp_pc.columns:
    _tc = _gp_pc[(_gp_pc["side"] == "Opponent")
                 & (_ps.astype(str) != "Defense")
                 & (_gp_pc["offense_team"].astype(str) == str(_gp_short))
                 & _gp_pc["shot_clock_situation"].notna()]
    if len(_tc) >= 10:
        _early = _tc["shot_clock_situation"].astype(str).str.contains("Early", case=False, na=False).sum()
        _tempo_real.append([_gp_short, "Early-offense share", round(100 * _early / len(_tc)),
                            f"% of {len(_tc)} tagged possessions shooting inside 10 seconds"])
tempo_profile = _gp_write("tempo_profile", _tempo_cols, _tempo_sample, real_rows=_tempo_real)

# ---- Are they changing? (REAL) -------------------------------------------------------------------------
# Four games treated as one static profile hides a team that has switched what it does. Split their tagged
# possessions into an earlier half and a recent half and report only splits that actually MOVED. Needs
# enough games to be two-vs-two or better, and says so rather than reporting noise.
_trend_cols = ["opponent", "split", "earlier", "recent", "change", "note"]
_trend_sample = [
    [_gp_short, "Zone share of defense", "20%", "60%", "+40", "Sample -- needs more tagged games"],
]
_trend_real = []
_TREND_MIN_GAMES = 4
_TREND_MIN_MOVE = 10        # percentage points before a change is worth printing
if not _gp_pc.empty and "game_date" in _gp_pc.columns:
    _tr = _gp_pc[(_gp_pc["side"] == "Opponent") & _gp_pc["game_date"].notna()].copy()
    _games = sorted(_tr["game_date"].dropna().astype(str).unique())
    if len(_games) >= _TREND_MIN_GAMES:
        _half = len(_games) // 2
        _early_g, _recent_g = set(_games[:_half]), set(_games[_half:])
        _tr["_era"] = _tr["game_date"].astype(str).map(
            lambda g: "earlier" if g in _early_g else ("recent" if g in _recent_g else None))
        for _label, _col, _test in (
                ("Zone share of their defense", "defense_played",
                 lambda s: s.astype(str).str.contains("zone", case=False, na=False)),
                ("Press share of their defense", "press_played", lambda s: s.astype(bool)),
                ("Early-offense share", "shot_clock_situation",
                 lambda s: s.astype(str).str.contains("Early", case=False, na=False))):
            if _col not in _tr.columns:
                continue
            _vals = {}
            for _era in ("earlier", "recent"):
                _g = _tr[(_tr["_era"] == _era) & _tr[_col].notna()]
                if len(_g) >= 8:
                    _vals[_era] = 100 * _test(_g[_col]).sum() / len(_g)
            if len(_vals) == 2 and abs(_vals["recent"] - _vals["earlier"]) >= _TREND_MIN_MOVE:
                _trend_real.append([_gp_short, _label, f"{_vals['earlier']:.0f}%", f"{_vals['recent']:.0f}%",
                                    f"{_vals['recent'] - _vals['earlier']:+.0f}",
                                    f"First {_half} game(s) vs last {len(_games) - _half}"])
    else:
        print(f"  trend_profile: only {len(_games)} tagged game(s) -- needs {_TREND_MIN_GAMES}+ before an "
              f"earlier-vs-recent split says anything. Staying sample.")
trend_profile = _gp_write("trend_profile", _trend_cols, _trend_sample, real_rows=_trend_real)

_help_cols = ["opponent", "trigger", "who_rotates", "tendency", "note"]
_help_sample = [
    [_gp_short, "Drive to the rim", "Weak-side corner defender", "Rotates late -- 1-count behind the drive",
     "Corner three is there if the extra pass comes quickly"],
    [_gp_short, "Skip pass to the corner", "Nearest wing defender", "Closes out under control, no fly-bys",
     "Better to attack this closeout off the dribble than shoot into it"],
    [_gp_short, "Post entry", f"{_S(_gp_big)}'s man", "Digs hard from the top, occasionally leaves for a full double",
     "Kick to the dig's man when the double comes"],
    [_gp_short, "Roller on a ball screen", "Weak-side big", "Tags the roller consistently, X-out is a beat slow",
     "Second cutter behind the tag is open more than the roller itself"],
]
help_rotation_tendencies = _gp_write("help_rotation_tendencies", _help_cols, _help_sample)

_pg_cols = ["opponent", "personnel_grouping", "minutes_pct", "primary_actions_used", "note"]
_pg_sample = [
    [_gp_short, "Base five (one big)", 72, "4-1 Ball Screen, Hi-Lo DHO", "Their most-used grouping all four games"],
    [_gp_short, "Two-big lineup", 18, "Post touches, offensive rebounding",
     "Comes in for defensive stops, stays if it's working"],
    [_gp_short, "Small / shooting five (no true big)", 10, f"5 Out, ball screens for {_S(_gp_shooter)}",
     "Closing lineup when trailing"],
]

# ---- REAL personnel groupings, aggregated by TYPE (two bigs / base five / small-ball) rather than the
# literal 5-man unit -- the literal lineups are already broken out, player by player with their own keys,
# in Top Lineups, so this pools every lineup sharing a personnel profile instead of repeating those same
# five names. Type comes from the play-calls cell's own classifier (_pg_grouping_type there, based on each
# team's two highest-rebounding players in the play-by-play -- an approximation of "who plays big minutes,"
# not a roster-accurate position; see that cell's comment for the full caveat). Reads
# level="Personnel grouping type" in uww_play_call_summary. A clip only carries a type when it MATCHED a
# play-by-play event, so this covers only the tagged possessions that matched, not every clip.
_pg_real = []
if not _gp_pcs.empty and {"side", "level", "name", "uses"}.issubset(_gp_pcs.columns):
    # CONFIRMED BUG (fixed here): the table showed one grouping at 47% of minutes and nothing else, so more
    # than half their playing time was simply absent. Only types with _PG_MIN_USES tagged clips were listed --
    # a type with plenty of real MINUTES but few matched clips vanished entirely. Every type with minutes is
    # listed now; the tagged columns are blank when there aren't enough clips to say anything about them.
    _pg_rows_df = _gp_pcs[(_gp_pcs["side"] == "Opponent") & (_gp_pcs["level"] == "Personnel grouping type")
                          & (_gp_pcs["scouted_opponent"].astype(str) == str(_gp_short))].sort_values(
                              "uses", ascending=False)
    # Real minutes share by TYPE: classify each literal lineup in the season lineup box score the SAME way
    # (top-2 rebounders = bigs) and sum its real MIN into that type's bucket, rather than guessing.
    # CONFIRMED CHANGE (requested): groupings are now the play-calls cell's own labels -- "3G-2B",
    # "3G-1W-1B" from real roster positions, falling back to two-big/one-big/no-big for a team with no
    # roster positions on file. That cell also exports the lineup -> grouping map (uww_lineup_grouping), so
    # MINUTES are aggregated on exactly the rule the tagged clips were classified with, instead of this cell
    # classifying lineups a second time (which is how minutes and clips once landed on different groupings).
    _pg_map_df = _gp_load("uww_lineup_grouping")
    _pg_map = {}
    if not _pg_map_df.empty and {"lineup", "grouping"}.issubset(_pg_map_df.columns):
        _side_rows = _pg_map_df[_pg_map_df["side"] == "Opponent"] if "side" in _pg_map_df.columns else _pg_map_df
        _pg_map = {str(r["lineup"]): r["grouping"] for _, r in _side_rows.iterrows() if pd.notna(r["grouping"])}

    def _pg_type_for(lineup_str):
        return _pg_map.get(str(lineup_str))

    _pg_min_by_type = {}
    if not _lu.empty and "lineup" in _lu.columns and "MIN" in _lu.columns:
        _lu_typed = _lu.assign(_type=_lu["lineup"].apply(_pg_type_for))
        _pg_total_min = pd.to_numeric(_lu["MIN"], errors="coerce").sum()
        if _pg_total_min:
            _pg_min_by_type = (_lu_typed.assign(_min=pd.to_numeric(_lu_typed["MIN"], errors="coerce"))
                              .dropna(subset=["_type", "_min"]).groupby("_type")["_min"].sum()
                              .div(_pg_total_min).mul(100).round().to_dict())

    _pg_seen = set()
    for _, r in _pg_rows_df.iterrows():
        _type_name = str(r["name"])
        _pg_seen.add(_type_name)
        _calls = (_gp_pc[(_gp_pc["side"] == "Opponent") & (_gp_pc["personnel_grouping_type"] == _type_name)
                         & ~_gp_pc["play_call"].astype(str).str.contains("unspecified", na=False)
                         & _gp_pc["play_call"].notna()]["play_call"].value_counts().head(3)
                  if not _gp_pc.empty and "personnel_grouping_type" in _gp_pc.columns else pd.Series(dtype=int))
        if int(r["uses"]) < _PG_MIN_USES:
            _pg_real.append([_gp_short, _type_name, _pg_min_by_type.get(_type_name), "--",
                             f"Only {int(r['uses'])} tagged possession(s) -- too few to read"])
            continue
        _what = ", ".join(f"{n} ({int(c)}x)" for n, c in _calls.items()) or (r.get("top_action") or "--")
        _note = f"{int(r['uses'])} tagged possessions"
        if pd.notna(r.get("ppp")):
            _note += f", {r['ppp']:.2f} PPP"
        if pd.notna(r.get("team_ppp")):
            _note += f" (their overall {r['team_ppp']:.2f})"
        _pg_real.append([_gp_short, _type_name, _pg_min_by_type.get(_type_name), _what, _note])

    for _type_name, _pct in sorted(_pg_min_by_type.items(), key=lambda kv: -kv[1]):
        if _type_name in _pg_seen:
            continue
        _pg_real.append([_gp_short, _type_name, _pct, "--", "No tagged clips matched this grouping yet"])
    # Keep the table in a fixed, readable order rather than whatever the tagged counts happened to be.
    # Busiest grouping first -- with position shapes ("3G-2B") there's no fixed order to impose.
    _pg_real.sort(key=lambda row: -(row[2] or 0))

personnel_grouping = _gp_write("personnel_grouping", _pg_cols, _pg_sample, real_rows=_pg_real)

# ---- REAL: what each five-man unit actually runs, for the brief's Top Lineups (requested) --------------
# The sets tagged on possessions with that exact unit on the floor, so a lineup row can say what it runs
# rather than only how it scored.
_lu_calls_rows = []
if not _gp_pc.empty and "on_court_lineup" in _gp_pc.columns:
    _named_calls = _gp_pc[_gp_pc["play_call"].notna()
                          & ~_gp_pc["play_call"].astype(str).str.contains("unspecified", na=False)
                          & (_gp_pc["decode_quality"] != "Needs review")]
    for (_side_val, _lu), _grp in _named_calls.groupby(["side", "on_court_lineup"]):
        _vc = _grp["play_call"].value_counts().head(3)
        _pts = pd.to_numeric(_grp["points"], errors="coerce")
        _lu_calls_rows.append({
            "scouted_opponent": _gp_short, "side": _side_val, "lineup": str(_lu),
            "top_calls": ", ".join(f"{n} ({int(c)}x)" for n, c in _vc.items()),
            "tagged_possessions": len(_grp),
            "ppp": round(_pts.sum() / _pts.notna().sum(), 2) if _pts.notna().any() else None,
            "grouping": _pg_map.get(str(_lu)) if "_pg_map" in dir() else None})
lineup_play_calls = pd.DataFrame(_lu_calls_rows, columns=["scouted_opponent", "side", "lineup", "top_calls",
                                                          "tagged_possessions", "ppp", "grouping"])
lineup_play_calls.to_csv(os.path.join(APP_DATA_DIR, "uww_lineup_play_calls.csv"), index=False)

_reb_cols = ["opponent", "situation", "crash_pct", "who_crashes", "note"]
_reb_sample = [
    [_gp_short, "Miss by a non-shooter (paint attempt)", 65, _S(_gp_big) + " + ball-side wing",
     "Second-chance points mostly come from this situation"],
    [_gp_short, "Miss by their primary shooter (three)", 20, _S(_gp_big) + " only",
     "Everyone else gets back -- transition D opportunity for us"],
    [_gp_short, "Missed free throw", 40, _S(_gp_big), "Lines up early, boxes out inconsistently"],
]

# ---- REAL: who gets the rebound after a miss, straight from the play-by-play -------------------------
# Every miss is paired with the rebound that follows it (requested). No tagging needed: the play-by-play
# already records missed_shot / free_throw_missed and then rebound_offensive / rebound_defensive with the
# rebounder's name. Pairing walks forward from the miss inside the same game and stops at the first
# rebound; if another shot, a turnover or the next period comes first, that miss is left unpaired rather
# than credited to the wrong board. Team (deadball) rebounds count toward the rate but not toward "who".
#
# Two directions, because they answer different questions:
#   their misses   -> how hard THEY crash the offensive glass, and who does it
#   opponent misses -> who on their side secures the defensive board (who we have to box out)
_reb_real = []
_REB_MIN_MISSES = 8
# Pairing is rebound_pairs() from the Keys to Victory cell -- ONE implementation shared by the key, the
# brief's Bottom Line / roster reads and this table, so they can't disagree about who got a rebound.
_reb_pbp = _gp_load("uww_opponent_prior_games_pbp")
if not _reb_pbp.empty and {"event_type", "team", "game_date", "event_order"}.issubset(_reb_pbp.columns):
    _pairs = rebound_pairs(_reb_pbp, _gp_short)
    if not _pairs.empty:
        _is_them = _pairs["is_them"].astype(bool)

        def _who(df):
            _p = df["reb_player"].dropna().astype(str)
            _p = _p[~_p.str.upper().isin({"TEAM", ""})].value_counts()
            return ", ".join(f"{_S(n)} ({int(c)})" for n, c in _p.head(3).items())

        _order = ["Missed layup / dunk", "Missed two-point jumper", "Missed three", "Missed free throw"]
        for _dir, _mask, _want_off, _prefix in (
                ("their", _is_them, True, "Their"),
                ("opp", ~_is_them, False, "Opponent")):
            _d = _pairs[_mask]
            for _kind in _order + ["All misses"]:
                _k = _d if _kind == "All misses" else _d[_d["kind"] == _kind]
                _paired = _k[_k["offensive"].notna()]
                if len(_k) < _REB_MIN_MISSES or _paired.empty:
                    continue
                if _want_off:
                    # Their miss: an OFFENSIVE rebound is theirs -- that's their crash rate.
                    _got = _paired[_paired["offensive"] == True]
                    _pct = round(100 * len(_got) / len(_paired))
                    _label = f"{_prefix} {_kind.lower()}" if _kind != "All misses" else "All their misses"
                    _note = (f"{_pct}% offensive rebound on {len(_paired)} of {len(_k)} misses "
                             f"({len(_k) - len(_paired)} unpaired)")
                else:
                    # Opponent's miss: a DEFENSIVE rebound is theirs -- who secures it.
                    _got = _paired[_paired["offensive"] == False]
                    _pct = round(100 * len(_got) / len(_paired))
                    _label = f"{_prefix} {_kind.lower()}" if _kind != "All misses" else "All opponent misses"
                    _note = (f"They secure {_pct}% of {len(_paired)} opponent misses "
                             f"({len(_k) - len(_paired)} unpaired)")
                _reb_real.append([_gp_short, _label, _pct, _who(_got), _note])
    # Say exactly what happened, every run: "tagged but still sample" has cost time more than once here.
    _np = int(_pairs["offensive"].notna().sum()) if not _pairs.empty else 0
    _rv = _pairs.attrs.get("reversed_games", 0)
    print(f"  rebound_tendencies: {len(_pairs)} misses across {_pairs.attrs.get('games', '?')} game(s), {_np} paired "
          f"to a rebound, {int(_pairs['is_them'].sum()) if not _pairs.empty else 0} of them {_gp_short}'s "
          f"-> {len(_reb_real)} row(s)"
          + (f"; {_rv} game file(s) were newest-first and read in reverse" if _rv else "") + ".")
    if _pairs.empty:
        print("    ^ no missed shots found -- check that event_type holds missed_shot / free_throw_missed.")
    elif _np == 0:
        print("    ^ misses found but none paired -- rebounds aren't landing next to misses in event order.")
    elif not _reb_real:
        print(f"    ^ paired, but no miss type reached {_REB_MIN_MISSES} misses -- staying sample until more games.")
else:
    print("  rebound_tendencies: uww_opponent_prior_games_pbp is missing or has no event_order -- staying "
          f"sample. Columns seen: {list(_reb_pbp.columns)[:12]}")
rebound_tendencies = _gp_write("rebound_tendencies", _reb_cols, _reb_sample, real_rows=_reb_real)

_gs_cols = ["opponent", "situation", "ppp", "primary_actions", "note"]
_gs_sample = [
    [_gp_short, "Leading by 10+", 0.85, "Slows down, more Hi-Lo DHO", "Stops running in transition"],
    [_gp_short, "Trailing by 10+", 1.15, "More ball screens, faster pace", f"{_S(_gp_driver)} takes over possessions"],
    [_gp_short, "Clutch (last 5 min, margin \u2264 8)", 0.97, "Isolation for " + _S(_gp_driver),
     "Goes away from their sets late"],
]

# ---- REAL game situation splits, reusing the exact clutch definition already used elsewhere in this
# pipeline (see the "Clutch-time event log" cell and the "Game situation" tag in the Play calls cell) --
# not a new definition invented for this table. Reads level="Game situation" in uww_play_call_summary.
_gs_real = []
if not _gp_pcs.empty and {"side", "level", "name", "uses"}.issubset(_gp_pcs.columns):
    _gs_rows_df = _gp_pcs[(_gp_pcs["side"] == "Opponent") & (_gp_pcs["level"] == "Game situation")
                          & (_gp_pcs["scouted_opponent"].astype(str) == str(_gp_short))
                          & (_gp_pcs["uses"] >= _GS_MIN_USES)]
    # Same left-to-right order as the sample rows, when present.
    _gs_order = ["Leading by 10+", "Trailing by 10+", "Clutch (last 5 min, margin \u2264 8)"]
    _gs_rows_df = _gs_rows_df.assign(_ord=_gs_rows_df["name"].apply(
        lambda n: _gs_order.index(n) if n in _gs_order else len(_gs_order))).sort_values("_ord")
    for _, r in _gs_rows_df.iterrows():
        _situ = str(r["name"])
        _calls = (_gp_pc[(_gp_pc["side"] == "Opponent") & (_gp_pc["game_situation"] == _situ)
                         & ~_gp_pc["play_call"].astype(str).str.contains("unspecified", na=False)
                         & _gp_pc["play_call"].notna()]["play_call"].value_counts().head(2)
                  if not _gp_pc.empty and "game_situation" in _gp_pc.columns else pd.Series(dtype=int))
        _what = ", ".join(f"{n} ({int(c)}x)" for n, c in _calls.items()) or (r.get("top_action") or "--")
        _note = f"{int(r['uses'])} tagged possessions"
        if pd.notna(r.get("team_ppp")):
            _note += f" (their overall {r['team_ppp']:.2f} PPP)"
        _gs_real.append([_gp_short, _situ, r.get("ppp"), _what, _note])

game_situation_splits = _gp_write("game_situation_splits", _gs_cols, _gs_sample, real_rows=_gs_real)

_sq_cols = ["opponent", "contest_level", "freq_pct", "fg_pct", "note"]
_sq_sample = [
    [_gp_short, "Wide open (no closeout)", 15, 58, "Mostly transition and scramble situations"],
    [_gp_short, "Open (closeout, no contest)", 30, 44, f"{_S(_gp_shooter)} shoots this well above the others"],
    [_gp_short, "Contested (hand up, on time)", 40, 33, "Team average drops hard here"],
    [_gp_short, "Tightly contested (late or rushed)", 15, 19, "Mostly late-clock possessions"],
]
shot_quality_by_contest = _gp_write("shot_quality_by_contest", _sq_cols, _sq_sample)

_dt_cols = ["opponent", "trigger", "from_where", "escape_read", "note"]
_dt_sample = [
    [_gp_short, f"{_S(_gp_big)} post touch below the block", "Baseline dig", "Kicks out to the corner",
     "Corner shooter is the read -- deny that pass first"],
    [_gp_short, f"{_S(_gp_driver)} isolation, dribbles into the lane", "Nail help", "Drives through it more than passing out",
     "Live-ball turnover risk if we trap instead of just digging"],
]
double_team_tendencies = _gp_write("double_team_tendencies", _dt_cols, _dt_sample)

_osn_cols = ["opponent", "screen_type", "technique", "freq_pct", "note"]
_osn_sample = [
    [_gp_short, "Down screen / pin down", "Trail (go over)", 60, f"Run {_S(_gp_shooter)} off these -- they chase, don't switch"],
    [_gp_short, "Flare screen", "Switch", 55, "Safer to attack the mismatch than the shot itself"],
    [_gp_short, "Stagger (two screens)", "Fight through first, switch second", 50, "Confusion point -- late defender is open man's man"],
]
offball_screen_navigation = _gp_write("offball_screen_navigation", _osn_cols, _osn_sample)

for _i, r in _gp_opp.head(5).iterrows():
    _d = _us_starters[_i] if _i < len(_us_starters) else ""
    _b = _us_bench[_i] if _i < len(_us_bench) else ""
    _match_sample.append([_gp_short, r["player"], _d, _b,
                          "Leading scorer -- top priority" if r["player"] == _top_threat else ""])
matchups = _gp_write("matchups", _match_cols, _match_sample)

_scout_cols = ["opponent", "scout_player", "plays_as", "imitate"]
_scout_sample = []
_bench_pool = list(_gp_us["player"].iloc[5:]) if len(_gp_us) > 5 else list(_gp_us["player"])
for _i, r in _gp_opp.head(5).iterrows():
    if _i >= len(_bench_pool):
        break
    _role = ("Post seals and offensive glass" if r["player"] == _gp_big else
             "Downhill drives, draw contact" if r["player"] == _gp_driver else
             "Catch-and-shoot off flares" if r["player"] == _gp_shooter else
             "Initiate sets, first pass" if r["player"] == _gp_handler else "Spot up, cut hard")
    _scout_sample.append([_gp_short, _bench_pool[_i], r["player"], _role])
scout_team = _gp_write("scout_team", _scout_cols, _scout_sample)

_avail_cols = ["opponent", "player", "status", "note"]
_avail_sample = [[_gp_short, p, "Available", ""] for p in _us_starters]
if _avail_sample:
    _avail_sample[-1] = [_gp_short, _avail_sample[-1][1], "Limited", "Non-contact Monday, full Tuesday"]
uww_availability = _gp_write("uww_availability", _avail_cols, _avail_sample)

_film_cols = ["opponent", "clip_group", "clips", "who_watches"]
_film_sample = [
    [_gp_short, "Their base offense (5-Out Motion)", 6, "Whole team"],
    [_gp_short, f"{_S(_gp_big)} post touches and offensive rebounds", 5, "Bigs"],
    [_gp_short, "BLOB / SLOB / ATO", 8, "Whole team"],
    [_gp_short, "Their ball-screen coverage vs us-type guards", 5, "Guards"],
    [_gp_short, "Press break and 1-2-1-1", 4, "Whole team"],
]
film_clips = _gp_write("film_clips", _film_cols, _film_sample, real_rows=_film_real)


# ======================================================================================================
# PRACTICE PLAN -- emphasis items REAL (keys + flags), calendar SAMPLE until a staff calendar exists
# ======================================================================================================
def _gp_parse_display_date(text):
    """'Wed, Nov 19' -> datetime, using reference_date's season for the year (Nov-Dec vs Jan-Mar)."""
    ts = pd.to_datetime(str(text), errors="coerce", format="%a, %b %d")
    if pd.isna(ts):
        ts = pd.to_datetime(str(text), errors="coerce")
    if pd.isna(ts):
        return None
    ref = globals().get("reference_date") or datetime.now()
    year = ref.year if (ts.month >= 7) == (ref.month >= 7) else (ref.year + 1 if ref.month >= 7 else ref.year - 1)
    return ts.replace(year=year).to_pydatetime()


_ktv = _gp_load("uww_ktv_keys")
if not _ktv.empty and "opponent" in _ktv.columns:
    _ktv = _ktv[_ktv["opponent"].astype(str) == str(_gp_short)].sort_values("key_number")


def _gp_keys(category, n):
    if _ktv.empty:
        return []
    return [(int(r["key_number"]), str(r["headline"])) for _, r in _ktv[_ktv["category"] == category].head(n).iterrows()]


_flags = _gp_load("uww_coaching_flags")
_cleanup_players = []
if not _flags.empty and "sentiment" in _flags.columns:
    _cleanup_players = list(dict.fromkeys(_flags[_flags["sentiment"].astype(str) == "Negative"]["player"].head(3)))

_sched = _gp_load("uww_schedule")
_game_dt = _prev_dt = None
if not _sched.empty and "Upcoming" in _sched.columns:
    _uww_rows = _sched[_sched["team"].astype(str).str.contains("Whitewater", case=False, na=False)]
    _up = _uww_rows[_uww_rows["Upcoming"].astype(str).str.strip().str.lower() == "yes"]
    if not _up.empty:
        _game_dt = _gp_parse_display_date(_up.iloc[0].get("date"))
        _played = _uww_rows.loc[:_up.index[0]].iloc[:-1]
        _played = _played[_played["outcome"].astype(str).str.upper().isin(["W", "L"])]
        if not _played.empty:
            _prev_dt = _gp_parse_display_date(_played.iloc[-1].get("date"))

_plan_cols = ["opponent", "day", "date", "segment", "minutes", "detail", "ties_to", "schedule_is_sample"]

# ---- Recommendations the practice plan consumes (REAL) -------------------------------------------------
# Which defense hurts them least, and whether pressure actually costs them the ball. Same math the brief's
# WHAT TO PLAY THEM IN section prints, computed once here so the plan and the brief can't disagree.
# defense_FACED, never the raw defense_type -- on a mixed offense/defense file the raw field flips meaning.
_def_rec_text = ""
_press_rec_text = ""
_REC_MIN = 6
if not _gp_pc.empty and "defense_faced" in _gp_pc.columns:
    _rc = _gp_pc[(_gp_pc["side"] == "Opponent")
                 & (_gp_pc["offense_team"].astype(str) == str(_gp_short))
                 & (_gp_pc["decode_quality"] != "Needs review")].copy()
    if not _rc.empty:
        _rc["_pts"] = pd.to_numeric(_rc.get("points"), errors="coerce")

        def _rec_family(r):
            if bool(r.get("press_faced")):
                return "press"
            d = str(r.get("defense_faced") or "")
            return "zone" if "zone" in d.lower() else ("man" if "man" in d.lower() else "")

        _rc["_fam"] = _rc.apply(_rec_family, axis=1)
        _fams = {f: g for f, g in _rc[_rc["_fam"] != ""].groupby("_fam") if len(g) >= _REC_MIN}
        if len(_fams) >= 2:
            _scored = {f: (g["_pts"].sum() / g["_pts"].notna().sum()) for f, g in _fams.items()
                       if g["_pts"].notna().sum()}
            if _scored:
                _best_d = min(_scored, key=_scored.get)
                _def_rec_text = (f"Reps in {_best_d} -- they scored {_scored[_best_d]:.2f} PPP against it on "
                                 f"{len(_fams[_best_d])} tagged possessions, their lowest")
        _pr = _rc[_rc["press_faced"].astype(bool)] if "press_faced" in _rc.columns else pd.DataFrame()
        _np = _rc[~_rc["press_faced"].astype(bool)] if "press_faced" in _rc.columns else pd.DataFrame()
        if len(_pr) >= _REC_MIN and len(_np) >= _REC_MIN:
            _res_p = _pr.get("result", pd.Series("", index=_pr.index)).astype(str).str.lower()
            _res_n = _np.get("result", pd.Series("", index=_np.index)).astype(str).str.lower()
            _to_p = 100 * _res_p.str.contains("turnover|violation|kicked", regex=True).sum() / len(_pr)
            _to_n = 100 * _res_n.str.contains("turnover|violation|kicked", regex=True).sum() / len(_np)
            _press_rec_text = (
                f"Press reps -- pressure moved their turnover rate {_to_p - _to_n:+.1f} points "
                f"({_to_n:.0f}% to {_to_p:.0f}%) over {len(_pr)} pressed possessions"
                if _to_p - _to_n >= 5 else
                f"Skip the press -- pressure only moved their turnover rate {_to_p - _to_n:+.1f} points; "
                f"work half-court defense instead")

_plan = []
_def_keys, _off_keys, _pers_keys = _gp_keys("Defense", 3), _gp_keys("Offense", 2), _gp_keys("Personnel", 1)
_foul_names = ", ".join(_gp_last(p) for p in late_game_foul_list[late_game_foul_list["call"] == "Foul"]["player"])
_set_names = ", ".join(opp_sets[opp_sets["situation"] == "Half court"]["set_name"].head(3))
_so_names = ", ".join(opp_sets[opp_sets["situation"].astype(str).str.match(r"^(BLOB|SLOB|ATO)")]["set_name"].head(3))

if _game_dt is not None:
    from datetime import timedelta as _gp_td
    _start = (_prev_dt + _gp_td(days=1)) if _prev_dt else (_game_dt - _gp_td(days=3))
    _start = max(_start, _game_dt - _gp_td(days=5))
    _days = []
    _d = _start
    while _d < _game_dt:
        _days.append(_d)
        _d += _gp_td(days=1)
    _label = lambda d: f"{d:%a}, {d:%b} {d.day}"  # noqa: E731

    def _seg(day, date, segment, minutes, detail, ties_to=""):
        _plan.append([_gp_short, day, _label(date), segment, minutes, detail, ties_to, True])

    _practice_no = 0
    for _i, _d in enumerate(_days):
        _is_first, _is_last = _i == 0, _i == len(_days) - 1
        if _is_first and len(_days) >= 3:
            _seg("Recovery + film", _d, "Film", 40, f"Scout film: {_set_names or 'their base offense'}",
                 "Opponent sets")
            _seg("Recovery + film", _d, "Shooting", 20, "Form and free throws, no contact",
                 ", ".join(_cleanup_players) if _cleanup_players else "")
            continue
        _heavy = not _is_last
        _practice_no += 1
        _pday = f"Practice {_practice_no}" + ("" if _heavy else " (light)")
        _seg(_pday, _d, "Warm-up / dynamic", 10, "")
        if _cleanup_players and _heavy:
            _seg(_pday, _d, "Individual", 12, "Catch-and-shoot and free-throw reps",
                 "Player flags: " + ", ".join(_gp_last(p) for p in _cleanup_players))
        for _n, _h in (_def_keys if _heavy else _def_keys[:1]):
            _seg(_pday, _d, "Defensive install" if _heavy else "Defensive walkthrough",
                 12 if _heavy else 10, _h, f"Key {_n}")
        _seg(_pday, _d, "Scout team", 15,
             f"Scout team runs {_set_names or 'their base sets'}", "Opponent sets")
        # Close the loop (requested): the brief now COMPUTES which defense hurts them and whether pressing
        # is worth it, so the plan asks for reps at that instead of leaving the staff to re-derive it.
        if _def_rec_text and _heavy:
            _seg(_pday, _d, "Defensive emphasis", 10, _def_rec_text, "What to play them in")
        if _press_rec_text and _heavy:
            _seg(_pday, _d, "Press reps", 8, _press_rec_text, "Pressure response")
        for _n, _h in (_off_keys if _heavy else _off_keys[:1]):
            _seg(_pday, _d, "Offensive emphasis", 10, _h, f"Key {_n}")
        _seg(_pday, _d, "Special situations", 8,
             f"Defend {_so_names or 'their BLOB/SLOB/ATO'}", "Opponent sets")
        if _heavy:
            _seg(_pday, _d, "Late game", 8,
                 f"Foul-list reps -- foul: {_foul_names}" if _foul_names else "End-of-game situations",
                 "Late-game foul list" if _foul_names else "")
            _seg(_pday, _d, "Live 5-on-5", 15,
                 "Scout team in their personnel; stop on key violations"
                 + (f" -- {_pers_keys[0][1][0].lower()}{_pers_keys[0][1][1:]}" if _pers_keys else ""),
                 f"Key {_pers_keys[0][0]}" if _pers_keys else "")
    _seg("Game day", _game_dt, "Shootaround", 45,
         "Walk their sets, matchups and the foul list; 50 game-speed shots each", "Matchups")

practice_plan = _gp_write("practice_plan", _plan_cols, _plan)
# is_sample for the practice plan means "the whole plan came from the generator". The emphasis text inside it
# is real regardless -- schedule_is_sample carries the narrower claim, so a renderer can say exactly that.

# ======================================================================================================
# REAL: personnel tiers for BOTH teams -- Starters, then the three bench tiers the app's Personnel tab uses
# ======================================================================================================
# CONFIRMED CHANGE (requested): the brief's personnel pages are grouped the same way as the app -- a Starters
# page, then "Bench -- rotation", "Bench -- limited minutes" and "Bench -- no minutes in last N game(s)".
# Built here, once, for both teams, so the brief renders a table instead of re-deriving tiers itself.
#   Bench tiers: the app's own rule (opponent_bench_tiers in streamlit_app.py) -- a player with no minutes in
#     the last _PT_RECENT_WINDOW games is "no minutes"; otherwise under _PT_ROTATION_MIN_MPG minutes a game is
#     "limited"; otherwise "rotation". Minutes, not box-score appearances: a row of zeros isn't playing.
#   Starters: the scouting report's Starter role when one exists for the opponent (the staff's word wins);
#     otherwise players who started at least half of the recent games (`started` -- official box-score
#     asterisks for UWW, the first five-man unit on the floor for the opponent), up to five. With no start
#     data at all, the five highest minutes-per-game players over the recent window, and the brief says so.
_PT_RECENT_WINDOW = 3      # RECENT_GAMES_WINDOW in streamlit_app.py
_PT_ROTATION_MIN_MPG = 8.0  # ROTATION_MIN_MPG in streamlit_app.py
_PT_TIER_ORDER = ["Starter", "Bench \u2014 rotation", "Bench \u2014 limited minutes", "Bench \u2014 no minutes"]
# RETURNING STARTER (requested, after Mekhi Doby): "started half the recent games" can't see a starter coming
# back from injury -- he missed games, so he has few starts, and his first game back is often off the bench
# while his minutes are managed. What gives him away is the minutes themselves. A player who MISSED at least
# one of the recent games, then in the most recent game played one of his team's top minutes (and real
# minutes, not a blowout cameo), is treated as a starter. If that makes six, the starter who played the
# fewest minutes in that most recent game moves to the bench -- that's whose spot he took.
_PT_RETURN_TOP_RANK = 2       # top-N in minutes on his team in the most recent game
_PT_RETURN_MIN_MINUTES = 20   # ...with at least this many minutes in it


def _pt_tiers(box, team_value, side, report_starters=()):
    if box.empty or "team" not in box.columns or "player" not in box.columns:
        return []
    own = box[(box["team"].astype(str) == str(team_value)) & (box["player"].astype(str) != "TEAM")].copy()
    if own.empty or "game_date" not in own.columns:
        return []
    own["_d"] = pd.to_datetime(own["game_date"], errors="coerce")
    games = sorted(own["_d"].dropna().unique(), reverse=True)
    if not games:
        return []
    recent = set(games[:_PT_RECENT_WINDOW])
    own["_min"] = pd.to_numeric(own["MIN"], errors="coerce") if "MIN" in own.columns else float("nan")
    has_min = own["_min"].notna().any()
    played = own[own["_min"].fillna(0) > 0] if has_min else own
    own["_started"] = own["started"].astype(str).str.lower().isin(["true", "1"]) if "started" in own.columns else False
    rows = []
    for name in own["player"].astype(str).unique():
        p_rows = played[played["player"].astype(str) == name]
        appearances = set(p_rows["_d"].dropna().unique())
        recent_count = len(appearances & recent)
        mpg = float(p_rows["_min"].mean()) if has_min and not p_rows.empty else None
        missed = 0
        for g in games:
            if g in appearances:
                break
            missed += 1
        starts_recent = int(own[(own["player"].astype(str) == name) & own["_d"].isin(recent)]["_started"].sum())
        rows.append({"side": side, "team": team_value, "player": name, "games": len(appearances),
                     "mpg": round(mpg, 1) if mpg is not None else None, "recent_count": recent_count,
                     "missed_recent": missed, "starts_recent": starts_recent, "recent_n": len(recent)})
    df = pd.DataFrame(rows)
    # Minutes in the MOST RECENT game, and each player's rank on his team in it (1 = most minutes).
    latest = games[0]
    _last = (played[played["_d"] == latest].groupby(played["player"].astype(str))["_min"].sum()
             if has_min else pd.Series(dtype=float))
    df["last_game_min"] = df["player"].map(_last)
    df["last_game_rank"] = df["last_game_min"].rank(ascending=False, method="min")
    df["tier_note"] = ""
    # Starters.
    starter_basis = ""
    report_starters = {str(n).strip().lower() for n in report_starters if str(n).strip()}
    if report_starters:
        starters = set(df[df["player"].str.lower().isin(report_starters)]["player"])
        starter_basis = "scouting report role"
    elif df["starts_recent"].sum() > 0:
        cand = df[df["starts_recent"] >= max(1, -(-len(recent) // 2))]
        starters = set(cand.sort_values(["starts_recent", "mpg"], ascending=False).head(5)["player"])
        starter_basis = f"started {max(1, -(-len(recent) // 2))}+ of the last {len(recent)} game(s)"
    else:
        starters = set(df[df["recent_count"] > 0].sort_values("mpg", ascending=False).head(5)["player"])
        starter_basis = f"no start data -- top five in minutes over the last {len(recent)} game(s)"

    # Returning starters -- only when the data decided the starters. The scouting report's role is the
    # staff's word and is never overridden.
    if not report_starters and has_min:
        _ret = df[(~df["player"].isin(starters)) & (df["recent_count"] < len(recent))
                  & df["last_game_min"].notna() & (df["last_game_rank"] <= _PT_RETURN_TOP_RANK)
                  & (df["last_game_min"] >= _PT_RETURN_MIN_MINUTES)]
        for _, _rr in _ret.sort_values("last_game_rank").iterrows():
            _missed_n = len(recent) - int(_rr["recent_count"])
            _rank_txt = "led the team" if int(_rr["last_game_rank"]) == 1 else f"ranked #{int(_rr['last_game_rank'])} on the team"
            starters.add(_rr["player"])
            df.loc[df["player"] == _rr["player"], "tier_note"] = (
                f"Returning starter \u2014 missed {_missed_n} of the last {len(recent)} games, then {_rank_txt} "
                f"in minutes ({_rr['last_game_min']:.0f}) in the most recent game")
            if len(starters) > 5:
                # The starter he displaced: fewest minutes in that most recent game (no minutes = fewest).
                _cands = df[df["player"].isin(starters) & (df["player"] != _rr["player"])
                            & (df["tier_note"] == "")].copy()
                _cands["_lm"] = _cands["last_game_min"].fillna(-1)
                _out = _cands.sort_values("_lm").iloc[0]
                starters.discard(_out["player"])
                df.loc[df["player"] == _out["player"], "tier_note"] = (
                    f"Moved to the bench \u2014 {_rr['player']} returned and took a starting spot; played "
                    + (f"{_out['last_game_min']:.0f}" if pd.notna(_out["last_game_min"]) else "no")
                    + " minutes in the most recent game, fewest of the starters")

    def tier(r):
        if r["player"] in starters:
            return "Starter"
        if r["recent_count"] == 0:
            return "Bench \u2014 no minutes"
        if r["mpg"] is not None and r["mpg"] < _PT_ROTATION_MIN_MPG:
            return "Bench \u2014 limited minutes"
        return "Bench \u2014 rotation"

    df["tier"] = df.apply(tier, axis=1)
    df["tier_order"] = df["tier"].map(_PT_TIER_ORDER.index)
    df["starter_basis"] = starter_basis
    return df.to_dict("records")


_pt_report_starters = []
for _pt_src_name in ("uww_opponent_rosters", "uww_player_profiles"):
    _pt_src = _gp_load(_pt_src_name)
    if not _pt_src.empty and {"opponent", "name", "role"}.issubset(_pt_src.columns):
        _pt_report_starters = list(_pt_src[(_pt_src["opponent"].astype(str) == str(_gp_short))
                                           & (_pt_src["role"].astype(str).str.lower() == "starter")]["name"])
        if _pt_report_starters:
            break

personnel_tiers = pd.DataFrame(
    _pt_tiers(_gp_prior, _gp_short, "Opponent", _pt_report_starters) + _pt_tiers(_gp_box, _GP_UWW, "UWW"),
    columns=["side", "team", "player", "tier", "tier_order", "games", "mpg", "recent_count", "missed_recent",
             "starts_recent", "recent_n", "starter_basis", "last_game_min", "last_game_rank", "tier_note"])
personnel_tiers.insert(0, "scouted_opponent", _gp_short)
# every player's offensive role (BBall Index's 12), from the same source as every other roster table
if "_or_attach" in globals():
    _or_attach(personnel_tiers, "player", "team")
if "_dr_attach" in globals():                 # and his defensive role (BBall Index's 7), same single source
    _dr_attach(personnel_tiers, "player", "team")
personnel_tiers.to_csv(os.path.join(APP_DATA_DIR, "uww_personnel_tiers.csv"), index=False)

# ======================================================================================================
# REAL: UWW's own season five-man units, so the brief's UWW section can mirror the opponent's Top Lineups
# ======================================================================================================
_uwl = _gp_load("uww_lineup_stints")
uww_lineup_season = pd.DataFrame(columns=["lineup", "GP", "MIN", "+/-"])
if not _uwl.empty and "uww_lineup" in _uwl.columns:
    _uwl = _uwl.dropna(subset=["uww_lineup"]).copy()
    _uwl["_min"] = pd.to_numeric(_uwl.get("stint_minutes"), errors="coerce")
    _uwl["_pm"] = pd.to_numeric(_uwl.get("uww_margin_change"), errors="coerce")
    uww_lineup_season = (_uwl.groupby("uww_lineup")
                         .agg(GP=("game_date", "nunique"), MIN=("_min", "sum"), **{"+/-": ("_pm", "sum")})
                         .reset_index().rename(columns={"uww_lineup": "lineup"}))
    uww_lineup_season["MIN"] = uww_lineup_season["MIN"].round(1)
    # Competitive minutes only, for ranking (requested: the brief's top lineups must be the BEST units, not
    # the most-used). Same garbage-time rule as the 3-man combos (COMBO_RULES), so a five-man unit and a trio
    # are judged the same way: a stint that starts in the 2nd half or later with the margin already at
    # garbage_margin+ is set aside.
    _CRg = globals().get("COMBO_RULES") or {"garbage_margin": 15, "garbage_from_period": 2, "shrink_minutes": 40}
    if {"start_prev_uww_score", "start_prev_opp_score", "start_period"}.issubset(_uwl.columns):
        _smargin = (pd.to_numeric(_uwl["start_prev_uww_score"], errors="coerce")
                    - pd.to_numeric(_uwl["start_prev_opp_score"], errors="coerce")).abs()
        _uwl["_garbage"] = ((pd.to_numeric(_uwl["start_period"], errors="coerce") >= _CRg["garbage_from_period"])
                            & (_smargin >= _CRg["garbage_margin"])).fillna(False)
    else:
        _uwl["_garbage"] = False
    _uwl_clean = (_uwl[~_uwl["_garbage"].astype(bool)].groupby("uww_lineup")
                  .agg(clean_gp=("game_date", "nunique"), clean_min=("_min", "sum"), clean_pm=("_pm", "sum"))
                  .reset_index().rename(columns={"uww_lineup": "lineup"}))
    uww_lineup_season = uww_lineup_season.merge(_uwl_clean, on="lineup", how="left")
    uww_lineup_season[["clean_gp", "clean_min", "clean_pm"]] = \
        uww_lineup_season[["clean_gp", "clean_min", "clean_pm"]].fillna(0)
    uww_lineup_season["clean_min"] = uww_lineup_season["clean_min"].round(1)
    _cmn = uww_lineup_season["clean_min"]
    uww_lineup_season["per40"] = (uww_lineup_season["clean_pm"] / _cmn * 40).where(_cmn > 0).round(1)
    uww_lineup_season["shrunk_per40"] = (uww_lineup_season["clean_pm"]
                                         / (_cmn + _CRg["shrink_minutes"]) * 40).round(2)
    uww_lineup_season = uww_lineup_season.sort_values("MIN", ascending=False)
uww_lineup_season.to_csv(os.path.join(APP_DATA_DIR, "uww_uww_lineup_season.csv"), index=False)

print(f"Wrote game-plan tables for {_gp_short or 'no opponent'}:")
for _name, _df in (("uww_late_game_foul_list", late_game_foul_list), ("uww_sample_size_warnings", sample_size_warnings),
                   ("uww_opp_sets", opp_sets), ("uww_opp_defense", opp_defense),
                   ("uww_opp_personnel", opp_personnel), ("uww_opp_shot_zones", opp_shot_zones),
                   ("uww_opp_tendencies", opp_tendencies), ("uww_matchups", matchups),
                   ("uww_scout_team", scout_team), ("uww_uww_availability", uww_availability),
                   ("uww_film_clips", film_clips), ("uww_shot_clock_tendencies", shot_clock_tendencies),
                   ("uww_defense_by_situation", defense_by_situation),
                   ("uww_ball_screen_coverage", ball_screen_coverage),
                   ("uww_help_rotation_tendencies", help_rotation_tendencies),
                   ("uww_personnel_grouping", personnel_grouping), ("uww_rebound_tendencies", rebound_tendencies),
                   ("uww_game_situation_splits", game_situation_splits),
                   ("uww_shot_quality_by_contest", shot_quality_by_contest),
                   ("uww_double_team_tendencies", double_team_tendencies),
                   ("uww_offball_screen_navigation", offball_screen_navigation),
                   ("uww_matchup_history", matchup_history), ("uww_play_counters", play_counters),
                   ("uww_practice_plan", practice_plan), ("uww_personnel_tiers", personnel_tiers),
                   ("uww_tempo_profile", tempo_profile), ("uww_trend_profile", trend_profile),
                   ("uww_uww_lineup_season", uww_lineup_season)):
    _src = ("SAMPLE" if (not _df.empty and "is_sample" in _df.columns and bool(_df["is_sample"].all()))
            else ("real" if not _df.empty else "empty"))
    print(f"  {_name:28s} {len(_df):3d} row(s)  [{_src}]")
print(f"  Staff input templates: {os.path.abspath(_GP_TEMPLATE_DIR)}")
if _gp_problems:
    for _p in _gp_problems:
        print(f"  - {_p}")
