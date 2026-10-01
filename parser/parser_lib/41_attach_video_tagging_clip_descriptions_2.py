# 41_attach_video_tagging_clip_descriptions_2.py -- code for the notebook section "Attach video-tagging clip descriptions ("*_video.mhtml") onto pbp_events -----------------"
# Runs inside the notebook via run_section("41_attach_video_tagging_clip_descriptions_2"); its settings are in that notebook cell.

# --- Attach video-tagging clip descriptions ("*_video.mhtml") onto pbp_events ---------------------------------
# The video-tagging export logs one row per CLIP, with a chained action "Description" (e.g. "3 Seth Bunders >
# Off Screen > ... > Miss 3 Pts") -- one row per POSSESSION-ENDING action, not one row per raw play-by-play
# event, and it carries no game-clock/timestamp. So there's no direct key to join on. Instead, run ONE global
# order-preserving (monotonic) alignment across the whole opponent's clip log against the whole list of
# attempted pbp events at once, using compatible() as a hard gate (event_type + player/team match, plus an
# on-court lineup check for fouls) and maximizing the total number of matches.
# RESULT_TO_KEY, AND1_SHOT_RE, FREE_THROW_EVENT_TYPES, expand_clip_to_subevents, global_align, and
# parse_video_mhtml are reused from the "Shared video-tagging helper functions" cell above.

def _game_date_str(game_date):
    return f"{game_date.month}_{game_date.day}_{game_date.strftime('%y')}"

# CONFIRMED BUG (fixed here): this cell used to align every "*_video" file found on disk against
# pbp_events regardless of date, including games on/after reference_date. pbp_events itself is already
# restricted to game_date < reference_date (see the "Play-by-play (PBP) data" cell), so a
# post-reference-date video file's own game simply isn't in pbp_events to align against -- that's more
# than wasted work, too: if UWW plays the SAME opponent twice (once before reference_date, once after),
# the date-scoped game_mask below finds no rows for the post-reference-date file and silently falls
# back to aligning its clips against the OTHER, earlier meeting's events instead -- misattributing an
# entire game's worth of video clips to the wrong game. Dropping post-reference-date files up front
# avoids that. A file with no parseable date is kept (same "can't tell, so don't guess" stance the
# WARNING branch further down already takes for ambiguous dates) -- only a CONFIRMED on/after-date file
# gets dropped.
def _drop_post_reference_date_videos(files):
    dated = [(f, game_date_from_pbp_filename(f.replace("_video.", "_pbp."))) for f in files]
    kept = [f for f, d in dated if d is None or d < reference_date.date()]
    n_dropped = len(files) - len(kept)
    if n_dropped:
        print(f"Skipping {n_dropped} video-tagging file(s) dated on/after reference_date ({reference_date_str}).")
    return kept

_t_attach_start = time.time()
video_files = sorted(glob.glob(f"{volume_dir}/*_video.mhtml") + glob.glob(f"{volume_dir}/*_video.html"))
video_files = _drop_post_reference_date_videos(video_files)

# Live-scrape+cache any scouted UWW game missing a local video-tagging file, using its "video_url" from
# uww_team_schedule -- same pattern as the opponent-prior-games video cell above.
games_needing_live_uww_video = []
_n_recent_fail = 0
if not uww_team_schedule.empty:
    for _, g_row in uww_team_schedule.iterrows():
        g_date = parse_schedule_date(g_row["date"], uww_season_start_year) if pd.notna(g_row.get("date")) else None
        if g_date is None or pd.isna(g_row.get("video_url")):
            continue
        # CONFIRMED BUG (fixed): games not played yet as of reference_date were scraped too. Their clip pages
        # have no clips, so every run waited out the page timeouts on each one -- and any file they did
        # produce was dropped by _drop_post_reference_date_videos anyway.
        if pd.Timestamp(g_date) >= reference_date:
            continue
        opp_short = next(
            (s for s in scouted_opponents if re.search(re.escape(s), str(g_row["opponent"]), re.IGNORECASE)), None
        )
        if opp_short is None or glob.glob(f"{volume_dir}/{_game_date_str(g_date)}*{opp_short}*_video.*"):
            continue
        if video_scrape_recently_failed(g_row["video_url"]) is not None:
            _n_recent_fail += 1
            continue
        games_needing_live_uww_video.append((g_row, g_date, opp_short))
if _n_recent_fail:
    print(f"Skipping {_n_recent_fail} UWW clip page(s) that failed to scrape in the last {VIDEO_SCRAPE_RETRY_DAYS} "
          f"day(s) (see _video_scrape_failures.csv; delete it to retry now).")

if games_needing_live_uww_video and fastscout_username and fastscout_password:
    for g_row, g_date, opp_short in games_needing_live_uww_video:
        try:
            if str(g_row.get("location", "")).strip().lower() == "home":
                matchup = f"{g_row['opponent']} @ UW-Whitewater"
            else:
                matchup = f"UW-Whitewater @ {g_row['opponent']}"
            video_save_path = f"{volume_dir}/{_game_date_str(g_date)} {matchup}_video.html"
            _t0 = time.time()
            run_in_fastscout_session(
                lambda page, url=g_row["video_url"], sp=video_save_path: scrape_video_clips_live(page, url, save_path=sp)
            )
            video_scrape_log(g_row["video_url"], matchup)
            print(f"  Scraped clip page for {matchup} ({time.time() - _t0:.0f}s)")
        except Exception as video_scrape_error:
            video_scrape_log(g_row["video_url"], str(g_row.get("opponent")), f"{type(video_scrape_error).__name__}: {video_scrape_error}")
            print(f"  Could not live-scrape UWW's own video clips for {g_row['opponent']} ({g_row['video_url']}): {type(video_scrape_error).__name__}: {video_scrape_error}")

    # Re-glob so the freshly-cached ".html" file(s) are picked up by the alignment loop below.
    video_files = sorted(glob.glob(f"{volume_dir}/*_video.mhtml") + glob.glob(f"{volume_dir}/*_video.html"))
    video_files = _drop_post_reference_date_videos(video_files)
elif games_needing_live_uww_video:
    print(
        f"{len(games_needing_live_uww_video)} scouted UWW game(s) are missing a local '_video' file and could "
        "be live-scraped, but no FASTSCOUT_USERNAME/FASTSCOUT_PASSWORD were found -- skipping."
    )

_t_scrape_done = time.time()
# CONFIRMED BUG (fixed): the glob above also finds OTHER teams' games (the opponent prior-game files, e.g.
# "UW-Stout @ UW-La Crosse"), which belong to the opponent cell earlier. Here they were read as a game against
# the first-named team and, when the date didn't match a UWW game, aligned against UWW's real game(s) with
# that team -- wasted time and the wrong game's clips. Only files that include UW-Whitewater are used here.
_other_team_files = [f for f in video_files if "UW-Whitewater" not in os.path.basename(f)]
if _other_team_files:
    print(f"Skipping {len(_other_team_files)} video file(s) for games UWW didn't play in (handled by the "
          f"opponent prior-games cell).")
video_files = [f for f in video_files if "UW-Whitewater" in os.path.basename(f)]
print(f"Found {len(video_files)} video-tagging file(s):")
for f in video_files:
    print(" -", os.path.basename(f))

video_desc_col = pd.Series(index=pbp_events.index, dtype=object)
video_result_col = pd.Series(index=pbp_events.index, dtype=object)
video_player_col = pd.Series(index=pbp_events.index, dtype=object)
video_clip_number_col = pd.Series(index=pbp_events.index, dtype=float)

# CONFIRMED_CLIP_EVENT_OVERRIDES is reused from the "Shared video-tagging helper functions" cell above.
opponents_with_video = []
for path in video_files:
    # Home/away-aware extraction (mirrors opponent_from_pbp_filename above); matches ".mhtml" or ".html".
    _vname = re.sub(r"_video\.(mhtml|html)$", "", os.path.basename(path), flags=re.IGNORECASE)
    _vname = re.sub(r"^\d+_\d+_\d+\s+", "", _vname)
    if " @ " in _vname:
        _left, _right = [side.strip() for side in _vname.split(" @ ", 1)]
        opponent_short = _right if _left == "UW-Whitewater" else _left
    else:
        opponent_short = _vname
    opponents_with_video.append(opponent_short)
    # A video file covers ONE game. Scope the alignment to that game (by its own filename date), or a
    # rematch's clips get aligned against both meetings' events at once.
    video_game_date = game_date_from_pbp_filename(path.replace("_video.", "_pbp."))
    clips = parse_video_mhtml_cached(path)
    total_clips_n = len(clips)

    game_mask = pbp_events["opponent"] == opponent_short
    if video_game_date is not None and (game_mask & (pbp_events["game_date"] == video_game_date)).any():
        game_mask &= pbp_events["game_date"] == video_game_date
    elif video_game_date is not None and game_mask.any():
        # CONFIRMED BUG (fixed): a dated file with no UWW game against that team on that date used to fall
        # through and be aligned against whatever other meeting(s) exist -- the wrong game's clips.
        print(f"    Skipping '{os.path.basename(path)}': no UWW play-by-play vs {opponent_short} on {video_game_date}.")
        continue
    elif pbp_events.loc[game_mask, "game_date"].nunique() > 1:
        print(f"    WARNING: '{os.path.basename(path)}' has no usable date prefix but "
              f"{opponent_short} has {pbp_events.loc[game_mask, 'game_date'].nunique()} games -- "
              f"clips will be aligned across all of them.")
    opp_all_events = pbp_events[game_mask]
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
    )

    target_event_types = {"made_shot", "missed_shot", "turnover", "foul"} | FREE_THROW_EVENT_TYPES
    opp_events = pbp_events[game_mask & pbp_events["event_type"].isin(target_event_types)].sort_values("event_order").copy()
    opp_events["match_event_type"] = opp_events["event_type"].where(
        ~opp_events["event_type"].isin(FREE_THROW_EVENT_TYPES), "free_throw"
    )
    opp_events["match_key"] = opp_events["team"].where(opp_events["event_type"] == "foul", opp_events["player"])
    total_pbp_n = pbp_events.loc[game_mask, "event_order"].max()

    matchable_clips = matchable_clips.sort_values("video_clip_number").reset_index(drop=True)
    opp_events = opp_events.sort_values("event_order")
    pbp_orig_index = opp_events.index.tolist()

    pbp_list = []
    for _, row in opp_events.iterrows():
        uww_set = set(row["uww_lineup"].split(", ")) if pd.notna(row["uww_lineup"]) else None
        opp_set = set(row["opp_lineup"].split(", ")) if pd.notna(row["opp_lineup"]) else None
        pbp_list.append({
            "event_order": row["event_order"], "match_event_type": row["match_event_type"],
            "match_key": row["match_key"], "uww_lineup_set": uww_set, "opp_lineup_set": opp_set,
        })
    video_list = matchable_clips.to_dict("records")
    n, m = len(pbp_list), len(video_list)

    def compatible(i, j):
        p, v = pbp_list[i], video_list[j]
        if p["match_event_type"] != v["event_type"] or p["match_key"] != v["match_key"]:
            return False
        if v["event_type"] == "foul":
            fouled_player = v["video_clip_player"]
            fouled_team = player_team_lookup.get(fouled_player)
            lineup_set = p["uww_lineup_set"] if fouled_team == "UW-Whitewater" else p["opp_lineup_set"]
            if lineup_set is not None and fouled_player not in lineup_set:
                return False
        return True

    def pos_cost(i, j):
        return abs(pbp_list[i]["event_order"] / total_pbp_n - video_list[j]["video_clip_number"] / total_clips_n)

    n_matched = 0
    n_ft_matched = 0
    n_ft_total = int((opp_events["match_event_type"] == "free_throw").sum())
    n_foul_matched = 0
    n_foul_total = int((opp_events["match_event_type"] == "foul").sum())
    pairs = global_align(n, m, compatible, pos_cost)

    pbp_order_to_i = {p["event_order"]: idx for idx, p in enumerate(pbp_list)}
    video_no_to_j = {v["video_clip_number"]: idx for idx, v in enumerate(video_list)}
    for (ov_opponent, ov_clip_no), ov_event_order in CONFIRMED_CLIP_EVENT_OVERRIDES.items():
        if ov_opponent != opponent_short or ov_clip_no not in video_no_to_j or ov_event_order not in pbp_order_to_i:
            continue
        override_i, override_j = pbp_order_to_i[ov_event_order], video_no_to_j[ov_clip_no]
        pairs = {i: j for i, j in pairs.items() if i != override_i and j != override_j}
        pairs[override_i] = override_j

    for i, j in pairs.items():
        pbp_idx = pbp_orig_index[i]
        clip = video_list[j]
        video_desc_col.loc[pbp_idx] = clip["Description"]
        video_result_col.loc[pbp_idx] = clip["video_result"]
        video_player_col.loc[pbp_idx] = clip["video_clip_player"]
        video_clip_number_col.loc[pbp_idx] = clip["video_clip_number"]
        n_matched += 1
        if pbp_list[i]["match_event_type"] == "free_throw":
            n_ft_matched += 1
        if pbp_list[i]["match_event_type"] == "foul":
            n_foul_matched += 1

    print(
        f"  {opponent_short}: matched {n_matched}/{len(opp_events)} made/missed-shot, turnover, free-throw & foul "
        f"pbp_events rows to a video clip description via a single global order-preserving alignment across the "
        f"whole game (of which {n_ft_matched}/{n_ft_total} are free throws, and {n_foul_matched}/{n_foul_total} "
        f"are fouls). video log had {len(matchable_clips)} taggable sub-events of these types."
    )

pbp_events["video_description"] = video_desc_col
pbp_events["video_result"] = video_result_col
pbp_events["video_clip_number"] = video_clip_number_col
pbp_events["video_player"] = video_player_col
print(
    pbp_events[["opponent", "event_order", "team", "player", "event_type", "raw_text","video_clip_number", "video_result", "video_player", "video_description"]]
    .head(20)
)

has_video_mask = pbp_events["opponent"].isin(opponents_with_video)
unmatched_mask = has_video_mask & pbp_events["event_type"].isin(ATTEMPTED_EVENT_TYPES) & pbp_events["video_description"].isna()
n_unattributed_turnover = (unmatched_mask & pbp_events["player"].isna()).sum()
unmatched = pbp_events[unmatched_mask & pbp_events["player"].notna()].sort_values(["opponent", "event_order"])
print(
    f"\n{len(unmatched)} still-unmatched row(s) among attempted event types across {len(opponents_with_video)} "
    f"game(s) with a video-tagging file ({n_unattributed_turnover} bare team-level turnover(s) with no player "
    f"excluded -- never matchable):"
)
for opponent_short in opponents_with_video:
    print(f"  {opponent_short}: {(unmatched['opponent'] == opponent_short).sum()} unmatched")
print(unmatched[["opponent", "event_order", "period", "time_remaining", "team", "player", "event_type", "raw_text"]])

matched_clip_numbers = set(video_clip_number_col.dropna().astype(int))
unmatched_clips = pd.DataFrame()
for path in video_files:
    # Home/away-aware extraction (mirrors opponent_from_pbp_filename above); matches ".mhtml" or ".html".
    _vname = re.sub(r"_video\.(mhtml|html)$", "", os.path.basename(path), flags=re.IGNORECASE)
    _vname = re.sub(r"^\d+_\d+_\d+\s+", "", _vname)
    if " @ " in _vname:
        _left, _right = [side.strip() for side in _vname.split(" @ ", 1)]
        opponent_short = _right if _left == "UW-Whitewater" else _left
    else:
        opponent_short = _vname
    clips = parse_video_mhtml_cached(path)
    NEVER_MATCHED_RESULTS = {"Run Offense", "No Violation", "Kicked Ball"}
    unmatched_c = clips[
        ~clips["No."].astype(int).isin(matched_clip_numbers) & ~clips["Result"].isin(NEVER_MATCHED_RESULTS)
    ]
    if not unmatched_c.empty:
        unmatched_c = unmatched_c.copy()
        unmatched_c["opponent"] = opponent_short
        unmatched_clips = pd.concat([unmatched_clips, unmatched_c], ignore_index=True)
if unmatched_clips.empty:
    print("No unmatched clips found in the video-tagging files.")
else:
    print("\nUnmatched clips from the video-tagging file(s):")
    print(unmatched_clips[["opponent", "No.", "player", "Result", "Description", "Team", "Duration"]])
print(f"\nTiming: live scraping {_t_scrape_done - _t_attach_start:.0f}s, parsing + aligning "
      f"{time.time() - _t_scrape_done:.0f}s.")
