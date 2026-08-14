"""UW-Whitewater men's basketball scouting/coaching analytics app.

Data is bundled directly with the app (CSV files under ./data, exported from the analysis notebook's Delta
tables) rather than queried live from a SQL warehouse -- no Unity Catalog / warehouse permissions are needed
at runtime. Four sections: Upcoming Game, Previous Games, Team, Players.
"""

import html
import os
import re

import pandas as pd
import streamlit as st
from openai import OpenAI


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# A single player's name is spelled differently between two of the underlying source tables (a known,
# already-reconciled discrepancy from the analysis notebook: the play-by-play/video-tagging pipeline spells
# him "Mauryon Turner" while the official season-stats page spells him "Maurquis Turner"). uww_coaching_flags
# already merged onto the season-stats spelling; this alias lets other tables (e.g. uww_pbp_box_score) join
# consistently against that same canonical name.
KNOWN_NAME_ALIASES = {"mauryon turner": "Maurquis Turner"}

st.set_page_config(page_title="UWW Basketball Scouting", page_icon="🏀", layout="wide")


@st.cache_data
def load_table(name: str) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"{name}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)


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


def played_mask(schedule: pd.DataFrame) -> pd.Series:
    return schedule["outcome"].notna() & schedule["team_score"].notna()


def _normalize_case(text: str) -> str:
    """Convert ALL-CAPS text to sentence case; leave mixed-case text alone."""
    stripped = re.sub(r"[^a-zA-Z]", "", text)
    if stripped and stripped == stripped.upper() and len(stripped) > 1:
        return text[0].upper() + text[1:].lower()
    return text


# Keys-to-Victory stat mapping: basketball terminology → stat columns
KEYS_TO_VICTORY_STAT_MAP = {
    # Ball Security / Turnovers
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
    "Ball Security / Turnovers": {"keywords": "ball security, turnover, protect the ball, take care of the ball, limit turnovers, careless", "stats": "TO"},
    "Rebounding": {"keywords": "own the paint, bully, glass, rebound, board, second chance, crash, dominate the paint", "stats": "REB, ORB, DRB"},
    "Three-Point Shooting": {"keywords": "three, 3 pt, 3pt, perimeter shooting, spacing, shooting ability, shooting team, sniper, will shoot", "stats": "3PM-A, 3P%"},
    "Free Throws": {"keywords": "free throw, ft line, getting to ft", "stats": "FTM-A, FT%"},
    "Fouls / Discipline": {"keywords": "foul, wall up, drawing fouls", "stats": "PF"},
    "Ball Movement / Assists": {"keywords": "assist, ball movement, share the ball, playmaking, playmaker, create", "stats": "AST"},
    "Paint Protection / Blocks": {"keywords": "block, protect the rim, paint protection", "stats": "BLK"},
    "Perimeter Defense / Ball Pressure": {"keywords": "steal, press capable, full court press, force turnovers, force to's, guard your yard, keep the ball in front, guard 1 on 1, early gap, help side, active hands, physical & aggressive on ball, on ball defensively, pressure", "stats": "STL"},
    "Scoring Inside": {"keywords": "dominate the paint, attack the paint, live in the paint, attack the basket, scoring at the rim, get to rim, attack the rim, get to the rim", "stats": "FG2M, FG2A, FG2%"},
    "Field Goal Efficiency": {"keywords": "limit their scoring", "stats": "FGM-A, FG%"},
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
    "three": "UWW", "3 pt": "OPP", "3pt": "OPP", "perimeter shooting": "UWW", "spacing": "UWW",
    "shooting ability": "OPP", "shooting team": "OPP", "sniper": "OPP", "will shoot": "OPP",
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
    opp_outcome = {}
    for _, row in schedule.iterrows():
        if pd.notna(row.get("outcome")):
            for opp in uww_per_game["opponent"].unique():
                if str(row["opponent"]).startswith(opp):
                    opp_outcome[opp] = row["outcome"]
                    break
    uww_per_game["outcome"] = uww_per_game["opponent"].map(opp_outcome)

    wins = uww_per_game[uww_per_game["outcome"] == "W"]
    losses = uww_per_game[uww_per_game["outcome"] == "L"]
    if wins.empty:
        return None

    # Map KTV categories to stat columns
    cat_stat_map = {
        "Ball Security / Turnovers": ["TO"],
        "Rebounding": ["REB", "OREB", "DREB"],
        "Three-Point Shooting": ["FG3M", "3P%"],
        "Free Throws": ["FTM", "FT%"],
        "Fouls / Discipline": ["PF"],
        "Ball Movement / Assists": ["AST"],
        "Paint Protection / Blocks": ["BLK"],
        "Perimeter Defense / Ball Pressure": ["STL"],
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
        try:
            _opp_sched = load_table("uww_opponent_schedules")
            _opp_games = _opp_sched[_opp_sched["opponent"] == short_opponent].copy()
            if not _opp_games.empty:
                # Find the UWW game row and only count games before it
                _uww_idx = None
                for _i, _r in _opp_games.iterrows():
                    _vs = str(_r.get("vs_opponent", "")).lower()
                    if "whitewater" in _vs or "uww" in _vs:
                        _uww_idx = _i
                        break
                if _uww_idx is not None:
                    _pre_uww = _opp_games.loc[:_uww_idx].iloc[:-1]
                else:
                    _pre_uww = _opp_games
                if not _pre_uww.empty:
                    _ow = int((_pre_uww["outcome"] == "W").sum())
                    _ol = int((_pre_uww["outcome"] == "L").sum())
                    opp_record = f"{_ow}-{_ol}"
                    # Compute opponent streak from pre-UWW games
                    _opp_streak_count = 0
                    _opp_streak_type = ""
                    for _out in _pre_uww["outcome"].iloc[::-1]:
                        if _opp_streak_count == 0:
                            _opp_streak_type = _out
                            _opp_streak_count = 1
                        elif _out == _opp_streak_type:
                            _opp_streak_count += 1
                        else:
                            break
                    if _opp_streak_count > 1:
                        _opp_s_label = "W" if _opp_streak_type == "W" else "L"
                        opp_streak_str = f"{_opp_streak_count}{_opp_s_label} streak"
        except Exception:
            pass

    # Build broadcast-style HTML banner with team logos
    import base64 as _b64

    def _load_logo_b64(team_name):
        """Load a team logo from data/logo/<team_name>.png and return base64 string."""
        logo_path = os.path.join(DATA_DIR, "logo", f"{team_name}.png")
        if os.path.exists(logo_path):
            with open(logo_path, "rb") as _lf:
                return _b64.b64encode(_lf.read()).decode()
        return ""

    uww_logo_b64 = _load_logo_b64("UW-Whitewater")
    opp_display = short_opponent or full_opponent
    opp_logo_b64 = _load_logo_b64(short_opponent) if short_opponent else ""

    uww_logo_img = f'<div style="height:64px;display:flex;align-items:center;justify-content:center;margin-bottom:8px;"><img src="data:image/png;base64,{uww_logo_b64}" style="max-height:64px;max-width:90px;object-fit:contain;"></div>' if uww_logo_b64 else '<div style="height:64px;"></div>'
    opp_logo_img = f'<div style="height:64px;display:flex;align-items:center;justify-content:center;margin-bottom:8px;"><img src="data:image/png;base64,{opp_logo_b64}" style="max-height:64px;max-width:90px;object-fit:contain;"></div>' if opp_logo_b64 else '<div style="height:64px;"></div>'

    _uww_streak_html = f'<div style="color:#aabbcc;font-size:0.8rem;font-style:italic;margin-top:2px;">{streak_str}</div>' if streak_str else ''
    _opp_streak_html = f'<div style="color:#aabbcc;font-size:0.8rem;font-style:italic;margin-top:2px;">{opp_streak_str}</div>' if opp_streak_str else ''
    banner_html = f'<div style="background:#1a1a2e;border-radius:10px;padding:22px 32px;margin-bottom:0.75rem;display:flex;align-items:center;justify-content:space-between;"><div style="text-align:center;flex:1;display:flex;flex-direction:column;align-items:center;">{uww_logo_img}<div style="color:#ffffff;font-family:Montserrat,sans-serif;font-weight:800;font-size:1.4rem;letter-spacing:0.5px;">UW-WHITEWATER</div><div style="color:#9DAAAC;font-size:1.05rem;font-weight:600;margin-top:3px;">{uww_wins}-{uww_losses}</div>{_uww_streak_html}</div><div style="text-align:center;flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;"><div style="color:#9DAAAC;font-size:1rem;font-weight:500;">{game_date}</div><div style="color:#ffffff;font-size:1.6rem;font-weight:700;margin:4px 0;">VS</div><div style="color:#9DAAAC;font-size:0.95rem;">{location}</div></div><div style="text-align:center;flex:1;display:flex;flex-direction:column;align-items:center;">{opp_logo_img}<div style="color:#ffffff;font-family:Montserrat,sans-serif;font-weight:800;font-size:1.4rem;letter-spacing:0.5px;">{html.escape(opp_display.upper())}</div><div style="color:#9DAAAC;font-size:1.05rem;font-weight:600;margin-top:3px;">{opp_record if opp_record else ""}</div>{_opp_streak_html}</div></div>'
    st.markdown(banner_html, unsafe_allow_html=True)

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
        # Expanded stats for All Stats dialog
        _uww_3pm = uww_box["3PM"].sum() if "3PM" in uww_box.columns else 0
        _uww_3pa = uww_box["3PA"].sum() if "3PA" in uww_box.columns else 0
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
        # REB and PTS are per-game averages; AST, BLK, STL are season totals (divide by games_est)
        _games_est = 5
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
        return f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:16px 18px;flex:1;width:100%;"><div style="font-weight:800;font-size:1.15rem;letter-spacing:0.5px;margin-bottom:12px;">TEAM STATS</div><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px;"><span style="font-size:1.05rem;font-weight:700;color:#4E2A84;">UWW</span><span style="font-size:1.05rem;font-weight:700;color:#222;">{html.escape(opp_name.upper())}</span></div>{rows_html}</div>'

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
            f'<span style="font-size:0.95rem;font-weight:700;color:#222;">{html.escape(opp_name.upper())}</span>'
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
        season_stats_mpg = season_stats.copy()
        season_stats_mpg["MIN_num"] = pd.to_numeric(season_stats_mpg["MIN"], errors="coerce")
        season_stats_mpg = season_stats_mpg[~season_stats_mpg["PLAYER"].isin(["Team Total", "Opponent"])]
        season_stats_mpg = season_stats_mpg.dropna(subset=["MIN_num"])
        # Only include players who appear in our PBP box score
        season_stats_mpg = season_stats_mpg[season_stats_mpg["PLAYER"].isin(totals["player"].tolist())]
        leaders = {}
        if not season_stats_mpg.empty:
            mpg_leader = season_stats_mpg.nlargest(1, "MIN_num").iloc[0]
            _pbp_games = int(games_per_player.get(mpg_leader["PLAYER"], 0))
            _gp_sub = f"{_pbp_games} GP" if _pbp_games > 0 else ""
            leaders["Minutes"] = {"name": mpg_leader["PLAYER"], "value": mpg_leader["MIN_num"], "sub": _gp_sub}
        # Points leader
        pts_leader = totals.nlargest(1, "PPG").iloc[0]
        leaders["Points"] = {"name": pts_leader["player"], "value": pts_leader["PPG"], "sub": f"{pts_leader['FG_pct']:.1f} FG%, {pts_leader['FT_pct']:.1f} FT%"}
        # Rebounds leader
        reb_leader = totals.nlargest(1, "RPG").iloc[0]
        leaders["Rebounds"] = {"name": reb_leader["player"], "value": reb_leader["RPG"], "sub": f"{reb_leader['DRPG']} DRPG, {reb_leader['ORPG']} ORPG"}
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
        leaders["Points"] = {"name": pts_leader["name"], "value": pts_leader["PTS"], "sub": f"{fg_val} FG%, {ft_val} FT%"}
        # Rebounds leader (REB is per-game)
        reb_leader = opp.nlargest(1, "REB").iloc[0]
        leaders["Rebounds"] = {"name": reb_leader["name"], "value": reb_leader["REB"], "sub": ""}
        # Assists leader (AST is season total, divide by games)
        opp_copy = opp.copy()
        opp_copy["APG"] = opp_copy["AST"] / games_est
        ast_leader = opp_copy.nlargest(1, "APG").iloc[0]
        topg = ast_leader["TO"] / games_est
        leaders["Assists"] = {"name": ast_leader["name"], "value": ast_leader["APG"], "sub": f"{topg:.1f} TOPG"}
        # Steals leader (STL is season total, divide by games)
        opp_copy["SPG"] = opp_copy["STL"] / games_est
        stl_leader = opp_copy.nlargest(1, "SPG").iloc[0]
        leaders["Steals"] = {"name": stl_leader["name"], "value": stl_leader["SPG"], "sub": ""}
        # Blocks leader (BLK is season total, divide by games)
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
            rows_html += f'<div style="border:1px solid #eee;border-radius:8px;padding:12px 14px;margin-bottom:8px;"><div style="display:flex;align-items:center;justify-content:space-between;"><div style="text-align:left;flex:1;"><div style="font-weight:700;font-size:1rem;">{html.escape(_short(uww_name))}</div><div style="font-size:0.85rem;color:#888;">{html.escape(uww_sub)}</div></div><div style="text-align:center;flex:1;"><div style="font-size:1.15rem;font-weight:700;">{uww_val:.1f}<span style="font-size:0.85rem;color:#666;margin:0 8px;">{cat}</span>{opp_val:.1f}</div></div><div style="text-align:right;flex:1;"><div style="font-weight:700;font-size:1rem;">{html.escape(_short(opp_name_l))}</div><div style="font-size:0.85rem;color:#888;">{html.escape(opp_sub)}</div></div></div></div>'
        return f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;flex:1;width:100%;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;margin-bottom:8px;">SEASON LEADERS</div><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px;"><span style="font-size:0.95rem;font-weight:700;color:#4E2A84;">UWW</span><span style="font-size:0.85rem;color:#888;">Avg. Per Game</span><span style="font-size:0.95rem;font-weight:700;color:#222;">{html.escape(opp_name.upper())}</span></div>{rows_html}</div>'

    uww_leaders = _get_uww_leaders(box, played)
    opp_leaders = _get_opp_leaders(opp_profiles_ts, short_opponent)

    # Render: Season Leaders | Team Stats | Last Five Games
    leaders_html = _build_season_leaders_html(uww_leaders, opp_leaders, opp_display)
    stats_html = _build_team_stats_html(uww_team_stats, opp_team_stats, opp_display) if uww_team_stats and opp_team_stats else ""
    l5_html = _build_last5_combined_html(uww_last5, opp_last5, opp_display)

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
        all_html = f'<div style="padding:8px 4px;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding:0 4px;"><span style="font-size:1.1rem;font-weight:700;color:#4E2A84;">UWW</span><span style="font-size:1.1rem;font-weight:700;color:#222;">{html.escape(opp_display.upper())}</span></div>{rows_html}</div>'
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
            f'<span style="font-size:1.05rem;font-weight:700;color:#222;">{html.escape(opp_display.upper())} ({len(opp_all_games)} games)</span>'
            f'</div>'
        )
        st.markdown(f'{header_html}{rows_html}', unsafe_allow_html=True)

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
            # Strip outer border from l5_html since container provides it
            _l5_inner = _re_stats.sub(
                r'^<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;flex:1;width:100%;">',
                '<div style="width:100%;">',
                l5_html, count=1
            )
            st.markdown(_l5_inner, unsafe_allow_html=True)
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
            f'<span style="font-size:0.95rem;font-weight:700;color:#222;">{html.escape(opp_name.upper())}</span>'
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
            f'<span style="font-size:0.95rem;font-weight:700;color:#222;">{html.escape(opp_name.upper())}</span>'
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
            f'<span style="font-size:0.95rem;font-weight:700;color:#222;">{html.escape(opp_name.upper())}</span>'
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
        st.markdown(f'<div style="zoom:1.1;">{_scouting_html}</div>', unsafe_allow_html=True)


    # Scouting Report header with PDF download link
    reports_dir = os.path.join(DATA_DIR, "scouting_reports")
    report_path = None
    if os.path.isdir(reports_dir):
        for f in os.listdir(reports_dir):
            if f.lower().endswith(".pdf") and short_opponent.lower() in f.lower():
                report_path = os.path.join(reports_dir, f)
                break
    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">SCOUTING REPORT</div></div>', unsafe_allow_html=True)
    if report_path and os.path.exists(report_path):
        with open(report_path, "rb") as pdf_file:
            st.download_button(
                label="📄 Download PDF",
                data=pdf_file,
                file_name=f"{short_opponent}_Scouting_Report.pdf",
                mime="application/pdf",
                key=f"pdf_download_{short_opponent}",
                use_container_width=False,
            )
    game_plans = load_table("uww_opponent_game_plans")
    opp_plan = game_plans[game_plans["opponent"] == short_opponent]
    if opp_plan.empty:
        st.warning(f"No scouting report / game plan found yet for {short_opponent}.")
    else:
        ktv_match = opp_plan[opp_plan["topic"] == "KEYS TO VICTORY"]
        strengths_match = opp_plan[opp_plan["topic"] == "TEAM STRENGTHS"]

        # Three-column layout: Keys to Victory + Team Strengths | Keys to Victory (data-driven) | How We Stack Up
        col_ktv, col_dd, col_hwsu = st.columns(3)

        with col_ktv:
          with st.container(border=True):
            st.markdown('<div style="font-weight:800;font-size:0.95rem;letter-spacing:0.3px;color:#4E2A84;margin-bottom:8px;">Keys to Victory</div>', unsafe_allow_html=True)
            if not ktv_match.empty:
                ktv_notes = ktv_match.iloc[0]["notes"]
                keys = [_normalize_case(re.sub(r"^\d+\.\s*", "", k.strip())) for k in str(ktv_notes).split("|") if k.strip()]
                _CAT_COLORS = {
                    "Ball Security / Turnovers": ("#fff3e0", "#e65100"),
                    "Rebounding": ("#e8f5e9", "#2e7d32"),
                    "Three-Point Shooting": ("#e3f2fd", "#1565c0"),
                    "Free Throws": ("#fce4ec", "#c62828"),
                    "Fouls / Discipline": ("#fff8e1", "#f57f17"),
                    "Ball Movement / Assists": ("#f3e5f5", "#6a1b9a"),
                    "Paint Protection / Blocks": ("#efebe9", "#4e342e"),
                    "Perimeter Defense / Ball Pressure": ("#e0f7fa", "#00838f"),
                    "Scoring Inside": ("#ede7f6", "#4527a0"),
                    "Field Goal Efficiency": ("#e8e0f0", "#4E2A84"),
                }
                _valid_cats = set(load_table("uww_ktv_splits")["category"].unique()) | set(KTV_CATEGORY_REFERENCE.keys())
                def _detect_side(text):
                    """Detect if a bullet is UWW (proactive) or OPP (contain opponent)."""
                    text_lower = text.lower()
                    sides_found = set()
                    for phrase, side in PHRASE_SIDE.items():
                        if phrase in text_lower:
                            sides_found.add(side)
                    if "OPP" in sides_found and "UWW" not in sides_found:
                        return "OPP"
                    if "UWW" in sides_found and "OPP" not in sides_found:
                        return "UWW"
                    if "OPP" in sides_found and "UWW" in sides_found:
                        return "BOTH"
                    return None
                def _match_categories(text):
                    text_lower = text.lower()
                    matched = []
                    for _cat, _details in KTV_CATEGORY_REFERENCE.items():
                        if _cat not in _valid_cats:
                            continue
                        _kws = [_kw.strip() for _kw in _details["keywords"].split(",")]
                        for _kw in _kws:
                            if _kw in text_lower:
                                if _cat not in matched:
                                    matched.append(_cat)
                                break
                    return matched
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
                    badges = ""
                    if side:
                        badges += _side_badge_html(side)
                    for c in cats:
                        bg, fg = _CAT_COLORS.get(c, ("#e8e0f0", "#4E2A84"))
                        badges += f' <span style="background:{bg};color:{fg};font-size:0.7rem;font-weight:600;padding:2px 8px;border-radius:10px;margin-left:4px;">{html.escape(c)}</span>'
                    return badges
                for k in keys:
                    _cats = _match_categories(k)
                    _side = _detect_side(k)
                    if _cats or _side:
                        st.markdown(f'<div style="margin-bottom:6px;"><span style="font-size:0.95rem;">\u2022 {html.escape(k)}</span>{_badges_html(_cats, _side)}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div style="margin-bottom:6px;"><span style="font-size:0.95rem;">\u2022 {html.escape(k)}</span></div>', unsafe_allow_html=True)
            else:
                st.caption("Not available.")
          with st.container(border=True):
            st.markdown('<div style="font-weight:800;font-size:0.95rem;letter-spacing:0.3px;color:#4E2A84;margin-bottom:8px;">Team Strengths</div>', unsafe_allow_html=True)
            if not strengths_match.empty:
                str_notes = strengths_match.iloc[0]["notes"]
                items = [re.sub(r"^\d+\.\s*", "", s.strip()) for s in str(str_notes).split("|") if s.strip()]
                for item in items:
                    _cats = _match_categories(item)
                    # Team Strengths always describe the OPPONENT's capabilities
                    if _cats:
                        st.markdown(f'<div style="margin-bottom:6px;"><span style="font-size:0.95rem;">{html.escape(item)}</span>{_badges_html(_cats, "OPP")}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div style="margin-bottom:6px;"><span style="font-size:0.95rem;">{html.escape(item)}</span>{_side_badge_html("OPP")}</div>', unsafe_allow_html=True)
            else:
                st.caption("Not available.")

        with col_dd:
          with st.container(border=True):
            st.markdown('<div style="font-weight:800;font-size:0.95rem;letter-spacing:0.3px;color:#4E2A84;margin-bottom:8px;">Keys to Victory (Data-Driven)</div>', unsafe_allow_html=True)
            derived_keys = load_table("uww_pbp_derived_keys")
            opp_keys = derived_keys[derived_keys["opponent"] == short_opponent].sort_values("key_number")
            if not opp_keys.empty:
                for _, dk_row in opp_keys.iterrows():
                    _dd_title = dk_row['title']
                    _dd_cats = _match_categories(_dd_title)
                    if not _dd_cats:
                        _dd_cats = _match_categories(dk_row['supporting_stats'])
                    _dd_side = _detect_side(_dd_title) or _detect_side(dk_row['recommendation'])
                    if _dd_cats:
                        st.markdown(f'<div style="margin-bottom:2px;"><span style="font-size:0.95rem;font-weight:700;">{int(dk_row["key_number"])}. {html.escape(_dd_title)}</span>{_badges_html(_dd_cats, _dd_side)}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f"**{int(dk_row['key_number'])}. {_dd_title}**")
                    st.caption(dk_row["supporting_stats"])
                    st.markdown(f"_{dk_row['recommendation']}_")
                    st.markdown("")
            else:
                st.caption("No PBP-derived keys available for this opponent.")

        with col_hwsu:
          with st.container(border=True):
            hwsu_title, hwsu_info = st.columns([5, 1])
            with hwsu_title:
                st.markdown('<div style="font-weight:800;font-size:0.95rem;letter-spacing:0.3px;color:#4E2A84;margin-bottom:8px;">How We Stack Up</div>', unsafe_allow_html=True)
            with hwsu_info:
                with st.popover("ℹ️"):
                    st.markdown("**KTV Category Reference**")
                    st.caption("How Keys to Victory keywords map to tracked stats:")
                    ref_rows = []
                    for cat, details in KTV_CATEGORY_REFERENCE.items():
                        ref_rows.append({"Category": cat, "Trigger Keywords": details["keywords"], "Stats Tracked": details["stats"]})
                    st.dataframe(pd.DataFrame(ref_rows), hide_index=True, use_container_width=True)
            if not ktv_match.empty:
                ktv_splits = load_table("uww_ktv_splits")
                # Derive this game's emphasis LIVE from KTV notes (same as badge detection)
                _SIDE_DISPLAY = {
                    ("Ball Security / Turnovers", "UWW"): "UWW: Protect the Ball",
                    ("Ball Security / Turnovers", "OPP"): "OPP: Force Turnovers",
                    ("Rebounding", "UWW"): "UWW: Crash the Boards",
                    ("Rebounding", "OPP"): "OPP: Limit Their Rebounding",
                    ("Three-Point Shooting", "UWW"): "UWW: Hit Our Threes",
                    ("Three-Point Shooting", "OPP"): "OPP: Contest Their Shooting",
                    ("Free Throws", "UWW"): "UWW: Get to the FT Line",
                    ("Free Throws", "OPP"): "OPP: Keep Them Off the Line",
                    ("Fouls / Discipline", "UWW"): "UWW: Stay Disciplined",
                    ("Fouls / Discipline", "OPP"): "OPP: They Draw Fouls",
                    ("Ball Movement / Assists", "UWW"): "UWW: Share the Ball",
                    ("Ball Movement / Assists", "OPP"): "OPP: Disrupt Their Ball Movement",
                    ("Perimeter Defense / Ball Pressure", "UWW"): "UWW: Create Pressure",
                    ("Perimeter Defense / Ball Pressure", "OPP"): "OPP: On-Ball Defense",
                    ("Paint Protection / Blocks", "UWW"): "UWW: Protect Our Rim",
                    ("Paint Protection / Blocks", "OPP"): "OPP: Limit Their Interior",
                    ("Scoring Inside", "UWW"): "UWW: Attack the Paint",
                    ("Scoring Inside", "OPP"): "OPP: Limit Their Inside Scoring",
                    ("Field Goal Efficiency", "UWW"): "UWW: Efficient Shooting",
                    ("Field Goal Efficiency", "OPP"): "OPP: Limit Their FG Efficiency",
                }
                _live_emphasis = []
                _live_cats = set()
                # Scan Keys to Victory notes
                _ktv_text = str(ktv_match.iloc[0]["notes"])
                for _kpart in _ktv_text.split("|"):
                    _kpart = _kpart.strip()
                    if not _kpart:
                        continue
                    _part_cats = _match_categories(_kpart)
                    _part_side = _detect_side(_kpart) or "UWW"
                    for _pc in _part_cats:
                        if (_pc, _part_side) not in _live_cats:
                            _live_cats.add((_pc, _part_side))
                            _live_emphasis.append((_pc, _part_side))
                # Also scan Team Strengths notes (always OPP side)
                if not strengths_match.empty:
                    _str_text = str(strengths_match.iloc[0]["notes"])
                    for _spart in _str_text.split("|"):
                        _spart = _spart.strip()
                        if not _spart:
                            continue
                        _spart_cats = _match_categories(_spart)
                        for _sc in _spart_cats:
                            if (_sc, "OPP") not in _live_cats:
                                _live_cats.add((_sc, "OPP"))
                                _live_emphasis.append((_sc, "OPP"))
                # (emphasis categories used for splits below)
                opp_cats = [c for c, _ in _live_emphasis]
                ktv_games = load_table("uww_ktv_game_categories")
                if len(opp_cats) > 0:
                    # Compute per-game stats for comparison
                    _uww_stats = {}
                    _opp_stats = {}
                    if not uww_box.empty:
                        _ng = uww_box["opponent"].nunique() or 1
                        _uww_stats["REB"] = uww_box["REB"].sum() / _ng
                        _uww_stats["AST"] = uww_box["AST"].sum() / _ng
                        _uww_stats["STL"] = uww_box["STL"].sum() / _ng
                        _uww_stats["BLK"] = uww_box["BLK"].sum() / _ng
                        _uww_stats["TO"] = uww_box["TO"].sum() / _ng
                        _uww_stats["PF"] = uww_box["PF"].sum() / _ng
                        _uww_stats["FG%"] = (uww_box["FGM"].sum() / uww_box["FGA"].sum() * 100) if uww_box["FGA"].sum() > 0 else 0
                        _uww_stats["3PM"] = uww_box["FG3M"].sum() / _ng
                        _uww_stats["3P%"] = (uww_box["FG3M"].sum() / uww_box["FG3A"].sum() * 100) if uww_box["FG3A"].sum() > 0 else 0
                        _uww_stats["FTM"] = uww_box["FTM"].sum() / _ng
                        _uww_stats["FT%"] = (uww_box["FTM"].sum() / uww_box["FTA"].sum() * 100) if uww_box["FTA"].sum() > 0 else 0
                        _fg2m = uww_box["FGM"].sum() - uww_box["FG3M"].sum()
                        _fg2a = uww_box["FGA"].sum() - uww_box["FG3A"].sum()
                        _uww_stats["FG2M"] = _fg2m / _ng
                        _uww_stats["FG2%"] = (_fg2m / _fg2a * 100) if _fg2a > 0 else 0
                    # Try opponent lineup season box (reuse validated _opp_lu from above)
                    _opp_lineup_box = _opp_lu if _opp_lu is not None else pd.DataFrame()
                    if not _opp_lineup_box.empty and "MIN" in _opp_lineup_box.columns:
                        _olb_min = _opp_lineup_box["MIN"].sum()
                        _olb_games = _olb_min / 40 if _olb_min > 0 else 1
                        _stat_cols = ["PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "REB", "AST", "STL", "BLK", "TO", "PF"]
                        _olb_totals = {c: _opp_lineup_box[c].sum() for c in _stat_cols if c in _opp_lineup_box.columns}
                        _opp_stats["REB"] = _olb_totals.get("REB", 0) / _olb_games
                        _opp_stats["AST"] = _olb_totals.get("AST", 0) / _olb_games
                        _opp_stats["STL"] = _olb_totals.get("STL", 0) / _olb_games
                        _opp_stats["BLK"] = _olb_totals.get("BLK", 0) / _olb_games
                        _opp_stats["TO"] = _olb_totals.get("TO", 0) / _olb_games
                        _opp_stats["PF"] = _olb_totals.get("PF", 0) / _olb_games
                        _opp_stats["FG%"] = (_olb_totals.get("FGM", 0) / _olb_totals.get("FGA", 1) * 100) if _olb_totals.get("FGA", 0) > 0 else 0
                        _opp_stats["3PM"] = _olb_totals.get("FG3M", 0) / _olb_games
                        _opp_stats["3P%"] = (_olb_totals.get("FG3M", 0) / _olb_totals.get("FG3A", 1) * 100) if _olb_totals.get("FG3A", 0) > 0 else 0
                        _opp_stats["FTM"] = _olb_totals.get("FTM", 0) / _olb_games
                        _opp_stats["FT%"] = (_olb_totals.get("FTM", 0) / _olb_totals.get("FTA", 1) * 100) if _olb_totals.get("FTA", 0) > 0 else 0
                        _ofg2m = _olb_totals.get("FGM", 0) - _olb_totals.get("FG3M", 0)
                        _ofg2a = _olb_totals.get("FGA", 0) - _olb_totals.get("FG3A", 0)
                        _opp_stats["FG2M"] = _ofg2m / _olb_games
                        _opp_stats["FG2%"] = (_ofg2m / _ofg2a * 100) if _ofg2a > 0 else 0
                    # Fallback: box score from games played vs UWW
                    elif not uww_box.empty and "team" in uww_box.columns:
                      _opp_box = uww_box[uww_box["team"] != "UW-Whitewater"]
                      _opp_box_match = _opp_box[_opp_box["team"] == short_opponent] if not _opp_box.empty else pd.DataFrame()
                    else:
                      _opp_box_match = pd.DataFrame()
                    if not _opp_lineup_box.empty:
                        pass  # Already computed above
                    elif not _opp_box_match.empty:
                        # Compute from box score (same method as UWW)
                        _ong = _opp_box_match["game_date"].nunique() if "game_date" in _opp_box_match.columns else 1
                        _opp_stats["REB"] = _opp_box_match["REB"].sum() / _ong
                        _opp_stats["AST"] = _opp_box_match["AST"].sum() / _ong
                        _opp_stats["STL"] = _opp_box_match["STL"].sum() / _ong
                        _opp_stats["BLK"] = _opp_box_match["BLK"].sum() / _ong
                        _opp_stats["TO"] = _opp_box_match["TO"].sum() / _ong
                        _opp_stats["PF"] = _opp_box_match["PF"].sum() / _ong
                        _opp_stats["FG%"] = (_opp_box_match["FGM"].sum() / _opp_box_match["FGA"].sum() * 100) if _opp_box_match["FGA"].sum() > 0 else 0
                        _opp_stats["3PM"] = _opp_box_match["FG3M"].sum() / _ong
                        _opp_stats["3P%"] = (_opp_box_match["FG3M"].sum() / _opp_box_match["FG3A"].sum() * 100) if _opp_box_match["FG3A"].sum() > 0 else 0
                        _opp_stats["FTM"] = _opp_box_match["FTM"].sum() / _ong
                        _opp_stats["FT%"] = (_opp_box_match["FTM"].sum() / _opp_box_match["FTA"].sum() * 100) if _opp_box_match["FTA"].sum() > 0 else 0
                        _ofg2m = _opp_box_match["FGM"].sum() - _opp_box_match["FG3M"].sum()
                        _ofg2a = _opp_box_match["FGA"].sum() - _opp_box_match["FG3A"].sum()
                        _opp_stats["FG2M"] = _ofg2m / _ong
                        _opp_stats["FG2%"] = (_ofg2m / _ofg2a * 100) if _ofg2a > 0 else 0
                    elif not opp_prof_ts.empty:
                        # Fallback: derive from player profiles for upcoming opponents
                        _opp_stats["REB"] = opp_prof_ts["REB"].sum()
                        _opp_stats["AST"] = opp_prof_ts["AST"].sum()
                        _opp_stats["STL"] = opp_prof_ts["STL"].sum()
                        _opp_stats["BLK"] = opp_prof_ts["BLK"].sum()
                        _opp_stats["TO"] = opp_prof_ts["TO"].sum()
                        _opp_stats["PF"] = 0
                        # Parse 3PM-A season totals
                        _o3m, _o3a = 0, 0
                        for _, _op in opp_prof_ts.iterrows():
                            _tpa = str(_op.get("3PM-A", "")).strip()
                            if "-" in _tpa and _tpa != "nan":
                                parts = _tpa.split("-")
                                try:
                                    _o3m += float(parts[0])
                                    _o3a += float(parts[1])
                                except (ValueError, IndexError):
                                    pass
                        _opp_stats["3P%"] = (_o3m / _o3a * 100) if _o3a > 0 else 0
                        # Parse FTM-A season totals
                        _oftm, _ofta = 0, 0
                        for _, _op in opp_prof_ts.iterrows():
                            _fta = str(_op.get("FTM-A", "")).strip()
                            if "-" in _fta and _fta != "nan":
                                parts = _fta.split("-")
                                try:
                                    _oftm += float(parts[0])
                                    _ofta += float(parts[1])
                                except (ValueError, IndexError):
                                    pass
                        _opp_stats["FT%"] = (_oftm / _ofta * 100) if _ofta > 0 else 0
                        # FG% (minutes-weighted)
                        _opp_fg_vals = []
                        for _, _op in opp_prof_ts.iterrows():
                            _fgs = str(_op.get("FG%", "")).replace("%", "").strip()
                            if _fgs and _fgs != "nan":
                                try:
                                    _opp_fg_vals.append((float(_fgs), float(_op.get("MIN", 1))))
                                except ValueError:
                                    pass
                        _opp_fg_pct = sum(v * m for v, m in _opp_fg_vals) / sum(m for _, m in _opp_fg_vals) if _opp_fg_vals else 0
                        _opp_stats["FG%"] = _opp_fg_pct
                        # Derive per-game stats using PPG and season totals
                        _opp_ppg = opp_prof_ts["PTS"].sum()
                        _opp_games_est = num_uww_games
                        _o3m_pg = _o3m / _opp_games_est if _opp_games_est > 0 else 0
                        _o3a_pg = _o3a / _opp_games_est if _opp_games_est > 0 else 0
                        _oftm_pg = _oftm / _opp_games_est if _opp_games_est > 0 else 0
                        _opp_stats["3PM"] = _o3m_pg
                        _opp_stats["FTM"] = _oftm_pg
                        # FGM/gm from PTS = 2*FGM + FG3M + FTM
                        _opp_fgm_pg = (_opp_ppg - _o3m_pg - _oftm_pg) / 2
                        _opp_fga_pg = _opp_fgm_pg / (_opp_fg_pct / 100) if _opp_fg_pct > 0 else 0
                        _opp_fg2m_pg = _opp_fgm_pg - _o3m_pg
                        _opp_fg2a_pg = _opp_fga_pg - _o3a_pg
                        _opp_stats["FG2M"] = max(_opp_fg2m_pg, 0)
                        _opp_stats["FG2%"] = (_opp_fg2m_pg / _opp_fg2a_pg * 100) if _opp_fg2a_pg > 0 else 0

                    # Stat display config per category
                    _CAT_STAT_DISPLAY = {
                        "Rebounding": [("RPG", "REB")],
                        "Three-Point Shooting": [("3P%", "3P%"), ("3PM/gm", "3PM")],
                        "Perimeter Defense / Ball Pressure": [("STL/gm", "STL")],
                        "Scoring Inside": [("2PT FG%", "FG2%"), ("2PT FGM/gm", "FG2M")],
                        "Ball Security / Turnovers": [("TO/gm", "TO")],
                        "Ball Movement / Assists": [("AST/gm", "AST")],
                        "Paint Protection / Blocks": [("BLK/gm", "BLK")],
                        "Free Throws": [("FT%", "FT%"), ("FTM/gm", "FTM")],
                        "Fouls / Discipline": [("PF/gm", "PF")],
                        "Field Goal Efficiency": [("FG%", "FG%")],
                    }

                    # Compute UWW defensive stats (what opponents do AGAINST UWW)
                    _uww_allowed = {}
                    if not box.empty and "team" in box.columns:
                        _def_box = box[box["team"] != "UW-Whitewater"]
                        _dg = _def_box["opponent"].nunique() if not _def_box.empty else 1
                        if not _def_box.empty:
                            _uww_allowed["REB"] = _def_box["REB"].sum() / _dg
                            _uww_allowed["AST"] = _def_box["AST"].sum() / _dg
                            _uww_allowed["STL"] = _def_box["STL"].sum() / _dg
                            _uww_allowed["BLK"] = _def_box["BLK"].sum() / _dg
                            _uww_allowed["TO"] = _def_box["TO"].sum() / _dg
                            _uww_allowed["PF"] = _def_box["PF"].sum() / _dg
                            _uww_allowed["FG%"] = (_def_box["FGM"].sum() / _def_box["FGA"].sum() * 100) if _def_box["FGA"].sum() > 0 else 0
                            _uww_allowed["3PM"] = _def_box["FG3M"].sum() / _dg
                            _uww_allowed["3P%"] = (_def_box["FG3M"].sum() / _def_box["FG3A"].sum() * 100) if _def_box["FG3A"].sum() > 0 else 0
                            _uww_allowed["FTM"] = _def_box["FTM"].sum() / _dg
                            _uww_allowed["FT%"] = (_def_box["FTM"].sum() / _def_box["FTA"].sum() * 100) if _def_box["FTA"].sum() > 0 else 0
                            _dfg2m = _def_box["FGM"].sum() - _def_box["FG3M"].sum()
                            _dfg2a = _def_box["FGA"].sum() - _def_box["FG3A"].sum()
                            _uww_allowed["FG2M"] = _dfg2m / _dg
                            _uww_allowed["FG2%"] = (_dfg2m / _dfg2a * 100) if _dfg2a > 0 else 0

                    # --- Win/Loss stat breakdowns ---
                    _uww_stats_w, _uww_stats_l = {}, {}
                    _uww_allowed_w, _uww_allowed_l = {}, {}
                    if not uww_box.empty:
                        # Map each opponent in box score to W/L outcome
                        _opp_outcomes = {}
                        for _, _sr in schedule.iterrows():
                            if pd.notna(_sr.get("outcome")):
                                for _opp_name in uww_box["opponent"].unique():
                                    if str(_sr["opponent"]).startswith(_opp_name):
                                        _opp_outcomes[_opp_name] = _sr["outcome"]
                                        break
                        _win_opps = [o for o, r in _opp_outcomes.items() if r == "W"]
                        _loss_opps = [o for o, r in _opp_outcomes.items() if r == "L"]

                        def _compute_split_stats(_df, _n_games):
                            """Compute per-game stats from a filtered box score subset."""
                            _s = {}
                            if _df.empty or _n_games == 0:
                                return _s
                            _s["REB"] = _df["REB"].sum() / _n_games
                            _s["AST"] = _df["AST"].sum() / _n_games
                            _s["STL"] = _df["STL"].sum() / _n_games
                            _s["BLK"] = _df["BLK"].sum() / _n_games
                            _s["TO"] = _df["TO"].sum() / _n_games
                            _s["PF"] = _df["PF"].sum() / _n_games
                            _s["FG%"] = (_df["FGM"].sum() / _df["FGA"].sum() * 100) if _df["FGA"].sum() > 0 else 0
                            _s["3PM"] = _df["FG3M"].sum() / _n_games
                            _s["3P%"] = (_df["FG3M"].sum() / _df["FG3A"].sum() * 100) if _df["FG3A"].sum() > 0 else 0
                            _s["FTM"] = _df["FTM"].sum() / _n_games
                            _s["FT%"] = (_df["FTM"].sum() / _df["FTA"].sum() * 100) if _df["FTA"].sum() > 0 else 0
                            _fg2m = _df["FGM"].sum() - _df["FG3M"].sum()
                            _fg2a = _df["FGA"].sum() - _df["FG3A"].sum()
                            _s["FG2M"] = _fg2m / _n_games
                            _s["FG2%"] = (_fg2m / _fg2a * 100) if _fg2a > 0 else 0
                            return _s

                        # UWW offensive stats in wins vs losses
                        if _win_opps:
                            _uww_w_box = uww_box[uww_box["opponent"].isin(_win_opps)]
                            _uww_stats_w = _compute_split_stats(_uww_w_box, len(_win_opps))
                        if _loss_opps:
                            _uww_l_box = uww_box[uww_box["opponent"].isin(_loss_opps)]
                            _uww_stats_l = _compute_split_stats(_uww_l_box, len(_loss_opps))

                        # UWW allowed (defensive) stats in wins vs losses
                        if _win_opps and not box.empty:
                            _def_w = box[(box["team"] != "UW-Whitewater") & (box["opponent"].isin(_win_opps))]
                            _uww_allowed_w = _compute_split_stats(_def_w, len(_win_opps))
                        if _loss_opps and not box.empty:
                            _def_l = box[(box["team"] != "UW-Whitewater") & (box["opponent"].isin(_loss_opps))]
                            _uww_allowed_l = _compute_split_stats(_def_l, len(_loss_opps))

                    _n_wins = len(_win_opps) if not uww_box.empty else 0
                    _n_losses = len(_loss_opps) if not uww_box.empty else 0

                    # Show splits + stats for each detected category
                    for _cat, _side in _live_emphasis:
                        _badge = _side_badge_html(_side) if _side else ""
                        # Find matching split row
                        _split_match = ktv_splits[(ktv_splits["category"] == _cat) & (ktv_splits["side"] == _side)] if not ktv_splits.empty and "side" in ktv_splits.columns else pd.DataFrame()
                        if _split_match.empty:
                            _split_match = ktv_splits[ktv_splits["category"] == _cat] if not ktv_splits.empty else pd.DataFrame()
                        # Build split text
                        if not _split_match.empty:
                            sr = _split_match.iloc[0]
                            games_played = int(sr["games"])
                            if games_played > 0:
                                w, l = int(sr["wins"]), int(sr["losses"])
                                pct = sr["win_pct"]
                                pct_str = f" ({pct:.0%})" if pd.notna(pct) else ""
                                _split_txt = f"{w}W\u2013{l}L{pct_str}"
                            else:
                                _split_txt = "No previous games"
                        else:
                            _split_txt = ""
                        # Category header with split
                        _split_span = f' <span style="font-size:0.85rem;color:#555;margin-left:6px;">{_split_txt}</span>' if _split_txt else ""
                        st.markdown(f'<div style="margin-bottom:2px;"><strong>{html.escape(_cat)}</strong>{_split_span}{_badge}</div>', unsafe_allow_html=True)
                        # Stat comparison – 2 rows for clarity
                        _stat_items = _CAT_STAT_DISPLAY.get(_cat, [])
                        if _stat_items and (_uww_stats or _opp_stats):
                            if _side == "OPP":
                                # Row 1: opponent's offensive stats
                                _r1_parts = []
                                for _lbl, _key in _stat_items:
                                    _ov = _opp_stats.get(_key, 0)
                                    if "%" in _lbl:
                                        _r1_parts.append(f"{_lbl}: <strong>{_ov:.1f}%</strong>")
                                    else:
                                        _r1_parts.append(f"{_lbl}: <strong>{_ov:.1f}</strong>")
                                _r1 = " &nbsp;|&nbsp; ".join(_r1_parts)
                                # Row 2: what UWW allows (defensive)
                                _r2_parts = []
                                for _lbl, _key in _stat_items:
                                    _uv = _uww_stats.get(_key, 0)
                                    if "%" in _lbl:
                                        _r2_parts.append(f"{_lbl}: {_uv:.1f}%")
                                    else:
                                        _r2_parts.append(f"{_lbl}: {_uv:.1f}")
                                _r2 = " &nbsp;|&nbsp; ".join(_r2_parts)
                                st.markdown(f'<div style="font-size:0.85rem;color:#444;margin:0 0 2px 8px;">{html.escape(opp_display)}: {_r1}</div>', unsafe_allow_html=True)
                                st.markdown(f'<div style="font-size:0.85rem;color:#666;margin:0 0 10px 8px;">UWW allows: {_r2}</div>', unsafe_allow_html=True)
                            else:
                                # Row 1: UWW offensive stats
                                _r1_parts = []
                                for _lbl, _key in _stat_items:
                                    _uv = _uww_stats.get(_key, 0)
                                    if "%" in _lbl:
                                        _r1_parts.append(f"{_lbl}: <strong>{_uv:.1f}%</strong>")
                                    else:
                                        _r1_parts.append(f"{_lbl}: <strong>{_uv:.1f}</strong>")
                                _r1 = " &nbsp;|&nbsp; ".join(_r1_parts)
                                # Row 2: opponent's stats for comparison
                                _r2_parts = []
                                for _lbl, _key in _stat_items:
                                    _ov = _opp_stats.get(_key, 0)
                                    if "%" in _lbl:
                                        _r2_parts.append(f"{_lbl}: {_ov:.1f}%")
                                    else:
                                        _r2_parts.append(f"{_lbl}: {_ov:.1f}")
                                _r2 = " &nbsp;|&nbsp; ".join(_r2_parts)
                                st.markdown(f'<div style="font-size:0.85rem;color:#444;margin:0 0 2px 8px;">UWW: {_r1}</div>', unsafe_allow_html=True)
                                st.markdown(f'<div style="font-size:0.85rem;color:#666;margin:0 0 10px 8px;">{html.escape(opp_display)}: {_r2}</div>', unsafe_allow_html=True)
            else:
                st.caption("Not available.")

        # Full game plan in expander
        other = opp_plan[~opp_plan["topic"].isin(["KEYS TO VICTORY", "TEAM STRENGTHS"])]
        if not other.empty:
            st.markdown("")
            with st.expander("📋 **FULL GAME PLAN** — Offensive & Defensive Schemes", expanded=False):
                categories = list(other["category"].unique())
                # Split into two columns (Offense left, Defense right)
                gp_left, gp_right = st.columns(2)
                for idx, category in enumerate(categories):
                    group = other[other["category"] == category]
                    col = gp_left if idx % 2 == 0 else gp_right
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

                            with st.container(border=True):
                                _p_img = _get_player_img_b64(name)
                                if _p_img:
                                    st.markdown(f'<div style="text-align:center;margin-bottom:6px;"><img src="data:image/png;base64,{_p_img}" style="width:60px;height:75px;object-fit:cover;border-radius:6px;"></div>', unsafe_allow_html=True)
                                st.markdown(
                                    f"<div style='min-height:2.8em;line-height:1.4em;'>"
                                    f"<strong>{jersey_str} {name}</strong></div>",
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


    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">COMPARABLE OPPONENTS</div></div>', unsafe_allow_html=True)
    st.info("Comparable opponent data will be available once previous game data is collected for this opponent.")

    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">PROJECTED BOX SCORE</div></div>', unsafe_allow_html=True)
    uww_proj = load_table("uww_projected_box_score")
    aurora_proj = load_table("aurora_projected_box_score")

    if uww_proj.empty or aurora_proj.empty:
        st.info("Projected box score not available yet for this opponent.")
    else:
        proj_uww_total = uww_proj["projected_PTS"].sum()
        proj_opp_total = aurora_proj["projected_PTS"].sum()
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
                aurora_proj.sort_values("projected_PTS", ascending=False),
                ["name", "jersey_number", "role", "projected_PTS", "projected_REB", "projected_AST"],
            )

    # ==================== LINEUP SIMULATOR ====================
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
                _preset_choice = st.selectbox("Most-used lineups", _preset_labels, index=0, key="lineup_sim_preset")
                if _preset_choice != "-- Select a lineup --":
                    _preset_idx = _preset_labels.index(_preset_choice) - 1
                    _default_sel = _preset_options[_preset_idx]["players"]
                else:
                    _default_sel = []
            else:
                _default_sel = []
            _selected = st.multiselect(
                "Select 5 UWW players", _sim_players,
                default=_default_sel,
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
    import base64 as _b64_pg
    def _load_logo_b64_pg(team_name):
        logo_path = os.path.join(DATA_DIR, "logo", f"{team_name}.png")
        if os.path.exists(logo_path):
            with open(logo_path, "rb") as _lf:
                return _b64_pg.b64encode(_lf.read()).decode()
        return ""

    uww_logo_b64 = _load_logo_b64_pg("UW-Whitewater")
    opp_display = short_opponent or full_opponent
    opp_logo_b64 = _load_logo_b64_pg(short_opponent) if short_opponent else ""

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

    if game_box.empty and game_stints.empty:
        st.warning("No reconstructed box score or lineup data found for this game yet.")
    else:
        # Precompute lineup data
        if not game_stints.empty:
            game_stints["margin_per_min"] = (game_stints["uww_margin_change"] / game_stints["stint_minutes"]).round(2)
            game_stints = game_stints.sort_values("stint_minutes", ascending=False)

        compact_cols = [c for c in ["player", "PTS", "REB", "AST", "STL", "TO", "FG%"]
                         if c in game_box.columns]
        full_cols = [c for c in ["player", "started", "PTS", "FGM", "FGA", "FG%", "FG3M", "FG3A", "3P%",
                                  "FTM", "FTA", "FT%", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF"]
                      if c in game_box.columns]
        teams = sorted(game_box["team"].unique().tolist()) if not game_box.empty else []

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
        else:
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
    except Exception:
        pass

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
        _best_lu = lineup_agg[lineup_agg["minutes"] >= 2.0].nlargest(3, "margin_per_min")
        _worst_lu = lineup_agg[lineup_agg["minutes"] >= 2.0].nsmallest(3, "margin_per_min")

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

        video_only = st.checkbox("Show only video-tagged plays", value=False, key=f"pbp_vidonly_{short_opponent}")

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
                                     "video_description", "uww_score", "opp_score"]
                         if c in filtered_pbp.columns]
        st.dataframe(filtered_pbp[display_cols], hide_index=True, use_container_width=True, height=400)

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
                                f'<div style="font-weight:700;font-size:0.9rem;">{flag_row["player"]} {_cat_badge}</div>'
                                f'<div style="font-size:0.85rem;margin-top:4px;">{flag_row["flag"]}</div>'
                                f'<div style="font-size:0.78rem;color:#666;margin-top:3px;"><em>Evidence:</em> {flag_row.get("evidence", "-")}</div>'
                                f'<div style="font-size:0.78rem;color:#1b5e20;margin-top:2px;"><em>Recommendation:</em> {flag_row.get("recommendation", "-")}</div>'
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
                                f'<div style="font-weight:700;font-size:0.9rem;">{flag_row["player"]} {_cat_badge}</div>'
                                f'<div style="font-size:0.85rem;margin-top:4px;">{flag_row["flag"]}</div>'
                                f'<div style="font-size:0.78rem;color:#666;margin-top:3px;"><em>Evidence:</em> {flag_row.get("evidence", "-")}</div>'
                                f'<div style="font-size:0.78rem;color:#b71c1c;margin-top:2px;"><em>Recommendation:</em> {flag_row.get("recommendation", "-")}</div>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
    except Exception:
        pass




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
                <div style="color:#9DAAAC;font-size:1.0rem;margin-top:4px;">2025-26 Season Overview</div>
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
    except Exception:
        pass

    st.markdown('<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;margin:1.5rem 0 0.75rem;"><div style="font-weight:800;font-size:1.05rem;letter-spacing:0.5px;color:#4E2A84;">COACHING FLAGS OVERVIEW</div></div>', unsafe_allow_html=True)
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
                                     "video_description", "uww_score", "opp_score"]
                         if c in filtered.columns]
        st.dataframe(filtered[display_cols], hide_index=True, use_container_width=True, height=400)

    # ==================== SITUATIONAL SPLITS ====================
    stints = load_table("uww_lineup_stints")
    if not stints.empty:
        def _last_names_team(lineup_str):
            names = [n.strip() for n in str(lineup_str).split(",")]
            return ", ".join(parts[-1] if len(parts := n.split()) > 1 else n for n in names)

        # Map stints to W/L outcomes from schedule
        _opp_outcomes = {}
        for _, _sr in schedule.iterrows():
            if pd.notna(_sr.get("outcome")):
                for _opp_name in stints["opponent"].unique():
                    if str(_sr["opponent"]).startswith(_opp_name):
                        _opp_outcomes[_opp_name] = _sr["outcome"]
                        break
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
                            if _col in _ps.index and pd.notna(_ps[_col]):
                                _stat_parts.append(f'<span style="margin-right:20px;"><span style="color:#666;font-size:0.8rem;">{_lbl}</span> <span style="font-weight:700;font-size:1.1rem;color:#4E2A84;">{_ps[_col]:.1f}</span></span>')
                        if _stat_parts:
                            st.markdown(f'<div style="margin-top:8px;">{"".join(_stat_parts)}</div>', unsafe_allow_html=True)
                        # Additional stats row
                        _stat_parts2 = []
                        for _col, _lbl in [("FG%", "FG%"), ("3P%", "3P%"), ("FT%", "FT%"), ("STL", "SPG"), ("TO", "TOPG")]:
                            if _col in _ps.index and pd.notna(_ps[_col]):
                                _val = _ps[_col]
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
            except Exception:
                pass

            # --- Coaching Flags ---
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
                            f'<div style="font-weight:700;font-size:0.88rem;">{f["flag"]}</div>'
                            f'<div style="font-size:0.8rem;color:#555;margin-top:3px;"><em>{f["evidence"]}</em></div>'
                            f'<div style="font-size:0.78rem;color:#1b5e20;margin-top:2px;">{f.get("recommendation", "") if pd.notna(f.get("recommendation")) else ""}</div>'
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
                            f'<div style="font-weight:700;font-size:0.88rem;">{f["flag"]}</div>'
                            f'<div style="font-size:0.8rem;color:#555;margin-top:3px;"><em>{f["evidence"]}</em></div>'
                            f'<div style="font-size:0.78rem;color:#b71c1c;margin-top:2px;">{f.get("recommendation", "") if pd.notna(f.get("recommendation")) else ""}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

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
                        _cs_row = _card_season_lookup.get(_cs_key) or _card_season_lookup.get(_cs_alt)
                        if _cs_row is not None:
                            _ppg = f"{_cs_row['PTS']:.1f}" if pd.notna(_cs_row.get('PTS')) else "-"
                            _rpg = f"{_cs_row['REB']:.1f}" if pd.notna(_cs_row.get('REB')) else "-"
                            _apg = f"{_cs_row['AST']:.1f}" if pd.notna(_cs_row.get('AST')) else "-"
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

    # Top navigation bar (native Streamlit radio styled as navbar)
    _NAV_CSS = """
    <style>
    div[data-testid="stRadio"][data-st-key="main_nav"] > label { display: none; }
    div[data-testid="stRadio"][data-st-key="main_nav"] > div {
        background-color: #4E2A84;
        padding: 10px 20px;
        border-radius: 6px;
        display: flex;
        justify-content: center;
        gap: 0;
    }
    div[data-testid="stRadio"][data-st-key="main_nav"] > div > label {
        color: rgba(255, 255, 255, 0.85) !important;
        font-size: 14px !important;
        font-family: 'Montserrat', sans-serif !important;
        padding: 10px 18px !important;
        border-radius: 4px !important;
        cursor: pointer;
        margin: 0 !important;
        white-space: nowrap;
    }
    div[data-testid="stRadio"][data-st-key="main_nav"] > div > label > div:first-child {
        display: none !important;
    }
    div[data-testid="stRadio"][data-st-key="main_nav"] > div > label[data-checked="true"] {
        background-color: #6B3FA0 !important;
        color: #FFFFFF !important;
        font-weight: 700 !important;
    }
    </style>
    """
    st.markdown(_NAV_CSS, unsafe_allow_html=True)
    page = st.radio(
        "Navigation",
        ["Home", "Upcoming Game", "Previous Games", "Team", "Players"],
        horizontal=True,
        label_visibility="collapsed",
        key="main_nav",
    )
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


if __name__ == "__main__":
    main()


