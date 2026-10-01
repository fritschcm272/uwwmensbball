# 45_aggregate_upcoming_opponent_5_man_lineup.py -- code for the notebook section "Season-aggregated 5-man lineup box scores for the UPCOMING OPPONENT ----------------------"
# Runs inside the notebook via run_section("45_aggregate_upcoming_opponent_5_man_lineup"); its settings are in that notebook cell.


if pbp_events_upcoming.empty:
    upcoming_lineup_season = pd.DataFrame()
    print(f"No PBP data available for {upcoming_opponent_short} -- "
          "lineup season box scores will populate once PBP files are uploaded.")
else:
    real_up = pbp_events_upcoming[
        pbp_events_upcoming["player"].notna() & (~pbp_events_upcoming["event_type"].isin(TEAM_LEVEL_UPCOMING))
    ].sort_values("event_order")

    def _starting_lineup(team_events):
        first_seen = team_events.groupby("player").first()
        return set(first_seen[first_seen["event_type"] != "sub_in"].index)

    self_lineup_col = pd.Series(index=pbp_events_upcoming.index, dtype=object)
    their_lineup_col = pd.Series(index=pbp_events_upcoming.index, dtype=object)

    # The upcoming opponent has the same problem on their own schedule -- e.g. three meetings with
    # one conference rival all carry the same `opponent` value.
    for (opp_name, opp_game_date), opp_rows in pbp_events_upcoming.groupby(GAME_KEYS, dropna=False):
        opp_real = real_up[(real_up["opponent"] == opp_name) & (real_up["game_date"] == opp_game_date)]
        period_starts = opp_real.dropna(subset=["period"]).groupby("period")["event_order"].min().sort_values()
        periods_in_order = period_starts.index.tolist()

        for team_label, target_col in [(upcoming_opponent_short, self_lineup_col), (opp_name, their_lineup_col)]:
            team_events = opp_real[opp_real["team"] == team_label]
            changes = []
            for period in periods_in_order:
                period_events = team_events[team_events["period"] == period].sort_values("event_order")
                starters = _starting_lineup(period_events)
                current = set(starters)
                changes.append((period_starts[period] - 1, frozenset(current)))
                sub_events = period_events[period_events["event_type"].isin(["sub_in", "sub_out"])].sort_values("event_order")
                for _, row in sub_events.iterrows():
                    if row["event_type"] == "sub_in":
                        current.add(row["player"])
                    else:
                        current.discard(row["player"])
                    if len(current) == 5:
                        changes.append((row["event_order"], frozenset(current)))

            if changes:
                changes_df = pd.DataFrame(changes, columns=["event_order", "lineup"]).sort_values("event_order")
                target_rows = opp_rows.sort_values("event_order")
                merged = pd.merge_asof(target_rows[["event_order"]], changes_df, on="event_order", direction="backward")
                lineup_strings = merged["lineup"].apply(lambda s: ", ".join(sorted(s)) if isinstance(s, frozenset) else None)
                lineup_strings.index = target_rows.index
                target_col.loc[target_rows.index] = lineup_strings

    pbp_up = pbp_events_upcoming.copy()
    pbp_up["self_lineup"] = self_lineup_col
    pbp_up["their_lineup"] = their_lineup_col

    # CONFIRMED CHANGE (requested): self_lineup used to live only on this cell's local `pbp_up` copy, so
    # nothing downstream of THIS cell could look up "which 5-man unit was on the floor" for a given
    # possession -- including the play-calls cell, which needs exactly that to cross-reference a decoded
    # play call with the personnel grouping running it. Persisted onto the real pbp_events_upcoming here so
    # it survives past this cell. (uww_lineup/opp_lineup already work the same way for UWW's own games --
    # see the "On-court 5-man lineups" cell earlier -- this just closes the equivalent gap on the opponent
    # side, which is why the play-calls cell was moved to run after this one.)
    pbp_events_upcoming["self_lineup"] = self_lineup_col
    # CONFIRMED CHANGE (requested: "we also know which 5 players were on the court for each team"): the OTHER
    # team's five is persisted too, so every opponent-game clip knows both lineups (offense and defense).
    pbp_events_upcoming["their_lineup"] = their_lineup_col

    stint_src = pbp_up[pbp_up["event_type"] != "period_marker"].sort_values(GAME_KEYS + ["event_order"]).copy()
    prev_self = stint_src.groupby(GAME_KEYS, dropna=False)["self_lineup"].shift(1)
    prev_their = stint_src.groupby(GAME_KEYS, dropna=False)["their_lineup"].shift(1)
    stint_changed = (stint_src["self_lineup"] != prev_self) | (stint_src["their_lineup"] != prev_their)
    stint_src["stint_num"] = stint_changed.fillna(True).groupby([stint_src[k] for k in GAME_KEYS]).cumsum()
    stint_src["prev_self_score"] = stint_src.groupby(GAME_KEYS, dropna=False)["uww_score"].shift(1).fillna(0)
    stint_src["prev_their_score"] = stint_src.groupby(GAME_KEYS, dropna=False)["opp_score"].shift(1).fillna(0)
    stint_src["clock"] = stint_src.groupby(GAME_KEYS + ["period"], dropna=False)["time_remaining_seconds"].cummin()
    stint_src["prev_time_remaining_seconds"] = stint_src.groupby(GAME_KEYS + ["period"], dropna=False)["clock"].shift(1)
    stint_src["seconds_elapsed"] = (stint_src["prev_time_remaining_seconds"] - stint_src["clock"]).clip(lower=0).fillna(0)

    stints = stint_src.groupby(GAME_KEYS + ["stint_num", "self_lineup"]).agg(
        end_self_score=("uww_score", "last"), end_their_score=("opp_score", "last"),
        start_prev_self_score=("prev_self_score", "first"), start_prev_their_score=("prev_their_score", "first"),
        stint_seconds=("seconds_elapsed", "sum"),
    ).reset_index()
    stints["margin_change"] = (
        (stints["end_self_score"] - stints["start_prev_self_score"]) -
        (stints["end_their_score"] - stints["start_prev_their_score"])
    )
    stints["stint_minutes"] = (stints["stint_seconds"] / 60).round(2)

    minutes_margin = stints.groupby(GAME_KEYS + ["self_lineup"]).agg(
        MIN=("stint_minutes", "sum"), **{"+/-": ("margin_change", "sum")}
    ).reset_index().rename(columns={"self_lineup": "lineup"})

    lu_events = pbp_up[
        (pbp_up["team"] == upcoming_opponent_short) & pbp_up["self_lineup"].notna()
    ].copy()
    lu_events["lineup"] = lu_events["self_lineup"]
    lu_events["points"] = lu_events.apply(
        lambda r: int(r["shot_type"]) if r["event_type"] == "made_shot" else (1 if r["event_type"] == "free_throw_made" else 0), axis=1)
    lu_events["is_fgm"] = lu_events["event_type"] == "made_shot"
    lu_events["is_fga"] = lu_events["event_type"].isin(["made_shot", "missed_shot"])
    lu_events["is_3pm"] = lu_events["is_fgm"] & (lu_events["shot_type"] == "3")
    lu_events["is_3pa"] = lu_events["is_fga"] & (lu_events["shot_type"] == "3")
    lu_events["is_ftm"] = lu_events["event_type"] == "free_throw_made"
    lu_events["is_fta"] = lu_events["event_type"].isin(["free_throw_made", "free_throw_missed"])
    lu_events["is_oreb"] = lu_events["event_type"].isin(["rebound_offensive", "team_deadball_rebound_offensive"])
    lu_events["is_dreb"] = lu_events["event_type"].isin(["rebound_defensive", "team_deadball_rebound_defensive"])
    lu_events["is_ast"] = lu_events["event_type"] == "assist"
    lu_events["is_stl"] = lu_events["event_type"] == "steal"
    lu_events["is_blk"] = lu_events["event_type"] == "block"
    lu_events["is_to"] = lu_events["event_type"] == "turnover"
    lu_events["is_pf"] = lu_events["event_type"] == "foul"

    per_game_lineup = lu_events.groupby(GAME_KEYS + ["lineup"], as_index=False).agg(
        PTS=("points", "sum"), FGM=("is_fgm", "sum"), FGA=("is_fga", "sum"),
        FG3M=("is_3pm", "sum"), FG3A=("is_3pa", "sum"), FTM=("is_ftm", "sum"), FTA=("is_fta", "sum"),
        OREB=("is_oreb", "sum"), DREB=("is_dreb", "sum"), AST=("is_ast", "sum"), STL=("is_stl", "sum"),
        BLK=("is_blk", "sum"), TO=("is_to", "sum"), PF=("is_pf", "sum"),
    )
    per_game_lineup["REB"] = per_game_lineup["OREB"] + per_game_lineup["DREB"]
    per_game_lineup = per_game_lineup.merge(minutes_margin, on=GAME_KEYS + ["lineup"], how="left")

    upcoming_lineup_season = per_game_lineup.groupby("lineup").agg(
        GP=("game_date", "nunique"),
        MIN=("MIN", "sum"),
        **{"+/-": ("+/-", "sum")},
        PTS=("PTS", "sum"), FGM=("FGM", "sum"), FGA=("FGA", "sum"),
        FG3M=("FG3M", "sum"), FG3A=("FG3A", "sum"), FTM=("FTM", "sum"), FTA=("FTA", "sum"),
        OREB=("OREB", "sum"), DREB=("DREB", "sum"), REB=("REB", "sum"),
        AST=("AST", "sum"), STL=("STL", "sum"), BLK=("BLK", "sum"), TO=("TO", "sum"), PF=("PF", "sum"),
    ).reset_index()
    upcoming_lineup_season["FG%"] = (100 * upcoming_lineup_season["FGM"] / upcoming_lineup_season["FGA"]).round(1)
    upcoming_lineup_season["3P%"] = (100 * upcoming_lineup_season["FG3M"] / upcoming_lineup_season["FG3A"]).round(1)
    upcoming_lineup_season["FT%"] = (100 * upcoming_lineup_season["FTM"] / upcoming_lineup_season["FTA"]).round(1)
    upcoming_lineup_season["MIN"] = upcoming_lineup_season["MIN"].round(1)
    upcoming_lineup_season = upcoming_lineup_season.sort_values("MIN", ascending=False).reset_index(drop=True)

    print(f"{upcoming_opponent_short} season 5-man lineup box scores "
          f"({upcoming_lineup_season['GP'].max()} game(s) of PBP data, "
          f"{len(upcoming_lineup_season)} distinct units):")
    print(upcoming_lineup_season[[
        "lineup", "GP", "MIN", "+/-", "PTS", "FGM", "FGA", "FG%",
        "FG3M", "FG3A", "3P%", "FTM", "FTA", "FT%",
        "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF",
    ]])
