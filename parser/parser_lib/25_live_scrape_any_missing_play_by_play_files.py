# 25_live_scrape_any_missing_play_by_play_files.py -- code for the notebook section "Determine which raw column ("uww_text" or "opp_text") actually holds THIS opponent's own e"
# Runs inside the notebook via run_section("25_live_scrape_any_missing_play_by_play_files"); its settings are in that notebook cell.

if not opp_schedule.empty:
    # Determine which raw column ("uww_text" or "opp_text") actually holds THIS opponent's own events for each pbp
    # file -- FastScout puts the exporting team's events in a fixed column regardless of home/away, but WHICH
    # column that is depends on whose account captured the snapshot. Resolve it per file by matching known
    # roster player names instead of assuming.
    known_names = set(player_profiles.loc[player_profiles["opponent"] == upcoming_opponent_short, "name"].dropna())

    def resolve_self_column(raw_df, known_names):
        uww_matches = sum(any(name in str(t) for name in known_names) for t in raw_df["uww_text"].dropna())
        opp_matches = sum(any(name in str(t) for name in known_names) for t in raw_df["opp_text"].dropna())
        if uww_matches or opp_matches:
            return "uww_text" if uww_matches >= opp_matches else "opp_text"

        # Neither column matched a single known name. The usual cause is that known_names is EMPTY --
        # it's built from player_profiles, which is built from scouting reports, so an opponent with no
        # report on file (the normal pre-scout state, and what before_scout="yes" reproduces) has none.
        # The old code returned "uww_text" here purely because 0 >= 0, silently assigning this
        # opponent's events to whichever column happened to be first. Read the table's own header
        # instead -- it names both teams (see parse_pbp_html).
        _rsc_labels = raw_df.attrs.get("column_teams") or {}
        _rsc_target = str(upcoming_opponent_short or "").strip().casefold()
        _rsc_first_word = _rsc_target.split()[0] if _rsc_target else ""
        for _rsc_col in ("uww_text", "opp_text"):
            _rsc_label = str(_rsc_labels.get(_rsc_col) or "").strip().casefold()
            if not _rsc_label:
                continue
            if _rsc_target and (_rsc_target in _rsc_label or _rsc_label in _rsc_target
                                or (_rsc_first_word and _rsc_first_word in _rsc_label)):
                return _rsc_col
        print(f"  WARNING: could not tell which play-by-play column holds {upcoming_opponent_short}'s "
              f"own events -- no roster names to match (no scouting report on file) and the table's "
              f"header columns ({_rsc_labels}) don't name them either. Defaulting to 'uww_text'; if "
              f"this game's numbers look like they belong to the other team, that's why.")
        return "uww_text"

    # Find which prior games are missing a local "_pbp.mhtml" file AND have a usable "game_url" to live-scrape
    # instead (only present when opp_schedule was sourced from team_schedules -- see above).
    games_needing_live_pbp = []
    for _, row in prev_games.iterrows():
        game_date_str = f"{row['game_date'].month}_{row['game_date'].day}_{row['game_date'].strftime('%y')}"
        pbp_pattern = f"{volume_dir}/{game_date_str}*{upcoming_opponent_short}*_pbp.*"
        if not glob.glob(pbp_pattern) and "game_url" in row.index and pd.notna(row.get("game_url")):
            games_needing_live_pbp.append(row)

    # Confirmed by the user: a game's own play-by-play page is reachable via a small path change to its
    # "game_url" (see scrape_pbp_live() in the pbp-parsing cell above) -- live-scrape it for any prior game
    # missing a local "_pbp.mhtml" file, the same live-scrape-with-fallback pattern Cell 4 already uses for
    # schedules and scout reports. One shared session covers every game that needs this, rather than opening
    # a new browser per game.
    live_pbp_by_game = {}
    if games_needing_live_pbp and fastscout_username and fastscout_password:
        # One run_in_fastscout_session call PER GAME (not one call looping over all games) -- run_in_fastscout_
        # session's own retry-on-dead-session logic (Cell 4) can only kick in on a call it directly wraps, so
        # if every game were scraped inside a single call, a mid-batch dead browser/driver would silently fail
        # every remaining game with no chance to self-heal. Reuses the ONE shared FastScout Playwright session
        # (opened lazily on first use) instead of opening its own separate browser+thread per game.
        for g_row in games_needing_live_pbp:
            try:
                # Same location-based "<Away> @ <Home>" matchup naming as scout-report downloads (Cell 4) and
                # the video-clip cache below, so the saved file matches the manually-uploaded naming
                # convention closely enough for the glob patterns above to find it on a future run.
                g_date_str = f"{g_row['game_date'].month}_{g_row['game_date'].day}_{g_row['game_date'].strftime('%y')}"
                if str(g_row.get("location", "")).strip().lower() == "home":
                    matchup = f"{g_row['opponent']} @ {upcoming_opponent_short}"
                else:
                    matchup = f"{upcoming_opponent_short} @ {g_row['opponent']}"
                pbp_save_path = f"{volume_dir}/{g_date_str} {matchup}_pbp.html"
                live_pbp_by_game[g_row["game_date"]] = run_in_fastscout_session(
                    lambda page, url=g_row["game_url"], sp=pbp_save_path: scrape_pbp_live(page, url, save_path=sp)
                )
            except Exception as pbp_scrape_error:
                print(f"  Could not live-scrape pbp for {g_row['opponent']} ({g_row['game_url']}): {type(pbp_scrape_error).__name__}: {pbp_scrape_error}")

else:
    # CONFIRMED BUG (fixed here): known_names is only ever defined inside the branch above -- when
    # opp_schedule is empty (no upcoming opponent identified, or no scout report on file for them), it
    # never gets assigned at all, and a later cell (the shot-tendency breakdown) reading it raised
    # "NameError: name 'known_names' is not defined". A well-formed empty fallback here, matching the
    # pattern already used elsewhere in this notebook (e.g. pbp_events_upcoming's own empty fallback).
    known_names = set()
