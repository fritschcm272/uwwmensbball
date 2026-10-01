# 72_minutes_played_for_upcoming_opponent_prior.py -- code for the notebook section "Minutes played for BOTH sides of the upcoming opponent's prior games, reusing cell above's"
# Runs inside the notebook via run_section("72_minutes_played_for_upcoming_opponent_prior"); its settings are in that notebook cell.

# --- Minutes played for BOTH sides of the upcoming opponent's prior games, reusing cell above's work --------
if pbp_events_upcoming.empty or "stint_src" not in globals():
    pbp_box_score_upcoming["MIN"] = None
    lineup_stints_upcoming = pd.DataFrame(columns=["opponent", "lineup", "MIN", "+/-"])
    print("No prior-game lineup data available yet -- MIN and lineup_stints_upcoming left empty.")
else:
    # Third-party side: same stint_seconds already computed in stint_src above, just grouped by their_lineup
    # instead of self_lineup (which is all the season-box cell needed and kept).
    third_party_minutes_by_lineup = stint_src.groupby(GAME_KEYS + ["their_lineup"])["seconds_elapsed"].sum().reset_index()
    third_party_minutes_by_lineup["MIN"] = (third_party_minutes_by_lineup["seconds_elapsed"] / 60).round(2)

    def _lineup_minutes_to_player_minutes(df, lineup_col, team_col_value_fn):
        rows = []
        for _, r in df.iterrows():
            if pd.isna(r[lineup_col]):
                continue
            for player in str(r[lineup_col]).split(", "):
                rows.append({"opponent": r["opponent"], "game_date": r["game_date"], "team": team_col_value_fn(r), "player": player, "minutes": r["MIN"]})
        return rows

    _self_rows = _lineup_minutes_to_player_minutes(
        minutes_margin.rename(columns={"lineup": "self_lineup"}), "self_lineup", lambda r: upcoming_opponent_short,
    )
    _third_party_rows = _lineup_minutes_to_player_minutes(
        third_party_minutes_by_lineup, "their_lineup", lambda r: r["opponent"],
    )

    _pu_minutes_rows = _self_rows + _third_party_rows
    if _pu_minutes_rows:
        _pu_player_minutes = pd.DataFrame(_pu_minutes_rows).groupby(GAME_KEYS + ["team", "player"])["minutes"].sum().reset_index()
        _pu_player_minutes["MIN"] = _pu_player_minutes["minutes"].round(1)
        if "MIN" in pbp_box_score_upcoming.columns:
            pbp_box_score_upcoming = pbp_box_score_upcoming.drop(columns=["MIN"])
        pbp_box_score_upcoming = pbp_box_score_upcoming.merge(
            _pu_player_minutes[GAME_KEYS + ["team", "player", "MIN"]], on=GAME_KEYS + ["team", "player"], how="left",
        )
        _pu_n_matched = int(pbp_box_score_upcoming["MIN"].notna().sum())
        print(f"Matched minutes played for {_pu_n_matched} of {len(pbp_box_score_upcoming)} pbp_box_score_upcoming row(s).")
    else:
        pbp_box_score_upcoming["MIN"] = None
        print("No lineup stints available yet -- pbp_box_score_upcoming.MIN left empty.")

    # Per-game lineup stints for the upcoming opponent's OWN lineups, already reconstructed above (`stints`) --
    # exported directly rather than rebuilt, matching upcoming_lineup_season's own scope (their own lineups
    # only; third-party lineup stints aren't exported standalone since nothing in the app needs that yet).
    lineup_stints_upcoming = stints.rename(columns={"self_lineup": "lineup"})[GAME_KEYS + ["lineup", "stint_minutes", "margin_change"]]

# --- Who STARTED each of the upcoming opponent's prior games -------------------------------------------------
# CONFIRMED CHANGE (requested): the brief's personnel pages now split Starters from the bench tiers the app
# uses. UWW's own box score already carries `started` (read from the official box-score asterisks), but the
# opponent's prior-game box score is rebuilt from play-by-play and never had one -- so with before_scout="yes"
# (no scouting-report roles) there was no way to say who starts. The play-by-play's own lineup reconstruction
# already knows the first five-man unit on the floor in each game (self_lineup, persisted onto
# pbp_events_upcoming by the season-lineup cell), and those five are the starters by definition.
pbp_box_score_upcoming["started"] = False
if not pbp_events_upcoming.empty and "self_lineup" in pbp_events_upcoming.columns:
    _st_src = pbp_events_upcoming.dropna(subset=["self_lineup"])
    if "event_order" in _st_src.columns:
        _st_src = _st_src.sort_values("event_order")
    _st_first = _st_src.groupby(GAME_KEYS)["self_lineup"].first()
    _st_by_game = {k: {p.strip() for p in str(v).split(",") if p.strip()} for k, v in _st_first.items()}
    pbp_box_score_upcoming["started"] = pbp_box_score_upcoming.apply(
        lambda r: r["team"] == upcoming_opponent_short
        and r["player"] in _st_by_game.get((r["opponent"], r["game_date"]), set()),
        axis=1,
    )
    print(f"Starters detected for {len(_st_by_game)} of {upcoming_opponent_short}'s prior game(s).")
