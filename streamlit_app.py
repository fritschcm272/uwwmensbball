"""UW-Whitewater men's basketball scouting/coaching analytics app.

Data is bundled directly with the app (CSV files under ./data, exported from the analysis notebook's Delta
tables) rather than queried live from a SQL warehouse -- no Unity Catalog / warehouse permissions are needed
at runtime. Six sections: Home (AI scouting assistant), Upcoming Game (including a "Game Plan
Recommendations" panel that synthesizes coach notes, lineup, and rate-stat data into specific pre-game
suggestions), Previous Games, Team, Players, Analytics (possession-adjusted advanced stats -- Four Factors,
efficiency/pace, shot quality, ball movement, clutch performance, schedule/rest context, and coach-tagged
play notes; see STAT_GLOSSARY for definitions of every derived metric).
"""

import hashlib
import html
import json
import math
import os
import re
from datetime import datetime

import pandas as pd
import streamlit as st
from openai import OpenAI


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _load_name_aliases() -> dict:
    """Known player-name spelling mismatches BETWEEN data sources (e.g. the play-by-play/video-tagging
    pipeline spells a player differently than the official season-stats page). Loaded from
    data/name_aliases.json so the app and the parser notebook (cell 124) share ONE copy instead of two
    hand-maintained dicts that can silently drift out of sync as new mismatches turn up. Falls back to the
    one known mismatch inline if the file is missing (e.g. an older data checkout), so this never hard-fails.
    """
    path = os.path.join(DATA_DIR, "name_aliases.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                raw = json.load(f)
            return {k: v for k, v in raw.items() if not k.startswith("_")}
        except Exception:
            pass
    return {"mauryon turner": "Maurquis Turner"}


KNOWN_NAME_ALIASES = _load_name_aliases()

# Play-by-play strings the parser's classify_event() couldn't recognise used to be stored as the event's
# "player", producing rows like "Commits Foul" or "Jump Ball (Block Tie Up)" with real minutes attached --
# one of them outranked every actual player on total minutes. The parser no longer does this, but the app
# still screens leaderboard inputs so an older CSV export (or a future unrecognised string) can't put a
# play description on the Season Leaders card.
JUNK_PLAYER_RE = r"(?i)^(?:TEAM$|Commits |Turnover|Jump Ball|Subs In|Subs Out|Timeout|Official )|(?: Commits Foul$)"

st.set_page_config(page_title="UWW Basketball Scouting", page_icon="🏀", layout="wide")


@st.cache_data(ttl=60)
def load_table(name: str) -> pd.DataFrame:
    """Loads a parser-exported CSV from DATA_DIR, cached for up to 60 seconds. A short TTL instead of the
    default no-expiry cache: with no TTL, a re-run of the parser (new CSVs on disk) has NO EFFECT on an
    already-running Streamlit process until it's manually restarted -- st.cache_data has no idea the
    underlying file changed, since it's keyed only on this function's arguments (`name`), not the file's own
    modification time. Confirmed as a real, live symptom, not a hypothetical: a fix that was verified correct
    against the parser's own data kept showing the old, pre-fix number in the app after a re-run. A short TTL
    trades a small amount of staleness (up to 60s) for the app self-correcting after any re-run without
    requiring a manual restart every single time -- a much better trade for how this app is actually used
    (frequent parser re-runs during active development/testing) than either extreme (no expiry, or no
    caching at all, which would reload every CSV on every single interaction)."""
    path = os.path.join(DATA_DIR, f"{name}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.columns.duplicated().any():
        # A CSV with two columns sharing the same header (e.g. two "PTS" columns from an upstream parsing
        # quirk) makes pandas return a Series/DataFrame instead of a scalar for ANY df[col] or row[col] access
        # on that name -- which then blows up downstream code that assumes a scalar (e.g. an f-string format,
        # or a `pd.notna(...)` truth check) with "truth value of a Series is ambiguous". Rather than chase
        # that error down individually everywhere a table gets used, guard it once here at the single
        # chokepoint every table load already goes through: keep the first occurrence of each duplicated
        # column name and drop the rest, so every table this function returns has unique column labels.
        df = df.loc[:, ~df.columns.duplicated()]
    return df


@st.cache_data
def _get_logo_filenames() -> list:
    """Return list of logo file stems (without extension) available in data/logo/."""
    logo_dir = os.path.join(DATA_DIR, "logo")
    if not os.path.isdir(logo_dir):
        return []
    return [os.path.splitext(f)[0] for f in os.listdir(logo_dir) if f.lower().endswith(".png")]


def find_logo_b64(*candidate_names: str) -> str:
    """Find and return base64-encoded logo for the first matching candidate name.

    Matching strategy (tried in order for each candidate):
      1. Exact match: data/logo/<candidate>.png
      2. Prefix match: candidate starts with a logo filename (longest match wins)
         e.g. candidate='Elmhurst Bluejays' matches logo 'Elmhurst.png'
      3. Reverse prefix: a logo filename starts with the candidate
         e.g. candidate='UW-Osh' would match logo 'UW-Oshkosh.png'
    """
    import base64 as _b64_logo
    logo_dir = os.path.join(DATA_DIR, "logo")
    if not os.path.isdir(logo_dir):
        return ""
    logo_stems = _get_logo_filenames()
    # Sort longest-first so the most specific prefix wins
    logo_stems_sorted = sorted(logo_stems, key=len, reverse=True)

    for name in candidate_names:
        if not name or pd.isna(name):
            continue
        name = str(name).strip()
        if not name:
            continue
        # Strategy 1: exact match
        logo_path = os.path.join(logo_dir, f"{name}.png")
        if os.path.exists(logo_path):
            with open(logo_path, "rb") as _lf:
                return _b64_logo.b64encode(_lf.read()).decode()
        # Strategy 2: candidate starts with a logo stem
        for stem in logo_stems_sorted:
            if name.startswith(stem) and len(stem) >= 3:
                logo_path = os.path.join(logo_dir, f"{stem}.png")
                with open(logo_path, "rb") as _lf:
                    return _b64_logo.b64encode(_lf.read()).decode()
        # Strategy 3: a logo stem starts with the candidate (reverse prefix)
        for stem in logo_stems_sorted:
            if stem.startswith(name) and len(name) >= 3:
                logo_path = os.path.join(logo_dir, f"{stem}.png")
                with open(logo_path, "rb") as _lf:
                    return _b64_logo.b64encode(_lf.read()).decode()
    return ""


@st.cache_data
def load_short_opponent_names() -> list:
    """uww_schedule uses full opponent names (e.g. "Ripon Red Hawks"), while every analytical table built from
    scouting reports / PBP / video tagging uses a shorter form (e.g. "Ripon") -- collect the union of short
    names actually in use so schedule rows can be resolved onto them."""
    names = set()
    for t in ["uww_pbp_events", "uww_opponent_game_plans", "uww_opponent_team_totals", "uww_opponent_rosters", "uww_opponent_schedules"]:
        df = load_table(t)
        names.update(n for n in df["opponent"].dropna().unique())
    return sorted(names, key=len, reverse=True)


def resolve_short_opponent(full_name, short_names: list):
    """Map a uww_schedule opponent name (e.g. "St. Thomas (TX) Celts") onto the shorter name used by the
    scouting-report / PBP tables (e.g. "St. Thomas (TX)"), by prefix match. Returns None if no scouting/PBP
    data exists yet for that opponent."""
    if pd.isna(full_name):
        return None
    full_name = str(full_name).strip()
    for short_name in short_names:  # already sorted longest-first so the most specific match wins
        if full_name.startswith(short_name):
            return short_name
    return None


# --------------------------------------------------------------------------------------------------------------
# Lineup profile matching -- what makes two opponent 5-man units "alike"
# --------------------------------------------------------------------------------------------------------------
# The Counter-Lineup panel used to rank UWW's best net-margin lineups season-wide and label them "vs <opponent>'s
# top lineup", even though nothing about the opponent entered the calculation -- the same three lineups came back
# for every opponent. A real counter has to depend on WHO is being countered.
#
# There is no head-to-head history to lean on for a first meeting, but uww_lineup_stints records the OPPONENT
# lineup on the floor for every stint UWW has played, and uww_player_profiles describes every scouted opponent
# player. So a lineup can be characterised (position mix, size, starters, scouted style) and UWW's record against
# SIMILAR units measured, even against a team never played.
LINEUP_STYLE_TAGS = ("three_point_shooter", "slasher_driver", "post_scorer", "playmaker",
                     "rebounder", "catch_and_shoot")
_POSITION_SLOTS = ("Guard", "Wing", "Forward/Post")

# Position mix carries full weight; a scouted style trait or an extra starter counts half as much. Height is
# handled separately in profile_distance().
_PROFILE_WEIGHTS = {**{f"pos_{p}": 1.0 for p in _POSITION_SLOTS},
                    "starters": 0.5,
                    **{f"tag_{t}": 0.5 for t in LINEUP_STYLE_TAGS}}


@st.cache_data(ttl=60)
def _opponent_player_lookup() -> dict:
    """(opponent, casefolded name) -> position group, role, height, scouted style tags."""
    prof = load_table("uww_player_profiles")
    lookup = {}
    if prof.empty or "name" not in prof.columns:
        return lookup
    for _, row in prof.iterrows():
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        tags = str(row.get("notes_tags_display", "") or "")
        lookup[(str(row.get("opponent", "")).strip(), name.casefold())] = {
            "position_group": str(row.get("position_group", "") or "Unknown"),
            "role": str(row.get("role", "") or ""),
            "height_inches": safe_float(row.get("height_inches")),
            "tags": {t.strip() for t in tags.split(",") if t.strip()},
        }
    return lookup


def lineup_profile(opponent, lineup_str):
    """Characterise one opponent 5-man unit, or None if it can't be characterised reliably.

    Returns None when fewer than three of the five players resolve in uww_player_profiles -- a profile built
    from two known players describes the gaps in the scouting data more than it describes the lineup, and
    silently matching on it would be worse than admitting there's no match.
    """
    lookup = _opponent_player_lookup()
    names = [n.strip() for n in str(lineup_str).split(",") if n.strip()]
    known = [p for p in (lookup.get((str(opponent).strip(), n.casefold())) for n in names) if p]
    if len(known) < 3:
        return None
    profile = {f"pos_{slot}": 0.0 for slot in _POSITION_SLOTS}
    for player in known:
        key = f"pos_{player['position_group']}"
        if key in profile:
            profile[key] += 1.0
    heights = [p["height_inches"] for p in known if p["height_inches"]]
    profile["height"] = (sum(heights) / len(heights)) if heights else None
    profile["starters"] = float(sum(1 for p in known if p["role"] == "Starter"))
    for tag in LINEUP_STYLE_TAGS:
        profile[f"tag_{tag}"] = float(sum(1 for p in known if tag in p["tags"]))
    profile["_known"] = len(known)
    return profile


def profile_distance(a, b) -> float:
    """Weighted Euclidean distance between two lineup profiles -- lower means more alike.

    Average height is compared in 3-inch units so that a three-inch difference in size counts about the same
    as one position slot differing; in raw inches it would swamp every other feature.
    """
    if not a or not b:
        return float("inf")
    total = sum(w * (a.get(k, 0.0) - b.get(k, 0.0)) ** 2 for k, w in _PROFILE_WEIGHTS.items())
    if a.get("height") and b.get("height"):
        total += ((a["height"] - b["height"]) / 3.0) ** 2
    return total ** 0.5


def describe_profile(profile) -> str:
    """Plain-language summary of a lineup profile, e.g. "3 guard, 2 forward - avg 6'4\" - three point shooter"."""
    if not profile:
        return ""
    bits = []
    mix = [f"{int(profile['pos_' + slot])} {slot.split('/')[0].lower()}"
           for slot in _POSITION_SLOTS if profile.get(f"pos_{slot}")]
    if mix:
        bits.append(", ".join(mix))
    if profile.get("height"):
        inches = profile["height"]
        bits.append(f"avg {int(inches // 12)}'{int(round(inches % 12))}\"")
    traits = [t.replace("_", " ") for t in LINEUP_STYLE_TAGS if profile.get(f"tag_{t}", 0) >= 2]
    if traits:
        bits.append(" / ".join(traits))
    return " · ".join(bits)


def counter_lineups(short_opponent, target_lineup, stints_df,
                    min_matched_minutes: float = 40.0, min_lineup_minutes: float = 2.0):
    """UWW's 5-man units ranked by net margin against opponent lineups that RESEMBLE `target_lineup`.

    Walks outward from the most similar opponent lineup UWW has faced until at least `min_matched_minutes`
    of floor time has been gathered, so the sample adapts to how much comparable basketball has been played
    rather than relying on a fixed similarity cutoff.

    Returns (table, matched_minutes, n_similar_units, target_description). `table` is None whenever the
    profile match can't be made -- the caller is expected to say so rather than quietly showing a
    season-wide ranking under a matchup-specific heading.
    """
    target = lineup_profile(short_opponent, target_lineup)
    needed = {"opponent", "opp_lineup", "uww_lineup", "stint_minutes", "uww_margin_change"}
    if target is None or stints_df is None or stints_df.empty or not needed <= set(stints_df.columns):
        return None, 0.0, 0, describe_profile(target)

    faced = stints_df[["opponent", "opp_lineup"]].dropna().drop_duplicates()
    scored = []
    for opp, lineup in faced.itertuples(index=False):
        distance = profile_distance(target, lineup_profile(opp, lineup))
        if distance != float("inf"):
            scored.append((distance, opp, lineup))
    if not scored:
        return None, 0.0, 0, describe_profile(target)
    scored.sort(key=lambda row: row[0])

    minutes_by_unit = stints_df.groupby(["opponent", "opp_lineup"])["stint_minutes"].sum()
    keep, matched_minutes = set(), 0.0
    for _, opp, lineup in scored:
        keep.add((opp, lineup))
        matched_minutes += float(minutes_by_unit.get((opp, lineup), 0.0))
        if matched_minutes >= min_matched_minutes:
            break
    if matched_minutes <= 0:
        return None, 0.0, 0, describe_profile(target)

    matched = stints_df[[(o, l) in keep for o, l in zip(stints_df["opponent"], stints_df["opp_lineup"])]]
    agg = (matched.groupby("uww_lineup")
                  .agg(MIN=("stint_minutes", "sum"), net=("uww_margin_change", "sum"))
                  .reset_index())
    agg = agg[agg["MIN"] >= min_lineup_minutes]
    if agg.empty:
        return None, matched_minutes, len(keep), describe_profile(target)
    agg["rate"] = agg["net"] / agg["MIN"]
    return (agg.sort_values("rate", ascending=False), matched_minutes, len(keep), describe_profile(target))


# --------------------------------------------------------------------------------------------------------------
# Opponent style profiles -- the basis for COMPARABLE OPPONENTS
# --------------------------------------------------------------------------------------------------------------
# The old comparison used the only two numbers in uww_opponent_team_totals -- points scored and points allowed --
# and called the nearest team "comparable". Two teams can post identical scoring lines and play nothing alike: a
# fast team that lives at the rim and a slow one that shoots 30 threes land on the same PPG. Points tell you how
# MUCH a team scores, not HOW, and "how" is what a game plan is built against.
#
# This builds a fuller profile per opponent out of tables that already exist, grouped into six style categories.
# Each CATEGORY carries equal weight in the distance, then splits that weight among its own features -- otherwise
# the four shot-profile numbers would outvote the single size number four to one purely by being more numerous.
#
# (key, display label, category)
OPPONENT_FEATURE_SPEC = [
    ("pts_pg",        "Points/gm",      "Scoring"),
    ("opp_pts_pg",    "Points allowed", "Scoring"),
    ("fg_pct",        "FG%",            "Shot profile"),
    ("tpa_pg",        "3PA/gm",         "Shot profile"),
    ("tp_pct",        "3P%",            "Shot profile"),
    ("fta_pg",        "FTA/gm",         "Shot profile"),
    ("ast_pg",        "Assists/gm",     "Ball control"),
    ("to_pg",         "Turnovers/gm",   "Ball control"),
    ("reb_pg",        "Rebounds/gm",    "Glass & rim"),
    ("blk_pg",        "Blocks/gm",      "Glass & rim"),
    ("stl_pg",        "Steals/gm",      "Pressure"),
    ("height_in",     "Avg height",     "Personnel"),
    ("share_shooter", "Shooter share",  "Personnel"),
    ("share_post",    "Post share",     "Personnel"),
]
OPPONENT_FEATURE_CATEGORIES = {}
for _k, _lbl, _cat in OPPONENT_FEATURE_SPEC:
    OPPONENT_FEATURE_CATEGORIES.setdefault(_cat, []).append(_k)


def _profile_games(opponent, group) -> tuple:
    """(games, is_verified) for an opponent's season -- the divisor behind every rate in the profile.

    get_opponent_games_played() falls back to a hardcoded 5 when it can't work the number out, which turns a
    28-game season into rates inflated more than fivefold (observed: 146 3PA/gm). A number that large is
    obviously wrong, but a 12-game team defaulting to 5 would produce a plausible-looking profile that is
    simply false -- and it would then be ranked as "comparable" on the strength of it. So the count is only
    treated as verified when it comes from real data, and unverified opponents have their rate-derived
    features dropped instead of guessed.
    """
    if "games_played" in group.columns:
        per_player = pd.to_numeric(group["games_played"], errors="coerce")
        if per_player.notna().any() and per_player.max() > 0:
            return float(per_player.max()), True
    # Deliberately NOT get_opponent_games_played(): its first branch counts games in
    # uww_opponent_prior_games_pbp keyed on `team`, which for a PAST opponent returns the handful of games
    # the UPCOMING opponent happened to play against them. Coe Kohawks came back as 3 that way, and Coe's
    # full-season totals divided by 3 read as 83.7 3PA/gm. Count from the opponent's own schedule instead.
    schedules = load_table("uww_opponent_schedules")
    if not schedules.empty and {"opponent", "outcome"} <= set(schedules.columns):
        own = schedules[schedules["opponent"] == opponent]
        completed = int(own["outcome"].notna().sum())
        if completed > 0:
            return float(completed), True
    return 5.0, False


def _pct_value(raw):
    """'44.8%' -> 44.8. Returns None for '-' / blank / unparseable."""
    text = str(raw).strip().rstrip("%")
    if not text or text.lower() in ("nan", "none", "-"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _sum_made_attempted(series) -> tuple:
    """Sum a column of 'made-attempted' strings (e.g. '73-201') into (made, attempted)."""
    made = attempted = 0
    for value in series.dropna():
        parts = str(value).split("-")
        if len(parts) == 2:
            try:
                made += int(parts[0]); attempted += int(parts[1])
            except ValueError:
                continue
    return made, attempted


def format_feature(key, value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    if key == "height_in":
        return f"{int(value // 12)}'{int(round(value % 12))}\""
    if key.startswith("share_"):
        return f"{value * 100:.0f}%"
    if key.endswith("_pct"):
        return f"{value:.1f}%"
    return f"{value:.1f}"


@st.cache_data(ttl=60)
def opponent_style_profiles() -> pd.DataFrame:
    """One row per scouted opponent describing HOW they play, indexed by opponent name.

    Built from uww_player_profiles (per-player season stats, size and scouted style tags) plus
    uww_opponent_team_totals for team scoring. Note the unit convention this table carries: PTS/REB/MIN are
    already per game, while AST/STL/BLK/TO are season TOTALS -- so the totals are divided by each player's own
    games played before being summed into a team rate.
    """
    prof = load_table("uww_player_profiles")
    totals = load_table("uww_opponent_team_totals")
    if prof.empty or "opponent" not in prof.columns:
        return pd.DataFrame()

    totals_by_opp = totals.set_index("opponent") if not totals.empty and "opponent" in totals.columns else pd.DataFrame()
    records = {}
    for opponent, group in prof.groupby("opponent"):
        group = group[~group["name"].astype(str).str.contains(JUNK_PLAYER_RE, na=False)]
        if group.empty:
            continue
        team_games, games_verified = _profile_games(opponent, group)
        team_games = team_games or 1
        games = (pd.to_numeric(group["games_played"], errors="coerce")
                 if "games_played" in group.columns else pd.Series(index=group.index, dtype="float64"))
        games = games.where(games > 0).fillna(team_games)

        col = lambda c: (pd.to_numeric(group[c], errors="coerce")
                         if c in group.columns else pd.Series(index=group.index, dtype="float64"))
        minutes = col("MIN").fillna(0.0)
        rotation = minutes >= 8.0                      # the players who actually shape how a team plays
        if not rotation.any():
            rotation = minutes > 0
        weights = minutes.where(rotation, 0.0)
        weight_total = float(weights.sum())

        def minute_weighted(values):
            usable = values.notna() & (weights > 0)
            return float((values[usable] * weights[usable]).sum() / weights[usable].sum()) if usable.any() else None

        tpm, tpa = _sum_made_attempted(group["3PM-A"]) if "3PM-A" in group.columns else (0, 0)
        _, fta = _sum_made_attempted(group["FTM-A"]) if "FTM-A" in group.columns else (0, 0)
        # Those made-attempted strings are season totals for the whole roster, so divide by team games.
        record = {
            "pts_pg": float(totals_by_opp.at[opponent, "team_ppg"]) if opponent in getattr(totals_by_opp, "index", []) and pd.notna(totals_by_opp.at[opponent, "team_ppg"]) else float(((col("PTS") * games).sum(skipna=True)) / team_games),
            "opp_pts_pg": float(totals_by_opp.at[opponent, "opp_ppg_allowed"]) if opponent in getattr(totals_by_opp, "index", []) and "opp_ppg_allowed" in totals_by_opp.columns and pd.notna(totals_by_opp.at[opponent, "opp_ppg_allowed"]) else None,
            "fg_pct": minute_weighted(group["FG%"].apply(_pct_value) if "FG%" in group.columns else pd.Series(dtype=float)),
            "tpa_pg": (tpa / team_games) if tpa else None,
            "tp_pct": (100.0 * tpm / tpa) if tpa else None,
            "fta_pg": (fta / team_games) if fta else None,
            # TEAM rate = every player's season total over the TEAM's games. Dividing each player's total by
            # his own games first and then summing answers a different question ("per game while available")
            # and overstates the team: it read 17.8 assists/gm where the play-by-play says 14.0.
            "ast_pg": float(col("AST").sum(skipna=True) / team_games),
            "to_pg": float(col("TO").sum(skipna=True) / team_games),
            # PTS/REB are per-player per-game averages over each player's OWN games. Summing them straight
            # overstates a team that rotates: ten players averaging 8 points across different subsets of the
            # season don't add up to 80 team points per game. Re-weight to real totals -> team games.
            "reb_pg": float(((col("REB") * games).sum(skipna=True)) / team_games),
            "blk_pg": float(col("BLK").sum(skipna=True) / team_games),
            "stl_pg": float(col("STL").sum(skipna=True) / team_games),
            "height_in": minute_weighted(col("height_inches")),
            "_players": int(len(group)),
            "_games": int(team_games),
        }
        # Without a trustworthy games count, every per-game rate derived from a season total is fiction.
        # Drop those features rather than publish them; the games-independent ones (scoring, size, style
        # shares) still stand, and the distance simply uses fewer features for this opponent.
        if not games_verified:
            for _unreliable in ("tpa_pg", "fta_pg", "ast_pg", "to_pg", "blk_pg", "stl_pg"):
                record[_unreliable] = None
        record["_games_verified"] = bool(games_verified)

        tags = group["notes_tags_display"].astype(str) if "notes_tags_display" in group.columns else pd.Series("", index=group.index)
        for share_key, tag in (("share_shooter", "three_point_shooter"), ("share_post", "post_scorer")):
            has_tag = tags.str.contains(tag, na=False)
            record[share_key] = float(weights[has_tag].sum() / weight_total) if weight_total > 0 else None
        records[opponent] = record

    frame = pd.DataFrame.from_dict(records, orient="index")
    return frame.replace([float("inf"), float("-inf")], pd.NA)


def _robust_scale(frame: pd.DataFrame) -> pd.DataFrame:
    """Median/IQR z-scores, clipped to +/-3.

    Deliberately not min-max (what this comparison used to do): min-max pins the range to the two most extreme
    teams, so one bad scrape -- and this pipeline has had them, hence the existing `team_ppg < 200` outlier
    guard -- squashes every real difference into a sliver of the 0-1 range. Median and IQR barely move.
    """
    scaled = pd.DataFrame(index=frame.index)
    for column in frame.columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        spread = (values.quantile(0.75) - values.quantile(0.25)) / 1.349
        if not spread or pd.isna(spread) or spread == 0:
            spread = values.std(ddof=0)
        if not spread or pd.isna(spread) or spread == 0:
            scaled[column] = 0.0
            continue
        scaled[column] = ((values - values.median()) / spread).clip(-3, 3)
    return scaled


def comparable_opponents(target_opponent: str, candidate_opponents, k: int = 3):
    """Rank `candidate_opponents` by how closely their style resembles `target_opponent`.

    Distance is a weighted RMS of z-score differences. Each category contributes equally; within a category the
    weight is split across its features; and the total is divided by the weight ACTUALLY used, so a team missing
    a feature isn't rewarded for having fewer things to differ on.

    Match score is 100*exp(-0.7*d): identical profiles score 100, a one-standard-deviation average gap scores
    about 50. Returns (ranked DataFrame, profile table) or (None, profiles).
    """
    profiles = opponent_style_profiles()
    feature_keys = [key for key, _, _ in OPPONENT_FEATURE_SPEC]
    if profiles.empty or target_opponent not in profiles.index:
        return None, profiles
    pool = [o for o in dict.fromkeys(candidate_opponents) if o in profiles.index and o != target_opponent]
    if not pool:
        return None, profiles

    present = [c for c in feature_keys if c in profiles.columns]
    scaled = _robust_scale(profiles[present])
    target = scaled.loc[target_opponent]
    category_weight = 1.0 / len(OPPONENT_FEATURE_CATEGORIES)

    rows = []
    for opponent in pool:
        candidate = scaled.loc[opponent]
        weighted_sq = used_weight = 0.0
        per_category = {}
        for category, keys in OPPONENT_FEATURE_CATEGORIES.items():
            keys = [key for key in keys if key in present]
            if not keys:
                continue
            each = category_weight / len(keys)
            cat_sq = cat_weight = 0.0
            for key in keys:
                a, b = target.get(key), candidate.get(key)
                if pd.isna(a) or pd.isna(b) or pd.isna(profiles.at[target_opponent, key]) or pd.isna(profiles.at[opponent, key]):
                    continue
                cat_sq += each * (a - b) ** 2
                cat_weight += each
            if cat_weight > 0:
                per_category[category] = (cat_sq / cat_weight) ** 0.5
                weighted_sq += cat_sq
                used_weight += cat_weight
        if used_weight <= 0:
            continue
        distance = (weighted_sq / used_weight) ** 0.5
        rows.append({"opponent": opponent, "distance": distance,
                     "match": int(round(100 * math.exp(-0.7 * distance))),
                     "features_used": sum(1 for key in present
                                          if not pd.isna(profiles.at[target_opponent, key])
                                          and not pd.isna(profiles.at[opponent, key])),
                     **{f"cat::{c}": v for c, v in per_category.items()}})
    if not rows:
        return None, profiles
    ranked = pd.DataFrame(rows).sort_values("distance").head(k).reset_index(drop=True)
    return ranked, profiles


# Mascot words seen in this league's schedules, plus the adjectives that only ever appear as part of a
# mascot ("Red Devils", "Flying Dutchmen"). Used to turn a schedule name into the school alone.
_MASCOT_WORDS = {
    "eagles", "titans", "spartans", "pioneers", "warhawks", "blugolds", "falcons", "pointers", "bears",
    "celts", "kohawks", "norse", "duhawks", "bluejays", "scots", "vikings", "storm", "wolves", "dutchmen",
    "beavers", "raiders", "knights", "lions", "tigers", "panthers", "cardinals", "yellowjackets", "devils",
    "hawks", "redhawks", "foresters", "britons", "leopards", "comets", "thunder", "chargers", "crusaders",
    "cobbers", "auggies", "royals", "tommies", "johnnies", "gusties", "oles", "pipers", "bulldogs",
    "trojans", "wildcats", "flames", "phoenix", "musketeers", "green", "blue", "gold",
}
_MASCOT_MODIFIERS = {"red", "blue", "flying", "prairie", "fighting", "golden", "big", "little", "green",
                     "black", "purple", "scarlet", "orange", "white", "grey", "gray"}
# Words that are part of a SCHOOL's name, never a mascot -- stripping these would break the name.
_SCHOOL_WORDS = {"state", "college", "university", "tech", "institute", "a&m", "saint", "st", "north",
                 "south", "east", "west", "central", "northern", "southern", "eastern", "western"}


def strip_team_mascot(name) -> str:
    """"UW-La Crosse Eagles" -> "UW-La Crosse", "Hope Flying Dutchmen" -> "Hope".

    Known mascot words are stripped from the end, then any modifier left dangling in front of one ("Red"
    in "Eureka Red Devils"). If nothing matched the list, a multi-word name drops its final word as a
    fallback -- schedule names in this data are "<School> <Mascot>" -- unless that word is part of a
    school name ("State", "College", "Tech") or a parenthetical qualifier like "(WI)". Never returns an
    empty string: if every token would be stripped, the original name is kept.

    Only safe to call on a RAW schedule name that's known to still carry a mascot -- the "guess and drop the
    last word" fallback above will wrongly chop a real word off a name that's already mascot-free (e.g.
    "UW-La Crosse" -> "UW-La"). For a name that might ALREADY be short (e.g. short_opponent, which usually
    already has no mascot but occasionally still does -- see strip_known_mascot_suffix()'s docstring), use
    strip_known_mascot_suffix() instead, which never guesses.
    """
    if not name or (isinstance(name, float) and pd.isna(name)):
        return ""
    _raw = str(name).strip()
    _toks = _raw.split()
    if len(_toks) < 2:
        return _raw
    _stripped = False
    while len(_toks) > 1 and _toks[-1].strip(".,").lower() in _MASCOT_WORDS:
        _toks.pop()
        _stripped = True
    if _stripped:
        while len(_toks) > 1 and _toks[-1].strip(".,").lower() in _MASCOT_MODIFIERS:
            _toks.pop()
    elif len(_toks) > 1:
        _last = _toks[-1].strip(".,").lower()
        if _last not in _SCHOOL_WORDS and not _toks[-1].startswith("("):
            _toks.pop()
    return " ".join(_toks) or _raw


def strip_known_mascot_suffix(name) -> str:
    """Strip a trailing mascot word (and any modifier in front of it, e.g. "Red" in "Red Devils") ONLY if
    the name ends with a word from the known _MASCOT_WORDS list. Unlike strip_team_mascot(), this never
    guesses at an unrecognized trailing word -- so it's safe to call on something that might ALREADY be
    mascot-free.

    CONFIRMED BUG (fixed here): opp_display used to be `short_opponent or strip_team_mascot(full_opponent)`
    -- which only stripped a mascot when short_opponent was falsy (no scouting data yet for that opponent).
    Once an opponent HAS scouting/PBP data, short_opponent is usually already mascot-free by convention, but
    isn't guaranteed to be -- if whichever source table resolve_short_opponent() matched against happens to
    still carry the mascot for a given opponent (e.g. "UW-Oshkosh Titans" instead of "UW-Oshkosh"), that
    string won a truthy `or` and the banner showed the mascot regardless of the earlier fix. Can't just run
    short_opponent through strip_team_mascot() to cover this -- its "guess the last word" fallback would
    mangle an already-correct multi-word short name like "UW-La Crosse" into "UW-La". This function is the
    safe middle ground: strips a mascot if (and only if) one is actually recognized.
    """
    if not name or (isinstance(name, float) and pd.isna(name)):
        return ""
    _raw = str(name).strip()
    _toks = _raw.split()
    if len(_toks) < 2:
        return _raw
    _stripped = False
    while len(_toks) > 1 and _toks[-1].strip(".,").lower() in _MASCOT_WORDS:
        _toks.pop()
        _stripped = True
    if _stripped:
        while len(_toks) > 1 and _toks[-1].strip(".,").lower() in _MASCOT_MODIFIERS:
            _toks.pop()
    return " ".join(_toks) or _raw


def get_team_abbreviation(name) -> str:
    """Derive a short (2-4 letter) code for a team name, e.g. "UW-Oshkosh Titans" -> "UWO", "UW-Whitewater"
    -> "UWW", "Elmhurst" -> "ELM". For narrow paired-column UI (Season Leaders, Team Stats, lineup/last-5
    comparison headers) where even the "short" scouting-report name (dropping the mascot) is too long to sit
    opposite "UWW" without crowding or wrapping. Not used for the broadcast-style banners, which have room
    for the full name.

    There's no official-abbreviation data source in the CSVs, so this is a heuristic:
      1. Drop any parenthetical content (e.g. "St. Thomas (TX)" -> "St. Thomas").
      2. Split on spaces and hyphens. A single-word name (e.g. "Elmhurst", "Ripon") uses its first 3 letters.
      3. A multi-word/hyphenated name takes one letter per word -- except an existing all-caps short token of
         3 letters or fewer (e.g. "UW") is kept whole, and "St" contributes "S" -- so "UW-Oshkosh" -> "UWO"
         and "St. Thomas" -> "ST".
    """
    if not name or (isinstance(name, float) and pd.isna(name)):
        return ""
    name = re.sub(r"\([^)]*\)", "", str(name)).strip()
    SKIP_WORDS = {"of", "the", "at"}
    tokens = [t.strip(".") for t in re.split(r"[\s\-]+", name) if t.strip(".")]
    tokens = [t for t in tokens if t.lower() not in SKIP_WORDS]
    if not tokens:
        return re.sub(r"[^A-Za-z]", "", name)[:4].upper()
    if len(tokens) == 1:
        letters = re.sub(r"[^A-Za-z]", "", tokens[0])
        return (letters[:3] if len(letters) > 3 else letters).upper()
    # Cap at the first 2 tokens: schedule opponent names are typically "<School> <Mascot>" (e.g. "UW-Oshkosh
    # Titans"), and a trailing mascot word should be DROPPED, not tacked on as a 3rd initial. This matches the
    # common case correctly (2-word real names like "Wisconsin Lutheran" are unaffected) at the cost of
    # occasionally under-abbreviating a genuine 3+-word school name with no mascot suffix -- an acceptable
    # trade-off since those are rare in this schedule.
    parts = []
    for t in tokens[:2]:
        if t.isupper() and len(t) <= 3:
            parts.append(t)
        elif t.lower() == "st":
            parts.append("S")
        else:
            parts.append(t[0].upper())
    abbr = "".join(parts)[:4]
    return abbr or re.sub(r"[^A-Za-z]", "", name)[:4].upper()


# A generational suffix is not a surname. Taking the last whitespace-separated token turned
# "Agape Keyes Jr." into a lineup member called "Jr." -- so strip any trailing suffix first and keep it
# attached to the name it belongs to.
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def surname(full_name) -> str:
    """'Agape Keyes Jr.' -> 'Keyes Jr.'; 'Tyshawn Teague-Johnson' -> 'Teague-Johnson'."""
    parts = [p for p in str(full_name).split() if p]
    if len(parts) < 2:
        return str(full_name).strip()
    suffix = []
    while len(parts) > 1 and parts[-1].strip(".").lower() in _NAME_SUFFIXES:
        suffix.insert(0, parts.pop())
    return " ".join(parts[-1:] + suffix)


def played_mask(schedule: pd.DataFrame) -> pd.Series:
    return schedule["outcome"].notna() & schedule["team_score"].notna()


# --------------------------------------------------------------------------------------------------------------
# Game identity: a game is (opponent, game_date), never the opponent name alone
# --------------------------------------------------------------------------------------------------------------
# UWW plays several conference opponents two or three times a season. Every table the parser exports is keyed on
# (opponent, game_date) for exactly that reason, but uww_schedule only carries a year-less DISPLAY date
# ("Sat, Jan 3"), so joining a schedule row to its game needs a translation step.
#
# Rather than re-infer the season's calendar year (the Dec->Jan boundary problem the parser itself has to solve),
# match on month/day against the ISO dates the data already carries. Two games can't share a month/day within one
# season, so the mapping is unambiguous and can't drift from whatever the parser produced.
_MONTH_ABBR = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
               "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


@st.cache_data(ttl=60)
def _game_date_index() -> dict:
    """(month, day) -> ISO 'YYYY-MM-DD', collected from every game-keyed table's own game_date column."""
    index = {}
    for table in ("uww_pbp_box_score", "uww_pbp_events", "uww_lineup_stints", "uww_scoring_runs"):
        df = load_table(table)
        if df.empty or "game_date" not in df.columns:
            continue
        for raw in df["game_date"].dropna().astype(str).unique():
            iso = raw[:10]
            try:
                _, month, day = (int(part) for part in iso.split("-"))
            except ValueError:
                continue
            index.setdefault((month, day), iso)
    return index


def resolve_game_date(display_date):
    """'Sat, Jan 3' -> '2026-01-03'. Returns None when no parsed game matches that day."""
    m = re.match(r"^\w{3},\s+(\w{3})\s+(\d+)$", str(display_date).strip())
    if not m:
        return None
    month = _MONTH_ABBR.get(m.group(1))
    return _game_date_index().get((month, int(m.group(2)))) if month else None


def played_game_dates(played: pd.DataFrame) -> set:
    """ISO dates of the games in `played` that actually have parsed data behind them."""
    if played.empty or "date" not in played.columns:
        return set()
    return {d for d in (resolve_game_date(v) for v in played["date"]) if d}


def scope_to_played(df: pd.DataFrame, played: pd.DataFrame) -> pd.DataFrame:
    """Restrict a game-keyed table to the games in `played`, matching on DATE rather than opponent name.

    Filtering on opponent name (what this app used to do) cannot express "the first Oshkosh game but not the
    second": both meetings share one name, so a season aggregate built before the rematch silently swallowed
    the rematch too. Falls back to returning `df` unchanged only when the table has no game_date at all.
    """
    if df.empty or "game_date" not in df.columns:
        return df
    dates = played_game_dates(played)
    if not dates:
        return df.iloc[0:0]
    return df[df["game_date"].astype(str).str[:10].isin(dates)]


def get_game_outcomes(schedule: pd.DataFrame) -> dict:
    """ISO game_date -> "W"/"L". The per-DATE counterpart to get_opponent_outcomes().

    get_opponent_outcomes() keys on the opponent's name, so for a home-and-home it can only report ONE result
    for two games -- and quietly reports the first meeting's for both. Use this wherever a per-game outcome is
    what's actually meant (win/loss splits, situational splits, trend charts).
    """
    outcomes = {}
    for _, row in schedule.iterrows():
        if pd.notna(row.get("outcome")):
            iso = resolve_game_date(row["date"])
            if iso:
                outcomes[iso] = row["outcome"]
    return outcomes


def get_opponent_outcomes(schedule: pd.DataFrame, opponent_names) -> dict:
    """Map each short opponent name in `opponent_names` to UWW's game outcome ("W"/"L") against them, by
    prefix-matching uww_schedule's full opponent names against the short names used by the scouting/PBP
    tables (same matching rule as resolve_short_opponent).

    This centralizes a "for schedule row -> for short name -> startswith" loop that was previously
    duplicated near-verbatim in ~6 places across this file (get_data_driven_ktv, the Upcoming Game team-stats
    builder, Previous Games, Team page situational splits, and the lineup-matchup sections). Keep new
    win/loss-split features going through this helper rather than re-adding another copy of the loop.
    """
    outcomes = {}
    for _, row in schedule.iterrows():
        if pd.notna(row.get("outcome")):
            full_name = str(row["opponent"])
            for opp in opponent_names:
                if full_name.startswith(opp):
                    outcomes[opp] = row["outcome"]
                    break
    return outcomes


def prior_opponent_shortnames(box: pd.DataFrame, played: pd.DataFrame) -> set:
    """DEPRECATED -- use scope_to_played(), which filters on game_date instead of opponent name.

    Kept only so an older call site still imports cleanly. Opponent names cannot distinguish a first meeting
    from a rematch, so this can never express "before the upcoming game" for a repeat opponent.
    """
    """The set of short opponent names in `box` (any table keyed the way uww_pbp_box_score is) corresponding
    to games UWW played BEFORE the upcoming game -- i.e. the rows in `played`.

    Box-score tables are NOT scoped by date: they hold every game that has been parsed, which can include
    games chronologically AFTER the simulated "upcoming" game whenever reference_date is set artificially
    early to test against a real, further-along season. Any season aggregate that doesn't intersect against
    `played` first will therefore quietly include the future. This is the single most repeated bug class in
    this project, so the intersection lives here once instead of being rewritten at each call site.
    """
    if box.empty or played.empty or "opponent" not in box.columns:
        return set()
    names = box["opponent"].dropna().unique().tolist()
    names.sort(key=len, reverse=True)  # longest-first so the most specific match wins
    return {resolve_short_opponent(_po, names) for _po in played["opponent"].dropna()} - {None}


def get_opponent_games_played(short_opponent: str, default: int = 5) -> int:
    """Count of games played by the opponent, before their matchup against UWW -- used to convert an
    opponent's season-TOTAL stats into per-game rates.

    In uww_player_profiles, PTS and REB are already per-game averages (no division needed), but AST/STL/BLK/TO
    and the 3PM-A/FTM-A "made-attempted" strings are season-CUMULATIVE totals and need dividing by this
    helper's result. (Confirmed empirically, not just from a comment: summing AST across a roster with no
    division produces an implausible ~200 "assists per game" figure -- only sane as a season sum. Not every
    column in this table shares the same units; don't assume otherwise without checking real output again.)

    CONFIRMED BUG (fixed here, a second time): first fix corrected this to slice uww_opponent_schedules down
    to "games before facing UWW" instead of counting their whole season -- correct in general, but for the
    CURRENT upcoming opponent specifically it's the WRONG SOURCE now that pbp_box_score_upcoming exists.
    Confirmed directly: Eureka's BLK/gm showed 1.0 instead of the real 1.67 (5 blocks over 3 games) -- exactly
    the shape of 5 blocks / 5 (this function's own DEFAULT fallback), meaning uww_opponent_schedules either
    had no usable pre-UWW entry for them or disagreed with the actual PBP-reconstructed game count. Two
    independent sources claiming to both mean "games before facing UWW" is exactly the kind of drift this
    project has hit before (the reference_date scoping bugs). For the CURRENT upcoming opponent, prefer
    pbp_box_score_upcoming's own game count directly -- the same data uww_player_profiles' BLK (etc.) now
    comes from after the parser-side override, so numerator and denominator are guaranteed to agree instead of
    trusting two different tables to have stayed in sync. Falls back to the schedule-based count (then the
    hardcoded default) only for an opponent that ISN'T the current upcoming one, where no PBP game log exists.
    """
    if not short_opponent:
        return default
    try:
        pbp_upcoming = load_table("uww_opponent_prior_games_pbp")
        # CONFIRMED BUG (fixed here): this matched on the "opponent" COLUMN, which in this table does NOT
        # mean "the upcoming opponent" -- the parser (build_pbp_events) sets it to whoever the upcoming
        # opponent ACTUALLY PLAYED in each prior game (these are their games BEFORE facing UWW, so Whitewater
        # isn't in them at all). So `opponent == short_opponent` matched ZERO rows for EVERY opponent, this
        # branch never fired once, and it silently fell through to the hardcoded default of 5 below. The
        # column carrying the upcoming opponent is "team" (which side each event belongs to).
        #
        # Exact equality is safe here: the parser labels these rows with `upcoming_opponent_short`, and this
        # app's `short_opponent` must be the identical string, because both sides also exact-match into
        # uww_player_profiles["opponent"] (the parser's stat override in cell 139, and opp_prof_ts here) and
        # both find rows. If those two names could differ, the opponent's stats would be empty long before
        # reaching this function.
        if not pbp_upcoming.empty and {"team", "game_date"} <= set(pbp_upcoming.columns):
            own_rows = pbp_upcoming[pbp_upcoming["team"] == short_opponent]
            n_pbp = own_rows["game_date"].nunique() if not own_rows.empty else 0
            if n_pbp > 0:
                return n_pbp
    except Exception:
        pass
    opp_sched = load_table("uww_opponent_schedules")
    if opp_sched.empty or "opponent" not in opp_sched.columns:
        return default
    opp_games = opp_sched[opp_sched["opponent"] == short_opponent]
    if opp_games.empty:
        return default
    uww_idx = None
    for i, r in opp_games.iterrows():
        vs = str(r.get("vs_opponent", "")).lower()
        if "whitewater" in vs or "uww" in vs:
            uww_idx = i
            break
    pre_uww = opp_games.loc[:uww_idx].iloc[:-1] if uww_idx is not None else opp_games
    games = pre_uww[pre_uww["outcome"].notna()]
    n = len(games)
    return n if n > 0 else default


def opponent_prior_games_scheduled(short_opponent: str):
    """How many games this opponent actually PLAYED before facing UWW, straight from their own schedule --
    or None when their schedule hasn't been parsed.

    Deliberately NOT get_opponent_games_played(): for the current upcoming opponent that function returns
    the number of games with play-by-play data (which is the point there -- it has to agree with the stat
    numerators it divides). Those are different numbers whenever some of the opponent's games have no
    local _pbp/_video file, and presenting the tagged-video count as their schedule is what made a key
    read "across 15 team(s) they played before UWW" for a team that had played 28 games.
    """
    opp_sched = load_table("uww_opponent_schedules")
    if opp_sched.empty or "opponent" not in opp_sched.columns:
        return None
    opp_games = opp_sched[opp_sched["opponent"] == short_opponent]
    if opp_games.empty:
        return None
    uww_idx = None
    for i, r in opp_games.iterrows():
        vs = str(r.get("vs_opponent", "")).lower()
        if "whitewater" in vs or "uww" in vs:
            uww_idx = i
            break
    pre_uww = opp_games.loc[:uww_idx].iloc[:-1] if uww_idx is not None else opp_games
    n = len(pre_uww[pre_uww["outcome"].notna()]) if "outcome" in pre_uww.columns else len(pre_uww)
    return n or None


def get_opponent_entering_record(short_opponent: str) -> tuple:
    """The opponent's own W-L record and current streak from the games on THEIR schedule (uww_opponent_schedules)
    that came before their matchup against UWW -- i.e. what their record looked like entering that specific
    game. Returns (record_str, streak_str), each "" if it can't be determined (e.g. no opponent-schedule data
    parsed for them yet).

    Shared by the Upcoming Game banner (that game hasn't happened yet, so "entering" just means "as of now")
    and the Previous Games banner (a past game, so "entering" means their record as of THAT game).

    CAVEAT: if this opponent played UWW more than once this season (e.g. a conference home-and-home), this
    always anchors on their FIRST "vs Whitewater"-labeled row on uww_opponent_schedules -- so for a second
    meeting, the record/streak shown here would actually be "entering the FIRST meeting," not the second.
    True multi-meeting scheduling is rare enough in this data that a date-based match wasn't worth the added
    fragility (uww_opponent_schedules' game_date is the same year-less "Fri, Nov 14"-style display string as
    everywhere else in this app, which can't be safely sorted across the season's Dec->Jan boundary without
    the same year-inference logic the parser itself uses).
    """
    if not short_opponent:
        return "", ""
    opp_sched = load_table("uww_opponent_schedules")
    opp_games = opp_sched[opp_sched["opponent"] == short_opponent] if not opp_sched.empty else pd.DataFrame()
    if opp_games.empty:
        return "", ""
    uww_idx = None
    for i, r in opp_games.iterrows():
        vs = str(r.get("vs_opponent", "")).lower()
        if "whitewater" in vs or "uww" in vs:
            uww_idx = i
            break
    pre_uww = opp_games.loc[:uww_idx].iloc[:-1] if uww_idx is not None else opp_games
    if pre_uww.empty:
        return "", ""
    ow = int((pre_uww["outcome"] == "W").sum())
    ol = int((pre_uww["outcome"] == "L").sum())
    record_str = f"{ow}-{ol}"
    streak_count, streak_type = 0, ""
    for out in pre_uww["outcome"].iloc[::-1]:
        if streak_count == 0:
            streak_type = out
            streak_count = 1
        elif out == streak_type:
            streak_count += 1
        else:
            break
    # CONFIRMED BUG (fixed here): this produced "3W streak" while the UWW-side streak computed independently
    # in render_upcoming_game() (the banner this feeds) produces "1-game loss streak" -- same banner, two
    # different wordings for the same kind of fact. Matched to the UWW-side phrasing rather than the reverse,
    # since "N-game win/loss streak" reads as a sentence and "3W streak" doesn't.
    streak_label = "win" if streak_type == "W" else "loss"
    streak_str = f"{streak_count}-game {streak_label} streak" if streak_count >= 1 else ""
    return record_str, streak_str


def get_season_label(schedule: pd.DataFrame) -> str:
    """Derive a "YYYY-YY Season Overview" label (e.g. "2025-26 Season Overview") from the schedule's own game
    dates, instead of a literal hardcoded string that silently goes stale every year the app isn't touched.
    A college basketball season runs Nov (year Y) through Mar/Apr (year Y+1); games falling Jul-Dec belong to
    the season that started that same calendar year, games Jan-Jun belong to the season that started the
    previous calendar year."""
    try:
        dates = pd.to_datetime(schedule["date"], errors="coerce").dropna()
        if dates.empty:
            return "Season Overview"
        start_years = dates.dt.year.where(dates.dt.month >= 7, dates.dt.year - 1)
        start_year = int(start_years.mode().iloc[0])
        return f"{start_year}-{str(start_year + 1)[-2:]} Season Overview"
    except Exception:
        return "Season Overview"


def report_section_error(section_name: str, exc: Exception) -> None:
    """Surface a section-level failure instead of silently hiding it.

    Several optional-but-substantive sections (season projection accuracy, projected-vs-actual performance,
    coaching flags) were wrapped in bare `except Exception: pass`, so a whole section could vanish from the
    page with zero indication of whether that's because there's genuinely no data yet, or because something
    broke. This at least tells the coach which happened, without crashing the page.
    """
    st.caption(f"⚠️ {section_name} unavailable right now ({exc.__class__.__name__}: {exc}).")


def esc(val) -> str:
    """html.escape() that tolerates None/NaN -- for any FREE-TEXT data field (scouting notes, coaching-flag
    text, game-plan notes) going into an f-string rendered with unsafe_allow_html=True.

    Player/opponent NAMES were already consistently escaped throughout this file with html.escape(), but
    several free-text fields sourced straight from scraped/PDF-parsed scouting reports (coaching-flag
    "flag"/"evidence"/"recommendation" text, in particular) were being interpolated unescaped. A stray
    "<"/">" in that source data would silently break the layout; if this app is ever opened to more than one
    trusted user it's also a stored-HTML-injection surface. Use this wrapper anywhere free text meets
    unsafe_allow_html=True.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return html.escape(str(val))


def style_map(styler, func, subset=None):
    """Styler.applymap() under pandas < 2.1, Styler.map() from 2.1 on.

    applymap was deprecated in pandas 2.1 and REMOVED in 3.0, which is what raised
    "'Styler' object has no attribute 'applymap'" on the Player Detail dialog. Routed through one helper
    so every styled table in this file works on either pandas.
    """
    _fn = getattr(styler, "map", None) or getattr(styler, "applymap")
    return _fn(func, subset=subset) if subset is not None else _fn(func)


def safe_scalar(val):
    """Coerce a value down to a single scalar if it's actually a pandas Series.

    Indexing a DataFrame ROW (e.g. `row['PTS']`, `row.get('PTS')`) normally returns a plain scalar -- but if
    the row's *source DataFrame* has two columns sharing the same name (a real, confirmed issue in one of the
    parser's scraped tables; load_table() now dedupes this at load time, but this is a second line of
    defense for any table/code path that reaches a row before that dedup can apply), the same lookup instead
    returns a Series, and anything downstream that formats it (an f-string, a `pd.notna(...)` truth check)
    crashes with "the truth value of a Series is ambiguous". Use this to unwrap that safely before display:
    `safe_scalar(row.get('PTS'))` always yields a scalar (or None), never a Series.
    """
    if isinstance(val, pd.Series):
        return val.iloc[0] if not val.empty else None
    return val


def safe_float(val):
    """Coerce a value to a float for display formatting (e.g. an f-string ':.1f' spec), or return None if
    that isn't possible.

    A CSV column pandas infers as `object` dtype (because at least one row in it wasn't cleanly numeric --
    a stray "-", a blank, a stat recorded as "N/A", etc.) hands back a plain Python str for every row, even
    the ones that "look like" a number. `pd.notna()` on that string is True (a string isn't null), so a naive
    `f"{val:.1f}" if pd.notna(val) else "-"` gets past the notna check and then crashes formatting a str with
    a numeric spec. Route every value through this first: run safe_scalar() to rule out a stray Series too,
    then try a real numeric conversion, falling back to None (never raising) so the caller's own `if ... else
    "-"` fallback still works for both "missing" and "not actually numeric" in one place.
    """
    val = safe_scalar(val)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _normalize_case(text: str) -> str:
    """Convert ALL-CAPS text to sentence case; leave mixed-case text alone."""
    stripped = re.sub(r"[^a-zA-Z]", "", text)
    if stripped and stripped == stripped.upper() and len(stripped) > 1:
        return text[0].upper() + text[1:].lower()
    return text


# Keys-to-Victory stat mapping: basketball terminology → stat columns
KEYS_TO_VICTORY_STAT_MAP = {
    # Ball Security
    "ball security": ["TO"], "turnover": ["TO"], "protect the ball": ["TO"], "take care of the ball": ["TO"],
    "limit turnovers": ["TO"], "careless": ["TO"],
    # Rebounding
    "own the paint": ["REB", "ORB", "DRB"], "bully": ["REB", "ORB", "DRB"], "glass": ["REB", "ORB", "DRB"],
    "rebound": ["REB", "ORB", "DRB"], "board": ["REB", "ORB", "DRB"], "second chance": ["ORB"],
    "crash": ["REB", "ORB", "DRB"],
    # Three-Point Shooting
    "three": ["3PM-A", "3P%"], "3 pt": ["3PM-A", "3P%"], "3pt": ["3PM-A", "3P%"],
    "perimeter shooting": ["3PM-A", "3P%"], "spacing": ["3PM-A", "3P%"],
    "shooting ability": ["3PM-A", "3P%"], "shooting team": ["3PM-A", "3P%"],
    "sniper": ["3PM-A", "3P%"], "will shoot": ["3PM-A", "3P%"],
    # Free Throws
    "free throw": ["FTM-A", "FT%"], "ft line": ["FTM-A", "FT%"], "getting to ft": ["FTM-A", "FT%"],
    # Fouls / Discipline
    "foul": ["PF"], "wall up": ["PF"], "drawing fouls": ["PF"],
    # Ball Movement / Assists
    "assist": ["AST"], "ball movement": ["AST"], "share the ball": ["AST"],
    "playmaking": ["AST"], "playmaker": ["AST"], "create": ["AST"],
    # Perimeter Defense / Ball Pressure
    "steal": ["STL"], "press capable": ["STL", "TO"], "full court press": ["STL", "TO"],
    "force turnovers": ["STL"], "force to's": ["STL"],
    "guard your yard": ["STL"], "keep the ball in front": ["STL"], "guard 1 on 1": ["STL"],
    "early gap": ["STL"], "help side": ["STL"], "active hands": ["STL"],
    "physical & aggressive on ball": ["STL"], "on ball defensively": ["STL"],
    "pressure": ["STL"],
    # Paint Protection / Blocks
    "block": ["BLK"], "protect the rim": ["BLK"], "paint protection": ["BLK"],
    # Scoring Inside (2PT FG)
    "dominate the paint": ["FG2M", "FG2A", "FG2%"], "attack the paint": ["FG2M", "FG2A", "FG2%"],
    "live in the paint": ["FG2M", "FG2A", "FG2%"], "attack the basket": ["FG2M", "FG2A", "FG2%"],
    "scoring at the rim": ["FG2M", "FG2A", "FG2%"], "get to rim": ["FG2M", "FG2A", "FG2%"],
    "attack the rim": ["FG2M", "FG2A", "FG2%"], "get to the rim": ["FG2M", "FG2A", "FG2%"],
    # Field Goal Efficiency (overall)
    "limit their scoring": ["FGM-A", "FG%"],
}
STAT_LABELS = {
    "TO": "Turnovers/gm", "REB": "Rebounds/gm", "ORB": "Off. rebounds/gm", "DRB": "Def. rebounds/gm",
    "AST": "Assists/gm", "STL": "Steals/gm", "BLK": "Blocks/gm", "3PM-A": "3PM-A/gm", "3P%": "3P%",
    "FGM-A": "FGM-A/gm", "FG%": "FG%", "FTM-A": "FTM-A/gm", "FT%": "FT%", "PF": "Fouls/gm",
    "FG2M": "2PT FGM/gm", "FG2A": "2PT FGA/gm", "FG2%": "2PT FG%",
}

# KTV Category Reference: maps categories to the keywords and stats they track
KTV_CATEGORY_REFERENCE = {
    "Ball Security": {"keywords": "ball security, protect the ball, take care of the ball, limit turnovers, our turnovers, live-ball turnover, live-ball turnovers, dead-ball turnover, dead-ball turnovers, careless, live dribble, sloppy, giveaway, giveaways, unforced, to's, turnover battle, possession battle, win the possession battle", "stats": "TO"},
    "Rebounding": {"keywords": "own the paint, bully, glass, rebound, rebounding, rebounds, board, boards, second chance, crash, dominate the paint, box out, put back, putback, reb, rebs, o-board, o-boards, d-board, d-boards, offensive board, offensive boards, rebound advantage", "stats": "REB, ORB, DRB"},
    "Three-Point Shooting": {"keywords": "three, threes, 3, 3s, 3's, 3 pt, 3pt, 3-pt, 3-point, 3-pointer, 3-pointers, three-point, three-pointer, three-pointers, three point, perimeter shooting, spacing, shooting ability, shooting team, sniper, will shoot, trey, treys, deep ball, deep balls, beyond the arc, from deep, transition three, transition threes, transition 3, transition 3's, catch and shoot, corner three, corner 3, above the break, shooter, shooters, can shoot, shoot it, stretch big, stretch four", "stats": "3PM-A, 3P%"},
    "Free Throws": {"keywords": "free throw, free throws, ft, ft's, fts, ft line, getting to ft, foul line, ft rate, and-one, and one", "stats": "FTM-A, FT%"},
    "Fouls / Discipline": {"keywords": "foul, fouls, wall up, drawing fouls, discipline, reach, reaching, hand check", "stats": "PF"},
    "Ball Movement / Assists": {"keywords": "assist, assists, ball movement, share the ball, playmaking, playmaker, create, extra pass, hockey assist, swing the ball", "stats": "AST"},
    "Paint Protection / Blocks": {"keywords": "block, blocks, protect the rim, paint protection, rim protection, shot blocking, contest at the rim, pack the paint, pack & protect, pack and protect, protect the paint, paint defense, build a wall, building a wall, wall around the paint, wall off, post defense, physicality, physical defense, strong gap, gap/pack, our paint, must be our paint, no easy paint, limit their scoring, limit their scoring @ the rim, keep them out of the paint", "stats": "BLK"},
    "Perimeter Defense / Ball Pressure/ Create Turnovers": {"keywords": "steal, steals, press capable, full court press, force turnovers, force to's, forcing turnovers, generate turnovers, turnover trigger, turnover triggers, guard your yard, keep the ball in front, guard 1 on 1, early gap, help side, active hands, physical & aggressive on ball, on ball defensively, pressure, ball pressure, deny, deflection, deflections, contain, containing, squeeze, squeeze & limit, lock up", "stats": "STL"},
    "Scoring Inside": {"keywords": "dominate the paint, attack the paint, live in the paint, attack the basket, scoring at the rim, get to rim, attack the rim, get to the rim, post up, post-up, paint touches, drive, drives, downhill, finish at the rim, attacking the paint, attacking the rim, attacking the basket, attacking inside, attack inside, inside-out, inside out, post play, scoring in the paint, points in the paint, paint points, payback inside", "stats": "FG2M, FG2A, FG2%"},
    "Field Goal Efficiency": {"keywords": "field goal, field goal%, fg%, shooting percentage, efficient shooting, efficiency, good shots, quality shots", "stats": "FGM-A, FG%"},
    "Defensive Efficiency": {"keywords": "high-volume, high volume, funnel, funneling, take away, most efficient, shot profile, shot diet, inefficient looks, worst looks, multiple efforts, multiple effort, never stop, multiple scorers, multiple threats, multiple weapons, multiple options, scoring options, scoring threats, balanced scoring, scoring balance, scoring depth, several scorers, many scorers, deep scoring, double-digit scorers, double digit scorers, leading scorer, top scorer, primary scorer, go-to scorer, go to scorer, versatile scorers, score from anywhere, score at all three levels, three levels, three-level scorer, three level scorer, their scorers, their weapons, set play, set plays, set piece, set pieces, counters, counter action, counter actions, wrinkle, wrinkles, playbook, play call, play calls, scripted, after timeout, out of bounds play, out of bounds plays, blob, slob, baseline out of bounds, sideline out of bounds, horns, stagger, staggered screen, pin down, pindown, down screen, back screen, flare screen, flex, ram screen, ball screen, ball screens, ball screen action, ball screen actions, pick and roll, pick-and-roll, pick and pop, pick-and-pop, dribble handoff, dho, motion offense, continuity, action, actions, action sets, screening, screening action, switch all screens, switch everything, switching off ball, create advantages, creating advantages, advantage creation, advantages, capable of carrying, carrying offense, carry the offense, main scorer, primary option, focal point, go-to guy, big scoring games, capable of big games, capable of big scoring", "stats": "Opp FG% by shot type"},
    "Offensive Efficiency": {"keywords": "attack & execute, attack and execute, execute offensively, attack offensively, shot selection, shot quality, best shot type, mismatch, mismatches, attacking mismatches, attack mismatches, attack the mismatch, hunt mismatches, hunt the mismatch, exploit mismatches, exploit the mismatch, target mismatches, find the mismatch, size advantage, size mismatch, speed advantage, quickness advantage, switch hunting, hunt switches, hunt the switch, isolate, isolation, iso, post mismatch, favorable matchup, favorable matchups, best matchup, best matchups, exploit matchup, exploit matchups, attack matchups, attack matchup, attacking matchups, matchups vs switches, attack & execute offensively", "stats": "TS%, eFG%"},
    "Personnel/Rotation": {"keywords": "bench trust, off the bench, foul trouble, closing lineup, closing 5, close the game, clutch, late-game, late game, rotation, sub pattern, substitution pattern, trust plan, who to trust, core players, deep bench, man rotation", "stats": "MIN, Game Score"},
    # NEW (added after an audit of every real key): transition/pace and effort/communication language was
    # scattered across PHRASE_SIDE with no category of its own, so keys like "TRANSITION DEFENSE!!!" and
    # "RELENTLESS EFFORT & WINNING PLAYS" fell through to the "Other" bucket. Defined LAST on purpose --
    # _grouped uses the FIRST matched category, so these only claim a key nothing more specific caught.
    # Our own called sets. Distinct from Offensive Efficiency (shot quality/selection) -- "which plays to
    # run" is its own decision, and the Plays to Lean On card is pinned here rather than being lumped in
    # with efficiency keys.
    "Four Factors": {"keywords": "four factors, efg, efg%, true shooting, ts%, turnover rate, offensive rebound rate, ft rate, possession game", "stats": "eFG%, TOV%, ORB%, FT Rate"},
    "Play Calls": {"keywords": "play call, play calls, called set, called sets, our sets, run this set, lean on, go-to play, go to play, go-to set, playbook set, best plays, top play", "stats": "Play FG%"},
    "Transition / Pace": {"keywords": "transition, transition defense, transition offense, get back, getting back, sprint back, run the floor, push the pace, push tempo, push hard, pushing the pace, fast break, fastbreak, early offense, secondary break, pace, tempo, run in transition", "stats": "Fast break pts, Pace"},
    "Coaching Notes": {"keywords": "effort, relentless, winning plays, connected, being connected, communication, communicate, talk, talking, toughness, tough, compete, competing, finish possessions, finish defensive possessions, late clock, both ends, multiple efforts, multiple effort, never stop, energy, all five, together", "stats": "--"},
}

# Side detection: maps scouting phrases to whether they describe UWW (proactive) or OPP (contain opponent)
PHRASE_SIDE = {
    # Ball Security: UWW = protect; OPP = force turnovers
    "ball security": "UWW", "turnover": "UWW", "protect the ball": "UWW",
    "take care of the ball": "UWW", "limit turnovers": "UWW", "careless": "UWW",
    # Rebounding: UWW = crash; OPP = box out
    "own the paint": "UWW", "bully": "UWW", "glass": "UWW",
    "rebound": "UWW", "board": "UWW", "second chance": "UWW", "crash": "UWW",
    "box out": "OPP", "keep off glass": "OPP",
    # Three-Point Shooting: UWW = hit shots; OPP = contest/run off
    "three": "UWW", "threes": "UWW", "3": "UWW", "3s": "UWW", "3's": "UWW",
    "3 pt": "OPP", "3pt": "OPP", "3-pt": "OPP", "3-point": "UWW", "3-pointer": "UWW", "3-pointers": "UWW",
    "three-point": "UWW", "three-pointer": "UWW", "three-pointers": "UWW", "three point": "UWW",
    "perimeter shooting": "UWW", "spacing": "UWW",
    "shooting ability": "OPP", "shooting team": "OPP", "sniper": "OPP", "will shoot": "OPP",
    "trey": "UWW", "treys": "UWW", "deep ball": "UWW", "deep balls": "UWW", "from deep": "UWW",
    "transition three": "UWW", "transition threes": "UWW", "transition 3": "UWW", "transition 3's": "UWW",
    "catch and shoot": "UWW", "corner three": "UWW", "corner 3": "UWW", "above the break": "UWW",
    "close out": "OPP", "closeout": "OPP", "run off the line": "OPP",
    # Free Throws: UWW = get to line; OPP = keep off line
    "free throw": "UWW", "ft line": "UWW", "getting to ft": "UWW",
    "don't foul": "OPP", "keep them off": "OPP",
    # Fouls / Discipline: UWW = stay disciplined; OPP = they draw fouls
    "foul": "OPP", "wall up": "OPP", "drawing fouls": "OPP",
    # Ball Movement: UWW = share
    "assist": "UWW", "ball movement": "UWW", "share the ball": "UWW",
    "playmaking": "UWW", "playmaker": "UWW", "create": "UWW",
    # Perimeter Defense / Ball Pressure: all OPP
    "steal": "OPP", "press capable": "OPP", "full court press": "OPP",
    "force turnovers": "OPP", "force to's": "OPP",
    "guard your yard": "OPP", "keep the ball in front": "OPP", "guard 1 on 1": "OPP",
    "early gap": "OPP", "help side": "OPP", "active hands": "OPP",
    "physical & aggressive on ball": "OPP", "on ball defensively": "OPP",
    "pressure": "OPP",
    # Paint Protection / Blocks: OPP
    "block": "OPP", "protect the rim": "OPP", "paint protection": "OPP",
    # Field Goal Efficiency: UWW = attack; OPP = limit
    "attack the paint": "UWW", "live in the paint": "UWW",
    "dominate the paint": "UWW", "attack the basket": "UWW",
    "scoring at the rim": "UWW", "get to rim": "UWW",
    "attack the rim": "UWW", "get to the rim": "UWW",
    "limit their scoring": "OPP",
    # Defensive Efficiency -- opponent set plays / actions / counters describe THEM, so OPP
    "set play": "OPP", "set plays": "OPP", "set piece": "OPP", "set pieces": "OPP",
    "counters": "OPP", "counter action": "OPP", "counter actions": "OPP",
    "wrinkle": "OPP", "wrinkles": "OPP", "playbook": "OPP",
    "play call": "OPP", "play calls": "OPP", "scripted": "OPP",
    "after timeout": "OPP", "out of bounds play": "OPP", "out of bounds plays": "OPP",
    "blob": "OPP", "slob": "OPP", "baseline out of bounds": "OPP", "sideline out of bounds": "OPP",
    "horns": "OPP", "stagger": "OPP", "staggered screen": "OPP",
    "pin down": "OPP", "pindown": "OPP", "down screen": "OPP", "back screen": "OPP",
    "flare screen": "OPP", "flex": "OPP", "ram screen": "OPP",
    "ball screen": "OPP", "ball screens": "OPP", "ball screen action": "OPP", "ball screen actions": "OPP",
    "pick and roll": "OPP", "pick-and-roll": "OPP", "pick and pop": "OPP", "pick-and-pop": "OPP",
    "dribble handoff": "OPP", "dho": "OPP", "motion offense": "OPP", "continuity": "OPP",
    "actions": "OPP", "action sets": "OPP",
    "create advantages": "OPP", "creating advantages": "OPP", "advantage creation": "OPP", "advantages": "OPP",
    # Defensive Efficiency -- opponent scoring-strength phrases describe THEM, so OPP
    "multiple scorers": "OPP", "multiple threats": "OPP", "multiple weapons": "OPP",
    "multiple options": "OPP", "scoring options": "OPP", "scoring threats": "OPP",
    "balanced scoring": "OPP", "scoring balance": "OPP", "scoring depth": "OPP",
    "several scorers": "OPP", "many scorers": "OPP", "deep scoring": "OPP",
    "double-digit scorers": "OPP", "double digit scorers": "OPP",
    "leading scorer": "OPP", "top scorer": "OPP", "primary scorer": "OPP",
    "go-to scorer": "OPP", "go to scorer": "OPP", "versatile scorers": "OPP",
    "score from anywhere": "OPP", "score at all three levels": "OPP",
    "three-level scorer": "OPP", "three level scorer": "OPP",
    "opponent strength": "OPP", "opponent strengths": "OPP",
    "their scorers": "OPP", "their weapons": "OPP",
    # General Defensive / Containment (OPP)
    "take away": "OPP", "funnel": "OPP", "deny": "OPP", "contain": "OPP",
    "limit": "OPP", "contest": "OPP", "make them": "OPP", "load up": "OPP",
    "transition defense": "OPP", "fight over": "OPP", "switch": "OPP",
    "trap": "OPP", "double team": "OPP", "coverage": "OPP",
    "don't help off": "OPP", "take away personnel": "OPP",
    # Offensive Efficiency -- mismatch/matchup hunting is something UWW does TO the opponent
    "mismatch": "UWW", "mismatches": "UWW", "attacking mismatches": "UWW",
    "attack mismatches": "UWW", "attack the mismatch": "UWW",
    "hunt mismatches": "UWW", "hunt the mismatch": "UWW",
    "exploit mismatches": "UWW", "exploit the mismatch": "UWW",
    "target mismatches": "UWW", "find the mismatch": "UWW",
    "size advantage": "UWW", "size mismatch": "UWW", "speed advantage": "UWW",
    "quickness advantage": "UWW", "switch hunting": "UWW", "hunt switches": "UWW",
    "hunt the switch": "UWW", "isolate": "UWW", "isolation": "UWW", "iso": "UWW",
    "post mismatch": "UWW", "favorable matchup": "UWW", "favorable matchups": "UWW",
    "best matchup": "UWW", "best matchups": "UWW",
    "exploit matchup": "UWW", "exploit matchups": "UWW",
    # Transition / Pace
    "transition defense": "OPP", "get back": "OPP", "getting back": "OPP", "sprint back": "OPP",
    "transition offense": "UWW", "push hard": "UWW", "pushing the pace": "UWW",
    "early offense": "UWW", "secondary break": "UWW", "run in transition": "UWW",
    # Paint defense -- what WE do to contain THEM
    "pack the paint": "OPP", "protect the paint": "OPP", "paint defense": "OPP",
    "build a wall": "OPP", "building a wall": "OPP", "wall around the paint": "OPP",
    "post defense": "OPP", "physical defense": "OPP", "strong gap": "OPP",
    "no easy paint": "OPP", "keep them out of the paint": "OPP",
    "contain": "OPP", "containing": "OPP", "squeeze": "OPP", "lock up": "OPP",
    # Opponent go-to scorer language
    "capable of carrying": "OPP", "carrying offense": "OPP", "carry the offense": "OPP",
    "main scorer": "OPP", "primary option": "OPP", "focal point": "OPP", "go-to guy": "OPP",
    "big scoring games": "OPP", "screening": "OPP", "switch all screens": "OPP",
    # Ours to execute
    "possession battle": "UWW", "turnover battle": "UWW", "rebound advantage": "UWW",
    "inside-out": "UWW", "inside out": "UWW", "post play": "UWW",
    "points in the paint": "UWW", "paint points": "UWW",
    "attacking the paint": "UWW", "attacking the rim": "UWW", "attacking the basket": "UWW",
    "attack matchups": "UWW", "attacking matchups": "UWW",
    # General Offensive / Proactive (UWW)
    "run the floor": "UWW", "push tempo": "UWW", "fast break": "UWW",
    "score in transition": "UWW", "finish": "UWW", "execute": "UWW",
    "dominate": "UWW", "impose": "UWW", "push the pace": "UWW",
}


def get_data_driven_ktv(short_opponent, played: pd.DataFrame):
    """Compute data-driven Keys to Victory: win/loss stat splits for the upcoming opponent's KTV categories.

    `played` is REQUIRED (games strictly before the upcoming game -- pre_upcoming/next_game_idx on the
    Upcoming Game page). It is a parameter rather than something loaded in here so this function cannot be
    called without a caller deciding what "before" means.

    CONFIRMED BUG (fixed here): this used to load uww_schedule itself and aggregate uww_pbp_box_score across
    EVERY opponent in the table, with no notion of a reference date -- two independent leaks of post-upcoming
    games into a pre-game win/loss split. The equivalent live code path (the per-category stat lines in the
    unified Keys to Victory section) was already fixed this way; this was its unscoped twin, left behind
    because nothing currently calls it. Both now go through scope_to_played() so they can't drift
    apart again.
    """
    ktv_games = load_table("uww_ktv_game_categories")
    box = load_table("uww_pbp_box_score")

    # Get categories assigned to this opponent
    opp_cats = ktv_games[ktv_games["opponent"] == short_opponent]["category"].unique()
    if len(opp_cats) == 0:
        return None

    # Build per-game UWW team totals from PBP box score -- restricted to games before the upcoming one.
    uww_box = scope_to_played(box[box["team"] == "UW-Whitewater"], played)
    if uww_box.empty:
        return None
    uww_per_game = uww_box.groupby(["opponent", "game_date"], as_index=False).agg({
        "PTS": "sum", "FGM": "sum", "FGA": "sum", "FG3M": "sum", "FG3A": "sum",
        "FTM": "sum", "FTA": "sum", "OREB": "sum", "DREB": "sum", "REB": "sum",
        "AST": "sum", "STL": "sum", "BLK": "sum", "TO": "sum", "PF": "sum"
    })
    uww_per_game["FG%"] = (uww_per_game["FGM"] / uww_per_game["FGA"] * 100).round(1)
    uww_per_game["3P%"] = (uww_per_game["FG3M"] / uww_per_game["FG3A"] * 100).round(1)
    uww_per_game["FT%"] = (uww_per_game["FTM"] / uww_per_game["FTA"] * 100).round(1)
    uww_per_game["FG2M"] = uww_per_game["FGM"] - uww_per_game["FG3M"]
    uww_per_game["FG2A"] = uww_per_game["FGA"] - uww_per_game["FG3A"]
    uww_per_game["FG2%"] = (uww_per_game["FG2M"] / uww_per_game["FG2A"] * 100).round(1)

    # Map outcomes from the pre-upcoming games only -- passing the full schedule here would readmit the
    # future results that the box-score scoping above just excluded.
    # Per-DATE outcome: two meetings with the same opponent can have opposite results.
    uww_per_game["outcome"] = uww_per_game["game_date"].astype(str).str[:10].map(get_game_outcomes(played))

    wins = uww_per_game[uww_per_game["outcome"] == "W"]
    losses = uww_per_game[uww_per_game["outcome"] == "L"]
    if wins.empty:
        return None

    # Map KTV categories to stat columns
    cat_stat_map = {
        "Ball Security": ["TO"],
        "Rebounding": ["REB", "OREB", "DREB"],
        "Three-Point Shooting": ["FG3M", "3P%"],
        "Free Throws": ["FTM", "FT%"],
        "Fouls / Discipline": ["PF"],
        "Ball Movement / Assists": ["AST"],
        "Paint Protection / Blocks": ["BLK"],
        "Perimeter Defense / Ball Pressure/ Create Turnovers": ["STL"],
        "Scoring Inside": ["FG2M", "FG2%"],
        "Field Goal Efficiency": ["FG%", "FGM"],
    }

    # Collect relevant stats from categories
    relevant_stats = []
    for cat in opp_cats:
        for s in cat_stat_map.get(cat, []):
            if s not in relevant_stats:
                relevant_stats.append(s)

    # Build comparison table
    stat_display = {
        "PTS": "Points", "FG%": "FG%", "3P%": "3P%", "FT%": "FT%",
        "REB": "Rebounds", "OREB": "Off. Reb.", "DREB": "Def. Reb.",
        "AST": "Assists", "TO": "Turnovers", "STL": "Steals",
        "BLK": "Blocks", "PF": "Fouls", "FGM": "FG Made", "FG3M": "3PT Made", "FTM": "FT Made",
    }
    # Stats where lower is better
    lower_better = {"TO", "PF"}

    results = []
    for stat in relevant_stats:
        w_avg = wins[stat].mean() if not wins.empty else None
        l_avg = losses[stat].mean() if not losses.empty else None
        if w_avg is None or pd.isna(w_avg):
            continue
        target = w_avg
        direction = "↓" if stat in lower_better else "↑"
        # Format
        is_pct = "%" in stat
        fmt = lambda v: f"{v:.1f}%" if is_pct else f"{v:.1f}"

        row = {"Stat": stat_display.get(stat, stat), "Win Avg": fmt(w_avg), "Target": f"{direction} {fmt(target)}"}
        if l_avg is not None and not pd.isna(l_avg):
            row["Loss Avg"] = fmt(l_avg)
        else:
            row["Loss Avg"] = "-"
        results.append(row)

    if not results:
        return None
    return pd.DataFrame(results), list(opp_cats), len(wins), len(losses)


def render_box_score_with_tooltips(df: pd.DataFrame, display_cols: list, tooltip_col: str = "projection_basis"):
    """Render a compact HTML table where every cell carries a native browser tooltip (the `title` attribute)
    with the full explanation of how that row's projection was derived. st.dataframe has no per-cell hover, so
    a small hand-rolled HTML table is the simplest way to get a real hover bubble on each player's projection."""
    if tooltip_col not in df.columns:
        st.dataframe(df[display_cols], hide_index=True, use_container_width=True)
        return
    header_html = "".join(
        f"<th style='text-align:left;padding:4px 10px;border-bottom:2px solid #ddd;font-size:0.85rem;'>"
        f"{html.escape(str(c))}</th>"
        for c in display_cols
    )
    body_rows = []
    for _, row in df.iterrows():
        tooltip = html.escape(str(row.get(tooltip_col, "")))
        cells = "".join(
            f"<td title=\"{tooltip}\" style='padding:4px 10px;border-bottom:1px solid #eee;cursor:help;font-size:0.85rem;'>"
            f"{html.escape('' if pd.isna(row[c]) else str(row[c]))}</td>"
            for c in display_cols
        )
        body_rows.append(f"<tr>{cells}</tr>")
    table_html = (
        "<table style='width:100%;border-collapse:collapse;'>"
        f"<thead><tr>{header_html}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    )
    st.markdown(table_html, unsafe_allow_html=True)
    st.caption("Hover any row to see how that projection was derived.")


# --------------------------------------------------------------------------------------------------------------
# Stat glossary + tooltip helpers (used by the new advanced-analytics sections below)
# --------------------------------------------------------------------------------------------------------------
# Every advanced/derived metric added to the app gets one entry here -- both so coaches can hover for a
# plain-language definition wherever the stat is shown (glossary_span on a column header, glossary_help_text
# on a section header), and so there is a SINGLE source of truth for each formula (rather than the definition
# living only as a scattered code comment).
STAT_GLOSSARY = {
    "eFG%": {
        "label": "Effective Field Goal %",
        "formula": "(FGM + 0.5 x 3PM) / FGA",
        "definition": "Field goal percentage adjusted to give 3-pointers the extra credit they deserve, since a "
                       "made 3 is worth 50% more than a made 2. A team can have a mediocre raw FG% but a strong "
                       "eFG% if a lot of those makes are from three.",
    },
    "TOV%": {
        "label": "Turnover Percentage",
        "formula": "TO / (FGA + 0.44 x FTA + TO)",
        "definition": "The share of a team's possessions that end in a turnover, rather than a shot or trip to "
                       "the line. Lower is better. Normalizing by possessions (not just raw turnover count) "
                       "makes this comparable between a fast team and a slow team.",
    },
    "ORB%": {
        "label": "Offensive Rebound %",
        "formula": "OREB / (OREB + Opponent DREB)",
        "definition": "Of all the rebounds available after a team's own missed shot, the percentage it actually "
                       "grabbed. Better than a raw rebound count because it accounts for how many rebounds were "
                       "actually up for grabs.",
    },
    "FT Rate": {
        "label": "Free Throw Rate",
        "formula": "FTA / FGA",
        "definition": "How often a team gets to the free-throw line relative to its field-goal attempts -- a "
                       "proxy for how aggressively it's attacking the basket (or how much it's fouling, on "
                       "defense).",
    },
    "Poss": {
        "label": "Possessions",
        "formula": "FGA - OREB + TO + 0.44 x FTA",
        "definition": "The standard estimate of how many possessions a team used, since possessions aren't "
                       "directly recorded in a normal box score. This is the denominator behind pace and "
                       "offensive/defensive rating.",
    },
    "Pace": {
        "label": "Pace",
        "formula": "Possessions / Games",
        "definition": "Estimated possessions per game -- how fast a team plays. A team can score a lot of points "
                       "just by playing fast, even if it isn't especially efficient per possession; pace lets "
                       "you tell those two things apart.",
    },
    "ORtg": {
        "label": "Offensive Rating",
        "formula": "Points Scored / Possessions x 100",
        "definition": "Points scored per 100 possessions. The standard way to measure offensive efficiency "
                       "independent of pace -- a slow team and a fast team can be compared fairly on this "
                       "number even though their raw PPG looks very different.",
    },
    "DRtg": {
        "label": "Defensive Rating",
        "formula": "Points Allowed / Possessions x 100",
        "definition": "Points allowed per 100 possessions -- the defensive mirror of Offensive Rating. Lower is "
                       "better.",
    },
    "Net Rtg": {
        "label": "Net Rating",
        "formula": "ORtg - DRtg",
        "definition": "The point-differential-per-100-possessions summary of a team's overall performance -- "
                       "positive means the team outscores opponents on a per-possession basis.",
    },
    "TS%": {
        "label": "True Shooting %",
        "formula": "PTS / (2 x (FGA + 0.44 x FTA))",
        "definition": "Shooting efficiency across ALL scoring (2s, 3s, and free throws) in one number, instead "
                       "of three separate percentages. The best single number for \"how efficiently does this "
                       "player score.\"",
    },
    "Game Score": {
        "label": "Game Score",
        "formula": "PTS + 0.4xFGM - 0.7xFGA - 0.4x(FTA-FTM) + 0.7xORB + 0.3xDRB + STL + 0.7xAST + 0.7xBLK - 0.4xPF - TO",
        "definition": "John Hollinger's single-number summary of a box score line -- a quick way to rank \"who "
                       "had the best game\" that credits efficient scoring and all-around production, not just "
                       "point totals. A Game Score around 10 is a solid game; 20+ is an excellent one; 40+ is "
                       "historic.",
    },
    "Usage%": {
        "label": "Usage Rate",
        "formula": "100 x ((FGA + 0.44xFTA + TO) x (Team MIN/5)) / (MIN x (Team FGA + 0.44xTeam FTA + Team TO))",
        "definition": "The percentage of a team's plays a player used (by shooting, getting to the line, or "
                       "turning it over) while on the floor. High usage isn't automatically good or bad -- it "
                       "just tells you who the offense runs through.",
    },
}


def glossary_span(key: str, display_text: str = None) -> str:
    """Return an HTML span with a native browser hover tooltip (the `title` attribute) explaining a stat from
    STAT_GLOSSARY. Use for compact table/column headers where a stat name has to stay short -- pairs with
    glossary_help_text() below, which explains a whole section's stats on its header icon."""
    entry = STAT_GLOSSARY.get(key)
    text = display_text if display_text is not None else key
    if not entry:
        return html.escape(text)
    tooltip = html.escape(f"{entry['label']}: {entry['definition']} Formula: {entry['formula']}")
    return f'<span title="{tooltip}" style="cursor:help;border-bottom:1px dotted #999;">{html.escape(text)}</span>'


def glossary_help_text(keys: list) -> str:
    """Definitions for a list of STAT_GLOSSARY stats as one block of plain text, for a hover tooltip.

    Replaces render_glossary_popover(), which put a "What do these mean?" BUTTON in its own row under every
    section header. Pass the result to section_header() instead -- the explanation costs no layout and needs
    no click.
    """
    parts = []
    for key in keys:
        entry = STAT_GLOSSARY.get(key)
        if entry:
            parts.append(f"{entry['label']} ({key}) = {entry['formula']}\n{entry['definition']}")
    return "\n\n".join(parts)


def section_header(title: str, help_text: str = None, margin: str = "1.5rem 0 0.75rem") -> None:
    """The app's standard bordered section header, with the section's explanation on a hover icon.

    Every explanation on these pages used to be an st.popover button sitting in its own row beneath the
    header: a full row of vertical space, plus a click, for text that is only ever context. The icon carries
    it instead.

    Uses a native `title` tooltip rather than a CSS one on purpose -- these headers sit inside bordered
    containers, and a CSS-positioned tooltip can be clipped by an ancestor's overflow, while a native tooltip
    is drawn by the browser and never is. Same mechanism as glossary_span().
    """
    icon = ""
    if help_text:
        # A LITERAL newline in this attribute breaks the whole header. st.markdown runs the string through a
        # Markdown renderer before the HTML reaches the browser, and a blank line ends a raw-HTML block --
        # so the tag is cut in half and everything after the break renders as visible text, attribute markup
        # and all. Encode the line breaks as &#10; instead: the browser still shows them as line breaks in
        # the tooltip, but there is no newline character for Markdown to trip over. Escape FIRST, so
        # html.escape() can't turn the entity's own "&" into "&amp;".
        _tip = html.escape(help_text).replace("\r\n", "\n").replace("\n", "&#10;")
        icon = (f'<span title="{_tip}" style="cursor:help;font-size:0.85rem;margin-left:8px;'
                f'opacity:0.65;font-weight:400;vertical-align:middle;">\u2139\ufe0f</span>')
    st.markdown(
        f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:{margin};">'
        f'<div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">{title}{icon}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------------------------------------------
# Advanced-analytics computation helpers
# --------------------------------------------------------------------------------------------------------------
# All of these operate on uww_pbp_box_score (columns confirmed against the parser: opponent, game_date, team,
# player, PTS, FGM, FGA, FG3M, FG3A, FTM, FTA, OREB, DREB, REB, AST, STL, BLK, TO, PF, FG%, 3P%, FT%, started)
# and/or uww_pbp_events -- no new data collection needed for any of these.

def estimate_possessions(fga, oreb, to, fta) -> float:
    """Standard possession estimate (there's no possession count in a normal box score, so this is the widely
    used approximation): a possession ends on a made shot, a defensive rebound, a turnover, or the last free
    throw of a trip -- 0.44 approximates "how often a FTA trip is the LAST FTA of its trip" without needing to
    know FT trip boundaries directly."""
    return fga - oreb + to + 0.44 * fta


# Dean Oliver's own weighting of the Four Factors -- shooting matters most, free throws least. Used to turn
# four separate gaps into one answer: which factor is most likely to decide THIS game.
FOUR_FACTOR_WEIGHTS = {"eFG%": 0.40, "TOV%": 0.25, "ORB%": 0.20, "FT Rate": 0.15}
# Higher is better for three of them; TOV% is the exception (a turnover is a lost possession).
FOUR_FACTOR_HIGHER_IS_BETTER = {"eFG%": True, "TOV%": False, "ORB%": True, "FT Rate": True}


@st.cache_data(ttl=60)
def adjusted_efficiency() -> dict:
    """Opponent-adjusted offensive and defensive efficiency, KenPom's method applied to what this app has.

    The idea is his: a rating is only meaningful relative to who you played, so each game's raw efficiency
    is shifted by how good that opponent is, then everyone's ratings are recomputed from the shifted
    numbers and the whole thing is iterated until it settles.

    Two honest departures from the real thing, both forced by the data available here:
      * The league graph is only UWW's own games plus each opponent's season point totals -- there is no
        full schedule of every team against every other, so opponent strength starts from their own
        points scored/allowed per game rather than from a converged rating.
      * Opponent per-game points are converted to per-100 using the average pace of UWW's games, because
        no possession estimate exists for games UWW didn't play in.
    So treat the adjustment as a correction for schedule strength, not as a KenPom rating. Raw numbers are
    returned alongside and shown next to it everywhere, precisely so the adjustment can be second-guessed.
    """
    box = load_table("uww_pbp_box_score")
    if box.empty or "team" not in box.columns:
        return {}
    uww = box[box["team"] == "UW-Whitewater"]
    opp = box[box["team"] != "UW-Whitewater"]
    if uww.empty or opp.empty:
        return {}
    keys = [c for c in ["opponent", "game_date"] if c in box.columns]
    if not keys:
        return {}

    games = []
    for key, u in uww.groupby(keys, dropna=False):
        mask = pd.Series(True, index=opp.index)
        for col, val in zip(keys, (key if isinstance(key, tuple) else (key,))):
            mask &= (opp[col] == val)
        o = opp[mask]
        if o.empty:
            continue
        d = compute_efficiency_pace(u, o, 1)
        games.append({"opponent": (key[0] if isinstance(key, tuple) else key),
                      "ortg": d["ORtg"], "drtg": d["DRtg"], "pace": d["Pace"]})
    gdf = pd.DataFrame(games)
    if gdf.empty or gdf["pace"].mean() <= 0:
        return {}
    pace = gdf["pace"].mean()

    # Seed every opponent from their own season scoring, converted to per-100 at UWW's average pace.
    totals = load_table("uww_opponent_team_totals")
    seed_off, seed_def = {}, {}
    if not totals.empty and "opponent" in totals.columns:
        for _, r in totals.iterrows():
            ppg, allowed = safe_float(r.get("team_ppg")), safe_float(r.get("opp_ppg_allowed"))
            if ppg is not None and 0 < ppg < 200:
                seed_off[str(r["opponent"])] = 100 * ppg / pace
            if allowed is not None and 0 < allowed < 200:
                seed_def[str(r["opponent"])] = 100 * allowed / pace
    league_off = (sum(seed_off.values()) / len(seed_off)) if seed_off else gdf["ortg"].mean()
    league_def = (sum(seed_def.values()) / len(seed_def)) if seed_def else gdf["drtg"].mean()

    short_names = sorted(set(seed_off) | set(seed_def), key=len, reverse=True)
    gdf["short"] = gdf["opponent"].apply(lambda o: resolve_short_opponent(o, short_names) or str(o))
    off_adj = dict(seed_off)
    def_adj = dict(seed_def)
    uww_off = gdf["ortg"].mean()
    uww_def = gdf["drtg"].mean()
    for _ in range(12):
        # UWW's own rating: each game shifted by how far that opponent's defense (offense) sits from average.
        uww_off = float((gdf["ortg"] + (league_def - gdf["short"].map(def_adj).fillna(league_def))).mean())
        uww_def = float((gdf["drtg"] - (gdf["short"].map(off_adj).fillna(league_off) - league_off)).mean())
        # Then each opponent, shifted by UWW's own strength in the one game they share with us.
        for _, g in gdf.iterrows():
            nm = g["short"]
            if nm in def_adj:
                def_adj[nm] = 0.5 * def_adj[nm] + 0.5 * (g["ortg"] + (uww_off - league_off) * -1 + (league_def - def_adj[nm]) * 0)
            if nm in off_adj:
                off_adj[nm] = 0.5 * off_adj[nm] + 0.5 * (g["drtg"] - (uww_def - league_def))
    return {
        "pace": pace, "league_off": league_off, "league_def": league_def,
        "uww": {"raw_off": float(gdf["ortg"].mean()), "raw_def": float(gdf["drtg"].mean()),
                "adj_off": uww_off, "adj_def": uww_def},
        "opponents_adj_off": off_adj, "opponents_adj_def": def_adj,
        "opponents_raw_off": seed_off, "opponents_raw_def": seed_def,
        "games": len(gdf),
    }


# Points of home-court advantage. ~3 is the long-standing college basketball figure; it is applied to the
# margin (split half to each side) only when the schedule says where the game is played.
HOME_COURT_POINTS = 3.0
# Standard deviation of a single game's margin around its projection. ~11 points is the usual college
# figure and is what turns a projected margin into an honest win probability and a range instead of a
# single number pretending to be exact.
GAME_MARGIN_SD = 11.0


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@st.cache_data(ttl=60)
def project_game(short_opponent: str, location: str = None) -> dict:
    """Projected score built the tempo-free way: efficiency x possessions, not points per game.

    The old projection blended UWW's own scoring average with their season average and scaled the
    opponent's PPG by a "scoring tier" ratio. Two problems with that: UWW's projected points never looked
    at the opponent's DEFENSE at all, and points per game bakes in pace, so a slow team that scores 68 on
    62 possessions was treated as a weaker offense than a fast team scoring 72 on 78.

    This does what a possession-based model does:
      * expected pace  = (UWW pace x opponent pace) / league pace -- two slow teams play a slow game
      * expected ORtg  = our adjusted offense shifted by how far their adjusted defense sits from average
      * points         = ORtg x possessions / 100, with home court applied to the margin
      * win probability = the normal CDF of that margin over a one-game standard deviation

    Returns {} when the inputs aren't there rather than inventing a number.
    """
    core = adjusted_efficiency()
    if not core or not short_opponent:
        return {}
    opp_off = core["opponents_adj_off"].get(short_opponent)
    opp_def = core["opponents_adj_def"].get(short_opponent)
    if opp_off is None or opp_def is None:
        return {}
    lg_off, lg_def, pace = core["league_off"], core["league_def"], core["pace"]
    u = core["uww"]

    # Opponent pace: their own games if reconstructed box scores exist, else assume league pace.
    opp_pace, opp_pace_known = pace, False
    prior = load_table("uww_opponent_prior_games_box_score")
    if not prior.empty and "team" in prior.columns:
        keys = [c for c in ["opponent", "game_date"] if c in prior.columns]
        paces = []
        for key, g in prior.groupby(keys, dropna=False):
            them = g[g["team"] == short_opponent]
            foes = g[g["team"] != short_opponent]
            if them.empty or foes.empty:
                continue
            paces.append(compute_efficiency_pace(them, foes, 1)["Pace"])
        if paces:
            opp_pace, opp_pace_known = float(sum(paces) / len(paces)), True

    # Expected tempo: the harmonic mean of the two teams' paces -- the "meet in the middle" estimate, and
    # the closest honest stand-in for the (team x team / league) form, which needs a real league average
    # pace this app has no way to compute.
    exp_poss = (2 * pace * opp_pace) / (pace + opp_pace) if (pace + opp_pace) > 0 else 0
    uww_ortg = u["adj_off"] + (opp_def - lg_def)
    opp_ortg = opp_off + (u["adj_def"] - lg_def)
    uww_pts = uww_ortg * exp_poss / 100
    opp_pts = opp_ortg * exp_poss / 100

    hca = 0.0
    if location:
        _loc = str(location).strip().lower()
        if _loc.startswith("home"):
            hca = HOME_COURT_POINTS
        elif _loc.startswith("away") or _loc.startswith("at"):
            hca = -HOME_COURT_POINTS
    uww_pts += hca / 2
    opp_pts -= hca / 2
    margin = uww_pts - opp_pts
    return {
        "uww_pts": uww_pts, "opp_pts": opp_pts, "margin": margin,
        "win_prob": _normal_cdf(margin / GAME_MARGIN_SD),
        "possessions": exp_poss, "uww_ortg": uww_ortg, "opp_ortg": opp_ortg,
        "uww_pace": pace, "opp_pace": opp_pace, "opp_pace_known": opp_pace_known,
        "hca": hca, "sd": GAME_MARGIN_SD,
        "core": core,
    }


@st.cache_data(ttl=60)
def project_uww_box(short_opponent: str, team_points: float, possessions: float) -> pd.DataFrame:
    """Per-player projection driven by MINUTES and PER-MINUTE RATES, then reconciled to the team total.

    The previous version took each player's season per-game averages and multiplied every one of them by a
    single scalar so the points column added up to the projected team total. That silently assumed the
    rotation never changes, and it left rebounds and assists unscaled, so those columns summed to whatever
    they summed to regardless of the projected pace.

    Here: minutes come from the last five games (what the rotation looks like NOW, not in November),
    normalised to the 200 a team plays; every stat is a per-minute rate times those minutes; and each stat
    column is reconciled to its own projected team total, so points, rebounds and assists are all
    internally consistent with the projected tempo.
    """
    box = load_table("uww_pbp_box_score")
    if box.empty:
        return pd.DataFrame()
    uww = box[box["team"] == "UW-Whitewater"].copy()
    if uww.empty or "player" not in uww.columns:
        return pd.DataFrame()
    for c in ["MIN", "PTS", "REB", "AST", "STL", "BLK", "TO", "FGA", "FGM", "FG3A", "FG3M", "FTA", "FTM"]:
        if c in uww.columns:
            uww[c] = pd.to_numeric(uww[c], errors="coerce")
    if "MIN" not in uww.columns or uww["MIN"].fillna(0).sum() <= 0:
        return pd.DataFrame()

    # Recent-form window: the last five games this app can see, by date when there is one.
    if "game_date" in uww.columns:
        recent_dates = sorted(uww["game_date"].dropna().unique())[-5:]
        recent = uww[uww["game_date"].isin(recent_dates)] if recent_dates else uww
    else:
        recent = uww
    stats = [c for c in ["PTS", "REB", "AST", "STL", "BLK", "TO", "FGA", "FGM", "FG3A", "FG3M", "FTA", "FTM"]
             if c in uww.columns]
    season = uww.groupby("player")[["MIN"] + stats].sum().reset_index()
    recent_min = recent.groupby("player")["MIN"].sum()
    n_recent = recent["game_date"].nunique() if "game_date" in recent.columns else 1

    season = season[season["MIN"] > 0].copy()
    if season.empty:
        return pd.DataFrame()
    for c in stats:
        season[f"_rate_{c}"] = season[c] / season["MIN"]
    # Projected minutes: recent per-game minutes, normalised so the five spots add to 200.
    season["proj_min"] = season["player"].map(recent_min).fillna(0) / max(n_recent, 1)
    if season["proj_min"].sum() <= 0:
        season["proj_min"] = season["MIN"] / max(uww["game_date"].nunique() if "game_date" in uww.columns else 1, 1)
    season["proj_min"] = 200 * season["proj_min"] / season["proj_min"].sum()

    out = pd.DataFrame({"player": season["player"], "MIN": season["proj_min"].round(1)})
    for c in stats:
        out[c] = season[f"_rate_{c}"] * season["proj_min"]

    # Reconcile: points to the projected team total, everything else to the season rate re-paced to this
    # game's projected possessions -- so a slow projected game lowers rebounds and assists too.
    n_games = uww["game_date"].nunique() if "game_date" in uww.columns else max(len(uww) // 10, 1)
    if out["PTS"].sum() > 0 and team_points:
        out["PTS"] *= team_points / out["PTS"].sum()
    _season_poss = estimate_possessions(
        uww["FGA"].sum() if "FGA" in uww.columns else 0,
        uww["OREB"].sum() if "OREB" in uww.columns else 0,
        uww["TO"].sum() if "TO" in uww.columns else 0,
        uww["FTA"].sum() if "FTA" in uww.columns else 0,
    ) / max(n_games, 1)
    pace_factor = (possessions / _season_poss) if _season_poss and possessions else 1.0
    for c in [x for x in stats if x != "PTS"]:
        target = (uww[c].sum() / max(n_games, 1)) * pace_factor
        if out[c].sum() > 0 and target > 0:
            out[c] *= target / out[c].sum()
    out = out[out["MIN"] >= 1].sort_values("PTS", ascending=False).reset_index(drop=True)
    for c in out.columns:
        if c != "player":
            out[c] = out[c].round(1)
    return out


def compute_four_factors(team_box: pd.DataFrame, opp_box: pd.DataFrame) -> dict:
    """Dean Oliver's "Four Factors" (eFG%, TOV%, ORB%, FT Rate) for `team_box`'s side of a game or set of
    games. `opp_box` (the other side's box-score rows over the same games) is needed for ORB%, since it
    requires the opponent's defensive rebounds as the denominator. Pass season-wide slices for season figures,
    or a single game's rows for a per-game breakdown."""
    fgm = team_box["FGM"].sum() if "FGM" in team_box.columns else 0
    fga = team_box["FGA"].sum() if "FGA" in team_box.columns else 0
    fg3m = team_box["FG3M"].sum() if "FG3M" in team_box.columns else 0
    to = team_box["TO"].sum() if "TO" in team_box.columns else 0
    fta = team_box["FTA"].sum() if "FTA" in team_box.columns else 0
    oreb = team_box["OREB"].sum() if "OREB" in team_box.columns else 0
    opp_dreb = opp_box["DREB"].sum() if "DREB" in opp_box.columns else 0
    poss = estimate_possessions(fga, oreb, to, fta)
    return {
        "eFG%": ((fgm + 0.5 * fg3m) / fga * 100) if fga > 0 else 0,
        "TOV%": (to / poss * 100) if poss > 0 else 0,
        "ORB%": (oreb / (oreb + opp_dreb) * 100) if (oreb + opp_dreb) > 0 else 0,
        "FT Rate": (fta / fga * 100) if fga > 0 else 0,
    }


def compute_efficiency_pace(team_box: pd.DataFrame, opp_box: pd.DataFrame, n_games: int) -> dict:
    """Offensive/Defensive Rating (points per 100 possessions) and Pace (possessions per game) for `team_box`'s
    side over `n_games` games, using `opp_box` for the opponent's own possession estimate (averaging both
    sides' estimates is the standard practice, since either alone is a noisy approximation)."""
    if n_games <= 0:
        return {"Pace": 0, "ORtg": 0, "DRtg": 0, "Net Rtg": 0}
    team_poss = estimate_possessions(
        team_box["FGA"].sum() if "FGA" in team_box.columns else 0,
        team_box["OREB"].sum() if "OREB" in team_box.columns else 0,
        team_box["TO"].sum() if "TO" in team_box.columns else 0,
        team_box["FTA"].sum() if "FTA" in team_box.columns else 0,
    )
    opp_poss = estimate_possessions(
        opp_box["FGA"].sum() if "FGA" in opp_box.columns else 0,
        opp_box["OREB"].sum() if "OREB" in opp_box.columns else 0,
        opp_box["TO"].sum() if "TO" in opp_box.columns else 0,
        opp_box["FTA"].sum() if "FTA" in opp_box.columns else 0,
    )
    avg_poss = (team_poss + opp_poss) / 2 if (team_poss > 0 or opp_poss > 0) else 0
    team_pts = team_box["PTS"].sum() if "PTS" in team_box.columns else 0
    opp_pts = opp_box["PTS"].sum() if "PTS" in opp_box.columns else 0
    ortg = (team_pts / avg_poss * 100) if avg_poss > 0 else 0
    drtg = (opp_pts / avg_poss * 100) if avg_poss > 0 else 0
    return {
        "Pace": avg_poss / n_games,
        "ORtg": ortg,
        "DRtg": drtg,
        "Net Rtg": ortg - drtg,
    }


def compute_uww_pace_by_game(as_of_date=None, exclusive=False):
    """Every UWW game's Pace/Net Rtg/ORtg/result, one row per game, bucketed 'fast'/'slow' against UWW's own
    season median pace (needs 4+ qualifying games; returns (None, None) below that). Factored out of the
    Pace & Style KTV card so that card and the per-game Pace indicator on the Previous Games page use the
    exact same games and the exact same definition of "fast" and "slow" for UWW, rather than two separate
    computations that could quietly drift apart.

    as_of_date: if given, restricts which games count toward the median -- used by the Previous Games page
    so a past game's fast/slow read reflects only what UWW's season looked like around that game, not games
    that hadn't been played yet. Leave as None (default) for the full-season view the Pace & Style KTV card
    wants when deciding how to approach an UPCOMING opponent, where every game played so far is fair game.
    exclusive: when True, only games STRICTLY BEFORE as_of_date count (an "entering this game" read); when
    False (default), games ON as_of_date count too (a "through this game, inclusive" read)."""
    box = load_table("uww_pbp_box_score")
    uww_side = box[box["team"] == "UW-Whitewater"] if not box.empty else pd.DataFrame()
    opp_side = box[box["team"] != "UW-Whitewater"] if not box.empty else pd.DataFrame()
    keys = [c for c in ["opponent", "game_date"] if c in uww_side.columns]
    if not keys:
        return None, None
    rows = []
    for k, u in uww_side.groupby(keys, dropna=False):
        key_vals = k if isinstance(k, tuple) else (k,)
        mask = pd.Series(True, index=opp_side.index)
        for c, v in zip(keys, key_vals):
            mask &= (opp_side[c] == v)
        o = opp_side[mask]
        if o.empty:
            continue
        d = compute_efficiency_pace(u, o, 1)
        rows.append({
            **dict(zip(keys, key_vals)),
            "pace": d["Pace"], "net": d["Net Rtg"], "ortg": d["ORtg"],
            "won": (u["PTS"].sum() > o["PTS"].sum()) if "PTS" in u.columns else None,
        })
    df = pd.DataFrame(rows)
    if as_of_date is not None and "game_date" in df.columns:
        _dates = pd.to_datetime(df["game_date"], errors="coerce")
        _cutoff = pd.to_datetime(as_of_date)
        df = df[_dates < _cutoff] if exclusive else df[_dates <= _cutoff]
    if len(df) < 4:
        return None, None
    median = df["pace"].median()
    df["_bucket"] = df["pace"].apply(lambda v: "fast" if v > median else "slow")
    return df, median


def compute_uww_run_rates(as_of_date=None, exclusive=False):
    """UWW's own share of games with a "big" run (10-0 or better, points_for and points_against) from
    uww_scoring_runs -- the same bar the Runs We Go On / Runs Against Us KTV cards already use, so a rate
    quoted here means the same thing as a rate quoted there.

    as_of_date/exclusive: same meaning as compute_uww_pace_by_game() -- restricts which games count, so the
    Previous Games page can describe UWW's run tendency ENTERING a specific past game rather than over the
    whole season. Returns (off_rate, def_rate, n); both rates are None when n == 0."""
    runs = load_table("uww_scoring_runs")
    if runs.empty or not {"uww_biggest_run", "opponent_biggest_run"} <= set(runs.columns):
        return None, None, 0
    r = runs.copy()
    for c in ("uww_biggest_run", "opponent_biggest_run"):
        r[c] = pd.to_numeric(r[c], errors="coerce")
    if as_of_date is not None and "game_date" in r.columns:
        _dates = pd.to_datetime(r["game_date"], errors="coerce")
        _cutoff = pd.to_datetime(as_of_date)
        r = r[_dates < _cutoff] if exclusive else r[_dates <= _cutoff]
    n = len(r)
    if n == 0:
        return None, None, 0
    return (r["uww_biggest_run"] >= 10).sum() / n, (r["opponent_biggest_run"] >= 10).sum() / n, n


def compute_true_shooting(pts, fga, fta) -> float:
    """True Shooting % -- see STAT_GLOSSARY['TS%']. Returns 0 if there were no shooting attempts of any kind."""
    denom = 2 * (fga + 0.44 * fta)
    return (pts / denom * 100) if denom > 0 else 0


def detect_biggest_runs_by_game(pbp_df: pd.DataFrame) -> pd.DataFrame:
    """Each game's biggest scoring run for each team that scored in it, from a PBP events table.

    Deliberately mirrors parser_nb.ipynb's own run-detection cell ("Scoring runs and largest lead/deficit per
    game") event-for-event -- same event types (made_shot/free_throw_made), same point value per event, same
    "consecutive scoring by one team with no answer" definition of a run, same grouping by (opponent,
    game_date) via event_order sequence -- so a run counted here means the same thing as a run in the
    already-exported uww_scoring_runs table. uww_scoring_runs only covers UWW's OWN games, though, so this
    exists to compute the same thing for uww_opponent_prior_games_pbp (the upcoming opponent's own prior
    games), which has no precomputed run table of its own. Returns columns: opponent, game_date, team,
    run_points -- one row per team that scored in a given game, with THEIR biggest run for it (a team with no
    run at all, i.e. never got to score, has no row).
    """
    _req_cols = {"event_type", "shot_type", "team", "event_order", "opponent", "game_date"}
    if pbp_df.empty or not _req_cols <= set(pbp_df.columns):
        return pd.DataFrame(columns=["opponent", "game_date", "team", "run_points"])
    scoring = pbp_df[pbp_df["event_type"].isin(["made_shot", "free_throw_made"])].copy()
    if scoring.empty:
        return pd.DataFrame(columns=["opponent", "game_date", "team", "run_points"])

    def _points(row):
        if row["event_type"] != "made_shot":
            return 1
        try:
            return int(row["shot_type"])
        except (TypeError, ValueError):
            return 2  # unparseable shot_type -- treat as a 2 rather than drop the event entirely

    scoring["points"] = scoring.apply(_points, axis=1)
    rows = []
    for (opp, gdate), group in scoring.groupby(["opponent", "game_date"], dropna=False):
        cur_team, cur_pts = None, 0
        runs = []
        for _, row in group.sort_values("event_order").iterrows():
            if row["team"] == cur_team:
                cur_pts += row["points"]
            else:
                if cur_team is not None:
                    runs.append({"team": cur_team, "run_points": cur_pts})
                cur_team, cur_pts = row["team"], row["points"]
        if cur_team is not None:
            runs.append({"team": cur_team, "run_points": cur_pts})
        if not runs:
            continue
        for team, pts in pd.DataFrame(runs).groupby("team")["run_points"].max().items():
            rows.append({"opponent": opp, "game_date": gdate, "team": team, "run_points": pts})
    return pd.DataFrame(rows)


def compute_game_score(row: pd.Series) -> float:
    """John Hollinger's Game Score for one box-score row -- see STAT_GLOSSARY['Game Score']. Missing columns
    are treated as 0 rather than raising, since some tables (e.g. season-stats exports) may not carry every
    field this formula wants."""
    g = lambda c: row[c] if c in row.index and pd.notna(row[c]) else 0
    return (
        g("PTS") + 0.4 * g("FGM") - 0.7 * g("FGA") - 0.4 * (g("FTA") - g("FTM"))
        + 0.7 * g("OREB") + 0.3 * g("DREB") + g("STL") + 0.7 * g("AST") + 0.7 * g("BLK")
        - 0.4 * g("PF") - g("TO")
    )


def compute_usage_rate(player_row: pd.Series, player_minutes: float, team_box: pd.DataFrame, team_minutes_total: float) -> float:
    """Usage Rate -- see STAT_GLOSSARY['Usage%']. `team_box` should be the player's own team's box-score rows
    over the same set of games used for `player_row`'s totals. Returns 0 if minutes are missing/zero (can't
    estimate usage for a player with no recorded minutes).

    NOTE: the standard Usage% formula's denominator is "team plays" = Tm FGA + 0.44 x Tm FTA + Tm TOV -- NOT
    the same "possessions" estimate used elsewhere for pace/ratings (which also subtracts OREB, since an
    offensive rebound extends the same possession rather than ending it). Using the OREB-subtracted version
    here would inflate every player's Usage% by roughly however much OREB shrinks the team's own FGA total --
    typically a 15-25% distortion. So this passes oreb=0 into estimate_possessions on purpose, for both the
    player and team side, to get the correct "plays" denominator instead of true "possessions".
    """
    if player_minutes <= 0 or team_minutes_total <= 0:
        return 0
    player_poss_used = estimate_possessions(
        player_row.get("FGA", 0) or 0, 0, player_row.get("TO", 0) or 0, player_row.get("FTA", 0) or 0
    )
    team_poss = estimate_possessions(
        team_box["FGA"].sum() if "FGA" in team_box.columns else 0,
        0,
        team_box["TO"].sum() if "TO" in team_box.columns else 0,
        team_box["FTA"].sum() if "FTA" in team_box.columns else 0,
    )
    if team_poss <= 0:
        return 0
    return 100 * (player_poss_used * (team_minutes_total / 5)) / (player_minutes * team_poss)


# The tagger's own vocabulary doesn't name every shot; these two labels mark where it runs out. Kept as
# named constants so the "best shot type" logic can recognise a residual bucket instead of presenting it as
# a real shot type.
UNCLASSIFIED_SHOT_MECHANIC = "Unclassified (no mechanic tag)"
NO_CONTEST_TAG = "Not tagged (contest recorded only on catch-and-shoot)"


def extract_shot_mechanic(description) -> str:
    """Which kind of shot this was, from the video tagger's own chained description.

    The first three tests are the tagger's SHOT MECHANIC vocabulary. Everything else used to fall through to
    a bucket called "Other" -- which was 19% of all tagged shots and, at 58.9%, the most efficient bucket on
    the board, so it kept winning "best shot type" while telling a coach nothing. Reading the raw tags, it was
    cuts to the rim, putbacks off the offensive glass, and post-ups.

    Those three are tested AFTER the mechanic tests, not before: they describe how a shot was CREATED rather
    than how it was released, and a post-up that finishes as a jumper should still count as a jumper. Checked
    against real tagged data -- "Cut" and "Offensive Rebound" appear in zero already-classified shots, and
    "Post-Up" in 169, all of which keep their existing (more specific) label under this ordering. Adding the
    tier shrinks the residual from 586 shots to 14.
    """
    if pd.isna(description):
        return None
    d = str(description)
    if "No Dribble Jumper" in d:
        return "Catch-and-shoot"
    if "Dribble Jumper" in d:
        return "Pull-up off the dribble"
    if "To Basket" in d:
        return "Drive to the basket"
    # --- fallback tier: shot ORIGIN, for tags carrying no mechanic keyword at all ---
    if "Offensive Rebound" in d:
        return "Putback off the offensive glass"
    if "Cut" in d:
        return "Cut to the basket"
    if "Post-Up" in d:
        return "Post-up"
    return UNCLASSIFIED_SHOT_MECHANIC


def extract_contest(description) -> str:
    """Defender contest, which the tagger records ONLY on catch-and-shoot jumpers.

    Verified across 3,039 tagged shots: every one of the 1,069 catch-and-shoot attempts carries Guarded or
    Open, and not one of the other 1,970 does. So a missing contest tag does not mean the shot was a drive --
    the previous label said "(drive, no contest tag)", which mislabelled every cut, putback and post-up as a
    drive. It means the contest dimension simply does not apply to this shot type.
    """
    if pd.isna(description):
        return None
    d = str(description)
    if "Guarded" in d:
        return "Guarded"
    if "Open" in d:
        return "Open"
    return NO_CONTEST_TAG


def describe_shot_look(mechanic, contest=None) -> str:
    """Plain-language name for a shot type, for use inside a sentence.

    The mechanic and the contest tag used to be pasted together with a comma, which produced
    "Putback off the offensive glass, Not tagged (contest recorded only on catch-and-shoot)" -- a caveat
    about the TAGGING system presented as if it were part of the shot's description. The contest dimension
    only exists for catch-and-shoot jumpers (see extract_contest), so for every other shot type the honest
    rendering is simply to say nothing about it.
    """
    if mechanic is None or (isinstance(mechanic, float) and mechanic != mechanic):
        return "untagged shots"
    _m = str(mechanic)
    if _m == UNCLASSIFIED_SHOT_MECHANIC:
        _m = "shots with no mechanic tag"
    if contest in ("Guarded", "Open"):
        return f"{_m} ({str(contest).lower()})"
    return _m


def extract_distance(description) -> str:
    """Parse the shot-distance tag out of a video_description string (see parser cell 114)."""
    if pd.isna(description):
        return None
    d = str(description)
    for tag in ["Long/3pt", "Medium/17' to <3p", "Short to < 17'"]:
        if tag in d:
            return tag
    return "N/A"


def extract_play_type(description, player) -> str:
    """Parse the play-type tag (the action segment right after the shooter's own name-token) out of a
    video_description string -- same approach as the parser's extract_play_type (cell 112), simplified to a
    direct case-insensitive match against the row's own `player` value rather than a full roster-name
    normalizer, since the app already has the canonical player name for that row."""
    if pd.isna(description) or pd.isna(player):
        return None
    segments = [s.strip() for s in str(description).split(">")]
    player_lower = str(player).strip().lower()
    last_player_idx = None
    for idx, seg in enumerate(segments):
        m = re.match(r"^\d+\s+(.+)$", seg)
        if m and m.group(1).strip().lower() == player_lower:
            last_player_idx = idx
    if last_player_idx is not None and last_player_idx + 1 < len(segments):
        return segments[last_player_idx + 1]
    return segments[1] if len(segments) > 1 else None


def extract_offensive_play_call(note) -> str:
    """Best-effort extraction of a named play/set call from an OFFENSIVE coach note, e.g. "PANTHER EXECUTION,
    BIG = WALK YOUR MAN UP" -> "PANTHER", "TWINS SWIRL EXECUTION = +CUT..." -> "TWINS SWIRL". Looks for a
    short, mostly-uppercase leading phrase immediately before the word "EXECUTION" -- the one consistent
    signal across this team's own notation. A note that doesn't follow that exact convention returns None
    rather than guessing at a name -- a wrong guess would be worse than that note simply not appearing in
    the play-call breakdown (it's still visible, verbatim, in the raw notes browser)."""
    if pd.isna(note):
        return None
    m = re.match(r"^([A-Z][A-Z0-9\-&' ]{1,24}?)\s+EXECUTION\b", str(note).strip())
    return m.group(1).strip() if m else None


def resolve_play_calls(df: pd.DataFrame, coach_note_col: str = "coach_note") -> pd.Series:
    """Play-call name per row, preferring the parser's own real "play_call" column (populated when a
    season-wide play-call log CSV -- e.g. "uww_plays_25_26.csv" -- covers that row) over the regex-based
    extract_offensive_play_call() guess from free-text coach commentary. The real column is exact,
    structured data straight from the play log; the regex is a best-effort fallback for rows that only have
    a coach's free-text note (from a single-game "*_recap.csv") with no matching play-log entry. Falls back
    entirely to the regex if "play_call" isn't a column at all yet (older data, before the parser's been
    re-run with this field added). Returns a Series aligned to df's index."""
    _regex_fallback = df[coach_note_col].apply(extract_offensive_play_call)
    if "play_call" not in df.columns:
        return _regex_fallback
    _has_real_call = df["play_call"].notna() & (df["play_call"].astype(str).str.strip() != "")
    # Canonicalize against the playbook catalog last, so both sources agree on one name per play: the
    # play log writes "Panther-4 \"P4\"", a coach note might say "P-4" or "P4", and without this they
    # counted as three separate plays in every breakdown on the page.
    return df["play_call"].where(_has_real_call, _regex_fallback).apply(canonical_play_call)


def _play_norm(text) -> str:
    """Normalization key for matching a play call against the playbook catalog: uppercase, letters and
    digits only. This is what lets "P-4", "P4", "P 4" and "p4" all land on the same catalog entry -- the
    coaches write the shorthand a different way in nearly every clip, and the catalog's own name for it
    ("Panther-4 \"P4\"") is a third spelling again."""
    return re.sub(r"[^A-Z0-9]", "", str(text).upper())


def play_catalog_lookup() -> dict:
    """{normalized key -> (play_name, series, play_family)} built from the team's own playbook index
    (the Hudl "Plays" page, parsed by the parser into uww_plays_catalog.csv). Every spelling the catalog
    knows about resolves to one entry: the full play name, the shorthand in quotes, and the name with the
    shorthand stripped. Empty dict when the catalog hasn't been parsed yet, in which case every play call
    just stays exactly as the coach typed it."""
    cat = load_table("uww_plays_catalog")
    if cat.empty or "play_name" not in cat.columns:
        return {}
    out = {}
    for _, r in cat.iterrows():
        _keys = [k for k in str(r.get("match_keys", "")).split("|") if k] or [_play_norm(r["play_name"])]
        for k in _keys:
            out.setdefault(k, (str(r["play_name"]), str(r.get("series", "")), str(r.get("play_family", ""))))
    return out


def _play_title_case(name) -> str:
    """Consistent display spelling for a play call the catalog doesn't list. Coaches type the same call in
    whatever case the moment called for -- "TWINS SWIRL" in one clip, "Twins Swirl" in the next -- and
    those grouped as two separate plays with half the attempts each. Title case matches the catalog's own
    style ("Twins Pitch Wrap"), except for tokens that are clearly acronyms or numbered tags (3 characters
    or fewer, or containing a digit), which stay exactly as typed so "DHO", "ELOB" and "P-4" don't become
    "Dho", "Elob" and "P-4"'s prettier, wronger cousins."""
    _PLAY_ACRONYMS = {"ELOB", "SLOB", "BLOB", "ATO", "DHO", "ISO", "PNR", "OB", "UCLA", "STS"}
    _out = []
    for _tok in re.split(r"(\s+)", str(name).strip()):
        if not _tok or _tok.isspace():
            _out.append(_tok)
        elif _tok.upper().strip("()\"'") in _PLAY_ACRONYMS:
            _out.append(_tok.upper())
        elif len(_tok) <= 3 or any(ch.isdigit() for ch in _tok):
            _out.append(_tok.upper() if _tok.isupper() else _tok)
        else:
            _out.append(_tok[:1].upper() + _tok[1:].lower())
    return "".join(_out)


# Situation/clock tags the clip software mixes in with real play names ("End of Half", "Timeout"). They
# come through the same "Text Overlay" field the season play log puts play names in, so without this they
# show up in the play-call breakdown as if they were sets the staff ran -- and "End of Half" was landing
# high in the list purely because every game has one.
NON_PLAY_CALL_PATTERNS = (
    r"^end\s+of\b",           # End of Half / End of Game / End of 1st / End of Period
    r"^(half|halftime|game|period|quarter|ot\d*|overtime)$",
    r"^(time\s*out|timeout|to)$",
    r"^(dead\s*ball|jump\s*ball|tip\s*off|tipoff)$",
    r"^(shot\s*clock|clock)\b",
    r"^(free\s*throws?|ft)$",
    r"^(n/?a|none|unknown|tbd|misc|other|untagged)$",
)


def is_non_play_call(name) -> bool:
    """True for a clock/situation tag that isn't a called play."""
    _t = re.sub(r"\s+", " ", str(name or "")).strip().lower()
    if not _t:
        return True
    return any(re.search(_p, _t) for _p in NON_PLAY_CALL_PATTERNS)


# Result/quality words the clip tagger appends to a play name ("P4 Good", "Twins Pitch Miss"). They are an
# outcome, not part of the call, and they split one play into a row per outcome in every breakdown.
PLAY_CALL_QUALIFIER_WORDS = {
    "good", "bad", "great", "ok", "okay", "nice", "poor",
    "make", "made", "makes", "miss", "missed", "misses", "score", "scored", "bucket",
    "and1", "and-1", "foul", "fouled", "to", "turnover", "tov", "execution", "exec",
}


def _strip_play_qualifiers(name) -> str:
    """Drop trailing outcome words from a play call: "P4 Good" -> "P4". Only whole trailing tokens from a
    known list are removed, and only from the END -- a generic "longest prefix that matches the catalog"
    rule would be worse than the problem, quietly turning the real play "Twins Swirl" into the different
    real play "Twins"."""
    _toks = str(name or "").strip().split()
    while len(_toks) > 1 and _toks[-1].strip("().,+-\"'").lower() in PLAY_CALL_QUALIFIER_WORDS:
        _toks.pop()
    return " ".join(_toks)


def canonical_play_call(name):
    """The catalog's own name for a play call. A call the catalog doesn't know keeps its own wording but
    gets a consistent case, so the same call typed two ways stays one play. Never drops a call."""
    if name is None or (isinstance(name, float) and name != name):
        return name
    _lookup = play_catalog_lookup()
    hit = _lookup.get(_play_norm(name))
    if hit:
        return hit[0]
    # Retry without a trailing outcome word ("P4 Good" -> "P4" -> Panther-4 "P4").
    _stripped = _strip_play_qualifiers(name)
    if _stripped and _play_norm(_stripped) != _play_norm(name):
        hit = _lookup.get(_play_norm(_stripped))
        if hit:
            return hit[0]
    # Situation tags are dropped (None), not renamed -- every consumer already filters play_call.notna(),
    # so they disappear from the breakdowns while the clip itself stays in the raw notes browser.
    if is_non_play_call(_stripped or name):
        return None
    return _play_title_case(_stripped or name)


def play_family_lookup() -> dict:
    """{normalized family stem -> (series, family)} -- e.g. "TWINS" -> ("Twins", "Twins"). Lets a call the
    catalog has never seen as a whole ("TWINS SWIRL", a combination tagged in a clip but not filed as its
    own play) still group under the right series by its leading word."""
    # A family can span series -- "Twins" is the SLOB out-of-bounds set AND the half-court Twins package --
    # so a family only reports a series when every play in it agrees. Otherwise the series is left blank
    # rather than reporting whichever one happened to be read first.
    _seen = {}
    for _pn, _series, _family in play_catalog_lookup().values():
        if not _family:
            continue
        _k = _play_norm(_family)
        _entry = _seen.setdefault(_k, {"family": _family, "series": set()})
        if _series:
            _entry["series"].add(_series)
    return {
        _k: ((next(iter(_v["series"])) if len(_v["series"]) == 1 else ""), _v["family"])
        for _k, _v in _seen.items()
    }


def play_call_series(name) -> tuple:
    """(series, family) for a play call -- e.g. Panther-4 -> ("Specials", "Panther"). Series is the
    catalog's own grouping; family is the play-name stem, which is what actually puts P, P2 and P4
    together as one Panther group even though the catalog files all three under Specials. A call the
    catalog doesn't list falls back to matching its FIRST word against known families, so an ad-hoc
    variant still lands with its series instead of alone."""
    _lookup = play_catalog_lookup()
    hit = _lookup.get(_play_norm(name)) or _lookup.get(_play_norm(_strip_play_qualifiers(name)))
    if hit:
        return (hit[1], hit[2])
    # A call written as "<series> <play>" ("Over Cheetah", "SLOB Twins") -- the tagger's own shorthand for
    # which package the set came out of. Keep it as its own call (the SLOB version of Twins is not the
    # half-court one), but read the series off the leading word so it still groups correctly.
    # Family first: "Twins" is both a series name and a play family, and reading it as a series would file
    # "Twins Right" under family "Right".
    _first = re.match(r"[A-Za-z]+", str(name or "").strip())
    if _first:
        _fam_first = play_family_lookup().get(_play_norm(_first.group(0)))
        if _fam_first:
            return _fam_first
    _toks = str(name or "").strip().split()
    if len(_toks) > 1:
        _series_map = {_play_norm(_se): _se for _pn, _se, _fa in play_catalog_lookup().values() if _se}
        _se_hit = _series_map.get(_play_norm(_toks[0]))
        if _se_hit:
            _rest_hit = play_catalog_lookup().get(_play_norm(" ".join(_toks[1:])))
            if _rest_hit:
                return (_se_hit, _rest_hit[2])
            _rest_first = re.match(r"[A-Za-z]+", _toks[1])
            _fam_hit = play_family_lookup().get(_play_norm(_rest_first.group(0))) if _rest_first else None
            return (_se_hit, _fam_hit[1] if _fam_hit else (_rest_first.group(0).title() if _rest_first else ""))
    _first = re.match(r"[A-Za-z]+", str(name or "").strip())
    if _first:
        return play_family_lookup().get(_play_norm(_first.group(0)), ("", ""))
    return ("", "")


# --- Points per possession -------------------------------------------------------------------------------
# FG% treats a made three and a made layup as the same event and ignores trips to the line entirely, so a
# play that generates 38% from three ranks below one that generates 48% from two even though it produces
# more points. Points per possession is the standard efficiency unit (roughly: 1.00 PPP is break-even for
# a college offense), so it leads every play-call number now, with FG% kept in parentheses because it's
# what the staff has been reading all season.
_RESULT_POINTS = {"make 3 pts": 3, "make 2 pts": 2, "1 pts": 1, "0 pts": 0}


def play_result_points(result):
    """Points produced by one tagged possession, or None when the tag doesn't say.

    "Foul"/"Non Shooting Foul"/"Free Throw"/"No Violation" are deliberately None rather than 0: a drawn
    shooting foul is usually a GOOD outcome worth more than a point on average, and scoring it as zero
    would punish exactly the plays that get to the line. Unknown outcomes are excluded from the
    denominator instead of guessed at.
    """
    _t = re.sub(r"\s+", " ", str(result or "")).strip().lower()
    if _t in _RESULT_POINTS:
        return _RESULT_POINTS[_t]
    if _t.startswith("miss"):
        return 0
    if _t == "turnover":
        return 0
    return None


def summarize_play_calls(rows: pd.DataFrame, min_possessions: int = 2) -> pd.DataFrame:
    """Per-play-call efficiency table: PPP over scoreable possessions, plus the FG% split.

    `rows` is coach-note rows already carrying a resolved `play_call` and a `result`.
    """
    if rows.empty or "play_call" not in rows.columns:
        return pd.DataFrame(columns=["play_call", "Poss", "Pts", "PPP", "Makes", "Attempts", "FG%"])
    _r = rows.copy()
    _r["_pts"] = _r["result"].apply(play_result_points)
    _r["_is_poss"] = _r["_pts"].notna()
    _r["_pts_f"] = pd.to_numeric(_r["_pts"], errors="coerce").fillna(0)
    _r["_mk"] = _r["result"].astype(str).str.contains("Make", case=False, na=False)
    _r["_at"] = _r["result"].astype(str).str.contains("Make|Miss", case=False, regex=True, na=False)
    _out = _r.groupby("play_call").agg(
        Poss=("_is_poss", "sum"), Pts=("_pts_f", "sum"),
        Makes=("_mk", "sum"), Attempts=("_at", "sum"),
    ).reset_index()
    _out["PPP"] = _out["Pts"] / pd.to_numeric(_out["Poss"], errors="coerce").replace(0, float("nan"))
    _out["FG%"] = 100 * _out["Makes"] / pd.to_numeric(_out["Attempts"], errors="coerce").replace(0, float("nan"))
    _out = _out[_out["Poss"] >= min_possessions]
    return _out.sort_values("PPP", ascending=False).reset_index(drop=True)


def format_ppp(row) -> str:
    """"1.24 PPP (52% FG)" -- the efficiency number leads, the familiar one stays visible."""
    _ppp = "--" if pd.isna(row.get("PPP")) else f"{row['PPP']:.2f} PPP"
    _fg = "" if pd.isna(row.get("FG%")) else f", {row['FG%']:.0f}% FG"
    return f"{_ppp}{_fg}"


# --- Coach feedback on Keys to Victory --------------------------------------------------------------------
# Every key on the Upcoming Opponent page can be rated by the staff in one click. Stored as an append-only
# CSV next to the parser's own tables so it can be opened in Excel, joined against the keys themselves, or
# read straight back into this app -- no database, no service, nothing to keep running.
KTV_FEEDBACK_FILE = "ktv_feedback.csv"
KTV_FEEDBACK_COLUMNS = [
    "recorded_at", "opponent", "game_date", "section", "category", "source", "key_id", "key_text",
    "rating", "coach", "comment",
]
KTV_RATINGS = ["Beneficial", "Not beneficial", "Not accurate"]


def ktv_feedback_path() -> str:
    return os.path.join(DATA_DIR, KTV_FEEDBACK_FILE)


def ktv_key_id(opponent, category, key_text) -> str:
    """Stable id for one key, so the same key rated across several weeks lines up in the CSV even though
    the surrounding numbers change. Hashed rather than stored raw because a key's text can be long and
    carries commas/quotes that make a CSV column awkward -- the text is stored alongside it anyway."""
    _basis = f"{str(category).strip().lower()}|{re.sub(r'[^a-z0-9]+', ' ', str(key_text).lower()).strip()}"
    return hashlib.md5(_basis.encode("utf-8")).hexdigest()[:12]


def load_ktv_feedback() -> pd.DataFrame:
    """Every rating recorded so far. Read directly (not via load_table's cache) so a rating shows up in the
    review table the moment it's saved."""
    _p = ktv_feedback_path()
    if not os.path.exists(_p):
        return pd.DataFrame(columns=KTV_FEEDBACK_COLUMNS)
    try:
        _df = pd.read_csv(_p)
    except Exception:
        return pd.DataFrame(columns=KTV_FEEDBACK_COLUMNS)
    for _c in KTV_FEEDBACK_COLUMNS:
        if _c not in _df.columns:
            _df[_c] = None
    return _df[KTV_FEEDBACK_COLUMNS]


def save_ktv_feedback(record: dict) -> bool:
    """Append one rating. Returns False (rather than raising) if the file can't be written, so a read-only
    filesystem degrades to "the buttons don't stick" instead of taking the page down."""
    _p = ktv_feedback_path()
    _row = {_c: record.get(_c) for _c in KTV_FEEDBACK_COLUMNS}
    _row["recorded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(os.path.dirname(_p) or ".", exist_ok=True)
        _write_header = not os.path.exists(_p) or os.path.getsize(_p) == 0
        pd.DataFrame([_row])[KTV_FEEDBACK_COLUMNS].to_csv(_p, mode="a", header=_write_header, index=False)
        return True
    except Exception:
        return False


# --- Coach-note themes ------------------------------------------------------------------------------------
# Grouping free-text clip notes by what they are ABOUT. The taxonomy (data/note_themes.json) was derived
# once, offline, from this staff's own note language; classification at runtime is pure phrase matching, so
# every new note is categorized instantly with no model call and no token cost, forever. Retuning means
# editing that JSON -- add a phrase, reload, done.
NOTE_THEMES_FILE = "note_themes.json"


@st.cache_data(ttl=60)
def load_note_themes() -> list:
    """[{theme, side, phrases}] from data/note_themes.json, or [] when the file isn't there."""
    path = os.path.join(DATA_DIR, NOTE_THEMES_FILE)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh).get("themes", [])
    except Exception:
        return []


def strip_note_play_call(note) -> str:
    """The coach's note minus the play call that opens it: "PANTHER EXECUTION. BIG = WALK YOUR MAN UP"
    -> "BIG = WALK YOUR MAN UP". The play name is already its own column; leaving it in the text made
    every Panther note look like it shared a theme with every other Panther note."""
    if note is None or (isinstance(note, float) and note != note):
        return ""
    _t = str(note).strip()
    _t = re.sub(r"^[A-Z][A-Z0-9\-&' ]{1,24}?\s+EXECUTION\b[.,:=]*\s*", "", _t)
    _t = re.sub(r"^[A-Z0-9\-' ]{2,20}=\s*", "", _t)
    return _t.strip(" ,.=")


def classify_note_themes(note, max_themes: int = 3) -> list:
    """[(theme, hits)] for one note, best first. Longer phrases score higher than single words, so
    "missed switch" counts for more than a stray "switch"; a note matching nothing returns []."""
    _text = " " + re.sub(r"\s+", " ", strip_note_play_call(note)).lower() + " "
    if not _text.strip():
        return []
    _scores = {}
    for _t in load_note_themes():
        _score = 0.0
        for _p in _t.get("phrases", []):
            _p = str(_p).lower().strip()
            if not _p:
                continue
            _pat = r"(?<!\w)" + re.escape(_p) + r"(?:s|es|ed|ing)?(?!\w)"
            if re.search(_pat, _text):
                _score += 1.0 + 0.5 * _p.count(" ")  # multi-word phrases are stronger evidence
        if _score:
            _scores[_t["theme"]] = _score
    return sorted(_scores.items(), key=lambda kv: -kv[1])[:max_themes]


def note_theme_table(notes_df: pd.DataFrame, note_col: str = "coach_note") -> pd.DataFrame:
    """One row per (note, theme) -- the long form everything else groups off. Carries the note's own
    +/- counts so a theme can be split into what went well and what didn't."""
    if notes_df.empty or note_col not in notes_df.columns:
        return pd.DataFrame(columns=["theme", "player", "opponent", "note", "pos", "neg", "score"])
    _rows = []
    for _, _r in notes_df.iterrows():
        _note = _r.get(note_col)
        if _note is None or (isinstance(_note, float) and _note != _note):
            continue
        _pos, _neg = note_sentiment_counts(_note)
        for _theme, _score in classify_note_themes(_note):
            _rows.append({"theme": _theme, "player": _r.get("player"), "opponent": _r.get("opponent"),
                          "note": strip_note_play_call(_note), "pos": _pos, "neg": _neg, "score": _score})
    return pd.DataFrame(_rows)


def note_sentiment_counts(note) -> tuple:
    """Count "+"-prefixed (execution point that went well) vs "-"-prefixed (went wrong) clauses within one
    coach note, splitting on commas -- this team's notation consistently marks individual observations this
    way within a single note (e.g. "+CUT, -GET TO DEFENDERS BODY, -PASSER LOWER" -> (1, 2)). A note with no
    +/- markers at all (plenty aren't broken out this way) returns (0, 0) rather than being miscounted as
    either."""
    if pd.isna(note):
        return 0, 0
    segments = [s.strip() for s in str(note).split(",")]
    pos = sum(1 for s in segments if s.startswith("+"))
    neg = sum(1 for s in segments if s.startswith("-"))
    return pos, neg


# --------------------------------------------------------------------------------------------------------------
# Section 0: Home — AI Scouting Assistant
# --------------------------------------------------------------------------------------------------------------

# LLM configuration — configure via environment variables:
#   OPENAI_API_KEY    — your API key (OpenAI, Azure, or any compatible provider)
#   OPENAI_BASE_URL   — (optional) custom endpoint URL, e.g. "https://api.openai.com/v1"
#                        or a local model server like "http://localhost:11434/v1" (Ollama)
#   AI_MODEL          — (optional) model name, defaults to "gpt-4o-mini"
AI_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")


def _get_openai_client():
    """Return an OpenAI client configured via environment variables.

    Supports any OpenAI-compatible API (OpenAI, Azure OpenAI, Ollama, vLLM, etc.)
    Set OPENAI_API_KEY and optionally OPENAI_BASE_URL.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL")  # None = default OpenAI endpoint
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY environment variable is not set. "
            "Set it to use the AI chat feature, or leave it blank to disable chat."
        )
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _build_system_prompt() -> str:
    """Build a system prompt with current UWW basketball context from loaded data."""
    # Team record and schedule context
    schedule = load_table("uww_schedule")

    # Upcoming opponent
    if "Upcoming" in schedule.columns:
        upcoming = schedule[schedule["Upcoming"].str.strip().str.lower() == "yes"]
    else:
        upcoming = schedule[~played_mask(schedule)]
    upcoming_opp = upcoming.iloc[0]["opponent"] if not upcoming.empty else "TBD"

    # Record going into the upcoming game (only games before it in the schedule)
    if not upcoming.empty:
        next_game_idx = upcoming.iloc[0].name
        pre_upcoming = schedule.loc[:next_game_idx].iloc[:-1]
        played = pre_upcoming[played_mask(pre_upcoming)]
    else:
        played = schedule[played_mask(schedule)]
    uww_wins = int((played["outcome"] == "W").sum())
    uww_losses = int((played["outcome"] == "L").sum())

    # Recent results
    recent_games = []
    for _, g in played.tail(5).iterrows():
        opp = g["opponent"]
        outcome = g["outcome"]
        score = f"{int(g['team_score'])}-{int(g['opponent_score'])}" if pd.notna(g.get("team_score")) else ""
        recent_games.append(f"{opp}: {outcome} {score}")
    recent_str = "; ".join(recent_games) if recent_games else "No games played yet."

    # Coaching flags summary
    try:
        flags = load_table("uww_coaching_flags")
        pos_flags = len(flags[flags["sentiment"] == "Positive"])
        neg_flags = len(flags[flags["sentiment"] == "Negative"])
        flags_str = f"{len(flags)} total coaching flags ({pos_flags} positive, {neg_flags} negative)"
    except Exception:
        flags_str = "No coaching flags data available."

    return f"""You are the UW-Whitewater Warhawks men's basketball AI scouting assistant.
You help coaches and staff analyze the team, opponents, and game preparation.

CURRENT TEAM CONTEXT:
- Record: {uww_wins}-{uww_losses}
- Next opponent: {upcoming_opp}
- Recent results: {recent_str}
- Coaching flags: {flags_str}

AVAILABLE DATA (the app has these datasets):
- uww_schedule: full season schedule with dates, opponents, outcomes, scores
- uww_coaching_flags: coaching observations categorized by sentiment and category
- uww_opponent_game_plans: scouting reports with keys to victory, strengths, offensive/defensive schemes
- uww_opponent_rosters: opponent player info (position, height, class, role)
- uww_opponent_team_totals: opponent PPG scored and allowed
- uww_pbp_events: play-by-play event data
- uww_pbp_box_score: game box scores from play-by-play
- uww_player_comparisons: player comparison data
- uww_player_profiles: player background profiles
- uww_ktv_game_categories: keys-to-victory emphasis categories per game
- uww_ktv_splits: UWW win/loss splits by KTV category

GUIDELINES:
- Be concise and basketball-focused.
- Reference specific numbers and players when possible.
- If asked about data you don't have in context, explain what's available in the app's other pages.
- Use coaching terminology appropriate for a D-III men's basketball program.
- Format responses with markdown for readability.
"""


def render_home():
    """Home page with AI scouting assistant chat interface."""
    # Welcome header
    st.markdown("## :house: Home")
    st.markdown(
        "Ask the AI scouting assistant anything about UWW basketball — "
        "team stats, opponent breakdowns, game prep, player analysis, and more."
    )

    # --- Chat interface ---
    if "home_messages" not in st.session_state:
        st.session_state.home_messages = []

    # Display chat history
    for msg in st.session_state.home_messages:
        with st.chat_message(msg["role"], avatar="🏀" if msg["role"] == "assistant" else None):
            st.markdown(msg["content"])

    # Chat input
    prompt = st.chat_input("Ask about UWW basketball...")

    # Suggestion chips below the chat bar when no conversation yet
    if not st.session_state.home_messages and not prompt:
        st.markdown("###### Try asking:")
        suggestions = [
            "What are our keys to victory against Elmhurst?",
            "Who is our best 3-point shooter?",
            "Summarize our team's biggest strengths and weaknesses.",
            "How have we performed in our last 3 games?",
        ]
        cols = st.columns(2)
        for i, suggestion in enumerate(suggestions):
            with cols[i % 2]:
                if st.button(suggestion, key=f"suggest_{i}", use_container_width=True):
                    st.session_state.home_messages.append({"role": "user", "content": suggestion})
                    st.rerun()

    # Determine if we need to generate a response:
    # Either the user just typed something, or a suggestion button was clicked (last msg is user with no reply)
    needs_response = False
    if prompt:
        st.session_state.home_messages.append({"role": "user", "content": prompt})
        needs_response = True
    elif st.session_state.home_messages and st.session_state.home_messages[-1]["role"] == "user":
        needs_response = True

    if needs_response:
        # Generate AI response
        with st.chat_message("assistant", avatar="🏀"):
            with st.spinner("Thinking..."):
                try:
                    client = _get_openai_client()
                    system_prompt = _build_system_prompt()

                    messages = [{"role": "system", "content": system_prompt}]
                    for m in st.session_state.home_messages[-20:]:
                        messages.append({"role": m["role"], "content": m["content"]})

                    response = client.chat.completions.create(
                        model=AI_MODEL,
                        messages=messages,
                        max_tokens=1024,
                        temperature=0.7,
                    )
                    answer = response.choices[0].message.content
                except Exception as e:
                    answer = f"⚠️ AI assistant unavailable: {e}"

                st.markdown(answer)
        st.session_state.home_messages.append({"role": "assistant", "content": answer})
        st.rerun()


# --------------------------------------------------------------------------------------------------------------
# Section 1: Upcoming Game
# --------------------------------------------------------------------------------------------------------------
def render_upcoming_game():
    """Upcoming Game page: banner, then Keys to Victory (combining pre-computed data-driven keys, the staff's
    written scouting report, lineup scouting, and season-stat-based recommendations into one grouped,
    hover/badge-tagged list) right after it, then the PPG/Team Stats/Season Leaders/Last Five Games block
    (with the short_opponent-is-None early-return guard right after it), then tabs for Stats & Analysis,
    Keys to Victory detail, Personnel, and Tools. Supersedes an earlier, more scattered version of this page
    (Game Plan Recommendations and Scouting Report used to be their own separate stacked sections) that this
    layout replaced entirely after side-by-side comparison.
    """
    schedule = load_table("uww_schedule")
    short_names = load_short_opponent_names()

    if "Upcoming" in schedule.columns:
        upcoming = schedule[schedule["Upcoming"].str.strip().str.lower() == "yes"]
    else:
        upcoming = schedule[~played_mask(schedule)]
    if upcoming.empty:
        st.info("No upcoming games found in the schedule.")
        return
    next_game = upcoming.iloc[0]
    full_opponent = next_game["opponent"]

    short_opponent = resolve_short_opponent(full_opponent, short_names)

    # --- Game header (broadcast-style matchup banner) ---
    game_date = str(next_game.get("date", "-"))
    location = str(next_game.get("location", "-"))
    record = next_game.get("opponent_season_record", "")
    # Compute UWW record and streak from games BEFORE the upcoming game (by schedule order)
    next_game_idx = next_game.name  # row index of the upcoming game
    pre_upcoming = schedule.loc[:next_game_idx].iloc[:-1]  # all rows before the upcoming game
    played = pre_upcoming[played_mask(pre_upcoming)]
    uww_wins = int((played["outcome"] == "W").sum())
    uww_losses = int((played["outcome"] == "L").sum())
    # Current streak
    streak_count = 0
    streak_type = ""
    for outcome in played["outcome"].iloc[::-1]:
        if streak_count == 0:
            streak_type = outcome
            streak_count = 1
        elif outcome == streak_type:
            streak_count += 1
        else:
            break
    streak_label = "win" if streak_type == "W" else "loss"
    streak_str = f"{streak_count}-game {streak_label} streak" if streak_count >= 1 else ""

    opp_record = str(record).strip() if pd.notna(record) and str(record).strip() else ""
    # "should always show the streak for both teams" -- get_opponent_entering_record() is the only source
    # that computes a streak at all; the schedule CSV's own `record` field (when present) never has one. This
    # used to only call it when opp_record was ALSO blank, which meant a game with a pre-filled record string
    # (opp_record truthy) never got a streak at all, silently. Always call it now for the streak specifically,
    # and only fall back to ITS record string if the schedule's own `record` field was empty.
    opp_streak_str = ""
    if short_opponent:
        _entering_record, opp_streak_str = get_opponent_entering_record(short_opponent)
        if not opp_record:
            opp_record = _entering_record

    # Build broadcast-style HTML banner with team logos
    uww_logo_b64 = find_logo_b64("UW-Whitewater")
    # CONFIRMED BUG (fixed here): opp_display used to fall back to the RAW uww_schedule name ("UW-Oshkosh
    # Titans") whenever short_opponent couldn't be resolved -- i.e. whenever an opponent has no scouting/PBP
    # data yet, which is exactly when a coach is most likely to be looking at this banner for a first read.
    # strip_team_mascot() is the same mascot-stripping helper already used elsewhere in the app for this.
    opp_display = strip_known_mascot_suffix(short_opponent) if short_opponent else strip_team_mascot(full_opponent)
    opp_logo_b64 = find_logo_b64(short_opponent, full_opponent)

    uww_logo_img = f'<div style="height:64px;display:flex;align-items:center;justify-content:center;margin-bottom:8px;"><img src="data:image/png;base64,{uww_logo_b64}" style="max-height:64px;max-width:90px;object-fit:contain;"></div>' if uww_logo_b64 else '<div style="height:64px;"></div>'
    opp_logo_img = f'<div style="height:64px;display:flex;align-items:center;justify-content:center;margin-bottom:8px;"><img src="data:image/png;base64,{opp_logo_b64}" style="max-height:64px;max-width:90px;object-fit:contain;"></div>' if opp_logo_b64 else '<div style="height:64px;"></div>'

    _uww_streak_html = f'<div style="color:#aabbcc;font-size:0.8rem;font-style:italic;margin-top:2px;">{streak_str}</div>' if streak_str else ''
    _opp_streak_html = f'<div style="color:#aabbcc;font-size:0.8rem;font-style:italic;margin-top:2px;">{opp_streak_str}</div>' if opp_streak_str else ''
    banner_html = f'<div style="background:#1a1a2e;border-radius:10px;padding:22px 32px;margin-bottom:0.75rem;display:flex;align-items:center;justify-content:space-between;"><div style="text-align:center;flex:1;display:flex;flex-direction:column;align-items:center;">{uww_logo_img}<div style="color:#ffffff;font-family:Montserrat,sans-serif;font-weight:800;font-size:1.4rem;letter-spacing:0.5px;">UW-WHITEWATER</div><div style="color:#9DAAAC;font-size:1.05rem;font-weight:600;margin-top:3px;">{uww_wins}-{uww_losses}</div>{_uww_streak_html}</div><div style="text-align:center;flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;"><div style="color:#9DAAAC;font-size:1rem;font-weight:500;">{game_date}</div><div style="color:#ffffff;font-size:1.6rem;font-weight:700;margin:4px 0;">VS</div><div style="color:#9DAAAC;font-size:0.95rem;">{location}</div></div><div style="text-align:center;flex:1;display:flex;flex-direction:column;align-items:center;">{opp_logo_img}<div style="color:#ffffff;font-family:Montserrat,sans-serif;font-weight:800;font-size:1.4rem;letter-spacing:0.5px;">{html.escape(opp_display.upper())}</div><div style="color:#9DAAAC;font-size:1.05rem;font-weight:600;margin-top:3px;">{opp_record if opp_record else ""}</div>{_opp_streak_html}</div></div>'
    st.markdown(banner_html, unsafe_allow_html=True)

    # --- Reserve layout slots up front (Streamlit fills a container wherever it was CREATED in the
    # layout, regardless of when in the script it is actually written to) -- this is what lets
    # Game Plan Recommendations and the data-driven Keys to Victory render first even though their
    # underlying code still runs later, in its original order. ---
    # Stats & Analysis first (per request), then Keys to Victory as its own tab (previously always-visible
    # at the top of the page), then Personnel, then Tools (which leads with Comparable Opponents).
    _new_tab_stats, _new_tab_ktv, _new_tab_personnel, _new_tab_tools = st.tabs(["\U0001f4ca Stats & Analysis", "\U0001f511 Keys to Victory", "\U0001f465 Personnel", "\U0001f3ae Tools"])
    with _new_tab_stats:
        _new_stats_leaders_c = st.container()
    with _new_tab_ktv:
        _new_ktv_container = st.container()
        _new_rec_container = st.container()
    with _new_tab_personnel:
        _new_personnel_roster_c = st.container()
        _new_personnel_scouting_c = st.container()
    with _new_tab_tools:
        # COMPARABLE OPPONENTS sits at the TOP of Tools (it used to be the last section of Stats &
        # Analysis). Only the slot moves -- the section's code still runs in its original place further
        # down, because a Streamlit container renders where it was CREATED, not where it is written to.
        _new_tools_comparable_c = st.container()
        _new_tools_proj_c = st.container()
        _new_tools_lineup_c = st.container()

    # --- NEW: Data-Driven Keys to Victory (get_data_driven_ktv() already existed but was never wired
    # into any page -- surfacing it here, right under the recommendations, was one of the specific
    # things asked for in the reorganization plan). ---
    with _new_ktv_container:
        pass  # folded into the unified Keys to Victory section below (was a separate card here)


    with _new_stats_leaders_c:
        # --- PPG comparison below banner ---
        uww_ppg = f"{played['team_score'].mean():.1f}" if not played.empty else "-"
        uww_ppg_allowed = f"{played['opponent_score'].mean():.1f}" if not played.empty else "-"

        team_totals = load_table("uww_opponent_team_totals")
        opp_totals = team_totals[team_totals["opponent"] == (short_opponent or "")]
        opp_ppg = "-"
        opp_ppg_allowed = "-"
        if not opp_totals.empty:
            row = opp_totals.iloc[0]
            opp_ppg = f"{row['team_ppg']:.1f}" if pd.notna(row["team_ppg"]) else "-"
            opp_ppg_allowed = f"{row['opp_ppg_allowed']:.1f}" if pd.notna(row.get("opp_ppg_allowed")) else "-"

        # --- Team Stats + Last Five Games (side by side) ---
        # Compute team stats for comparison (only games before the upcoming game)
        box = load_table("uww_pbp_box_score")
        # Restrict to games played BEFORE the upcoming one, by date. The old opponent-name filter let a
        # rematch played after the upcoming game slip into these season averages, since both meetings share
        # a name.
        box = scope_to_played(box, played)
        uww_box = box[box["team"] == "UW-Whitewater"]
        num_uww_games = uww_box["game_date"].nunique() if not uww_box.empty else 1
        uww_team_stats = {}
        uww_team_stats_full = {}
        if not uww_box.empty:
            uww_team_stats = {
                "Points": played["team_score"].mean() if not played.empty else 0,
                "Points Against": played["opponent_score"].mean() if not played.empty else 0,
                "FG%": (uww_box["FGM"].sum() / uww_box["FGA"].sum() * 100) if uww_box["FGA"].sum() > 0 else 0,
                "Rebounds": uww_box["REB"].sum() / num_uww_games if "REB" in uww_box.columns else 0,
                "Assists": uww_box["AST"].sum() / num_uww_games if "AST" in uww_box.columns else 0,
                "Blocks": uww_box["BLK"].sum() / num_uww_games if "BLK" in uww_box.columns else 0,
                "Steals": uww_box["STL"].sum() / num_uww_games if "STL" in uww_box.columns else 0,
            }
            # Expanded stats for All Stats dialog. Column is "FG3M"/"FG3A" in uww_pbp_box_score (confirmed against
            # the parser's actual box-score construction) -- "3PM"/"3PA" never existed, so this silently summed to
            # 0 for UWW's own 3P% and 3PA/game in the All Stats dialog.
            _uww_3pm = uww_box["FG3M"].sum() if "FG3M" in uww_box.columns else 0
            _uww_3pa = uww_box["FG3A"].sum() if "FG3A" in uww_box.columns else 0
            _uww_ftm = uww_box["FTM"].sum() if "FTM" in uww_box.columns else 0
            _uww_fta = uww_box["FTA"].sum() if "FTA" in uww_box.columns else 0
            _uww_to = uww_box["TO"].sum() / num_uww_games if "TO" in uww_box.columns else 0
            _uww_ast = uww_box["AST"].sum() / num_uww_games if "AST" in uww_box.columns else 0
            uww_team_stats_full = {
                **uww_team_stats,
                "3P%": (_uww_3pm / _uww_3pa * 100) if _uww_3pa > 0 else 0,
                "FT%": (_uww_ftm / _uww_fta * 100) if _uww_fta > 0 else 0,
                "3PA/game": _uww_3pa / num_uww_games,
                "FTA/game": _uww_fta / num_uww_games,
                "Turnovers": _uww_to,
                "A:TO Ratio": (_uww_ast / _uww_to) if _uww_to > 0 else 0,
                "Stocks": (uww_box["STL"].sum() + uww_box["BLK"].sum()) / num_uww_games,
            }

        # Opponent averages from player profiles
        opp_profiles_ts = load_table("uww_player_profiles")
        opp_prof_ts = opp_profiles_ts[opp_profiles_ts["opponent"] == short_opponent] if short_opponent else pd.DataFrame()
        opp_team_stats = {}
        opp_team_stats_full = {}
        if not opp_prof_ts.empty:
            opp_team_stats["Points"] = float(opp_ppg) if opp_ppg != "-" else 0
            opp_team_stats["Points Against"] = float(opp_ppg_allowed) if opp_ppg_allowed != "-" else 0
            _opp_fg_pcts = []
            for _, _p in opp_prof_ts.iterrows():
                _fg_str = str(_p.get("FG%", "")).replace("%", "").strip()
                if _fg_str and _fg_str != "nan":
                    try:
                        _opp_fg_pcts.append((float(_fg_str), float(_p.get("MIN", 1))))
                    except ValueError:
                        pass
            opp_team_stats["FG%"] = sum(pct * mins for pct, mins in _opp_fg_pcts) / sum(mins for _, mins in _opp_fg_pcts) if _opp_fg_pcts else 0
            # REB and PTS are per-game averages (confirmed: team_ppg above is the boxscore's "Team Total" row PTS
            # taken with no division). AST/STL/BLK/TO are SEASON TOTALS in this same table, though -- confirmed
            # the other way, empirically: summing AST across a roster with no division produced a ~200 "assists
            # per game" figure, which is only sane as a season sum. So divide those (but not REB/PTS) by games_est.
            # (Not every column in this table shares the same units -- don't assume it again without checking.)
            _games_est = get_opponent_games_played(short_opponent)
            opp_team_stats["Rebounds"] = opp_prof_ts["REB"].sum()
            opp_team_stats["Assists"] = opp_prof_ts["AST"].sum() / _games_est
            opp_team_stats["Blocks"] = opp_prof_ts["BLK"].sum() / _games_est
            opp_team_stats["Steals"] = opp_prof_ts["STL"].sum() / _games_est
            # Expanded opponent stats for All Stats dialog
            def _parse_ma_ts(series):
                made, att = 0, 0
                for val in series.dropna():
                    parts = str(val).split("-")
                    if len(parts) == 2:
                        try:
                            made += int(parts[0])
                            att += int(parts[1])
                        except ValueError:
                            pass
                return made, att
            _opp_3m, _opp_3a = _parse_ma_ts(opp_prof_ts["3PM-A"]) if "3PM-A" in opp_prof_ts.columns else (0, 0)
            _opp_ftm, _opp_fta = _parse_ma_ts(opp_prof_ts["FTM-A"]) if "FTM-A" in opp_prof_ts.columns else (0, 0)
            _opp_to_total = opp_prof_ts["TO"].sum() if "TO" in opp_prof_ts.columns else 0
            _opp_ast_total = opp_prof_ts["AST"].sum() if "AST" in opp_prof_ts.columns else 0
            _opp_to_pg = _opp_to_total / _games_est
            _opp_ast_pg = _opp_ast_total / _games_est
            opp_team_stats_full = {
                **opp_team_stats,
                "3P%": (_opp_3m / _opp_3a * 100) if _opp_3a > 0 else 0,
                "FT%": (_opp_ftm / _opp_fta * 100) if _opp_fta > 0 else 0,
                "3PA/game": _opp_3a / _games_est,
                "FTA/game": _opp_fta / _games_est,
                "Turnovers": _opp_to_pg,
                "A:TO Ratio": (_opp_ast_pg / _opp_to_pg) if _opp_to_pg > 0 else 0,
                "Stocks": (opp_prof_ts["STL"].sum() + opp_prof_ts["BLK"].sum()) / _games_est,
            }


        def _build_team_stats_html(uww_s, opp_s, opp_name):
            """Build broadcast-style team stats comparison with bar charts."""
            stat_order = ["Points", "Points Against", "FG%", "Rebounds", "Assists", "Blocks", "Steals"]
            rows_html = ""
            for stat in stat_order:
                uww_val = uww_s.get(stat, 0)
                opp_val = opp_s.get(stat, 0)
                is_pct = "%" in stat
                max_val = max(uww_val, opp_val, 0.1)
                uww_bar_pct = uww_val / max_val * 100
                opp_bar_pct = opp_val / max_val * 100
                if stat == "Points Against":
                    uww_bold = "font-weight:800;" if uww_val < opp_val else ""
                    opp_bold = "font-weight:800;" if opp_val < uww_val else ""
                else:
                    uww_bold = "font-weight:800;" if uww_val > opp_val else ""
                    opp_bold = "font-weight:800;" if opp_val > uww_val else ""
                uww_fmt = f"{uww_val:.1f}%" if is_pct else f"{uww_val:.1f}"
                opp_fmt = f"{opp_val:.1f}%" if is_pct else f"{opp_val:.1f}"
                rows_html += f'<div style="padding:10px 0;border-bottom:1px solid #eee;"><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;"><span style="font-size:1.2rem;{uww_bold}width:70px;">{uww_fmt}</span><span style="font-size:0.95rem;color:#666;font-weight:600;text-transform:uppercase;flex:1;text-align:center;">{stat}</span><span style="font-size:1.2rem;{opp_bold}width:70px;text-align:right;">{opp_fmt}</span></div><div style="display:flex;gap:4px;height:6px;"><div style="flex:1;display:flex;justify-content:flex-end;"><div style="width:{uww_bar_pct:.0f}%;background:#4E2A84;border-radius:3px;height:100%;"></div></div><div style="flex:1;display:flex;justify-content:flex-start;"><div style="width:{opp_bar_pct:.0f}%;background:#222;border-radius:3px;height:100%;"></div></div></div></div>\n'
            return f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:16px 18px;flex:1;width:100%;"><div style="font-weight:800;font-size:1.15rem;letter-spacing:0.5px;margin-bottom:12px;">TEAM STATS</div><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px;"><span style="font-size:1.05rem;font-weight:700;color:#4E2A84;">UWW</span><span style="font-size:1.05rem;font-weight:700;color:#222;">{html.escape(get_team_abbreviation(opp_name))}</span></div>{rows_html}</div>'

        def _build_last5_combined_html(uww_rows, opp_rows, opp_name):
            """Build broadcast-style last 5 games comparison matching Season Leaders layout."""
            def _game_cell(r):
                if r is None:
                    return '<div style="font-size:0.95rem;color:#aaa;">—</div>'
                loc_prefix = "@ " if "away" in str(r.get("location", "")).lower() else "vs "
                result_color = "#2e7d32" if r["outcome"] == "W" else "#c62828"
                score_str = f"{int(r['team_score'])}-{int(r['opp_score'])}" if r.get("team_score") is not None else ""
                opp_short = str(r.get("opp_name", ""))
                # Truncate long opponent names
                if len(opp_short) > 18:
                    opp_short = opp_short[:16] + "..."
                date_str = str(r.get("date", ""))
                return (
                    f'<div style="font-weight:600;font-size:0.95rem;">'
                    f'<span style="color:{result_color};font-weight:700;">{r["outcome"]}</span> {score_str}</div>'
                    f'<div style="font-size:0.8rem;color:#888;">{loc_prefix}{html.escape(opp_short)}</div>'
                    f'<div style="font-size:0.75rem;color:#999;margin-top:2px;">{html.escape(date_str)}</div>'
                )
            # Build rows — pair UWW and opponent games side by side
            max_games = max(len(uww_rows), len(opp_rows), 1)
            rows_html = ""
            for i in range(min(max_games, 5)):
                uww_game = uww_rows[i] if i < len(uww_rows) else None
                opp_game = opp_rows[i] if i < len(opp_rows) else None
                rows_html += (
                    f'<div style="border:1px solid #eee;border-radius:8px;padding:10px 12px;margin-bottom:8px;">'
                    f'<div style="display:flex;align-items:center;justify-content:space-between;">'
                    f'<div style="text-align:left;flex:1;">{_game_cell(uww_game)}</div>'
                    f'<div style="text-align:right;flex:1;">{_game_cell(opp_game)}</div>'
                    f'</div></div>'
                )
            if not rows_html:
                rows_html = '<div style="text-align:center;font-size:0.95rem;color:#888;padding:12px;">No games available</div>'
            return (
                f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;flex:1;width:100%;">'
                f'<div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;margin-bottom:8px;">LAST FIVE GAMES</div>'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px;">'
                f'<span style="font-size:0.95rem;font-weight:700;color:#4E2A84;">UWW</span>'
                f'<span style="font-size:0.85rem;color:#888;">Recent Results</span>'
                f'<span style="font-size:0.95rem;font-weight:700;color:#222;">{html.escape(get_team_abbreviation(opp_name))}</span>'
                f'</div>{rows_html}</div>'
            )

        # Gather opponent's recent games (pre-UWW)
        try:
            opp_schedule = load_table("uww_opponent_schedules")
            opp_games = opp_schedule[opp_schedule["opponent"] == short_opponent] if short_opponent else pd.DataFrame()
        except Exception as _e:
            opp_games = pd.DataFrame()
            st.warning(f"Could not load opponent schedule: {_e}")

        # Filter opponent games to only those before UWW matchup
        if not opp_games.empty:
            uww_idx = None
            for i, (_, g) in enumerate(opp_games.iterrows()):
                vs = str(g.get("vs_opponent", "")).lower()
                if "whitewater" in vs or "uww" in vs:
                    uww_idx = i
                    break
            if uww_idx is not None:
                opp_games = opp_games.iloc[:uww_idx]

        opp_display = strip_known_mascot_suffix(short_opponent) if short_opponent else strip_team_mascot(full_opponent)

        # Build UWW last 5
        uww_last5 = []
        if not played.empty:
            recent = played.tail(5).iloc[::-1]
            for _, g in recent.iterrows():
                uww_last5.append({
                    "date": g["date"],
                    "opp_name": g["opponent"],
                    "location": g.get("location", ""),
                    "outcome": g["outcome"],
                    "team_score": g["team_score"] if pd.notna(g.get("team_score")) else None,
                    "opp_score": g["opponent_score"] if pd.notna(g.get("opponent_score")) else None,
                })

        # Build opponent last 5 (most recent pre-UWW, reversed)
        opp_last5 = []
        if not opp_games.empty:
            opp_recent = opp_games.tail(5).iloc[::-1]
            for _, g in opp_recent.iterrows():
                opp_last5.append({
                    "date": g["game_date"],
                    "opp_name": g["vs_opponent"],
                    "location": g.get("location", ""),
                    "outcome": g["outcome"],
                    "team_score": g["team_score"] if pd.notna(g.get("team_score")) else None,
                    "opp_score": g["opponent_score"] if pd.notna(g.get("opponent_score")) else None,
                })

        # Build ALL games lists for the All Games dialog
        uww_all_games = []
        if not played.empty:
            for _, g in played.iloc[::-1].iterrows():
                uww_all_games.append({
                    "date": g["date"],
                    "opp_name": g["opponent"],
                    "location": g.get("location", ""),
                    "outcome": g["outcome"],
                    "team_score": g["team_score"] if pd.notna(g.get("team_score")) else None,
                    "opp_score": g["opponent_score"] if pd.notna(g.get("opponent_score")) else None,
                })
        opp_all_games = []
        if not opp_games.empty:
            for _, g in opp_games.iloc[::-1].iterrows():
                opp_all_games.append({
                    "date": g["game_date"],
                    "opp_name": g["vs_opponent"],
                    "location": g.get("location", ""),
                    "outcome": g["outcome"],
                    "team_score": g["team_score"] if pd.notna(g.get("team_score")) else None,
                    "opp_score": g["opponent_score"] if pd.notna(g.get("opponent_score")) else None,
                })

        # --- Season Leaders computation ---
        def _get_uww_leaders(box_df, schedule_df):
            """Get UWW per-game leaders from box score data."""
            # Cross-reference with season stats roster to handle games where team labels are swapped
            season_stats = load_table("uww_season_stats")
            if season_stats.empty or "PLAYER" not in season_stats.columns:
                # Fallback: use box score team labels directly
                uww = box_df[box_df["team"] == "UW-Whitewater"]
            else:
                uww_roster = set(season_stats["PLAYER"].dropna().tolist()) - {"Team Total", "Opponent"}
                uww = box_df[box_df["player"].isin(uww_roster)]
            uww = uww[~uww["player"].astype(str).str.contains(JUNK_PLAYER_RE, na=False)]
            if uww.empty:
                return {}
            # Compute per-game averages
            # Count distinct GAMES, not distinct opponents. With three UW-La Crosse meetings on the
            # schedule, nunique("opponent") returns 1 for all three, inflating every per-game average.
            games_per_player = uww.groupby("player")["game_date"].nunique()
            totals = uww.groupby("player").agg({"PTS": "sum", "REB": "sum", "AST": "sum", "STL": "sum", "BLK": "sum", "TO": "sum", "FGM": "sum", "FGA": "sum", "FTM": "sum", "FTA": "sum", "OREB": "sum", "DREB": "sum"}).reset_index()
            if "MIN" in uww.columns:
                totals["MIN_total"] = totals["player"].map(uww.groupby("player")["MIN"].sum())
            totals["games"] = totals["player"].map(games_per_player)
            totals["PPG"] = totals["PTS"] / totals["games"]
            totals["RPG"] = totals["REB"] / totals["games"]
            totals["APG"] = totals["AST"] / totals["games"]
            totals["FG_pct"] = (totals["FGM"] / totals["FGA"] * 100).round(1)
            totals["FT_pct"] = (totals["FTM"] / totals["FTA"] * 100).round(1)
            totals["DRPG"] = (totals["DREB"] / totals["games"]).round(1)
            totals["ORPG"] = (totals["OREB"] / totals["games"]).round(1)
            totals["TOPG"] = (totals["TO"] / totals["games"]).round(1)
            # CONFIRMED BUG (fixed here): Minutes used to come from uww_season_stats -- UWW's own OFFICIAL
            # scraped season-stats page, live-rendered off the current real season, with the exact same
            # "no reference_date awareness at all" problem the opponent's scouting-report PDFs had (already
            # fixed for the opponent side by aggregating from PBP instead). Now computed the same way as
            # PPG/RPG/APG immediately above -- from `uww` (box_df, already correctly scoped to games before
            # reference_date by the pbp_events fix earlier in this project) -- instead of a second, unscoped
            # data source that silently disagreed with everything else on this page.
            leaders = {}
            if "MIN_total" in totals.columns:
                mpg_totals = totals.dropna(subset=["MIN_total"])
                if not mpg_totals.empty:
                    mpg_totals = mpg_totals.copy()
                    mpg_totals["MIN_num"] = (mpg_totals["MIN_total"] / mpg_totals["games"]).round(1)
                    mpg_leader = mpg_totals.nlargest(1, "MIN_num").iloc[0]
                    _pbp_games = int(mpg_leader["games"])
                    _gp_sub = f"{_pbp_games} GP" if _pbp_games > 0 else ""
                    leaders["Minutes"] = {"name": mpg_leader["player"], "value": mpg_leader["MIN_num"], "sub": _gp_sub}
            # Points leader
            pts_leader = totals.nlargest(1, "PPG").iloc[0]
            leaders["Points"] = {"name": pts_leader["player"], "value": pts_leader["PPG"], "sub": f"{pts_leader['FG_pct']:.1f} FG%\n{pts_leader['FT_pct']:.1f} FT%"}
            # Rebounds leader
            reb_leader = totals.nlargest(1, "RPG").iloc[0]
            leaders["Rebounds"] = {"name": reb_leader["player"], "value": reb_leader["RPG"], "sub": f"{reb_leader['DRPG']} DRPG\n{reb_leader['ORPG']} ORPG"}
            # Assists leader
            ast_leader = totals.nlargest(1, "APG").iloc[0]
            leaders["Assists"] = {"name": ast_leader["player"], "value": ast_leader["APG"], "sub": f"{ast_leader['TOPG']} TOPG"}
            # Steals leader
            totals["SPG"] = (totals["STL"] / totals["games"]).round(1)
            stl_leader = totals.nlargest(1, "SPG").iloc[0]
            leaders["Steals"] = {"name": stl_leader["player"], "value": stl_leader["SPG"], "sub": ""}
            # Blocks leader
            totals["BPG"] = (totals["BLK"] / totals["games"]).round(1)
            blk_leader = totals.nlargest(1, "BPG").iloc[0]
            leaders["Blocks"] = {"name": blk_leader["player"], "value": blk_leader["BPG"], "sub": ""}
            return leaders

        def _get_opp_leaders(profiles_df, opp_name, games_est=5):
            """Get opponent per-game leaders from player profiles."""
            opp = profiles_df[profiles_df["opponent"] == opp_name]
            opp = opp[~opp["name"].astype(str).str.contains(JUNK_PLAYER_RE, na=False)]
            if opp.empty:
                return {}

            # PTS/REB/MIN in this table are already per game; AST/STL/BLK/TO are SEASON TOTALS the app has to
            # divide. It used to divide by the TEAM's games played, which understates anyone who missed time --
            # 73 assists over the 24 games a player actually appeared in rendered as 2.6/gm instead of 3.0
            # because the divisor was the team's 28. Use the per-player games_played the parser now exports,
            # falling back to the team count for an opponent whose stats still come from a scouting-report PDF.
            if "games_played" in opp.columns:
                _opp_gp = pd.to_numeric(opp["games_played"], errors="coerce")
            else:
                _opp_gp = pd.Series(index=opp.index, dtype="float64")
            _opp_gp = _opp_gp.where(_opp_gp > 0).fillna(games_est if games_est else 1)

            leaders = {}
            # Minutes leader
            if "MIN" in opp.columns:
                opp_min = opp.copy()
                opp_min["MIN_num"] = pd.to_numeric(opp_min["MIN"], errors="coerce")
                opp_min = opp_min.dropna(subset=["MIN_num"])
                if not opp_min.empty:
                    min_leader = opp_min.nlargest(1, "MIN_num").iloc[0]
                    # Matches UWW's own Minutes leader sub ("X GP") -- games_est is already the correctly-
                    # scoped (pre-UWW-matchup) games-played count passed in by the caller.
                    _min_gp = _opp_gp.get(min_leader.name, games_est)
                    _opp_gp_sub = f"{int(_min_gp)} GP" if _min_gp else ""
                    leaders["Minutes"] = {"name": min_leader["name"], "value": min_leader["MIN_num"], "sub": _opp_gp_sub}
            # Points leader (PTS is already per-game in profiles)
            pts_leader = opp.nlargest(1, "PTS").iloc[0]
            fg_str = str(pts_leader.get("FG%", "")).replace("%", "").strip()
            ft_str = str(pts_leader.get("FT%", "")).replace("%", "").strip()
            fg_val = fg_str if fg_str and fg_str != "nan" else "-"
            ft_val = ft_str if ft_str and ft_str != "nan" else "-"
            leaders["Points"] = {"name": pts_leader["name"], "value": pts_leader["PTS"], "sub": f"{fg_val} FG%\n{ft_val} FT%"}
            # Rebounds leader (REB is per-game). DRPG/ORPG sub only exists for the CURRENT upcoming opponent
            # -- their prior-games PBP reconstruction has an offensive/defensive rebound split, unlike the
            # PDF-sourced stats every other scouted opponent still uses, which only ever have a combined REB.
            reb_leader = opp.nlargest(1, "REB").iloc[0]
            _reb_sub = ""
            if {"OREB", "DREB"} <= set(opp.columns):
                _reb_oreb = pd.to_numeric(reb_leader.get("OREB"), errors="coerce")
                _reb_dreb = pd.to_numeric(reb_leader.get("DREB"), errors="coerce")
                if pd.notna(_reb_oreb) and pd.notna(_reb_dreb):
                    _reb_sub = f"{_reb_dreb:.1f} DRPG\n{_reb_oreb:.1f} ORPG"
            leaders["Rebounds"] = {"name": reb_leader["name"], "value": reb_leader["REB"], "sub": _reb_sub}
            # Season totals -> per game, each divided by that player's own games (see _opp_gp above).
            opp_copy = opp.copy()
            opp_copy["APG"] = pd.to_numeric(opp_copy["AST"], errors="coerce") / _opp_gp
            opp_copy["TOPG"] = pd.to_numeric(opp_copy["TO"], errors="coerce") / _opp_gp
            ast_leader = opp_copy.nlargest(1, "APG").iloc[0]
            leaders["Assists"] = {"name": ast_leader["name"], "value": ast_leader["APG"],
                                  "sub": f"{ast_leader['TOPG']:.1f} TOPG" if pd.notna(ast_leader["TOPG"]) else ""}
            opp_copy["SPG"] = pd.to_numeric(opp_copy["STL"], errors="coerce") / _opp_gp
            stl_leader = opp_copy.nlargest(1, "SPG").iloc[0]
            leaders["Steals"] = {"name": stl_leader["name"], "value": stl_leader["SPG"], "sub": ""}
            opp_copy["BPG"] = pd.to_numeric(opp_copy["BLK"], errors="coerce") / _opp_gp
            blk_leader = opp_copy.nlargest(1, "BPG").iloc[0]
            leaders["Blocks"] = {"name": blk_leader["name"], "value": blk_leader["BPG"], "sub": ""}
            return leaders

        def _build_season_leaders_html(uww_leaders, opp_leaders, opp_name):
            """Build broadcast-style season leaders comparison HTML."""
            if not uww_leaders or not opp_leaders:
                return ""
            categories = ["Minutes", "Points", "Rebounds", "Assists", "Steals", "Blocks"]
            rows_html = ""
            for cat in categories:
                uww_l = uww_leaders.get(cat, {})
                opp_l = opp_leaders.get(cat, {})
                if not uww_l or not opp_l:
                    continue
                uww_name = uww_l.get("name", "-")
                uww_val = uww_l.get("value", 0)
                uww_sub = uww_l.get("sub", "")
                opp_name_l = opp_l.get("name", "-")
                opp_val = opp_l.get("value", 0)
                opp_sub = opp_l.get("sub", "")
                # Shorten names: first initial + last name
                def _short(n):
                    parts = n.split()
                    if len(parts) >= 2:
                        return f"{parts[0][0]}. {parts[-1]}"
                    return n

                def _sub_html(sub_text):
                    """A "sub" value can carry multiple lines (e.g. FG% and FT% under the Points leader) joined
                    by a literal "\\n" -- escape first (so any stray "<"/">" in the underlying data still renders
                    as plain text, not markup), THEN turn newlines into real <br> line breaks, so each stat sits
                    on its own line instead of being crammed into one comma-separated line."""
                    return html.escape(sub_text).replace("\n", "<br>")

                rows_html += f'<div style="border:1px solid #eee;border-radius:8px;padding:12px 14px;margin-bottom:8px;"><div style="display:flex;align-items:center;justify-content:space-between;"><div style="text-align:left;flex:1;"><div style="font-weight:700;font-size:1rem;">{html.escape(_short(uww_name))}</div><div style="font-size:0.85rem;color:#888;line-height:1.4;">{_sub_html(uww_sub)}</div></div><div style="text-align:center;flex:1;"><div style="font-size:1.15rem;font-weight:700;">{uww_val:.1f}<span style="font-size:0.85rem;color:#666;margin:0 8px;">{cat}</span>{opp_val:.1f}</div></div><div style="text-align:right;flex:1;"><div style="font-weight:700;font-size:1rem;">{html.escape(_short(opp_name_l))}</div><div style="font-size:0.85rem;color:#888;line-height:1.4;">{_sub_html(opp_sub)}</div></div></div></div>'
            return f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;flex:1;width:100%;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;margin-bottom:8px;">SEASON LEADERS</div><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px;"><span style="font-size:0.95rem;font-weight:700;color:#4E2A84;">UWW</span><span style="font-size:0.85rem;color:#888;">Avg. Per Game</span><span style="font-size:0.95rem;font-weight:700;color:#222;">{html.escape(get_team_abbreviation(opp_name))}</span></div>{rows_html}</div>'

        uww_leaders = _get_uww_leaders(box, played)
        opp_leaders = _get_opp_leaders(opp_profiles_ts, short_opponent, games_est=get_opponent_games_played(short_opponent))

        # Render: Season Leaders | Team Stats | Last Five Games
        leaders_html = _build_season_leaders_html(uww_leaders, opp_leaders, opp_display)
        stats_html = _build_team_stats_html(uww_team_stats, opp_team_stats, opp_display) if uww_team_stats and opp_team_stats else ""

        def _l5_button_label(_g, _short_names=None):
            """Same information, same shape as the read-only result cards above: date on top and
            dimmed, opponent below it, result and score last in win/loss colour.

            The opponent is shown by its SCOUTING short name where one exists ("UW-La Crosse"
            rather than "UW-La Crosse Eagles") -- these cards are half a narrow column wide, and
            the mascot is the part a coach doesn't need. Only if no short name matches does the
            full name get used, and then it wraps rather than being cut off."""
            _res = str(_g.get("outcome", ""))
            _score = (f"{int(_g['team_score'])}-{int(_g['opp_score'])}"
                      if _g.get("team_score") is not None and _g.get("opp_score") is not None else "")
            _loc = "@" if "away" in str(_g.get("location", "")).lower() else "vs"
            _name = str(_g.get("opp_name", "") or "")
            # The "short names" in the box-score tables still carry the mascot ("UW-La Crosse
            # Eagles"), so strip it after resolving -- the school alone is what identifies the game.
            _short = resolve_short_opponent(_name, _short_names) if _short_names else None
            _name = strip_team_mascot(_short or _name)
            _date = str(_g.get("date", "") or "").strip()
            _res_md = f":green[**{_res}**]" if _res == "W" else f":red[**{_res}**]"
            # Date first, dimmed, then the result -- reading order matches how a coach scans a
            # schedule (when, then what happened), and the score keeps its own line at the bottom
            # where the eye lands last.
            _lines = []
            if _date:
                _lines.append(f":gray[{_date}]")
            _lines.append(f"{_loc} {_name}")
            _lines.append(f"{_res_md} **{_score}**")
            return "  \n".join(_lines)

        @st.dialog("Game Detail", width="large")
        def _show_last5_game_dialog(_game_key, _game_label, _source_table="uww_pbp_box_score", _team_a_hint="UW-Whitewater", _game_date=None):
            """Full box score + a simple team-stats comparison for one specific past game -- triggered by
            clicking a result in the Last Five Games list, either UWW's own (_source_table="uww_pbp_box_score",
            keyed by the opponent they played) or the upcoming opponent's own prior-game result
            (_source_table="uww_opponent_prior_games_box_score", keyed by whoever THEY played that game --
            reconstructed from the same shot-by-shot video-tagged data already collected for the shot-
            selection analysis, not a separate live-scrape)."""
            st.markdown(f"#### {_game_label}")
            if not _game_key:
                # This isn't a name-matching bug -- it means no game in _source_table matched this opponent
                # at all, which happens when no local/live-scraped PBP data was ever collected for this
                # specific game (confirmed case: missing FastScout credentials + no local backup file). Same
                # underlying situation as the "empty box score" case below, just caught one step earlier.
                st.info("No box score data collected yet for this game -- no local or live-scraped play-by-play was available for it.")
                return
            _gd_box_all = load_table(_source_table)
            _gd_game_box = _gd_box_all[_gd_box_all["opponent"] == _game_key] if not _gd_box_all.empty else pd.DataFrame()
            # Narrow to the one meeting that was clicked -- without this, a home-and-home shows both games'
            # rows stacked, so every player appears twice.
            if _game_date and not _gd_game_box.empty and "game_date" in _gd_game_box.columns:
                _gd_same_date = _gd_game_box[_gd_game_box["game_date"].astype(str).str[:10] == _game_date]
                if not _gd_same_date.empty:
                    _gd_game_box = _gd_same_date
            if _gd_game_box.empty:
                st.warning("No reconstructed box score found for this game yet.")
                return
            _gd_teams = sorted(_gd_game_box["team"].dropna().unique().tolist())
            if _team_a_hint in _gd_teams:
                _team_a = _team_a_hint
                _team_b = next((t for t in _gd_teams if t != _team_a), _team_a)
            else:
                _team_a = _gd_teams[0] if _gd_teams else _team_a_hint
                _team_b = _gd_teams[1] if len(_gd_teams) > 1 else _team_a
            _gd_uww_side = _gd_game_box[_gd_game_box["team"] == _team_a]
            _gd_opp_side = _gd_game_box[_gd_game_box["team"] == _team_b]

            st.markdown("**Team Stats**")
            # One row per TEAM, one column per stat -- the same orientation as every box score on the page
            # (and as the two player tables directly below), instead of a tall two-column list that read
            # nothing like its neighbours and made the two teams hard to compare at a glance.
            _gd_stat_cols = [c for c in ["PTS", "REB", "AST", "STL", "BLK", "TO", "PF"] if c in _gd_game_box.columns]
            _gd_team_rows = []
            for _gd_label, _gd_side in ((_team_a, _gd_uww_side), (_team_b, _gd_opp_side)):
                _row = {"Team": _gd_label}
                for _sc in _gd_stat_cols:
                    _val = _gd_side[_sc].sum()
                    _row[_sc] = int(_val) if float(_val).is_integer() else round(float(_val), 1)
                if {"FGM", "FGA"} <= set(_gd_game_box.columns):
                    _m, _a = _gd_side["FGM"].sum(), _gd_side["FGA"].sum()
                    _row["FG"] = f"{int(_m)}-{int(_a)}"
                    _row["FG%"] = round(100 * _m / _a, 1) if _a else None
                if {"FG3M", "FG3A"} <= set(_gd_game_box.columns):
                    _m3, _a3 = _gd_side["FG3M"].sum(), _gd_side["FG3A"].sum()
                    _row["3P"] = f"{int(_m3)}-{int(_a3)}"
                    _row["3P%"] = round(100 * _m3 / _a3, 1) if _a3 else None
                if {"FTM", "FTA"} <= set(_gd_game_box.columns):
                    _mf, _af = _gd_side["FTM"].sum(), _gd_side["FTA"].sum()
                    _row["FT"] = f"{int(_mf)}-{int(_af)}"
                    _row["FT%"] = round(100 * _mf / _af, 1) if _af else None
                if {"FGA", "OREB", "TO", "FTA"} <= set(_gd_game_box.columns):
                    _row["Poss"] = round(estimate_possessions(
                        _gd_side["FGA"].sum(), _gd_side["OREB"].sum(), _gd_side["TO"].sum(), _gd_side["FTA"].sum()
                    ), 1)
                _gd_team_rows.append(_row)
            _gd_team_df = pd.DataFrame(_gd_team_rows)
            _gd_order = ["Team", "PTS", "Poss", "FG", "FG%", "3P", "3P%", "FT", "FT%", "REB", "AST", "STL", "BLK", "TO", "PF"]
            _gd_team_df = _gd_team_df[[c for c in _gd_order if c in _gd_team_df.columns]]
            st.dataframe(
                _gd_team_df, hide_index=True, use_container_width=True,
                column_config={_c: st.column_config.NumberColumn(_c, format="%.1f%%")
                               for _c in ("FG%", "3P%", "FT%") if _c in _gd_team_df.columns},
            )

            st.markdown("**Box Score**")
            # BLK sits between STL and TO to match the PTS/REB/AST/STL/BLK/TO order used by the Team Stats
            # rows just above and by full_cols in the Previous Games box score -- both box-score tables
            # (uww_pbp_box_score and uww_opponent_prior_games_box_score) carry a per-player BLK column.
            _gd_compact_cols = [c for c in ["player", "MIN", "PTS", "REB", "AST", "STL", "BLK", "TO", "FG%"] if c in _gd_game_box.columns]
            _gd_col1, _gd_col2 = st.columns(2)
            with _gd_col1:
                st.markdown(f"**{_team_a}**")
                _gd_uww_sorted = _gd_uww_side.sort_values("PTS", ascending=False) if "PTS" in _gd_uww_side.columns else _gd_uww_side
                st.dataframe(_gd_uww_sorted[_gd_compact_cols], hide_index=True, use_container_width=True)
            with _gd_col2:
                st.markdown(f"**{_team_b}**")
                _gd_opp_sorted = _gd_opp_side.sort_values("PTS", ascending=False) if "PTS" in _gd_opp_side.columns else _gd_opp_side
                st.dataframe(_gd_opp_sorted[_gd_compact_cols], hide_index=True, use_container_width=True)

        # Short opponent names to resolve each Last Five Games entry's full schedule name (e.g. "Ripon Red
        # Hawks") down to the short name uww_pbp_box_score keys its rows by (e.g. "Ripon Red Hawks" or
        # "Ripon") -- same resolve_short_opponent pattern used throughout this file.
        _l5_short_names = load_table("uww_pbp_box_score")["opponent"].unique().tolist()
        _l5_short_names.sort(key=len, reverse=True)
        # Same idea for the upcoming opponent's OWN prior-game results -- uww_opponent_prior_games_box_score
        # keys each game by whichever THIRD PARTY they played (not by short_opponent itself), reconstructed
        # from the same shot-by-shot data already collected for the shot-selection analysis.
        _l5_opp_short_names = load_table("uww_opponent_prior_games_box_score")["opponent"].unique().tolist()
        _l5_opp_short_names.sort(key=len, reverse=True)

        # All Stats dialog (full team comparison including TENDENCIES stats)
        @st.dialog("ALL STATS", width="large")
        def _show_all_stats_dialog():
            _all_stat_order = ["Points", "Points Against", "FG%", "3P%", "FT%", "Rebounds", "Assists", "Turnovers", "A:TO Ratio", "Steals", "Blocks", "Stocks", "3PA/game", "FTA/game"]
            _uww_full = uww_team_stats_full if uww_team_stats_full else uww_team_stats
            _opp_full = opp_team_stats_full if opp_team_stats_full else opp_team_stats
            rows_html = ""
            for stat in _all_stat_order:
                uww_val = _uww_full.get(stat, 0)
                opp_val = _opp_full.get(stat, 0)
                if uww_val == 0 and opp_val == 0:
                    continue
                is_pct = "%" in stat or "Ratio" in stat
                max_val = max(uww_val, opp_val, 0.1)
                uww_bar_pct = uww_val / max_val * 100
                opp_bar_pct = opp_val / max_val * 100
                if stat in ("Points Against", "Turnovers"):
                    uww_bold = "font-weight:800;" if uww_val < opp_val else ""
                    opp_bold = "font-weight:800;" if opp_val < uww_val else ""
                else:
                    uww_bold = "font-weight:800;" if uww_val > opp_val else ""
                    opp_bold = "font-weight:800;" if opp_val > uww_val else ""
                if is_pct:
                    uww_fmt = f"{uww_val:.1f}{'%' if '%' in stat else ''}"
                    opp_fmt = f"{opp_val:.1f}{'%' if '%' in stat else ''}"
                else:
                    uww_fmt = f"{uww_val:.1f}"
                    opp_fmt = f"{opp_val:.1f}"
                if "Ratio" in stat:
                    uww_fmt = f"{uww_val:.2f}"
                    opp_fmt = f"{opp_val:.2f}"
                rows_html += f'<div style="padding:10px 0;border-bottom:1px solid #eee;"><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;"><span style="font-size:1.2rem;{uww_bold}width:70px;">{uww_fmt}</span><span style="font-size:0.95rem;color:#666;font-weight:600;text-transform:uppercase;flex:1;text-align:center;">{stat}</span><span style="font-size:1.2rem;{opp_bold}width:70px;text-align:right;">{opp_fmt}</span></div><div style="display:flex;gap:4px;height:6px;"><div style="flex:1;display:flex;justify-content:flex-end;"><div style="width:{uww_bar_pct:.0f}%;background:#4E2A84;border-radius:3px;height:100%;"></div></div><div style="flex:1;display:flex;justify-content:flex-start;"><div style="width:{opp_bar_pct:.0f}%;background:#222;border-radius:3px;height:100%;"></div></div></div></div>\n'
            all_html = f'<div style="padding:8px 4px;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding:0 4px;"><span style="font-size:1.1rem;font-weight:700;color:#4E2A84;">UWW</span><span style="font-size:1.1rem;font-weight:700;color:#222;">{html.escape(get_team_abbreviation(opp_display))}</span></div>{rows_html}</div>'
            st.markdown(all_html, unsafe_allow_html=True)

        # All Games dialog
        @st.dialog("ALL GAMES", width="large")
        def _show_all_games_dialog():
            def _game_cell_dlg(r):
                if r is None:
                    return '<div style="font-size:0.95rem;color:#aaa;">\u2014</div>'
                loc_prefix = "@ " if "away" in str(r.get("location", "")).lower() else "vs "
                result_color = "#2e7d32" if r["outcome"] == "W" else "#c62828"
                score_str = f"{int(r['team_score'])}-{int(r['opp_score'])}" if r.get("team_score") is not None else ""
                opp_short = str(r.get("opp_name", ""))
                if len(opp_short) > 22:
                    opp_short = opp_short[:20] + "..."
                date_str = str(r.get("date", ""))
                return (
                    f'<div style="font-size:0.75rem;color:#999;margin-bottom:2px;">{html.escape(date_str)}</div>'
                    f'<div style="font-weight:600;font-size:0.95rem;">'
                    f'<span style="color:{result_color};font-weight:700;">{r["outcome"]}</span> {score_str}</div>'
                    f'<div style="font-size:0.8rem;color:#888;">{loc_prefix}{html.escape(opp_short)}</div>'
                )
            header_html = (
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding:0 4px;">'
                f'<span style="font-size:1.05rem;font-weight:700;color:#4E2A84;">UWW ({len(uww_all_games)} games)</span>'
                f'<span style="font-size:1.05rem;font-weight:700;color:#222;">{html.escape(get_team_abbreviation(opp_display))} ({len(opp_all_games)} games)</span>'
                f'</div>'
            )
            st.markdown(header_html, unsafe_allow_html=True)
            st.caption("Click any game for its box score.")

            # Every game here is clickable, same as the five on the page behind this dialog. Streamlit
            # allows only ONE dialog open at a time, so a click can't call the Game Detail dialog directly
            # from in here -- it records what was clicked in session state and reruns, which closes this
            # dialog; the pending request is picked up on that rerun (see the block after this function)
            # and opens Game Detail then.
            _ag_max = max(len(uww_all_games), len(opp_all_games), 1)
            for _ag_i in range(_ag_max):
                _ag_u = uww_all_games[_ag_i] if _ag_i < len(uww_all_games) else None
                _ag_o = opp_all_games[_ag_i] if _ag_i < len(opp_all_games) else None
                _ag_c1, _ag_c2 = st.columns(2)
                with _ag_c1:
                    if _ag_u is not None:
                        if st.button(_l5_button_label(_ag_u, _l5_short_names), key=f"l5_all_uww_{_ag_i}",
                                     use_container_width=True):
                            st.session_state["_pending_game_detail"] = {
                                "game_key": resolve_short_opponent(_ag_u["opp_name"], _l5_short_names),
                                "label": f"UWW vs {_ag_u['opp_name']} \u2014 {_ag_u.get('date', '')}",
                                "game_date": resolve_game_date(_ag_u.get("date")),
                            }
                            st.rerun()
                    else:
                        st.caption("\u2014")
                with _ag_c2:
                    if _ag_o is not None:
                        if st.button(_l5_button_label(_ag_o, _l5_opp_short_names), key=f"l5_all_opp_{_ag_i}",
                                     use_container_width=True):
                            st.session_state["_pending_game_detail"] = {
                                "game_key": resolve_short_opponent(_ag_o["opp_name"], _l5_opp_short_names),
                                "label": f"{short_opponent} vs {_ag_o['opp_name']} \u2014 {_ag_o.get('date', '')}",
                                "source_table": "uww_opponent_prior_games_box_score",
                                "team_a_hint": short_opponent,
                            }
                            st.rerun()
                    else:
                        st.caption("\u2014")

        # A game clicked inside the All Games dialog can't open Game Detail from in there (Streamlit allows
        # one dialog at a time), so it parks the request in session state and reruns. This is that rerun:
        # pop the request and open Game Detail for it. Popped BEFORE the call so a rerun triggered from
        # inside Game Detail itself doesn't reopen it in a loop.
        _pending_detail = st.session_state.pop("_pending_game_detail", None)
        if _pending_detail:
            _show_last5_game_dialog(
                _pending_detail.get("game_key"),
                _pending_detail.get("label", "Game Detail"),
                _source_table=_pending_detail.get("source_table", "uww_pbp_box_score"),
                _team_a_hint=_pending_detail.get("team_a_hint", "UW-Whitewater"),
                _game_date=_pending_detail.get("game_date"),
            )

        # Three columns: Season Leaders | Team Stats + All Stats button | Last Five Games
        _col_leaders, _col_stats, _col_l5 = st.columns(3)
        with _col_leaders:
            st.markdown(leaders_html, unsafe_allow_html=True)
        with _col_stats:
            with st.container(border=True):
                # Strip outer border from stats_html since container provides it
                import re as _re_stats
                _stats_inner = _re_stats.sub(
                    r'^<div style="border:1px solid #e0e0e0;border-radius:8px;padding:16px 18px;flex:1;width:100%;">',
                    '<div style="width:100%;">',
                    stats_html, count=1
                )
                st.markdown(_stats_inner, unsafe_allow_html=True)
                if st.button("\U0001f4ca All Stats", key="all_stats_btn", use_container_width=True):
                    _show_all_stats_dialog()
        with _col_l5:
            with st.container(border=True):
                st.markdown('<div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;margin-bottom:8px;">LAST FIVE GAMES</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;padding:0 2px;">'
                    f'<span style="font-size:0.85rem;font-weight:700;color:#4E2A84;">UWW</span>'
                    f'<span style="font-size:0.85rem;font-weight:700;color:#222;">{html.escape(get_team_abbreviation(opp_display))}</span>'
                    f'</div>', unsafe_allow_html=True,
                )
                # The clickable version of this panel used bare st.buttons, which render as generic grey
                # pills with centre-aligned, truncated text -- nothing like the bordered result cards the
                # rest of the page uses. Streamlit tags each widget's container with an "st-key-<key>"
                # class, so the buttons can be restyled to match those cards while staying real buttons
                # (a styled div can't open the box-score dialog). Purely cosmetic: if a Streamlit version
                # ever drops that class the buttons simply look default again.
                st.markdown("""
                <style>
                div[class*="st-key-l5_"] button {
                    border: 1px solid #e8e8e8 !important;
                    border-radius: 8px !important;
                    background: #fff !important;
                    padding: 10px 12px !important;
                    min-height: 0 !important;
                    text-align: left !important;
                    justify-content: flex-start !important;
                    line-height: 1.35 !important;
                    transition: border-color .12s ease, box-shadow .12s ease;
                }
                div[class*="st-key-l5_"] button:hover {
                    border-color: #4E2A84 !important;
                    box-shadow: 0 1px 4px rgba(78,42,132,.14) !important;
                }
                div[class*="st-key-l5_"] button p {
                    text-align: left !important;
                    margin: 0 !important;
                    font-size: 0.95rem !important;
                    /* Streamlit's default button label is a single no-wrap line with an ellipsis, which is
                       what was cutting "UW-La Crosse Eagles" down to "UW-La Crosse Eagl...". Let it wrap
                       and give the card room to grow instead of hiding the name. */
                    white-space: normal !important;
                    overflow: visible !important;
                    text-overflow: clip !important;
                    overflow-wrap: anywhere !important;
                }
                div[class*="st-key-l5_"] button > div,
                div[class*="st-key-l5_"] button > div > div {
                    white-space: normal !important;
                    overflow: visible !important;
                    text-overflow: clip !important;
                }
                div[class*="st-key-all_games_btn"] button {
                    border: 1px dashed #cfc7dd !important;
                    border-radius: 8px !important;
                    background: #faf8fd !important;
                    color: #4E2A84 !important;
                    font-weight: 700 !important;
                }
                </style>
                """, unsafe_allow_html=True)


                _l5_max = max(len(uww_last5), len(opp_last5), 1)
                if _l5_max == 0 or (not uww_last5 and not opp_last5):
                    st.caption("No games available")
                for _l5_i in range(min(_l5_max, 5)):
                    _u_game = uww_last5[_l5_i] if _l5_i < len(uww_last5) else None
                    _o_game = opp_last5[_l5_i] if _l5_i < len(opp_last5) else None
                    _l5_c1, _l5_c2 = st.columns(2)
                    with _l5_c1:
                        if _u_game is not None:
                            if st.button(_l5_button_label(_u_game, _l5_short_names), key=f"l5_uww_btn_{_l5_i}", use_container_width=True):
                                _u_short = resolve_short_opponent(_u_game["opp_name"], _l5_short_names)
                                _show_last5_game_dialog(
                                    _u_short, f"UWW vs {_u_game['opp_name']} \u2014 {_u_game.get('date', '')}",
                                    _game_date=resolve_game_date(_u_game.get("date")),
                                )
                        else:
                            st.caption("\u2014")
                    with _l5_c2:
                        if _o_game is not None:
                            # Now reconstructed from the same shot-by-shot data already collected for the
                            # shot-selection analysis (uww_opponent_prior_games_box_score), not a separate
                            # live-scrape -- so these ARE clickable now, same as UWW's own results, wherever
                            # that reconstruction actually found data for this specific game.
                            _o_third_party_short = resolve_short_opponent(_o_game["opp_name"], _l5_opp_short_names)
                            if st.button(_l5_button_label(_o_game, _l5_opp_short_names), key=f"l5_opp_btn_{_l5_i}", use_container_width=True):
                                _show_last5_game_dialog(
                                    _o_third_party_short, f"{short_opponent} vs {_o_game['opp_name']} \u2014 {_o_game.get('date', '')}",
                                    _source_table="uww_opponent_prior_games_box_score", _team_a_hint=short_opponent,
                                )
                        else:
                            st.caption("\u2014")
                if st.button("\U0001f4c5 All Games", key="all_games_btn", use_container_width=True):
                    _show_all_games_dialog()

        # Previous matchup callout
        prev_matchups = played[played["opponent"].str.contains(short_opponent or "__NOMATCH__", case=False, na=False)] if short_opponent else pd.DataFrame()
        if not prev_matchups.empty:
            st.markdown(f"**Previous matchup vs {short_opponent}:**")
            for _, pm in prev_matchups.iterrows():
                outcome_emoji = "\u2705" if pm["outcome"] == "W" else "\u274c"
                score_str = f"{int(pm['team_score'])}-{int(pm['opponent_score'])}" if pd.notna(pm.get("team_score")) else ""
                margin = f" ({pm['point_margin']:+.0f})" if pd.notna(pm.get("point_margin")) else ""
                st.markdown(f"{outcome_emoji} {pm['date']} \u2014 **{pm['outcome']} {score_str}**{margin} ({pm['location']})")


    if short_opponent is None:
        st.warning(f"No scouting report, roster, or game-plan data has been parsed yet for {full_opponent}.")
        return

    # ==================== TOP 5-MAN LINEUPS SECTION ====================
    def _last_names(lineup_str):
        """Convert 'First Last, First Last, ...' to 'Last, Last, ...' for compact display.

        The scoring-runs table can hold TWO lineups in one field joined by " / " (the parser records every
        unit seen across a run's event window, so a substitution mid-run produces two). Split on that first
        and de-duplicate, otherwise the naive comma split rendered nine names with four repeated -- e.g.
        "Marino, Madson, Verges, Quast, Marino, Madson, Verges, Quast, Bara".
        """
        _units = [u for u in str(lineup_str).split(" / ") if u.strip()]
        _names, _seen = [], set()
        for _u in _units:
            for _n in _u.split(","):
                _sn = surname(_n)
                if _sn and _sn not in _seen:
                    _seen.add(_sn)
                    _names.append(_sn)
        return ", ".join(_names)

    def _get_core_players(all_top_players_list):
        """Return list of (player, count) for players in 2+ of the 3 metric top-3 lists."""
        from collections import Counter
        player_counts = Counter()
        for pset in all_top_players_list:
            for p in pset:
                player_counts[p] += 1
        return sorted([(p, c) for p, c in player_counts.items() if c >= 2], key=lambda x: -x[1])

    def _find_core_players(df_sorted, top_n=3):
        """Return set of player last names appearing in the top N lineups."""
        top = df_sorted.head(top_n)
        players = set()
        for _, row in top.iterrows():
            for n in str(row["lineup"]).split(","):
                if n.strip():
                    players.add(surname(n))
        return players

    def _build_lineup_rows_html(df_sorted, metric_col, min_col="MIN"):
        """Build HTML for top 3 lineups for one metric, showing per-minute rates."""
        top3 = df_sorted.head(3)
        rows = ""
        for rank, (_, row) in enumerate(top3.iterrows(), 1):
            lineup_short = _last_names(row["lineup"])
            val = row[metric_col]
            mins = row[min_col] if min_col and min_col in row.index and row[min_col] > 0 else None
            if metric_col == "EFF":
                val_str = f"{val:+.3f}/min"
                total_pm = row["+/-"] if "+/-" in row.index else None
                rate_str = f"<span style='color:#777;font-size:0.75rem;'> ({total_pm:+.0f} total)</span>" if total_pm is not None else ""
            elif metric_col == "+/-":
                val_str = f"{val:+.1f}"
                rate_str = f"<span style='color:#777;font-size:0.75rem;'> ({val/mins:+.2f}/min)</span>" if mins else ""
            elif metric_col == "MIN":
                val_str = f"{val:.1f}"
                gp = row["GP"] if "GP" in row.index and row["GP"] > 0 else None
                rate_str = f"<span style='color:#777;font-size:0.75rem;'> ({val/gp:.1f}/gm)</span>" if gp else ""
            else:
                val_str = f"{val:.1f}"
                rate_str = f"<span style='color:#777;font-size:0.75rem;'> ({val/mins:.2f}/min)</span>" if mins else ""
            rows += f'<div style="font-size:0.82rem;margin:2px 0;"><strong>{val_str}</strong>{rate_str} \u2014 {html.escape(lineup_short)}</div>'
        return rows if rows else '<div style="font-size:0.82rem;color:#aaa;">No data</div>'

    def _build_lineups_card_html(uww_agg, opp_lu, opp_name):
        """Build broadcast-style TOP 5-MAN LINEUPS card matching Season Leaders layout."""
        metrics = [("MIN", "By Minutes"), ("PTS", "By Points"), ("+/-", "By +/\u2212"), ("EFF", "By Efficiency Rating")]
        rows_html = ""
        for metric_col, label in metrics:
            # Sort by rate: MIN→per game, EFF→net per min (min 3 min), others→per minute
            if uww_agg is not None and not uww_agg.empty:
                if metric_col == "MIN":
                    # "Top lineups by minutes" means MOST USED, so rank on the season total. Ranking on MIN/GP
                    # let a unit that shared the floor for one blowout outrank the starting five's
                    # entire season (12.6 min in 1 game placed above 203.0 min across 21). The
                    # per-game figure still prints alongside as context.
                    _uww_s = uww_agg.assign(_r=uww_agg["MIN"])
                elif metric_col == "EFF":
                    _uww_s = uww_agg[uww_agg["MIN"] >= 3.0].copy()
                    _uww_s["EFF"] = (_uww_s["+/-"] / _uww_s["MIN"].replace(0, float('nan'))).round(3)
                    _uww_s = _uww_s.assign(_r=_uww_s["EFF"])
                else:
                    # PTS and +/- rank on the season TOTAL, matching By Minutes. Ranking on value/MIN put
                    # sub-minute stints on top -- 4 points in 0.12 min read as "33.33/min" and
                    # outranked the starting five's whole season. The rate still prints as context.
                    _uww_s = uww_agg.assign(_r=uww_agg[metric_col])
                uww_rows = _build_lineup_rows_html(_uww_s.sort_values("_r", ascending=False).drop(columns=["_r"]), metric_col, min_col="MIN")
            else:
                uww_rows = '<div style="font-size:0.82rem;color:#aaa;">No data</div>'
            if opp_lu is not None and not opp_lu.empty:
                if metric_col == "MIN":
                    _opp_s = opp_lu.assign(_r=opp_lu["MIN"])
                elif metric_col == "EFF":
                    _opp_s = opp_lu[opp_lu["MIN"] >= 3.0].copy()
                    _opp_s["EFF"] = (_opp_s["+/-"] / _opp_s["MIN"].replace(0, float('nan'))).round(3)
                    _opp_s = _opp_s.assign(_r=_opp_s["EFF"])
                else:
                    _opp_s = opp_lu.assign(_r=opp_lu[metric_col])
                opp_rows = _build_lineup_rows_html(_opp_s.sort_values("_r", ascending=False).drop(columns=["_r"]), metric_col, min_col="MIN")
            else:
                opp_rows = '<div style="font-size:0.82rem;color:#aaa;">No data</div>'
            rows_html += (
                f'<div style="border:1px solid #eee;border-radius:8px;padding:10px 14px;margin-bottom:8px;">'
                f'<div style="text-align:center;font-size:0.85rem;font-weight:700;color:#555;margin-bottom:6px;">{label}</div>'
                f'<div style="display:flex;gap:16px;">'
                f'<div style="flex:1;">{uww_rows}</div>'
                f'<div style="flex:1;text-align:right;">{opp_rows}</div>'
                f'</div></div>'
            )

        return (
            f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;width:100%;margin:1.5rem 0 0.75rem;">'
            f'<div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;margin-bottom:8px;">TOP 5-MAN LINEUPS</div>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px;">'
            f'<span style="font-size:0.95rem;font-weight:700;color:#4E2A84;">UWW</span>'
            f'<span style="font-size:0.85rem;color:#888;">Season Totals</span>'
            f'<span style="font-size:0.95rem;font-weight:700;color:#222;">{html.escape(get_team_abbreviation(opp_name))}</span>'
            f'</div>{rows_html}</div>'
        )

    # Compute UWW lineup aggregates
    _stints = load_table("uww_lineup_stints")
    _uww_lu_agg = None
    if not _stints.empty:
        # Only include games before the upcoming game (by date), and exclude Aurora (lineup columns swapped)
        _stints = scope_to_played(_stints, played)
        _stints = _stints[_stints["opponent"] != "Aurora"].copy()
        _stints["uww_pts"] = _stints["end_uww_score"] - _stints["start_prev_uww_score"]
        _uww_lu_agg = _stints.groupby("uww_lineup").agg(
            MIN=("stint_minutes", "sum"),
            PTS=("uww_pts", "sum"),
            plus_minus=("uww_margin_change", "sum"),
            GP=("game_date", "nunique")
        ).reset_index().rename(columns={"uww_lineup": "lineup", "plus_minus": "+/-"})

    # Compute opponent lineup data (validate it actually belongs to the current opponent)
    _opp_lu = load_table("uww_opp_lineup_season_box")
    if not _opp_lu.empty and "MIN" in _opp_lu.columns:
        # Validate lineup players match the current opponent's roster/profiles
        _opp_roster_names = set()
        _opp_prof = load_table("uww_player_profiles")
        if not _opp_prof.empty and short_opponent:
            _opp_roster_names = set(_opp_prof[_opp_prof["opponent"] == short_opponent]["name"].dropna())
        if not _opp_roster_names:
            _opp_rost = load_table("uww_opponent_rosters")
            if not _opp_rost.empty and short_opponent:
                _opp_roster_names = set(_opp_rost[_opp_rost["opponent"] == short_opponent]["name"].dropna())
        # Extract all player names from lineup strings and check overlap
        if _opp_roster_names and "lineup" in _opp_lu.columns:
            _lu_players = set()
            for _lu_str in _opp_lu["lineup"].dropna():
                _lu_players.update(p.strip() for p in str(_lu_str).split(","))
            _overlap = _lu_players & _opp_roster_names
            if not _overlap:
                # Lineup data belongs to a different opponent -- suppress it
                _opp_lu = None
        if _opp_lu is not None:
            for _c in ["MIN", "PTS", "+/-", "GP"]:
                if _c in _opp_lu.columns:
                    _opp_lu[_c] = pd.to_numeric(_opp_lu[_c], errors="coerce").fillna(0)
    else:
        _opp_lu = None

    _lineups_html = _build_lineups_card_html(_uww_lu_agg, _opp_lu, opp_display)

    # ==================== TOP 3-MAN COMBINATIONS SECTION ====================
    def _build_3man_card_html(uww_3man, opp_3man, opp_name):
        """Build broadcast-style TOP 3-MAN COMBINATIONS card matching 5-man lineup layout."""
        metrics = [("MIN", "By Minutes"), ("PTS", "By Points"), ("+/-", "By +/\u2212"), ("EFF", "By Efficiency Rating")]
        rows_html = ""
        for metric_col, label in metrics:
            if uww_3man is not None and not uww_3man.empty:
                if metric_col == "MIN":
                    _uww_s = uww_3man.assign(_r=uww_3man["MIN"])   # most-used: rank on the season total
                elif metric_col == "EFF":
                    _uww_s = uww_3man[uww_3man["MIN"] >= 5.0].copy()
                    _uww_s["EFF"] = (_uww_s["+/-"] / _uww_s["MIN"].replace(0, float('nan'))).round(3)
                    _uww_s = _uww_s.assign(_r=_uww_s["EFF"])
                else:
                    _uww_s = uww_3man.assign(_r=uww_3man[metric_col])   # season total, as above
                uww_rows = _build_lineup_rows_html(_uww_s.sort_values("_r", ascending=False).drop(columns=["_r"]), metric_col, min_col="MIN")
            else:
                uww_rows = '<div style="font-size:0.82rem;color:#aaa;">No data</div>'
            if opp_3man is not None and not opp_3man.empty:
                if metric_col == "MIN":
                    _opp_s = opp_3man.assign(_r=opp_3man["MIN"])   # most-used: rank on the season total
                elif metric_col == "EFF":
                    _opp_s = opp_3man[opp_3man["MIN"] >= 5.0].copy()
                    _opp_s["EFF"] = (_opp_s["+/-"] / _opp_s["MIN"].replace(0, float('nan'))).round(3)
                    _opp_s = _opp_s.assign(_r=_opp_s["EFF"])
                else:
                    _opp_s = opp_3man.assign(_r=opp_3man[metric_col])   # season total, as above
                opp_rows = _build_lineup_rows_html(_opp_s.sort_values("_r", ascending=False).drop(columns=["_r"]), metric_col, min_col="MIN")
            else:
                opp_rows = '<div style="font-size:0.82rem;color:#aaa;">No data</div>'
            rows_html += (
                f'<div style="border:1px solid #eee;border-radius:8px;padding:10px 14px;margin-bottom:8px;">'
                f'<div style="text-align:center;font-size:0.85rem;font-weight:700;color:#555;margin-bottom:6px;">{label}</div>'
                f'<div style="display:flex;gap:16px;">'
                f'<div style="flex:1;">{uww_rows}</div>'
                f'<div style="flex:1;text-align:right;">{opp_rows}</div>'
                f'</div></div>'
            )
        # Core players footer
        uww_core_html = ""
        opp_core_html = ""
        if uww_3man is not None and not uww_3man.empty:
            _uww_eff_3 = uww_3man[uww_3man["MIN"] >= 5.0].copy()
            _uww_eff_3["EFF"] = _uww_eff_3["+/-"] / _uww_eff_3["MIN"].replace(0, float('nan'))
            uww_tops = [
                _find_core_players(uww_3man.sort_values("MIN", ascending=False)),
                _find_core_players(uww_3man.sort_values("PTS", ascending=False)),
                _find_core_players(uww_3man.sort_values("+/-", ascending=False)),
                _find_core_players(_uww_eff_3.sort_values("EFF", ascending=False)),
            ]
            uww_core = _get_core_players(uww_tops)
            if uww_core:
                uww_core_html = ", ".join(f"<strong>{html.escape(p)}</strong> ({c}/4)" for p, c in uww_core)
        if opp_3man is not None and not opp_3man.empty:
            _opp_eff_3 = opp_3man[opp_3man["MIN"] >= 5.0].copy()
            _opp_eff_3["EFF"] = _opp_eff_3["+/-"] / _opp_eff_3["MIN"].replace(0, float('nan'))
            opp_tops = [
                _find_core_players(opp_3man.sort_values("MIN", ascending=False)),
                _find_core_players(opp_3man.sort_values("PTS", ascending=False)),
                _find_core_players(opp_3man.sort_values("+/-", ascending=False)),
                _find_core_players(_opp_eff_3.sort_values("EFF", ascending=False)),
            ]
            opp_core = _get_core_players(opp_tops)
            if opp_core:
                opp_core_html = ", ".join(f"<strong>{html.escape(p)}</strong> ({c}/4)" for p, c in opp_core)
        if uww_core_html or opp_core_html:
            rows_html += (
                f'<div style="border-top:1px solid #eee;padding-top:8px;margin-top:4px;display:flex;gap:16px;">'
                f'<div style="flex:1;font-size:0.8rem;"><span style="color:#4E2A84;font-weight:700;">Core:</span> {uww_core_html}</div>'
                f'<div style="flex:1;font-size:0.8rem;text-align:right;"><span style="color:#222;font-weight:700;">Core:</span> {opp_core_html}</div>'
                f'</div>'
            )
        return (
            f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;width:100%;margin:1.5rem 0 0.75rem;">'
            f'<div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;margin-bottom:8px;">TOP 3-MAN COMBINATIONS</div>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px;">'
            f'<span style="font-size:0.95rem;font-weight:700;color:#4E2A84;">UWW</span>'
            f'<span style="font-size:0.85rem;color:#888;">Season Totals</span>'
            f'<span style="font-size:0.95rem;font-weight:700;color:#222;">{html.escape(get_team_abbreviation(opp_name))}</span>'
            f'</div>{rows_html}</div>'
        )

    # Compute UWW 3-man combination aggregates from stint data
    from itertools import combinations as _lu_combos
    _uww_3man_agg = None
    if not _stints.empty:
        _3man_records = []
        for _, _stint_row in _stints.iterrows():
            _players = sorted([p.strip() for p in str(_stint_row["uww_lineup"]).split(",")])
            _mins = _stint_row["stint_minutes"]
            _pts = _stint_row["uww_pts"] if "uww_pts" in _stint_row.index else 0
            _margin = _stint_row["uww_margin_change"]
            _opp_name_3 = _stint_row["opponent"]
            for _combo in _lu_combos(_players, 3):
                _3man_records.append({
                    "lineup": ", ".join(_combo),
                    "stint_minutes": _mins,
                    "uww_pts": _pts,
                    "uww_margin_change": _margin,
                    "opponent": _opp_name_3,
                    "game_date": _stint_row.get("game_date"),
                })
        if _3man_records:
            _3man_df = pd.DataFrame(_3man_records)
            _uww_3man_agg = _3man_df.groupby("lineup").agg(
                MIN=("stint_minutes", "sum"),
                PTS=("uww_pts", "sum"),
                plus_minus=("uww_margin_change", "sum"),
                GP=("game_date", "nunique")
            ).reset_index().rename(columns={"plus_minus": "+/-"})

    # Compute opponent 3-man combination aggregates
    _opp_3man_agg = None
    if _opp_lu is not None and not _opp_lu.empty:
        _opp_3man_records = []
        for _, _opp_row_3 in _opp_lu.iterrows():
            _opp_players_3 = sorted([p.strip() for p in str(_opp_row_3["lineup"]).split(",")])
            if len(_opp_players_3) >= 3:
                _o_mins = float(_opp_row_3["MIN"]) if pd.notna(_opp_row_3["MIN"]) else 0
                _o_pts = float(_opp_row_3["PTS"]) if pd.notna(_opp_row_3["PTS"]) else 0
                _o_pm = float(_opp_row_3["+/-"]) if pd.notna(_opp_row_3["+/-"]) else 0
                _o_gp = float(_opp_row_3["GP"]) if "GP" in _opp_row_3.index and pd.notna(_opp_row_3["GP"]) else 1
                for _combo in _lu_combos(_opp_players_3, 3):
                    _opp_3man_records.append({
                        "lineup": ", ".join(_combo),
                        "MIN": _o_mins,
                        "PTS": _o_pts,
                        "+/-": _o_pm,
                        "GP": _o_gp,
                    })
        if _opp_3man_records:
            _opp_3man_df = pd.DataFrame(_opp_3man_records)
            _opp_3man_agg = _opp_3man_df.groupby("lineup").agg(
                MIN=("MIN", "sum"),
                PTS=("PTS", "sum"),
                plus_minus=("+/-", "sum"),
                GP=("GP", "max")
            ).reset_index().rename(columns={"plus_minus": "+/-"})

    _3man_html = _build_3man_card_html(_uww_3man_agg, _opp_3man_agg, opp_display)

    # ==================== BUILD COMBINED LAYOUT ====================
    # Combined card: both 5-man and 3-man in one card
    def _build_combined_lineups_card(uww_5man, opp_5man, uww_3man, opp_3man, opp_name):
        """Build a single card with 5-MAN and 3-MAN lineup metrics stacked."""
        metrics = [("MIN", "By Minutes"), ("PTS", "By Points"), ("+/-", "By +/\u2212"), ("EFF", "By Efficiency Rating")]

        def _metric_rows(uww_agg, opp_lu, min_thresh_eff):
            rows = ""
            for metric_col, label in metrics:
                if uww_agg is not None and not uww_agg.empty:
                    if metric_col == "MIN":
                        # "Top lineups by minutes" means MOST USED, so rank on the season total. Ranking on MIN/GP
                        # let a unit that shared the floor for one blowout outrank the starting five's
                        # entire season (12.6 min in 1 game placed above 203.0 min across 21). The
                        # per-game figure still prints alongside as context.
                        _s = uww_agg.assign(_r=uww_agg["MIN"])
                    elif metric_col == "EFF":
                        _s = uww_agg[uww_agg["MIN"] >= min_thresh_eff].copy()
                        _s["EFF"] = (_s["+/-"] / _s["MIN"].replace(0, float('nan'))).round(3)
                        _s = _s.assign(_r=_s["EFF"])
                    else:
                        _s = uww_agg.assign(_r=uww_agg[metric_col])   # season total, as above
                    uww_rows = _build_lineup_rows_html(_s.sort_values("_r", ascending=False).drop(columns=["_r"]), metric_col, min_col="MIN")
                else:
                    uww_rows = '<div style="font-size:0.82rem;color:#aaa;">No data</div>'
                if opp_lu is not None and not opp_lu.empty:
                    if metric_col == "MIN":
                        _s = opp_lu.assign(_r=opp_lu["MIN"])
                    elif metric_col == "EFF":
                        _s = opp_lu[opp_lu["MIN"] >= min_thresh_eff].copy()
                        _s["EFF"] = (_s["+/-"] / _s["MIN"].replace(0, float('nan'))).round(3)
                        _s = _s.assign(_r=_s["EFF"])
                    else:
                        _s = opp_lu.assign(_r=opp_lu[metric_col])   # season total, as above
                    opp_rows = _build_lineup_rows_html(_s.sort_values("_r", ascending=False).drop(columns=["_r"]), metric_col, min_col="MIN")
                else:
                    opp_rows = '<div style="font-size:0.82rem;color:#aaa;">No data</div>'
                rows += (
                    f'<div style="border:1px solid #eee;border-radius:8px;padding:8px 12px;margin-bottom:6px;">'
                    f'<div style="text-align:center;font-size:0.8rem;font-weight:700;color:#555;margin-bottom:4px;">{label}</div>'
                    f'<div style="display:flex;gap:12px;">'
                    f'<div style="flex:1;">{uww_rows}</div>'
                    f'<div style="flex:1;text-align:right;">{opp_rows}</div>'
                    f'</div></div>'
                )
            return rows

        # 5-MAN section
        five_rows = _metric_rows(uww_5man, opp_5man, 3.0)
        # 3-MAN section
        three_rows = _metric_rows(uww_3man, opp_3man, 5.0)

        return (
            f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;width:100%;">'
            f'<div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;margin-bottom:8px;">TOP LINEUPS</div>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px;">'
            f'<span style="font-size:0.95rem;font-weight:700;color:#4E2A84;">UWW</span>'
            f'<span style="font-size:0.85rem;color:#888;">Season Totals</span>'
            f'<span style="font-size:0.95rem;font-weight:700;color:#222;">{html.escape(get_team_abbreviation(opp_name))}</span>'
            f'</div>'
            f'<div style="font-weight:700;font-size:0.9rem;color:#4E2A84;margin:10px 0 6px;border-bottom:1px solid #e0e0e0;padding-bottom:4px;">5-MAN LINEUPS</div>'
            f'{five_rows}'
            f'<div style="font-weight:700;font-size:0.9rem;color:#4E2A84;margin:14px 0 6px;border-bottom:1px solid #e0e0e0;padding-bottom:4px;">3-MAN COMBINATIONS</div>'
            f'{three_rows}'
            f'</div>'
        )

    # The LINEUP SCOUTING panel that used to sit to the right of the lineup card is gone. Its opponent
    # vulnerabilities and counter-lineup recommendations became Keys to Victory items ("Attack ..." and
    # "Counter with ..."); its UWW Core Players list was removed with the panel.

    _combined_lineups_html = _build_combined_lineups_card(_uww_lu_agg, _opp_lu, _uww_3man_agg, _opp_3man_agg, opp_display)

    # The TOP 5-MAN LINEUPS / TOP 3-MAN COMBINATIONS toggle card that used to render here (Stats &
    # Analysis tab) is gone -- per request, this page no longer needs it now that the same
    # _uww_lu_agg/_opp_lu/_uww_3man_agg/_opp_3man_agg data is put to use as actual recommendations in
    # the Keys to Victory tab (Lineup Scouting + 3-man combo scouting items below) instead of just being
    # displayed as a leaderboard. UWW's season-wide version of this data also now lives on the Team page
    # (SEASON-WIDE 5-MAN LINEUP ANALYSIS / SEASON-WIDE 3-MAN COMBINATION ANALYSIS). _lineups_html/
    # _3man_html/_combined_lineups_html are left computed above in case a future card wants them again,
    # but nothing renders them now.

    # Scouting Report header with PDF download link
    reports_dir = os.path.join(DATA_DIR, "scouting_reports")
    report_path = None
    if os.path.isdir(reports_dir):
        for f in os.listdir(reports_dir):
            if f.lower().endswith(".pdf") and short_opponent.lower() in f.lower():
                report_path = os.path.join(reports_dir, f)
                break
    with _new_personnel_scouting_c:
        pass  # Scouting Report content (Keys to Victory, Team Strengths, Full Game Plan, PDF/export
        # buttons) is now folded into the unified Keys to Victory section up top, instead of living
        # here as its own separate tab section.



    with _new_personnel_roster_c:
        st.markdown(f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">{html.escape(short_opponent)} ROSTER</div></div>', unsafe_allow_html=True)
        rosters = load_table("uww_opponent_rosters")
        opp_roster = rosters[rosters["opponent"] == short_opponent]
        if opp_roster.empty:
            st.warning("No roster data found for this opponent yet.")
        else:
            _comp_profiles = load_table("uww_player_profiles")
            _comparisons = load_table("uww_player_comparisons")

            # Load player headshot images
            _player_img_dir = os.path.join(DATA_DIR, "player_images")
            def _get_player_img_b64(player_name):
                """Return base64-encoded player headshot or None."""
                for ext in ["png", "jpeg", "jpg"]:
                    fpath = os.path.join(_player_img_dir, f"{player_name}.{ext}")
                    if os.path.isfile(fpath):
                        import base64
                        with open(fpath, "rb") as img_f:
                            return base64.b64encode(img_f.read()).decode()
                return None

            @st.dialog("Player Details", width="large")
            def _show_player_dialog(player_name, player_row_dict):
                jersey_raw = str(player_row_dict.get("jersey_number", "")).strip()
                jersey_str = f"{'#' if not jersey_raw.startswith('#') else ''}{jersey_raw} " if jersey_raw and jersey_raw != "nan" else ""
                pos = player_row_dict.get("position", "")
                height = player_row_dict.get("height", "")
                class_yr = player_row_dict.get("class_year", "")
                info_parts = [str(x) for x in [pos, height, class_yr] if x and str(x).strip() and str(x) != "nan"]
                # Optional availability/injury status (see the roster-card comment above for how to populate it).
                _dlg_status_raw = str(player_row_dict.get("status", "")).strip()
                if _dlg_status_raw and _dlg_status_raw.lower() not in ("nan", "active", "available"):
                    st.warning(f"Status: {_dlg_status_raw}")
                _dlg_img = _get_player_img_b64(player_name)
                if _dlg_img:
                    _dlg_col_img, _dlg_col_info = st.columns([1, 3])
                    with _dlg_col_img:
                        st.markdown(f'<img src="data:image/png;base64,{_dlg_img}" style="width:100px;height:125px;object-fit:cover;border-radius:8px;">', unsafe_allow_html=True)
                    with _dlg_col_info:
                        st.markdown(f"### {jersey_str}{player_name}")
                        if info_parts:
                            st.caption(" · ".join(info_parts))
                else:
                    st.markdown(f"### {jersey_str}{player_name}")
                    if info_parts:
                        st.caption(" · ".join(info_parts))

                with st.container(border=True):
                    st.markdown("**Scouting Notes**")
                    notes = player_row_dict.get("player_notes", "")
                    keys = player_row_dict.get("keys_to_defending", "")
                    if notes and str(notes).strip() and str(notes) != "nan":
                        st.markdown(f"_{notes}_")
                    else:
                        st.caption("No player notes.")
                    if keys and str(keys).strip() and str(keys) != "nan":
                        st.markdown(f"**Keys to Defending:** {keys}")

                with st.container(border=True):
                    st.markdown("**Season Stats**")
                    player_prof = _comp_profiles[(_comp_profiles["name"] == player_name) & (_comp_profiles["opponent"] == short_opponent)]
                    if not player_prof.empty:
                        p = player_prof.iloc[0]
                        # One row, stats as columns (was one row PER stat with a "Stat"/"Avg" pair) -- reads
                        # like a box-score line instead of a tall 8-row list in a narrow dialog. PTS/REB are
                        # per game here but AST/STL/BLK/TO are season totals; printed side by side they read
                        # as one box-score line, so convert the totals to per game (by this player's own
                        # games) rather than showing four raw season sums next to four per-game figures.
                        _pd_gp = safe_float(p.get("games_played")) or (get_opponent_games_played(short_opponent) or 1)
                        _pd_season_totals = {"AST", "STL", "BLK", "TO"}
                        s_row = {}
                        for sc in ["PTS", "REB", "AST", "STL", "BLK", "TO", "FG%", "3P%"]:
                            _sv = p.get(sc)
                            if not (pd.notna(_sv) and str(_sv).strip()):
                                continue
                            _sn = safe_float(_sv) if sc in _pd_season_totals else None
                            s_row[sc] = f"{_sn / _pd_gp:.1f}" if _sn is not None and _pd_gp else str(_sv)
                        if s_row:
                            st.dataframe(pd.DataFrame([s_row]), hide_index=True, use_container_width=True)
                        else:
                            st.caption("No season stats available.")
                    else:
                        st.caption("No season stats available.")

                with st.container(border=True):
                    st.markdown("**Comparable Player**")
                    if not _comparisons.empty:
                        # Match on target_player AND target_opponent, case/whitespace-tolerantly.
                        # uww_player_comparisons is built for ONE opponent per parser run -- the most recently
                        # scouted game (see the parser's `target_opponent`) -- so a name-only match could pull
                        # a same-named player from a different team's block, and an exact-string match is
                        # brittle against roster-vs-report name spacing.
                        _cmp_key = str(player_name).strip().casefold()
                        comp_match = _comparisons[
                            (_comparisons["target_player"].astype(str).str.strip().str.casefold() == _cmp_key)
                            & (_comparisons["target_opponent"].astype(str).str.strip().str.casefold()
                               == str(short_opponent).strip().casefold())
                        ] if "target_opponent" in _comparisons.columns else _comparisons[
                            _comparisons["target_player"].astype(str).str.strip().str.casefold() == _cmp_key
                        ]
                        # The whole table targets a different opponent -- say so instead of the generic "no
                        # comparable player found", which reads as "this player has no match" and hides the
                        # real cause (the comparison cells were last run against another opponent).
                        _cmp_targets = (
                            sorted(_comparisons["target_opponent"].dropna().astype(str).unique())
                            if "target_opponent" in _comparisons.columns else []
                        )
                        if comp_match.empty and _cmp_targets and short_opponent not in _cmp_targets:
                            st.caption(
                                f"No comparison data for {short_opponent} yet -- uww_player_comparisons "
                                f"currently targets {', '.join(_cmp_targets)}. Re-run the parser's player "
                                f"comparison cells with {short_opponent} as the most recently scouted game."
                            )
                        elif not comp_match.empty:
                            comp = comp_match.iloc[0]
                            game_date = comp.get("compared_game_date", "")
                            date_str = f" — {game_date}" if pd.notna(game_date) and str(game_date).strip() else ""
                            st.markdown(
                                f"{comp['compared_player']} "
                                f"({comp['compared_position']}, {comp['compared_opponent']}{date_str})"
                            )
                            shared = []
                            if pd.notna(comp.get("shared_notes_tags")) and str(comp["shared_notes_tags"]).strip():
                                shared.append(f"Style: {comp['shared_notes_tags']}")
                            if pd.notna(comp.get("shared_keys_tags")) and str(comp["shared_keys_tags"]).strip():
                                shared.append(f"Defense: {comp['shared_keys_tags']}")
                            if shared:
                                st.caption(" | ".join(shared))
                            box_score = load_table("uww_pbp_box_score")
                            comp_name = comp["compared_player"]
                            comp_opp = comp["compared_opponent"]
                            game_row = box_score[(box_score["player"] == comp_name) & (box_score["team"] == comp_opp)]
                            season_row = _comp_profiles[(_comp_profiles["name"] == comp_name) & (_comp_profiles["opponent"] == comp_opp)]
                            if not game_row.empty and not season_row.empty:
                                g = game_row.iloc[0]
                                s = season_row.iloc[0]
                                perf_cols = ["PTS", "REB", "AST", "STL", "BLK", "TO"]
                                perf_data = []
                                for sc in perf_cols:
                                    gval, sval = g.get(sc), s.get(sc)
                                    if pd.notna(gval) and pd.notna(sval):
                                        try:
                                            gv, sv = float(gval), float(sval)
                                            diff = gv - sv
                                            perf_data.append({"Stat": sc, "vs UWW": f"{gv:.0f}", "Avg": f"{sv:.1f}", "+/-": f"{diff:+.1f}" if diff != 0 else "0"})
                                        except (ValueError, TypeError):
                                            pass
                                if perf_data:
                                    st.caption(f"{comp_name} vs UWW:")
                                    st.dataframe(pd.DataFrame(perf_data), hide_index=True, use_container_width=True)
                            elif not season_row.empty:
                                s = season_row.iloc[0]
                                st.caption(f"Season avg: {s.get('PTS', '-')} PTS, {s.get('REB', '-')} REB, {s.get('AST', '-')} AST")
                        else:
                            st.caption("No comparable player found.")
                    else:
                        st.caption("No comparison data available.")

            for role_label in ["Starter", "Bench"]:
                subset = opp_roster[opp_roster["role"] == role_label]
                if not subset.empty:
                    st.markdown(f"**{role_label + 's' if role_label != 'Bench' else role_label}**")
                    cols_per_row = 5
                    player_rows = [subset.iloc[i:i + cols_per_row] for i in range(0, len(subset), cols_per_row)]
                    for row_chunk in player_rows:
                        cols = st.columns(cols_per_row)
                        for col_idx, (_, player) in enumerate(row_chunk.iterrows()):
                            with cols[col_idx]:
                                jersey_raw = str(player.get("jersey_number", "")).strip()
                                jersey_str = f"{'#' if not jersey_raw.startswith('#') else ''}{jersey_raw}" if pd.notna(player.get("jersey_number")) and jersey_raw else ""
                                name = player.get("name", "Unknown")
                                pos = player.get("position", "")
                                height = player.get("height", "")
                                prof_row = _comp_profiles[(_comp_profiles["name"] == name) & (_comp_profiles["opponent"] == short_opponent)]
                                pts_str = f"{float(prof_row.iloc[0]['PTS']):.1f}" if not prof_row.empty and pd.notna(prof_row.iloc[0].get("PTS")) else "-"
                                # Optional availability/injury status. Not currently populated by the parser --
                                # add a "status" column to uww_opponent_rosters.csv (e.g. "Out", "Questionable",
                                # "Probable") to surface it here; the app renders nothing if the column is absent
                                # or blank, so this is safe to leave unpopulated.
                                _status_raw = str(player.get("status", "")).strip()
                                _status_badge = ""
                                if _status_raw and _status_raw.lower() not in ("nan", "active", "available"):
                                    _status_color = "#c62828" if _status_raw.lower() in ("out", "injured") else "#f57c00"
                                    _status_badge = f'<span style="background:{_status_color};color:#fff;font-size:0.65rem;font-weight:700;padding:2px 6px;border-radius:8px;margin-left:4px;">{esc(_status_raw).upper()}</span>'

                                with st.container(border=True):
                                    _p_img = _get_player_img_b64(name)
                                    if _p_img:
                                        st.markdown(f'<div style="text-align:center;margin-bottom:6px;"><img src="data:image/png;base64,{_p_img}" style="width:60px;height:75px;object-fit:cover;border-radius:6px;"></div>', unsafe_allow_html=True)
                                    st.markdown(
                                        f"<div style='min-height:2.8em;line-height:1.4em;'>"
                                        f"<strong>{jersey_str} {esc(name)}</strong>{_status_badge}</div>",
                                        unsafe_allow_html=True,
                                    )
                                    info_parts = [str(x) for x in [pos, height] if pd.notna(x) and str(x).strip()]
                                    st.caption(" · ".join(info_parts) if info_parts else "\u00a0")
                                    st.markdown(f"**{pts_str}** PPG")
                                    if st.button("Details", key=f"roster_card_{short_opponent}_{name}", use_container_width=True):
                                        st.session_state["_opp_roster_detail"] = (name, player.to_dict())

            # Trigger opponent player dialog from session state (outside loop for reliability)
            if st.session_state.get("_opp_roster_detail"):
                _opp_name, _opp_dict = st.session_state.pop("_opp_roster_detail")
                _show_player_dialog(_opp_name, _opp_dict)



    with _new_tools_comparable_c:
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">COMPARABLE OPPONENTS</div></div>', unsafe_allow_html=True)
        # Which teams UWW has ALREADY PLAYED most resemble the one being prepared for -- so the staff can look
        # at what actually worked (and didn't) against that style. Scoped to `played`, i.e. games before the
        # upcoming one, so a result that hasn't happened yet can never appear here.
        _co_profiles_all = opponent_style_profiles()
        if _co_profiles_all.empty or not short_opponent or short_opponent not in _co_profiles_all.index:
            st.info("Comparable opponent data will be available once a style profile can be built for this opponent.")
        else:
            # Map each played game onto the opponent name the profile table uses, keeping EVERY meeting -- a
            # home-and-home is two separate results, and the split may be the most interesting thing about it.
            _co_index = sorted(_co_profiles_all.index.astype(str), key=len, reverse=True)
            _co_games = {}
            for _, _g in played.iterrows():
                _s = resolve_short_opponent(_g["opponent"], _co_index)
                if _s and _s != short_opponent:
                    _co_games.setdefault(_s, []).append(_g)

            _co_ranked, _co_profiles = comparable_opponents(short_opponent, list(_co_games), k=3)
            if _co_ranked is None or _co_ranked.empty:
                st.info("No previously-played opponent has enough profile data to compare against yet.")
            else:
                _co_target = _co_profiles.loc[short_opponent]
                st.caption(
                    f"Ranked on a {len(OPPONENT_FEATURE_SPEC)}-feature style profile across "
                    f"{len(OPPONENT_FEATURE_CATEGORIES)} categories ({', '.join(OPPONENT_FEATURE_CATEGORIES)}), "
                    f"each category weighted equally. Match is 100 for an identical profile, ~50 for an average "
                    f"gap of one standard deviation."
                )

                _co_cols = st.columns(len(_co_ranked))
                for _ci, (_, _cr) in enumerate(_co_ranked.iterrows()):
                    _co_name = _cr["opponent"]
                    _co_row = _co_profiles.loc[_co_name]
                    _cats = {c.split("::", 1)[1]: _cr[c] for c in _co_ranked.columns
                             if c.startswith("cat::") and pd.notna(_cr[c])}
                    _alike = sorted(_cats, key=_cats.get)[:2]
                    _differs = sorted(_cats, key=_cats.get, reverse=True)[:1]
                    with _co_cols[_ci]:
                        with st.container(border=True):
                            st.markdown(
                                f'<div style="font-weight:700;font-size:0.95rem;color:#4E2A84;">{esc(_co_name)}</div>'
                                f'<div style="font-size:1.6rem;font-weight:800;line-height:1.1;">{int(_cr["match"])}'
                                f'<span style="font-size:0.7rem;color:#888;font-weight:600;"> / 100 match</span></div>',
                                unsafe_allow_html=True,
                            )
                            # Every meeting, with its own result -- not one result standing in for two games.
                            for _g in _co_games.get(_co_name, []):
                                _oc = _g.get("outcome")
                                _colr = "#2e7d32" if _oc == "W" else "#c62828"
                                _sc = (f"{int(_g['team_score'])}-{int(_g['opponent_score'])}"
                                       if pd.notna(_g.get("team_score")) and pd.notna(_g.get("opponent_score")) else "")
                                st.markdown(
                                    f'<div style="font-size:0.85rem;margin-top:2px;">'
                                    f'<span style="color:{_colr};font-weight:700;">{esc(_oc)}</span> {esc(_sc)}'
                                    f'<span style="color:#999;font-size:0.75rem;"> · {esc(_g.get("date", ""))}</span></div>',
                                    unsafe_allow_html=True,
                                )
                            if _alike:
                                st.markdown(
                                    f'<div style="font-size:0.75rem;color:#2e7d32;margin-top:6px;">Alike: '
                                    f'{esc(", ".join(_alike))}</div>', unsafe_allow_html=True)
                            if _differs:
                                st.markdown(
                                    f'<div style="font-size:0.75rem;color:#c62828;">Differs: '
                                    f'{esc(", ".join(_differs))}</div>', unsafe_allow_html=True)
                            # The two features that separate them most, with both teams' actual numbers, so a
                            # coach can judge the match instead of trusting the score.
                            _gaps = []
                            for _fk, _flabel, _fcat in OPPONENT_FEATURE_SPEC:
                                _a, _b = _co_target.get(_fk), _co_row.get(_fk)
                                if pd.isna(_a) or pd.isna(_b):
                                    continue
                                _gaps.append((abs(float(_a) - float(_b)) / (abs(float(_a)) + 1e-6), _fk, _flabel, _a, _b))
                            for _, _fk, _flabel, _a, _b in sorted(_gaps, reverse=True)[:2]:
                                st.markdown(
                                    f'<div style="font-size:0.72rem;color:#666;margin-top:2px;">{esc(_flabel)}: '
                                    f'<strong>{esc(format_feature(_fk, _b))}</strong> vs {esc(format_feature(_fk, _a))} '
                                    f'({esc(get_team_abbreviation(short_opponent))})</div>', unsafe_allow_html=True)

                # What actually happened against this style -- the reason the panel exists.
                _co_rows = [g for name in _co_ranked["opponent"] for g in _co_games.get(name, [])]
                if _co_rows:
                    _co_played = pd.DataFrame(_co_rows)
                    _w = int((_co_played["outcome"] == "W").sum())
                    _l = int((_co_played["outcome"] == "L").sum())
                    _pf, _pa = _co_played["team_score"].mean(), _co_played["opponent_score"].mean()
                    _season_pf = played["team_score"].mean() if not played.empty else None
                    _season_pa = played["opponent_score"].mean() if not played.empty else None
                    _delta = ""
                    if _season_pf is not None and pd.notna(_season_pf):
                        _delta = (f" ({_pf - _season_pf:+.1f} pts scored, {_pa - _season_pa:+.1f} allowed "
                                  f"vs UWW's season average)")
                    st.markdown(
                        f'<div style="border:1px solid #eee;border-radius:8px;padding:10px 12px;margin-top:8px;'
                        f'font-size:0.85rem;">Against these {len(_co_ranked)} teams UWW is <strong>{_w}-{_l}</strong>, '
                        f'averaging <strong>{_pf:.1f}</strong> scored and <strong>{_pa:.1f}</strong> allowed'
                        f'{esc(_delta)}.</div>', unsafe_allow_html=True)

                with st.expander("Full style profile comparison", expanded=False):
                    _co_table = []
                    for _fk, _flabel, _fcat in OPPONENT_FEATURE_SPEC:
                        _entry = {"Category": _fcat, "Feature": _flabel,
                                  f"{get_team_abbreviation(short_opponent)} (upcoming)": format_feature(_fk, _co_target.get(_fk))}
                        for _cn in _co_ranked["opponent"]:
                            _entry[get_team_abbreviation(_cn)] = format_feature(_fk, _co_profiles.loc[_cn].get(_fk))
                        _co_table.append(_entry)
                    st.dataframe(pd.DataFrame(_co_table), hide_index=True, use_container_width=True)
                    st.caption(
                        "PTS/REB are per game in the source table; AST/STL/BLK/TO are season totals there and are "
                        "divided by each player's own games played. Size and style shares are minutes-weighted "
                        "across the rotation (8+ MPG). Profiles for opponents already played come from their own "
                        "scouting report, so a thinly scouted team will have fewer comparable features -- the "
                        "match score only counts features both teams actually have."
                    )



        # ============================ TEAMS LIKE US THAT PLAYED THEM ============================
        # The mirror of the panel above. That one asks "which team WE'VE played resembles this opponent";
        # this asks "which team THEY'VE played resembles US" -- and then shows what happened, because a
        # team built like UWW that beat them is the closest thing to a dress rehearsal this data holds.
        #
        # These profiles cannot come from opponent_style_profiles(): that table is built from scouted
        # opponents' season stats, and the upcoming opponent's other opponents were never scouted. What
        # does exist is the reconstructed box score of each of those games, so the profile is built from
        # the ONE game each team played against them -- which is a real limitation, not a footnote, and is
        # stated on the panel rather than buried here.
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;">'
                    '<div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">'
                    'TEAMS LIKE US THAT PLAYED THEM</div></div>', unsafe_allow_html=True)
        _tl_prior = load_table("uww_opponent_prior_games_box_score")
        _tl_uww_box = load_table("uww_pbp_box_score")
        if _tl_prior.empty or _tl_uww_box.empty or not short_opponent:
            st.info("Needs the upcoming opponent's prior-game box scores and UWW's own -- not available yet.")
        else:
            # Per-game team totals, on features any box score can produce (so UWW and the third-party teams
            # are described the same way). Rates, not raw counts, wherever the pace of one game would
            # otherwise masquerade as style.
            def _tl_profile(_g):
                _fga, _fta = _g["FGA"].sum(), _g["FTA"].sum()
                _3pa, _pts = _g["FG3A"].sum(), _g["PTS"].sum()
                if _fga <= 0:
                    return None
                return {
                    "pts": _pts, "fg_pct": 100 * _g["FGM"].sum() / _fga,
                    "tp_rate": 100 * _3pa / _fga,
                    "tp_pct": (100 * _g["FG3M"].sum() / _3pa) if _3pa > 0 else float("nan"),
                    "ft_rate": 100 * _fta / _fga,
                    "ast": _g["AST"].sum(), "to": _g["TO"].sum(),
                    "oreb": _g["OREB"].sum() if "OREB" in _g.columns else float("nan"),
                    "reb": _g["REB"].sum() if "REB" in _g.columns else float("nan"),
                }

            _tl_feats = ["fg_pct", "tp_rate", "tp_pct", "ft_rate", "ast", "to", "oreb", "reb"]
            _tl_rows = []
            _tl_keys = [c for c in ["opponent", "game_date"] if c in _tl_prior.columns]
            for _tl_k, _tl_g in _tl_prior.groupby(_tl_keys, dropna=False):
                _foe = _tl_g[_tl_g["team"] != short_opponent]
                _them = _tl_g[_tl_g["team"] == short_opponent]
                if _foe.empty or _them.empty:
                    continue
                _prof = _tl_profile(_foe)
                if not _prof:
                    continue
                _prof["team"] = str(_foe["team"].dropna().iloc[0]) if _foe["team"].notna().any() else str(
                    _tl_k[0] if isinstance(_tl_k, tuple) else _tl_k)
                _prof["game_date"] = (_tl_k[1] if isinstance(_tl_k, tuple) and len(_tl_k) > 1 else None)
                _prof["their_pts"] = _them["PTS"].sum()
                _prof["won"] = _prof["pts"] > _prof["their_pts"]
                _tl_rows.append(_prof)

            # UWW's own season profile, built the identical way so the comparison is apples to apples.
            _tl_uww_side = _tl_uww_box[_tl_uww_box["team"] == "UW-Whitewater"]
            _tl_uww_games = _tl_uww_side.groupby([c for c in ["opponent", "game_date"] if c in _tl_uww_side.columns],
                                                 dropna=False) if not _tl_uww_side.empty else None
            _tl_uww_rows = [p for p in (_tl_profile(_g) for _, _g in _tl_uww_games) if p] if _tl_uww_games is not None else []
            if not _tl_rows or not _tl_uww_rows:
                st.info(f"Not enough reconstructed box scores from {short_opponent}'s prior games yet.")
            else:
                _tl_df = pd.DataFrame(_tl_rows)
                _tl_me = pd.DataFrame(_tl_uww_rows)[_tl_feats].mean()
                # z-scored on the pool the comparison is made within (their opponents plus us), so "similar"
                # means similar relative to the teams this opponent actually faces.
                _tl_pool = pd.concat([_tl_df[_tl_feats], _tl_me.to_frame().T], ignore_index=True)
                _tl_sd = _tl_pool.std(ddof=0).replace(0, float("nan"))
                _tl_mu = _tl_pool.mean()
                _tl_z = (_tl_df[_tl_feats] - _tl_mu) / _tl_sd
                _tl_me_z = (_tl_me - _tl_mu) / _tl_sd
                _tl_df["distance"] = ((_tl_z - _tl_me_z) ** 2).mean(axis=1) ** 0.5
                # Same 100*exp(-0.7*d) scale the Comparable Opponents panel uses, so a "78% match" means
                # the same thing in both places.
                _tl_df["match"] = _tl_df["distance"].apply(lambda d: int(round(100 * math.exp(-0.7 * d))))
                _tl_top = _tl_df.nsmallest(3, "distance")

                st.caption(
                    f"Ranked on how each of {short_opponent}'s opponents played that night versus how UWW plays "
                    f"on average -- shooting split, three-point rate, free-throw rate, assists, turnovers and "
                    f"the glass. Each of their opponents is described by ONE game, so treat these as rough "
                    f"style matches, not season profiles."
                )
                _tl_cols = st.columns(len(_tl_top))
                for _i, (_, _r) in enumerate(_tl_top.iterrows()):
                    with _tl_cols[_i]:
                        with st.container(border=True):
                            _res = "W" if _r["won"] else "L"
                            _color = "#2e7d32" if _r["won"] else "#c62828"
                            st.markdown(
                                f'<div style="font-weight:700;color:#4E2A84;">{esc(str(_r["team"]))}</div>'
                                f'<div style="font-size:0.75rem;color:#666;">{_r["match"]}% style match</div>'
                                f'<div style="margin-top:6px;font-size:1.1rem;font-weight:800;color:{_color};">'
                                f'{_res} {int(_r["pts"])}-{int(_r["their_pts"])}</div>'
                                f'<div style="font-size:0.75rem;color:#666;margin-top:4px;">'
                                f'{_r["fg_pct"]:.0f}% FG &middot; {_r["tp_rate"]:.0f}% of shots from three '
                                f'({_r["tp_pct"]:.0f}%)<br>{int(_r["ast"])} AST &middot; {int(_r["to"])} TO'
                                f'</div>', unsafe_allow_html=True)

                _tl_w = int(_tl_top["won"].sum())
                st.markdown(
                    f'<div style="border:1px solid #eee;border-radius:8px;padding:10px 12px;margin-top:8px;'
                    f'font-size:0.85rem;">Teams that played like us went <strong>{_tl_w}-{len(_tl_top) - _tl_w}</strong> '
                    f'against {esc(short_opponent)}, averaging <strong>{_tl_top["pts"].mean():.1f}</strong> scored '
                    f'and <strong>{_tl_top["their_pts"].mean():.1f}</strong> allowed. '
                    f'{esc(short_opponent)} allowed <strong>{_tl_df["pts"].mean():.1f}</strong> to the field.</div>',
                    unsafe_allow_html=True)

                with st.expander("How each of their opponents compares to us", expanded=False):
                    _tl_show = _tl_df.assign(
                        Team=_tl_df["team"], Match=_tl_df["match"],
                        Result=_tl_df.apply(lambda r: f"{'W' if r['won'] else 'L'} {int(r['pts'])}-{int(r['their_pts'])}", axis=1),
                        **{"FG%": _tl_df["fg_pct"].round(1), "3PA rate": _tl_df["tp_rate"].round(1),
                           "3P%": _tl_df["tp_pct"].round(1), "FT rate": _tl_df["ft_rate"].round(1),
                           "AST": _tl_df["ast"].round(0), "TO": _tl_df["to"].round(0)},
                    )
                    st.dataframe(
                        _tl_show[["Team", "Match", "Result", "FG%", "3PA rate", "3P%", "FT rate", "AST", "TO"]]
                        .sort_values("Match", ascending=False), hide_index=True, use_container_width=True)
                    st.caption(
                        "UWW's own season averages for the same features: "
                        + " &middot; ".join(f"{_k} {_tl_me[_k]:.1f}" for _k in _tl_feats)
                        + ". Match is 100 for an identical profile, ~50 for an average gap of one standard "
                          "deviation across the pool."
                    )



    with _new_tools_proj_c:
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">PROJECTED BOX SCORE</div></div>', unsafe_allow_html=True)
        uww_proj = load_table("uww_projected_box_score")
        opp_proj = load_table("uww_opponent_projected_box_score")  # was mismatched to a nonexistent "aurora_projected_box_score" file — this is the name the parser notebook actually exports (see parser cell 128)

        # --- Possession-based projection (see project_game) ------------------------------------------------
        _pg = project_game(short_opponent, location)
        if _pg:
            _pg_lo, _pg_hi = _pg["margin"] - _pg["sd"], _pg["margin"] + _pg["sd"]
            _m1, _m2, _m3, _m4 = st.columns(4)
            _m1.metric("Projected UWW", f"{_pg['uww_pts']:.0f}")
            _m2.metric(f"Projected {short_opponent}", f"{_pg['opp_pts']:.0f}")
            _m3.metric("Margin", f"{_pg['margin']:+.1f}", help=f"Likely range {_pg_lo:+.0f} to {_pg_hi:+.0f} (one standard deviation).")
            _m4.metric("Win probability", f"{_pg['win_prob']:.0%}")
            st.markdown(
                f"Expected tempo **{_pg['possessions']:.0f}** possessions "
                f"(UWW {_pg['uww_pace']:.1f}, {short_opponent} {_pg['opp_pace']:.1f}"
                + ("" if _pg["opp_pace_known"] else ", estimated") + "). "
                f"Efficiency this matchup: UWW **{_pg['uww_ortg']:.1f}** per 100, "
                f"{short_opponent} **{_pg['opp_ortg']:.1f}**."
                + (f" Home court applied: **{_pg['hca']:+.1f}** points." if _pg["hca"] else " Neutral floor.")
            )
            st.caption(
                "Efficiency x possessions, not points per game: expected tempo is the harmonic mean of the two "
                "teams' paces, each offense is its opponent-adjusted rating shifted by how far the other "
                f"defense sits from average, and the win probability is the normal CDF of the margin over a "
                f"{GAME_MARGIN_SD:.0f}-point one-game standard deviation. The margin is a center of a "
                "distribution, not a prediction -- the range on the margin tile is what an ordinary game looks "
                "like around it."
            )

            _new_box = project_uww_box(short_opponent, _pg["uww_pts"], _pg["possessions"])
            if not _new_box.empty:
                with st.expander("UWW player projection (minutes-and-rates model)", expanded=True):
                    _nb_cols = [c for c in ["player", "MIN", "PTS", "REB", "AST", "STL", "BLK", "TO"] if c in _new_box.columns]
                    st.dataframe(_new_box[_nb_cols].rename(columns={"player": "Player"}),
                                 hide_index=True, use_container_width=True)
                    st.caption(
                        "Minutes come from the last five games (the rotation as it stands now), normalised to "
                        "the 200 a team plays. Every stat is a per-minute rate times those minutes; points are "
                        "reconciled to the projected team total and every other column to its own season rate "
                        "re-paced to this game's projected possessions -- so a slow projected game lowers "
                        "rebounds and assists too, which per-game-average scaling never did."
                    )
            st.markdown("---")

        if uww_proj.empty or opp_proj.empty:
            st.info("Parser-side projected box score not available yet for this opponent.")
        else:
            proj_uww_total = uww_proj["projected_PTS"].sum()
            proj_opp_total = opp_proj["projected_PTS"].sum()
            st.markdown("**Parser projection (per-player comparables)**")
            pcol1, pcol2, pcol3 = st.columns(3)
            pcol1.metric("Projected UWW", f"{proj_uww_total:.0f}")
            pcol2.metric(f"Projected {short_opponent}", f"{proj_opp_total:.0f}")
            pcol3.metric("Projected margin", f"{proj_uww_total - proj_opp_total:+.0f}")
            if _pg:
                _delta = (proj_uww_total - proj_opp_total) - _pg["margin"]
                st.caption(
                    f"This is the older model, kept because it projects the OPPONENT'S players individually "
                    f"(via similarity comps), which the possession model above does not. It differs from the "
                    f"possession model by {_delta:+.1f} points of margin -- when the two disagree sharply, the "
                    f"usual cause is pace: this one works in points per game, which bakes tempo into every number."
                )
            else:
                st.caption(
                    "Team totals blend each team's season scoring rate with the ACTUAL points scored/allowed against "
                    "comparable competition this season -- not just a season average. Hover any player row below for "
                    "exactly how that individual projection was derived."
                )

            pbox_col1, pbox_col2 = st.columns(2)
            with pbox_col1:
                st.markdown("**UW-Whitewater**")
                render_box_score_with_tooltips(
                    uww_proj.sort_values("projected_PTS", ascending=False),
                    ["PLAYER", "MIN", "projected_PTS", "projected_REB", "projected_AST", "FG%", "3P%", "FT%"],
                )
            with pbox_col2:
                st.markdown(f"**{short_opponent}**")
                render_box_score_with_tooltips(
                    opp_proj.sort_values("projected_PTS", ascending=False),
                    [c for c in ["name", "jersey_number", "role", "MIN", "projected_PTS", "projected_REB", "projected_AST"] if c in opp_proj.columns],
                )

        # ==================== LINEUP SIMULATOR ====================

    with _new_tools_lineup_c:
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">\U0001f3ae LINEUP SIMULATOR</div></div>', unsafe_allow_html=True)
        with st.expander("Build a lineup and see projected performance", expanded=False):
            _sim_players = sorted(uww_box["player"].dropna().unique().tolist()) if not uww_box.empty else []
            # Build most-used lineup options from aggregated data
            _preset_options = []
            if _uww_lu_agg is not None and not _uww_lu_agg.empty:
                _top_lineups = _uww_lu_agg.nlargest(min(5, len(_uww_lu_agg)), "MIN")
                for _, _tl_row in _top_lineups.iterrows():
                    _tl_players = [p.strip() for p in str(_tl_row["lineup"]).split(",")]
                    _tl_short = _last_names(_tl_row["lineup"])
                    _tl_mins = _tl_row["MIN"]
                    _preset_options.append({"label": f"{_tl_short} ({_tl_mins:.0f} min)", "players": _tl_players})
            if _sim_players:
                # Quick-select from most-used lineups
                if _preset_options:
                    _preset_labels = ["-- Select a lineup --"] + [p["label"] for p in _preset_options]

                    def _apply_lineup_preset():
                        # NOTE: this MUST run via on_change (writing directly into the multiselect's own
                        # session_state slot) rather than via the multiselect's `default=` parameter. Once a
                        # widget's `key` has ever been set in st.session_state (which happens the moment it's
                        # first rendered), Streamlit permanently ignores that widget's `default=` on every future
                        # rerun -- so picking a different preset here would recompute the right player list, but
                        # it would never actually reach the multiselect. This was confirmed to be exactly why
                        # "Most-Used Lineup" selections weren't taking effect: the old code relied purely on
                        # `default=_default_sel`, which only worked before the multiselect's key had a value yet
                        # (i.e. only on a completely fresh page load with no prior interaction).
                        _choice = st.session_state.get("lineup_sim_preset")
                        if _choice and _choice != "-- Select a lineup --" and _choice in _preset_labels:
                            _idx = _preset_labels.index(_choice) - 1
                            st.session_state["lineup_sim_select"] = _preset_options[_idx]["players"]
                        else:
                            st.session_state["lineup_sim_select"] = []

                    st.selectbox(
                        "Most-used lineups", _preset_labels, index=0, key="lineup_sim_preset",
                        on_change=_apply_lineup_preset,
                    )
                _selected = st.multiselect(
                    "Select 5 UWW players", _sim_players,
                    max_selections=5, key="lineup_sim_select",
                )
                if len(_selected) == 5:
                    from itertools import combinations as _sim_combos
                    _sim_col1, _sim_col2 = st.columns(2)
                    _match = pd.DataFrame()
                    _rate = 0
                    _proj_rate = 0
                    _found_pairs = 0
                    with _sim_col1:
                        st.markdown("**Historical Performance**")
                        _match = _uww_lu_agg[_uww_lu_agg["lineup"].apply(
                            lambda x: set(p.strip() for p in str(x).split(",")) == set(_selected)
                        )] if _uww_lu_agg is not None else pd.DataFrame()
                        if not _match.empty:
                            _m = _match.iloc[0]
                            _rate = _m["+/-"] / _m["MIN"] if _m["MIN"] > 0 else 0
                            st.metric("Total Minutes", f"{_m['MIN']:.1f}")
                            st.metric("Total +/-", f"{_m['+/-']:+.1f}")
                            st.metric("Net Rating", f"{_rate:+.2f}/min")
                            st.metric("Points Scored", f"{_m['PTS']:.0f}")
                            st.metric("Games Appeared", f"{_m['GP']:.0f}")
                        else:
                            st.info("This exact 5-man lineup has not played together yet.")
                            st.markdown("**Projected (from component pairs):**")
                            _pair_data = {}
                            if not _stints.empty:
                                for _, _stint in _stints.iterrows():
                                    _stint_players = [p.strip() for p in str(_stint["uww_lineup"]).split(",")]
                                    _stint_mins = _stint["stint_minutes"]
                                    _stint_margin = _stint["uww_margin_change"]
                                    for _pair in _sim_combos(sorted(_stint_players), 2):
                                        if _pair not in _pair_data:
                                            _pair_data[_pair] = {"min": 0, "margin": 0}
                                        _pair_data[_pair]["min"] += _stint_mins
                                        _pair_data[_pair]["margin"] += _stint_margin
                            _sel_pairs = list(_sim_combos(sorted(_selected), 2))
                            _found_pairs = 0
                            _total_rate = 0
                            for _sp in _sel_pairs:
                                if _sp in _pair_data and _pair_data[_sp]["min"] >= 2.0:
                                    _found_pairs += 1
                                    _total_rate += _pair_data[_sp]["margin"] / _pair_data[_sp]["min"]
                            if _found_pairs > 0:
                                _proj_rate = _total_rate / _found_pairs
                                st.metric("Projected Net Rating", f"{_proj_rate:+.2f}/min")
                                st.caption(f"Based on {_found_pairs}/10 known pair combinations")
                            else:
                                st.caption("Not enough pair data to project.")

                    with _sim_col2:
                        st.markdown("**2-Man Chemistry Scores**")
                        _pair_data_sim = {}
                        if not _stints.empty:
                            for _, _stint in _stints.iterrows():
                                _stint_players = [p.strip() for p in str(_stint["uww_lineup"]).split(",")]
                                _stint_mins = _stint["stint_minutes"]
                                _stint_margin = _stint["uww_margin_change"]
                                for _pair in _sim_combos(sorted(_stint_players), 2):
                                    if _pair not in _pair_data_sim:
                                        _pair_data_sim[_pair] = {"min": 0, "margin": 0}
                                    _pair_data_sim[_pair]["min"] += _stint_mins
                                    _pair_data_sim[_pair]["margin"] += _stint_margin
                        _sel_pairs = list(_sim_combos(sorted(_selected), 2))
                        _chem_rows = []
                        for _sp in _sel_pairs:
                            if _sp in _pair_data_sim and _pair_data_sim[_sp]["min"] >= 1.0:
                                _pd = _pair_data_sim[_sp]
                                _chem_rate = _pd["margin"] / _pd["min"]
                                _p1 = _sp[0].split()[-1] if " " in _sp[0] else _sp[0]
                                _p2 = _sp[1].split()[-1] if " " in _sp[1] else _sp[1]
                                _chem_rows.append({"Pair": f"{_p1} + {_p2}", "+/-": f"{_pd['margin']:+.1f}", "Min": f"{_pd['min']:.1f}", "Rate": f"{_chem_rate:+.2f}"})
                        if _chem_rows:
                            _chem_rows.sort(key=lambda x: float(x["Rate"]), reverse=True)
                            st.dataframe(pd.DataFrame(_chem_rows), hide_index=True, use_container_width=True)
                        else:
                            st.caption("No shared court time data for these pairs.")

                        if _opp_lu is not None and not _opp_lu.empty:
                            st.markdown("**vs Opponent's Top Lineup**")
                            _opp_top = _opp_lu.nlargest(1, "MIN").iloc[0]
                            _opp_top_ln = _last_names(_opp_top["lineup"])
                            _opp_top_rate = _opp_top["+/-"] / _opp_top["MIN"] if _opp_top["MIN"] > 0 else 0
                            st.caption(f"{opp_display}'s most-used: {_opp_top_ln}")
                            st.caption(f"Their net rating: {_opp_top_rate:+.2f}/min")
                            if not _match.empty:
                                st.caption(f"Your lineup: {_rate:+.2f}/min \u2192 Projected edge: {_rate - _opp_top_rate:+.2f}/min")
                            elif _found_pairs > 0:
                                st.caption(f"Your lineup (est): {_proj_rate:+.2f}/min \u2192 Projected edge: {_proj_rate - _opp_top_rate:+.2f}/min")

                elif len(_selected) > 0:
                    st.caption(f"Select {5 - len(_selected)} more player{'s' if 5 - len(_selected) > 1 else ''}.")
            else:
                st.caption("No player data available for simulation.")

        # ==================== GAME PLAN RECOMMENDATIONS ====================

    with _new_rec_container:
        # Explanation sits on a hover icon in the title rather than a separate button below it: the button
        # occupied a full row of its own and had to be clicked to reveal text that is only ever context.
        # Native `title` tooltip, same mechanism as glossary_span() and the box-score hovers, so it can't be
        # clipped by the bordered containers this header sits inside.
        _ktv_help = (
            "Everything the staff and the data have on this opponent, combined into one list: "
            "pre-computed data-driven keys, the staff's own written scouting report (Keys to Victory, "
            "Team Strengths, the full game plan), lineup scouting, and season-stat-based recommendations.\n\n"
            "Each item shows its source, the supporting numbers, and the reasoning behind it. "
            "Categories with a Game Plan button have written game-plan notes matched to that category."
        )
        section_header("\U0001f511 KEYS TO VICTORY", _ktv_help)

        # Still two columns with the second left empty, so the remaining PDF button keeps the same half-width
        # placement it has always had rather than stretching to full width.
        _util_c1, _ = st.columns(2)
        with _util_c1:
            if report_path and os.path.exists(report_path):
                with open(report_path, "rb") as pdf_file:
                    st.download_button(
                        label="\U0001f4c4 Download Scouting Report PDF", data=pdf_file,
                        file_name=f"{short_opponent}_Scouting_Report.pdf", mime="application/pdf",
                        key=f"pdf_download_{short_opponent}", use_container_width=True,
                    )

        _keys = []  # list of (icon, headline, reason) -- every source below appends here, nothing renders separately

        # A. Pre-computed data-driven keys (title + supporting stat + recommendation, already in
        # exactly a "key + reason why" shape from the parser)
        try:
            _dk_all = load_table("uww_pbp_derived_keys")
            _dk_opp = _dk_all[_dk_all["opponent"] == short_opponent].sort_values("key_number") if not _dk_all.empty and short_opponent else pd.DataFrame()
            for _, _dk in _dk_opp.iterrows():
                _keys.append(("\U0001f4ca", str(_dk["title"]), str(_dk["supporting_stats"]), str(_dk["recommendation"]), "Data-Driven"))
        except Exception:
            pass

        # B/C/D. The staff's own written scouting report -- Keys to Victory, Team Strengths, and
        # the rest of the full game plan (offensive/defensive schemes by category)
        try:
            _sr_game_plans = load_table("uww_opponent_game_plans")
            _sr_opp_plan = _sr_game_plans[_sr_game_plans["opponent"] == short_opponent] if not _sr_game_plans.empty and short_opponent else pd.DataFrame()
            if not _sr_opp_plan.empty:
                _sr_ktv = _sr_opp_plan[_sr_opp_plan["topic"] == "KEYS TO VICTORY"]
                if not _sr_ktv.empty:
                    for _k in str(_sr_ktv.iloc[0]["notes"]).split("|"):
                        _k = re.sub(r"^\d+\.\s*", "", _k.strip())
                        if _k:
                            _keys.append(("\U0001f4cb", _k, None, None, "Keys to Victory"))
                _sr_strengths = _sr_opp_plan[_sr_opp_plan["topic"] == "TEAM STRENGTHS"]
                if not _sr_strengths.empty:
                    for _s in str(_sr_strengths.iloc[0]["notes"]).split("|"):
                        _s = re.sub(r"^\d+\.\s*", "", _s.strip())
                        if _s:
                            _keys.append(("\u26a0\ufe0f", f"Opponent strength: {_s}", None, None, "Team Strengths"))
                # The rest of the game plan (categories with "Game Plan" in the name, e.g. "Offensive Game
                # Plan"/"Defensive Game Plan") is NOT flattened into individual keys here anymore -- it's
                # shown in the "\U0001f4cb Game Plan" popup dialog instead (see _show_game_plan_dialog below),
                # since listing every full-game-plan bullet out inline made the list too long.
        except Exception:
            pass

        # E. Lineup scouting (opponent vulnerability + best UWW counter, from the same lineup data
        # the Tools tab's simulator uses)
        try:
            if _opp_lu is not None and not _opp_lu.empty:
                # The full opponent-vulnerability picture -- formerly its own card in the Lineup Scouting
                # panel: their worst net-rating units (with shooting), plus the units that turn it over
                # most. Both answer the same question ("when are they beatable?"), so they belong in one
                # key rather than a side card.
                _vl = _opp_lu.copy()
                _vl["_pm_fg"] = pd.to_numeric(_vl["FG%"], errors="coerce").fillna(0) if "FG%" in _vl.columns else 0
                if "TO" in _vl.columns:
                    _vl["_to_rate"] = (_vl["TO"] / _vl["MIN"].replace(0, float("nan")) * 40).round(1)
                _vl_qual = _vl[_vl["MIN"] >= 3.0]
                _ls_worst = _vl_qual.nsmallest(3, "+/-")
                if not _ls_worst.empty:
                    _ls_wr = _ls_worst.iloc[0]
                    _vl_lines = ["_Worst +/- lineups:_"]
                    for _, _r in _ls_worst.iterrows():
                        _fg = f", {_r['_pm_fg']:.0f}% FG" if _r.get("_pm_fg", 0) > 0 else ""
                        _vl_lines.append(
                            f"**{_r['+/-']:+.1f}** in {_r['MIN']:.1f} min{_fg} — {_last_names(_r['lineup'])}"
                        )
                    if "_to_rate" in _vl_qual.columns:
                        _vl_high_to = _vl_qual.nlargest(2, "_to_rate")
                        if not _vl_high_to.empty:
                            _vl_lines.append("_Highest TO rate (per 40 min):_")
                            for _, _r in _vl_high_to.iterrows():
                                _vl_lines.append(
                                    f"**{_r['_to_rate']:.1f}** TO/40 — {_last_names(_r['lineup'])}"
                                )
                    _keys.append((
                        "\U0001f512",
                        f"Attack {short_opponent}'s {_last_names(_ls_wr['lineup'])} lineup",
                        "  \n".join(_vl_lines),
                        f"{short_opponent}'s most exploitable units: their worst net-rating lineups with "
                        f"real minutes this season (3+ min), and the lineups that give the ball away most "
                        f"per 40 minutes. The headline names the worst of them.",
                        "Lineup Scouting",
                    ))
            # The full counter-lineup recommendation -- formerly its own card in the Lineup Scouting panel.
            # Two modes, and the key always says which one it is in:
            #   MATCHED  -- UWW's net margin against opponent lineups that RESEMBLE the one being prepared
            #               for (position mix, size, starters, scouted style). A genuine counter.
            #   FALLBACK -- UWW's best net-margin lineups season-wide. Useful, but NOT opponent-specific,
            #               and labelled as such rather than dressed up with a "vs <opponent>" heading.
            _cl_target_lineup = None
            if _opp_lu is not None and not _opp_lu.empty:
                _cl_opp_top = _opp_lu.nlargest(1, "MIN")
                if not _cl_opp_top.empty:
                    _cl_target_lineup = _cl_opp_top.iloc[0]["lineup"]

            _cl_matched, _cl_matched_min, _cl_n_similar, _cl_target_desc = (None, 0.0, 0, "")
            if _cl_target_lineup is not None:
                try:
                    _cl_matched, _cl_matched_min, _cl_n_similar, _cl_target_desc = counter_lineups(
                        short_opponent, _cl_target_lineup, _stints,
                    )
                except Exception as _cl_err:
                    report_section_error("Counter-lineup profile match", _cl_err)

            if _cl_matched is not None and not _cl_matched.empty:
                _cl_rows = list(_cl_matched.head(3).iterrows())
                _cl_best = _cl_rows[0][1]
                # Caption: every recommended unit, best first, with the same per-minute rate and raw
                # (net in minutes) breakdown the old card showed.
                _cl_caption_lines = [
                    f"**{_r['rate']:+.2f}/min** ({_r['net']:+.0f} in {_r['MIN']:.1f} min) — {_last_names(_r['uww_lineup'])}"
                    for _, _r in _cl_rows
                ]
                _cl_caption = "  \n".join(_cl_caption_lines)
                _cl_reason_parts = [
                    f"UWW's best net margin against opponent units that resemble {short_opponent}'s "
                    f"most-used lineup ({_last_names(_cl_target_lineup)})."
                ]
                if _cl_target_desc:
                    _cl_reason_parts.append(f"Target profile: {_cl_target_desc}.")
                _cl_reason_parts.append(
                    f"Measured across {_cl_n_similar} comparable opponent unit(s), "
                    f"{_cl_matched_min:.0f} min this season."
                )
                _keys.append((
                    "\U0001f512",
                    f"Counter with {_last_names(_cl_best['uww_lineup'])}",
                    _cl_caption,
                    " ".join(_cl_reason_parts),
                    "Lineup Scouting",
                ))
            elif _uww_lu_agg is not None and not _uww_lu_agg.empty:
                _cl_fallback = _uww_lu_agg[_uww_lu_agg["MIN"] >= 3.0].nlargest(3, "+/-")
                if not _cl_fallback.empty:
                    _cl_rows = list(_cl_fallback.iterrows())
                    _cl_best = _cl_rows[0][1]
                    _cl_caption_lines = []
                    for _, _r in _cl_rows:
                        _r_rate = _r["+/-"] / _r["MIN"] if _r["MIN"] > 0 else 0.0
                        _cl_caption_lines.append(
                            f"**{_r['+/-']:+.1f}** total ({_r_rate:+.2f}/min in {_r['MIN']:.1f} min) "
                            f"— {_last_names(_r['lineup'])}"
                        )
                    _cl_why = ("no comparable opponent lineups on record yet"
                               if _cl_target_lineup is not None else "no opponent lineup data yet")
                    _keys.append((
                        "\U0001f512",
                        f"Counter with {_last_names(_cl_best['lineup'])}",
                        "  \n".join(_cl_caption_lines),
                        f"UWW's best lineups by net margin season-wide — **not** matchup-specific, "
                        f"because there are {_cl_why}.",
                        "Lineup Scouting",
                    ))
        except Exception:
            pass

        # E-bis. 3-man combination scouting -- same idea as the 5-man Lineup Scouting above, but for
        # the smaller units. This is the data the Stats & Analysis "TOP 3-MAN COMBINATIONS" card used to
        # just display; it's now put to use here instead (that card no longer renders on its own).
        # _uww_3man_agg / _opp_3man_agg only carry MIN/PTS/+/-/GP (no FG%/TO, unlike the 5-man data), so
        # this is scoped to net-margin exploitability/production rather than shooting or turnovers.
        try:
            if _opp_3man_agg is not None and not _opp_3man_agg.empty:
                _v3_qual = _opp_3man_agg[_opp_3man_agg["MIN"] >= 3.0]
                _v3_worst = _v3_qual.nsmallest(3, "+/-")
                if not _v3_worst.empty:
                    _v3_wr = _v3_worst.iloc[0]
                    _v3_lines = ["_Worst +/- 3-man combos:_"]
                    for _, _r in _v3_worst.iterrows():
                        _v3_lines.append(
                            f"**{_r['+/-']:+.1f}** in {_r['MIN']:.1f} min — {_last_names(_r['lineup'])}"
                        )
                    _keys.append((
                        "\U0001f512",
                        f"Attack {short_opponent}'s {_last_names(_v3_wr['lineup'])} combo",
                        "  \n".join(_v3_lines),
                        f"{short_opponent}'s most exploitable 3-man combinations: their worst net-rating "
                        f"units with real minutes this season (3+ min).",
                        "Lineup Scouting",
                    ))
            if _uww_3man_agg is not None and not _uww_3man_agg.empty:
                _c3_qual = _uww_3man_agg[_uww_3man_agg["MIN"] >= 5.0]
                _c3_best = _c3_qual.nlargest(3, "+/-")
                if not _c3_best.empty:
                    _c3_rows = list(_c3_best.iterrows())
                    _c3_top = _c3_rows[0][1]
                    _c3_lines = []
                    for _, _r in _c3_rows:
                        _r_rate = _r["+/-"] / _r["MIN"] if _r["MIN"] > 0 else 0.0
                        _c3_lines.append(
                            f"**{_r['+/-']:+.1f}** total ({_r_rate:+.2f}/min in {_r['MIN']:.1f} min) "
                            f"— {_last_names(_r['lineup'])}"
                        )
                    _keys.append((
                        "\U0001f512",
                        f"Feature the {_last_names(_c3_top['lineup'])} combo",
                        "  \n".join(_c3_lines),
                        "UWW's best 3-man combinations by net margin season-wide (5+ min) — not "
                        "matchup-specific like the 5-man counter above, but the smaller units most worth "
                        "leaning on regardless of opponent.",
                        "Lineup Scouting",
                    ))
        except Exception:
            pass

        # E2. Best shot type: what UWW is most efficient at as a team (shot mechanic + contest level, from
        # the same video-tagging the Analytics page's Shot Selection & Quality section already uses), which
        # 5-man lineup gets that shot type most efficiently, and which offensive play call generates it most
        # often. All three combined into one Offensive Efficiency key.
        try:
            _ss_pbp = load_table("uww_pbp_events")
            _ss_uww = _ss_pbp[(_ss_pbp["team"] == "UW-Whitewater") & (_ss_pbp["event_type"].isin(["made_shot", "missed_shot"]))].copy()
            _ss_uww = _ss_uww[_ss_uww["video_description"].notna()]
            if not _ss_uww.empty:
                _ss_uww["_mechanic"] = _ss_uww["video_description"].apply(extract_shot_mechanic)
                _ss_uww["_contest"] = _ss_uww["video_description"].apply(extract_contest)
                _ss_uww["_make"] = _ss_uww["event_type"] == "made_shot"
                _ss_grouped = _ss_uww[_ss_uww["_mechanic"].notna() & _ss_uww["_contest"].notna()].groupby(["_mechanic", "_contest"]).agg(
                    Attempts=("_make", "count"), Makes=("_make", "sum"),
                ).reset_index()
                _ss_grouped = _ss_grouped[_ss_grouped["Attempts"] >= 8]  # need a real sample before calling it "best"
                if not _ss_grouped.empty:
                    _ss_grouped["FG%"] = 100 * _ss_grouped["Makes"] / _ss_grouped["Attempts"]
                    # A residual bucket is not a shot type. Prefer the best NAMED one; only fall back to the
                    # unclassified pile if nothing else clears the attempt threshold, and label it plainly.
                    _ss_named = _ss_grouped[_ss_grouped["_mechanic"] != UNCLASSIFIED_SHOT_MECHANIC]
                    _ss_best = (_ss_named if not _ss_named.empty else _ss_grouped).nlargest(1, "FG%").iloc[0]
                    _ss_best_mechanic, _ss_best_contest = _ss_best["_mechanic"], _ss_best["_contest"]
                    _ss_best_rows = _ss_uww[(_ss_uww["_mechanic"] == _ss_best_mechanic) & (_ss_uww["_contest"] == _ss_best_contest)]

                    # Which 5-man lineup gets this specific shot type most efficiently (needs uww_lineup on
                    # pbp_events -- only present after re-running the parser with the export fix; gracefully
                    # omitted rather than guessed at if it's not there yet).
                    _ss_lineup_txt = None
                    if "uww_lineup" in _ss_best_rows.columns:
                        _ss_lu_rows = _ss_best_rows[_ss_best_rows["uww_lineup"].notna()]
                        if not _ss_lu_rows.empty:
                            _ss_lu_grouped = _ss_lu_rows.groupby("uww_lineup").agg(Attempts=("_make", "count"), Makes=("_make", "sum")).reset_index()
                            _ss_lu_grouped = _ss_lu_grouped[_ss_lu_grouped["Attempts"] >= 3]
                            if not _ss_lu_grouped.empty:
                                _ss_lu_grouped["FG%"] = 100 * _ss_lu_grouped["Makes"] / _ss_lu_grouped["Attempts"]
                                _ss_best_lu = _ss_lu_grouped.nlargest(1, "FG%").iloc[0]
                                _ss_lineup_txt = f"{_last_names(_ss_best_lu['uww_lineup'])} gets it best ({int(_ss_best_lu['Makes'])}/{int(_ss_best_lu['Attempts'])}, {_ss_best_lu['FG%']:.0f}%)"

                    # Which offensive play call generates this shot type most often (needs a coach_note with
                    # an extractable play call on the same event -- only present for games with a recap CSV).
                    _ss_play_txt = None
                    if "coach_note" in _ss_best_rows.columns:
                        _ss_calls = resolve_play_calls(_ss_best_rows).dropna()
                        if not _ss_calls.empty:
                            _ss_top_call = _ss_calls.value_counts().idxmax()
                            _ss_play_txt = f"Usually comes off {_ss_top_call} ({int((_ss_calls == _ss_top_call).sum())}x this season)"

                    _ss_parts = [p for p in [_ss_lineup_txt, _ss_play_txt] if p]
                    _ss_reason = " -- ".join(_ss_parts) if _ss_parts else "Not enough lineup or play-call data linked to these shots yet to say who runs this most."
                    # CONFIRMED BUG (fixed here): this title used to read "UWW Best Offensive Shot Selection &
                    # Quality: Cut to the basket" -- a report-section label pasted in front of the shot name,
                    # not something a coach would actually say. describe_shot_look() is the same helper the
                    # "Attack their weakest look" card below already uses for this; reusing it here keeps the
                    # two cards consistent AND picks up its handling of an unclassified/untagged mechanic,
                    # which this line previously didn't have at all.
                    _keys.append((
                        "\U0001f3c0",
                        "Feature our best look: " + describe_shot_look(_ss_best_mechanic, _ss_best_contest),
                        f"{int(_ss_best['Makes'])}/{int(_ss_best['Attempts'])} ({_ss_best['FG%']:.0f}%) this season",
                        _ss_reason,
                        "Data-Driven",
                    ))
        except Exception:
            pass

        # E3. Attack the opponent's worst-defended shot type -- using REAL third-party data now: shots taken
        # by whoever the upcoming opponent played in each of their games BEFORE facing UWW (uww_opponent_
        #_prior_games_pbp, exported from the parser's pbp_events_upcoming -- previously computed for
        # print/diagnostic output only inside the notebook, never exported, so this was genuinely impossible
        # from the app until now). The shot type where THOSE opponents were most efficient is this opponent's
        # worst-defended type. Once identified, cross-referenced against UWW\'s own SEASON-WIDE shot data
        # (not scoped to a prior UWW-vs-this-opponent meeting -- none may exist) to find which UWW lineup and
        # play call already generates that same shot type most often, i.e. who/what to feature to attack it.
        try:
            _aw_prior = load_table("uww_opponent_prior_games_pbp")
            _aw_third_party = _aw_prior[
                _aw_prior["team"].notna() & (_aw_prior["team"] != short_opponent)
                & (_aw_prior["event_type"].isin(["made_shot", "missed_shot"]))
            ].copy() if not _aw_prior.empty else pd.DataFrame()
            _aw_third_party = _aw_third_party[_aw_third_party["video_description"].notna()] if not _aw_third_party.empty else _aw_third_party

            if _aw_third_party.empty:
                _keys.append((
                    "\U0001f3af", "Attack Opponent Worst Offensive Shot Selection & Quality", None,
                    f"No video-tagged data yet for teams {short_opponent} played before facing UWW this "
                    f"season -- needs a local/live-scraped _pbp and _video file for each of those games (see "
                    f"the parser's \'opponent's games before facing Whitewater\' section).",
                    "Data-Driven",
                ))
            else:
                _aw_third_party["_mechanic"] = _aw_third_party["video_description"].apply(extract_shot_mechanic)
                _aw_third_party["_contest"] = _aw_third_party["video_description"].apply(extract_contest)
                _aw_third_party["_make"] = _aw_third_party["event_type"] == "made_shot"
                _aw_grouped = _aw_third_party[_aw_third_party["_mechanic"].notna() & _aw_third_party["_contest"].notna()].groupby(["_mechanic", "_contest"]).agg(
                    Attempts=("_make", "count"), Makes=("_make", "sum"),
                ).reset_index()
                _aw_grouped = _aw_grouped[_aw_grouped["Attempts"] >= 5]  # scoped to a handful of prior games, not a full season
                if _aw_grouped.empty:
                    _keys.append((
                        "\U0001f3af", "Attack Opponent Worst Offensive Shot Selection & Quality", None,
                        f"Some video-tagged data exists for teams {short_opponent} played before UWW, but not "
                        f"enough attempts yet of any one shot type (need 5+) to call one a clear weakness.",
                        "Data-Driven",
                    ))
                else:
                    _aw_grouped["FG%"] = 100 * _aw_grouped["Makes"] / _aw_grouped["Attempts"]
                    _aw_best = _aw_grouped.nlargest(1, "FG%").iloc[0]
                    _aw_best_mechanic, _aw_best_contest = _aw_best["_mechanic"], _aw_best["_contest"]
                    _aw_n_opponents = _aw_third_party.loc[
                        (_aw_third_party["_mechanic"] == _aw_best_mechanic) & (_aw_third_party["_contest"] == _aw_best_contest), "team"
                    ].nunique()
                    _aw_n_tagged_games = (_aw_third_party["game_date"].nunique()
                                          if "game_date" in _aw_third_party.columns else 0)
                    _aw_n_prior_games = opponent_prior_games_scheduled(short_opponent)

                    # Cross-reference against UWW's OWN season-wide shot data (all games, not scoped to
                    # having already played this opponent) for that SAME shot type, to find which lineup and
                    # play call already generates it most for UWW.
                    _aw_uww_all = load_table("uww_pbp_events")
                    _aw_uww_shots = _aw_uww_all[
                        (_aw_uww_all["team"] == "UW-Whitewater") & (_aw_uww_all["event_type"].isin(["made_shot", "missed_shot"]))
                    ].copy() if not _aw_uww_all.empty else pd.DataFrame()
                    _aw_uww_shots = _aw_uww_shots[_aw_uww_shots["video_description"].notna()] if not _aw_uww_shots.empty else _aw_uww_shots
                    _aw_lineup_txt, _aw_play_txt, _aw_volume_txt = None, None, None
                    if not _aw_uww_shots.empty:
                        _aw_uww_shots["_mechanic"] = _aw_uww_shots["video_description"].apply(extract_shot_mechanic)
                        _aw_uww_shots["_contest"] = _aw_uww_shots["video_description"].apply(extract_contest)
                        _aw_uww_shots["_make"] = _aw_uww_shots["event_type"] == "made_shot"
                        _aw_match_rows = _aw_uww_shots[(_aw_uww_shots["_mechanic"] == _aw_best_mechanic) & (_aw_uww_shots["_contest"] == _aw_best_contest)]

                        if "uww_lineup" in _aw_match_rows.columns:
                            _aw_lu_rows = _aw_match_rows[_aw_match_rows["uww_lineup"].notna()]
                            if not _aw_lu_rows.empty:
                                _aw_lu_all = _aw_lu_rows.groupby("uww_lineup").agg(
                                    Attempts=("_make", "count"), Makes=("_make", "sum"),
                                ).reset_index()
                                _aw_lu_all["FG%"] = 100 * _aw_lu_all["Makes"] / _aw_lu_all["Attempts"]

                                def _aw_lu_line(_r, _show_pct=True):
                                    _nm = _last_names(_r["uww_lineup"])
                                    return (f"{_nm} {int(_r['Makes'])}/{int(_r['Attempts'])} ({_r['FG%']:.0f}%)"
                                            if _show_pct else
                                            f"{_nm} {int(_r['Attempts'])}x ({_r['FG%']:.0f}%)")

                                # Two different questions, two different lists. Ranking by FG% alone rewards a
                                # unit that happened to go 3/3, so the accuracy list keeps the 3+ attempt floor
                                # and the volume list answers "who actually generates this shot for us" with no
                                # floor at all -- a coach needs both before deciding who to feature.
                                _aw_lu_qual = _aw_lu_all[_aw_lu_all["Attempts"] >= 3]
                                if not _aw_lu_qual.empty:
                                    _aw_top_fg = _aw_lu_qual.sort_values(["FG%", "Attempts"], ascending=False).head(3)
                                    # One lineup per line: five last names plus a split makes each entry long
                                    # enough that three of them joined by semicolons read as one wall of text.
                                    _aw_lineup_txt = "\n".join(
                                        ["Best on this shot (3+ attempts):"]
                                        + [f"\u2022 {_aw_lu_line(_r)}" for _, _r in _aw_top_fg.iterrows()]
                                    )
                                _aw_top_vol = _aw_lu_all.sort_values(["Attempts", "FG%"], ascending=False).head(3)
                                if not _aw_top_vol.empty:
                                    _aw_volume_txt = "\n".join(
                                        ["Runs it most:"]
                                        + [f"\u2022 {_aw_lu_line(_r, _show_pct=False)}" for _, _r in _aw_top_vol.iterrows()]
                                    )

                        if "coach_note" in _aw_match_rows.columns:
                            _aw_calls = resolve_play_calls(_aw_match_rows).dropna()
                            if not _aw_calls.empty:
                                _aw_top_call = _aw_calls.value_counts().idxmax()
                                _aw_play_txt = f"Usually comes off {_aw_top_call} for us ({int((_aw_calls == _aw_top_call).sum())}x this season)"

                    # One line per angle rather than one run-on sentence -- three lineups per list is too
                    # much to read joined by dashes.
                    _aw_parts = [p for p in [_aw_lineup_txt, _aw_volume_txt, _aw_play_txt] if p]
                    _aw_reason = "\n".join(_aw_parts) if _aw_parts else "Not enough UWW lineup or play-call data linked to this shot type yet to say who runs it most for us."
                    _keys.append((
                        "\U0001f3af",
                        f"Attack their weakest look: {describe_shot_look(_aw_best_mechanic, _aw_best_contest)}",
                        # Say exactly what the sample IS. "across N team(s) they played before UWW" read as
                        # their whole pre-UWW schedule, but N only ever counted the opponents that took THIS
                        # shot type, drawn from the subset of their games that have tagged video at all.
                        (f"Opponents shot {int(_aw_best['Makes'])}/{int(_aw_best['Attempts'])} "
                         f"({_aw_best['FG%']:.0f}%) on this against {short_opponent}, "
                         f"{_aw_n_opponents} different team(s) doing it"
                         + (f" -- across {_aw_n_tagged_games} of {short_opponent}'s "
                            + (f"{_aw_n_prior_games} " if _aw_n_prior_games else "")
                            + "games before UWW (the ones with tagged video)" if _aw_n_tagged_games else "")),
                        _aw_reason,
                        "Data-Driven",
                    ))
        except Exception:
            pass

        # E4. Extra, from the same new data source: what the opponent's OWN offense actually leans on most
        # (by volume, not efficiency) in their games before UWW -- the natural complement to E3, useful for
        # UWW's defensive prep rather than its offensive attack. Tagged into Defensive Efficiency (which
        # already keys on "high-volume" language from earlier work) rather than Offensive Efficiency.
        try:
            _dv_prior = load_table("uww_opponent_prior_games_pbp")
            _dv_own = _dv_prior[
                (_dv_prior["team"] == short_opponent) & (_dv_prior["event_type"].isin(["made_shot", "missed_shot"]))
            ].copy() if not _dv_prior.empty else pd.DataFrame()
            _dv_own = _dv_own[_dv_own["video_description"].notna()] if not _dv_own.empty else _dv_own
            if not _dv_own.empty:
                _dv_own["_mechanic"] = _dv_own["video_description"].apply(extract_shot_mechanic)
                _dv_own["_contest"] = _dv_own["video_description"].apply(extract_contest)
                _dv_own["_make"] = _dv_own["event_type"] == "made_shot"
                _dv_grouped = _dv_own[_dv_own["_mechanic"].notna() & _dv_own["_contest"].notna()].groupby(["_mechanic", "_contest"]).agg(
                    Attempts=("_make", "count"), Makes=("_make", "sum"),
                ).reset_index()
                _dv_grouped = _dv_grouped[_dv_grouped["Attempts"] >= 5]
                if not _dv_grouped.empty:
                    _dv_grouped["FG%"] = 100 * _dv_grouped["Makes"] / _dv_grouped["Attempts"]
                    _dv_top = _dv_grouped.nlargest(1, "Attempts").iloc[0]
                    _keys.append((
                        "\U0001f6e1\ufe0f",
                        f"What {short_opponent} goes to most: {describe_shot_look(_dv_top['_mechanic'], _dv_top['_contest'])}",
                        f"{int(_dv_top['Attempts'])} attempts, {_dv_top['FG%']:.0f}% -- across their games before UWW",
                        "What their offense goes to most often, regardless of how well it's worked -- worth a specific defensive scheme item to take away.",
                        "Data-Driven",
                    ))
        except Exception:
            pass

        # F. Season-stat-based recommendations (pace/style, rebounding, bench trust, clutch, turnovers,
        # closing lineup, top play call) -- same computations as before, now feeding the same list
        # instead of their own separate tile grid.
        _CAT_COLORS = {
            "Ball Security": ("#fff3e0", "#e65100"),
            "Rebounding": ("#e8f5e9", "#2e7d32"),
            "Three-Point Shooting": ("#e3f2fd", "#1565c0"),
            "Free Throws": ("#fce4ec", "#c62828"),
            "Fouls / Discipline": ("#fff8e1", "#f57f17"),
            "Ball Movement / Assists": ("#f3e5f5", "#6a1b9a"),
            "Paint Protection / Blocks": ("#efebe9", "#4e342e"),
            "Perimeter Defense / Ball Pressure/ Create Turnovers": ("#e0f7fa", "#00838f"),
            "Scoring Inside": ("#ede7f6", "#4527a0"),
            "Field Goal Efficiency": ("#e8e0f0", "#4E2A84"),
            "Defensive Efficiency": ("#eceff1", "#37474f"),
            "Offensive Efficiency": ("#fff9c4", "#f9a825"),
            "Personnel/Rotation": ("#e1f5fe", "#0277bd"),
            "Play Calls": ("#ede7f6", "#5e35b1"),
            "Four Factors": ("#e0f2f1", "#00695c"),
            "Transition / Pace": ("#fce4ec", "#ad1457"),
            "Coaching Notes": ("#f1f8e9", "#558b2f"),
        }
        _valid_cats = set(load_table("uww_ktv_splits")["category"].unique()) | set(KTV_CATEGORY_REFERENCE.keys())

        def _keyword_matches(keyword, text_lower):
            """Word-boundary match instead of naive substring -- a bare "3" as a keyword now correctly
            matches "3's"/"3s"/"hit their 3" (a real gap: "hunt transition 3's" matched NO Three-Point
            Shooting keyword under the old naive `kw in text` check, since none of "three"/"3 pt"/"3pt" is a
            literal substring of "transition 3's" -- landing it in "Other" instead of being tagged).

            CONFIRMED BUG (fixed here): plain \\b3\\b, while correctly avoiding "23" (no boundary between two
            digits), does NOT avoid a decimal number ending in .3 -- e.g. "8.3%": "." is a non-word character
            just like a space or apostrophe, so \\b still sees a boundary on both sides of the "3" in "8.3%"
            and fires. This is a common shape in a stat-heavy app (any FG%/turnover-rate/etc. number that
            happens to end in .3), so it was a real, frequent false positive (confirmed: "Pressure their
            biggest turnover triggers" -- containing "(8.3%)" -- landing under Three-Point Shooting instead
            of Perimeter Defense/Ball Pressure/Create Turnovers). Purely numeric keywords (just "3" here) now
            use a decimal-aware pattern instead: a negative lookbehind/lookahead excluding a digit or "." on
            either side, so "8.3%" and "3.5" are correctly excluded while "3's"/"hit 3 shots"/"transition 3"
            still match (apostrophes, spaces, and word characters aren't in the exclusion set).
            """
            if keyword.isdigit():
                pattern = r"(?<![\d.])" + re.escape(keyword) + r"(?:'?s)?(?![\w.])"
            else:
                # (?<!\w) / (?!\w) instead of \b, plus an optional plural/tense suffix on the keyword's
                # last word. Two fixes in one: (a) \b after a keyword ENDING in a non-word character never
                # matched at all -- "fg%" and "3's" could not fire, since \b needs a word char on one side;
                # (b) scouting text is written in whatever tense the coach felt like, so "rebound" missed
                # "rebounds"/"rebounding" and "block" missed "blocks"/"blocking" unless every form was
                # spelled out as its own keyword. The suffix is deliberately additive only (no stripping),
                # so "attacking the paint" still needs its own entry -- prefixes aren't stemmed.
                pattern = r"(?<!\w)" + re.escape(keyword) + r"(?:s|es|ed|ing)?(?!\w)"
            return re.search(pattern, text_lower) is not None

        # Category-level false-positive guards: a keyword can fire on text that is plainly about something
        # else. "three"/"3" is the worst offender -- it is a Three-Point Shooting keyword, but in scouting
        # text it is just as often a count ("three double-digit scorers", "three levels", "three guards"),
        # which was mis-tagging opponent-scoring notes as a shooting key. If a category's exclusion pattern
        # matches AND none of its keywords match outside that pattern, the category is skipped.
        _CATEGORY_EXCLUSIONS = {
            # "foul" (Fouls / Discipline) also fires inside "foul line" -- a Free Throws phrase about
            # GETTING to the line, not about fouling. Scrub that context so "get to the foul line" is a
            # Free Throws key only.
            # "force TO's" / "creates turnovers" describe pressure being applied, not ball security.
            "Ball Security": r"(?:forc|creat|generat|caus)(?:e|es|ed|ing)\s+(?:\w+\s+){0,2}(?:turnovers?|to's)",
            "Fouls / Discipline": r"\bfoul\s+line\b|\bfree[- ]throw\s+line\b",
            # "drive down 3pt attempts" is about REDUCING their threes, not about our drives.
            "Scoring Inside": r"\bdriv(?:e|es|ing)\s+down\b",
            # "efficiency" (Field Goal Efficiency) fires on the literal phrases "offensive efficiency" and
            # "defensive efficiency", which are their own categories -- scrub those two before matching so a
            # key about offensive efficiency doesn't also land under Field Goal Efficiency.
            "Field Goal Efficiency": r"\b(?:offensive|defensive)\s+efficienc(?:y|ies)\b",
            "Ball Movement / Assists": r"\bcreat(?:e|es|ed|ing)\b(?=\s+(?:advantage|advantages|separation|mismatch|mismatches|problems|issues|turnover|turnovers|to's))",
            "Three-Point Shooting": r"\bthree\b(?=\s+(?:double|level|scorer|scorers|players|player|guards|guard|starters|starter|bigs|kids|of\b))|\bthree\s+levels?\b|\bthree[- ]level\b",
        }

        def _match_categories(text):
            text_lower = str(text).lower()
            matched = []
            for _cat, _details in KTV_CATEGORY_REFERENCE.items():
                if _cat not in _valid_cats:
                    continue
                _excl = _CATEGORY_EXCLUSIONS.get(_cat)
                _scrubbed = re.sub(_excl, " ", text_lower) if _excl else text_lower
                for _kw in [_kw.strip() for _kw in _details["keywords"].split(",")]:
                    if _kw and _keyword_matches(_kw, _scrubbed):
                        if _cat not in matched:
                            matched.append(_cat)
                        break
            return matched

        # Same false-positive guard as _CATEGORY_EXCLUSIONS, but per side-phrase: "create" is a UWW
        # phrase, yet "create advantages" in an opponent-strength note is describing THEM, and letting
        # both fire produced a misleading BOTH badge.
        _PHRASE_EXCLUSIONS = {
            "create": r"\bcreat(?:e|es|ed|ing)\b(?=\s+(?:advantage|advantages|separation|mismatch|mismatches|problems|issues|turnover|turnovers|to's))",
        }

        def _detect_side(text):
            text_lower = str(text).lower()
            sides_found = set()
            for phrase, side in PHRASE_SIDE.items():
                if not phrase:
                    continue
                _pe = _PHRASE_EXCLUSIONS.get(phrase)
                _pt = re.sub(_pe, " ", text_lower) if _pe else text_lower
                if _keyword_matches(phrase, _pt):
                    sides_found.add(side)
            if "OPP" in sides_found and "UWW" not in sides_found:
                return "OPP"
            if "UWW" in sides_found and "OPP" not in sides_found:
                return "UWW"
            if "OPP" in sides_found and "UWW" in sides_found:
                return "BOTH"
            return None

        def _side_badge_html(side):
            if side == "UWW":
                return ' <span style="background:#4E2A84;color:#fff;font-size:0.65rem;font-weight:700;padding:2px 6px;border-radius:8px;margin-left:3px;">UWW</span>'
            elif side == "OPP":
                return ' <span style="background:#1a1a2e;color:#fff;font-size:0.65rem;font-weight:700;padding:2px 6px;border-radius:8px;margin-left:3px;">OPP</span>'
            elif side == "BOTH":
                return (' <span style="background:#4E2A84;color:#fff;font-size:0.65rem;font-weight:700;padding:2px 6px;border-radius:8px 0 0 8px;margin-left:3px;">UWW</span>'
                        '<span style="background:#1a1a2e;color:#fff;font-size:0.65rem;font-weight:700;padding:2px 6px;border-radius:0 8px 8px 0;">OPP</span>')
            return ""

        def _badges_html(cats, side=None):
            badges = _side_badge_html(side) if side else ""
            for c in cats:
                bg, fg = _CAT_COLORS.get(c, ("#e8e0f0", "#4E2A84"))
                badges += f' <span style="background:{bg};color:{fg};font-size:0.7rem;font-weight:600;padding:2px 8px;border-radius:10px;margin-left:4px;">{html.escape(c)}</span>'
            return badges

        # Source badges use an outlined style (colored border + white fill) instead of the category badges'
        # solid fill, so the two badge types read as visually distinct at a glance. Full Game Plan items use
        # their own game-plan "category" field as the source badge instead of one generic "Full Game Plan"
        # label -- those category names are staff-defined per opponent, so they aren't enumerable here and
        # fall back to _source_badge_html's default gray outline instead of a specific color.
        _SOURCE_COLORS = {
            "Data-Driven": "#37474f",
            "Keys to Victory": "#4E2A84",
            "Team Strengths": "#c62828",
            "Lineup Scouting": "#5d4037",
            "Coach Notes": "#00695c",
        }

        def _source_badge_html(source):
            if not source:
                return ""
            _color = _SOURCE_COLORS.get(source, "#666")
            return f' <span style="border:1px solid {_color};color:{_color};background:#fff;font-size:0.65rem;font-weight:600;padding:1px 7px;border-radius:8px;margin-left:4px;">{html.escape(source)}</span>'

        _at_a_glance = []  # list of (label, value, help) -- filled defensively, one try per tile
        _card_data = {}  # richer detail behind each tile (top-3 plays, 2 bench players, etc.), for the full
        # card grid below -- stashed here instead of relying on each try block's own local variables still
        # existing afterward, since a try block that raises partway through wouldn't leave them assigned.

        try:
            _ag_notes = load_table("uww_coach_notes")
            _ag_off = _ag_notes[_ag_notes["clip_side"] == "Offense"].copy() if not _ag_notes.empty and "clip_side" in _ag_notes.columns else pd.DataFrame()
            _ag_off["play_call"] = resolve_play_calls(_ag_off) if not _ag_off.empty else None
            _ag_calls = _ag_off[_ag_off["play_call"].notna()].copy() if not _ag_off.empty else pd.DataFrame()
            if not _ag_calls.empty:
                _ag_calls["_mk"] = _ag_calls["result"].astype(str).str.contains("Make", case=False, na=False)
                _ag_calls["_at"] = _ag_calls["result"].astype(str).str.contains("Make|Miss", case=False, regex=True, na=False)
                # Same possession can appear twice (a recap note and the season play log both tagged it) --
                # see the Analytics page's play-call table for the full reasoning. Collapse before counting.
                if "time_remaining_seconds" in _ag_calls.columns:
                    _ag_k = [c for c in ["opponent", "period", "time_remaining_seconds", "team", "player", "play_call"]
                             if c in _ag_calls.columns]
                    _ag_t = _ag_calls[_ag_calls["time_remaining_seconds"].notna()].drop_duplicates(subset=_ag_k)
                    _ag_calls = pd.concat([_ag_t, _ag_calls[_ag_calls["time_remaining_seconds"].isna()]], ignore_index=True)
                _card_data["plays_rows"] = _ag_calls
                _ag_sum = summarize_play_calls(_ag_calls, min_possessions=2)
                if not _ag_sum.empty:
                    _ag_best = _ag_sum.nlargest(1, "PPP").iloc[0]
                    _ag_se, _ag_fa = play_call_series(_ag_best["play_call"])
                    _ag_ctx = ", ".join(dict.fromkeys([x for x in [_ag_fa, _ag_se] if x]))
                    _at_a_glance.append((
                        "\U0001f3c0 Top Play", str(_ag_best["play_call"]),
                        (f"{_ag_ctx} series. " if _ag_ctx else "")
                        + f"Best points per possession among plays with 2+ tracked possessions this season: "
                          f"{format_ppp(_ag_best)} over {int(_ag_best['Poss'])} possessions "
                          f"({int(_ag_best['Makes'])}/{int(_ag_best['Attempts'])} shooting)."))
                    _card_data["plays"] = _ag_sum

                    # --- Same two lists, but only from games against teams that PLAY LIKE the upcoming
                    # opponent. Season-wide play numbers answer "what works for us"; this answers "what
                    # works against this kind of team", which is the question a game plan actually asks.
                    # Reuses the same style-profile ranking the Comparable Opponents panel is built on.
                    try:
                        _sp_index = sorted(opponent_style_profiles().index.astype(str), key=len, reverse=True)
                        _sp_by_short = {}
                        for _sp_raw in _ag_calls["opponent"].dropna().unique():
                            _sp_short = resolve_short_opponent(_sp_raw, _sp_index)
                            if _sp_short and _sp_short != short_opponent:
                                _sp_by_short.setdefault(_sp_short, []).append(_sp_raw)
                        _sp_ranked, _ = comparable_opponents(short_opponent, list(_sp_by_short), k=3)
                        if _sp_ranked is not None and not _sp_ranked.empty:
                            _sp_names = list(_sp_ranked["opponent"])
                            _sp_raw_names = [r for n in _sp_names for r in _sp_by_short.get(n, [])]
                            _sp_rows = _ag_calls[_ag_calls["opponent"].isin(_sp_raw_names)]
                            if not _sp_rows.empty:
                                # A 1-possession floor here, not the season list's 2: three games is a
                                # small sample by construction, and a 2-possession floor would empty it.
                                _sp_sum = summarize_play_calls(_sp_rows, min_possessions=1)
                                if not _sp_sum.empty:
                                    _card_data["plays_similar"] = {
                                        "summary": _sp_sum,
                                        "opponents": [(n, int(_sp_ranked.loc[_sp_ranked["opponent"] == n, "match"].iloc[0]))
                                                      for n in _sp_names],
                                    }
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            _ag_op = load_table("uww_player_profiles")
            _ag_op = _ag_op[_ag_op["opponent"] == short_opponent] if not _ag_op.empty and short_opponent else pd.DataFrame()
            if not _ag_op.empty and "PTS" in _ag_op.columns:
                _ag_op = _ag_op.copy()
                _ag_op["PTS"] = pd.to_numeric(_ag_op["PTS"], errors="coerce")
                _ag_team_pts = _ag_op["PTS"].sum()
                if _ag_team_pts > 0:
                    _ag_share = 100 * _ag_op.nlargest(2, "PTS")["PTS"].sum() / _ag_team_pts
                    _ag_val = "Concentrated" if _ag_share >= 45 else "Balanced"
                    _at_a_glance.append(("\U0001f3af Scoring Focus", _ag_val, f"Their top 2 scorers account for {_ag_share:.0f}% of team points."))
                    _card_data["scoring_reliance"] = (_ag_share, _ag_val)
        except Exception:
            pass

        try:
            _ag_box = load_table("uww_pbp_box_score")
            _ag_uww_side = _ag_box[_ag_box["team"] == "UW-Whitewater"] if not _ag_box.empty else pd.DataFrame()
            _ag_opp_side = _ag_box[_ag_box["team"] != "UW-Whitewater"] if not _ag_box.empty else pd.DataFrame()
            _ag_ng = _ag_uww_side["opponent"].nunique() if not _ag_uww_side.empty else 0
            _ag_tt = load_table("uww_opponent_team_totals")
            _ag_tt_row = _ag_tt[_ag_tt["opponent"] == short_opponent] if not _ag_tt.empty and short_opponent else pd.DataFrame()
            if _ag_ng > 0 and not _ag_tt_row.empty and "team_ppg" in _ag_tt_row.columns:
                _ag_pace_d = compute_efficiency_pace(_ag_uww_side, _ag_opp_side, _ag_ng)
                _ag_opp_ppg = safe_float(_ag_tt_row.iloc[0].get("team_ppg"))
                _ag_opp_allowed = safe_float(_ag_tt_row.iloc[0].get("opp_ppg_allowed")) if "opp_ppg_allowed" in _ag_tt_row.columns else None

                # How UWW has actually fared at each tempo -- split UWW's own games by their per-game pace
                # (median-split against themselves, so "fast" and "slow" mean fast/slow FOR THIS TEAM, not
                # against some league constant). Shared with the Previous Games page's per-game Pace
                # indicator via compute_uww_pace_by_game() -- see that function's docstring for why.
                try:
                    _ps_df, _ps_median = compute_uww_pace_by_game()
                except Exception:
                    _ps_df, _ps_median = None, None

                # The mirror image: how the OPPONENT'S opponents fared at each tempo, from the upcoming
                # opponent's own prior games -- what has actually worked AGAINST them, rather than just
                # what UWW happens to be good at.
                _po_df, _po_median = None, None
                try:
                    _po_box = load_table("uww_opponent_prior_games_box_score")
                    if not _po_box.empty and {"team", "game_date"} <= set(_po_box.columns):
                        _po_rows = []
                        for _po_k, _po_g in _po_box.groupby([c for c in ["opponent", "game_date"] if c in _po_box.columns], dropna=False):
                            _po_them = _po_g[_po_g["team"] == short_opponent]
                            _po_foe = _po_g[_po_g["team"] != short_opponent]
                            if _po_them.empty or _po_foe.empty:
                                continue
                            # Rated from the OPPONENT-OF-THEIRS side, so Net Rtg reads "how the other
                            # team did against them" without needing to be mentally flipped.
                            _po_d = compute_efficiency_pace(_po_foe, _po_them, 1)
                            _po_rows.append({
                                "game_date": _po_g["game_date"].iloc[0] if "game_date" in _po_g.columns else None,
                                "foe": _po_foe["team"].iloc[0],
                                "pace": _po_d["Pace"], "net": _po_d["Net Rtg"], "ortg": _po_d["ORtg"],
                                "won": (_po_foe["PTS"].sum() > _po_them["PTS"].sum()) if "PTS" in _po_foe.columns else None,
                            })
                        _po_all = pd.DataFrame(_po_rows)
                        if len(_po_all) >= 4:
                            _po_median = _po_all["pace"].median()
                            _po_all["_bucket"] = _po_all["pace"].apply(lambda v: "fast" if v > _po_median else "slow")
                            _po_df = _po_all
                except Exception:
                    pass

                # CONFIRMED CHANGE (requested): this card used to always show once team-total PPG data existed
                # for the opponent, recommending "Push Tempo" purely because they give up more than they score
                # on average -- a scoring-margin read that has nothing to do with pace specifically, and shown
                # regardless of whether UWW is actually any good at playing that way. Now it only fires when
                # BOTH sides of a real pace mismatch line up, using the two splits above: the opponent has
                # genuinely struggled against that tempo in their own past games (their foes' average Net Rtg
                # in that bucket is positive), AND UWW has actually been good playing that way itself (UWW's
                # own average Net Rtg in that bucket is positive). Needs both splits (each already gated at 4+
                # games) -- no card at all if either is missing, or if neither tempo clears both bars.
                _ag_style = None
                if _ps_df is not None and _po_df is not None:
                    _ps_net = _ps_df.groupby("_bucket")["net"].mean()
                    _po_net = _po_df.groupby("_bucket")["net"].mean()
                    for _bucket, _label in (("fast", "Push Tempo"), ("slow", "Slow It Down")):
                        if (_bucket in _ps_net.index and _bucket in _po_net.index
                                and _ps_net[_bucket] > 0 and _po_net[_bucket] > 0):
                            _ag_style = _label
                            break  # "fast" checked first: if both tempos somehow clear the bar, pushing the
                                   # pace is the more decisive, higher-ceiling call.

                if _ag_style and _ag_opp_ppg is not None and _ag_opp_allowed is not None:
                    _at_a_glance.append(("\u23f1\ufe0f Style", _ag_style, f"UWW season pace: {_ag_pace_d['Pace']:.1f} poss/game. {esc(short_opponent)}: {_ag_opp_ppg:.1f} PPG, allows {_ag_opp_allowed:.1f}."))
                    _card_data["pace_style"] = (_ag_pace_d, _ag_opp_ppg, _ag_opp_allowed, _ag_style)
                    _card_data["pace_style_history"] = {"games": _ps_df, "median": _ps_median}
                    _card_data["pace_style_opp_history"] = {"games": _po_df, "median": _po_median}
        except Exception:
            pass

        try:
            _ag_box2 = load_table("uww_pbp_box_score")
            _ag_op2 = load_table("uww_player_profiles")
            _ag_op2 = _ag_op2[_ag_op2["opponent"] == short_opponent] if not _ag_op2.empty and short_opponent else pd.DataFrame()
            _ag_uww_r = _ag_box2[_ag_box2["team"] == "UW-Whitewater"] if not _ag_box2.empty else pd.DataFrame()
            _ag_ng2 = _ag_uww_r["opponent"].nunique() if not _ag_uww_r.empty else 0
            if _ag_ng2 > 0 and not _ag_op2.empty and "REB" in _ag_uww_r.columns:
                _ag_op2 = _ag_op2.copy()
                _ag_op2["REB"] = pd.to_numeric(_ag_op2["REB"], errors="coerce")
                _ag_uww_rpg = _ag_uww_r["REB"].sum() / _ag_ng2
                _ag_opp_rpg = _ag_op2["REB"].sum()
                _ag_diff = _ag_uww_rpg - _ag_opp_rpg
                _ag_reb_val = "Crash the Glass" if _ag_diff >= 3 else ("Prioritize Balance" if _ag_diff <= -3 else "Roughly Even")
                _at_a_glance.append(("\U0001f4aa Boards", _ag_reb_val, f"UWW: {_ag_uww_rpg:.1f} RPG this season. {esc(short_opponent)}: {_ag_opp_rpg:.1f} RPG."))
                _card_data["rebounding"] = (_ag_uww_rpg, _ag_opp_rpg, _ag_reb_val)
        except Exception:
            pass

        try:
            if _uww_lu_agg is not None and not _uww_lu_agg.empty:
                _ag_lu = _uww_lu_agg[_uww_lu_agg["MIN"] >= 10].copy()
                if not _ag_lu.empty:
                    _ag_lu["rate"] = _ag_lu["+/-"] / _ag_lu["MIN"]
                    _ag_best_lu = _ag_lu.nlargest(1, "rate").iloc[0]
                    _at_a_glance.append(("\U0001f512 Closing 5", _last_names(_ag_best_lu["lineup"]), f"Best net rating this season among lineups with real minutes: {_ag_best_lu['rate']:+.2f}/min over {_ag_best_lu['MIN']:.0f} minutes."))
                    _card_data["closing_lineup"] = _ag_best_lu
        except Exception:
            pass

        try:
            _ag_box3 = load_table("uww_pbp_box_score")
            _ag_uww_b = _ag_box3[_ag_box3["team"] == "UW-Whitewater"] if not _ag_box3.empty else pd.DataFrame()
            if not _ag_uww_b.empty and "started" in _ag_uww_b.columns:
                _ag_rate = _ag_uww_b.groupby("player")["started"].mean()
                _ag_bench_names = _ag_rate[_ag_rate < 0.5].index.tolist()
                _ag_bench_rows = _ag_uww_b[_ag_uww_b["player"].isin(_ag_bench_names)].copy()
                if not _ag_bench_rows.empty:
                    _ag_bench_rows["_gs"] = _ag_bench_rows.apply(compute_game_score, axis=1)
                    _ag_bench_sum = _ag_bench_rows.groupby("player").agg(GP=("_gs", "count"), Avg=("_gs", "mean")).reset_index()
                    # No games-played minimum: every bench player who has logged a game is eligible here,
                    # so a small sample is surfaced rather than hidden. The games count is shown with the
                    # figure, so a one-game average is visible as exactly that.
                    if not _ag_bench_sum.empty:
                        _ag_top_bench = _ag_bench_sum.nlargest(1, "Avg").iloc[0]
                        _at_a_glance.append(("\U0001fa91 Bench Trust", str(_ag_top_bench["player"]), f"{_ag_top_bench['Avg']:.1f} avg Game Score off the bench over {int(_ag_top_bench['GP'])} games this season."))
                        _card_data["bench"] = _ag_bench_sum
        except Exception:
            pass

        try:
            _ag_clutch = load_table("uww_clutch_events")
            _ag_clutch_u = _ag_clutch[_ag_clutch["team"] == "UW-Whitewater"].copy() if not _ag_clutch.empty else pd.DataFrame()
            if not _ag_clutch_u.empty:
                def _ag_pts(r):
                    if r.get("event_type") == "made_shot":
                        try:
                            return int(r.get("shot_type"))
                        except (TypeError, ValueError):
                            return 0
                    return 1 if r.get("event_type") == "free_throw_made" else 0
                _ag_clutch_u["_pts"] = _ag_clutch_u.apply(_ag_pts, axis=1)
                _ag_clutch_scoring = _ag_clutch_u[_ag_clutch_u["_pts"] > 0].groupby("player")["_pts"].sum()
                if not _ag_clutch_scoring.empty:
                    _ag_top_clutch = _ag_clutch_scoring.idxmax()
                    _at_a_glance.append(("\U0001f3c1 Clutch Option", str(_ag_top_clutch), f"{int(_ag_clutch_scoring.max())} points in clutch minutes (last 5 min, score within 8) this season -- the most of anyone on the roster."))
                    _card_data["clutch"] = _ag_clutch_scoring
        except Exception:
            pass

        try:
            _ag_op3 = load_table("uww_player_profiles")
            _ag_op3 = _ag_op3[_ag_op3["opponent"] == short_opponent] if not _ag_op3.empty and short_opponent else pd.DataFrame()
            _ag_box4 = load_table("uww_pbp_box_score")
            if not _ag_op3.empty and not _ag_box4.empty and "TO" in _ag_op3.columns:
                _ag_games = get_opponent_games_played(short_opponent)
                _ag_topg = pd.to_numeric(_ag_op3["TO"], errors="coerce").sum() / _ag_games if _ag_games > 0 else 0
                if _ag_topg > 0:
                    _ag_to_val = "Press / Extend" if _ag_topg >= 13 else "Standard Pressure"
                    _at_a_glance.append(("\U0001f504 TO Pressure", _ag_to_val, f"{esc(short_opponent)} averages {_ag_topg:.1f} turnovers/game (season total, not opponent-adjusted)."))
                    _ag_uww_side4 = _ag_box4[_ag_box4["team"] == "UW-Whitewater"] if not _ag_box4.empty else pd.DataFrame()
                    _ag_ng4 = _ag_uww_side4["opponent"].nunique() if not _ag_uww_side4.empty else 0
                    _ag_uww_stl_pg = _ag_uww_side4["STL"].sum() / _ag_ng4 if _ag_ng4 > 0 and "STL" in _ag_uww_side4.columns else 0
                    _card_data["turnovers"] = (_ag_topg, _ag_uww_stl_pg, _ag_to_val)
        except Exception:
            pass

        # --- Opponent-adjusted efficiency (KenPom's method, see adjusted_efficiency()) ------------------
        try:
            _ae = adjusted_efficiency()
            if _ae and short_opponent:
                _card_data["adj_efficiency"] = {
                    "core": _ae,
                    "opp_adj": (_ae["opponents_adj_off"].get(short_opponent), _ae["opponents_adj_def"].get(short_opponent)),
                    "opp_raw": (_ae["opponents_raw_off"].get(short_opponent), _ae["opponents_raw_def"].get(short_opponent)),
                }
                _at_a_glance.append((
                    "\U0001f4c8 Adj. Net Rtg",
                    f"{_ae['uww']['adj_off'] - _ae['uww']['adj_def']:+.1f}",
                    f"UWW opponent-adjusted: {_ae['uww']['adj_off']:.1f} off / {_ae['uww']['adj_def']:.1f} def "
                    f"(raw {_ae['uww']['raw_off']:.1f} / {_ae['uww']['raw_def']:.1f}) over {_ae['games']} games."))
        except Exception:
            pass

        # --- Weighted Four Factors: which factor actually decides this game -------------------------------
        try:
            _ff_box = load_table("uww_pbp_box_score")
            _ff_uww = _ff_box[_ff_box["team"] == "UW-Whitewater"] if not _ff_box.empty else pd.DataFrame()
            _ff_opp_side = _ff_box[_ff_box["team"] != "UW-Whitewater"] if not _ff_box.empty else pd.DataFrame()
            _ff_prior = load_table("uww_opponent_prior_games_box_score")
            _ff_them = _ff_prior[_ff_prior["team"] == short_opponent] if not _ff_prior.empty else pd.DataFrame()
            _ff_foes = _ff_prior[_ff_prior["team"] != short_opponent] if not _ff_prior.empty else pd.DataFrame()
            if not _ff_uww.empty and not _ff_opp_side.empty and not _ff_them.empty and not _ff_foes.empty:
                _ff_us = compute_four_factors(_ff_uww, _ff_opp_side)
                _ff_they = compute_four_factors(_ff_them, _ff_foes)
                _ff_rows = []
                for _k, _w in FOUR_FACTOR_WEIGHTS.items():
                    _a, _b = safe_float(_ff_us.get(_k)), safe_float(_ff_they.get(_k))
                    if _a is None or _b is None:
                        continue
                    _edge = (_a - _b) if FOUR_FACTOR_HIGHER_IS_BETTER[_k] else (_b - _a)
                    _ff_rows.append({"factor": _k, "uww": _a, "opp": _b, "edge": _edge, "weight": _w,
                                     "weighted": _edge * _w})
                if _ff_rows:
                    _card_data["four_factors"] = pd.DataFrame(_ff_rows)
        except Exception:
            pass

        # --- Scoring runs -------------------------------------------------------------------------------
        try:
            _sr_runs = load_table("uww_scoring_runs")
            if not _sr_runs.empty and {"uww_biggest_run", "opponent_biggest_run"} <= set(_sr_runs.columns):
                _sr_r = _sr_runs.copy()
                for _c in ("uww_biggest_run", "opponent_biggest_run", "uww_largest_lead", "opponent_largest_lead"):
                    if _c in _sr_r.columns:
                        _sr_r[_c] = pd.to_numeric(_sr_r[_c], errors="coerce")
                _sr_n = len(_sr_r)
                _sr_off_rate = (_sr_r["uww_biggest_run"] >= 10).sum() / _sr_n if _sr_n else 0
                _sr_def_rate = (_sr_r["opponent_biggest_run"] >= 10).sum() / _sr_n if _sr_n else 0

                # CONFIRMED CHANGE (requested): built out to a full two-sided mismatch check, same shape as
                # the Pace & Style rework -- now checks not just whether UWW does this often, but whether
                # THIS specific opponent has shown the matching vulnerability/tendency in their own prior
                # games. uww_opponent_prior_games_pbp has no precomputed run table of its own (unlike UWW's
                # games, which already have uww_scoring_runs), so detect_biggest_runs_by_game() replicates
                # the parser's own run-detection algorithm against it exactly, rather than inventing a
                # different definition of "run" that could quietly disagree with uww_scoring_runs' own.
                _opp_own_rate, _opp_foe_rate, _opp_n = None, None, 0
                _opp_pbp = load_table("uww_opponent_prior_games_pbp")
                if not _opp_pbp.empty and short_opponent:
                    _opp_runs = detect_biggest_runs_by_game(_opp_pbp)
                    if not _opp_runs.empty:
                        _opp_n = _opp_runs[["opponent", "game_date"]].drop_duplicates().shape[0]
                        if _opp_n >= 3:
                            _opp_own = _opp_runs[_opp_runs["team"] == short_opponent]
                            _opp_foe = _opp_runs[_opp_runs["team"] != short_opponent]
                            _opp_own_rate = (_opp_own["run_points"] >= 10).sum() / _opp_n
                            _opp_foe_rate = (_opp_foe["run_points"] >= 10).sum() / _opp_n

                # "Runs We Go On" is only a real key if WE actually do it often AND this opponent has shown
                # (in their own prior games, against other teams) that they give up big runs often -- i.e.
                # they're genuinely vulnerable to it, not just a hypothetical target.
                if _sr_off_rate >= 0.5 and _opp_foe_rate is not None and _opp_foe_rate >= 0.5:
                    _card_data["scoring_runs_off"] = _sr_r
                    _card_data["scoring_runs_off_opp"] = {"rate": _opp_foe_rate, "n": _opp_n}

                # "Runs Against Us" is only a real key if WE actually give them up often AND this opponent has
                # shown (in their own prior games) that they GO ON big runs against other teams often -- i.e.
                # they're a genuinely run-prone team we need to be ready to weather.
                if _sr_def_rate >= 0.5 and _opp_own_rate is not None and _opp_own_rate >= 0.5:
                    _card_data["scoring_runs_def"] = _sr_r
                    _card_data["scoring_runs_def_opp"] = {"rate": _opp_own_rate, "n": _opp_n}
        except Exception:
            pass

        # --- Lineup stints ------------------------------------------------------------------------------
        try:
            _ls = load_table("uww_lineup_stints")
            if not _ls.empty and {"uww_lineup", "stint_minutes", "uww_margin_change"} <= set(_ls.columns):
                _ls = _ls.copy()
                _ls["stint_minutes"] = pd.to_numeric(_ls["stint_minutes"], errors="coerce")
                _ls["uww_margin_change"] = pd.to_numeric(_ls["uww_margin_change"], errors="coerce")
                _ls_g = _ls.dropna(subset=["uww_lineup"]).groupby("uww_lineup").agg(
                    Minutes=("stint_minutes", "sum"), Margin=("uww_margin_change", "sum"),
                    Stints=("stint_minutes", "size"),
                ).reset_index()
                _ls_g = _ls_g[_ls_g["Minutes"] >= 4]
                if not _ls_g.empty:
                    _ls_g["Per40"] = 40 * _ls_g["Margin"] / _ls_g["Minutes"].replace(0, float("nan"))
                    _card_data["lineup_stints"] = _ls_g
        except Exception:
            pass

        # --- Coach-note sentiment -----------------------------------------------------------------------
        try:
            _ns_notes = load_table("uww_coach_notes")
            _ns_uww = _ns_notes[_ns_notes["team"] == "UW-Whitewater"] if not _ns_notes.empty and "team" in _ns_notes.columns else pd.DataFrame()
            if not _ns_uww.empty and "coach_note" in _ns_uww.columns:
                _ns_pos, _ns_neg = {}, {}
                for _nt in _ns_uww["coach_note"].dropna():
                    for _seg in str(_nt).split(","):
                        _seg = _seg.strip()
                        if len(_seg) < 5:
                            continue
                        _key = _seg.lstrip("+- ").strip().title()
                        if _seg.startswith("+"):
                            _ns_pos[_key] = _ns_pos.get(_key, 0) + 1
                        elif _seg.startswith("-"):
                            _ns_neg[_key] = _ns_neg.get(_key, 0) + 1
                if _ns_pos or _ns_neg:
                    _ns_theme_rows = note_theme_table(_ns_uww)
                    _ns_theme_top = []
                    if not _ns_theme_rows.empty:
                        _ns_ts = _ns_theme_rows.groupby("theme").agg(
                            n=("note", "count"), pos=("pos", "sum"), neg=("neg", "sum")).reset_index()
                        _ns_theme_top = [(r["theme"], r["n"], r["pos"], r["neg"])
                                         for _, r in _ns_ts.nlargest(4, "n").iterrows()]
                    _card_data["note_sentiment"] = {
                        "pos": sorted(_ns_pos.items(), key=lambda kv: -kv[1])[:4],
                        "neg": sorted(_ns_neg.items(), key=lambda kv: -kv[1])[:4],
                        "themes": _ns_theme_top,
                        "n_notes": int(_ns_uww["coach_note"].notna().sum()),
                    }
        except Exception:
            pass

        # --- Coaching flags for UWW players --------------------------------------------------------------
        try:
            _cf = load_table("uww_coaching_flags")
            if not _cf.empty and {"player", "flag", "sentiment"} <= set(_cf.columns):
                _card_data["coaching_flags"] = _cf.copy()
        except Exception:
            pass

        # NOTE: _at_a_glance itself is no longer converted into condensed "Data-Driven" entries in _keys --
        # the Full Game Plan Recommendations grid below is the sole representation of this data now, not an
        # addition alongside a condensed duplicate of it in the Keys to Victory list.

        # --- Full Game Plan Recommendations: the fuller version of the 8 tiles above (top-3 plays and a
        # "use sparingly" list instead of just the single best/worst, 2 bench/clutch players instead of 1,
        # the opponent's actual lineup names, etc.). This REPLACES the condensed single-line "Data-Driven"
        # entries that used to also appear in the Keys to Victory list below -- shown here instead of there,
        # not in addition to it. ---
        # --- Full Game Plan Recommendation cards (Plays to Lean On, Opponent Scoring Reliance, Pace & Style,
        # Rebounding Edge, Bench Trust Plan, Late-Game Trust, Turnover-Forcing Opportunity, Recommended
        # Closing Lineup) -- defined as render functions here, keyed the same as _card_data, and CALLED from
        # within each category's own section further down instead of as a separate top-level block. This is
        # what actually combines them with the rest of Keys to Victory: a coach looking at "Rebounding" sees
        # the Rebounding Edge card right alongside every other Rebounding-tagged item, not in a different
        # section of the page.
        def _fp_label(_call):
            """Play name plus where it sits in the playbook -- 'Panther-4 "P4" (Panther, Specials)'.
            Without the family a coach reads three Panther entries as three unrelated sets."""
            _se, _fa = play_call_series(_call)
            _ctx = ", ".join(dict.fromkeys([x for x in [_fa, _se] if x]))
            return f"{_call}" + (f" _({_ctx})_" if _ctx else "")

        def _fp_best_worst(_df, _n_best=3, _n_worst=2, _suffix=""):
            """Render the Best/Worst pair off one play summary table, ranked on POINTS PER POSSESSION with
            FG% alongside. Worst excludes anything already named as best, so a short list doesn't print the
            same play under both headings."""
            _rank = "PPP" if "PPP" in _df.columns else "FG%"
            _best = _df.nlargest(_n_best, _rank)
            st.markdown("**Best Overall Plays**" if not _suffix else f"**Best Plays {_suffix}**")
            for _, _r in _best.iterrows():
                st.markdown(f"- **{_fp_label(_r['play_call'])}** -- {format_ppp(_r)} "
                            f"({int(_r['Makes'])}/{int(_r['Attempts'])} over {int(_r.get('Poss', 0))} poss)")
            _worst = _df.nsmallest(_n_worst, _rank)
            _worst = _worst[~_worst["play_call"].isin(_best["play_call"])]
            if not _worst.empty:
                st.markdown("**Worst Overall Plays**" if not _suffix else f"**Worst Plays {_suffix}**")
                for _, _r in _worst.iterrows():
                    st.markdown(f"- {_fp_label(_r['play_call'])} -- {format_ppp(_r)} "
                                f"({int(_r['Makes'])}/{int(_r['Attempts'])} over {int(_r.get('Poss', 0))} poss)")

        def _render_plays_card(_n):
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">{_n}. \U0001f3c0 Play Calls -- Full Season</span>{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            _fp_plays = _card_data["plays"].copy()
            _fp_best_worst(_fp_plays)

            # Family rollup: individual calls are thin (a handful of attempts each), so which PACKAGE is
            # working is the more reliable read -- and it's the level a coach actually game-plans at.
            _fp_plays["_family"] = _fp_plays["play_call"].apply(lambda c: play_call_series(c)[1])
            _fp_fam = _fp_plays[_fp_plays["_family"].astype(str).str.strip() != ""].groupby("_family").agg(
                Attempts=("Attempts", "sum"), Makes=("Makes", "sum"),
                Poss=("Poss", "sum"), Pts=("Pts", "sum"),
            ).reset_index()
            if len(_fp_fam) > 1:
                _fp_fam["PPP"] = _fp_fam["Pts"] / _fp_fam["Poss"].replace(0, float("nan"))
                _fp_fam["FG%"] = 100 * _fp_fam["Makes"] / _fp_fam["Attempts"].replace(0, float("nan"))
                _fp_fam = _fp_fam.nlargest(3, "PPP")
                st.markdown("**By series:** " + " &middot; ".join(
                    f"{_r['_family']} {format_ppp(_r)}" for _, _r in _fp_fam.iterrows()
                ))
            st.caption("Play names, series and family come from the team's playbook catalog; calls not in the catalog keep the tagger's own wording (see the Analytics page for the full breakdown).")
            st.markdown("")

        def _render_similar_plays_card(_n):
            """The same Best/Worst pair, restricted to games against the teams whose STYLE most resembles
            this opponent. Season numbers say what works for us in general; this says what has worked
            against this kind of team, which is what a game plan is actually deciding."""
            _sp = _card_data["plays_similar"]
            _sp_names = _sp["opponents"]
            st.markdown(
                f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">'
                f'{_n}. \U0001f501 Play Calls -- vs Similar Opponents</span>'
                f'{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            st.caption("Style-matched from the same profile the Comparable Opponents panel uses: "
                       + ", ".join(f"{_nm} ({_mt}% match)" for _nm, _mt in _sp_names))
            _fp_best_worst(_sp["summary"], _suffix="vs This Style")
            st.caption("A three-game sample by construction -- a 1-attempt floor, so read it as a pointer, "
                       "not a verdict. The full-season card above is the larger sample.")
            st.markdown("")

        def _render_adj_efficiency_card(_n):
            _ae = _card_data["adj_efficiency"]
            _core, (_o_adj_off, _o_adj_def), (_o_raw_off, _o_raw_def) = _ae["core"], _ae["opp_adj"], _ae["opp_raw"]
            _u = _core["uww"]
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">'
                        f'{_n}. \U0001f4c8 Efficiency, Opponent-Adjusted</span>'
                        f'{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            st.markdown(
                f"**UWW** -- adjusted **{_u['adj_off']:.1f}** off / **{_u['adj_def']:.1f}** def "
                f"(**{_u['adj_off'] - _u['adj_def']:+.1f}** net) &nbsp;·&nbsp; raw {_u['raw_off']:.1f} / "
                f"{_u['raw_def']:.1f} ({_u['raw_off'] - _u['raw_def']:+.1f})")
            if _o_adj_off is not None and _o_adj_def is not None:
                _raw_txt = (f" &nbsp;·&nbsp; raw {_o_raw_off:.1f} / {_o_raw_def:.1f}"
                            if _o_raw_off is not None and _o_raw_def is not None else "")
                st.markdown(
                    f"**{short_opponent}** -- adjusted **{_o_adj_off:.1f}** off / **{_o_adj_def:.1f}** def "
                    f"(**{_o_adj_off - _o_adj_def:+.1f}** net){_raw_txt}")
                _edge = (_u['adj_off'] - _u['adj_def']) - (_o_adj_off - _o_adj_def)
                st.markdown(f"Projected edge on neutral floor: **{_edge:+.1f}** points per 100 possessions.")
            st.caption(
                f"KenPom's method -- each game's efficiency shifted by that opponent's own strength, then "
                f"iterated until stable -- over {_core['games']} games at {_core['pace']:.1f} poss/gm. Two "
                f"honest limits: the only schedule this app can see is UWW's own games plus each opponent's "
                f"season point totals, and opponent points are converted to per-100 at UWW's average pace. "
                f"Raw numbers are shown next to every adjusted one so the adjustment can be argued with.")
            st.markdown("")

        def _render_four_factors_card(_n):
            _ff = _card_data["four_factors"].copy()
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">'
                        f'{_n}. \u2696\ufe0f Four Factors -- What Decides This Game</span>'
                        f'{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            _ff["_abs"] = _ff["weighted"].abs()
            _top = _ff.nlargest(1, "_abs").iloc[0]
            _verb = "our edge" if _top["edge"] > 0 else f"{short_opponent}'s edge"
            st.markdown(f"Biggest weighted gap: **{_top['factor']}** -- {_verb} "
                        f"(UWW {_top['uww']:.1f} vs {_top['opp']:.1f}).")
            _ff_show = _ff.assign(
                Factor=_ff["factor"], UWW=_ff["uww"].round(1),
                **{short_opponent[:18]: _ff["opp"].round(1)},
                Edge=_ff["edge"].round(1), Weight=(_ff["weight"] * 100).astype(int).astype(str) + "%",
                Weighted=_ff["weighted"].round(2),
            )
            st.dataframe(
                _ff_show[["Factor", "UWW", short_opponent[:18], "Edge", "Weight", "Weighted"]]
                .sort_values("Weighted", key=lambda c: c.abs(), ascending=False),
                hide_index=True, use_container_width=True)
            st.caption("Dean Oliver's weights (shooting 40%, turnovers 25%, offensive rebounding 20%, free "
                       "throws 15%). Edge is stated so positive always favors UWW -- for turnovers that "
                       "means a LOWER rate. UWW's factors are from their own games; the opponent's are from "
                       "their prior games, so neither is adjusted for who they played.")
            st.markdown("")

        # Runs cut both ways, and the two halves belong to different sections: the runs WE go on are an
        # offensive story, the runs we give up are a defensive one. One combined card put both under
        # Defense, where "our biggest run averages 9.4" had no business being.
        def _render_scoring_runs_off_card(_n):
            _sr = _card_data["scoring_runs_off"]
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">'
                        f'{_n}. \U0001f30a Runs We Go On</span>'
                        f'{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            _ours = _sr["uww_biggest_run"].dropna()
            if not _ours.empty:
                _big = _sr[_sr["uww_biggest_run"] >= 10]
                st.markdown(f"Across {len(_sr)} games our biggest run averages **{_ours.mean():.1f}** points "
                            f"(best **{int(_ours.max())}**). We reached a 10-0 run or better in "
                            f"**{len(_big)}** of them.")
                _sro = _card_data.get("scoring_runs_off_opp")
                if _sro:
                    st.markdown(f"{esc(short_opponent)} has given up a run that size in "
                                f"**{100 * _sro['rate']:.0f}%** of their own games this season ({_sro['n']} "
                                f"games) -- a real target, not just something every team is vulnerable to.")
                if "uww_run_uww_lineup" in _sr.columns:
                    _gl = _sr["uww_run_uww_lineup"].dropna()
                    if not _gl.empty:
                        st.markdown(f"On the floor for the most of our runs: **{_last_names(_gl.value_counts().idxmax())}**.")
                if "uww_largest_lead" in _sr.columns:
                    _lead = _sr["uww_largest_lead"].dropna()
                    if not _lead.empty:
                        st.markdown(f"Largest lead built: **{int(_lead.max())}** points "
                                    f"(averaging {_lead.mean():.1f} per game).")
            st.caption("A run is consecutive scoring by one team with no answer. Lineups are whoever was on "
                       "the floor across the run's own event window.")
            st.markdown("")

        def _render_scoring_runs_def_card(_n):
            _sr = _card_data["scoring_runs_def"]
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">'
                        f'{_n}. \U0001f6a8 Runs Against Us</span>'
                        f'{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            _theirs = _sr["opponent_biggest_run"].dropna()
            if not _theirs.empty:
                _bad = _sr[_sr["opponent_biggest_run"] >= 10]
                st.markdown(f"Across {len(_sr)} games the biggest run against us averages **{_theirs.mean():.1f}** "
                            f"points (worst **{int(_theirs.max())}**). We gave up a 10-0 run or better in "
                            f"**{len(_bad)}** of them.")
                _srd = _card_data.get("scoring_runs_def_opp")
                if _srd:
                    st.markdown(f"{esc(short_opponent)} has gone on a run that size against their own "
                                f"opponents in **{100 * _srd['rate']:.0f}%** of their games this season "
                                f"({_srd['n']} games) -- a real, run-prone team, not just bad luck.")
                _bled = _sr[_sr["opponent_biggest_run"] >= _sr["opponent_biggest_run"].quantile(0.75)]
                if "opp_run_uww_lineup" in _bled.columns:
                    _bl = _bled["opp_run_uww_lineup"].dropna()
                    if not _bl.empty:
                        st.markdown(f"On the floor for the most of their biggest runs: "
                                    f"**{_last_names(_bl.value_counts().idxmax())}**.")
                if "opponent_largest_lead" in _sr.columns:
                    _dfc = _sr["opponent_largest_lead"].dropna()
                    if not _dfc.empty:
                        st.markdown(f"Largest deficit faced: **{int(_dfc.max())}** points "
                                    f"(averaging {_dfc.mean():.1f} per game).")
            st.caption("Their-run lineups are drawn from the games in the worst quartile, so this names the "
                       "unit on the floor when the damage was heaviest -- not merely the most-used one.")
            st.markdown("")

        def _render_lineup_stints_card(_n):
            _ls = _card_data["lineup_stints"]
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">'
                        f'{_n}. \u23f2\ufe0f Five-Man Units -- Minutes Won</span>'
                        f'{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            st.markdown("**Best by margin per 40:**")
            for _, _r in _ls.nlargest(3, "Per40").iterrows():
                st.markdown(f"- **{_last_names(_r['uww_lineup'])}** -- {_r['Per40']:+.1f}/40 "
                            f"({_r['Margin']:+.0f} in {_r['Minutes']:.0f} min, {int(_r['Stints'])} stints)")
            _bad = _ls.nsmallest(2, "Per40")
            if not _bad.empty:
                st.markdown("**Struggling:**")
                for _, _r in _bad.iterrows():
                    st.markdown(f"- {_last_names(_r['uww_lineup'])} -- {_r['Per40']:+.1f}/40 "
                                f"({_r['Margin']:+.0f} in {_r['Minutes']:.0f} min)")
            st.caption("Units with 4+ minutes together. Small samples swing hard -- minutes are shown so a "
                       "3-minute lineup isn't read as a rotation decision.")
            st.markdown("")

        def _render_note_sentiment_card(_n):
            _ns = _card_data["note_sentiment"]
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">'
                        f'{_n}. \U0001f4dd What the Staff Keeps Writing Down</span>'
                        f'{_source_badge_html("Coach Notes")}</div>', unsafe_allow_html=True)
            if _ns.get("themes"):
                st.markdown("**By subject:**")
                for _t, _n, _p, _g in _ns["themes"]:
                    _mix = " &middot; ".join(x for x in [f"{int(_g)} correction(s)" if _g else "",
                                                        f"{int(_p)} positive(s)" if _p else ""] if x)
                    st.markdown(f"- **{_t}** -- {int(_n)} notes" + (f" ({_mix})" if _mix else ""))
            if _ns["neg"]:
                st.markdown("**Exact phrases most repeated:**")
                for _t, _c in _ns["neg"]:
                    st.markdown(f"- {_t} -- **{_c}x**")
            if _ns["pos"]:
                st.markdown("**Repeatedly done well:**")
                for _t, _c in _ns["pos"]:
                    st.markdown(f"- {_t} -- {_c}x")
            st.caption(f"From {_ns['n_notes']} UWW clip notes this season, counting the coach's own \"+\" and "
                       f"\"-\" clauses. A theme repeating across games is a practice plan, not a one-off.")
            st.markdown("")

        def _render_coaching_flags_card(_n):
            _cf = _card_data["coaching_flags"]
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">'
                        f'{_n}. \U0001f6a9 Player Flags to Coach This Week</span>'
                        f'{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            _order = {"High": 0, "Medium": 1, "Low": 2}
            _cf = _cf.assign(_rank=_cf.get("confidence", pd.Series("Medium", index=_cf.index)).map(_order).fillna(1))
            for _lbl, _sent in (("Lean on", "Positive"), ("Clean up", "Negative")):
                _sel = _cf[_cf["sentiment"] == _sent].sort_values("_rank").head(3)
                if _sel.empty:
                    continue
                st.markdown(f"**{_lbl}:**")
                for _, _r in _sel.iterrows():
                    _ev = f" _{_r['evidence']}_" if "evidence" in _r.index and pd.notna(_r.get("evidence")) else ""
                    st.markdown(f"- **{_r['player']}** -- {_r['flag']}.{_ev}")
            st.caption("Highest-confidence flags first; the Team page carries the full list with "
                       "recommendations.")
            st.markdown("")

        def _render_scoring_reliance_card(_n):
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">{_n}. \U0001f3af Opponent Scoring Reliance</span>{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            _fp_share, _fp_val = _card_data["scoring_reliance"]
            if _fp_val == "Concentrated":
                st.markdown(f"Their top 2 scorers account for **{_fp_share:.0f}%** of team scoring -- a concentrated attack. Sending extra attention their way is likely to matter more here than against a balanced team.")
            else:
                st.markdown(f"Their top 2 scorers account for only **{_fp_share:.0f}%** of team scoring -- a balanced attack with no single focal point to key on.")
                st.markdown("Defensive game-planning likely matters more at the team-scheme level here than picking one player to load up on.")
            st.markdown("")

        def _render_pace_style_card(_n):
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">{_n}. \u23f1\ufe0f Pace & Style</span>{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            _fp_pace_d, _fp_opp_ppg, _fp_opp_allowed, _fp_style = _card_data["pace_style"]
            st.markdown(f"UWW season pace: **{_fp_pace_d['Pace']:.1f}** possessions/game, Net Rtg **{_fp_pace_d['Net Rtg']:+.1f}**.")
            st.markdown(f"{short_opponent}: **{_fp_opp_ppg:.1f}** PPG, allows **{_fp_opp_allowed:.1f}**.")
            if _fp_style == "Push Tempo":
                st.markdown("They've struggled against faster tempo, and UWW has been good playing that way -- **push tempo** and get into transition before their defense sets.")
            else:
                st.markdown("They've struggled when games slow down, and UWW has been good playing that way -- a **half-court, execution-first** approach fits here.")

            # Does UWW actually play well that way? The recommendation is about the OPPONENT; this is the
            # part about us, and it's the half a coach needs before committing to a tempo.
            _fp_hist = _card_data.get("pace_style_history")
            if _fp_hist is not None:
                _fp_g = _fp_hist["games"]
                _fp_want = "fast" if _fp_style == "Push Tempo" else "slow"
                _fp_sel = _fp_g[_fp_g["_bucket"] == _fp_want]
                _fp_oth = _fp_g[_fp_g["_bucket"] != _fp_want]

                def _fp_line(_lbl, _d):
                    if _d.empty:
                        return None
                    _w = int(_d["won"].fillna(False).sum())
                    _l = len(_d) - _w
                    return (f"**{_lbl}** ({len(_d)} games, {_fp_g.loc[_d.index, 'pace'].mean():.1f} poss/gm): "
                            f"**{_w}-{_l}**, Net Rtg **{_d['net'].mean():+.1f}**, ORtg {_d['ortg'].mean():.1f}")

                st.markdown(f"**How UWW has fared at each tempo** (own-median split at {_fp_hist['median']:.1f} poss/gm):")
                for _lbl, _d in (("Slower games" if _fp_want == "slow" else "Faster games", _fp_sel),
                                 ("Faster games" if _fp_want == "slow" else "Slower games", _fp_oth)):
                    _txt = _fp_line(_lbl, _d)
                    if _txt:
                        st.markdown(f"- {_txt}" + (" \u2190 *the recommended approach*" if _d is _fp_sel else ""))
                if not _fp_sel.empty and not _fp_oth.empty:
                    _fp_gap = _fp_sel["net"].mean() - _fp_oth["net"].mean()
                    _fp_gap_txt = _fp_gap
                    st.caption(
                        (f"UWW has been {abs(_fp_gap):.1f} points/100 better at this tempo -- the matchup read and "
                         "our own record agree." if _fp_gap > 0 else
                         f"Note: UWW has actually been {abs(_fp_gap):.1f} points/100 WORSE at this tempo. The "
                         "matchup argues for it, our own results don't -- worth weighing both.")
                        + " Pace is an estimate from the box score (FGA - OREB + TO + 0.44*FTA), split at UWW's own median."
                    )

            _fp_ohist = _card_data.get("pace_style_opp_history")
            if _fp_ohist is not None:
                _fo_g = _fp_ohist["games"]
                _fo_sel = _fo_g[_fo_g["_bucket"] == ("fast" if _fp_style == "Push Tempo" else "slow")]
                _fo_oth = _fo_g[_fo_g["_bucket"] != ("fast" if _fp_style == "Push Tempo" else "slow")]

                def _fo_line(_lbl, _d):
                    if _d.empty:
                        return None
                    _w = int(_d["won"].fillna(False).sum())
                    return (f"**{_lbl}** ({len(_d)} games, {_d['pace'].mean():.1f} poss/gm): "
                            f"opponents went **{_w}-{len(_d) - _w}**, Net Rtg **{_d['net'].mean():+.1f}**")

                st.markdown(f"**How {short_opponent}'s opponents have fared at each tempo** "
                            f"(their median: {_fp_ohist['median']:.1f} poss/gm):")
                for _lbl, _d in ((("Faster games" if _fp_style == "Push Tempo" else "Slower games"), _fo_sel),
                                 (("Slower games" if _fp_style == "Push Tempo" else "Faster games"), _fo_oth)):
                    _txt = _fo_line(_lbl, _d)
                    if _txt:
                        st.markdown(f"- {_txt}" + (" \u2190 *the recommended approach*" if _d is _fo_sel else ""))
                if not _fo_sel.empty and not _fo_oth.empty:
                    _fo_gap = _fo_sel["net"].mean() - _fo_oth["net"].mean()
                    st.caption(
                        f"Teams have been {abs(_fo_gap):.1f} points/100 "
                        + ("better" if _fo_gap > 0 else "worse")
                        + f" against {short_opponent} at this tempo. Rated from the other team's side, so a "
                          "positive Net Rtg means they beat "
                        + f"{short_opponent} on the scoreboard."
                    )

            # The two sections above only show bucket AVERAGES -- a coach who wants to sanity-check the read
            # (or spot a single blowout skewing a bucket) needs to see which specific games landed where.
            with st.expander("See the games behind this"):
                if _fp_hist is not None:
                    _ps_disp = _fp_hist["games"].copy()
                    _ps_disp["Pace"] = _ps_disp["pace"].round(1)
                    _ps_disp["Net Rtg"] = _ps_disp["net"].round(1)
                    _ps_disp["Result"] = _ps_disp["won"].map({True: "W", False: "L"})
                    _ps_disp["Bucket"] = _ps_disp["_bucket"].str.capitalize()
                    if "game_date" in _ps_disp.columns:
                        _ps_disp["_sort"] = pd.to_datetime(_ps_disp["game_date"], errors="coerce")
                        _ps_disp["Date"] = _ps_disp["_sort"].dt.strftime("%b %d")
                        _ps_disp = _ps_disp.sort_values("_sort", na_position="last")
                    else:
                        _ps_disp = _ps_disp.sort_values("Pace", ascending=False)
                    _ps_disp = _ps_disp.rename(columns={"opponent": "Opponent"})
                    _ps_cols = [c for c in ["Date", "Opponent", "Pace", "Net Rtg", "Result", "Bucket"] if c in _ps_disp.columns]
                    st.markdown(f"**UWW's games**, split at UWW's own median pace ({_fp_hist['median']:.1f} poss/gm):")
                    st.dataframe(_ps_disp[_ps_cols], hide_index=True, use_container_width=True)

                if _fp_ohist is not None:
                    _fo_disp = _fp_ohist["games"].copy()
                    _fo_disp["Pace"] = _fo_disp["pace"].round(1)
                    _fo_disp["Net Rtg"] = _fo_disp["net"].round(1)
                    _fo_disp["Result"] = _fo_disp["won"].map({True: "W", False: "L"})
                    _fo_disp["Bucket"] = _fo_disp["_bucket"].str.capitalize()
                    if "game_date" in _fo_disp.columns:
                        _fo_disp["_sort"] = pd.to_datetime(_fo_disp["game_date"], errors="coerce")
                        _fo_disp["Date"] = _fo_disp["_sort"].dt.strftime("%b %d")
                        _fo_disp = _fo_disp.sort_values("_sort", na_position="last")
                    else:
                        _fo_disp = _fo_disp.sort_values("Pace", ascending=False)
                    _fo_disp = _fo_disp.rename(columns={"foe": "Played them"})
                    _fo_cols = [c for c in ["Date", "Played them", "Pace", "Net Rtg", "Result", "Bucket"] if c in _fo_disp.columns]
                    st.markdown(f"**{short_opponent}'s prior games**, split at their own median pace "
                                f"({_fp_ohist['median']:.1f} poss/gm). Result/Net Rtg are from the challenger's "
                                f"side, i.e. the team named in \"Played them\":")
                    st.dataframe(_fo_disp[_fo_cols], hide_index=True, use_container_width=True)
            st.markdown("")

        def _render_rebounding_card(_n):
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">{_n}. \U0001f4aa Rebounding Edge</span>{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            _fp_uww_rpg, _fp_opp_rpg, _fp_reb_val = _card_data["rebounding"]
            st.markdown(f"UWW: **{_fp_uww_rpg:.1f}** RPG this season. {short_opponent}: **{_fp_opp_rpg:.1f}** RPG.")
            if _fp_reb_val == "Crash the Glass":
                st.markdown("A clear rebounding edge on paper -- **crash the offensive glass** for extra possessions rather than getting back in transition D early.")
            elif _fp_reb_val == "Prioritize Balance":
                st.markdown("They out-rebound their opponents on paper -- prioritize **boxing out and transition balance** over offensive-rebound crashes.")
            else:
                st.markdown("Rebounding looks roughly even on paper -- likely decided by effort plays, not a structural mismatch.")
            st.markdown("")

        def _render_bench_card(_n):
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">{_n}. \U0001fa91 Bench Trust Plan</span>{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            st.markdown("If a starter gets into foul trouble, these bench players have earned the most trust this season:")
            for _, _r in _card_data["bench"].nlargest(2, "Avg").iterrows():
                st.markdown(f"- **{_r['player']}** -- {_r['Avg']:.1f} avg Game Score off the bench ({int(_r['GP'])} games)")
            st.markdown("")

        def _render_clutch_card(_n):
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">{_n}. \U0001f3c1 Late-Game Trust</span>{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            st.markdown("Most productive scorers in clutch minutes (last 5 min, score within 8) this season:")
            for _player, _pts in _card_data["clutch"].nlargest(2).items():
                st.markdown(f"- **{_player}** -- {int(_pts)} clutch pts")
            st.caption("Worth building the closing possession around, all else equal -- see the Team page's full clutch breakdown for more.")
            st.markdown("")

        def _render_turnovers_card(_n):
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">{_n}. \U0001f504 Turnover-Forcing Opportunity</span>{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            _fp_topg, _fp_uww_stl, _fp_to_val = _card_data["turnovers"]
            st.markdown(f"{short_opponent} averages **{_fp_topg:.1f}** turnovers/game (season total, not opponent-adjusted). UWW forces **{_fp_uww_stl:.1f}** steals/game.")
            if _fp_to_val == "Press / Extend":
                st.markdown("A turnover-prone opponent on paper -- **extending ball pressure and denying easy entries** is more likely to pay off here than against a low-turnover team.")
            else:
                st.markdown("A relatively careful ball-handling team on paper -- pressure is still worth applying, but don't expect turnovers alone to be the deciding factor.")
            st.markdown("")

        def _render_closing_lineup_card(_n):
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">{_n}. \U0001f512 Recommended Closing Lineup</span>{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            _fp_best_lu = _card_data["closing_lineup"]
            st.markdown(f"**{_last_names(_fp_best_lu['lineup'])}** -- your best net rating this season among lineups with real minutes: **{_fp_best_lu['rate']:+.2f}/min** over {_fp_best_lu['MIN']:.0f} minutes.")
            if _opp_lu is not None and not _opp_lu.empty:
                _fp_opp_top_lu = _opp_lu.nlargest(1, "MIN").iloc[0]
                _fp_opp_rate = _fp_opp_top_lu["+/-"] / _fp_opp_top_lu["MIN"] if _fp_opp_top_lu["MIN"] > 0 else 0
                st.markdown(f"{short_opponent}'s most-used lineup (**{_last_names(_fp_opp_top_lu['lineup'])}**) has run at **{_fp_opp_rate:+.2f}/min**.")
                st.markdown(f"Projected edge if both closing units are on the floor: **{_fp_best_lu['rate'] - _fp_opp_rate:+.2f}/min**.")
            st.caption("Full lineup-vs-lineup exploration (including untried combinations) is available in the Lineup Simulator above.")
            st.markdown("")

        # card_data key -> (KTV category it belongs under, render function). Direct assignment rather than
        # running each card's text through the fuzzy keyword matcher -- these are 8 fixed, known card types,
        # so a reliable direct mapping beats hoping the wording happens to trip the right keywords.
        _CARD_CATEGORY_MAP = {
            "plays": ("Play Calls", _render_plays_card),
            "plays_similar": ("Play Calls", _render_similar_plays_card),
            "adj_efficiency": ("Offensive Efficiency", _render_adj_efficiency_card),
            "four_factors": ("Four Factors", _render_four_factors_card),
            "scoring_runs_off": ("Offensive Efficiency", _render_scoring_runs_off_card),
            "scoring_runs_def": ("Defensive Efficiency", _render_scoring_runs_def_card),
            "lineup_stints": ("Personnel/Rotation", _render_lineup_stints_card),
            "note_sentiment": ("Coaching Notes", _render_note_sentiment_card),
            "coaching_flags": ("Personnel/Rotation", _render_coaching_flags_card),
            "scoring_reliance": ("Defensive Efficiency", _render_scoring_reliance_card),
            "pace_style": ("Offensive Efficiency", _render_pace_style_card),
            "rebounding": ("Rebounding", _render_rebounding_card),
            "bench": ("Personnel/Rotation", _render_bench_card),
            "clutch": ("Personnel/Rotation", _render_clutch_card),
            "turnovers": ("Perimeter Defense / Ball Pressure/ Create Turnovers", _render_turnovers_card),
            "closing_lineup": ("Personnel/Rotation", _render_closing_lineup_card),
        }
        _cards_by_category = {}
        for _cd_key, (_cd_cat, _cd_renderer) in _CARD_CATEGORY_MAP.items():
            if _cd_key in _card_data:
                _cards_by_category.setdefault(_cd_cat, []).append(_cd_renderer)


        # --- Group by KTV category and render like the old page's "Keys to Victory (Data-Driven)" section:
        # numbered items with colored category badges, a stat caption, and the reasoning in italics --
        # instead of a flat list with reasoning hidden behind a popover. ---

        if _keys or _card_data:
            _grouped = {}
            _ungrouped = []
            # A key's SOURCE can determine its category outright, overriding the keyword matcher. Lineup
            # Scouting keys ("Attack <their worst lineup>", "Counter with <our best lineup>") are personnel
            # decisions by definition, but their text is about net rating and minutes, so _match_categories
            # scattered them into whatever stat category their wording happened to trip -- or dropped them
            # into _ungrouped when nothing matched. Pin them to Personnel/Rotation instead of trying to
            # express "this came from lineup data" as more keywords.
            _SOURCE_FORCED_CATEGORY = {"Lineup Scouting": "Personnel/Rotation"}
            # Some generated keys carry the SHOT MECHANIC in their own title ("...high-volume look: Drive to
            # the basket, Not tagged"), and that mechanic text reliably out-votes what the key is actually
            # about -- "Drive to the basket" tripped Scoring Inside, filing a purely DEFENSIVE prep key
            # ("what their offense goes to most often") under Offense. These titles are generated by this
            # file, so their category is known outright and doesn't need to be guessed from wording.
            _HEADLINE_FORCED_CATEGORY = (
                (r"high-volume look|goes to most", "Defensive Efficiency"),
                (r"attack opponent worst offensive shot selection|attack their weakest look", "Offensive Efficiency"),
                # "Feature our best look" (the retitled counterpart of "attack their weakest look" above) no
                # longer contains the "shot selection"/"shot quality" keywords the keyword matcher relies on
                # for Offensive Efficiency, so it needs the same explicit pin.
                (r"feature our best look", "Offensive Efficiency"),
            )
            for _icon, _headline, _caption, _reason, _source in _keys:
                # Data-Driven keys carry raw stat text in _caption/_reason ("Offensive Rebound: 87.7% on
                # 57 attempts"), which reliably out-voted the title's own wording -- "Take away their most
                # efficient high-volume actions" was landing under Rebounding. Match their TITLE only.
                _match_text = _headline if _source == "Data-Driven" else f"{_headline} {_caption or ''} {_reason or ''}"
                _forced_cat = _SOURCE_FORCED_CATEGORY.get(_source)
                if not _forced_cat:
                    for _hf_pat, _hf_cat in _HEADLINE_FORCED_CATEGORY:
                        if re.search(_hf_pat, str(_headline), re.I):
                            _forced_cat = _hf_cat
                            break
                _cats = [_forced_cat] if _forced_cat else _match_categories(_match_text)
                # "Opponent strength: ..." keys describe THEM, full stop -- the phrase matcher kept reading
                # their offense as ours ("2 playmaking guards" came back UWW), so the source decides here.
                _side = "OPP" if _source == "Team Strengths" else _detect_side(_match_text)
                if _forced_cat == "Defensive Efficiency" and _side != "OPP":
                    # A forced defensive-prep key is about THEM by construction; the mechanic wording in
                    # the title ("Drive to the basket") otherwise reads as one of ours.
                    _side = "OPP"
                if _cats:
                    _grouped.setdefault(_cats[0], []).append((_icon, _headline, _caption, _reason, _cats, _side, _source))
                else:
                    _ungrouped.append((_icon, _headline, _caption, _reason, [], _side, _source))

            # Stable category order: whichever order they're defined in KTV_CATEGORY_REFERENCE, skipping
            # any category nothing matched this game.
            _cat_order = [c for c in KTV_CATEGORY_REFERENCE if c in _grouped or c in _cards_by_category]

            # Icon-only rating buttons, styled small enough to sit on the same line as a key's title.
            # Streamlit's own `help=` tooltip is rendered in a portal that places itself ABOVE the
            # trigger, and its position can't be steered from CSS without moving every tooltip in the app.
            # So these buttons carry their own: a ::after bubble anchored under the icon, driven by the
            # rating slug that is part of each button's key (hence the "__beneficial" style suffixes).
            st.markdown("""
            <style>
            div[class*="st-key-ktv_fb_"] button {
                padding: 0 6px !important;
                min-height: 28px !important;
                height: 28px !important;
                border: 1px solid #eaeaea !important;
                background: #fff !important;
                line-height: 1 !important;
                position: relative !important;
            }
            div[class*="st-key-ktv_fb_"] button:hover { border-color: #4E2A84 !important; }
            div[class*="st-key-ktv_fb_"] button p { font-size: 0.95rem !important; margin: 0 !important; }
            div[class*="st-key-ktv_fb_"] button:disabled { opacity: .45 !important; }
            /* the bubble itself -- hidden until hover, and never clipped by the column it sits in */
            div[class*="st-key-ktv_fb_"] { overflow: visible !important; }
            div[class*="st-key-ktv_fb_"] button::after {
                position: absolute;
                top: calc(100% + 6px);
                right: 0;
                white-space: nowrap;
                background: #222;
                color: #fff;
                font-size: 0.68rem;
                font-weight: 600;
                padding: 3px 8px;
                border-radius: 6px;
                opacity: 0;
                pointer-events: none;
                transition: opacity .12s ease;
                z-index: 60;
            }
            div[class*="st-key-ktv_fb_"] button:hover::after { opacity: 1; }
            div[class*="st-key-ktv_fb_"][class*="__beneficial"] button::after { content: "Beneficial \2014 worth keeping"; }
            div[class*="st-key-ktv_fb_"][class*="__not-useful"] button::after { content: "Not useful \2014 true, but doesn't help"; }
            div[class*="st-key-ktv_fb_"][class*="__not-accurate"] button::after { content: "Not accurate \2014 wrong number or read"; }
            </style>
            """, unsafe_allow_html=True)

            def _ktv_cols(_spec, _align="center"):
                """st.columns with vertical alignment where the installed Streamlit supports it (1.36+),
                and without it where it doesn't -- the layout is slightly less tidy on an older version
                rather than the page failing outright."""
                try:
                    return st.columns(_spec, vertical_alignment=_align)
                except TypeError:
                    return st.columns(_spec)

            # (icon, rating stored in the CSV, css slug used for the button key and its tooltip rule)
            _KTV_RATING_ICONS = (
                ("\U0001f44d", "Beneficial", "beneficial"),
                ("\U0001f44e", "Not beneficial", "not-useful"),
                ("\u26a0\ufe0f", "Not accurate", "not-accurate"),
            )

            def _ktv_feedback_state(_key_text, _category, _slot=""):
                _kid = ktv_key_id(short_opponent, _category, _key_text)
                _state_key = f"ktv_fb_{_kid}_{_slot}"
                return _kid, _state_key, st.session_state.get(_state_key)

            def _ktv_feedback_icons(_cols, _key_text, _category, _section, _source=None, _slot=""):
                """Three icon buttons, one per verdict, rendered into columns the caller supplies -- which
                is what lets them sit inline with the key's own title instead of on a row of their own.

                The click writes to the CSV and records the verdict in session state, so the buttons grey
                out immediately and a double-click can't file two rows."""
                _kid, _state_key, _already = _ktv_feedback_state(_key_text, _category, _slot)
                for _col, (_icon, _rating, _slug_css) in zip(_cols, _KTV_RATING_ICONS):
                    with _col:
                        # The key ends in the slug so the CSS above can tell the three buttons apart --
                        # and it stays free of spaces, which Streamlit would turn into separate classes.
                        if st.button(_icon, key=f"{_state_key}__{_slug_css}",
                                     use_container_width=True, disabled=_already is not None):
                            _ok = save_ktv_feedback({
                                "opponent": short_opponent, "game_date": game_date,
                                "section": _section, "category": _category, "source": _source,
                                "key_id": _kid, "key_text": _key_text, "rating": _rating,
                                "coach": st.session_state.get("ktv_feedback_coach", ""),
                                "comment": "",
                            })
                            st.session_state[_state_key] = _rating if _ok else "__failed__"
                            st.rerun()

            def _ktv_recorded_badge(_already) -> str:
                """Small inline marker appended to the title once a verdict is in."""
                if not _already:
                    return ""
                if _already == "__failed__":
                    return (' <span style="color:#c62828;font-size:0.7rem;font-weight:600;">'
                            'not saved (folder read-only)</span>')
                _bg = {"Beneficial": "#2e7d32", "Not beneficial": "#8d6e63", "Not accurate": "#c62828"}.get(_already, "#666")
                return (f' <span style="background:{_bg};color:#fff;font-size:0.62rem;font-weight:700;'
                        f'padding:2px 7px;border-radius:8px;margin-left:6px;">{html.escape(_already)}</span>')

            def _render_key_item(_n, _icon, _headline, _caption, _reason, _cats, _side, _source,
                                 _category=None, _section=None):
                # No per-item category badge -- the section header above already names the category, so
                # repeating it on every item was redundant. Side (UWW/OPP) badges removed too, per request.
                # The rating icons share the title's row: a coach reads a key and reacts to it in place,
                # without a separate strip of buttons doubling the height of every item on the page.
                _fb_ready = bool(_category)
                if _fb_ready:
                    _title_col, _fb1, _fb2, _fb3 = _ktv_cols([12, 1, 1, 1], "center")
                    _, _, _already = _ktv_feedback_state(_headline, _category)
                else:
                    _title_col, _already = st.container(), None
                with _title_col:
                    st.markdown(
                        f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">'
                        f'{_n}. {_icon} {html.escape(_headline)}</span>{_source_badge_html(_source)}'
                        f'{_ktv_recorded_badge(_already)}</div>', unsafe_allow_html=True)
                if _fb_ready:
                    _ktv_feedback_icons((_fb1, _fb2, _fb3), _headline, _category, _section or "", _source)
                if _caption:
                    st.caption(_caption)
                if _reason:
                    # A reason can carry several angles (e.g. best-shooting lineups AND highest-volume
                    # lineups); render one italic line each instead of one unreadable run-on.
                    for _rl in str(_reason).split("\n"):
                        if _rl.strip():
                            st.markdown(f"_{_rl.strip()}_")
                st.markdown("")

            # --- Per-category stat lines: real UWW-vs-opponent numbers for whatever this category actually
            # tracks, not just the abstract stat names. Loaded once here rather than per-category. ---
            _cs_uww_box_all = load_table("uww_pbp_box_score")
            _cs_uww_side_all = _cs_uww_box_all[_cs_uww_box_all["team"] == "UW-Whitewater"] if not _cs_uww_box_all.empty else pd.DataFrame()
            # ROOT CAUSE FOUND (confirmed against real diagnostic output, after two wrong attempts at this):
            # `played` (games strictly before the upcoming game, via pre_upcoming/next_game_idx) was correct
            # all along -- len(played)==1 matches what the user confirmed should be true. The actual bug was
            # never the denominator: it was that _cs_uww_side pulled from the ENTIRE uww_pbp_box_score table,
            # unfiltered by date, which can (and here does) contain box-score data for games beyond just
            # "before the upcoming game" -- e.g. when reference_date is set artificially early for testing
            # against a real, further-along season, box scores exist for games chronologically AFTER the
            # simulated "upcoming" game too. Both the numerator (turnovers summed) and denominator (games
            # count) need the SAME "games before the upcoming game" scope, or they silently disagree.
            # Same date-based scoping get_data_driven_ktv() does -- shared via scope_to_played() so the
            # two can't drift apart (this exact scoping was fixed here first, then found missing there).
            _cs_uww_side = scope_to_played(_cs_uww_side_all, played)
            _cs_n_games = len(played)
            _cs_opp_prof = load_table("uww_player_profiles")
            _cs_opp_prof = _cs_opp_prof[_cs_opp_prof["opponent"] == short_opponent] if not _cs_opp_prof.empty and short_opponent else pd.DataFrame()
            _cs_opp_games = get_opponent_games_played(short_opponent) if short_opponent else 0
            _cs_team_totals = load_table("uww_opponent_team_totals")
            _cs_opp_totals_row = _cs_team_totals[_cs_team_totals["opponent"] == short_opponent] if not _cs_team_totals.empty and short_opponent else pd.DataFrame()

            def _parse_ma_totals(series):
                made, att = 0, 0
                for val in series.dropna():
                    parts = str(val).split("-")
                    if len(parts) == 2:
                        try:
                            made += int(parts[0])
                            att += int(parts[1])
                        except ValueError:
                            pass
                return made, att

            def _category_stat_line(cat):
                """Real per-game numbers for whatever this category tracks -- (uww_str, opp_str) or None for
                a side that isn't reliably computable from available data (e.g. opponent 2-pt FG% -- we only
                have their overall FG% per player, not a made/attempted split). PTS and REB are already
                per-game for the opponent; AST/STL/BLK/TO are season totals there and need /opp_games --
                confirmed the hard way earlier in this project, so this distinction is deliberate, not an
                oversight."""
                if _cs_n_games == 0:
                    return None
                if cat == "Ball Security":
                    u = _cs_uww_side["TO"].sum() / _cs_n_games if "TO" in _cs_uww_side.columns else None
                    # Opponent side is turnovers THEY FORCE, computed directly from real third-party PBP data
                    # (uww_opponent_prior_games_pbp: whoever they actually played, before facing UWW) instead
                    # of the STL-based proxy this used before. This is a genuinely different number from the
                    # "X of 24 turnovers" shown elsewhere on this page for the "turnover triggers" key -- that
                    # 24 is the opponent's OWN turnovers committed (their ball-security weakness, a RAW TOTAL
                    # across all their prior games), not turnovers they forced on someone else, and not a
                    # per-game rate. The raw components are shown directly below rather than asserted, since
                    # this exact stat has been wrong twice already in this project and a third unverified claim
                    # isn't worth as much as the coach being able to check the arithmetic themselves.
                    o = None
                    _cs_forced_total, _cs_forced_games = None, None
                    _cs_prior_pbp = load_table("uww_opponent_prior_games_pbp")
                    if not _cs_prior_pbp.empty and short_opponent:
                        _cs_forced = _cs_prior_pbp[
                            (_cs_prior_pbp["team"] != short_opponent) & _cs_prior_pbp["team"].notna()
                            & (_cs_prior_pbp["event_type"] == "turnover")
                        ]
                        _cs_forced_total = len(_cs_forced)
                        _cs_forced_games = _cs_prior_pbp.loc[_cs_prior_pbp["team"] != short_opponent, "opponent"].nunique()
                        if _cs_forced_games > 0:
                            o = _cs_forced_total / _cs_forced_games
                    _o_label = f"{short_opponent} turnovers forced/gm: {o:.1f} ({_cs_forced_total} forced across {_cs_forced_games} game(s) with data)" if o is not None else None
                    return (f"UWW turnovers/gm: {u:.1f}" if u is not None else None, _o_label)
                if cat == "Rebounding":
                    u = _cs_uww_side["REB"].sum() / _cs_n_games if "REB" in _cs_uww_side.columns else None
                    o = pd.to_numeric(_cs_opp_prof["REB"], errors="coerce").sum() if not _cs_opp_prof.empty and "REB" in _cs_opp_prof.columns else None
                    return (f"UWW: {u:.1f} RPG" if u is not None else None, f"{short_opponent}: {o:.1f} RPG" if o is not None else None)
                if cat == "Three-Point Shooting":
                    u_txt = None
                    if {"FG3M", "FG3A"} <= set(_cs_uww_side.columns) and _cs_uww_side["FG3A"].sum() > 0:
                        u_m, u_a = _cs_uww_side["FG3M"].sum(), _cs_uww_side["FG3A"].sum()
                        u_txt = f"UWW: {u_m/_cs_n_games:.1f}/{u_a/_cs_n_games:.1f} 3PA/gm ({100*u_m/u_a:.0f}%)"
                    o_txt = None
                    if not _cs_opp_prof.empty and "3PM-A" in _cs_opp_prof.columns:
                        o_m, o_a = _parse_ma_totals(_cs_opp_prof["3PM-A"])
                        if o_a > 0 and _cs_opp_games > 0:
                            o_txt = f"{short_opponent}: {o_m/_cs_opp_games:.1f}/{o_a/_cs_opp_games:.1f} 3PA/gm ({100*o_m/o_a:.0f}%)"
                    return (u_txt, o_txt)
                if cat == "Free Throws":
                    u_txt = None
                    if {"FTM", "FTA"} <= set(_cs_uww_side.columns) and _cs_uww_side["FTA"].sum() > 0:
                        u_m, u_a = _cs_uww_side["FTM"].sum(), _cs_uww_side["FTA"].sum()
                        u_txt = f"UWW: {u_m/_cs_n_games:.1f}/{u_a/_cs_n_games:.1f} FTA/gm ({100*u_m/u_a:.0f}%)"
                    o_txt = None
                    if not _cs_opp_prof.empty and "FTM-A" in _cs_opp_prof.columns:
                        o_m, o_a = _parse_ma_totals(_cs_opp_prof["FTM-A"])
                        if o_a > 0 and _cs_opp_games > 0:
                            o_txt = f"{short_opponent}: {o_m/_cs_opp_games:.1f}/{o_a/_cs_opp_games:.1f} FTA/gm ({100*o_m/o_a:.0f}%)"
                    return (u_txt, o_txt)
                if cat == "Fouls / Discipline":
                    u = _cs_uww_side["PF"].sum() / _cs_n_games if "PF" in _cs_uww_side.columns else None
                    # Opponent PF isn't tracked in uww_player_profiles -- UWW-only, not a gap in this logic.
                    return (f"UWW: {u:.1f} PF/gm" if u is not None else None, None)
                if cat == "Ball Movement / Assists":
                    u = _cs_uww_side["AST"].sum() / _cs_n_games if "AST" in _cs_uww_side.columns else None
                    o = pd.to_numeric(_cs_opp_prof["AST"], errors="coerce").sum() / _cs_opp_games if not _cs_opp_prof.empty and "AST" in _cs_opp_prof.columns and _cs_opp_games > 0 else None
                    return (f"UWW: {u:.1f} APG" if u is not None else None, f"{short_opponent}: {o:.1f} APG" if o is not None else None)
                if cat == "Paint Protection / Blocks":
                    u = _cs_uww_side["BLK"].sum() / _cs_n_games if "BLK" in _cs_uww_side.columns else None
                    o = pd.to_numeric(_cs_opp_prof["BLK"], errors="coerce").sum() / _cs_opp_games if not _cs_opp_prof.empty and "BLK" in _cs_opp_prof.columns and _cs_opp_games > 0 else None
                    return (f"UWW: {u:.1f} BPG" if u is not None else None, f"{short_opponent}: {o:.1f} BPG" if o is not None else None)
                if cat == "Perimeter Defense / Ball Pressure/ Create Turnovers":
                    u = _cs_uww_side["STL"].sum() / _cs_n_games if "STL" in _cs_uww_side.columns else None
                    o_stl = pd.to_numeric(_cs_opp_prof["STL"], errors="coerce").sum() / _cs_opp_games if not _cs_opp_prof.empty and "STL" in _cs_opp_prof.columns and _cs_opp_games > 0 else None
                    o_to = pd.to_numeric(_cs_opp_prof["TO"], errors="coerce").sum() / _cs_opp_games if not _cs_opp_prof.empty and "TO" in _cs_opp_prof.columns and _cs_opp_games > 0 else None
                    o_txt = None
                    if o_stl is not None or o_to is not None:
                        _bits = []
                        if o_to is not None:
                            _bits.append(f"forces {o_to:.1f} TO/gm on themselves")
                        o_txt = f"{short_opponent}: {', '.join(_bits)}" if _bits else None
                    return (f"UWW: {u:.1f} SPG" if u is not None else None, o_txt)
                if cat == "Scoring Inside":
                    if {"FGM", "FGA", "FG3M", "FG3A"} <= set(_cs_uww_side.columns):
                        _2m, _2a = _cs_uww_side["FGM"].sum() - _cs_uww_side["FG3M"].sum(), _cs_uww_side["FGA"].sum() - _cs_uww_side["FG3A"].sum()
                        if _2a > 0:
                            return (f"UWW: {_2m/_cs_n_games:.1f}/{_2a/_cs_n_games:.1f} 2PA/gm ({100*_2m/_2a:.0f}%)", None)
                    return None
                if cat == "Field Goal Efficiency":
                    u_txt = None
                    if {"FGM", "FGA"} <= set(_cs_uww_side.columns) and _cs_uww_side["FGA"].sum() > 0:
                        u_txt = f"UWW: {100*_cs_uww_side['FGM'].sum()/_cs_uww_side['FGA'].sum():.0f}% FG"
                    o_txt = None
                    if not _cs_opp_totals_row.empty and "team_ppg" in _cs_opp_totals_row.columns:
                        pass  # team_totals doesn't carry a team FG% -- left out rather than guessed at
                    return (u_txt, o_txt)
                if cat == "Offensive Efficiency":
                    if {"PTS", "FGA", "FTA"} <= set(_cs_uww_side.columns) and _cs_uww_side["FGA"].sum() > 0:
                        _ts = compute_true_shooting(_cs_uww_side["PTS"].sum(), _cs_uww_side["FGA"].sum(), _cs_uww_side["FTA"].sum())
                        return (f"UWW: {_ts:.1f} TS%", None)
                    return None
                return None  # Defensive Efficiency and any future category with no single clean box-score stat

            # --- Map every full-game-plan item to whichever KTV category(ies) it actually relates to, using
            # the same matcher the keys themselves use -- so each category's "Game Plan" button shows only
            # the game-plan content relevant to THAT category, not the entire game plan every time. ---
            _gpd_plans_all = load_table("uww_opponent_game_plans")
            _gpd_opp_all = _gpd_plans_all[_gpd_plans_all["opponent"] == short_opponent] if not _gpd_plans_all.empty and short_opponent else pd.DataFrame()
            _gpd_other_all = _gpd_opp_all[~_gpd_opp_all["topic"].isin(["KEYS TO VICTORY", "TEAM STRENGTHS"])] if not _gpd_opp_all.empty else pd.DataFrame()
            _gpd_other_all = _gpd_other_all[_gpd_other_all["category"].astype(str).str.contains("game plan", case=False, na=False)] if not _gpd_other_all.empty else _gpd_other_all

            _game_plan_by_cat = {}  # KTV category -> list of (game-plan category, topic, item text)
            if not _gpd_other_all.empty:
                for _, _gpd_row in _gpd_other_all.iterrows():
                    _gpd_notes = str(_gpd_row["notes"])
                    _gpd_items = [_i.strip() for _i in _gpd_notes.split("|") if _i.strip()] if "|" in _gpd_notes else [_gpd_notes.strip()]
                    for _gpd_item in _gpd_items:
                        if not _gpd_item:
                            continue
                        for _gpd_ktv_cat in _match_categories(f"{_gpd_row['topic']} {_gpd_item}"):
                            _game_plan_by_cat.setdefault(_gpd_ktv_cat, []).append((_gpd_row["category"], _gpd_row["topic"], _gpd_item))

            @st.dialog("\U0001f4cb Game Plan", width="large")
            def _show_game_plan_dialog(ktv_category):
                """Only the full-game-plan items that matched THIS KTV category (see _game_plan_by_cat above)
                -- organized by the game plan's own category and topic, same as the old page's expander did,
                just scoped down to what's actually relevant here instead of the whole game plan."""
                _gpd_items_for_cat = _game_plan_by_cat.get(ktv_category, [])
                if not _gpd_items_for_cat:
                    st.info(f"No full game plan items matched to {ktv_category} yet for {short_opponent}.")
                    return
                st.caption(f"Game plan items related to **{ktv_category}**:")
                _gpd_by_gp_cat = {}
                for _gpd_cat, _gpd_topic, _gpd_item in _gpd_items_for_cat:
                    _gpd_by_gp_cat.setdefault(_gpd_cat, {}).setdefault(_gpd_topic, []).append(_gpd_item)
                for _gpd_cat, _gpd_topics in _gpd_by_gp_cat.items():
                    st.markdown(f"#### {_gpd_cat}")
                    for _gpd_topic, _gpd_item_list in _gpd_topics.items():
                        st.markdown(f"**{_gpd_topic}**")
                        for _gpd_item in _gpd_item_list:
                            st.markdown(f"- {_gpd_item}")
                    st.markdown("")

            # Two-column Offense/Defense split instead of one flat stack of category expanders. Categories
            # that don't cleanly belong to either side (Personnel/Rotation -- a personnel decision, not a
            # stat category) render full-width below the two columns instead of being forced into one.
            _OFFENSE_CATS = {
                "Ball Security", "Three-Point Shooting", "Free Throws", "Ball Movement / Assists",
                "Scoring Inside", "Field Goal Efficiency", "Offensive Efficiency", "Play Calls",
                "Four Factors",
            }
            _DEFENSE_CATS = {
                "Rebounding", "Fouls / Discipline", "Paint Protection / Blocks",
                "Perimeter Defense / Ball Pressure/ Create Turnovers", "Defensive Efficiency",
            }
            # Categories that are genuinely BOTH sides of the ball: "Three-Point Shooting" covers both
            # hitting ours and contesting theirs, "Free Throws" both getting to the line and keeping them
            # off it. Hard-coding them as offense sent real defensive keys ("DRIVE DOWN 3PT ATTEMPTS!!!",
            # "LIMIT THEIR SCORING @ THE RIM") into the Offense section. For these, the detected side
            # picks the section instead of the category.
            _DUAL_USE_CATS = {
                "Three-Point Shooting", "Field Goal Efficiency", "Free Throws", "Fouls / Discipline",
                "Transition / Pace",
            }
            _SEC_OFF, _SEC_DEF, _SEC_PERS = "Offense", "Defense", "Personnel, Rotation & Intangibles"

            def _default_section(_cat):
                if _cat in _OFFENSE_CATS:
                    return _SEC_OFF
                if _cat in _DEFENSE_CATS:
                    return _SEC_DEF
                return _SEC_PERS

            def _section_for(_cat, _side, _source):
                # An opponent-strength key is a defensive assignment no matter which stat category its
                # wording tripped -- "Opponent strength: High level 3pt shooting" is something to guard,
                # not something we do.
                if _source == "Team Strengths":
                    # ...unless the strength is a roster/rotation fact rather than something to guard
                    # ("Deep Bench (12-13 man rotation)"), which belongs with the other personnel notes.
                    return _default_section(_cat) if _cat == "Personnel/Rotation" else _SEC_DEF
                if _cat in _DUAL_USE_CATS:
                    if _side == "OPP":
                        return _SEC_DEF
                    if _side == "UWW":
                        return _SEC_OFF
                return _default_section(_cat)

            # Same category can now appear in two sections with different items in each, so grouping is
            # (section -> category -> items) rather than one section per category.
            _sectioned = {_SEC_OFF: {}, _SEC_DEF: {}, _SEC_PERS: {}}
            for _sc_cat, _sc_items in _grouped.items():
                for _sc_item in _sc_items:
                    _sc_side, _sc_source = _sc_item[5], _sc_item[6]
                    _sectioned[_section_for(_sc_cat, _sc_side, _sc_source)].setdefault(_sc_cat, []).append(_sc_item)
            _cards_sectioned = {}
            for _cc_cat, _cc_cards in _cards_by_category.items():
                _cards_sectioned.setdefault(_default_section(_cc_cat), {})[_cc_cat] = _cc_cards

            def _render_cat_expander(_cat, _cat_items=None, _cat_cards=None, _sec_key=""):
                """One KTV category, always visible (no expander) -- a styled header plus its items,
                so a coach sees every key at once instead of clicking each category open. Items are
                passed in per SECTION, since a dual-use category (e.g. Three-Point Shooting) can hold
                offensive keys in the Offense section and defensive ones in Defense."""
                _cat_items = _grouped.get(_cat, []) if _cat_items is None else _cat_items
                _cat_cards = _cards_by_category.get(_cat, []) if _cat_cards is None else _cat_cards
                _n_items = len(_cat_items) + len(_cat_cards)
                st.markdown(
                    '<div style="background:#f3f0f9;border-left:4px solid #4E2A84;border-radius:4px;'
                    'padding:6px 10px;margin:12px 0 6px 0;font-weight:700;font-size:0.92rem;color:#4E2A84;">'
                    f'{_cat} &mdash; {_n_items} item{"s" if _n_items != 1 else ""}</div>',
                    unsafe_allow_html=True,
                )
                _cat_has_gp = bool(_game_plan_by_cat.get(_cat))
                if _cat_has_gp:
                    if st.button("\U0001f4cb Game Plan", key=f"gameplan_btn_{_sec_key}_{_cat}"):
                        _show_game_plan_dialog(_cat)
                _cs_line = _category_stat_line(_cat)
                if _cs_line and (_cs_line[0] or _cs_line[1]):
                    st.caption("  |  ".join(x for x in _cs_line if x))
                for _n, (_icon, _headline, _caption, _reason, _cats, _side, _source) in enumerate(_cat_items, start=1):
                    _render_key_item(_n, _icon, _headline, _caption, _reason, _cats, _side, _source,
                                     _category=_cat, _section=_sec_key)

                # Full Game Plan Recommendation card(s) tagged to this same category -- continuing the
                # SAME numbered-item formatting as the keys above (numbered header, source badge, no
                # bordered box), instead of a separate boxed-off "card" sitting apart from the list.
                for _ci, _renderer in enumerate(_cat_cards):
                    # Cards are keys too as far as a coach is concerned. Rendering the card into the wide
                    # column puts its own title on the same line as the icons, matching the keys above --
                    # and the card is identified by its render function's name, which stays stable across
                    # weeks even as every number inside it changes.
                    _card_label = (getattr(_renderer, "__name__", "card")
                                   .replace("_render_", "").replace("_card", "").replace("_", " ").title())
                    _card_col, _cfb1, _cfb2, _cfb3 = _ktv_cols([12, 1, 1, 1], "top")
                    with _card_col:
                        _renderer(len(_cat_items) + _ci + 1)
                    _ktv_feedback_icons((_cfb1, _cfb2, _cfb3), _card_label, _cat, _sec_key, "Data-Driven",
                                        _slot=f"card{_ci}")

            # Stacked top-to-bottom (Offense, then Defense, then Personnel/Rotation & Intangibles)
            # rather than three side-by-side columns -- full width per section keeps each key readable,
            # and the sections read in scouting order instead of competing for a third of the page each.
            for _sec_title in (_SEC_OFF, _SEC_DEF, _SEC_PERS):
                _sec_items = _sectioned.get(_sec_title, {})
                _sec_cards = _cards_sectioned.get(_sec_title, {})
                _sec_order = [c for c in _cat_order if c in _sec_items or c in _sec_cards]
                st.markdown(
                    '<div style="font-weight:800;font-size:1.15rem;color:#4E2A84;border-bottom:2px solid #4E2A84;'
                    f'padding-bottom:4px;margin:22px 0 8px 0;">{_sec_title}</div>',
                    unsafe_allow_html=True,
                )
                if _sec_order:
                    for _cat in _sec_order:
                        _render_cat_expander(_cat, _sec_items.get(_cat, []), _sec_cards.get(_cat, []), _sec_title)
                else:
                    st.caption("Nothing tagged yet.")

            # --- Feedback review + export -----------------------------------------------------------
            # The ratings are only worth collecting if they can be looked at, so the file that collects
            # them is readable right here: who rated what, which categories are landing and which aren't,
            # and a download of the raw CSV.
            with st.expander("\U0001f4dd Key feedback \u2014 review and export", expanded=False):
                st.text_input("Your name (saved with each rating)", key="ktv_feedback_coach",
                              placeholder="optional")
                _fb = load_ktv_feedback()
                if _fb.empty:
                    st.caption("No ratings recorded yet. Use the buttons under any key to start.")
                else:
                    _fb_c1, _fb_c2, _fb_c3 = st.columns(3)
                    _fb_c1.metric("Ratings recorded", len(_fb))
                    _fb_c2.metric("Beneficial", int((_fb["rating"] == "Beneficial").sum()))
                    _fb_c3.metric("Flagged inaccurate", int((_fb["rating"] == "Not accurate").sum()))

                    _fb_by_cat = (_fb.groupby(["category", "rating"]).size().unstack(fill_value=0)
                                  .reindex(columns=KTV_RATINGS, fill_value=0).reset_index())
                    _fb_by_cat["Total"] = _fb_by_cat[KTV_RATINGS].sum(axis=1)
                    st.markdown("**By category**")
                    st.dataframe(_fb_by_cat.rename(columns={"category": "Category"}).sort_values("Total", ascending=False),
                                 hide_index=True, use_container_width=True)

                    _fb_bad = _fb[_fb["rating"] == "Not accurate"]
                    if not _fb_bad.empty:
                        st.markdown("**Flagged as inaccurate** \u2014 the ones worth fixing first")
                        st.dataframe(
                            _fb_bad.groupby(["key_text", "category"]).size().reset_index(name="Times flagged")
                            .sort_values("Times flagged", ascending=False).head(10),
                            hide_index=True, use_container_width=True)

                    st.markdown("**All ratings**")
                    st.dataframe(_fb.sort_values("recorded_at", ascending=False),
                                 hide_index=True, use_container_width=True)
                    st.download_button(
                        "\u2b07\ufe0f Download ktv_feedback.csv", data=_fb.to_csv(index=False).encode("utf-8"),
                        file_name="ktv_feedback.csv", mime="text/csv", key="ktv_fb_download")
                st.caption(
                    f"Saved to `{KTV_FEEDBACK_FILE}` in the same folder as the parser's CSVs, appended one "
                    "row per click (never overwritten). On a hosted Streamlit instance that folder resets "
                    "when the app restarts -- download the CSV, or point DATA_DIR at a synced folder, if "
                    "these need to survive a redeploy."
                )

            if _ungrouped:
                with st.expander(f"Other \u2014 {len(_ungrouped)} item{'s' if len(_ungrouped) != 1 else ''}", expanded=False):
                    for _n, (_icon, _headline, _caption, _reason, _cats, _side, _source) in enumerate(_ungrouped, start=1):
                        _render_key_item(_n, _icon, _headline, _caption, _reason, _cats, _side, _source,
                                         _category="Other", _section="Other")
        else:
            st.info("No scouting data available yet for this opponent.")






# --------------------------------------------------------------------------------------------------------------
# Section 2: Previous Games
# --------------------------------------------------------------------------------------------------------------
def render_previous_games():
    schedule = load_table("uww_schedule")
    short_names = load_short_opponent_names()

    # Only show games before the upcoming game (exclude future-scheduled games with results)
    if "Upcoming" in schedule.columns:
        upcoming = schedule[schedule["Upcoming"].str.strip().str.lower() == "yes"]
    else:
        upcoming = schedule[~played_mask(schedule)]
    if not upcoming.empty:
        next_game_idx = upcoming.iloc[0].name
        pre_upcoming = schedule.loc[:next_game_idx].iloc[:-1]
    else:
        pre_upcoming = schedule
    played = pre_upcoming[played_mask(pre_upcoming)].reset_index(drop=True)
    if played.empty:
        st.info("No played games found in the schedule.")
        return

    played = played.iloc[::-1].reset_index(drop=True)  # most recent first
    labels = [
        f"{row['date']} vs {row['opponent']} ({row['outcome']} {int(row['team_score'])}-{int(row['opponent_score'])})"
        for _, row in played.iterrows()
    ]
    idx = st.selectbox("Select a game", options=range(len(labels)), format_func=lambda i: labels[i])
    game = played.iloc[idx]
    full_opponent = game["opponent"]
    short_opponent = resolve_short_opponent(full_opponent, short_names)

    # --- Broadcast-style game result banner ---
    uww_logo_b64 = find_logo_b64("UW-Whitewater")
    opp_display = strip_known_mascot_suffix(short_opponent) if short_opponent else strip_team_mascot(full_opponent)
    opp_logo_b64 = find_logo_b64(short_opponent, full_opponent)

    uww_logo_img = f'<div style="height:56px;display:flex;align-items:center;justify-content:center;margin-bottom:6px;"><img src="data:image/png;base64,{uww_logo_b64}" style="max-height:56px;max-width:80px;object-fit:contain;"></div>' if uww_logo_b64 else '<div style="height:56px;"></div>'
    opp_logo_img = f'<div style="height:56px;display:flex;align-items:center;justify-content:center;margin-bottom:6px;"><img src="data:image/png;base64,{opp_logo_b64}" style="max-height:56px;max-width:80px;object-fit:contain;"></div>' if opp_logo_b64 else '<div style="height:56px;"></div>'

    game_date = str(game.get("date", "-"))
    location = str(game.get("location", "-"))
    uww_score = int(game["team_score"])
    opp_score = int(game["opponent_score"])
    outcome = game["outcome"]
    margin = int(game["point_margin"])

    # Compute UWW record going INTO this game
    game_schedule_idx = game.name  # this is the index in the reversed played df
    # Find the original schedule position for this game
    _orig_played = pre_upcoming[played_mask(pre_upcoming)].reset_index(drop=True)
    _orig_played_rev = _orig_played.iloc[::-1].reset_index(drop=True)
    _game_original_pos = None
    for _oi, _or in _orig_played.iterrows():
        if str(_or["date"]) == str(game["date"]) and str(_or["opponent"]) == str(game["opponent"]):
            _game_original_pos = _oi
            break
    if _game_original_pos is not None and _game_original_pos > 0:
        _pre_game = _orig_played.iloc[:_game_original_pos]
        _uww_wins_pre = int((_pre_game["outcome"] == "W").sum())
        _uww_losses_pre = int((_pre_game["outcome"] == "L").sum())
    else:
        _uww_wins_pre = 0
        _uww_losses_pre = 0

    # Opponent's own record entering this game (see get_opponent_entering_record's docstring for the
    # multi-meeting caveat) -- previously never computed at all on this page, unlike UWW's own record above.
    _opp_record_pg, _opp_streak_pg = get_opponent_entering_record(short_opponent) if short_opponent else ("", "")
    _opp_entering_html = f'<div style="color:#9DAAAC;font-size:0.9rem;margin-top:2px;">{html.escape(_opp_record_pg)} entering</div>' if _opp_record_pg else ""

    outcome_color = "#2e7d32" if outcome == "W" else "#c62828"
    outcome_label = "WIN" if outcome == "W" else "LOSS"

    banner_html = (
        f'<div style="background:#1a1a2e;border-radius:10px;padding:20px 28px;margin-bottom:0.75rem;display:flex;align-items:center;justify-content:space-between;">'
        f'<div style="text-align:center;flex:1;display:flex;flex-direction:column;align-items:center;">'
        f'{uww_logo_img}'
        f'<div style="color:#ffffff;font-family:Montserrat,sans-serif;font-weight:800;font-size:1.2rem;letter-spacing:0.5px;">UW-WHITEWATER</div>'
        f'<div style="color:#ffffff;font-size:2rem;font-weight:800;margin-top:4px;">{uww_score}</div>'
        f'<div style="color:#9DAAAC;font-size:0.9rem;margin-top:2px;">{_uww_wins_pre}-{_uww_losses_pre} entering</div>'
        f'</div>'
        f'<div style="text-align:center;flex:0.8;display:flex;flex-direction:column;align-items:center;justify-content:center;">'
        f'<div style="color:{outcome_color};font-size:1.1rem;font-weight:800;letter-spacing:1px;padding:4px 14px;border:2px solid {outcome_color};border-radius:6px;">{outcome_label}</div>'
        f'<div style="color:#ffffff;font-size:1.3rem;font-weight:700;margin:6px 0;">FINAL</div>'
        f'<div style="color:#9DAAAC;font-size:0.9rem;">{game_date}</div>'
        f'<div style="color:#9DAAAC;font-size:0.85rem;">{location}</div>'
        f'</div>'
        f'<div style="text-align:center;flex:1;display:flex;flex-direction:column;align-items:center;">'
        f'{opp_logo_img}'
        f'<div style="color:#ffffff;font-family:Montserrat,sans-serif;font-weight:800;font-size:1.2rem;letter-spacing:0.5px;">{html.escape(opp_display.upper())}</div>'
        f'<div style="color:#ffffff;font-size:2rem;font-weight:800;margin-top:4px;">{opp_score}</div>'
        f'{_opp_entering_html}'
        f'</div>'
        f'</div>'
    )
    st.markdown(banner_html, unsafe_allow_html=True)

    if short_opponent is None:
        st.warning(f"No reconstructed box score, lineup, or play-by-play data found for {full_opponent} yet.")
        return

    # --- Load game data ---
    # Everything on this page is about ONE game, so filter on the date as well as the opponent. Filtering on
    # the opponent alone stacks every meeting with that team into one "game": duplicate players in the box
    # score, lineup minutes summed across both nights, and a Plan-vs-Reality panel comparing a two-game total
    # against a one-game average.
    _pg_game_date = resolve_game_date(game.get("date"))

    def _this_game(df):
        if df.empty or "opponent" not in df.columns:
            return df
        out = df[df["opponent"] == short_opponent]
        if _pg_game_date and "game_date" in out.columns:
            same = out[out["game_date"].astype(str).str[:10] == _pg_game_date]
            if not same.empty:
                return same.copy()
        return out.copy()

    box = load_table("uww_pbp_box_score")
    game_box = _this_game(box)
    stints = load_table("uww_lineup_stints")
    game_stints = _this_game(stints)

    # Fix swapped team labels / lineup columns
    _flags_df = load_table("uww_coaching_flags")
    uww_names = set(_flags_df["player"].dropna().str.lower().tolist())
    if not game_box.empty:
        uww_labeled = game_box[game_box["team"] == "UW-Whitewater"]
        if not uww_labeled.empty:
            sample_players = uww_labeled["player"].str.lower().tolist()
            if sum(1 for p in sample_players if p in uww_names) == 0:
                team_map = {"UW-Whitewater": short_opponent, short_opponent: "UW-Whitewater"}
                game_box["team"] = game_box["team"].map(team_map).fillna(game_box["team"])
    if not game_stints.empty:
        sample_lineup = str(game_stints.iloc[0]["uww_lineup"])
        names_in_col = [p.strip().lower() for p in sample_lineup.split(",")]
        if sum(1 for n in names_in_col if n in uww_names) == 0:
            game_stints[["uww_lineup", "opp_lineup"]] = game_stints[["opp_lineup", "uww_lineup"]].values

    uww_game_box = game_box[game_box["team"] == "UW-Whitewater"] if not game_box.empty else pd.DataFrame()
    opp_game_box = game_box[game_box["team"] != "UW-Whitewater"] if not game_box.empty else pd.DataFrame()

    # --- TEAM STATS: PLAN vs REALITY  |  BOX SCORE (side by side) ---
    _tsb_left, _tsb_right = st.columns([1, 2])
    with _tsb_left:
        # --- TEAM STATS: EXPECTED vs ACTUAL ---
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">TEAM STATS: PLAN vs REALITY</div></div>', unsafe_allow_html=True)

        if not uww_game_box.empty:
            # Compute actual game stats
            _ng = 1
            actual_stats = {
                "Points": uww_score,
                "Points Against": opp_score,
                "FG%": (uww_game_box["FGM"].sum() / uww_game_box["FGA"].sum() * 100) if uww_game_box["FGA"].sum() > 0 else 0,
                "Rebounds": uww_game_box["REB"].sum() if "REB" in uww_game_box.columns else 0,
                "Assists": uww_game_box["AST"].sum() if "AST" in uww_game_box.columns else 0,
                "Turnovers": uww_game_box["TO"].sum() if "TO" in uww_game_box.columns else 0,
                "Steals": uww_game_box["STL"].sum() if "STL" in uww_game_box.columns else 0,
                "Blocks": uww_game_box["BLK"].sum() if "BLK" in uww_game_box.columns else 0,
            }
            _uww_3pm = uww_game_box["FG3M"].sum() if "FG3M" in uww_game_box.columns else 0
            _uww_3pa = uww_game_box["FG3A"].sum() if "FG3A" in uww_game_box.columns else 0
            _uww_ftm = uww_game_box["FTM"].sum() if "FTM" in uww_game_box.columns else 0
            _uww_fta = uww_game_box["FTA"].sum() if "FTA" in uww_game_box.columns else 0
            actual_stats["3P%"] = (_uww_3pm / _uww_3pa * 100) if _uww_3pa > 0 else 0
            actual_stats["FT%"] = (_uww_ftm / _uww_fta * 100) if _uww_fta > 0 else 0
            actual_stats["A:TO Ratio"] = (actual_stats["Assists"] / actual_stats["Turnovers"]) if actual_stats["Turnovers"] > 0 else 0

            # Compute season averages going INTO this game (expected)
            _pre_box = scope_to_played(box, _orig_played.iloc[:_game_original_pos]) if _game_original_pos else box.iloc[0:0]
            _pre_uww_box = _pre_box[_pre_box["team"] == "UW-Whitewater"] if not _pre_box.empty else pd.DataFrame()
            # Validate using roster
            if not _pre_uww_box.empty:
                _sample = _pre_uww_box["player"].str.lower().tolist()[:5]
                if sum(1 for p in _sample if p in uww_names) == 0:
                    _pre_uww_box = _pre_box[_pre_box["team"] != "UW-Whitewater"]

            expected_stats = {}
            if not _pre_uww_box.empty:
                _n_pre = _pre_uww_box["opponent"].nunique() or 1
                _pre_games = _orig_played.iloc[:_game_original_pos] if _game_original_pos else pd.DataFrame()
                expected_stats = {
                    "Points": _pre_games["team_score"].mean() if not _pre_games.empty else 0,
                    "Points Against": _pre_games["opponent_score"].mean() if not _pre_games.empty else 0,
                    "FG%": (_pre_uww_box["FGM"].sum() / _pre_uww_box["FGA"].sum() * 100) if _pre_uww_box["FGA"].sum() > 0 else 0,
                    "Rebounds": _pre_uww_box["REB"].sum() / _n_pre if "REB" in _pre_uww_box.columns else 0,
                    "Assists": _pre_uww_box["AST"].sum() / _n_pre if "AST" in _pre_uww_box.columns else 0,
                    "Turnovers": _pre_uww_box["TO"].sum() / _n_pre if "TO" in _pre_uww_box.columns else 0,
                    "Steals": _pre_uww_box["STL"].sum() / _n_pre if "STL" in _pre_uww_box.columns else 0,
                    "Blocks": _pre_uww_box["BLK"].sum() / _n_pre if "BLK" in _pre_uww_box.columns else 0,
                }
                _p3pm = _pre_uww_box["FG3M"].sum() if "FG3M" in _pre_uww_box.columns else 0
                _p3pa = _pre_uww_box["FG3A"].sum() if "FG3A" in _pre_uww_box.columns else 0
                _pftm = _pre_uww_box["FTM"].sum() if "FTM" in _pre_uww_box.columns else 0
                _pfta = _pre_uww_box["FTA"].sum() if "FTA" in _pre_uww_box.columns else 0
                expected_stats["3P%"] = (_p3pm / _p3pa * 100) if _p3pa > 0 else 0
                expected_stats["FT%"] = (_pftm / _pfta * 100) if _pfta > 0 else 0
                _e_ast = expected_stats["Assists"]
                _e_to = expected_stats["Turnovers"]
                expected_stats["A:TO Ratio"] = (_e_ast / _e_to) if _e_to > 0 else 0

            # Build comparison HTML
            stat_order = ["Points", "Points Against", "FG%", "3P%", "FT%", "Rebounds", "Assists", "Turnovers", "A:TO Ratio", "Steals", "Blocks"]
            lower_better = {"Points Against", "Turnovers"}
            rows_html = ""
            for stat in stat_order:
                act = actual_stats.get(stat, 0)
                exp = expected_stats.get(stat, 0)
                if act == 0 and exp == 0:
                    continue
                is_pct = "%" in stat or "Ratio" in stat
                if is_pct:
                    act_fmt = f"{act:.1f}{'%' if '%' in stat else ''}"
                    exp_fmt = f"{exp:.1f}{'%' if '%' in stat else ''}"
                elif "Ratio" in stat:
                    act_fmt = f"{act:.2f}"
                    exp_fmt = f"{exp:.2f}"
                else:
                    act_fmt = f"{act:.1f}"
                    exp_fmt = f"{exp:.1f}"
                # Determine if actual was better/worse than expected
                diff = act - exp
                if stat in lower_better:
                    better = diff < 0
                else:
                    better = diff > 0
                diff_color = "#2e7d32" if better else "#c62828" if abs(diff) > 0.5 else "#666"
                diff_fmt = f"{diff:+.1f}" if not is_pct else f"{diff:+.1f}{'%' if '%' in stat else ''}"
                if "Ratio" in stat:
                    diff_fmt = f"{diff:+.2f}"
                rows_html += (
                    f'<div style="padding:8px 0;border-bottom:1px solid #eee;display:flex;align-items:center;justify-content:space-between;">'
                    f'<span style="font-size:1rem;width:80px;font-weight:600;">{exp_fmt}</span>'
                    f'<span style="font-size:0.85rem;color:#666;font-weight:600;text-transform:uppercase;flex:1;text-align:center;">{stat}</span>'
                    f'<span style="font-size:1rem;width:80px;text-align:right;font-weight:700;">{act_fmt}</span>'
                    f'<span style="font-size:0.8rem;width:60px;text-align:right;color:{diff_color};font-weight:600;">{diff_fmt}</span>'
                    f'</div>'
                )
            if rows_html:
                stats_comparison_html = (
                    f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:14px 18px;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding:0 4px;">'
                    f'<span style="font-size:0.9rem;font-weight:700;color:#888;">Season Avg</span>'
                    f'<span style="font-size:0.9rem;font-weight:700;color:#4E2A84;">UWW This Game</span>'
                    f'<span style="font-size:0.8rem;font-weight:600;color:#888;">+/-</span>'
                    f'</div>{rows_html}</div>'
                )
                st.markdown(stats_comparison_html, unsafe_allow_html=True)
            else:
                st.caption("Not enough prior game data for comparison.")
        else:
            st.caption("No box score data available for this game.")
    with _tsb_right:
        # --- BOX SCORE ---
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">BOX SCORE</div></div>', unsafe_allow_html=True)

        # Precompute lineup data for the later LINEUP PERFORMANCE section (kept here since it's been computed
        # alongside the box score since before this fix -- not actually used by the box-score table below).
        if not game_stints.empty:
            game_stints["margin_per_min"] = (game_stints["uww_margin_change"] / game_stints["stint_minutes"]).round(2)
            game_stints = game_stints.sort_values("stint_minutes", ascending=False)

        # NOTE: this used to be gated on `game_box.empty and game_stints.empty` -- so if game_box was empty but
        # game_stints wasn't, this whole section rendered NOTHING (no table, no warning) instead of explaining
        # why. The box score table only ever depends on game_box, so check that alone.
        if game_box.empty:
            st.warning("No reconstructed box score found for this game yet.")
        else:
            compact_cols = [c for c in ["player", "MIN", "PTS", "REB", "AST", "STL", "BLK", "TO", "FG%"]
                             if c in game_box.columns]
            full_cols = [c for c in ["player", "MIN", "started", "PTS", "FGM", "FGA", "FG%", "FG3M", "FG3A", "3P%",
                                      "FTM", "FTA", "FT%", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF"]
                          if c in game_box.columns]
            teams = sorted(game_box["team"].unique().tolist())

            # Side-by-side box score (UWW left, Opp right)
            if len(teams) == 2:
                _t_uww = "UW-Whitewater" if "UW-Whitewater" in teams else teams[0]
                _t_opp = [t for t in teams if t != _t_uww][0] if len(teams) > 1 else teams[0]
                col_uww_box, col_opp_box = st.columns(2)
                with col_uww_box:
                    st.markdown(f"**UW-Whitewater**")
                    _uww_df = game_box[game_box["team"] == _t_uww].sort_values(["started", "PTS"], ascending=[False, False])
                    st.dataframe(_uww_df[compact_cols], hide_index=True, use_container_width=True)
                with col_opp_box:
                    st.markdown(f"**{_t_opp}**")
                    _opp_df = game_box[game_box["team"] == _t_opp].sort_values(["started", "PTS"], ascending=[False, False])
                    st.dataframe(_opp_df[compact_cols], hide_index=True, use_container_width=True)

                # Full box score, in a dialog rather than an expander -- keeps the main box score compact
                # (especially now that it shares a column with Team Stats) while still one click away.
                @st.dialog("Full Box Score", width="large")
                def _show_full_box_score_dialog():
                    st.markdown("**UW-Whitewater**")
                    st.dataframe(_uww_df[full_cols], hide_index=True, use_container_width=True)
                    st.markdown(f"**{_t_opp}**")
                    st.dataframe(_opp_df[full_cols], hide_index=True, use_container_width=True)

                if st.button("View full box score", key=f"full_box_score_btn_{short_opponent}_{game.get('date')}"):
                    _show_full_box_score_dialog()
            elif len(teams) == 1:
                # Only one team's rows made it into game_box -- still show what's there, with a heads-up that
                # the other side is missing, rather than silently rendering half a box score with no explanation.
                st.info(f"Box score data found for {teams[0]} only -- the other team's rows weren't reconstructed for this game.")
                for team_name in teams:
                    st.markdown(f"**{team_name}**")
                    team_df = game_box[game_box["team"] == team_name].sort_values(["started", "PTS"], ascending=[False, False])
                    st.dataframe(team_df[compact_cols], hide_index=True, use_container_width=True)
            else:
                st.warning(f"Box score has {len(teams)} distinct team label(s) ({teams}) instead of the expected 2 -- showing each as found.")
                for team_name in teams:
                    st.markdown(f"**{team_name}**")
                    team_df = game_box[game_box["team"] == team_name].sort_values(["started", "PTS"], ascending=[False, False])
                    st.dataframe(team_df[compact_cols], hide_index=True, use_container_width=True)

    # --- KEYS TO VICTORY: PLAN vs EXECUTION ---
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">KEYS TO VICTORY: PLAN vs EXECUTION</div></div>', unsafe_allow_html=True)
    game_plans = load_table("uww_opponent_game_plans")
    ktv_plan = game_plans[(game_plans["opponent"] == short_opponent) & (game_plans["topic"] == "KEYS TO VICTORY")]
    strengths_match = game_plans[(game_plans["opponent"] == short_opponent) & (game_plans["topic"] == "TEAM STRENGTHS")]

    if ktv_plan.empty:
        st.info("No keys to victory were defined for this game.")
    else:
        ktv_notes = str(ktv_plan.iloc[0]["notes"])
        keys = [_normalize_case(re.sub(r"^\d+\.\s*", "", k.strip())) for k in ktv_notes.split("|") if k.strip()]

        # Get actual game stats for grading
        if not uww_game_box.empty:
            _act_pts = int(uww_game_box["PTS"].sum())
            _act_reb = int(uww_game_box["REB"].sum()) if "REB" in uww_game_box.columns else 0
            _act_ast = int(uww_game_box["AST"].sum()) if "AST" in uww_game_box.columns else 0
            _act_to = int(uww_game_box["TO"].sum()) if "TO" in uww_game_box.columns else 0
            _act_stl = int(uww_game_box["STL"].sum()) if "STL" in uww_game_box.columns else 0
            _act_blk = int(uww_game_box["BLK"].sum()) if "BLK" in uww_game_box.columns else 0
            _act_pf = int(uww_game_box["PF"].sum()) if "PF" in uww_game_box.columns else 0
            _fgm_t = int(uww_game_box["FGM"].sum()) if "FGM" in uww_game_box.columns else 0
            _fg3m_t = int(uww_game_box["FG3M"].sum()) if "FG3M" in uww_game_box.columns else 0
            _fga_t = int(uww_game_box["FGA"].sum()) if "FGA" in uww_game_box.columns else 0
            _fg3a_t = int(uww_game_box["FG3A"].sum()) if "FG3A" in uww_game_box.columns else 0
            _ftm_t = int(uww_game_box["FTM"].sum()) if "FTM" in uww_game_box.columns else 0
            _fta_t = int(uww_game_box["FTA"].sum()) if "FTA" in uww_game_box.columns else 0

            actual_map = {"PTS": _act_pts, "REB": _act_reb, "AST": _act_ast,
                          "TO": _act_to, "STL": _act_stl, "BLK": _act_blk, "PF": _act_pf}
            if "OREB" in uww_game_box.columns:
                actual_map["ORB"] = int(uww_game_box["OREB"].sum())
            if "DREB" in uww_game_box.columns:
                actual_map["DRB"] = int(uww_game_box["DREB"].sum())
            actual_map["FG2M"] = _fgm_t - _fg3m_t
            actual_map["FG2A"] = _fga_t - _fg3a_t
            actual_map["FG2%"] = round(actual_map["FG2M"] / actual_map["FG2A"] * 100, 1) if actual_map["FG2A"] > 0 else 0
            actual_map["3PM-A"] = f"{_fg3m_t}-{_fg3a_t}"
            actual_map["3P%"] = round(_fg3m_t / _fg3a_t * 100, 1) if _fg3a_t > 0 else 0
            actual_map["FGM-A"] = f"{_fgm_t}-{_fga_t}"
            actual_map["FG%"] = round(_fgm_t / _fga_t * 100, 1) if _fga_t > 0 else 0
            actual_map["FTM-A"] = f"{_ftm_t}-{_fta_t}"
            actual_map["FT%"] = round(_ftm_t / _fta_t * 100, 1) if _fta_t > 0 else 0

            # Show each key with relevant actual stats
            for ki, k in enumerate(keys):
                ktv_text_lower = k.lower()
                relevant_stats = []
                for phrase, stat_cols in KEYS_TO_VICTORY_STAT_MAP.items():
                    if phrase in ktv_text_lower:
                        for sc in stat_cols:
                            if sc not in relevant_stats:
                                relevant_stats.append(sc)
                # Build stat string for this key
                stat_parts = []
                for rs in relevant_stats:
                    val = actual_map.get(rs)
                    if val is not None:
                        label = STAT_LABELS.get(rs, rs)
                        if isinstance(val, str):
                            stat_parts.append(f"{label}: {val}")
                        elif isinstance(val, float):
                            stat_parts.append(f"{label}: {val:.1f}")
                        else:
                            stat_parts.append(f"{label}: {val}")
                stat_str = " | ".join(stat_parts) if stat_parts else ""
                # Outcome badge
                outcome_badge = f' <span style="background:{outcome_color};color:#fff;font-size:0.7rem;font-weight:700;padding:2px 8px;border-radius:8px;margin-left:6px;">{outcome}</span>'
                stat_html = f' <span style="font-size:0.8rem;color:#555;margin-left:8px;">{stat_str}</span>' if stat_str else ""
                st.markdown(
                    f'<div style="border:1px solid #eee;border-radius:8px;padding:10px 14px;margin-bottom:6px;">'
                    f'<span style="font-size:0.95rem;font-weight:600;">{ki+1}. {html.escape(k)}</span>'
                    f'{stat_html}</div>',
                    unsafe_allow_html=True
                )

            # KTV categories + outcome
            ktv_game_cats = load_table("uww_ktv_game_categories")
            opp_cats = ktv_game_cats[ktv_game_cats["opponent"] == short_opponent]
            if not opp_cats.empty:
                cats = opp_cats["category"].tolist()
                cat_outcome = opp_cats.iloc[0].get("outcome", "")
                _cat_out_str = f" — {cat_outcome}" if pd.notna(cat_outcome) and str(cat_outcome).strip() else ""
                st.caption(f"Categories: {', '.join(cats)}{_cat_out_str}")
        else:
            for k in keys:
                st.markdown(f"- {k}")
            st.caption("No box score data to evaluate performance.")

    # --- TEAM STRENGTHS (scouting notes) ---
    if not strengths_match.empty:
        with st.expander("📋 **OPPONENT STRENGTHS** (pre-game scouting notes)", expanded=False):
            str_notes = strengths_match.iloc[0]["notes"]
            items = [re.sub(r"^\d+\.\s*", "", s.strip()) for s in str(str_notes).split("|") if s.strip()]
            for item in items:
                st.markdown(f"- {item}")

    # --- PROJECTED vs ACTUAL ---
    try:
        _proj_box = load_table("uww_projected_box_score")
        if not _proj_box.empty and not uww_game_box.empty:
            # Match projected players to actual game box by player name
            _proj_box["_join_key"] = _proj_box["PLAYER"].str.strip().str.lower()
            _actual = uww_game_box.copy()
            _actual["_join_key"] = _actual["player"].str.strip().str.lower()

            _merged = _proj_box.merge(_actual[["_join_key", "PTS", "REB", "AST", "MIN"]], on="_join_key", how="inner", suffixes=("_proj", "_act"))

            if not _merged.empty:
                st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">PROJECTED vs ACTUAL PERFORMANCE</div></div>', unsafe_allow_html=True)

                # Team totals comparison
                proj_pts_total = _merged["projected_PTS"].sum()
                act_pts_total = _merged["PTS"].sum()
                proj_reb_total = _merged["projected_REB"].sum()
                act_reb_total = _merged["REB"].sum()
                proj_ast_total = _merged["projected_AST"].sum()
                act_ast_total = _merged["AST"].sum()

                _m1, _m2, _m3 = st.columns(3)
                _pts_diff = act_pts_total - proj_pts_total
                _reb_diff = act_reb_total - proj_reb_total
                _ast_diff = act_ast_total - proj_ast_total
                _m1.metric("Team PTS (Proj → Act)", f"{int(proj_pts_total)} → {int(act_pts_total)}", delta=f"{_pts_diff:+.0f}")
                _m2.metric("Team REB (Proj → Act)", f"{int(proj_reb_total)} → {int(act_reb_total)}", delta=f"{_reb_diff:+.0f}")
                _m3.metric("Team AST (Proj → Act)", f"{int(proj_ast_total)} → {int(act_ast_total)}", delta=f"{_ast_diff:+.0f}")

                # Player-level comparison table
                _comp_rows = []
                for _, r in _merged.iterrows():
                    _comp_rows.append({
                        "Player": r["PLAYER"],
                        "Proj MIN": round(r.get("MIN_proj", r.get("MIN", 0)), 1) if "MIN_proj" in r.index or "MIN" in r.index else "-",
                        "Act MIN": round(r.get("MIN_act", r.get("MIN", 0)), 1) if "MIN_act" in r.index else "-",
                        "Proj PTS": int(r["projected_PTS"]),
                        "Act PTS": int(r["PTS"]),
                        "PTS +/-": int(r["PTS"] - r["projected_PTS"]),
                        "Proj REB": int(r["projected_REB"]),
                        "Act REB": int(r["REB"]),
                        "REB +/-": int(r["REB"] - r["projected_REB"]),
                        "Proj AST": int(r["projected_AST"]),
                        "Act AST": int(r["AST"]),
                        "AST +/-": int(r["AST"] - r["projected_AST"]),
                    })
                _comp_df = pd.DataFrame(_comp_rows)

                def _color_diff(val):
                    if isinstance(val, (int, float)):
                        if val > 0:
                            return "color: #2e7d32; font-weight: 600;"
                        elif val < 0:
                            return "color: #c62828; font-weight: 600;"
                    return ""

                diff_cols = ["PTS +/-", "REB +/-", "AST +/-"]
                styled = style_map(_comp_df.style, _color_diff, subset=diff_cols)
                st.dataframe(styled, hide_index=True, use_container_width=True)

                # Biggest over/under performers
                _comp_df["total_diff"] = _comp_df["PTS +/-"] + _comp_df["REB +/-"] + _comp_df["AST +/-"]
                _over = _comp_df.nlargest(1, "total_diff")
                _under = _comp_df.nsmallest(1, "total_diff")
                _oc, _uc = st.columns(2)
                if not _over.empty:
                    _op = _over.iloc[0]
                    _oc.success(f"🔥 **Exceeded Projection**: {_op['Player']} (+{int(_op['total_diff'])} combined PTS/REB/AST)")
                if not _under.empty:
                    _up = _under.iloc[0]
                    if _up["total_diff"] < 0:
                        _uc.warning(f"📉 **Below Projection**: {_up['Player']} ({int(_up['total_diff'])} combined PTS/REB/AST)")
    except Exception as _e:
        report_section_error("Projected vs. Actual performance", _e)

    # --- LINEUP PERFORMANCE ---
    if not game_stints.empty:
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">LINEUP PERFORMANCE</div></div>', unsafe_allow_html=True)
        lineup_agg = (
            game_stints.groupby("uww_lineup")
            .agg(minutes=("stint_minutes", "sum"), actual_margin=("uww_margin_change", "sum"))
            .reset_index()
            .rename(columns={"uww_lineup": "lineup"})
        )
        lineup_agg["margin_per_min"] = (lineup_agg["actual_margin"] / lineup_agg["minutes"]).round(2)
        lineup_agg = lineup_agg.sort_values("minutes", ascending=False)

        # Show best and worst lineups side by side
        # Minimum 1 minute played this game -- keeps a lineup that barely saw the floor from topping the
        # list off a small, noisy sample (e.g. a 20-second stretch with a lucky run).
        _best_lu = lineup_agg[lineup_agg["minutes"] >= 1.0].nlargest(3, "margin_per_min")
        _worst_lu = lineup_agg[lineup_agg["minutes"] >= 1.0].nsmallest(3, "margin_per_min")

        def _last_names_pg(lineup_str):
            return ", ".join(surname(n) for n in str(lineup_str).split(",") if n.strip())

        _lu_col1, _lu_col2 = st.columns(2)
        with _lu_col1:
            st.markdown("**Best Lineups**")
            for _, r in _best_lu.iterrows():
                ln = _last_names_pg(r["lineup"])
                st.markdown(f'<div style="font-size:0.85rem;margin:4px 0;"><strong style="color:#2e7d32;">{r["margin_per_min"]:+.2f}</strong>/min ({r["minutes"]:.1f} min) — {html.escape(ln)}</div>', unsafe_allow_html=True)
        with _lu_col2:
            st.markdown("**Worst Lineups**")
            for _, r in _worst_lu.iterrows():
                ln = _last_names_pg(r["lineup"])
                st.markdown(f'<div style="font-size:0.85rem;margin:4px 0;"><strong style="color:#c62828;">{r["margin_per_min"]:+.2f}</strong>/min ({r["minutes"]:.1f} min) — {html.escape(ln)}</div>', unsafe_allow_html=True)
        st.caption("Best/Worst Lineups require a minimum of 1 minute played this game, so a lineup that was on the floor for a few seconds can't top the list on a fluke run.")

        with st.expander("All lineups", expanded=False):
            st.dataframe(
                lineup_agg[["lineup", "minutes", "actual_margin", "margin_per_min"]],
                hide_index=True, use_container_width=True,
            )

    # --- LINEUP MATCHUP HISTORY ---
    if not game_stints.empty:
        matchup_agg = game_stints.groupby(["uww_lineup", "opp_lineup"]).agg(
            mins=("stint_minutes", "sum"), margin=("uww_margin_change", "sum")
        ).reset_index()
        matchup_agg = matchup_agg[matchup_agg["mins"] >= 2.0]
        if not matchup_agg.empty:
            matchup_agg["rate"] = (matchup_agg["margin"] / matchup_agg["mins"]).round(2)
            st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">\u2694\uFE0F LINEUP MATCHUPS (min 2 min)</div></div>', unsafe_allow_html=True)
            best = matchup_agg.nlargest(3, "rate")
            matchup_html = '<div style="font-size:0.85rem;font-weight:600;margin-bottom:4px;">Best:</div>'
            for _, r in best.iterrows():
                uww_ln = _last_names_pg(r["uww_lineup"])
                opp_ln = _last_names_pg(r["opp_lineup"])
                matchup_html += f'<div style="font-size:0.85rem;margin:3px 0;"><strong>{r["rate"]:+.2f}</strong>/min \u2014 <span style="color:#4E2A84;">{html.escape(uww_ln)}</span> vs <span style="color:#c62828;">{html.escape(opp_ln)}</span> <span style="color:#888;">[{r["mins"]:.1f} min]</span></div>'
            worst = matchup_agg.nsmallest(3, "rate")
            matchup_html += '<div style="font-size:0.85rem;font-weight:600;margin:8px 0 4px;">Worst:</div>'
            for _, r in worst.iterrows():
                uww_ln = _last_names_pg(r["uww_lineup"])
                opp_ln = _last_names_pg(r["opp_lineup"])
                matchup_html += f'<div style="font-size:0.85rem;margin:3px 0;"><strong>{r["rate"]:+.2f}</strong>/min \u2014 <span style="color:#4E2A84;">{html.escape(uww_ln)}</span> vs <span style="color:#c62828;">{html.escape(opp_ln)}</span> <span style="color:#888;">[{r["mins"]:.1f} min]</span></div>'
            st.markdown(matchup_html, unsafe_allow_html=True)

    # --- FULL GAME PLAN (expander) ---
    other_plans = game_plans[(game_plans["opponent"] == short_opponent) & (~game_plans["topic"].isin(["KEYS TO VICTORY", "TEAM STRENGTHS"]))]
    if not other_plans.empty:
        with st.expander("\U0001f4cb **FULL GAME PLAN** — Offensive & Defensive Schemes", expanded=False):
            categories = list(other_plans["category"].unique())
            gp_left, gp_right = st.columns(2)
            for idx_c, category in enumerate(categories):
                group = other_plans[other_plans["category"] == category]
                col = gp_left if idx_c % 2 == 0 else gp_right
                with col:
                    with st.container(border=True):
                        st.markdown(f"#### {category}")
                        for _, r in group.iterrows():
                            st.markdown(f"**{r['topic']}**")
                            notes = str(r["notes"])
                            if "|" in notes:
                                items = [item.strip() for item in notes.split("|") if item.strip()]
                                for item in items:
                                    st.markdown(f"- {item}")
                            else:
                                st.write(notes)
                            st.markdown("")

    # --- GAME TEMPO ---
    # CONFIRMED CHANGE (requested): previously just a single caption line under the box score showing this
    # game's own pace. Now its own section with the same "entering this game" + "result" shape as the
    # Scoring Runs section below and the Pace & Style KTV card on the Upcoming Game page -- what UWW's own
    # tempo tendency looked like BEFORE this game (games strictly before it, via exclusive=True -- this is
    # deliberately NOT the same inclusive cutoff the old caption used, since "entering the game" should mean
    # what was known walking in, not a number this very game itself helped produce), alongside what actually
    # happened. _pg_game_date can be None (resolve_game_date() doesn't match every display-date format) -- in
    # that case the section still shows the result, just without a fast/slow read against nothing solid.
    try:
        if not uww_game_box.empty and not opp_game_box.empty:
            _pg_pace_d = compute_efficiency_pace(uww_game_box, opp_game_box, 1)
            _pg_pre_median = None
            if _pg_game_date is not None:
                _, _pg_pre_median = compute_uww_pace_by_game(as_of_date=_pg_game_date, exclusive=True)
            st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">\u23F1\uFE0F GAME TEMPO</div></div>', unsafe_allow_html=True)
            if _pg_pre_median is not None:
                st.markdown(f"**Entering this game:** UWW's own median pace across the games before this one "
                            f"was **{_pg_pre_median:.1f}** poss/gm.")
                _pg_bucket = "faster" if _pg_pace_d["Pace"] > _pg_pre_median else "slower"
                st.markdown(f"**Result:** this game was played at **{_pg_pace_d['Pace']:.0f}** poss/gm -- "
                            f"**{_pg_bucket}** than UWW's tempo up to that point. Net Rtg "
                            f"**{_pg_pace_d['Net Rtg']:+.1f}**.")
            else:
                st.markdown(f"**Result:** this game was played at **{_pg_pace_d['Pace']:.0f}** poss/gm. "
                            f"Net Rtg **{_pg_pace_d['Net Rtg']:+.1f}**.")
                st.caption("Not enough games before this one yet (need 4+) to say whether this was fast or "
                           "slow for UWW at the time.")
    except Exception:
        pass

    # --- SCORING RUNS & CLUTCH MOMENTS (this game) ---
    _pg_runs = load_table("uww_scoring_runs")
    _pg_run_row = _this_game(_pg_runs) if not _pg_runs.empty else pd.DataFrame()
    if not _pg_run_row.empty:
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">\U0001F4C8 SCORING RUNS &amp; LARGEST LEADS</div></div>', unsafe_allow_html=True)
        # CONFIRMED CHANGE (requested): added this "entering this game" line, same idea as GAME TEMPO above
        # and the Runs We Go On / Runs Against Us KTV cards -- UWW's own run tendency BEFORE this game,
        # using the exact same >=10-point "big run" bar those cards use, from games strictly before this one.
        if _pg_game_date is not None:
            _pg_off_rate, _pg_def_rate, _pg_run_n = compute_uww_run_rates(as_of_date=_pg_game_date, exclusive=True)
            if _pg_off_rate is not None:
                st.markdown(f"**Entering this game:** across the {_pg_run_n} game(s) before this one, UWW had "
                            f"gone on a 10-0-or-better run in **{100 * _pg_off_rate:.0f}%** of them, and given "
                            f"one up in **{100 * _pg_def_rate:.0f}%**.")
            else:
                st.caption("Not enough games before this one yet (need at least 1 with run data) to describe "
                           "UWW's run tendency at the time.")
        st.markdown("**Result:**")
        _rr = _pg_run_row.iloc[0]
        rr_col1, rr_col2 = st.columns(2)
        rr_col1.metric("UWW biggest run", f"{int(_rr['uww_biggest_run'])} pts")
        rr_col1.metric("UWW largest lead", f"{int(_rr['uww_largest_lead'])} pts")
        rr_col2.metric(f"{short_opponent} biggest run", f"{int(_rr['opponent_biggest_run'])} pts")
        rr_col2.metric(f"{short_opponent} largest lead", f"{int(_rr['opponent_largest_lead'])} pts")
        st.caption(f"During UWW's run — UWW: {_rr.get('uww_run_uww_lineup', '-')} | {short_opponent}: {_rr.get('uww_run_opp_lineup', '-')}")

    _pg_clutch = load_table("uww_clutch_events")
    _pg_clutch_game = _this_game(_pg_clutch) if not _pg_clutch.empty else pd.DataFrame()
    if not _pg_clutch_game.empty:
        section_header("\U0001F3C0 CLUTCH MOMENTS", "Last 5 minutes of the 2nd half or any overtime, with the score within 8 points.")
        _cg_display_cols = [c for c in ["period", "time_remaining", "team", "player", "event_type", "raw_text", "uww_score", "opp_score"] if c in _pg_clutch_game.columns]
        st.dataframe(_pg_clutch_game[_cg_display_cols], hide_index=True, use_container_width=True, height=250)

    # --- PLAY-BY-PLAY ---
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">PLAY-BY-PLAY</div></div>', unsafe_allow_html=True)
    pbp = load_table("uww_pbp_events")
    game_pbp = _this_game(pbp).sort_values("event_order")
    if game_pbp.empty:
        st.warning("No play-by-play data found for this game yet.")
    else:
        game_pbp["play_type"] = game_pbp["video_description"].str.split(">").str[1].str.strip()
        game_pbp["shot_outcome"] = game_pbp["video_description"].str.extract(r"(Make \d+ Pts|Miss \d+ Pts|Turnover|Foul)", expand=False)

        pbp_r1c1, pbp_r1c2, pbp_r1c3, pbp_r1c4 = st.columns(4)
        with pbp_r1c1:
            pbp_team_filter = st.selectbox("Team", ["All"] + sorted(game_pbp["team"].dropna().unique().tolist()), key=f"pbp_team_{short_opponent}")
        with pbp_r1c2:
            pbp_event_filter = st.selectbox("Event type", ["All"] + sorted(game_pbp["event_type"].dropna().unique().tolist()), key=f"pbp_event_{short_opponent}")
        with pbp_r1c3:
            pbp_player_search = st.text_input("Player", "", key=f"pbp_player_{short_opponent}", placeholder="Filter by player...")
        with pbp_r1c4:
            period_filter = st.selectbox("Period", ["All"] + sorted(game_pbp["period"].dropna().unique().tolist()), key=f"pbp_period_{short_opponent}")

        pbp_r2c1, pbp_r2c2, pbp_r2c3 = st.columns(3)
        with pbp_r2c1:
            pbp_play_type = st.selectbox("Play type", ["All"] + sorted(game_pbp["play_type"].dropna().unique().tolist()), key=f"pbp_playtype_{short_opponent}")
        with pbp_r2c2:
            pbp_outcome = st.selectbox("Outcome", ["All"] + sorted(game_pbp["shot_outcome"].dropna().unique().tolist()), key=f"pbp_outcome_{short_opponent}")
        with pbp_r2c3:
            pbp_video_search = st.text_input("Video description search", "", key=f"pbp_video_{short_opponent}", placeholder="e.g. P&R, Drives Left, 3pt...")

        pbp_r3c1, pbp_r3c2 = st.columns(2)
        with pbp_r3c1:
            video_only = st.checkbox("Show only video-tagged plays", value=False, key=f"pbp_vidonly_{short_opponent}")
        with pbp_r3c2:
            notes_only = st.checkbox("Show only plays with a coach note", value=False, key=f"pbp_notesonly_{short_opponent}") if "coach_note" in game_pbp.columns else False

        filtered_pbp = game_pbp.copy()
        if pbp_team_filter != "All":
            filtered_pbp = filtered_pbp[filtered_pbp["team"] == pbp_team_filter]
        if pbp_event_filter != "All":
            filtered_pbp = filtered_pbp[filtered_pbp["event_type"] == pbp_event_filter]
        if pbp_player_search.strip():
            filtered_pbp = filtered_pbp[filtered_pbp["player"].str.contains(pbp_player_search.strip(), case=False, na=False)]
        if period_filter != "All":
            filtered_pbp = filtered_pbp[filtered_pbp["period"] == period_filter]
        if pbp_play_type != "All":
            filtered_pbp = filtered_pbp[filtered_pbp["play_type"] == pbp_play_type]
        if pbp_outcome != "All":
            filtered_pbp = filtered_pbp[filtered_pbp["shot_outcome"] == pbp_outcome]
        if pbp_video_search.strip():
            filtered_pbp = filtered_pbp[filtered_pbp["video_description"].str.contains(pbp_video_search.strip(), case=False, na=False)]
        if video_only:
            filtered_pbp = filtered_pbp[filtered_pbp["video_description"].notna()]
        if notes_only:
            filtered_pbp = filtered_pbp[filtered_pbp["coach_note"].notna()]

        kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
        kpi1.metric("Total Events", len(filtered_pbp))
        scoring_events = filtered_pbp[filtered_pbp["event_type"].str.contains("made", case=False, na=False)]
        kpi2.metric("Makes", len(scoring_events))
        misses = filtered_pbp[filtered_pbp["event_type"].str.contains("missed", case=False, na=False)]
        kpi3.metric("Misses", len(misses))
        to_count = filtered_pbp[filtered_pbp["event_type"].str.contains("turnover", case=False, na=False)]
        kpi4.metric("Turnovers", len(to_count))
        unique_players = filtered_pbp["player"].dropna().nunique()
        kpi5.metric("Players", unique_players)

        display_cols = [c for c in ["period", "time_remaining", "team", "player", "event_type",
                                     "video_description", "coach_note", "uww_score", "opp_score"]
                         if c in filtered_pbp.columns]
        st.dataframe(
            filtered_pbp[display_cols].rename(columns={"coach_note": "Coach Note", "video_description": "Video Tag"}),
            hide_index=True, use_container_width=True, height=400,
        )

        # --- Coach notes summary, this game only ---
        if "coach_note" in game_pbp.columns:
            _game_notes = game_pbp[game_pbp["coach_note"].notna()]
            if not _game_notes.empty:
                _pos_total, _neg_total = 0, 0
                for _n in _game_notes["coach_note"]:
                    _p, _n_ct = note_sentiment_counts(_n)
                    _pos_total += _p
                    _neg_total += _n_ct
                st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:0.75rem 0;"><div style="font-weight:800;font-size:0.95rem;letter-spacing:0.5px;color:#4E2A84;">COACH NOTES THIS GAME</div></div>', unsafe_allow_html=True)
                _cn_c1, _cn_c2, _cn_c3 = st.columns(3)
                _cn_c1.metric("Notes captured", len(_game_notes))
                _cn_c2.metric("Positive flags", _pos_total)
                _cn_c3.metric("Negative flags", _neg_total)

# --------------------------------------------------------------------------------------------------------------
# Section 3: Team
# --------------------------------------------------------------------------------------------------------------
def render_team():
    schedule = load_table("uww_schedule")
    played = schedule[played_mask(schedule)]

    wins = int((played["outcome"] == "W").sum())
    losses = int((played["outcome"] == "L").sum())

    # --- Broadcast-style team banner ---
    import base64 as _b64_team
    _team_logo_path = os.path.join(DATA_DIR, "logo", "UW-Whitewater.png")
    _team_logo_b64 = ""
    if os.path.exists(_team_logo_path):
        with open(_team_logo_path, "rb") as _lf:
            _team_logo_b64 = _b64_team.b64encode(_lf.read()).decode()
    _team_logo_html = f'<img src="data:image/png;base64,{_team_logo_b64}" style="max-height:72px;max-width:100px;object-fit:contain;">' if _team_logo_b64 else ""

    avg_margin = f"{played['point_margin'].mean():+.1f}" if not played.empty else "-"
    avg_ppg = f"{played['team_score'].mean():.1f}" if not played.empty else "-"
    avg_opp_ppg = f"{played['opponent_score'].mean():.1f}" if not played.empty else "-"

    # Streak
    _t_streak_count = 0
    _t_streak_type = ""
    for _out in played["outcome"].iloc[::-1]:
        if _t_streak_count == 0:
            _t_streak_type = _out
            _t_streak_count = 1
        elif _out == _t_streak_type:
            _t_streak_count += 1
        else:
            break
    _t_streak_label = "W" if _t_streak_type == "W" else "L"
    _t_streak_str = f"{_t_streak_count}{_t_streak_label}" if _t_streak_count > 1 else ""
    _t_streak_html = f'<span style="color:#aabbcc;font-size:0.85rem;font-style:italic;margin-left:12px;">{_t_streak_str} streak</span>' if _t_streak_str else ""

    _team_banner = f"""<div style="background:#1a1a2e;border-radius:10px;padding:22px 32px;margin-bottom:1.25rem;display:flex;align-items:center;justify-content:space-between;">
        <div style="display:flex;align-items:center;gap:20px;">
            {_team_logo_html}
            <div>
                <div style="color:#ffffff;font-family:Montserrat,sans-serif;font-weight:800;font-size:1.6rem;letter-spacing:0.5px;">UW-WHITEWATER</div>
                <div style="color:#9DAAAC;font-size:1.0rem;margin-top:4px;">{html.escape(get_season_label(schedule))}</div>
            </div>
        </div>
        <div style="display:flex;gap:32px;align-items:center;">
            <div style="text-align:center;">
                <div style="color:#9DAAAC;font-size:0.75rem;text-transform:uppercase;letter-spacing:1px;">Record</div>
                <div style="color:#ffffff;font-size:1.5rem;font-weight:700;">{wins}-{losses}</div>
            </div>
            <div style="text-align:center;">
                <div style="color:#9DAAAC;font-size:0.75rem;text-transform:uppercase;letter-spacing:1px;">PPG</div>
                <div style="color:#ffffff;font-size:1.5rem;font-weight:700;">{avg_ppg}</div>
            </div>
            <div style="text-align:center;">
                <div style="color:#9DAAAC;font-size:0.75rem;text-transform:uppercase;letter-spacing:1px;">Opp PPG</div>
                <div style="color:#ffffff;font-size:1.5rem;font-weight:700;">{avg_opp_ppg}</div>
            </div>
            <div style="text-align:center;">
                <div style="color:#9DAAAC;font-size:0.75rem;text-transform:uppercase;letter-spacing:1px;">Avg Margin</div>
                <div style="color:#ffffff;font-size:1.5rem;font-weight:700;">{avg_margin}</div>
            </div>
            <div style="text-align:center;">
                <div style="color:#9DAAAC;font-size:0.75rem;text-transform:uppercase;letter-spacing:1px;">Streak</div>
                <div style="color:#ffffff;font-size:1.5rem;font-weight:700;">{_t_streak_str if _t_streak_str else "-"}</div>
            </div>
        </div>
    </div>"""
    st.markdown(_team_banner, unsafe_allow_html=True)

    # --- SEASON PROJECTION ACCURACY ---
    try:
        _proj_box_team = load_table("uww_projected_box_score")
        _pbp_box_team = load_table("uww_pbp_box_score")
        _uww_box_team = _pbp_box_team[_pbp_box_team["team"] == "UW-Whitewater"].copy()
        if not _proj_box_team.empty and not _uww_box_team.empty:
            _proj_box_team["_jk"] = _proj_box_team["PLAYER"].str.strip().str.lower()
            _uww_box_team["_jk"] = _uww_box_team["player"].str.strip().str.lower()
            # Aggregate actuals across all games per player
            _act_agg = _uww_box_team.groupby("_jk").agg(
                act_PTS=("PTS", "sum"), act_REB=("REB", "sum"), act_AST=("AST", "sum"), games=("opponent", "nunique")
            ).reset_index()
            _proj_merged = _proj_box_team.merge(_act_agg, on="_jk", how="inner")
            if not _proj_merged.empty:
                # Multiply projections by number of games each player appeared in
                _proj_merged["proj_PTS_total"] = _proj_merged["projected_PTS"] * _proj_merged["games"]
                _proj_merged["proj_REB_total"] = _proj_merged["projected_REB"] * _proj_merged["games"]
                _proj_merged["proj_AST_total"] = _proj_merged["projected_AST"] * _proj_merged["games"]

                st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">SEASON PROJECTION ACCURACY</div></div>', unsafe_allow_html=True)
                st.caption("Comparing pre-game projected stats (per game x games played) vs actual season totals")

                _t_proj_pts = _proj_merged["proj_PTS_total"].sum()
                _t_act_pts = _proj_merged["act_PTS"].sum()
                _t_proj_reb = _proj_merged["proj_REB_total"].sum()
                _t_act_reb = _proj_merged["act_REB"].sum()
                _t_proj_ast = _proj_merged["proj_AST_total"].sum()
                _t_act_ast = _proj_merged["act_AST"].sum()

                _tm1, _tm2, _tm3, _tm4 = st.columns(4)
                _tm1.metric("Projected PTS", f"{int(_t_proj_pts)}", delta=f"{int(_t_act_pts - _t_proj_pts):+d} actual")
                _tm2.metric("Projected REB", f"{int(_t_proj_reb)}", delta=f"{int(_t_act_reb - _t_proj_reb):+d} actual")
                _tm3.metric("Projected AST", f"{int(_t_proj_ast)}", delta=f"{int(_t_act_ast - _t_proj_ast):+d} actual")
                _accuracy = (1 - abs(_t_act_pts - _t_proj_pts) / max(_t_proj_pts, 1)) * 100
                _tm4.metric("PTS Accuracy", f"{_accuracy:.0f}%")

                # Per-player accuracy table
                _pa_rows = []
                for _, _r in _proj_merged.iterrows():
                    _pa_rows.append({
                        "Player": _r["PLAYER"],
                        "Games": int(_r["games"]),
                        "Proj PTS": int(_r["proj_PTS_total"]),
                        "Act PTS": int(_r["act_PTS"]),
                        "PTS Diff": int(_r["act_PTS"] - _r["proj_PTS_total"]),
                        "Proj REB": int(_r["proj_REB_total"]),
                        "Act REB": int(_r["act_REB"]),
                        "REB Diff": int(_r["act_REB"] - _r["proj_REB_total"]),
                        "Proj AST": int(_r["proj_AST_total"]),
                        "Act AST": int(_r["act_AST"]),
                        "AST Diff": int(_r["act_AST"] - _r["proj_AST_total"]),
                    })
                _pa_df = pd.DataFrame(_pa_rows).sort_values("Act PTS", ascending=False)
                with st.expander("Player-level projection accuracy", expanded=False):
                    def _color_diff_team(val):
                        if isinstance(val, (int, float)):
                            if val > 0:
                                return "color: #2e7d32; font-weight: 600;"
                            elif val < 0:
                                return "color: #c62828; font-weight: 600;"
                        return ""
                    _diff_cols_t = ["PTS Diff", "REB Diff", "AST Diff"]
                    _styled_t = style_map(_pa_df.style, _color_diff_team, subset=_diff_cols_t)
                    st.dataframe(_styled_t, hide_index=True, use_container_width=True)
    except Exception as _e:
        report_section_error("Season projection accuracy", _e)
    flags = load_table("uww_coaching_flags")
    if not flags.empty:
        # Team-level aggregates
        total_flags = len(flags)
        sentiment_counts = flags["sentiment"].value_counts()
        pos = int(sentiment_counts.get("Positive", 0))
        neg = int(sentiment_counts.get("Negative", 0))
        neu = int(sentiment_counts.get("Neutral", 0))

        @st.dialog("Coaching Flags", width="large")
        def _show_sentiment_flags(sentiment_filter):
            filtered = flags if sentiment_filter == "All" else flags[flags["sentiment"] == sentiment_filter]
            title = f"All Flags ({len(filtered)})" if sentiment_filter == "All" else f"{sentiment_filter} Flags ({len(filtered)})"
            st.markdown(f"### {title}")
            for _, f in filtered.iterrows():
                s_icon = ":white_check_mark:" if f["sentiment"] == "Positive" else (":warning:" if f["sentiment"] == "Negative" else ":grey_question:")
                st.markdown(f"{s_icon} **{f['flag']}** — {f['player']}")
                st.markdown(f"_{f['evidence']}_")
                if pd.notna(f.get("recommendation")) and str(f["recommendation"]).strip():
                    st.caption(f"Recommendation: {f['recommendation']}")
                st.markdown("---")

        f_col1, f_col2, f_col3, f_col4 = st.columns(4)
        with f_col1:
            st.metric("Total Flags", total_flags)
            if st.button("View All", key="cf_kpi_all"):
                _show_sentiment_flags("All")
        with f_col2:
            st.metric("Positive", pos)
            if pos > 0 and st.button("View", key="cf_kpi_pos"):
                _show_sentiment_flags("Positive")
        with f_col3:
            st.metric("Negative", neg)
            if neg > 0 and st.button("View", key="cf_kpi_neg"):
                _show_sentiment_flags("Negative")
        with f_col4:
            st.metric("Neutral", neu)
            if neu > 0 and st.button("View", key="cf_kpi_neu"):
                _show_sentiment_flags("Neutral")

        # Breakdown by category with clickable dialog
        cat_summary = flags.groupby(["category", "sentiment"]).size().unstack(fill_value=0).reset_index()
        for col in ["Positive", "Negative", "Neutral"]:
            if col not in cat_summary.columns:
                cat_summary[col] = 0
        cat_summary["Total"] = cat_summary["Positive"] + cat_summary["Negative"] + cat_summary["Neutral"]
        cat_summary = cat_summary.sort_values("Total", ascending=False)
        @st.dialog("Coaching Flags Detail", width="large")
        def _show_category_flags(cat_name, sentiment_filter):
            cat_flags = flags[flags["category"] == cat_name]
            if sentiment_filter != "All":
                cat_flags = cat_flags[cat_flags["sentiment"] == sentiment_filter]
            st.markdown(f"### {cat_name}")
            if sentiment_filter != "All":
                st.caption(f"Showing: {sentiment_filter} flags")
            for _, f in cat_flags.iterrows():
                sentiment_icon = ":white_check_mark:" if f["sentiment"] == "Positive" else (":warning:" if f["sentiment"] == "Negative" else ":grey_question:")
                st.markdown(f"{sentiment_icon} **{f['flag']}** — {f['player']}")
                st.markdown(f"_{f['evidence']}_")
                if pd.notna(f.get("recommendation")) and str(f["recommendation"]).strip():
                    st.caption(f"Recommendation: {f['recommendation']}")
                st.markdown("---")

        # Build hover tooltips per category+sentiment
        def _build_tooltip(cat_name, sentiment):
            subset = flags[(flags["category"] == cat_name) & (flags["sentiment"] == sentiment)] if sentiment != "All" else flags[flags["category"] == cat_name]
            if subset.empty:
                return ""
            lines = []
            for _, f in subset.iterrows():
                line = f"{f['player']}: {f['flag']}"
                if pd.notna(f.get("evidence")) and str(f["evidence"]).strip():
                    line += f" — {f['evidence'][:80]}"
                lines.append(line)
            return html.escape("\n".join(lines))

        # Polished HTML table with hover tooltips
        cell_style = "padding:10px 16px;text-align:center;cursor:help;"
        table_rows_html = ""
        for i, (_, row) in enumerate(cat_summary.iterrows()):
            cat_name = row["category"]
            p_val = int(row["Positive"])
            n_val = int(row["Negative"])
            nu_val = int(row["Neutral"])
            t_val = int(row["Total"])
            bg = "#faf8fc" if i % 2 == 0 else "#ffffff"
            # Tooltips
            p_tip = _build_tooltip(cat_name, "Positive")
            n_tip = _build_tooltip(cat_name, "Negative")
            nu_tip = _build_tooltip(cat_name, "Neutral")
            t_tip = _build_tooltip(cat_name, "All")
            # Cells
            if p_val > 0:
                p_td = f'<td title="{p_tip}" style="{cell_style}color:#2e7d32;font-weight:700;">{p_val}</td>'
            else:
                p_td = f'<td style="{cell_style}color:#ddd;">0</td>'
            if n_val > 0:
                n_td = f'<td title="{n_tip}" style="{cell_style}color:#c62828;font-weight:700;">{n_val}</td>'
            else:
                n_td = f'<td style="{cell_style}color:#ddd;">0</td>'
            if nu_val > 0:
                nu_td = f'<td title="{nu_tip}" style="{cell_style}color:#f57c00;font-weight:700;">{nu_val}</td>'
            else:
                nu_td = f'<td style="{cell_style}color:#ddd;">0</td>'
            t_td = f'<td title="{t_tip}" style="{cell_style}font-weight:700;color:#4E2A84;">{t_val}</td>'
            cat_tip = _build_tooltip(cat_name, "All")
            table_rows_html += (
                f'<tr style="background:{bg};" title="{cat_tip}">'
                f'<td style="padding:10px 16px;font-size:0.9rem;cursor:help;" title="{cat_tip}">{html.escape(cat_name)}</td>'
                f"{p_td}{n_td}{nu_td}{t_td}</tr>"
            )

        st.markdown(f"""
        <table style="width:100%;border-collapse:collapse;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);margin:0.5rem 0 1rem 0;">
        <thead>
            <tr style="background:#4E2A84;">
                <th style="padding:12px 16px;text-align:left;color:#fff;font-size:0.85rem;font-weight:600;">Category</th>
                <th style="padding:12px 16px;text-align:center;color:#a5d6a7;font-size:0.85rem;font-weight:600;">Positive</th>
                <th style="padding:12px 16px;text-align:center;color:#ef9a9a;font-size:0.85rem;font-weight:600;">Negative</th>
                <th style="padding:12px 16px;text-align:center;color:#ffe0b2;font-size:0.85rem;font-weight:600;">Neutral</th>
                <th style="padding:12px 16px;text-align:center;color:#fff;font-size:0.85rem;font-weight:600;">Total</th>
            </tr>
        </thead>
        <tbody>{table_rows_html}</tbody>
        </table>
        <p style="font-size:0.75rem;color:#888;margin-top:4px;">Hover any cell to see flag details.</p>
        """, unsafe_allow_html=True)

    else:
        st.info("No coaching flags data available yet.")

    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">HOME / AWAY / NEUTRAL SPLITS</div></div>', unsafe_allow_html=True)
    split_summary = played.groupby(["location", "outcome"]).size().unstack(fill_value=0).reset_index()
    for col in ["W", "L"]:
        if col not in split_summary.columns:
            split_summary[col] = 0
    split_summary["games"] = split_summary["W"] + split_summary["L"]

    # Styled split cards
    _split_cols = st.columns(len(split_summary))
    for _si, (_, _sr) in enumerate(split_summary.iterrows()):
        with _split_cols[_si]:
            _loc = _sr["location"]
            _w = int(_sr["W"])
            _l = int(_sr["L"])
            _g = int(_sr["games"])
            _wp = f"{(_w/_g*100):.0f}%" if _g > 0 else "-"
            _loc_icon = "🏠" if "home" in str(_loc).lower() else ("✈️" if "away" in str(_loc).lower() else "⚖️")
            _margin_sub = played[played["location"] == _loc]["point_margin"].mean()
            _margin_str = f"{_margin_sub:+.1f}" if not played[played["location"] == _loc].empty else "-"
            st.markdown(
                f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:16px;text-align:center;background:#faf8fc;">'
                f'<div style="font-size:1.5rem;margin-bottom:4px;">{_loc_icon}</div>'
                f'<div style="font-weight:700;font-size:1.0rem;color:#4E2A84;">{_loc}</div>'
                f'<div style="font-size:1.8rem;font-weight:800;color:#4E2A84;margin:6px 0;">{_w}-{_l}</div>'
                f'<div style="font-size:0.85rem;color:#666;">Win%: {_wp}</div>'
                f'<div style="font-size:0.85rem;color:#666;">Avg margin: {_margin_str}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">SEASON-WIDE 5-MAN LINEUP ANALYSIS</div></div>', unsafe_allow_html=True)
    stints = load_table("uww_lineup_stints")
    season_lineups = (
        stints.groupby("uww_lineup")
        .agg(
            total_minutes=("stint_minutes", "sum"),
            net_margin=("uww_margin_change", "sum"),
            games=("game_date", "nunique"),
            stints=("stint_num", "count"),
        )
        .reset_index()
    )
    season_lineups["margin_per_min"] = (season_lineups["net_margin"] / season_lineups["total_minutes"]).round(2)

    meaningful = season_lineups[season_lineups["total_minutes"] >= 2.0]

    # Best / Worst lineups with styled cards
    def _last_names_card(lineup_str):
        return ", ".join(surname(n) for n in str(lineup_str).split(",") if n.strip())

    _best_5 = meaningful.sort_values("margin_per_min", ascending=False).head(5)
    _worst_5 = meaningful.sort_values("margin_per_min", ascending=True).head(5)

    _lu_c1, _lu_c2 = st.columns(2)
    with _lu_c1:
        st.markdown('<div style="font-weight:700;font-size:0.95rem;color:#2e7d32;margin-bottom:6px;">Best Lineups (by margin/min)</div>', unsafe_allow_html=True)
        for _, _lr in _best_5.iterrows():
            _ln = _last_names_card(_lr["uww_lineup"])
            st.markdown(
                f'<div style="border-left:3px solid #4caf50;padding:6px 12px;margin:4px 0;background:#f9fdf9;border-radius:4px;">'
                f'<div style="font-size:0.85rem;"><strong style="color:#2e7d32;">{_lr["margin_per_min"]:+.2f}</strong>/min'
                f' <span style="color:#888;">({_lr["total_minutes"]:.1f} min, {int(_lr["games"])} games)</span></div>'
                f'<div style="font-size:0.8rem;color:#333;">{html.escape(_ln)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
    with _lu_c2:
        st.markdown('<div style="font-weight:700;font-size:0.95rem;color:#c62828;margin-bottom:6px;">Worst Lineups (by margin/min)</div>', unsafe_allow_html=True)
        for _, _lr in _worst_5.iterrows():
            _ln = _last_names_card(_lr["uww_lineup"])
            st.markdown(
                f'<div style="border-left:3px solid #ef5350;padding:6px 12px;margin:4px 0;background:#fffafa;border-radius:4px;">'
                f'<div style="font-size:0.85rem;"><strong style="color:#c62828;">{_lr["margin_per_min"]:+.2f}</strong>/min'
                f' <span style="color:#888;">({_lr["total_minutes"]:.1f} min, {int(_lr["games"])} games)</span></div>'
                f'<div style="font-size:0.8rem;color:#333;">{html.escape(_ln)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # Full lineup table in expander
    with st.expander("All lineups by minutes played", expanded=False):
        st.dataframe(
            season_lineups.sort_values("total_minutes", ascending=False).head(20),
            hide_index=True, use_container_width=True,
        )
    if not meaningful.empty:
        st.bar_chart(meaningful.sort_values("margin_per_min", ascending=False).head(15).set_index("uww_lineup")["margin_per_min"])

    # --- SEASON-WIDE 3-MAN COMBINATION ANALYSIS --- (same shape as the 5-man section above, but for
    # 3-man combos -- the UWW season-wide half of the data that used to only appear in the Upcoming
    # Opponent page's Stats & Analysis "TOP 3-MAN COMBINATIONS" card, which no longer renders that card)
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">SEASON-WIDE 3-MAN COMBINATION ANALYSIS</div></div>', unsafe_allow_html=True)
    from itertools import combinations as _team_3man_combos
    _team_3man_records = []
    for _, _t_stint in stints.iterrows():
        _t_players = sorted([p.strip() for p in str(_t_stint["uww_lineup"]).split(",")])
        for _combo in _team_3man_combos(_t_players, 3):
            _team_3man_records.append({
                "lineup": ", ".join(_combo),
                "stint_minutes": _t_stint["stint_minutes"],
                "uww_margin_change": _t_stint["uww_margin_change"],
                "game_date": _t_stint.get("game_date"),
            })
    if _team_3man_records:
        _team_3man_df = pd.DataFrame(_team_3man_records)
        season_3man = _team_3man_df.groupby("lineup").agg(
            total_minutes=("stint_minutes", "sum"),
            net_margin=("uww_margin_change", "sum"),
            games=("game_date", "nunique"),
        ).reset_index()
        season_3man["margin_per_min"] = (season_3man["net_margin"] / season_3man["total_minutes"]).round(2)
        meaningful_3 = season_3man[season_3man["total_minutes"] >= 2.0]

        _best_3man = meaningful_3.sort_values("margin_per_min", ascending=False).head(5)
        _worst_3man = meaningful_3.sort_values("margin_per_min", ascending=True).head(5)

        _lu3_c1, _lu3_c2 = st.columns(2)
        with _lu3_c1:
            st.markdown('<div style="font-weight:700;font-size:0.95rem;color:#2e7d32;margin-bottom:6px;">Best Combos (by margin/min)</div>', unsafe_allow_html=True)
            for _, _lr in _best_3man.iterrows():
                _ln = _last_names_card(_lr["lineup"])
                st.markdown(
                    f'<div style="border-left:3px solid #4caf50;padding:6px 12px;margin:4px 0;background:#f9fdf9;border-radius:4px;">'
                    f'<div style="font-size:0.85rem;"><strong style="color:#2e7d32;">{_lr["margin_per_min"]:+.2f}</strong>/min'
                    f' <span style="color:#888;">({_lr["total_minutes"]:.1f} min, {int(_lr["games"])} games)</span></div>'
                    f'<div style="font-size:0.8rem;color:#333;">{html.escape(_ln)}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        with _lu3_c2:
            st.markdown('<div style="font-weight:700;font-size:0.95rem;color:#c62828;margin-bottom:6px;">Worst Combos (by margin/min)</div>', unsafe_allow_html=True)
            for _, _lr in _worst_3man.iterrows():
                _ln = _last_names_card(_lr["lineup"])
                st.markdown(
                    f'<div style="border-left:3px solid #ef5350;padding:6px 12px;margin:4px 0;background:#fffafa;border-radius:4px;">'
                    f'<div style="font-size:0.85rem;"><strong style="color:#c62828;">{_lr["margin_per_min"]:+.2f}</strong>/min'
                    f' <span style="color:#888;">({_lr["total_minutes"]:.1f} min, {int(_lr["games"])} games)</span></div>'
                    f'<div style="font-size:0.8rem;color:#333;">{html.escape(_ln)}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        with st.expander("All 3-man combinations by minutes played", expanded=False):
            st.dataframe(
                season_3man.sort_values("total_minutes", ascending=False).head(20),
                hide_index=True, use_container_width=True,
            )
        if not meaningful_3.empty:
            st.bar_chart(meaningful_3.sort_values("margin_per_min", ascending=False).head(15).set_index("lineup")["margin_per_min"])
    else:
        st.info("No 3-man combination data available yet.")

    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">KEYS-TO-VICTORY WIN/LOSS SPLITS</div></div>', unsafe_allow_html=True)
    ktv = load_table("uww_ktv_splits")
    if not ktv.empty:
        st.dataframe(ktv.sort_values("games", ascending=False), hide_index=True, use_container_width=True)
        st.bar_chart(ktv.set_index("category")["win_pct"])
        st.caption("Small sample -- grows automatically as more scout reports are added to the schedule.")
    else:
        st.info("No Keys-to-Victory splits available yet.")

    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">PLAY-BY-PLAY</div></div>', unsafe_allow_html=True)
    pbp = load_table("uww_pbp_events")
    if pbp.empty:
        st.info("No play-by-play data available yet.")
    else:
        # Parse play type and outcome from video_description
        pbp["play_type"] = pbp["video_description"].str.split(">").str[1].str.strip()
        pbp["shot_outcome"] = pbp["video_description"].str.extract(r"(Make \d+ Pts|Miss \d+ Pts|Turnover|Foul)", expand=False)

        # Row 1: Core filters
        pbp_opponents = sorted(pbp["opponent"].dropna().unique().tolist())
        tr1c1, tr1c2, tr1c3, tr1c4 = st.columns(4)
        with tr1c1:
            game_filter = st.selectbox("Game", ["All Games"] + pbp_opponents, key="team_pbp_game")
        with tr1c2:
            team_pbp_team = st.selectbox(
                "Team", ["All"] + sorted(pbp["team"].dropna().unique().tolist()),
                key="team_pbp_team"
            )
        with tr1c3:
            team_pbp_event = st.selectbox(
                "Event type", ["All"] + sorted(pbp["event_type"].dropna().unique().tolist()),
                key="team_pbp_event_type"
            )
        with tr1c4:
            team_pbp_player = st.text_input("Player", "", key="team_pbp_player", placeholder="Filter by player...")

        # Row 2: Video description filters
        tr2c1, tr2c2, tr2c3, tr2c4 = st.columns(4)
        with tr2c1:
            team_play_types = sorted(pbp["play_type"].dropna().unique().tolist())
            team_pbp_playtype = st.selectbox("Play type", ["All"] + team_play_types, key="team_pbp_playtype")
        with tr2c2:
            team_outcomes = sorted(pbp["shot_outcome"].dropna().unique().tolist())
            team_pbp_outcome = st.selectbox("Outcome", ["All"] + team_outcomes, key="team_pbp_outcome")
        with tr2c3:
            team_period = st.selectbox(
                "Period", ["All"] + sorted(pbp["period"].dropna().unique().tolist()),
                key="team_pbp_period"
            )
        with tr2c4:
            team_pbp_video = st.text_input("Video description search", "", key="team_pbp_video", placeholder="e.g. P&R, ISO, 3pt...")

        # Toggle for video-tagged only
        team_video_only = st.checkbox("Show only video-tagged plays", value=False, key="team_pbp_vidonly")
        team_notes_only = st.checkbox("Show only plays with a coach note", value=False, key="team_pbp_notesonly") if "coach_note" in pbp.columns else False

        # Apply filters
        filtered = pbp.copy()
        if game_filter != "All Games":
            filtered = filtered[filtered["opponent"] == game_filter]
        if team_pbp_team != "All":
            filtered = filtered[filtered["team"] == team_pbp_team]
        if team_pbp_event != "All":
            filtered = filtered[filtered["event_type"] == team_pbp_event]
        if team_pbp_player.strip():
            filtered = filtered[filtered["player"].str.contains(team_pbp_player.strip(), case=False, na=False)]
        if team_pbp_playtype != "All":
            filtered = filtered[filtered["play_type"] == team_pbp_playtype]
        if team_pbp_outcome != "All":
            filtered = filtered[filtered["shot_outcome"] == team_pbp_outcome]
        if team_period != "All":
            filtered = filtered[filtered["period"] == team_period]
        if team_pbp_video.strip():
            filtered = filtered[filtered["video_description"].str.contains(team_pbp_video.strip(), case=False, na=False)]
        if team_video_only:
            filtered = filtered[filtered["video_description"].notna()]
        if team_notes_only:
            filtered = filtered[filtered["coach_note"].notna()]

        filtered = filtered.sort_values("event_order")

        # KPI metrics
        tkpi1, tkpi2, tkpi3, tkpi4, tkpi5 = st.columns(5)
        tkpi1.metric("Total Events", len(filtered))
        t_makes = filtered[filtered["event_type"].str.contains("made", case=False, na=False)]
        tkpi2.metric("Makes", len(t_makes))
        t_misses = filtered[filtered["event_type"].str.contains("missed", case=False, na=False)]
        tkpi3.metric("Misses", len(t_misses))
        t_turnovers = filtered[filtered["event_type"].str.contains("turnover", case=False, na=False)]
        tkpi4.metric("Turnovers", len(t_turnovers))
        t_players = filtered["player"].dropna().nunique()
        tkpi5.metric("Players", t_players)

        display_cols = [c for c in ["opponent", "period", "time_remaining", "team", "player", "event_type",
                                     "video_description", "coach_note", "uww_score", "opp_score"]
                         if c in filtered.columns]
        st.dataframe(
            filtered[display_cols].rename(columns={"coach_note": "Coach Note", "video_description": "Video Tag"}),
            hide_index=True, use_container_width=True, height=400,
        )


    # ==================== SITUATIONAL SPLITS ====================
    stints = load_table("uww_lineup_stints")
    if not stints.empty:
        def _last_names_team(lineup_str):
            return ", ".join(surname(n) for n in str(lineup_str).split(",") if n.strip())

        # Map stints to W/L outcomes from the schedule, per GAME -- an opponent UWW split a home-and-home
        # with has one result per meeting, not one result overall.
        stints_split = stints.copy()
        if "game_date" in stints_split.columns:
            stints_split["outcome"] = stints_split["game_date"].astype(str).str[:10].map(get_game_outcomes(schedule))
        else:
            stints_split["outcome"] = stints_split["opponent"].map(get_opponent_outcomes(schedule, stints["opponent"].unique()))

        split_html = ""
        for outcome_label, outcome_val in [("Wins", "W"), ("Losses", "L")]:
            sub = stints_split[stints_split["outcome"] == outcome_val]
            if sub.empty:
                continue
            sub_agg = sub.groupby("uww_lineup").agg(
                mins=("stint_minutes", "sum"), margin=("uww_margin_change", "sum")
            ).reset_index()
            sub_agg["rate"] = (sub_agg["margin"] / sub_agg["mins"]).round(2)
            top = sub_agg[sub_agg["mins"] >= 2.0].nlargest(3, "rate")
            color = "#2e7d32" if outcome_val == "W" else "#c62828"
            split_html += f'<div style="font-size:0.85rem;color:{color};font-weight:600;margin:6px 0 3px;">In {outcome_label}:</div>'
            for _, r in top.iterrows():
                ln = _last_names_team(r["uww_lineup"])
                split_html += f'<div style="font-size:0.85rem;margin:3px 0;"><strong>{r["rate"]:+.2f}</strong>/min ({r["mins"]:.1f} min) \u2014 {html.escape(ln)}</div>'

        if split_html:
            st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">\U0001F4CA SITUATIONAL SPLITS</div></div>', unsafe_allow_html=True)
            st.markdown(split_html, unsafe_allow_html=True)

    # ==================== CLUTCH PERFORMANCE ====================
    section_header("\U0001F3C0 CLUTCH PERFORMANCE", (
            "Last 5 minutes of the 2nd half or any overtime, with the score within 8 points. This is computed "
            "once by the parser (not recomputed here) and grows automatically as closer games are added."
        ))
    clutch = load_table("uww_clutch_events")
    if clutch.empty:
        st.info("No clutch-time stretches yet -- no game this season has been within 8 points in the last 5 minutes of the 2nd half or later.")
    else:
        clutch_scoring = clutch[clutch["event_type"].isin(["made_shot", "free_throw_made"])].copy()
        clutch_scoring["points"] = clutch_scoring.apply(
            lambda r: int(r["shot_type"]) if (r["event_type"] == "made_shot" and pd.notna(r.get("shot_type"))) else 1, axis=1
        )
        by_team = clutch_scoring.groupby("team")["points"].sum().reset_index().rename(columns={"team": "Team", "points": "Clutch Points"})
        uww_clutch_pts = int(by_team.loc[by_team["Team"] == "UW-Whitewater", "Clutch Points"].sum())
        opp_clutch_pts = int(by_team.loc[by_team["Team"] != "UW-Whitewater", "Clutch Points"].sum())
        ccol1, ccol2, ccol3 = st.columns(3)
        ccol1.metric("UWW clutch points", uww_clutch_pts)
        ccol2.metric("Opponent clutch points", opp_clutch_pts)
        ccol3.metric("Clutch stretches logged", clutch["opponent"].nunique())

        uww_clutch_players = clutch_scoring[clutch_scoring["team"] == "UW-Whitewater"].groupby("player")["points"].sum().reset_index().sort_values("points", ascending=False)
        if not uww_clutch_players.empty:
            st.markdown("**UWW clutch scorers**")
            st.dataframe(uww_clutch_players.rename(columns={"player": "Player", "points": "Clutch Points"}), hide_index=True, use_container_width=True)

        with st.expander("Clutch-time event log", expanded=False):
            _clutch_display_cols = [c for c in ["opponent", "period", "time_remaining", "team", "player", "event_type", "raw_text", "uww_score", "opp_score"] if c in clutch.columns]
            st.dataframe(clutch[_clutch_display_cols].sort_values(["opponent", "period"]), hide_index=True, use_container_width=True, height=300)

    # ==================== SCORING RUNS & LARGEST LEADS ====================
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">\U0001F4C8 SCORING RUNS &amp; LARGEST LEADS</div></div>', unsafe_allow_html=True)
    runs = load_table("uww_scoring_runs")
    if runs.empty:
        st.info("No scoring-run data available yet.")
    else:
        runs_display = runs[["opponent", "uww_biggest_run", "opponent_biggest_run", "uww_largest_lead", "opponent_largest_lead"]].rename(columns={
            "opponent": "Opponent", "uww_biggest_run": "UWW Biggest Run", "opponent_biggest_run": "Opp. Biggest Run",
            "uww_largest_lead": "UWW Largest Lead", "opponent_largest_lead": "Opp. Largest Lead",
        })
        st.dataframe(runs_display, hide_index=True, use_container_width=True)
        with st.expander("Which lineups were on the floor for each biggest run", expanded=False):
            for _, r in runs.iterrows():
                st.markdown(f"**{r['opponent']}** — UWW's biggest run: {r['uww_biggest_run']} pts (UWW: {r.get('uww_run_uww_lineup', '-')} | Opp: {r.get('uww_run_opp_lineup', '-')})")
                st.caption(f"{r['opponent']}'s biggest run: {r['opponent_biggest_run']} pts (UWW: {r.get('opp_run_uww_lineup', '-')} | Opp: {r.get('opp_run_opp_lineup', '-')})")


# --------------------------------------------------------------------------------------------------------------
# Section 4: Players
# --------------------------------------------------------------------------------------------------------------
def render_players():
    tab_uww, tab_opponents = st.tabs(["UWW Roster", "Opponent Scouting"])

    with tab_uww:
        flags = load_table("uww_coaching_flags")
        player_list = sorted(flags["player"].dropna().unique())

        # Player picture lookup helper
        pic_dir = os.path.join(DATA_DIR, "uww_player_pictures")
        def get_player_pic(player_name):
            """Find a matching picture for a player by scanning filenames."""
            if not os.path.isdir(pic_dir):
                return None
            name_lower = player_name.lower().replace(".", "").strip()
            for suffix in [" jr", " sr", " ii", " iii", " iv"]:
                if name_lower.endswith(suffix):
                    name_lower = name_lower[:-len(suffix)].strip()
            parts = [p for p in name_lower.split() if p]
            if not parts:
                return None
            for f in os.listdir(pic_dir):
                f_lower = f.lower()
                f_name = f_lower.replace("uww_", "").split(".")[0]
                score = 0
                for part in parts:
                    for fp in f_name.split("_"):
                        if len(part) >= 2 and len(fp) >= 2:
                            if part in fp or fp in part or part[:2] == fp[:2]:
                                score += 1
                                break
                if score >= 2:
                    return os.path.join(pic_dir, f)
            return None

        # Dialog for player detail — triggered via session state for reliability
        @st.dialog("Player Detail", width="large")
        def _show_uww_player_detail(player_name):
            alias_key = KNOWN_NAME_ALIASES.get(player_name.strip().lower(), player_name)
            player_flags = flags[flags["player"].isin([player_name, alias_key])]
            positive_flags = player_flags[player_flags["sentiment"] == "Positive"]
            negative_flags = player_flags[player_flags["sentiment"] == "Negative"]

            pic = get_player_pic(player_name)

            # --- Broadcast-style player header ---
            _p_header_cols = st.columns([1, 4])
            with _p_header_cols[0]:
                if pic and os.path.exists(pic):
                    st.image(pic, width=140)
                else:
                    st.markdown('<div style="width:140px;height:140px;background:#e8e0f0;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:3rem;">🏀</div>', unsafe_allow_html=True)
            with _p_header_cols[1]:
                st.markdown(f'<div style="font-family:Montserrat,sans-serif;font-weight:800;font-size:1.6rem;color:#4E2A84;">{player_name}</div>', unsafe_allow_html=True)

                # Load season stats for this player
                try:
                    _p_season = load_table("uww_season_stats")
                    _p_match = _p_season[_p_season["PLAYER"].str.strip().str.lower().isin([player_name.strip().lower(), alias_key.strip().lower() if alias_key != player_name else ""])]
                    if not _p_match.empty:
                        _ps = _p_match.iloc[0]
                        _stat_parts = []
                        for _col, _lbl in [("PTS", "PPG"), ("REB", "RPG"), ("AST", "APG"), ("MIN", "MPG")]:
                            _val = safe_float(_ps.get(_col)) if _col in _ps.index else None
                            if _val is not None:
                                _stat_parts.append(f'<span style="margin-right:20px;"><span style="color:#666;font-size:0.8rem;">{_lbl}</span> <span style="font-weight:700;font-size:1.1rem;color:#4E2A84;">{_val:.1f}</span></span>')
                        if _stat_parts:
                            st.markdown(f'<div style="margin-top:8px;">{"".join(_stat_parts)}</div>', unsafe_allow_html=True)
                        # Additional stats row
                        _stat_parts2 = []
                        for _col, _lbl in [("FG%", "FG%"), ("3P%", "3P%"), ("FT%", "FT%"), ("STL", "SPG"), ("TO", "TOPG")]:
                            _val = safe_float(_ps.get(_col)) if _col in _ps.index else None
                            if _val is not None:
                                if "%" in _col:
                                    _stat_parts2.append(f'<span style="margin-right:20px;"><span style="color:#666;font-size:0.75rem;">{_lbl}</span> <span style="font-weight:600;font-size:0.95rem;">{_val:.1f}%</span></span>')
                                else:
                                    _stat_parts2.append(f'<span style="margin-right:20px;"><span style="color:#666;font-size:0.75rem;">{_lbl}</span> <span style="font-weight:600;font-size:0.95rem;">{_val:.1f}</span></span>')
                        if _stat_parts2:
                            st.markdown(f'<div style="margin-top:4px;">{"".join(_stat_parts2)}</div>', unsafe_allow_html=True)
                except Exception:
                    pass

            # --- Projected vs Actual Performance ---
            try:
                _p_proj = load_table("uww_projected_box_score")
                _p_box = load_table("uww_pbp_box_score")
                _p_uww_box = _p_box[_p_box["team"] == "UW-Whitewater"].copy()
                _p_proj["_jk"] = _p_proj["PLAYER"].str.strip().str.lower()
                _p_uww_box["_jk"] = _p_uww_box["player"].str.strip().str.lower()
                _p_key = player_name.strip().lower()
                _p_alias_key = alias_key.strip().lower() if alias_key != player_name else ""
                _p_proj_row = _p_proj[_p_proj["_jk"].isin([_p_key, _p_alias_key])]
                _p_actual_games = _p_uww_box[_p_uww_box["_jk"].isin([_p_key, _p_alias_key])]

                if not _p_proj_row.empty and not _p_actual_games.empty:
                    _pr = _p_proj_row.iloc[0]
                    _n_games = len(_p_actual_games)
                    _avg_pts = _p_actual_games["PTS"].mean()
                    _avg_reb = _p_actual_games["REB"].mean()
                    _avg_ast = _p_actual_games["AST"].mean()

                    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:10px 14px;margin:1rem 0 0.5rem;"><div style="font-weight:700;font-size:0.9rem;color:#4E2A84;">PROJECTED vs ACTUAL (per game avg)</div></div>', unsafe_allow_html=True)

                    _pc1, _pc2, _pc3 = st.columns(3)
                    _pts_d = _avg_pts - _pr["projected_PTS"]
                    _reb_d = _avg_reb - _pr["projected_REB"]
                    _ast_d = _avg_ast - _pr["projected_AST"]
                    _pc1.metric("PTS", f"{_pr['projected_PTS']:.0f} → {_avg_pts:.1f}", delta=f"{_pts_d:+.1f}")
                    _pc2.metric("REB", f"{_pr['projected_REB']:.0f} → {_avg_reb:.1f}", delta=f"{_reb_d:+.1f}")
                    _pc3.metric("AST", f"{_pr['projected_AST']:.0f} → {_avg_ast:.1f}", delta=f"{_ast_d:+.1f}")

                    # Per-game breakdown in expander -- ordered by the date the game was played, oldest
                    # first, so the column reads as a season arc. The box-score table's own row order is
                    # whatever the groupby produced (alphabetical by opponent), which made a run of good
                    # or bad games impossible to see.
                    with st.expander(f"Game-by-game breakdown ({_n_games} games)", expanded=False):
                        _gm_src = _p_actual_games.copy()
                        if "game_date" in _gm_src.columns:
                            _gm_src["_sort_date"] = pd.to_datetime(_gm_src["game_date"], errors="coerce")
                            # Rows whose date won't parse sort last rather than silently jumping to the top.
                            _gm_src = _gm_src.sort_values("_sort_date", na_position="last")
                        _gm_rows = []
                        for _, _gr in _gm_src.iterrows():
                            _gm_date = _gr.get("game_date")
                            _gm_rows.append({
                                "Date": (pd.to_datetime(_gm_date, errors="coerce").strftime("%b %d")
                                         if pd.notna(pd.to_datetime(_gm_date, errors="coerce")) else "-"),
                                "Opponent": _gr.get("opponent", "-"),
                                "PTS": int(_gr["PTS"]),
                                "vs Proj": int(_gr["PTS"] - _pr["projected_PTS"]),
                                "REB": int(_gr["REB"]),
                                "AST": int(_gr["AST"]),
                            })
                        _gm_df = pd.DataFrame(_gm_rows)
                        if "game_date" not in _p_actual_games.columns:
                            _gm_df = _gm_df.drop(columns=["Date"])
                        def _cd_player(val):
                            if isinstance(val, (int, float)):
                                if val > 0: return "color: #2e7d32; font-weight: 600;"
                                elif val < 0: return "color: #c62828; font-weight: 600;"
                            return ""
                        st.dataframe(style_map(_gm_df.style, _cd_player, subset=["vs Proj"]), hide_index=True, use_container_width=True)
            except Exception as _e:
                report_section_error("Projected vs. actual performance", _e)

            # --- Coach Notes (offensive clips only -- see the Analytics page's "By Player" caveat: a
            # defensive clip's "player" is the OPPONENT player who acted, not which UWW defender the note is
            # about, so only this player's own offensive clips can be attributed to them specifically) ---
            try:
                _pd_notes = load_table("uww_coach_notes")
                if not _pd_notes.empty and "clip_side" in _pd_notes.columns:
                    _pd_alias = KNOWN_NAME_ALIASES.get(player_name.strip().lower(), player_name)
                    _pd_own_notes = _pd_notes[
                        (_pd_notes["clip_side"] == "Offense")
                        & (_pd_notes["player"].isin([player_name, _pd_alias]))
                    ]
                    if not _pd_own_notes.empty:
                        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:10px 14px;margin:1rem 0 0.5rem;"><div style="font-weight:700;font-size:0.9rem;color:#4E2A84;">COACH NOTES</div></div>', unsafe_allow_html=True)
                        _pd_pos, _pd_neg = 0, 0
                        for _n in _pd_own_notes["coach_note"]:
                            _p, _ng = note_sentiment_counts(_n)
                            _pd_pos += _p
                            _pd_neg += _ng
                        _pdc1, _pdc2, _pdc3 = st.columns(3)
                        _pdc1.metric("Clips", len(_pd_own_notes))
                        _pdc2.metric("Positive flags", _pd_pos)
                        _pdc3.metric("Negative flags", _pd_neg)
                        with st.expander("View notes", expanded=False):
                            for _, _nr in _pd_own_notes.iterrows():
                                # Plain st.markdown (no unsafe_allow_html) already sanitizes stray HTML on its
                                # own -- html.escape()'d text here would incorrectly show literal "&amp;" etc.
                                # for a note containing a plain "&", so this is NOT the same esc()-wrapped
                                # pattern used elsewhere in this file for raw-HTML-div blocks.
                                st.markdown(f"- *{_nr.get('opponent', '')}, {_nr.get('period', '')}:* {_nr['coach_note']}")
            except Exception as _e:
                report_section_error("Coach notes", _e)

            st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:10px 14px;margin:1rem 0 0.5rem;"><div style="font-weight:700;font-size:0.9rem;color:#4E2A84;">COACHING FLAGS</div></div>', unsafe_allow_html=True)

            if player_flags.empty:
                st.info("No coaching flags for this player.")
                return

            col_pos, col_neg = st.columns(2)
            with col_pos:
                st.markdown("**✅ Strengths**")
                if positive_flags.empty:
                    st.caption("No positive flags.")
                else:
                    for idx, (_, f) in enumerate(positive_flags.iterrows()):
                        st.markdown(
                            f'<div style="border-left:3px solid #4caf50;padding:8px 12px;margin:6px 0;background:#f9fdf9;border-radius:4px;">'
                            f'<div style="font-weight:700;font-size:0.88rem;">{esc(f["flag"])}</div>'
                            f'<div style="font-size:0.8rem;color:#555;margin-top:3px;"><em>{esc(f["evidence"])}</em></div>'
                            f'<div style="font-size:0.78rem;color:#1b5e20;margin-top:2px;">{esc(f.get("recommendation", "")) if pd.notna(f.get("recommendation")) else ""}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
            with col_neg:
                st.markdown("**⚠️ Areas to Improve**")
                if negative_flags.empty:
                    st.caption("No negative flags.")
                else:
                    for idx, (_, f) in enumerate(negative_flags.iterrows()):
                        st.markdown(
                            f'<div style="border-left:3px solid #ef5350;padding:8px 12px;margin:6px 0;background:#fffafa;border-radius:4px;">'
                            f'<div style="font-weight:700;font-size:0.88rem;">{esc(f["flag"])}</div>'
                            f'<div style="font-size:0.8rem;color:#555;margin-top:3px;"><em>{esc(f["evidence"])}</em></div>'
                            f'<div style="font-size:0.78rem;color:#b71c1c;margin-top:2px;">{esc(f.get("recommendation", "")) if pd.notna(f.get("recommendation")) else ""}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

        # ==================== ADVANCED STATS LEADERBOARD ====================
        section_header("ADVANCED STATS LEADERBOARD", glossary_help_text(["TS%", "Game Score", "Usage%"]), margin="0.5rem 0 1rem")
        _adv_box = load_table("uww_pbp_box_score")
        _adv_uww_box = _adv_box[_adv_box["team"] == "UW-Whitewater"] if not _adv_box.empty else pd.DataFrame()
        if _adv_uww_box.empty:
            st.caption("Not enough box score data yet for advanced stats.")
        else:
            _team_minutes_total = None  # per-game team minutes (5 players x game minutes) for usage rate
            _season_stats_min = load_table("uww_season_stats")
            _adv_rows = []
            for player_name, p_games in _adv_uww_box.groupby("player"):
                totals = p_games[["PTS", "FGM", "FGA", "FTM", "FTA", "OREB", "DREB", "STL", "AST", "BLK", "PF", "TO"]].sum()
                n_pg = p_games["game_date"].nunique() if "game_date" in p_games.columns else p_games["opponent"].nunique()
                ts_pct = compute_true_shooting(totals["PTS"], totals["FGA"], totals["FTA"])
                avg_game_score = p_games.apply(compute_game_score, axis=1).mean()
                # Usage rate needs the player's own minutes and the team's total minutes over the same games --
                # season_stats' MIN column is already a per-game average (see uww_season_stats), so approximate
                # the player's total minutes as MPG x games played, and team minutes as 5 x 40 x games (a full
                # college game is 40 minutes with 5 players on the floor).
                mpg = None
                if not _season_stats_min.empty and "PLAYER" in _season_stats_min.columns:
                    _match = _season_stats_min[_season_stats_min["PLAYER"].str.strip().str.lower() == str(player_name).strip().lower()]
                    if not _match.empty:
                        mpg = safe_float(_match.iloc[0].get("MIN"))
                player_minutes_total = (mpg * n_pg) if mpg else 0
                team_minutes_total = 5 * 40 * n_pg
                _adv_scope = (_adv_uww_box[_adv_uww_box["game_date"].isin(p_games["game_date"].unique())]
                              if "game_date" in _adv_uww_box.columns
                              else _adv_uww_box[_adv_uww_box["opponent"].isin(p_games["opponent"].unique())])
                usage = compute_usage_rate(totals, player_minutes_total, _adv_scope, team_minutes_total)
                _adv_rows.append({
                    "Player": player_name, "GP": n_pg, "TS%": round(ts_pct, 1),
                    "Game Score": round(avg_game_score, 1), "Usage%": round(usage, 1) if mpg else "-",
                })
            _adv_df = pd.DataFrame(_adv_rows).sort_values("Game Score", ascending=False)
            st.dataframe(_adv_df, hide_index=True, use_container_width=True)
            st.caption("TS% and Game Score are season averages; Usage% needs a recorded MPG and is left blank without one.")

        # Load season stats for card display
        _card_season_stats = load_table("uww_season_stats")
        _card_season_lookup = {}
        if not _card_season_stats.empty:
            for _, _cs in _card_season_stats.iterrows():
                _card_season_lookup[str(_cs["PLAYER"]).strip().lower()] = _cs

        # Render player cards in a 4-per-row grid (wider cards with stats)
        CARDS_PER_ROW = 4
        for row_start in range(0, len(player_list), CARDS_PER_ROW):
            row_players = player_list[row_start:row_start + CARDS_PER_ROW]
            cols = st.columns(CARDS_PER_ROW)
            for col_idx, player_name in enumerate(row_players):
                with cols[col_idx]:
                    with st.container(border=True):
                        pic = get_player_pic(player_name)
                        if pic and os.path.exists(pic):
                            st.image(pic, width=90)
                        else:
                            st.markdown('<div style="width:90px;height:90px;background:#e8e0f0;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:2rem;margin:0 auto;">🏀</div>', unsafe_allow_html=True)
                        alias_key = KNOWN_NAME_ALIASES.get(player_name.strip().lower(), player_name)
                        p_flags = flags[flags["player"].isin([player_name, alias_key])]
                        st.markdown(f"**{player_name}**")

                        # Season stats mini-line
                        _cs_key = player_name.strip().lower()
                        _cs_alt = alias_key.strip().lower() if alias_key != player_name else ""
                        # NOTE: `dict.get(a) or dict.get(b)` is unsafe here -- once .get(a) finds a match it
                        # returns a pandas Series (one row of _card_season_stats), and `or` tries to evaluate
                        # that Series' truthiness, which pandas raises a ValueError on ("truth value of a
                        # Series is ambiguous"). Explicit None-checks avoid ever evaluating a Series as a bool.
                        _cs_row = _card_season_lookup.get(_cs_key)
                        if _cs_row is None and _cs_alt:
                            _cs_row = _card_season_lookup.get(_cs_alt)
                        if _cs_row is not None:
                            _pts_val, _reb_val, _ast_val = safe_float(_cs_row.get('PTS')), safe_float(_cs_row.get('REB')), safe_float(_cs_row.get('AST'))
                            _ppg = f"{_pts_val:.1f}" if _pts_val is not None else "-"
                            _rpg = f"{_reb_val:.1f}" if _reb_val is not None else "-"
                            _apg = f"{_ast_val:.1f}" if _ast_val is not None else "-"
                            st.markdown(
                                f'<div style="font-size:0.78rem;color:#4E2A84;margin:2px 0 4px;">'
                                f'<strong>{_ppg}</strong> pts  <strong>{_rpg}</strong> reb  <strong>{_apg}</strong> ast</div>',
                                unsafe_allow_html=True,
                            )

                        pos_count = len(p_flags[p_flags["sentiment"] == "Positive"])
                        neg_count = len(p_flags[p_flags["sentiment"] == "Negative"])
                        badge_html = ""
                        if pos_count > 0:
                            badge_html += f'<span style="background:#e8f5e9;color:#2e7d32;padding:1px 6px;border-radius:8px;font-size:0.72rem;font-weight:600;margin-right:4px;">✅ {pos_count}</span>'
                        if neg_count > 0:
                            badge_html += f'<span style="background:#fbe9e7;color:#c62828;padding:1px 6px;border-radius:8px;font-size:0.72rem;font-weight:600;">⚠️ {neg_count}</span>'
                        if badge_html:
                            st.markdown(badge_html, unsafe_allow_html=True)
                        if st.button("Details", key=f"uww_card_{player_name}", use_container_width=True):
                            st.session_state["_uww_detail_player"] = player_name

        # Open dialog outside the loop for reliable rendering
        if st.session_state.get("_uww_detail_player"):
            _sel = st.session_state.pop("_uww_detail_player")
            _show_uww_player_detail(_sel)

    with tab_opponents:
        profiles = load_table("uww_player_profiles")
        comparisons = load_table("uww_player_comparisons")
        opponent_choice = st.selectbox(
            "Opponent", sorted(profiles["opponent"].dropna().unique()), key="opp_profile_pick"
        )
        subset = profiles[profiles["opponent"] == opponent_choice]

        # Merge comparison data (target = upcoming Aurora players, compared = previous game players)
        # Check both directions: this opponent's players as target OR as compared
        opp_comps_as_target = comparisons[comparisons["target_opponent"] == opponent_choice] if not comparisons.empty else pd.DataFrame()
        opp_comps_as_compared = comparisons[comparisons["compared_opponent"] == opponent_choice] if not comparisons.empty else pd.DataFrame()

        # Build lookup: opponent player -> comparable player info
        comp_lookup = {}
        if not opp_comps_as_target.empty:
            for _, c in opp_comps_as_target.iterrows():
                comp_lookup[c["target_player"]] = {
                    "comp_player": c["compared_player"],
                    "comp_opponent": c["compared_opponent"],
                    "comp_position": c["compared_position"],
                    "similarity": c.get("similarity_score", ""),
                    "shared_notes": c.get("shared_notes_tags", ""),
                    "shared_keys": c.get("shared_keys_tags", ""),
                    "comp_game_date": c.get("compared_game_date", ""),
                }
        if not opp_comps_as_compared.empty:
            for _, c in opp_comps_as_compared.iterrows():
                comp_lookup[c["compared_player"]] = {
                    "comp_player": c["target_player"],
                    "comp_opponent": c["target_opponent"],
                    "comp_position": c["target_position"],
                    "similarity": c.get("similarity_score", ""),
                    "shared_notes": c.get("shared_notes_tags", ""),
                    "shared_keys": c.get("shared_keys_tags", ""),
                    "comp_game_date": "",
                }

        # Opponent header banner
        import base64 as _b64_opp
        _opp_logo_path = os.path.join(DATA_DIR, "logo", f"{opponent_choice}.png")
        _opp_logo_b64 = ""
        if os.path.exists(_opp_logo_path):
            with open(_opp_logo_path, "rb") as _lf:
                _opp_logo_b64 = _b64_opp.b64encode(_lf.read()).decode()
        _opp_logo_html = f'<img src="data:image/png;base64,{_opp_logo_b64}" style="max-height:48px;max-width:60px;object-fit:contain;margin-right:12px;">' if _opp_logo_b64 else ""
        _n_players = len(subset)
        st.markdown(
            f'<div style="background:#1a1a2e;border-radius:8px;padding:14px 20px;margin-bottom:1rem;display:flex;align-items:center;">'
            f'{_opp_logo_html}'
            f'<div style="color:#ffffff;font-family:Montserrat,sans-serif;font-weight:700;font-size:1.2rem;">{html.escape(opponent_choice.upper())}</div>'
            f'<div style="color:#9DAAAC;font-size:0.9rem;margin-left:16px;">{_n_players} scouted players</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Render styled player cards for starters (role) then bench
        starters = subset[subset["role"].str.strip().str.lower() == "starter"] if "role" in subset.columns else subset.head(5)
        bench = subset[subset["role"].str.strip().str.lower() != "starter"] if "role" in subset.columns else subset.iloc[5:]

        for _section_label, _section_df in [("Starters", starters), ("Bench", bench)]:
            if _section_df.empty:
                continue
            st.markdown(f'<div style="font-weight:700;font-size:0.95rem;color:#4E2A84;margin:0.75rem 0 0.5rem;border-bottom:2px solid #4E2A84;padding-bottom:4px;">{_section_label}</div>', unsafe_allow_html=True)
            _opp_cards_per_row = 3
            for _r_start in range(0, len(_section_df), _opp_cards_per_row):
                _row_df = _section_df.iloc[_r_start:_r_start + _opp_cards_per_row]
                _opp_cols = st.columns(_opp_cards_per_row)
                for _ci, (_, _pr) in enumerate(_row_df.iterrows()):
                    with _opp_cols[_ci]:
                        _comp_info = comp_lookup.get(_pr["name"], {})
                        _comp_html = ""
                        if _comp_info:
                            _comp_html = f'<div style="font-size:0.75rem;color:#1565c0;margin-top:4px;">Similar to: {html.escape(str(_comp_info.get("comp_player", "")))} ({html.escape(str(_comp_info.get("comp_opponent", "")))})</div>'

                        _pos = _pr.get("position", "-")
                        _ht = _pr.get("height", "")
                        # pd.notna() is True for a STRING, so a column pandas read as object dtype (one
                        # stray "-" anywhere in it is enough) got past this check and then blew up
                        # formatting a str with a numeric spec. safe_float()/_pct_value() exist for
                        # exactly this -- see safe_float's own docstring.
                        _pts_v = safe_float(_pr.get("PTS"))
                        _reb_v = safe_float(_pr.get("REB"))
                        _pts = f"{_pts_v:.1f}" if _pts_v is not None else "-"
                        _reb = f"{_reb_v:.1f}" if _reb_v is not None else "-"
                        # AST is a season total in this table -- divide by this player's own games played.
                        _card_gp = safe_float(_pr.get("games_played")) or (get_opponent_games_played(opponent_choice) or 1)
                        _ast_val = safe_float(_pr.get("AST"))
                        _ast = f"{_ast_val / _card_gp:.1f}" if _ast_val is not None and _card_gp else "-"
                        # FG% arrives as "44.8%" (or "-") in this table, so it needs the percent-aware
                        # parser rather than a plain float() -- this is the line that raised ValueError.
                        _fg_v = _pct_value(_pr.get("FG%"))
                        _fg = f"{_fg_v:.0f}%" if _fg_v is not None else "-"
                        _notes = str(_pr.get("player_notes", "")) if pd.notna(_pr.get("player_notes")) else ""
                        _keys = str(_pr.get("keys_to_defending", "")) if pd.notna(_pr.get("keys_to_defending")) else ""

                        _notes_html = f'<div style="font-size:0.78rem;color:#333;margin-top:6px;border-top:1px solid #eee;padding-top:4px;">{html.escape(_notes[:120])}</div>' if _notes else ""
                        _keys_html = f'<div style="font-size:0.75rem;color:#c62828;margin-top:3px;"><em>Defend:</em> {html.escape(_keys[:100])}</div>' if _keys else ""
                        _ht_html = " | " + html.escape(str(_ht)) if _ht else ""
                        st.markdown(
                            f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px;margin-bottom:8px;background:#faf8fc;">'
                            f'<div style="font-weight:700;font-size:0.95rem;color:#4E2A84;">{html.escape(str(_pr["name"]))}</div>'
                            f'<div style="font-size:0.8rem;color:#666;margin-top:2px;">{html.escape(str(_pos))}{_ht_html}</div>'
                            f'<div style="margin-top:6px;font-size:0.82rem;"><strong>{_pts}</strong> pts  <strong>{_reb}</strong> reb  <strong>{_ast}</strong> ast  <strong>{_fg}</strong> FG</div>'
                            f'{_comp_html}'
                            f'{_notes_html}'
                            f'{_keys_html}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

        # Full table in expander
        with st.expander("View full scouting table", expanded=False):
            # Add comparison columns to the display
            if comp_lookup:
                subset = subset.copy()
                subset["comparable_player"] = subset["name"].map(
                    lambda n: f"{comp_lookup[n]['comp_player']} ({comp_lookup[n]['comp_opponent']})" if n in comp_lookup else ""
                )
                subset["similarity"] = subset["name"].map(
                    lambda n: comp_lookup[n]["similarity"] if n in comp_lookup else ""
                )
                subset["shared_style"] = subset["name"].map(
                    lambda n: comp_lookup[n]["shared_notes"] if n in comp_lookup else ""
                )
                subset["shared_defense"] = subset["name"].map(
                    lambda n: comp_lookup[n]["shared_keys"] if n in comp_lookup else ""
                )

            # Put AST/TO/STL/BLK on the same per-game footing as PTS/REB, using each player's own games.
            subset = subset.copy()
            if "games_played" in subset.columns:
                _tbl_gp = pd.to_numeric(subset["games_played"], errors="coerce")
            else:
                _tbl_gp = pd.Series(index=subset.index, dtype="float64")
            _tbl_gp = _tbl_gp.where(_tbl_gp > 0).fillna(get_opponent_games_played(opponent_choice) or 1)
            for _tc in ("AST", "TO", "STL", "BLK"):
                if _tc in subset.columns:
                    subset[_tc] = (pd.to_numeric(subset[_tc], errors="coerce") / _tbl_gp).round(1)

            display_cols = [c for c in [
                "name", "role", "position", "height", "class_year",
                "PTS", "FG%", "3P%", "REB", "AST", "TO",
                "comparable_player", "similarity", "shared_style", "shared_defense",
                "player_notes", "keys_to_defending",
            ] if c in subset.columns]
            st.dataframe(subset[display_cols], hide_index=True, use_container_width=True)


# --------------------------------------------------------------------------------------------------------------
# Section 5: Analytics — Four Factors, efficiency/pace, shot quality, ball movement, schedule context,
# coach-tagged play notes
# --------------------------------------------------------------------------------------------------------------
def render_analytics():
    st.markdown("## :bar_chart: Analytics")
    st.caption(
        "Advanced, possession-adjusted stats built entirely from data already being collected -- box scores, "
        "play-by-play, and the schedule. No new charting or data collection required for anything on this page."
    )

    schedule = load_table("uww_schedule")
    box = load_table("uww_pbp_box_score")
    pbp = load_table("uww_pbp_events")

    if box.empty:
        st.info("No box score data available yet.")
        return

    uww_box_all = box[box["team"] == "UW-Whitewater"]
    opp_box_all = box[box["team"] != "UW-Whitewater"]
    n_games = uww_box_all["game_date"].nunique() if not uww_box_all.empty else 0

    # Split by GAME date, not opponent name: a team UWW beat once and lost to once would otherwise land
    # entirely in whichever bucket the first meeting fell into.
    short_names = load_short_opponent_names()
    game_outcomes = get_game_outcomes(schedule)
    _iso = lambda df: df["game_date"].astype(str).str[:10]
    win_dates = {d for d, r in game_outcomes.items() if r == "W"}
    loss_dates = {d for d, r in game_outcomes.items() if r == "L"}

    # ==================== FOUR FACTORS ====================
    section_header("FOUR FACTORS", glossary_help_text(["eFG%", "TOV%", "ORB%", "FT Rate"]))
    if uww_box_all.empty:
        st.info("Not enough box score data for Four Factors yet.")
    else:
        def _four_factors_row(label, team_b, opp_b):
            ff = compute_four_factors(team_b, opp_b)
            return {"Split": label, **{k: round(v, 1) for k, v in ff.items()}}

        ff_rows = [_four_factors_row("Season", uww_box_all, opp_box_all)]
        if win_dates:
            ff_rows.append(_four_factors_row("In Wins", uww_box_all[_iso(uww_box_all).isin(win_dates)], opp_box_all[_iso(opp_box_all).isin(win_dates)]))
        if loss_dates:
            ff_rows.append(_four_factors_row("In Losses", uww_box_all[_iso(uww_box_all).isin(loss_dates)], opp_box_all[_iso(opp_box_all).isin(loss_dates)]))
        opp_ff_rows = [_four_factors_row("Opponents (season)", opp_box_all, uww_box_all)]

        ff_col1, ff_col2 = st.columns(2)
        with ff_col1:
            st.markdown("**UWW**")
            st.dataframe(pd.DataFrame(ff_rows), hide_index=True, use_container_width=True)
        with ff_col2:
            st.markdown("**Opponents**")
            st.dataframe(pd.DataFrame(opp_ff_rows), hide_index=True, use_container_width=True)
        st.caption(
            "Compare the \"In Wins\" vs \"In Losses\" rows -- whichever factor moves the most between them is "
            "usually the best evidence for what this team's games actually hinge on, more so than any single "
            "raw counting stat."
        )

    # ==================== EFFICIENCY & PACE ====================
    section_header("EFFICIENCY &amp; PACE", glossary_help_text(["Pace", "ORtg", "DRtg", "Net Rtg", "Poss"]))
    if uww_box_all.empty or n_games == 0:
        st.info("Not enough box score data for efficiency/pace yet.")
    else:
        eff = compute_efficiency_pace(uww_box_all, opp_box_all, n_games)
        ecol1, ecol2, ecol3, ecol4 = st.columns(4)
        ecol1.metric("Pace", f"{eff['Pace']:.1f}", help=STAT_GLOSSARY["Pace"]["definition"])
        ecol2.metric("ORtg", f"{eff['ORtg']:.1f}", help=STAT_GLOSSARY["ORtg"]["definition"])
        ecol3.metric("DRtg", f"{eff['DRtg']:.1f}", help=STAT_GLOSSARY["DRtg"]["definition"])
        ecol4.metric("Net Rtg", f"{eff['Net Rtg']:+.1f}", help=STAT_GLOSSARY["Net Rtg"]["definition"])

        # Per-opponent efficiency trend (chronological, in schedule order) -- the "doable now" trend-chart item.
        played_order = schedule[played_mask(schedule)].copy()
        trend_rows = []
        for _, srow in played_order.iterrows():
            opp_short = resolve_short_opponent(srow["opponent"], short_names)
            g_date = resolve_game_date(srow["date"])
            if not opp_short or not g_date:
                continue
            # One point per GAME. Selecting by opponent name plotted a rematch's combined totals twice.
            g_uww = uww_box_all[_iso(uww_box_all) == g_date]
            g_opp = opp_box_all[_iso(opp_box_all) == g_date]
            if g_uww.empty:
                continue
            g_eff = compute_efficiency_pace(g_uww, g_opp, 1)
            label = f"{opp_short} {g_date[5:]}" if (played_order["opponent"] == srow["opponent"]).sum() > 1 else opp_short
            trend_rows.append({"Game": label, "ORtg": round(g_eff["ORtg"], 1), "DRtg": round(g_eff["DRtg"], 1), "Net Rtg": round(g_eff["Net Rtg"], 1)})
        if len(trend_rows) >= 2:
            trend_df = pd.DataFrame(trend_rows).set_index("Game")
            st.markdown("**Game-by-game trend** (chronological)")
            st.line_chart(trend_df[["ORtg", "DRtg"]])
            st.caption("Rising ORtg / falling DRtg over the season is the clearest single trendline for whether a team is actually improving, independent of schedule strength swings.")

    # ==================== REBOUNDING RATE ====================
    section_header("REBOUNDING RATE", glossary_help_text(["ORB%"]))
    if not uww_box_all.empty:
        uww_oreb = uww_box_all["OREB"].sum()
        uww_dreb = uww_box_all["DREB"].sum()
        opp_oreb = opp_box_all["OREB"].sum()
        opp_dreb = opp_box_all["DREB"].sum()
        uww_orb_pct = (uww_oreb / (uww_oreb + opp_dreb) * 100) if (uww_oreb + opp_dreb) > 0 else 0
        uww_drb_pct = (uww_dreb / (uww_dreb + opp_oreb) * 100) if (uww_dreb + opp_oreb) > 0 else 0
        rcol1, rcol2 = st.columns(2)
        rcol1.metric("Offensive Rebound %", f"{uww_orb_pct:.1f}%", help="Share of UWW's own missed shots that UWW rebounded.")
        rcol2.metric("Defensive Rebound %", f"{uww_drb_pct:.1f}%", help="Share of the opponent's missed shots that UWW rebounded.")
        st.caption("Raw rebound totals are confounded by how many shots were missed in the first place -- these percentages account for that, so they're comparable across games of very different pace.")
    else:
        st.info("Not enough box score data for rebounding rate yet.")

    # ==================== SHOT SELECTION / SHOT QUALITY ====================
    section_header("SHOT SELECTION &amp; QUALITY", (
            "Built from the same video-tagging your scouting pipeline already does for shot-quality diagnosis "
            "(play type, catch-and-shoot vs. pull-up, contest level, distance) -- surfaced here as a standalone "
            "team-wide view instead of only being used internally to generate coaching flags."
        ))
    if pbp.empty or "video_description" not in pbp.columns:
        st.info("No video-tagged play-by-play data available yet.")
    else:
        uww_shots = pbp[
            (pbp["team"] == "UW-Whitewater")
            & pbp["event_type"].isin(["made_shot", "missed_shot"])
            & pbp["video_description"].notna()
        ].copy()
        if uww_shots.empty:
            st.info("No video-tagged shot attempts available yet for UWW.")
        else:
            uww_shots["made"] = uww_shots["event_type"] == "made_shot"
            uww_shots["shot_mechanic"] = uww_shots["video_description"].apply(extract_shot_mechanic)
            uww_shots["contest"] = uww_shots["video_description"].apply(extract_contest)
            uww_shots["distance"] = uww_shots["video_description"].apply(extract_distance)

            sq_col1, sq_col2, sq_col3 = st.columns(3)
            with sq_col1:
                st.markdown("**By Shot Mechanic**")
                mech = uww_shots.groupby("shot_mechanic").agg(Attempts=("made", "count"), Makes=("made", "sum")).reset_index()
                mech["FG%"] = (100 * mech["Makes"] / mech["Attempts"]).round(1)
                st.dataframe(mech.sort_values("Attempts", ascending=False), hide_index=True, use_container_width=True)
            with sq_col2:
                st.markdown("**By Contest Level**")
                cont = uww_shots.groupby("contest").agg(Attempts=("made", "count"), Makes=("made", "sum")).reset_index()
                cont["FG%"] = (100 * cont["Makes"] / cont["Attempts"]).round(1)
                st.dataframe(cont.sort_values("Attempts", ascending=False), hide_index=True, use_container_width=True)
            with sq_col3:
                st.markdown("**By Distance**")
                dist = uww_shots.groupby("distance").agg(Attempts=("made", "count"), Makes=("made", "sum")).reset_index()
                dist["FG%"] = (100 * dist["Makes"] / dist["Attempts"]).round(1)
                st.dataframe(dist.sort_values("Attempts", ascending=False), hide_index=True, use_container_width=True)
            st.caption(f"Based on {len(uww_shots)} video-matched shot attempts across {uww_shots['game_date'].nunique() if 'game_date' in uww_shots.columns else uww_shots['opponent'].nunique()} game(s).")

    # ==================== ASSIST NETWORK ====================
    section_header("ASSIST NETWORK", (
            "Pairs each recorded assist event with the made-shot event immediately before it in the same "
            "team's play-by-play log (the standard convention this data already follows) to build a "
            "passer -> scorer breakdown -- no new tagging needed beyond what's already recorded per play."
        ))
    if pbp.empty:
        st.info("No play-by-play data available yet.")
    else:
        uww_pbp = pbp[pbp["team"] == "UW-Whitewater"].sort_values(["opponent", "event_order"]).copy()
        pairs = []
        prev_row = None
        for _, r in uww_pbp.iterrows():
            if r["event_type"] == "assist" and prev_row is not None and prev_row["event_type"] == "made_shot" and prev_row["opponent"] == r["opponent"]:
                pairs.append({"Passer": r["player"], "Scorer": prev_row["player"]})
            prev_row = r
        if not pairs:
            st.info("No assist events found in the play-by-play yet.")
        else:
            pairs_df = pd.DataFrame(pairs)
            combo = pairs_df.groupby(["Passer", "Scorer"]).size().reset_index(name="Assists").sort_values("Assists", ascending=False)
            an_col1, an_col2 = st.columns(2)
            with an_col1:
                st.markdown("**Top Passer → Scorer combos**")
                st.dataframe(combo.head(10), hide_index=True, use_container_width=True)
            with an_col2:
                st.markdown("**Assists Given (by passer)**")
                by_passer = pairs_df.groupby("Passer").size().reset_index(name="Assists").sort_values("Assists", ascending=False)
                st.dataframe(by_passer, hide_index=True, use_container_width=True)

    # ==================== TRANSITION POINTS OFF TURNOVERS ====================
    section_header("TRANSITION OFF TURNOVERS", (
            "Matches each steal to whether that same team scored within the next few play-by-play events -- an "
            "approximation of \"points off turnovers,\" since a live-ball turnover time isn't separately "
            "flagged in the data. A generous same-team-scores-soon-after window is used since exact shot-clock "
            "timing after a takeaway isn't recorded."
        ))
    if pbp.empty:
        st.info("No play-by-play data available yet.")
    else:
        pbp_sorted = pbp.sort_values(["opponent", "event_order"]).reset_index(drop=True)
        steal_rows = pbp_sorted[pbp_sorted["event_type"] == "steal"]
        transition_points = {"UW-Whitewater": 0, "Opponent": 0}
        transition_chances = {"UW-Whitewater": 0, "Opponent": 0}
        for idx in steal_rows.index:
            steal_team = pbp_sorted.loc[idx, "team"]
            opp_name = pbp_sorted.loc[idx, "opponent"]
            window = pbp_sorted[(pbp_sorted["opponent"] == opp_name) & (pbp_sorted.index > idx) & (pbp_sorted.index <= idx + 4)]
            side_key = "UW-Whitewater" if steal_team == "UW-Whitewater" else "Opponent"
            transition_chances[side_key] += 1
            scoring_after = window[(window["team"] == steal_team) & (window["event_type"].isin(["made_shot", "free_throw_made"]))]
            if not scoring_after.empty:
                first_score = scoring_after.iloc[0]
                pts = int(first_score["shot_type"]) if (first_score["event_type"] == "made_shot" and "shot_type" in first_score.index and pd.notna(first_score.get("shot_type"))) else 1
                transition_points[side_key] += pts
        tcol1, tcol2 = st.columns(2)
        tcol1.metric("UWW points off steals (approx.)", transition_points["UW-Whitewater"], help=f"From {transition_chances['UW-Whitewater']} steals this season.")
        tcol2.metric("Opponent points off steals (approx.)", transition_points["Opponent"], help=f"From {transition_chances['Opponent']} opponent steals this season.")

    # ==================== SCHEDULE / REST CONTEXT ====================
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">SCHEDULE &amp; REST CONTEXT</div></div>', unsafe_allow_html=True)
    played_sched = schedule[played_mask(schedule)].copy()
    if played_sched.empty:
        st.info("No played games yet.")
    else:
        played_sched["_parsed_date"] = pd.to_datetime(played_sched["date"], errors="coerce")
        played_sched = played_sched.sort_values("_parsed_date")
        played_sched["Rest Days"] = played_sched["_parsed_date"].diff().dt.days
        display_rest = played_sched[["date", "opponent", "outcome", "point_margin", "Rest Days"]].copy()
        display_rest["Rest Days"] = display_rest["Rest Days"].apply(lambda x: "-" if pd.isna(x) else ("Back-to-back" if x <= 1 else f"{int(x)} days"))
        st.dataframe(display_rest.rename(columns={"date": "Date", "opponent": "Opponent", "outcome": "Result", "point_margin": "Margin"}), hide_index=True, use_container_width=True)
        b2b = played_sched[played_sched["_parsed_date"].diff().dt.days <= 1].dropna(subset=["_parsed_date"])
        if not b2b.empty:
            b2b_wins = int((b2b["outcome"] == "W").sum())
            st.caption(f"Back-to-back or same-day games this season: {len(b2b)} (record: {b2b_wins}-{len(b2b) - b2b_wins}).")

    # ==================== COACH-TAGGED PLAY NOTES ====================
    section_header("COACH-TAGGED PLAY NOTES", (
            "Built from a coach-annotated video-clip export (a \"<matchup>_recap.csv\" file per game) -- each "
            "tagged clip carries the coach's own free-text note for that specific play: an offensive play call "
            "and how it was executed, or a defensive breakdown of what went right/wrong. Only games with a "
            "matching recap file have this data; everything else on this page comes from the box score and "
            "play-by-play alone."
        ))
    coach_notes = load_table("uww_coach_notes")
    if coach_notes.empty:
        st.info("No coach-tagged play notes available yet -- add a \"<matchup>_recap.csv\" file for a game and re-run the parser.")
    else:
        off_notes = coach_notes[coach_notes["clip_side"] == "Offense"].copy() if "clip_side" in coach_notes.columns else pd.DataFrame()
        def_notes = coach_notes[coach_notes["clip_side"] == "Defense"].copy() if "clip_side" in coach_notes.columns else pd.DataFrame()

        cn_col1, cn_col2, cn_col3 = st.columns(3)
        cn_col1.metric("Total Notes", len(coach_notes))
        cn_col2.metric("Offensive Clips", len(off_notes))
        cn_col3.metric("Defensive Clips", len(def_notes))

        # --- Play calls (offense only) ---
        if not off_notes.empty:
            off_notes["play_call"] = resolve_play_calls(off_notes)
            call_rows = off_notes[off_notes["play_call"].notna()].copy()
            # The SAME possession can arrive twice: once from a game recap note ("PANTHER EXECUTION...")
            # and once from the season play-call log, and again if two play-log exports overlap. Both
            # rows describe one call, so counting both double-counts every possession the staff tagged in
            # more than one place. Collapse on the possession key, keeping whichever copy carries the
            # coach's note so the detail view keeps the commentary. Rows with no clock can't be identified
            # as the same possession, so they're left alone rather than merged on a guess.
            _cr_key = [c for c in ["opponent", "period", "time_remaining_seconds", "team", "player", "play_call"]
                       if c in call_rows.columns]
            if "time_remaining_seconds" in call_rows.columns and _cr_key:
                _cr_timed = call_rows[call_rows["time_remaining_seconds"].notna()].copy()
                _cr_untimed = call_rows[call_rows["time_remaining_seconds"].isna()]
                _cr_timed["_has_note"] = _cr_timed["coach_note"].notna() if "coach_note" in _cr_timed.columns else False
                _cr_timed = (_cr_timed.sort_values("_has_note", ascending=False)
                             .drop_duplicates(subset=_cr_key, keep="first")
                             .drop(columns=["_has_note"]))
                _cr_dropped = len(call_rows) - len(_cr_timed) - len(_cr_untimed)
                call_rows = pd.concat([_cr_timed, _cr_untimed], ignore_index=True)
            else:
                _cr_dropped = 0
            st.markdown("**Play Calls**")
            if not call_rows.empty:
                call_rows["_is_make"] = call_rows["result"].astype(str).str.contains("Make", case=False, na=False)
                call_rows["_is_attempt"] = call_rows["result"].astype(str).str.contains("Make|Miss", case=False, regex=True, na=False)
                # Calls was ("coach_note", "count") -- and count() SKIPS nulls, so it only ever counted the
                # clips that carried a written note. Every row that came from the season play-call log has
                # no coach_note at all, so those possessions vanished from the count while still counting
                # toward Attempts: Kentucky showed "1 call, 5 attempts". Count rows instead.
                call_summary = call_rows.groupby("play_call").agg(
                    Calls=("play_call", "size"), Makes=("_is_make", "sum"), Attempts=("_is_attempt", "sum"),
                    Notes=("coach_note", "count"),
                ).reset_index()
                # Points per possession, the metric the play lists are now ranked on -- FG% stays as a
                # column rather than being replaced, since it's what the staff has read all season.
                _pc_eff = summarize_play_calls(call_rows, min_possessions=1)[["play_call", "Poss", "Pts", "PPP"]]
                call_summary = call_summary.merge(_pc_eff, on="play_call", how="left")
                # .replace(0, pd.NA) turned Attempts into an OBJECT-dtype Series, so the division produced
                # object values and .round(1) then called round() on a pd.NA element -> TypeError (crashed
                # the whole Analytics page). Coerce to float and use NaN for the divide-by-zero guard
                # instead, which keeps the Series numeric and rounds cleanly.
                _pc_makes = pd.to_numeric(call_summary["Makes"], errors="coerce")
                _pc_att = pd.to_numeric(call_summary["Attempts"], errors="coerce").replace(0, float("nan"))
                call_summary["FG%"] = (100 * _pc_makes / _pc_att).round(1)
                call_summary["PPP"] = call_summary["PPP"].round(2)
                call_summary = call_summary.drop(columns=["Makes", "Pts"]).sort_values(
                    ["PPP", "Calls"], ascending=False).reset_index(drop=True)
                # Playbook context, when the catalog has been parsed: the catalog's own SERIES plus the
                # play-name family that actually groups the shorthand together (Panther "P" / Panther 2
                # "P2" / Panther-4 "P4" are all filed under Specials, but a coach reads them as Panther).
                _pc_ser = call_summary["play_call"].apply(play_call_series)
                call_summary["Series"] = [x[0] for x in _pc_ser]
                call_summary["Family"] = [x[1] for x in _pc_ser]
                _pc_has_catalog = bool(call_summary["Series"].astype(str).str.strip().any())

                # --- Possession-level detail behind each play call -------------------------------------
                # The summary answers "how often, how well"; the obvious next question a coach asks is
                # "show me WHICH ones" -- so a row click opens every tagged possession for that call, with
                # the game, clock and score attached. uww_pbp_events is the richer source (the parser
                # already merged coach_note/play_call onto it, and it alone carries game_date, running
                # score and the on-floor lineup); the coach-notes rows themselves are the fallback for
                # clips that never matched a play-by-play row (no usable clock, or a name spelled
                # differently between the two exports), so a call's possessions are never silently missing.
                def _pc_clock(_secs):
                    _v = safe_float(_secs)
                    if _v is None or _v != _v:
                        return "--"
                    _v = max(int(_v), 0)
                    return f"{_v // 60}:{_v % 60:02d}"

                _pc_events = load_table("uww_pbp_events")
                if not _pc_events.empty and "coach_note" in _pc_events.columns:
                    _pc_events = _pc_events.copy()
                    _pc_events["_pc_call"] = resolve_play_calls(_pc_events)
                    _pc_events = _pc_events[_pc_events["_pc_call"].notna()]
                else:
                    _pc_events = pd.DataFrame()

                @st.dialog("Play Call Detail", width="large")
                def _show_play_call_detail(_call):
                    _sum_row = call_summary[call_summary["play_call"] == _call]
                    if not _sum_row.empty:
                        _sr = _sum_row.iloc[0]
                        _fg_txt = "--" if pd.isna(_sr["FG%"]) else f"{_sr['FG%']:.1f}%"
                        _ppp_txt = "" if pd.isna(_sr.get("PPP")) else f"{_sr['PPP']:.2f} PPP &middot; "
                        _pc_sr_series, _pc_sr_family = play_call_series(_call)
                        _pc_ctx = " &middot; ".join(x for x in [
                            f"{html.escape(_pc_sr_family)} series" if _pc_sr_family else "",
                            html.escape(_pc_sr_series) if _pc_sr_series else "",
                        ] if x)
                        st.markdown(
                            f'<div style="font-family:Montserrat,sans-serif;font-weight:800;font-size:1.5rem;color:#4E2A84;">{html.escape(str(_call))}</div>'
                            + (f'<div style="color:#4E2A84;font-size:0.85rem;font-weight:600;">{_pc_ctx}</div>' if _pc_ctx else "")
                            + f'<div style="color:#666;margin-bottom:10px;">{_ppp_txt}{int(_sr["Calls"])} tagged clip(s) &middot; '
                            f'{int(_sr["Attempts"])} shot attempt(s) &middot; {_fg_txt} FG</div>',
                            unsafe_allow_html=True,
                        )

                    _det = _pc_events[_pc_events["_pc_call"] == _call].copy() if not _pc_events.empty else pd.DataFrame()
                    if not _det.empty:
                        _det["Game"] = _det.apply(
                            lambda r: f"vs {r['opponent']}" + (f" ({r['game_date']})" if pd.notna(r.get("game_date")) else ""), axis=1
                        )
                        _det["Time"] = _det.apply(
                            lambda r: f"{r.get('period', '')} {str(r.get('time_remaining', '')).split(' (')[0]}".strip(), axis=1
                        )
                        _det["Score"] = _det.apply(
                            lambda r: "--" if pd.isna(r.get("uww_score")) or pd.isna(r.get("opp_score"))
                            else f"{int(safe_float(r['uww_score']) or 0)}-{int(safe_float(r['opp_score']) or 0)}", axis=1
                        )
                        _det_cols = [c for c in ["Game", "Time", "Score", "player", "event_type", "shot_type",
                                                 "coach_note", "uww_lineup"] if c in _det.columns]
                        _det = _det.sort_values([c for c in ["game_date", "event_order"] if c in _det.columns])
                        st.dataframe(
                            _det[_det_cols].rename(columns={
                                "player": "Player", "event_type": "Result", "shot_type": "Shot Type",
                                "coach_note": "Coach Note", "uww_lineup": "Lineup On Floor",
                            }),
                            hide_index=True, use_container_width=True,
                        )
                    else:
                        # Fallback: the clips themselves, which always exist even when nothing linked to a
                        # play-by-play row -- no running score available for these, hence no Score column.
                        _fb = call_rows[call_rows["play_call"] == _call].copy()
                        _fb["Game"] = "vs " + _fb["opponent"].astype(str)
                        _fb["Time"] = _fb.apply(
                            lambda r: f"{r.get('period', '')} {_pc_clock(r.get('time_remaining_seconds'))}".strip(), axis=1
                        )
                        _fb_cols = [c for c in ["Game", "Time", "player", "result", "coach_note"] if c in _fb.columns]
                        st.dataframe(
                            _fb[_fb_cols].rename(columns={"player": "Player", "result": "Result", "coach_note": "Coach Note"}),
                            hide_index=True, use_container_width=True,
                        )
                        st.caption("These clips didn't match a play-by-play row, so no running score is available for them.")

                _pc_display = call_summary[
                    [c for c in ["play_call", "Series", "Family", "Calls", "Poss", "PPP", "Attempts", "FG%", "Notes"] if c in call_summary.columns]
                    if _pc_has_catalog else ["play_call", "Calls", "Poss", "PPP", "Attempts", "FG%", "Notes"]
                ].rename(columns={"play_call": "Play Call"})
                _pc_picked = None
                try:
                    _pc_event = st.dataframe(
                        _pc_display, hide_index=True, use_container_width=True,
                        on_select="rerun", selection_mode="single-row", key="play_calls_table",
                    )
                    _pc_rows = (_pc_event.selection.get("rows") if hasattr(_pc_event, "selection") else _pc_event["selection"]["rows"]) or []
                    if _pc_rows:
                        _pc_picked = call_summary.iloc[_pc_rows[0]]["play_call"]
                except TypeError:
                    # Older Streamlit without dataframe row selection -- keep the table usable and offer the
                    # same detail through a picker instead of failing the page.
                    st.dataframe(_pc_display, hide_index=True, use_container_width=True)
                    _pc_choice = st.selectbox(
                        "Play call detail", ["--"] + call_summary["play_call"].astype(str).tolist(), key="play_calls_pick",
                    )
                    _pc_picked = None if _pc_choice == "--" else _pc_choice
                if _pc_picked:
                    _show_play_call_detail(_pc_picked)

                if _pc_has_catalog:
                    # Series-level rollup: individual calls are thin slices (a handful of clips each), so
                    # the family totals are what actually say whether the Panther package is working.
                    _pc_fam = call_summary[call_summary["Family"].astype(str).str.strip() != ""].groupby("Family").agg(
                        Calls=("Calls", "sum"), Attempts=("Attempts", "sum"), Poss=("Poss", "sum"),
                    ).reset_index()
                    _pc_fam_src = call_rows.copy()
                    _pc_fam_src["_fam"] = _pc_fam_src["play_call"].apply(lambda c: play_call_series(c)[1])
                    _pc_fam_src = _pc_fam_src[_pc_fam_src["_fam"].astype(str).str.strip() != ""]
                    _pc_fam_src["_pts"] = pd.to_numeric(_pc_fam_src["result"].apply(play_result_points), errors="coerce")
                    _pc_fam_agg = _pc_fam_src.groupby("_fam").agg(
                        _makes=("_is_make", "sum"), _pts=("_pts", "sum"),
                    )
                    _pc_fam["FG%"] = (100 * _pc_fam["Family"].map(_pc_fam_agg["_makes"]).astype(float)
                                      / pd.to_numeric(_pc_fam["Attempts"], errors="coerce").replace(0, float("nan"))).round(1)
                    _pc_fam["PPP"] = (_pc_fam["Family"].map(_pc_fam_agg["_pts"]).astype(float)
                                      / pd.to_numeric(_pc_fam["Poss"], errors="coerce").replace(0, float("nan"))).round(2)
                    if len(_pc_fam) > 1:
                        with st.expander(f"By play series ({len(_pc_fam)} families)", expanded=False):
                            st.dataframe(
                                _pc_fam[[c for c in ["Family", "Calls", "Poss", "PPP", "Attempts", "FG%"] if c in _pc_fam.columns]]
                                .sort_values("PPP", ascending=False), hide_index=True, use_container_width=True,
                            )

                if _cr_dropped:
                    st.caption(f"{_cr_dropped} duplicate possession(s) merged -- the same play tagged both in a game recap and in the season play-call log.")
                st.caption("Click a row to see every tagged possession for that play call -- game, clock, score, result and the coach's note. Play call comes from the season play-call log when that game is covered by it, and otherwise from a best-effort read of the coach's own note text (a name immediately before the word \"EXECUTION\").")
            else:
                st.caption("No named play calls detected yet (looks for a name immediately before the word \"EXECUTION\" in offensive notes).")

        # --- Grouped themes: what the notes are ABOUT, not the exact words used --------------------------
        # The flag counts below group on the coach's literal clause text, so "MISSED SWITCH" and "-BAD
        # MISSED SWITCH" are two different themes with one mention each. This groups by subject instead,
        # against the taxonomy in data/note_themes.json -- pure phrase matching, so classifying a new note
        # costs nothing and happens the moment the parser writes it.
        _nt_themes = load_note_themes()
        st.markdown("**Note Themes**")
        if not _nt_themes:
            st.caption("No theme file found -- add data/note_themes.json to group notes by subject.")
        else:
            _nt_long = note_theme_table(coach_notes)
            if _nt_long.empty:
                st.caption("No notes matched a theme yet.")
            else:
                _nt_side = {t["theme"]: t.get("side", "") for t in _nt_themes}
                _nt_sum = _nt_long.groupby("theme").agg(
                    Notes=("note", "count"), Positive=("pos", "sum"), Negative=("neg", "sum"),
                ).reset_index()
                _nt_sum["Side"] = _nt_sum["theme"].map(_nt_side)
                _nt_sum = _nt_sum.rename(columns={"theme": "Theme"}).sort_values("Notes", ascending=False)
                _nt_c1, _nt_c2 = st.columns([3, 2])
                with _nt_c1:
                    st.dataframe(_nt_sum[["Theme", "Side", "Notes", "Positive", "Negative"]],
                                 hide_index=True, use_container_width=True)
                with _nt_c2:
                    _nt_worst = _nt_sum[_nt_sum["Negative"] > 0].nlargest(3, "Negative")
                    if not _nt_worst.empty:
                        st.markdown("**Most-corrected subjects**")
                        for _, _r in _nt_worst.iterrows():
                            st.markdown(f"- **{_r['Theme']}** -- {int(_r['Negative'])} corrections "
                                        f"across {int(_r['Notes'])} notes")
                    _nt_best = _nt_sum[_nt_sum["Positive"] > 0].nlargest(3, "Positive")
                    if not _nt_best.empty:
                        st.markdown("**Most-praised subjects**")
                        for _, _r in _nt_best.iterrows():
                            st.markdown(f"- {_r['Theme']} -- {int(_r['Positive'])} positives")
                _nt_pick = st.selectbox("Read the notes behind a theme",
                                        ["--"] + _nt_sum["Theme"].tolist(), key="note_theme_pick")
                if _nt_pick != "--":
                    _nt_rows = _nt_long[_nt_long["theme"] == _nt_pick]
                    _nt_cols = [c for c in ["opponent", "player", "note"] if c in _nt_rows.columns]
                    st.dataframe(_nt_rows[_nt_cols].rename(columns={
                        "opponent": "Game", "player": "Player", "note": "Note"}),
                        hide_index=True, use_container_width=True)
                st.caption(
                    f"{len(_nt_themes)} themes, matched by phrase -- a note can belong to more than one "
                    "(a missed switch that led to a foul is both). Classification is lexical, so new notes "
                    "are grouped instantly at zero cost; to retune, edit the phrase lists in "
                    "data/note_themes.json -- no re-running a model."
                )

        # --- Most common flagged themes ---
        def _theme_counts(notes_df, sign):
            themes = []
            for note in notes_df["coach_note"].dropna():
                for seg in str(note).split(","):
                    seg = seg.strip()
                    if seg.startswith(sign):
                        themes.append(seg.lstrip("+-").strip())
            if not themes:
                return pd.DataFrame(columns=["Theme", "Times Flagged"])
            return pd.Series(themes).value_counts().rename_axis("Theme").reset_index(name="Times Flagged").head(8)

        cn_theme_col1, cn_theme_col2 = st.columns(2)
        with cn_theme_col1:
            st.markdown("**Most Common Positive Flags**")
            pos_themes = _theme_counts(coach_notes, "+")
            if not pos_themes.empty:
                st.dataframe(pos_themes, hide_index=True, use_container_width=True)
            else:
                st.caption("No \"+\"-flagged themes recorded yet.")
        with cn_theme_col2:
            st.markdown("**Most Common Negative Flags**")
            neg_themes = _theme_counts(coach_notes, "-")
            if not neg_themes.empty:
                st.dataframe(neg_themes, hide_index=True, use_container_width=True)
            else:
                st.caption("No \"-\"-flagged themes recorded yet.")
        st.caption("Themes are tallied by exact matching text after the +/- marker is stripped -- two notes phrasing the same idea slightly differently (e.g. \"MISSED SWITCH\" vs \"MISSED SWITCH LEADS TO BAD CLOSEOUT\") count as separate themes, not one. Read as a rough signal of what's coming up often, not a precise count.")

        # --- By player (offense only) ---
        # Defensive clips are tagged with the OPPONENT player who took the shot (that's who "Player" refers
        # to on a defensive clip), not which UWW defender the note is actually about -- the free text rarely
        # names a specific UWW defender. Attributing a defensive note to that row's "player" would credit/
        # blame the wrong team's player, so this breakdown only covers offensive clips, where "player" really
        # is the UWW player the note is evaluating.
        if not off_notes.empty:
            st.markdown("**By Player (Offense)**")
            _player_rows = []
            for _player, _grp in off_notes.groupby("player"):
                _p_pos, _p_neg = 0, 0
                for _n in _grp["coach_note"]:
                    _pp, _pn = note_sentiment_counts(_n)
                    _p_pos += _pp
                    _p_neg += _pn
                _player_rows.append({"Player": _player, "Notes": len(_grp), "Positive Flags": _p_pos, "Negative Flags": _p_neg})
            player_summary = pd.DataFrame(_player_rows).sort_values("Notes", ascending=False)
            st.dataframe(player_summary, hide_index=True, use_container_width=True)
            st.caption("Defensive clips aren't broken out by player -- the \"Player\" on a defensive clip is the opponent player who took the shot, not necessarily which UWW defender the note is about, so attributing it to a specific UWW player here would be misleading. Browse defensive notes directly below instead.")

        # --- Browse all notes ---
        with st.expander("Browse all coach notes", expanded=False):
            cn_search = st.text_input("Search notes", "", key="coach_notes_search", placeholder="e.g. switch, execution, closeout...")
            browse_df = coach_notes.copy()
            if cn_search.strip():
                browse_df = browse_df[browse_df["coach_note"].str.contains(cn_search.strip(), case=False, na=False)]
            browse_cols = [c for c in ["opponent", "period", "clip_side", "team", "player", "result", "coach_note"] if c in browse_df.columns]
            st.dataframe(
                browse_df[browse_cols].rename(columns={"coach_note": "Coach Note", "clip_side": "Side"}),
                hide_index=True, use_container_width=True, height=300,
            )


# --------------------------------------------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&family=Georgia&display=swap');

:root {
    --warhawk-purple: #4E2A84;
    --warhawk-gray: #9DAAAC;
    --warhawk-light: #F0EDF5;
}

html, body, [class*="css"] {
    font-family: 'Montserrat', sans-serif;
}

h1, h2, h3 {
    font-family: 'Montserrat', sans-serif;
    color: var(--warhawk-purple) !important;
    font-weight: 700;
}

h4, h5, h6 {
    font-family: 'Montserrat', sans-serif;
    color: var(--warhawk-purple) !important;
    font-weight: 600;
}

.stSidebar {
    background-color: var(--warhawk-purple) !important;
}

.stSidebar [data-testid="stSidebarContent"] {
    background-color: var(--warhawk-purple) !important;
}

.stSidebar h1, .stSidebar h2, .stSidebar h3,
.stSidebar .stMarkdown, .stSidebar label,
.stSidebar [data-testid="stMarkdownContainer"] {
    color: #FFFFFF !important;
}



div[data-testid="stMetricValue"] {
    font-family: 'Montserrat', sans-serif;
    color: var(--warhawk-purple) !important;
    font-weight: 700;
}

/* Larger tab labels */
.stTabs [data-baseweb="tab-list"] button,
.stTabs [data-baseweb="tab-list"] button p,
.stTabs [data-baseweb="tab"] button p {
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    padding: 12px 24px !important;
}

div[data-testid="stMetricLabel"] {
    font-family: 'Montserrat', sans-serif;
}

.stSubheader {
    border-bottom: 2px solid var(--warhawk-purple);
    padding-bottom: 4px;
}

[data-testid="stExpander"] summary {
    font-family: 'Montserrat', sans-serif;
    font-weight: 600;
}

/* Word wrap in dataframes (coaching flags) */
[data-testid="stDataFrame"] td {
    white-space: normal !important;
    word-wrap: break-word !important;
}

/* Force dialog to near-full width */
div[data-testid="stModal"] > div {
    max-width: 95vw !important;
    width: 95vw !important;
}

div[data-testid="stModal"] [data-testid="stVerticalBlock"] {
    width: 100%;
}
/* Sidebar collapse button: gray, always visible */
button[data-testid="stSidebarCollapseButton"],
button[data-testid="baseButton-headerNoPadding"] {
    color: #9DAAAC !important;
    opacity: 1 !important;
    visibility: visible !important;
}

button[data-testid="stSidebarCollapseButton"] svg,
button[data-testid="baseButton-headerNoPadding"] svg {
    fill: #9DAAAC !important;
    stroke: #9DAAAC !important;
}

/* Remove any remaining white from sidebar/nav */
.stSidebar > div,
.stSidebar [data-testid="stSidebarContent"] > div,
.stSidebar [data-testid="stSidebarUserContent"],
.stSidebar [data-testid="stSidebarUserContent"] > div {
    background-color: #4E2A84 !important;
}

section[data-testid="stSidebar"] > div {
    background-color: #4E2A84 !important;
}


/* Reduce spacing between bullet points */
div[data-testid="stMarkdownContainer"] ul {
    margin-top: 0;
    margin-bottom: 0.5rem;
}
div[data-testid="stMarkdownContainer"] ul li {
    margin-bottom: -0.5rem;
    padding-bottom: 0;
    line-height: 1.4;
}
div[data-testid="stMarkdownContainer"] ul li:last-child {
    margin-bottom: 0.5rem;
}
div[data-testid="stMarkdownContainer"] p {
    margin-bottom: 0;
}

/* Remove all rounded corners from sidebar/nav elements */
.stSidebar *,
section[data-testid="stSidebar"] * {
    border-radius: 0px !important;
}
</style>
"""


def main():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # Navigation state
    if "nav_page" not in st.session_state:
        st.session_state.nav_page = "Home"

    pages = ["Home", "Upcoming Game", "Previous Games", "Team", "Players", "Analytics"]

    # Button-based navbar: uses theme primaryColor for the active page, no internal DOM hacks
    cols = st.columns(len(pages))
    for i, p in enumerate(pages):
        with cols[i]:
            is_active = st.session_state.nav_page == p
            if st.button(
                p,
                key=f"nav_{p}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state.nav_page = p
                st.rerun()

    page = st.session_state.nav_page
    if page == "Home":
        render_home()
    elif page == "Upcoming Game":
        render_upcoming_game()
    elif page == "Previous Games":
        render_previous_games()
    elif page == "Team":
        render_team()
    elif page == "Players":
        render_players()
    elif page == "Analytics":
        render_analytics()


if __name__ == "__main__":
    main()


