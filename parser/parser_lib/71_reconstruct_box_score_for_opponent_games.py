# 71_reconstruct_box_score_for_opponent_games.py -- code for the notebook section "Reconstruct a box score from pbp_events_upcoming, same event_type -> stat mapping as pbp_b"
# Runs inside the notebook via run_section("71_reconstruct_box_score_for_opponent_games"); its settings are in that notebook cell.

# --- Reconstruct a box score from pbp_events_upcoming, same event_type -> stat mapping as pbp_box_score ---
# CONFIRMED CHANGE (requested): the aggregation below used to be written inline against
# pbp_events_upcoming. It is now a function, because a second caller exists: the cell that back-fills
# PAST scouted opponents' stats from their own prior-game PBP. Two copies of an event_type -> stat mapping
# is precisely the drift this notebook has been bitten by before -- one copy gets a fix, the other doesn't,
# and two tables that claim to mean the same thing quietly stop agreeing. One function, two callers.
def box_score_from_pbp_events(events, label="the upcoming opponent's prior game(s)", verbose=True):
    """Player-level box score from parsed PBP events. Empty-but-well-formed frame when there's nothing.

    Columns are keyed (opponent, game_date, team, player) -- note `opponent` here means the THIRD PARTY in
    that game, and `team` is the side the player was on, the same convention pbp_events uses everywhere
    else in this notebook.
    """
    box_cols = ["opponent", "game_date", "team", "player", "PTS", "FGM", "FGA", "FG3M", "FG3A",
                "FTM", "FTA", "OREB", "DREB", "AST", "STL", "BLK", "TO", "PF", "REB", "FG%", "3P%", "FT%"]
    if events is None or events.empty:
        if verbose:
            print(f"No PBP data available for {label} -- box score is empty but well-formed.")
        return pd.DataFrame(columns=box_cols)

    player_events = events[
        events["player"].notna() & (~events["event_type"].isin(TEAM_LEVEL_EVENT_TYPES_BOX))
    ].copy()
    if player_events.empty:
        if verbose:
            print(f"No player-attributed PBP events for {label} -- box score is empty but well-formed.")
        return pd.DataFrame(columns=box_cols)

    player_events["points"] = player_events.apply(
        lambda row: int(row["shot_type"]) if row["event_type"] == "made_shot" else (1 if row["event_type"] == "free_throw_made" else 0),
        axis=1,
    )
    player_events["is_fgm"] = player_events["event_type"] == "made_shot"
    player_events["is_fga"] = player_events["event_type"].isin(["made_shot", "missed_shot"])
    player_events["is_3pm"] = player_events["is_fgm"] & (player_events["shot_type"] == "3")
    player_events["is_3pa"] = player_events["is_fga"] & (player_events["shot_type"] == "3")
    player_events["is_ftm"] = player_events["event_type"] == "free_throw_made"
    player_events["is_fta"] = player_events["event_type"].isin(["free_throw_made", "free_throw_missed"])
    player_events["is_oreb"] = player_events["event_type"] == "rebound_offensive"
    player_events["is_dreb"] = player_events["event_type"] == "rebound_defensive"
    player_events["is_ast"] = player_events["event_type"] == "assist"
    player_events["is_stl"] = player_events["event_type"] == "steal"
    player_events["is_blk"] = player_events["event_type"] == "block"
    player_events["is_to"] = player_events["event_type"] == "turnover"
    player_events["is_pf"] = player_events["event_type"] == "foul"

    box = player_events.groupby(["opponent", "game_date", "team", "player"]).agg(
        PTS=("points", "sum"), FGM=("is_fgm", "sum"), FGA=("is_fga", "sum"),
        FG3M=("is_3pm", "sum"), FG3A=("is_3pa", "sum"), FTM=("is_ftm", "sum"), FTA=("is_fta", "sum"),
        OREB=("is_oreb", "sum"), DREB=("is_dreb", "sum"), AST=("is_ast", "sum"), STL=("is_stl", "sum"),
        BLK=("is_blk", "sum"), TO=("is_to", "sum"), PF=("is_pf", "sum"),
    ).reset_index()

    # Same gap, same fix as pbp_box_score above: a bare team-level turnover (no player attached) is correctly
    # excluded from player_events via the player.notna() filter, but that means it never appeared anywhere
    # in this box score either. Surfaced as a synthetic "TEAM" row instead of silently dropped.
    team_level_turnovers = events[events["player"].isna() & (events["event_type"] == "turnover")]
    if not team_level_turnovers.empty:
        team_to_rows = team_level_turnovers.groupby(["opponent", "game_date", "team"]).size().reset_index(name="TO")
        team_to_rows["player"] = "TEAM"
        for stat_col in ["PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", "AST", "STL", "BLK", "PF"]:
            team_to_rows[stat_col] = 0
        box = pd.concat([box, team_to_rows], ignore_index=True)
        if verbose:
            print(f"Added {len(team_to_rows)} synthetic TEAM row(s) for {int(team_to_rows['TO'].sum())} bare team-level turnover(s) in {label}.")

    box["REB"] = box["OREB"] + box["DREB"]
    box["FG%"] = (100 * box["FGM"] / box["FGA"]).round(1)
    box["3P%"] = (100 * box["FG3M"] / box["FG3A"]).round(1)
    box["FT%"] = (100 * box["FTM"] / box["FTA"]).round(1)
    if verbose:
        print(f"Reconstructed box score for {box['opponent'].nunique()} of {label}, {len(box)} player-game row(s) total.")
    return box


pbp_box_score_upcoming = box_score_from_pbp_events(pbp_events_upcoming)
