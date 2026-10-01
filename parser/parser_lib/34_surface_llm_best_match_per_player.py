# 34_surface_llm_best_match_per_player.py -- code for the notebook section "34_surface_llm_best_match_per_player"
# Runs inside the notebook via run_section("34_surface_llm_best_match_per_player"); its settings are in that notebook cell.

if not use_llm:
    print("LLM-based comparison was skipped (USE_LLM=False). Set the USE_LLM config variable to True to run this cell.")
else:
    print(combined[[
        "target_player", "target_position", "compared_player", "compared_opponent",
        "llm_notes_similarity_score", "llm_notes_shared_traits", "llm_keys_similarity_score", "llm_keys_shared_traits",
        "tag_based_pick", "tag_based_score", "picks_agree",
    ]])

    print(f"LLM-based best match per {target_opponent} player -- playing-style (notes) and defensive-approach (keys) "
          "judged as SEPARATE dimensions:\n")
    for _, row in combined.iterrows():
        agree_note = "agrees with" if row["picks_agree"] else "DIFFERS from"
        print(f"{row['target_player']} ({row['target_position']}) -> {row['compared_player']} of "
              f"{row['compared_opponent']} (keyword-tag approach {agree_note} this pick: {row['tag_based_pick']}, score={row['tag_based_score']})")
        print(f"    [Notes] score={row['llm_notes_similarity_score']:.1f}/10 -- shared traits: {row['llm_notes_shared_traits']}")
        print(f"      {row['llm_notes_rationale']}")
        print(f"    [Keys]  score={row['llm_keys_similarity_score']:.1f}/10 -- shared traits: {row['llm_keys_shared_traits']}")
        print(f"      {row['llm_keys_rationale']}\n")
