# 26_parse_play_by_play_events_for_opponent.py -- code for the notebook section "Run play-by-play parsing for the upcoming opponent's previous games"
# Runs inside the notebook via run_section("26_parse_play_by_play_events_for_opponent"); its settings are in that notebook cell.

if opp_schedule.empty:
    pbp_events_upcoming = pd.DataFrame(columns=[
        "opponent", "game_date", "event_order", "period", "time_remaining",
        "time_remaining_seconds", "team", "event_type", "raw_text",
        "uww_score", "opp_score", "player", "shot_type", "shot_desc",
        "turnover_type", "foul_type", "ft_num", "ft_total"
    ])
else:
    # Run play-by-play parsing for the upcoming opponent's previous games
    pbp_events_list = []
    for _, row in prev_games.iterrows():
        # Same Windows strftime portability fix as above -- "%-m"/"%-d" aren't supported by Windows' CRT.
        game_date_str = f"{row['game_date'].month}_{row['game_date'].day}_{row['game_date'].strftime('%y')}"
        pbp_pattern = f"{volume_dir}/{game_date_str}*{upcoming_opponent_short}*_pbp.*"
        pbp_files = glob.glob(pbp_pattern)
        raw_dfs = [parse_pbp_mhtml(path) for path in pbp_files]
        if not raw_dfs and row["game_date"] in live_pbp_by_game:
            raw_dfs = [live_pbp_by_game[row["game_date"]]]
        for raw_df in raw_dfs:
            self_column = resolve_self_column(raw_df, known_names)
            # `self_team`/`self_column` = the upcoming opponent's own events (whichever raw column actually has
            # their players); `opponent` = row["opponent"] -- whoever they actually played in THIS game, NOT
            # literally "UW-Whitewater", since Whitewater isn't in these games at all.
            events = build_pbp_events(
                raw_df, row["opponent"], row["game_date"], self_team=upcoming_opponent_short, self_column=self_column
            )
            pbp_events_list.append(events)

    # CONFIRMED BUG (fixed here): a bare pd.DataFrame() has ZERO columns, unlike the well-formed empty
    # fallback in the "opp_schedule.empty" branch above -- so if prev_games was non-empty but EVERY one of
    # those games failed to produce PBP data (no local _pbp file, and not in live_pbp_by_game either -- e.g.
    # an opponent whose games are so early in the season that this data simply isn't available yet), the
    # resulting pbp_events_upcoming had no "opponent" column at all, and the very next cell's
    # pbp_events_upcoming["opponent"] lookup crashed with KeyError: 'opponent' instead of just being empty.
    _PBP_EVENTS_UPCOMING_COLS = [
        "opponent", "game_date", "event_order", "period", "time_remaining",
        "time_remaining_seconds", "team", "event_type", "raw_text",
        "uww_score", "opp_score", "player", "shot_type", "shot_desc",
        "turnover_type", "foul_type", "ft_num", "ft_total",
    ]
    pbp_events_upcoming = (
        pd.concat(pbp_events_list, ignore_index=True) if pbp_events_list
        else pd.DataFrame(columns=_PBP_EVENTS_UPCOMING_COLS)
    )
    if not pbp_events_list:
        print(f"  No PBP data found/scraped for any of {upcoming_opponent_short}'s {len(prev_games)} game(s) before UWW -- pbp_events_upcoming is empty but well-formed.")
    _show(pbp_events_upcoming, rows=20)
