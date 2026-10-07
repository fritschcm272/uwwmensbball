# 65_diagnose_spot_up_struggles.py -- code for the notebook section "Diagnosing UWW's Spot-Up struggles: is it shot QUALITY (contested/long attempts) or SHOOTE"
# Runs inside the notebook via run_section("65_diagnose_spot_up_struggles"); its settings are in that notebook cell.

# --- Diagnosing UWW's Spot-Up struggles: is it shot QUALITY (contested/long attempts) or SHOOTER-specific? ----
# The tagger's own vocabulary doesn't name every shot; these two labels mark where it runs out. Kept as
# named constants so the "best shot type" logic can recognise a residual bucket instead of presenting it as
# a real shot type.


def extract_shot_mechanic(description):
    """Which kind of shot this was, from the video tagger's own chained description.

    The first three tests are the tagger's SHOT MECHANIC vocabulary. Everything else used to fall through to
    a bucket called "Other" -- which was 19% of all tagged shots and, at 58.9%, the most efficient bucket on
    the board, so it kept winning "best shot type" while telling a coach nothing. Reading the raw tags, it was
    cuts to the rim, putbacks off the offensive glass, and post-ups.

    Those three are tested AFTER the mechanic tests, not before: they describe how a shot was CREATED rather
    than how it was released, and a post-up that finishes as a jumper should still count as a jumper. Checked
    against real tagged data -- "Cut" and "Offensive Rebound" appear in zero already-classified shots, and
    "Post-Up" in 169, all of which keep their existing (more specific) label under this ordering. Adding the
    tier shrinks the residual from 586 shots to 14.
    """
    if pd.isna(description):
        return None
    d = str(description)
    if "No Dribble Jumper" in d:
        return "Catch-and-shoot"
    if "Dribble Jumper" in d:
        return "Pull-up off the dribble"
    if "To Basket" in d:
        return "Drive to the basket"
    # --- fallback tier: shot ORIGIN, for tags carrying no mechanic keyword at all ---
    if "Offensive Rebound" in d:
        return "Putback off the offensive glass"
    if "Cut" in d:
        return "Cut to the basket"
    if "Post-Up" in d:
        return "Post-up"
    return UNCLASSIFIED_SHOT_MECHANIC


def extract_contest(description):
    """Defender contest, which the tagger records ONLY on catch-and-shoot jumpers.

    Verified across 3,039 tagged shots: every one of the 1,069 catch-and-shoot attempts carries Guarded or
    Open, and not one of the other 1,970 does. So a missing contest tag does not mean the shot was a drive --
    the previous label said "(drive, no contest tag)", which mislabelled every cut, putback and post-up as a
    drive. It means the contest dimension simply does not apply to this shot type.
    """
    if pd.isna(description):
        return None
    d = str(description)
    if "Guarded" in d:
        return "Guarded"
    if "Open" in d:
        return "Open"
    return NO_CONTEST_TAG

def extract_distance(description):
    if pd.isna(description):
        return None
    for tag in ["Long/3pt", "Medium/17' to <3p", "Short to < 17'"]:
        if tag in description:
            return tag
    return "N/A"

spotup = uww_shot_rows[uww_shot_rows["play_type"] == "Spot-Up"].copy()
spotup["shot_mechanic"] = spotup["video_description"].apply(extract_shot_mechanic)
spotup["contest"] = spotup["video_description"].apply(extract_contest)
spotup["distance"] = spotup["video_description"].apply(extract_distance)

print(f"Spot-Up shot-quality breakdown, season-wide ({len(spotup)} video-matched attempts):\n")

mechanic_summary = spotup.groupby("shot_mechanic").agg(attempts=("made", "count"), makes=("made", "sum")).reset_index()
mechanic_summary["fg_pct"] = (100 * mechanic_summary["makes"] / mechanic_summary["attempts"]).round(1)
print("By shot mechanic:")
_show(mechanic_summary.sort_values("attempts", ascending=False))

contest_summary = spotup.groupby("contest").agg(attempts=("made", "count"), makes=("made", "sum")).reset_index()
contest_summary["fg_pct"] = (100 * contest_summary["makes"] / contest_summary["attempts"]).round(1)
print("\nBy contest level:")
_show(contest_summary.sort_values("attempts", ascending=False))

distance_summary = spotup.groupby("distance").agg(attempts=("made", "count"), makes=("made", "sum")).reset_index()
distance_summary["fg_pct"] = (100 * distance_summary["makes"] / distance_summary["attempts"]).round(1)
print("\nBy shot distance:")
_show(distance_summary.sort_values("attempts", ascending=False))

catch_shoot = spotup[spotup["shot_mechanic"] == "Catch-and-shoot"]
cs_combo = catch_shoot.groupby(["contest", "distance"]).agg(attempts=("made", "count"), makes=("made", "sum")).reset_index()
cs_combo["fg_pct"] = (100 * cs_combo["makes"] / cs_combo["attempts"]).round(1)
print(f"\nCatch-and-shoot Spot-Up jumpers only ({len(catch_shoot)} attempts) -- contest x distance:")
_show(cs_combo.sort_values("attempts", ascending=False))

player_spotup = spotup.groupby("player").agg(
    attempts=("made", "count"), makes=("made", "sum"),
    pct_catch_and_shoot=("shot_mechanic", lambda s: round(100 * (s == "Catch-and-shoot").mean(), 1)),
    pct_guarded=("contest", lambda s: round(100 * (s == "Guarded").mean(), 1)),
).reset_index()
player_spotup["fg_pct"] = (100 * player_spotup["makes"] / player_spotup["attempts"]).round(1)
player_spotup = player_spotup.sort_values("attempts", ascending=False)
print("\nPer-player Spot-Up volume/efficiency, with their catch-and-shoot% and guarded% of those attempts:")
print(player_spotup[["player", "attempts", "makes", "fg_pct", "pct_catch_and_shoot", "pct_guarded"]])
