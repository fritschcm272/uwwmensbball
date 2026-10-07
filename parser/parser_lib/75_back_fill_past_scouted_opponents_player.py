# 75_back_fill_past_scouted_opponents_player.py -- code for the notebook section "Back-fill PAST scouted opponents' player_profiles stats from their own prior-game PBP ----"
# Runs inside the notebook via run_section("75_back_fill_past_scouted_opponents_player"); its settings are in that notebook cell.

# --- Back-fill PAST scouted opponents' player_profiles stats from their own prior-game PBP -----------------
# CONFIRMED BUG (fixed here): player_profiles' stat columns are set all-null for EVERY opponent in the
# player-profiles cell (scouting-report stats are last-season data, disabled parser-wide). The only thing
# that ever filled them back in was the PBP override a couple of cells up, whose mask is
# `player_profiles["opponent"] == upcoming_opponent_short`. So exactly one team per run had stats and every
# previously-scouted opponent kept nulls forever.
#
# Downstream that surfaced as a comparison bug rather than a data bug, which is why it took a while to see:
# player_comparison.py's stat_similarity() returns None when either side has no numbers, similarity_score()
# then labels the pair "scouting notes, no stats", and EVERY row of uww_player_comparisons carried that
# label with an empty compared_PTS -- e.g. Damyen Jackson (Loras) compared to EJ Marshall (Elmhurst) on
# notes alone, despite Elmhurst's five pre-Dec-2 games sitting in INPUT_DIR the whole time. The stat_weight
# term (3 of a possible 11.5 evidence points) was silently unavailable for every comparison ever made.
#
# The cutoff is the same rule prev_games uses, applied per opponent: strictly before the EARLIER of their
# own UWW matchup and reference_date. A past opponent has played plenty of games since we faced them, and
# folding those in would describe a team we never played.
#
# Scope limits, on purpose:
#   - Only fills rows that already exist. Unlike the upcoming-opponent override, this does NOT add
#     PBP-only players to player_profiles/all_rosters: those feed roster panels and team-level sums for
#     the team being prepared for, and quietly growing every past opponent's roster is a bigger change
#     than the bug being fixed here.
#   - MIN is left alone. Minutes come from lineup stints (the cell above), which are only computed for the
#     upcoming opponent; fabricating a minutes column here would be inventing data.
_pp_targets = [o for o in scout_reports if o != upcoming_opponent_short]
_pp_filled_rows, _pp_summary, _pp_skipped = 0, [], []

if not _pp_targets:
    print("No previously-scouted opponents to back-fill.")
else:
    def _pp_own_schedule(opp_name):
        """This opponent's OWN schedule -- in-memory parse first, local backup file second.

        Mirrors the upcoming-opponent path (the team_schedules lookup and the _schedule_file_for fallback),
        rather than reimplementing the naming tolerance those two already carry.
        """
        for ts in team_schedules:
            if ts.empty:
                continue
            team = str(ts["team"].iloc[0])
            if team.lower() in opp_name.lower() or opp_name.lower() in team.lower():
                out = pd.DataFrame({
                    "date": ts["date"],
                    "opponent": ts["opponent"],
                })
                out["game_date"] = out["date"].apply(parse_schedule_date)
                return out
        path = _schedule_file_for(opp_name, opp_name, volume_dir)
        if not os.path.exists(path):
            return None
        raw = pd.read_html(StringIO(str(BeautifulSoup(load_html_snapshot(path), "lxml").find_all("table")[0])))[0]
        out = pd.DataFrame({
            "date": raw["Date"],
            "opponent": raw["Opponent"].apply(lambda x: split_opponent(x)[0]),
        })
        out["game_date"] = out["date"].apply(parse_schedule_date)
        return out

    def _pp_self_column(raw_df, known_names):
        """Which raw PBP column holds this team's own events, resolved by roster-name hits.

        Defined here rather than reusing cell 57's resolve_self_column: that one is created inside an
        `if not opp_schedule.empty:` branch, so on a run with no upcoming opponent it does not exist at
        all and this cell would die with a NameError on a code path that has nothing to do with the
        upcoming game.
        """
        uww_hits = sum(any(n in str(t) for n in known_names) for t in raw_df["uww_text"].dropna())
        opp_hits = sum(any(n in str(t) for n in known_names) for t in raw_df["opp_text"].dropna())
        return "uww_text" if uww_hits >= opp_hits else "opp_text"

    def _pp_uww_matchup_date(opp_name):
        """The date UWW played them, read off UWW's own schedule -- same source upcoming_game comes from."""
        rows = schedule[schedule["opponent"].astype(str).str.contains(re.escape(opp_name), case=False, na=False)]
        if rows.empty:
            return None
        return parse_schedule_date(rows.iloc[0]["date"], uww_season_start_year)

    for _pp_opp in _pp_targets:
        _pp_uww_date = _pp_uww_matchup_date(_pp_opp)
        if _pp_uww_date is None:
            _pp_skipped.append(f"{_pp_opp}: not resolvable on UWW's schedule")
            continue

        _pp_sched = _pp_own_schedule(_pp_opp)
        if _pp_sched is None or _pp_sched.empty:
            _pp_skipped.append(f"{_pp_opp}: no own-schedule file ('{_pp_opp} - Schedule.html/.mhtml')")
            continue

        _pp_cutoff = min(_pp_uww_date, reference_date.date())
        _pp_prev = _pp_sched[_pp_sched["game_date"].notna() & (_pp_sched["game_date"] < _pp_cutoff)]
        if _pp_prev.empty:
            _pp_skipped.append(f"{_pp_opp}: no games before {_pp_cutoff}")
            continue

        # Same column-resolution problem the upcoming opponent has: which raw PBP column holds THIS team's
        # own events depends on whose account exported the snapshot, so resolve it per file against their
        # known roster names rather than assuming.
        _pp_known = set(player_profiles.loc[player_profiles["opponent"] == _pp_opp, "name"].dropna())

        _pp_events_list = []
        _pp_games_found = 0
        for _, _pp_row in _pp_prev.iterrows():
            _pp_date_str = f"{_pp_row['game_date'].month}_{_pp_row['game_date'].day}_{_pp_row['game_date'].strftime('%y')}"
            _pp_files = glob.glob(f"{volume_dir}/{_pp_date_str}*{_pp_opp}*_pbp.*")
            if not _pp_files:
                continue
            _pp_games_found += 1
            for _pp_path in _pp_files:
                _pp_raw = parse_pbp_mhtml(_pp_path)
                _pp_events_list.append(build_pbp_events(
                    _pp_raw, _pp_row["opponent"], _pp_row["game_date"],
                    self_team=_pp_opp, self_column=_pp_self_column(_pp_raw, _pp_known),
                ))

        if not _pp_events_list:
            _pp_skipped.append(f"{_pp_opp}: {len(_pp_prev)} prior game(s) on their schedule, no _pbp file for any of them")
            continue

        _pp_box = box_score_from_pbp_events(
            pd.concat(_pp_events_list, ignore_index=True), label=f"{_pp_opp}'s games before UWW", verbose=False)
        _pp_own = _pp_box[(_pp_box["team"] == _pp_opp) & (_pp_box["player"] != "TEAM")]
        if _pp_own.empty:
            _pp_skipped.append(f"{_pp_opp}: PBP parsed but no rows attributed to them (self-column resolution?)")
            continue

        # Aggregate exactly the way the upcoming-opponent override does, so a number means the same thing
        # whichever side of the comparison it lands on:
        #   PTS/REB/OREB/DREB -> per-game averages
        #   AST/STL/BLK/TO    -> SEASON TOTALS (the app divides these by games_played downstream)
        _pp_agg = _pp_own.groupby("player").agg(
            games=("game_date", "nunique"),
            PTS_total=("PTS", "sum"), REB_total=("REB", "sum"),
            OREB_total=("OREB", "sum"), DREB_total=("DREB", "sum"),
            FGM=("FGM", "sum"), FGA=("FGA", "sum"), FG3M=("FG3M", "sum"), FG3A=("FG3A", "sum"),
            FTM=("FTM", "sum"), FTA=("FTA", "sum"),
            AST=("AST", "sum"), STL=("STL", "sum"), BLK=("BLK", "sum"), TO=("TO", "sum"),
        ).reset_index()
        for _pp_stat in ("PTS", "REB", "OREB", "DREB"):
            _pp_agg[_pp_stat] = (_pp_agg[f"{_pp_stat}_total"] / _pp_agg["games"]).round(1)

        def _pp_pct(v):
            return f"{v}%" if pd.notna(v) else "-"
        _pp_agg["FG%"] = (100 * _pp_agg["FGM"] / _pp_agg["FGA"]).round(1).apply(_pp_pct)
        _pp_agg["3P%"] = (100 * _pp_agg["FG3M"] / _pp_agg["FG3A"]).round(1).apply(_pp_pct)
        _pp_agg["FT%"] = (100 * _pp_agg["FTM"] / _pp_agg["FTA"]).round(1).apply(_pp_pct)
        _pp_agg["3PM-A"] = _pp_agg["FG3M"].astype(int).astype(str) + "-" + _pp_agg["FG3A"].astype(int).astype(str)
        _pp_agg["FTM-A"] = _pp_agg["FTM"].astype(int).astype(str) + "-" + _pp_agg["FTA"].astype(int).astype(str)
        _pp_agg["games_played"] = _pp_agg["games"]

        _pp_cols = ["FG%", "3PM-A", "3P%", "FTM-A", "FT%", "REB", "OREB", "DREB",
                    "AST", "TO", "STL", "BLK", "PTS", "games_played"]
        for _pp_col in _pp_cols:
            if _pp_col not in player_profiles.columns:
                player_profiles[_pp_col] = pd.NA

        _pp_by_name = {str(r["player"]).strip().casefold(): r for r in _pp_agg.to_dict("records")}
        _pp_mask = player_profiles["opponent"] == _pp_opp
        _pp_matched = 0
        for _pp_idx in player_profiles[_pp_mask].index:
            _pp_key = str(player_profiles.at[_pp_idx, "name"]).strip().casefold()
            if _pp_key in _pp_by_name:
                for _pp_col in _pp_cols:
                    player_profiles.at[_pp_idx, _pp_col] = _pp_by_name[_pp_key][_pp_col]
                _pp_matched += 1
        _pp_filled_rows += _pp_matched

        _pp_unmatched = sorted(
            {str(n) for n in player_profiles.loc[_pp_mask, "name"].dropna()}
            - {str(p) for p in _pp_agg["player"]}
        )
        _pp_summary.append({
            "opponent": _pp_opp,
            "UWW matchup": _pp_uww_date,
            "prior games on schedule": len(_pp_prev),
            "with _pbp file": _pp_games_found,
            "players filled": _pp_matched,
            "roster rows": int(_pp_mask.sum()),
            "no PBP match": len(_pp_unmatched),
        })
        if _pp_unmatched:
            print(f"  {_pp_opp}: no PBP box-score rows for {_pp_unmatched} (left blank rather than guessed)")

    print(f"\nBack-filled PBP-derived stats for {_pp_filled_rows} player_profiles row(s) across "
          f"{len(_pp_summary)} past opponent(s).")
    if _pp_summary:
        _show(pd.DataFrame(_pp_summary))
    if _pp_skipped:
        print("\nSkipped (no data, not an error -- these keep blank stats and their comparisons stay "
              "notes-only):")
        for _pp_line in _pp_skipped:
            print(f"  {_pp_line}")

    # Spot-check the reported case directly rather than trusting the counts above.
    _pp_check = player_profiles[player_profiles["opponent"].astype(str).str.contains("Elmhurst", case=False, na=False)]
    if not _pp_check.empty:
        print("\nElmhurst spot-check (season stats BEFORE they played UWW on their matchup date):")
        _show(_pp_check[["name", "games_played", "PTS", "REB", "AST", "FG%", "3P%"]])
