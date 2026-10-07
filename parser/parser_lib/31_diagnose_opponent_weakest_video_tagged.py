# 31_diagnose_opponent_weakest_video_tagged.py -- code for the notebook section "Diagnose the upcoming opponent's weakest video-tagged play type, same method as UWW's own "
# Runs inside the notebook via run_section("31_diagnose_opponent_weakest_video_tagged"); its settings are in that notebook cell.

# --- Diagnose the upcoming opponent's weakest video-tagged play type, same method as UWW's own diagnosis -------
_safe_display = lambda df: _show(df)
# Play type is whatever chained segment comes right after the LAST "<jersey#> <player name>" token in
# video_description that matches the shooter -- an earlier segment may belong to a DIFFERENT player (e.g. the
# screener/passer who set up the shot), so anchoring on the shooter's own name-token avoids misattributing
# someone else's action. Self-contained name normalization (via `known_names`, their own roster from the
# schedule-loading cell above) rather than reusing the video-attach cell's `normalize_player_name` closure,
# since that one is left pointing at whichever game it last iterated over.
def normalize_elmhurst_name(name, names):
    if name in names:
        return name
    for p in names:
        if p.casefold() == str(name).casefold():
            return p
    return name

def extract_play_type(description, player, names):
    if pd.isna(description) or pd.isna(player):
        return None
    segments = [s.strip() for s in description.split(" > ")]
    player_norm = normalize_elmhurst_name(player, names)
    last_player_idx = None
    for idx, seg in enumerate(segments):
        m = re.match(r"^\d+\s+(.+)$", seg)
        if m and normalize_elmhurst_name(m.group(1), names) == player_norm:
            last_player_idx = idx
    if last_player_idx is not None and last_player_idx + 1 < len(segments):
        return segments[last_player_idx + 1]
    return segments[1] if len(segments) > 1 else None

elmhurst_shot_rows = elmhurst_events[
    elmhurst_events["event_type"].isin(["made_shot", "missed_shot"]) & elmhurst_events["video_description"].notna()
].copy()
elmhurst_shot_rows["play_type"] = elmhurst_shot_rows.apply(
    lambda r: extract_play_type(r["video_description"], r["player"], known_names), axis=1, result_type='reduce'
)
elmhurst_shot_rows["made"] = elmhurst_shot_rows["event_type"] == "made_shot"

play_type_summary = elmhurst_shot_rows.groupby("play_type").agg(attempts=("made", "count"), makes=("made", "sum")).reset_index()
play_type_summary["fg_pct"] = (100 * play_type_summary["makes"] / play_type_summary["attempts"]).round(1)
play_type_summary = play_type_summary.sort_values("attempts", ascending=False).reset_index(drop=True)
print(f"{upcoming_opponent_short}'s video-tagged play types, across their {prev_games.shape[0]} games before Whitewater "
      f"({len(elmhurst_shot_rows)} video-matched attempts):\n")
_safe_display(play_type_summary)

high_volume = play_type_summary[play_type_summary["attempts"] >= HIGH_VOLUME_MIN_ATTEMPTS]
if not high_volume.empty:
    weakest = high_volume.sort_values("fg_pct").iloc[0]
else:
    weakest = pd.Series({"play_type": "(none)", "fg_pct": 0, "makes": 0, "attempts": 0})
print(f"Weakest high-volume play type (>= {HIGH_VOLUME_MIN_ATTEMPTS} attempts): '{weakest['play_type']}' at "
      f"{weakest['fg_pct']}% ({int(weakest['makes'])}/{int(weakest['attempts'])})\n")



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

weak_type_rows = elmhurst_shot_rows[elmhurst_shot_rows["play_type"] == weakest["play_type"]].copy()
weak_type_rows["shot_mechanic"] = weak_type_rows["video_description"].apply(extract_shot_mechanic)
weak_type_rows["contest"] = weak_type_rows["video_description"].apply(extract_contest)
weak_type_rows["distance"] = weak_type_rows["video_description"].apply(extract_distance)

print(f"'{weakest['play_type']}' shot-quality breakdown ({len(weak_type_rows)} attempts):\n")

mechanic_summary = weak_type_rows.groupby("shot_mechanic").agg(attempts=("made", "count"), makes=("made", "sum")).reset_index()
mechanic_summary["fg_pct"] = (100 * mechanic_summary["makes"] / mechanic_summary["attempts"]).round(1)
print("By shot mechanic:")
_safe_display(mechanic_summary.sort_values("attempts", ascending=False))

contest_summary = weak_type_rows.groupby("contest").agg(attempts=("made", "count"), makes=("made", "sum")).reset_index()
contest_summary["fg_pct"] = (100 * contest_summary["makes"] / contest_summary["attempts"]).round(1)
print("\nBy contest level:")
_safe_display(contest_summary.sort_values("attempts", ascending=False))

distance_summary = weak_type_rows.groupby("distance").agg(attempts=("made", "count"), makes=("made", "sum")).reset_index()
distance_summary["fg_pct"] = (100 * distance_summary["makes"] / distance_summary["attempts"]).round(1)
print("\nBy shot distance:")
_safe_display(distance_summary.sort_values("attempts", ascending=False))

player_weak_type = weak_type_rows.groupby("player").agg(
    attempts=("made", "count"), makes=("made", "sum"),
    pct_catch_and_shoot=("shot_mechanic", lambda s: round(100 * (s == "Catch-and-shoot").mean(), 1)),
    pct_guarded=("contest", lambda s: round(100 * (s == "Guarded").mean(), 1)),
).reset_index()
player_weak_type["fg_pct"] = (100 * player_weak_type["makes"] / player_weak_type["attempts"]).round(1)
player_weak_type = player_weak_type.sort_values("attempts", ascending=False)
print(f"\nPer-player '{weakest['play_type']}' volume/efficiency, with catch-and-shoot% and guarded% of those attempts:")
_safe_display(player_weak_type[["player", "attempts", "makes", "fg_pct", "pct_catch_and_shoot", "pct_guarded"]])
