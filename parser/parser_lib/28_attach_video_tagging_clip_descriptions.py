# 28_attach_video_tagging_clip_descriptions.py -- code for the notebook section "Attach video-tagging clip descriptions onto pbp_events_upcoming, same method as pbp_events"
# Runs inside the notebook via run_section("28_attach_video_tagging_clip_descriptions"); its settings are in that notebook cell.

# --- Attach video-tagging clip descriptions onto pbp_events_upcoming, same method as pbp_events uses --------
# Reuses parse_video_mhtml / expand_clip_to_subevents / global_align / RESULT_TO_KEY / FREE_THROW_EVENT_TYPES
# from the cell above. Only the per-game team resolution differs here: these are the opponent's OWN games
# against a VARYING actual opponent each time, not always UW-Whitewater vs a fixed opponent, and there's no
# lineup reconstruction for these games.
video_desc_col = pd.Series(index=pbp_events_upcoming.index, dtype=object)
video_result_col = pd.Series(index=pbp_events_upcoming.index, dtype=object)
video_player_col = pd.Series(index=pbp_events_upcoming.index, dtype=object)
video_clip_number_col = pd.Series(index=pbp_events_upcoming.index, dtype=float)

# Same Windows strftime portability fix used in the opponent-schedule cell above -- "%-m"/"%-d" (no-leading-
# zero month/day) aren't supported by Windows' CRT strftime.
def _game_date_str(game_date):
    return f"{game_date.month}_{game_date.day}_{game_date.strftime('%y')}"


# Find which prior games are missing a local "_video.*" file AND have a usable "video_url" to live-scrape
# instead (only present when opp_schedule was sourced from team_schedules -- see the opponent-schedule cell).
games_needing_live_video = []
for _, row in prev_games.iterrows():
    video_matches = glob.glob(f"{volume_dir}/{_game_date_str(row['game_date'])}*{upcoming_opponent_short}*_video.*")
    if not video_matches and "video_url" in row.index and pd.notna(row.get("video_url")):
        # Pages that failed recently aren't retried every run (see VIDEO_SCRAPE_RETRY_DAYS in the helpers cell).
        if video_scrape_recently_failed(row["video_url"]) is not None:
            print(f"  Skipping {row['opponent']} ({row['game_date']}): its clip page failed to scrape within the last "
                  f"{VIDEO_SCRAPE_RETRY_DAYS} day(s) (see _video_scrape_failures.csv).")
            continue
        games_needing_live_video.append(row)

# Confirmed by the user: a game's own video-clip tagging table renders directly at its "video_url" (see
# scrape_video_clips_live() in the video-tagging helpers cell above) -- live-scrape it for any prior game
# missing a local "_video.mhtml" file, the same live-scrape-with-fallback pattern Cell 4 already uses for
# schedules and scout reports. One shared session covers every game that needs this.
live_clips_by_game = {}
if games_needing_live_video and fastscout_username and fastscout_password:
    # One run_in_fastscout_session call PER GAME (not one call looping over all games) -- run_in_fastscout_
    # session's own retry-on-dead-session logic (Cell 4) can only kick in on a call it directly wraps, so if
    # every game were scraped inside a single call, a mid-batch dead browser/driver would silently fail every
    # remaining game with no chance to self-heal. Reuses the ONE shared FastScout Playwright session (opened
    # lazily on first use) instead of opening its own separate browser+thread per game.
    for g_row in games_needing_live_video:
        try:
            # Same location-based "<Away> @ <Home>" matchup naming as scout-report downloads (Cell 4) and
            # the pbp cache above, so the saved file matches the manually-uploaded naming convention closely
            # enough for the glob pattern above to find it on a future run.
            g_date_str = _game_date_str(g_row["game_date"])
            if str(g_row.get("location", "")).strip().lower() == "home":
                matchup = f"{g_row['opponent']} @ {upcoming_opponent_short}"
            else:
                matchup = f"{upcoming_opponent_short} @ {g_row['opponent']}"
            video_save_path = f"{volume_dir}/{g_date_str} {matchup}_video.html"
            live_clips_by_game[g_row["game_date"]] = run_in_fastscout_session(
                lambda page, url=g_row["video_url"], sp=video_save_path: scrape_video_clips_live(page, url, save_path=sp)
            )
            video_scrape_log(g_row["video_url"], matchup)
        except Exception as video_scrape_error:
            video_scrape_log(g_row["video_url"], str(g_row.get("opponent")), f"{type(video_scrape_error).__name__}: {video_scrape_error}")
            print(f"  Could not live-scrape video clips for {g_row['opponent']} ({g_row['video_url']}): {type(video_scrape_error).__name__}: {video_scrape_error}")

games_with_video = []
# Per-game accounting for why a prior game ends up with no tagged shots. Every skip below used to be a bare
# `continue`, so a game that produced nothing looked identical to a game that was never on the schedule --
# and the app could only report how many games DID have tagged video, never which ones didn't or why.
video_status_rows = []
for _, row in prev_games.iterrows():
    video_matches = glob.glob(f"{volume_dir}/{_game_date_str(row['game_date'])}*{upcoming_opponent_short}*_video.*")
    actual_opponent = row["opponent"]
    game_mask = (pbp_events_upcoming["opponent"] == actual_opponent) & (pbp_events_upcoming["game_date"] == row["game_date"])
    _vs_row = {
        "game_date": row["game_date"], "vs": actual_opponent,
        "video_file": os.path.basename(video_matches[0]) if video_matches else ("(live-scraped)" if row["game_date"] in live_clips_by_game else ""),
        "pbp_rows": int(game_mask.sum()), "clips": 0, "matched": 0, "why": "",
    }
    if video_matches:
        clips = parse_video_mhtml_cached(video_matches[0])
    elif row["game_date"] in live_clips_by_game:
        clips = live_clips_by_game[row["game_date"]]
    else:
        # No local "<m>_<d>_<yy>*<Opponent>*_video.*" file, and either no video_url on the schedule row or
        # the live scrape failed. Note that the glob needs BOTH the no-leading-zero date and the opponent's
        # short name in the filename -- "01_10_26 ..." or a file named with their full name won't be found.
        _vs_row["why"] = "no _video file found and no live scrape"
        video_status_rows.append(_vs_row)
        continue
    if _vs_row["pbp_rows"] == 0:
        # Clips exist but there are no play-by-play rows to hang them on: the _pbp file is missing for this
        # game, or its opponent string doesn't match this schedule row's spelling.
        _vs_row["clips"] = len(clips)
        _vs_row["why"] = "no pbp events for this game (missing _pbp file, or opponent name mismatch)"
        video_status_rows.append(_vs_row)
        continue
    total_clips_n = len(clips)

    opp_all_events = pbp_events_upcoming[game_mask]
    player_team_lookup = opp_all_events.dropna(subset=["player"]).drop_duplicates("player").set_index("player")["team"]
    known_teams = set(player_team_lookup.unique())
    known_players = set(player_team_lookup.index)

    def normalize_player_name(name):
        if name in known_players:
            return name
        for p in known_players:
            if p.casefold() == str(name).casefold():
                return p
        return name

    def committing_team_for(fouled_player):
        fouled_team = player_team_lookup.get(fouled_player)
        others = known_teams - {fouled_team}
        return next(iter(others)) if len(others) == 1 else None

    subevent_rows = []
    for _, clip_row in clips.iterrows():
        clip_player = normalize_player_name(clip_row["player"])
        for event_type in expand_clip_to_subevents(clip_row):
            match_key = committing_team_for(clip_player) if event_type == "foul" else clip_player
            subevent_rows.append({
                "match_key": match_key, "event_type": event_type,
                "Description": clip_row["Description"], "video_result": clip_row["Result"],
                "video_clip_player": clip_player, "video_clip_number": clip_row["No."],
            })
    matchable_clips = pd.DataFrame(
        subevent_rows, columns=["match_key", "event_type", "Description", "video_result", "video_clip_player", "video_clip_number"]
    ).sort_values("video_clip_number").reset_index(drop=True)

    target_event_types = {"made_shot", "missed_shot", "turnover", "foul"} | FREE_THROW_EVENT_TYPES
    opp_events = pbp_events_upcoming[game_mask & pbp_events_upcoming["event_type"].isin(target_event_types)].sort_values("event_order").copy()
    opp_events["match_event_type"] = opp_events["event_type"].where(~opp_events["event_type"].isin(FREE_THROW_EVENT_TYPES), "free_throw")
    opp_events["match_key"] = opp_events["team"].where(opp_events["event_type"] == "foul", opp_events["player"])
    total_pbp_n = pbp_events_upcoming.loc[game_mask, "event_order"].max()

    pbp_orig_index = opp_events.index.tolist()
    pbp_list = [
        {"event_order": r["event_order"], "match_event_type": r["match_event_type"], "match_key": r["match_key"]}
        for _, r in opp_events.iterrows()
    ]
    video_list = matchable_clips.to_dict("records")
    n, m = len(pbp_list), len(video_list)

    def compatible(i, j):
        p, v = pbp_list[i], video_list[j]
        return p["match_event_type"] == v["event_type"] and p["match_key"] == v["match_key"]

    def pos_cost(i, j):
        return abs(pbp_list[i]["event_order"] / total_pbp_n - video_list[j]["video_clip_number"] / total_clips_n)

    pairs = global_align(n, m, compatible, pos_cost)
    for i, j in pairs.items():
        orig_idx = pbp_orig_index[i]
        v = video_list[j]
        video_desc_col.loc[orig_idx] = v["Description"]
        video_result_col.loc[orig_idx] = v["video_result"]
        video_player_col.loc[orig_idx] = v["video_clip_player"]
        video_clip_number_col.loc[orig_idx] = v["video_clip_number"]

    games_with_video.append(actual_opponent)
    _vs_row.update({"clips": total_clips_n, "matched": len(pairs),
                    "why": "" if pairs else "clips found but none aligned to a pbp event"})
    video_status_rows.append(_vs_row)
    print(f"  {actual_opponent}: matched {len(pairs)}/{len(pbp_list)} eligible pbp events to {len(video_list)} video sub-events ({total_clips_n} clips)")

pbp_events_upcoming["video_description"] = video_desc_col
pbp_events_upcoming["video_result"] = video_result_col
pbp_events_upcoming["video_player"] = video_player_col
pbp_events_upcoming["video_clip_number"] = video_clip_number_col

# One table answering "which of their prior games actually contributed tagged shots, and why not the rest".
video_status = pd.DataFrame(video_status_rows)
if not video_status.empty:
    _n_ok = int((video_status["matched"] > 0).sum())
    print(f"\nTagged-video coverage for {upcoming_opponent_short}: {_n_ok} of {len(prev_games)} game(s) "
          f"before facing UWW contributed tagged shots.")
    print(video_status.to_string(index=False))
    _gaps = video_status[video_status["why"] != ""]
    if not _gaps.empty:
        print(f"\n{len(_gaps)} game(s) contributed nothing -- reasons above. The most common cause is a "
              f"filename the glob can't see: it needs BOTH the no-leading-zero date "
              f"(\"1_10_26\", not \"01_10_26\") and \"{upcoming_opponent_short}\" in the name, "
              f"e.g. \"1_10_26 {upcoming_opponent_short} @ Coe_video.mhtml\".")

print(f"\nGames with a video-tagging file: {games_with_video}")
print(f"pbp_events_upcoming rows with a matched video description: {pbp_events_upcoming['video_description'].notna().sum()} of {len(pbp_events_upcoming)}")
if not pbp_events_upcoming.empty:
    print(pbp_events_upcoming[pbp_events_upcoming["video_description"].notna()].head(20))
else:
    print("WARNING: No opponent prior-game events to display (opponent schedule file not loaded).")
