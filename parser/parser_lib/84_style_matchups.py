# 84_style_matchups.py -- code for the notebook section "Style matchups: teams like them that we've played, and teams like us that have played them"
# Runs inside the notebook via run_section("84_style_matchups"); its settings are in that notebook cell.

# --- Style matchups: teams like them that we've played, and teams like us that have played them -------------
# Both halves of the app's STYLE MATCHUPS section, computed here and written to uww_style_matchups.csv so the
# brief, the app and anything else render one answer instead of each deriving their own.
#
# One model, two directions. The distance is a weighted RMS of robust z-score differences over the
# seventeen-feature style profile, and the match score is 100*exp(-0.7*d) -- so a 78 in one direction means
# exactly what a 78 means in the other. What changes is who is the target and who is the pool:
#   like_them   target = the upcoming opponent, pool = teams UWW has already played this season. Answers
#               "what has actually worked against this style".
#   like_us     target = UWW, pool = the teams the upcoming opponent has already played. Answers "what did
#               teams built like us produce against them".
#
# WHY THE PROFILES COME FROM BOX SCORES. Every team in the pool is described by reconstructed box scores, so
# describing the target from a scouting-report PDF instead would compare two things built by different
# methods and call the difference style. The upcoming opponent is measured from their OWN prior games rather
# than from the one meeting against UWW, since a body of work against several teams describes them better.
# Height and the shooter/post shares are the one block no box score carries; those come from the scouting
# reports, minutes-weighted across the rotation.
#
# SAMPLE SIZE IS REPORTED, NOT BAKED IN. Shrinking each team's rates toward the pool median was tried in the
# app and removed: the target has a season of prior games while most candidates have exactly one, so
# shrinkage systematically favoured whichever candidate happened to be sampled most like the target (a
# planted style-clone with identical raw rates came out 5.7 points apart on sample size alone). The distance
# runs on observed rates and each row carries a confidence instead.
#
# PORTING NOTE -- one deliberate omission. The app tops the like_them pool up with teams UWW played LAST
# season when this season is short of MIN_COMPARABLE_POOL candidates, reading them out of a sibling
# data_<season> archive folder. That archive lookup is an app concept (_discover_available_seasons); this
# parser has no multi-season view, so the pool here is current-season only. In the opening weeks of a season
# that means this table can be thinner than the app's panel, or empty when the app's is not. Everything else
# -- the feature spec, the weights, the scaling, the ranking, the confidence -- is copied verbatim.

import math as _sm_math

_SM_OUT = "uww_style_matchups"

# (key, display label, category, weight). Category weights: offense and defense 0.25 each because preparing
# for a team is equally about both; shot selection 0.15 kept separate from shooting SKILL because how often
# a team shoots threes is a schematic choice a game plan responds to while whether they make them is form;
# tempo 0.12; scoring level 0.10, deliberately low because how good they are is not how much they resemble
# someone; personnel 0.13, the only block that can't come from a box score. Inside the four factors, Dean
# Oliver's own weights.
_SM_FEATURE_SPEC = [
    ("off_efg",       "Their eFG%",             "Their offense",   0.100),
    ("off_tov",       "Their TOV%",             "Their offense",   0.0625),
    ("off_orb",       "Their ORB%",             "Their offense",   0.050),
    ("off_ftr",       "Their FT rate",          "Their offense",   0.0375),
    ("def_efg",       "eFG% they allow",        "Their defense",   0.100),
    ("def_tov",       "TOV% they force",        "Their defense",   0.0625),
    ("def_drb",       "DRB% they secure",       "Their defense",   0.050),
    ("def_ftr",       "FT rate they allow",     "Their defense",   0.0375),
    ("off_3par",      "Their 3PA rate",         "Shot selection",  0.060),
    ("off_astr",      "Their AST per made FG",  "Shot selection",  0.040),
    ("def_3par",      "3PA rate they allow",    "Shot selection",  0.050),
    ("pace",          "Pace (poss/40)",         "Tempo",           0.120),
    ("off_rtg",       "Points per 100",         "Scoring level",   0.050),
    ("def_rtg",       "Points allowed per 100", "Scoring level",   0.050),
    ("height_in",     "Avg height",             "Personnel",       0.070),
    ("share_shooter", "Shooter share",          "Personnel",       0.030),
    ("share_post",    "Post share",             "Personnel",       0.030),
]
_SM_WEIGHTS = {k: w for k, _, _, w in _SM_FEATURE_SPEC}
_SM_LABELS = {k: lbl for k, lbl, _, _ in _SM_FEATURE_SPEC}
_SM_CATEGORIES = {}
for _k, _lbl, _cat, _w in _SM_FEATURE_SPEC:
    _SM_CATEGORIES.setdefault(_cat, []).append(_k)

_SM_CONFIDENCE_GAMES = 2.0     # games at which a candidate's sample carries half weight in confidence
_SM_MIN_FEATURES = 5           # shared, discriminating features a match score needs to mean anything
_SM_TOP_K = 3
_SM_ROTATION_MIN_MPG = 8.0
_SM_JUNK_PLAYER_RE = (r"(?i)^(?:TEAM$|Commits |Turnover|Jump Ball|Subs In|Subs Out|Timeout|Official )"
                      r"|(?: Commits Foul$)")
_SM_DATE_COLS = ("game_date", "date", "iso_date")

_sm_rows = []
# The record behind each panel as NUMBERS (requested: the brief shows these panels only in THE BOTTOM LINE,
# and only when they matter -- which can't be decided by parsing strip_text). Filled per direction below.
_sm_dir_summary = {}
_sm_problems = []


def _sm_load(name):
    try:
        return pd.read_csv(os.path.join(APP_DATA_DIR, f"{name}.csv"))
    except Exception:
        return pd.DataFrame()


def _sm_pretty_date(value):
    """'2025-11-07' -> 'Fri, Nov 7'. Anything unparseable is returned as-is."""
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return str(value)
    return f"{ts:%a}, {ts:%b} {ts.day}"


_SM_LOW_CONF = 0.35  # same amber/red cut the card colour uses


def _sm_low_conf_prefix(ranked):
    """Strip lead-in when EVERY card in a panel is red-confidence. A record over three one-game profiles is
    worth showing, but not as if it were a finding."""
    if ranked is None or ranked.empty or "confidence" not in ranked.columns:
        return ""
    conf = pd.to_numeric(ranked["confidence"], errors="coerce")
    if conf.notna().any() and float(conf.max()) < _SM_LOW_CONF:
        return "Low confidence -- every match here rests on a one- or two-game profile. "
    return ""


def _sm_date_col(df):
    for c in _SM_DATE_COLS:
        if c in df.columns:
            return c
    return None


def _sm_possessions(fga, oreb, to, fta):
    return fga - oreb + to + 0.44 * fta


def _sm_rate_profile(team_box, foe_box, games):
    """The fourteen box-derivable features for one team over one set of games.

    Everything here is a RATE: nothing changes when a team plays faster, which is the point -- pace is its
    own feature rather than a hidden contaminant. A component with no denominator returns None rather than
    0, because a zero would be read as a real value and count as agreement in the distance.
    """
    def tot(df, c):
        return pd.to_numeric(df[c], errors="coerce").sum() if c in df.columns else float("nan")

    cols = ("FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", "AST", "TO", "PTS")
    o = {c: tot(team_box, c) for c in cols}
    d = {c: tot(foe_box, c) for c in cols}

    def safe(n, dn, scale=100.0):
        return (scale * n / dn) if (pd.notna(n) and pd.notna(dn) and dn > 0) else None

    off_poss = _sm_possessions(o["FGA"], o["OREB"], o["TO"], o["FTA"]) if pd.notna(o["FGA"]) else float("nan")
    def_poss = _sm_possessions(d["FGA"], d["OREB"], d["TO"], d["FTA"]) if pd.notna(d["FGA"]) else float("nan")
    # Averaging the two possession estimates is standard practice -- either side alone is a noisy
    # approximation of the same underlying number, and they should agree.
    if pd.notna(off_poss) and pd.notna(def_poss):
        poss = (off_poss + def_poss) / 2
    elif pd.notna(off_poss):
        poss = off_poss
    elif pd.notna(def_poss):
        poss = def_poss
    else:
        poss = None

    def _den(a, b):
        return (a + b) if (pd.notna(a) and pd.notna(b)) else float("nan")

    return {
        "off_efg": safe(o["FGM"] + 0.5 * o["FG3M"], o["FGA"]) if pd.notna(o["FGM"]) else None,
        "off_tov": safe(o["TO"], off_poss) if pd.notna(off_poss) else None,
        "off_orb": safe(o["OREB"], _den(o["OREB"], d["DREB"])),
        "off_ftr": safe(o["FTA"], o["FGA"]),
        "def_efg": safe(d["FGM"] + 0.5 * d["FG3M"], d["FGA"]) if pd.notna(d["FGM"]) else None,
        "def_tov": safe(d["TO"], def_poss) if pd.notna(def_poss) else None,
        # Stated as the share of available defensive rebounds THEY secured, so higher is better for them --
        # the same direction as every other feature, which keeps the distance interpretable.
        "def_drb": safe(o["DREB"], _den(o["DREB"], d["OREB"])),
        "def_ftr": safe(d["FTA"], d["FGA"]),
        "off_3par": safe(o["FG3A"], o["FGA"]),
        "off_astr": safe(o["AST"], o["FGM"]) if pd.notna(o["AST"]) else None,
        "def_3par": safe(d["FG3A"], d["FGA"]),
        "pace": (poss / games) if (poss is not None and games > 0) else None,
        "off_rtg": safe(o["PTS"], poss) if poss else None,
        "def_rtg": safe(d["PTS"], poss) if poss else None,
    }


def _sm_format_feature(key, value):
    """Display form for one feature. Every rate is already on a 0-100 scale, so the unit suffix is chosen
    by what the number MEANS rather than by its size."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"
    if key == "height_in":
        return f"{int(value // 12)}'{int(round(value % 12))}\""
    if key.startswith("share_"):
        return f"{value * 100:.0f}%"
    if key in ("off_rtg", "def_rtg", "pace"):
        return f"{value:.1f}"
    if key == "off_astr":
        return f"{value / 100:.2f}"     # assists per made field goal, stored x100 by safe()
    if key.endswith(("_efg", "_tov", "_orb", "_drb", "_ftr", "_3par")):
        return f"{value:.1f}%"
    return f"{value:.1f}"


def _sm_robust_scale(frame):
    """Median/IQR z-scores, clipped to +/-3.

    Deliberately not min-max: that pins the range to the two most extreme teams, so one bad scrape squashes
    every real difference into a sliver. A feature with no spread becomes NaN rather than 0.0 -- writing 0.0
    makes every team identical on it and counts that as perfect agreement, which quietly inflates match
    scores toward 100 on features nobody varies on.
    """
    scaled = pd.DataFrame(index=frame.index)
    for column in frame.columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        spread = (values.quantile(0.75) - values.quantile(0.25)) / 1.349
        if not spread or pd.isna(spread) or spread == 0:
            spread = values.std(ddof=0)
        if not spread or pd.isna(spread) or spread == 0:
            scaled[column] = float("nan")
            continue
        scaled[column] = ((values - values.median()) / spread).clip(-3, 3)
    return scaled


def _sm_rank(target, candidates, profiles, k=_SM_TOP_K):
    """Rank `candidates` by how closely their style resembles `target`.

    The total is divided by the weight ACTUALLY used, so a team missing a feature is neither rewarded nor
    punished for having fewer things to differ on -- but how much weight was available is reported, so a
    match built on half the profile is visibly that. Returns (ranked frame or None, thin flag).
    """
    keys = [k_ for k_, _, _, _ in _SM_FEATURE_SPEC]
    if profiles.empty or target not in profiles.index:
        return None, False
    pool = [o for o in dict.fromkeys(candidates) if o in profiles.index and o != target]
    if not pool:
        return None, False

    present = [c for c in keys if c in profiles.columns]
    scaled = _sm_robust_scale(profiles[present])
    target_row = scaled.loc[target]
    total_weight = sum(_SM_WEIGHTS[k_] for k_ in present)

    def games_for(name):
        if "_games" not in profiles.columns:
            return float("nan")
        v = pd.to_numeric(pd.Series([profiles.at[name, "_games"]]), errors="coerce").iloc[0]
        return float(v) if pd.notna(v) else float("nan")

    rows = []
    for opponent in pool:
        candidate = scaled.loc[opponent]
        weighted_sq = used_weight = 0.0
        per_category, scored_keys = {}, []
        for category, cat_keys in _SM_CATEGORIES.items():
            cat_sq = cat_weight = 0.0
            for key in [k_ for k_ in cat_keys if k_ in present]:
                a, b = target_row.get(key), candidate.get(key)
                if (pd.isna(a) or pd.isna(b)
                        or pd.isna(profiles.at[target, key]) or pd.isna(profiles.at[opponent, key])):
                    continue
                w = _SM_WEIGHTS[key]
                cat_sq += w * (a - b) ** 2
                cat_weight += w
                scored_keys.append(key)
            if cat_weight > 0:
                per_category[category] = (cat_sq / cat_weight) ** 0.5
                weighted_sq += cat_sq
                used_weight += cat_weight
        if used_weight <= 0:
            continue
        distance = (weighted_sq / used_weight) ** 0.5
        games = games_for(opponent)
        coverage = (used_weight / total_weight) if total_weight else 0.0
        rows.append({
            "opponent": opponent, "distance": distance,
            "match": int(round(100 * _sm_math.exp(-0.7 * distance))),
            "features_scored": len(set(scored_keys)),
            "weight_covered": coverage,
            "games": games,
            "confidence": (coverage * (games / (games + _SM_CONFIDENCE_GAMES))
                           if pd.notna(games) else float("nan")),
            **{f"cat::{c}": v for c, v in per_category.items()},
        })
    if not rows:
        return None, False

    ranked = pd.DataFrame(rows)
    solid = ranked[ranked["features_scored"] >= _SM_MIN_FEATURES]
    chosen = (solid if not solid.empty else ranked).sort_values("distance").head(k).reset_index(drop=True)
    return chosen, bool(solid.empty)


def _sm_card_fields(rank_row, profiles, target_row, target_label):
    """The per-team detail the card shows: which categories are alike, which differs most, and the two
    features that separate them most with both teams' actual numbers -- so a coach can judge the match
    rather than trusting the score."""
    cats = {c.split("::", 1)[1]: rank_row[c] for c in rank_row.index
            if str(c).startswith("cat::") and pd.notna(rank_row.get(c))}
    alike = sorted(cats, key=cats.get)[:2]
    differs = sorted(cats, key=cats.get, reverse=True)[:1]
    gaps = []
    for key, label, _, _ in _SM_FEATURE_SPEC:
        a, b = target_row.get(key), profiles.loc[rank_row["opponent"]].get(key)
        if pd.isna(a) or pd.isna(b):
            continue
        gaps.append((abs(float(a) - float(b)) / (abs(float(a)) + 1e-6), key, label, a, b))
    gap_lines = [f"{label}: {_sm_format_feature(key, b)} vs {_sm_format_feature(key, a)} ({target_label})"
                 for _, key, label, a, b in sorted(gaps, reverse=True)[:2]]
    return ", ".join(alike), ", ".join(differs), " | ".join(gap_lines)


def _sm_add(direction, rank, name, rank_row, profiles, target_row, target_label, meetings,
            strip_label, strip_text, thin):
    alike, differs, gaps = _sm_card_fields(rank_row, profiles, target_row, target_label)
    _sm_rows.append({
        "opponent": upcoming_opponent_short,
        "direction": direction,
        "rank": rank,
        "team": name,
        "match": int(rank_row["match"]),
        "features_scored": int(rank_row["features_scored"]),
        "total_features": len(_SM_FEATURE_SPEC),
        "weight_covered": round(float(rank_row["weight_covered"]), 4),
        "games": (int(rank_row["games"]) if pd.notna(rank_row.get("games")) else None),
        "confidence": (round(float(rank_row["confidence"]), 4)
                       if pd.notna(rank_row.get("confidence")) else None),
        "alike": alike,
        "differs": differs,
        "biggest_gaps": gaps,
        "meetings": " | ".join(meetings),
        # Repeated on every row of a direction rather than kept in a second table: one row is enough to
        # render the panel, and a summary that can go missing when a row is filtered out is worse.
        "strip_label": strip_label,
        "strip_text": strip_text,
        "thin": thin,
    })


# ========================================================================================================
# Shared profile table
# ========================================================================================================
_sm_short = upcoming_opponent_short
_sm_box = _sm_load("uww_pbp_box_score")
_sm_prior = _sm_load("uww_opponent_prior_games_box_score")
_sm_sched = _sm_load("uww_schedule")

# Rate profiles for every opponent UWW has PLAYED, from the reconstructed box scores. These describe how
# that team played AGAINST UWW -- arguably the most relevant sample for a style comparison, but not their
# season at large, which is stated on the panel rather than buried.
_sm_records = {}
if not _sm_box.empty and {"team", "opponent"}.issubset(_sm_box.columns):
    _sm_bcol = _sm_date_col(_sm_box)
    for _opp, _grp in _sm_box.groupby("opponent"):
        _them, _us = _grp[_grp["team"] != "UW-Whitewater"], _grp[_grp["team"] == "UW-Whitewater"]
        if _them.empty or _us.empty:
            continue
        _games = int(_them[_sm_bcol].nunique()) if _sm_bcol else 1
        _rec = _sm_rate_profile(_them, _us, _games or 1)
        _rec["_games"] = _games or 1
        _sm_records[_opp] = _rec

# The upcoming opponent's own prior games win over "how they looked against UWW" if both exist -- a body of
# work against several teams describes them better than one meeting.
if not _sm_prior.empty and "team" in _sm_prior.columns and _sm_short:
    _sm_pcol = _sm_date_col(_sm_prior)
    _them = _sm_prior[_sm_prior["team"].astype(str) == str(_sm_short)]
    _foes = _sm_prior[_sm_prior["team"].astype(str) != str(_sm_short)]
    if not _them.empty and not _foes.empty:
        _games = int(_them[_sm_pcol].nunique()) if _sm_pcol else 1
        _rec = _sm_rate_profile(_them, _foes, _games or 1)
        _rec["_games"] = _games or 1
        _sm_records[_sm_short] = _rec

# Height and style shares -- the three features no box score can produce, minutes-weighted across the
# rotation so a 30-minute starter counts for more than a 4-minute reserve.
_sm_people = {}
_sm_prof_tbl = _sm_load("uww_player_profiles")
if not _sm_prof_tbl.empty and "opponent" in _sm_prof_tbl.columns:
    for _opp, _grp in _sm_prof_tbl.groupby("opponent"):
        if "name" in _grp.columns:
            _grp = _grp[~_grp["name"].astype(str).str.contains(_SM_JUNK_PLAYER_RE, na=False, regex=True)]
        if _grp.empty:
            continue
        _mins = (pd.to_numeric(_grp["MIN"], errors="coerce").fillna(0.0)
                 if "MIN" in _grp.columns else pd.Series(0.0, index=_grp.index))
        _rot = _mins >= _SM_ROTATION_MIN_MPG
        if not _rot.any():
            _rot = _mins > 0
        _wts = _mins.where(_rot, 0.0)
        _total = float(_wts.sum())
        _hts = (pd.to_numeric(_grp["height_inches"], errors="coerce")
                if "height_inches" in _grp.columns else pd.Series(dtype=float))
        _usable = (_hts.notna() & (_wts > 0)) if not _hts.empty else pd.Series(False, index=_grp.index)
        _entry = {"height_in": (float((_hts[_usable] * _wts[_usable]).sum() / _wts[_usable].sum())
                                if _usable.any() else None)}
        _tags = (_grp["notes_tags_display"].astype(str)
                 if "notes_tags_display" in _grp.columns else pd.Series("", index=_grp.index))
        for _sk, _tag in (("share_shooter", "three_point_shooter"), ("share_post", "post_scorer")):
            _has = _tags.str.contains(_tag, na=False)
            _entry[_sk] = float(_wts[_has].sum() / _total) if _total > 0 else None
        _sm_people[_opp] = _entry

_sm_profiles = pd.DataFrame.from_dict(_sm_records, orient="index") if _sm_records else pd.DataFrame()
if _sm_people:
    _sm_ppl = pd.DataFrame.from_dict(_sm_people, orient="index")
    _sm_profiles = _sm_profiles.join(_sm_ppl, how="outer") if not _sm_profiles.empty else _sm_ppl
if not _sm_profiles.empty:
    for _k in _SM_WEIGHTS:
        if _k not in _sm_profiles.columns:
            _sm_profiles[_k] = None
    if "_games" not in _sm_profiles.columns:
        _sm_profiles["_games"] = 1
    _sm_profiles["_games"] = pd.to_numeric(_sm_profiles["_games"], errors="coerce").fillna(1)
    _sm_profiles = _sm_profiles.replace([float("inf"), float("-inf")], pd.NA)

# ========================================================================================================
# Direction 1: teams like THEM that we have played
# ========================================================================================================
try:
    if _sm_profiles.empty or not _sm_short or _sm_short not in _sm_profiles.index:
        _sm_problems.append(f"like_them: no style profile could be built for {_sm_short or 'the opponent'}")
    else:
        # UWW's completed games before the upcoming one. Scoped this way so a result that hasn't happened
        # yet can never appear here.
        _sm_uww_sched = _sm_sched[_sm_sched["team"].astype(str).str.contains("Whitewater", case=False, na=False)] \
            if not _sm_sched.empty and "team" in _sm_sched.columns else pd.DataFrame()
        _sm_played = _sm_uww_sched[_sm_uww_sched["outcome"].notna() & _sm_uww_sched["team_score"].notna()] \
            if not _sm_uww_sched.empty and {"outcome", "team_score"}.issubset(_sm_uww_sched.columns) \
            else pd.DataFrame()

        # Map each played game onto the name the profile table uses, keeping EVERY meeting -- a
        # home-and-home is two separate results and the split may be the most interesting thing about it.
        _sm_index = sorted([str(n) for n in _sm_profiles.index], key=len, reverse=True)
        _sm_games_by = {}
        for _, _g in _sm_played.iterrows():
            _full = str(_g.get("opponent", "")).strip()
            _hit = next((n for n in _sm_index if _full.startswith(n)), None)
            if _hit and _hit != _sm_short:
                _sm_games_by.setdefault(_hit, []).append(_g)

        _sm_ranked, _sm_thin = _sm_rank(_sm_short, list(_sm_games_by), _sm_profiles)
        if _sm_ranked is None or _sm_ranked.empty:
            _sm_problems.append(
                f"like_them: no usable comparison against the {len(_sm_games_by)} previously-played "
                f"opponent(s) -- most likely their profiles are too thin to share features with "
                f"{_sm_short}")
        else:
            # What actually happened against this style -- the reason the panel exists.
            _sm_rows_played = [g for n in _sm_ranked["opponent"] for g in _sm_games_by.get(n, [])]
            _sm_strip = ""
            if _sm_rows_played:
                _sm_df = pd.DataFrame(_sm_rows_played)
                _w = int((_sm_df["outcome"] == "W").sum())
                _l = int((_sm_df["outcome"] == "L").sum())
                _pf = pd.to_numeric(_sm_df["team_score"], errors="coerce").mean()
                _pa = pd.to_numeric(_sm_df["opponent_score"], errors="coerce").mean()
                # CONFIRMED BUG (fixed here): the comparison was against UWW's average over ALL games, and
                # the matched teams are part of that average. With three games played and all three matched,
                # it printed "+0.0 pts scored, +0.0 allowed" -- guaranteed by construction, and read as
                # "this style makes no difference". Compared against the games NOT in the matched set
                # instead; when there aren't any, the delta is left off and the strip says why.
                _matched_names = set(_sm_ranked["opponent"])
                _rest = [g for n, gs in _sm_games_by.items() if n not in _matched_names for g in gs]
                _delta = ""
                if _rest:
                    _rest_df = pd.DataFrame(_rest)
                    _rest_pf = pd.to_numeric(_rest_df["team_score"], errors="coerce").mean()
                    _rest_pa = pd.to_numeric(_rest_df["opponent_score"], errors="coerce").mean()
                    if pd.notna(_rest_pf) and pd.notna(_rest_pa):
                        _delta = (f" ({_pf - _rest_pf:+.1f} pts scored, {_pa - _rest_pa:+.1f} allowed vs our "
                                  f"other {len(_rest)} game{'s' if len(_rest) != 1 else ''})")
                else:
                    _delta = (" -- that is every game we have played, so there is no other style to "
                              "compare it against yet")
                _sm_strip = (f"UWW is {_w}-{_l} against these {len(_sm_ranked)} teams, averaging "
                             f"{_pf:.1f} scored and {_pa:.1f} allowed{_delta}.")
                _sm_dir_summary["like_them"] = {"dir_wins": _w, "dir_losses": _l, "dir_pf": round(float(_pf), 1),
                                                "dir_pa": round(float(_pa), 1)}

                _sm_strip = _sm_low_conf_prefix(_sm_ranked) + _sm_strip

            _sm_target_row = _sm_profiles.loc[_sm_short]
            for _i, (_, _r) in enumerate(_sm_ranked.iterrows(), start=1):
                _name = _r["opponent"]
                _meetings = []
                for _g in _sm_games_by.get(_name, []):
                    _sc = ""
                    if pd.notna(_g.get("team_score")) and pd.notna(_g.get("opponent_score")):
                        _sc = f" {int(_g['team_score'])}-{int(_g['opponent_score'])}"
                    _meetings.append(f"{_g.get('outcome', '')}{_sc}"
                                     + (f" ({_g.get('date')})" if _g.get("date") else ""))
                _sm_add("like_them", _i, _name, _r, _sm_profiles, _sm_target_row,
                        _sm_short, _meetings, "How we did against this style", _sm_strip, _sm_thin)
except Exception as _e:
    _sm_problems.append(f"like_them: {_e}")

# ========================================================================================================
# Direction 2: teams like US that have played them
# ========================================================================================================
# These profiles cannot come from the shared table above: that is built from scouted opponents, and the
# upcoming opponent's other opponents were never scouted. What does exist is the reconstructed box score of
# each of those games, so each team is profiled from the ONE game they played them -- a real limitation,
# which is why the Personnel rows are blank for them and the confidence figure is low.
try:
    if _sm_prior.empty or _sm_box.empty or not _sm_short:
        _sm_problems.append("like_us: needs the opponent's prior-game box scores and UWW's own")
    else:
        _sm_key = _sm_date_col(_sm_prior)
        _sm_ctx, _sm_recs = {}, {}
        for _team, _g in _sm_prior.groupby("team", dropna=True):
            if str(_team) == str(_sm_short):
                continue
            # Multiple meetings with the same team pool into one profile, exactly as they do above.
            _dates = _g[_sm_key].dropna().unique() if _sm_key else []
            _them = (_sm_prior[(_sm_prior["team"].astype(str) == str(_sm_short))
                               & (_sm_prior[_sm_key].isin(_dates))] if len(_dates)
                     else _sm_prior[_sm_prior["team"].astype(str) == str(_sm_short)])
            if _them.empty:
                continue
            _n = int(len(_dates)) or 1
            _rec = _sm_rate_profile(_g, _them, _n)
            _rec["_games"] = _n
            _sm_recs[str(_team)] = _rec

            # Pooling games is right for the PROFILE (more possessions, less noise) and wrong for the
            # RESULT, which is per game by definition -- summing PTS across three meetings produced an
            # impossible "L 225-231" scoreline. Each meeting is scored on its own.
            _meets = []
            for _d in (_dates if len(_dates) else [None]):
                _side = _g if _d is None else _g[_g[_sm_key] == _d]
                _oside = _them if _d is None else _them[_them[_sm_key] == _d]
                _a = float(pd.to_numeric(_side.get("PTS"), errors="coerce").sum())
                _b = float(pd.to_numeric(_oside.get("PTS"), errors="coerce").sum())
                if _a or _b:
                    _meets.append({"pts": _a, "their_pts": _b, "won": _a > _b, "date": _d})
            if _meets:
                _sm_ctx[str(_team)] = {"meetings": _meets}

        # UWW's own profile, built by the same function from the same kind of source.
        _sm_us = _sm_box[_sm_box["team"] == "UW-Whitewater"]
        _sm_foes = _sm_box[_sm_box["team"] != "UW-Whitewater"]
        _sm_ucol = _sm_date_col(_sm_us)
        _sm_ugames = int(_sm_us[_sm_ucol].nunique()) if (_sm_ucol and not _sm_us.empty) else 0
        if _sm_recs and not _sm_us.empty and _sm_ugames:
            _rec = _sm_rate_profile(_sm_us, _sm_foes, _sm_ugames)
            _rec["_games"] = _sm_ugames
            _sm_recs["UW-Whitewater"] = _rec

        if len(_sm_recs) < 2:
            _sm_problems.append(f"like_us: not enough reconstructed box scores from {_sm_short}'s prior games")
        else:
            _sm_tl_profiles = pd.DataFrame.from_dict(_sm_recs, orient="index")
            for _k in _SM_WEIGHTS:
                if _k not in _sm_tl_profiles.columns:
                    _sm_tl_profiles[_k] = None
            _sm_tl_ranked, _sm_tl_thin = _sm_rank("UW-Whitewater", list(_sm_ctx), _sm_tl_profiles)
            if _sm_tl_ranked is None or _sm_tl_ranked.empty:
                _sm_problems.append(f"like_us: none of {_sm_short}'s prior opponents could be compared "
                                    f"against UWW on a usable set of features")
            else:
                # Averaged over GAMES, not over teams -- a team met three times contributes three games to
                # the record and to the averages, which is what the question actually asks.
                _top = [m for n in _sm_tl_ranked["opponent"] for m in _sm_ctx.get(n, {}).get("meetings", [])]
                _all = [m for c in _sm_ctx.values() for m in c.get("meetings", [])]
                _w = sum(1 for m in _top if m["won"])
                _sm_dir_summary["like_us"] = {"dir_wins": _w, "dir_losses": len(_top) - _w,
                                              "dir_pf": round(sum(m["pts"] for m in _top) / len(_top), 1) if _top else None,
                                              "dir_pa": round(sum(m["their_pts"] for m in _top) / len(_top), 1) if _top else None}
                _pf = (sum(m["pts"] for m in _top) / len(_top)) if _top else 0
                _pa = (sum(m["their_pts"] for m in _top) / len(_top)) if _top else 0
                _field = (sum(m["pts"] for m in _all) / len(_all)) if _all else 0
                _strip = (_sm_low_conf_prefix(_sm_tl_ranked)
                          + f"They went {_w}-{len(_top) - _w} against {_sm_short} in {len(_top)} game(s), "
                          f"averaging {_pf:.1f} scored and {_pa:.1f} allowed. Across all {len(_all)} of "
                          f"their games, {_sm_short} allowed {_field:.1f} per game.")

                _sm_me_row = _sm_tl_profiles.loc["UW-Whitewater"]
                for _i, (_, _r) in enumerate(_sm_tl_ranked.iterrows(), start=1):
                    _meets = _sm_ctx.get(_r["opponent"], {}).get("meetings", [])
                    # Dates formatted like the like_them panel ("Fri, Nov 7") -- the two panels sit on the
                    # same page and printed ISO dates on one side and weekday dates on the other.
                    _meetings = [f"{'W' if m['won'] else 'L'} {int(m['pts'])}-{int(m['their_pts'])}"
                                 + (f" ({_sm_pretty_date(m['date'])})" if m.get("date") else "") for m in _meets]
                    _sm_add("like_us", _i, _r["opponent"], _r, _sm_tl_profiles, _sm_me_row,
                            "UWW", _meetings, "How teams like us did against them", _strip, _sm_tl_thin)
except Exception as _e:
    _sm_problems.append(f"like_us: {_e}")

# ========================================================================================================
style_matchups = pd.DataFrame(_sm_rows)
for _dcol in ("dir_wins", "dir_losses", "dir_pf", "dir_pa"):
    style_matchups[_dcol] = (style_matchups["direction"].map(lambda d: _sm_dir_summary.get(d, {}).get(_dcol))
                             if not style_matchups.empty else None)
if style_matchups.empty:
    style_matchups = pd.DataFrame(columns=[
        "opponent", "direction", "rank", "team", "match", "features_scored", "total_features",
        "weight_covered", "games", "confidence", "alike", "differs", "biggest_gaps", "meetings",
        "strip_label", "strip_text", "thin"])
style_matchups.to_csv(os.path.join(APP_DATA_DIR, f"{_SM_OUT}.csv"), index=False)

print(f"Wrote {_SM_OUT}.csv -- {len(style_matchups)} matched team(s) for {_sm_short or 'no opponent'}"
      + (f": {style_matchups['direction'].value_counts().to_dict()}" if not style_matchups.empty else ""))
if not style_matchups.empty and style_matchups["thin"].any():
    print("  THIN: at least one direction's best candidate shares fewer than "
          f"{_SM_MIN_FEATURES} scoring features with the target. Those are the closest available, not a "
          f"confident match.")
if _sm_problems:
    # Printed, not swallowed -- a panel silently absent from a coach's brief is the worse failure.
    print("  Directions that produced nothing:")
    for _p in _sm_problems:
        print(f"    - {_p}")
