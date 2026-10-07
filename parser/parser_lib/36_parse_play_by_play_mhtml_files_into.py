# 36_parse_play_by_play_mhtml_files_into.py -- code for the notebook section "Play-by-play (PBP) data ------------------------------------------------------------------"
# Runs inside the notebook via run_section("36_parse_play_by_play_mhtml_files_into"); its settings are in that notebook cell.

# --- Play-by-play (PBP) data -----------------------------------------------------------------------------
# Parsing functions (parse_pbp_mhtml, classify_event, build_pbp_events, opponent_from_pbp_filename) live in the
# "Play-by-play parsing functions" cell above. This cell just runs them over every "*_pbp.mhtml" file in
# INPUT_DIR (same pattern as the "*_scout.pdf" loop above) so newly added games are picked up automatically.

# Filter to "*UW-Whitewater*_pbp.mhtml" rather than the broader "*_pbp.mhtml" -- INPUT_DIR may also hold pbp
# files for OTHER teams' games that don't involve UW-Whitewater at all (uploaded while cross-scouting an
# opponent's other games). Those have no "UW-Whitewater" column in their 4-column layout at all, so parsing
# them here would silently misread one of the other two teams' event text as if it were UWW's.
pbp_files = sorted(glob.glob(f"{volume_dir}/*UW-Whitewater*_pbp.mhtml") + glob.glob(f"{volume_dir}/*UW-Whitewater*_pbp.html"))

# Live-scrape+cache any scouted UWW game missing a local pbp file, using its "game_url" from
# uww_team_schedule -- same pattern as the opponent-prior-games pbp cell above.
def _game_date_str(game_date):
    return f"{game_date.month}_{game_date.day}_{game_date.strftime('%y')}"

games_needing_live_uww_pbp = []
if not uww_team_schedule.empty:
    for _, g_row in uww_team_schedule.iterrows():
        g_date = parse_schedule_date(g_row["date"], uww_season_start_year) if pd.notna(g_row.get("date")) else None
        if g_date is None or pd.isna(g_row.get("game_url")):
            continue
        opp_short = next(
            (s for s in scouted_opponents if re.search(re.escape(s), str(g_row["opponent"]), re.IGNORECASE)), None
        )
        if opp_short is None or glob.glob(f"{volume_dir}/{_game_date_str(g_date)}*{opp_short}*_pbp.*"):
            continue
        games_needing_live_uww_pbp.append((g_row, g_date, opp_short))

if games_needing_live_uww_pbp and fastscout_username and fastscout_password:
    # One session call per game so a dead session can self-heal mid-batch (see the pbp cell above).
    for g_row, g_date, opp_short in games_needing_live_uww_pbp:
        try:
            if str(g_row.get("location", "")).strip().lower() == "home":
                matchup = f"{g_row['opponent']} @ UW-Whitewater"
            else:
                matchup = f"UW-Whitewater @ {g_row['opponent']}"
            pbp_save_path = f"{volume_dir}/{_game_date_str(g_date)} {matchup}_pbp.html"
            run_in_fastscout_session(
                lambda page, url=g_row["game_url"], sp=pbp_save_path: scrape_pbp_live(page, url, save_path=sp)
            )
        except Exception as pbp_scrape_error:
            print(f"  Could not live-scrape UWW's own pbp for {g_row['opponent']} ({g_row['game_url']}): {type(pbp_scrape_error).__name__}: {pbp_scrape_error}")

    # Re-glob so the freshly-cached ".html" file(s) are picked up by the parsing loop below.
    pbp_files = sorted(glob.glob(f"{volume_dir}/*UW-Whitewater*_pbp.mhtml") + glob.glob(f"{volume_dir}/*UW-Whitewater*_pbp.html"))
elif games_needing_live_uww_pbp:
    print(
        f"{len(games_needing_live_uww_pbp)} scouted UWW game(s) are missing a local '_pbp' file and could be "
        "live-scraped, but no FASTSCOUT_USERNAME/FASTSCOUT_PASSWORD were found -- skipping."
    )

print(f"Found {len(pbp_files)} UW-Whitewater play-by-play file(s):")
for f in pbp_files:
    print(" -", os.path.basename(f))

# Build a roster set for auto-detecting column swaps -- UWW season stats' second column is the player name.
_player_col = stats.columns[1]
uww_roster_names = set(stats[_player_col].dropna().tolist()) - {"Team Total", "Opponent"}

pbp_events_list = []
for path in pbp_files:
    opponent_short = opponent_from_pbp_filename(path)
    raw_df = parse_pbp_mhtml(path)

    # Auto-detect if UWW's events ended up in the wrong column. FastScout's 4-column layout is
    # "Time | LeftTeam | Score | RightTeam", and which side UWW is on depends on whether they're home or away
    # in that particular export -- it does NOT always match our assumed "uww_text" = column 2 convention.
    # Cross-reference extracted player names from each text column against the known UWW roster.
    def _extract_player_names(series):
        names = set()
        for text in series.dropna():
            parsed = classify_event(str(text).strip())
            if parsed.get("player"):
                names.add(parsed["player"])
        return names

    uww_col_players = _extract_player_names(raw_df["uww_text"])
    opp_col_players = _extract_player_names(raw_df["opp_text"])
    uww_in_uww_col = len(uww_col_players & uww_roster_names)
    uww_in_opp_col = len(opp_col_players & uww_roster_names)

    if uww_in_opp_col > uww_in_uww_col:
        # Columns are swapped: UWW events are in "opp_text" and opponent events in "uww_text".
        # Swap both text column VALUES and reverse the score format ("OppScore-UWWScore" -> "UWWScore-OppScore")
        # so build_pbp_events' defaults (self_column="uww_text", score group(1)=UWW) work correctly.
        raw_df["uww_text"], raw_df["opp_text"] = raw_df["opp_text"].copy(), raw_df["uww_text"].copy()
        raw_df["score_raw"] = raw_df["score_raw"].apply(
            lambda s: "-".join(reversed(str(s).strip().split("-"))) if pd.notna(s) and re.match(r"^\d+-\d+$", str(s).strip()) else s
        )
        print(f"  WARNING: Detected swapped columns for '{opponent_short}' (UWW roster found in right column) -- auto-corrected")

    # Date this game from its OWN filename, not from game_date_for() -- see
    # game_date_from_pbp_filename(). Without this, a rematch inherits the first meeting's date and
    # collapses into it in every groupby downstream.
    file_game_date = game_date_from_pbp_filename(path)
    if file_game_date is None:
        file_game_date = game_date_for(opponent_short)
        print(f"    WARNING: '{os.path.basename(path)}' has no '<m>_<d>_<yy> ' date prefix -- falling "
              f"back to the schedule's FIRST '{opponent_short}' meeting ({file_game_date}). If UWW "
              f"plays this opponent more than once, rename the file so the two games stay distinct.")
    events = build_pbp_events(raw_df, opponent_short, file_game_date)
    n_unclassified = (events["event_type"] == "unclassified").sum()
    print(f"  Parsed '{opponent_short}': {len(events)} events" + (f" ({n_unclassified} UNCLASSIFIED -- inspect raw_text)" if n_unclassified else ""))
    pbp_events_list.append(events)

pbp_events = pd.concat(pbp_events_list, ignore_index=True) if pbp_events_list else pd.DataFrame()

# CONFIRMED BUG (fixed here): pbp_files (above) is a pure filesystem glob with no reference_date awareness at
# all -- it picks up EVERY local "*_pbp.mhtml"/"*_pbp.html" file regardless of that game's date, so pbp_events
# (and everything built from it downstream: uww_pbp_box_score, uww_lineup_stints, the video-tagging attachment
# in the next section, scoring runs, clutch events...) silently included games on/after reference_date whenever
# local files for them already existed on disk. In normal usage (reference_date left at the real "today") this
# never shows up, since future games' PBP files genuinely don't exist yet -- but when reference_date is set
# earlier than the files actually available (e.g. simulating an earlier point in an already-completed season,
# exactly how this was caught), pbp_events ends up scoped to "every game with a local file" instead of "every
# game played so far," which threw off several season-average stats downstream (confirmed: UWW's own turnovers/
# game on the Upcoming Game page). Filtered here, once, at the source, rather than patching every downstream
# consumer individually. Keeps rows with no resolved game_date rather than dropping them -- an unresolved date
# is a different, separate problem (see game_date_for()) and silently discarding that data isn't the fix for it.
if not pbp_events.empty and "game_date" in pbp_events.columns:
    _pbp_events_before = len(pbp_events)
    pbp_events = pbp_events[pbp_events["game_date"].isna() | (pbp_events["game_date"] < reference_date.date())].reset_index(drop=True)
    _n_dropped = _pbp_events_before - len(pbp_events)
    if _n_dropped:
        print(f"Dropped {_n_dropped} pbp_events row(s) with a game_date on/after reference_date ({reference_date_str}) -- not yet \'played\' in this simulation.")

# Anything still unclassified is invisible in every downstream table now that it carries no player --
# so list the distinct raw strings here, which is what a new EVENT_PATTERNS entry gets written from.
if not pbp_events.empty and (pbp_events["event_type"] == "unclassified").any():
    _unc = pbp_events.loc[pbp_events["event_type"] == "unclassified", "raw_text"].value_counts()
    print(f"\n{int(_unc.sum())} unclassified event(s) across {len(_unc)} distinct string(s) -- "
          f"add a pattern to EVENT_PATTERNS for any of these that should be counted:")
    _show(_unc, rows=20)
else:
    print("\nEvery play-by-play line was classified.")

_show(pbp_events, rows=20)
