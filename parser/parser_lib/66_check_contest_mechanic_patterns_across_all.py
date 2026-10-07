# 66_check_contest_mechanic_patterns_across_all.py -- code for the notebook section "Does the guarded/open contest pattern hold for catch-and-shoot jumpers on NON-SPOT-UP play"
# Runs inside the notebook via run_section("66_check_contest_mechanic_patterns_across_all"); its settings are in that notebook cell.

# --- Does the guarded/open contest pattern hold for catch-and-shoot jumpers on NON-SPOT-UP play types too? ----
uww_shot_rows["shot_mechanic"] = uww_shot_rows["video_description"].apply(extract_shot_mechanic)
uww_shot_rows["contest"] = uww_shot_rows["video_description"].apply(extract_contest)
uww_shot_rows["distance"] = uww_shot_rows["video_description"].apply(extract_distance)

catch_and_shoot_all = uww_shot_rows[uww_shot_rows["shot_mechanic"] == "Catch-and-shoot"]
print(f"ALL catch-and-shoot jumpers, every play type, season-wide ({len(catch_and_shoot_all)} attempts):\n")
by_play_type_mechanic = (
    catch_and_shoot_all.groupby("play_type")
    .agg(attempts=("made", "count"), makes=("made", "sum"))
    .reset_index()
)
by_play_type_mechanic["fg_pct"] = (100 * by_play_type_mechanic["makes"] / by_play_type_mechanic["attempts"]).round(1)
print("Which play types produce catch-and-shoot jumpers, and their efficiency:")
_show(by_play_type_mechanic.sort_values("attempts", ascending=False))

contest_all = catch_and_shoot_all.groupby("contest").agg(attempts=("made", "count"), makes=("made", "sum")).reset_index()
contest_all["fg_pct"] = (100 * contest_all["makes"] / contest_all["attempts"]).round(1)
print("\nGuarded vs. Open, ALL catch-and-shoot jumpers (every play type combined), season-wide:")
_show(contest_all.sort_values("attempts", ascending=False))

guarded_all = (
    catch_and_shoot_all[catch_and_shoot_all["contest"] == "Guarded"].groupby("player")
    .agg(guarded_attempts=("made", "count"), guarded_makes=("made", "sum"))
    .reset_index()
)
guarded_all["guarded_fg_pct"] = (100 * guarded_all["guarded_makes"] / guarded_all["guarded_attempts"]).round(1)
open_all = (
    catch_and_shoot_all[catch_and_shoot_all["contest"] == "Open"].groupby("player")
    .agg(open_attempts=("made", "count"), open_makes=("made", "sum"))
    .reset_index()
)
open_all["open_fg_pct"] = (100 * open_all["open_makes"] / open_all["open_attempts"]).round(1)
compare_all = guarded_all.merge(open_all, on="player", how="outer")
compare_all["total_attempts"] = compare_all[["guarded_attempts", "open_attempts"]].sum(axis=1, skipna=True)
compare_all = compare_all.sort_values("total_attempts", ascending=False)
print("\nGuarded vs. Open catch-and-shoot jumpers, by player, ALL play types combined, season-wide:")
print(compare_all[[
    "player", "guarded_attempts", "guarded_makes", "guarded_fg_pct",
    "open_attempts", "open_makes", "open_fg_pct", "total_attempts",
]])

non_jumper = uww_shot_rows[uww_shot_rows["shot_mechanic"] != "Catch-and-shoot"]
non_jumper_summary = (
    non_jumper.groupby(["play_type", "shot_mechanic"])
    .agg(attempts=("made", "count"), makes=("made", "sum"))
    .reset_index()
)
non_jumper_summary["fg_pct"] = (100 * non_jumper_summary["makes"] / non_jumper_summary["attempts"]).round(1)
print("\nNon-catch-and-shoot attempts (drives, pull-ups, post moves, etc.), by play type and mechanic:")
_show(non_jumper_summary.sort_values("attempts", ascending=False))
