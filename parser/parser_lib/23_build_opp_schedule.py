# 23_build_opp_schedule.py -- code for the notebook section "team_schedules (built in Cell 4 from the live scrape/MHTML) already carries each game's Fa"
# Runs inside the notebook via run_section("23_build_opp_schedule"); its settings are in that notebook cell.

if opp_team_schedule is not None:
    opp_schedule = pd.DataFrame()
    opp_schedule["date"] = opp_team_schedule["date"]
    opp_schedule["game_date"] = opp_schedule["date"].apply(parse_schedule_date)
    opp_schedule["opponent"] = opp_team_schedule["opponent"]
    opp_schedule["outcome"] = opp_team_schedule["outcome"]
    opp_schedule["team_score"] = opp_team_schedule["team_score"]
    opp_schedule["opponent_score"] = opp_team_schedule["opponent_score"]
    # team_schedules (built in Cell 4 from the live scrape/MHTML) already carries each game's FastScout/Synergy
    # links straight from that row's own <a href> tags -- confirmed by the user: video_url is a direct link to
    # that game's full film on Synergy (e.g. "https://editor-web.synergysports.com/video?playlistUrl=...").
    # Carry it through here (dropped in the manual column selection above) so prev_games below exposes a
    # clickable video link per prior game even when no separately-exported/tagged "_video.mhtml" file exists.
    opp_schedule["video_url"] = opp_team_schedule["video_url"]
    opp_schedule["game_url"] = opp_team_schedule["game_url"]
    # Needed to build an accurate "<Away> @ <Home>" matchup string for live-scrape cache filenames below
    # (mirrors the same location-based matchup naming already used for scout-report downloads in Cell 4).
    opp_schedule["location"] = opp_team_schedule["location"]
elif upcoming_opponent is None or upcoming_opponent_short is None:
    # CONFIRMED BUG (fixed here): _schedule_file_for() calls .lower() on both of these unconditionally --
    # they can now legitimately be None (see the "Identify the upcoming opponent" cell), which raised
    # AttributeError. Same fallback the rest of this notebook already uses for "no upcoming opponent".
    print("No upcoming opponent identified (or no scout report on file for them) -- skipping opponent "
          "schedule parsing and prior-game pbp analysis.")
    opp_schedule = pd.DataFrame(columns=["date", "game_date", "opponent", "outcome", "team_score", "opponent_score"])
else:
    # team_schedules truly has no entry for this opponent (e.g. it wasn't in UWW's own scouted schedule at
    # all this run) -- fall back to the old local "<Team> - Schedule.mhtml" backup file lookup.
    opp_schedule_path = _schedule_file_for(upcoming_opponent, upcoming_opponent_short, volume_dir)
    if not os.path.exists(opp_schedule_path):
        print(f"WARNING: Opponent schedule file not found: {opp_schedule_path}")
        print(f"    Upload '{upcoming_opponent_short} - Schedule.mhtml' to enable full scouting analysis.")
        print(f"    Skipping opponent schedule parsing and prior-game pbp analysis for {upcoming_opponent_short}.")
        opp_schedule = pd.DataFrame(columns=["date", "game_date", "opponent", "outcome", "team_score", "opponent_score"])
    else:
        opp_html = load_html_snapshot(opp_schedule_path)
        opp_schedule_raw = pd.read_html(StringIO(str(BeautifulSoup(opp_html, "lxml").find_all("table")[0])))[0]

        opp_schedule = pd.DataFrame()
        opp_schedule["date"] = opp_schedule_raw["Date"]
        opp_schedule["game_date"] = opp_schedule["date"].apply(parse_schedule_date)
        opp_schedule["opponent"] = opp_schedule_raw["Opponent"].apply(lambda x: split_opponent(x)[0])
        res_split = opp_schedule_raw["Result"].apply(split_result)
        opp_schedule["outcome"] = res_split.apply(lambda x: x[0])
        opp_schedule["team_score"] = res_split.apply(lambda x: x[1])
        opp_schedule["opponent_score"] = res_split.apply(lambda x: x[2])
