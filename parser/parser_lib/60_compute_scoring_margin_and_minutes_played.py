# 60_compute_scoring_margin_and_minutes_played.py -- code for the notebook section "Scoring margin and minutes played by 5-man lineup combination ----------------------------"
# Runs inside the notebook via run_section("60_compute_scoring_margin_and_minutes_played"); its settings are in that notebook cell.

# --- Scoring margin and minutes played by 5-man lineup combination -----------------------------------------
pbp_scoreable = pbp_events[pbp_events["event_type"] != "period_marker"].sort_values(GAME_KEYS + ["event_order"]).copy()

# Every grouping here is on GAME_KEYS, not "opponent" -- see GAME_KEYS. `event_order` restarts at 0
# for each game, so sorting/grouping by opponent alone interleaves a home-and-home's events and the
# clock diff below re-counts the same seconds over and over (observed: 9x-33x inflated minutes).
prev_uww_lineup = pbp_scoreable.groupby(GAME_KEYS, dropna=False)["uww_lineup"].shift(1)
prev_opp_lineup = pbp_scoreable.groupby(GAME_KEYS, dropna=False)["opp_lineup"].shift(1)
lineup_changed = (pbp_scoreable["uww_lineup"] != prev_uww_lineup) | (pbp_scoreable["opp_lineup"] != prev_opp_lineup)
pbp_scoreable["stint_num"] = lineup_changed.fillna(True).groupby([pbp_scoreable[k] for k in GAME_KEYS]).cumsum()

pbp_scoreable["prev_uww_score"] = pbp_scoreable.groupby(GAME_KEYS, dropna=False)["uww_score"].shift(1).fillna(0)
pbp_scoreable["prev_opp_score"] = pbp_scoreable.groupby(GAME_KEYS, dropna=False)["opp_score"].shift(1).fillna(0)

# Monotone clock, then diff -- see the matching comment in the lineup-box-score cell above.
pbp_scoreable["clock"] = pbp_scoreable.groupby(GAME_KEYS + ["period"], dropna=False)["time_remaining_seconds"].cummin()
pbp_scoreable["prev_time_remaining_seconds"] = pbp_scoreable.groupby(GAME_KEYS + ["period"], dropna=False)["clock"].shift(1)
pbp_scoreable["seconds_elapsed"] = (pbp_scoreable["prev_time_remaining_seconds"] - pbp_scoreable["clock"]).clip(lower=0).fillna(0)

lineup_stints = pbp_scoreable.groupby(GAME_KEYS + ["stint_num", "uww_lineup", "opp_lineup"]).agg(
    start_event_order=("event_order", "min"), end_event_order=("event_order", "max"),
    end_uww_score=("uww_score", "last"), end_opp_score=("opp_score", "last"),
    start_prev_uww_score=("prev_uww_score", "first"), start_prev_opp_score=("prev_opp_score", "first"),
    stint_seconds=("seconds_elapsed", "sum"), n_events=("event_order", "count"),
    # Where in the game the stint STARTED -- lets consumers set aside garbage time (a stint that begins
    # late with the game already decided), which the combo keys now do. Seconds remaining in the period.
    start_period=("period", "first"), start_clock=("clock", "first"),
).reset_index()

# (Swapped lineup columns are corrected at the source, where lineups are attached to pbp_events.)
lineup_stints["uww_margin_change"] = (
    (lineup_stints["end_uww_score"] - lineup_stints["start_prev_uww_score"])
    - (lineup_stints["end_opp_score"] - lineup_stints["start_prev_opp_score"])
)
lineup_stints["stint_minutes"] = (lineup_stints["stint_seconds"] / 60).round(2)
print(lineup_stints[[
    "opponent", "stint_num", "uww_lineup", "opp_lineup", "stint_minutes", "uww_margin_change", "n_events",
]].sort_values(["opponent", "stint_num"]))

# Per-game sanity check: five players x 40 minutes means each game must total about 200 minutes.
_clock_check = lineup_stints.groupby(GAME_KEYS)["stint_minutes"].sum().round(1)
_clock_bad = _clock_check[(_clock_check < 35) | (_clock_check > 65)]
if len(_clock_bad):
    print(f"WARNING: {len(_clock_bad)} game(s) have an implausible total elapsed clock "
          f"(expected ~40 min per game):\n{_clock_bad.to_string()}\n")
else:
    print(f"Clock check: all {len(_clock_check)} game(s) between 35 and 65 elapsed minutes.\n")

uww_lineup_summary = (
    lineup_stints.groupby(["opponent", "uww_lineup"])
    .agg(stints=("stint_num", "count"), total_minutes=("stint_minutes", "sum"), net_margin=("uww_margin_change", "sum"))
    .reset_index()
)
uww_lineup_summary["margin_per_min"] = (uww_lineup_summary["net_margin"] / uww_lineup_summary["total_minutes"]).round(2)
uww_lineup_summary = uww_lineup_summary.sort_values("net_margin", ascending=False)

opp_lineup_summary = (
    lineup_stints.groupby(["opponent", "opp_lineup"])
    .agg(stints=("stint_num", "count"), total_minutes=("stint_minutes", "sum"), net_margin_for_uww=("uww_margin_change", "sum"))
    .reset_index()
)
opp_lineup_summary["margin_per_min_for_uww"] = (opp_lineup_summary["net_margin_for_uww"] / opp_lineup_summary["total_minutes"]).round(2)
opp_lineup_summary = opp_lineup_summary.sort_values("net_margin_for_uww", ascending=True)

print("UWW's 5-man lineups, ranked by net scoring margin while on the floor:\n")
for _, row in uww_lineup_summary.iterrows():
    print(f"[{row['opponent']}] {row['uww_lineup']}")
    print(f"    {row['total_minutes']:.1f} min over {row['stints']} stint(s), net margin {row['net_margin']:+.0f} "
          f"({row['margin_per_min']:+.2f}/min)\n")
print(uww_lineup_summary)

print(f"\n{pbp_events['opponent'].dropna().unique().tolist()} lineups, ranked by how they fared AGAINST UWW (most negative net_margin_for_uww = best for them):\n")
for _, row in opp_lineup_summary.iterrows():
    print(f"[{row['opponent']}] {row['opp_lineup']}")
    print(f"    {row['total_minutes']:.1f} min over {row['stints']} stint(s), UWW's net margin vs. this lineup "
          f"{row['net_margin_for_uww']:+.0f} ({row['margin_per_min_for_uww']:+.2f}/min)\n")
print(opp_lineup_summary)
