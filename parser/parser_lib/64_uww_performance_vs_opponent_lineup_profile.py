# 64_uww_performance_vs_opponent_lineup_profile.py -- code for the notebook section "UWW performance vs. OPPONENT lineup profile, and video-tagged PLAY TYPES -- both season-wi"
# Runs inside the notebook via run_section("64_uww_performance_vs_opponent_lineup_profile"); its settings are in that notebook cell.

# --- UWW performance vs. OPPONENT lineup profile, and video-tagged PLAY TYPES -- both season-wide -------------
opp_lineup_class = pbp_events[GAME_KEYS + ["opp_lineup", "opp_lineup_summary"]].drop_duplicates()
stints_with_opp_class = lineup_stints.merge(opp_lineup_class, on=GAME_KEYS + ["opp_lineup"], how="left")

def opp_role_bucket(summary):
    if pd.isna(summary):
        return "Unknown (no scouting match)"
    m = re.search(r"(\d+) Starter", summary)
    if not m:
        return "Unknown (no scouting match)"
    starters = int(m.group(1))
    if starters >= 4:
        return "Starter-heavy (4-5 starters)"
    if starters <= 1:
        return "Bench-heavy (0-1 starters)"
    return "Mixed (2-3 starters)"

stints_with_opp_class["opp_role_bucket"] = stints_with_opp_class["opp_lineup_summary"].apply(opp_role_bucket)
role_bucket_summary = (
    stints_with_opp_class.groupby("opp_role_bucket")
    .agg(stints=("stint_num", "count"), total_minutes=("stint_minutes", "sum"), net_margin_for_uww=("uww_margin_change", "sum"))
    .reset_index()
)
role_bucket_summary["margin_per_min"] = (role_bucket_summary["net_margin_for_uww"] / role_bucket_summary["total_minutes"]).round(2)
role_bucket_summary = role_bucket_summary.sort_values("total_minutes", ascending=False)
print("UWW's season-wide net margin by OPPONENT lineup role composition (Starter/Bench mix on the floor):\n")
print(role_bucket_summary)

def extract_style_tags(summary):
    if pd.isna(summary):
        return []
    m = re.search(r"Style: ([^|]+)", summary)
    if not m or "no tagged traits" in m.group(1):
        return []
    return [t.split(" x")[0].strip() for t in m.group(1).split(",")]

stints_with_opp_class["opp_style_tags"] = stints_with_opp_class["opp_lineup_summary"].apply(extract_style_tags)
style_summary = (
    stints_with_opp_class.explode("opp_style_tags").dropna(subset=["opp_style_tags"])
    .groupby("opp_style_tags")
    .agg(stints=("stint_num", "count"), total_minutes=("stint_minutes", "sum"), net_margin_for_uww=("uww_margin_change", "sum"))
    .reset_index()
)
style_summary["margin_per_min"] = (style_summary["net_margin_for_uww"] / style_summary["total_minutes"]).round(2)
style_summary = style_summary.sort_values("total_minutes", ascending=False)
print("\nUWW's season-wide net margin by the OPPONENT lineup's dominant scouted playing style (a lineup can "
      "count toward more than one tag):\n")
print(style_summary)

def extract_play_type(description, player):
    if pd.isna(description) or pd.isna(player):
        return None
    segments = [s.strip() for s in description.split(" > ")]
    player_norm = normalize_player_name(player)
    last_player_idx = None
    for idx, seg in enumerate(segments):
        m = re.match(r"^\d+\s+(.+)$", seg)
        if m and normalize_player_name(m.group(1)) == player_norm:
            last_player_idx = idx
    if last_player_idx is not None and last_player_idx + 1 < len(segments):
        return segments[last_player_idx + 1]
    return segments[1] if len(segments) > 1 else None

uww_shot_rows = pbp_events[
    (pbp_events["team"] == "UW-Whitewater")
    & pbp_events["event_type"].isin(["made_shot", "missed_shot"])
    & pbp_events["video_description"].notna()
].copy()
uww_shot_rows["play_type"] = uww_shot_rows.apply(lambda r: extract_play_type(r["video_description"], r["player"]), axis=1)
uww_shot_rows["made"] = uww_shot_rows["event_type"] == "made_shot"

play_type_summary = (
    uww_shot_rows.groupby("play_type")
    .agg(attempts=("made", "count"), makes=("made", "sum"))
    .reset_index()
)
play_type_summary["fg_pct"] = (100 * play_type_summary["makes"] / play_type_summary["attempts"]).round(1)
play_type_summary = play_type_summary.sort_values("attempts", ascending=False)
print(f"\nUWW's video-tagged shot-attempt play types, season-wide ({len(uww_shot_rows)} video-matched attempts "
      f"across {uww_shot_rows['opponent'].nunique()} game(s)):\n")
print(play_type_summary)

play_type_by_lineup = (
    uww_shot_rows.groupby(["play_type", "uww_lineup"])
    .agg(attempts=("made", "count"), makes=("made", "sum"))
    .reset_index()
)
play_type_by_lineup["fg_pct"] = (100 * play_type_by_lineup["makes"] / play_type_by_lineup["attempts"]).round(1)
top_play_types = play_type_summary.head(5)["play_type"].tolist()
print(f"\nFor the top {len(top_play_types)} most-attempted play types, which UWW lineup ran them most:\n")
print(
    play_type_by_lineup[play_type_by_lineup["play_type"].isin(top_play_types)]
    .sort_values(["play_type", "attempts"], ascending=[True, False])
)

play_type_by_player = (
    uww_shot_rows.groupby(["player", "play_type"])
    .agg(attempts=("made", "count"), makes=("made", "sum"))
    .reset_index()
)
play_type_by_player["fg_pct"] = (100 * play_type_by_player["makes"] / play_type_by_player["attempts"]).round(1)
print("\nUWW's video-tagged play-type efficiency by individual player, season-wide (every player/play-type "
      "combination with at least one attempt):\n")
_show(play_type_by_player.sort_values(["player", "attempts"], ascending=[True, False]))

player_top_play_type = (
    play_type_by_player.sort_values("attempts", ascending=False)
    .groupby("player", as_index=False)
    .first()
    .rename(columns={"play_type": "most_used_play_type", "attempts": "attempts_of_that_type", "makes": "makes_of_that_type"})
)
player_overall = (
    uww_shot_rows.groupby("player")
    .agg(total_attempts=("made", "count"), total_makes=("made", "sum"))
    .reset_index()
)
player_overall["overall_fg_pct"] = (100 * player_overall["total_makes"] / player_overall["total_attempts"]).round(1)
player_summary = player_overall.merge(player_top_play_type, on="player", how="left").sort_values(
    "total_attempts", ascending=False
)
print("\nPer-player summary -- overall video-tagged volume/efficiency plus each player's single most-used play "
      "type, season-wide:\n")
print(player_summary[[
    "player", "total_attempts", "total_makes", "overall_fg_pct",
    "most_used_play_type", "attempts_of_that_type", "makes_of_that_type",
]])

starter_flags = pbp_box_score[pbp_box_score["team"] == "UW-Whitewater"][["opponent", "player", "started"]].drop_duplicates()
uww_shot_rows_roles = uww_shot_rows.merge(starter_flags, on=["opponent", "player"], how="left")
uww_shot_rows_roles["role"] = uww_shot_rows_roles["started"].map({True: "Starter", False: "Bench"}).fillna("Unknown")
n_unknown_role = (uww_shot_rows_roles["role"] == "Unknown").sum()
if n_unknown_role:
    print(f"NOTE: {n_unknown_role} attempt(s) could not be matched to a started/bench flag in pbp_box_score "
          f"and are grouped as 'Unknown' below.")

role_overall = (
    uww_shot_rows_roles.groupby("role")
    .agg(attempts=("made", "count"), makes=("made", "sum"))
    .reset_index()
)
role_overall["fg_pct"] = (100 * role_overall["makes"] / role_overall["attempts"]).round(1)
print("\nStarters vs. Bench: overall video-tagged shooting, season-wide:\n")
print(role_overall)

role_by_play_type = (
    uww_shot_rows_roles.groupby(["role", "play_type"])
    .agg(attempts=("made", "count"), makes=("made", "sum"))
    .reset_index()
)
role_by_play_type["fg_pct"] = (100 * role_by_play_type["makes"] / role_by_play_type["attempts"]).round(1)
role_by_play_type = role_by_play_type.sort_values(["role", "attempts"], ascending=[True, False])
print("\nStarters vs. Bench shooting, broken down by play type, season-wide:\n")
print(role_by_play_type)
