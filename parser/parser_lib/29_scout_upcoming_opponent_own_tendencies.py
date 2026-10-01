# 29_scout_upcoming_opponent_own_tendencies.py -- code for the notebook section "Scout the upcoming opponent's own tendencies from their games before facing Whitewater ---"
# Runs inside the notebook via run_section("29_scout_upcoming_opponent_own_tendencies"); its settings are in that notebook cell.

# --- Scout the upcoming opponent's own tendencies from their games before facing Whitewater -------------------
_safe_display = lambda df: print(df) if not df.empty else print("  (no data)")

elmhurst_events = pbp_events_upcoming[pbp_events_upcoming["team"] == upcoming_opponent_short].copy()
opponent_events = pbp_events_upcoming[
    pbp_events_upcoming["team"].notna() & (pbp_events_upcoming["team"] != upcoming_opponent_short)
].copy()

print(f"{upcoming_opponent_short}'s own events across their {prev_games.shape[0]} games before Whitewater: {len(elmhurst_events)}")
print(f"Their opponents' events across those same games: {len(opponent_events)}\n")

def normalize_elmhurst_player(name):
    if name in known_names:
        return name
    for p in known_names:
        if p.casefold() == str(name).casefold():
            return p
    return name

def extract_play_segment(description, player):
    if pd.isna(description) or pd.isna(player):
        return None
    segments = [s.strip() for s in description.split(" > ")]
    player_norm = normalize_elmhurst_player(player)
    last_player_idx = None
    for idx, seg in enumerate(segments):
        m = re.match(r"^\d+\s+(.+)$", seg)
        if m and normalize_elmhurst_player(m.group(1)) == player_norm:
            last_player_idx = idx
    if last_player_idx is not None and last_player_idx + 1 < len(segments):
        return segments[last_player_idx + 1]
    return segments[1] if len(segments) > 1 else None

def extract_guarded(description):
    if pd.isna(description):
        return None
    if "Guarded" in description:
        return "Yes"
    if "Open" in description:
        return "No"
    return "N/A"

shots = elmhurst_events[elmhurst_events["event_type"].isin(["made_shot", "missed_shot"])].copy()
shots["made"] = shots["event_type"] == "made_shot"
shots["play_type"] = shots.apply(lambda r: extract_play_segment(r["video_description"], r["player"]), axis=1)
shots["guarded"] = shots["video_description"].apply(extract_guarded)
shot_profile = (
    shots.groupby(["shot_type", "shot_desc", "play_type", "guarded"])
    .agg(attempts=("made", "count"), makes=("made", "sum"))
    .reset_index()
)
shot_profile["fg_pct"] = (shot_profile["makes"] / shot_profile["attempts"] * 100).round(1)
shot_profile = shot_profile.sort_values("attempts", ascending=False).reset_index(drop=True)
print(f"{upcoming_opponent_short}'s shot-type tendencies (volume + efficiency, tagged by play_type/guarded) across their last {prev_games.shape[0]} games:")
_safe_display(shot_profile)

play_type_tendency = shots.groupby("play_type").agg(attempts=("made", "count"), makes=("made", "sum")).reset_index()
play_type_tendency["fg_pct"] = (play_type_tendency["makes"] / play_type_tendency["attempts"] * 100).round(1)
play_type_tendency = play_type_tendency.sort_values("attempts", ascending=False).reset_index(drop=True)
print(f"\n{upcoming_opponent_short}'s shot attempts by play type:")
_safe_display(play_type_tendency)

guarded_tendency = shots.groupby("guarded").agg(attempts=("made", "count"), makes=("made", "sum")).reset_index()
guarded_tendency["fg_pct"] = (guarded_tendency["makes"] / guarded_tendency["attempts"] * 100).round(1)
guarded_tendency = guarded_tendency.sort_values("attempts", ascending=False).reset_index(drop=True)
print(f"\n{upcoming_opponent_short}'s shot attempts by contest level:")
_safe_display(guarded_tendency)

turnovers = elmhurst_events[elmhurst_events["event_type"] == "turnover"].copy()
turnovers["play_type"] = turnovers.apply(lambda r: extract_play_segment(r["video_description"], r["player"]), axis=1)
turnover_profile = (
    turnovers.groupby(["turnover_type", "play_type"])
    .size()
    .reset_index(name="count")
    .sort_values("count", ascending=False)
)
print(f"\n{upcoming_opponent_short}'s turnover types ({len(turnovers)} total, tagged by play_type):")
_safe_display(turnover_profile)

fouls = elmhurst_events[elmhurst_events["event_type"] == "foul"]
foul_profile = (
    fouls.groupby(["foul_type", "video_description"])
    .size()
    .reset_index(name="count")
    .sort_values("count", ascending=False)
)
print(f"\n{upcoming_opponent_short}'s foul types ({len(fouls)} total, with video_description):")
_safe_display(foul_profile)

made_shots = elmhurst_events[elmhurst_events["event_type"] == "made_shot"].copy()
made_shots["points"] = made_shots["shot_type"].astype(float)
made_fts = elmhurst_events[elmhurst_events["event_type"] == "free_throw_made"].copy()
made_fts["points"] = 1.0
scoring = pd.concat([made_shots[["player", "points"]], made_fts[["player", "points"]]], ignore_index=True)
top_scorers = scoring.groupby("player")["points"].sum().sort_values(ascending=False).reset_index()
top_scorers.columns = ["player", f"total_points_across_{prev_games.shape[0]}_games"]
print(f"\n{upcoming_opponent_short}'s top scorers across their last {prev_games.shape[0]} games (from play-by-play):")
_safe_display(top_scorers.head(10))
