# 56_compute_biggest_scoring_runs_and_largest.py -- code for the notebook section "Scoring runs and largest lead/deficit per game, with the 5-man lineups on the floor for ea"
# Runs inside the notebook via run_section("56_compute_biggest_scoring_runs_and_largest"); its settings are in that notebook cell.

# --- Scoring runs and largest lead/deficit per game, with the 5-man lineups on the floor for each ------------
scoring_events = pbp_events[pbp_events["event_type"].isin(["made_shot", "free_throw_made"])].copy()
scoring_events["points"] = scoring_events.apply(
    lambda row: int(row["shot_type"]) if row["event_type"] == "made_shot" else 1, axis=1
)

def detailed_runs(group):
    """Same run-detection as before, but keeps each run's start/end event_order so the lineup on the floor can be looked up."""
    runs, cur_team, cur_pts, cur_start, cur_end = [], None, 0, None, None
    for _, row in group.sort_values("event_order").iterrows():
        if row["team"] == cur_team:
            cur_pts += row["points"]
            cur_end = row["event_order"]
        else:
            if cur_team is not None:
                runs.append({"team": cur_team, "run_points": cur_pts, "start_event_order": cur_start, "end_event_order": cur_end})
            cur_team, cur_pts, cur_start, cur_end = row["team"], row["points"], row["event_order"], row["event_order"]
    if cur_team is not None:
        runs.append({"team": cur_team, "run_points": cur_pts, "start_event_order": cur_start, "end_event_order": cur_end})
    return pd.DataFrame(runs)

def lineups_during(opponent, game_date, start_eo, end_eo):
    """Unique UWW/opponent lineups seen across [start_eo, end_eo] of ONE game -- normally just one of
    each, unless a sub happened mid-window. `game_date` is required: event_order restarts every game,
    so an opponent-only filter would sweep in the same event_order range from a rematch too."""
    window = pbp_events[
        (pbp_events["opponent"] == opponent) & (pbp_events["game_date"] == game_date)
        & (pbp_events["event_order"] >= start_eo) & (pbp_events["event_order"] <= end_eo)
    ]
    uww_l = window["uww_lineup"].dropna().unique().tolist()
    opp_l = window["opp_lineup"].dropna().unique().tolist()
    return (uww_l[0] if len(uww_l) == 1 else (" / ".join(uww_l) or None)), (opp_l[0] if len(opp_l) == 1 else (" / ".join(opp_l) or None))

run_rows = []
for (opponent, game_date), group in scoring_events.groupby(GAME_KEYS, dropna=False):
    runs_df = detailed_runs(group)
    biggest_by_team = runs_df.loc[runs_df.groupby("team")["run_points"].idxmax()].set_index("team") if not runs_df.empty else runs_df

    margins_full = pbp_events[(pbp_events["opponent"] == opponent) & (pbp_events["game_date"] == game_date)].dropna(subset=["uww_score"]).copy()
    margins_full["margin"] = margins_full["uww_score"] - margins_full["opp_score"]
    uww_lead_row = margins_full.loc[margins_full["margin"].idxmax()] if not margins_full.empty else None
    opp_lead_row = margins_full.loc[margins_full["margin"].idxmin()] if not margins_full.empty else None

    uww_run = biggest_by_team.loc["UW-Whitewater"] if "UW-Whitewater" in biggest_by_team.index else None
    opp_run = biggest_by_team.loc[opponent] if opponent in biggest_by_team.index else None
    uww_run_lineups = lineups_during(opponent, game_date, uww_run["start_event_order"], uww_run["end_event_order"]) if uww_run is not None else (None, None)
    opp_run_lineups = lineups_during(opponent, game_date, opp_run["start_event_order"], opp_run["end_event_order"]) if opp_run is not None else (None, None)

    run_rows.append({
        "opponent": opponent,
        "game_date": game_date,
        "uww_biggest_run": int(uww_run["run_points"]) if uww_run is not None else 0,
        "uww_run_uww_lineup": uww_run_lineups[0], "uww_run_opp_lineup": uww_run_lineups[1],
        "opponent_biggest_run": int(opp_run["run_points"]) if opp_run is not None else 0,
        "opp_run_uww_lineup": opp_run_lineups[0], "opp_run_opp_lineup": opp_run_lineups[1],
        "uww_largest_lead": int(uww_lead_row["margin"]) if uww_lead_row is not None else 0,
        "uww_lead_uww_lineup": uww_lead_row["uww_lineup"] if uww_lead_row is not None else None,
        "uww_lead_opp_lineup": uww_lead_row["opp_lineup"] if uww_lead_row is not None else None,
        "opponent_largest_lead": int(-opp_lead_row["margin"]) if opp_lead_row is not None else 0,
        "opp_lead_uww_lineup": opp_lead_row["uww_lineup"] if opp_lead_row is not None else None,
        "opp_lead_opp_lineup": opp_lead_row["opp_lineup"] if opp_lead_row is not None else None,
    })
scoring_runs = pd.DataFrame(run_rows)
print(scoring_runs)

print("Scoring run & lead summary, with the 5-man lineups on the floor for each:\n")
for _, row in scoring_runs.iterrows():
    print(f"{row['opponent']}: UWW's biggest run = {row['uww_biggest_run']} pts, {row['opponent']}'s biggest run = {row['opponent_biggest_run']} pts")
    print(f"    During UWW's run -- UWW: {row['uww_run_uww_lineup']} | {row['opponent']}: {row['uww_run_opp_lineup']}")
    print(f"    During {row['opponent']}'s run -- UWW: {row['opp_run_uww_lineup']} | {row['opponent']}: {row['opp_run_opp_lineup']}")
    print(f"    Largest UWW lead: {row['uww_largest_lead']} pts (UWW: {row['uww_lead_uww_lineup']} | {row['opponent']}: {row['uww_lead_opp_lineup']})")
    print(f"    Largest {row['opponent']} lead: {row['opponent_largest_lead']} pts (UWW: {row['opp_lead_uww_lineup']} | {row['opponent']}: {row['opp_lead_opp_lineup']})\n")
