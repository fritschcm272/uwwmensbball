"""UW-Whitewater men's basketball scouting/coaching analytics app.

Data is bundled directly with the app (CSV files under ./data, exported from the analysis notebook's Delta
tables) rather than queried live from a SQL warehouse -- no Unity Catalog / warehouse permissions are needed
at runtime. Six sections: Home (AI scouting assistant), Upcoming Game (including a "Game Plan
Recommendations" panel that synthesizes coach notes, lineup, and rate-stat data into specific pre-game
suggestions), Previous Games, Team, Players, Analytics (possession-adjusted advanced stats -- Four Factors,
efficiency/pace, shot quality, ball movement, clutch performance, schedule/rest context, and coach-tagged
play notes; see STAT_GLOSSARY for definitions of every derived metric).
"""

import html
import json
import os
import re

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

st.set_page_config(page_title="UWW Basketball Scouting", page_icon="🏀", layout="wide")


@st.cache_data
def load_table(name: str) -> pd.DataFrame:
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


def played_mask(schedule: pd.DataFrame) -> pd.Series:
    return schedule["outcome"].notna() & schedule["team_score"].notna()


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


def get_opponent_games_played(short_opponent: str, default: int = 5) -> int:
    """Count of games with a recorded outcome in the opponent's own season schedule (uww_opponent_schedules)
    -- used to convert an opponent's season-TOTAL stats into per-game rates.

    In uww_player_profiles, PTS and REB are already per-game averages (no division needed), but AST/STL/BLK/TO
    and the 3PM-A/FTM-A "made-attempted" strings are season-CUMULATIVE totals and need dividing by this
    helper's result. (Confirmed empirically, not just from a comment: summing AST across a roster with no
    division produces an implausible ~200 "assists per game" figure -- only sane as a season sum. Not every
    column in this table shares the same units; don't assume otherwise without checking real output again.)

    Previously this was a hardcoded `_games_est = 5` sprinkled across several Upcoming Game computations,
    which silently misstates every opponent's per-game rates except in whichever week they happen to have
    played exactly 5 games. Falls back to `default` only when no schedule data exists yet for that opponent
    (e.g. very early season, before any of their games have been scraped/parsed).
    """
    if not short_opponent:
        return default
    opp_sched = load_table("uww_opponent_schedules")
    if opp_sched.empty or "opponent" not in opp_sched.columns:
        return default
    games = opp_sched[(opp_sched["opponent"] == short_opponent) & opp_sched["outcome"].notna()]
    n = len(games)
    return n if n > 0 else default


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
    streak_str = f"{streak_count}{'W' if streak_type == 'W' else 'L'} streak" if streak_count > 1 else ""
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
    "Ball Security": {"keywords": "ball security, protect the ball, take care of the ball, limit turnovers, our turnovers, live-ball turnover, live-ball turnovers, dead-ball turnover, dead-ball turnovers, careless, live dribble, sloppy, giveaway, giveaways, unforced", "stats": "TO"},
    "Rebounding": {"keywords": "own the paint, bully, glass, rebound, rebounding, rebounds, board, boards, second chance, crash, dominate the paint, box out, put back, putback", "stats": "REB, ORB, DRB"},
    "Three-Point Shooting": {"keywords": "three, threes, 3, 3s, 3's, 3 pt, 3pt, 3-pt, 3-point, 3-pointer, 3-pointers, three-point, three-pointer, three-pointers, three point, perimeter shooting, spacing, shooting ability, shooting team, sniper, will shoot, trey, treys, deep ball, deep balls, beyond the arc, from deep, transition three, transition threes, transition 3, transition 3's, catch and shoot, corner three, corner 3, above the break", "stats": "3PM-A, 3P%"},
    "Free Throws": {"keywords": "free throw, free throws, ft line, getting to ft, foul line, and-one, and one", "stats": "FTM-A, FT%"},
    "Fouls / Discipline": {"keywords": "foul, fouls, wall up, drawing fouls, discipline, reach, reaching, hand check", "stats": "PF"},
    "Ball Movement / Assists": {"keywords": "assist, assists, ball movement, share the ball, playmaking, playmaker, create, extra pass, hockey assist, swing the ball", "stats": "AST"},
    "Paint Protection / Blocks": {"keywords": "block, blocks, protect the rim, paint protection, rim protection, shot blocking, contest at the rim", "stats": "BLK"},
    "Perimeter Defense / Ball Pressure/ Create Turnovers": {"keywords": "steal, steals, press capable, full court press, force turnovers, force to's, forcing turnovers, generate turnovers, turnover trigger, turnover triggers, guard your yard, keep the ball in front, guard 1 on 1, early gap, help side, active hands, physical & aggressive on ball, on ball defensively, pressure, ball pressure, deny, deflection, deflections", "stats": "STL"},
    "Scoring Inside": {"keywords": "dominate the paint, attack the paint, live in the paint, attack the basket, scoring at the rim, get to rim, attack the rim, get to the rim, post up, post-up, paint touches, drive, drives, downhill, finish at the rim", "stats": "FG2M, FG2A, FG2%"},
    "Field Goal Efficiency": {"keywords": "limit their scoring, field goal, field goal%, fg%, shooting percentage, efficient shooting, efficiency, good shots, quality shots", "stats": "FGM-A, FG%"},
    "Defensive Efficiency": {"keywords": "high-volume, high volume, funnel, funneling, take away, most efficient, shot profile, shot diet, inefficient looks, worst looks, multiple efforts, multiple effort, never stop", "stats": "Opp FG% by shot type"},
    "Offensive Efficiency": {"keywords": "attack & execute, attack and execute, execute offensively, attack offensively, shot selection, shot quality, best shot type", "stats": "TS%, eFG%"},
    "Personnel/Rotation": {"keywords": "bench trust, off the bench, foul trouble, closing lineup, closing 5, close the game, clutch, late-game, late game, rotation, sub pattern, substitution pattern, trust plan, who to trust, core players", "stats": "MIN, Game Score"},
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
    # General Defensive / Containment (OPP)
    "take away": "OPP", "funnel": "OPP", "deny": "OPP", "contain": "OPP",
    "limit": "OPP", "contest": "OPP", "make them": "OPP", "load up": "OPP",
    "transition defense": "OPP", "fight over": "OPP", "switch": "OPP",
    "trap": "OPP", "double team": "OPP", "coverage": "OPP",
    "don't help off": "OPP", "take away personnel": "OPP",
    # General Offensive / Proactive (UWW)
    "run the floor": "UWW", "push tempo": "UWW", "fast break": "UWW",
    "score in transition": "UWW", "finish": "UWW", "execute": "UWW",
    "dominate": "UWW", "impose": "UWW", "push the pace": "UWW",
}


def get_data_driven_ktv(short_opponent):
    """Compute data-driven Keys to Victory: win/loss stat splits for the upcoming opponent's KTV categories."""
    ktv_games = load_table("uww_ktv_game_categories")
    box = load_table("uww_pbp_box_score")
    schedule = load_table("uww_schedule")

    # Get categories assigned to this opponent
    opp_cats = ktv_games[ktv_games["opponent"] == short_opponent]["category"].unique()
    if len(opp_cats) == 0:
        return None

    # Build per-game UWW team totals from PBP box score
    uww_box = box[box["team"] == "UW-Whitewater"]
    if uww_box.empty:
        return None
    uww_per_game = uww_box.groupby("opponent").agg({
        "PTS": "sum", "FGM": "sum", "FGA": "sum", "FG3M": "sum", "FG3A": "sum",
        "FTM": "sum", "FTA": "sum", "OREB": "sum", "DREB": "sum", "REB": "sum",
        "AST": "sum", "STL": "sum", "BLK": "sum", "TO": "sum", "PF": "sum"
    }).reset_index()
    uww_per_game["FG%"] = (uww_per_game["FGM"] / uww_per_game["FGA"] * 100).round(1)
    uww_per_game["3P%"] = (uww_per_game["FG3M"] / uww_per_game["FG3A"] * 100).round(1)
    uww_per_game["FT%"] = (uww_per_game["FTM"] / uww_per_game["FTA"] * 100).round(1)
    uww_per_game["FG2M"] = uww_per_game["FGM"] - uww_per_game["FG3M"]
    uww_per_game["FG2A"] = uww_per_game["FGA"] - uww_per_game["FG3A"]
    uww_per_game["FG2%"] = (uww_per_game["FG2M"] / uww_per_game["FG2A"] * 100).round(1)

    # Map outcomes from schedule
    opp_outcome = get_opponent_outcomes(schedule, uww_per_game["opponent"].unique())
    uww_per_game["outcome"] = uww_per_game["opponent"].map(opp_outcome)

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
# Every advanced/derived metric added to the app gets one entry here -- both so coaches can hover/click for a
# plain-language definition wherever the stat is shown, and so there is a SINGLE source of truth for each
# formula (rather than the definition living only as a scattered code comment).
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
    STAT_GLOSSARY. Use for compact table/column headers where a full popover would be too heavy -- pairs with
    render_glossary_popover() below for a fuller, tap-friendly explanation of a whole section's stats."""
    entry = STAT_GLOSSARY.get(key)
    text = display_text if display_text is not None else key
    if not entry:
        return html.escape(text)
    tooltip = html.escape(f"{entry['label']}: {entry['definition']} Formula: {entry['formula']}")
    return f'<span title="{tooltip}" style="cursor:help;border-bottom:1px dotted #999;">{html.escape(text)}</span>'


def render_glossary_popover(keys: list, label: str = "ℹ️ What do these mean?") -> None:
    """Render a tap/click-friendly popover explaining a list of STAT_GLOSSARY stats -- the fuller-detail
    counterpart to glossary_span's hover tooltips, matching the existing 'KTV Category Reference' popover
    pattern already used elsewhere in this app. Use one of these at the top of any section that introduces new
    advanced stats, so a coach unfamiliar with a metric has a place to look it up without leaving the page."""
    with st.popover(label):
        for key in keys:
            entry = STAT_GLOSSARY.get(key)
            if not entry:
                continue
            st.markdown(f"**{entry['label']}** (`{key}`)")
            st.caption(f"{entry['definition']}  \nFormula: {entry['formula']}")


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


def compute_true_shooting(pts, fga, fta) -> float:
    """True Shooting % -- see STAT_GLOSSARY['TS%']. Returns 0 if there were no shooting attempts of any kind."""
    denom = 2 * (fga + 0.44 * fta)
    return (pts / denom * 100) if denom > 0 else 0


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


def extract_shot_mechanic(description) -> str:
    """Parse the shot-mechanic tag out of a video_description string (same tags the parser's video-tagging
    pipeline already uses -- see parser cell 114): catch-and-shoot vs. pull-up vs. a drive to the rim."""
    if pd.isna(description):
        return None
    d = str(description)
    if "No Dribble Jumper" in d:
        return "Catch-and-shoot"
    if "Dribble Jumper" in d:
        return "Pull-up off the dribble"
    if "To Basket" in d:
        return "Drive to the basket"
    return "Other"


def extract_contest(description) -> str:
    """Parse the defender-contest tag out of a video_description string (see parser cell 114)."""
    if pd.isna(description):
        return None
    d = str(description)
    if "Guarded" in d:
        return "Guarded"
    if "Open" in d:
        return "Open"
    return "N/A (drive, no contest tag)"


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
    return df["play_call"].where(_has_real_call, _regex_fallback)


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
    streak_str = f"{streak_count}-game {streak_label} streak" if streak_count > 1 else ""

    opp_record = str(record).strip() if pd.notna(record) and str(record).strip() else ""
    opp_streak_str = ""
    # If no record in schedule CSV, compute from opponent_schedules (only pre-UWW games)
    if not opp_record and short_opponent:
        opp_record, opp_streak_str = get_opponent_entering_record(short_opponent)

    # Build broadcast-style HTML banner with team logos
    uww_logo_b64 = find_logo_b64("UW-Whitewater")
    opp_display = short_opponent or full_opponent
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
    # at the top of the page), then Personnel, then Tools.
    _new_tab_stats, _new_tab_ktv, _new_tab_personnel, _new_tab_tools = st.tabs(["\U0001f4ca Stats & Analysis", "\U0001f511 Keys to Victory", "\U0001f465 Personnel", "\U0001f3ae Tools"])
    with _new_tab_stats:
        _new_stats_leaders_c = st.container()
        _new_stats_top5_c = st.container()
        _new_stats_comparable_c = st.container()
    with _new_tab_ktv:
        _new_ktv_container = st.container()
        _new_rec_container = st.container()
    with _new_tab_personnel:
        _new_personnel_roster_c = st.container()
        _new_personnel_scouting_c = st.container()
    with _new_tab_tools:
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
        # Filter box score to only include pre-upcoming games
        _played_opponents_short = set()
        for _, _row in played.iterrows():
            _short = resolve_short_opponent(_row["opponent"], short_names)
            if _short:
                _played_opponents_short.add(_short)
        box = box[box["opponent"].isin(_played_opponents_short)]
        uww_box = box[box["team"] == "UW-Whitewater"]
        num_uww_games = uww_box["opponent"].nunique() if not uww_box.empty else 1
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

        opp_display = short_opponent or full_opponent

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
            if uww.empty:
                return {}
            # Compute per-game averages
            games_per_player = uww.groupby("player")["opponent"].nunique()
            totals = uww.groupby("player").agg({"PTS": "sum", "REB": "sum", "AST": "sum", "STL": "sum", "BLK": "sum", "TO": "sum", "FGM": "sum", "FGA": "sum", "FTM": "sum", "FTA": "sum", "OREB": "sum", "DREB": "sum"}).reset_index()
            totals["games"] = totals["player"].map(games_per_player)
            totals["PPG"] = totals["PTS"] / totals["games"]
            totals["RPG"] = totals["REB"] / totals["games"]
            totals["APG"] = totals["AST"] / totals["games"]
            totals["FG_pct"] = (totals["FGM"] / totals["FGA"] * 100).round(1)
            totals["FT_pct"] = (totals["FTM"] / totals["FTA"] * 100).round(1)
            totals["DRPG"] = (totals["DREB"] / totals["games"]).round(1)
            totals["ORPG"] = (totals["OREB"] / totals["games"]).round(1)
            totals["TOPG"] = (totals["TO"] / totals["games"]).round(1)
            # Compute MPG from season stats (MIN column is already per-game)
            leaders = {}
            if not season_stats.empty and "PLAYER" in season_stats.columns and "MIN" in season_stats.columns:
                season_stats_mpg = season_stats.copy()
                season_stats_mpg["MIN_num"] = pd.to_numeric(season_stats_mpg["MIN"], errors="coerce")
                season_stats_mpg = season_stats_mpg[~season_stats_mpg["PLAYER"].isin(["Team Total", "Opponent"])]
                season_stats_mpg = season_stats_mpg.dropna(subset=["MIN_num"])
                # Only include players who appear in our PBP box score
                season_stats_mpg = season_stats_mpg[season_stats_mpg["PLAYER"].isin(totals["player"].tolist())]
            else:
                season_stats_mpg = pd.DataFrame()
            if not season_stats_mpg.empty:
                mpg_leader = season_stats_mpg.nlargest(1, "MIN_num").iloc[0]
                # NOTE: this counts games with a RECONSTRUCTED PLAY-BY-PLAY BOX SCORE for this player (i.e. how
                # many of this player's games have been video-tagged/PBP-parsed so far), not their real season
                # total games played -- PBP reconstruction is more labor-intensive than basic season-stat
                # scraping and can lag well behind how many games the team has actually played. Label it
                # explicitly as "tracked" so it doesn't read as (and get mistaken for) the player's true GP.
                _pbp_games = int(games_per_player.get(mpg_leader["PLAYER"], 0))
                _gp_sub = f"{_pbp_games} GP tracked" if _pbp_games > 0 else ""
                leaders["Minutes"] = {"name": mpg_leader["PLAYER"], "value": mpg_leader["MIN_num"], "sub": _gp_sub}
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
            if opp.empty:
                return {}
            leaders = {}
            # Minutes leader
            if "MIN" in opp.columns:
                opp_min = opp.copy()
                opp_min["MIN_num"] = pd.to_numeric(opp_min["MIN"], errors="coerce")
                opp_min = opp_min.dropna(subset=["MIN_num"])
                if not opp_min.empty:
                    min_leader = opp_min.nlargest(1, "MIN_num").iloc[0]
                    leaders["Minutes"] = {"name": min_leader["name"], "value": min_leader["MIN_num"], "sub": ""}
            # Points leader (PTS is already per-game in profiles)
            pts_leader = opp.nlargest(1, "PTS").iloc[0]
            fg_str = str(pts_leader.get("FG%", "")).replace("%", "").strip()
            ft_str = str(pts_leader.get("FT%", "")).replace("%", "").strip()
            fg_val = fg_str if fg_str and fg_str != "nan" else "-"
            ft_val = ft_str if ft_str and ft_str != "nan" else "-"
            leaders["Points"] = {"name": pts_leader["name"], "value": pts_leader["PTS"], "sub": f"{fg_val} FG%\n{ft_val} FT%"}
            # Rebounds leader (REB is per-game)
            reb_leader = opp.nlargest(1, "REB").iloc[0]
            leaders["Rebounds"] = {"name": reb_leader["name"], "value": reb_leader["REB"], "sub": ""}
            # Assists leader (AST/TO are SEASON TOTALS in this table, unlike PTS/REB -- divide by games_est)
            opp_copy = opp.copy()
            opp_copy["APG"] = opp_copy["AST"] / games_est
            ast_leader = opp_copy.nlargest(1, "APG").iloc[0]
            topg = ast_leader["TO"] / games_est
            leaders["Assists"] = {"name": ast_leader["name"], "value": ast_leader["APG"], "sub": f"{topg:.1f} TOPG"}
            # Steals leader (STL is a season total, divide by games_est)
            opp_copy["SPG"] = opp_copy["STL"] / games_est
            stl_leader = opp_copy.nlargest(1, "SPG").iloc[0]
            leaders["Steals"] = {"name": stl_leader["name"], "value": stl_leader["SPG"], "sub": ""}
            # Blocks leader (BLK is a season total, divide by games_est)
            opp_copy["BPG"] = opp_copy["BLK"] / games_est
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

        @st.dialog("Game Detail", width="large")
        def _show_last5_game_dialog(_game_key, _game_label, _source_table="uww_pbp_box_score", _team_a_hint="UW-Whitewater"):
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
            _gd_stat_cols = [c for c in ["PTS", "REB", "AST", "STL", "BLK", "TO", "PF"] if c in _gd_game_box.columns]
            _gd_rows = [{"Stat": _sc, _team_a: _gd_uww_side[_sc].sum(), _team_b: _gd_opp_side[_sc].sum()} for _sc in _gd_stat_cols]
            if {"FGM", "FGA"} <= set(_gd_game_box.columns):
                _u_fgm, _u_fga = _gd_uww_side["FGM"].sum(), _gd_uww_side["FGA"].sum()
                _o_fgm, _o_fga = _gd_opp_side["FGM"].sum(), _gd_opp_side["FGA"].sum()
                _gd_rows.append({"Stat": "FG%", _team_a: f"{100*_u_fgm/_u_fga:.1f}%" if _u_fga else "-", _team_b: f"{100*_o_fgm/_o_fga:.1f}%" if _o_fga else "-"})
            if {"FG3M", "FG3A"} <= set(_gd_game_box.columns):
                _u_3m, _u_3a = _gd_uww_side["FG3M"].sum(), _gd_uww_side["FG3A"].sum()
                _o_3m, _o_3a = _gd_opp_side["FG3M"].sum(), _gd_opp_side["FG3A"].sum()
                _gd_rows.append({"Stat": "3P%", _team_a: f"{100*_u_3m/_u_3a:.1f}%" if _u_3a else "-", _team_b: f"{100*_o_3m/_o_3a:.1f}%" if _o_3a else "-"})
            st.dataframe(pd.DataFrame(_gd_rows), hide_index=True, use_container_width=True)

            st.markdown("**Box Score**")
            _gd_compact_cols = [c for c in ["player", "MIN", "PTS", "REB", "AST", "STL", "TO", "FG%"] if c in _gd_game_box.columns]
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
            max_games = max(len(uww_all_games), len(opp_all_games), 1)
            rows_html = ""
            for i in range(max_games):
                uww_game = uww_all_games[i] if i < len(uww_all_games) else None
                opp_game = opp_all_games[i] if i < len(opp_all_games) else None
                rows_html += (
                    f'<div style="border:1px solid #eee;border-radius:8px;padding:10px 12px;margin-bottom:8px;">'
                    f'<div style="display:flex;align-items:center;justify-content:space-between;">'
                    f'<div style="text-align:left;flex:1;">{_game_cell_dlg(uww_game)}</div>'
                    f'<div style="text-align:right;flex:1;">{_game_cell_dlg(opp_game)}</div>'
                    f'</div></div>'
                )
            header_html = (
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding:0 4px;">'
                f'<span style="font-size:1.05rem;font-weight:700;color:#4E2A84;">UWW ({len(uww_all_games)} games)</span>'
                f'<span style="font-size:1.05rem;font-weight:700;color:#222;">{html.escape(get_team_abbreviation(opp_display))} ({len(opp_all_games)} games)</span>'
                f'</div>'
            )
            st.markdown(f'{header_html}{rows_html}', unsafe_allow_html=True)

        # Three columns: Season Leaders | Team Stats + All Stats button | Last Five Games
        _col_leaders, _col_stats, _col_l5 = st.columns(3)
        with _col_leaders:
            st.markdown(leaders_html, unsafe_allow_html=True)
            if uww_leaders.get("Minutes", {}).get("sub"):
                st.caption("\"GP tracked\" = games with a reconstructed play-by-play box score so far, not necessarily the player's full season game count -- video/PBP tagging can lag behind games actually played.")
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
                    f'<span style="font-size:0.85rem;font-weight:700;color:#4E2A84;">UWW (click for box score)</span>'
                    f'<span style="font-size:0.85rem;font-weight:700;color:#222;">{html.escape(get_team_abbreviation(opp_display))}</span>'
                    f'</div>', unsafe_allow_html=True,
                )
                _l5_max = max(len(uww_last5), len(opp_last5), 1)
                if _l5_max == 0 or (not uww_last5 and not opp_last5):
                    st.caption("No games available")
                for _l5_i in range(min(_l5_max, 5)):
                    _u_game = uww_last5[_l5_i] if _l5_i < len(uww_last5) else None
                    _o_game = opp_last5[_l5_i] if _l5_i < len(opp_last5) else None
                    _l5_c1, _l5_c2 = st.columns(2)
                    with _l5_c1:
                        if _u_game is not None:
                            _u_score = f"{int(_u_game['team_score'])}-{int(_u_game['opp_score'])}" if _u_game.get("team_score") is not None else ""
                            _u_loc = "@ " if "away" in str(_u_game.get("location", "")).lower() else "vs "
                            _u_opp_short_label = str(_u_game.get("opp_name", ""))
                            if len(_u_opp_short_label) > 16:
                                _u_opp_short_label = _u_opp_short_label[:14] + "..."
                            if st.button(f"{_u_game['outcome']} {_u_score} {_u_loc}{_u_opp_short_label}", key=f"l5_uww_btn_{_l5_i}", use_container_width=True):
                                _u_short = resolve_short_opponent(_u_game["opp_name"], _l5_short_names)
                                _show_last5_game_dialog(_u_short, f"UWW vs {_u_game['opp_name']} \u2014 {_u_game.get('date', '')}")
                        else:
                            st.caption("\u2014")
                    with _l5_c2:
                        if _o_game is not None:
                            _o_score = f"{int(_o_game['team_score'])}-{int(_o_game['opp_score'])}" if _o_game.get("team_score") is not None else ""
                            _o_loc = "@ " if "away" in str(_o_game.get("location", "")).lower() else "vs "
                            _o_opp_label = str(_o_game.get("opp_name", ""))
                            if len(_o_opp_label) > 16:
                                _o_opp_label = _o_opp_label[:14] + "..."
                            # Now reconstructed from the same shot-by-shot data already collected for the
                            # shot-selection analysis (uww_opponent_prior_games_box_score), not a separate
                            # live-scrape -- so these ARE clickable now, same as UWW's own results, wherever
                            # that reconstruction actually found data for this specific game.
                            _o_third_party_short = resolve_short_opponent(_o_game["opp_name"], _l5_opp_short_names)
                            if st.button(f"{_o_game['outcome']} {_o_score} {_o_loc}{_o_opp_label}", key=f"l5_opp_btn_{_l5_i}", use_container_width=True):
                                _show_last5_game_dialog(
                                    _o_third_party_short, f"{short_opponent} vs {_o_game['opp_name']} \u2014 {_o_game.get('date', '')}",
                                    _source_table="uww_opponent_prior_games_box_score", _team_a_hint=short_opponent,
                                )
                        else:
                            st.caption("\u2014")
                st.caption(f"{short_opponent}'s results are clickable when a box score has been reconstructed for that specific game -- some prior games may not have one yet (e.g. no local/live-scraped PBP data was available for that game).")
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
        """Convert 'First Last, First Last, ...' to 'Last, Last, ...' for compact display."""
        names = [n.strip() for n in str(lineup_str).split(",")]
        return ", ".join(parts[-1] if len(parts := n.split()) > 1 else n for n in names)

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
                parts = n.strip().split()
                players.add(parts[-1] if len(parts) > 1 else n.strip())
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
                    _uww_s = uww_agg.assign(_r=uww_agg["MIN"] / uww_agg["GP"].replace(0, float('nan')))
                elif metric_col == "EFF":
                    _uww_s = uww_agg[uww_agg["MIN"] >= 3.0].copy()
                    _uww_s["EFF"] = (_uww_s["+/-"] / _uww_s["MIN"].replace(0, float('nan'))).round(3)
                    _uww_s = _uww_s.assign(_r=_uww_s["EFF"])
                else:
                    _uww_s = uww_agg.assign(_r=uww_agg[metric_col] / uww_agg["MIN"].replace(0, float('nan')))
                uww_rows = _build_lineup_rows_html(_uww_s.sort_values("_r", ascending=False).drop(columns=["_r"]), metric_col, min_col="MIN")
            else:
                uww_rows = '<div style="font-size:0.82rem;color:#aaa;">No data</div>'
            if opp_lu is not None and not opp_lu.empty:
                if metric_col == "MIN":
                    _opp_s = opp_lu.assign(_r=opp_lu["MIN"] / opp_lu["GP"].replace(0, float('nan')))
                elif metric_col == "EFF":
                    _opp_s = opp_lu[opp_lu["MIN"] >= 3.0].copy()
                    _opp_s["EFF"] = (_opp_s["+/-"] / _opp_s["MIN"].replace(0, float('nan'))).round(3)
                    _opp_s = _opp_s.assign(_r=_opp_s["EFF"])
                else:
                    _opp_s = opp_lu.assign(_r=opp_lu[metric_col] / opp_lu["MIN"].replace(0, float('nan')))
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
        # Only include games before the upcoming game, and exclude Aurora (lineup columns swapped)
        _stints = _stints[_stints["opponent"].isin(_played_opponents_short - {"Aurora"})].copy()
        _stints["uww_pts"] = _stints["end_uww_score"] - _stints["start_prev_uww_score"]
        _uww_lu_agg = _stints.groupby("uww_lineup").agg(
            MIN=("stint_minutes", "sum"),
            PTS=("uww_pts", "sum"),
            plus_minus=("uww_margin_change", "sum"),
            GP=("opponent", "nunique")
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
                    _uww_s = uww_3man.assign(_r=uww_3man["MIN"] / uww_3man["GP"].replace(0, float('nan')))
                elif metric_col == "EFF":
                    _uww_s = uww_3man[uww_3man["MIN"] >= 5.0].copy()
                    _uww_s["EFF"] = (_uww_s["+/-"] / _uww_s["MIN"].replace(0, float('nan'))).round(3)
                    _uww_s = _uww_s.assign(_r=_uww_s["EFF"])
                else:
                    _uww_s = uww_3man.assign(_r=uww_3man[metric_col] / uww_3man["MIN"].replace(0, float('nan')))
                uww_rows = _build_lineup_rows_html(_uww_s.sort_values("_r", ascending=False).drop(columns=["_r"]), metric_col, min_col="MIN")
            else:
                uww_rows = '<div style="font-size:0.82rem;color:#aaa;">No data</div>'
            if opp_3man is not None and not opp_3man.empty:
                if metric_col == "MIN":
                    _opp_s = opp_3man.assign(_r=opp_3man["MIN"] / opp_3man["GP"].replace(0, float('nan')))
                elif metric_col == "EFF":
                    _opp_s = opp_3man[opp_3man["MIN"] >= 5.0].copy()
                    _opp_s["EFF"] = (_opp_s["+/-"] / _opp_s["MIN"].replace(0, float('nan'))).round(3)
                    _opp_s = _opp_s.assign(_r=_opp_s["EFF"])
                else:
                    _opp_s = opp_3man.assign(_r=opp_3man[metric_col] / opp_3man["MIN"].replace(0, float('nan')))
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
                })
        if _3man_records:
            _3man_df = pd.DataFrame(_3man_records)
            _uww_3man_agg = _3man_df.groupby("lineup").agg(
                MIN=("stint_minutes", "sum"),
                PTS=("uww_pts", "sum"),
                plus_minus=("uww_margin_change", "sum"),
                GP=("opponent", "nunique")
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
                        _s = uww_agg.assign(_r=uww_agg["MIN"] / uww_agg["GP"].replace(0, float('nan')))
                    elif metric_col == "EFF":
                        _s = uww_agg[uww_agg["MIN"] >= min_thresh_eff].copy()
                        _s["EFF"] = (_s["+/-"] / _s["MIN"].replace(0, float('nan'))).round(3)
                        _s = _s.assign(_r=_s["EFF"])
                    else:
                        _s = uww_agg.assign(_r=uww_agg[metric_col] / uww_agg["MIN"].replace(0, float('nan')))
                    uww_rows = _build_lineup_rows_html(_s.sort_values("_r", ascending=False).drop(columns=["_r"]), metric_col, min_col="MIN")
                else:
                    uww_rows = '<div style="font-size:0.82rem;color:#aaa;">No data</div>'
                if opp_lu is not None and not opp_lu.empty:
                    if metric_col == "MIN":
                        _s = opp_lu.assign(_r=opp_lu["MIN"] / opp_lu["GP"].replace(0, float('nan')))
                    elif metric_col == "EFF":
                        _s = opp_lu[opp_lu["MIN"] >= min_thresh_eff].copy()
                        _s["EFF"] = (_s["+/-"] / _s["MIN"].replace(0, float('nan'))).round(3)
                        _s = _s.assign(_r=_s["EFF"])
                    else:
                        _s = opp_lu.assign(_r=opp_lu[metric_col] / opp_lu["MIN"].replace(0, float('nan')))
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

    # Scouting summary card (right): Core UWW players + Vulnerabilities + Counter-Lineups
    def _build_scouting_summary_html(uww_5man, uww_3man, opp_lu_df, opp_name, stints_df):
        """Build scouting summary card with core players, vulnerabilities, and counter-lineups."""
        sections = ""

        # --- CORE UWW PLAYERS (combined 5-man + 3-man = 8 metrics) ---
        from collections import Counter as _CoreCounter
        _all_tops = []
        if uww_5man is not None and not uww_5man.empty:
            _eff5 = uww_5man[uww_5man["MIN"] >= 3.0].copy()
            _eff5["EFF"] = _eff5["+/-"] / _eff5["MIN"].replace(0, float('nan'))
            _all_tops.extend([
                _find_core_players(uww_5man.sort_values("MIN", ascending=False)),
                _find_core_players(uww_5man.sort_values("PTS", ascending=False)),
                _find_core_players(uww_5man.sort_values("+/-", ascending=False)),
                _find_core_players(_eff5.sort_values("EFF", ascending=False)),
            ])
        if uww_3man is not None and not uww_3man.empty:
            _eff3 = uww_3man[uww_3man["MIN"] >= 5.0].copy()
            _eff3["EFF"] = _eff3["+/-"] / _eff3["MIN"].replace(0, float('nan'))
            _all_tops.extend([
                _find_core_players(uww_3man.sort_values("MIN", ascending=False)),
                _find_core_players(uww_3man.sort_values("PTS", ascending=False)),
                _find_core_players(uww_3man.sort_values("+/-", ascending=False)),
                _find_core_players(_eff3.sort_values("EFF", ascending=False)),
            ])
        _core_html = ""
        if _all_tops:
            _player_counts = _CoreCounter()
            for _pset in _all_tops:
                for _p in _pset:
                    _player_counts[_p] += 1
            _core_combined = sorted([(_p, _c) for _p, _c in _player_counts.items() if _c >= 2], key=lambda x: -x[1])[:5]
            if _core_combined:
                for _p, _c in _core_combined:
                    _core_html += f'<div style="font-size:0.82rem;margin:2px 0;"><strong>{html.escape(_p)}</strong> <span style="color:#777;">({_c}/8 metrics)</span></div>'
        if _core_html:
            sections += (
                f'<div style="border:1px solid #eee;border-radius:8px;padding:10px 12px;margin-bottom:8px;">'
                f'<div style="font-size:0.85rem;font-weight:700;color:#4E2A84;margin-bottom:6px;">\u2B50 UWW CORE PLAYERS</div>'
                f'<div style="font-size:0.75rem;color:#888;margin-bottom:4px;">Players in top-3 across 5-man &amp; 3-man metrics</div>'
                f'{_core_html}</div>'
            )

        # --- OPPONENT VULNERABILITIES ---
        vuln_rows = ""
        if opp_lu_df is not None and not opp_lu_df.empty:
            opp_v = opp_lu_df.copy()
            opp_v["TO_rate"] = (opp_v["TO"] / opp_v["MIN"] * 40).round(1) if "TO" in opp_v.columns else 0
            opp_v["FG%"] = pd.to_numeric(opp_v["FG%"], errors="coerce").fillna(0) if "FG%" in opp_v.columns else 0
            # Worst +/- lineups (min 3 min)
            worst_pm = opp_v[opp_v["MIN"] >= 3.0].nsmallest(3, "+/-")
            vuln_rows += '<div style="font-size:0.75rem;color:#888;margin-bottom:2px;">Worst +/- lineups:</div>'
            for _, r in worst_pm.iterrows():
                ln = _last_names(r["lineup"])
                fg = f", {r['FG%']:.0f}% FG" if r.get('FG%', 0) > 0 else ""
                vuln_rows += f'<div style="font-size:0.8rem;margin:2px 0;"><strong style="color:#c62828;">{r["+/-"]:+.1f}</strong> in {r["MIN"]:.1f} min{fg} \u2014 {html.escape(ln)}</div>'
            # Highest turnover rate
            if "TO" in opp_v.columns:
                high_to = opp_v[opp_v["MIN"] >= 3.0].nlargest(2, "TO_rate")
                if not high_to.empty:
                    vuln_rows += '<div style="font-size:0.75rem;color:#888;margin:4px 0 2px;">Highest TO rate (per 40 min):</div>'
                    for _, r in high_to.iterrows():
                        ln = _last_names(r["lineup"])
                        vuln_rows += f'<div style="font-size:0.8rem;margin:2px 0;"><strong style="color:#c62828;">{r["TO_rate"]:.1f}</strong> TO/40 \u2014 {html.escape(ln)}</div>'
        if not vuln_rows:
            vuln_rows = '<div style="font-size:0.8rem;color:#aaa;">No opponent lineup data</div>'
        sections += (
            f'<div style="border:1px solid #eee;border-radius:8px;padding:10px 12px;margin-bottom:8px;">'
            f'<div style="font-size:0.85rem;font-weight:700;color:#555;margin-bottom:4px;">\U0001F534 {html.escape(opp_name)} Vulnerabilities</div>'
            f'{vuln_rows}</div>'
        )

        # --- COUNTER-LINEUP RECOMMENDATIONS ---
        counter_rows = ""
        if opp_lu_df is not None and not opp_lu_df.empty and uww_5man is not None and not uww_5man.empty:
            opp_top = opp_lu_df.nlargest(1, "MIN")
            if not opp_top.empty:
                opp_top_lineup = _last_names(opp_top.iloc[0]["lineup"])
                best_uww = uww_5man[uww_5man["MIN"] >= 3.0].nlargest(3, "+/-")
                counter_rows += f'<div style="font-size:0.75rem;color:#888;margin-bottom:2px;">vs {html.escape(opp_name)}\'s top lineup ({html.escape(opp_top_lineup)}):</div>'
                for _, r in best_uww.iterrows():
                    ln = _last_names(r["lineup"])
                    rate = r["+/-"] / r["MIN"] if r["MIN"] > 0 else 0
                    counter_rows += f'<div style="font-size:0.8rem;margin:2px 0;"><strong style="color:#2e7d32;">{rate:+.2f}</strong>/min ({r["+/-"]:+.1f} total) \u2014 {html.escape(ln)}</div>'
        if not counter_rows:
            counter_rows = '<div style="font-size:0.8rem;color:#aaa;">Need opponent lineup data</div>'
        sections += (
            f'<div style="border:1px solid #eee;border-radius:8px;padding:10px 12px;margin-bottom:8px;">'
            f'<div style="font-size:0.85rem;font-weight:700;color:#555;margin-bottom:4px;">\U0001F3AF Counter-Lineup Recommendations</div>'
            f'{counter_rows}</div>'
        )

        return (
            f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;width:100%;">'
            f'<div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;margin-bottom:8px;">LINEUP SCOUTING</div>'
            f'{sections}</div>'
        )

    _combined_lineups_html = _build_combined_lineups_card(_uww_lu_agg, _opp_lu, _uww_3man_agg, _opp_3man_agg, opp_display)
    _scouting_html = _build_scouting_summary_html(_uww_lu_agg, _uww_3man_agg, _opp_lu, opp_display, _stints)

    with _new_stats_top5_c:
        # Spacing between sections above and lineup row below
        st.markdown('<div style="margin-top:2.5rem;"></div>', unsafe_allow_html=True)

        # Render: Lineup toggle (5-Man or 3-Man) | Lineup Scouting in one row
        if "lineup_view" not in st.session_state:
            st.session_state.lineup_view = "5-Man Lineups"
        _current_title = "TOP 5-MAN LINEUPS" if st.session_state.lineup_view == "5-Man Lineups" else "TOP 3-MAN COMBINATIONS"
        _other_view = "3-Man Combinations" if st.session_state.lineup_view == "5-Man Lineups" else "5-Man Lineups"
        _active_lineup_html = _lineups_html if st.session_state.lineup_view == "5-Man Lineups" else _3man_html
        # Strip outer card wrapper (border/padding) and title — we'll use st.container for the border
        import re as _re
        _active_lineup_html = _re.sub(r'<div style="font-weight:800;font-size:1\.05rem;letter-spacing:0\.5px;margin-bottom:8px;">TOP [53]-MAN [A-Z]+</div>', '', _active_lineup_html, count=1)
        _active_lineup_html = _re.sub(r'^<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;width:100%;margin:1\.5rem 0 0\.75rem;">', '<div style="zoom:1.1;">', _active_lineup_html, count=1)
        _col_lu, _col_sc = st.columns([1.4, 0.8])
        with _col_lu:
            with st.container(border=True):
                # Center the toggle button via CSS
                st.markdown('<style>[data-testid="stButton"] button[kind="secondary"] { display: block; margin: 0 auto; }</style>', unsafe_allow_html=True)
                _left_pad, _btn_col, _right_pad = st.columns([1, 2, 1])
                with _btn_col:
                    if st.button(f"{_current_title}  ⇄", key="lineup_toggle_btn", use_container_width=True):
                        st.session_state.lineup_view = _other_view
                        st.rerun()
                st.markdown(_active_lineup_html, unsafe_allow_html=True)
        with _col_sc:
            # Lineup Scouting -- UWW Core Players, {Opponent} Vulnerabilities, Counter-Lineup Recommendations.
            # Back to sitting alongside the lineup toggle, same as originally, rather than stacked below it.
            st.markdown(f'<div style="zoom:1.1;">{_scouting_html}</div>', unsafe_allow_html=True)


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
                        stat_cols = ["PTS", "REB", "AST", "STL", "BLK", "TO", "FG%", "3P%"]
                        s_data = [{"Stat": sc, "Avg": str(p.get(sc))} for sc in stat_cols if pd.notna(p.get(sc)) and str(p.get(sc)).strip()]
                        if s_data:
                            st.dataframe(pd.DataFrame(s_data), hide_index=True, use_container_width=True)
                        else:
                            st.caption("No season stats available.")
                    else:
                        st.caption("No season stats available.")

                with st.container(border=True):
                    st.markdown("**Comparable Player**")
                    if not _comparisons.empty:
                        comp_match = _comparisons[_comparisons["target_player"] == player_name]
                        if not comp_match.empty:
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



    with _new_stats_comparable_c:
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">COMPARABLE OPPONENTS</div></div>', unsafe_allow_html=True)
        _team_totals_co = load_table("uww_opponent_team_totals")
        if _team_totals_co.empty or not short_opponent or short_opponent not in _team_totals_co["opponent"].values:
            st.info("Comparable opponent data will be available once previous game data is collected for this opponent.")
        else:
            _numeric_cols_co = [c for c in _team_totals_co.columns if c != "opponent" and pd.api.types.is_numeric_dtype(_team_totals_co[c])]
            if not _numeric_cols_co:
                st.info("Not enough team-level stats recorded yet to compare opponents.")
            else:
                _co_df = _team_totals_co.dropna(subset=_numeric_cols_co, how="all").copy()
                # Only compare against opponents UWW has actually PLAYED, so the comparison comes with a real result.
                _co_outcomes = get_opponent_outcomes(schedule, _co_df["opponent"].unique())
                _co_df = _co_df[_co_df["opponent"].isin(_co_outcomes.keys()) & (_co_df["opponent"] != short_opponent)]
                if _co_df.empty:
                    st.info("No previously-played opponents with recorded team stats to compare against yet.")
                else:
                    _target_row = _team_totals_co[_team_totals_co["opponent"] == short_opponent].iloc[0]
                    # Min-max normalize each stat across the candidate pool + the target, so no single stat (e.g. a
                    # PPG figure in the 60-90 range) dominates the distance purely because of its raw scale.
                    _all_vals_co = pd.concat(
                        [_co_df[_numeric_cols_co], _target_row[_numeric_cols_co].to_frame().T], ignore_index=True
                    ).astype(float)
                    _mins_co = _all_vals_co.min()
                    _ranges_co = (_all_vals_co.max() - _mins_co).replace(0, 1)
                    _target_norm_co = (_target_row[_numeric_cols_co].astype(float) - _mins_co) / _ranges_co

                    def _co_distance(row):
                        row_norm = (row[_numeric_cols_co].astype(float) - _mins_co) / _ranges_co
                        return float(((row_norm - _target_norm_co) ** 2).sum() ** 0.5)

                    _co_df["_similarity_dist"] = _co_df.apply(_co_distance, axis=1)
                    _top_similar = _co_df.nsmallest(min(3, len(_co_df)), "_similarity_dist")

                    st.caption(
                        f"Other scouted opponents whose team-level stats ({', '.join(_numeric_cols_co)}) most closely "
                        f"resemble {esc(short_opponent)}'s this season — with UWW's actual result against each, as a "
                        f"rough style proxy for how {esc(short_opponent)} might play."
                    )
                    _co_cols = st.columns(len(_top_similar))
                    for _ci, (_, _cr) in enumerate(_top_similar.iterrows()):
                        with _co_cols[_ci]:
                            _co_name = _cr["opponent"]
                            _co_outcome = _co_outcomes.get(_co_name, "-")
                            _co_color = "#2e7d32" if _co_outcome == "W" else "#c62828"
                            _co_game = played[played["opponent"].astype(str).str.startswith(_co_name)] if not played.empty else pd.DataFrame()
                            _co_score_str = ""
                            if not _co_game.empty:
                                _g = _co_game.iloc[0]
                                if pd.notna(_g.get("team_score")) and pd.notna(_g.get("opponent_score")):
                                    _co_score_str = f"{int(_g['team_score'])}-{int(_g['opponent_score'])}"
                            with st.container(border=True):
                                st.markdown(f"**{esc(_co_name)}**")
                                st.markdown(
                                    f'<span style="color:{_co_color};font-weight:700;">{esc(_co_outcome)}</span> {esc(_co_score_str)}',
                                    unsafe_allow_html=True,
                                )
                                st.caption(f"Similarity score: {_cr['_similarity_dist']:.2f} (lower = more similar)")


    with _new_tools_proj_c:
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">PROJECTED BOX SCORE</div></div>', unsafe_allow_html=True)
        uww_proj = load_table("uww_projected_box_score")
        opp_proj = load_table("uww_opponent_projected_box_score")  # was mismatched to a nonexistent "aurora_projected_box_score" file — this is the name the parser notebook actually exports (see parser cell 128)

        if uww_proj.empty or opp_proj.empty:
            st.info("Projected box score not available yet for this opponent.")
        else:
            proj_uww_total = uww_proj["projected_PTS"].sum()
            proj_opp_total = opp_proj["projected_PTS"].sum()
            pcol1, pcol2, pcol3 = st.columns(3)
            pcol1.metric("Projected UWW", f"{proj_uww_total:.0f}")
            pcol2.metric(f"Projected {short_opponent}", f"{proj_opp_total:.0f}")
            pcol3.metric("Projected margin", f"{proj_uww_total - proj_opp_total:+.0f}")
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
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">\U0001f511 KEYS TO VICTORY</div></div>', unsafe_allow_html=True)
        with st.popover("\u2139\ufe0f What is this?"):
            st.markdown(
                "Everything the staff and the data have on this opponent, combined into one list -- "
                "pre-computed data-driven keys, the staff's own written scouting report (Keys to "
                "Victory, Team Strengths, the full game plan), lineup scouting, and season-stat-based "
                "recommendations. Tap the \u2753 next to any item for the reasoning and numbers behind it."
            )

        def _build_printable_game_plan_html(opp_name: str, opp_plan_df: pd.DataFrame) -> str:
            """Self-contained, printable one-pager (Keys to Victory, Team Strengths, and the full offensive/
            defensive game plan) built from the same uww_opponent_game_plans rows already rendered on this page
            -- for a coach to print or hand to players, rather than only being viewable on-screen."""
            sections_html = ""
            priority_topics = ["KEYS TO VICTORY", "TEAM STRENGTHS"]
            for topic in priority_topics:
                rows = opp_plan_df[opp_plan_df["topic"] == topic]
                if rows.empty:
                    continue
                notes = str(rows.iloc[0]["notes"])
                items = [html.escape(re.sub(r"^\d+\.\s*", "", n.strip())) for n in notes.split("|") if n.strip()]
                sections_html += f"<h2>{html.escape(topic.title())}</h2><ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"
            other_rows = opp_plan_df[~opp_plan_df["topic"].isin(priority_topics)]
            if not other_rows.empty:
                sections_html += "<h2>Full Game Plan</h2>"
                for category in other_rows["category"].unique():
                    group = other_rows[other_rows["category"] == category]
                    sections_html += f"<h3>{html.escape(str(category))}</h3>"
                    for _, r in group.iterrows():
                        notes = str(r["notes"])
                        items = [html.escape(n.strip()) for n in notes.split("|") if n.strip()] if "|" in notes else [html.escape(notes)]
                        sections_html += f"<p><strong>{html.escape(str(r['topic']))}</strong></p><ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"
            return f"""<!DOCTYPE html>
    <html><head><meta charset="utf-8"><title>Game Plan vs {html.escape(opp_name)}</title>
    <style>
    body {{ font-family: Georgia, serif; max-width: 800px; margin: 2rem auto; color: #222; }}
    h1 {{ color: #4E2A84; border-bottom: 3px solid #4E2A84; padding-bottom: 8px; }}
    h2 {{ color: #4E2A84; margin-top: 1.5rem; }}
    h3 {{ color: #333; margin-top: 1rem; }}
    li {{ margin-bottom: 4px; }}
    @media print {{ body {{ margin: 0.5in; }} }}
    </style></head>
    <body>
    <h1>UW-Whitewater vs {html.escape(opp_name)} — Game Plan</h1>
    {sections_html}
    </body></html>"""

        _util_c1, _util_c2 = st.columns(2)
        with _util_c1:
            if report_path and os.path.exists(report_path):
                with open(report_path, "rb") as pdf_file:
                    st.download_button(
                        label="\U0001f4c4 Download Scouting Report PDF", data=pdf_file,
                        file_name=f"{short_opponent}_Scouting_Report.pdf", mime="application/pdf",
                        key=f"pdf_download_{short_opponent}", use_container_width=True,
                    )
        with _util_c2:
            try:
                _u_game_plans = load_table("uww_opponent_game_plans")
                _u_opp_plan = _u_game_plans[_u_game_plans["opponent"] == short_opponent] if not _u_game_plans.empty and short_opponent else pd.DataFrame()
                if not _u_opp_plan.empty:
                    st.download_button(
                        label="\U0001f5a8\ufe0f Print / export game plan",
                        data=_build_printable_game_plan_html(short_opponent, _u_opp_plan),
                        file_name=f"{short_opponent}_Game_Plan.html", mime="text/html",
                        key=f"gameplan_export_new_{short_opponent}", use_container_width=True,
                        help="Downloads a printable one-pager -- open it and use your browser's Print dialog to hand it to players.",
                    )
            except Exception:
                pass

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
                _ls_worst = _opp_lu[_opp_lu["MIN"] >= 3.0].nsmallest(1, "+/-")
                if not _ls_worst.empty:
                    _ls_wr = _ls_worst.iloc[0]
                    _keys.append(("\U0001f512", f"Attack {short_opponent}'s {_last_names(_ls_wr['lineup'])} lineup", f"{_ls_wr['+/-']:+.1f} in {_ls_wr['MIN']:.1f} min", "Their worst net-rating lineup with real minutes this season.", "Lineup Scouting"))
            if _opp_lu is not None and not _opp_lu.empty and _uww_lu_agg is not None and not _uww_lu_agg.empty:
                _ls_opp_top = _opp_lu.nlargest(1, "MIN")
                _ls_best_uww = _uww_lu_agg[_uww_lu_agg["MIN"] >= 3.0].nlargest(1, "+/-")
                if not _ls_opp_top.empty and not _ls_best_uww.empty:
                    _ls_bu = _ls_best_uww.iloc[0]
                    _keys.append(("\U0001f512", f"Counter with {_last_names(_ls_bu['lineup'])}", f"{_ls_bu['+/-']:+.1f} in {_ls_bu['MIN']:.1f} min", f"Best UWW lineup by net rating vs. {short_opponent}'s most-used lineup ({_last_names(_ls_opp_top.iloc[0]['lineup'])}).", "Lineup Scouting"))
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
                    _ss_best = _ss_grouped.nlargest(1, "FG%").iloc[0]
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
                            _ss_play_txt = f'"{_ss_top_call}" generates it most often ({int((_ss_calls == _ss_top_call).sum())}x)'

                    _ss_parts = [p for p in [_ss_lineup_txt, _ss_play_txt] if p]
                    _ss_reason = " -- ".join(_ss_parts) if _ss_parts else "Not enough lineup/play-call data linked to these shots yet to say which lineup or play generates them most."
                    _keys.append((
                        "\U0001f3c0",
                        f"UWW Best Offensive Shot Selection & Quality: {_ss_best_mechanic}, {_ss_best_contest}",
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

                    # Cross-reference against UWW's OWN season-wide shot data (all games, not scoped to
                    # having already played this opponent) for that SAME shot type, to find which lineup and
                    # play call already generates it most for UWW.
                    _aw_uww_all = load_table("uww_pbp_events")
                    _aw_uww_shots = _aw_uww_all[
                        (_aw_uww_all["team"] == "UW-Whitewater") & (_aw_uww_all["event_type"].isin(["made_shot", "missed_shot"]))
                    ].copy() if not _aw_uww_all.empty else pd.DataFrame()
                    _aw_uww_shots = _aw_uww_shots[_aw_uww_shots["video_description"].notna()] if not _aw_uww_shots.empty else _aw_uww_shots
                    _aw_lineup_txt, _aw_play_txt = None, None
                    if not _aw_uww_shots.empty:
                        _aw_uww_shots["_mechanic"] = _aw_uww_shots["video_description"].apply(extract_shot_mechanic)
                        _aw_uww_shots["_contest"] = _aw_uww_shots["video_description"].apply(extract_contest)
                        _aw_uww_shots["_make"] = _aw_uww_shots["event_type"] == "made_shot"
                        _aw_match_rows = _aw_uww_shots[(_aw_uww_shots["_mechanic"] == _aw_best_mechanic) & (_aw_uww_shots["_contest"] == _aw_best_contest)]

                        if "uww_lineup" in _aw_match_rows.columns:
                            _aw_lu_rows = _aw_match_rows[_aw_match_rows["uww_lineup"].notna()]
                            if not _aw_lu_rows.empty:
                                _aw_lu_grouped = _aw_lu_rows.groupby("uww_lineup").agg(Attempts=("_make", "count"), Makes=("_make", "sum")).reset_index()
                                _aw_lu_grouped = _aw_lu_grouped[_aw_lu_grouped["Attempts"] >= 3]
                                if not _aw_lu_grouped.empty:
                                    _aw_lu_grouped["FG%"] = 100 * _aw_lu_grouped["Makes"] / _aw_lu_grouped["Attempts"]
                                    _aw_best_lu = _aw_lu_grouped.nlargest(1, "FG%").iloc[0]
                                    _aw_lineup_txt = f"{_last_names(_aw_best_lu['uww_lineup'])} gets it best for us ({int(_aw_best_lu['Makes'])}/{int(_aw_best_lu['Attempts'])}, {_aw_best_lu['FG%']:.0f}%)"

                        if "coach_note" in _aw_match_rows.columns:
                            _aw_calls = resolve_play_calls(_aw_match_rows).dropna()
                            if not _aw_calls.empty:
                                _aw_top_call = _aw_calls.value_counts().idxmax()
                                _aw_play_txt = f'"{_aw_top_call}" generates it most often for us ({int((_aw_calls == _aw_top_call).sum())}x)'

                    _aw_parts = [p for p in [_aw_lineup_txt, _aw_play_txt] if p]
                    _aw_reason = " -- ".join(_aw_parts) if _aw_parts else "Not enough UWW lineup/play-call data linked to this shot type yet to say which lineup or play generates it most for us."
                    _keys.append((
                        "\U0001f3af",
                        f"Attack Opponent Worst Offensive Shot Selection & Quality: {_aw_best_mechanic}, {_aw_best_contest}",
                        f"Opponents shot {int(_aw_best['Makes'])}/{int(_aw_best['Attempts'])} ({_aw_best['FG%']:.0f}%) on this vs. {short_opponent}, across {_aw_n_opponents} team(s) they played before UWW",
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
                        f"{short_opponent}'s high-volume look: {_dv_top['_mechanic']}, {_dv_top['_contest']}",
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
                pattern = r"(?<![\d.])" + re.escape(keyword) + r"(?![\d.])"
            else:
                pattern = r"\b" + re.escape(keyword) + r"\b"
            return re.search(pattern, text_lower) is not None

        def _match_categories(text):
            text_lower = str(text).lower()
            matched = []
            for _cat, _details in KTV_CATEGORY_REFERENCE.items():
                if _cat not in _valid_cats:
                    continue
                for _kw in [_kw.strip() for _kw in _details["keywords"].split(",")]:
                    if _kw and _keyword_matches(_kw, text_lower):
                        if _cat not in matched:
                            matched.append(_cat)
                        break
            return matched

        def _detect_side(text):
            text_lower = str(text).lower()
            sides_found = set()
            for phrase, side in PHRASE_SIDE.items():
                if phrase and _keyword_matches(phrase, text_lower):
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
                _ag_sum = _ag_calls.groupby("play_call").agg(Makes=("_mk", "sum"), Attempts=("_at", "sum")).reset_index()
                _ag_sum = _ag_sum[_ag_sum["Attempts"] >= 2]
                if not _ag_sum.empty:
                    _ag_sum["FG%"] = 100 * _ag_sum["Makes"] / _ag_sum["Attempts"]
                    _ag_best = _ag_sum.nlargest(1, "FG%").iloc[0]
                    _at_a_glance.append(("\U0001f3c0 Top Play", str(_ag_best["play_call"]), f"Best make rate among plays with 2+ tracked attempts this season: {int(_ag_best['Makes'])}/{int(_ag_best['Attempts'])} ({_ag_best['FG%']:.0f}%)."))
                    _card_data["plays"] = _ag_sum
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
                if _ag_opp_ppg is not None and _ag_opp_allowed is not None:
                    _ag_style = "Push Tempo" if _ag_opp_allowed > _ag_opp_ppg else "Slow It Down"
                    _at_a_glance.append(("\u23f1\ufe0f Style", _ag_style, f"UWW season pace: {_ag_pace_d['Pace']:.1f} poss/game. {esc(short_opponent)}: {_ag_opp_ppg:.1f} PPG, allows {_ag_opp_allowed:.1f}."))
                    _card_data["pace_style"] = (_ag_pace_d, _ag_opp_ppg, _ag_opp_allowed, _ag_style)
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
                    _ag_bench_sum = _ag_bench_sum[_ag_bench_sum["GP"] >= 3]
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
        def _render_plays_card(_n):
            st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">{_n}. \U0001f3c0 Plays to Lean On</span>{_source_badge_html("Data-Driven")}</div>', unsafe_allow_html=True)
            _fp_plays = _card_data["plays"]
            _fp_go_to = _fp_plays.nlargest(3, "FG%")
            for _, _r in _fp_go_to.iterrows():
                st.markdown(f"- **{_r['play_call']}** -- {int(_r['Makes'])}/{int(_r['Attempts'])} ({_r['FG%']:.0f}%) this season")
            _fp_cold = _fp_plays.nsmallest(2, "FG%")
            _fp_cold = _fp_cold[~_fp_cold["play_call"].isin(_fp_go_to["play_call"])]
            if not _fp_cold.empty:
                st.markdown("**Use sparingly:**")
                for _, _r in _fp_cold.iterrows():
                    st.markdown(f"- {_r['play_call']} -- {int(_r['Makes'])}/{int(_r['Attempts'])} ({_r['FG%']:.0f}%)")
            st.caption("Play call names are a best-effort extraction from coach notes (see the Analytics page for the full breakdown and how it's parsed).")
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
                st.markdown("They give up more than they score on average -- **push tempo** and get into transition before their defense sets.")
            else:
                st.markdown("They're stingier than their own offense -- a **half-court, execution-first** approach may serve better than trying to speed them up.")
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
            "plays": ("Offensive Efficiency", _render_plays_card),
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
            for _icon, _headline, _caption, _reason, _source in _keys:
                _match_text = f"{_headline} {_caption or ''} {_reason or ''}"
                _cats = _match_categories(_match_text)
                _side = _detect_side(_match_text)
                if _cats:
                    _grouped.setdefault(_cats[0], []).append((_icon, _headline, _caption, _reason, _cats, _side, _source))
                else:
                    _ungrouped.append((_icon, _headline, _caption, _reason, [], _side, _source))

            # Stable category order: whichever order they're defined in KTV_CATEGORY_REFERENCE, skipping
            # any category nothing matched this game.
            _cat_order = [c for c in KTV_CATEGORY_REFERENCE if c in _grouped or c in _cards_by_category]

            def _render_key_item(_n, _icon, _headline, _caption, _reason, _cats, _side, _source):
                # No per-item category badge -- the section header above already names the category, so
                # repeating it on every item was redundant. Side (UWW/OPP) badges removed too, per request.
                st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">{_n}. {_icon} {html.escape(_headline)}</span>{_source_badge_html(_source)}</div>', unsafe_allow_html=True)
                if _caption:
                    st.caption(_caption)
                if _reason:
                    st.markdown(f"_{_reason}_")
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
            _cs_prior_opponent_shortnames = _cs_uww_box_all["opponent"].unique().tolist() if not _cs_uww_box_all.empty else []
            _cs_prior_opponent_shortnames.sort(key=len, reverse=True)  # longest-first so the most specific match wins
            _cs_prior_opponents = {
                resolve_short_opponent(_po, _cs_prior_opponent_shortnames)
                for _po in played["opponent"].dropna()
            } - {None}
            _cs_uww_side = _cs_uww_side_all[_cs_uww_side_all["opponent"].isin(_cs_prior_opponents)] if _cs_prior_opponents else _cs_uww_side_all.iloc[0:0]
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
                    # Opponent side is turnovers THEY FORCE (their own STL, the same forces-turnovers proxy
                    # already used by the Turnover-Forcing Opportunity card elsewhere on this page) -- not
                    # their own turnovers committed, which isn't a relevant comparison for UWW's own ball
                    # security. Previously showed the opponent's own TO/gm here, which answered a different
                    # question than the one this category is actually about.
                    o = pd.to_numeric(_cs_opp_prof["STL"], errors="coerce").sum() / _cs_opp_games if not _cs_opp_prof.empty and "STL" in _cs_opp_prof.columns and _cs_opp_games > 0 else None
                    return (f"UWW turnovers/gm: {u:.1f}" if u is not None else None, f"{short_opponent} turnovers forced/gm: {o:.1f}" if o is not None else None)
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
                "Scoring Inside", "Field Goal Efficiency", "Offensive Efficiency",
            }
            _DEFENSE_CATS = {
                "Rebounding", "Fouls / Discipline", "Paint Protection / Blocks",
                "Perimeter Defense / Ball Pressure/ Create Turnovers", "Defensive Efficiency",
            }

            def _render_cat_expander(_cat):
                _cat_items = _grouped.get(_cat, [])
                _cat_cards = _cards_by_category.get(_cat, [])
                _n_items = len(_cat_items) + len(_cat_cards)
                with st.expander(f"{_cat} \u2014 {_n_items} item{'s' if _n_items != 1 else ''}", expanded=False):
                    _cat_has_gp = bool(_game_plan_by_cat.get(_cat))
                    if _cat_has_gp:
                        if st.button("\U0001f4cb Game Plan", key=f"gameplan_btn_{_cat}"):
                            _show_game_plan_dialog(_cat)
                    _cs_line = _category_stat_line(_cat)
                    if _cs_line and (_cs_line[0] or _cs_line[1]):
                        st.caption("  |  ".join(x for x in _cs_line if x))
                    for _n, (_icon, _headline, _caption, _reason, _cats, _side, _source) in enumerate(_cat_items, start=1):
                        _render_key_item(_n, _icon, _headline, _caption, _reason, _cats, _side, _source)

                    # Full Game Plan Recommendation card(s) tagged to this same category -- continuing the
                    # SAME numbered-item formatting as the keys above (numbered header, source badge, no
                    # bordered box), instead of a separate boxed-off "card" sitting apart from the list.
                    for _ci, _renderer in enumerate(_cat_cards):
                        _renderer(len(_cat_items) + _ci + 1)

            _offense_order = [c for c in _cat_order if c in _OFFENSE_CATS]
            _defense_order = [c for c in _cat_order if c in _DEFENSE_CATS]
            _personnel_order = [c for c in _cat_order if c not in _OFFENSE_CATS and c not in _DEFENSE_CATS]

            _off_col, _def_col, _pers_col = st.columns(3)
            with _off_col:
                st.markdown('<div style="font-weight:700;font-size:0.95rem;color:#4E2A84;margin-bottom:4px;">Offense</div>', unsafe_allow_html=True)
                if _offense_order:
                    for _cat in _offense_order:
                        _render_cat_expander(_cat)
                else:
                    st.caption("Nothing tagged yet.")
            with _def_col:
                st.markdown('<div style="font-weight:700;font-size:0.95rem;color:#4E2A84;margin-bottom:4px;">Defense</div>', unsafe_allow_html=True)
                if _defense_order:
                    for _cat in _defense_order:
                        _render_cat_expander(_cat)
                else:
                    st.caption("Nothing tagged yet.")
            with _pers_col:
                # Categories that aren't cleanly offense or defense -- currently just Personnel/Rotation (a
                # rotation/personnel decision, not a stat category). Its own column, same footing as Offense
                # and Defense, rather than a lesser full-width row underneath them.
                st.markdown('<div style="font-weight:700;font-size:0.95rem;color:#4E2A84;margin-bottom:4px;">Personnel/Rotation</div>', unsafe_allow_html=True)
                if _personnel_order:
                    for _cat in _personnel_order:
                        _render_cat_expander(_cat)
                else:
                    st.caption("Nothing tagged yet.")

            if _ungrouped:
                with st.expander(f"Other \u2014 {len(_ungrouped)} item{'s' if len(_ungrouped) != 1 else ''}", expanded=False):
                    for _n, (_icon, _headline, _caption, _reason, _cats, _side, _source) in enumerate(_ungrouped, start=1):
                        _render_key_item(_n, _icon, _headline, _caption, _reason, _cats, _side, _source)
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
    opp_display = short_opponent or full_opponent
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
    box = load_table("uww_pbp_box_score")
    game_box = box[box["opponent"] == short_opponent].copy()
    stints = load_table("uww_lineup_stints")
    game_stints = stints[stints["opponent"] == short_opponent].copy()

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
        _played_opponents_pre = set()
        if _game_original_pos is not None and _game_original_pos > 0:
            for _, _row in _orig_played.iloc[:_game_original_pos].iterrows():
                _short = resolve_short_opponent(_row["opponent"], short_names)
                if _short:
                    _played_opponents_pre.add(_short)
        _pre_box = box[box["opponent"].isin(_played_opponents_pre)]
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
        compact_cols = [c for c in ["player", "MIN", "PTS", "REB", "AST", "STL", "TO", "FG%"]
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

            # Full box score in expander
            with st.expander("View full box score", expanded=False):
                st.markdown("**UW-Whitewater**")
                st.dataframe(_uww_df[full_cols], hide_index=True, use_container_width=True)
                st.markdown(f"**{_t_opp}**")
                st.dataframe(_opp_df[full_cols], hide_index=True, use_container_width=True)
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
                styled = _comp_df.style.applymap(_color_diff, subset=diff_cols)
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
            names = [n.strip() for n in str(lineup_str).split(",")]
            return ", ".join(parts[-1] if len(parts := n.split()) > 1 else n for n in names)

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

    # --- SCORING RUNS & CLUTCH MOMENTS (this game) ---
    _pg_runs = load_table("uww_scoring_runs")
    _pg_run_row = _pg_runs[_pg_runs["opponent"] == short_opponent] if not _pg_runs.empty else pd.DataFrame()
    if not _pg_run_row.empty:
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">\U0001F4C8 SCORING RUNS &amp; LARGEST LEADS</div></div>', unsafe_allow_html=True)
        _rr = _pg_run_row.iloc[0]
        rr_col1, rr_col2 = st.columns(2)
        rr_col1.metric("UWW biggest run", f"{int(_rr['uww_biggest_run'])} pts")
        rr_col1.metric("UWW largest lead", f"{int(_rr['uww_largest_lead'])} pts")
        rr_col2.metric(f"{short_opponent} biggest run", f"{int(_rr['opponent_biggest_run'])} pts")
        rr_col2.metric(f"{short_opponent} largest lead", f"{int(_rr['opponent_largest_lead'])} pts")
        st.caption(f"During UWW's run — UWW: {_rr.get('uww_run_uww_lineup', '-')} | {short_opponent}: {_rr.get('uww_run_opp_lineup', '-')}")

    _pg_clutch = load_table("uww_clutch_events")
    _pg_clutch_game = _pg_clutch[_pg_clutch["opponent"] == short_opponent] if not _pg_clutch.empty else pd.DataFrame()
    if not _pg_clutch_game.empty:
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">\U0001F3C0 CLUTCH MOMENTS</div></div>', unsafe_allow_html=True)
        with st.popover("ℹ️ What counts as clutch?"):
            st.markdown("Last 5 minutes of the 2nd half or any overtime, with the score within 8 points.")
        _cg_display_cols = [c for c in ["period", "time_remaining", "team", "player", "event_type", "raw_text", "uww_score", "opp_score"] if c in _pg_clutch_game.columns]
        st.dataframe(_pg_clutch_game[_cg_display_cols], hide_index=True, use_container_width=True, height=250)

    # --- PLAY-BY-PLAY ---
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">PLAY-BY-PLAY</div></div>', unsafe_allow_html=True)
    pbp = load_table("uww_pbp_events")
    game_pbp = pbp[pbp["opponent"] == short_opponent].sort_values("event_order")
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

    # --- COACHING FLAGS ---
    try:
        _coaching_flags = load_table("uww_coaching_flags")
        if not _coaching_flags.empty and not uww_game_box.empty:
            # Filter to players who appeared in this game
            _game_players = set(uww_game_box["player"].str.strip().str.lower())
            _coaching_flags["_join_key"] = _coaching_flags["player"].str.strip().str.lower()
            _game_flags = _coaching_flags[_coaching_flags["_join_key"].isin(_game_players)].copy()

            if not _game_flags.empty:
                st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">COACHING FLAGS</div></div>', unsafe_allow_html=True)
                st.caption("Season-long coaching observations for players who appeared in this game")

                _positive = _game_flags[_game_flags["sentiment"].str.strip().str.lower() == "positive"]
                _negative = _game_flags[_game_flags["sentiment"].str.strip().str.lower() == "negative"]

                _col_pos, _col_neg = st.columns(2)

                with _col_pos:
                    st.markdown("**✅ Strengths**")
                    if _positive.empty:
                        st.caption("No positive flags for this game's players")
                    else:
                        for _, flag_row in _positive.iterrows():
                            _cat_badge = f'<span style="background:#e8f5e9;color:#2e7d32;padding:2px 8px;border-radius:10px;font-size:0.75rem;font-weight:600;">{flag_row.get("category", "")}</span>' if pd.notna(flag_row.get("category")) else ""
                            st.markdown(
                                f'<div style="border-left:3px solid #4caf50;padding:8px 12px;margin:6px 0;background:#f9fdf9;border-radius:4px;">'
                                f'<div style="font-weight:700;font-size:0.9rem;">{esc(flag_row["player"])} {_cat_badge}</div>'
                                f'<div style="font-size:0.85rem;margin-top:4px;">{esc(flag_row["flag"])}</div>'
                                f'<div style="font-size:0.78rem;color:#666;margin-top:3px;"><em>Evidence:</em> {esc(flag_row.get("evidence", "-"))}</div>'
                                f'<div style="font-size:0.78rem;color:#1b5e20;margin-top:2px;"><em>Recommendation:</em> {esc(flag_row.get("recommendation", "-"))}</div>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

                with _col_neg:
                    st.markdown("**⚠️ Areas to Improve**")
                    if _negative.empty:
                        st.caption("No negative flags for this game's players")
                    else:
                        for _, flag_row in _negative.iterrows():
                            _cat_badge = f'<span style="background:#fbe9e7;color:#c62828;padding:2px 8px;border-radius:10px;font-size:0.75rem;font-weight:600;">{flag_row.get("category", "")}</span>' if pd.notna(flag_row.get("category")) else ""
                            st.markdown(
                                f'<div style="border-left:3px solid #ef5350;padding:8px 12px;margin:6px 0;background:#fffafa;border-radius:4px;">'
                                f'<div style="font-weight:700;font-size:0.9rem;">{esc(flag_row["player"])} {_cat_badge}</div>'
                                f'<div style="font-size:0.85rem;margin-top:4px;">{esc(flag_row["flag"])}</div>'
                                f'<div style="font-size:0.78rem;color:#666;margin-top:3px;"><em>Evidence:</em> {esc(flag_row.get("evidence", "-"))}</div>'
                                f'<div style="font-size:0.78rem;color:#b71c1c;margin-top:2px;"><em>Recommendation:</em> {esc(flag_row.get("recommendation", "-"))}</div>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
    except Exception as _e:
        report_section_error("Coaching flags for this game", _e)

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
                    _styled_t = _pa_df.style.applymap(_color_diff_team, subset=_diff_cols_t)
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
            games=("opponent", "nunique"),
            stints=("stint_num", "count"),
        )
        .reset_index()
    )
    season_lineups["margin_per_min"] = (season_lineups["net_margin"] / season_lineups["total_minutes"]).round(2)

    meaningful = season_lineups[season_lineups["total_minutes"] >= 2.0]

    # Best / Worst lineups with styled cards
    def _last_names_card(lineup_str):
        names = [n.strip() for n in str(lineup_str).split(",")]
        return ", ".join(parts[-1] if len(parts := n.split()) > 1 else n for n in names)

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
            names = [n.strip() for n in str(lineup_str).split(",")]
            return ", ".join(parts[-1] if len(parts := n.split()) > 1 else n for n in names)

        # Map stints to W/L outcomes from schedule
        _opp_outcomes = get_opponent_outcomes(schedule, stints["opponent"].unique())
        stints_split = stints.copy()
        stints_split["outcome"] = stints_split["opponent"].map(_opp_outcomes)

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
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">\U0001F3C0 CLUTCH PERFORMANCE</div></div>', unsafe_allow_html=True)
    with st.popover("ℹ️ What counts as clutch?"):
        st.markdown(
            "Last 5 minutes of the 2nd half or any overtime, with the score within 8 points. This is computed "
            "once by the parser (not recomputed here) and grows automatically as closer games are added."
        )
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

                    # Per-game breakdown in expander
                    with st.expander(f"Game-by-game breakdown ({_n_games} games)", expanded=False):
                        _gm_rows = []
                        for _, _gr in _p_actual_games.iterrows():
                            _gm_rows.append({
                                "Opponent": _gr.get("opponent", "-"),
                                "PTS": int(_gr["PTS"]),
                                "vs Proj": int(_gr["PTS"] - _pr["projected_PTS"]),
                                "REB": int(_gr["REB"]),
                                "AST": int(_gr["AST"]),
                            })
                        _gm_df = pd.DataFrame(_gm_rows)
                        def _cd_player(val):
                            if isinstance(val, (int, float)):
                                if val > 0: return "color: #2e7d32; font-weight: 600;"
                                elif val < 0: return "color: #c62828; font-weight: 600;"
                            return ""
                        st.dataframe(_gm_df.style.applymap(_cd_player, subset=["vs Proj"]), hide_index=True, use_container_width=True)
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
        st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:0.5rem 0 1rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">ADVANCED STATS LEADERBOARD</div></div>', unsafe_allow_html=True)
        render_glossary_popover(["TS%", "Game Score", "Usage%"])
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
                n_pg = p_games["opponent"].nunique()
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
                usage = compute_usage_rate(totals, player_minutes_total, _adv_uww_box[_adv_uww_box["opponent"].isin(p_games["opponent"].unique())], team_minutes_total)
                _adv_rows.append({
                    "Player": player_name, "GP": n_pg, "TS%": round(ts_pct, 1),
                    "Game Score": round(avg_game_score, 1), "Usage%": round(usage, 1) if mpg else "-",
                })
            _adv_df = pd.DataFrame(_adv_rows).sort_values("Game Score", ascending=False)
            st.dataframe(_adv_df, hide_index=True, use_container_width=True)
            st.caption("TS% and Game Score are season averages; Usage% needs a recorded MPG (from uww_season_stats) and is left blank without one.")

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
                        _pts = f"{_pr['PTS']:.1f}" if pd.notna(_pr.get("PTS")) else "-"
                        _reb = f"{_pr['REB']:.1f}" if pd.notna(_pr.get("REB")) else "-"
                        _ast = f"{_pr['AST']:.1f}" if pd.notna(_pr.get("AST")) else "-"
                        _fg = f"{_pr['FG%']:.0f}%" if pd.notna(_pr.get("FG%")) else "-"
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
    n_games = uww_box_all["opponent"].nunique() if not uww_box_all.empty else 0

    # Map each opponent to a W/L outcome so every section below can split by wins vs losses.
    short_names = load_short_opponent_names()
    opp_outcomes = get_opponent_outcomes(schedule, uww_box_all["opponent"].unique()) if not uww_box_all.empty else {}
    win_opps = [o for o, r in opp_outcomes.items() if r == "W"]
    loss_opps = [o for o, r in opp_outcomes.items() if r == "L"]

    # ==================== FOUR FACTORS ====================
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">FOUR FACTORS</div></div>', unsafe_allow_html=True)
    render_glossary_popover(["eFG%", "TOV%", "ORB%", "FT Rate"])
    if uww_box_all.empty:
        st.info("Not enough box score data for Four Factors yet.")
    else:
        def _four_factors_row(label, team_b, opp_b):
            ff = compute_four_factors(team_b, opp_b)
            return {"Split": label, **{k: round(v, 1) for k, v in ff.items()}}

        ff_rows = [_four_factors_row("Season", uww_box_all, opp_box_all)]
        if win_opps:
            ff_rows.append(_four_factors_row("In Wins", uww_box_all[uww_box_all["opponent"].isin(win_opps)], opp_box_all[opp_box_all["opponent"].isin(win_opps)]))
        if loss_opps:
            ff_rows.append(_four_factors_row("In Losses", uww_box_all[uww_box_all["opponent"].isin(loss_opps)], opp_box_all[opp_box_all["opponent"].isin(loss_opps)]))
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
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">EFFICIENCY &amp; PACE</div></div>', unsafe_allow_html=True)
    render_glossary_popover(["Pace", "ORtg", "DRtg", "Net Rtg", "Poss"])
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
            if not opp_short:
                continue
            g_uww = uww_box_all[uww_box_all["opponent"] == opp_short]
            g_opp = opp_box_all[opp_box_all["opponent"] == opp_short]
            if g_uww.empty:
                continue
            g_eff = compute_efficiency_pace(g_uww, g_opp, 1)
            trend_rows.append({"Game": opp_short, "ORtg": round(g_eff["ORtg"], 1), "DRtg": round(g_eff["DRtg"], 1), "Net Rtg": round(g_eff["Net Rtg"], 1)})
        if len(trend_rows) >= 2:
            trend_df = pd.DataFrame(trend_rows).set_index("Game")
            st.markdown("**Game-by-game trend** (chronological)")
            st.line_chart(trend_df[["ORtg", "DRtg"]])
            st.caption("Rising ORtg / falling DRtg over the season is the clearest single trendline for whether a team is actually improving, independent of schedule strength swings.")

    # ==================== REBOUNDING RATE ====================
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">REBOUNDING RATE</div></div>', unsafe_allow_html=True)
    render_glossary_popover(["ORB%"])
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
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">SHOT SELECTION &amp; QUALITY</div></div>', unsafe_allow_html=True)
    with st.popover("ℹ️ What is this?"):
        st.markdown(
            "Built from the same video-tagging your scouting pipeline already does for shot-quality diagnosis "
            "(play type, catch-and-shoot vs. pull-up, contest level, distance) -- surfaced here as a standalone "
            "team-wide view instead of only being used internally to generate coaching flags."
        )
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
            st.caption(f"Based on {len(uww_shots)} video-matched shot attempts across {uww_shots['opponent'].nunique()} game(s).")

    # ==================== ASSIST NETWORK ====================
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">ASSIST NETWORK</div></div>', unsafe_allow_html=True)
    with st.popover("ℹ️ What is this?"):
        st.markdown(
            "Pairs each recorded assist event with the made-shot event immediately before it in the same "
            "team's play-by-play log (the standard convention this data already follows) to build a "
            "passer -> scorer breakdown -- no new tagging needed beyond what's already recorded per play."
        )
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
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">TRANSITION OFF TURNOVERS</div></div>', unsafe_allow_html=True)
    with st.popover("ℹ️ What is this?"):
        st.markdown(
            "Matches each steal to whether that same team scored within the next few play-by-play events -- an "
            "approximation of \"points off turnovers,\" since a live-ball turnover time isn't separately "
            "flagged in the data. A generous same-team-scores-soon-after window is used since exact shot-clock "
            "timing after a takeaway isn't recorded."
        )
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
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">COACH-TAGGED PLAY NOTES</div></div>', unsafe_allow_html=True)
    with st.popover("ℹ️ What is this?"):
        st.markdown(
            "Built from a coach-annotated video-clip export (a `\"<matchup>_recap.csv\"` file per game) -- each "
            "tagged clip carries the coach's own free-text note for that specific play: an offensive play call "
            "and how it was executed, or a defensive breakdown of what went right/wrong. Only games with a "
            "matching recap file have this data; everything else on this page comes from the box score and "
            "play-by-play alone."
        )
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
            st.markdown("**Play Calls**")
            if not call_rows.empty:
                call_rows["_is_make"] = call_rows["result"].astype(str).str.contains("Make", case=False, na=False)
                call_rows["_is_attempt"] = call_rows["result"].astype(str).str.contains("Make|Miss", case=False, regex=True, na=False)
                call_summary = call_rows.groupby("play_call").agg(
                    Calls=("coach_note", "count"), Makes=("_is_make", "sum"), Attempts=("_is_attempt", "sum"),
                ).reset_index()
                call_summary["FG%"] = (100 * call_summary["Makes"] / call_summary["Attempts"].replace(0, pd.NA)).round(1)
                call_summary = call_summary.drop(columns=["Makes"]).sort_values("Calls", ascending=False)
                st.dataframe(call_summary.rename(columns={"play_call": "Play Call"}), hide_index=True, use_container_width=True)
                st.caption("Play call is a best-effort extraction from the coach's own note text (a name immediately before the word \"EXECUTION\") -- a note that doesn't follow that exact pattern won't show up here, but is still visible in the raw notes browser below.")
            else:
                st.caption("No named play calls detected yet (looks for a name immediately before the word \"EXECUTION\" in offensive notes).")

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


