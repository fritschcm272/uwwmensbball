# 73_replace_upcoming_opponent_pdf_scouting.py -- code for the notebook section "Override the upcoming opponent's player_profiles stats with a PBP-derived aggregate ------"
# Runs inside the notebook via run_section("73_replace_upcoming_opponent_pdf_scouting"); its settings are in that notebook cell.

# --- Override the upcoming opponent's player_profiles stats with a PBP-derived aggregate ---------------------
# CONFIRMED CHANGE (requested): reference_date can be set before the opponent has played ANY game at all
# -- confirmed directly via their OWN schedule, prev_games, which is now correctly reference-date-gated
# (see the prev_games fix above). In that case, a PDF scout report's stats (if one already exists, dated
# from whenever it was actually compiled in the real world) aren't just "not yet overridden" -- they're
# KNOWN to describe games that, as of reference_date, haven't happened yet. Leaving them in place is
# exactly the leak reported live: "Opponent Scoring Reliance" showing real numbers for an opponent who
# hasn't played a game this year. Blank the stat columns outright here, rather than leaving PDF-sourced
# numbers in place, since their own schedule is direct proof no legitimate stats can exist yet.
if prev_games.empty and upcoming_opponent_short is not None:
    _pu_upcoming_mask = player_profiles["opponent"] == upcoming_opponent_short
    _pu_blank_cols = ["MIN", "FG%", "3PM-A", "3P%", "FTM-A", "FT%", "REB", "OREB", "DREB", "AST", "TO", "STL", "BLK", "PTS", "games_played"]
    for _pu_col in _pu_blank_cols:
        if _pu_col in player_profiles.columns:
            player_profiles.loc[_pu_upcoming_mask, _pu_col] = None
    print(f"{upcoming_opponent_short} has no games on record before reference_date ({reference_date_str}) -- "
          f"blanked any PDF-sourced season stats for their {int(_pu_upcoming_mask.sum())} player_profiles "
          f"row(s) rather than showing numbers from games that haven't happened yet.")
elif pbp_box_score_upcoming.empty or upcoming_opponent_short is None:
    print("No prior-game box score available yet -- upcoming opponent's player_profiles stats left as-is (PDF-sourced, if any).")
else:
    _pu_own_box = pbp_box_score_upcoming[pbp_box_score_upcoming["team"] == upcoming_opponent_short].copy()
    _pu_own_box = _pu_own_box[_pu_own_box["player"] != "TEAM"]  # exclude the synthetic bare-turnover row
    if _pu_own_box.empty:
        print(f"No player-level PBP box score data available yet for {upcoming_opponent_short} -- player_profiles stats left as-is.")
    else:
        _pu_agg = _pu_own_box.groupby("player").agg(
            games=("game_date", "nunique"),
            PTS_total=("PTS", "sum"), REB_total=("REB", "sum"), MIN_total=("MIN", "sum"),
            OREB_total=("OREB", "sum"), DREB_total=("DREB", "sum"),
            FGM=("FGM", "sum"), FGA=("FGA", "sum"), FG3M=("FG3M", "sum"), FG3A=("FG3A", "sum"),
            FTM=("FTM", "sum"), FTA=("FTA", "sum"),
            AST=("AST", "sum"), STL=("STL", "sum"), BLK=("BLK", "sum"), TO=("TO", "sum"),
        ).reset_index()

        # PTS/REB/MIN/OREB/DREB: per-game averages (matches player_profiles' existing convention for PTS/REB/
        # MIN; OREB/DREB are new here -- the PDF-sourced player_profiles table never had a rebound split at
        # all, only combined REB, so these two columns didn't exist on this table before this override).
        # AST/STL/BLK/TO: left as SEASON TOTALS on purpose -- get_opponent_games_played() divides these
        # downstream throughout the app; pre-dividing here would double-divide them.
        _pu_agg["PTS"] = (_pu_agg["PTS_total"] / _pu_agg["games"]).round(1)
        _pu_agg["REB"] = (_pu_agg["REB_total"] / _pu_agg["games"]).round(1)
        _pu_agg["MIN"] = (_pu_agg["MIN_total"] / _pu_agg["games"]).round(1)
        _pu_agg["OREB"] = (_pu_agg["OREB_total"] / _pu_agg["games"]).round(1)
        _pu_agg["DREB"] = (_pu_agg["DREB_total"] / _pu_agg["games"]).round(1)
        # CONFIRMED BUG (fixed here): the original `.astype(str).replace("nan", "")` approach for a
        # zero-attempts player (FGA/FG3A/FTA == 0, a real case -- e.g. a player who saw the floor but never
        # attempted a 3) doesn't actually work in this pandas version: .astype(str) on a float NaN keeps it
        # as an actual null rather than stringifying it to the literal text "nan", so .replace("nan", "") has
        # nothing to match and the NaN survives all the way through, then poisons the "+ \'%\'" concatenation
        # into another NaN. Verified directly (not assumed) before shipping this fix -- the old code would
        # have left a real, silent NaN in this column for exactly the players this was meant to handle
        # gracefully. Using an explicit per-value formatter instead of a dtype-fragile string trick.
        def _pct_str(v):
            return f"{v}%" if pd.notna(v) else "-"
        _pu_agg["FG%"] = (100 * _pu_agg["FGM"] / _pu_agg["FGA"]).round(1).apply(_pct_str)
        _pu_agg["3P%"] = (100 * _pu_agg["FG3M"] / _pu_agg["FG3A"]).round(1).apply(_pct_str)
        _pu_agg["FT%"] = (100 * _pu_agg["FTM"] / _pu_agg["FTA"]).round(1).apply(_pct_str)
        _pu_agg["3PM-A"] = _pu_agg["FG3M"].astype(int).astype(str) + "-" + _pu_agg["FG3A"].astype(int).astype(str)
        _pu_agg["FTM-A"] = _pu_agg["FTM"].astype(int).astype(str) + "-" + _pu_agg["FTA"].astype(int).astype(str)

        # AST/STL/BLK/TO stay SEASON TOTALS (the app divides them) -- but the app was dividing by the
        # TEAM's games played, which understates anyone who missed time: Gavin Sarvis' 73 assists in the 24
        # games he actually played rendered as 2.6/gm instead of 3.0 because the divisor was Loras' 28.
        # Ship each player's own games-played alongside the totals so the app can divide correctly.
        _pu_agg["games_played"] = _pu_agg["games"]
        _pu_stat_cols = ["MIN", "FG%", "3PM-A", "3P%", "FTM-A", "FT%", "REB", "OREB", "DREB", "AST", "TO", "STL", "BLK", "PTS", "games_played"]
        if "games_played" not in player_profiles.columns:
            player_profiles["games_played"] = pd.NA
        _pu_replacement = _pu_agg[["player"] + _pu_stat_cols].rename(columns={"player": "name"})

        # Match by player name (pbp_box_score_upcoming has no jersey_number) -- case-insensitive, since roster
        # names elsewhere in this notebook are sometimes cased slightly differently between sources.
        _pu_upcoming_mask = player_profiles["opponent"] == upcoming_opponent_short
        _pu_name_to_row = {str(n).strip().casefold(): row for n, row in zip(_pu_replacement["name"], _pu_replacement.to_dict("records"))}
        _pu_n_matched = 0
        for _pu_idx in player_profiles[_pu_upcoming_mask].index:
            _pu_key = str(player_profiles.at[_pu_idx, "name"]).strip().casefold()
            if _pu_key in _pu_name_to_row:
                for _pu_col in _pu_stat_cols:
                    player_profiles.at[_pu_idx, _pu_col] = _pu_name_to_row[_pu_key][_pu_col]
                _pu_n_matched += 1
        print(f"Replaced PDF-sourced stats with PBP-derived stats for {_pu_n_matched} of {_pu_upcoming_mask.sum()} "
              f"{upcoming_opponent_short} player_profiles row(s), from {_pu_agg['games'].max()} prior game(s) of PBP data.")

        # --- Add PBP-derived players who have NO scout-report entry at all ---------------------------------
        # CONFIRMED BUG (fixed here): the loop above only ever UPDATES rows that already exist in
        # player_profiles, so a player who shows up in the opponent's prior-game PBP but was never in the
        # scout report was dropped on the floor entirely -- and with him, his contribution to every
        # team-level sum the app builds off this table.
        #
        # Confirmed case: Andrew Wells had 2 blocks for Eureka vs Dominican (IL), but "Wells" appears nowhere
        # in Eureka's scout report -- not in the roster AND not in its season BOXSCORE table, so the
        # `box_only` backfill in the player_profiles cell can't recover him either (that one only rescues
        # players the scout report's own boxscore lists). The app therefore summed 3 of Eureka's 5 blocks and
        # rendered 1.0 BPG (3/3) instead of 1.67 (5/3). Note the failing number was the NUMERATOR -- the
        # games-played denominator was correct all along.
        #
        # These additions get the same treatment `box_only` gives its own: role="Bench",
        # has_scouting_report=False, null demographics. jersey_number stays null because
        # pbp_box_score_upcoming has no jersey column (that's why the update loop above matches on name).
        _pu_existing = {str(n).strip().casefold() for n in player_profiles.loc[_pu_upcoming_mask, "name"].dropna()}
        _pu_add = _pu_replacement[
            ~_pu_replacement["name"].astype(str).str.strip().str.casefold().isin(_pu_existing)
        ].copy()
        if not _pu_add.empty:
            _pu_add["opponent"] = upcoming_opponent_short
            _pu_add["game_date"] = game_date_for(upcoming_opponent_short)
            _pu_add["jersey_number"] = None
            _pu_add["role"] = "Bench"
            _pu_add["has_scouting_report"] = False
            _pu_add["position_group"] = "Unknown"
            _pu_add["player_notes"] = ""
            _pu_add["keys_to_defending"] = ""
            _pu_add["notes_tags_display"] = ""
            _pu_add["keys_tags_display"] = ""
            for _pu_missing_col in player_profiles.columns:
                if _pu_missing_col not in _pu_add.columns:
                    _pu_add[_pu_missing_col] = None
            # Assigned AFTER the None-fill loop above on purpose: these two columns hold real sets (other
            # cells call set operations on them directly), and a column of shared Nones would break that.
            _pu_add["notes_tags"] = [set() for _ in range(len(_pu_add))]
            _pu_add["keys_tags"] = [set() for _ in range(len(_pu_add))]
            player_profiles = pd.concat(
                [player_profiles, _pu_add[player_profiles.columns.tolist()]], ignore_index=True
            )
            # _pu_upcoming_mask was built against the PRE-concat frame; reusing a now-too-short boolean mask
            # against the grown frame is a pandas IndexingError, so rebuild it before the diagnostics below.
            _pu_upcoming_mask = player_profiles["opponent"] == upcoming_opponent_short
            print(f"  Added {len(_pu_add)} PBP-only player(s) with no scout-report entry at all "
                  f"(role=Bench): {sorted(_pu_add['name'].astype(str))}")

            # Mirror the same additions into all_rosters, which is exported as uww_opponent_rosters and is
            # what the app's ROSTER panel reads -- without this a PBP-only player shows up in the team-stat
            # sums (player_profiles) but is invisible in the roster list, which reads as a data bug to whoever
            # is checking the numbers by hand. Kept to roster_cols only: all_rosters is the pre-enrichment
            # table (no stat columns, no tag columns).
            _pu_roster_add = _pu_add[[c for c in roster_cols if c in _pu_add.columns]].copy()
            for _pu_missing_roster_col in roster_cols:
                if _pu_missing_roster_col not in _pu_roster_add.columns:
                    _pu_roster_add[_pu_missing_roster_col] = None
            # Independent dedupe rather than relying on the enclosing `if not _pu_add.empty` guard: that guard
            # is driven by player_profiles, so re-running the player-profiles cell WITHOUT re-running the
            # roster cell would otherwise append a second copy of the same player here.
            _pu_roster_have = {
                (str(o).strip().casefold(), str(n).strip().casefold())
                for o, n in zip(all_rosters.get("opponent", []), all_rosters.get("name", []))
            }
            _pu_roster_add = _pu_roster_add[[
                (str(r["opponent"]).strip().casefold(), str(r["name"]).strip().casefold()) not in _pu_roster_have
                for _, r in _pu_roster_add.iterrows()
            ]]
            if not _pu_roster_add.empty:
                all_rosters = pd.concat([all_rosters, _pu_roster_add[roster_cols]], ignore_index=True)
                print(f"  Also added {len(_pu_roster_add)} of them to all_rosters (uww_opponent_rosters) so "
                      f"they appear in the app's ROSTER panel, not just the team-stat sums.")
        else:
            print("  No PBP-only players to add -- every player in the prior-game PBP already had a "
                  "player_profiles row.")
        _pu_roster_names = set(player_profiles.loc[_pu_upcoming_mask, "name"].astype(str))
        _pu_pbp_names = set(_pu_replacement["name"].astype(str))
        _pu_unmatched_names = _pu_roster_names - _pu_pbp_names
        if _pu_unmatched_names:
            print(f"  Roster player(s) with no matching PBP box-score row yet (kept their PDF-sourced stats, if any): {sorted(_pu_unmatched_names)}")
        # STRENGTHENED DIAGNOSTIC -- this exact override has now been reported as "still showing the old
        # number" once already; rather than guess a third time, print everything needed to tell apart the
        # three real possibilities in one look: (a) a genuine name-spelling mismatch between the roster and
        # what got parsed off the raw PBP text (b) the override ran but the app is reading a stale/un-
        # redeployed CSV (c) this cell genuinely hasn't been re-run since the fix went in.
        print(f"\n  Roster names for {upcoming_opponent_short} ({len(_pu_roster_names)}): {sorted(_pu_roster_names)}")
        print(f"  PBP-derived names found ({len(_pu_pbp_names)}): {sorted(_pu_pbp_names)}")
        print("  Per-player PTS after this override (spot-check against what the app is showing):")
        _show(player_profiles.loc[_pu_upcoming_mask, ["name", "PTS"]].sort_values("PTS", ascending=False))
