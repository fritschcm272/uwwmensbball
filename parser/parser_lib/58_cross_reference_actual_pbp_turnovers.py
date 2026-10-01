# 58_cross_reference_actual_pbp_turnovers.py -- code for the notebook section "Cross-reference ACTUAL PBP turnover counts against the Keys-to-Victory splits ------------"
# Runs inside the notebook via run_section("58_cross_reference_actual_pbp_turnovers"); its settings are in that notebook cell.

# --- Cross-reference ACTUAL PBP turnover counts against the Keys-to-Victory splits -----------------------
pbp_turnovers = (
    pbp_events[pbp_events["event_type"] == "turnover"]
    .groupby(["opponent", "team"])
    .size()
    .reset_index(name="turnovers")
)

uww_season_avg_to = float(uww_team_totals["TO"]) if uww_team_totals is not None else None
uww_season_avg_to_forced = float(uww_opp_totals["TO"]) if uww_opp_totals is not None else None

turnover_crossref_rows = []
for opponent in pbp_events["opponent"].dropna().unique():
    uww_to = pbp_turnovers[(pbp_turnovers["opponent"] == opponent) & (pbp_turnovers["team"] == "UW-Whitewater")]["turnovers"]
    opp_to = pbp_turnovers[(pbp_turnovers["opponent"] == opponent) & (pbp_turnovers["team"] == opponent)]["turnovers"]
    uww_to_val = int(uww_to.iloc[0]) if not uww_to.empty else 0
    opp_to_val = int(opp_to.iloc[0]) if not opp_to.empty else 0

    game_row = scouted_game_comparison[scouted_game_comparison["opponent"] == opponent]
    outcome = game_row["outcome"].iloc[0] if not game_row.empty else None
    was_key = "Ball Security / Turnovers" in game_categories.loc[game_categories["opponent"] == opponent, "category"].tolist()

    turnover_crossref_rows.append({
        "opponent": opponent, "outcome": outcome, "ball_security_was_a_key": was_key,
        "uww_actual_turnovers": uww_to_val, "uww_season_avg_turnovers": uww_season_avg_to,
        "uww_vs_season_avg": round(uww_to_val - uww_season_avg_to, 1) if uww_season_avg_to is not None else None,
        "opponent_actual_turnovers": opp_to_val, "uww_season_avg_turnovers_forced": uww_season_avg_to_forced,
        "turnover_margin_uww_favor": opp_to_val - uww_to_val,
    })

turnover_crossref = pd.DataFrame(turnover_crossref_rows)
print(turnover_crossref)

print("Actual PBP turnovers vs. the Keys-to-Victory 'Ball Security / Turnovers' emphasis:\n")
for _, row in turnover_crossref.iterrows():
    key_note = "WAS" if row["ball_security_was_a_key"] else "was NOT"
    print(f"{row['opponent']} ({row['outcome']}): ball security {key_note} called out as a pre-game key.")
    avg_to = row['uww_season_avg_turnovers']
    vs_avg = row['uww_vs_season_avg']
    avg_forced = row['uww_season_avg_turnovers_forced']
    avg_to_str = f"{avg_to:.1f}" if avg_to is not None else "N/A"
    vs_avg_str = f"{vs_avg:+.1f}" if vs_avg is not None else "N/A"
    avg_forced_str = f"{avg_forced:.1f}" if avg_forced is not None else "N/A"
    print(f"    UWW committed {row['uww_actual_turnovers']} turnovers this game vs. their {avg_to_str} season "
          f"average ({vs_avg_str}).")
    print(f"    {row['opponent']} committed {row['opponent_actual_turnovers']} turnovers (UWW forces "
          f"{avg_forced_str}/gm on average).")
    margin_desc = "in UWW's favor" if row["turnover_margin_uww_favor"] > 0 else ("against UWW" if row["turnover_margin_uww_favor"] < 0 else "even")
    print(f"    Turnover margin (opponent TOs minus UWW TOs): {row['turnover_margin_uww_favor']:+d} ({margin_desc})\n")

if len(turnover_crossref) > 1:
    pbp_turnover_split = (
        turnover_crossref.assign(won_turnover_battle=lambda d: d["turnover_margin_uww_favor"] > 0)
        .groupby("won_turnover_battle")["outcome"]
        .agg(games="count", wins=lambda s: (s == "W").sum(), losses=lambda s: (s == "L").sum())
        .reset_index()
    )
    pbp_turnover_split["win_pct"] = (pbp_turnover_split["wins"] / pbp_turnover_split["games"]).round(3)
    print("Win/loss record by who actually won the turnover battle (PBP-verified, once enough games have PBP data):")
    print(pbp_turnover_split)
else:
    print("Only 1 game has play-by-play data so far -- a real win/loss split by turnover-battle outcome will "
          "populate automatically once more games are uploaded.")

to_events = pbp_events[pbp_events["event_type"] == "turnover"]
uww_to_by_lineup = (
    to_events[to_events["team"] == "UW-Whitewater"]
    .groupby(["opponent", "uww_lineup"]).size().reset_index(name="turnovers")
    .sort_values("turnovers", ascending=False)
)
opp_to_by_lineup = (
    to_events[to_events["team"] != "UW-Whitewater"]
    .groupby(["opponent", "opp_lineup"]).size().reset_index(name="turnovers")
    .sort_values("turnovers", ascending=False)
)
print("\nUWW turnovers by 5-man lineup on the floor:")
print(uww_to_by_lineup)
print("\nOpponent turnovers by their 5-man lineup on the floor:")
print(opp_to_by_lineup)
