# 59_cross_reference_actual_pbp_rebounding.py -- code for the notebook section "Cross-reference ACTUAL PBP rebounding totals against the Keys-to-Victory splits ----------"
# Runs inside the notebook via run_section("59_cross_reference_actual_pbp_rebounding"); its settings are in that notebook cell.

# --- Cross-reference ACTUAL PBP rebounding totals against the Keys-to-Victory splits ----------------------
rebound_team_totals = pbp_box_score.groupby(["opponent", "team"])[["REB", "OREB", "DREB"]].sum().reset_index()

uww_season_avg_reb = {c: float(uww_team_totals[c]) for c in ["REB", "ORB", "DRB"]} if uww_team_totals is not None else None
uww_season_avg_reb_allowed = {c: float(uww_opp_totals[c]) for c in ["REB", "ORB", "DRB"]} if uww_opp_totals is not None else None

rebound_crossref_rows = []
for opponent in pbp_events["opponent"].dropna().unique():
    uww_row = rebound_team_totals[(rebound_team_totals["opponent"] == opponent) & (rebound_team_totals["team"] == "UW-Whitewater")]
    opp_row = rebound_team_totals[(rebound_team_totals["opponent"] == opponent) & (rebound_team_totals["team"] == opponent)]
    uww_reb = int(uww_row["REB"].iloc[0]) if not uww_row.empty else 0
    uww_oreb = int(uww_row["OREB"].iloc[0]) if not uww_row.empty else 0
    uww_dreb = int(uww_row["DREB"].iloc[0]) if not uww_row.empty else 0
    opp_reb = int(opp_row["REB"].iloc[0]) if not opp_row.empty else 0
    opp_oreb = int(opp_row["OREB"].iloc[0]) if not opp_row.empty else 0
    opp_dreb = int(opp_row["DREB"].iloc[0]) if not opp_row.empty else 0

    game_row = scouted_game_comparison[scouted_game_comparison["opponent"] == opponent]
    outcome = game_row["outcome"].iloc[0] if not game_row.empty else None
    was_key = "Rebounding" in game_categories.loc[game_categories["opponent"] == opponent, "category"].tolist()

    rebound_crossref_rows.append({
        "opponent": opponent, "outcome": outcome, "rebounding_was_a_key": was_key,
        "uww_actual_reb": uww_reb, "uww_season_avg_reb": uww_season_avg_reb["REB"] if uww_season_avg_reb else None,
        "uww_vs_season_avg_reb": round(uww_reb - uww_season_avg_reb["REB"], 1) if uww_season_avg_reb else None,
        "uww_actual_oreb": uww_oreb, "uww_actual_dreb": uww_dreb,
        "opponent_actual_reb": opp_reb, "uww_season_avg_reb_allowed": uww_season_avg_reb_allowed["REB"] if uww_season_avg_reb_allowed else None,
        "opponent_actual_oreb": opp_oreb, "opponent_actual_dreb": opp_dreb,
        "rebound_margin_uww_favor": uww_reb - opp_reb,
    })

rebound_crossref = pd.DataFrame(rebound_crossref_rows)
print(rebound_crossref)

print("Actual PBP rebounding vs. the Keys-to-Victory 'Rebounding' emphasis:\n")
for _, row in rebound_crossref.iterrows():
    key_note = "WAS" if row["rebounding_was_a_key"] else "was NOT"
    print(f"{row['opponent']} ({row['outcome']}): rebounding {key_note} called out as a pre-game key.")
    avg_reb = row['uww_season_avg_reb']
    vs_avg_reb = row['uww_vs_season_avg_reb']
    avg_allowed = row['uww_season_avg_reb_allowed']
    avg_reb_str = f"{avg_reb:.1f}" if avg_reb is not None else "N/A"
    vs_avg_reb_str = f"{vs_avg_reb:+.1f}" if vs_avg_reb is not None else "N/A"
    avg_allowed_str = f"{avg_allowed:.1f}" if avg_allowed is not None else "N/A"
    print(f"    UWW grabbed {row['uww_actual_reb']} rebounds ({row['uww_actual_oreb']} off. / {row['uww_actual_dreb']} def.) this game vs. "
          f"their {avg_reb_str} season average ({vs_avg_reb_str}).")
    print(f"    {row['opponent']} grabbed {row['opponent_actual_reb']} rebounds ({row['opponent_actual_oreb']} off. / "
          f"{row['opponent_actual_dreb']} def.) -- UWW allows {avg_allowed_str}/gm on average.")
    margin_desc = "in UWW's favor" if row["rebound_margin_uww_favor"] > 0 else ("against UWW" if row["rebound_margin_uww_favor"] < 0 else "even")
    print(f"    Rebound margin (UWW minus opponent): {row['rebound_margin_uww_favor']:+d} ({margin_desc})\n")

if len(rebound_crossref) > 1:
    pbp_rebound_split = (
        rebound_crossref.assign(won_rebound_battle=lambda d: d["rebound_margin_uww_favor"] > 0)
        .groupby("won_rebound_battle")["outcome"]
        .agg(games="count", wins=lambda s: (s == "W").sum(), losses=lambda s: (s == "L").sum())
        .reset_index()
    )
    pbp_rebound_split["win_pct"] = (pbp_rebound_split["wins"] / pbp_rebound_split["games"]).round(3)
    print("Win/loss record by who actually won the rebound battle (PBP-verified, once enough games have PBP data):")
    print(pbp_rebound_split)
else:
    print("Only 1 game has play-by-play data so far -- a real win/loss split by rebound-battle outcome will "
          "populate automatically once more games are uploaded.")

reb_events = pbp_events[pbp_events["event_type"].isin(["rebound_offensive", "rebound_defensive"])]
uww_reb_by_lineup = (
    reb_events[reb_events["team"] == "UW-Whitewater"]
    .groupby(["opponent", "uww_lineup"]).size().reset_index(name="rebounds")
    .sort_values("rebounds", ascending=False)
)
opp_reb_by_lineup = (
    reb_events[reb_events["team"] != "UW-Whitewater"]
    .groupby(["opponent", "opp_lineup"]).size().reset_index(name="rebounds")
    .sort_values("rebounds", ascending=False)
)
print("\nUWW rebounds by 5-man lineup on the floor:")
print(uww_reb_by_lineup)
print("\nOpponent rebounds by their 5-man lineup on the floor:")
print(opp_reb_by_lineup)
