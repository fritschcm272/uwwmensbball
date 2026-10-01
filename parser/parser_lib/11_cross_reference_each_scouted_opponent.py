# 11_cross_reference_each_scouted_opponent.py -- code for the notebook section "The FASTINTELLIGENCE narrative used previously is gone (see prior cell), so this now cross"
# Runs inside the notebook via run_section("11_cross_reference_each_scouted_opponent"); its settings are in that notebook cell.

# The FASTINTELLIGENCE narrative used previously is gone (see prior cell), so this now cross-references each
# opponent's season-average PPG scored/allowed straight from their PDF's "...BOXSCORE" table's "Team Total"
# and "Opponent" rows -- a different underlying data source than the old narrative, so exact figures may differ
# from what MHTML-based reports previously showed.
def _dedupe_boxscore_columns(df):
    """read_boxscore_table below builds its DataFrame from a plain Python `headers` list via
    `pd.DataFrame(records, columns=headers)` -- unlike pd.read_html elsewhere in this notebook, this gets NO
    automatic duplicate-column mangling from pandas at all, so two header cells that happen to render the
    same text (confirmed to happen on the live-rendered ScoutBuilder boxscore widget -- see the app-side fix
    this mirrors) silently produce a DataFrame with two identically-named columns. Any later df[col] or
    row[col] access on that name then returns a Series instead of a scalar without raising, which is exactly
    the "truth value of a Series is ambiguous" crash this was tracked down from. Dedupe once here, right at
    construction, rather than downstream wherever it happens to first get accessed."""
    if df.columns.duplicated().any():
        dupes = df.columns[df.columns.duplicated()].unique().tolist()
        print(f"WARNING: boxscore table has duplicate column name(s) {dupes} -- keeping the first occurrence "
              f"of each and dropping the rest.")
        df = df.loc[:, ~df.columns.duplicated()]
    return df


def read_boxscore_table(html_str):
    """Parse a FastScout PDF boxscore <table> into a DataFrame. On some (not all) opponents' PDFs, a player's
    full name is split across two separate <td> cells (first name, last name) while the header row only
    allocates a single <th>PLAYER</th> slot for it -- silently shifting every later column (FG%, 3P%, etc.) one
    position to the right of its real header when read naively via pd.read_html(). Detect that per-row and
    merge the split name cells back into one before assigning headers, so every stat column lines up correctly
    regardless of which layout a given PDF used."""
    table_soup = BeautifulSoup(html_str, "html.parser")
    header_row = table_soup.find("tr")
    header_cells = header_row.find_all("th")

    # The LIVE ScoutBuilder HTML boxscore table (Cell 8's HTML path, as opposed to a pdfplumber-extracted PDF
    # table) wraps every REAL header/data cell in its own "cell-content" div, and ALSO carries decorative
    # leading cells (a blank "table-gutter" cell + a sort-handle cell) that never get one -- confirmed against
    # a real live-downloaded report: naive positional header/cell alignment (the PDF-oriented path below)
    # silently misaligns every column by those decorative cells, since headers ends up 2 shorter than the
    # actual <td> count per row for a totally unrelated reason than the split-name case it was built for.
    # Detect that shape via "cell-content" and filter on it directly instead of position.
    if any(th.find(class_="cell-content") is not None for th in header_cells):
        headers = []
        for th in header_cells:
            content_div = th.find(class_="cell-content")
            if content_div is not None:
                headers.append(normalize_html_text(content_div.get_text(" ", strip=True)))
        body = table_soup.find("tbody")
        body_rows = body.find_all("tr") if body else table_soup.find_all("tr")[1:]
        records = []
        for tr in body_rows:
            cells = []
            for td in tr.find_all("td"):
                content_div = td.find(class_="cell-content")
                cells.append(normalize_html_text(content_div.get_text(" ", strip=True)) if content_div is not None else None)
            cells = [c for c in cells if c is not None]
            records.append(cells[: len(headers)])
        _boxscore_df = pd.DataFrame(records, columns=headers)
        return _dedupe_boxscore_columns(_boxscore_df)

    # --- PDF-oriented path (pdfplumber's plain-text cells have no "cell-content" wrapper at all) ---
    header_cells_text = [th.get_text(strip=True) for th in header_cells]
    # Drop trailing decorative header cell(s) with no real stat name -- this is sometimes a blank "" and
    # sometimes a private-use-area icon glyph (e.g. "\uf107", presumably a sort-arrow icon that pdfplumber
    # extracted as text) depending on the PDF, but either way it never has any alphanumeric content.
    headers = header_cells_text[:]
    while headers and not any(c.isalnum() for c in headers[-1]):
        headers = headers[:-1]
    name_idx = headers.index("PLAYER")
    body = table_soup.find("tbody")
    body_rows = body.find_all("tr") if body else table_soup.find_all("tr")[1:]
    records = []
    for tr in body_rows:
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) == len(headers) + 1:
            cells = cells[:name_idx] + [" ".join(c for c in cells[name_idx:name_idx + 2] if c)] + cells[name_idx + 2:]
        records.append(cells[: len(headers)])
    _boxscore_df = pd.DataFrame(records, columns=headers)
    return _dedupe_boxscore_columns(_boxscore_df)


def extract_team_totals_from_pdf(elements_df, opponent):
    rows = elements_df.to_dict("records")
    box_idx = next(
        (i for i, r in enumerate(rows) if r["element_type"] == "section_header" and "BOXSCORE" in r["element_content"].upper()),
        None,
    )
    if box_idx is None or rows[box_idx + 1]["element_type"] != "table":
        return None
    stats_df = read_boxscore_table(rows[box_idx + 1]["element_content"]).rename(columns={"PLAYER": "name"})
    # See the analogous fix in the player-tagging cell above -- pdfplumber can truncate "Team Total" down to just
    # "Team", so also fall back to the jersey-number column ("#" == "-" for the aggregate row) to find it.
    team_row = stats_df[(stats_df["name"] == "Team Total") | (stats_df.get("#") == "-")]
    opp_row = stats_df[stats_df["name"] == "Opponent"]
    if team_row.empty:
        print(f"  Skipping '{opponent}': no 'Team Total' row in its boxscore table.")
        return None
    if opp_row.empty:
        print(f"  Note: '{opponent}' boxscore has no 'Opponent' row (points allowed) -- reporting team_ppg only.")
    return {
        "opponent": opponent,
        "team_ppg": float(team_row["PTS"].iloc[0]),
        "opp_ppg_allowed": float(opp_row["PTS"].iloc[0]) if not opp_row.empty else None,
    }

team_totals = pd.DataFrame([
    r for r in (extract_team_totals_from_pdf(df, opponent) for opponent, df in scout_reports.items()) if r
])

# CONFIRMED CHANGE (requested): stop using ANY team or player statistics sourced from the scouting
# report, parser-wide. Root cause of a real, reported leak: these PDF scout reports are explicitly
# labeled "Last Season" and carry the PRIOR YEAR's numbers -- Ripon's real per-game PPG/points-allowed
# had nothing to do with any game either team has played this year, and no reference_date fix can make a
# stale, undated PDF summary trustworthy. team_ppg/opp_ppg_allowed are blanked immediately after parsing
# (team_totals is kept for the opponent-identity/schedule-matching logic below, which doesn't need real
# stats). The ONLY legitimate source for these numbers from here on is the PBP-derived override further
# down this notebook (see "Override the upcoming opponent's team_totals"), which uses real, current-
# season game data instead.
if not team_totals.empty:
    team_totals["team_ppg"] = None
    team_totals["opp_ppg_allowed"] = None

# "Keys to Victory" notes use basketball terminology rather than stat names directly ("Ball Security" ==
# turnovers, "Own the Paint"/"Bully them on the glass" == rebounding, etc). Map that terminology to the UWW
# season stat columns it corresponds to, then surface UWW's season-long "Team Total" (their own average) vs.
# "Opponent" (what teams average against UWW) rows from `stats` for whichever columns a given note touches on --
# there's no per-game UWW box score in this pipeline (the PDF boxscore only covers the OPPONENT's roster), so the
# season averages are the best available context for whether that emphasis is one UWW has actually executed on.
KEYS_TO_VICTORY_STAT_MAP = {
    # --- Ball Security / Turnovers (TO) ---
    "ball security": ["TO"], "turnover": ["TO"], "protect the ball": ["TO"], "take care of the ball": ["TO"],
    "limit turnovers": ["TO"], "careless": ["TO"],
    # --- Rebounding (REB, ORB, DRB) ---
    "own the paint": ["REB", "ORB", "DRB"], "bully": ["REB", "ORB", "DRB"], "glass": ["REB", "ORB", "DRB"],
    "rebound": ["REB", "ORB", "DRB"], "board": ["REB", "ORB", "DRB"], "second chance": ["ORB"],
    "crash": ["REB", "ORB", "DRB"],
    # --- Three-Point Shooting (3PM-A, 3P%) ---
    "three": ["3PM-A", "3P%"], "3 pt": ["3PM-A", "3P%"], "3pt": ["3PM-A", "3P%"],
    "perimeter shooting": ["3PM-A", "3P%"], "spacing": ["3PM-A", "3P%"],
    "shooting ability": ["3PM-A", "3P%"], "shooting team": ["3PM-A", "3P%"],
    "sniper": ["3PM-A", "3P%"], "will shoot": ["3PM-A", "3P%"],
    # --- Free Throws (FTM-A, FT%) ---
    "free throw": ["FTM-A", "FT%"], "ft line": ["FTM-A", "FT%"], "getting to ft": ["FTM-A", "FT%"],
    # --- Fouls / Discipline (PF) ---
    "foul": ["PF"], "wall up": ["PF"], "drawing fouls": ["PF"],
    # --- Ball Movement / Assists (AST) ---
    "assist": ["AST"], "ball movement": ["AST"], "share the ball": ["AST"],
    "playmaking": ["AST"], "playmaker": ["AST"], "create": ["AST"],
    # --- Perimeter Defense / Ball Pressure (STL) ---
    "steal": ["STL"], "press capable": ["STL", "TO"], "full court press": ["STL", "TO"],
    "force turnovers": ["STL"], "force to's": ["STL"],
    "guard your yard": ["STL"], "keep the ball in front": ["STL"], "guard 1 on 1": ["STL"],
    "early gap": ["STL"], "help side": ["STL"], "active hands": ["STL"],
    "physical & aggressive on ball": ["STL"], "on ball defensively": ["STL"],
    "pressure": ["STL"],
    # --- Paint Protection / Blocks (BLK) ---
    "block": ["BLK"], "protect the rim": ["BLK"], "paint protection": ["BLK"],
    # --- Scoring Inside (FG2M, FG2A, FG2% — derived as FGM-FG3M, FGA-FG3A) ---
    "dominate the paint": ["FG2M", "FG2A", "FG2%"], "attack the paint": ["FG2M", "FG2A", "FG2%"],
    "live in the paint": ["FG2M", "FG2A", "FG2%"], "attack the basket": ["FG2M", "FG2A", "FG2%"],
    "scoring at the rim": ["FG2M", "FG2A", "FG2%"], "get to rim": ["FG2M", "FG2A", "FG2%"],
    "attack the rim": ["FG2M", "FG2A", "FG2%"], "get to the rim": ["FG2M", "FG2A", "FG2%"],
    # --- Field Goal Efficiency (FGM-A, FG%) — overall ---
    "limit their scoring": ["FGM-A", "FG%"],
}

# --- Side attribution: Is this phrase about what UWW does (offense/proactive) or containing the opponent? ---
PHRASE_SIDE = {
    "ball security": "UWW", "turnover": "UWW", "protect the ball": "UWW",
    "take care of the ball": "UWW", "limit turnovers": "UWW", "careless": "UWW",
    "own the paint": "UWW", "bully": "UWW", "glass": "UWW",
    "rebound": "UWW", "board": "UWW", "second chance": "UWW", "crash": "UWW",
    "box out": "OPP", "keep off glass": "OPP",
    "three": "UWW", "3 pt": "OPP", "3pt": "OPP", "perimeter shooting": "UWW", "spacing": "UWW",
    "shooting ability": "OPP", "shooting team": "OPP", "sniper": "OPP", "will shoot": "OPP",
    "close out": "OPP", "closeout": "OPP", "run off the line": "OPP",
    "free throw": "UWW", "ft line": "UWW", "getting to ft": "UWW",
    "don't foul": "OPP", "keep them off": "OPP",
    "foul": "OPP", "wall up": "OPP", "drawing fouls": "OPP",
    "assist": "UWW", "ball movement": "UWW", "share the ball": "UWW",
    "playmaking": "UWW", "playmaker": "UWW", "create": "UWW",
    "steal": "OPP", "press capable": "OPP", "full court press": "OPP",
    "force turnovers": "OPP", "force to's": "OPP",
    "guard your yard": "OPP", "keep the ball in front": "OPP", "guard 1 on 1": "OPP",
    "early gap": "OPP", "help side": "OPP", "active hands": "OPP",
    "physical & aggressive on ball": "OPP", "on ball defensively": "OPP",
    "pressure": "OPP",
    "block": "OPP", "protect the rim": "OPP", "paint protection": "OPP",
    "attack the paint": "UWW", "live in the paint": "UWW",
    "dominate the paint": "UWW", "attack the basket": "UWW",
    "scoring at the rim": "UWW", "get to rim": "UWW",
    "attack the rim": "UWW", "get to the rim": "UWW",
    "limit their scoring": "OPP",
    "take away": "OPP", "funnel": "OPP", "deny": "OPP", "contain": "OPP",
    "limit": "OPP", "contest": "OPP", "make them": "OPP", "load up": "OPP",
    "transition defense": "OPP", "fight over": "OPP", "switch": "OPP",
    "trap": "OPP", "double team": "OPP", "coverage": "OPP",
    "don't help off": "OPP", "take away personnel": "OPP",
    "run the floor": "UWW", "push tempo": "UWW", "fast break": "UWW",
    "score in transition": "UWW", "finish": "UWW", "execute": "UWW",
    "dominate": "UWW", "impose": "UWW", "push the pace": "UWW",
}
STAT_LABELS = {
    "TO": "Turnovers/gm", "REB": "Rebounds/gm", "ORB": "Off. rebounds/gm", "DRB": "Def. rebounds/gm",
    "AST": "Assists/gm", "STL": "Steals/gm", "BLK": "Blocks/gm", "3PM-A": "3PM-A/gm", "3P%": "3P%",
    "FGM-A": "FGM-A/gm", "FG%": "FG%", "FTM-A": "FTM-A/gm", "FT%": "FT%", "PF": "Fouls/gm",
}
# uww_team_totals = stats[stats["PLAYER"] == "Team Total"].iloc[0] if (stats["PLAYER"] == "Team Total").any() else None
uww_team_totals = None
# uww_opp_totals = stats[stats["PLAYER"] == "Opponent"].iloc[0] if (stats["PLAYER"] == "Opponent").any() else None
uww_opp_totals = None

def stat_cols_for_note(note_text):
    text = str(note_text).lower()
    cols = []
    for phrase, stat_cols in KEYS_TO_VICTORY_STAT_MAP.items():
        if phrase in text:
            for c in stat_cols:
                if c not in cols:
                    cols.append(c)
    return cols

def print_keys_to_victory_stats(note_text):
    cols = stat_cols_for_note(note_text)
    if not cols or uww_team_totals is None:
        return
    print("    Relevant UWW season averages (Team Total = UWW's own avg, Opponent = what teams average against UWW):")
    for c in cols:
        print(f"      {STAT_LABELS.get(c, c)}: UWW {uww_team_totals[c]}  |  Opponent avg {uww_opp_totals[c]}")

# CONFIRMED BUG (fixed here): my first pass at removing the PDF-stat comparison deleted this ENTIRE
# section, including scouted_game_comparison itself -- which broke a separate, LEGITIMATE downstream cell
# (the win/loss-splits-by-"Keys to Victory"-category cell) that only ever reads its `opponent` and
# `outcome` columns, both of which come from the real schedule, not the PDF. That cell crashed with
# "NameError: name 'scouted_game_comparison' is not defined" the very next run. Restored below: every
# column sourced from the REAL schedule (opponent, date, location, outcome, actual scores, point_margin)
# stays; only the PDF-derived season-average PPG comparison columns are permanently None (they inherit
# that from team_totals's blanking above) and guarded with pd.notna() so they read as "N/A" in the
# printout instead of crashing on None -- consistent with the opp_ppg_allowed side, which already had to
# handle a sometimes-missing value the same way even before this change.
comparison_rows = []
for _, tt in team_totals.iterrows():
    opponent = tt["opponent"]
    matches = schedule[schedule["opponent"].str.contains(re.escape(opponent), case=False)]
    if matches.empty:
        print(f"No schedule match found for scouted opponent '{opponent}' -- skipping.")
        continue
    game_result = matches.iloc[0]

    comparison_rows.append({
        "opponent": opponent,
        "date": game_result["date"],
        "location": game_result["location"],
        "outcome": game_result["outcome"],
        "opp_season_avg_ppg": tt["team_ppg"],
        "opp_actual_ppg": game_result["opponent_score"],
        "opp_ppg_vs_average": (
            round(game_result["opponent_score"] - tt["team_ppg"], 1) if pd.notna(tt["team_ppg"]) else None
        ),
        "uww_points": game_result["team_score"],
        "opp_season_avg_ppg_allowed": tt["opp_ppg_allowed"],
        "uww_ppg_vs_opp_avg_allowed": (
            round(game_result["team_score"] - tt["opp_ppg_allowed"], 1) if pd.notna(tt["opp_ppg_allowed"]) else None
        ),
        "point_margin": game_result["point_margin"],
    })

scouted_game_comparison = pd.DataFrame(comparison_rows)
if scouted_game_comparison.empty:
    print("No opponents with a schedule match -- nothing to cross-reference.")
else:
    print(scouted_game_comparison)
    print("\n(opp_season_avg_ppg / opp_ppg_vs_average / opp_season_avg_ppg_allowed / uww_ppg_vs_opp_avg_allowed "
          "are always blank now -- team/player statistics from the scouting report are no longer used; see "
          "the blanking earlier in this cell.)")
    for _, row in scouted_game_comparison.iterrows():
        keys_to_victory = all_game_plans.loc[
            (all_game_plans["opponent"] == row["opponent"]) & (all_game_plans["topic"] == "KEYS TO VICTORY"), "notes"
        ]
        print(f"\n{row['opponent']} ({row['date']}, {row['location']}): UWW {row['uww_points']} - "
              f"{row['opponent']} {row['opp_actual_ppg']} ({row['outcome']}, margin {row['point_margin']:+.0f})")
        if not keys_to_victory.empty:
            print("  Pre-game keys to victory:", keys_to_victory.iloc[0])
            print_keys_to_victory_stats(keys_to_victory.iloc[0])
        if pd.notna(row["opp_ppg_vs_average"]):
            print(f"  Opponent scored {row['opp_ppg_vs_average']:+.1f} vs their season-average PPG (from the PDF box score).")
        else:
            print("  No season-average PPG available for comparison (scouting-report statistics are not used).")
        if pd.notna(row["uww_ppg_vs_opp_avg_allowed"]):
            print(f"  UWW scored {row['uww_ppg_vs_opp_avg_allowed']:+.1f} vs the opponent's season-average points allowed.")
        else:
            print("  No season-average points-allowed figure available for comparison (scouting-report statistics are not used).")
