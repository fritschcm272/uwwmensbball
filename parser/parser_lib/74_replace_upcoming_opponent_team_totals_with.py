# 74_replace_upcoming_opponent_team_totals_with.py -- code for the notebook section "Override the upcoming opponent's team_totals (PPG / opponent-PPG-allowed) with a PBP-deriv"
# Runs inside the notebook via run_section("74_replace_upcoming_opponent_team_totals_with"); its settings are in that notebook cell.

# --- Override the upcoming opponent's team_totals (PPG / opponent-PPG-allowed) with a PBP-derived aggregate --
# NOTE: no team-level BLK here on purpose. Checked before building it: the app's Team Stats panel already
# computes team Blocks by summing player_profiles' own BLK column and dividing by get_opponent_games_played()
# -- which are both already fixed (the player-level PBP override two cells up, and the games-played scoping
# fix from earlier this project). Sum of player blocks IS the team total, by definition of what a box score
# is, so a separate team-level BLK column here would just be unused dead weight -- confirmed nothing in the
# app reads one before adding it.
# CONFIRMED CHANGE (requested): same fix as the player_profiles override above, and the same underlying
# leak -- prev_games (now reference-date-gated) proves this opponent hasn't played any game yet, so any
# PDF-sourced team_ppg/opp_ppg_allowed is known to describe games that haven't happened as of
# reference_date. Blanked here rather than left in place.
if prev_games.empty and upcoming_opponent_short is not None:
    if not team_totals.empty and upcoming_opponent_short in set(team_totals["opponent"]):
        _tt_mask = team_totals["opponent"] == upcoming_opponent_short
        team_totals.loc[_tt_mask, ["team_ppg", "opp_ppg_allowed"]] = None
        print(f"{upcoming_opponent_short} has no games on record before reference_date ({reference_date_str}) "
              f"-- blanked their PDF-sourced team_totals row rather than showing numbers from games that "
              f"haven't happened yet.")
    else:
        print(f"{upcoming_opponent_short} has no games on record before reference_date ({reference_date_str}) "
              f"and no existing team_totals row to blank -- nothing to do.")
elif pbp_box_score_upcoming.empty or upcoming_opponent_short is None:
    print("No prior-game box score available yet -- upcoming opponent's team_totals left as-is (PDF-sourced, if any).")
else:
    _tt_own = pbp_box_score_upcoming[pbp_box_score_upcoming["team"] == upcoming_opponent_short]
    _tt_opp = pbp_box_score_upcoming[pbp_box_score_upcoming["team"] != upcoming_opponent_short]
    _tt_n_games = pbp_box_score_upcoming["game_date"].nunique()
    if _tt_own.empty or _tt_n_games == 0:
        print(f"No PBP box score data available yet for {upcoming_opponent_short} -- team_totals left as-is.")
    else:
        _tt_team_ppg = round(_tt_own["PTS"].sum() / _tt_n_games, 2)
        _tt_opp_ppg_allowed = round(_tt_opp["PTS"].sum() / _tt_n_games, 2) if not _tt_opp.empty else None

        if team_totals.empty or upcoming_opponent_short not in set(team_totals["opponent"]):
            team_totals = pd.concat([team_totals, pd.DataFrame([{
                "opponent": upcoming_opponent_short, "team_ppg": _tt_team_ppg, "opp_ppg_allowed": _tt_opp_ppg_allowed,
            }])], ignore_index=True)
            print(f"Added a new PBP-derived team_totals row for {upcoming_opponent_short} (none existed from a PDF).")
        else:
            _tt_mask = team_totals["opponent"] == upcoming_opponent_short
            team_totals.loc[_tt_mask, "team_ppg"] = _tt_team_ppg
            if _tt_opp_ppg_allowed is not None:
                team_totals.loc[_tt_mask, "opp_ppg_allowed"] = _tt_opp_ppg_allowed
            print(f"Replaced PDF-sourced team_totals for {upcoming_opponent_short}: team_ppg={_tt_team_ppg}, "
                  f"opp_ppg_allowed={_tt_opp_ppg_allowed} (from {_tt_n_games} prior game(s) of PBP data).")
