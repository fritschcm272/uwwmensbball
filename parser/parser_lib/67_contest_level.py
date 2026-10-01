# 67_contest_level.py -- code for the notebook section "Same contest-level breakdown as the flagged-player note above, generalized to EVERY shoote"
# Runs inside the notebook via run_section("67_contest_level"); its settings are in that notebook cell.

# --- Same contest-level breakdown as the flagged-player note above, generalized to EVERY shooter with Spot-Up
# volume -- so the pattern (missing mostly on guarded/contested looks vs. mostly on open looks) can be checked
# player by player, not just for one flagged player.
player_contest = (
    spotup.groupby(["player", "contest"])
    .agg(attempts=("made", "count"), makes=("made", "sum"))
    .reset_index()
)
player_contest["fg_pct"] = (100 * player_contest["makes"] / player_contest["attempts"]).round(1)
player_contest = player_contest.sort_values(["player", "attempts"], ascending=[True, False])
print("Spot-Up shooting by player and contest level, season-wide (every player/contest combination with at "
      "least one attempt):\n")
print(player_contest)

guarded_summary = (
    spotup[spotup["contest"] == "Guarded"].groupby("player")
    .agg(guarded_attempts=("made", "count"), guarded_makes=("made", "sum"))
    .reset_index()
)
guarded_summary["guarded_fg_pct"] = (100 * guarded_summary["guarded_makes"] / guarded_summary["guarded_attempts"]).round(1)

open_summary = (
    spotup[spotup["contest"] == "Open"].groupby("player")
    .agg(open_attempts=("made", "count"), open_makes=("made", "sum"))
    .reset_index()
)
open_summary["open_fg_pct"] = (100 * open_summary["open_makes"] / open_summary["open_attempts"]).round(1)

contest_compare = guarded_summary.merge(open_summary, on="player", how="outer")
contest_compare["total_attempts"] = contest_compare[["guarded_attempts", "open_attempts"]].sum(axis=1, skipna=True)
contest_compare = contest_compare.sort_values("total_attempts", ascending=False)
print("\nGuarded vs. Open Spot-Up shooting side-by-side, by player (season-wide):\n")
print(contest_compare[[
    "player", "guarded_attempts", "guarded_makes", "guarded_fg_pct",
    "open_attempts", "open_makes", "open_fg_pct", "total_attempts",
]])
