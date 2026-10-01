# 44_reconstruct_single_game_box_score_by_5_man.py -- code for the notebook section "Single-game box score aggregated by 5-MAN LINEUP instead of by individual player ---------"
# Runs inside the notebook via run_section("44_reconstruct_single_game_box_score_by_5_man"); its settings are in that notebook cell.

# --- Single-game box score aggregated by 5-MAN LINEUP instead of by individual player -----------------------
lineup_events = pbp_events[pbp_events["event_type"] != "period_marker"].copy()
lineup_events["lineup"] = lineup_events.apply(
    lambda row: row["uww_lineup"] if row["team"] == "UW-Whitewater" else row["opp_lineup"], axis=1
)

lineup_events["points"] = lineup_events.apply(
    lambda row: int(row["shot_type"]) if row["event_type"] == "made_shot" else (1 if row["event_type"] == "free_throw_made" else 0),
    axis=1,
)
lineup_events["is_fgm"] = lineup_events["event_type"] == "made_shot"
lineup_events["is_fga"] = lineup_events["event_type"].isin(["made_shot", "missed_shot"])
lineup_events["is_3pm"] = lineup_events["is_fgm"] & (lineup_events["shot_type"] == "3")
lineup_events["is_3pa"] = lineup_events["is_fga"] & (lineup_events["shot_type"] == "3")
lineup_events["is_ftm"] = lineup_events["event_type"] == "free_throw_made"
lineup_events["is_fta"] = lineup_events["event_type"].isin(["free_throw_made", "free_throw_missed"])
lineup_events["is_oreb"] = lineup_events["event_type"].isin(["rebound_offensive", "team_deadball_rebound_offensive"])
lineup_events["is_dreb"] = lineup_events["event_type"].isin(["rebound_defensive", "team_deadball_rebound_defensive"])
lineup_events["is_ast"] = lineup_events["event_type"] == "assist"
lineup_events["is_stl"] = lineup_events["event_type"] == "steal"
lineup_events["is_blk"] = lineup_events["event_type"] == "block"
lineup_events["is_to"] = lineup_events["event_type"] == "turnover"
lineup_events["is_pf"] = lineup_events["event_type"] == "foul"

lineup_box_score = lineup_events.dropna(subset=["lineup"]).groupby(["opponent", "game_date", "team", "lineup"]).agg(
    PTS=("points", "sum"), FGM=("is_fgm", "sum"), FGA=("is_fga", "sum"),
    FG3M=("is_3pm", "sum"), FG3A=("is_3pa", "sum"), FTM=("is_ftm", "sum"), FTA=("is_fta", "sum"),
    OREB=("is_oreb", "sum"), DREB=("is_dreb", "sum"), AST=("is_ast", "sum"), STL=("is_stl", "sum"),
    BLK=("is_blk", "sum"), TO=("is_to", "sum"), PF=("is_pf", "sum"),
).reset_index()
lineup_box_score["REB"] = lineup_box_score["OREB"] + lineup_box_score["DREB"]
lineup_box_score["FG%"] = (100 * lineup_box_score["FGM"] / lineup_box_score["FGA"]).round(1)
lineup_box_score["3P%"] = (100 * lineup_box_score["FG3M"] / lineup_box_score["FG3A"]).round(1)
lineup_box_score["FT%"] = (100 * lineup_box_score["FTM"] / lineup_box_score["FTA"]).round(1)

stint_source = pbp_events[pbp_events["event_type"] != "period_marker"].sort_values(GAME_KEYS + ["event_order"]).copy()
prev_uww_lineup = stint_source.groupby(GAME_KEYS, dropna=False)["uww_lineup"].shift(1)
prev_opp_lineup = stint_source.groupby(GAME_KEYS, dropna=False)["opp_lineup"].shift(1)
stint_changed = (stint_source["uww_lineup"] != prev_uww_lineup) | (stint_source["opp_lineup"] != prev_opp_lineup)
stint_source["stint_num"] = stint_changed.fillna(True).groupby([stint_source[k] for k in GAME_KEYS]).cumsum()
stint_source["prev_uww_score"] = stint_source.groupby(GAME_KEYS, dropna=False)["uww_score"].shift(1).fillna(0)
stint_source["prev_opp_score"] = stint_source.groupby(GAME_KEYS, dropna=False)["opp_score"].shift(1).fillna(0)
# The game clock never runs backwards inside a period, so take a running minimum before differencing.
# Without it, ANY out-of-order row makes (prev - now) positive on the way back down and .clip(lower=0)
# keeps that phantom elapsed time while discarding the compensating negative -- silently inventing
# minutes. Grouping on the game (not just the opponent) is what stops two meetings interleaving here.
stint_source["clock"] = stint_source.groupby(GAME_KEYS + ["period"], dropna=False)["time_remaining_seconds"].cummin()
stint_source["prev_time_remaining_seconds"] = stint_source.groupby(GAME_KEYS + ["period"], dropna=False)["clock"].shift(1)
stint_source["seconds_elapsed"] = (stint_source["prev_time_remaining_seconds"] - stint_source["clock"]).clip(lower=0).fillna(0)

stints_for_box = stint_source.groupby(GAME_KEYS + ["stint_num", "uww_lineup", "opp_lineup"]).agg(
    end_uww_score=("uww_score", "last"), end_opp_score=("opp_score", "last"),
    start_prev_uww_score=("prev_uww_score", "first"), start_prev_opp_score=("prev_opp_score", "first"),
    stint_seconds=("seconds_elapsed", "sum"),
).reset_index()
stints_for_box["uww_margin_change"] = (
    (stints_for_box["end_uww_score"] - stints_for_box["start_prev_uww_score"]) - (stints_for_box["end_opp_score"] - stints_for_box["start_prev_opp_score"])
)
stints_for_box["stint_minutes"] = (stints_for_box["stint_seconds"] / 60).round(2)

uww_minutes_margin = stints_for_box.groupby(GAME_KEYS + ["uww_lineup"]).agg(
    MIN=("stint_minutes", "sum"), **{"+/-": ("uww_margin_change", "sum")}
).reset_index().rename(columns={"uww_lineup": "lineup"})
uww_minutes_margin["team"] = "UW-Whitewater"

opp_minutes_margin = stints_for_box.groupby(GAME_KEYS + ["opp_lineup"]).agg(
    MIN=("stint_minutes", "sum"), **{"+/-": ("uww_margin_change", lambda s: -s.sum())}
).reset_index().rename(columns={"opp_lineup": "lineup"})
opp_minutes_margin["team"] = opp_minutes_margin["opponent"]

minutes_margin = pd.concat([uww_minutes_margin, opp_minutes_margin], ignore_index=True)
# CONFIRMED BUG (fixed here): for the first game of the season, lineup reconstruction can come back
# with uww_lineup/opp_lineup entirely NaN for the whole game (e.g. no logged substitution events yet to
# build a lineup sequence from). groupby() drops an all-NaN key entirely, so uww_minutes_margin/
# opp_minutes_margin end up EMPTY -- and pandas infers an empty/all-NaN "lineup" column as float64
# rather than object (string). lineup_box_score's own "lineup" column is always a real object/string
# dtype (built from dropna()'d string values earlier in this cell), so the two sides' dtypes disagreed
# and the merge below raised "ValueError: You are trying to merge on float64 and object columns for key
# 'lineup'." Casting both sides to the same dtype right before merging fixes this regardless of which
# side (if either) ends up empty.
lineup_box_score["lineup"] = lineup_box_score["lineup"].astype(object)
minutes_margin["lineup"] = minutes_margin["lineup"].astype(object)
lineup_box_score = lineup_box_score.merge(minutes_margin, on=GAME_KEYS + ["team", "lineup"], how="left")

lineup_team_totals = lineup_box_score.groupby(GAME_KEYS + ["team"])["PTS"].sum().reset_index()
print("Validating lineup-level PTS totals against the schedule:\n")
for (opponent, game_date) in pbp_events[GAME_KEYS].dropna(subset=["opponent"]).drop_duplicates().itertuples(index=False):
    cand = schedule[schedule["opponent"].str.contains(re.escape(opponent), case=False, na=False)].copy()
    cand = cand[cand["date"].apply(parse_schedule_date) == game_date] if game_date is not None else cand
    if cand.empty:
        continue
    sched_row = cand.iloc[0]
    sel = (lineup_team_totals["opponent"] == opponent) & (lineup_team_totals["game_date"] == game_date)
    uww_pts = lineup_team_totals[sel & (lineup_team_totals["team"] == "UW-Whitewater")]["PTS"]
    opp_pts = lineup_team_totals[sel & (lineup_team_totals["team"] == opponent)]["PTS"]
    uww_val = int(uww_pts.iloc[0]) if not uww_pts.empty else None
    opp_val = int(opp_pts.iloc[0]) if not opp_pts.empty else None
    status = "OK" if (uww_val, opp_val) == (sched_row["team_score"], sched_row["opponent_score"]) else "MISMATCH -- check lineup attribution for this game"
    print(f"  {opponent} {game_date}: lineup box score {uww_val}-{opp_val} vs. schedule {sched_row['team_score']}-{sched_row['opponent_score']} [{status}]")

print(lineup_box_score.sort_values(["opponent", "team", "PTS"], ascending=[True, True, False])[[
    "opponent", "game_date", "team", "lineup", "MIN", "+/-", "PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA",
    "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "FG%", "3P%", "FT%",
]])
