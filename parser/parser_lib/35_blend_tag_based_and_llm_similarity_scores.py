# 35_blend_tag_based_and_llm_similarity_scores.py -- code for the notebook section "35_blend_tag_based_and_llm_similarity_scores"
# Runs inside the notebook via run_section("35_blend_tag_based_and_llm_similarity_scores"); its settings are in that notebook cell.

if not use_llm:
    print("LLM-based comparison was skipped (USE_LLM=False), so there is no LLM score to blend with the tag-based "
          "score. Set the USE_LLM config variable to True to run this cell.")
else:
    print(blended_best_matches[[
        "target_player", "target_position", "compared_player", "compared_opponent",
        "blended_score", "tag_similarity_score", "llm_similarity_score",
        "matches_tag_pick", "matches_llm_pick",
        "shared_notes_tags", "shared_keys_tags", "llm_notes_shared_traits", "llm_keys_shared_traits",
    ]])

    print(f"Blended (tag + LLM average) best match per {target_opponent} player, ranked highest to lowest:\n")
    for rank, (_, row) in enumerate(blended_best_matches.iterrows(), start=1):
        tag_note = "same as tag-only pick" if row["matches_tag_pick"] else f"tag-only picked {row['tag_only_pick']}"
        llm_note = "same as LLM-only pick" if row["matches_llm_pick"] else f"LLM-only picked {row['llm_only_pick']}"
        print(f"{rank}. {row['target_player']} ({row['target_position']}) -> {row['compared_player']} of "
              f"{row['compared_opponent']}, blended={row['blended_score']:.2f} "
              f"(tag={row['tag_similarity_score']:.2f}, llm={row['llm_similarity_score']:.1f}/10)")
        print(f"    {tag_note}; {llm_note}")
        print(f"    Tag-based shared NOTES tags: {row['shared_notes_tags'] or '(none)'}")
        print(f"    Tag-based shared KEYS tags: {row['shared_keys_tags'] or '(none)'}")
        print(f"    LLM shared NOTES traits: {row['llm_notes_shared_traits']}")
        print(f"    LLM shared KEYS traits: {row['llm_keys_shared_traits']}\n")
