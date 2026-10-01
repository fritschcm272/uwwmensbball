# 87_build_html_scouting_brief_for_upcoming.py -- code for the notebook section "Build a one-file HTML scouting brief for the upcoming opponent ---------------------------"
# Runs inside the notebook via run_section("87_build_html_scouting_brief_for_upcoming"); its settings are in that notebook cell.

# --- Build a one-file HTML scouting brief for the upcoming opponent ----------------------------------------
# An executive summary the staff can read (or print, or forward) BEFORE they sit down to write their own
# scouting reports -- the handful of things from across this whole notebook that change how you prepare,
# not a dump of every table.
#
# Reads the CSVs the export cell just wrote rather than the in-memory DataFrames above. That is deliberate:
# those CSVs are exactly what the Streamlit app reads, so the brief and the app can never quietly disagree
# about a number -- and a coach who checks a figure in the app against the emailed brief gets the same
# answer. It also means this cell can be re-run on its own without re-running the notebook.
#
# Output is a single self-contained file: no images, no scripts, no external CSS, so it survives being sent
# as an email attachment and prints cleanly.
#
# Every section stands or falls on its own. With before_scout="yes" there is no game plan, no player notes
# and no tag-based comparisons, so those sections drop out and the footer names the tables that were empty
# -- a coach should never have to wonder whether data was missing or the brief was broken.
import html as _sb_html

_SB_OUT_DIR = os.path.join(APP_DATA_DIR, "scouting_briefs")

# ---- THE BOTTOM LINE: when a conditional sentence is printed ------------------------------------------
# Some Bottom Line sentences only appear past a threshold -- below it the difference isn't big enough to
# change how we prepare, and printing it anyway trains the staff to skim the section. These are the ONLY
# place the thresholds live: the rule text in each sentence's note (which the brief links to, and the app
# prints) is generated from them, so changing a number here updates the explanation too.
# Roster layout. "table" = one wide row per player (the original). "stacked" = a header bar per player
# (photo, name, bio) with the full width below for the box-score line, WHERE HE SHOOTS FROM (from the
# play-by-play) and the reads. Stacked replaces the separate SHOT LOCATIONS section, whose zone split is a
# placeholder; with "table" that section stays where it was.

BOTTOM_LINE_RULES = {
    # Tempo: printed when EITHER is true.
    "tempo_pace_gap": 5,          # their possessions per game minus ours, either direction
    "tempo_early_share": 40,      # % of their tagged possessions that shoot inside 10 seconds
    # Four factors: printed when BOTH are true, so it names one clear story rather than a close call.
    "ff_min_weighted": 1.0,       # the top factor's weighted gap, absolute
    "ff_dominance": 2.0,          # ...and at least this many times the second-largest factor's
    # Style matchups (TEAMS LIKE ... panels, no longer their own sections): printed when ALL are true.
    "style_min_games": 3,         # games behind the record
    "style_min_confidence": 0.35, # best match in the panel at least this confident (the app's amber/red cut)
    "style_lopsided": 0.75,       # win share at/above this, or at/below 1 minus this
    # Rebounding thresholds live in REBOUND_RULES (Keys to Victory cell), because the key, this sentence
    # and the roster read must all fire on the same numbers. Read from there, never restated here.
}


_SB_UWW = "UW-Whitewater"


# --------------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------------

class _SbData:
    """CSV access that never raises on a missing or empty table.

    A scouting report assembled from twenty-odd tables should not fail to build because one of
    them hasn't been produced yet -- an early-season run legitimately has no lineup data, and a
    before_scout run legitimately has no game plan. Missing is recorded, not fatal.
    """

    def __init__(self, data_dir):
        self.dir = data_dir
        self.missing = []
        self.sample_dropped = []
        self._cache = {}

    def __call__(self, name):
        if name not in self._cache:
            path = os.path.join(self.dir, f"{name}.csv")
            try:
                df = pd.read_csv(path)
            except Exception:
                df = pd.DataFrame()
            # No sample data on the brief (requested). Placeholder rows (is_sample True) are dropped HERE,
            # once, for every table the brief reads, so a section whose data is all placeholder simply
            # doesn't print. The app reads the CSVs itself and still shows them, labelled as sample.
            if not df.empty and "is_sample" in df.columns:
                _is_s = df["is_sample"].astype(str).str.strip().str.lower().isin(["true", "1"])
                if _is_s.any():
                    self.sample_dropped.append(name)
                    df = df[~_is_s].reset_index(drop=True)
            if df.empty:
                self.missing.append(name)
            self._cache[name] = df
        return self._cache[name]


def _sb_num(series):
    return pd.to_numeric(series, errors="coerce")


def _sb_pct(made, att):
    made, att = float(made or 0), float(att or 0)
    return round(100 * made / att, 1) if att else None


def _sb_fmt(value, digits=1, dash="--"):
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
        return dash
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}" if digits else f"{value:.0f}"
    return str(value)


def _sb_esc(value):
    return _sb_html.escape("" if value is None else str(value))


def _sb_clean(value):
    """One scalar's worth of the same test _sb_has_text applies to a column."""
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in ("nan", "none") else text


def _sb_has_text(series):
    """True where a column holds a real value. An empty tag round-trips through CSV as NaN, and
    NaN.astype(str) is the literal text "nan" -- which passes a `!= ""` check and then shows up in the brief
    as a coverage (or a player) called "nan". Every "is this blank?" filter on CSV data goes through here."""
    return series.notna() & ~series.astype(str).str.strip().str.lower().isin(["", "nan", "none"])


def _sb_split(value):
    """Split a pipe-joined field into its items, dropping anything blank.

    Reads go through here rather than `str(value or "").split(" | ")`, which looks safe and isn't: an
    empty CSV cell arrives from pandas as a float NaN, and NaN is TRUTHY, so the `or ""` never fires and
    str(NaN) yields the literal text "nan" -- which then renders as a bullet point reading "nan".
    """
    text = _sb_clean(value)
    return [part.strip() for part in text.split(" | ") if part.strip()] if text else []


def _sb_has_text(series):
    """True where a column holds something a coach would actually read.

    A missing scouting note arrives here three different ways -- a real NaN, an empty string, or
    the literal text "nan" left behind by an earlier astype(str) -- and all three have to count as
    empty, or a player with no notes gets his own write-up block containing nothing.
    """
    # fillna BEFORE astype(str): in this pandas version .astype(str) on a float NaN leaves a real
    # null rather than the text "nan", so every subsequent comparison returns True and a player
    # with no notes passes the filter. The same trap is documented in the parser itself.
    cleaned = series.fillna("").astype(str).str.strip()
    return cleaned.ne("") & ~cleaned.str.lower().isin(["nan", "none"])


# --------------------------------------------------------------------------------------------
# Who are we playing
# --------------------------------------------------------------------------------------------

def _sb_resolve_matchup(_sb_d):
    """The upcoming game, and the opponent's short name as every other table spells it.

    uww_schedule holds every team's rows (_SB_UWW's own plus each opponent's), so filter to _SB_UWW's
    before looking for the Upcoming flag. The short name is then resolved against the tables that
    actually key on it, rather than assumed to equal the schedule's own opponent text -- those two
    agree in the normal case, but the whole point of pinning it down here is so that they can't
    quietly disagree in the report.
    """
    sched = _sb_d("uww_schedule")
    if sched.empty or "Upcoming" not in sched.columns:
        return None, None, None

    uww_rows = sched[sched["team"].astype(str).str.contains("Whitewater", case=False, na=False)]
    upcoming = uww_rows[uww_rows["Upcoming"].astype(str).str.strip().str.lower() == "yes"]
    if upcoming.empty:
        return None, None, None
    game = upcoming.iloc[0]
    scheduled_name = str(game["opponent"]).strip()

    candidates = set()
    for table, col in (("uww_player_profiles", "opponent"), ("uww_opponent_team_totals", "opponent"),
                       ("uww_opponent_rosters", "opponent")):
        df = _sb_d(table)
        if not df.empty and col in df.columns:
            candidates |= set(df[col].dropna().astype(str))

    short = next(
        (c for c in sorted(candidates, key=len, reverse=True)
         if c.lower() in scheduled_name.lower() or scheduled_name.lower() in c.lower()),
        scheduled_name,
    )
    return game, scheduled_name, short


# --------------------------------------------------------------------------------------------
# Team-level numbers
# --------------------------------------------------------------------------------------------

def _sb_team_line(box, team_col, team_value, invert=False):
    """Per-game team averages straight from a play-by-play-derived box score.

    Deliberately NOT read off uww_player_profiles: that table mixes conventions (PTS/REB/MIN are
    per game, AST/STL/BLK/TO are season totals awaiting a games-played divisor), which is exactly
    the kind of thing that produces a report where two numbers on the same row mean different
    things. A raw box score has one convention: totals. Divide once, here.
    """
    if box.empty or team_col not in box.columns:
        return {}
    mask = box[team_col].astype(str) == str(team_value)
    rows = box[~mask] if invert else box[mask]
    if rows.empty:
        return {}

    games = rows["game_date"].nunique() if "game_date" in rows.columns else 0
    if not games:
        return {}

    total = {c: _sb_num(rows[c]).sum() if c in rows.columns else 0
             for c in ("PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA",
                       "REB", "OREB", "DREB", "AST", "STL", "BLK", "TO")}
    return {
        "games": games,
        "PTS": total["PTS"] / games,
        "REB": total["REB"] / games,
        "AST": total["AST"] / games,
        "TO": total["TO"] / games,
        "STL": total["STL"] / games,
        "BLK": total["BLK"] / games,
        "FG%": _sb_pct(total["FGM"], total["FGA"]),
        "3P%": _sb_pct(total["FG3M"], total["FG3A"]),
        "FT%": _sb_pct(total["FTM"], total["FTA"]),
        "3PA": total["FG3A"] / games,
        "FGA": total["FGA"] / games,
        # Pace: possessions per game, same estimate the app's tempo table uses (FGA - OREB + TO +
        # 0.475*FTA) over the same rows -- players AND the synthetic TEAM row, which carries team
        # turnovers. Left out entirely when the box has no OREB column: the sum above would silently
        # treat it as zero and overstate pace by every offensive rebound.
        "PACE": ((total["FGA"] - total["OREB"] + total["TO"] + 0.475 * total["FTA"]) / games
                 if "OREB" in rows.columns else None),
    }


# --- Four Factors ---------------------------------------------------------------------------------------
# Dean Oliver's own weighting -- shooting matters most, free throws least. Copied from the app rather than
# re-chosen, so the brief's table and the app's dialog can't rank the factors differently.
_SB_FF_WEIGHTS = {"eFG%": 0.40, "TOV%": 0.25, "ORB%": 0.20, "FT Rate": 0.15}
# Higher is better for three of them; TOV% is the exception -- a turnover is a lost possession.
_SB_FF_HIGHER_IS_BETTER = {"eFG%": True, "TOV%": False, "ORB%": True, "FT Rate": True}


def _sb_possessions(fga, oreb, to, fta):
    """The standard possession estimate. A box score carries no possession count, so this is the widely
    used approximation: a possession ends on a made shot, a defensive rebound, a turnover, or the last free
    throw of a trip -- 0.44 approximating how often an FTA is the last of its trip."""
    return fga - oreb + to + 0.44 * fta


def _sb_four_factors(team_box, opp_box):
    """eFG%, TOV%, ORB% and FT Rate for team_box's side. opp_box (the other side over the same games) is
    required for ORB%, whose denominator is the opponent's defensive rebounds."""
    def total(df, col):
        return _sb_num(df[col]).sum() if col in df.columns else 0

    fgm, fga = total(team_box, "FGM"), total(team_box, "FGA")
    fg3m, to = total(team_box, "FG3M"), total(team_box, "TO")
    fta, oreb = total(team_box, "FTA"), total(team_box, "OREB")
    opp_dreb = total(opp_box, "DREB")
    poss = _sb_possessions(fga, oreb, to, fta)
    return {
        "eFG%": ((fgm + 0.5 * fg3m) / fga * 100) if fga > 0 else None,
        "TOV%": (to / poss * 100) if poss > 0 else None,
        "ORB%": (oreb / (oreb + opp_dreb) * 100) if (oreb + opp_dreb) > 0 else None,
        "FT Rate": (fta / fga * 100) if fga > 0 else None,
    }


def _sb_player_table(_sb_d, short):
    """One row per opponent player: identity from the roster, production from their own film."""
    box = _sb_d("uww_opponent_prior_games_box_score")
    profiles = _sb_d("uww_player_profiles")

    rows = []
    if not box.empty and "team" in box.columns:
        own = box[box["team"].astype(str) == str(short)]
        own = own[own["player"].astype(str) != "TEAM"]
        if not own.empty:
            grouped = own.groupby("player")
            for name, g in grouped:
                games = g["game_date"].nunique() if "game_date" in g.columns else len(g)
                total = {c: _sb_num(g[c]).sum() if c in g.columns else 0
                         for c in ("PTS", "REB", "AST", "STL", "BLK", "TO", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA")}
                rows.append({
                    "name": str(name),
                    "games": games,
                    "PTS": total["PTS"] / games if games else None,
                    "REB": total["REB"] / games if games else None,
                    "AST": total["AST"] / games if games else None,
                    "STL": total["STL"] / games if games else None,
                    "BLK": total["BLK"] / games if games else None,
                    "TO": total["TO"] / games if games else None,
                    "FG%": _sb_pct(total["FGM"], total["FGA"]),
                    "3P%": _sb_pct(total["FG3M"], total["FG3A"]),
                    "FT%": _sb_pct(total["FTM"], total["FTA"]),
                    # Season totals kept alongside the per-game rates: the reads below need volume to
                    # decide whether a percentage means anything, and a rate alone can't say that.
                    "FGA": total["FGA"],
                    "3PA": total["FG3A"],
                    "FTA": total["FTA"],
                    "PTS_total": total["PTS"],
                })

    table = pd.DataFrame(rows)
    if table.empty:
        return table

    ident_cols = ["name", "jersey_number", "position", "height", "class_year", "role",
                  "player_notes", "keys_to_defending", "notes_tags_display", "keys_tags_display"]
    # Two identity sources, tried in order, the second only filling gaps the first left. Both are
    # built from the scouting report, so with before_scout="yes" neither exists and this is a no-op
    # -- which is why the jersey fallback below reads the play-by-play name itself.
    for ident_table in (profiles, _sb_d("uww_opponent_rosters")):
        if ident_table.empty or not {"opponent", "name"}.issubset(ident_table.columns):
            continue
        ident = ident_table[ident_table["opponent"].astype(str) == str(short)]
        ident = ident[[c for c in ident_cols if c in ident.columns]].drop_duplicates("name")
        if ident.empty:
            continue
        table = table.merge(ident, on="name", how="left", suffixes=("", "_alt"))
        for col in ident_cols:
            alt = f"{col}_alt"
            if alt in table.columns:
                table[col] = table[col].where(_sb_has_text(table[col]), table[alt])
                table = table.drop(columns=[alt])

    for col in ident_cols:
        if col not in table.columns:
            table[col] = None

    # Some play-by-play feeds prefix the jersey onto the name ("3 Jalen Ward"); others carry no
    # number at all. Take one off the front when it's there, and strip it from the displayed name so
    # it isn't printed twice. When neither the roster nor the feed has a number the column stays
    # blank, which is the honest answer -- better than inventing one.
    parsed = table["name"].astype(str).str.extract(r"^#?\s*(\d{1,2})\s+(.*)$")
    table["jersey_number"] = table["jersey_number"].where(
        _sb_has_text(table["jersey_number"]), parsed[0])
    table["name"] = parsed[1].where(parsed[1].notna(), table["name"])

    table["role"] = table["role"].fillna("Bench")
    # Season volume first: ordering by PPG put a one-game 15-point night above a four-game 13.5 ppg starter.
    return table.sort_values(["PTS_total", "PTS"], ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------------------------

# --------------------------------------------------------------------------------------------
# Presentation -- deliberately the app's own visual language
# --------------------------------------------------------------------------------------------
# Every value below is lifted from streamlit_app.py rather than invented here: Montserrat and the
# --warhawk-* variables from its global stylesheet, #1a1a2e / 10px radius / #9DAAAC labels from the
# Upcoming Game banner, the 1px #e0e0e0 + 8px radius bordered box from section_header(), and the
# "N. <headline>" + dimmed 0.8rem evidence line from the Keys to Victory renderer. A coach
# reading this next to the app should not be able to tell they came from different code.

_SB_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap');

:root {
  --warhawk-purple: #4E2A84;
  --warhawk-gray: #9DAAAC;
  --warhawk-light: #F0EDF5;
  --banner: #1a1a2e;
  --edge: #e0e0e0;
  --body: #262730;
  --dim: #666;
  --win: #2e7d32;
  --loss: #c62828;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 18px 18px 56px;
  background: #fff; color: var(--body);
  font-family: 'Montserrat', -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 15px; line-height: 1.5;
  -webkit-text-size-adjust: 100%;
}
.page { max-width: 1000px; margin: 0 auto; }
p { margin: 0 0 0.65rem; }

/* section_header() */
.sect { border: 1px solid var(--edge); border-radius: 8px; padding: 12px 16px; margin: 1.5rem 0 0.75rem; }
.sect .t { font-weight: 800; font-size: 1.05rem; letter-spacing: 0.5px; color: var(--warhawk-purple); }
.card { border: 1px solid var(--edge); border-radius: 8px; padding: 12px 16px; margin: 0 0 0.75rem; }
.card .hd { font-weight: 800; font-size: 1.05rem; letter-spacing: 0.5px; margin-bottom: 8px; }

/* Two panels side by side, the way the app pairs Team Stats with Last Five Games. min-width:0 is
   load-bearing: without it a flex child refuses to shrink below its content's intrinsic width, and
   the roster table's eight columns push the pair wider than the page instead of compressing. */
.cols { display: flex; gap: 16px; align-items: flex-start; }
.cols > .col { flex: 1; min-width: 0; }
.cols .sect { margin-top: 0; }
.cols table { font-size: 0.78rem; }
.cols th, .cols td { padding-left: 5px; padding-right: 5px; }
.lede { font-size: 0.95rem; }
ul.bl { margin: 0; padding-left: 1.1rem; }
ul.bl li { font-size: 0.95rem; margin-bottom: 5px; }
ul.bl li::marker { color: var(--warhawk-purple); }
ul.bl li:last-child { margin-bottom: 0; }

/* banner */
.banner { background: var(--banner); border-radius: 10px; padding: 22px 32px; margin-bottom: 0.75rem;
          display: flex; align-items: center; justify-content: space-between; }
.banner .side { text-align: center; flex: 1; display: flex; flex-direction: column; align-items: center; }
.banner .mid { justify-content: center; }
.banner .crest { height: 64px; display: flex; align-items: center; justify-content: center; margin-bottom: 8px; }
.banner .crest img { max-height: 64px; max-width: 90px; object-fit: contain; }
.banner .team { color: #fff; font-weight: 800; font-size: 1.4rem; letter-spacing: 0.5px; }
.banner .rec { color: var(--warhawk-gray); font-size: 1.05rem; font-weight: 600; margin-top: 3px; }
.banner .streak { color: #aabbcc; font-size: 0.8rem; font-style: italic; margin-top: 2px; }
.banner .when { color: var(--warhawk-gray); font-size: 1rem; font-weight: 500; }
.banner .vs { color: #fff; font-size: 1.6rem; font-weight: 700; margin: 4px 0; }
.banner .where { color: var(--warhawk-gray); font-size: 0.95rem; }

/* team stats: UWW left, stat centre, opponent right */
.cmp .row { display: flex; align-items: center; justify-content: space-between;
            padding: 7px 4px; border-bottom: 1px solid #f0f0f0; }
.cmp .row:last-child { border-bottom: 0; }
.cmp .us, .cmp .them { flex: 1; font-size: 0.95rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.cmp .us { color: var(--warhawk-purple); }
.cmp .them { color: #222; text-align: right; }
.cmp .stat { flex: 1.1; text-align: center; font-size: 0.8rem; color: var(--dim); font-weight: 600; }
.cmp .who { display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 8px; padding: 0 4px; }
.cmp .who .l { font-size: 0.95rem; font-weight: 700; color: var(--warhawk-purple); }
.cmp .who .c { font-size: 0.85rem; color: #888; }
.cmp .who .r { font-size: 0.95rem; font-weight: 700; color: #222; }
.lead { font-size: 0.68rem; font-weight: 700; padding: 1px 6px; border-radius: 8px; margin-left: 6px;
        vertical-align: middle; }
.lead.us { background: var(--warhawk-light); color: var(--warhawk-purple); }
.lead.them { background: #f1f1f1; color: #555; }

.ff-lede { font-size: 0.88rem; margin: 0 0 6px; }
td.ff-us { color: var(--warhawk-purple); font-weight: 700; }
td.ff-them { color: var(--loss); font-weight: 700; }

/* keys */
.ktvcat { font-size: 0.72rem; font-weight: 800; letter-spacing: 0.8px; text-transform: uppercase;
          color: var(--warhawk-purple); border-bottom: 2px solid var(--warhawk-light);
          padding-bottom: 4px; margin: 14px 0 10px; }
.ktvcat:first-child { margin-top: 0; }
.key { margin-bottom: 14px; }
.key .hl { font-size: 0.95rem; font-weight: 700; }
/* The lineup and shot-look keys carry multi-line captions ("Worst +/- lineups:" then one unit per
   line). pre-line keeps those breaks without turning the text into a <pre> block. */
.key .ev { font-size: 0.8rem; color: var(--dim); margin: 0 0 6px 18px; white-space: pre-line; }
.key .why { font-size: 0.88rem; margin: 0 0 0 18px; font-style: italic; color: #333;
            white-space: pre-line; }
.key .src { border: 1px solid #666; background: #fff; font-size: 0.65rem; font-weight: 600;
            padding: 1px 7px; border-radius: 8px; margin-left: 4px; white-space: nowrap; }

/* tables */
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th { text-align: right; font-weight: 700; color: var(--dim); font-size: 0.72rem; letter-spacing: 0.3px;
     padding: 0 8px 6px; border-bottom: 1px solid var(--edge); white-space: nowrap; }
td { text-align: right; padding: 7px 8px; border-bottom: 1px solid #f0f0f0; white-space: nowrap;
     font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: 0; }
th:first-child, td:first-child { text-align: left; white-space: normal; }
td.wrap { text-align: left; white-space: normal; font-variant-numeric: normal; }
th.read, td.read { text-align: left; white-space: normal; font-variant-numeric: normal; min-width: 130px; }
.dot { display: block; font-size: 0.76rem; line-height: 1.35; padding-left: 10px; position: relative; }
.dot::before { content: "\u25aa"; position: absolute; left: 0; }
.dot.good { color: #1b5e20; }
.dot.bad { color: #8c1d2c; }
tr.starter td { font-weight: 700; }
td.jersey { color: var(--warhawk-purple); font-weight: 700; }
th.num, td.num { text-align: right; width: 2.4rem; }
.meta { color: #888; font-weight: 500; font-size: 0.78rem; margin-left: 7px; }

/* player notes, mirroring the Player Details dialog */
.player { border: 1px solid var(--edge); border-radius: 8px; padding: 12px 16px; margin-bottom: 10px; }
.player .nm { font-weight: 700; font-size: 1rem; }
.player .role { font-size: 0.6rem; font-weight: 700; letter-spacing: 0.4px; text-transform: uppercase;
                background: var(--warhawk-light); color: var(--warhawk-purple); border-radius: 8px;
                padding: 2px 7px; margin-left: 6px; vertical-align: middle; }
.player .statline { font-size: 0.8rem; color: var(--dim); font-variant-numeric: tabular-nums;
                    margin-top: 2px; }
.player .reads { margin-top: 6px; }
.player .ln { color: #888; font-weight: 500; font-size: 0.8rem; margin-left: 8px; }
.player .lbl { font-weight: 700; font-size: 0.85rem; }
.player .notes { font-style: italic; color: #333; font-size: 0.88rem; margin: 4px 0 0; }
.player .keys { font-size: 0.88rem; margin: 4px 0 0; }
.srcblock { border-left: 3px solid var(--edge); padding: 2px 0 2px 10px; margin: 8px 0 0; }
.srcblock.coach { border-left-color: var(--warhawk-purple); }
.srcblock.derived { border-left-color: #37474f; }
.srclabel { font-size: 0.65rem; font-weight: 700; letter-spacing: 0.4px; text-transform: uppercase;
            color: #888; margin-bottom: 2px; }
.kd { margin-top: 4px; }
.kd .lbl { font-weight: 700; font-size: 0.8rem; display: block; }
.kdline { font-size: 0.85rem; padding-left: 10px; position: relative; }
.kdline::before { content: "\u25aa"; position: absolute; left: 0;
                 color: var(--warhawk-purple); }

/* last five */
.five { display: flex; flex-wrap: wrap; gap: 10px; }
.five .g { border: 1px solid var(--edge); border-radius: 8px; padding: 10px 14px; min-width: 150px; flex: 1; }
.five .d { color: #888; font-size: 0.78rem; }
.five .o { font-size: 0.92rem; font-weight: 600; margin: 2px 0; }
.five .r { font-weight: 700; font-size: 0.92rem; }
.five .r.w { color: var(--win); }
.five .r.l { color: var(--loss); }

/* style matchup cards */
.matchrow { display: flex; gap: 10px; align-items: stretch; }
.matchrow > .match { flex: 1; min-width: 0; margin-bottom: 0; }
.match { border: 1px solid #eee; border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; }
.match .nm { font-weight: 700; font-size: 0.95rem; color: var(--warhawk-purple); }
.match .score { font-size: 1.6rem; font-weight: 800; line-height: 1.1; }
.match .score .of { font-size: 0.7rem; color: #888; font-weight: 600; }
.match .sub { font-size: 0.68rem; color: #999; }
.match .conf { font-size: 0.68rem; font-weight: 700; }
.match .conf.hi { color: #2e7d32; }
.match .conf.mid { color: #8a6d3b; }
.match .conf.lo { color: #b3261e; }
.match .meet { font-size: 0.85rem; margin-top: 2px; }
.match .meet .w { color: var(--win); font-weight: 700; }
.match .meet .l { color: var(--loss); font-weight: 700; }
.match .alike { font-size: 0.75rem; color: #2e7d32; margin-top: 6px; }
.match .differs { font-size: 0.75rem; color: #c62828; }
.match .gap { font-size: 0.72rem; color: #666; margin-top: 2px; }
.strip { border: 1px solid #eee; border-radius: 8px; padding: 10px 12px; margin-top: 8px; font-size: 0.85rem; }
.strip .lb { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.4px; color: var(--warhawk-purple);
             text-transform: uppercase; margin-bottom: 2px; }
.thin { font-size: 0.78rem; color: #8a6d3b; background: #fdf6e3; border-radius: 6px; padding: 8px 10px;
        margin: 0 0 8px; }

.flag { margin-bottom: 10px; }
.flag .fl { font-size: 0.9rem; }
.flag .conf-tag { font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.4px;
                  color: #888; border: 1px solid var(--edge); border-radius: 8px; padding: 1px 6px;
                  margin-left: 4px; white-space: nowrap; }

.note { font-size: 0.78rem; color: var(--dim); margin: 8px 0 0; }

/* SAMPLE DATA boxes. Anything generated as a placeholder (is_sample=True in its CSV) is drawn inside one of
   these and nowhere else, so a coach can never mistake a placeholder for scouting. */
.sample { border: 2px solid #c62828; background: #fff5f5; border-radius: 8px; padding: 10px 14px 12px;
          margin: 0 0 0.75rem; }
.sample .sample-tag { display: inline-block; background: #c62828; color: #fff; font-size: 0.66rem;
                      font-weight: 800; letter-spacing: 0.6px; text-transform: uppercase; border-radius: 6px;
                      padding: 2px 8px; margin-bottom: 6px; }
.sample .sample-why { font-size: 0.78rem; color: #8c1d2c; margin: 0 0 8px; }
.sample table td { border-bottom-color: #f6dada; }
.sect.sample-sect { border: 2px solid #c62828; background: #fff5f5; }
.pc-grid { display: flex; gap: 12px; flex-wrap: wrap; }
/* ---- condensed layout (#6) ---- */
.pb { break-after: page; page-break-after: always; height: 0; }
.divider { margin: 18px 0 10px; padding: 10px 14px; border-radius: 8px; background: var(--banner); color: #fff; }
.divider .dt { font-size: 1.05rem; font-weight: 800; letter-spacing: 0.6px; }
.divider .ds { font-size: 0.78rem; color: var(--warhawk-gray); margin-top: 2px; }
.linkbar { font-size: 0.8rem; margin: -4px 0 10px; }
a.applink { color: var(--warhawk-purple); font-weight: 700; text-decoration: none; white-space: nowrap; }
a.applink:hover { text-decoration: underline; }
.applink.off { color: var(--dim); font-weight: 600; font-style: italic; }
a.nmlink { color: inherit; text-decoration: none; border-bottom: 1px dotted #b9a9d3; }
sup.fn { font-size: 0.62rem; color: var(--warhawk-purple); font-weight: 700; margin-left: 2px; }
sup.fn a.fnlink { color: inherit; text-decoration: none; border-bottom: 1px dotted #b9a9d3; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; align-items: start; }
/* Newspaper-style flow: cards fill the first column then the second, so a short card never strands the rest
   of a page the way a grid row does in print. */
.flow2 { column-count: 2; column-gap: 12px; }
.flow2 > .player, .flow2 > .gcell { display: inline-block; width: 100%; break-inside: avoid; }
.grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0 10px; align-items: start; }
.player, .key, .match { break-inside: avoid; page-break-inside: avoid; }
.chips { display: flex; flex-wrap: wrap; gap: 4px 6px; margin-top: 6px; }
.chip { font-size: 0.68rem; border-radius: 10px; padding: 1px 8px; background: #f3f0f8; color: var(--body); }
.chip.warn { background: #fdf6e3; color: #8a6d3b; }
.ktvline { display: flex; gap: 6px; align-items: baseline; padding: 3px 0; border-bottom: 1px solid #f2f2f2; font-size: 0.9rem; }
.ktvline:last-child { border-bottom: 0; }
.ktvline .n { font-weight: 800; color: var(--warhawk-purple); min-width: 1.6em; }
.ktvline .src { font-size: 0.6rem; font-weight: 700; letter-spacing: 0.3px; text-transform: uppercase; border: 1px solid; border-radius: 8px; padding: 0 6px; margin-left: 4px; white-space: nowrap; vertical-align: middle; }
.tier-h { font-size: 0.8rem; font-weight: 800; letter-spacing: 0.5px; text-transform: uppercase; color: var(--warhawk-purple); margin: 12px 0 2px; }
.tier-c { font-size: 0.76rem; color: var(--dim); margin: 0 0 6px; }
table.compact td, table.compact th { padding: 4px 6px; font-size: 0.78rem; }
td.nm { font-weight: 700; white-space: nowrap; }
.mini { font-size: 0.74rem; color: var(--dim); }
.results { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.foul-icon { font-size: 1rem; text-align: center; }
tr.serrow td { font-weight: 700; background: var(--warhawk-light); }
tr.setrow td:first-child { padding-left: 12px; }
td.foul-icon { font-size: 0.95rem; font-weight: 700; }
.tbl-bul { margin: 0; padding-left: 14px; }
.tbl-bul li { margin: 0 0 1px; }
/* Defense-family table: THEIR offense and OUR defense sit under separate labelled bands with different
   tints, so a coach can't mistake "PPP allowed" (ours) for "PPP" (theirs) at a glance. */
table.dfam .dfam-band th { font-size: 0.6rem; letter-spacing: 0.5px; text-transform: uppercase;
                            text-align: center; padding: 3px 4px; border-bottom: 0; }
table.dfam th.band-them, table.dfam td.band-them { background: #f6f3fa; }
table.dfam th.band-us, table.dfam td.band-us { background: #eaf3ea; }
table.dfam .dfam-band th.band-them { color: var(--warhawk-purple); border-top: 2px solid var(--warhawk-purple); }
table.dfam .dfam-band th.band-us { color: #2e7d32; border-top: 2px solid #2e7d32; }
/* ---- stacked roster (ROSTER_LAYOUT = "stacked") ---- */
.pcard { border: 1px solid var(--edge); border-radius: 8px; margin: 0 0 10px; overflow: hidden;
         break-inside: avoid; page-break-inside: avoid; }
.pcard .ph { display: flex; align-items: center; gap: 10px; background: var(--warhawk-light);
             border-bottom: 2px solid var(--warhawk-purple); padding: 6px 10px; }
.pcard .ph img, .pcard .ph .photo-thumb { width: 42px; height: 42px; }
.pcard .ph-name { font-weight: 800; font-size: 0.95rem; }
.pcard .ph-bio { font-weight: 400; font-size: 0.72rem; color: var(--dim); }
.pcard .ph-foul { margin-left: auto; font-size: 0.72rem; font-weight: 700; white-space: nowrap; }
.pcard table.pstats { width: 100%; margin: 4px 0 0; }
.pcard table.pstats th, .pcard table.pstats td { text-align: center; }
.pcard table.sz-row { width: 100%; border-collapse: collapse; table-layout: fixed; margin: 2px 0 0; }
.pcard table.sz-row td { border: 0; padding: 3px 10px; vertical-align: top; text-align: left; }
.pcard .sz-cap { font-size: 0.62rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.4px;
                 color: var(--warhawk-purple); padding-bottom: 0 !important; }
.pcard .sz-cap .mini { text-transform: none; letter-spacing: 0; font-weight: 400; }
.pcard .sz-l { font-size: 0.66rem; color: var(--dim); font-weight: 400; }
.pcard .sz-bar { height: 6px; background: #ece8f3; border-radius: 3px; overflow: hidden; margin: 2px 0; }
.pcard .sz-bar span { display: block; height: 100%; background: var(--warhawk-purple); }
.pcard .sz-v { font-size: 0.74rem; font-weight: 400; }
.pcard .p-reads { padding: 2px 10px 6px; font-size: 0.76rem; }
.teamrow { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
/* ---- alternative offense layout #2 (_TEST): usage x efficiency quadrants ---- */
/* Flex, not CSS grid: the brief gets printed and PDF'd, and older print/WebKit engines silently collapse
   `display:grid` to a single stacked column -- which turns a 2x2 quadrant into a meaningless list. */
.quad { display: flex; flex-wrap: wrap; margin: 0 -4px; }
/* The UWW section carries five labelled lines per set; at half width those wrap into an unreadable
   column, so that section stacks its cells full width instead. */
.quad.quad-rich .quad-cell { width: 100%; }
.quad-cell { width: 50%; box-sizing: border-box; margin: 0 0 8px; padding: 7px 9px;
             border: 1px solid var(--edge); border-radius: 6px; border-top-width: 3px;
             break-inside: avoid; float: left; }
.quad-cell.q-good { border-top-color: #2e7d32; }
.quad-cell.q-up   { border-top-color: #1565c0; }
.quad-cell.q-bad  { border-top-color: #c62828; }
.quad-cell.q-dim  { border-top-color: #9e9e9e; }
.quad-h { font-size: 0.8rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.4px;
          display: flex; align-items: baseline; }
.quad-n { margin-left: auto; font-size: 0.68rem; font-weight: 700; color: var(--dim); }
.quad-sub { font-size: 0.68rem; color: var(--dim); margin-bottom: 5px; }
.quad-row { border-top: 1px dotted var(--edge); padding: 3px 0 2px; }
.quad-row:first-of-type { border-top: 0; }
.quad-set { font-weight: 700; font-size: 0.8rem; }
.quad-num { float: right; font-size: 0.78rem; font-weight: 700; }
.quad-meta { font-size: 0.68rem; color: var(--dim); clear: both; line-height: 1.35; }
.quad-meta .qk { display: inline-block; min-width: 54px; font-weight: 700; color: var(--warhawk-purple);
                 text-transform: uppercase; font-size: 0.58rem; letter-spacing: 0.3px; }
.quad-cov { font-size: 0.68rem; color: var(--warhawk-purple); font-weight: 600; clear: both; }
.quad-empty, .quad-more { font-size: 0.7rem; color: var(--dim); font-style: italic; padding-top: 3px; }
/* ---- alternative offense layout (_TEST) ---- */
.ot-situ { display: flex; align-items: baseline; gap: 8px; margin: 10px 0 4px;
           border-bottom: 2px solid var(--warhawk-purple); padding-bottom: 2px; }
.ot-situ-name { font-size: 0.82rem; font-weight: 800; text-transform: uppercase;
                letter-spacing: 0.5px; color: var(--warhawk-purple); }
.ot-situ-n { font-size: 0.68rem; color: var(--dim); margin-left: auto; }
.ot-row { margin: 5px 0 7px; break-inside: avoid; }
.ot-head { display: flex; align-items: baseline; gap: 8px; }
.ot-name { font-weight: 700; font-size: 0.84rem; }
.ot-num { margin-left: auto; font-size: 0.78rem; font-weight: 700; white-space: nowrap; }
.ot-bar { height: 7px; background: #ece8f3; border-radius: 4px; overflow: hidden; margin: 2px 0 3px; }
.ot-fill { display: block; height: 100%; background: var(--warhawk-purple); }
.ot-fill.ot-good { background: #2e7d32; }
.ot-fill.ot-bad { background: #c62828; }
.ot-num.ot-good { color: #2e7d32; }
.ot-num.ot-bad { color: #c62828; }
.ot-detail { font-size: 0.78rem; padding-left: 2px; }
.ot-cov { font-size: 0.72rem; color: var(--dim); }
/* Horizontal team-stat strip: one narrow column per stat, running left to right across the full width.
   Columns are allowed to shrink but not wrap mid-stat, so the strip stays one scannable row. */
.hstat { display: flex; align-items: stretch; gap: 0; width: 100%; overflow: hidden; }
.hs-col { flex: 1 1 0; min-width: 0; text-align: center; padding: 3px 2px; border-left: 1px solid var(--edge); }
.hs-col:first-child { border-left: 0; }
.hs-key { flex: 0 0 auto; text-align: right; padding-right: 8px; color: var(--dim); font-weight: 700; }
.hs-l { font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.3px; color: var(--dim);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hs-v { font-size: 0.86rem; line-height: 1.5; white-space: nowrap; }
.hs-win { font-weight: 800; color: var(--warhawk-purple); }
.fnhold { float: right; }
.tchip { border: 1px solid var(--edge); border-radius: 12px; padding: 2px 10px; font-size: 0.8rem; font-weight: 600; }
.strip-line { font-size: 0.8rem; margin: 4px 0; }
.results .rs { border: 1px solid var(--edge); border-radius: 6px; padding: 2px 8px; font-size: 0.74rem; }
.results .rs b.w { color: var(--win); } .results .rs b.l { color: var(--loss); }
.dayg { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 8px; }
.dayg .day { border: 1px solid var(--edge); border-radius: 6px; padding: 6px 8px; font-size: 0.74rem; break-inside: avoid; }
.sample .dayg .day { border-color: #f6dada; background: #fff; }
.dayg .day .dh { font-weight: 800; color: var(--warhawk-purple); margin-bottom: 4px; }
.dayg .day .sg { margin: 2px 0; } .dayg .day .sg .tie { color: var(--dim); }
.cols .matchrow { flex-direction: column; }
@media print {
  body { font-size: 10pt; padding: 0; }
  .card, .sample { padding: 6px 10px; margin-bottom: 6px; }
  .sect { padding: 4px 10px; margin: 8px 0 4px; }
  .player { padding: 6px 10px; }
  a.applink, a.nmlink { color: var(--warhawk-purple); }
  @page { size: letter; margin: 0.45in; }
}
.pc-grid > div { flex: 1; min-width: 260px; }
.pc-sub { font-size: 0.72rem; font-weight: 800; letter-spacing: 0.6px; text-transform: uppercase;
          color: var(--warhawk-purple); margin: 10px 0 4px; }
td.ppp-good { color: #1b5e20; font-weight: 700; }
td.ppp-bad { color: #8c1d2c; font-weight: 700; }
.pc-raw { color: #888; font-size: 0.74rem; }
.photo-thumb { width: 34px; height: 34px; border-radius: 50%; object-fit: cover; display: block; }
.photo-thumb-blank { background: #e0dbea; border: 1px solid var(--edge); }
.bio { display: flex; align-items: center; gap: 10px; margin: 6px 0 8px; padding: 4px 6px; border-radius: 6px; }
.bio.sample-bio { background: #fff5f5; border: 1px solid #f6dada; }
.bio-text { font-size: 0.82rem; color: var(--dim); }
details.gloss summary { cursor: pointer; font-size: 0.8rem; color: var(--warhawk-purple); font-weight: 700; margin-top: 8px; }
details.gloss table { margin-top: 6px; }
.sect.sample-sect .t { color: #c62828; }
.legend { font-size: 0.8rem; color: var(--dim); margin: 0 0 0.75rem; display: flex; gap: 14px; flex-wrap: wrap; }
.legend .sw { display: inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -2px;
              margin-right: 5px; }
.legend .sw.real { border: 1px solid var(--edge); background: #fff; }
.legend .sw.fake { border: 2px solid #c62828; background: #fff5f5; }
.pill-thin { font-size: 0.62rem; font-weight: 700; letter-spacing: 0.3px; text-transform: uppercase;
             color: #8a6d3b; background: #fdf6e3; border-radius: 8px; padding: 1px 7px; margin-left: 6px;
             vertical-align: middle; }
.caution { background: #fdf6e3; border: 1px solid #f0dca8; }
.caution .row { font-size: 0.85rem; padding: 4px 0; border-bottom: 1px solid #f3e6c4; }
.caution .row:last-child { border-bottom: 0; }
.caution .area { font-weight: 700; color: #8a6d3b; margin-right: 6px; }
td.call-foul { color: #1b5e20; font-weight: 700; }
td.call-nofoul { color: #8c1d2c; font-weight: 700; }
tr.dayhead td { background: var(--warhawk-light); color: var(--warhawk-purple); font-weight: 800;
                font-size: 0.78rem; letter-spacing: 0.4px; text-transform: uppercase; }
.sample tr.dayhead td { background: #fde3e3; color: #8c1d2c; }
.foot { margin-top: 1.5rem; padding-top: 12px; border-top: 1px solid var(--edge);
        font-size: 0.75rem; color: var(--dim); }

@media screen and (max-width: 820px) {
  .cols { display: block; }
  .matchrow { display: block; }
  .matchrow > .match { margin-bottom: 8px; }
  .cols .col + .col .sect { margin-top: 1.5rem; }
}
@media screen and (max-width: 720px) {
  .banner { padding: 16px; }
  .banner .team { font-size: 1rem; }
  .banner .crest, .banner .crest img { height: 44px; max-height: 44px; }
  .five .g { min-width: 130px; }
}
@media print {
  /* CONFIRMED BUG (fixed here): the responsive rules above used to be plain (max-width: ...) queries, and a
     Letter page is narrower than 820px -- so in print every side-by-side layout collapsed to one column.
     This block also used to forbid ANY card or table from splitting across pages, which left half-empty
     pages wherever a tall section didn't fit. Only small, self-contained blocks are kept whole now. */
  body { padding: 0; font-size: 9.5pt; line-height: 1.35; }
  .banner, .divider, .sample, .sect, .chip, td.ppp-good, td.ppp-bad { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .player, .key, .match, .gcell, .dayg .day, tr, .ktvline { break-inside: avoid; }
  .sect { break-after: avoid; }
  .banner { padding: 10px 14px; }
  .banner .crest, .banner .crest img { height: 40px; max-height: 40px; }
  .card, .sample { padding: 6px 10px; margin-bottom: 6px; }
  .sect { padding: 3px 10px; margin: 6px 0 4px; }
  .player { padding: 6px 10px; margin-bottom: 6px; }
  .photo-thumb { width: 28px; height: 28px; }
  /* Starter cards: reads as wrapping inline chips, note/key text a size down, so five fit one page. */
  .flow2 .player .reads { display: flex; flex-wrap: wrap; gap: 0 10px; margin: 2px 0; }
  .flow2 .player .reads .dot { font-size: 7.5pt; }
  .flow2 .player .notes { font-size: 8pt; line-height: 1.3; margin: 2px 0; }
  .flow2 .player .kdline { font-size: 8pt; line-height: 1.3; }
  .flow2 .player .statline, .flow2 .player .bio-text { font-size: 7.5pt; }
  .flow2 .player .bio { margin: 2px 0 4px; padding: 2px 4px; }
  .flow2 .player .srcblock { margin-top: 4px; padding-left: 8px; }
  .flow2 .player .nm { font-size: 10pt; }
}

/* Full-width KTV sentences with reasoning (requested) */
.ktv-sentence { 
    display: flex; align-items: flex-start; gap: 8px; margin-bottom: 10px; font-size: 0.9rem; line-height: 1.4;
}
.ktv-sentence .n { 
    font-weight: 700; color: var(--warhawk-purple); flex-shrink: 0; min-width: 20px;
}
.ktv-sentence .src {
    margin-left: auto; flex-shrink: 0;
}
"""


def _sb_headshot_b64(name):
    """A player's headshot from data/player_images as base64, or "" -- the same folder and filename variants
    the app's _get_player_img_b64() uses. This is the fallback when the FastScout roster page's own photo URL
    isn't available for a player (no live scrape yet for that team, or the scrape found no photo for him),
    which is why our own players showed no picture while the opponent's did: opponent headshots also get
    extracted from scouting-report PDFs into this folder, and UWW's don't come from a report at all.
    Embedded rather than linked so the brief stays a single self-contained file, like the crests."""
    import base64 as _sb_b64
    img_dir = os.path.join(APP_DATA_DIR, "player_images")
    if not name or not os.path.isdir(img_dir):
        return ""
    raw = re.sub(r"\s+", " ", str(name)).strip()
    variants = {raw, re.sub(r"[^\w\s\-]", "", raw).strip()}
    for stem in variants:
        for ext in ("png", "jpeg", "jpg"):
            path = os.path.join(img_dir, f"{stem}.{ext}")
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    return _sb_b64.b64encode(f.read()).decode()
    # Last resort: case-insensitive match on the directory listing.
    lower = {f.lower(): f for f in os.listdir(img_dir)}
    for stem in variants:
        for ext in ("png", "jpeg", "jpg"):
            hit = lower.get(f"{stem}.{ext}".lower())
            if hit:
                with open(os.path.join(img_dir, hit), "rb") as f:
                    return _sb_b64.b64encode(f.read()).decode()
    return ""


def _sb_logo_b64(*candidates):
    """Team logo as base64, using the same lookup the app's find_logo_b64() uses.

    The banner is the most recognisable thing on the Upcoming Game page and the crests are most of
    why -- a brief with empty squares where the app has logos reads as a different document. Same
    data/logo directory, same exact/prefix/reverse-prefix order, so a team that has a crest in the
    app has one here.
    """
    import base64 as _sb_b64
    logo_dir = os.path.join(APP_DATA_DIR, "logo")
    if not os.path.isdir(logo_dir):
        return ""
    stems = sorted((os.path.splitext(f)[0] for f in os.listdir(logo_dir) if f.lower().endswith(".png")),
                   key=len, reverse=True)

    def _read(stem):
        with open(os.path.join(logo_dir, f"{stem}.png"), "rb") as f:
            return _sb_b64.b64encode(f.read()).decode()

    for name in candidates:
        if not name or (isinstance(name, float) and pd.isna(name)):
            continue
        name = str(name).strip()
        if not name:
            continue
        if os.path.exists(os.path.join(logo_dir, f"{name}.png")):
            return _read(name)
        for stem in stems:
            if name.startswith(stem) and len(stem) >= 3:
                return _read(stem)
        for stem in stems:
            if stem.startswith(name) and len(name) >= 3:
                return _read(stem)
    return ""


def _sb_record_and_streak(games):
    """Win-loss record and current streak from a set of completed games, newest last."""
    if games.empty or "outcome" not in games.columns:
        return "", ""
    played = games[games["outcome"].astype(str).str.upper().isin(["W", "L"])]
    if played.empty:
        return "", ""
    wins = int((played["outcome"].astype(str).str.upper() == "W").sum())
    losses = int((played["outcome"].astype(str).str.upper() == "L").sum())
    count, kind = 0, ""
    for outcome in played["outcome"].astype(str).str.upper().iloc[::-1]:
        if count == 0:
            kind, count = outcome, 1
        elif outcome == kind:
            count += 1
        else:
            break
    streak = f"{count}-game {'win' if kind == 'W' else 'loss'} streak" if count else ""
    return f"{wins}-{losses}", streak


def _sb_strip_mascot(name):
    """"Aurora Spartans" -> "Aurora", the way the banner shows it.

    The app has a full known-mascot list for this; a brief only needs the banner line, so this
    trims the trailing mascot word conservatively and leaves anything it isn't sure about alone
    rather than mangling a real team name.
    """
    text = str(name or "").strip()
    if not text or text.endswith(")"):
        return text
    words = text.split()
    # CONFIRMED BUG (fixed here): a since-removed branch collapsed any 3+-word "UW-..." name down to just
    # its first word, on the assumption a UW campus name is always one word. It isn't -- "UW-Stevens Point
    # Pointers" has a two-word campus name ("Stevens Point"), so that branch dropped BOTH "Point" and the
    # real mascot "Pointers", leaving "UW-Stevens" on every banner and section header. Stripping only the
    # trailing word works correctly for every UW campus regardless of how many words its name has --
    # "UW-Eau Claire Blugolds" -> "UW-Eau Claire", "UW-Whitewater Warhawks" -> "UW-Whitewater", etc.
    if len(words) >= 2 and words[-1][:1].isupper():
        return " ".join(words[:-1])
    return text


# Filled in by _sb_build_html so the run can report which players ended up with no headshot -- a silent
# blank circle is how our own players' pictures went missing without anyone noticing.
_sb_photo_report = {}

# Filled in by _sb_build_html with the methodology notes, in the order they were registered. The brief only
# prints the ⓘ markers now (they deep-link into the app), so this is what the app reads to show the text --
# and the numbering here is what those markers point at, so it has to stay in registration order.
_sb_notes_report = []


def _sb_film_status():
    """How the automatic film work stands -> (summary dict, metric rows). CONFIRMED CHANGE (requested: the
    METHODOLOGY section explains how film is watched, players and plays are tagged, how many games and reviews
    went in, and how well the models are performing). Also written to uww_film_ai_status.csv for the app."""
    g_ = globals()
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "--"
    info, rows = {}, []
    # --- data so far
    cf = g_.get("clip_frames")
    if isinstance(cf, pd.DataFrame) and not cf.empty:
        info["games_captured"] = int(cf.get("source_url", pd.Series(dtype=str)).nunique())
        info["clips_captured"] = len(cf)
    pc = g_.get("play_calls")
    if isinstance(pc, pd.DataFrame) and not pc.empty:
        info["games_tagged"] = int(pc.groupby(["game_date", "game_code"]).ngroups) if {"game_date", "game_code"} <= set(pc.columns) else None
        info["clips_tagged"] = len(pc)
        if "track_files" in pc.columns:
            _t = pc[pc["track_files"].notna()]
            info["games_tracked"] = int(_t.groupby(["game_date", "game_code"]).ngroups) if len(_t) else 0
            info["clips_tracked"] = len(_t)
            info["frames_tracked"] = int(_t["track_files"].astype(str).str.count(";").add(1).sum()) if len(_t) else 0
    try:
        _checks = coach_checks_all()[0] if "coach_checks_all" in g_ else []
    except Exception:
        _checks = []
    info["player_checks"] = len(_checks)
    info["plays_checked"] = len({c.get("clip_key") for c in _checks})
    try:
        if "title_review_answers" in g_:
            title_review_answers()
        _marks = g_.get("_title_review_marks") or {}
    except Exception:
        _marks = {}
    info["title_answers"] = len(_marks)
    info["plays_title_reviewed"] = len({ck for ck, _f in _marks})
    if isinstance(pc, pd.DataFrame) and "tag_validation" in pc.columns:
        info["validation_plays"] = int(pc["tag_validation"].fillna(False).astype(bool).sum())

    # --- how well it's working = how often the film's automatic answer AGREED WITH THE COACHES' CHECK
    # CONFIRMED CHANGE (requested: "a comparison of how accurate the automatic film creation did against the coach
    # checks"). Every row is something a coach checked; coverage numbers (players named from evidence, frames on the
    # court) moved to the "So far" line -- they say how much the film covers, not whether it's right.
    sl = g_.get("trk_lineup_slots")
    if isinstance(sl, pd.DataFrame) and not sl.empty and "how" in sl.columns:
        info["players_from_evidence"] = int(sl["how"].map(
            lambda h: any(x not in ("best guess", "not located") for x in str(h).split(";"))).sum())
        info["player_slots"] = len(sl)
    cr = g_.get("court_report")
    if isinstance(cr, pd.DataFrame) and not cr.empty and "mapped_pct" in cr.columns:
        _c = cr[cr.get("calibrated", True) == True]
        if len(_c):
            info["court_mapped_pct"] = round(float(_c["mapped_pct"].mean()))
    agree = lambda r_, n_: f"{r_} of {n_} ({pct(r_, n_)})"
    if _checks:
        _n_real = sum(1 for c in _checks if c.get("verdict") != "not a player")
        rows.append(("Players", "Real player (not a referee, coach or fan)", agree(_n_real, len(_checks)),
                     "every box a coach checked"))
        _side = [c for c in _checks if c.get("verdict") != "not a player"]
        if _side:
            rows.append(("Players", "Right team", agree(sum(1 for c in _side if c.get("verdict") != "wrong team"), len(_side)),
                         "boxes that were players; 'wrong team' counts against"))
        _named = [c for c in _checks if c.get("assigned")]

        def _misses(cs):
            """Which wrong answers the coaches gave, e.g. '2 really someone else, 1 wrong team'."""
            lab = {"wrong": "really someone else", "wrong team": "wrong team", "not a player": "not a player"}
            n_ = {}
            for c in cs:
                v = c.get("verdict")
                if v != "correct":
                    n_[lab.get(v, str(v))] = n_.get(lab.get(v, str(v)), 0) + 1
            return ", ".join(f"{v_} {k_}" for k_, v_ in sorted(n_.items(), key=lambda x: -x[1]))

        if _named:
            _r = sum(1 for c in _named if c.get("verdict") == "correct")
            _m = _misses(_named)
            rows.append(("Players", "Right name -- all names the film gave",
                         agree(_r, len(_named)) + (f" -- {_m}" if _m else ""), "named boxes a coach checked"))
            by = {}
            for c in _named:
                by.setdefault(c.get("assigned_how") or "other", []).append(c)
            for h, cs in sorted(by.items(), key=lambda x: -len(x[1])):
                _r = sum(1 for c in cs if c.get("verdict") == "correct")
                _m = _misses(cs)
                rows.append(("Players", f"Right name -- named by {h}", agree(_r, len(cs)) + (f" -- {_m}" if _m else ""), ""))
    sc = (g_.get("JERSEY_READER_COACH_SCORE") or {})
    best = g_.get("JERSEY_READER_BEST")
    for eng, (r_, w_, n_) in sc.items():
        if eng == best or eng == "trained":
            rows.append(("Jersey numbers", f"Number read by the '{eng}' reader"
                         + (" (in use)" if eng == best else " (not reliable enough to use yet)"),
                         f"{agree(r_, r_ + w_)} of its answers; no answer on {n_ - r_ - w_} of {n_}",
                         "coach-checked players it never trained on"))
    # automatic Title: one row per field, every kind of coach check side by side
    tv = g_.get("tag_model_validation")
    tr = g_.get("tag_model_report")
    rep = {}
    for (_ck, f), a_ in _marks.items():
        # untouched prefilled "wrong" answers just repeat the coach-Title comparison -- not counted as reviews
        if a_.get("verdict") in ("right", "wrong") and not a_.get("prefilled"):
            rep.setdefault(f, [0, 0])
            rep[f][1] += 1
            rep[f][0] += int(a_["verdict"] == "right")
    for f in ["situation", "formation", "play_call", "primary_action", "defense", "press", "ball_screen_coverage",
              "offball_coverage", "screener", "screen_defender"]:
        parts_ = []
        if f in rep:
            parts_.append(f"coach reviews {agree(*rep[f])}")
        if isinstance(tv, pd.DataFrame) and not tv.empty and "field" in tv.columns and (tv["field"] == f).any():
            r = tv[tv["field"] == f].iloc[0]
            parts_.append(f"coach Titles, validation plays {agree(int(r['right']), int(r['validation_plays']))}")
        if isinstance(tr, pd.DataFrame) and not tr.empty and "accuracy_pct" in tr.columns and (tr["field"] == f).any():
            r = tr[tr["field"] == f].iloc[0]
            if pd.notna(r.get("accuracy_pct")) and pd.notna(r.get("clips_scored")):
                parts_.append(f"coach Titles, held-out plays {r['accuracy_pct']:.0f}% of {int(r['clips_scored'])}"
                              + (f" (always guessing the usual answer: {r['baseline_pct']:.0f}%)"
                                 if pd.notna(r.get("baseline_pct")) else ""))
        if parts_:
            rows.append(("Automatic Title", f.replace("_", " ").capitalize(), "\n".join(parts_),
                         "plays the model never trained on, or coaches' right/wrong marks"))
    return info, rows


def _sb_build_html(_sb_d, game, scheduled_name, short):
    parts = []
    # Output goes to whichever list is on top of _sinks, so a block can be rendered into a side-by-side
    # column (see capture()) with the exact same code that renders it full width.
    _sinks = [parts]

    def add(html_text):
        _sinks[-1].append(html_text)

    def capture(fn, *args, **kwargs):
        _sinks.append([])
        try:
            fn(*args, **kwargs)
        finally:
            out = _sinks.pop()
        return out

    # ---- links into the app (#7) -------------------------------------------------------------------
    # CONFIRMED CHANGE (requested): the brief is condensed, and every place detail was cut links into the
    # app instead. Links carry query parameters the app reads on load (see handle_brief_deeplink in
    # streamlit_app.py): page, tab, and optionally key / player+team / set / section. The hosted URL comes
    # from APP_BASE_URL (set it in the config cell) or the UWW_APP_URL environment variable; with neither,
    # links degrade to plain "(in the app: ...)" text rather than pointing nowhere.
    from urllib.parse import urlencode as _sb_urlencode

    def _sb_normalize_app_url(raw):
        """Force an absolute https:// URL, or nothing.

        A bare host ("uwwmensbball-new.streamlit.app") in an href is a RELATIVE url: the browser resolves
        it against wherever the brief happens to sit, so a link opens
        file:///C:/.../scouting_briefs/uwwmensbball-new.streamlit.app/?page=... instead of the app. The
        brief is emailed around and opened from disk, so this fails silently for every reader. Normalizing
        happens HERE, at the point of use, rather than only in the config cell -- app_href re-reads the raw
        global/env value, so a fix applied only at config time is bypassed whenever the value arrives by
        another route (env var, a re-run config cell, an edit made after this cell ran).
        """
        u = str(raw or "").strip().strip('"\'').rstrip("/")
        if not u:
            return ""
        # Typos that would otherwise sail through as "has no scheme": https//host, https:/host, http:host.
        u = re.sub(r"^(https?)(?::/{0,2}|/{1,2})", r"\1://", u, flags=re.I)
        if not re.match(r"^https?://", u, flags=re.I):
            u = "https://" + u
        return u.rstrip("/")

    _app_url = _sb_normalize_app_url(globals().get("APP_BASE_URL") or os.environ.get("UWW_APP_URL"))

    # Every app link opens in a NEW TAB (requested). rel="noopener" goes with target="_blank" as a matter
    # of course: without it the opened page gets a handle on the opener via window.opener, and "noreferrer"
    # keeps the local file:// path of the brief out of the referrer header when it is opened from disk.
    _SB_NEWTAB = ' target="_blank" rel="noopener noreferrer"'

    def app_href(**params):
        q = _sb_urlencode({k: v for k, v in params.items() if v not in (None, "")})
        return f"{_app_url}/?{q}" if _app_url else ""

    def app_link(label, **params):
        href = app_href(**params)
        if href:
            return f'<a class="applink" href="{_sb_esc(href)}"{_SB_NEWTAB}>{_sb_esc(label)} &rarr;</a>'
        return f'<span class="applink off">{_sb_esc(label)} (in the app)</span>'

    def name_link(text, **params):
        href = app_href(**params)
        return f'<a class="nmlink" href="{_sb_esc(href)}"{_SB_NEWTAB}>{_sb_esc(text)}</a>' if href else _sb_esc(text)

    def _name_two_lines(name):
        """First name, line break, last name -- for the compact roster table, where the name column has to
        stay narrow. Splits on the first space only, so a suffix or two-word last name ("Agape Keyes Jr.")
        stays together on the second line."""
        first, sep, rest = str(name).partition(" ")
        return f"{_sb_esc(first)}<br>{_sb_esc(rest)}" if sep else _sb_esc(name)

    def name_link_lines(name, **params):
        href = app_href(**params)
        label = _name_two_lines(name)
        return f'<a class="nmlink" href="{_sb_esc(href)}"{_SB_NEWTAB}>{label}</a>' if href else label

    # ---- footnotes (#6) ----------------------------------------------------------------------------
    # Long methodology paragraphs used to sit under each table, then on a Notes page at the end of the
    # brief. They live in the APP now (requested) -- the brief keeps only the small numbered ⓘ at each
    # section title, hyperlinked to that note in the app, so the explanation is one tap away without
    # spending brief pages on it. Still collected here because the numbering has to match what the app
    # prints, and because the export below is what the app reads.
    footnotes = []

    def footnote(text):
        text = _sb_clean(text)
        if not text:
            return ""
        footnotes.append(text)
        _n = len(footnotes)
        _href = app_href(page="upcoming", tab="notes", note=_n)
        if not _href:
            # No app URL configured -- a numbered marker pointing at a page the reader can't reach (and
            # that isn't printed here any more) is worse than no marker at all.
            return ""
        return (f' <sup class="fn"><a class="fnlink" href="{_sb_esc(_href)}"{_SB_NEWTAB} '
                f'title="Why this number is what it is \u2014 opens the app">\u24d8{_n}</a></sup>')

    def page_break():
        add('<div class="pb"></div>')

    def divider(title, sub=""):
        add(f'<div class="divider"><div class="dt">{title}</div>'
            + (f'<div class="ds">{sub}</div>' if sub else "") + "</div>")

    def section_html(title):
        return f'<div class="sect"><div class="t">{title}</div></div>'

    def section(title):
        add(section_html(title))

    # ---- banner (same markup and values as render_upcoming_game) ---------------------------
    sched = _sb_d("uww_schedule")
    uww_games = sched[sched["team"].astype(str).str.contains("Whitewater", case=False, na=False)] \
        if not sched.empty else pd.DataFrame()
    uww_before = uww_games.loc[:game.name].iloc[:-1] if not uww_games.empty else pd.DataFrame()
    uww_record, uww_streak = _sb_record_and_streak(uww_before)

    opp_sched = _sb_d("uww_opponent_schedules")
    opp_before = pd.DataFrame()
    if not opp_sched.empty and "opponent" in opp_sched.columns:
        opp_before = opp_sched[opp_sched["opponent"].astype(str).str.strip() == str(short).strip()]
    opp_record, opp_streak = _sb_record_and_streak(opp_before)

    opp_display = _sb_strip_mascot(short)
    uww_logo = _sb_logo_b64("UW-Whitewater")
    opp_logo = _sb_logo_b64(short, scheduled_name, opp_display)

    def crest(b64):
        return (f'<div class="crest"><img src="data:image/png;base64,{b64}" alt=""></div>'
                if b64 else '<div class="crest"></div>')

    add('<div class="banner">')
    add(f'<div class="side">{crest(uww_logo)}'
        f'<div class="team">UW-WHITEWATER</div>'
        f'<div class="rec">{_sb_esc(uww_record)}</div>'
        + (f'<div class="streak">{_sb_esc(uww_streak)}</div>' if uww_streak else "")
        + "</div>")
    add(f'<div class="side mid"><div class="when">{_sb_esc(game.get("date", "-"))}</div>'
        f'<div class="vs">VS</div>'
        f'<div class="where">{_sb_esc(game.get("location", "-"))}</div></div>')
    add(f'<div class="side">{crest(opp_logo)}'
        f'<div class="team">{_sb_esc(str(opp_display).upper())}</div>'
        f'<div class="rec">{_sb_esc(opp_record)}</div>'
        + (f'<div class="streak">{_sb_esc(opp_streak)}</div>' if opp_streak else "")
        + "</div>")
    add("</div>")

    # ---- gather ---------------------------------------------------------------------------
    us = _sb_team_line(_sb_d("uww_pbp_box_score"), "team", _SB_UWW)
    them = _sb_team_line(_sb_d("uww_opponent_prior_games_box_score"), "team", short)
    them_allowed = _sb_team_line(_sb_d("uww_opponent_prior_games_box_score"), "team", short, invert=True)
    us_allowed = _sb_team_line(_sb_d("uww_pbp_box_score"), "team", _SB_UWW, invert=True)

    totals = _sb_d("uww_opponent_team_totals")
    if not totals.empty and "opponent" in totals.columns:
        row = totals[totals["opponent"].astype(str) == str(short)]
        if not row.empty:
            them.setdefault("PTS", _sb_num(row["team_ppg"]).iloc[0])
            them_allowed.setdefault("PTS", _sb_num(row["opp_ppg_allowed"]).iloc[0])

    players = _sb_player_table(_sb_d, short)

    # ---- staff-input / sample sections ---------------------------------------------------------
    # One renderer for every table the game-plan cell writes. When the table is SAMPLE (is_sample True on
    # every row), the card is drawn as a red box with a SAMPLE DATA tag and a line saying what real input
    # would replace it. When the staff has supplied the file, the same table renders as an ordinary card.
    def staff_rows(table_name):
        df = _sb_d(table_name)
        if df.empty:
            return df, False
        if "opponent" in df.columns:
            df = df[df["opponent"].astype(str) == str(short)]
        is_sample = bool("is_sample" in df.columns and not df.empty
                         and df["is_sample"].astype(str).str.lower().isin(["true", "1"]).all())
        return df, is_sample

    def open_card(is_sample, why):
        if is_sample:
            add('<div class="sample"><div class="sample-tag">Sample data \u2014 not from your files</div>')
            if why:
                add(f'<p class="sample-why">{_sb_esc(why)}</p>')
        else:
            add('<div class="card">')

    def staff_cell(value):
        if isinstance(value, float) and not pd.isna(value) and float(value).is_integer():
            return str(int(value))
        return _sb_clean(value)

    def staff_table(table_name, title, columns, why_sample, note=None):
        df, is_sample = staff_rows(table_name)
        if df.empty:
            return
        add('<div class="gcell">')
        add(f'<div class="sect{" sample-sect" if is_sample else ""}"><div class="t">{title}'
            f'{footnote(note) if note else ""}</div></div>')
        open_card(is_sample, why_sample)
        add("<table><thead><tr>" + "".join(
            f'<th style="text-align:left">{_sb_esc(label)}</th>' for _, label in columns) + "</tr></thead><tbody>")
        for _, r in df.iterrows():
            add("<tr>" + "".join(f'<td class="wrap">{_sb_esc(staff_cell(r.get(col)))}</td>'
                                 for col, _ in columns) + "</tr>")
        add("</tbody></table>")
        add("</div></div>")

    # ---- team stats and four factors, side by side ----------------------------------------
    # Collected into lists first rather than written straight out, so the top two can be dropped into
    # one flex row. Either panel can be absent -- no box score, or not enough of one to compute the
    # factors -- and a lone panel is emitted full width instead of stranded in half a row.
    team_parts, ff_parts = [], []
    t_add, f_add = team_parts.append, ff_parts.append

    # ---- team stats -----------------------------------------------------------------------
    # Laid out HORIZONTALLY (requested): each stat is its own narrow column reading top-to-bottom
    # (label, our number, theirs), and the columns run left to right across the full width of the
    # section. The old "cmp" layout stacked one stat per line down the page, which made this a tall
    # narrow list instead of a strip a coach can scan in one pass.
    if us and them:
        t_add('<span class="fnhold">' + footnote(
            "Team stats: both sides are built the same way, from play-by-play box scores rather than a scouting "
            "report, so they compare like with like. Their figures cover only the games before this matchup.")
            + "</span>")
        comparisons = [
            # Pace sits right after scoring (requested): points per game only mean something next to how
            # many possessions produced them. Neither direction is "better", so it is never bolded.
            ("Points", "PTS", True), (None, None, None), ("Pace (poss/g)", "PACE", None),
            ("Field Goal %", "FG%", True), ("3PT %", "3P%", True), ("3PA", "3PA", None),
            ("Rebounds", "REB", True), ("Assists", "AST", True),
            ("Turnovers", "TO", False), ("Steals", "STL", True), ("Blocks", "BLK", True),
        ]
        _cells = []
        for label, key, higher_is_better in comparisons:
            if key is None:
                label, a, b, higher_is_better = "Points Against", us_allowed.get("PTS"), them_allowed.get("PTS"), False
            else:
                a, b = us.get(key), them.get(key)
            if a is None and b is None:
                continue
            _us_cls, _them_cls = "hs-v", "hs-v"
            if higher_is_better is not None and a is not None and b is not None and abs(float(a) - float(b)) >= 0.05:
                if (float(a) > float(b)) == bool(higher_is_better):
                    _us_cls += " hs-win"
                else:
                    _them_cls += " hs-win"
            _cells.append(f'<div class="hs-col"><div class="hs-l">{_sb_esc(label)}</div>'
                          f'<div class="{_us_cls}">{_sb_fmt(a)}</div>'
                          f'<div class="{_them_cls}">{_sb_fmt(b)}</div></div>')
        t_add('<div class="hstat"><div class="hs-col hs-key"><div class="hs-l">&nbsp;</div>'
              f'<div class="hs-v">UWW</div><div class="hs-v">{_sb_esc(str(opp_display).upper())}</div></div>'
              + "".join(_cells) + "</div>")
        t_add('<p class="mini">Per game, before this matchup. Bold is the better number.</p>')

    # ---- four factors ---------------------------------------------------------------------
    # Same computation and the same weighted ranking as the app's Four Factors dialog. Ours come from
    # our own games, theirs from their prior games, so neither side is adjusted for who they played
    # -- stated under the table rather than left for a coach to assume one way or the other.
    _ff_box = _sb_d("uww_pbp_box_score")
    _ff_prior = _sb_d("uww_opponent_prior_games_box_score")
    _ff_top, _ff_rows = None, []
    if not _ff_box.empty and not _ff_prior.empty and "team" in _ff_box.columns and "team" in _ff_prior.columns:
        _ff_us = _sb_four_factors(_ff_box[_ff_box["team"] == _SB_UWW],
                                  _ff_box[_ff_box["team"] != _SB_UWW])
        _ff_them = _sb_four_factors(_ff_prior[_ff_prior["team"].astype(str) == str(short)],
                                    _ff_prior[_ff_prior["team"].astype(str) != str(short)])
        _ff_rows = []
        for _factor, _weight in _SB_FF_WEIGHTS.items():
            _a, _b = _ff_us.get(_factor), _ff_them.get(_factor)
            if _a is None or _b is None:
                continue
            # Edge is stated so positive always favours us -- which for turnovers means a LOWER rate.
            _edge = (_a - _b) if _SB_FF_HIGHER_IS_BETTER[_factor] else (_b - _a)
            _ff_rows.append({"factor": _factor, "uww": _a, "opp": _b, "edge": _edge,
                             "weight": _weight, "weighted": _edge * _weight})
        if _ff_rows:
            _ff_rows.sort(key=lambda r: abs(r["weighted"]), reverse=True)
            _ff_top = _ff_rows[0]
            # The table itself is gone from the brief (requested) -- every factor is one tap away in the app's
            # Four Factors dialog. The methodology note is registered on THE BOTTOM LINE sentence itself (when
            # it prints), not here: a note registered here had no marker anywhere in the brief pointing to it.

    def two_up(left, right):
        """Two panels in one flex row, or whichever one exists full width. A lone panel stranded in
        half a row reads as a rendering failure rather than as missing data."""
        if left and right:
            return ('<div class="cols"><div class="col">' + "\n".join(left) + "</div>"
                    + '<div class="col">' + "\n".join(right) + "</div></div>")
        return "\n".join(left + right)


    # =====================================================================================================
    # CONDENSED LAYOUT (requested): Page 1 game plan -> opponent (glance, starters, bench, lineups, offense,
    # context, tagging-dependent) -> UWW mirror (starters, bench, lineups, offense, context, our week) -> notes.
    # Nothing was removed: detail that no longer fits a page is one link away in the app, and every
    # methodology paragraph is on the Notes page under its ⓘ number.
    # =====================================================================================================
    OPP_UP = _sb_esc(str(opp_display).upper())
    _team_gp = int(them.get("games") or 0)
    add('<div class="linkbar">' + app_link("Open this matchup in the app", page="upcoming") + "</div>")

    # ---- shared data --------------------------------------------------------------------------------
    _notes_tbl = _sb_d("uww_scouting_notes")
    if not _notes_tbl.empty and "opponent" in _notes_tbl.columns:
        _notes_tbl = _notes_tbl[_notes_tbl["opponent"].astype(str) == str(short)]
    _tiers = _sb_d("uww_personnel_tiers")
    if not _tiers.empty and "scouted_opponent" in _tiers.columns:
        _tiers = _tiers[_tiers["scouted_opponent"].astype(str) == str(short)]
    _pcs_all = _sb_d("uww_play_call_summary")
    _pcc_all = _sb_d("uww_play_calls")
    if not _pcs_all.empty and "scouted_opponent" in _pcs_all.columns:
        _pcs_all = _pcs_all[_pcs_all["scouted_opponent"].astype(str) == str(short)]

    def _offense_rows(side):
        """play_call_summary rows for one side's OWN OFFENSE.

        side alone is not enough any more: it names the FILE a clip came from, and those files now carry
        defensive possessions too. Without the possession_side filter our offensive tables pick up
        possessions where the opponent had the ball -- which is how a SLOB finished by a Ripon player
        turned up under our own sets. Rows written before possession_side existed have no value for it and
        are treated as offensive, which is what they were.
        """
        if _pcs_all.empty or "side" not in _pcs_all.columns:
            return pd.DataFrame()
        rows = _pcs_all[_pcs_all["side"] == side]
        if "possession_side" in rows.columns:
            rows = rows[rows["possession_side"].astype(str) != "Defense"]
        return rows
    if not _pcc_all.empty and "scouted_opponent" in _pcc_all.columns:
        _pcc_all = _pcc_all[_pcc_all["scouted_opponent"].astype(str) == str(short)]
    _flags = _sb_d("uww_coaching_flags")
    _live_ros = _sb_d("uww_live_rosters")
    _avail, _avail_sample = staff_rows("uww_uww_availability")

    def _norm(n):
        return re.sub(r"\s+", " ", str(n)).strip().lower()

    def _sb_title(n):
        """ALL-CAPS roster names read as shouting in running prose. Title-case them, but leave a name that
        already has mixed case alone -- "McEwen" and "Mur Martin" are correct as tagged and .title() would
        wreck them."""
        n = re.sub(r"\s+", " ", str(n)).strip()
        if not n or n != n.upper():
            return n
        return " ".join(w[:1].upper() + w[1:].lower() if w else w for w in n.split(" "))

    def players_for(box_name, team_value):
        """Per-game lines for any team's players -- same math as _sb_player_table, which is opponent-only."""
        box = _sb_d(box_name)
        if box.empty or "team" not in box.columns:
            return pd.DataFrame()
        own = box[(box["team"].astype(str) == str(team_value)) & (box["player"].astype(str) != "TEAM")]
        rows = []
        for name, g in own.groupby("player"):
            games = g["game_date"].nunique() if "game_date" in g.columns else len(g)
            t = {c: _sb_num(g[c]).sum() if c in g.columns else 0
                 for c in ("PTS", "REB", "AST", "STL", "BLK", "TO", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "MIN")}
            rows.append({"name": str(name), "games": games,
                         **{k: (t[k] / games if games else None) for k in ("PTS", "REB", "AST", "STL", "BLK", "TO", "MIN")},
                         "FG%": _sb_pct(t["FGM"], t["FGA"]), "3P%": _sb_pct(t["FG3M"], t["FG3A"]),
                         "FT%": _sb_pct(t["FTM"], t["FTA"]), "FTM": t["FTM"], "FTA": t["FTA"],
                         "PTS_total": t["PTS"]})
        return pd.DataFrame(rows)

    def stat_line(p):
        return (f'{_sb_fmt(p["games"], 0)} GP &middot; {_sb_fmt(p.get("MIN"))} MIN &middot; {_sb_fmt(p["PTS"])} PTS &middot; '
                f'{_sb_fmt(p["REB"])} REB &middot; {_sb_fmt(p["AST"])} AST &middot; {_sb_fmt(p["TO"])} TO &middot; '
                f'{_sb_fmt(p["FG%"])}% FG &middot; {_sb_fmt(p["3P%"])}% 3P &middot; {_sb_fmt(p["FT%"])}% FT')

    def tier_groups(side, player_names):
        """[(label, caption, [names])] in the app's order. Falls back to one group when no tiers exist."""
        t = _tiers[_tiers["side"] == side] if not _tiers.empty and "side" in _tiers.columns else pd.DataFrame()
        if t.empty:
            return None, [("Players", "No personnel tiers on file yet -- ordered by production.", list(player_names))], "", []
        n = int(t["recent_n"].max() or 0)
        basis = _sb_clean(t["starter_basis"].iloc[0])
        by = lambda label: list(t[t["tier"] == label].sort_values("mpg", ascending=False)["player"])  # noqa: E731
        starters = by("Starter")
        # "Bench -- limited minutes" is no longer printed (requested): under-8-minute players filled a
        # third of the roster pages without changing how anyone prepares. They are still tiered in the
        # data and still in the app -- the list comes back here so the brief can say how many were left
        # out and point the staff at them, rather than silently shortening the roster.
        # "No minutes in last N games" is no longer printed either (requested) -- it lives in the app. Both
        # omitted tiers are returned so the roster's single app link can say how many were left out.
        _limited = by("Bench \u2014 limited minutes") + by("Bench \u2014 no minutes")
        bench = [
            ("Bench \u2014 rotation", f"Played in the last {n} game(s) and averaging 8+ minutes.", by("Bench \u2014 rotation")),
        ]
        return starters, bench, basis, _limited

    # ---- personnel identity (photo / # / pos / ht / yr) ------------------------------------------------
    _pers_tbl, _pers_is_sample = staff_rows("uww_opp_personnel")
    _opp_bio = {_norm(r["player"]): r for _, r in _pers_tbl.iterrows()} if not _pers_tbl.empty else {}
    _uww_bio = {}
    if not _live_ros.empty and "team" in _live_ros.columns:
        _uww_labels = {_norm(_SB_UWW)}
        _sched_all = _sb_d("uww_schedule")
        if not _sched_all.empty and "team" in _sched_all.columns:
            _uww_labels |= {_norm(t) for t in _sched_all["team"].dropna().unique() if "whitewater" in str(t).lower()}
        _uww_ros_rows = _live_ros[_live_ros["team"].astype(str).str.contains("whitewater", case=False, na=False)
                                  | _live_ros["team"].astype(str).map(_norm).isin(_uww_labels)]
        for _, r in _uww_ros_rows.iterrows():
            _uww_bio[_norm(r["name"])] = {"player": r["name"], "jersey": r.get("jersey_number"),
                                          "position": r.get("position"), "height": r.get("height"),
                                          "class_year": r.get("class_year"), "photo_url": r.get("photo_url")}
    _avail_by = {_norm(r["player"]): r for _, r in _avail.iterrows()} if not _avail.empty else {}

    _photo_stats = {"Opponent": [0, []], "UWW": [0, []]}

    def photo_cell(url, name=None, side=None):
        url = _sb_clean(url)
        if not url and name:
            b64 = _sb_headshot_b64(name)
            if b64:
                url = f"data:image/png;base64,{b64}"
        if side in _photo_stats and name:
            if url:
                _photo_stats[side][0] += 1
            else:
                _photo_stats[side][1].append(str(name))
        return (f'<img src="{_sb_esc(url)}" class="photo-thumb" alt="">' if url
                else '<div class="photo-thumb photo-thumb-blank"></div>')

    def bio_bits(r, extra=None):
        bits = []
        if r is not None:
            if _sb_clean(r.get("jersey")):
                bits.append(f"#{_sb_esc(_sb_clean(r.get('jersey')))}")
            for c in ("position", "height", "hand", "class_year", "status"):
                if _sb_clean(r.get(c)):
                    bits.append(_sb_esc(_sb_clean(r.get(c))))
        return bits + (extra or [])

    # ---- one full card (starters) ----------------------------------------------------------------------
    def opp_card(name, p):
        rows = (_notes_tbl[(_notes_tbl["subject_type"] == "player") & (_notes_tbl["name"].map(_norm) == _norm(name))]
                if not _notes_tbl.empty else pd.DataFrame())
        bio = _opp_bio.get(_norm(name))
        title = name_link(name, page="upcoming", tab="personnel", team="opponent", player=name)
        if p is not None and _team_gp > 1 and float(p["games"]) < 0.5 * _team_gp:
            title += f' <span class="pill-thin">{int(p["games"])} of {_team_gp} games</span>'
        add('<div class="player">')
        add(f'<div class="nm">{title}</div>')
        gof = _sb_clean(bio.get("games_on_film")) if bio is not None else ""
        add(f'<div class="bio{" sample-bio" if _pers_is_sample else ""}">'
            f'{photo_cell(bio.get("photo_url") if bio is not None else None, name, "Opponent")}'
            f'<div class="bio-text">{" &middot; ".join(bio_bits(bio, [f"{_sb_esc(gof)} games on film"] if gof else []))}'
            f'</div></div>')
        if p is not None:
            add(f'<div class="statline">{stat_line(p)}</div>')
        good, bad = [], []
        for _, r in rows.iterrows():
            good += _sb_split(r.get("strengths"))
            bad += _sb_split(r.get("weaknesses"))
        if good or bad:
            add('<div class="reads">' + "".join(f'<span class="dot good">{_sb_esc(i)}</span>' for i in good)
                + "".join(f'<span class="dot bad">{_sb_esc(i)}</span>' for i in bad) + "</div>")
        for src in ("Coach", "Data-Driven"):
            r = rows[rows["source"] == src] if not rows.empty else pd.DataFrame()
            if r.empty:
                continue
            r = r.iloc[0]
            notes, keys = _sb_clean(r.get("notes")), _sb_clean(r.get("keys_to_defending"))
            if not notes and not keys:
                continue
            add(f'<div class="srcblock {"coach" if src == "Coach" else "derived"}"><div class="srclabel">{_sb_esc(src)}</div>')
            if notes:
                add(f'<p class="notes">{_sb_esc(notes)}</p>')
            if keys:
                add('<div class="kd"><span class="lbl">Keys to Defending</span>'
                    + "".join(f'<div class="kdline">{_sb_esc(k)}</div>' for k in _sb_split(keys)) + "</div>")
            add("</div>")
        add("</div>")

    def uww_player_calls(name):
        if _pcc_all.empty or "side" not in _pcc_all.columns:
            return ""
        c = _pcc_all[(_pcc_all["side"] == "UWW") & (_pcc_all["player"].astype(str).map(_norm) == _norm(name))
                     & (_pcc_all["decode_quality"] != "Needs review")]
        named = c[c["play_call"].notna() & ~c["play_call"].astype(str).str.contains("unspecified", na=False)]
        vc = named["play_call"].value_counts()
        vc = vc[vc >= 3]
        if vc.empty:
            return ""
        pts = pd.to_numeric(c["points"], errors="coerce")
        ppp = pts.sum() / pts.notna().sum() if pts.notna().any() else None
        return (f"Tagged film: featured in " + ", ".join(f"{n} ({int(k)}x)" for n, k in vc.head(3).items())
                + f" out of {len(c)} tagged possession(s)" + (f" \u2014 {ppp:.2f} PPP." if ppp is not None else "."))

    def uww_card(name, p):
        bio = _uww_bio.get(_norm(name))
        av = _avail_by.get(_norm(name))
        extra = []
        if av is not None and _sb_clean(av.get("status")):
            extra.append(_sb_esc(_sb_clean(av.get("status"))) + (" (sample)" if _avail_sample else "")
                         + (f" \u2014 {_sb_esc(_sb_clean(av.get('note')))}" if _sb_clean(av.get("note")) else ""))
        add('<div class="player">')
        add(f'<div class="nm">{name_link(name, page="upcoming", tab="personnel", team="uww", player=name)}</div>')
        add(f'<div class="bio">{photo_cell(bio.get("photo_url") if bio else None, name, "UWW")}'
            f'<div class="bio-text">{" &middot; ".join(bio_bits(bio, extra)) or "No roster-page details on file"}</div></div>')
        if p is not None:
            add(f'<div class="statline">{stat_line(p)}</div>')
        pf = (_flags[_flags["player"].astype(str).map(_norm) == _norm(name)]
              if not _flags.empty and "player" in _flags.columns else pd.DataFrame())
        if not pf.empty:
            for label, sentiment in (("Lean on", "positive"), ("Clean up", "negative")):
                sel = pf[pf["sentiment"].astype(str).str.lower() == sentiment]
                if sel.empty:
                    continue
                add(f'<div class="srcblock derived"><div class="srclabel">{label}</div>')
                for _, f in sel.iterrows():
                    # Confidence labels read like "Low (n=3 Off Screen attempts -- small sample, re-check...)"; the
                    # tier and the count are what a card needs -- the full sentence stays in the app.
                    _conf = _sb_clean(f.get("confidence"))
                    _cm = re.match(r"^(\w+)\s*\((n=\d+)", _conf)
                    _conf = f"{_cm.group(1)}, {_cm.group(2)}" if _cm else _conf
                    add(f'<p class="notes"><strong>{_sb_esc(_sb_clean(f.get("flag")))}</strong>'
                        + (f' <span class="conf-tag">{_sb_esc(_conf)}</span>' if _conf else "")
                        + f' \u2014 {_sb_esc(_sb_clean(f.get("evidence")))}</p>')
                    if _sb_clean(f.get("recommendation")):
                        add(f'<div class="kdline">{_sb_esc(_sb_clean(f.get("recommendation")))}</div>')
                add("</div>")
        calls = uww_player_calls(name)
        if calls:
            add(f'<div class="srcblock derived"><div class="srclabel">Play calls</div><p class="notes">{_sb_esc(calls)}</p></div>')
        add("</div>")

    # CONFIRMED CHANGE (requested): the standalone Late-Game Foul List is gone; its call now rides along in
    # the opponent's roster table beside each player's FT%, which is where a coach reads it anyway.
    _foul_tbl, _ = staff_rows("uww_late_game_foul_list")
    _foul_by = {_norm(r["player"]): r for _, r in _foul_tbl.iterrows()} if not _foul_tbl.empty else {}

    def foul_cell(name):
        r = _foul_by.get(_norm(name))
        if r is None:
            return '<td class="mini">--</td>'
        call = _sb_clean(r.get("call"))
        # Icon rather than words (requested): a check means foul him, a cross means don't. The words stay in
        # the cell's tooltip and are spelled out under the table, so the icon is never the only explanation.
        icon, cls = {"Foul": ("\u2714", "call-foul"),
                     "Do not foul": ("\u2718", "call-nofoul")}.get(call, ("\u2013", "mini"))
        return (f'<td class="{cls} foul-icon" title="{_sb_esc(call)} \u2014 {_sb_fmt(r.get("ft_pct"))}% FT">'
                f'{icon}</td>')

    # ---- compact roster rows ---------------------------------------------------------------------------
    # One table shape for every tier, with fixed column widths so the starters, rotation, limited-minutes and
    # no-minutes tables all line up down the page instead of each sizing itself to its own content.
    _ROSTER_COLS = ('<colgroup><col style="width:30px"><col style="width:13%"><col style="width:9%">'
                    '<col style="width:4%"><col style="width:5%"><col style="width:5%"><col style="width:5%">'
                    '<col style="width:5%"><col style="width:5%"><col style="width:5%"><col style="width:5%">'
                    '<col style="width:7%"><col style="width:32%"></colgroup>')

    _DEF_FAMILY_MIN = 6      # possessions before a family is reported at all
    _DEF_SPLIT_MIN = 4       # possessions before a per-player / per-series split is reported

    def _def_family(row):
        """man / zone / press, from the decoded defense fields. Press is its own family because it's a
        separate decision and a separate practice block -- a pressing man team lands in 'press'."""
        if bool(row.get("press_faced")):
            return "Press"
        d = _sb_clean(row.get("defense_faced"))
        if not d:
            return ""
        return "Zone" if "zone" in d.lower() else ("Man" if "man" in d.lower() else d)

    def _pf_clips(side_val, team_val=None):
        """Decoded, reviewable clips for one side with a defense read on them."""
        if _pcc_all.empty or "defense_faced" not in _pcc_all.columns:
            return pd.DataFrame()
        # OFFENSIVE possessions only. On a mixed file a defensive clip's defense tag is what this team
        # PLAYED, which would silently invert every row in this section.
        d = _pcc_all[(_pcc_all["side"] == side_val) & (_pcc_all["decode_quality"] != "Needs review")].copy()
        if "possession_side" in d.columns:
            d = d[d["possession_side"].astype(str) != "Defense"]
        if team_val is not None and "offense_team" in d.columns:
            d = d[d["offense_team"].astype(str) == str(team_val)]
        if d.empty:
            return d
        d["_fam"] = d.apply(_def_family, axis=1)
        d = d[d["_fam"].astype(str) != ""]
        if d.empty:
            return d
        _res = d["result"].astype(str).str.lower() if "result" in d.columns else pd.Series("", index=d.index)
        d["_pts"] = pd.to_numeric(d.get("points"), errors="coerce")
        d["_to"] = _res.str.contains("turnover|violation|kicked", regex=True)
        d["_fga"] = _res.str.startswith(("make", "miss")) & _res.str.contains("2|3", regex=True)
        d["_fgm"] = _res.str.startswith("make") & _res.str.contains("2|3", regex=True)
        return d

    def _ppp_of(grp):
        _known = grp["_pts"].notna().sum()
        return (grp["_pts"].sum() / _known) if _known else None

    def _ppp_cls(v, base):
        if v is None or base is None or pd.isna(v) or pd.isna(base):
            return ""
        return "ppp-good" if v >= base + 0.15 else ("ppp-bad" if v <= base - 0.15 else "")


    # ---- Defense splits in the Player Notes (requested; replaces the "Who changes by defense" table) -----
    # A player gets a note only when his scoring really moves with the defense family he faces. Each
    # family's PPP is shrunk toward his own overall PPP as if shrink_poss average possessions were added, so
    # 4-for-4 against a zone can't read as a real split; the gap is judged on the shrunk numbers and the raw
    # numbers are what the note prints.
    DEF_SPLIT_RULES = {
        "min_poss_each": _DEF_FAMILY_MIN,  # possessions against a family before it's compared
        "shrink_poss": 8,                   # average possessions added to each family before comparing
        "min_gap": 0.30,                    # shrunk PPP gap (points per possession) worth a note
    }
    _def_split_note = {}
    _pf_opp = _pf_clips("Opponent", short)
    if not _pf_opp.empty and "player" in _pf_opp.columns:
        _plx = _pf_opp[_sb_has_text(_pf_opp["player"]) & _pf_opp["_pts"].notna()]
        for _who, _g in _plx.groupby(_plx["player"].astype(str)):
            _overall = _g["_pts"].mean()
            _fams = {}
            for _fam, _fg in _g.groupby("_fam"):
                _n = len(_fg)
                if _n >= DEF_SPLIT_RULES["min_poss_each"]:
                    _k = DEF_SPLIT_RULES["shrink_poss"]
                    _fams[_fam] = (_fg["_pts"].mean(), _n, (_fg["_pts"].sum() + _k * _overall) / (_n + _k))
            if len(_fams) < 2:
                continue
            _hi = max(_fams.items(), key=lambda kv: kv[1][2])
            _lo = min(_fams.items(), key=lambda kv: kv[1][2])
            if _hi[1][2] - _lo[1][2] < DEF_SPLIT_RULES["min_gap"]:
                continue
            _def_split_note[_norm(_who)] = (
                f"Scores {_hi[1][0]:.2f} PPP vs {_hi[0].lower()} ({_hi[1][1]} poss) but {_lo[1][0]:.2f} vs "
                f"{_lo[0].lower()} ({_lo[1][1]}) \u2014 stay attached to him against {_hi[0].lower()}, "
                f"help off him in {_lo[0].lower()}")

    # Who dominates their offensive glass, if anyone -- keyed by normalised name for the roster read above.
    _reb_crasher = {}
    _RRr = globals().get("REBOUND_RULES") or {"min_paired": 20, "player_share": 35, "player_min": 5}
    _rsr = _sb_d("uww_rebound_summary")
    if not _rsr.empty and {"opponent", "metric", "player", "value", "count", "paired"}.issubset(_rsr.columns):
        _rsr = _rsr[(_rsr["opponent"].astype(str) == str(short)) & (_rsr["metric"] == "their_oreb_player")]
        for _, _cr in _rsr.iterrows():
            _share = pd.to_numeric(_cr["value"], errors="coerce")
            _cnt = int(pd.to_numeric(_cr["count"], errors="coerce") or 0)
            if (pd.notna(_share) and _share >= _RRr["player_share"] and _cnt >= _RRr["player_min"]
                    and int(pd.to_numeric(_cr["paired"], errors="coerce") or 0) >= _RRr["min_paired"]):
                _reb_crasher[_norm(_cr["player"])] = (f"Crashes the offensive glass \u2014 {_cnt} of their "
                                                      f"offensive rebounds after misses ({_share:.0f}%)")

    # Why a player is in an unexpected tier (a returning starter, or the starter he displaced) -- shown as
    # that player's first roster line so the promotion is never unexplained.
    _tier_note = {}
    _tn = _sb_d("uww_personnel_tiers")
    if not _tn.empty and {"player", "tier_note", "side"}.issubset(_tn.columns):
        for _, _t in _tn.iterrows():
            if _sb_clean(_t.get("tier_note")):
                _tier_note[(_t["side"], _norm(_t["player"]))] = _sb_clean(_t["tier_note"])

    def _roster_player(name, stats_df, side, bullets):
        """Everything one roster entry needs, assembled once so the table layout and the stacked layout
        can't show different reads, keys or flags for the same player."""
        s_ = stats_df[stats_df["name"].map(_norm) == _norm(name)] if not stats_df.empty else pd.DataFrame()
        p = s_.iloc[0] if not s_.empty else None
        if side == "Opponent":
            bio = _opp_bio.get(_norm(name))
            rows = (_notes_tbl[(_notes_tbl["subject_type"] == "player") & (_notes_tbl["name"].map(_norm) == _norm(name))]
                    if not _notes_tbl.empty else pd.DataFrame())
            reads = [x for _, r in rows.iterrows() for x in _sb_split(r.get("strengths")) + _sb_split(r.get("weaknesses"))]
            keys = [x for _, r in rows.iterrows() for x in _sb_split(r.get("keys_to_defending"))]
            items = reads[:2] + keys[:1]
            # No real read: show the stats that fell short of a minimum (or that nothing met a threshold)
            # rather than a blank cell -- requested, because a blank looked like the notes had failed.
            if not items and "below_minimum" in rows.columns:
                items = [x for _, r in rows.iterrows() for x in _sb_split(r.get("below_minimum"))]
            # Rebounding read (requested): only for the one player who dominates their offensive glass, by
            # the same REBOUND_RULES as the key and the Bottom Line. Goes FIRST so it survives the top-three
            # cut -- if he's doing this, it's the thing to know about him.
            _crash = _reb_crasher.get(_norm(name))
            _dsplit = _def_split_note.get(_norm(name))
            if _dsplit:
                items = [_dsplit] + items
            if _crash:
                items = [_crash] + items
            if bullets and len(items) < 3:
                # Fill to three from whatever is left, keys first -- an instruction beats another label.
                items += [x for x in keys[1:] + reads[2:] if x not in items][:3 - len(items)]
            team = "opponent"
        else:
            bio = _uww_bio.get(_norm(name))
            pf = (_flags[_flags["player"].astype(str).map(_norm) == _norm(name)]
                  if not _flags.empty and "player" in _flags.columns else pd.DataFrame())
            items = [_sb_clean(f.get("flag")) for _, f in pf.iterrows()]
            calls = uww_player_calls(name)
            items += [calls] if calls else []
            team = "uww"
        if _tier_note.get((side, _norm(name))):
            items = [_tier_note[(side, _norm(name))]] + items
        detail = (("<ul class=\"tbl-bul\">" + "".join(f"<li>{_sb_esc(x)}</li>" for x in items[:3]) + "</ul>")
                  if bullets else " \u00b7 ".join(_sb_esc(x) for x in items))
        bits = " ".join(bio_bits(bio)) if bio is not None else ""
        # his offensive role (BBall Index's 12) -- the same lookup every roster table uses
        _team_q = short if side == "Opponent" else "Whitewater"
        _q = lambda bb: (" (low sample)" if "low sample" in str(bb) else
                         " (position only)" if str(bb) == "position only" else "")
        if "offensive_role_for" in globals():
            _role, _basis = offensive_role_for(name, _team_q)
            if _role:
                bits = (bits + " &middot; " if bits else "") + f'Off: <strong>{_sb_esc(_role)}</strong><span class="mini">{_q(_basis)}</span>'
        if "defensive_role_for" in globals():
            _drole, _dbasis = defensive_role_for(name, _team_q)
            if _drole:
                bits = (bits + " &middot; " if bits else "") + f'Def: <strong>{_sb_esc(_drole)}</strong><span class="mini">{_q(_dbasis)}</span>'
        return {"p": p, "bio": bio, "bits": bits, "items": items, "detail": detail, "team": team}

    def _ft_cell(p):
        # A bare "100.0" invites exactly the question asked about Hillmer's free throws -- real, or one
        # attempt? The makes-attempts pair rides along whenever the sample is thin -- unless it's already
        # 100%, where the fraction adds nothing a coach needs at a glance.
        return (f'<td title="{int(p.get("FTM") or 0)}-for-{int(p.get("FTA") or 0)}">{_sb_fmt(p["FT%"])}'
                + (f' <span class="mini">({int(p.get("FTM") or 0)}-{int(p.get("FTA") or 0)})</span>'
                   if (p.get("FTA") or 0) and p["FTA"] < 10
                   and round(float(p.get("FT%") or 0), 1) != 100.0 else "") + "</td>")

    def bench_table(names, stats_df, side, bullets=False):
        """bullets=True (starters): the last column holds up to three bulleted items instead of a one-line
        summary -- the same table the bench uses, with room for more of each starter's read."""
        if ROSTER_LAYOUT == "stacked":
            return stacked_roster(names, stats_df, side, bullets)
        add('<table class="compact roster">' + _ROSTER_COLS
            + '<thead><tr><th></th><th style="text-align:left">Player</th>'
            '<th style="text-align:left">Bio</th><th>GP</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th>'
            '<th>FG%</th><th>3P%</th><th>FT%</th><th style="text-align:left">Late game foul</th>'
            '<th style="text-align:left">'
            + ("Top read / key" if side == "Opponent" else "Flag / play calls") + "</th></tr></thead><tbody>")
        for name in names:
            r = _roster_player(name, stats_df, side, bullets)
            p, bio = r["p"], r["bio"]
            add(f'<tr><td>{photo_cell(bio.get("photo_url") if bio is not None else None, name, side)}</td>'
                f'<td class="nm">{name_link_lines(name, page="upcoming", tab="personnel", team=r["team"], player=name)}</td>'
                f'<td class="wrap mini">{r["bits"]}</td>'
                + (f'<td>{_sb_fmt(p["games"], 0)}</td><td>{_sb_fmt(p.get("MIN"))}</td><td>{_sb_fmt(p["PTS"])}</td>'
                   f'<td>{_sb_fmt(p["REB"])}</td><td>{_sb_fmt(p["AST"])}</td><td>{_sb_fmt(p["FG%"])}</td>'
                   f'<td>{_sb_fmt(p["3P%"])}</td>' + _ft_cell(p)
                   if p is not None else '<td colspan="8" class="mini">no box-score line</td>')
                + (foul_cell(name) if side == "Opponent" else '<td class="mini">--</td>')
                + f'<td class="wrap mini">{r["detail"]}</td></tr>')
        add("</tbody></table>")

    # ---- STACKED roster layout (requested example) ---------------------------------------------------
    # Each player gets a HEADER BAR -- photo, name, bio, late-game foul call -- and the full width below
    # it goes to the numbers: the box-score line, then the shot profile (where he shoots from and how well,
    # from the play-by-play), then the reads. The table layout above has to fit all of that into one row,
    # which is why name and bio were squeezed into narrow columns and there was no room for shot data.
    _shot_prof = _sb_d("uww_player_shot_profile")

    def _shot_line(name, side):
        if _shot_prof.empty or "player" not in _shot_prof.columns:
            return ""
        sp = _shot_prof[(_shot_prof["side"] == side) & (_shot_prof["player"].map(_norm) == _norm(name))]
        if side == "Opponent" and "opponent" in sp.columns:
            sp = sp[sp["opponent"].astype(str) == str(short)]
        if sp.empty:
            return ""
        r = sp.iloc[0]
        fga = int(pd.to_numeric(r.get("fga"), errors="coerce") or 0)
        if fga < 5:
            return ""
        # A TABLE, not flex: the brief is printed and PDF'd, and older print engines lay a wrapping flex row
        # out unpredictably -- the caption and the three zones collapsed into one squeezed line in testing.
        cells = []
        for key, label in (("rim", "At the rim"), ("other2", "Other 2s"), ("three", "Threes")):
            share = pd.to_numeric(r.get(f"{key}_share"), errors="coerce")
            fg = pd.to_numeric(r.get(f"{key}_fg"), errors="coerce")
            att = int(pd.to_numeric(r.get(f"{key}_att"), errors="coerce") or 0)
            share = int(share) if pd.notna(share) else 0
            cells.append(f'<td class="sz"><div class="sz-l">{label}</div>'
                         f'<div class="sz-bar"><span style="width:{max(share, 2)}%"></span></div>'
                         f'<div class="sz-v"><strong>{share}%</strong> of shots &middot; '
                         + (f'{fg:.0f}% FG' if pd.notna(fg) else "no attempts" if not att else "--")
                         + (f' <span class="mini">({att})</span>' if att else "") + "</div></td>")
        return (f'<table class="sz-row"><tr><td class="sz-cap" colspan="3">Where he shoots '
                f'<span class="mini">{fga} FGA, from the play-by-play</span></td></tr><tr>'
                + "".join(cells) + "</tr></table>")

    def stacked_roster(names, stats_df, side, bullets=False):
        for name in names:
            r = _roster_player(name, stats_df, side, bullets)
            p, bio = r["p"], r["bio"]
            # The header has room for words, which are clearer than the table's check / cross icon.
            _foul = ""
            _fr = _foul_by.get(_norm(name)) if side == "Opponent" else None
            if _fr is not None:
                _call = _sb_clean(_fr.get("call"))
                if _call in ("Foul", "Do not foul"):
                    # Built outside the f-string: a backslash escape inside an f-string EXPRESSION is a
                    # SyntaxError before Python 3.12.
                    _fl = "Foul him late" if _call == "Foul" else "Don\u2019t foul late"
                    _fc = "call-foul" if _call == "Foul" else "call-nofoul"
                    _foul = (f'<span class="ph-foul {_fc}">{_fl} '
                             f'<span class="mini">({_sb_fmt(_fr.get("ft_pct"))}% FT)</span></span>')
            add('<div class="pcard">')
            add(f'<div class="ph">{photo_cell(bio.get("photo_url") if bio is not None else None, name, side)}'
                f'<div class="ph-name">{name_link(name, page="upcoming", tab="personnel", team=r["team"], player=name)}'
                f'<div class="ph-bio">{r["bits"]}</div></div>{_foul}</div>')
            if p is not None:
                add('<table class="compact pstats"><thead><tr><th>GP</th><th>MIN</th><th>PTS</th><th>REB</th>'
                    '<th>AST</th><th>FG%</th><th>3P%</th><th>FT%</th></tr></thead><tbody><tr>'
                    f'<td>{_sb_fmt(p["games"], 0)}</td><td>{_sb_fmt(p.get("MIN"))}</td><td>{_sb_fmt(p["PTS"])}</td>'
                    f'<td>{_sb_fmt(p["REB"])}</td><td>{_sb_fmt(p["AST"])}</td><td>{_sb_fmt(p["FG%"])}</td>'
                    f'<td>{_sb_fmt(p["3P%"])}</td>' + _ft_cell(p) + "</tr></tbody></table>")
            else:
                add('<p class="mini">No box-score line.</p>')
            add(_shot_line(name, side))
            if r["items"]:
                add('<div class="p-reads">' + ("<ul class=\"tbl-bul\">" + "".join(
                    f"<li>{_sb_esc(x)}</li>" for x in r["items"][:3]) + "</ul>") + "</div>")
            add("</div>")

    def personnel_pages(side, team_title, stats_df, card_fn, extra_no_min="", break_first=True, lead=None):
        names_by_prod = list(stats_df.sort_values("PTS_total", ascending=False)["name"]) if not stats_df.empty else []
        starters, bench, basis, limited = tier_groups(side, names_by_prod)
        if starters is None:
            starters, bench = names_by_prod[:5], [("Bench", "No personnel tiers on file yet.", names_by_prod[5:])]
            basis = "no tier table -- top five by production"
        if not starters and not any(g[2] for g in bench):
            return
        if break_first:
            page_break()
        if lead:
            lead()  # e.g. the team divider, kept on the same page as the starters it introduces
        section(f"\U0001f465 {team_title} - ROSTER"
                + footnote(f"{team_title} starters: {basis}. Per-game averages from their own film. "
                           "After each bio: 'Off' = his offensive role (BBall Index's 12) from his play types; 'Def' "
                           "= his defensive role (BBall Index's 7) from coverage tags with his number, film tracking "
                           "where he was identified for sure, and his steals/blocks -- '(low sample)' when there's "
                           "little to go on, '(position only)' with no data. "
                           + ("Photo, jersey, position, height and class come from the FastScout roster page when "
                              "a live scrape has run; hand and status aren't on that page and stay blank. Coach "
                              "notes pass through as written; data-driven lines are stated against the team's own "
                              "averages with attempt floors." if side == "Opponent" else
                              "Flags come from our own season film (highest-confidence first in the app). Play-call "
                              "lines need 3+ tagged uses of a set.")))
        # CONFIRMED CHANGE (requested): starters and every bench tier live in ONE roster section, in the same
        # table shape. Starters get up to three bullets in the last column; each player's full card (every
        # read, note and key) is one click away in the app.
        add('<div class="card">')
        add('<div class="tier-h">Starters</div>')
        bench_table(starters, stats_df, side, bullets=True)
        for label, caption, names in bench:
            if not names:
                continue
            add(f'<div class="tier-h">{_sb_esc(label)}</div><p class="tier-c">{_sb_esc(caption)}</p>')
            bench_table(names, stats_df, side)
        # Players never on the floor in any game on film are also app-only now; count them with the rest.
        _extra_n = len([x for x in str(extra_no_min or "").split(",") if x.strip()])
        if side == "Opponent" and _foul_by:
            add('<p class="mini">Late game foul: <span class="call-foul">\u2714</span> foul him '
                '(62% or worse on 8+ attempts) &middot; <span class="call-nofoul">\u2718</span> do not foul '
                '(75% or better, or 85%+ on as few as 4 attempts) &middot; \u2013 neutral or too few '
                'attempts to say.</p>')
        # ONE link out of the roster, not two (requested). Under-8-minute players are tiered but no longer
        # printed, so the count rides on this same line rather than earning a second identical hyperlink.
        _omitted = len(limited) + _extra_n
        add('<p class="mini">'
            + (f'{_omitted} more player(s) \u2014 under 8 minutes a game or not playing recently \u2014 are '
               f'not listed here. ' if _omitted else "")
            + app_link("Full card for any player", page="upcoming", tab="personnel",
                       team="uww" if side == "UWW" else "opponent") + "</p>")
        add("</div>")

    # ---- compact tables used by several sections -------------------------------------------------------
    def pc_table(rows, cols, team_ppp=None, row_class=""):
        out = ["<table class=\"compact\"><thead><tr>"
               + "".join(f'<th style="text-align:{"left" if k in ("name", "top_player", "situation") else "right"}">{_sb_esc(l)}</th>' for k, l in cols)
               + "</tr></thead><tbody>"]
        _rc = f' class="{row_class}"' if row_class else ""
        for _, r in rows.iterrows():
            cells = []
            for k, _l in cols:
                v = r.get(k)
                if k == "ppp":
                    cls = ""
                    if pd.notna(v) and team_ppp is not None and pd.notna(team_ppp):
                        cls = "ppp-good" if v >= team_ppp + 0.15 else ("ppp-bad" if v <= team_ppp - 0.15 else "")
                    cells.append(f'<td class="{cls}">{_sb_fmt(v, 2)}</td>')
                elif k == "fg":
                    cells.append(f'<td>{int(r["fgm"])}/{int(r["fga"])}</td>' if int(r.get("fga") or 0) else "<td>--</td>")
                elif k in ("name", "top_player", "situation"):
                    cells.append(f'<td class="wrap">{_sb_esc(_sb_clean(v))}</td>')
                else:
                    cells.append(f"<td>{_sb_fmt(v, 0)}</td>")
            out.append(f"<tr{_rc}>" + "".join(cells) + "</tr>")
        out.append("</tbody></table>")
        return "".join(out)

    # ---- how TOP LINEUPS & 3-MAN COMBOS picks the BEST units (requested) -----------------------------
    # Both teams, five-man units and trios alike, are ranked the same way the "Feature the ... combo" key
    # ranks trios: scoring margin per 40 minutes, shrunk toward zero as if shrink_minutes of an even game
    # were added, so a unit that was +9 in 6 minutes can't outrank one that was +30 in 90. A unit must also
    # clear a minutes floor; if fewer than three do, the table fills with the next best and marks them *.
    # Ours use competitive minutes only (garbage time set aside). Theirs can't: their lineup data has no
    # score at the start of each stint.
    _CRt = globals().get("COMBO_RULES") or {"shrink_minutes": 40, "min_minutes": 40, "min_games": 3,
                                            "min_on_off": 0.0}
    LINEUP_TABLE_RULES = {
        "shrink_minutes": _CRt["shrink_minutes"],
        "five_min_minutes": globals().get("_KTV_OPP_LU_MIN_MINUTES", 8.0),     # same floor as the lineup keys
        "opp_three_min_minutes": globals().get("_KTV_OPP_3MAN_MIN_MINUTES", 12.0),
        "uww_three_min_minutes": _CRt["min_minutes"],                          # same bar as the combo key
        "uww_three_min_games": _CRt["min_games"],
        "uww_three_min_on_off": _CRt["min_on_off"],
    }

    def _rank_units(df, min_col, pm_col, floor, n=3, elig=None, collapse_twins=False):
        """Top n units by shrunk margin per 40. Adds _rmin, _rpm, _per40, _shrunk, _below, _twins."""
        d = df.copy()
        d["_rmin"] = pd.to_numeric(d[min_col], errors="coerce").fillna(0)
        d["_rpm"] = pd.to_numeric(d[pm_col], errors="coerce").fillna(0)
        d = d[d["_rmin"] > 0]
        if d.empty:
            return d
        d["_per40"] = d["_rpm"] / d["_rmin"] * 40
        d["_shrunk"] = d["_rpm"] / (d["_rmin"] + LINEUP_TABLE_RULES["shrink_minutes"]) * 40
        d = d.sort_values(["_shrunk", "_rmin"], ascending=[False, False], kind="stable")
        d["_twins"] = 0
        if collapse_twins:
            # Trios cut from one five-man unit that only ever played together have identical numbers --
            # show the first once and say how many others share it, instead of three identical rows.
            _sig = d["_rmin"].round(2).astype(str) + "|" + d["_rpm"].round(2).astype(str)
            d["_twins"] = _sig.map(_sig.value_counts()) - 1
            d = d[~_sig.duplicated()]
        _ok = d["_rmin"] >= floor
        if elig is not None:
            _ok &= elig.reindex(d.index).fillna(False).astype(bool)
        d["_below"] = ~_ok
        return pd.concat([d[_ok], d[~_ok]]).head(n)

    def _signed(v, digits=1):
        return ("+" if pd.notna(v) and v > 0 else "") + _sb_fmt(v, digits)

    def lineups_table(lu_df, side, note_rows=True):
        if lu_df.empty or "lineup" not in lu_df.columns:
            return
        # PPP per five-man unit, from the play-call summary's own per-lineup rows (level "Personnel grouping"),
        # so it means the same thing here as everywhere else in the brief.
        _lu_ppp = {}
        if not _pcs_all.empty and "level" in _pcs_all.columns:
            _lp = _pcs_all[(_pcs_all["side"] == side) & (_pcs_all["level"] == "Personnel grouping")]
            _lu_ppp = {str(r["name"]): (r.get("ppp"), r.get("uses")) for _, r in _lp.iterrows()}
        # Best units by shrunk margin per 40 (LINEUP_TABLE_RULES). Ours on competitive minutes when the
        # parser exported them; PPP is shown but no longer ranks -- it's offense only, from tagged clips.
        _clean = side == "UWW" and {"clean_min", "clean_pm"}.issubset(lu_df.columns)
        top = _rank_units(lu_df, "clean_min" if _clean else "MIN", "clean_pm" if _clean else "+/-",
                          LINEUP_TABLE_RULES["five_min_minutes"])
        if top.empty:
            return
        # What each unit actually runs (requested), from the parser's per-lineup play-call table, plus its
        # grouping shape so the row says who is on the floor as well as what they call.
        _lu_calls, _lu_group = {}, {}
        _lpc = _sb_d("uww_lineup_play_calls")
        if not _lpc.empty and "lineup" in _lpc.columns:
            _lpc = _lpc[_lpc["side"] == side] if "side" in _lpc.columns else _lpc
            _lu_calls = {str(r["lineup"]): _sb_clean(r.get("top_calls")) for _, r in _lpc.iterrows()}
            _lu_group = {str(r["lineup"]): _sb_clean(r.get("grouping")) for _, r in _lpc.iterrows()}
        add('<table class="compact"><thead><tr><th style="text-align:left">Lineup</th>'
            '<th style="text-align:left">Group</th><th>GP</th><th>MIN</th>'
            '<th>+/-</th><th>per 40</th><th>PPP</th>' + ("<th>FG%</th><th>3P%</th>" if "FG%" in lu_df.columns else "")
            + '<th style="text-align:left">What they run</th>'
            + ('<th style="text-align:left">Key</th>' if note_rows else "") + "</tr></thead><tbody>")
        for _, u in top.iterrows():
            key = ""
            if note_rows and not _notes_tbl.empty:
                nr = _notes_tbl[(_notes_tbl["subject_type"] == "lineup") & (_notes_tbl["name"] == str(u["lineup"]))]
                ks = [k for _, r in nr.iterrows() for k in _sb_split(r.get("keys_to_defending"))]
                key = ks[0] if ks else ""
            _ppp, _ppp_n = _lu_ppp.get(str(u["lineup"]), (None, None))
            add(f'<tr><td class="wrap">{_sb_esc(u["lineup"])}</td>'
                f'<td class="mini">{_sb_esc(_lu_group.get(str(u["lineup"]), ""))}</td>'
                f'<td>{_sb_fmt(u.get("GP"), 0)}</td>'
                f'<td>{_sb_fmt(u["_rmin"])}{"*" if u["_below"] else ""}</td><td>{_signed(u["_rpm"], 0)}</td>'
                f'<td>{_signed(u["_per40"])}</td>'
                + (f'<td title="{int(_ppp_n)} tagged possessions">{_sb_fmt(_ppp, 2)}</td>'
                   if _ppp is not None and pd.notna(_ppp) else '<td class="mini">--</td>')
                + (f'<td>{_sb_fmt(u.get("FG%"))}</td><td>{_sb_fmt(u.get("3P%"))}</td>' if "FG%" in lu_df.columns else "")
                + f'<td class="wrap mini">{_sb_esc(_lu_calls.get(str(u["lineup"]), "--"))}</td>'
                + (f'<td class="wrap mini">{_sb_esc(key)}</td>' if note_rows else "") + "</tr>")
        add("</tbody></table>")

    def combos_table(side):
        """Top three 3-man combos (alongside the five-man units).

        UWW's own combos are sorted by PPP with a minutes-per-game floor (requested) -- the opponent's stay
        sorted by minutes, since we're not trying to pick their best combo to run, just show what's real.
        Same table the Keys to Victory's combo keys are built from (uww_three_man_combos, exported by the
        KTV cell), so a combo named in a key and the combo shown here can never disagree. PPP and "What they
        run" come from tagged possessions with all three on the floor; per-100 margin is shown next to raw
        +/- because a trio's minutes vary far more than a five's, and raw +/- mostly measures playing time.
        """
        df = _sb_d("uww_three_man_combos")
        if df.empty or "lineup" not in df.columns or "side" not in df.columns:
            return False
        df = df[df["side"] == side]
        if "scouted_opponent" in df.columns:
            df = df[df["scouted_opponent"].astype(str) == str(short)]
        if df.empty:
            return False
        df = df.assign(_min=pd.to_numeric(df["MIN"], errors="coerce"),
                       _pm=pd.to_numeric(df["+/-"], errors="coerce"))
        _gp_exact = bool(df["gp_exact"].astype(str).str.lower().eq("true").all()) if "gp_exact" in df.columns else True

        # Tagged possessions with all three on the floor -- offensive possessions only, matched on
        # normalised names so "Jake Quast" and "JAKE QUAST" count as the same player.
        _clips = pd.DataFrame()
        if not _pcc_all.empty and "on_court_lineup" in _pcc_all.columns:
            _clips = _pcc_all[(_pcc_all["side"] == side) & (_pcc_all["decode_quality"] != "Needs review")
                              & _pcc_all["on_court_lineup"].notna()].copy()
            if "possession_side" in _clips.columns:
                _clips = _clips[_clips["possession_side"].astype(str) != "Defense"]
            if not _clips.empty:
                _clips["_five"] = _clips["on_court_lineup"].astype(str).map(
                    lambda s: {_norm(x) for x in re.split(r"[,/|]", s) if x.strip()})
                _clips["_pts"] = pd.to_numeric(_clips.get("points"), errors="coerce")

        def _combo_detail(lineup_str):
            """(ppp, n tagged possessions, "what they run" text) for one trio, computed once and reused by
            both the PPP-sort above and the row rendering below -- no duplicate clip-matching."""
            _trio = {_norm(x) for x in str(lineup_str).split(",") if x.strip()}
            if _clips.empty or len(_trio) != 3:
                return None, 0, "--"
            _on = _clips[_clips["_five"].map(lambda f: _trio <= f)]
            _k = int(_on["_pts"].notna().sum()) if not _on.empty else 0
            _ppp = (_on["_pts"].sum() / _k) if _k else None
            _run = "--"
            if not _on.empty and "play_call" in _on.columns:
                _vc = (_on["play_call"].dropna().astype(str)
                       .loc[lambda x: ~x.str.contains("unspecified", na=False)].value_counts())
                if len(_vc):
                    _run = ", ".join(f"{n} ({int(c)}x)" for n, c in _vc.head(2).items())
            return _ppp, _k, _run

        R = LINEUP_TABLE_RULES
        if side == "UWW" and {"clean_min", "clean_pm"}.issubset(df.columns):
            # Exactly the "Feature the ... combo" key's bar -- competitive minutes, games, positive on/off --
            # so the combo the key features is the top row here.
            _elig = (pd.to_numeric(df.get("clean_gp"), errors="coerce").fillna(0) >= R["uww_three_min_games"])
            if "on_off" in df.columns:
                _elig &= pd.to_numeric(df["on_off"], errors="coerce").fillna(-999) > R["uww_three_min_on_off"]
            top = _rank_units(df, "clean_min", "clean_pm", R["uww_three_min_minutes"], elig=_elig,
                              collapse_twins=True)
        else:
            top = _rank_units(df, "MIN", "+/-", R["opp_three_min_minutes"] if side != "UWW"
                              else R["uww_three_min_minutes"], collapse_twins=True)
        if top.empty:
            return False

        add('<table class="compact"><thead><tr><th style="text-align:left">Combo</th>'
            + ("<th>GP</th>" if _gp_exact else "")
            + "<th>MIN</th><th>+/-</th><th>per 40</th><th>PPP</th>"
            + '<th style="text-align:left">What they run</th></tr></thead><tbody>')
        for _, u in top.iterrows():
            _ppp, _k, _run = _combo_detail(u["lineup"])
            _ppp_cell = (f'<td title="{_k} tagged possessions">{_sb_fmt(_ppp, 2)}</td>'
                        if _ppp is not None else '<td class="mini">--</td>')
            _twin_txt = (f' <span class="mini">(+{int(u["_twins"])} identical)</span>' if u["_twins"] > 0 else "")
            add(f'<tr><td class="wrap">{_sb_esc(", ".join(_sb_title(x.strip()) for x in str(u["lineup"]).split(",")))}'
                f'{_twin_txt}</td>'
                + (f'<td>{_sb_fmt(u.get("GP"), 0)}</td>' if _gp_exact else "")
                + f'<td>{_sb_fmt(u["_rmin"])}{"*" if u["_below"] else ""}</td><td>{_signed(u["_rpm"], 0)}</td>'
                + f'<td>{_signed(u["_per40"])}</td>'
                + _ppp_cell
                + f'<td class="wrap mini">{_sb_esc(_run)}</td></tr>')
        add("</tbody></table>")
        return True

    # Reconciliation-only now (requested: the "shows its top set..." explanation moved to a visible line
    # under each section header instead of staying a footnote -- see the description added right after
    # section() in the offense sections below). This one stays a footnote: it's a caveat about missing
    # data, not a description of what's shown.
    _SERIES_PIVOT_NOTE = (
        "Not every tagged possession in HOW {OPP} RUNS OFFENSE or HOW WE RUN OFFENSE ran a named set -- some "
        "are tagged with the situation only (untagged, flagged for rewatch, or the title named only a player). "
        "The full list of named sets and their clips is in the app.")

    def _film_clip_lookup():
        """normalized set name -> clip count, from uww_film_clips -- only ever populated for the Opponent
        side (see the game-plan cell). Used to badge the matching rows in HOW {OPP} RUNS OFFENSE instead of
        listing them again in their own FILM SESSION section (requested). clip_group arrives as
        "Set Name (Situation)"; the situation is dropped and counts are summed, so a set tagged in more than
        one situation badges with its full clip count wherever it appears."""
        df, _ = staff_rows("uww_film_clips")
        out = {}
        if df.empty or "clip_group" not in df.columns:
            return out
        for _, r in df.iterrows():
            _group = _sb_clean(r.get("clip_group"))
            m = re.match(r"^(.*) \((.*)\)$", _group)
            _name = m.group(1) if m else _group
            if not _name:
                continue
            out[_norm(_name)] = out.get(_norm(_name), 0) + int(pd.to_numeric(r.get("clips"), errors="coerce") or 0)
        return out


    _CLOCK_ORDER = ["Early clock (0-9 sec used)", "Organized offense (10-19 sec used)", "Late clock (20+ sec used)"]
    _SIT_ORDER = ["Leading by 10+", "Trailing by 10+", "Clutch (last 5 min, margin \u2264 8)"]

    # =====================================================================================================
    # PAGE 1 -- GAME PLAN
    # =====================================================================================================
    lede = []
    if them.get("games"):
        lede.append(f"Scoring {_sb_fmt(them.get('PTS'))} a game and allowing {_sb_fmt(them_allowed.get('PTS'))}, "
                    f"over {int(them['games'])} game{'s' if them['games'] != 1 else ''} of film.")
    if not players.empty:
        _tg = int(them.get("games") or players["games"].max() or 1)
        _regular = players[players["games"] >= max(1, 0.5 * _tg)].sort_values("PTS_total", ascending=False)
        _team_pts_total = float(players["PTS_total"].sum()) or None
        if not _regular.empty:
            top = _regular.iloc[0]
            share = round(100 * float(top["PTS_total"]) / _team_pts_total) if _team_pts_total else None
            lede.append(f"{top['name']} leads them at {_sb_fmt(top['PTS'])} a night"
                        + (f" \u2014 {share}% of their points on film." if share else "."))
            if len(_regular) > 1:
                second = _regular.iloc[1]
                lede.append(f"{second['name']} is the next threat at {_sb_fmt(second['PTS'])} "
                            f"({_sb_fmt(second['REB'])} reb, {_sb_fmt(second['AST'])} ast).")
    if them.get("3P%") is not None and them.get("3PA") is not None:
        lede.append(f"They shoot {_sb_fmt(them['3P%'])}% from three on {_sb_fmt(them['3PA'])} attempts a game.")
    # Pace moved out of its own section (requested) -- the full tempo table stays in the app. It earns a
    # Bottom Line sentence only when it would change preparation; the thresholds are BOTTOM_LINE_RULES at
    # the top of this cell, and the sentence carries a note stating them so the staff can see the rule.
    _R = BOTTOM_LINE_RULES
    _tp, _tp_sample = staff_rows("uww_tempo_profile")
    if not _tp.empty and not _tp_sample and {"opponent", "metric", "value"}.issubset(_tp.columns):
        def _tv(team, metric):
            _r = _tp[(_tp["opponent"].astype(str) == str(team)) & (_tp["metric"].astype(str) == metric)]
            return pd.to_numeric(_r["value"].iloc[0], errors="coerce") if not _r.empty else None
        _their_pace = _tv(short, "Possessions per game")
        _our_pace = _tv("UW-Whitewater", "Possessions per game")
        _early = _tv(short, "Early-offense share")
        _bits = []
        if _their_pace is not None and _our_pace is not None and pd.notna(_their_pace) and pd.notna(_our_pace) \
                and abs(_their_pace - _our_pace) >= _R["tempo_pace_gap"]:
            _bits.append(f"they play {'faster' if _their_pace > _our_pace else 'slower'} than we do "
                         f"({_their_pace:.0f} possessions a game to our {_our_pace:.0f})")
        if _early is not None and pd.notna(_early) and _early >= _R["tempo_early_share"]:
            _bits.append(f"{_early:.0f}% of their tagged possessions shoot inside 10 seconds, so transition "
                         "defense needs its own work")
        if _bits:
            lede.append("Tempo: " + "; ".join(_bits) + ".")
    # Four Factors no longer gets its own table (requested) -- call out the biggest weighted gap here instead,
    # but only when it's genuinely decisive: the top factor's weighted edge has to clear both an absolute floor
    # (so a game with four small, similar factors stays quiet) and a relative one (at least double the next
    # factor, so it reads as THE story, not just nominally first).
    if _ff_top is not None and len(_ff_rows) > 1:
        _ff_second = _ff_rows[1]
        _ff_others_sum = sum(abs(r["weighted"]) for r in _ff_rows[1:])
        if (abs(_ff_top["weighted"]) >= BOTTOM_LINE_RULES["ff_min_weighted"]
                and abs(_ff_top["weighted"]) >= BOTTOM_LINE_RULES["ff_dominance"] * abs(_ff_second["weighted"])):
            _whose = "our" if _ff_top["edge"] > 0 else f"{_sb_clean(opp_display)}'s"
            _tail = (", more than the other three factors combined."
                     if abs(_ff_top["weighted"]) > _ff_others_sum
                     else f", well clear of the next-largest factor ({_ff_second['factor']}, "
                          f"{_ff_second['weighted']:+.2f}).")
            lede.append(f"The clearest statistical edge is {_ff_top['factor']} \u2014 {_whose} edge "
                        f"(UWW {_ff_top['uww']:.1f} vs {_ff_top['opp']:.1f}), a {_ff_top['edge']:+.1f} point gap "
                        f"worth {_ff_top['weighted']:+.2f} weighted" + _tail)

    # ---- Rebounding: only when lopsided (REBOUND_RULES, shared with the key and the roster read) -------
    _RR = globals().get("REBOUND_RULES") or {"min_paired": 20, "crash_rate": 35, "soft_rate": 65,
                                              "player_share": 35, "player_min": 5}
    _rs = _sb_d("uww_rebound_summary")
    if not _rs.empty and "opponent" in _rs.columns:
        _rs = _rs[_rs["opponent"].astype(str) == str(short)]
    _reb_bits = []
    if not _rs.empty and "metric" in _rs.columns:
        def _rv(metric):
            _r = _rs[_rs["metric"] == metric]
            return _r.iloc[0] if not _r.empty else None
        _o, _d = _rv("their_oreb_pct"), _rv("their_dreb_pct")
        _our_dreb_base = _rv("our_dreb_allowed_base")
        _our_oreb_base = _rv("our_oreb_base")
        if _o is not None and int(_o["paired"]) >= _RR["min_paired"] and float(_o["value"]) >= _RR["crash_rate"]:
            _top = _rs[_rs["metric"] == "their_oreb_player"].sort_values("count", ascending=False)
            # "Is 38% a lot?" (requested) -- compared against what we usually allow ourselves, from our own
            # season's play-by-play, not a bare percentage with nothing to judge it against.
            _vs = (f" (we usually allow {float(_our_dreb_base['value']):.0f}%)" if _our_dreb_base is not None else "")
            _reb_bits.append(f"they grab {float(_o['value']):.0f}% of their own misses{_vs}"
                             + (f", {_sb_title(_top.iloc[0]['player'])} the most ({int(_top.iloc[0]['count'])})"
                                if not _top.empty else ""))
        if _d is not None and int(_d["paired"]) >= _RR["min_paired"] and float(_d["value"]) <= _RR["soft_rate"]:
            _vs2 = (f" (we usually get {float(_our_oreb_base['value']):.0f}%)" if _our_oreb_base is not None else "")
            _reb_bits.append(f"they secure only {float(_d['value']):.0f}% of opponents' misses{_vs2}, so our "
                             "misses are live balls")
    if _reb_bits:
        lede.append("Rebounding: " + "; ".join(_reb_bits) + ".")

    # ---- Style matchups: only when the record is lopsided, on enough games, at real confidence ---------
    _sm = _sb_d("uww_style_matchups")
    if not _sm.empty and {"opponent", "direction", "dir_wins", "dir_losses", "confidence"}.issubset(_sm.columns):
        _sm = _sm[_sm["opponent"].astype(str) == str(short)]
        for _dir in ("like_them", "like_us"):
            _g = _sm[_sm["direction"] == _dir]
            if _g.empty:
                continue
            _w = pd.to_numeric(_g["dir_wins"], errors="coerce").iloc[0]
            _l = pd.to_numeric(_g["dir_losses"], errors="coerce").iloc[0]
            _conf = pd.to_numeric(_g["confidence"], errors="coerce").max()
            if pd.isna(_w) or pd.isna(_l) or pd.isna(_conf):
                continue
            _n = int(_w) + int(_l)
            _share = (_w / _n) if _n else 0.5
            if (_n < BOTTOM_LINE_RULES["style_min_games"] or _conf < BOTTOM_LINE_RULES["style_min_confidence"]
                    or (1 - BOTTOM_LINE_RULES["style_lopsided"]) < _share < BOTTOM_LINE_RULES["style_lopsided"]):
                continue
            _teams = ", ".join(_sb_strip_mascot(t) for t in _g.sort_values("rank")["team"].head(3))
            _pf = pd.to_numeric(_g["dir_pf"], errors="coerce").iloc[0] if "dir_pf" in _g.columns else None
            _pa = pd.to_numeric(_g["dir_pa"], errors="coerce").iloc[0] if "dir_pa" in _g.columns else None
            _sc = f", averaging {_pf:.0f}-{_pa:.0f}" if _pf is not None and _pa is not None and pd.notna(_pf) \
                and pd.notna(_pa) else ""
            if _dir == "like_them":
                lede.append(f"Against teams that play like them ({_teams}) we're {int(_w)}-{int(_l)}{_sc}.")
            else:
                lede.append(f"Teams that play like us ({_teams}) went {int(_w)}-{int(_l)} against them{_sc}.")
    # Read-with-caution items are rendered at the very END of the brief (requested) -- they qualify numbers
    # throughout, so they read better as a closing caveat than as a wall of warnings on the game-plan page.
    _warn_df, _ = staff_rows("uww_sample_size_warnings")

    _SB_SOURCE_COLORS = {"Data-Driven": "#37474f", "Keys to Victory": "#4E2A84", "Team Strengths": "#c62828",
                         "Lineup Scouting": "#5d4037", "Coach Notes": "#00695c", "Game Plan": "#FF6B6B"}

    def source_badge(source):
        source = _sb_clean(source)
        if not source:
            return ""
        color = _SB_SOURCE_COLORS.get(source, "#666")
        return f' <span class="src" style="border-color:{color};color:{color};">{_sb_esc(source)}</span>'

    ktv = _sb_d("uww_ktv_keys")
    if not ktv.empty and "opponent" in ktv.columns:
        ktv = ktv[ktv["opponent"].astype(str) == str(short)]
        if "key_number" in ktv.columns:
            ktv = ktv.sort_values("key_number")

    # --- Synthesize key insights from THE BOTTOM LINE into KEYS TO VICTORY ---
    # If information was important enough for THE BOTTOM LINE (conditional or core), it belongs in KEYS TO VICTORY
    _synthesized_keys = []
    _next_key_number = int(ktv["key_number"].max()) + 1 if not ktv.empty and "key_number" in ktv.columns else 1

    # Map lede items to synthesized keys with appropriate categories
    if lede:
        # Extract the insights that came from conditions (these are the ones most worth highlighting)
        for _lede_item in lede:
            _item_text = _lede_item[0] if isinstance(_lede_item, tuple) else _lede_item
            _category = "General"
            _headline = None

            # Categorize and shorten the lede insight for KTV display
            if "Tempo:" in _item_text:
                _category = "Offense"
                _headline = "Tempo adjustment: " + _item_text.replace("Tempo: ", "").rstrip(".")
            elif "Four Factors" in _item_text or "statistical edge" in _item_text:
                _category = "Defense" if "edge" in _item_text.lower() else "Offense"
                # Extract just the factor name and which team's edge
                if "—" in _item_text:
                    _factor_part = _item_text.split("—")[1].split("(")[0].strip()
                    _headline = f"Focus on {_factor_part.lower()}"
                else:
                    _headline = "Key statistical edge"
            elif "Rebounding:" in _item_text:
                _category = "Defense"
                _headline = "Rebounding edge: " + _item_text.replace("Rebounding: ", "").rstrip(".")
            elif "teams that play" in _item_text.lower():
                _category = "General"
                _headline = "Style matchup: " + _item_text.rstrip(".")
            elif "shoot" in _item_text.lower() and "three" in _item_text.lower():
                _category = "Defense"
                _headline = "Monitor three-point shooting"
            elif "leads them" in _item_text.lower() or "threat at" in _item_text.lower():
                _category = "Personnel"
                _headline = _item_text.rstrip(".")
            elif "Scoring" in _item_text and "allowing" in _item_text:
                _category = "General"
                _headline = "Scoring/pace context"

            if _headline and len(_headline) > 8:
                # Edge size for the priority model: their top scorer and a Four Factors edge are the
                # biggest game-plan items; a bare scoring/pace summary is context, not a key.
                if _category == "Personnel" or _headline.startswith("Focus on"):
                    _gp_impact = 0.7
                elif _headline.startswith("Monitor three"):
                    _gp_impact = 0.6
                elif _headline.startswith("Style matchup"):
                    _gp_impact = 0.4
                else:
                    _gp_impact = 0.5
                _synthesized_keys.append({
                    "key_number": _next_key_number,
                    "opponent": str(short),
                    "headline": _headline,
                    "category": _category,
                    "source": "Game Plan",
                    "impact": _gp_impact,
                    "confidence": 0.6,
                    "brief_eligible": _headline != "Scoring/pace context",
                })
                _next_key_number += 1

    # Append synthesized keys to the ktv dataframe
    if _synthesized_keys:
        _synth_df = pd.DataFrame(_synthesized_keys)
        ktv = pd.concat([ktv, _synth_df], ignore_index=True) if not ktv.empty else _synth_df
        ktv = ktv.sort_values("key_number") if "key_number" in ktv.columns else ktv

    # Only the highest-priority keys go on the brief (KTV_BRIEF_RULES / ktv_select_for_brief, defined in the
    # key-building cell). The app still shows every key from uww_ktv_keys.csv.
    _ktv_total = len(ktv)
    _ktv_select = globals().get("ktv_select_for_brief")
    ktv_brief = _ktv_select(ktv) if (_ktv_select and not ktv.empty) else ktv
    _KBR = globals().get("KTV_BRIEF_RULES") or {"min_score": 55, "max_keys": 6}

    if not ktv_brief.empty:
        # How the data-driven keys that pick PEOPLE are chosen, stated from the same settings the parser
        # uses (COMBO_RULES, REBOUND_RULES), so the explanation can't drift from what the code does.
        _CRn = globals().get("COMBO_RULES") or {"garbage_margin": 15, "garbage_from_period": 2, "min_minutes": 40,
                                                "min_games": 3, "shrink_minutes": 40, "min_on_off": 0.0}
        _RRn = globals().get("REBOUND_RULES") or {"min_paired": 20, "crash_rate": 35, "soft_rate": 65}
        section("\U0001f511 KEYS TO VICTORY" + footnote(
            f"The brief shows the {len(ktv_brief)} highest-priority of {_ktv_total} keys; every key is on the "
            "app. Each key is scored 0-100: who says so (staff-written keys score highest), how big the edge "
            "is, how much data backs it, and whether it is an instruction. Keys scoring "
            f"{_KBR['min_score']}+ are shown, best first, up to {_KBR['max_keys']}, one per topic. "
            "Keys are built by the parser into uww_ktv_keys.csv and rendered identically by the app. Each key's "
            "evidence (the numbers behind it) and full reasoning are on the app's Keys to Victory tab -- click a "
            "key to open it there. "
            "HOW \"FEATURE THE ... COMBO\" IS CHOSEN: every 3-player group from our lineup stints, counting "
            f"competitive minutes only -- a stint that starts in the 2nd half or OT with the margin at "
            f"{_CRn['garbage_margin']}+ is garbage time and set aside. A trio needs {_CRn['min_minutes']}+ "
            f"competitive minutes across {_CRn['min_games']}+ games. It is ranked by scoring margin per 40 "
            f"minutes, shrunk toward zero as if {_CRn['shrink_minutes']} more minutes of an even game were added, "
            "so a short hot streak can't top the list. It must also be on/off positive: we do better with those "
            "three on the floor than with them off, which separates the trio from whoever else was out there. "
            "If no trio clears all of that, there is no combo key -- a missing key means none qualified yet, not "
            "that it wasn't checked. When the top trio has numbers identical to other trios (they only ever played "
            "together as one group), no single trio can be singled out, so the key names the whole group as a "
            "\"unit\" instead. Season-wide, not specific to this opponent. "
            f"REBOUNDING KEYS: \"box out\" when they rebound {_RRn['crash_rate']}%+ of their own misses, \"crash "
            f"the glass\" when they secure {_RRn['soft_rate']}% or less of opponents' misses, each on "
            f"{_RRn['min_paired']}+ paired misses from their play-by-play."))
        # Full-width display with reasoning (requested)
        add('<div class="card">')
        for _, k in ktv_brief.iterrows():
            _rank = int(k["brief_rank"]) if "brief_rank" in k and pd.notna(k.get("brief_rank")) else ""
            _app_key = int(k["key_number"]) if pd.notna(k.get("key_number")) else None
            _headline = _sb_clean(k.get("headline")).rstrip(".")
            _reasoning = _sb_clean(k.get("reasoning")).rstrip(".")
            _source = source_badge(k.get("source"))
            # Bottom Line keys exist only in the brief, so only the app's own keys link to an entry there.
            _head_html = (name_link(_headline, page="upcoming", tab="keys", key=_app_key)
                          if _app_key and str(k.get("source")) != "Game Plan" else _sb_esc(_headline))

            # Sentence format: "N. Headline — reason."
            _sentence = f'<span class="n">{_rank}.</span> <span>{_head_html}'
            if _reasoning:
                _sentence += f' — {_sb_esc(_reasoning)}'
            _sentence += '.</span>'

            add(f'<div class="ktv-sentence">{_sentence} {_source}</div>')   # a space: copied text reads "... reason. Data-Driven"
        add('<p class="mini">' + app_link(f"All {_ktv_total} keys with evidence and reasoning", page="upcoming", tab="keys") + "</p>")
        add("</div>")


    # ---- head-to-head: how the previous meeting(s) went (requested) ------------------------------------
    _h2h = _sb_d("uww_head_to_head")
    if not _h2h.empty:
        # Scope to what's actually useful for THIS matchup (requested): if we've already played them this
        # season, last season's numbers are stale -- show only this season's meeting(s). Otherwise fall back
        # to the most recent seasons on file. Either way, cap at the 3 most recent -- head_to_head is already
        # sorted season desc, date desc, so .head(3) is exactly that.
        _this_season = _sb_clean(game.get("season"))
        _h2h_this_season = _h2h[_h2h["season"].astype(str) == _this_season] if _this_season else pd.DataFrame()
        _h2h = (_h2h_this_season if not _h2h_this_season.empty else _h2h).head(3)
    if not _h2h.empty:
        _h2h_w = int((_h2h["outcome"].astype(str).str.upper() == "W").sum())
        section(f"\U0001f501 WHEN WE'VE PLAYED {OPP_UP}" + footnote(
            "Previous meetings with this opponent, from our own schedules. Scoped to this matchup: if we've "
            "already played them this season, only this season's meeting(s) are shown, since an earlier "
            "season's numbers are the less relevant read once there's a current one; otherwise it's the most "
            "recent seasons on file. Capped at the 3 most recent meetings either way. Each meeting's play-by-play "
            "is pulled from its own box score and cached, so the numbers below are that game's real box score. "
            "\\\"How this team is different now\\\" compares who played in that meeting against this year's roster "
            "and box scores -- points shown in brackets are what that player scored against US in the meeting, "
            "not a season average."))
        add('<div class="card">')
        # CONFIRMED CHANGE (coach: "not formatted to help coaches know if the previous games against the upcoming
        # opponent matter"). The section opens with the VERDICT -- computed in the parser from how long ago the
        # meetings were and how much of each team's scoring in them is still on its roster -- then one compact
        # table of the meetings with each team's top scorer marked still there / gone.
        _cont = _sb_d("uww_head_to_head_continuity")
        if not _cont.empty and "opponent" in _cont.columns:
            _cont = _cont[_cont["opponent"].astype(str) == str(short)]
        if not _cont.empty and _sb_clean(_cont.iloc[0].get("verdict_headline")):
            _c0 = _cont.iloc[0]
            _vc = {"Yes": "#1b7a3a", "Partly": "#b06b00", "Mostly no": "#b3261e"}.get(_sb_clean(_c0.get("verdict")), "#4E2A84")
            add(f'<p class="ff-lede"><strong style="color:{_vc}">Do these games matter? {_sb_esc(_sb_clean(_c0.get("verdict_headline")))}.</strong></p>'
                f'<p>{_sb_esc(_sb_clean(_c0.get("verdict_why")))} {_sb_esc(_sb_clean(_c0.get("verdict_use")))}</p>')
        _h2h_box_all = _sb_d("uww_head_to_head_box")
        _chg_all = _sb_d("uww_head_to_head_roster_change")
        if not _chg_all.empty and "opponent" in _chg_all.columns:
            _chg_all = _chg_all[_chg_all["opponent"].astype(str) == str(short)]
        _status = {_norm(r["player"]): r["status"] for _, r in _chg_all.iterrows()} if not _chg_all.empty else {}

        def _top_scorer(md, uww):
            if _h2h_box_all.empty or "meeting_date" not in _h2h_box_all.columns:
                return None
            _m = _h2h_box_all[_h2h_box_all["meeting_date"].astype(str) == str(md)]
            _m = _m[_m["team"].astype(str).str.contains("whitewater", case=False, na=False) == uww]
            if _m.empty:
                return None
            _m = _m.assign(_p=pd.to_numeric(_m["PTS"], errors="coerce")).sort_values("_p", ascending=False)
            return _m.iloc[0]["player"], _m.iloc[0]["_p"]

        add(f'<p class="mini">{_h2h_w}-{len(_h2h) - _h2h_w} in the {len(_h2h)} meeting{"s" if len(_h2h) != 1 else ""} shown.</p>')
        add('<table class="compact"><thead><tr><th style="text-align:left">Meeting</th><th style="text-align:left">Result</th>'
            '<th style="text-align:left">Their top scorer</th><th style="text-align:left">Our top scorer</th></tr></thead><tbody>')
        for _, _g in _h2h.iterrows():
            _oc = _sb_clean(_g.get("outcome")).upper()
            _score = (f'{int(_g["team_score"])}-{int(_g["opponent_score"])}'
                      if pd.notna(_g.get("team_score")) and pd.notna(_g.get("opponent_score")) else "")
            _ts, _us = _top_scorer(_g.get("date"), False), _top_scorer(_g.get("date"), True)
            _mark = ""
            if _ts:
                _st = _status.get(_norm(_ts[0]))
                _mark = (' <span class="ppp-good">&#10003; still there</span>' if _st == "Returning" else
                         ' <span class="mini">&#10007; gone</span>' if _st == "Gone" else "")
            add(f'<tr><td style="text-align:left">{_sb_esc(_sb_clean(_g.get("date")))}'
                + (f' &middot; {_sb_esc(_sb_clean(_g.get("home_away")))}' if _sb_clean(_g.get("home_away")) else "")
                + f'<br><span class="mini">{_sb_esc(_sb_clean(_g.get("season")))}</span></td>'
                f'<td style="text-align:left"><span class="{"call-foul" if _oc == "W" else "call-nofoul"}">{_sb_esc(_oc)} {_sb_esc(_score)}</span></td>'
                f'<td style="text-align:left">{(_sb_esc(_ts[0]) + " " + _sb_fmt(_ts[1], 0) + _mark) if _ts else "<span class=mini>--</span>"}</td>'
                f'<td style="text-align:left">{(_sb_esc(_us[0]) + " " + _sb_fmt(_us[1], 0)) if _us else "<span class=mini>--</span>"}</td></tr>')
        add("</tbody></table>")

        # ---- what we ran in each meeting, what defense, and whether it worked (requested) ----------------
        # From the tagged clips of that game, joined on the meeting's real date (head_to_head.game_date).
        # "Worked" is measured against our own season average, not an absolute number: 0.95 PPP is good
        # for some teams and bad for others, and the question is whether the plan beat what we normally do.
        # Most meetings are from earlier seasons that were never tagged -- when NONE of them are, this says
        # so and shows a clearly-labelled sample of what the block will look like, so the staff knows the
        # section exists and what tagging it needs, rather than it silently not appearing.
        def _h2h_clip_view():
            # CONFIRMED BUG (fixed here): filtering to side == "UWW" missed meetings tagged from the OTHER
            # team's file -- e.g. our 2/24/2025 game vs Stevens Point is tagged inside opponent_plays.csv
            # (144 clips, both teams' possessions) because that is whose season file it belongs to, not
            # ours. "side" says which team's file a clip came from, not who had the ball, so it is not the
            # right filter for "every clip of a specific date". Every clip on the meeting's date matters,
            # from either file.
            #
            # possession_side is similarly file-relative -- it is computed against whichever team OWNS the
            # file the clip came from (UWW in uww_plays.csv, the opponent in opponent_plays.csv), so
            # "Offense" on an opponent-side clip means the OPPONENT had the ball, not us. offense_team is
            # already the unambiguous, side-agnostic field (computed once, downstream of possession_side),
            # so it is what decides whether WE had the ball here.
            if _pcc_all.empty or "game_date" not in _h2h.columns or "game_date" not in _pcc_all.columns:
                return []
            _c = _pcc_all[_pcc_all["decode_quality"] != "Needs review"].copy()
            if _c.empty:
                return []
            _c["_d"] = pd.to_datetime(_c["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            _c["_pts"] = pd.to_numeric(_c.get("points"), errors="coerce")
            _c["_off"] = _c.get("offense_team", pd.Series(_SB_UWW, index=_c.index)).astype(str).str.contains(
                "whitewater", case=False, na=False)

            def _ppp(g):
                k = g["_pts"].notna().sum()
                return (g["_pts"].sum() / k) if k else None

            # Season baselines -- what "worked" is measured against.
            _base_off = _ppp(_c[_c["_off"]])
            _base_def = _ppp(_c[~_c["_off"]])
            # The defense split (defense_faced / defense_played) is ALSO file-relative -- populated against
            # whichever team owns the file, same root cause as _off above. On any one clip only one of the
            # pair is ever non-null (see decode_defense_tag), and whichever one it is always describes the
            # defense of whoever did NOT have the ball -- so coalescing them recovers that value regardless
            # of which file it came from, and _off (now side-agnostic) says whose defense it is.
            if "defense_faced" in _c.columns and "defense_played" in _c.columns:
                _c["_def_tag"] = _c["defense_faced"].combine_first(_c["defense_played"])
            else:
                _c["_def_tag"] = pd.Series(pd.NA, index=_c.index)
            views = []
            for _, _g in _h2h.iterrows():
                _gd = _sb_clean(_g.get("game_date"))
                if not _gd:
                    continue
                _m = _c[_c["_d"] == _gd]
                if _m.empty:
                    continue
                views.append((_g, _m[_m["_off"]], _m[~_m["_off"]], _base_off, _base_def, _ppp))
            return views

        def _verdict(v, base, lower_is_better=False):
            if v is None or base is None or pd.isna(v) or pd.isna(base):
                return ""
            d = v - base
            good = (d <= -0.10) if lower_is_better else (d >= 0.10)
            bad = (d >= 0.10) if lower_is_better else (d <= -0.10)
            tag = "worked" if good else ("didn't work" if bad else "about normal")
            cls = "ppp-good" if good else ("ppp-bad" if bad else "")
            return f'<span class="{cls}"><strong>{tag}</strong></span> ({v:.2f} vs our usual {base:.2f})'

        def _top_calls(g, _ppp, n=3):
            if g.empty or "play_call" not in g.columns:
                return ""
            g = g[g["play_call"].notna() & ~g["play_call"].astype(str).str.contains("unspecified", na=False)]
            out = []
            for _name, _cg in g.groupby(g["play_call"].astype(str)):
                out.append((_name, len(_cg), _ppp(_cg)))
            out.sort(key=lambda x: -x[1])
            return ", ".join(f"{_sb_esc(nm)} {k}x" + (f" ({p:.2f})" if p is not None else "")
                             for nm, k, p in out[:n])

        def _def_mix(g, col):
            if g.empty or col not in g.columns or g[col].isna().all():
                return ""
            vc = g[col].dropna().astype(str).value_counts()
            return ", ".join(f"{_sb_esc(k)} {round(100 * int(v) / int(vc.sum()))}%" for k, v in vc.head(2).items())

        _views = _h2h_clip_view()
        if _views:
            add('<div class="pc-sub">What we ran, and did it work</div>')
            add('<table class="compact"><thead><tr><th style="text-align:left">Meeting</th>'
                '<th style="text-align:left">Our offense</th><th style="text-align:left">Our defense</th>'
                "</tr></thead><tbody>")
            for _g, _off, _def, _bo, _bd, _ppp in _views:
                _off_ppp, _def_ppp = _ppp(_off), _ppp(_def)
                _o = []
                if len(_off):
                    _o.append(f"{len(_off)} tagged possessions \u2014 {_verdict(_off_ppp, _bo)}")
                    _tc = _top_calls(_off, _ppp)
                    if _tc:
                        _o.append(f"Ran most: {_tc}")
                    _dm = _def_mix(_off, "_def_tag")
                    if _dm:
                        _o.append(f"They played: {_dm}")
                else:
                    _o.append('<span class="mini">not tagged</span>')
                _d = []
                if len(_def):
                    _d.append(f"{len(_def)} tagged possessions \u2014 {_verdict(_def_ppp, _bd, lower_is_better=True)}")
                    _dm = _def_mix(_def, "_def_tag")
                    if _dm:
                        _d.append(f"We played: {_dm}")
                    _tc = _top_calls(_def, _ppp)
                    if _tc:
                        _d.append(f"They ran: {_tc}")
                else:
                    _d.append('<span class="mini">not tagged</span>')
                # Meeting cell now carries everything the standalone table used to (site, result, margin,
                # leading scorers) -- requested, folded into this table instead of a separate one above it.
                _oc = _sb_clean(_g.get("outcome")).upper()
                _score = (f'{int(_g["team_score"])}-{int(_g["opponent_score"])}'
                          if pd.notna(_g.get("team_score")) and pd.notna(_g.get("opponent_score")) else "")
                _m = _g.get("margin")
                _margin_txt = (" (" + ("+" if pd.notna(_m) and _m > 0 else "") + _sb_fmt(_m, 0) + ")"
                              if pd.notna(_m) else "")
                _leaders = ", ".join(x for x in [
                    f"Us: {_sb_esc(_sb_clean(_g.get('uww_leader')))}" if _sb_clean(_g.get("uww_leader")) else "",
                    f"Them: {_sb_esc(_sb_clean(_g.get('opp_leader')))}" if _sb_clean(_g.get("opp_leader")) else "",
                ] if x)
                add(f'<tr><td class="wrap">{_sb_esc(_sb_clean(_g.get("date")))}'
                    + (f' &middot; {_sb_esc(_sb_clean(_g.get("home_away")))}' if _sb_clean(_g.get("home_away")) else "")
                    + '<br><span class="mini">' + _sb_esc(_sb_clean(_g.get("season")))
                    + f' &middot; <span class="{"call-foul" if _oc == "W" else "call-nofoul"}">{_sb_esc(_oc)}'
                    + f' {_sb_esc(_score)}{_margin_txt}</span></span>'
                    + (f'<br><span class="mini">{_leaders}</span>' if _leaders else "") + '</td>'
                    f'<td class="wrap mini">{"<br>".join(_o)}</td>'
                    f'<td class="wrap mini">{"<br>".join(_d)}</td></tr>')
            add("</tbody></table>")
            add('<p class="mini">"Worked" means 0.10+ PPP better than our season average (on defense, 0.10+ '
                'fewer allowed); numbers in brackets are PPP. Meetings without tagged clips are left out.</p>')
        else:
            add(f'<p class="mini">These meetings have no tagged play calls yet, so what we ran in them isn\'t shown.</p>')

        # ---- their players: who from those games is still there (the useful list), who's gone, who's new ---------
        _h2h_chg = _chg_all
        if not _h2h_chg.empty:
            _ret = _h2h_chg[_h2h_chg["status"] == "Returning"].assign(_p=lambda d: pd.to_numeric(d["prev_pts"], errors="coerce"))
            _gone = _h2h_chg[_h2h_chg["status"] == "Gone"].assign(_p=lambda d: pd.to_numeric(d["prev_pts"], errors="coerce"))
            _new = _h2h_chg[_h2h_chg["status"] == "New since then"]
            add('<div class="pc-sub">Their players from those games</div>')
            if not _ret.empty:
                _ret = _ret.sort_values("_p", ascending=False)
                add('<p class="mini"><strong>Still there</strong> (points against us in those games): '
                    + _sb_esc(", ".join(f"{r['player']} ({int(r['_p'])})" if pd.notna(r["_p"]) else str(r["player"])
                                        for _, r in _ret.iterrows())) + "</p>")
            else:
                add('<p class="mini"><strong>Still there:</strong> nobody who played against us.</p>')
            if not _gone.empty:
                _gone = _gone.sort_values("_p", ascending=False)
                _top_g = ", ".join(f"{r['player']} ({int(r['_p'])})" for _, r in _gone.head(3).iterrows() if pd.notna(r["_p"]))
                add(f'<p class="mini"><strong>Gone:</strong> {len(_gone)} player(s)'
                    + (f", including {_sb_esc(_top_g)}" if _top_g else "") + ".</p>")
            if not _new.empty:
                _new_names = [str(x) for x in _new["player"].astype(str)]
                _new_box = players_for("uww_opponent_prior_games_box_score", short)
                _cur = {_norm(r["name"]): r for _, r in _new_box.iterrows()} if not _new_box.empty and "name" in _new_box.columns else {}
                _ranked = []
                for _nm in _new_names:
                    _row = _cur.get(_norm(_nm))
                    _ranked.append((_nm, pd.to_numeric(_row.get("MIN"), errors="coerce") if _row is not None else None,
                                    pd.to_numeric(_row.get("PTS"), errors="coerce") if _row is not None else None))
                _worth = sorted([x for x in _ranked if (pd.notna(x[1]) and x[1] >= 8) or (pd.notna(x[2]) and x[2] >= 4)],
                                key=lambda x: (-(x[1] if pd.notna(x[1]) else 0), -(x[2] if pd.notna(x[2]) else 0)))[:5]
                if _worth:
                    add('<p class="mini"><strong>New since then</strong> (who plays): '
                        + _sb_esc(", ".join(_sb_title(n) + (f" ({p:.1f} ppg)" if pd.notna(p) else "") for n, _m, p in _worth))
                        + (f" + {len(_new_names) - len(_worth)} more who barely play" if len(_new_names) > len(_worth) else "")
                        + "</p>")
                else:
                    add(f'<p class="mini"><strong>New since then:</strong> {len(_new_names)}, none averaging real minutes yet.</p>')
        add("</div>")

    def foul_list_block():
        _foul, _ = staff_rows("uww_late_game_foul_list")
        if _foul.empty:
            return
        add('<div class="gcell">')
        section("\u23f1\ufe0f LATE-GAME FOUL LIST" + footnote(
            "From their own free-throw shooting on film. The two calls need different evidence: FOUL him takes 8+ "
            "attempts and a rate at 62% or worse, because it's a deliberate act; DO NOT FOUL takes 8+ attempts "
            "at 75% or better, OR as few as 4 attempts when he hasn't missed (85%+) -- avoiding a shooter "
            "costs nothing if we're wrong. Rates are shrunk toward a 70% baseline before the call, so 6-for-6 "
            "doesn't read as a true 100% shooter; the makes-attempts pair shown is raw. Check who is actually "
            "on the floor before the call."))
        add('<div class="card"><table class="compact"><thead><tr><th style="text-align:left">Player</th>'
            '<th style="text-align:left">Call</th><th>FT%</th><th>FTM-FTA</th></tr></thead><tbody>')
        for _, _f in _foul.iterrows():
            _cls = {"Foul": "call-foul", "Do not foul": "call-nofoul"}.get(_sb_clean(_f.get("call")), "")
            # Games-played detail removed from this table (requested) -- thin samples are flagged on page 1.
            add(f'<tr><td class="nm">{_sb_esc(_f["player"])}</td>'
                f'<td class="{_cls}">{_sb_esc(_f["call"])}</td><td>{_sb_fmt(_f["ft_pct"])}</td>'
                f'<td>{int(_f["ftm"])}-{int(_f["fta"])}</td></tr>')
        add("</tbody></table></div></div>")

    # ---- team stats, four factors and the style comparisons, side by side above the Aurora section --------
    if team_parts:
        section("\U0001f4ca TEAM STATS")
        add('<div class="card">' + "".join(team_parts) + "</div>")
    # TEAMS LIKE ... sections removed from the brief (requested) -- the full panels stay in the app's Tools
    # tab. The record only reaches the brief as a Bottom Line sentence, and only when it's lopsided on
    # enough games at non-low confidence (BOTTOM_LINE_RULES "style_*").

    # =====================================================================================================
    # OPPONENT
    # =====================================================================================================
    page_break()
    divider(f"{OPP_UP}", "Scouting the opponent")

    # ---- recent results ------------------------------------------------------------------------------
    if not opp_before.empty:
        section(f"\U0001f4c5 {OPP_UP} RECENT RESULTS")
        add('<div class="card">')
        add('<div class="results">')
        for _, g in opp_before.tail(5).iterrows():
            outcome = _sb_clean(g.get("outcome")).upper()
            score = (f' {int(g["team_score"])}-{int(g["opponent_score"])}'
                     if pd.notna(g.get("team_score")) and pd.notna(g.get("opponent_score")) else "")
            home = _sb_clean(g.get("location")).lower() == "home"
            add(f'<span class="rs">{_sb_esc(g.get("game_date"))} {"vs" if home else "@"} '
                f'{_sb_esc(_sb_strip_mascot(g.get("vs_opponent")))} <b class="{"w" if outcome == "W" else "l"}">'
                f'{_sb_esc(outcome)}{score}</b></span>')
        add("</div></div>")

    _sm_unused = None
    if not _sm.empty and "opponent" in _sm.columns:
        _sm = _sm[_sm["opponent"].astype(str) == str(short)]


    # ---- personnel: starters page + bench page (#3) ---------------------------------------------------
    _no_min = _sb_d("uww_roster_no_minutes")
    _no_min_names = ""
    if not _no_min.empty and "opponent" in _no_min.columns:
        _no_min = _no_min[_no_min["opponent"].astype(str) == str(short)]
        if not _no_min.empty and int(_no_min.iloc[0].get("count") or 0):
            _no_min_names = _sb_clean(_no_min.iloc[0]["names"])
    _opp_stats = players_for("uww_opponent_prior_games_box_score", short)
    personnel_pages("Opponent", OPP_UP, _opp_stats, opp_card, extra_no_min=_no_min_names)

    # ---- lineups, offense, context --------------------------------------------------------------------
    page_break()
    lineups = _sb_d("uww_opp_lineup_season_box")
    # This table has no opponent column. The key-building cell checks its names against this opponent's
    # roster and sets _ktv_opp_lu to None when it's a stale table from the previous opponent -- honour that
    # here too, instead of printing someone else's lineups under this opponent's name.
    if not lineups.empty and globals().get("_ktv_opp_lu", "unchecked") is None:
        print(f"TOP LINEUPS skipped: uww_opp_lineup_season_box doesn't match {short}'s roster (stale table?).")
        lineups = pd.DataFrame()
    if not lineups.empty and "lineup" in lineups.columns:
        section("\U0001f501 TOP LINEUPS & 3-MAN COMBOS" + footnote(
            "Their best three five-man units and best three 3-man combos, ranked by scoring margin per 40 "
            f"minutes, shrunk toward zero as if {LINEUP_TABLE_RULES['shrink_minutes']:.0f} minutes of an even "
            "game were added, so a short hot stretch can't top the list. A five-man unit needs "
            f"{LINEUP_TABLE_RULES['five_min_minutes']:.0f}+ minutes and a combo "
            f"{LINEUP_TABLE_RULES['opp_three_min_minutes']:.0f}+; * marks a unit shown below that floor "
            "because fewer than three cleared it. Includes all minutes: their lineup data has no score at the "
            "start of each stint, so garbage time can't be set aside. A combo's minutes are every stint with "
            "all three on the floor, whoever the other two were. GP isn't shown for their combos: games "
            "played can't be counted exactly from their lineup data. The key shown "
            "is the first data-driven key for that unit. \"What they run\" is the sets tagged on possessions with "
            "that exact five on the floor, and \"Group\" is its position shape (3G-2B = three guards and two "
            "bigs, from roster positions). Every lineup's full strengths, weaknesses and keys are in the app."))
        add('<div class="card">')
        lineups_table(lineups, "Opponent")
        # Top three 3-man combos under the five-man units (requested). Captured first so the sub-heading
        # only prints when there is a table to put under it.
        _combo_html = capture(combos_table, "Opponent")
        if _combo_html:
            add('<div class="pc-sub">Top 3-man combos</div>')
            add("".join(_combo_html))
        add('<p class="mini">' + app_link("All lineups and combos with full reads", page="upcoming",
                                          tab="personnel", section="lineups") + "</p>")
        add("</div>")

    # =====================================================================================================
    # HOW THEY GUARD SCREENS (requested) -- from the structured tags' defensive details ("5tl" = defender #5
    # top-locked the down screen). Rendered from uww_screen_coverage_summary, built in the play-calls cell;
    # nothing is computed here beyond picking rows. Perspective "Opponent defense" = the upcoming opponent
    # DEFENDING, from their own defensive possessions in opponent_plays.csv. Every row prints its count.
    # =====================================================================================================
    _scv_s = _sb_d("uww_screen_coverage_summary")
    if not _scv_s.empty and {"perspective", "level", "scouted_opponent"}.issubset(_scv_s.columns):
        _scv_s = _scv_s[(_scv_s["scouted_opponent"].astype(str) == str(short))
                        & (_scv_s["perspective"] == "Opponent defense")]
    else:
        _scv_s = pd.DataFrame()
    if not _scv_s.empty:
        _scv_thin_n = globals().get("SCREEN_COVERAGE_RULES", {}).get("thin_screens", 5)
        _scv_t = _scv_s[_scv_s["level"] == "Screen x coverage"].copy()
        _scv_d = _scv_s[_scv_s["level"] == "Defender x screen x coverage"].copy()
        section(f"\U0001f6e1\ufe0f HOW {OPP_UP} GUARDS SCREENS" + footnote(
            "From the coaches' coverage tags on their defensive possessions: each tag names the defender "
            "(by jersey) and how he played the screen, paired with the screen it answered. % is the share of "
            "that screen type. PPP is points on the possessions where that coverage was used -- what happened "
            f"after, not proof the coverage caused it. * = under {_scv_thin_n} tagged screens of that type: "
            "confirm on film."))
        add('<div class="card">')
        add('<table class="compact"><thead><tr><th style="text-align:left">Screen</th><th>Tagged</th>'
            '<th style="text-align:left">Main coverage</th><th>PPP</th>'
            '<th style="text-align:left">Also</th><th style="text-align:left">Usually by</th></tr></thead><tbody>')
        _scv_types = _scv_t.groupby(["screen_family", "screen_type"])["uses"].sum().sort_values(ascending=False)
        _scv_main = {}
        for (_fam, _st), _tot in _scv_types.items():
            _g = _scv_t[(_scv_t["screen_type"] == _st) & (_scv_t["screen_family"] == _fam)].sort_values(
                "uses", ascending=False)
            _m = _g.iloc[0]
            _scv_main[_st] = _m["coverage"]
            _also = ", ".join(f"{_sb_esc(r['coverage'])} {int(r['share_pct'])}% ({int(r['uses'])})"
                              for _, r in _g.iloc[1:4].iterrows()) or "&mdash;"
            _thin = "*" if str(_m.get("thin_sample")).lower() == "true" else ""
            add(f'<tr><td style="text-align:left">{_sb_esc(_st)}{_thin}</td><td>{int(_tot)}</td>'
                f'<td style="text-align:left"><b>{_sb_esc(_m["coverage"])}</b> {int(_m["share_pct"])}% '
                f'({int(_m["uses"])})</td><td>{_sb_fmt(_m.get("ppp"), 2)}</td>'
                f'<td style="text-align:left">{_also}</td>'
                f'<td style="text-align:left">{_sb_esc(_sb_clean(_m.get("top_defender")))}</td></tr>')
        add("</tbody></table>")
        # Defenders who play a screen differently from the team's main call -- the actionable exceptions
        # (who to screen with, who to attack). Needs 2+ tags of that coverage from that defender.
        _scv_exc = []
        for (_st, _who), _g in (_scv_d.groupby(["screen_type", "defender"]) if not _scv_d.empty else []):
            _top = _g.sort_values("uses", ascending=False).iloc[0]
            _n = int(_g["uses"].sum())
            if int(_top["uses"]) >= 2 and _top["coverage"] != _scv_main.get(_st):
                _scv_exc.append((_n, f"<b>{_sb_esc(_who)}</b> &mdash; {_sb_esc(_st)}: "
                                     f"{_sb_esc(_top['coverage'])} {int(_top['uses'])} of {_n} "
                                     f"(team: {_sb_esc(_scv_main.get(_st, '?'))})"))
        if _scv_exc:
            add('<div class="pc-sub">Defenders who guard it differently</div><ul class="mini">'
                + "".join(f"<li>{t}</li>" for _, t in sorted(_scv_exc, key=lambda x: -x[0])[:5]) + "</ul>")
        add('<p class="mini">' + app_link("Every screen coverage, by defender", page="upcoming",
                                          tab="game_plan", section="screen_coverage") + "</p>")
        add("</div>")

    # CONFIRMED CHANGE (requested: "move all the sections related to the film under 'How the film is watched
    # automatically'"). The film sections (FROM THE FILM: <team>, SELF-SCOUT FROM THE FILM, ON THE COURT) still run
    # here -- later code relies on names they set up -- but their output is collected into _film_html and printed
    # at the end, right after "How the film is watched automatically".
    _sinks.append([])
    # =====================================================================================================
    # FROM THE FILM (requested: every tracking section in the brief, even on a small sample). Rendered from the
    # tracking-insight tables built in the parser; nothing is computed here beyond picking rows. If the
    # upcoming opponent has no tracked film yet, the opponent with the most tracked clips is shown instead and
    # the header says so (TRACK_BRIEF_TEAM overrides the choice).
    # =====================================================================================================
    _tk_clips = _sb_d("uww_trk_clips")
    if not _tk_clips.empty:
        def _tk_is(team, label):
            words = {w for w in re.split(r"[\s\-@()]+", str(label).lower()) if len(w) > 3 and w not in ("titans", "warhawks")}
            return any(w in str(team).lower() for w in words)
        _tk_is_uww = lambda t: "whitewater" in str(t).lower()
        _tk_teams = pd.concat([_tk_clips["offense_team"], _tk_clips["defense_team"]]).astype(str)
        _tk_teams = _tk_teams[~_tk_teams.map(_tk_is_uww)]
        _tk_pick = globals().get("TRACK_BRIEF_TEAM")
        _tk_team = next((t for t in _tk_teams.value_counts().index if _tk_is(t, _tk_pick or short)), None)
        _tk_note = ""
        if _tk_team is None and len(_tk_teams):
            _tk_team = _tk_teams.value_counts().index[0]
            _tk_note = f" -- no tracked film of {OPP_UP} yet, so this shows {_tk_team.upper()}, the most-tracked opponent"
        _tk_rep = _sb_d("uww_tracking_report")
        _tk_check = ""
        if not _tk_rep.empty and "anchor_name_check" in _tk_rep.columns:
            _hits = _tk_rep["anchor_name_check"].astype(str).str.extract(r"(\d+)/(\d+)").dropna().astype(int)
            if len(_hits):
                _tk_check = (f" Name check: tracking named {_hits[0].sum()} of {_hits[1].sum()} known players "
                             f"correctly ({round(100 * _hits[0].sum() / max(_hits[1].sum(), 1))}%).")
        _tk_n = int(((_tk_clips["offense_team"].astype(str) == str(_tk_team)) |
                     (_tk_clips["defense_team"].astype(str) == str(_tk_team))).sum()) if _tk_team else 0

        def _tk_table(df, cols, heads, limit=10):
            if df.empty:
                return '<p class="mini">None found in the tracked clips yet.</p>'
            h = "".join(f'<th style="text-align:left">{_sb_esc(x)}</th>' for x in heads)
            body = ""
            for _, r in df.head(limit).iterrows():
                body += "<tr>" + "".join(f'<td style="text-align:left">{_sb_esc(_sb_clean(r.get(c)))}</td>' for c in cols) + "</tr>"
            more = f'<p class="mini">+{len(df) - limit} more in the app.</p>' if len(df) > limit else ""
            return f'<table class="compact"><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>{more}'

        if _tk_team:
            section(f"\U0001f3a5 FROM THE FILM: {str(_tk_team).upper()}" + footnote(
                f"Built from player tracking on {_tk_n} tracked clip(s){_tk_note}. Names come from Synergy's named "
                f"player + the ball, then appearance matched against the five on the floor.{_tk_check} Coverage marked "
                "* is tracking's own estimate (no coach tag on that clip). Feet are approximate (measured with the "
                "players' own height in the picture). SMALL SAMPLE -- treat every number as a lead to check on film."))
            _D = lambda name, col: (lambda d: d[d[col].astype(str) == str(_tk_team)] if not d.empty and col in d.columns else pd.DataFrame())(_sb_d(name))
            # 1. How their defenders play screens -- laid out like "HOW <OPP> GUARDS SCREENS" (requested): one row per
            #    screen type with its main coverage, then the defenders who guard it differently. One row per screen
            #    (uww_trk_screens), so the two defenders of the same screen aren't counted twice.
            _scr = _D("uww_trk_screens", "defense_team")
            add('<div class="card"><div class="pc-sub">How their defenders play screens</div>')
            if _scr.empty or "screen_type" not in _scr.columns:
                add('<p class="mini">No screens found in the tracked clips yet.</p>')
            else:
                _scr = _scr.assign(_cov=_scr["coverage"].fillna("unclear").astype(str),
                                   _est=_scr.get("coverage_source", pd.Series("", index=_scr.index)).astype(str).eq("tracking estimate"),
                                   _pts=pd.to_numeric(_scr.get("points"), errors="coerce"))
                add('<table class="compact"><thead><tr><th style="text-align:left">Screen</th><th>Tracked</th>'
                    '<th style="text-align:left">Main coverage</th><th>PPP</th><th style="text-align:left">Also</th>'
                    '<th style="text-align:left">Usually by</th></tr></thead><tbody>')
                _film_main = {}
                for _st, _g in sorted(_scr.groupby("screen_type"), key=lambda x: -len(x[1])):
                    _vc = _g.groupby("_cov").agg(n=("_cov", "size"), est=("_est", "mean"), ppp=("_pts", "mean")).sort_values("n", ascending=False)
                    _mc, _mr = _vc.index[0], _vc.iloc[0]
                    _film_main[_st] = _mc
                    _star = "*" if _mr["est"] > 0.5 else ""
                    _also = ", ".join(f"{_sb_esc(c)}{'*' if r_['est'] > 0.5 else ''} {round(100 * r_['n'] / len(_g))}% ({int(r_['n'])})"
                                      for c, r_ in _vc.iloc[1:4].iterrows()) or "&mdash;"
                    _by = _g[_g["_cov"] == _mc]["screened_defender"].dropna().astype(str).value_counts() \
                        if "screened_defender" in _g.columns else pd.Series(dtype=int)
                    _thin = "*" if len(_g) < 5 else ""
                    add(f'<tr><td style="text-align:left">{_sb_esc(_st)}{_thin}</td><td>{len(_g)}</td>'
                        f'<td style="text-align:left"><b>{_sb_esc(_mc)}{_star}</b> {round(100 * _mr["n"] / len(_g))}% ({int(_mr["n"])})</td>'
                        f'<td>{_sb_fmt(_mr["ppp"], 2)}</td><td style="text-align:left">{_also}</td>'
                        f'<td style="text-align:left">{_sb_esc(_by.index[0]) if len(_by) else "&mdash;"}</td></tr>')
                add("</tbody></table>")
                _c = _D("uww_trk_screen_coverage", "defense_team")
                _exc = []
                if not _c.empty and {"defender", "screen_type", "coverage", "times"} <= set(_c.columns):
                    for (_st, _who), _g in _c.groupby(["screen_type", "defender"]):
                        _top = _g.sort_values("times", ascending=False).iloc[0]
                        _n = int(_g["times"].sum())
                        if int(_top["times"]) >= 2 and str(_top["coverage"]) != str(_film_main.get(_st)):
                            _exc.append((_n, f"<b>{_sb_esc(_who)}</b> &mdash; {_sb_esc(_st)}: {_sb_esc(_top['coverage'])} "
                                             f"{int(_top['times'])} of {_n} (team: {_sb_esc(_film_main.get(_st, '?'))})"))
                if _exc:
                    add('<div class="pc-sub">Defenders who guard it differently</div><ul class="mini">'
                        + "".join(f"<li>{t}</li>" for _, t in sorted(_exc, key=lambda x: -x[0])[:5]) + "</ul>")
                add('<p class="mini">* main coverage mostly from tracking\'s own estimate (no coach tag); screen types marked '
                    '* have under 5 tracked. PPP = points on those possessions.</p>')
            add("</div>")
            # 2. Who guards whom -- grouped by the offensive role (BBall Index's 12) of the player being guarded
            #    (requested): for each kind of player, how many possessions and which of their defenders take him.
            _m = _D("uww_trk_matchups", "defense_team")
            _orl = _sb_d("uww_offensive_roles")
            _role_of = ({_norm(p): r for p, r in zip(_orl["player"], _orl["offensive_role"])}
                        if not _orl.empty and {"player", "offensive_role"} <= set(_orl.columns) else {})
            _drl = _sb_d("uww_defensive_roles")
            _drole_of = ({_norm(p): r for p, r in zip(_drl["player"], _drl["defensive_role"])}
                         if not _drl.empty and {"player", "defensive_role"} <= set(_drl.columns) else {})
            add('<div class="card"><div class="pc-sub">Who guards whom, by the kind of player</div>')
            if _m.empty or not {"defender", "guards", "possessions"} <= set(_m.columns):
                add('<p class="mini">None found in the tracked clips yet.</p>')
            else:
                _order = ["Primary Ball Handler", "Secondary Ball Handler", "Shot Creator", "Slasher", "Athletic Finisher",
                          "Off Screen Shooter", "Movement Shooter", "Stationary Shooter", "Versatile Big", "Post Scorer",
                          "Stretch Big", "Roll & Cut Big"]
                _mm = _m.assign(_role=_m["guards"].map(lambda n: _role_of.get(_norm(n), "Role not known yet")),
                                _poss=pd.to_numeric(_m["possessions"], errors="coerce").fillna(0),
                                _ppp=pd.to_numeric(_m.get("ppp"), errors="coerce"))
                add('<table class="compact"><thead><tr><th style="text-align:left">Guarding our&hellip;</th><th>Poss.</th>'
                    '<th style="text-align:left">Their usual defenders (share)</th><th>PPP</th></tr></thead><tbody>')
                for _rl in _order + ["Role not known yet"]:
                    _g = _mm[_mm["_role"] == _rl]
                    if _g.empty or _g["_poss"].sum() <= 0:
                        continue
                    _tot = _g["_poss"].sum()
                    _by = _g.groupby("defender")["_poss"].sum().sort_values(ascending=False)
                    _who = ", ".join(f"{_sb_esc(d)}" + (f" <span class='mini'>({_sb_esc(_drole_of[_norm(d)])})</span>"
                                                       if _drole_of.get(_norm(d)) else "") + f" {round(100 * v / _tot)}%"
                                     for d, v in _by.head(3).items())
                    _ppp = (_g["_ppp"] * _g["_poss"]).sum() / _tot if _g["_ppp"].notna().any() else None
                    add(f'<tr><td style="text-align:left">{_sb_esc(_rl)}s</td><td>{int(round(_tot))}</td>'
                        f'<td style="text-align:left">{_who}</td><td>{_sb_fmt(_ppp, 2) if _ppp is not None else "&mdash;"}</td></tr>')
                add("</tbody></table>")
                add('<p class="mini">Each row: the possessions their defenders spent on players of that offensive role, and '
                    "which defenders took them (with each defender's own defensive role). Names on film are partly best "
                    "guesses until reviewed -- see the Play review.</p>")
            add("</div>")
            # 3. Help tendencies
            _hh = _D("uww_trk_help", "defense_team")
            add('<div class="card"><div class="pc-sub">Help: how far each defender plays off his man (approx ft)</div>'
                + _tk_table(_hh, ["defender", "approx_ft_off_man_weak side", "approx_ft_off_man_ball side",
                                  "approx_ft_off_man_on ball", "tendency", "clips"],
                            ["Defender", "Weak side", "Ball side", "On ball", "Tendency", "Clips"]) + "</div>")
            # 4. Zone and press
            _zp = _D("uww_trk_zone_press", "defense_team")
            if not _zp.empty:
                _z, _p = _zp[_zp["zone"].astype(str) == "True"], _zp[_zp["press"].astype(str) == "True"]
                _zt = (f"Zone on {len(_z)} tracked clip(s)"
                       + (f", spread about {_sb_fmt(pd.to_numeric(_z.get('zone_width_ft_approx'), errors='coerce').mean(), 0)} ft wide and "
                          f"{_sb_fmt(pd.to_numeric(_z.get('zone_depth_ft_approx'), errors='coerce').mean(), 0)} ft deep" if len(_z) else "")
                       + f", {_sb_fmt(pd.to_numeric(_z['points'], errors='coerce').mean(), 2)} PPP. " if len(_z) else "No zone clips tracked. ")
                _trapped = _p[pd.to_numeric(_p.get("trap_frames"), errors="coerce").fillna(0) > 0] if len(_p) else _p
                _pt = (f"Pressed on {len(_p)} clip(s); trapped on {len(_trapped)}"
                       + (f", first trap about {_sb_fmt(pd.to_numeric(_trapped['first_trap_seconds_into_clip'], errors='coerce').mean(), 1)} s into the clip" if len(_trapped) else "")
                       + "." if len(_p) else "No press clips tracked.")
                add(f'<div class="card"><div class="pc-sub">Zone and press</div><p class="mini">{_sb_esc(_zt + _pt)} '
                    'Layouts are drawn in the app.</p></div>')
            # 5. Who screens for whom
            _sp = _D("uww_trk_screen_pairs", "offense_team")
            if not _sp.empty:
                _sp = _sp.assign(after=_sp.apply(lambda r: ", ".join(f"{k} {int(r[c])}" for k, c in
                                                                     (("roll", "rolls"), ("pop", "pops"), ("slip", "slips")) if int(r[c] or 0)) or "--", axis=1))
            add('<div class="card"><div class="pc-sub">Who screens for whom</div>'
                + _tk_table(_sp, ["screener", "screened", "screen_type", "times", "ppp", "after"],
                            ["Screener", "For", "Screen", "Times", "PPP", "Screener after"]) + "</div>")
            # 6. Sets found in the film
            _st = _D("uww_trk_sets", "offense_team")
            if not _st.empty:
                _st = _st.assign(call=_st["most_common_call"].astype(str) + " (" + _st["call_share_pct"].fillna(0).astype(int).astype(str) + "%)")
            add('<div class="card"><div class="pc-sub">Recurring alignments found in the film (diagrams in the app)</div>'
                + _tk_table(_st, ["set_id", "clips", "call", "situations", "ppp"],
                            ["Alignment", "Clips", "Most common tagged call", "Situations", "PPP"]) + "</div>")
            # 7. Inbounds
            _ib = _D("uww_trk_inbounds", "offense_team")
            if not _ib.empty:
                _ib = (_ib.groupby(["situation", "alignment"]).agg(clips=("clip_key", "count"), ppp=("points", "mean"))
                       .reset_index().sort_values("clips", ascending=False))
                _ib["ppp"] = _ib["ppp"].round(2)
            add('<div class="card"><div class="pc-sub">Inbounds alignments</div>'
                + _tk_table(_ib, ["situation", "alignment", "clips", "ppp"], ["Situation", "Alignment", "Clips", "PPP"]) + "</div>")

        # Self-scout: UWW's own coverage execution and spacing
        _ce = _sb_d("uww_trk_coverage_execution")
        _spc = _sb_d("uww_trk_spacing")
        if not _ce.empty or not _spc.empty:
            section("\U0001fa9e SELF-SCOUT FROM THE FILM" + footnote(
                "Our defense: the coverage we played on each tracked screen vs the plan in "
                "staff_inputs/uww_coverage_plan.csv (a template is in staff_input_templates/). Our offense: spacing by "
                "lineup -- average distance to the nearest teammate, how wide the five are, and how often two "
                "teammates (not screening) were within 6 ft. Approximate feet; small sample."))
            if not _ce.empty:
                _ce = _ce.assign(cov=_ce["coverage"].astype(str) + _ce["coverage_source"].map(lambda s: "*" if s == "tracking estimate" else ""))
                add('<div class="card"><div class="pc-sub">Our screen coverage vs the plan</div>'
                    + _tk_table(_ce, ["defender", "role", "screen_type", "cov", "times", "planned", "followed_pct"],
                                ["Our defender", "Role", "Screen", "Coverage", "Times", "Planned", "Followed %"]) + "</div>")
            if not _spc.empty:
                add('<div class="card"><div class="pc-sub">Our spacing by lineup (approx ft)</div>'
                    + _tk_table(_spc, ["lineup", "possessions", "spacing_ft_approx", "width_ft_approx", "crowded_pct", "ppp"],
                                ["Lineup", "Poss.", "Nearest teammate", "Width", "Crowded %", "PPP"], limit=8) + "</div>")
        # =====================================================================================================
        # ON THE COURT (requested: court-mapped information in the brief). Rendered from the court-insight tables;
        # the shot chart and play diagram are drawn here as small PNG pictures (embedded, so they survive email).
        # Half court drawn FastDraw-style: basket at the top, the offense's left on the left.
        # =====================================================================================================
        _cz_rep = _sb_d("uww_court_report")
        if not _cz_rep.empty or not _sb_d("uww_court_shots").empty:
            _team_c = locals().get("_tk_team")
            _cal_rows = _cz_rep[_cz_rep["calibrated"].astype(str) == "False"] if not _cz_rep.empty and "calibrated" in _cz_rep.columns else pd.DataFrame()
            section("\U0001f3c0 ON THE COURT" + (f": {str(_team_c).upper()}" if _team_c else "") + footnote(
                "Positions mapped onto the real court (feet) from the tracked film. Checks: " +
                ("; ".join(f"{r['game']}: {r.get('mapped_pct')}% of frames mapped, calibration error {r.get('calibration_error_ft')} ft"
                           + (f", {int(r['shots_zone_agrees_with_2_or_3_pct'])}% of {int(r['shots_checked'])} shots on the right side "
                              f"of the 3-pt line" if pd.notna(r.get("shots_zone_agrees_with_2_or_3_pct")) else "")
                           for r in _cz_rep[_cz_rep["calibrated"].astype(str) == "True"].to_dict("records")) or "none calibrated yet")
                + ". SMALL SAMPLE."))
            if len(_cal_rows):
                add('<p class="mini">Not on the court yet (gym not calibrated): '
                    + "; ".join(_sb_esc(f"{r['game']} -- open {r['calibration_page']}") for r in _cal_rows.to_dict("records")) + "</p>")

            def _cz_png(shots=None, diagram=None, title=""):
                """Half court (basket at top) as an embedded PNG: shots (green made / red missed) or a play diagram."""
                import base64, io
                from PIL import Image, ImageDraw
                S, W, H = 6, 300, 290
                im = Image.new("RGB", (W, H), (236, 214, 170))
                d = ImageDraw.Draw(im)
                P = lambda hx, hy: (hy * S, hx * S + 4)
                white, ink = (255, 255, 255), (40, 40, 40)
                d.rectangle([P(0, 0), P(47, 50)], outline=white, width=2)
                d.rectangle([P(0, 19), P(19, 31)], outline=white, width=2)
                d.ellipse([P(13, 19), P(25, 31)], outline=white, width=2)
                d.line([P(0, 3.33), P(9.83, 3.33)], fill=white, width=2)
                d.line([P(0, 46.67), P(9.83, 46.67)], fill=white, width=2)
                arc = [P(5.25 + 22.146 * np.cos(a), 25 + 22.146 * np.sin(a)) for a in np.linspace(-1.35, 1.35, 60)]
                d.line(arc, fill=white, width=2)
                d.line([P(4, 22), P(4, 28)], fill=ink, width=2)
                d.ellipse([P(4.5, 24.25), P(6.0, 25.75)], outline=(200, 60, 30), width=2)
                if shots is not None:
                    for _, s_ in shots.iterrows():
                        x, y = P(float(s_["hx"]), float(s_["hy"]))
                        col = (40, 150, 60) if str(s_["made"]) == "True" else (200, 40, 40)
                        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=col, outline=ink)
                if diagram is not None:
                    dg = diagram if isinstance(diagram, dict) else _trk_json.loads(diagram)
                    pos = {}
                    for p_ in dg.get("players", []):
                        pts = [P(hx, hy) for _, hx, hy in p_["path"]]
                        if not pts:
                            continue
                        if p_["side"] == "offense" and p_.get("num"):
                            pos[p_["num"]] = {int(t): P(hx, hy) for t, hx, hy in p_["path"]}
                            if len(pts) > 1:
                                d.line(pts, fill=ink, width=2)
                                (x1, y1), (x2, y2) = pts[-2], pts[-1]
                                ang = np.arctan2(y2 - y1, x2 - x1)
                                d.polygon([(x2, y2), (x2 - 9 * np.cos(ang - 0.4), y2 - 9 * np.sin(ang - 0.4)),
                                           (x2 - 9 * np.cos(ang + 0.4), y2 - 9 * np.sin(ang + 0.4))], fill=ink)
                            x0, y0 = pts[0]
                            d.ellipse([x0 - 8, y0 - 8, x0 + 8, y0 + 8], fill=(255, 255, 255), outline=ink, width=2)
                            d.text((x0 - 3, y0 - 6), str(p_["num"]), fill=ink)
                        elif p_["side"] == "defense":
                            x, y = pts[0]
                            d.line([x - 4, y - 4, x + 4, y + 4], fill=(30, 110, 190), width=2)
                            d.line([x - 4, y + 4, x + 4, y - 4], fill=(30, 110, 190), width=2)
                    for ps in dg.get("passes", []):
                        a, b = pos.get(ps["from"], {}), pos.get(ps["to"], {})
                        if a and b:
                            pa = a[min(a, key=lambda t: abs(t - ps["t"]))]
                            pb = b[min(b, key=lambda t: abs(t - ps["t"]))]
                            for k in range(0, 10, 2):   # dashed pass line
                                d.line([(pa[0] + (pb[0] - pa[0]) * k / 10, pa[1] + (pb[1] - pa[1]) * k / 10),
                                        (pa[0] + (pb[0] - pa[0]) * (k + 1) / 10, pa[1] + (pb[1] - pa[1]) * (k + 1) / 10)], fill=ink, width=2)
                    sc = dg.get("screen")
                    if sc:
                        x, y = P(sc["hx"], sc["hy"])
                        d.line([x - 7, y, x + 7, y], fill=(200, 40, 40), width=3)   # the screen "T"
                        d.line([x, y, x, y - 7], fill=(200, 40, 40), width=3)
                if title:
                    d.text((4, H - 12), title[:48], fill=ink)
                buf = io.BytesIO()
                im.save(buf, "PNG")
                return f'<img src="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}" width="{W}" height="{H}" style="margin:4px"/>'

            _CZ = lambda name, col: (lambda d_: d_[d_[col].astype(str) == str(_team_c)] if _team_c and not d_.empty and col in d_.columns else pd.DataFrame())(_sb_d(name))
            _sh = _CZ("uww_court_shots", "offense_team")
            _zn = _CZ("uww_court_shot_zones", "offense_team")
            if not _sh.empty:
                _zt = _zn[_zn["shooter"] == "TEAM"].sort_values("attempts", ascending=False) if not _zn.empty else pd.DataFrame()
                # only spots that match the play-by-play (a 3 outside the arc, a 2 inside it, ...) -- see _cz_shots
                _n_all = len(_sh)
                if "location_ok" in _sh.columns:
                    _sh = _sh[_sh["location_ok"].astype(str).str.lower() == "true"]
                _aside = _n_all - len(_sh)
                add('<div class="card"><div class="pc-sub">Where they shoot (tracked shots)</div>'
                    + _cz_png(shots=_sh, title=f"{len(_sh)} tracked shots" + (f" ({_aside} set aside)" if _aside else ""))
                    + (f'<p class="mini">{_aside} of {_n_all} tracked shots were left off: the shooter\'s spot on film '
                       "didn't match the shot in the play-by-play (a 3 inside the arc, a 2 outside it, a layup far from "
                       "the rim). They come back as tracking improves.</p>" if _aside else "")
                    + _tk_table(_zt.assign(fg=_zt["makes"].astype(int).astype(str) + "/" + _zt["attempts"].astype(int).astype(str)),
                                ["zone", "fg", "fg_pct", "pts_per_shot"], ["Zone", "Made/Att", "FG%", "Pts/shot"]) + "</div>")
            _scz = _CZ("uww_court_screen_zones", "offense_team")
            if not _scz.empty:
                add('<div class="card"><div class="pc-sub">Where they set screens, and how they were guarded</div>'
                    + _tk_table(_scz.sort_values("screens", ascending=False), ["zone", "screen_type", "coverage", "screens", "ppp"],
                                ["Spot", "Screen", "Coverage", "Screens", "PPP"]) + "</div>")
            _hp = _CZ("uww_court_help", "defense_team")
            if not _hp.empty:
                add('<div class="card"><div class="pc-sub">Their help, on the court: weak-side defenders in the paint</div>'
                    + _tk_table(_hp, ["defender", "weak_side_in_paint_pct", "weak_side_ft_off_man", "on_ball_ft", "clips"],
                                ["Defender", "Weak side in paint %", "Weak side ft off man", "On-ball ft", "Clips"]) + "</div>")
            _zc = _CZ("uww_court_zone_press", "defense_team")
            if not _zc.empty:
                _al = _zc["alignment"].dropna().value_counts() if "alignment" in _zc.columns else pd.Series(dtype=int)
                _tp = _zc["trap_spot"].dropna().value_counts() if "trap_spot" in _zc.columns else pd.Series(dtype=int)
                add('<div class="card"><div class="pc-sub">Zone alignment and trap spots (court)</div><p class="mini">'
                    + _sb_esc(("Zone read from the court: " + ", ".join(f"{a} x{n}" for a, n in _al.items()) + ". ") if len(_al) else "No zone clips on the court. ")
                    + _sb_esc(("Traps: " + ", ".join(f"{a} x{n}" for a, n in _tp.items()) + ".") if len(_tp) else "No traps on the court.") + "</p></div>")
            _sets_c = _tk_team and _sb_d("uww_trk_sets")
            _dg = _sb_d("uww_court_diagrams")
            if isinstance(_sets_c, pd.DataFrame) and not _sets_c.empty and not _dg.empty:
                _sets_c = _sets_c[_sets_c["offense_team"].astype(str) == str(_team_c)].sort_values("clips", ascending=False).head(2)
                pics = ""
                for _, s_ in _sets_c.iterrows():
                    hit = _dg[_dg["clip_key"] == s_["example_clip"]]
                    if len(hit):
                        pics += _cz_png(diagram=hit.iloc[0]["diagram"], title=f"{s_['set_id']} ({int(s_['clips'])} clips)")
                if pics:
                    add('<div class="card"><div class="pc-sub">Their most common alignments, drawn from a real possession '
                        '(numbers = offense, x = defense, dashed = pass, red T = screen)</div>' + pics + "</div>")
            _spc_c = _sb_d("uww_court_spacing")
            if not _spc_c.empty:
                add('<div class="card"><div class="pc-sub">Self-scout on the court: our spacing by lineup</div>'
                    + _tk_table(_spc_c, ["lineup", "possessions", "both_corners_pct", "paint_crowded_pct", "spacing_ft", "ppp"],
                                ["Lineup", "Poss.", "Both corners filled %", "Paint crowded %", "Nearest teammate ft", "PPP"], limit=8) + "</div>")

        add('<p class="mini">' + app_link("Film tracking: diagrams, possession replays, search by player", page="upcoming",
                                          tab="game_plan", section="film_tracking") + "</p>")

    _film_html = _sinks.pop()                        # the film sections, printed at the end (see above)

    # =====================================================================================================
    # WHAT TO PLAY THEM IN -- everything here is only possible now that offense AND defense are tagged on
    # the same possession. It answers the questions a staff argues about BEFORE anyone watches film.
    #
    # In opponent_plays.csv the tagged defense is the defense the OPPONENT FACED, so these read as "how
    # Aurora's offense did against X", not "what Aurora plays on defense" (that's DEFENSE TYPE BY SITUATION
    # further down). Everything aggregates at defense FAMILY level (man / zone / press), not specific
    # coverage: with ~120 tagged possessions a specific set against a specific coverage is 2-3 clips, which
    # is noise. Clip counts are printed on every row so nobody reads a percentage off a sample of three.
    # =====================================================================================================
    _pf_opp = _pf_clips("Opponent", short)
    _pf_uww = _pf_clips("UWW")
    _pf_any = (not _pf_opp.empty) or (not _pf_uww.empty)

    if _pf_any:
        page_break()
        section(f"\U0001f3af WHAT TO PLAY {OPP_UP} IN" + footnote(
            "Every row here is the defense the opponent's offense FACED on a tagged possession, so it reads "
            "as how they did against that look -- not what they run on defense themselves. Man, Zone and "
            "Press are families, not specific coverages: at this sample size a named coverage is a handful "
            "of clips. PPP is points per tagged possession. Treat these as things to CONFIRM on film, not "
            "as settled reads -- the clip count on each row is how much weight it carries."))
        add('<div class="card">')

        # ---- 1+2. Each defense, AND whether pressing is worth it -- one table ----------------------
        # These used to be two tables, and the second ("Do they handle pressure") repeated the Press row
        # of the first (requested: combine). Press is already a row here; the only thing the second table
        # added was the turnover-rate COMPARISON against not being pressed, so that is now a sentence under
        # the table instead of its own grid.
        #
        # Their columns and ours are grouped under two labelled header bands (requested: make it clear which
        # columns are OUR defense) -- a bare "We allow" sitting next to "PPP" was easy to read as theirs.
        if not _pf_opp.empty:
            _base = _ppp_of(_pf_opp)
            _ours = pd.DataFrame()
            if not _pcc_all.empty and "defense_played" in _pcc_all.columns:
                _ours = _pcc_all[(_pcc_all["side"] == "UWW")
                                 & (_pcc_all["decode_quality"] != "Needs review")
                                 & _pcc_all["defense_played"].notna()].copy()
                if not _ours.empty:
                    _ours["_pts"] = pd.to_numeric(_ours.get("points"), errors="coerce")
                    _ores = _ours["result"].astype(str).str.lower() if "result" in _ours.columns \
                        else pd.Series("", index=_ours.index)
                    _ours["_to"] = _ores.str.contains("turnover|violation|kicked", regex=True)
                    _ours["_fam"] = _ours.apply(
                        lambda r: "Press" if bool(r.get("press_played")) else
                        ("Zone" if "zone" in str(r.get("defense_played") or "").lower() else
                         ("Man" if "man" in str(r.get("defense_played") or "").lower() else "")), axis=1)
                    _ours = _ours[_ours["_fam"] != ""]
            _have_ours = not _ours.empty

            add('<div class="tier-h">How they score against each defense</div>')
            add('<table class="compact dfam"><thead>'
                '<tr class="dfam-band"><th></th>'
                f'<th colspan="4" class="band-them">{_sb_esc(OPP_UP)} OFFENSE vs this defense</th>'
                + ('<th colspan="3" class="band-us">OUR DEFENSE when we play it</th>' if _have_ours else "")
                + '<th></th></tr>'
                '<tr><th style="text-align:left">Defense</th>'
                '<th class="band-them">Poss</th><th class="band-them">PPP</th>'
                '<th class="band-them">FG%</th><th class="band-them">TO%</th>'
                + ('<th class="band-us">Poss</th><th class="band-us">PPP allowed</th>'
                   '<th class="band-us">TO% forced</th>' if _have_ours else "")
                + '<th style="text-align:left">What they went to most</th>'
                "</tr></thead><tbody>")
            _fam_rows = []
            for _fam, _g in _pf_opp.groupby("_fam"):
                if len(_g) < _DEF_FAMILY_MIN:
                    continue
                _fam_rows.append((_fam, _g, _ppp_of(_g)))
            # Fixed order so Press is always last and reads as "and when you pressure them".
            _order = {"Man": 0, "Zone": 1, "Press": 2}
            for _fam, _g, _p in sorted(_fam_rows, key=lambda x: (_order.get(x[0], 9), -len(x[1]))):
                _fga, _fgm = int(_g["_fga"].sum()), int(_g["_fgm"].sum())
                _top = ""
                if "play_series" in _g.columns and _g["play_series"].notna().any():
                    _tc = _g["play_series"].dropna().astype(str).value_counts()
                    if len(_tc):
                        _top = f"{_tc.index[0]} ({int(_tc.iloc[0])}x)"
                _ours_cells = ""
                if _have_ours:
                    _og = _ours[_ours["_fam"] == _fam]
                    if len(_og):
                        _op = _ppp_of(_og)
                        _ours_cells = (f'<td class="band-us">{len(_og)}</td>'
                                       f'<td class="band-us">{_sb_fmt(_op, 2) if _op is not None else "--"}</td>'
                                       f'<td class="band-us">{_sb_fmt(100 * _og["_to"].sum() / len(_og), 1)}</td>')
                    else:
                        _ours_cells = '<td class="band-us" colspan="3"><span class="mini">not run yet</span></td>'
                add(f'<tr class="serrow"><td class="wrap">{_sb_esc(_fam)}</td>'
                    f'<td class="band-them">{len(_g)}</td>'
                    f'<td class="band-them {_ppp_cls(_p, _base)}">{_sb_fmt(_p, 2)}</td>'
                    f'<td class="band-them">{_sb_fmt(100 * _fgm / _fga, 1) if _fga else "--"}</td>'
                    f'<td class="band-them">{_sb_fmt(100 * _g["_to"].sum() / len(_g), 1)}</td>'
                    + _ours_cells
                    + f'<td class="wrap mini">{_sb_esc(_top)}</td></tr>')
            if not _fam_rows:
                add(f'<tr><td colspan="{9 if _have_ours else 6}" class="mini">No defense family has reached '
                    f'{_DEF_FAMILY_MIN} tagged possessions yet.</td></tr>')
            add("</tbody></table>")

            _notes = []
            if _fam_rows:
                _best = min(_fam_rows, key=lambda x: (x[2] if x[2] is not None else 9))
                _worst = max(_fam_rows, key=lambda x: (x[2] if x[2] is not None else -9))
                if _best[0] != _worst[0] and _best[2] is not None and _worst[2] is not None:
                    _notes.append(f"They struggle most against <strong>{_sb_esc(_best[0])}</strong> "
                                  f"({_sb_fmt(_best[2], 2)} PPP on {len(_best[1])}) and hurt you most against "
                                  f"<strong>{_sb_esc(_worst[0])}</strong> ({_sb_fmt(_worst[2], 2)} PPP on "
                                  f"{len(_worst[1])}).")
            # The pressure verdict -- what the separate table used to say, in one line.
            if "press_faced" in _pf_opp.columns:
                _pressed = _pf_opp[_pf_opp["press_faced"].astype(bool)]
                _unpressed = _pf_opp[~_pf_opp["press_faced"].astype(bool)]
                if len(_pressed) >= _DEF_FAMILY_MIN and len(_unpressed) >= _DEF_FAMILY_MIN:
                    _to_p = 100 * _pressed["_to"].sum() / len(_pressed)
                    _to_u = 100 * _unpressed["_to"].sum() / len(_unpressed)
                    _forms = (_pressed["press_formation_faced"].dropna().astype(str).value_counts()
                              if "press_formation_faced" in _pressed.columns else pd.Series(dtype=int))
                    _notes.append(
                        f"<strong>Pressure</strong> moves their turnover rate {_to_p - _to_u:+.1f} points "
                        f"({_to_u:.1f}% unpressed \u2192 {_to_p:.1f}% pressed) \u2014 "
                        + ("worth pressing." if _to_p - _to_u >= 5 else "not enough to be worth the risk.")
                        + (f" Presses seen: {_sb_esc(', '.join(_forms.index[:3]))}." if len(_forms) else ""))
            for _n in _notes:
                add(f'<p class="strip-line">{_n}</p>')

        # ---- 3. Counters: what a coverage change makes them do ------------------------------------
        if not _pf_opp.empty and "coverage_faced" in _pf_opp.columns:
            _cov = _pf_opp[_sb_has_text(_pf_opp["coverage_faced"])]
            if not _cov.empty:
                _cov_rows = []
                for _cname, _g in _cov.groupby(_cov["coverage_faced"].astype(str)):
                    if len(_g) < _DEF_SPLIT_MIN:
                        continue
                    _went = ""
                    if "play_call" in _g.columns and _g["play_call"].notna().any():
                        _wc = _g["play_call"].dropna().astype(str)
                        _wc = _wc[~_wc.str.contains("unspecified", na=False)].value_counts()
                        if len(_wc):
                            _went = ", ".join(f"{n} ({int(c)}x)" for n, c in _wc.head(2).items())
                    _cov_rows.append((_cname, _g, _ppp_of(_g), _went))
                if _cov_rows:
                    _cbase = _ppp_of(_cov)
                    add('<div class="tier-h">When you change the coverage, what do they go to</div>')
                    add('<table class="compact"><thead><tr><th style="text-align:left">Coverage they saw</th>'
                        '<th>Poss</th><th>PPP</th><th style="text-align:left">What they called</th>'
                        "</tr></thead><tbody>")
                    for _cname, _g, _p, _went in sorted(_cov_rows, key=lambda x: -len(x[1])):
                        add(f'<tr class="serrow"><td class="wrap">{_sb_esc(_cname)}</td><td>{len(_g)}</td>'
                            f'<td class="{_ppp_cls(_p, _cbase)}">{_sb_fmt(_p, 2)}</td>'
                            f'<td class="wrap mini">{_sb_esc(_went)}</td></tr>')
                    add("</tbody></table>")

        # ---- 4. Personnel x defense: moved into the opponent Player Notes (DEF_SPLIT_RULES, above the
        # roster) -- only players whose gap is large enough get a line.

        # ---- 5. Confirm on film -------------------------------------------------------------------
        # The brief's job before film is to hand over HYPOTHESES to confirm, not conclusions. Ordered by
        # how much the claim would change the plan, with the clip count behind each one stated.
        _checks = []
        if not _pf_opp.empty:
            _fams = {f: g for f, g in _pf_opp.groupby("_fam") if len(g) >= _DEF_FAMILY_MIN}
            if len(_fams) >= 2:
                _ranked = sorted(_fams.items(), key=lambda kv: (_ppp_of(kv[1]) or 9))
                _b, _w = _ranked[0], _ranked[-1]
                _checks.append((abs((_ppp_of(_w[1]) or 0) - (_ppp_of(_b[1]) or 0)),
                                f"They score {_sb_fmt(_ppp_of(_b[1]), 2)} PPP against {_b[0]} vs "
                                f"{_sb_fmt(_ppp_of(_w[1]), 2)} against {_w[0]} \u2014 watch whether that's the "
                                f"defense or just shot-making.", len(_b[1]) + len(_w[1])))
            _pr = _pf_opp[_pf_opp["press_faced"].astype(bool)] if "press_faced" in _pf_opp.columns else pd.DataFrame()
            if len(_pr) >= _DEF_FAMILY_MIN:
                _rest = _pf_opp[~_pf_opp["press_faced"].astype(bool)]
                if len(_rest):
                    _d = 100 * _pr["_to"].sum() / len(_pr) - 100 * _rest["_to"].sum() / len(_rest)
                    _checks.append((abs(_d) / 10,
                                    f"Their turnover rate moves {_d:+.1f} points under pressure \u2014 check "
                                    f"who is actually bringing it up and whether they have a second handler.",
                                    len(_pr)))
        if not _pf_uww.empty:
            _ufams = {f: g for f, g in _pf_uww.groupby("_fam") if len(g) >= _DEF_FAMILY_MIN}
            if len(_ufams) >= 2:
                _ur = sorted(_ufams.items(), key=lambda kv: -(_ppp_of(kv[1]) or 0))
                _checks.append((abs((_ppp_of(_ur[0][1]) or 0) - (_ppp_of(_ur[-1][1]) or 0)),
                                f"Our own offense scores best against {_ur[0][0]} "
                                f"({_sb_fmt(_ppp_of(_ur[0][1]), 2)} PPP) \u2014 confirm they'll actually show "
                                f"it before building around it.", len(_ur[0][1])))
        if _checks:
            add('<div class="tier-h">Confirm these on film</div>')
            add('<ul class="bl">')
            for _w8, _text, _n in sorted(_checks, key=lambda x: -x[0])[:5]:
                add(f'<li>{_sb_esc(_text)} <span class="mini">({_n} tagged possessions)</span></li>')
            add("</ul>")
        add("</div>")




    # =====================================================================================================
    # HOW THEY RUN OFFENSE -- the quadrant view, built for the defensive side of the ball. Replaced an
    # other side of the ball. The axes are the same (how often x how well), but the QUESTION flips: on our
    # own sets the answer is "call it more / stop calling it", which is meaningless for an opponent we
    # don't coach. Here the same two axes answer "what do we have to take away, and what can we live with",
    # so the quadrant names, the ordering and the per-row detail are all defensive. The scary cell is
    # low-usage / high-efficiency -- the thing they don't run often enough to have shown up on film, which
    # is exactly what beats an under-prepared defense.
    # =====================================================================================================
    def offense_section_test2(side, title):
        sm = _offense_rows(side)
        if sm.empty:
            return
        calls = sm[(sm["level"] == "Play call")
                   & ~sm["name"].astype(str).str.contains("unspecified", na=False)].copy()
        if calls.empty:
            return
        calls["_uses"] = pd.to_numeric(calls["uses"], errors="coerce").fillna(0)
        calls["_ppp"] = pd.to_numeric(calls["ppp"], errors="coerce")
        _QSHOW = 3     # plays listed per quadrant; the rest collapse to "+ N more"
        _QMIN = 2      # lower than our own side: a set they ran twice and scored on is still a warning
        _rated = calls[(calls["_uses"] >= _QMIN) & calls["_ppp"].notna()]
        if _rated.empty:
            return
        team_ppp = calls["team_ppp"].dropna().iloc[0] if calls["team_ppp"].notna().any() else _rated["_ppp"].mean()
        _use_cut = _rated["_uses"].median()
        _meta_df, _meta_sample = staff_rows("uww_opp_sets")
        _meta = {_norm(r["set_name"]): r for _, r in _meta_df.iterrows()} if not _meta_df.empty else {}
        _film = _film_clip_lookup() if side == "Opponent" else {}

        section(title + footnote(
            "Same tagged possessions as the sections above, sorted by how often they run a set against how "
            f"well it scores. The usage line is the median ({_use_cut:.0f} uses) and the efficiency line is "
            f"their own average ({team_ppp:.2f} PPP), so this is relative to them, not to the league. Sets "
            f"with fewer than {_QMIN} tagged possessions are left out. \"Haven't seen it enough\" is the "
            "cell to read twice: those are efficient looks with a thin sample, which is what beats a "
            "defense that only prepared for the obvious."))
        add('<div class="card">')

        _quads = [
            ("Take this away", "They run it a lot and it works", "q-bad",
             lambda r: r["_uses"] >= _use_cut and r["_ppp"] >= team_ppp, "ppp"),
            ("Haven't seen it enough", "Efficient, but thin sample \u2014 don't get surprised", "q-up",
             lambda r: r["_uses"] < _use_cut and r["_ppp"] >= team_ppp, "ppp"),
            # Sorted by USAGE, not PPP: the point of this cell is "they keep going to it and it doesn't
            # work", so their most-run sets lead. Sorting by PPP here put the least-bad sets first and cut
            # their two most-run sets (4-1 Ball Screen, OK State Pat Miller) off the bottom.
            ("Make them keep running it", "They go to it often and it doesn't score", "q-good",
             lambda r: r["_uses"] >= _use_cut and r["_ppp"] < team_ppp, "uses"),
            ("Live with it", "Rare and ineffective \u2014 don't spend practice on it", "q-dim",
             lambda r: r["_uses"] < _use_cut and r["_ppp"] < team_ppp, "ppp"),
        ]
        add('<div class="quad">')
        for _qname, _qsub, _qcls, _test, _sort in _quads:
            # Most dangerous first by default; "Make them keep running it" leads with what they run most.
            _order = ["_uses", "_ppp"] if _sort == "uses" else ["_ppp", "_uses"]
            _rows = _rated[_rated.apply(_test, axis=1)].sort_values(_order, ascending=[False, False])
            add(f'<div class="quad-cell {_qcls}">'
                f'<div class="quad-h">{_sb_esc(_qname)}<span class="quad-n">{len(_rows)}</span></div>'
                f'<div class="quad-sub">{_sb_esc(_qsub)}</div>')
            if _rows.empty:
                add('<div class="quad-empty">Nothing here yet.</div>')
            for _, r in _rows.head(_QSHOW).iterrows():
                # Defensive detail: who finishes it, where it happens, and our coverage call -- the three
                # things a defender needs. (Our own version showed "best vs defense", which is an offensive
                # read and has no meaning for a team we don't call plays for.)
                _who = _sb_clean(r.get("top_player"))
                _where = _sb_clean(r.get("top_location"))
                _m = _meta.get(_norm(r["name"]))
                _cov = _sb_clean(_m.get("our_call")) if _m is not None else ""
                _cn = _film.get(_norm(r["name"]))
                _meta_bits = " &middot; ".join(x for x in (_who, _where) if x)
                add(f'<div class="quad-row"><span class="quad-set">{_sb_esc(_sb_clean(r["name"]))}</span>'
                    + (f' <span class="mini">\U0001f3ac {_cn}</span>' if _cn else "")
                    + f'<span class="quad-num">{r["_ppp"]:.2f} PPP<span class="mini"> in {int(r["_uses"])} possession{"" if int(r["_uses"]) == 1 else "s"}</span></span>'
                    + (f'<div class="quad-meta">{_sb_esc(_meta_bits)}</div>' if _meta_bits else "")
                    + (f'<div class="quad-cov">{_sb_esc(_cov)}</div>' if _cov else "")
                    + "</div>")
            if len(_rows) > _QSHOW:
                add(f'<div class="quad-more">+ {len(_rows) - _QSHOW} more</div>')
            add("</div>")
        add("</div>")
        if _meta_sample:
            add('<p class="mini">Coverage calls are a generated placeholder until '
                'staff_inputs/opp_sets.csv exists.</p>')
        add('<p class="mini">' + app_link("Every set, clip and spot", page="upcoming", tab="game_plan",
                                          section=f"play_calls_{side.lower()}") + "</p>")
        add("</div>")

    offense_section_test2("Opponent", f"\U0001f3ac HOW {OPP_UP} RUNS OFFENSE")

    # ---- sections that need tagging or staff input (kept, laid out two-up) ---------------------------------
    # Only real rows reach these tables now (sample rows are dropped at load), so the section prints only
    # when at least one of them has something to show.
    def _staff_input_tables():
        # THEIR DEFENSE & HOW WE ATTACK IT, DEFENSE TYPE BY SITUATION and BALL SCREEN COVERAGE moved out of
        # this block: they are real now (defense tagging) and all three are combined into "What they will play
        # against us" at the top of HOW WE RUN OFFENSE. The tables are still exported for the app.
        # HELP & ROTATION removed from the brief (requested) -- still built and shown in the app's Game Plan tab.
        # MATCHUP HISTORY removed from the brief (requested) -- still exported for the app.
        staff_table("uww_play_counters", "\U0001f504 WHEN WE TAKE AWAY THEIR SET",
                    [("set", "Set"), ("their_counter", "Their counter"), ("our_adjustment", "Our adjustment")],
                    "A title captures one action, not a sequence.",
                    note="Counters: tag a second clip when a denied action leads into another, linked to the first clip's "
                         "number. Value: High, but hardest to tag consistently -- a season-two addition.")
        if ROSTER_LAYOUT != "stacked":   # stacked roster carries a real per-player shot line instead
            staff_table("uww_opp_shot_zones", "\U0001f3af SHOT LOCATIONS \u2014 TOP FIVE",
                    [("player", "Player"), ("rim", "Rim"), ("paint_non_rim", "Paint"), ("midrange", "Mid"),
                     ("corner_3", "C3"), ("above_break_3", "AB3")],
                    "Three-point share is real; the zone split is a placeholder.",
                    note="Shot locations: tag a zone (rim / paint / mid / corner 3 / above-break 3) on every shot. The decoder "
                         "reads some spots from titles (\"LW 3\") but never for twos. Value: High.")
        staff_table("uww_opp_tendencies", "\U0001f3c3 TRANSITION, GLASS &amp; BENCH",
                    [("item", "Area"), ("detail", "What they do")],
                    "Placeholders (staff_inputs/opp_tendencies.csv).",
                    note="Transition/glass/bench: tag \"Transition\" as its own situation (Early clock is only a rough "
                         "stand-in); glass crashers need a rebounder tag; timeouts and officials aren't in the play-by-play. "
                         "Value: Medium.")
        # REBOUND TENDENCIES removed as a section (requested). The full table stays in the app; the brief
        # carries rebounding only when it's lopsided -- a Keys to Victory key (built in the KTV cell), a Bottom
        # Line sentence, and a roster read on the player doing the crashing. Rules: REBOUND_RULES.
        staff_table("uww_shot_quality_by_contest", "\U0001f3af SHOT QUALITY BY CONTEST",
                    [("contest_level", "Contest"), ("freq_pct", "%"), ("fg_pct", "FG%")],
                    "Contest level isn't tagged beyond Synergy's guarded/open.",
                    note="Shot quality: tag wide open / open / contested / tightly contested on every shot. Value: Medium.")
        staff_table("uww_double_team_tendencies", "\U0001f465 DOUBLE-TEAMS",
                    [("trigger", "Trigger"), ("from_where", "From"), ("escape_read", "Escape")],
                    "Double teams aren't tagged.",
                    note="Double teams: tag when one occurs, from where, and the read. Value: Medium, narrow scope.")
        staff_table("uww_offball_screen_navigation", "\U0001f504 OFF-BALL SCREEN NAVIGATION",
                    [("screen_type", "Screen"), ("technique", "Technique"), ("freq_pct", "%")],
                    "Off-ball screen technique isn't tagged.",
                    note="Off-ball screens: tag over/under/switch/fight-through on down screens, pin downs and staggers. "
                         "Value: Medium-to-low; pairs with Ball Screen Coverage.")

    _staff_html = capture(_staff_input_tables)
    if _staff_html:
        page_break()
        section("\U0001f52c NEEDS TAGGING OR STAFF INPUT" + footnote(
            "Each section's own \u24d8 note says what to tag and how much it would add. Controlled vocabulary for "
            "play titles: every title decoded correctly only because the decoder absorbs spelling variance "
            "(\"Blob-Box-Curl\" vs \"BLOB- Box- Curl\"); a dropdown or autocomplete built from the playbook "
            "would remove that fragility. Value: process, not new data."))
        add('<div class="flow2">')
        add("".join(_staff_html))
        add("</div>")

    # =====================================================================================================
    # UW-WHITEWATER -- mirrors the opponent section
    # =====================================================================================================
    _uww_stats = players_for("uww_pbp_box_score", _SB_UWW)
    personnel_pages("UWW", "UW-WHITEWATER", _uww_stats, uww_card, break_first=True,
                    lead=lambda: divider("UW-WHITEWATER", "Our own personnel, offense and week"))

    page_break()
    # MATCHUPS removed from the brief (requested) -- still built and shown in the app's Game Plan tab.
    _uww_lu = _sb_d("uww_uww_lineup_season")
    if not _uww_lu.empty:
        section("\U0001f501 OUR TOP LINEUPS & 3-MAN COMBOS" + footnote(
            "Our best three five-man units and best three 3-man combos this season, from the play-by-play's "
            "lineup stints, ranked by scoring margin per 40 minutes shrunk toward zero as if "
            f"{LINEUP_TABLE_RULES['shrink_minutes']:.0f} minutes of an even game were added. Competitive "
            "minutes only: MIN and +/- leave out stints that start in the 2nd half or later with the margin "
            "already lopsided. A five-man unit needs "
            f"{LINEUP_TABLE_RULES['five_min_minutes']:.0f}+ minutes; a combo meets the same bar as the "
            f"\"Feature the ... combo\" key ({LINEUP_TABLE_RULES['uww_three_min_minutes']:.0f}+ minutes, "
            f"{LINEUP_TABLE_RULES['uww_three_min_games']}+ games, better with them on than off), so that "
            "combo is the top row. * marks a unit shown below the bar because fewer than three cleared it. "
            "PPP is offense only, from tagged possessions, and does not affect the order."))
        add('<div class="card">')
        lineups_table(_uww_lu, "UWW", note_rows=False)
        _combo_html = capture(combos_table, "UWW")
        if _combo_html:
            add('<div class="pc-sub">Top 3-man combos</div>')
            add("".join(_combo_html))
        add('<p class="mini">' + app_link("All of our lineups and combos", page="upcoming", tab="stats",
                                          section="uww_lineups") + "</p></div>")

    # =====================================================================================================
    # HOW WE RUN OFFENSE -- the same quadrant idea as the opponent's section above, but the question flips:
    # table and the bar layout used for the opponent. Scouting THEM is about recognition ("what are they
    # about to run"); scouting OURSELVES is a different question -- what should we call more, and what
    # should we stop calling. So this one drops the situation-by-situation structure entirely and sorts
    # every set into a usage x efficiency quadrant, which turns the table into a decision instead of a
    # reference. Cut whichever of the three loses.
    # =====================================================================================================
    def offense_section_test_uww(side, title):
        sm = _offense_rows(side)
        if sm.empty:
            return
        calls = sm[(sm["level"] == "Play call")
                   & ~sm["name"].astype(str).str.contains("unspecified", na=False)].copy()
        if calls.empty:
            return
        calls["_uses"] = pd.to_numeric(calls["uses"], errors="coerce").fillna(0)
        calls["_ppp"] = pd.to_numeric(calls["ppp"], errors="coerce")
        # A set needs enough reps for its PPP to mean anything before it can be told to call it more or less.
        _QMIN = 3
        _QSHOW = 3     # sets listed per quadrant; the rest collapse to "+ N more"
        _rated = calls[(calls["_uses"] >= _QMIN) & calls["_ppp"].notna()]
        if _rated.empty:
            return
        team_ppp = calls["team_ppp"].dropna().iloc[0] if calls["team_ppp"].notna().any() else _rated["_ppp"].mean()
        # Split on the median so the quadrants always have something in them -- a fixed usage cutoff would
        # empty out early in the season and overflow late.
        _use_cut = _rated["_uses"].median()

        r_uses_cut = _use_cut

        def _q_context(set_name):
            """The four things a coach asked for on every quadrant row, each computed from that set's own
            clips: who finishes it (and how often, so "Jake Quast" can't be misread as a recommendation),
            which personnel group and clock window it lives in, and WHY it landed in this quadrant --
            shooting, turnovers, or simply how rarely we call it."""
            blank = {"who": "", "lineup": "", "clock": "", "driver": "", "unit": ""}
            if _pcc_all.empty or "play_call" not in _pcc_all.columns:
                return blank
            d = _pcc_all[(_pcc_all["side"] == side)
                        & (_pcc_all["play_call"].astype(str) == str(set_name))
                        & (_pcc_all["decode_quality"] != "Needs review")].copy()
            if "possession_side" in d.columns:
                d = d[d["possession_side"].astype(str) != "Defense"]
            if d.empty:
                return blank
            n = len(d)
            d["_pts"] = pd.to_numeric(d.get("points"), errors="coerce")
            _res = d["result"].astype(str).str.lower() if "result" in d.columns else pd.Series("", index=d.index)
            d["_to"] = _res.str.contains("turnover|violation|kicked", regex=True)
            d["_fga"] = _res.str.startswith(("make", "miss")) & _res.str.contains("2|3", regex=True)
            d["_fgm"] = _res.str.startswith("make") & _res.str.contains("2|3", regex=True)
            out = dict(blank)

            # WHO -- stated as observed usage, never as a recommendation.
            if "player" in d.columns and d["player"].notna().any():
                _vc = d["player"].dropna().astype(str).value_counts()
                if len(_vc):
                    out["who"] = f"Finished by {_sb_title(_vc.index[0])} on {int(_vc.iloc[0])} of {n}"

            def _ppp_txt(g):
                k = g["_pts"].notna().sum()
                return f"{g['_pts'].sum() / k:.2f}" if k else "--"

            def _split_best(col, label_fmt):
                """Best- and worst-scoring bucket of a split, WITH what the split doesn't cover.

                Personnel and shot clock only exist on clips matched to a play-by-play event, so a split
                usually covers only part of the set's possessions. Without saying so, "worst 1.43" could sit
                above the set's 1.30 -- because the low-scoring possessions were the ones left out. So every
                bucket carries its count, and the uncovered remainder is stated with its own PPP; the pieces
                then reconcile with the number in the header."""
                if col not in d.columns:
                    return ""
                has = d[_sb_has_text(d[col])]
                rest = d.drop(has.index)
                _rest_txt = (f" &middot; {len(rest)} with no {'personnel' if 'personnel' in col else 'clock'} "
                             f"read (no play-by-play match) \u2014 {_ppp_txt(rest)}" if len(rest) else "")
                if has.empty:
                    return (f"No {'personnel' if 'personnel' in col else 'clock'} read on any of the {n} "
                            "(none matched to the play-by-play)")
                agg = has.groupby(has[col].astype(str)).agg(
                    n=("_pts", "size"), pts=("_pts", "sum"), known=("_pts", lambda x: x.notna().sum()))
                agg["ppp"] = agg["pts"] / agg["known"].replace(0, pd.NA)
                agg = agg.dropna(subset=["ppp"]).sort_values("ppp", ascending=False)
                if agg.empty:
                    return ""
                _top = agg.iloc[0]
                if len(agg) == 1:
                    return (label_fmt.format(kind="All", name=agg.index[0], ppp=_top["ppp"], n=int(_top["n"]))
                            + _rest_txt)
                _bot = agg.iloc[-1]
                return (label_fmt.format(kind="Best", name=agg.index[0], ppp=_top["ppp"], n=int(_top["n"]))
                        + f" &middot; worst {_bot.name} \u2014 {_bot['ppp']:.2f} ({int(_bot['n'])})" + _rest_txt)

            out["lineup"] = _split_best("personnel_grouping_type",
                                        "{kind} in {name} \u2014 {ppp:.2f} ({n})")
            out["clock"] = _split_best("shot_clock_situation",
                                       "{kind} on {name} \u2014 {ppp:.2f} ({n})")

            # UNIT -- the five- or three-man group it runs with most. on_court_lineup is a full five;
            # trimmed to three names so it fits a quadrant cell without wrapping to four lines.
            if "on_court_lineup" in d.columns and d["on_court_lineup"].notna().any():
                _lu = d["on_court_lineup"].dropna().astype(str).value_counts()
                if len(_lu) and int(_lu.iloc[0]) >= 2:
                    _names = [x.strip() for x in re.split(r"[,/|]", _lu.index[0]) if x.strip()]
                    _trio = ", ".join(_sb_title(x) for x in _names[:3])
                    out["unit"] = (f"Most with {_trio}"
                                   + (f" +{len(_names) - 3}" if len(_names) > 3 else "")
                                   + f" ({int(_lu.iloc[0])}x)")

            # HOW -- every possession and every point, so the header's PPP is explained, not asserted.
            # (It replaced a WHY line that only described the possessions that ended in a shot -- 6 of 11 in
            # the case that prompted this -- leaving fouls, turnovers and resets, and their points, invisible.)
            # Points include free throws: a possession that ends in a shooting foul scores at the line.
            def _outcome(r):
                t = str(r or "").lower()
                if t.startswith("make 3"):
                    return "made 3"
                if t.startswith("make"):
                    return "made 2"
                if t.startswith("miss"):
                    return "missed shot"
                if "turnover" in t:
                    return "turnover"
                if t in ("foul", "free throw", "1 pts", "0 pts") or "free throw" in t:
                    return "fouled"
                return "no shot"          # non-shooting foul, kicked ball, no violation, reset
            d["_out"] = d["result"].map(_outcome) if "result" in d.columns else "no shot"
            _order = ["made 3", "made 2", "fouled", "missed shot", "turnover", "no shot"]
            _labels = {"made 3": ("made three", "made threes"), "made 2": ("made two", "made twos"),
                       "fouled": ("fouled", "fouled"), "missed shot": ("missed shot", "missed shots"),
                       "turnover": ("turnover", "turnovers"),
                       "no shot": ("reset / non-shooting foul", "resets / non-shooting fouls")}
            _parts = []
            for _o in _order:
                _g = d[d["_out"] == _o]
                if _g.empty:
                    continue
                _k = len(_g)
                _p = _g["_pts"].sum()
                _name = _labels[_o][0 if _k == 1 else 1]
                if _o == "fouled":
                    _parts.append(f"{_k} {_name} \u2192 {_p:.0f} at the line")
                elif _p > 0:
                    _parts.append(f"{_k} {_name} ({_p:.0f})")
                else:
                    _parts.append(f"{_k} {_name}")
            _known = int(d["_pts"].notna().sum())
            _total = d["_pts"].sum()
            _head = f"{n} possessions, {_total:.0f} points"
            if _known < n:
                _head += f" ({n - _known} with no points read, left out of PPP)"
            out["driver"] = _head + ": " + " &middot; ".join(_parts)
            if r_uses_cut is not None and n < r_uses_cut:
                out["driver"] += " &middot; small sample"
            return out

        def _q_best_defense(set_name):
            """Highest-PPP defense this set scored against. Same rule as the main section's "Best vs.
            defense" column."""
            if _pcc_all.empty or "defense_faced" not in _pcc_all.columns or "play_call" not in _pcc_all.columns:
                return ""
            d = _pcc_all[(_pcc_all["side"] == side)
                        & (_pcc_all["play_call"].astype(str) == str(set_name))
                        & _pcc_all["defense_faced"].notna()
                        & (_pcc_all["decode_quality"] != "Needs review")].copy()
            if "possession_side" in d.columns:
                d = d[d["possession_side"].astype(str) != "Defense"]
            if d.empty:
                return ""
            d["_pts"] = pd.to_numeric(d.get("points"), errors="coerce")
            by = d.groupby("defense_faced").agg(uses=("defense_faced", "size"), pts=("_pts", "sum"),
                                                known=("_pts", lambda s: s.notna().sum()))
            by["ppp"] = by["pts"] / by["known"].replace(0, pd.NA)
            if len(by) == 1:
                return _sb_clean(by.index[0])
            by = by[by["uses"] >= 2].dropna(subset=["ppp"])
            return _sb_clean(by.sort_values("ppp", ascending=False).index[0]) if not by.empty else ""

        section(title + footnote(
            "Same tagged possessions as HOW WE RUN OFFENSE above, sorted by how often we call a set against "
            f"how well it scores. The usage line is the median ({_use_cut:.0f} uses) and the efficiency line "
            f"is our own average ({team_ppp:.2f} PPP), so this is relative to us, not to the league. Sets "
            f"with fewer than {_QMIN} tagged possessions are left out -- not enough reps to judge. Read it "
            "as a call sheet, not a verdict: a low-efficiency set may still be there to set up something "
            "else."))
        add('<div class="card">')

        _quads = [
            ("Keep calling it", "Called often, scores well", "q-good",
             lambda r: r["_uses"] >= _use_cut and r["_ppp"] >= team_ppp),
            ("Call it more", "Scores well, we barely call it", "q-up",
             lambda r: r["_uses"] < _use_cut and r["_ppp"] >= team_ppp),
            ("Fix it or cut it", "Called often, does not score", "q-bad",
             lambda r: r["_uses"] >= _use_cut and r["_ppp"] < team_ppp),
            ("Shelve it", "Rarely called, does not score", "q-dim",
             lambda r: r["_uses"] < _use_cut and r["_ppp"] < team_ppp),
        ]
        # ---- What they will play against us -- replaces three separate sections --------------------
        # THEIR DEFENSE & HOW WE ATTACK IT, DEFENSE TYPE BY SITUATION and BALL SCREEN COVERAGE all
        # described the same thing -- the opponent's own defense -- three ways, and each partly restated
        # the others (requested: combine). It lives HERE rather than in WHAT TO PLAY THEM IN because that
        # section is about THEIR OFFENSE; this is the other side of the ball, and it is exactly what our
        # sets below have to beat. Computed straight from the clips (defense_PLAYED on the opponent's
        # defensive possessions) so the base-defense, by-situation and coverage numbers can't disagree.
        _td = pd.DataFrame()
        if not _pcc_all.empty and "defense_played" in _pcc_all.columns:
            _td = _pcc_all[(_pcc_all["side"] == "Opponent")
                           & (_pcc_all["decode_quality"] != "Needs review")
                           & _pcc_all["defense_played"].notna()].copy()
            if "possession_side" in _td.columns:
                _td = _td[_td["possession_side"].astype(str) == "Defense"]
        _TD_MIN = 4
        if len(_td) >= _TD_MIN:
            _td["_pts"] = pd.to_numeric(_td.get("points"), errors="coerce")
            add(f'<div class="tier-h">What {_sb_esc(OPP_UP)} will play against us</div>')
            add('<table class="compact"><thead><tr><th style="text-align:left">Situation</th><th>Poss</th>'
                '<th style="text-align:left">Base defense</th><th style="text-align:left">Changes to</th>'
                '<th>PPP allowed</th></tr></thead><tbody>')
            # Overall first, then each situation that has enough possessions to say something.
            _groups = [("All", _td)]
            if "play_situation" in _td.columns:
                _so = ["Half court", "Transition", "BLOB", "SLOB", "ATO"]
                for _sit in _so + [x for x in _td["play_situation"].dropna().astype(str).unique() if x not in _so]:
                    _sg = _td[_td["play_situation"].astype(str) == _sit]
                    if len(_sg) >= _TD_MIN:
                        _groups.append((_sit, _sg))
            for _lbl, _g in _groups:
                _vc = _g["defense_played"].astype(str).value_counts()
                _base_txt = f"{_vc.index[0]} ({round(100 * int(_vc.iloc[0]) / len(_g))}%)"
                _chg = (f"{_vc.index[1]} ({round(100 * int(_vc.iloc[1]) / len(_g))}%)" if len(_vc) > 1 else "--")
                _known = _g["_pts"].notna().sum()
                _ppp = (_g["_pts"].sum() / _known) if _known else None
                add(f'<tr class="{"serrow" if _lbl == "All" else "setrow"}"><td class="wrap">{_sb_esc(_lbl)}</td>'
                    f'<td>{len(_g)}</td><td class="wrap">{_sb_esc(_base_txt)}</td>'
                    f'<td class="wrap mini">{_sb_esc(_chg)}</td><td>{_sb_fmt(_ppp, 2)}</td></tr>')
            add("</tbody></table>")

            _lines = []
            # Ball-screen coverage, with what it gives up -- the coverage that leaks most is the one to attack.
            if "coverage_played" in _td.columns:
                _cv = _td[_sb_has_text(_td["coverage_played"])]
                if not _cv.empty:
                    _cvs = []
                    for _cn, _cg in _cv.groupby(_cv["coverage_played"].astype(str)):
                        _k = _cg["_pts"].notna().sum()
                        _cvs.append((_cn, len(_cg), (_cg["_pts"].sum() / _k) if _k else None))
                    _cvs.sort(key=lambda x: -x[1])
                    _lines.append("<strong>Ball screens:</strong> " + ", ".join(
                        f"{_sb_esc(n)} {c}x" + (f" ({p:.2f} allowed)" if p is not None else "")
                        for n, c, p in _cvs[:4]))
                    _leak = [x for x in _cvs if x[1] >= 3 and x[2] is not None]
                    if len(_leak) >= 2:
                        _worst_cov = max(_leak, key=lambda x: x[2])
                        _lines[-1] += (f" \u2014 attack <strong>{_sb_esc(_worst_cov[0])}</strong>, "
                                       f"it gives up the most.")
            if "press_played" in _td.columns and int(_td["press_played"].astype(bool).sum()):
                _pr = _td[_td["press_played"].astype(bool)]
                _pf = (_pr["press_formation_played"].dropna().astype(str).value_counts()
                       if "press_formation_played" in _pr.columns else pd.Series(dtype=int))
                _lines.append(f"<strong>Pressure:</strong> pressed on {len(_pr)} of {len(_td)} possessions"
                              + (f" ({_sb_esc(', '.join(_pf.index[:2]))})" if len(_pf) else "") + ".")
            # Staff's "how we attack it" notes carry over when the staff has actually written them -- the
            # generated sample text never does.
            _sd, _sd_sample = staff_rows("uww_opp_defense")
            if not _sd.empty and not _sd_sample and "how_we_attack" in _sd.columns:
                for _, _sr in _sd.iterrows():
                    _how = _sb_clean(_sr.get("how_we_attack"))
                    if _how:
                        _lines.append(f"<strong>{_sb_esc(_sb_clean(_sr.get('item')))}:</strong> "
                                      f"{_sb_esc(_how)}")
            for _l in _lines:
                add(f'<p class="strip-line">{_l}</p>')
            add('<p class="mini">Each set below shows which defense it beat \u2014 read the two together.</p>')
        else:
            add(f'<p class="mini">{_sb_esc(OPP_UP)}\'s own defense isn\'t tagged yet, so what they\'ll play '
                'against us isn\'t shown. It appears here once their defensive possessions are tagged.</p>')

        add('<div class="quad quad-rich">')
        for _qname, _qsub, _qcls, _test in _quads:
            _rows = _rated[_rated.apply(_test, axis=1)].sort_values(
                ["_ppp", "_uses"], ascending=[False, False])
            add(f'<div class="quad-cell {_qcls}">'
                f'<div class="quad-h">{_sb_esc(_qname)}<span class="quad-n">{len(_rows)}</span></div>'
                f'<div class="quad-sub">{_sb_esc(_qsub)}</div>')
            if _rows.empty:
                add('<div class="quad-empty">Nothing here yet.</div>')
            for _, r in _rows.head(_QSHOW).iterrows():
                _vs = _q_best_defense(r["name"])
                _cx = _q_context(r["name"])
                # Each line answers a different question, so they are labelled rather than run together:
                # who actually finishes it, what it runs with, when it runs, and why it scores the way it
                # does. The "who" line in particular is phrased as observed usage -- a bare name read as
                # "we should run this for him", which is not what the number says.
                _lines = []
                if _cx["who"]:
                    _lines.append(("Who", _cx["who"] + (f" &middot; best vs {_sb_esc(_vs)}" if _vs else "")))
                elif _vs:
                    _lines.append(("Who", f"best vs {_sb_esc(_vs)}"))
                if _cx["unit"]:
                    _lines.append(("Unit", _cx["unit"]))
                if _cx["lineup"]:
                    _lines.append(("Personnel", _cx["lineup"]))
                if _cx["clock"]:
                    _lines.append(("Clock", _cx["clock"]))
                if _cx["driver"]:
                    _lines.append(("How", _cx["driver"]))
                add(f'<div class="quad-row"><span class="quad-set">{_sb_esc(_sb_clean(r["name"]))}</span>'
                    f'<span class="quad-num">{r["_ppp"]:.2f} PPP<span class="mini"> in {int(r["_uses"])} possession{"" if int(r["_uses"]) == 1 else "s"}</span></span>'
                    + "".join(f'<div class="quad-meta"><span class="qk">{k}</span> {v}</div>'
                              for k, v in _lines)
                    + "</div>")
            if len(_rows) > _QSHOW:
                add(f'<div class="quad-more">+ {len(_rows) - _QSHOW} more</div>')
            add("</div>")
        add("</div>")
        add('<p class="mini">' + app_link("Every set, clip and spot", page="upcoming", tab="game_plan",
                                          section="play_calls_uww") + "</p>")
        add("</div>")

    offense_section_test_uww("UWW", "\U0001f3c0 HOW WE RUN OFFENSE")

    # AVAILABILITY and SCOUT TEAM removed from the brief (requested) -- still built and shown in full in
    # the app's Game Plan tab. Availability status still feeds the roster's per-player flag (see _avail_by
    # above), so that lookup stays; only the standalone OUR WEEK section is gone.

    # PRACTICE PLAN removed from the brief (requested) -- still built and shown in full in the app's Game
    # Plan tab. The brief's defensive recommendation and press verdict still feed it there.

    # =====================================================================================================
    # NOTES
    # =====================================================================================================
    _sb_photo_report.clear()
    _sb_photo_report.update({k: (v[0], list(v[1])) for k, v in _photo_stats.items()})
    _sb_notes_report.clear()
    _sb_notes_report.extend(footnotes)

    gl = _sb_d("uww_play_glossary")
    # The Notes list and the play-title glossary live in the APP now (requested). READ WITH CAUTION stays
    # -- it's a warning about the numbers on THIS page, not reference material, so it has to travel with
    # the brief. What's left here is a pointer: the ⓘ markers throughout already deep-link to individual
    # notes, and this card covers the two whole collections.
    _fs_info, _fs_rows = _sb_film_status()
    try:
        pd.DataFrame(_fs_rows, columns=["area", "measure", "value", "detail"]).assign(
            **{k: v for k, v in _fs_info.items()}).to_csv(os.path.join(APP_DATA_DIR, "uww_film_ai_status.csv"), index=False)
    except Exception:
        pass
    if _fs_rows or _fs_info or _film_html:
        page_break()
        section("\U0001f3a5 HOW THE FILM IS WATCHED AUTOMATICALLY")
        # --- how the film is watched automatically, what went in, and how well it's working
        _i = _fs_info
        _n = lambda k: f"{int(_i[k]):,}" if _i.get(k) is not None else "--"
        add('<div class="card"><p><strong>How it works</strong></p><ol class="bl">'
            "<li><strong>Capture.</strong> For every tagged clip, the parser opens the game on Synergy and saves "
            "still frames of the play: 5 key frames, plus 4 frames a second for player tracking.</li>"
            "<li><strong>Players.</strong> A detection model finds every person in each frame; a one-time court "
            "calibration per gym places them on the floor; jersey colors split the teams, and referees, coaches "
            "and fans are set aside. Each player is followed frame to frame and across back-to-back plays. Names "
            "come from the coaches' checks, a jersey-number reader trained on our own film, and the five known to "
            "be on the floor (play-by-play substitutions); anyone else gets a best guess, marked as one.</li>"
            "<li><strong>Plays.</strong> The Tag model learns the coaches' Titles from Synergy's description of "
            "each play, its key frames and the players' positions, then writes an automatic Title -- formation, "
            "play call, situation, defense, press, coverages -- for every play, tagged or not.</li>"
            "<li><strong>Coaches' reviews.</strong> Each run builds a review of 20 random plays per game. A coach "
            "checks the players and the automatic Title; every check becomes a certain name and training data, "
            "so the models improve with each review.</li></ol>")
        add(f'<p class="mini">So far: {_n("games_captured")} game(s) captured ({_n("clips_captured")} clips); '
            f'{_n("games_tagged")} game(s) tagged by the coaches ({_n("clips_tagged")} plays); '
            f'{_n("games_tracked")} game(s) tracked ({_n("clips_tracked")} plays, {_n("frames_tracked")} frames). '
            f'Coach reviews: {_n("player_checks")} player check(s) on {_n("plays_checked")} play(s), '
            f'{_n("title_answers")} Title answer(s) on {_n("plays_title_reviewed")} play(s)'
            + (f'; {_n("validation_plays")} tagged plays held out of training to test the Tag model'
               if _i.get("validation_plays") else "")
            + (f'. Players on the floor named from evidence (not a best guess): {_n("players_from_evidence")} of '
               f'{_n("player_slots")}' if _i.get("player_slots") else "")
            + (f'; tracked frames placed on the court: {_i["court_mapped_pct"]}%' if _i.get("court_mapped_pct") is not None else "")
            + ".</p>")
        if _fs_rows:
            _td = 'style="text-align:left;vertical-align:top;padding:3px 6px;white-space:normal"'
            add('<p><strong>How well it\'s working</strong> -- every row is something a coach checked, and how often the '
                "film's automatic answer agreed</p>"
                '<table class="compact" style="width:100%;table-layout:fixed"><colgroup><col style="width:18%">'
                '<col style="width:50%"><col style="width:32%"></colgroup><thead><tr>'
                f'<th {_td}>Area</th><th {_td}>What the coaches checked</th><th {_td}>Film agreed with the coaches</th></tr></thead><tbody>'
                + "".join(f"<tr><td {_td}>{_sb_esc(a)}</td><td {_td}>{_sb_esc(m)}"
                          + (f'<div class="mini">{_sb_esc(d)}</div>' if d else "")
                          + f"</td><td {_td}><strong>{_sb_esc(v).replace(chr(10), '<br>')}</strong></td></tr>" for a, m, v, d in _fs_rows)
                + "</tbody></table>")
            add('<p class="mini"><strong>How to read these counts</strong></p><ul class="mini">'
                "<li>Only boxes and answers a coach actually judged count. A box left on <em>-- not checked --</em> is "
                "never saved, so it is never counted as right or wrong.</li>"
                "<li>A name is not right when the coach marked it <em>really someone else</em> (right team, wrong player), "
                "<em>wrong team</em>, or <em>not a player</em>; each Right-name row lists which.</li>"
                "<li><em>Named by ...</em> is how the film had named that box when its review page was built, so it "
                "reflects that run's naming, even if a later run names the player differently.</li>"
                "<li>A box checked in more than one saved review counts once -- the latest check.</li>"
                "<li>Small samples move a lot from one run to the next -- a row with only a few checks says little yet. "
                "Read these as where things stand today, not final grades.</li></ul>")
            add('<p class="mini"><strong>How the coaches\' review answers are used</strong></p><ul class="mini">'
                "<li><em>right</em> = the automatic answer was correct; <em>wrong</em> + a typed answer = the typed answer is "
                "correct; <em>wrong</em> with nothing typed, or <em>can\'t tell</em> = only the mark is kept (no answer to learn).</li>"
                "<li>The latest saved answer for a play\'s field counts -- an older one is replaced, never added.</li>"
                "<li>Every answer becomes what the Tag model learns for that play: it fills fields the coach\'s Title left "
                "empty and, when it disagrees with the coach\'s Title, it overrides it"
                + ("" if globals().get("TAG_MODEL_REVIEW_OVERRIDES_TITLE", True) else
                   " (switched off on this run -- disagreements leave the coach\'s Title in place)")
                + ". The model retrains on the next run.</li>"
                "<li>Rows prefilled as <em>wrong</em> (the coach\'s value differed from the automatic one) and left untouched "
                "never override anything and are not counted as reviews -- the coach-Title comparison already counts them. "
                "Changed or re-picked, they count.</li>"
                "<li>The <em>Coach</em> values and the coach-Title comparisons above always show what the coach actually "
                "tagged; only what the model learns changes. Validation plays are never trained on, answers included.</li>"
                "<li>A typed answer that matches a known answer apart from capitals, spaces or punctuation is stored in the "
                "known spelling (\'2-3 zone\' -> \'2-3 Zone\'); a genuinely new answer is kept as typed and listed in the "
                "parser\'s output to check for typos.</li>"
                "<li>Review answers never change uww_plays.csv; the brief and app still report the coach\'s Titles.</li>"
                "<li>The most recent review beats a coach\'s later re-tag of the same play -- to let a new tag stand, change "
                "or clear that play\'s answer in a review.</li></ul>")
        add("</div>")
        # ...followed by every section built from the film
        for _h in _film_html:
            add(_h)
    if not _warn_df.empty or footnotes or not gl.empty:
        page_break()
        if not _warn_df.empty:
            section("\u26a0\ufe0f READ WITH CAUTION")
            add('<div class="card caution">')
            for _, _w in _warn_df.iterrows():
                add(f'<div class="row"><span class="area">{_sb_esc(_w.get("area"))}</span>'
                    f'<strong>{_sb_esc(_w.get("subject"))}</strong> \u2014 {_sb_esc(_w.get("detail"))}</div>')
            add("</div>")
        if footnotes or not gl.empty:
            section("\u24d8 METHODOLOGY")
            add('<div class="card"><ul class="bl">')
            if footnotes:
                add("<li>" + app_link(f"Notes ({len(footnotes)}) \u2014 how every number on this brief was built",
                                      page="upcoming", tab="notes")
                    + " \u2014 each \u24d8 in this brief links straight to its own note.</li>")
            if not gl.empty:
                add("<li>" + app_link(f"How the play titles were decoded ({len(gl)} shorthand terms)",
                                      page="upcoming", tab="notes", section="glossary")
                    + " \u2014 what each tagging shorthand reads as, and how confident that read is.</li>")
            add("</ul></div>")

    # ---- footer ---------------------------------------------------------------------------
    try:
        generated = datetime.now().strftime("%B %-d, %Y at %-I:%M %p")
    except ValueError:
        # "%-d"/"%-I" are a glibc strftime extension that Windows' CRT rejects outright -- the same
        # portability trap the play-by-play cells already hit with "%-m"/"%-d". Fall back rather
        # than let a timestamp take down the whole report.
        generated = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    add('<div class="foot">')
    add(f"<p>Generated {_sb_esc(generated)} from the scouting parser's exported data \u2014 the same "
        f"tables the scouting app reads, reconstructed from play-by-play, video-tagging and box-score "
        f"exports. Sample (placeholder) data is left out of this report; it still shows in the app.</p>")
    if _sb_d.missing:
        add(f'<p>Not available for this build: {_sb_esc(", ".join(sorted(set(_sb_d.missing))))}. '
            f'Sections relying on those sources were left out rather than filled with estimates.</p>')
    add("<p>Prepared ahead of the staff's own scouting reports. Numbers will move as more film is "
        "tagged.</p></div>")

    body = "\n".join(parts)
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_sb_esc(_SB_UWW)} vs {_sb_esc(short)} &mdash; scouting brief</title>\n"
        f"<style>{_SB_CSS}</style>\n</head>\n<body>\n<div class=\"page\">\n{body}\n</div>\n</body>\n</html>\n"
    )


# --- Run it ------------------------------------------------------------------------------------------------
_sb_data = _SbData(APP_DATA_DIR)
_sb_game, _sb_scheduled_name, _sb_short = _sb_resolve_matchup(_sb_data)

# Prefer the name this notebook already resolved (see the "Identify the upcoming opponent" cell, including
# its no-scout-report fallback) over the one derived from the CSVs -- one source of truth for who we are
# playing, rather than two that agree right up until they don't.
_sb_notebook_short = globals().get("upcoming_opponent_short")
if _sb_notebook_short:
    _sb_short = _sb_notebook_short

if _sb_game is None:
    print("No upcoming game found in uww_schedule.csv -- no brief written. Check that the CSV export cell "
          "ran, and that reference_date falls on or before the next game you want a brief for.")
else:
    _sb_document = _sb_build_html(_sb_data, _sb_game, _sb_scheduled_name, _sb_short)
    if _sb_data.sample_dropped:
        print("Sample data left out of the brief (still in the app): " + ", ".join(sorted(set(_sb_data.sample_dropped))))
    os.makedirs(_SB_OUT_DIR, exist_ok=True)
    _sb_slug = re.sub(r"[^\w]+", "_", str(_sb_short)).strip("_") or "opponent"
    _sb_path = os.path.join(_SB_OUT_DIR, f"scouting_brief_{_sb_slug}.html")
    with open(_sb_path, "w", encoding="utf-8") as _sb_f:
        _sb_f.write(_sb_document)
    print(f"Wrote {os.path.abspath(_sb_path)} ({len(_sb_document):,} bytes) -- open it in a browser, or "
          f"attach it to an email as-is.")
    # The Notes page moved out of the brief and into the app (requested), so the app needs the text. Note
    # numbers are the deep-link target the brief's ⓘ markers point at, so they're stored explicitly rather
    # than left to row order.
    _sb_notes_df = pd.DataFrame({"note": range(1, len(_sb_notes_report) + 1),
                                 "opponent": str(_sb_short),
                                 "text": _sb_notes_report})
    _sb_notes_df.to_csv(os.path.join(APP_DATA_DIR, "uww_brief_notes.csv"), index=False)
    print(f"  {len(_sb_notes_df)} methodology note(s) -> uww_brief_notes.csv (the brief links to these "
          f"instead of printing them).")
    if not str(globals().get("APP_BASE_URL") or os.environ.get("UWW_APP_URL") or "").strip():
        print("  NOTE: APP_BASE_URL is blank, so the brief's \u24d8 markers and the Methodology links are "
              "omitted entirely -- with the notes no longer printed in the brief, there is currently no "
              "way for a reader to reach them. Set APP_BASE_URL in the config cell.")
    for _side, (_hit, _miss) in _sb_photo_report.items():
        if _hit or _miss:
            print(f"  {_side} headshots: {_hit} found, {len(_miss)} missing"
                  + (f" -- {', '.join(_miss[:6])}{' ...' if len(_miss) > 6 else ''}" if _miss else "")
                  + ("" if _hit else " (no live roster scrape for this team yet, and no files in "
                                    "data/player_images -- see the Roster pages cell)"))
    if _sb_data.missing:
        print("  Tables that were empty or missing (their sections were left out of the brief): "
              + ", ".join(sorted(set(_sb_data.missing))))
