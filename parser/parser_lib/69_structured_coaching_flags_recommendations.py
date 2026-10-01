# 69_structured_coaching_flags_recommendations.py -- code for the notebook section "Structured coaching-flags DATABASE: one row per (player, flag) -- replaces one-off markdow"
# Runs inside the notebook via run_section("69_structured_coaching_flags_recommendations"); its settings are in that notebook cell.

# --- Structured coaching-flags DATABASE: one row per (player, flag) -- replaces one-off markdown notes and
# inline comments with a rule-based, queryable table that recomputes automatically as more games get logged.
# Every rostered player gets at least one row (falls back to season box-score context when a player's
# logged shot volume is too thin for a play-type diagnosis).
# KNOWN_NAME_ALIASES reconciles known name-spelling mismatches BETWEEN data sources -- e.g. the play-by-play
# pipeline may spell a player differently than the official schedule-page season stats.
# Loaded from data/name_aliases.json (shared with streamlit_app.py) instead of a hardcoded dict here, so a
# newly-discovered mismatch only needs to be added in ONE place rather than kept in sync across the app and
# this notebook. Falls back to the one known mismatch if the file isn't found (e.g. first run before the app
# repo's data/ folder exists locally).
def _load_known_name_aliases():
    alias_path = os.path.join(OUTPUT_DIR, "name_aliases.json")
    if os.path.exists(alias_path):
        try:
            with open(alias_path) as _af:
                raw = json.load(_af)
            return {k.lower(): v.lower() for k, v in raw.items() if not k.startswith("_")}
        except Exception as _e:
            print(f"WARNING: could not read {alias_path} ({_e}); using inline fallback alias.")
    return {"mauryon turner": "maurquis turner"}

KNOWN_NAME_ALIASES = _load_known_name_aliases()

# CONFIRMED BUG (fixed here): this cell used to call a bare normalize_player_name(name) -- which isn't
# actually defined anywhere at the top level of this notebook. It only ever exists as a function defined
# INSIDE a `for` loop in the video-tagging cell above, and Python `for` loops don't create their own
# scope, so that `def` leaks into the global namespace once the loop body has run at least once. If that
# loop's file list is empty -- e.g. no video-tagging files yet, or reference_date is before every game
# so every file gets filtered out -- normalize_player_name was never defined at all, and this cell would
# raise "NameError: name 'normalize_player_name' is not defined" the same way the player-comparison cell
# did before its own fix. Built fresh and self-contained here instead, scoped to UWW's own known players
# across every game in pbp_events (the same fix already applied where this exact problem first surfaced).
_coaching_flags_known_players = set(pbp_events.loc[pbp_events["team"] == "UW-Whitewater", "player"].dropna().unique())

def normalize_player_name(name):
    if name in _coaching_flags_known_players:
        return name
    for p in _coaching_flags_known_players:
        if p.casefold() == str(name).casefold():
            return p
    return name

def resolve_player_key(name):
    # normalize_player_name() only folds CASING/spelling to UWW's own known-player set (and preserves the
    # original string untouched when no case-insensitive match exists there) -- it does NOT lowercase, so a
    # dict lookup against it needs an explicit .lower() to be reliably case-insensitive across sources whose
    # canonical spelling itself differs.
    norm = normalize_player_name(name).lower()
    return KNOWN_NAME_ALIASES.get(norm, norm)

coaching_flags = []

def add_flag(player, player_key, category, flag, evidence, recommendation, confidence, sentiment):
    coaching_flags.append({
        "player": player, "player_key": player_key, "category": category, "flag": flag,
        "evidence": evidence, "recommendation": recommendation, "confidence": confidence,
        "sentiment": sentiment,
    })

# --- CONFIRMED BUG (fixed here): every flag below used to carry a hardcoded confidence STRING regardless of
# how many actual attempts backed the number -- "High (season-long sample)" on every season-stat rule,
# "Medium (small sample -- re-check as more games are logged)" on every per-shot rule. Checked against
# real season output (cell 10's printed `stats` table): Maurquis Turner's "Below-average free-throw shooter"
# flag was tagged "High (season-long sample)" off 0.0-0.7 FTA/gm over a 3-0 (GP-GS) season -- ~2 total FT
# attempts, not a real signal. Agape Keyes Jr.'s "Respectable 3-point shooter" flag was also labelled "High"
# off ~7 total 3PT attempts (0.5-1.2/gm over 6 games) -- identically worded to Kelton McEwen's same flag,
# which is backed by ~53 attempts. The two aren't remotely equivalent, but the old code couldn't tell them
# apart because it never computed a real attempt count, only checked a per-game RATE against a fixed
# threshold. confidence_label() below computes a tier from the actual attempt count behind each number, and
# MIN_ATTEMPTS_TO_FLAG suppresses a rate-stat flag entirely when that count is too thin to mean anything --
# Turner's ~2 FT attempts (0-for-2) no longer produce a flag at all, rather than a misleadingly confident one.

# CONFIRMED BUG (fixed here): the per-shot rules passed low_max=5 / medium_max=11, so 12 attempts already read
# "High". Brock Marino's "Highly efficient scorer" flag was printed as HIGH confidence off 18 shots -- a
# 14-for-18 stretch that one cold night erases. "High" now needs a genuinely season-sized denominator no
# matter which rule is asking: _CONF_HIGH_FLOOR attempts, applied inside confidence_label itself so an
# individual rule can't hand out "High" cheaply again.
_CONF_HIGH_FLOOR = 30

def confidence_label(n, noun="attempts", low_max=9, medium_max=29):
    """n = the actual count of attempts behind a percentage. A rate is only as trustworthy as its
    denominator, so this replaces a single fixed string with a tier computed from real sample size."""
    if n is None or pd.isna(n):
        return "Unknown (sample size not available)"
    n = int(round(n))
    if n <= low_max:
        return f"Low (n={n} {noun} -- small sample, re-check as more games are played)"
    if n <= medium_max or n < _CONF_HIGH_FLOOR:
        return f"Medium (n={n} {noun})"
    return f"High (n={n} {noun}, season-long sample)"

def format_rate_pair(makes, attempts, games_played):
    """Recreate a FastScout-style 'M-A per game' display string (e.g. '0.4-1.2') from raw totals, since
    season_asof (below) carries totals, not the pre-formatted per-game strings the old `stats` page had."""
    if not games_played:
        return "-"
    return f"{makes / games_played:.1f}-{attempts / games_played:.1f}"

# Fresh, self-contained recomputation of UWW's logged shot attempts with play type / mechanic / contest /
# distance tags (mirrors the logic in the cells above; kept self-contained so this cell doesn't depend on the
# execution order of earlier ones). No extra date filter needed here: pbp_events itself was already cut down
# to game_date < reference_date by the fix in the "Play-by-play (PBP) data" cell above, and uww_shots is
# built directly from pbp_events, so that restriction already carries through.
uww_shots = pbp_events[
    (pbp_events["team"] == "UW-Whitewater")
    & pbp_events["event_type"].isin(["made_shot", "missed_shot"])
    & pbp_events["video_description"].notna()
].copy()
uww_shots["play_type"] = uww_shots.apply(lambda r: extract_play_type(r["video_description"], r["player"]), axis=1)
uww_shots["made"] = uww_shots["event_type"] == "made_shot"
uww_shots["shot_mechanic"] = uww_shots["video_description"].apply(extract_shot_mechanic)
uww_shots["contest"] = uww_shots["video_description"].apply(extract_contest)
uww_shots["distance"] = uww_shots["video_description"].apply(extract_distance)
uww_shots["player_key"] = uww_shots["player"].apply(resolve_player_key)

# Full ROSTER identity only (names, jersey numbers, player_key) -- who's on the team doesn't change
# game-to-game the way cumulative stats do, so this is safe to pull from the official season-stats page
# regardless of reference_date. Deliberately does NOT carry FG%/3P%/FT%/MIN/PTS/GP-GS from that page --
# see season_asof below for why.
roster = stats[~stats["PLAYER"].str.contains("Team|Opponent", case=False, na=False)].copy()
roster["player_key"] = roster["PLAYER"].apply(resolve_player_key)
# The season-stats source table itself has a duplicate-row quirk for at least one jersey number (a placeholder
# row with all "-" stats under one name spelling, alongside a real-stats row under the corrected spelling).
# When the alias/key resolution above merges such rows onto the same player_key, prefer whichever row actually
# has a real GP-GS entry over an all-placeholder one.
roster["_has_real_row"] = roster["GP-GS"].astype(str) != "-"
roster = roster.sort_values("_has_real_row", ascending=False).drop_duplicates("player_key", keep="first").drop(columns="_has_real_row")

# --- CONFIRMED BUG (fixed here): every season-stat rule below (FG%/3P%/FT%/PPG/MPG/GP-GS) previously read
# straight from `stats` -- FastScout's live CUMULATIVE season-stats page (scraped in cell 10). That page has
# no date granularity at all: it's whatever the season total is AT SCRAPE TIME, with no way to ask "as of
# reference_date". Caught via a real example: Brock Marino's free-throw flag showed "~112 attempts" even
# though reference_date is 2025-11-15 -- 112 FTA across 28 games is a near-full-season total, not something
# that could have happened by mid-November. `pbp_events` (and everything built from it, including
# `pbp_box_score`) is already correctly restricted to `game_date < reference_date` by the fix in the
# "Play-by-play (PBP) data" cell above -- so every season-stat rule below now reads from `season_asof`,
# rebuilt here from `pbp_box_score`'s real per-game shooting lines, totalled only over games that had
# actually been played as of reference_date.
# TRADEOFF: pbp_box_score only covers games with a parsed play-by-play file, so a player whose
# pre-reference-date games weren't logged that way will show a thinner (or empty) sample here than the
# season-to-date page would have shown. That's the correct tradeoff for a pre-game report -- an honest
# thin/no sample (which MIN_ATTEMPTS_TO_FLAG and confidence_label() already handle gracefully) beats a
# precise-looking number partly built from games that, as of reference_date, hadn't been played yet.
uww_box_asof = pbp_box_score[
    (pbp_box_score["team"] == "UW-Whitewater") & (pbp_box_score["player"] != "TEAM")
].copy()
uww_box_asof["player_key"] = uww_box_asof["player"].apply(resolve_player_key)
uww_box_asof["MIN"] = pd.to_numeric(uww_box_asof["MIN"], errors="coerce")
season_asof = uww_box_asof.groupby("player_key").agg(
    FGM=("FGM", "sum"), FGA=("FGA", "sum"), FG3M=("FG3M", "sum"), FG3A=("FG3A", "sum"),
    FTM=("FTM", "sum"), FTA=("FTA", "sum"), PTS=("PTS", "sum"), MIN=("MIN", "sum"),
    games_played=("game_date", "nunique"), games_started=("started", "sum"),
).reset_index()
season_asof["fg_pct_season"] = (100 * season_asof["FGM"] / season_asof["FGA"]).round(1)
season_asof["three_pt_pct_season"] = (100 * season_asof["FG3M"] / season_asof["FG3A"]).round(1)
season_asof["ft_pct_season"] = (100 * season_asof["FTM"] / season_asof["FTA"]).round(1)
season_asof["mpg_season"] = (season_asof["MIN"] / season_asof["games_played"]).round(1)
season_asof["pts_season"] = (season_asof["PTS"] / season_asof["games_played"]).round(1)
# These are now EXACT totals from real per-game box scores, not the M-A-per-game-times-GP estimate the old
# `stats`-page version needed (that page never exposed a raw attempt count, only a rounded per-game rate).
season_asof["fga_total_est"] = season_asof["FGA"]
season_asof["tpa_total_est"] = season_asof["FG3A"]
season_asof["fta_total_est"] = season_asof["FTA"]

# Season-wide Starter/Bench role, from the per-game `started` flag reconstructed from the PBP.
# CONFIRMED BUG (fixed here, superseding an earlier "fix"): a previous version of this cell filled in role
# "Unknown" for a player with no PBP data by falling back to the official season-stats page's GP-GS column
# (games started > 0 => Starter). That page has the exact same reference_date leak described above -- a
# player's season-long "started 24 of 29 games" is just as much of a leak as their season-long FT% is, so
# that fallback has been removed. A player with no PBP-tagged games before reference_date genuinely has an
# unknown role AS OF reference_date, and "Unknown" is the honest answer, not a bug to paper over.
starter_flags = pbp_box_score[pbp_box_score["team"] == "UW-Whitewater"][["player", "started"]].drop_duplicates()
starter_flags["player_key"] = starter_flags["player"].apply(resolve_player_key)
player_role = starter_flags.groupby("player_key")["started"].any().map({True: "Starter", False: "Bench"})

# Canonical DISPLAY name per resolved key -- prefer the official roster spelling when available (the athletic
# department's own roster page), otherwise whatever spelling shows up in the logged PBP data. Names only --
# no performance numbers -- so this is unaffected by the reference_date fix above.
canonical_name_by_key = {}
for _, row in roster.iterrows():
    canonical_name_by_key.setdefault(row["player_key"], row["PLAYER"])
for name in uww_shots["player"].unique():
    canonical_name_by_key.setdefault(resolve_player_key(name), name)

roster_keys = sorted(set(roster["player_key"]) | set(uww_shots["player_key"]))

for player_key in roster_keys:
    player = canonical_name_by_key[player_key]
    p_shots = uww_shots[uww_shots["player_key"] == player_key]
    asof_row = season_asof[season_asof["player_key"] == player_key]
    total_attempts = len(p_shots)
    has_positive_flag = False

    cs = p_shots[p_shots["shot_mechanic"] == "Catch-and-shoot"]
    guarded_cs = cs[cs["contest"] == "Guarded"]
    open_cs = cs[cs["contest"] == "Open"]

    # Rule 1: shot diet is skewed heavily toward contested catch-and-shoot looks. Requires guarded to be at
    # least 80% of catch-and-shoot volume, with at most 1 stray open attempt, so a single outlier doesn't mask
    # an otherwise heavily-contested shot diet, while still requiring a real majority skew.
    # CONFIRMED BUG (fixed here): this fired on Brock Marino at 3-for-3 on guarded catch-and-shoots and filed
    # it under "Clean up". A player MAKING every contested look is not a problem to fix this week. The rule now
    # also requires the guarded looks to be underperforming (_CS_GUARDED_MAX_PCT or worse) -- it is a flag
    # about lost points, not about shot diet in the abstract.
    _CS_GUARDED_MAX_PCT = 40
    cs_total = len(guarded_cs) + len(open_cs)
    g_pct_rule1 = (100 * guarded_cs["made"].sum() / len(guarded_cs)) if len(guarded_cs) else None
    if (len(guarded_cs) >= 3 and len(open_cs) <= 1 and cs_total and (len(open_cs) / cs_total) <= 0.2
            and g_pct_rule1 is not None and g_pct_rule1 <= _CS_GUARDED_MAX_PCT):
        g_makes, g_att, o_att = int(guarded_cs["made"].sum()), len(guarded_cs), len(open_cs)
        add_flag(
            player, player_key, "Shot selection",
            "Shot diet skewed heavily toward contested catch-and-shoot looks",
            f"{g_makes}-for-{g_att} ({100 * g_makes / g_att:.0f}%) on guarded catch-and-shoot attempts this "
            f"season, vs. only {o_att} open catch-and-shoot attempt(s).",
            "Design more actions to create separation before the catch (relocation, screens, drive-and-kick "
            "reads) rather than relying on standstill catches against a set defense.",
            confidence_label(cs_total, noun="catch-and-shoot attempts", low_max=5, medium_max=11), "Negative",
        )

    # Rule 2: misses concentrate on OPEN catch-and-shoot looks specifically -- a shooter-specific issue, not a
    # shot-quality one.
    if len(open_cs) >= 3:
        o_makes, o_att = int(open_cs["made"].sum()), len(open_cs)
        o_pct = 100 * o_makes / o_att
        if o_pct <= 35:
            season_3p = None
            if not asof_row.empty and pd.notna(asof_row["three_pt_pct_season"].iloc[0]):
                season_3p = asof_row["three_pt_pct_season"].iloc[0]
            evidence = f"{o_makes}-for-{o_att} ({o_pct:.0f}%) on open catch-and-shoot attempts this season"
            evidence += f" -- below his season 3P% of {season_3p:.1f}%." if season_3p is not None else "."
            add_flag(
                player, player_key, "Shooting efficiency",
                "Missing predominantly OPEN catch-and-shoot looks",
                evidence,
                "Since these are UNCONTESTED misses, treat as a shooting-mechanics/rhythm issue -- prioritize "
                "catch-and-shoot reps in practice rather than trying to generate better shot quality in-game.",
                confidence_label(o_att, noun="open catch-and-shoot attempts", low_max=5, medium_max=11), "Negative",
            )

    # Rule 3 / 4: efficiency on the player's single most-attempted play type (their "go-to" action).
    if total_attempts:
        top_pt = p_shots["play_type"].value_counts().idxmax()
        top_rows = p_shots[p_shots["play_type"] == top_pt]
        top_att, top_makes = len(top_rows), int(top_rows["made"].sum())
        top_pct = 100 * top_makes / top_att if top_att else None
        if top_att >= 4 and top_pct is not None:
            if top_pct <= 30:
                add_flag(
                    player, player_key, "Play-type efficiency",
                    f"Struggles specifically in his most-used action ({top_pt})",
                    f"{top_makes}-for-{top_att} ({top_pct:.0f}%) on {top_pt} -- his single most-attempted "
                    f"action this season, well below his overall shooting split.",
                    f"Reduce reliance on {top_pt} as his primary look, or work on the specific mechanics/reads "
                    f"for that action in practice.",
                    confidence_label(top_att, noun=f"{top_pt} attempts", low_max=5, medium_max=11), "Negative",
                )
            elif top_pct >= 70:
                add_flag(
                    player, player_key, "Play-type efficiency",
                    f"Highly efficient in his most-used action ({top_pt}) -- underused upside",
                    f"{top_makes}-for-{top_att} ({top_pct:.0f}%) on {top_pt}, his most-attempted "
                    f"action this season.",
                    f"Consider increasing his usage/touches in {top_pt} sets -- the efficiency supports more "
                    f"volume there.",
                    confidence_label(top_att, noun=f"{top_pt} attempts", low_max=5, medium_max=11), "Positive",
                )
                has_positive_flag = True

    # Rule 5: overall shot efficiency, for a broader positive signal independent of a single play type.
    if total_attempts >= 8:
        overall_pct = 100 * p_shots["made"].sum() / total_attempts
        if overall_pct >= 70:
            add_flag(
                player, player_key, "Overall efficiency",
                "Highly efficient scorer, season-wide",
                f"{int(p_shots['made'].sum())}-for-{total_attempts} ({overall_pct:.0f}%) across all "
                f"shot attempts this season.",
                "A clear, efficient scoring option -- consider featuring him more prominently in the "
                "half-court offense.",
                confidence_label(total_attempts, noun="shot attempts", low_max=5, medium_max=11), "Positive",
            )
            has_positive_flag = True

    # Rule 6: free-throw shooting as of reference_date (independent of shot logging -- covers every rostered
    # player). Fires only once season_asof gives us a real attempt count to trust (MIN_ATTEMPTS_TO_FLAG floor).
    if not asof_row.empty:
        r6 = asof_row.iloc[0]
        ft_pct, fta_total = r6["ft_pct_season"], r6["fta_total_est"]
        if pd.notna(ft_pct) and pd.notna(fta_total) and fta_total >= MIN_ATTEMPTS_TO_FLAG and ft_pct <= 60:
            # CONFIRMED BUG (fixed here): evidence read "(1.3-4.7 per game, 14 attempts)" -- a FastScout-style
            # makes-attempts pair that looks like a range. Spelled out instead.
            _gp6 = int(r6["games_played"]) if pd.notna(r6["games_played"]) else 0
            add_flag(
                player, player_key, "Free-throw shooting",
                "Below-average free-throw shooter with meaningful attempt volume",
                f"{ft_pct:.1f}% FT this season -- {int(r6['FTM'])}-for-{int(fta_total)} over {_gp6} "
                f"game{'s' if _gp6 != 1 else ''} ({fta_total / max(_gp6, 1):.1f} attempts a game).",
                "Target free-throw shooting in individual workouts -- meaningful attempt volume means this is "
                "costing points.",
                confidence_label(fta_total, noun="FT attempts"), "Negative",
            )

    # --- POSITIVE-signal cascade: guarantees at least one Positive flag per player wherever the data supports
    # one, independent of whether the rules above already found a negative issue for him. Evaluated in
    # priority order; the first candidate with real supporting data is used.
    if not has_positive_flag:
        pt_stats = p_shots.groupby("play_type").agg(attempts=("made", "count"), makes=("made", "sum")).reset_index()
        pt_stats["pct"] = 100 * pt_stats["makes"] / pt_stats["attempts"]
        best_pt = pt_stats[pt_stats["attempts"] >= 3].sort_values("pct", ascending=False).head(1)
        if not best_pt.empty and best_pt["pct"].iloc[0] >= 65:
            r = best_pt.iloc[0]
            add_flag(
                player, player_key, "Play-type efficiency",
                f"Efficient secondary action: {r['play_type']}",
                f"{int(r['makes'])}-for-{int(r['attempts'])} ({r['pct']:.0f}%) on {r['play_type']} this season.",
                "A reliable look worth calling more often, even if not his primary action.",
                confidence_label(r["attempts"], noun=f"{r['play_type']} attempts", low_max=5, medium_max=11), "Positive",
            )
            has_positive_flag = True

    if not has_positive_flag and total_attempts >= 4:
        overall_pct = 100 * p_shots["made"].sum() / total_attempts
        if overall_pct >= 55:
            add_flag(
                player, player_key, "Overall efficiency",
                "Solid overall shooting, season-wide",
                f"{int(p_shots['made'].sum())}-for-{total_attempts} ({overall_pct:.0f}%) across all "
                f"shot attempts this season.",
                "A dependable scoring option in the offense.",
                confidence_label(total_attempts, noun="shot attempts", low_max=5, medium_max=11), "Positive",
            )
            has_positive_flag = True

    if not has_positive_flag and not asof_row.empty:
        r = asof_row.iloc[0]
        if (
            pd.notna(r["fg_pct_season"]) and r["fg_pct_season"] >= 45
            and pd.notna(r["mpg_season"]) and r["mpg_season"] >= 3
            and pd.notna(r["fga_total_est"]) and r["fga_total_est"] >= MIN_ATTEMPTS_TO_FLAG
        ):
            fgm_a = format_rate_pair(r["FGM"], r["FGA"], r["games_played"])
            add_flag(
                player, player_key, "Season shooting",
                "Solid season field-goal percentage",
                f"{r['fg_pct_season']:.1f}% FG this season ({fgm_a} per game, {r['mpg_season']:.0f} MPG, "
                f"{int(r['fga_total_est'])} attempts).",
                "A reasonably efficient finisher for his role -- keep him involved in the offense.",
                confidence_label(r["fga_total_est"], noun="FGA"), "Positive",
            )
            has_positive_flag = True
        elif (
            pd.notna(r["ft_pct_season"]) and r["ft_pct_season"] >= 70
            and pd.notna(r["fta_total_est"]) and r["fta_total_est"] >= MIN_ATTEMPTS_TO_FLAG
        ):
            ftm_a = format_rate_pair(r["FTM"], r["FTA"], r["games_played"])
            add_flag(
                player, player_key, "Free-throw shooting",
                "Reliable free-throw shooter",
                f"{r['ft_pct_season']:.1f}% FT this season ({ftm_a} per game, {int(r['fta_total_est'])} attempts).",
                "A safe option to have on the floor in late-game free-throw situations.",
                confidence_label(r["fta_total_est"], noun="FT attempts"), "Positive",
            )
            has_positive_flag = True
        elif (
            pd.notna(r["three_pt_pct_season"]) and r["three_pt_pct_season"] >= 33
            and pd.notna(r["tpa_total_est"]) and r["tpa_total_est"] >= MIN_ATTEMPTS_TO_FLAG
        ):
            tpm_a = format_rate_pair(r["FG3M"], r["FG3A"], r["games_played"])
            add_flag(
                player, player_key, "Season shooting",
                "Respectable 3-point shooter this season",
                f"{r['three_pt_pct_season']:.1f}% 3PT this season ({tpm_a} per game, {int(r['tpa_total_est'])} "
                f"attempts).",
                "Worth designing catch-and-shoot looks for him specifically.",
                confidence_label(r["tpa_total_est"], noun="3PT attempts"), "Positive",
            )
            has_positive_flag = True
        elif pd.notna(r["mpg_season"]) and r["mpg_season"] > 0:
            # This catch-all used to say the same sentence, differing only by MPG/GP-GS, for every player with
            # real minutes but no threshold-crossing shooting number. Adding season PPG and splitting the
            # framing by usage level gives a coach something to actually distinguish those cases on.
            pts_str = f", {r['pts_season']:.1f} PPG" if pd.notna(r["pts_season"]) else ""
            gp_gs = f"{int(r['games_played'])}-{int(r['games_started'])}"
            if r["mpg_season"] >= 10:
                flag_text = "Regular rotation minutes without a standout shooting number yet"
                usage_note = "a real rotation role"
            else:
                flag_text = "Seeing early/situational game action"
                usage_note = "limited minutes"
            add_flag(
                player, player_key, "General",
                flag_text,
                f"Averaging {r['mpg_season']:.0f} MPG{pts_str} over {gp_gs} (GP-GS) as of reference_date -- no "
                f"shooting percentage has crossed a flag threshold yet, but he's logging {usage_note}.",
                "Keep tracking as more games are played for a clearer efficiency signal.",
                "Low (no standout stat yet)", "Positive",
            )
            has_positive_flag = True

    if not has_positive_flag:
        add_flag(
            player, player_key, "General / limited data",
            "No performance data yet to flag positively",
            "No recorded minutes, shot attempts, or season stats found for him as of reference_date.",
            "Re-evaluate once he sees game action and stats are recorded.",
            "Low (no data)", "Neutral",
        )

coaching_flags_df = pd.DataFrame(coaching_flags)
coaching_flags_df["role"] = coaching_flags_df["player_key"].map(player_role).fillna("Unknown")
coaching_flags_df = coaching_flags_df[
    ["player", "player_key", "role", "sentiment", "category", "flag", "evidence", "recommendation", "confidence"]
]
_sentiment_order = {"Positive": 0, "Negative": 1, "Neutral": 2}
coaching_flags_df["_sentiment_order"] = coaching_flags_df["sentiment"].map(_sentiment_order)
# CONFIRMED BUG (fixed here): role was previously sorted with ascending=False on the raw string, which only
# put Starters ahead of Bench by alphabetical coincidence -- "Unknown" > "Starter" > "Bench" in reverse
# alphabetical order, so any Unknown-role player actually sorted to the TOP of the table, ahead of every
# starter. Explicit priority order below puts Starters first, Bench second, and any genuinely unresolved
# players last, which is what a coach opening this table actually wants.
_role_order = {"Starter": 0, "Bench": 1, "Unknown": 2}
coaching_flags_df["_role_order"] = coaching_flags_df["role"].map(_role_order).fillna(3)
coaching_flags_df = coaching_flags_df.sort_values(
    ["_role_order", "player", "_sentiment_order", "category"], ascending=[True, True, True, True]
).drop(columns=["_sentiment_order", "_role_order"])

n_players_with_positive = coaching_flags_df.loc[coaching_flags_df["sentiment"] == "Positive", "player"].nunique()
n_no_asof_data = sum(1 for k in roster_keys if season_asof[season_asof["player_key"] == k].empty)
print(f"Coaching flags database: {len(coaching_flags_df)} flag(s) across {coaching_flags_df['player'].nunique()} "
      f"player(s) (full roster: {len(roster_keys)}).")
print(f"{n_players_with_positive} of {len(roster_keys)} players have at least one Positive flag.")
print(f"All season-stat rules (FG%/3P%/FT%/PPG/MPG/GP-GS) are now built from pbp_box_score restricted to "
      f"game_date < reference_date ({reference_date_str}), not the ungated season-to-date page -- "
      f"{n_no_asof_data} of {len(roster_keys)} rostered player(s) have no play-by-play data at all before "
      f"reference_date and fall back to the 'no data yet' flag rather than a leaked full-season number.\n")
print("Name reconciliation applied via KNOWN_NAME_ALIASES where the play-by-play spelling and the "
      "official season-stats spelling of a player's name differ.\n")
print(coaching_flags_df)
