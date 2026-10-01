import re
# 83_assemble_every_key_to_victory_into_one.py -- code for the notebook section "Assemble every Key to Victory into ONE table ---------------------------------------------"
# Runs inside the notebook via run_section("83_assemble_every_key_to_victory_into_one"); its settings are in that notebook cell.

# --- Assemble every Key to Victory into ONE table -----------------------------------------------------------
# The keys on the app's Upcoming Game page used to be built in two places: the data-driven ones here, the
# rest inside streamlit_app.py at render time. Anything else that wanted the keys -- the HTML brief below, a
# printout, an email -- had to re-derive them and could quietly end up with a different list.
#
# This cell is now the single place keys are BUILT. It writes uww_ktv_keys.csv, one row per key in display
# order, and everything downstream just renders it.
#
# All seven generators are here:
#   Data-Driven      pbp_derived_keys; "Feature our best look"; "Attack their weakest look"; "What they go
#                    to most" (the last three from video-tagged shot data)
#   Keys to Victory  the staff's written keys from the scouting report
#   Team Strengths   the staff's read on the opponent, as "Opponent strength: ..." lines
#   Lineup Scouting  attack their worst 5-man unit; counter with ours; attack their worst 3-man combo;
#                    feature our best 3-man combo
#
# READS CSVs, not the in-memory frames above, even though those are right here. Two reasons. The CSVs are
# what the app reads, so the two can't diverge on what a column is called or how it was scoped. And it
# makes this cell re-runnable on its own, which matters while the ported logic is still being checked
# against the app's output.
#
# PORTING NOTES -- worth reading before validating this against the app:
#   * Thresholds are copied verbatim, not re-chosen: 3.0 min for opponent lineups, COMBO_RULES for our 3-man
#     combos, 2.0 in the counter match, 8 attempts for our own shot looks, 5 for the opponent's, 25 for
#     the PPA shrinkage. Each was set against real data in the app; changing one here would make the two
#     lists differ for a reason that looks like a bug.
#   * Play-call resolution is ported in full (catalog canonicalization plus the regex fallback for
#     free-text notes), since dropping the fallback would silently change which play a key names.
#   * (Historical) The app used to exclude opponent == "Aurora" from stints because that game's lineup
#     columns were swapped; that is now corrected at the source and neither side excludes it. This note
#     in both consumers.
#   * The app wraps each generator in try/except and moves on. Same here, but the failure is PRINTED
#     rather than swallowed: a key silently missing from a coach's brief is the worse outcome.

from itertools import combinations as _ktv_combos

_KTV_COLS = ["opponent", "game_date", "category", "key_number", "icon", "headline",
             "evidence", "reasoning", "source", "impact", "confidence", "brief_eligible", "priority_score"]

# (_KTV_STINT_EXCLUDE removed: the swapped-lineup game is now corrected upstream, where lineups are attached
# to the play-by-play, so no opponent needs to be excluded here or in the app.)

# --- Sample-size floors for the Personnel keys ------------------------------------------------------------
# CONFIRMED BUG (fixed here): "Attack their worst lineup" fired on units with 3.0 minutes together and named a
# -5 in 3.0 min group as the headline -- two possessions of noise. It also picked the three LOWEST +/- units
# even when every qualifying unit was positive, so a +7/40 group could be printed under "attack". The floors
# are raised and a unit now has to actually be losing its minutes to be called a target.
#   NOTE FOR THE APP: the app used to compute these keys itself with the 3.0 floor. It should now render
#   uww_ktv_keys.csv only; if it still recomputes, the two lists will differ by design.
_KTV_OPP_LU_MIN_MINUTES = 8.0     # opponent 5-man unit
_KTV_OPP_3MAN_MIN_MINUTES = 12.0  # opponent 3-man combo

# ---- How "Feature the ... combo" picks OUR best 3-man combo -------------------------------------------
# Rebuilt (requested) after it proved unable to tell a good trio from a lucky one: it ranked by TOTAL +/-
# (rewarding minutes played while winning), counted blowout minutes the same as close ones, credited a trio
# for whoever else was on the floor, and needed only 10 minutes. The rules below replace that, and the
# key's reasoning text and the brief's Keys to Victory note are generated FROM them, so what coaches read
# is exactly what the code does.
COMBO_RULES = {
    "garbage_margin": 15,     # a stint starting with the margin at this or more...
    "garbage_from_period": 2, # ...in this period or later (the 2nd half, and OT) is garbage time: set aside
    "min_minutes": 40,        # competitive minutes together before a trio can be featured
    "min_games": 3,           # ...across at least this many games
    "shrink_minutes": 40,     # per-40 margin is shrunk toward 0 as if it had this many minutes of "0" added
    "min_on_off": 0.0,        # the team must do better with the trio ON than OFF (per 40) to feature it
}
_KTV_LOOK_LINEUP_MIN_ATTEMPTS = 5 # a lineup's attempts on a look before "gets it best" is claimed

# --- Categories -------------------------------------------------------------------------------------------
# Offense / Defense / Personnel. Where a key comes from a generator, the category is set explicitly by the
# generator, because the generator knows what the key is FOR -- "attack their weakest look" is an offensive
# instruction even though every number in it describes their defense, and keyword matching on the text gets
# that backwards.
#
# Only the staff's free-text keys have to be classified from words, and those fall back to "General" rather
# than being forced into one of the three. A misfiled key is worse than an unfiled one: a defensive
# instruction sitting in the offensive section is an instruction a coach reads at the wrong moment.
_KTV_CATEGORY_ORDER = ["Offense", "Defense", "Personnel", "General"]
_KTV_CATEGORY_KEYWORDS = {
    "Defense": (r"defen[sc]|guard|deny|contest|close ?out|help|rotate|box ?out|defensive (?:glass|rebound)"
                r"|take away|shut|stop|force|contain|transition d|get back|protect the (?:rim|paint)"
                r"|pack|switch|trap|press|steal|turnover(?:s)? (?:we|forced)|no (?:middle|baseline)"),
    "Offense": (r"attack|score|shoot|shot|three|3(?:'s|s)?|drive|finish|paint touch|ball movement|assist"
                r"|offensive (?:glass|rebound)|second chance|pace|push|run|execute|spacing|post up"
                r"|free ?throw|get to the line|feature|hunt"),
    "Personnel": (r"lineup|rotation|minutes|bench|foul trouble|matchup|substitut|combo|unit|starter"
                  r"|who(?:'s| is) on the floor"),
}


def _ktv_categorize(text):
    """Category for a free-text key, by word-boundary keyword match; "General" when nothing fits.

    Defense is tested first: a written key is usually phrased around what the opponent does, so "take away
    their transition threes" hits an offensive word ("threes") while plainly being a defensive
    instruction. Matching defense first stops the more specific reading losing to the more generic one.
    """
    low = str(text or "").lower()
    for category in ("Defense", "Offense", "Personnel"):
        if re.search(_KTV_CATEGORY_KEYWORDS[category], low):
            return category
    return "General"


_ktv_rows = []
_ktv_problems = []


def _ktv_load(name):
    """One exported table, or an empty frame. Missing tables are normal (early season, before_scout)."""
    try:
        return pd.read_csv(os.path.join(APP_DATA_DIR, f"{name}.csv"))
    except Exception:
        return pd.DataFrame()


def _ktv_add(icon, headline, evidence, reasoning, source, category,
             impact=None, confidence=None, brief_eligible=True):
    # impact (0-1): how big this key's edge is, set by the generator from its own numbers.
    # confidence (0-1): how much data stands behind it. Either left as None gets the model's default.
    # brief_eligible=False: a placeholder ("no data yet") -- stays on the app, never on the brief.
    _clip = lambda v: None if v is None or pd.isna(v) else max(0.0, min(1.0, float(v)))
    _ktv_rows.append({
        "impact": _clip(impact),
        "confidence": _clip(confidence),
        "brief_eligible": bool(brief_eligible),
        "opponent": upcoming_opponent_short,
        "category": category,
        "icon": icon,
        "headline": str(headline or "").strip(),
        "evidence": "" if evidence is None else str(evidence).strip(),
        "reasoning": "" if reasoning is None else str(reasoning).strip(),
        "source": source,
    })


def _ktv_last_names(lineup_str):
    """'First Last, First Last, ...' -> 'Last, Last, ...'.

    A lineup field can hold TWO units joined by " / " (a substitution mid-run), so split on that first
    and de-duplicate -- the naive comma split rendered nine names with four repeated.
    """
    names = []
    for unit in str(lineup_str or "").split(" / "):
        for full in unit.split(","):
            full = full.strip()
            if full and full not in names:
                names.append(full)
    return ", ".join(n.split()[-1] if n.split() else n for n in names)


# --- shot-look tagging (ported from the app's extract_shot_mechanic / extract_contest) ------------------
_KTV_UNCLASSIFIED_MECHANIC = "Unclassified (no mechanic tag)"
_KTV_NO_CONTEST_TAG = "Not tagged (contest recorded only on catch-and-shoot)"
_KTV_SHRINKAGE_ATTEMPTS = 25


def _ktv_mechanic(description):
    """Which kind of shot this was, from the tagger's own chained description. The three origin tests run
    AFTER the mechanic tests on purpose: they describe how a shot was created rather than how it was
    released, so a post-up finishing as a jumper still counts as a jumper."""
    if pd.isna(description):
        return None
    d = str(description)
    if "No Dribble Jumper" in d:
        return "Catch-and-shoot"
    if "Dribble Jumper" in d:
        return "Pull-up off the dribble"
    if "To Basket" in d:
        return "Drive to the basket"
    if "Offensive Rebound" in d:
        return "Putback off the offensive glass"
    if "Cut" in d:
        return "Cut to the basket"
    if "Post-Up" in d:
        return "Post-up"
    return _KTV_UNCLASSIFIED_MECHANIC


def _ktv_contest(description):
    """Defender contest, which the tagger records ONLY on catch-and-shoot jumpers -- so a missing tag means
    the dimension doesn't apply to this shot type, not that the shot was a drive."""
    if pd.isna(description):
        return None
    d = str(description)
    if "Guarded" in d:
        return "Guarded"
    if "Open" in d:
        return "Open"
    return _KTV_NO_CONTEST_TAG


def _ktv_shot_looks(shots, min_attempts=8):
    """Per mechanic-by-contest look: volume, FG%, eFG%, points per attempt, and a shrunk PPA to rank on.

    Ranked on points per attempt rather than FG% (a 34% three is worth more than a 44% two), and shrunk
    toward the overall rate by attempts so a lucky 5-of-8 bucket can't top a 30-of-70 that is genuinely
    better. Returns an empty frame when nothing clears min_attempts.
    """
    if shots.empty:
        return pd.DataFrame()
    work = shots[shots["_mechanic"].notna() & shots["_contest"].notna()].copy()
    if work.empty:
        return pd.DataFrame()

    if "shot_type" in work.columns:
        value = pd.to_numeric(work["shot_type"], errors="coerce")
        work["_value"] = value.where(value.isin([2, 3]), 2)
    else:
        work["_value"] = 2
    work["_points"] = work["_value"] * work["_make"].astype(int)
    work["_is_three"] = work["_value"] == 3
    work["_three_make"] = (work["_is_three"] & work["_make"].astype(bool)).astype(int)

    grouped = work.groupby(["_mechanic", "_contest"]).agg(
        Attempts=("_make", "count"), Makes=("_make", "sum"),
        Points=("_points", "sum"), Threes=("_is_three", "sum"), ThreeMakes=("_three_make", "sum"),
    ).reset_index()
    grouped = grouped[grouped["Attempts"] >= min_attempts]
    if grouped.empty:
        return pd.DataFrame()

    total_attempts = float(work["_make"].count())
    baseline_ppa = float(work["_points"].sum()) / total_attempts if total_attempts else 0.0
    grouped["FG%"] = 100 * grouped["Makes"] / grouped["Attempts"]
    grouped["eFG%"] = 100 * (grouped["Makes"] + 0.5 * grouped["ThreeMakes"]) / grouped["Attempts"]
    grouped["PPA"] = grouped["Points"] / grouped["Attempts"]
    grouped["Share"] = 100 * grouped["Attempts"] / total_attempts if total_attempts else 0.0
    grouped["ThreeRate"] = 100 * grouped["Threes"] / grouped["Attempts"]
    credibility = grouped["Attempts"] / (grouped["Attempts"] + _KTV_SHRINKAGE_ATTEMPTS)
    grouped["PPA_adj"] = grouped["PPA"] * credibility + baseline_ppa * (1 - credibility)
    grouped.attrs["baseline_ppa"] = baseline_ppa
    return grouped.sort_values("PPA_adj", ascending=False).reset_index(drop=True)


def _ktv_shot_stat_line(row, baseline_ppa=None):
    parts = [
        f"{int(row['Makes'])}/{int(row['Attempts'])} ({row['FG%']:.0f}% FG, {row['eFG%']:.0f}% eFG)",
        f"{row['PPA']:.2f} pts/attempt",
    ]
    if baseline_ppa:
        parts.append(f"{row['PPA'] - baseline_ppa:+.2f} vs all looks ({baseline_ppa:.2f})")
    parts.append(f"{row['Share']:.0f}% of attempts")
    # CONFIRMED BUG (fixed here): printed "100% from three", which reads as a make rate and sat next to
    # "50% FG" on the same line. ThreeRate is the SHARE of these attempts that are threes.
    if row.get("ThreeRate", 0) >= 99.5:
        parts.append("all threes")
    elif row.get("ThreeRate", 0) >= 1:
        parts.append(f"{row['ThreeRate']:.0f}% of them threes")
    return " \u00b7 ".join(parts)


def _ktv_describe_look(mechanic, contest=None):
    """Plain-language name for a shot type. The contest dimension only exists for catch-and-shoot, so for
    every other shot the honest rendering is to say nothing about it rather than paste on a caveat about
    the tagging system as if it described the shot."""
    if mechanic is None or (isinstance(mechanic, float) and mechanic != mechanic):
        return "untagged shots"
    m = str(mechanic)
    if m == _KTV_UNCLASSIFIED_MECHANIC:
        m = "shots with no mechanic tag"
    if contest in ("Guarded", "Open"):
        return f"{m} ({str(contest).lower()})"
    return m


def _ktv_tag_shots(events, team=None, exclude_team=None):
    """Shot events with _mechanic/_contest/_make attached, filtered to tagged video only."""
    if events.empty or "event_type" not in events.columns:
        return pd.DataFrame()
    shots = events[events["event_type"].isin(["made_shot", "missed_shot"])].copy()
    if team is not None:
        shots = shots[shots["team"] == team]
    if exclude_team is not None:
        shots = shots[shots["team"].notna() & (shots["team"] != exclude_team)]
    if shots.empty or "video_description" not in shots.columns:
        return pd.DataFrame()
    shots = shots[shots["video_description"].notna()]
    if shots.empty:
        return shots
    shots["_mechanic"] = shots["video_description"].apply(_ktv_mechanic)
    shots["_contest"] = shots["video_description"].apply(_ktv_contest)
    shots["_make"] = shots["event_type"] == "made_shot"
    return shots


# --- play-call resolution (ported in full) --------------------------------------------------------------
_KTV_NON_PLAY_CALL_PATTERNS = (
    r"^end\s+of\b",
    r"^(half|halftime|game|period|quarter|ot\d*|overtime)$",
    r"^(time\s*out|timeout|to)$",
    r"^(dead\s*ball|jump\s*ball|tip\s*off|tipoff)$",
    r"^(shot\s*clock|clock)\b",
    r"^(free\s*throws?|ft)$",
    r"^(n/?a|none|unknown|tbd|misc|other|untagged)$",
)
_KTV_QUALIFIER_WORDS = {
    "good", "bad", "great", "ok", "okay", "nice", "poor",
    "make", "made", "makes", "miss", "missed", "misses", "score", "scored", "bucket",
    "and1", "and-1", "foul", "fouled", "to", "turnover", "tov", "execution", "exec",
}
_KTV_PLAY_ACRONYMS = {"ELOB", "SLOB", "BLOB", "ATO", "DHO", "ISO", "PNR", "OB", "UCLA", "STS"}


def _ktv_play_norm(text):
    return re.sub(r"[^A-Z0-9]", "", str(text).upper())


_ktv_play_catalog = {}
_ktv_cat = _ktv_load("uww_plays_catalog")
if not _ktv_cat.empty and "play_name" in _ktv_cat.columns:
    for _, _cr in _ktv_cat.iterrows():
        _ks = [k for k in str(_cr.get("match_keys", "")).split("|") if k] or [_ktv_play_norm(_cr["play_name"])]
        for _k in _ks:
            _ktv_play_catalog.setdefault(_k, str(_cr["play_name"]))


def _ktv_is_non_play(name):
    t = re.sub(r"\s+", " ", str(name or "")).strip().lower()
    return True if not t else any(re.search(p, t) for p in _KTV_NON_PLAY_CALL_PATTERNS)


def _ktv_strip_qualifiers(name):
    """Only whole trailing tokens from a known list, only from the END -- a 'longest prefix that matches
    the catalog' rule would turn the real play 'Twins Swirl' into the different real play 'Twins'."""
    toks = str(name or "").strip().split()
    while len(toks) > 1 and toks[-1].strip("().,+-\"'").lower() in _KTV_QUALIFIER_WORDS:
        toks.pop()
    return " ".join(toks)


def _ktv_title_case(name):
    """Consistent spelling for a call the catalog doesn't list, so 'TWINS SWIRL' and 'Twins Swirl' don't
    group as two plays. Short or digit-bearing tokens stay as typed so DHO and P-4 survive."""
    out = []
    for tok in re.split(r"(\s+)", str(name).strip()):
        if not tok or tok.isspace():
            out.append(tok)
        elif tok.upper().strip("()\"'") in _KTV_PLAY_ACRONYMS:
            out.append(tok.upper())
        elif len(tok) <= 3 or any(ch.isdigit() for ch in tok):
            out.append(tok.upper() if tok.isupper() else tok)
        else:
            out.append(tok[:1].upper() + tok[1:].lower())
    return "".join(out)


def _ktv_canonical_play(name):
    if name is None or (isinstance(name, float) and name != name):
        return name
    hit = _ktv_play_catalog.get(_ktv_play_norm(name))
    if hit:
        return hit
    stripped = _ktv_strip_qualifiers(name)
    if stripped and _ktv_play_norm(stripped) != _ktv_play_norm(name):
        hit = _ktv_play_catalog.get(_ktv_play_norm(stripped))
        if hit:
            return hit
    if _ktv_is_non_play(stripped or name):
        return None
    return _ktv_title_case(stripped or name)


def _ktv_extract_play_call(note):
    """A short, mostly-uppercase leading phrase before the word EXECUTION -- the one consistent signal in
    this staff's notation. Anything else returns None rather than guessing a name."""
    if pd.isna(note):
        return None
    m = re.match(r"^([A-Z][A-Z0-9\-&' ]{1,24}?)\s+EXECUTION\b", str(note).strip())
    return m.group(1).strip() if m else None


def _ktv_resolve_play_calls(df):
    """Prefer the parser's structured play_call column; fall back to the regex on free-text coach notes for
    rows the play log doesn't cover; canonicalize both against the catalog so one play has one name."""
    if "coach_note" in df.columns and _KTV_USE_COACH_NOTE_PLAY_CALLS:
        regex_fallback = df["coach_note"].apply(_ktv_extract_play_call)
    else:
        regex_fallback = pd.Series([None] * len(df), index=df.index)
    if "play_call" not in df.columns:
        return regex_fallback.apply(_ktv_canonical_play)
    has_real = df["play_call"].notna() & (df["play_call"].astype(str).str.strip() != "")
    return df["play_call"].where(has_real, regex_fallback).apply(_ktv_canonical_play)


# "Usually" is a claim about a pattern, so it needs enough repetitions to be one. Without these floors a
# single tagged possession produced "Usually comes off Twins Right Swirl (1x this season)" -- a sentence a
# coach would reasonably act on, resting on one clip. The share floor covers the other half of the problem:
# 3 of 40 is a real count and still not what they usually do.
_KTV_MIN_PLAY_CALLS = 3
_KTV_MIN_PLAY_SHARE = 0.25

# The play log is the reliable source. The regex fallback reads a play name out of free-text coach notes
# ("TWINS RIGHT SWIRL EXECUTION = ..."), which is how a name can still appear after the structured
# play_call data has been cleared out. Set this False to use the play log only.
_KTV_USE_COACH_NOTE_PLAY_CALLS = True


def _ktv_top_play_name(rows):
    """The play call these possessions usually come out of (same floors as _ktv_top_play_text), or None."""
    if rows.empty or not ({"coach_note", "play_call"} & set(rows.columns)):
        return None
    calls = _ktv_resolve_play_calls(rows).dropna()
    if calls.empty:
        return None
    counts = calls.value_counts()
    top, n = counts.index[0], int(counts.iloc[0])
    return None if n < _KTV_MIN_PLAY_CALLS or (n / len(calls)) < _KTV_MIN_PLAY_SHARE else str(top)


def _ktv_top_play_text(rows, suffix=""):
    if rows.empty or not ({"coach_note", "play_call"} & set(rows.columns)):
        return None
    calls = _ktv_resolve_play_calls(rows).dropna()
    if calls.empty:
        return None
    counts = calls.value_counts()
    top, n = counts.index[0], int(counts.iloc[0])
    if n < _KTV_MIN_PLAY_CALLS or (n / len(calls)) < _KTV_MIN_PLAY_SHARE:
        return None
    return (f"Usually comes off {top}{suffix} "
            f"({n} of {len(calls)} tagged possessions this season)")


# --- lineup profile matching (ported from lineup_profile / profile_distance / counter_lineups) ----------
_KTV_STYLE_TAGS = ("three_point_shooter", "slasher_driver", "post_scorer", "playmaker",
                   "rebounder", "catch_and_shoot")
_KTV_POSITION_SLOTS = ("Guard", "Wing", "Forward/Post")
_KTV_PROFILE_WEIGHTS = {**{f"pos_{p}": 1.0 for p in _KTV_POSITION_SLOTS},
                        "starters": 0.5,
                        **{f"tag_{t}": 0.5 for t in _KTV_STYLE_TAGS}}


def _ktv_safe_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


_ktv_player_lookup = {}
_ktv_prof = _ktv_load("uww_player_profiles")
if not _ktv_prof.empty and "name" in _ktv_prof.columns:
    for _, _pr in _ktv_prof.iterrows():
        _nm = str(_pr.get("name", "")).strip()
        if not _nm:
            continue
        _tags = str(_pr.get("notes_tags_display", "") or "")
        _ktv_player_lookup[(str(_pr.get("opponent", "")).strip(), _nm.casefold())] = {
            "position_group": str(_pr.get("position_group", "") or "Unknown"),
            "role": str(_pr.get("role", "") or ""),
            "height_inches": _ktv_safe_float(_pr.get("height_inches")),
            "tags": {t.strip() for t in _tags.split(",") if t.strip()},
        }


def _ktv_lineup_profile(opponent, lineup_str):
    """None when fewer than three of the five players resolve -- a profile built from two known players
    describes the gaps in the scouting data more than it describes the lineup."""
    names = [n.strip() for n in str(lineup_str).split(",") if n.strip()]
    known = [p for p in (_ktv_player_lookup.get((str(opponent).strip(), n.casefold())) for n in names) if p]
    if len(known) < 3:
        return None
    profile = {f"pos_{slot}": 0.0 for slot in _KTV_POSITION_SLOTS}
    for player in known:
        key = f"pos_{player['position_group']}"
        if key in profile:
            profile[key] += 1.0
    heights = [p["height_inches"] for p in known if p["height_inches"]]
    profile["height"] = (sum(heights) / len(heights)) if heights else None
    profile["starters"] = float(sum(1 for p in known if p["role"] == "Starter"))
    for tag in _KTV_STYLE_TAGS:
        profile[f"tag_{tag}"] = float(sum(1 for p in known if tag in p["tags"]))
    return profile


def _ktv_profile_distance(a, b):
    """Height compared in 3-inch units so a three-inch difference counts about the same as one position
    slot differing; in raw inches it would swamp every other feature."""
    if not a or not b:
        return float("inf")
    total = sum(w * (a.get(k, 0.0) - b.get(k, 0.0)) ** 2 for k, w in _KTV_PROFILE_WEIGHTS.items())
    if a.get("height") and b.get("height"):
        total += ((a["height"] - b["height"]) / 3.0) ** 2
    return total ** 0.5


def _ktv_describe_profile(profile):
    if not profile:
        return ""
    bits = []
    mix = [f"{int(profile['pos_' + slot])} {slot.split('/')[0].lower()}"
           for slot in _KTV_POSITION_SLOTS if profile.get(f"pos_{slot}")]
    if mix:
        bits.append(", ".join(mix))
    if profile.get("height"):
        inches = profile["height"]
        bits.append(f"avg {int(inches // 12)}'{int(round(inches % 12))}\"")
    traits = [t.replace("_", " ") for t in _KTV_STYLE_TAGS if profile.get(f"tag_{t}", 0) >= 2]
    if traits:
        bits.append(" / ".join(traits))
    return " \u00b7 ".join(bits)


def _ktv_counter_lineups(short, target_lineup, stints_df, min_matched_minutes=40.0, min_lineup_minutes=2.0):
    """Our 5-man units by net margin against opponent lineups that RESEMBLE target_lineup.

    Walks outward from the most similar unit we've faced until enough floor time is gathered, so the
    sample adapts to how much comparable basketball has been played rather than using a fixed cutoff.
    Returns (table, matched_minutes, n_similar, target_description); table is None whenever the match
    can't be made, so the caller says so rather than showing a season-wide ranking under a
    matchup-specific heading.
    """
    target = _ktv_lineup_profile(short, target_lineup)
    needed = {"opponent", "opp_lineup", "uww_lineup", "stint_minutes", "uww_margin_change"}
    if target is None or stints_df is None or stints_df.empty or not needed <= set(stints_df.columns):
        return None, 0.0, 0, _ktv_describe_profile(target)

    faced = stints_df[["opponent", "opp_lineup"]].dropna().drop_duplicates()
    scored = []
    for opp, lineup in faced.itertuples(index=False):
        distance = _ktv_profile_distance(target, _ktv_lineup_profile(opp, lineup))
        if distance != float("inf"):
            scored.append((distance, opp, lineup))
    if not scored:
        return None, 0.0, 0, _ktv_describe_profile(target)
    scored.sort(key=lambda row: row[0])

    minutes_by_unit = stints_df.groupby(["opponent", "opp_lineup"])["stint_minutes"].sum()
    keep, matched_minutes = set(), 0.0
    for _, opp, lineup in scored:
        keep.add((opp, lineup))
        matched_minutes += float(minutes_by_unit.get((opp, lineup), 0.0))
        if matched_minutes >= min_matched_minutes:
            break
    if matched_minutes <= 0:
        return None, 0.0, 0, _ktv_describe_profile(target)

    matched = stints_df[[(o, l) in keep for o, l in zip(stints_df["opponent"], stints_df["opp_lineup"])]]
    agg = (matched.groupby("uww_lineup")
                  .agg(MIN=("stint_minutes", "sum"), net=("uww_margin_change", "sum")).reset_index())
    agg = agg[agg["MIN"] >= min_lineup_minutes]
    if agg.empty:
        return None, matched_minutes, len(keep), _ktv_describe_profile(target)
    agg["rate"] = agg["net"] / agg["MIN"]
    return agg.sort_values("rate", ascending=False), matched_minutes, len(keep), _ktv_describe_profile(target)


# ========================================================================================================
# Build the keys
# ========================================================================================================
_ktv_game_date = None
try:
    _ktv_game_date = game_date_for(upcoming_opponent_short)
except Exception:
    pass

_ktv_short = upcoming_opponent_short

# --- A. Data-driven keys already built above from play-by-play -----------------------------------------
try:
    _dk = _ktv_load("uww_pbp_derived_keys")
    if not _dk.empty and "opponent" in _dk.columns and _ktv_short:
        _dk = _dk[_dk["opponent"].astype(str) == str(_ktv_short)]
        if "key_number" in _dk.columns:
            _dk = _dk.sort_values("key_number")
        for _, _k in _dk.iterrows():
            # Both derived keys are instructions about what to take away, i.e. defensive.
            _ktv_add("\U0001f4ca", _k.get("title"), _k.get("supporting_stats"),
                     _k.get("recommendation"), "Data-Driven", "Defense")
except Exception as _e:
    _ktv_problems.append(f"Data-Driven (pbp_derived_keys): {_e}")

# --- B/C. The staff's written report --------------------------------------------------------------------
# Both topics store their items as one "|"-joined string with "1. " numbering baked in.
try:
    _gp = _ktv_load("uww_opponent_game_plans")
    if not _gp.empty and {"opponent", "topic", "notes"}.issubset(_gp.columns) and _ktv_short:
        _plan = _gp[_gp["opponent"].astype(str) == str(_ktv_short)]
        # Team Strengths are classified as Defense outright rather than by keywords: an opponent strength
        # is by definition a thing we have to take away, whatever words the staff used to describe it.
        # That also dodges a real false positive -- "two playmaking guards" matched the defensive keyword
        # "guard" by accident, and "second-chance points" matched nothing at all.
        for _topic, _icon, _source, _prefix, _fixed_cat in (
            ("KEYS TO VICTORY", "\U0001f4cb", "Keys to Victory", "", None),
            ("TEAM STRENGTHS", "\u26a0\ufe0f", "Team Strengths", "Opponent strength: ", "Defense"),
        ):
            _rows = _plan[_plan["topic"].astype(str).str.strip().str.upper() == _topic]
            if _rows.empty:
                continue
            for _item in str(_rows.iloc[0]["notes"]).split("|"):
                _item = re.sub(r"^\d+\.\s*", "", _item.strip())
                if _item and _item.lower() != "nan":
                    # The staff's written Keys to Victory are the only ones read off the text.
                    _ktv_add(_icon, f"{_prefix}{_item}", None, None, _source,
                             _fixed_cat or _ktv_categorize(_item))
except Exception as _e:
    _ktv_problems.append(f"Keys to Victory / Team Strengths (game plans): {_e}")

# --- lineup data, shared by the four Lineup Scouting keys ------------------------------------------------
_ktv_stints = _ktv_load("uww_lineup_stints")
_ktv_uww_lu = None
if not _ktv_stints.empty:
    # No opponent is excluded any more: the one game with swapped lineup columns (vs Aurora) is corrected at
    # the source, where lineups are attached to the play-by-play. Excluding the opponent threw away every
    # game against them -- including, with Aurora up next, the most relevant one.
    _ktv_stints = _ktv_stints.copy()
    if {"end_uww_score", "start_prev_uww_score"}.issubset(_ktv_stints.columns):
        _ktv_stints["uww_pts"] = _ktv_stints["end_uww_score"] - _ktv_stints["start_prev_uww_score"]
    if {"uww_lineup", "stint_minutes", "uww_margin_change"}.issubset(_ktv_stints.columns):
        _ktv_uww_lu = _ktv_stints.groupby("uww_lineup").agg(
            MIN=("stint_minutes", "sum"),
            PTS=("uww_pts", "sum") if "uww_pts" in _ktv_stints.columns else ("stint_minutes", "size"),
            plus_minus=("uww_margin_change", "sum"),
            GP=("game_date", "nunique"),
        ).reset_index().rename(columns={"uww_lineup": "lineup", "plus_minus": "+/-"})

# The opponent lineup table carries no opponent column, so validate it actually belongs to THIS opponent
# by checking its player names against their roster. Without this, a stale table left from the previous
# opponent gets scouted as if it were theirs.
_ktv_opp_lu = _ktv_load("uww_opp_lineup_season_box")
if _ktv_opp_lu.empty or "MIN" not in _ktv_opp_lu.columns:
    _ktv_opp_lu = None
else:
    _names = set()
    for _tbl in ("uww_player_profiles", "uww_opponent_rosters"):
        _t = _ktv_load(_tbl)
        if not _t.empty and "opponent" in _t.columns and _ktv_short:
            _names = set(_t[_t["opponent"].astype(str) == str(_ktv_short)]["name"].dropna())
        if _names:
            break
    if _names and "lineup" in _ktv_opp_lu.columns:
        _lu_players = set()
        for _lu in _ktv_opp_lu["lineup"].dropna():
            _lu_players.update(p.strip() for p in str(_lu).split(","))
        if not (_lu_players & _names):
            _ktv_opp_lu = None
    if _ktv_opp_lu is not None:
        for _c in ("MIN", "PTS", "+/-", "GP"):
            if _c in _ktv_opp_lu.columns:
                _ktv_opp_lu[_c] = pd.to_numeric(_ktv_opp_lu[_c], errors="coerce").fillna(0)

# --- D. Attack their worst 5-man unit --------------------------------------------------------------------
try:
    if _ktv_opp_lu is not None and not _ktv_opp_lu.empty:
        _vl = _ktv_opp_lu.copy()
        _vl["_pm_fg"] = pd.to_numeric(_vl["FG%"], errors="coerce").fillna(0) if "FG%" in _vl.columns else 0
        if "TO" in _vl.columns:
            _vl["_to_rate"] = (_vl["TO"] / _vl["MIN"].replace(0, float("nan")) * 40).round(1)
        _vl_qual = _vl[_vl["MIN"] >= _KTV_OPP_LU_MIN_MINUTES]
        _worst = _vl_qual[_vl_qual["+/-"] < 0].nsmallest(3, "+/-")
        if not _worst.empty:
            _lines = ["Worst +/- lineups:"]
            for _, _r in _worst.iterrows():
                _fg = f", {_r['_pm_fg']:.0f}% FG" if _r.get("_pm_fg", 0) > 0 else ""
                _lines.append(f"{_r['+/-']:+.1f} in {_r['MIN']:.1f} min{_fg} \u2014 {_ktv_last_names(_r['lineup'])}")
            if "_to_rate" in _vl_qual.columns:
                _high_to = _vl_qual.nlargest(2, "_to_rate")
                if not _high_to.empty:
                    _lines.append("Highest TO rate (per 40 min):")
                    for _, _r in _high_to.iterrows():
                        _lines.append(f"{_r['_to_rate']:.1f} TO/40 \u2014 {_ktv_last_names(_r['lineup'])}")
            _ktv_add("\U0001f512",
                     f"Attack {_ktv_short}'s {_ktv_last_names(_worst.iloc[0]['lineup'])} lineup",
                     "\n".join(_lines),
                     f"{_ktv_short}'s most exploitable units: their worst net-rating lineups with real "
                     f"minutes this season ({_KTV_OPP_LU_MIN_MINUTES:.0f}+ min, losing their minutes), and "
                     f"the lineups that give the ball away most per 40 "
                     f"minutes. The headline names the worst of them.",
                     "Lineup Scouting", "Personnel",
                     impact=-_worst.iloc[0]['+/-'] / max(_worst.iloc[0]['MIN'], 1) * 40 / 20, confidence=_worst.iloc[0]['MIN'] / 40)
except Exception as _e:
    _ktv_problems.append(f"Lineup Scouting (attack worst 5-man): {_e}")

# --- E. Counter with our best unit -----------------------------------------------------------------------
# Two modes, and the key always says which: MATCHED is our net margin against opponent lineups that
# resemble the one being prepared for -- a genuine counter. FALLBACK is our best units season-wide, which
# is useful but NOT opponent-specific and is labelled as such rather than dressed up as a matchup call.
try:
    _target = None
    if _ktv_opp_lu is not None and not _ktv_opp_lu.empty:
        _top = _ktv_opp_lu.nlargest(1, "MIN")
        if not _top.empty:
            _target = _top.iloc[0]["lineup"]

    _matched, _matched_min, _n_similar, _target_desc = (None, 0.0, 0, "")
    if _target is not None:
        _matched, _matched_min, _n_similar, _target_desc = _ktv_counter_lineups(
            _ktv_short, _target, _ktv_stints)

    if _matched is not None and not _matched.empty:
        _rows = list(_matched.head(3).iterrows())
        _caption = "\n".join(
            f"{_r['rate']:+.2f}/min ({_r['net']:+.0f} in {_r['MIN']:.1f} min) \u2014 {_ktv_last_names(_r['uww_lineup'])}"
            for _, _r in _rows)
        _reason = [f"UWW's best net margin against opponent units that resemble {_ktv_short}'s most-used "
                   f"lineup ({_ktv_last_names(_target)})."]
        if _target_desc:
            _reason.append(f"Target profile: {_target_desc}.")
        _reason.append(f"Measured across {_n_similar} comparable opponent unit(s), {_matched_min:.0f} min "
                       f"this season.")
        _ktv_add("\U0001f512", f"Counter with {_ktv_last_names(_rows[0][1]['uww_lineup'])}",
                 _caption, " ".join(_reason), "Lineup Scouting", "Personnel",
                 impact=_rows[0][1]['rate'] * 2, confidence=_matched_min / 60)
    elif _ktv_uww_lu is not None and not _ktv_uww_lu.empty:
        _fb = _ktv_uww_lu[_ktv_uww_lu["MIN"] >= _KTV_OPP_LU_MIN_MINUTES].nlargest(3, "+/-")
        if not _fb.empty:
            _rows = list(_fb.iterrows())
            _caption = "\n".join(
                f"{_r['+/-']:+.1f} total ({(_r['+/-'] / _r['MIN'] if _r['MIN'] > 0 else 0.0):+.2f}/min in "
                f"{_r['MIN']:.1f} min) \u2014 {_ktv_last_names(_r['lineup'])}" for _, _r in _rows)
            _why = ("no comparable opponent lineups on record yet" if _target is not None
                    else "no opponent lineup data yet")
            _ktv_add("\U0001f512", f"Counter with {_ktv_last_names(_rows[0][1]['lineup'])}", _caption,
                     f"UWW's best lineups by net margin season-wide \u2014 NOT matchup-specific, because "
                     f"there are {_why}.", "Lineup Scouting", "Personnel",
                     impact=0.3, confidence=0.3)
except Exception as _e:
    _ktv_problems.append(f"Lineup Scouting (counter lineup): {_e}")

# --- F. 3-man combinations -------------------------------------------------------------------------------
# Same idea as the 5-man keys but for the smaller units. The 3-man aggregates only carry MIN/PTS/+/-/GP
# (no FG%/TO), so this is scoped to net margin rather than shooting or turnovers.
# Both reset BEFORE the try: if the first half raised on a re-run, the second frame would otherwise keep its
# value from the previous run and be exported below as if it were current.
_uww_3man = None
_opp_3man = None
try:
    _uww_3man = None
    if _ktv_stints is not None and not _ktv_stints.empty and "uww_lineup" in _ktv_stints.columns:
        # Garbage time: a stint that STARTS in the 2nd half (or later) with the game already decided.
        _CR = COMBO_RULES
        _st_all = _ktv_stints.copy()
        _st_all["_min"] = pd.to_numeric(_st_all["stint_minutes"], errors="coerce").fillna(0)
        _st_all["_mc"] = pd.to_numeric(_st_all["uww_margin_change"], errors="coerce").fillna(0)
        _garbage_excludable = {"start_prev_uww_score", "start_prev_opp_score", "start_period"}.issubset(_st_all.columns)
        if _garbage_excludable:
            _start_margin = (pd.to_numeric(_st_all["start_prev_uww_score"], errors="coerce")
                             - pd.to_numeric(_st_all["start_prev_opp_score"], errors="coerce")).abs()
            _st_all["_garbage"] = ((pd.to_numeric(_st_all["start_period"], errors="coerce") >= _CR["garbage_from_period"])
                                   & (_start_margin >= _CR["garbage_margin"])).fillna(False)
        else:
            # Older stint export, from before start position was added to lineup_stints -- nothing CAN be set
            # aside, so every trio's "competitive minutes" below silently includes any blowout stretches too.
            # This degrades the whole point of the rule, so it is stated on the key itself (not just printed
            # to the notebook run) -- a coach reading "Feature the ... combo" with no caveat has no way to
            # know the safeguard didn't actually run.
            _st_all["_garbage"] = False
            _ktv_problems.append("3-man combos: stints have no start period -- garbage time could not be excluded; "
                                 "re-run from the lineup-stint cell.")
        _clean = _st_all[~_st_all["_garbage"]]
        _clean_min_total = float(_clean["_min"].sum())
        _clean_mc_total = float(_clean["_mc"].sum())

        _recs = []
        for _, _st in _st_all.iterrows():
            _players = sorted(p.strip() for p in str(_st["uww_lineup"]).split(","))
            for _combo in _ktv_combos(_players, 3):
                _recs.append({"lineup": ", ".join(_combo), "stint_minutes": _st["_min"],
                              "uww_pts": _st.get("uww_pts", 0),
                              "uww_margin_change": _st["_mc"], "garbage": bool(_st["_garbage"]),
                              "game_date": _st.get("game_date")})
        if _recs:
            _r3 = pd.DataFrame(_recs)
            # Totals over EVERY minute -- what the brief's "Top 3-man combos" table shows (ranked by minutes).
            _uww_3man = _r3.groupby("lineup").agg(
                MIN=("stint_minutes", "sum"), PTS=("uww_pts", "sum"),
                plus_minus=("uww_margin_change", "sum"), GP=("game_date", "nunique"),
            ).reset_index().rename(columns={"plus_minus": "+/-"})
            # Competitive minutes only -- what the "Feature the ... combo" key is chosen from.
            _c3 = _r3[~_r3["garbage"]].groupby("lineup").agg(
                clean_min=("stint_minutes", "sum"), clean_pm=("uww_margin_change", "sum"),
                clean_gp=("game_date", "nunique")).reset_index()
            _g3 = _r3[_r3["garbage"]].groupby("lineup")["stint_minutes"].sum().rename("garbage_min").reset_index()
            _uww_3man = _uww_3man.merge(_c3, on="lineup", how="left").merge(_g3, on="lineup", how="left")
            _uww_3man[["clean_min", "clean_pm", "clean_gp", "garbage_min"]] = \
                _uww_3man[["clean_min", "clean_pm", "clean_gp", "garbage_min"]].fillna(0)
            _cm = _uww_3man["clean_min"]
            _uww_3man["per40"] = (_uww_3man["clean_pm"] / _cm * 40).where(_cm > 0)
            # Shrunk toward zero: a trio with few minutes can't post an extreme rate just by luck.
            _uww_3man["shrunk_per40"] = _uww_3man["clean_pm"] / (_cm + _CR["shrink_minutes"]) * 40
            # ON vs OFF: our per-40 margin in competitive minutes WITH the trio minus WITHOUT it. This is
            # what separates the trio from whoever else happened to be on the floor with them.
            _off_min = _clean_min_total - _cm
            _uww_3man["off_per40"] = ((_clean_mc_total - _uww_3man["clean_pm"]) / _off_min * 40).where(_off_min > 0)
            _uww_3man["on_off"] = _uww_3man["per40"] - _uww_3man["off_per40"]

    _opp_3man = None
    if _ktv_opp_lu is not None and not _ktv_opp_lu.empty:
        _recs = []
        for _, _r in _ktv_opp_lu.iterrows():
            _players = sorted(p.strip() for p in str(_r["lineup"]).split(","))
            if len(_players) >= 3:
                for _combo in _ktv_combos(_players, 3):
                    _recs.append({"lineup": ", ".join(_combo),
                                  "MIN": float(_r["MIN"]) if pd.notna(_r["MIN"]) else 0,
                                  "PTS": float(_r["PTS"]) if pd.notna(_r.get("PTS")) else 0,
                                  "+/-": float(_r["+/-"]) if pd.notna(_r.get("+/-")) else 0,
                                  "GP": float(_r["GP"]) if pd.notna(_r.get("GP")) else 1})
        if _recs:
            _opp_3man = pd.DataFrame(_recs).groupby("lineup").agg(
                MIN=("MIN", "sum"), PTS=("PTS", "sum"), plus_minus=("+/-", "sum"), GP=("GP", "max"),
            ).reset_index().rename(columns={"plus_minus": "+/-"})

    if _opp_3man is not None and not _opp_3man.empty:
        _worst3 = _opp_3man[(_opp_3man["MIN"] >= _KTV_OPP_3MAN_MIN_MINUTES)
                            & (_opp_3man["+/-"] < 0)].nsmallest(3, "+/-")
        if not _worst3.empty:
            _lines = ["Worst +/- 3-man combos:"] + [
                f"{_r['+/-']:+.1f} in {_r['MIN']:.1f} min \u2014 {_ktv_last_names(_r['lineup'])}"
                for _, _r in _worst3.iterrows()]
            _ktv_add("\U0001f512",
                     f"Attack {_ktv_short}'s {_ktv_last_names(_worst3.iloc[0]['lineup'])} combo",
                     "\n".join(_lines),
                     f"{_ktv_short}'s most exploitable 3-man combinations: their worst net-rating units "
                     f"with real minutes this season ({_KTV_OPP_3MAN_MIN_MINUTES:.0f}+ min).",
                     "Lineup Scouting", "Personnel",
                     impact=-_worst3.iloc[0]['+/-'] / max(_worst3.iloc[0]['MIN'], 1) * 40 / 20, confidence=_worst3.iloc[0]['MIN'] / 40)

    if _uww_3man is not None and not _uww_3man.empty and "shrunk_per40" in _uww_3man.columns:
        _CR = COMBO_RULES
        _elig = _uww_3man[(_uww_3man["clean_min"] >= _CR["min_minutes"])
                          & (_uww_3man["clean_gp"] >= _CR["min_games"])
                          & (_uww_3man["shrunk_per40"] > 0)
                          & (_uww_3man["on_off"] > _CR["min_on_off"])]
        # Trios drawn from the same five-man unit that always played together have IDENTICAL numbers; listing
        # three of them says the same thing three times. Collapse each identical group to its first trio and
        # say how many others shared it -- that is itself useful (it's really one unit, not three combos).
        _ranked = _elig.sort_values("shrunk_per40", ascending=False).copy()
        _ranked["_sig"] = _ranked["clean_min"].round(2).astype(str) + "|" + _ranked["clean_pm"].round(2).astype(str)
        _dupes = _ranked.groupby("_sig")["lineup"].transform("count") - 1
        _ranked["_same_as"] = _dupes
        _best3 = _ranked.drop_duplicates("_sig").head(3)
        _n_short = int(((_uww_3man["clean_min"] > 0) & ((_uww_3man["clean_min"] < _CR["min_minutes"])
                                                         | (_uww_3man["clean_gp"] < _CR["min_games"]))).sum())
        if not _best3.empty:
            _lines = [
                f"{_ktv_last_names(_r['lineup'])}: {_r['shrunk_per40']:+.1f} per 40 after shrinkage "
                f"({_r['per40']:+.1f} raw) \u00b7 on/off {_r['on_off']:+.1f} \u00b7 {_r['clean_min']:.0f} competitive "
                f"min in {int(_r['clean_gp'])} games"
                + (f" ({_r['garbage_min']:.0f} garbage-time min set aside)" if _r["garbage_min"] >= 1
                   else " (0 garbage-time min found)" if _garbage_excludable else
                   " \u26a0\ufe0f GARBAGE TIME NOT EXCLUDED -- stints have no start position; these minutes "
                   "may include blowout stretches")
                + (f"; {int(_r['_same_as'])} other trio(s) have identical numbers -- they only ever played "
                   "together as one unit" if _r["_same_as"] > 0 else "")
                for _, _r in _best3.iterrows()]
            # If the top trio is one of several with identical numbers, no single trio can be singled out --
            # the finding is the unit they all come from, so the headline names every player in it.
            _top = _best3.iloc[0]
            _twins = _ranked[_ranked["_sig"] == _top["_sig"]]["lineup"]
            _unit = sorted({p.strip() for l in _twins for p in str(l).split(",")})
            _headline = (f"Feature the {_ktv_last_names(', '.join(_unit))} unit" if len(_twins) > 1
                         else f"Feature the {_ktv_last_names(_top['lineup'])} combo")
            _ktv_add("", _headline,
                     "\n".join(_lines + [f"On/off: {_top['on_off']:+.1f} per 40 minutes (better with them on the floor)"]),
                     f"Our best trio this season -- {_top['shrunk_per40']:+.1f} per 40 minutes together; get them on "
                     f"the floor together."
                     + ("" if _garbage_excludable else
                        " (Caution: garbage time couldn't be left out of these minutes on this run -- see the app.)"),
                     "Lineup Scouting", "Personnel",
                     impact=_top['shrunk_per40'] / 12, confidence=_top['clean_min'] / 120 * (1 if _garbage_excludable else 0.5))
        else:
            _ktv_problems.append(
                f"3-man combos: no trio qualified to feature ({_CR['min_minutes']}+ competitive min, "
                f"{_CR['min_games']}+ games, positive shrunk margin and on/off) -- {_n_short} trio(s) are "
                "still short of the minutes or games. No key rather than a weak one.")
except Exception as _e:
    _ktv_problems.append(f"Lineup Scouting (3-man combos): {_e}")

# Export the 3-man tables (requested: show the top three in the brief, like the five-man units). These are
# the SAME frames the "Attack their ... combo" / "Feature the ... combo" keys above are built from, written
# out rather than recomputed elsewhere, so a combo named in a key and the combo table can never disagree.
# GP is only exact for our side: ours is counted from stints; theirs is assembled from five-man season rows
# with no game dates, where max() over the units is a floor, not a count -- so it is exported as a floor.
_three_man_frames = []
if "_uww_3man" in globals() and _uww_3man is not None and not _uww_3man.empty:
    _three_man_frames.append(_uww_3man.assign(side="UWW", scouted_opponent=_ktv_short, gp_exact=True))
if "_opp_3man" in globals() and _opp_3man is not None and not _opp_3man.empty:
    _three_man_frames.append(_opp_3man.assign(side="Opponent", scouted_opponent=_ktv_short, gp_exact=False))
three_man_combos = (pd.concat(_three_man_frames, ignore_index=True) if _three_man_frames
                    else pd.DataFrame(columns=["lineup", "MIN", "PTS", "+/-", "GP", "side",
                                               "scouted_opponent", "gp_exact"]))
three_man_combos.to_csv(os.path.join(APP_DATA_DIR, "uww_three_man_combos.csv"), index=False)
print(f"  3-man combos: {int((three_man_combos['side'] == 'UWW').sum())} ours, "
      f"{int((three_man_combos['side'] == 'Opponent').sum())} {_ktv_short} -> uww_three_man_combos.csv")

# ========================================================================================================
# REBOUNDING (Data-Driven) -- every miss in their play-by-play paired with the rebound that follows it.
# Defined HERE (and reused by the game-plan cell's REBOUND TENDENCIES table) so the key, the brief's Bottom
# Line and roster reads, and the app's full table all come from one pairing -- not two copies that can drift.
#
# The brief no longer has a rebounding section (requested). Rebounding only reaches it when it's lopsided
# enough to change the plan; these are the thresholds, and the brief's Bottom Line note prints them.
# ========================================================================================================
REBOUND_RULES = {
    "min_paired": 20,     # paired misses before any team-level rate is trusted
    "crash_rate": 35,     # THEIR offensive-rebound % on their own misses at/above this -> box-out key
    "soft_rate": 65,      # THEIR defensive-rebound % on opponent misses at/below this -> crash-the-glass key
    "player_share": 35,   # one player with this % of their offensive rebounds after misses -> roster read
    "player_min": 5,      # ...and at least this many of them
}
_REB_SKIP_STOP = {"made_shot", "missed_shot", "turnover", "free_throw_made", "free_throw_missed", "jump_ball",
                  "period_end", "period_start"}
_REB_OFF_EV = {"rebound_offensive", "team_deadball_rebound_offensive"}
_REB_DEF_EV = {"rebound_defensive", "team_deadball_rebound_defensive"}


def _reb_shot_kind(ev):
    """What kind of miss -- the crash rate after a missed layup is a different number from after a three."""
    if ev["event_type"] == "free_throw_missed":
        return "Missed free throw"
    if str(ev.get("shot_type")) == "3":
        return "Missed three"
    _t = str(ev.get("raw_text") or "").lower()
    if any(w in _t for w in ("layup", "lay-up", "dunk", "tip", "hook", "putback", "put back", "jam")):
        return "Missed layup / dunk"
    return "Missed two-point jumper"


def rebound_pairs(pbp, team):
    """One row per miss: who missed, what kind, and the rebound that followed (or None). Walks forward from
    each miss inside the same game and period and stops at the first rebound; a make, another miss, a
    turnover or a period change first leaves the miss unpaired rather than crediting the wrong board.
    is_them marks misses by `team` -- offensive=True on those is THEIR offensive rebound."""
    cols = ["shooter_team", "kind", "reb_team", "reb_player", "offensive", "is_them"]
    if pbp is None or pbp.empty or not {"event_type", "team", "game_date", "event_order"}.issubset(pbp.columns):
        return pd.DataFrame(columns=cols)
    rp = pbp.copy()
    rp["event_type"] = rp["event_type"].astype(str)
    rp["_ord"] = pd.to_numeric(rp["event_order"], errors="coerce")
    gkey = ["game_date", "opponent"] if "opponent" in rp.columns else ["game_date"]
    out = []
    _reversed_games = 0
    for _, gm in rp.sort_values(gkey + ["_ord"]).groupby(gkey, dropna=False):
        # DIRECTION CHECK. The walk below goes forward from a miss to the rebound after it, which assumes
        # event_order runs OLDEST-first. Nothing guarantees that: event_order is just the row number in the
        # exported file, and a newest-first export puts every rebound BEFORE its miss -- the walk then finds
        # nothing, every miss comes back unpaired, and the table silently stays sample. The game clock settles
        # it: within a period, time remaining must go DOWN as play goes on. If it mostly goes up with
        # event_order, this game's file is newest-first and is walked in reverse.
        if "time_remaining_seconds" in gm.columns and "period" in gm.columns:
            _t = gm[["period", "_ord"]].assign(
                _sec=pd.to_numeric(gm["time_remaining_seconds"], errors="coerce")).dropna()
            _up = _down = 0
            for _, _pg in _t.groupby("period"):
                _d = _pg.sort_values("_ord")["_sec"].diff().dropna()
                _up += int((_d > 0).sum())
                _down += int((_d < 0).sum())
            if _up > _down:
                gm = gm.iloc[::-1]
                _reversed_games += 1
        evs = gm.to_dict("records")
        for i, e in enumerate(evs):
            if e["event_type"] not in ("missed_shot", "free_throw_missed"):
                continue
            reb = None
            for nx in evs[i + 1:i + 6]:
                if nx.get("period") != e.get("period"):
                    break
                if nx["event_type"] in _REB_OFF_EV or nx["event_type"] in _REB_DEF_EV:
                    reb = nx
                    break
                if nx["event_type"] in _REB_SKIP_STOP:
                    break
            out.append({"shooter_team": str(e.get("team")), "kind": _reb_shot_kind(e),
                        "reb_team": None if reb is None else str(reb.get("team")),
                        "reb_player": None if reb is None else reb.get("player"),
                        "offensive": None if reb is None else reb["event_type"] in _REB_OFF_EV})
    df = pd.DataFrame(out, columns=cols[:-1])
    if df.empty:
        return pd.DataFrame(columns=cols)
    # CONFIRMED BUG (fixed here): a "team rebound" -- no player recorded, the raw play-by-play just credits
    # the rebound to the team itself -- doesn't always come through as event_type team_deadball_rebound_*
    # with player=None; some exports put the TEAM'S OWN NAME in the player field of an ordinary rebound
    # event instead ("Wis.-Stevens Point" as reb_player). Every consumer downstream only excluded the
    # literal word "TEAM", so a team-attributed board was counted as a "player" and could even come out on
    # top of a crasher list. Any reb_player that matches its own reb_team (case/whitespace-insensitive) is
    # a team rebound by definition, regardless of how the source text spelled it, so it's nulled out HERE,
    # once, rather than re-filtered (and potentially missed) at every place that reads reb_player.
    _rp_norm = df["reb_player"].astype(str).str.strip().str.lower()
    _rt_norm = df["reb_team"].astype(str).str.strip().str.lower()
    df.loc[df["reb_player"].notna() & (_rp_norm == _rt_norm), "reb_player"] = None
    df["is_them"] = df["shooter_team"] == str(team)
    if not df["is_them"].any() and str(team).strip():   # names can carry a mascot in the pbp
        df["is_them"] = df["shooter_team"].str.lower().str.contains(str(team).lower().split()[0], na=False)
    df.attrs["reversed_games"] = _reversed_games
    df.attrs["games"] = int(rp.groupby(gkey, dropna=False).ngroups)
    return df


# --- G. Feature our best look ----------------------------------------------------------------------------
# Redesigned (requested): this used to rank our own shot MECHANICS in isolation (catch-and-shoot vs drive vs
# putback etc., from the Synergy-style chain tags) and crown whichever had the best points-per-attempt, with
# no check on whether the opponent is actually bad at stopping it, and no floor on real opportunity -- a hot
# few putbacks could top the list with no real rebounding edge behind it (a "Putback" mechanic and offensive
# rebounding volume are two different things; PPA on the rare putbacks we get says nothing about whether we
# generate enough of them to matter -- see REBOUND_RULES / the rebounding key for that check). It now looks
# at named SERIES (the same vocabulary as HOW WE RUN OFFENSE / WHAT TO PLAY THEM IN) and requires BOTH
# halves of the matchup: a series we're genuinely good at, that this opponent has ALSO been bad at defending
# against whoever else has run it against them this season -- not just something we happen to run well.
_G_MIN_OUR_USES = 6       # our own tagged possessions in a series before its PPP is trusted
_G_MIN_THEIR_ALLOWED = 5  # possessions run against them (by anyone) before their allowed-PPP is trusted

try:
    _pcs = _ktv_load("uww_play_call_summary")
    _our_series = pd.DataFrame()
    _our_avg_ppp = None
    if not _pcs.empty and {"side", "level", "name", "uses", "ppp"}.issubset(_pcs.columns):
        _os = _pcs[(_pcs["side"] == "UWW") & (_pcs["level"] == "Series")]
        if "team_ppp" in _os.columns and _os["team_ppp"].notna().any():
            _our_avg_ppp = float(pd.to_numeric(_os["team_ppp"], errors="coerce").dropna().iloc[0])
        _our_series = _os[(pd.to_numeric(_os["uses"], errors="coerce") >= _G_MIN_OUR_USES)
                          & pd.to_numeric(_os["ppp"], errors="coerce").notna()]

    _clips = _ktv_load("uww_play_calls")
    _their_def_series = pd.DataFrame()
    if not _clips.empty and {"side", "possession_side", "play_series", "points",
                             "decode_quality"}.issubset(_clips.columns):
        # Possessions where THEY were defending (someone else had the ball) -- the offense's series is what
        # was run AGAINST their defense, so its PPP here is how well THEY defend that series.
        _d = _clips[(_clips["side"] == "Opponent") & (_clips["possession_side"] == "Defense")
                    & (_clips["decode_quality"] != "Needs review") & _clips["play_series"].notna()].copy()
        if not _d.empty:
            _d["_pts"] = pd.to_numeric(_d["points"], errors="coerce")
            _agg = _d.groupby("play_series").agg(
                uses=("play_series", "size"), pts=("_pts", "sum"),
                known=("_pts", lambda s: s.notna().sum())).reset_index()
            _agg["ppp"] = _agg["pts"] / _agg["known"].replace(0, pd.NA)
            _their_def_series = _agg[(_agg["uses"] >= _G_MIN_THEIR_ALLOWED) & _agg["ppp"].notna()]

    if _our_series.empty or _their_def_series.empty:
        _ktv_problems.append(
            "Data-Driven (feature our best look): not enough tagged data yet on both sides -- our own "
            f"series usage ({_G_MIN_OUR_USES}+ needed) and what's been run against this opponent by anyone "
            f"({_G_MIN_THEIR_ALLOWED}+ needed) -- to cross-reference a matchup-specific best look.")
    else:
        _merged = _our_series.merge(_their_def_series, left_on="name", right_on="play_series",
                                    suffixes=("_us", "_them"))
        # Both sides have to clear a real bar, not just whichever series happens to overlap: our own PPP
        # has to be at or above our season average (one of our BETTER series, not just an eligible one), and
        # theirs has to be a real number (their allowed-PPP, already required to be non-null above).
        if _our_avg_ppp is not None:
            _merged = _merged[_merged["ppp_us"] >= _our_avg_ppp]
        if _merged.empty:
            _ktv_problems.append(
                "Data-Driven (feature our best look): no series is both above our own season average AND "
                "has enough tagged possessions run against this opponent to compare -- nothing to feature "
                "yet that's specific to this matchup.")
        else:
            # Ranked by how much THEY give up on it -- among series we're already good at, the one that
            # hurts their defense the most is the one to call.
            _best = _merged.sort_values("ppp_them", ascending=False).iloc[0]
            _lineup_txt = None
            _best_clips = _clips[(_clips["side"] == "UWW") & (_clips.get("possession_side") != "Defense")
                                 & (_clips["play_series"].astype(str) == str(_best["name"]))] \
                if not _clips.empty else pd.DataFrame()
            if not _best_clips.empty and "on_court_lineup" in _best_clips.columns:
                _lu_rows = _best_clips[_best_clips["on_court_lineup"].notna()]
                if not _lu_rows.empty:
                    _lu_vc = _lu_rows["on_court_lineup"].astype(str).value_counts()
                    if len(_lu_vc):
                        _lineup_txt = f"Runs it most: {_ktv_last_names(_lu_vc.index[0])} ({int(_lu_vc.iloc[0])}x)"
            _play_txt = _ktv_top_play_text(_best_clips) if not _best_clips.empty else None
            _play_name = _ktv_top_play_name(_best_clips) if not _best_clips.empty else None
            # CONFIRMED CHANGE (coach: keys must read as a plain sentence). The brief prints HEADLINE -- REASONING;
            # the reasoning is now one coaching sentence, and the lineup / play-call detail sits in the evidence.
            _how_in = (f", usually out of {_play_name}" if _play_name and _play_name.lower() != str(_best["name"]).lower() else "")
            _ktv_add("\U0001f3c0", f"Feature our best look: {_best['name']}",
                     "\n".join(p for p in (
                         f"Us: {_best['ppp_us']:.2f} PPP on {int(_best['uses_us'])} tagged possessions this season "
                         f"(team average {_our_avg_ppp:.2f})",
                         f"Them: opponents scored {_best['ppp_them']:.2f} PPP running this against {_ktv_short} on "
                         f"{int(_best['uses_them'])} tagged possessions", _lineup_txt, _play_txt) if p),
                     f"We score {_best['ppp_us']:.2f} a possession on it and {_ktv_short} gives up "
                     f"{_best['ppp_them']:.2f} defending it -- go to it early{_how_in}.",
                     "Data-Driven", "Offense",
                     impact=(0.3 + (_best['ppp_us'] - _our_avg_ppp) / 0.5) if _our_avg_ppp else 0.5, confidence=min(_best['uses_us'], _best['uses_them']) / 20)
except Exception as _e:
    _ktv_problems.append(f"Data-Driven (feature our best look): {_e}")

# --- H. Attack their weakest look ------------------------------------------------------------------------
# Uses the shots taken BY whoever the opponent played in each game before facing UWW: the look those teams
# were most efficient at is this opponent's worst-defended one. Then cross-referenced against our own
# season-wide shot data for the same look, to say which of our lineups and play calls already generates it.
try:
    _third = _ktv_tag_shots(_ktv_load("uww_opponent_prior_games_pbp"), exclude_team=_ktv_short)
    if _third.empty:
        _ktv_add("\U0001f3af", "Attack Opponent Worst Offensive Shot Selection & Quality", None,
                 f"No video-tagged data yet for teams {_ktv_short} played before facing UWW this season -- "
                 f"needs a local/live-scraped _pbp and _video file for each of those games.",
                 "Data-Driven", "Offense",
                 brief_eligible=False)
    else:
        _grouped = _ktv_shot_looks(_third, min_attempts=5)  # a handful of prior games, not a season
        if _grouped.empty:
            _ktv_add("\U0001f3af", "Attack Opponent Worst Offensive Shot Selection & Quality", None,
                     f"Some video-tagged data exists for teams {_ktv_short} played before UWW, but not "
                     f"enough attempts yet of any one shot type (need 5+) to call one a clear weakness.",
                     "Data-Driven", "Offense",
                     brief_eligible=False)
        else:
            _baseline = _grouped.attrs.get("baseline_ppa")
            _best = _grouped.iloc[0]
            # Putback is generated by OFFENSIVE REBOUNDING volume, not shot-making (requested) -- a hot game
            # on the handful of putbacks some team got doesn't mean there's a real opportunity here unless
            # this opponent is ACTUALLY bad on the defensive glass. Same computation as the standalone
            # rebounding key (REBOUND_RULES), so the two can't disagree about whether the edge is real. If
            # Putback tops the list without that edge, skip it for the next-best mechanic instead.
            if _best["_mechanic"] == "Putback off the offensive glass" and len(_grouped) > 1:
                _real_edge = False
                _rp = rebound_pairs(_ktv_load("uww_opponent_prior_games_pbp"), _ktv_short)
                if not _rp.empty:
                    _rpaired = _rp[_rp["offensive"].notna()].copy()
                    _rpaired["offensive"] = _rpaired["offensive"].astype(bool)
                    _rdef = _rpaired[~_rpaired["is_them"]]  # misses by whoever THEY were defending
                    if len(_rdef) >= REBOUND_RULES["min_paired"]:
                        _dreb_pct = 100 * (~_rdef["offensive"]).sum() / len(_rdef)
                        _real_edge = _dreb_pct <= REBOUND_RULES["soft_rate"]
                if not _real_edge:
                    _grouped = _grouped[_grouped["_mechanic"] != "Putback off the offensive glass"]
                    if not _grouped.empty:
                        _best = _grouped.iloc[0]
            _bm, _bc = _best["_mechanic"], _best["_contest"]
            _our_shots = _ktv_tag_shots(_ktv_load("uww_pbp_events"), team="UW-Whitewater")
            _lineup_txt = _volume_txt = _play_txt = None
            if not _our_shots.empty:
                _match = _our_shots[(_our_shots["_mechanic"] == _bm) & (_our_shots["_contest"] == _bc)]
                if "uww_lineup" in _match.columns:
                    _lu_rows = _match[_match["uww_lineup"].notna()]
                    if not _lu_rows.empty:
                        _lu = _lu_rows.groupby("uww_lineup").agg(
                            Attempts=("_make", "count"), Makes=("_make", "sum")).reset_index()
                        _lu["FG%"] = 100 * _lu["Makes"] / _lu["Attempts"]
                        # Two questions, two lists: ranking by FG% alone rewards a unit that went 3/3, so
                        # the accuracy list keeps a 3+ attempt floor and the volume list answers "who
                        # actually generates this for us" with no floor. A coach needs both.
                        _qual = _lu[_lu["Attempts"] >= _KTV_LOOK_LINEUP_MIN_ATTEMPTS]
                        if not _qual.empty:
                            _top_fg = _qual.sort_values(["FG%", "Attempts"], ascending=False).head(3)
                            _lineup_txt = "\n".join([f"Best on this shot ({_KTV_LOOK_LINEUP_MIN_ATTEMPTS}+ attempts):"] + [
                                f"\u2022 {_ktv_last_names(_r['uww_lineup'])} {int(_r['Makes'])}/"
                                f"{int(_r['Attempts'])} ({_r['FG%']:.0f}%)" for _, _r in _top_fg.iterrows()])
                        _top_vol = _lu.sort_values(["Attempts", "FG%"], ascending=False).head(3)
                        if not _top_vol.empty:
                            _volume_txt = "\n".join(["Runs it most:"] + [
                                f"\u2022 {_ktv_last_names(_r['uww_lineup'])} {int(_r['Attempts'])}x "
                                f"({_r['FG%']:.0f}%)" for _, _r in _top_vol.iterrows()])
                _play_txt = _ktv_top_play_text(_match, suffix=" for us")

            _parts = [p for p in (_lineup_txt, _volume_txt, _play_txt) if p]
            _play_name = _ktv_top_play_name(_match) if not _our_shots.empty and not _match.empty else None
            _ktv_add("\U0001f3af",
                     f"Attack their weakest look: {_ktv_describe_look(_bm, _bc)}",
                     # evidence (the app): the full shot line plus which of our lineups get / make this shot
                     "\n".join([f"Opponents shot {_ktv_shot_stat_line(_best, _baseline)} on this against {_ktv_short}"]
                               + _parts),
                     # the brief: one plain sentence
                     f"Teams have shot {_best['FG%']:.0f}% on it against {_ktv_short} -- hunt it"
                     + (f"; we usually get it out of {_play_name}." if _play_name else "."),
                     # Offense: every number describes their defense, but the instruction is what WE run.
                     "Data-Driven", "Offense",
                     impact=0.6, confidence=float(_best.get('Attempts', 0) or 0) / 30)
except Exception as _e:
    _ktv_problems.append(f"Data-Driven (attack their weakest look): {_e}")

# --- I. What their offense goes to most ------------------------------------------------------------------
# The complement to H: by VOLUME rather than efficiency, for defensive prep rather than offensive attack.
try:
    _own = _ktv_tag_shots(_ktv_load("uww_opponent_prior_games_pbp"), team=_ktv_short)
    if not _own.empty:
        _g = _own[_own["_mechanic"].notna() & _own["_contest"].notna()].groupby(
            ["_mechanic", "_contest"]).agg(Attempts=("_make", "count"), Makes=("_make", "sum")).reset_index()
        _g = _g[_g["Attempts"] >= 5]
        if not _g.empty:
            _g["FG%"] = 100 * _g["Makes"] / _g["Attempts"]
            _top = _g.nlargest(1, "Attempts").iloc[0]
            _ktv_add("\U0001f6e1\ufe0f",
                     f"What {_ktv_short} goes to most: {_ktv_describe_look(_top['_mechanic'], _top['_contest'])}",
                     f"{int(_top['Attempts'])} attempts, {_top['FG%']:.0f}% -- across their games before UWW",
                     "What their offense goes to most often, regardless of how well it's worked -- worth a "
                     "specific defensive scheme item to take away.",
                     "Data-Driven", "Defense",
                     impact=0.5, confidence=_top['Attempts'] / 30)
except Exception as _e:
    _ktv_problems.append(f"Data-Driven (what they go to most): {_e}")

# --- J/K. Play calls (uww_plays.csv / opponent_plays.csv, decoded by the "Play calls" cell) -------------
# J names the opponent's go-to set and what it produces; K names our most productive set with real volume.
# Both read uww_play_call_summary.csv, which excludes Rewatch/TBD clips from every ranking.
_KTV_PLAY_MIN_USES = 4
try:
    _pcs = _ktv_load("uww_play_call_summary")
    if not _pcs.empty and {"side", "level", "name", "uses"}.issubset(_pcs.columns) and _ktv_short:
        _pcs = _pcs[_pcs["scouted_opponent"].astype(str) == str(_ktv_short)]
        # Rank "best set" on PPP shrunk toward the side's own average by _KTV_PLAY_SHRINK possessions, so a
        # 4-for-4 week can't outrank a set that has worked across twenty trips.
        _KTV_PLAY_SHRINK = 8
        _pcs = _pcs.assign(_ppp_adj=(pd.to_numeric(_pcs["points"], errors="coerce")
                                     + pd.to_numeric(_pcs["team_ppp"], errors="coerce") * _KTV_PLAY_SHRINK)
                           / (pd.to_numeric(_pcs["poss_with_points"], errors="coerce") + _KTV_PLAY_SHRINK))
        _calls = _pcs[(_pcs["level"] == "Play call")
                      & ~_pcs["name"].astype(str).str.contains("unspecified", na=False)
                      & (_pcs["uses"] >= _KTV_PLAY_MIN_USES)]

        _theirs = _calls[_calls["side"] == "Opponent"].sort_values(["uses", "ppp"], ascending=[False, False])
        # "Go-to set" means half court: an inbounds set can top the count just because every game has a dozen
        # baseline out-of-bounds trips. The busiest inbounds set is named in the reasoning instead.
        _theirs_half = _theirs[_theirs["situation"].astype(str) == "Half court"]
        _theirs_oob = _theirs[_theirs["situation"].astype(str).str.match(r"^(BLOB|SLOB)")]
        # CONFIRMED CHANGE (coach: "too much information and not easy to read as a sentence"). The brief prints a key as
        # HEADLINE -- REASONING, so the reasoning is now ONE plain coaching sentence (what the set is, who finishes it,
        # what to take away). Every supporting number -- uses, PPP, FG, turnovers, the next set, the busiest
        # inbounds set, example tags -- moves to the EVIDENCE, which the app shows when the key is opened.
        def _ktv_set_finisher(r):
            return (r["top_player"] if isinstance(r.get("top_player"), str) and int(r.get("top_player_uses") or 0) >= 2
                    else None)

        def _ktv_set_action(r):
            a_ = r.get("top_action")
            return str(a_).strip().lower() if isinstance(a_, str) and a_.strip() else None

        if not _theirs_half.empty:
            _t = _theirs_half.iloc[0]
            _who, _act = _ktv_set_finisher(_t), _ktv_set_action(_t)
            _lead = f"Their most-called half-court set ({int(_t['uses'])} times in {int(_t['games'])} games)."
            if _who and _act:
                _do = f"{_who} finishes it most, usually off the {_act} -- take away the {_act} and make someone else beat us."
            elif _who:
                _do = f"{_who} finishes it most -- make someone else take that shot."
            elif _act:
                _do = f"It's built on the {_act} -- take that away first."
            else:
                _do = "Know the alignment and call it out before the action starts."
            _reason = f"{_lead} {_do}"
            _second = _theirs_half.iloc[1] if len(_theirs_half) > 1 else None
            _ev_lines = [
                f"{int(_t['uses'])} uses in {int(_t['games'])} games"
                + (f" · {_t['ppp']:.2f} PPP (their overall {_t['team_ppp']:.2f})" if pd.notna(_t.get("ppp")) and pd.notna(_t.get("team_ppp")) else "")
                + (f" · {int(_t['fgm'])}/{int(_t['fga'])} FG" if int(_t.get("fga") or 0) else "")
                + (f" · {int(_t['turnovers'])} TO" if int(_t.get("turnovers") or 0) else ""),
                f"Finished most by {_t['top_player']} ({int(_t['top_player_uses'])}x)" if _who else "",
                f"Built on: {_t['top_action']}" if _act else "",
                f"Usually run to the {_t['top_location'].lower()}" if isinstance(_t.get("top_location"), str) else "",
                f"Next most-called: {_second['name']} ({int(_second['uses'])} uses)" if _second is not None else "",
                (f"Busiest inbounds set: {_theirs_oob.iloc[0]['name']} ({int(_theirs_oob.iloc[0]['uses'])} uses"
                 + (f", {_theirs_oob.iloc[0]['ppp']:.2f} PPP)" if pd.notna(_theirs_oob.iloc[0].get('ppp')) else ")")
                 if not _theirs_oob.empty else ""),
                f"Tagged as: {_t['example_titles']}" if isinstance(_t.get("example_titles"), str) else ""]
            _ev = "\n".join(x for x in _ev_lines if x)
            _ktv_add("\U0001f4cb", f"Take away their go-to set: {_t['name']}", _ev, _reason,
                     "Data-Driven", "Defense",
                     impact=_t['uses'] / max(_t['games'], 1) / 4, confidence=_t['uses'] / 20)
            # Their most productive set with volume, when it isn't the same one.
            _eff = _theirs[_theirs["_ppp_adj"].notna()].sort_values("_ppp_adj", ascending=False)
            if not _eff.empty and _eff.iloc[0]["name"] != _t["name"] and pd.notna(_eff.iloc[0].get("team_ppp")) \
                    and _eff.iloc[0]["ppp"] >= _eff.iloc[0]["team_ppp"] + 0.15:
                _e = _eff.iloc[0]
                _ew = _ktv_set_finisher(_e)
                _ktv_add("\U0001f4cb", f"Know their best set: {_e['name']}",
                         f"{_e['ppp']:.2f} PPP on {int(_e['uses'])} uses vs {_e['team_ppp']:.2f} overall"
                         + (f"\nFinished most by {_e['top_player']} ({int(_e['top_player_uses'])}x)" if _ew else ""),
                         "Their most productive set -- recognize the alignment and call it out before the action starts"
                         + (f"; {_ew} is usually the one finishing it." if _ew else "."),
                         "Data-Driven", "Defense",
                         impact=(_e['ppp'] - _e['team_ppp']) / 0.5, confidence=_e['uses'] / 20)

        _ours = _calls[(_calls["side"] == "UWW") & _calls["_ppp_adj"].notna()].sort_values(["_ppp_adj", "uses"], ascending=False)
        if not _ours.empty and pd.notna(_ours.iloc[0].get("team_ppp")) and _ours.iloc[0]["_ppp_adj"] > _ours.iloc[0]["team_ppp"]:
            _o = _ours.iloc[0]
            _ow = _ktv_set_finisher(_o)
            _ktv_add("\U0001f4cb", f"Call our best set: {_o['name']}",
                     f"{_o['ppp']:.2f} PPP on {int(_o['uses'])} uses vs our {_o['team_ppp']:.2f} overall"
                     + (f" · {int(_o['fgm'])}/{int(_o['fga'])} FG" if int(_o.get("fga") or 0) else "")
                     + (f"\nFinished most by {_o['top_player']} ({int(_o['top_player_uses'])}x)" if _ow else ""),
                     "Our most productive set this season -- go to it when we need a good look"
                     + (f", with {_ow} finishing." if _ow else "."),
                     "Data-Driven", "Offense",
                     impact=(_o['_ppp_adj'] - _o['team_ppp']) / 0.5, confidence=_o['uses'] / 20)
except Exception as _e:
    _ktv_problems.append(f"Data-Driven (play calls): {_e}")




_reb_summary_rows = []
try:
    _rpairs = rebound_pairs(_ktv_load("uww_opponent_prior_games_pbp"), _ktv_short)
    if not _rpairs.empty:
        _R = REBOUND_RULES
        _paired = _rpairs[_rpairs["offensive"].notna()].copy()
        _paired["offensive"] = _paired["offensive"].astype(bool)
        _their = _paired[_paired["is_them"]]
        _opp = _paired[~_paired["is_them"]]
        # OUR OWN baseline (requested: "is 38% a lot?" needed something to compare it to). From every
        # opponent WE'VE faced this season, not just this one -- the rate teams generally get their own
        # miss back against OUR defense, and the rate WE generally get ours back on offense. Same
        # rebound_pairs() function, run against our own play-by-play instead of the scouted opponent's, so
        # it can never disagree with how "their" rate above was computed.
        _our_oreb_base = _our_dreb_allowed_base = None
        try:
            _our_pairs = rebound_pairs(_ktv_load("uww_pbp_events"), "UW-Whitewater")
            if not _our_pairs.empty:
                _our_paired = _our_pairs[_our_pairs["offensive"].notna()].copy()
                _our_paired["offensive"] = _our_paired["offensive"].astype(bool)
                _our_off = _our_paired[_our_paired["is_them"]]        # our own misses
                _our_def = _our_paired[~_our_paired["is_them"]]       # opponents' misses against us
                if len(_our_off) >= _R["min_paired"]:
                    _our_oreb_base = 100 * _our_off["offensive"].mean()
                if len(_our_def) >= _R["min_paired"]:
                    _our_dreb_allowed_base = 100 * _our_def["offensive"].mean()
        except Exception:
            pass  # baseline is a nice-to-have; the rest of this key still stands without it
        # Extra safety net alongside the reb_player==reb_team null-out in rebound_pairs() above: that catches
        # a team rebound when the two fields agree, but some exports set reb_team to a generic "TEAM" while
        # still putting the opponent's own display name in reb_player, so the two never match each other.
        # Excluding the opponent's own short name here directly closes that gap, so a team board can never
        # outrank an actual player in the crasher list or the Rebounding key.
        _team_name_variants = {"TEAM", "", "NAN", str(_ktv_short).strip().upper()}
        # CONFIRMED BUG (fixed): the play-by-play credits team rebounds to the school as "Wis.-Stevens Point" while
        # the short name is "UW-Stevens Point", so the TEAM topped the crasher list and the key said "put a body on
        # Wis.-Stevens Point". Any spelling of the school (UW- / Wis. / Wisconsin prefixes ignored) is not a player.
        _core = lambda x: re.sub(r"^(uw|wis|wisc|wisconsin)", "", re.sub(r"[^a-z]", "", str(x).lower()))
        _team_core = _core(_ktv_short)
        _crashers = (_their[_their["offensive"]]["reb_player"].dropna().astype(str)
                     .loc[lambda s: ~s.str.strip().str.upper().isin(_team_name_variants)]
                     .loc[lambda s: ~s.map(lambda n: bool(_team_core) and _team_core in _core(n))]
                     .value_counts())
        _oreb_n = int(_their["offensive"].sum())
        if len(_their):
            _oreb_pct = 100 * _oreb_n / len(_their)
            _reb_summary_rows.append({"metric": "their_oreb_pct", "value": round(_oreb_pct, 1),
                                      "paired": len(_their), "player": None, "count": _oreb_n})
            if _our_dreb_allowed_base is not None:
                _reb_summary_rows.append({"metric": "our_dreb_allowed_base", "value": round(_our_dreb_allowed_base, 1),
                                          "paired": len(_our_def), "player": None, "count": None})
            for _pl, _c in _crashers.head(3).items():
                _reb_summary_rows.append({"metric": "their_oreb_player", "value": round(100 * _c / _oreb_n, 1)
                                          if _oreb_n else None, "paired": len(_their), "player": _pl,
                                          "count": int(_c)})
            if len(_their) >= _R["min_paired"] and _oreb_pct >= _R["crash_rate"]:
                _who = ", ".join(f"{p} ({int(c)})" for p, c in _crashers.head(2).items())
                _vs_us = (f" -- we usually allow {_our_dreb_allowed_base:.0f}%, so this is "
                          f"{'well above' if _oreb_pct - _our_dreb_allowed_base >= 8 else 'above'} our norm"
                          if _our_dreb_allowed_base is not None else "")
                _ktv_add("", "Finish every defensive possession with a box-out",
                         f"They grab {_oreb_pct:.0f}% of their own misses ({_oreb_n} of {len(_their)} paired "
                         f"misses in their play-by-play){_vs_us}" + (f"; most by {_who}." if _who else "."),
                         f"They get {_oreb_pct:.0f}% of their own misses back -- a stop isn't a stop until we "
                         "secure the rebound"
                         + (f"; find {_crashers.index[0]} on every shot." if len(_crashers) else "."),
                         "Data-Driven", "Defense",
                         impact=0.4 + (_oreb_pct - _R['crash_rate']) / 15, confidence=len(_their) / 150)
        if len(_opp):
            _dreb_pct = 100 * (~_opp["offensive"]).sum() / len(_opp)
            _reb_summary_rows.append({"metric": "their_dreb_pct", "value": round(_dreb_pct, 1),
                                      "paired": len(_opp), "player": None, "count": int((~_opp["offensive"]).sum())})
            if _our_oreb_base is not None:
                _reb_summary_rows.append({"metric": "our_oreb_base", "value": round(_our_oreb_base, 1),
                                          "paired": len(_our_off), "player": None, "count": None})
            if len(_opp) >= _R["min_paired"] and _dreb_pct <= _R["soft_rate"]:
                _vs_us2 = (f" -- we usually get {_our_oreb_base:.0f}% ourselves, so this is a real opening"
                          if _our_oreb_base is not None and (100 - _dreb_pct) - _our_oreb_base >= 8 else "")
                _ktv_add("", "Send an extra body to the offensive glass",
                         f"Opponents rebound {100 - _dreb_pct:.0f}% of their own misses against them "
                         f"({int(_opp['offensive'].sum())} of {len(_opp)} paired misses){_vs_us2}.",
                         f"They secure only {_dreb_pct:.0f}% of defensive boards -- our misses are live balls. "
                         "Crash with a fourth man when the shot goes up from the perimeter.",
                         "Data-Driven", "Offense",
                         impact=0.4 + (_R['soft_rate'] - _dreb_pct) / 15, confidence=len(_opp) / 150)
except Exception as _e:
    _ktv_problems.append(f"Data-Driven (rebounding): {_e}")

rebound_summary = pd.DataFrame(_reb_summary_rows, columns=["metric", "value", "paired", "player", "count"])
rebound_summary.insert(0, "opponent", _ktv_short)
rebound_summary.to_csv(os.path.join(APP_DATA_DIR, "uww_rebound_summary.csv"), index=False)

# ========================================================================================================
# KEY PRIORITY MODEL -- which keys make the printed brief (requested: "only the most important KTV").
# Every key still goes to uww_ktv_keys.csv and the app; this only decides what the brief prints.
#
#   priority_score (0-100) = source points      (0-30)  who says so: staff > computed > context
#                          + 40 x impact        (0-40)  how big the edge is, from the generator's numbers
#                          + 15 x confidence    (0-15)  how much data backs it
#                          + action points      (0-15)  an instruction beats a description
#
# The brief shows keys scoring min_score or more, best first, up to max_keys; if fewer than min_keys
# clear the bar it fills up to min_keys with the next best, so the brief is never empty. Only one key
# per topic (e.g. one rebounding key), and placeholders ("no data yet") are never shown.
KTV_BRIEF_RULES = {
    "min_score": 55,
    "max_keys": 6,
    "min_keys": 3,
    "source_points": {"Keys to Victory": 30, "Coach Notes": 26, "Data-Driven": 20, "Lineup Scouting": 18,
                      "Game Plan": 16, "Team Strengths": 14},
    "default_impact": 0.5,
    "default_confidence": 0.5,
    "staff_sources": ("Keys to Victory", "Coach Notes"),   # written by the staff for THIS game
}

_KTV_ACTION_VERBS = ("feature", "attack", "take away", "call", "counter", "finish", "send", "box", "crash",
                     "limit", "stop", "deny", "force", "push", "slow", "run", "keep", "get", "make", "focus",
                     "monitor", "pressure", "control", "win", "contain", "protect", "defend", "switch", "trap",
                     "help", "close", "contest", "execute", "value", "take care", "rebound", "play")


def _ktv_num(v, default):
    try:
        v = float(v)
        return default if pd.isna(v) else max(0.0, min(1.0, v))
    except (TypeError, ValueError):
        return default


def ktv_priority(row):
    """0-100 importance score for one key (a dict or DataFrame row)."""
    R = KTV_BRIEF_RULES
    source = str(row.get("source") or "")
    headline = str(row.get("headline") or "").strip().lower()
    staff = source in R["staff_sources"]
    src_pts = R["source_points"].get(source, 12)
    impact = _ktv_num(row.get("impact"), R["default_impact"])
    confidence = _ktv_num(row.get("confidence"), 1.0 if staff else R["default_confidence"])
    if staff or headline.startswith(_KTV_ACTION_VERBS):
        action = 15
    else:
        action = 8
    return round(src_pts + 40 * impact + 15 * confidence + action, 1)


def ktv_topic(headline):
    """Keys on the same subject compete for one spot on the brief."""
    h = str(headline or "").lower()
    if any(w in h for w in ("rebound", "box-out", "box out", "glass", "crash")):
        return "rebounding"
    if "tempo" in h or " pace" in h:
        return "tempo"
    if "three" in h or "3-point" in h:
        return "perimeter"
    if h.startswith("feature the"):
        return "our-trio"
    if h.startswith("counter with"):
        return "our-five"
    if h.startswith("attack") and ("lineup" in h or "combo" in h):
        return "their-lineups"
    return None


def ktv_select_for_brief(keys):
    """The keys the printed brief shows, best first, with brief_rank 1..N."""
    R = KTV_BRIEF_RULES
    if keys is None or keys.empty:
        return keys
    k = keys.copy()
    k["priority_score"] = k.apply(ktv_priority, axis=1)
    if "brief_eligible" in k.columns:
        k = k[~k["brief_eligible"].astype(str).str.strip().str.lower().isin({"false", "0", "no"})]
    k = k.sort_values("priority_score", ascending=False, kind="stable")
    k["_topic"] = k["headline"].apply(ktv_topic)
    k = pd.concat([k[k["_topic"].isna()], k[k["_topic"].notna()].drop_duplicates("_topic")])
    k = k.sort_values("priority_score", ascending=False, kind="stable")
    shown = k[k["priority_score"] >= R["min_score"]].head(R["max_keys"])
    if len(shown) < R["min_keys"]:
        shown = k.head(R["min_keys"])
    shown = shown.drop(columns="_topic")
    shown["brief_rank"] = range(1, len(shown) + 1)
    return shown


ktv_keys = pd.DataFrame(_ktv_rows)
if ktv_keys.empty:
    ktv_keys = pd.DataFrame(columns=_KTV_COLS)
else:
    ktv_keys["game_date"] = _ktv_game_date
    # Grouped by category, generator order preserved inside each group, then numbered across the whole
    # sorted list -- so a coach can cite "key 7" and everyone is looking at the same key.
    ktv_keys["_cat_rank"] = ktv_keys["category"].apply(
        lambda c: _KTV_CATEGORY_ORDER.index(c) if c in _KTV_CATEGORY_ORDER else len(_KTV_CATEGORY_ORDER))
    ktv_keys = ktv_keys.sort_values("_cat_rank", kind="stable").drop(columns="_cat_rank")
    ktv_keys["key_number"] = range(1, len(ktv_keys) + 1)
    ktv_keys["priority_score"] = ktv_keys.apply(ktv_priority, axis=1)
    ktv_keys = ktv_keys[_KTV_COLS]

ktv_keys.to_csv(os.path.join(APP_DATA_DIR, "uww_ktv_keys.csv"), index=False)
print(f"Wrote uww_ktv_keys.csv -- {len(ktv_keys)} key(s) for {_ktv_short or 'no opponent'}"
      + (f": {ktv_keys['category'].value_counts().to_dict()}" if not ktv_keys.empty else ""))
if not ktv_keys.empty:
    _brief_pick = ktv_select_for_brief(ktv_keys)
    print(f"  Brief will show {len(_brief_pick)} of {len(ktv_keys)} (score >= {KTV_BRIEF_RULES['min_score']}, "
          f"max {KTV_BRIEF_RULES['max_keys']}); Bottom Line keys are added and re-ranked in the brief cell:")
    for _, _r in ktv_keys.sort_values("priority_score", ascending=False).iterrows():
        _on = "*" if _r["key_number"] in set(_brief_pick["key_number"]) else " "
        print(f"   {_on} {_r['priority_score']:5.1f}  #{int(_r['key_number'])} {_r['headline'][:80]}")
if _ktv_problems:
    # Printed, not swallowed: a key quietly missing from a coach's brief is the worse failure.
    print("  Generators that FAILED (their keys are missing from the table above):")
    for _p in _ktv_problems:
        print(f"    - {_p}")
if ktv_keys.empty and not _ktv_problems:
    print("  (No keys built. Expected with before_scout=\"yes\" for the written ones; the rest need the "
          "opponent's tagged prior games and this season's lineup stints.)")
