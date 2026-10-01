# 57_surface_clutch_time_events_with_lineup.py -- code for the notebook section "Clutch-time event log: last 5 minutes of the 2nd half or any overtime, with the score with"
# Runs inside the notebook via run_section("57_surface_clutch_time_events_with_lineup"); its settings are in that notebook cell.

# --- Clutch-time event log: last 5 minutes of the 2nd half or any overtime, with the score within 8 points ----
clutch_mask = (
    (pbp_events["period"] != "H1")
    & (pbp_events["time_remaining_seconds"] <= 300)
    & ((pbp_events["uww_score"] - pbp_events["opp_score"]).abs() <= 8)
)
clutch_events = pbp_events[clutch_mask & pbp_events["event_type"].isin([
    "made_shot", "missed_shot", "free_throw_made", "free_throw_missed", "turnover", "steal", "foul", "block", "assist",
])].copy()

if clutch_events.empty:
    print("No clutch-time stretches yet -- no game so far has been within 8 points in the last 5 minutes of the "
          "2nd half or later. This will populate automatically as closer games are uploaded.")
else:
    print(clutch_events[[
        "opponent", "period", "time_remaining", "team", "player", "event_type", "raw_text", "uww_score", "opp_score",
        "uww_lineup", "opp_lineup",
    ]])
    clutch_points = clutch_events[clutch_events["event_type"].isin(["made_shot", "free_throw_made"])].copy()
    clutch_points["points"] = clutch_points.apply(
        lambda row: int(row["shot_type"]) if row["event_type"] == "made_shot" else 1, axis=1
    )
    print("\nClutch-time points scored, by team:")
    print(clutch_points.groupby(GAME_KEYS + ["team"])["points"].sum().reset_index())

    print("\nUWW's 5-man lineup(s) used in clutch time, by game:")
    for (opponent, game_date), group in clutch_events.groupby(GAME_KEYS, dropna=False):
        print(f"  {opponent} {game_date}: {sorted(group['uww_lineup'].dropna().unique().tolist())}")
