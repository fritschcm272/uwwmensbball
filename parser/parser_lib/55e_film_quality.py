# 55e_film_quality.py -- code for the notebook section "Film quality and coverage: what the film can be trusted for, team by team"
# Runs inside the notebook via run_section("55e_film_quality"); its settings are in that notebook cell.

# --- Film quality and coverage -------------------------------------------------------------------------------------
# CONFIRMED CHANGE (requested, from the film-tracking review): every film-built read in the scouting brief and the app
# now checks how much film there is and how good it is before it's shown, and the Upcoming Game page / brief say up
# front how much film exists on the next opponent. One row per team in the tracked or tagged film:
#   tracked_games / tracked_clips       games and clips player tracking ran on (the team on offense or defense)
#   tagged_offense / tagged_defense     possessions the coaches tagged (a Title or Film Tagging) with the team on
#                                       offense / on defense
#   named_share_pct                     % of the team's on-floor spots (five per clip) where tracking found WHO the
#                                       player is (uww_trk_lineup_slots: located)
#   court_mapped_pct, shot_zone_agree_pct   the court mapping of the team's tracked games: % of frames placed on the
#                                       court, and % of shots whose spot agrees with Synergy's 2 / 3
#   names_ok   named_share_pct >= FILM_NAMES_OK_PCT        -> per-player film reads (who guards whom, help) may go in the brief
#   court_ok   court_mapped_pct >= FILM_COURT_OK_MAPPED and shot_zone_agree_pct >= FILM_COURT_OK_ZONE (on
#              FILM_COURT_MIN_SHOTS+ shots)                 -> the court sections (shot chart, screen spots, court help) may
#              go in the brief
# The app always shows everything (with this table's numbers beside it); only the brief is gated.
# Writes uww_film_quality.csv.
FILM_NAMES_OK_PCT = float(globals().get("FILM_NAMES_OK_PCT", 50))
FILM_COURT_OK_MAPPED = float(globals().get("FILM_COURT_OK_MAPPED", 60))
FILM_COURT_OK_ZONE = float(globals().get("FILM_COURT_OK_ZONE", 80))
FILM_COURT_MIN_SHOTS = int(globals().get("FILM_COURT_MIN_SHOTS", 20))


def _fq_table(name, mem=None):
    """This run's table if an earlier cell built it, else the last exported CSV."""
    for src in (globals().get("_ti_tables") or {}, globals().get("_cz_tables") or {}):
        d = src.get(name)
        if isinstance(d, pd.DataFrame) and not d.empty:
            return d
    if mem is not None:
        d = globals().get(mem)
        if isinstance(d, pd.DataFrame) and not d.empty:
            return d
    try:
        return pd.read_csv(os.path.join(globals().get("APP_DATA_DIR") or OUTPUT_DIR, f"{name}.csv"), low_memory=False)
    except Exception:
        return pd.DataFrame()


def _fq_short_date(d):
    t = pd.to_datetime(d, errors="coerce")
    return f"{t.month}/{t.day}/{str(t.year)[2:]}" if pd.notna(t) else str(d)


_fq_clips = _fq_table("uww_trk_clips")
_fq_slots = _fq_table("uww_trk_lineup_slots", mem="trk_lineup_slots")
_fq_court = _fq_table("uww_court_report", mem="court_report")
_fq_pc = globals().get("play_calls")
if not isinstance(_fq_pc, pd.DataFrame) or _fq_pc.empty:
    _fq_pc = _fq_table("uww_play_calls")
_fq_short = globals().get("upcoming_opponent_short")

_fq_teams = set()
for _d, _cols in ((_fq_clips, ("offense_team", "defense_team")), (_fq_pc, ("offense_team", "defense_team"))):
    for _c in _cols:
        if not _d.empty and _c in _d.columns:
            _fq_teams |= set(_d[_c].dropna().astype(str))
if _fq_short:
    _fq_teams.add(str(_fq_short))
_fq_teams.add(next((t for t in _fq_teams if "whitewater" in t.lower()), "UW-Whitewater"))

# court quality per game, keyed by date (the report's game key is "<date>|<code>")
_fq_court_by_date = {}
if not _fq_court.empty and "game" in _fq_court.columns:
    for _, _r in _fq_court.iterrows():
        _fq_court_by_date[str(_r["game"]).split("|")[0]] = _r

_fq_rows = []
for _t in sorted(_fq_teams):
    rec = {"team": _t, "is_upcoming": bool(_fq_short and _t == str(_fq_short)), "is_uww": "whitewater" in _t.lower()}
    tc = (_fq_clips[(_fq_clips["offense_team"].astype(str) == _t) | (_fq_clips["defense_team"].astype(str) == _t)]
          if not _fq_clips.empty and {"offense_team", "defense_team"} <= set(_fq_clips.columns) else pd.DataFrame())
    dates = sorted(set(tc["game_date"].astype(str).str[:10])) if len(tc) and "game_date" in tc.columns else []
    rec.update(tracked_games=len(dates), tracked_clips=len(tc), last_tracked=dates[-1] if dates else None)
    # who they played in those games, for the line ("3/7/26 vs Washington-St. Louis Bears")
    _vs = []
    for d in dates:
        g = tc[tc["game_date"].astype(str).str[:10] == d]
        opp = sorted((set(g["offense_team"].dropna().astype(str)) | set(g["defense_team"].dropna().astype(str))) - {_t})
        _vs.append(f"{_fq_short_date(d)} vs {opp[0]}" if opp else _fq_short_date(d))
    rec["tracked_vs"] = "; ".join(_vs) or None
    if not _fq_pc.empty and {"offense_team", "defense_team", "decode_quality"} <= set(_fq_pc.columns):
        tagged = ~_fq_pc["decode_quality"].astype(str).isin(["Untagged", "Needs review"])
        rec["tagged_offense"] = int((tagged & (_fq_pc["offense_team"].astype(str) == _t)).sum())
        rec["tagged_defense"] = int((tagged & (_fq_pc["defense_team"].astype(str) == _t)).sum())
        rec["clips_on_file"] = int(((_fq_pc["offense_team"].astype(str) == _t) | (_fq_pc["defense_team"].astype(str) == _t)).sum())
    else:
        rec.update(tagged_offense=0, tagged_defense=0, clips_on_file=0)
    ts = _fq_slots[_fq_slots["team"].astype(str) == _t] if not _fq_slots.empty and "team" in _fq_slots.columns else pd.DataFrame()
    rec["floor_spots"] = len(ts)
    rec["named_share_pct"] = (round(100 * ts["located"].astype(str).str.lower().eq("true").mean()) if len(ts) else None)
    cr = [_fq_court_by_date[d] for d in dates if d in _fq_court_by_date]
    mp = [pd.to_numeric(r.get("mapped_pct"), errors="coerce") for r in cr]
    za = [(pd.to_numeric(r.get("shots_zone_agrees_with_2_or_3_pct"), errors="coerce"),
           pd.to_numeric(r.get("shots_checked"), errors="coerce")) for r in cr]
    mp = [x for x in mp if pd.notna(x)]
    za = [(a, n) for a, n in za if pd.notna(a) and pd.notna(n) and n > 0]
    rec["court_mapped_pct"] = round(float(np.mean(mp))) if mp else None
    rec["shots_checked"] = int(sum(n for _, n in za)) if za else 0
    rec["shot_zone_agree_pct"] = round(sum(a * n for a, n in za) / sum(n for _, n in za)) if za else None
    rec["names_ok"] = bool(rec["named_share_pct"] is not None and rec["named_share_pct"] >= FILM_NAMES_OK_PCT)
    rec["court_ok"] = bool(rec["court_mapped_pct"] is not None and rec["court_mapped_pct"] >= FILM_COURT_OK_MAPPED
                           and rec["shot_zone_agree_pct"] is not None and rec["shot_zone_agree_pct"] >= FILM_COURT_OK_ZONE
                           and rec["shots_checked"] >= FILM_COURT_MIN_SHOTS)
    # the one-line summary the Upcoming Game page and the brief print
    if rec["tracked_games"]:
        film = (f"{rec['tracked_games']} tracked game{'s' if rec['tracked_games'] != 1 else ''} ({rec['tracked_vs']}, "
                f"{rec['tracked_clips']} clips)")
        q = []
        if rec["named_share_pct"] is not None:
            q.append(f"players named on {rec['named_share_pct']}% of floor spots")
        if rec["court_mapped_pct"] is not None:
            q.append(f"court placed on {rec['court_mapped_pct']}% of frames")
        film += (" -- " + ", ".join(q)) if q else ""
    else:
        film = "no tracked games yet"
    rec["film_line"] = (f"{film}; {rec['tagged_offense']} coach-tagged possession{'s' if rec['tagged_offense'] != 1 else ''}"
                        f" on offense, {rec['tagged_defense']} on defense")
    _fq_rows.append(rec)

film_quality = pd.DataFrame(_fq_rows)
for _c in ("named_share_pct", "court_mapped_pct", "shot_zone_agree_pct"):
    if _c in film_quality.columns:
        film_quality[_c] = pd.to_numeric(film_quality[_c], errors="coerce").round().astype("Int64")
# CONFIRMED BUG (fixed): APP_DATA_DIR is first set in the CSV-export cell further down, so this cell (and the new code
# in Play calls, Tag model, Tracking insights and Play review) failed or silently skipped its writes in a fresh session.
# OUTPUT_DIR is the same folder (../data).
film_quality.to_csv(os.path.join(globals().get("APP_DATA_DIR") or OUTPUT_DIR, "uww_film_quality.csv"), index=False)
for _, _r in film_quality[film_quality["is_upcoming"] | film_quality["is_uww"]].iterrows():
    print(f"Film on {_r['team']}: {_r['film_line']}."
          + ("" if not _r["tracked_games"] else
             f" Brief: per-player film reads {'ON' if _r['names_ok'] else 'off'} (named {_r['named_share_pct']}%, needs "
             f"{FILM_NAMES_OK_PCT:.0f}%), court sections {'ON' if _r['court_ok'] else 'off'} (placed "
             f"{_r['court_mapped_pct']}%, shot spots agree {_r['shot_zone_agree_pct']}% -- needs {FILM_COURT_OK_MAPPED:.0f}% "
             f"and {FILM_COURT_OK_ZONE:.0f}%). The app shows everything either way."))
