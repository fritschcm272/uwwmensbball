# 62_identify_lineups_on_court_during_each_team.py -- code for the notebook section "Which lineup was on the floor for each team's biggest scoring run ------------------------"
# Runs inside the notebook via run_section("62_identify_lineups_on_court_during_each_team"); its settings are in that notebook cell.

# --- Which lineup was on the floor for each team's biggest scoring run -------------------------------------
scoring_events_detail = pbp_events[pbp_events["event_type"].isin(["made_shot", "free_throw_made"])].copy()
scoring_events_detail["points"] = scoring_events_detail.apply(
    lambda row: int(row["shot_type"]) if row["event_type"] == "made_shot" else 1, axis=1
)

def detailed_runs(group):
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

all_runs_detail = []
for (opponent, game_date), group in scoring_events_detail.groupby(GAME_KEYS, dropna=False):
    rd = detailed_runs(group)
    rd["opponent"] = opponent
    rd["game_date"] = game_date
    all_runs_detail.append(rd)

# CONFIRMED BUG (fixed here): if scoring_events_detail has zero rows -- e.g. reference_date is set to
# ON OR BEFORE your most recently played game rather than after it, which would filter that game's
# events entirely out of pbp_events (see the "Play-by-play (PBP) data" cell) -- the loop above never
# appends anything, and pd.concat([]) raised "ValueError: No objects to concatenate". Worth
# double-checking reference_date for that reason if this fires unexpectedly with games actually played.
# An empty-but-correctly-shaped frame here lets the groupby/first() and print loop below run through
# cleanly with zero rows instead of crashing.
if all_runs_detail:
    all_runs_detail = pd.concat(all_runs_detail, ignore_index=True)
else:
    all_runs_detail = pd.DataFrame(columns=["team", "run_points", "start_event_order", "end_event_order", "opponent", "game_date"])

biggest_runs_detail = (
    all_runs_detail.sort_values("run_points", ascending=False)
    .groupby(GAME_KEYS + ["team"], as_index=False)
    .first()
)

print("Lineups on the floor during each team's biggest scoring run:\n")
for _, run in biggest_runs_detail.iterrows():
    window = pbp_events[
        (pbp_events["opponent"] == run["opponent"])
        & (pbp_events["game_date"] == run["game_date"])
        & (pbp_events["event_order"] >= run["start_event_order"])
        & (pbp_events["event_order"] <= run["end_event_order"])
    ].sort_values("event_order")
    uww_lineups_during = window["uww_lineup"].dropna().unique().tolist()
    opp_lineups_during = window["opp_lineup"].dropna().unique().tolist()
    start_row, end_row = window.iloc[0], window.iloc[-1]

    print(f"[{run['opponent']}] {run['team']}'s biggest run: {run['run_points']} points "
          f"({start_row['period']} {start_row['time_remaining']} -> {end_row['period']} {end_row['time_remaining']})")
    if len(uww_lineups_during) == 1:
        print(f"    UWW lineup on the floor the whole run: {uww_lineups_during[0]}")
    else:
        print(f"    UWW made a substitution mid-run -- lineups on the floor: {uww_lineups_during}")
    if len(opp_lineups_during) == 1:
        print(f"    {run['opponent']} lineup on the floor the whole run: {opp_lineups_during[0]}")
    else:
        print(f"    {run['opponent']} made a substitution mid-run -- lineups on the floor: {opp_lineups_during}")
    print()

print(biggest_runs_detail)
