# 70_expected_box_score_for_upcoming_game.py -- code for the notebook section "Expected box score for the upcoming game (Elmhurst) --------------------------------------"
# Runs inside the notebook via run_section("70_expected_box_score_for_upcoming_game"); its settings are in that notebook cell.

# --- Expected box score for the upcoming game (Elmhurst) ------------------------------------------------------
# Combines every signal already computed elsewhere in this notebook rather than inventing a new data source:
#   1. TEAM-LEVEL SCORE: a log5-style blend of each team's own scoring average with the OTHER side's actual
#      defensive output this season -- using ACTUAL results from completed games (not just season averages)
#      as the best available evidence of how UWW performs against this tier of competition.
#   2. OPPONENT PLAYER LINES: each player's own season per-game average, blended with the ACTUAL box-score
#      line their tag+stat-similarity comparable player (from the `best_matches` player-comparison cell) put
#      up in their real game against this same UWW defense -- a matchup-specific signal a season average
#      alone can't capture. Individual point projections are then scaled so they sum to the team-level
#      projection above.
#   3. UWW PLAYER LINES: each player's own season per-game average, scaled by the same team-level pace/quality
#      adjustment, preserving each player's share of the offense.
# NOTE: this cell is written for the specific upcoming opponent ("Elmhurst") named below -- update the
# opponent name if/when the upcoming matchup changes again. Elmhurst's PDF boxscore has no "Opponent" row (no
# points-allowed figure for them), so there's no way to log5 that side directly -- the model leans on their
# season scoring average instead.

def pct_to_float(s):
    if pd.isna(s):
        return None
    s = str(s).strip()
    return None if s in ("", "-") else float(s.rstrip("%"))

# --- 1. Team-level projected score --------------------------------------------------------------------------
uww_team_pts_season = float(stats.loc[stats["PLAYER"] == "Team Total", "PTS"].iloc[0])

played = schedule[schedule["outcome"].notna()]
uww_actual_pts_avg = played["team_score"].mean()
opp_actual_pts_avg = played["opponent_score"].mean()  # what UWW's actual scouted opponents have scored on them

# CONFIRMED BUG (fixed here): team_totals["team_ppg"] is now ALWAYS None -- team/player statistics from
# the scouting report are no longer used at all (see the blanking in the "Cross-reference each scouted
# opponent" cell). float(None) crashed here outright. Digging further, this wasn't just a "handle the
# missing value" fix: tier_avg_ppg needs a real team_ppg for MANY scouted opponents at once to compute a
# "typical opponent" baseline, and that's no longer computable at all now that team_ppg only ever gets a
# real number from a PBP-derived override, applied to exactly ONE opponent (whoever is upcoming) -- there
# is no longer a "tier" of opponents to average. Also, that PBP override happens in a LATER cell than
# this one runs, so even the upcoming opponent's own team_ppg is never populated by the time this line
# runs, regardless of the tier problem. Fixed by computing the upcoming opponent's own PPG directly from
# pbp_box_score_upcoming here (the same real, current-season data the later override cell uses), and
# dropping the no-longer-computable tier normalization in favor of the same plain 50/50 blend already
# used for UWW's own side two lines below -- both sides of the projection now rest on exactly the same
# kind of evidence (a season rate blended with real actual-game evidence), instead of one side secretly
# depending on scouting-report data the other side never used to begin with.
# CONFIRMED BUG (fixed here, on top of the fix above): the first attempt at this used
# pbp_box_score_upcoming for the same purpose -- but that variable has the EXACT same forward-reference
# problem team_totals had: it's built in a LATER cell ("Single-game box score aggregated by 5-MAN
# LINEUP..." / the box-score reconstruction cell), so it raised "NameError: name
# 'pbp_box_score_upcoming' is not defined" the very next run, for the identical reason as before --
# just one variable deeper. pbp_events_upcoming (built two cells after prev_games, well before this one)
# has everything needed instead: uww_score is the running score for the upcoming opponent's own side in
# each of their prior games (self_team=upcoming_opponent_short when these events were built), so its
# LAST value per game (sorted by event_order) is that game's final score for them -- averaging that
# across their games gives the same real, PBP-derived PPG without depending on anything built later.
opponent_team_ppg = None
if not pbp_events_upcoming.empty and UPCOMING_MATCHUP_OPPONENT is not None:
    _ebs_final_scores = (
        pbp_events_upcoming.sort_values("event_order")
        .groupby(["opponent", "game_date"])["uww_score"]
        .last()
    )
    if not _ebs_final_scores.empty:
        opponent_team_ppg = round(_ebs_final_scores.mean(), 2)

if opponent_team_ppg is None:
    print(f"Not enough real game data yet for {UPCOMING_MATCHUP_OPPONENT} to project an expected box "
          f"score -- scouting-report statistics are no longer used, and there's no prior-game "
          f"play-by-play data available yet for this opponent. Skipping the projected box score for "
          f"now; it will populate automatically once real game data exists.")
    projected_uww_box = pd.DataFrame(columns=["PLAYER", "MIN", "projected_PTS", "projected_REB", "projected_AST", "FG%", "3P%", "FT%", "projection_basis"])
    projected_opponent_box = pd.DataFrame(columns=["name", "jersey_number", "role", "position", "MIN", "projected_PTS", "projected_REB", "projected_AST", "comp_used", "comp_from_game", "similarity_score", "projection_basis"])
else:
    # UWW's own scoring average, blended 50/50 with their ACTUAL scoring average against comparable competition
    # this season (mean of the completed games) -- real matchup evidence, not just a season-long number.
    expected_uww_pts = round(0.5 * uww_team_pts_season + 0.5 * uww_actual_pts_avg, 1)
    # Same 50/50 blend, mirrored for the opponent's side: their own real PBP-derived scoring average with
    # UWW's real actual PTS/gm allowed to scouted opponents this season.
    expected_opponent_pts = round(0.5 * opponent_team_ppg + 0.5 * opp_actual_pts_avg, 1)

    print(f"Projected final score: UW-Whitewater {expected_uww_pts:.0f} - {UPCOMING_MATCHUP_OPPONENT} {expected_opponent_pts:.0f} "
          f"(margin {expected_uww_pts - expected_opponent_pts:+.0f})")
    print(f"  UWW inputs: season PTS/gm={uww_team_pts_season:.1f}, actual PTS/gm vs scouted opponents={uww_actual_pts_avg:.1f}")
    print(f"  {UPCOMING_MATCHUP_OPPONENT} inputs: PBP-derived PTS/gm={opponent_team_ppg:.1f}, UWW's actual PTS/gm allowed to scouted "
          f"opponents={opp_actual_pts_avg:.1f}")

    # --- 2. Opponent projected player box score -------------------------------------------------------------------
    opponent_players = player_profiles[player_profiles["opponent"] == UPCOMING_MATCHUP_OPPONENT].copy()
    for col in ["PTS", "REB", "AST", "MIN"]:
        opponent_players[col] = pd.to_numeric(opponent_players[col], errors="coerce")

    # CONFIRMED BUG (fixed here): same root cause as the player-comparison display cell above -- for the
    # first scouted game of the season, best_matches comes back empty and columnless (no prior opponent to
    # compare against yet), so filtering it on "target_opponent" raised a KeyError instead of just yielding
    # no matches. An empty frame WITH the right column names lets everything below (the merges, and
    # blend_stat()'s existing NaN-comp fallback to each player's own season average) work exactly as it
    # already does for any individual player with no match found -- no separate empty-season code path needed.
    _bm_cols = ["target_player", "target_opponent", "compared_player", "compared_opponent", "similarity_score"]
    if best_matches.empty or not set(_bm_cols) <= set(best_matches.columns):
        opponent_matches = pd.DataFrame(columns=_bm_cols)
    else:
        opponent_matches = best_matches[best_matches["target_opponent"] == UPCOMING_MATCHUP_OPPONENT]
    opp_actuals = pbp_box_score[pbp_box_score["team"] != "UW-Whitewater"][
        ["opponent", "player", "PTS", "REB", "AST"]
    ].rename(columns={"opponent": "compared_opponent", "player": "compared_player",
                       "PTS": "comp_actual_PTS", "REB": "comp_actual_REB", "AST": "comp_actual_AST"})
    comp_actuals = opponent_matches.merge(opp_actuals, on=["compared_opponent", "compared_player"], how="left")

    opponent_players = opponent_players.merge(
        comp_actuals[["target_player", "compared_player", "compared_opponent", "similarity_score",
                      "comp_actual_PTS", "comp_actual_REB", "comp_actual_AST"]],
        left_on="name", right_on="target_player", how="left",
    )

    OWN_WEIGHT = 0.6  # own season average is the more direct predictor; the comp's actual game is a secondary signal

    def blend_stat(row, own_col, comp_col):
        own, comp = row[own_col], row[comp_col]
        if pd.isna(comp):
            return own
        if pd.isna(own):
            return comp
        return OWN_WEIGHT * own + (1 - OWN_WEIGHT) * comp

    for stat in ["PTS", "REB", "AST"]:
        opponent_players[f"blended_{stat}"] = opponent_players.apply(lambda r, s=stat: blend_stat(r, s, f"comp_actual_{s}"), axis=1)

    blended_total_pts = opponent_players["blended_PTS"].sum()
    opponent_scale = expected_opponent_pts / blended_total_pts if blended_total_pts else 1.0
    opponent_players["projected_PTS"] = (opponent_players["blended_PTS"] * opponent_scale).round(1)
    opponent_players["projected_REB"] = opponent_players["blended_REB"].round(1)
    opponent_players["projected_AST"] = opponent_players["blended_AST"].round(1)

    # Per-player projection basis -- a plain-text explanation of exactly how each line was derived. Intended to be
    # surfaced as a hover tooltip/bubble wherever this table is displayed (e.g. an info icon next to each row in
    # the app), rather than as its own always-visible column.
    def opponent_projection_basis(row):
        if pd.isna(row["PTS"]):
            return "No season stats recorded for this player yet -- insufficient data to project."
        basis = f"Own season avg: {row['PTS']:.1f} PTS, {row['REB']:.1f} REB, {row['AST']:.1f} AST/gm"
        if pd.notna(row["comp_actual_PTS"]):
            basis += (
                f" | Blended {OWN_WEIGHT:.0%} own avg / {1 - OWN_WEIGHT:.0%} actual game -- comp match: "
                f"{row['compared_player']} ({row['compared_opponent']}, similarity {row['similarity_score']:.1f}) "
                f"actually posted {row['comp_actual_PTS']:.0f} PTS, {row['comp_actual_REB']:.0f} REB, "
                f"{row['comp_actual_AST']:.0f} AST vs this same UWW defense"
            )
        else:
            basis += " | No PBP data available for this player's comp match -- used own season average only"
        basis += f" | Scaled x{opponent_scale:.2f} so the roster sums to the projected team total ({expected_opponent_pts:.0f} pts)"
        return basis

    opponent_players["projection_basis"] = opponent_players.apply(opponent_projection_basis, axis=1)

    # MIN was previously left out of this selection even though opponent_players already carries the opponent's
    # own season-average minutes (same source uww_player_profiles.MIN the app already reads elsewhere) -- added
    # so the opponent's side of Projected Box Score isn't missing minutes played while UWW's own side has it.
    projected_opponent_box = opponent_players[
        [c for c in ["name", "jersey_number", "role", "position", "MIN", "projected_PTS", "projected_REB", "projected_AST",
         "compared_player", "compared_opponent", "similarity_score", "projection_basis"] if c in opponent_players.columns]
    ].rename(columns={"compared_player": "comp_used", "compared_opponent": "comp_from_game"}).sort_values("projected_PTS", ascending=False).reset_index(drop=True)

    print(f"\n{UPCOMING_MATCHUP_OPPONENT} projected team total: {projected_opponent_box['projected_PTS'].sum():.1f} pts "
          f"(scaled from a {OWN_WEIGHT:.0%} own-season-average / {1 - OWN_WEIGHT:.0%} comp-actual-game blend)")
    print(projected_opponent_box)

    # --- 3. UWW projected player box score -----------------------------------------------------------------------
    # Scale against the SUM of individual player PTS averages, not the season "Team Total" row -- per-player
    # averages are each computed over that player's OWN games played (GP-GS varies by player), so they don't sum
    # exactly to the team's average PPG (a pre-existing quirk of the scraped season stats, not introduced here).
    # Scaling to the raw individual sum keeps this table's total consistent with the printed team-level projection.
    uww_player_rows = stats[~stats["PLAYER"].isin(["Team Total", "Opponent"])].copy()
    for col in ["PTS", "REB", "AST", "MIN"]:
        uww_player_rows[col] = pd.to_numeric(uww_player_rows[col], errors="coerce")
    raw_individual_pts_sum = uww_player_rows["PTS"].sum()
    uww_scale = expected_uww_pts / raw_individual_pts_sum if raw_individual_pts_sum else 1.0
    uww_player_rows["projected_PTS"] = (uww_player_rows["PTS"] * uww_scale).round(1)
    uww_player_rows["projected_REB"] = uww_player_rows["REB"]
    uww_player_rows["projected_AST"] = uww_player_rows["AST"]

    # Per-player projection basis -- same idea as the opponent's: a plain-text explanation meant for a hover tooltip/bubble.
    def uww_projection_basis(row):
        if pd.isna(row["PTS"]):
            return "No season stats recorded for this player yet -- insufficient data to project."
        min_str = f"{row['MIN']:.0f}" if pd.notna(row["MIN"]) else "?"
        return (
            f"Own season avg: {row['PTS']:.1f} PTS, {row['REB']:.1f} REB, {row['AST']:.1f} AST/gm over {min_str} min "
            f"| Scaled x{uww_scale:.2f} for this matchup's projected pace (UWW projected team total {expected_uww_pts:.0f} pts: "
            f"50% season PPG {uww_team_pts_season:.1f} + 50% actual PPG vs scouted opponents this season {uww_actual_pts_avg:.1f})"
        )

    uww_player_rows["projection_basis"] = uww_player_rows.apply(uww_projection_basis, axis=1)

    projected_uww_box = uww_player_rows[
        ["PLAYER", "MIN", "projected_PTS", "projected_REB", "projected_AST", "FG%", "3P%", "FT%", "projection_basis"]
    ].sort_values("projected_PTS", ascending=False).reset_index(drop=True)

    # --- Stamp WHICH GAME this projection is for -------------------------------------------------------
    # Both projection tables described "the upcoming game" and carried nothing saying which game that was,
    # so once the next parser run overwrote them there was no way to line an old projection up against the
    # game it was made for. The app's Previous Games page could only compare a past game against whatever
    # projection happened to be on disk. These two columns plus the append-on-export below (see the CSV
    # export cell) turn the projections into a permanent per-game record.
    _proj_opp = upcoming_opponent if upcoming_game is not None else UPCOMING_MATCHUP_OPPONENT
    _proj_date = upcoming_game["date"] if upcoming_game is not None else None
    for _pf in (projected_uww_box, projected_opponent_box):
        _pf.insert(0, "game_date", _proj_date)
        _pf.insert(0, "opponent", _proj_opp)

    print(f"\nUW-Whitewater projected team total: {projected_uww_box['projected_PTS'].sum():.1f} pts "
          f"(season averages scaled x{uww_scale:.2f} for pace/matchup)")
    print(projected_uww_box)

    # --- Narrative context from the opponent's game plan + relevant coaching flags on UWW's top projected scorers -
    opponent_ktv = all_game_plans.loc[
        (all_game_plans["opponent"] == UPCOMING_MATCHUP_OPPONENT) & (all_game_plans["topic"] == "KEYS TO VICTORY"), "notes"
    ]
    opponent_strengths = all_game_plans.loc[
        (all_game_plans["opponent"] == UPCOMING_MATCHUP_OPPONENT) & (all_game_plans["topic"] == "TEAM STRENGTHS"), "notes"
    ]
    print(f"\n{UPCOMING_MATCHUP_OPPONENT}'s pre-game keys to victory:", opponent_ktv.iloc[0] if not opponent_ktv.empty else "n/a")
    print(f"{UPCOMING_MATCHUP_OPPONENT}'s team strengths:", opponent_strengths.iloc[0] if not opponent_strengths.empty else "n/a")

    top_scorers = set(projected_uww_box.head(5)["PLAYER"].str.lower())
    relevant_flags = coaching_flags_df[coaching_flags_df["player_key"].isin(top_scorers)]
    if not relevant_flags.empty:
        print("\nCoaching flags on UWW's top-5 projected scorers:")
        for _, f in relevant_flags.iterrows():
            print(f"  [{f['sentiment']}] {f['player']} -- {f['flag']} ({f['evidence']})")
