# 20_identify_upcoming_opponent.py -- code for the notebook section "Identify the upcoming opponent from the schedule"
# Runs inside the notebook via run_section("20_identify_upcoming_opponent"); its settings are in that notebook cell.

# Identify the upcoming opponent from the schedule
# CONFIRMED BUG (fixed here): this assumed there's ALWAYS a row flagged "Upcoming" (a next game to
# prepare for), AND that whichever opponent it is always already has a scout report on file. Neither
# holds for a fully historical/archived season run: reference_date set after an already-played game
# (the normal way to mark a past game as "already happened") makes the SCHEDULE'S NEXT game "Upcoming"
# whether or not any data has actually been prepared for it -- and for an old, archived opponent there
# is no live version of their page left to auto-scrape a report from either. .iloc[0] on no "Upcoming"
# row raised IndexError; next() with no scouted_opponents match raised StopIteration. Both are now
# handled the same way the rest of this notebook already treats "not enough data yet" --
# upcoming_game/upcoming_opponent/upcoming_opponent_short fall back to None with a clear explanation,
# instead of crashing the whole run over what is actually a normal state for a purely historical load.
_upcoming_rows = schedule[schedule["Upcoming"] == "Yes"]
if _upcoming_rows.empty:
    print("No game on/after reference_date found in the schedule -- nothing to identify as \"upcoming\" "
          "(expected for a fully historical/archived season run). Downstream cells that rely on an "
          "upcoming opponent will be skipped or come back empty rather than crash.")
    upcoming_game = None
    upcoming_opponent = None
    upcoming_opponent_short = None
else:
    upcoming_game = _upcoming_rows.iloc[0]
    upcoming_opponent = upcoming_game["opponent"]
    upcoming_opponent_short = next(
        (s for s in scouted_opponents if re.search(re.escape(s), upcoming_opponent, re.IGNORECASE)), None
    )
    if upcoming_opponent_short is None:
        # CONFIRMED BUG (fixed here): leaving this as None switched OFF the entire upcoming-game
        # pipeline, not just the scouting-report parts of it. upcoming_opponent_short is the key every
        # downstream cell keys on -- opp_team_schedule, prev_games, the "_pbp"/"_video" glob patterns,
        # pbp_events_upcoming's self_team label, the player_profiles and team_totals PBP overrides -- so
        # None meant no opponent season leaders and no opponent team stats either, even though NONE of
        # that data comes from a scouting report: it is all reconstructed from the opponent's own
        # play-by-play. Reported live with before_scout="yes": the Stats & Analysis page came up blank.
        #
        # Having no report for the next opponent is a NORMAL state, not a failure -- it is every
        # opponent's state until their report gets built, and it is exactly what before_scout="yes"
        # reproduces on purpose. Fall back to the schedule's own opponent text as the short name. That
        # is the same string the auto-downloader builds scout/pbp filenames from (see
        # _download_matching_scout_pdf's `matchup`), so the glob patterns downstream still match. When a
        # report DOES exist, the scouted_opponents match above still wins, so nothing changes.
        upcoming_opponent_short = upcoming_opponent
        print(f"No scout report on file for the next scheduled opponent ({upcoming_opponent}) -- using "
              f"the schedule's own name for them as the short name, so their prior-game PBP (season "
              f"leaders, team stats, lineups) is still built. Only the scouting-report-sourced output "
              f"(game plan, keys to victory, player notes, tag-based comparisons) will be missing.")
