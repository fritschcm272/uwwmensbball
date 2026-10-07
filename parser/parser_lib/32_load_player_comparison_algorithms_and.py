# 32_load_player_comparison_algorithms_and.py -- code for the notebook section "Portable replacement for "%run UW Whitewater Player Comparison Algorithms" -- imports the "
# Runs inside the notebook via run_section("32_load_player_comparison_algorithms_and"); its settings are in that notebook cell.

# Portable replacement for "%run UW Whitewater Player Comparison Algorithms" -- imports the same helper logic
# from player_comparison.py, sitting alongside this notebook. Force a reload so re-running this cell always
# picks up the latest edits to player_comparison.py, even though the module is already cached in sys.modules
# from an earlier run in this same kernel session.
import importlib
import player_comparison
importlib.reload(player_comparison)
from player_comparison import build_player_comparison_artifacts, PLAYER_COMPARISON_ALGORITHMS_VERSION

# USE_LLM is set in the Configuration cell at the top -- defaults to False so player comparisons run on
# tag-based similarity only, without any LLM calls or cost. Set USE_LLM=True to also run the LLM-based
# comparison (cells below).
use_llm = USE_LLM

comparison_artifacts = build_player_comparison_artifacts(
    schedule=schedule,
    scout_reports=scout_reports,
    player_profiles=player_profiles,
    cache_path=os.path.join(OUTPUT_DIR, "_cache", "llm_player_comparison_cache.jsonl"),
    use_llm=use_llm,
    # Build the comparisons FOR the upcoming opponent (defined in the "Identify the upcoming opponent" cell
    # above). Without this the module defaults to "whichever scouted opponent sits latest on the schedule",
    # which silently produced a uww_player_comparisons full of rows for a DIFFERENT team -- the app's Player
    # Details dialog then matched none of the upcoming opponent's roster players and showed "No comparable
    # player found" against a CSV that was not empty at all.
    upcoming_opponent=upcoming_opponent_short,
)
globals().update(comparison_artifacts)

# Fail loudly rather than quietly shipping comparisons for the wrong team -- this exact mismatch reached the
# app once already and looked like an app bug from there.
if target_opponent != upcoming_opponent_short:
    print(f"WARNING: comparison target is {target_opponent!r}, not the upcoming opponent "
          f"{upcoming_opponent_short!r} -- uww_player_comparisons will not match the app's roster view.")

print(f"Loaded player comparison algorithms (version {PLAYER_COMPARISON_ALGORITHMS_VERSION}). use_llm={use_llm}\n")
print("Scouted opponents and their game number on the schedule:")
for opp, num in sorted(scout_game_numbers.items(), key=lambda x: (x[1] is None, x[1])):
    print(f"  Game #{num}: {opp}")

if target_opponent is None:
    print("\nWARNING: no scouted opponent has a resolvable game number on the schedule, so there's no valid target for a similarity comparison yet.")
else:
    print(f"\nTarget (most recently scouted game): {target_opponent} (game #{target_game_number})")
    print("Previous scouted opponents to compare against:", previous_opponents)

print("\nplayer_notes-derived tag frequency and rarity-based importance weight (rarer tags count more toward similarity):")
_show(notes_tag_importance_df)

print("\nkeys_to_defending-derived tag frequency and rarity-based importance weight:")
_show(keys_tag_importance_df)
