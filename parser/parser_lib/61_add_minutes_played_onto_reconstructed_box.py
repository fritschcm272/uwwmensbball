# 61_add_minutes_played_onto_reconstructed_box.py -- code for the notebook section "Derive per-player minutes played from lineup_stints and merge onto pbp_box_score ---------"
# Runs inside the notebook via run_section("61_add_minutes_played_onto_reconstructed_box"); its settings are in that notebook cell.

# --- Derive per-player minutes played from lineup_stints and merge onto pbp_box_score ------------------
_minutes_rows = []
for _, _stint in lineup_stints.iterrows():
    if pd.notna(_stint["uww_lineup"]):
        for _player in str(_stint["uww_lineup"]).split(", "):
            _minutes_rows.append({"opponent": _stint["opponent"], "game_date": _stint["game_date"], "team": "UW-Whitewater", "player": _player, "minutes": _stint["stint_minutes"]})
    if pd.notna(_stint["opp_lineup"]):
        for _player in str(_stint["opp_lineup"]).split(", "):
            _minutes_rows.append({"opponent": _stint["opponent"], "game_date": _stint["game_date"], "team": _stint["opponent"], "player": _player, "minutes": _stint["stint_minutes"]})

if _minutes_rows:
    player_minutes = pd.DataFrame(_minutes_rows).groupby(GAME_KEYS + ["team", "player"])["minutes"].sum().reset_index()
    player_minutes["MIN"] = player_minutes["minutes"].round(1)
    if "MIN" in pbp_box_score.columns:
        pbp_box_score = pbp_box_score.drop(columns=["MIN"])
    # Merged on the game, not just the opponent. Merging on (opponent, team, player) attached ONE
    # combined minutes figure to EVERY meeting's row against that opponent.
    pbp_box_score = pbp_box_score.merge(player_minutes[GAME_KEYS + ["team", "player", "MIN"]], on=GAME_KEYS + ["team", "player"], how="left")
    _n_matched = int(pbp_box_score["MIN"].notna().sum())
    print(f"Matched minutes played for {_n_matched} of {len(pbp_box_score)} pbp_box_score row(s).")
else:
    pbp_box_score["MIN"] = None
    print("No lineup stints available yet -- pbp_box_score.MIN left empty.")
