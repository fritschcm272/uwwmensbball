# 76_rebuild_player_comparisons_with_pbp.py -- code for the notebook section "Rebuild player comparisons now that the upcoming opponent's stats are PBP-derived --------"
# Runs inside the notebook via run_section("76_rebuild_player_comparisons_with_pbp"); its settings are in that notebook cell.

# --- Rebuild player comparisons now that the upcoming opponent's stats are PBP-derived ----------------------
# CONFIRMED BUG (fixed here): the comparison cell near the top of this notebook runs BEFORE the override a
# few cells up, which replaces the upcoming opponent's player_profiles stats with PBP-derived per-game
# aggregates. Order matters more than it looks:
#
#   - A scouted starter has PTS/REB/AST in the PDF, so his comparison had stat evidence either way.
#   - A bench player who was never written up has NO PDF season stats. At comparison time his stat columns
#     were empty, stat_similarity came back None, and his "comparable player" was decided by position,
#     height and role alone -- a size guess wearing the same score as a real match. Observed directly: an
#     un-scouted bench player scored 5.17 against a fully-scouted starter's 5.25.
#   - The PBP override then fills exactly those missing numbers, from the opponent's own prior games...
#     several cells too late for anyone to use them.
#
# Re-running the same function here, unchanged, with the now-populated player_profiles gives bench players
# real production evidence. Nothing else about the algorithm changes, and the earlier run stays where it is
# so its output can still be inspected above.
if target_opponent is None or not previous_opponents:
    print("No comparison target or no previously-scouted opponent -- leaving the earlier comparisons as they are.")
else:
    _pre_rebuild = best_matches.copy() if isinstance(best_matches, pd.DataFrame) else pd.DataFrame()

    _rebuilt = build_player_comparison_artifacts(
        schedule=schedule,
        scout_reports=scout_reports,
        player_profiles=player_profiles,   # now carries PBP-derived stats for the upcoming opponent
        cache_path=os.path.join(OUTPUT_DIR, "_cache", "llm_player_comparison_cache.jsonl"),
        use_llm=False,   # the LLM pass compares scouting NOTES, which the override didn't touch -- rerunning
                         # it would spend calls to reproduce the same answers. The earlier LLM artifacts are
                         # left untouched in the globals from the first run.
        upcoming_opponent=upcoming_opponent_short,
    )
    _new_best = _rebuilt["best_matches"]

    if _new_best.empty:
        print("Rebuild produced no comparisons -- keeping the earlier result rather than exporting an empty table.")
    else:
        best_matches = _new_best
        player_similarity = _rebuilt["player_similarity"]

        _gained = _stat_backed = 0
        if not _pre_rebuild.empty and "stat_similarity" in _pre_rebuild.columns:
            _before = _pre_rebuild.set_index("target_player")["stat_similarity"].to_dict()
            for _, _r in best_matches.iterrows():
                _was = _before.get(_r["target_player"])
                if pd.isna(_was) and pd.notna(_r.get("stat_similarity")):
                    _gained += 1
        _stat_backed = int(best_matches["stat_similarity"].notna().sum())

        print(f"Rebuilt player comparisons for {target_opponent} using PBP-derived stats.")
        print(f"  {_stat_backed} of {len(best_matches)} comparisons now have stat evidence "
              f"({_gained} gained it in this rebuild -- those were size-and-position guesses before).")

        _weak = best_matches[best_matches["evidence_coverage"] < 0.7]
        if not _weak.empty:
            print(f"\n  Still thin ({len(_weak)}) -- the app labels these so they aren't read as real matches:")
            for _, _r in _weak.iterrows():
                print(f"    {_r['target_player']} -> {_r['compared_player']} "
                      f"({_r['evidence_coverage']:.0%} evidence) -- {_r['comparison_method']}")

        print("\n  Comparisons for players with no scouting-report entry:")
        _unscouted = best_matches[~best_matches["target_has_scouting_report"].fillna(True)]
        if _unscouted.empty:
            print("    (none -- every rostered player has a scouting-report entry)")
        else:
            for _, _r in _unscouted.iterrows():
                print(f"    {_r['target_player']} -> {_r['compared_player']} of {_r['compared_opponent']} "
                      f"(score {_r['similarity_score']}, {_r['evidence_coverage']:.0%} evidence)")
