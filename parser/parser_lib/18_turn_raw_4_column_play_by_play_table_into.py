# 18_turn_raw_4_column_play_by_play_table_into.py -- code for the notebook section "e.g. "Start 1st Half" / "End 2nd Half" -- no team/player/score attached to these marker ro"
# Runs inside the notebook via run_section("18_turn_raw_4_column_play_by_play_table_into"); its settings are in that notebook cell.

def parse_time_to_seconds(time_raw):
    """'19:58 (H1)' -> ('H1', 1198)."""
    if pd.isna(time_raw):
        return None, None
    m = re.match(r"(\d+):(\d+)\s*\((\w+)\)", str(time_raw).strip())
    if not m:
        return None, None
    minutes, seconds, period = m.groups()
    return period, int(minutes) * 60 + int(seconds)


def build_pbp_events(raw_df, opponent, game_date, self_team="UW-Whitewater", self_column="uww_text"):
    """One row per event (or per period-start/end marker), carrying the running score after that event.
    `self_team` labels whichever column `self_column` points at. Defaults match UW-Whitewater's own game files,
    where the "uww_text" column is always UWW's own events. For an opponent's OWN schedule snapshot (e.g.
    scouting an opponent's games before they face Whitewater), FastScout puts the exporting team's own events in
    a FIXED column regardless of home/away -- but which raw column that is varies file-to-file depending on
    whose FastScout account captured it, so the caller must resolve `self_column` empirically (e.g. by matching
    known roster player names) rather than assume "uww_text"."""
    rows = []
    current_period = None
    for i, r in raw_df.iterrows():
        period, seconds = parse_time_to_seconds(r["time_raw"])
        if period:
            current_period = period
        score_raw = r["score_raw"]
        score_m = re.match(r"^(\d+)-(\d+)$", str(score_raw).strip()) if pd.notna(score_raw) else None
        if score_m is None:
            # e.g. "Start 1st Half" / "End 2nd Half" -- no team/player/score attached to these marker rows
            rows.append({
                "opponent": opponent, "game_date": game_date, "event_order": i, "period": current_period,
                "time_remaining": None, "time_remaining_seconds": None, "team": None,
                "event_type": "period_marker", "raw_text": str(score_raw).strip(),
                "uww_score": None, "opp_score": None,
            })
            continue
        uww_score, opp_score = int(score_m.group(1)), int(score_m.group(2))
        # CONFIRMED BUG (found 11/19 from the brief: Hope's late possessions against Franklin were labelled
        # "Trailing by 10+" when Hope were WINNING by 20). The score cell follows the TABLE'S COLUMN ORDER --
        # header "Time | <Team A> | Score | <Team B>" means "<A>-<B>" -- but these two names were assigned
        # positionally no matter which column `self_column` points at. For UWW's own files that is right
        # (36_ pre-swaps the columns AND reverses the score before calling), but an opponent's own file puts
        # their events in whichever column their FastScout account captured, and all four of Hope's prior
        # games put them SECOND. Everything that reads "uww_score" as the self_team's score was therefore
        # inverted on those games: the Leading/Trailing labels, and -- the costly one -- 45_'s opponent
        # lineup +/-, which feeds "their worst net-rating units" on the keys, the cards and the app. Hope's
        # stints summed to -6 and -20 in games they won by 6 and 20. The clutch filter uses abs(margin), so
        # it was never affected. Scores now follow self_column, as the events already do.
        if self_column != "uww_text":
            uww_score, opp_score = opp_score, uww_score
        opp_column = "opp_text" if self_column == "uww_text" else "uww_text"
        for team_label, text in [(self_team, r[self_column]), (opponent, r[opp_column])]:
            if pd.notna(text) and str(text).strip():
                rows.append({
                    "opponent": opponent, "game_date": game_date, "event_order": i, "period": current_period,
                    "time_remaining": r["time_raw"], "time_remaining_seconds": seconds, "team": team_label,
                    "raw_text": str(text).strip(), "uww_score": uww_score, "opp_score": opp_score,
                    **classify_event(str(text).strip()),
                })
    return pd.DataFrame(rows)
