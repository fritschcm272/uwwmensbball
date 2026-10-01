# 33_surface_tag_based_best_match_per_target.py -- code for the notebook section "CONFIRMED BUG (fixed here): for the very first scouted game of the season there's no PREVI"
# Runs inside the notebook via run_section("33_surface_tag_based_best_match_per_target"); its settings are in that notebook cell.

stat_cols_display = [c for c in best_matches.columns if c.startswith("target_") or c.startswith("compared_")]
stat_cols_display = [c for c in stat_cols_display if c.split("_")[-1] in {"PTS", "REB", "AST", "FG%", "3P%"}]

# CONFIRMED BUG (fixed here): for the very first scouted game of the season there's no PREVIOUS opponent to
# compare players against yet (previous_opponents is empty), so build_player_comparison_artifacts() hands
# back an empty, columnless best_matches. Every column reference below then raised "KeyError: None of
# [Index([...])] are in the [columns]" instead of just explaining that there's nothing to compare against
# yet -- an expected, one-time state at the start of a season, not a real failure.
_bm_required_cols = {
    "target_player", "target_position", "target_opponent", "target_game_date",
    "compared_player", "compared_opponent", "compared_game_date",
    "compared_position", "similarity_score", "stat_similarity", "shared_notes_tags", "shared_keys_tags",
}
if best_matches.empty or not _bm_required_cols <= set(best_matches.columns):
    print(f"No player comparisons available for {target_opponent} yet -- there's no previously-scouted "
          f"opponent on record to compare their players against. Expected for the first scouted game of "
          f"the season; comparisons will start appearing once a second opponent has been scouted.")
else:
    print(best_matches[[
        "target_player", "target_position", "target_opponent", "target_game_date",
        "compared_player", "compared_opponent", "compared_game_date",
        "compared_position", "similarity_score", "stat_similarity", "shared_notes_tags", "shared_keys_tags",
    ] + stat_cols_display])

    print(f"Most comparable previously-scouted player for each {target_opponent} player "
          f"(scouted {scout_game_dates.get(target_opponent)}):\n")
    for _, row in best_matches.iterrows():
        notes_note = f" -- shared NOTES tags: {row['shared_notes_tags']}" if row["shared_notes_tags"] else " -- no shared notes tags"
        keys_note = f"; shared KEYS tags: {row['shared_keys_tags']}" if row["shared_keys_tags"] else "; no shared keys tags"
        print(f"{row['target_player']} ({row['target_position']}) -> {row['compared_player']} of "
              f"{row['compared_opponent']} on {row['compared_game_date']} ({row['compared_position']}), "
              f"score={row['similarity_score']}{notes_note}{keys_note}")
        if pd.notna(row.get("stat_similarity")):
            print(f"    Season-stat similarity contribution: {row['stat_similarity']} (0-1 scale, weighted x{stat_weight} into the score above)")
        else:
            print("    No comparable season stats for this pair -- stat similarity contributed nothing to the score.")
        if pd.notna(row.get("compared_PTS")):
            print(f"    {row['compared_player']}'s season averages: {row['compared_PTS']} PTS, {row['compared_REB']} REB, "
                  f"{row['compared_AST']} AST, {row['compared_FG%']} FG%, {row['compared_3P%']} 3P%")
        else:
            print(f"    No season stats available for {row['compared_player']} (no PDF scout report for {row['compared_opponent']}).")
        if pd.notna(row.get("target_PTS")):
            print(f"    {row['target_player']}'s season averages: {row['target_PTS']} PTS, {row['target_REB']} REB, "
                  f"{row['target_AST']} AST, {row['target_FG%']} FG%, {row['target_3P%']} 3P%")
        else:
            print(f"    No season stats available for {row['target_player']} (no PDF scout report for {target_opponent} yet).")
