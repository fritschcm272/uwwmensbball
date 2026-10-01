# 43_diagnostic.py -- code for the notebook section "Diagnostic: reconcile uww_team_schedule (what the app expects a box score for) against pbp"
# Runs inside the notebook via run_section("43_diagnostic"); its settings are in that notebook cell.

# --- Diagnostic: reconcile uww_team_schedule (what the app expects a box score for) against pbp_box_score
# (what actually got built) -- prints a specific reason for every gap instead of leaving it to be discovered
# later as a blank "Box Score" section in the Streamlit app.
if uww_team_schedule.empty:
    print("uww_team_schedule is empty -- nothing to reconcile.")
else:
    _pbp_opponents_found = set(pbp_events["opponent"].dropna().unique()) if not pbp_events.empty else set()
    _box_opponents_found = set(pbp_box_score["opponent"].dropna().unique()) if not pbp_box_score.empty else set()
    _has_creds = bool(fastscout_username and fastscout_password)

    _gaps = []
    for _, _g in uww_team_schedule.iterrows():
        if _g.get("Upcoming") == "Yes":
            continue  # hasn't been played yet -- not expected to have a box score
        _opp_full = str(_g.get("opponent", ""))
        _opp_short = next((s for s in scouted_opponents if re.search(re.escape(s), _opp_full, re.IGNORECASE)), None)
        if _opp_short is None:
            _gaps.append((_opp_full, "not in scouted_opponents -- no scout report was matched for this game at all"))
            continue
        if _opp_short in _box_opponents_found:
            continue  # has a box score -- nothing to report
        _g_date = parse_schedule_date(_g["date"], uww_season_start_year) if pd.notna(_g.get("date")) else None
        _local_pbp = glob.glob(f"{volume_dir}/*{_opp_short}*_pbp.*") if _g_date is None else glob.glob(
            f"{volume_dir}/{_g_date.month}_{_g_date.day}_{_g_date.strftime('%y')}*{_opp_short}*_pbp.*"
        )
        if _opp_short in _pbp_opponents_found:
            reason = (
                f"PBP events exist under opponent name mismatch -- check whether any of "
                f"{sorted(_pbp_opponents_found)} was actually meant to be '{_opp_short}' "
                f"(opponent_from_pbp_filename() derives this from the _pbp file's own filename)"
            )
        elif _local_pbp:
            reason = f"a local PBP file exists ({[os.path.basename(p) for p in _local_pbp]}) but produced no box score rows -- check its parsing for errors/UNCLASSIFIED events"
        elif not _has_creds:
            reason = "no local _pbp file found, and no FASTSCOUT_USERNAME/FASTSCOUT_PASSWORD were set to attempt a live scrape"
        else:
            reason = "no local _pbp file found, and the live-scrape fallback either wasn't attempted or failed -- check the earlier cell's output for this opponent's name"
        _gaps.append((_opp_short, reason))

    if not _gaps:
        print("Every played, scouted game in uww_team_schedule has a box score in pbp_box_score. No gaps found.")
    else:
        print(f"{len(_gaps)} played game(s) are missing a box score:\n")
        for opp, reason in _gaps:
            print(f"  {opp}: {reason}")
