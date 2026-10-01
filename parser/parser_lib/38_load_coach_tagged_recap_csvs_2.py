# 38_load_coach_tagged_recap_csvs_2.py -- code for the notebook section "Parse "*_recap.csv" (single-game coach notes) and "*_plays_*.csv" (season-wide play-call l"
# Runs inside the notebook via run_section("38_load_coach_tagged_recap_csvs_2"); its settings are in that notebook cell.

# --- Parse "*_recap.csv" (single-game coach notes) and "*_plays_*.csv" (season-wide play-call log) exports,
# and attach them onto pbp_events ---------------------------------------------------------------------------
# CONFIRMED CHANGE (requested): season-wide play-call logs ("*_plays_*.csv") are retired. Play calls now come from
# INPUT_DIR/uww_plays.csv and INPUT_DIR/opponent_plays.csv, decoded and joined in the "Play calls" cell after the
# video-tagging attach. This cell now reads single-game coach recaps only; the season-wide branch below stays
# for any old multi-date recap file but no longer has a glob feeding it log exports.
recap_files = sorted(glob.glob(f"{volume_dir}/*_recap.csv"))
print(f"Found {len(recap_files)} coach-note/play-log CSV(s):")
for f in recap_files:
    print(" -", os.path.basename(f))


def _recap_period_label(pd_val):
    """Recap CSVs use a bare half number in "Pd." (1, 2, 3+ for OT) -- pbp_events uses "H1"/"H2"/"OT"/"OT2"
    (whatever token build_pbp_events pulled out of the raw PBP source's own "MM:SS (TOKEN)" format). Map the
    bare number onto that same convention so notes line up with pbp_events' own "period" values."""
    try:
        n = int(float(pd_val))
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n <= 2:
        return f"H{n}"
    return "OT" if n == 3 else f"OT{n - 2}"


def _clock_to_seconds(clock_val):
    """"10:46" -> 646. Returns None for a blank/unparseable clock (some clips -- e.g. a between-play summary
    note -- have no captured game clock at all)."""
    m = re.match(r"^(\d+):(\d+)", str(clock_val).strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _normalize_for_match(text):
    """Collapse ALL whitespace and lowercase, so "Ripon Red Hawks" and "Ripon Redhawks" -- a real, confirmed
    spelling inconsistency between one of these CSVs' own "Team" column and the schedule/scout-file spelling
    used to build scouted_opponents -- compare as equal. A plain substring check fails on exactly this kind
    of whitespace difference even though it's obviously the same opponent."""
    return re.sub(r"\s+", "", str(text)).lower()


# Date -> short opponent name, built from UWW's own schedule -- used to resolve each ROW's own opponent in a
# season-wide play-call log (one file covering many games), where a single "whole file belongs to one
# opponent" assumption (used for the single-game recap files below) doesn't hold.
_date_to_opponent = {}
if not uww_team_schedule.empty:
    for _, _sched_row in uww_team_schedule.iterrows():
        _d = parse_schedule_date(_sched_row.get("date"), uww_season_start_year)
        if _d is None:
            continue
        _full_opp = str(_sched_row.get("opponent", ""))
        _short_match = next((s for s in scouted_opponents if re.search(re.escape(s), _full_opp, re.IGNORECASE)), None)
        _date_to_opponent[_d] = _short_match or _full_opp


_recap_rows = []
for path in recap_files:
    try:
        recap_df = pd.read_csv(path)
    except Exception as e:
        print(f"  Could not read {os.path.basename(path)}: {type(e).__name__}: {e}")
        continue

    required_cols = {"Player", "Team", "Pd.", "Clock", "Text Overlay", "Result"}
    missing = required_cols - set(recap_df.columns)
    if missing:
        print(f"  {os.path.basename(path)}: missing expected column(s) {missing} -- skipping.")
        continue

    # Section-header rows ("DEFENSIVE CLIPS" / "OFFENSIVE CLIPS" / a play-family header like "Panther Series"
    # in the season-wide log) and any row with no real note/tag carry no Player at all -- drop those first.
    recap_df = recap_df[recap_df["Player"].notna() & (recap_df["Player"].astype(str).str.strip() != "")].copy()
    recap_df = recap_df[recap_df["Text Overlay"].notna() & (recap_df["Text Overlay"].astype(str).str.strip() != "")]
    if recap_df.empty:
        continue

    _is_season_wide = "Date" in recap_df.columns and pd.to_datetime(recap_df["Date"], errors="coerce").dt.date.nunique() > 1

    if _is_season_wide:
        # Season-wide play-call log: each ROW belongs to a different game, so resolve opponent per-row from
        # that row's own "Date" (matched against UWW's own schedule) rather than assuming one opponent for
        # the whole file. Also: this file's "Text Overlay" is a clean PLAY NAME (e.g. "Panther - Elmhurst",
        # "Twins Right Swirl - Ripon"), not free-text coach commentary like the single-game recap files use
        # -- so it goes into its own "play_call" field instead of "coach_note", rather than force two
        # different kinds of content through a format built for one of them.
        recap_df["_parsed_date"] = pd.to_datetime(recap_df["Date"], errors="coerce").dt.date
        # CONFIRMED BUG (fixed here): this file has ALL of a season's play-call rows in one CSV -- unlike
        # every other data source in this notebook (pbp_events, video files, coaching flags), nothing here
        # ever checked a row's own date against reference_date. Set reference_date before a game has been
        # played and its play calls -- if already logged in this file -- showed up anyway. Dropped here,
        # before opponent resolution, so a coach can't end up seeing tendencies from a game that, as of
        # reference_date, hasn't happened yet.
        _n_future = int((recap_df["_parsed_date"].notna() & (recap_df["_parsed_date"] >= reference_date.date())).sum())
        recap_df = recap_df[recap_df["_parsed_date"].isna() | (recap_df["_parsed_date"] < reference_date.date())]
        if _n_future:
            print(f"  {os.path.basename(path)}: dropped {_n_future} row(s) dated on/after reference_date ({reference_date_str}).")
        recap_df["opponent"] = recap_df["_parsed_date"].map(_date_to_opponent)
        _unresolved = recap_df["opponent"].isna().sum()
        recap_df = recap_df[recap_df["opponent"].notna()]
        if _unresolved:
            print(f"  {os.path.basename(path)}: {_unresolved} row(s) had a date that didn't match any UWW schedule game -- skipped.")
        if recap_df.empty:
            continue
        recap_df["team"] = recap_df["Team"].apply(lambda t: "UW-Whitewater" if "whitewater" in str(t).lower() else None)
        recap_df = recap_df[recap_df["team"].notna()]  # this log is offense-only (no "Team" = opponent rows observed)
        recap_df["period"] = recap_df["Pd."].apply(_recap_period_label)
        recap_df["time_remaining_seconds"] = recap_df["Clock"].apply(_clock_to_seconds)
        recap_df["player"] = recap_df["Player"].astype(str).str.strip()
        # Play name = the text before the first " - "-style delimiter in Text Overlay (handles the observed
        # inconsistent spacing, e.g. "Panther - Elmhurst" and "Over Action- Pin to Flare..." alike).
        recap_df["play_call"] = recap_df["Text Overlay"].astype(str).apply(lambda t: re.split(r"\s*-\s*", t.strip(), maxsplit=1)[0].strip())
        # The same "Text Overlay" field also carries clock/situation tags ("End of Half", "Timeout") that
        # aren't called plays at all. Left in, they rank in the app's play-call breakdown as if the staff
        # ran them -- and "End of Half" ranks high purely because every game has one. Drop those rows here:
        # with no coach_note either, they carry nothing else worth keeping.
        _NON_PLAY_CALL_PATTERNS = (
            r"^end\s+of\b",
            r"^(half|halftime|game|period|quarter|ot\d*|overtime)$",
            r"^(time\s*out|timeout|to)$",
            r"^(dead\s*ball|jump\s*ball|tip\s*off|tipoff)$",
            r"^(shot\s*clock|clock)\b",
            r"^(free\s*throws?|ft)$",
            r"^(n/?a|none|unknown|tbd|misc|other|untagged)$",
        )
        # Canonicalize against the playbook catalog parsed just above: the tagger writes the same set a
        # different way in nearly every clip ("P4", "P-4", "PANTHER 4") and often appends the OUTCOME to
        # the name ("P4 Good"), which split one play into a row per spelling and per result downstream.
        # Store the catalog's own name so every consumer of uww_coach_notes agrees on one play per set.
        _PLAY_QUALIFIER_WORDS = {
            "good", "bad", "great", "ok", "okay", "nice", "poor",
            "make", "made", "makes", "miss", "missed", "misses", "score", "scored", "bucket",
            "and1", "and-1", "foul", "fouled", "to", "turnover", "tov", "execution", "exec",
        }
        _play_lookup = {}
        if not plays_catalog.empty:
            for _, _cat_row in plays_catalog.iterrows():
                for _k in [k for k in str(_cat_row["match_keys"]).split("|") if k]:
                    _play_lookup.setdefault(_k, str(_cat_row["play_name"]))

        def _canonical_play(raw):
            """Catalog name for a tagged call, else the call with any trailing outcome word removed.
            Qualifiers are stripped only from the END and only from the known list -- a general
            "longest prefix in the catalog" rule would rewrite the real play "Twins Swirl" into the
            different real play "Twins"."""
            _toks = str(raw or "").strip().split()
            _hit = _play_lookup.get(_play_norm(raw))
            if _hit:
                return _hit
            while len(_toks) > 1 and _toks[-1].strip("().,+-\"'").lower() in _PLAY_QUALIFIER_WORDS:
                _toks.pop()
            _stripped = " ".join(_toks)
            _hit = _play_lookup.get(_play_norm(_stripped))
            if _hit:
                return _hit
            # Not in the catalog (a combination tagged in clips but never filed as its own play, e.g.
            # "Twins Right Swirl"): keep the wording, normalize the CASE. Coaches type the same call as
            # "TWINS SWIRL" one clip and "Twins Swirl" the next, and those grouped as two plays.
            _PLAY_ACRONYMS = {"ELOB", "SLOB", "BLOB", "ATO", "DHO", "ISO", "PNR", "OB", "UCLA", "STS"}
            _cased = []
            for _tok in _stripped.split():
                if _tok.upper().strip("()\"'") in _PLAY_ACRONYMS:
                    _cased.append(_tok.upper())
                elif len(_tok) <= 3 or any(_ch.isdigit() for _ch in _tok):
                    _cased.append(_tok.upper() if _tok.isupper() else _tok)
                else:
                    _cased.append(_tok[:1].upper() + _tok[1:].lower())
            return " ".join(_cased)

        _pre_canon = recap_df["play_call"].copy()
        recap_df["play_call"] = recap_df["play_call"].apply(_canonical_play)
        _n_canon = int((_pre_canon.astype(str) != recap_df["play_call"].astype(str)).sum())
        if _n_canon:
            print(f"  {os.path.basename(path)}: normalized {_n_canon} play call(s) to their catalog names.")

        _is_non_play = recap_df["play_call"].astype(str).str.strip().str.lower().apply(
            lambda t: (not t) or any(re.search(_p, re.sub(r"\s+", " ", t)) for _p in _NON_PLAY_CALL_PATTERNS)
        )
        if int(_is_non_play.sum()):
            print(f"  {os.path.basename(path)}: dropped {int(_is_non_play.sum())} non-play row(s) "
                  f"({', '.join(sorted(set(recap_df.loc[_is_non_play, 'play_call'].astype(str)))[:5])}).")
        recap_df = recap_df[~_is_non_play]
        if recap_df.empty:
            continue
        recap_df["coach_note"] = None
        recap_df["result"] = recap_df["Result"].astype(str).str.strip()
        recap_df["clip_side"] = "Offense"
        _recap_rows.append(recap_df[[
            "opponent", "period", "time_remaining_seconds", "team", "player", "result", "coach_note", "play_call", "clip_side",
        ]])
        print(f"  {os.path.basename(path)}: {len(recap_df)} play-call log row(s) across {recap_df['opponent'].nunique()} opponent(s)")
        continue

    # CONFIRMED BUG (fixed here): same leak as the season-wide log above, for the single-game recap case --
    # nothing here checked this file's own game date against reference_date before including it. These
    # files follow the same "<m>_<d>_<yy> ..." filename convention the PBP/video files use, so their date
    # is available the same way, via game_date_from_pbp_filename() (it only reads the filename prefix, so
    # it works on any file named that way regardless of what comes after).
    _recap_file_date = game_date_from_pbp_filename(path)
    if _recap_file_date is not None and _recap_file_date >= reference_date.date():
        print(f"  {os.path.basename(path)}: game date {_recap_file_date} is on/after reference_date ({reference_date_str}) -- skipping.")
        continue

    # Single-game recap: whole file belongs to one opponent, resolved from whichever non-UWW "Team" value
    # appears (e.g. "Ripon Redhawks") -- whitespace-normalized match against scouted_opponents.
    _opp_team_vals = recap_df.loc[
        ~recap_df["Team"].astype(str).str.contains("whitewater", case=False, na=False), "Team"
    ].dropna().unique()
    _recap_opponent = None
    for _tv in _opp_team_vals:
        _tv_norm = _normalize_for_match(_tv)
        _match = next(
            (s for s in scouted_opponents if _normalize_for_match(s) in _tv_norm or _tv_norm in _normalize_for_match(s)),
            None,
        )
        if _match:
            _recap_opponent = _match
            break
    if _recap_opponent is None:
        print(f"  Could not resolve which scouted opponent {os.path.basename(path)} belongs to (Team values seen: {list(_opp_team_vals)}) -- skipping.")
        continue

    recap_df["opponent"] = _recap_opponent
    recap_df["team"] = recap_df["Team"].apply(lambda t: "UW-Whitewater" if "whitewater" in str(t).lower() else _recap_opponent)
    recap_df["period"] = recap_df["Pd."].apply(_recap_period_label)
    recap_df["time_remaining_seconds"] = recap_df["Clock"].apply(_clock_to_seconds)
    recap_df["player"] = recap_df["Player"].astype(str).str.strip()
    recap_df["coach_note"] = recap_df["Text Overlay"].astype(str).str.strip()
    recap_df["play_call"] = None
    recap_df["result"] = recap_df["Result"].astype(str).str.strip()
    recap_df["clip_side"] = recap_df["team"].apply(lambda t: "Offense" if t == "UW-Whitewater" else "Defense")

    _recap_rows.append(recap_df[[
        "opponent", "period", "time_remaining_seconds", "team", "player", "result", "coach_note", "play_call", "clip_side",
    ]])
    print(f"  {os.path.basename(path)}: {len(recap_df)} coach note(s) for opponent '{_recap_opponent}'")

coach_notes = pd.concat(_recap_rows, ignore_index=True) if _recap_rows else pd.DataFrame(
    columns=["opponent", "period", "time_remaining_seconds", "team", "player", "result", "coach_note", "play_call", "clip_side"]
)

# One possession, one row. The same play can be tagged in BOTH a single-game recap ("PANTHER EXECUTION,
# BIG = WALK YOUR MAN UP") and the season play-call log, and two play-log exports can overlap each other --
# each of which produced a separate row here for one real possession, double-counting it in every play-call
# breakdown downstream. Collapse on the possession key, keeping the first non-null value of each field so
# the merged row carries BOTH the coach's note and the structured play_call. Rows with no clock can't be
# identified as the same possession, so they pass through untouched rather than being merged on a guess.
if not coach_notes.empty and "time_remaining_seconds" in coach_notes.columns:
    _cn_key = ["opponent", "period", "time_remaining_seconds", "team", "player"]
    _cn_timed = coach_notes[coach_notes["time_remaining_seconds"].notna()].copy()
    _cn_untimed = coach_notes[coach_notes["time_remaining_seconds"].isna()]
    _cn_before = len(_cn_timed)
    if _cn_before:
        _cn_timed = (
            _cn_timed.groupby(_cn_key, dropna=False, as_index=False, sort=False)
            .agg({c: "first" for c in coach_notes.columns if c not in _cn_key})
        )
        # groupby().first() skips nulls per column, which is exactly what merges a note-only row and a
        # play-log-only row for the same possession into one complete row.
        if _cn_before != len(_cn_timed):
            print(f"\nMerged {_cn_before - len(_cn_timed)} duplicate possession row(s) "
                  f"(same play tagged in more than one export).")
    coach_notes = pd.concat([_cn_timed, _cn_untimed], ignore_index=True)[list(coach_notes.columns)]

# Attach coach_note/play_call onto the matching pbp_events row by (opponent, period, time_remaining_seconds,
# team, player) -- pbp_events already carries a clean time_remaining_seconds column (parsed from the raw PBP
# source's own "MM:SS (PERIOD)" text), so match on THAT rather than pbp_events' "time_remaining" column,
# which is that unparsed raw string (e.g. "10:46 (H1)") and would never equal the recap's plain "10:46".
# A small number of clips have no clock at all (time_remaining_seconds is None) and simply won't match any
# row -- their note is still preserved in the standalone coach_notes table above, just not linked in-line.
for _c in ("coach_note", "play_call"):
    if _c in pbp_events.columns:
        pbp_events = pbp_events.drop(columns=[_c])
if not coach_notes.empty and not pbp_events.empty:
    _matchable_notes = coach_notes[coach_notes["time_remaining_seconds"].notna() & coach_notes["period"].notna()]
    _join_keys = ["opponent", "period", "time_remaining_seconds", "team", "player"]
    pbp_events = pbp_events.merge(
        _matchable_notes[_join_keys + ["coach_note", "play_call"]].drop_duplicates(subset=_join_keys),
        on=_join_keys, how="left",
    )
    _n_matched = int((pbp_events["coach_note"].notna() | pbp_events["play_call"].notna()).sum())
    print(
        f"\nAttached {_n_matched} coach note(s)/play-call(s) onto pbp_events out of {len(coach_notes)} parsed "
        f"({len(coach_notes) - len(_matchable_notes)} had no usable clock and can't be linked to a specific "
        "play; the rest may not match if a player name is spelled differently between sources)."
    )
    # If the match rate is suspiciously low, print exactly what didn't line up -- side-by-side against a
    # sample of pbp_events' own keys for the same opponent(s) -- rather than leaving "why" as a guessing game.
    if _n_matched < len(_matchable_notes):
        _unmatched = _matchable_notes.merge(
            pbp_events[_join_keys].drop_duplicates(), on=_join_keys, how="left", indicator=True
        )
        _unmatched = _unmatched[_unmatched["_merge"] == "left_only"]
        if not _unmatched.empty:
            print(f"\n{len(_unmatched)} note(s) did NOT find a matching pbp_events row. First few unmatched note keys:")
            print(_unmatched[_join_keys].head(8).to_string(index=False))
            _sample_opp = _unmatched["opponent"].iloc[0]
            print(f"\nFor comparison, actual pbp_events keys for opponent \'{_sample_opp}\' (first 8 rows with a player):")
            _sample_pbp = pbp_events[(pbp_events["opponent"] == _sample_opp) & pbp_events["player"].notna()]
            print(_sample_pbp[_join_keys].head(8).to_string(index=False))
            print(
                "\nCompare the two tables above column-by-column -- the mismatch (differently-spelled player "
                "name, a period token that doesn\'t match, an opponent string that isn\'t identical) should be "
                "visible directly. A common cause: this game\'s local _pbp file used a different exact player-"
                "name spelling than the recap CSV (e.g. a nickname or suffix like \'Jr\')."
            )
else:
    pbp_events["coach_note"] = None
    pbp_events["play_call"] = None
