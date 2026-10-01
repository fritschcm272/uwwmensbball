# 24_find_opponent_games_before_they_played_uw.py -- code for the notebook section "Whitewater's own matchup date -- games strictly before that are what to check for existing"
# Runs inside the notebook via run_section("24_find_opponent_games_before_they_played_uw"); its settings are in that notebook cell.

if opp_schedule.empty:
    prev_games = pd.DataFrame(columns=["date", "game_date", "opponent", "outcome", "team_score", "opponent_score"])
else:
    # Whitewater's own matchup date -- games strictly before that are what to check for existing _pbp/_video
    # files (the opponent's games against teams other than Whitewater). Read this straight from UWW's OWN
    # schedule row (upcoming_game, already resolved above) rather than searching for a "vs Whitewater" row
    # inside the OPPONENT's own schedule -- confirmed by a live run: when opp_schedule comes from
    # team_schedules, that entry was already filtered (in Cell 4) to games strictly before reference_date,
    # which can exclude the Whitewater matchup itself if it falls ON OR AFTER reference_date from the
    # opponent's side (e.g. Elmhurst's Dec 2 game vs a Dec 1 reference_date) -- so searching for it inside
    # opp_schedule can come up empty even though the date is already known independently.
    whitewater_date = parse_schedule_date(upcoming_game["date"], uww_season_start_year)
    if whitewater_date is None:
        raise ValueError(f"Could not parse UW-Whitewater's own matchup date for {upcoming_opponent_short} from {upcoming_game['date']!r}.")

    # CONFIRMED BUG (fixed here): this only ever compared against whitewater_date -- the date UWW itself
    # plays this opponent -- with no consideration of reference_date at all. reference_date represents
    # "today" for the WHOLE scouting exercise, not just for UWW's own games (pbp_events already respects
    # this via its own reference_date filter) -- when reference_date falls BEFORE whitewater_date, which
    # is the normal case (you scout an opponent ahead of actually playing them), this let the opponent's
    # own games between reference_date and whitewater_date leak in as if they'd already happened.
    # Confirmed as the root cause of a real, reported case: reference_date set before Ripon's own season
    # had even started, and the app still showed real scoring-distribution numbers for Ripon -- every
    # opponent-scouting table downstream (pbp_events_upcoming, pbp_box_score_upcoming, the
    # player_profiles/team_totals overrides below, and the opponent-history halves of the Pace & Style /
    # Runs KTV cards) traces back to this one line. The cutoff is now whichever of the two dates is
    # EARLIER: the matchup itself, or "today".
    _prev_games_cutoff = min(whitewater_date, reference_date.date())
    prev_games = opp_schedule[opp_schedule["game_date"] < _prev_games_cutoff].reset_index(drop=True)
    print(f"{upcoming_opponent_short}'s games before facing UW-Whitewater on {whitewater_date}:")
    print(prev_games)
    if "video_url" in prev_games.columns:
        print("\nVideo links for these games (raw full-game film, independent of any manually-tagged _video.mhtml export):")
        for _, _pg_row in prev_games.iterrows():
            # game_date can come through as either datetime.date or datetime.datetime/Timestamp depending on
            # how opp_schedule was sourced -- pd.Timestamp(...) normalizes either into something .date() works
            # on, rather than assuming one specific type (confirmed by a live run: plain .date() raised
            # "'datetime.date' object has no attribute 'date'" here).
            print(f"  {pd.Timestamp(_pg_row['game_date']).date()} vs {_pg_row['opponent']}: {_pg_row['video_url'] or '(no video_url)'}")

    # Check for _pbp and _video files for each previous game. Filenames are "<m>_<d>_<yy> ..." (no leading zeros).
    missing_files = []
    for _, row in prev_games.iterrows():
        # "%-m"/"%-d" (no-leading-zero month/day) are a glibc-only strftime extension -- Windows' CRT
        # strftime rejects them outright with "ValueError: Invalid format string". Since this notebook runs
        # via Databricks Connect from a local Windows machine, build the no-leading-zero month/day manually
        # instead (plain int formatting has no platform-specific behavior), keeping "%y" (a portable, standard
        # strftime directive) for the 2-digit year.
        game_date_str = f"{row['game_date'].month}_{row['game_date'].day}_{row['game_date'].strftime('%y')}"
        # "_pbp.*" (not just "_pbp.mhtml") so this also finds this notebook's own live-scrape ".html" cache
        # (see _save_scraped_html in Cell 4), the same broad wildcard already used for "_video.*" below.
        pbp_pattern = f"{volume_dir}/{game_date_str}*{upcoming_opponent_short}*_pbp.*"
        video_pattern = f"{volume_dir}/{game_date_str}*{upcoming_opponent_short}*_video.*"
        pbp_files = glob.glob(pbp_pattern)
        video_files = glob.glob(video_pattern)
        if not pbp_files or not video_files:
            missing_files.append({
                "date": row["game_date"], "opponent": row["opponent"],
                "pbp_found": bool(pbp_files), "video_found": bool(video_files)
            })

    if missing_files:
        print("\nMissing _pbp or _video files for the following games before the Whitewater matchup:")
        for mf in missing_files:
            print(f"  {mf['date']} vs {mf['opponent']}: pbp_found={mf['pbp_found']}, video_found={mf['video_found']}")
    else:
        print("\nAll required _pbp and _video files found for the upcoming opponent's previous games before Whitewater.")
