"""UW-Whitewater Player Comparison Algorithms — portable version.


Replaces Databricks-specific dependencies (Spark, ai_query, Unity Catalog Volumes)
with standard Python equivalents (OpenAI client, local file paths).


Original: /Users/cfritsch2@uwhealth.org/UW Whitewater Player Comparison Algorithms.py
"""


import hashlib
import json
import math
import os
import re
from collections import Counter


import pandas as pd


PLAYER_COMPARISON_ALGORITHMS_VERSION = "2026-07-29-portable"


# --- LLM configuration (env vars) --------------------------------------------------------------------------
# Set OPENAI_API_KEY and optionally OPENAI_BASE_URL + AI_MODEL
LLM_MODEL_NAME = os.environ.get("AI_MODEL", "gpt-4o-mini")
LLM_PROMPT_VERSION = "v1"
DEFAULT_LLM_CACHE_PATH = os.path.join(os.path.dirname(__file__), "_cache", "llm_player_comparison_cache.jsonl")




def _to_jsonable(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value




def _llm_cache_key(pair):
    canonical = json.dumps(
        {
            "model": LLM_MODEL_NAME,
            "prompt_version": LLM_PROMPT_VERSION,
            "target_player": pair["target_player"],
            "target_position": pair["target_position"],
            "target_notes": pair["target_notes"],
            "target_keys": pair["target_keys"],
            "compared_opponent": pair["compared_opponent"],
            "compared_player": pair["compared_player"],
            "compared_position": pair["compared_position"],
            "compared_notes": pair["compared_notes"],
            "compared_keys": pair["compared_keys"],
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()




def _load_llm_cache(cache_path):
    cache = {}
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "cache_key" in row:
                    cache[row["cache_key"]] = row
    return cache




def _append_llm_cache(cache_path, new_rows):
    if not cache_path or not new_rows:
        return
    cache_dir = os.path.dirname(cache_path)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    with open(cache_path, "a") as f:
        for row in new_rows:
            f.write(json.dumps({k: _to_jsonable(v) for k, v in row.items()}) + "\n")




def _llm_compare_pair(client, pair):
    """Call the OpenAI-compatible API to compare two players. Replaces Spark ai_query()."""
    prompt = (
        "You are a college basketball scouting analyst comparing two players purely on PLAYING STYLE, based "
        "on the free-text scouting notes below (ignore names/jerseys/teams -- focus on how each player plays).\n\n"
        f"Player A ({pair['target_position']}) -- {pair['target_player']}:\n"
        f"  Scouting notes (how they play): {pair['target_notes']}\n"
        f"  Keys to defending them: {pair['target_keys']}\n\n"
        f"Player B ({pair['compared_position']}) -- {pair['compared_player']}:\n"
        f"  Scouting notes (how they play): {pair['compared_notes']}\n"
        f"  Keys to defending them: {pair['compared_keys']}\n\n"
        "Evaluate Player A vs. Player B along TWO SEPARATE dimensions, using ONLY the matching text for each "
        "dimension -- do not let one dimension influence the other.\n"
        "DIMENSION \"notes\": comparing ONLY the \"Scouting notes\" text above, on a 0-10 scale (10 = nearly "
        "identical playing style, 0 = no resemblance), how similar do Player A and Player B play? List 2-4 "
        "shared traits (short phrases) and a one-sentence rationale.\n"
        "DIMENSION \"keys\": comparing ONLY the \"Keys to defending them\" text above, on a 0-10 scale (10 = "
        "nearly identical defensive game plan needed, 0 = no resemblance), how similar is the approach for "
        "defending Player A vs. defending Player B? List 2-4 shared traits and a one-sentence rationale.\n\n"
        "Respond in this exact JSON format:\n"
        '{"comparison": {"notes": {"similarity_score": <float>, "shared_traits": [<strings>], "rationale": "<string>"}, '
        '"keys": {"similarity_score": <float>, "shared_traits": [<strings>], "rationale": "<string>"}}}'
    )


    response = client.chat.completions.create(
        model=LLM_MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=512,
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    raw_text = response.choices[0].message.content
    return json.loads(raw_text)




def compute_tag_importance(tag_series):
    counts = Counter(tag for tags in tag_series for tag in tags)
    n_total = len(tag_series)
    importance = {tag: math.log((n_total + 1) / (count + 1)) + 1 for tag, count in counts.items()}
    return counts, importance




def weighted_tag_similarity(tags1, tags2, importance):
    union_tags = tags1 | tags2
    if not union_tags:
        return 0.0, set()
    shared_tags = tags1 & tags2
    union_weight = sum(importance[t] for t in union_tags)
    shared_weight = sum(importance[t] for t in shared_tags)
    return (shared_weight / union_weight if union_weight else 0.0), shared_tags




def parse_pct(val):
    s = str(val).strip()
    if s in ("", "-", "nan", "None"):
        return None
    if re.match(r"^\d+-\d+$", s):
        # A "made-attempted" totals string (e.g. "21-55") ended up here instead of a percentage --
        # some low-game bench players' PDFs render FG%/3P% as raw made-attempted totals rather than a
        # computed percentage. Not a percentage value, so treat it as missing rather than raising.
        return None
    return float(s.rstrip("%"))




def build_player_comparison_artifacts(schedule, scout_reports, player_profiles,
                                      cache_path=None, use_llm=True, upcoming_opponent=None):
    """Build player comparison data. No Spark required.


    Args:
        schedule: DataFrame with game schedule
        scout_reports: dict of {opponent: parsed_elements}
        player_profiles: DataFrame with player scouting profiles
        cache_path: path to LLM cache file (default: ./_cache/...)
        use_llm: whether to use LLM for comparisons (requires OPENAI_API_KEY)
        upcoming_opponent: the opponent to build comparisons FOR. Pass the notebook's
            `upcoming_opponent_short`. When None, falls back to the old behavior of picking whichever
            scouted opponent has the highest schedule game number ("most recently scouted").


    Returns:
        dict with keys: best_matches, player_similarity, llm_player_comparison, etc.
    """
    if cache_path is None:
        cache_path = DEFAULT_LLM_CACHE_PATH


    position_weight = 3
    height_weight = 2
    height_decay_inches = 3
    notes_tag_weight = 3
    keys_tag_weight = 2
    role_weight = 0.5
    stat_weight = 3
    stat_decay_std = 1.5
    stat_cols = ["PTS", "REB", "AST"]
    pct_cols = ["FG%", "3P%"]
    all_stat_cols = stat_cols + pct_cols
    # CONFIRMED BUG (fixed here): player_profiles does NOT store these three on one scale. PTS and REB are
    # per-game averages; AST/STL/BLK/TO are deliberately left as SEASON TOTALS, because the app divides
    # them by games_played at render time (see the parser's PBP override cell, which says so explicitly,
    # and profile_stat_per_game() in the app). This function read all three straight out of the frame and
    # z-scored them together, so the AST axis of every comparison was measuring season volume -- a player
    # with 73 assists over 24 games sat far from one with 40 over 12 even though they are the same 3.0 and
    # 3.3 per game, and anyone who missed time looked like a non-passer. Converted to per game here so all
    # five features are rates before anything is z-scored.
    total_cols = {"AST"}


    schedule_ordered = schedule.reset_index(drop=True).copy()
    schedule_ordered["game_number"] = schedule_ordered.index + 1


    def schedule_row_for(opponent_short):
        matches = schedule_ordered[schedule_ordered["opponent"].str.contains(re.escape(opponent_short), case=False)]
        return matches.iloc[0] if not matches.empty else None


    scout_game_numbers = {}
    scout_game_dates = {}
    for opp in scout_reports:
        row = schedule_row_for(opp)
        scout_game_numbers[opp] = row["game_number"] if row is not None else None
        scout_game_dates[opp] = row["date"] if row is not None else None


    scouted_with_game_number = {opp: num for opp, num in scout_game_numbers.items() if num is not None}


    def resolve_scouted_name(name, scouted_names):
        """Match `name` onto whichever key scout_reports actually uses, tolerating the short-vs-full naming
        drift documented in the notebook (scouted_opponents holds full names like "Eureka Red Devils" since
        auto-downloaded HTML reports carry the schedule's full name, while older material used "Eureka")."""
        if name is None:
            return None
        target = str(name).strip().casefold()
        names = sorted((str(n) for n in scouted_names), key=len, reverse=True)
        for candidate in names:                      # exact
            if candidate.strip().casefold() == target:
                return candidate
        for candidate in names:                      # either side a prefix of the other
            c = candidate.strip().casefold()
            if c.startswith(target) or target.startswith(c):
                return candidate
        return None


    # The comparison target is the UPCOMING opponent -- the team being prepared for -- not whichever scouted
    # report happens to sit latest on the schedule.
    #
    # CONFIRMED BUG (fixed here): target_opponent was `max(scouted_with_game_number, ...)`, i.e. "most
    # recently scouted game". Whenever a scout report existed for a game further down the schedule than the
    # upcoming one, every row of uww_player_comparisons was built for THAT team instead, and the app's Player
    # Details dialog -- which looks up the upcoming opponent's roster players -- matched nothing and showed
    # "No comparable player found" against a CSV that was full of data for a different team.
    if upcoming_opponent is not None:
        resolved_target = resolve_scouted_name(upcoming_opponent, scout_game_numbers.keys())
        if resolved_target is None:
            # Deliberately NOT falling back to the old "latest scouted" pick: silently comparing a different
            # team is exactly the failure this parameter exists to prevent. Better an empty result that says
            # why.
            print(f"WARNING: upcoming opponent {upcoming_opponent!r} has no scout report loaded "
                  f"(scouted: {sorted(scout_game_numbers)}) -- player comparisons will be empty for them. "
                  f"Add their scout report to INPUT_DIR and re-run.")
            target_opponent = upcoming_opponent
            target_game_number = None
        else:
            target_opponent = resolved_target
            target_game_number = scout_game_numbers.get(target_opponent)
        if target_game_number is None:
            # Not resolvable on the schedule: compare against every other scouted opponent rather than none.
            previous_opponents = [opp for opp in scouted_with_game_number if opp != target_opponent]
        else:
            previous_opponents = [
                opp for opp, num in scouted_with_game_number.items()
                if num < target_game_number and opp != target_opponent
            ]
    elif not scouted_with_game_number:
        target_opponent = None
        target_game_number = None
        previous_opponents = []
    else:
        target_opponent = max(scouted_with_game_number, key=scouted_with_game_number.get)
        target_game_number = scouted_with_game_number[target_opponent]
        previous_opponents = [opp for opp, num in scouted_with_game_number.items() if num < target_game_number]


    notes_tag_counts, notes_tag_importance = compute_tag_importance(player_profiles["notes_tags"])
    keys_tag_counts, keys_tag_importance = compute_tag_importance(player_profiles["keys_tags"])


    target_players = player_profiles[player_profiles["opponent"] == target_opponent]
    candidate_players = player_profiles[player_profiles["opponent"].isin(previous_opponents)]


    def per_game(row, col):
        """`col` as a per-game rate, whatever scale player_profiles happens to store it on.

        A total with no games_played to divide by is returned as missing rather than as itself: an
        undivided total silently compared against per-game figures is the bug this function exists to
        stop, and stat_similarity() already handles a missing feature correctly (it drops it from the
        pair and lowers the evidence, rather than scoring it as agreement).
        """
        value = pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]
        if pd.isna(value) or col not in total_cols:
            return value
        games = pd.to_numeric(pd.Series([row.get("games_played")]), errors="coerce").iloc[0]
        if pd.isna(games) or games <= 0:
            return float("nan")
        return value / games

    pool = pd.concat([target_players, candidate_players], ignore_index=True)
    # Keyed by (opponent, name) rather than (opponent, jersey_number): players added straight from the
    # play-by-play have no jersey number at all, so several of them on one team collapsed onto the same
    # (opponent, None) key and every one but the last silently inherited another player's z-scores.
    pool_stats = pool[["opponent", "name"]].copy() if not pool.empty else pd.DataFrame(columns=["opponent", "name"])
    for col in stat_cols:
        pool_stats[col] = [per_game(r, col) for _, r in pool.iterrows()] if not pool.empty else []
    for col in pct_cols:
        pool_stats[col] = pool[col].apply(parse_pct) if not pool.empty else []


    def zscore_col(s):
        std = s.std()
        if not std or pd.isna(std):
            return pd.Series(0.0, index=s.index)
        return (s - s.mean()) / std


    zscored = pool_stats[all_stat_cols].apply(zscore_col) if not pool_stats.empty else pd.DataFrame(columns=all_stat_cols)
    def stat_key(row):
        return (str(row.get("opponent")).strip().casefold(), str(row.get("name")).strip().casefold())

    stat_z_lookup = {
        stat_key(row): {col: zscored.loc[i, col] for col in all_stat_cols}
        for i, row in pool_stats.iterrows()
    }


    def stat_similarity(p1, p2):
        z1 = stat_z_lookup.get(stat_key(p1), {})
        z2 = stat_z_lookup.get(stat_key(p2), {})
        diffs = [abs(z1[col] - z2[col]) for col in all_stat_cols if pd.notna(z1.get(col)) and pd.notna(z2.get(col))]
        if not diffs:
            return None
        avg_diff = sum(diffs) / len(diffs)
        return round(max(0.0, 1 - avg_diff / stat_decay_std), 3)


    def similarity_score(p1, p2):
        score = 0.0
        if p1["position_group"] == p2["position_group"] and p1["position_group"] != "Unknown":
            score += position_weight
        if p1["height_inches"] and p2["height_inches"]:
            height_diff = abs(p1["height_inches"] - p2["height_inches"])
            score += max(0, height_weight - height_diff / height_decay_inches)
        else:
            height_diff = None
        notes_tag_sim, shared_notes_tags = weighted_tag_similarity(p1["notes_tags"], p2["notes_tags"], notes_tag_importance)
        score += notes_tag_sim * notes_tag_weight
        keys_tag_sim, shared_keys_tags = weighted_tag_similarity(p1["keys_tags"], p2["keys_tags"], keys_tag_importance)
        score += keys_tag_sim * keys_tag_weight
        if p1["role"] == p2["role"]:
            score += role_weight
        stat_sim = stat_similarity(p1, p2)
        if stat_sim is not None:
            score += stat_sim * stat_weight

        # WHAT EVIDENCE WAS ACTUALLY AVAILABLE for this pair. The score above is an absolute sum, so a
        # comparison resting on height and position alone lands on the same scale as one backed by
        # scouting notes and season stats -- observed directly: an un-scouted bench player with no stats
        # scored 5.17 while a fully-scouted starter scored 5.25, and the app displayed them identically.
        # This does not change the score (that would silently move every existing ranking); it records
        # what the score is standing on so the app can say so.
        evidence = 0.0
        if p1["position_group"] == p2["position_group"] and p1["position_group"] != "Unknown":
            evidence += position_weight
        elif p1["position_group"] != "Unknown" and p2["position_group"] != "Unknown":
            evidence += position_weight       # comparable either way: a mismatch is still information
        if p1["height_inches"] and p2["height_inches"]:
            evidence += height_weight
        if p1["notes_tags"] or p2["notes_tags"]:
            evidence += notes_tag_weight
        if p1["keys_tags"] or p2["keys_tags"]:
            evidence += keys_tag_weight
        if p1["role"] and p2["role"]:
            evidence += role_weight
        if stat_sim is not None:
            evidence += stat_weight
        max_evidence = position_weight + height_weight + notes_tag_weight + keys_tag_weight + role_weight + stat_weight
        coverage = round(evidence / max_evidence, 3) if max_evidence else 0.0

        has_tags = bool(p1["notes_tags"] or p1["keys_tags"])
        if has_tags and stat_sim is not None:
            method = "scouting notes + stats"
        elif has_tags:
            method = "scouting notes, no stats"
        elif stat_sim is not None:
            method = "stats and size (no scouting notes for this player)"
        else:
            method = "size and position only (no scouting notes, no stats)"
        return (round(score, 2), shared_notes_tags, shared_keys_tags, height_diff, stat_sim,
                coverage, method)


    stat_display_cols = ["PTS", "REB", "AST", "FG%", "3P%"]
    similarity_rows = []
    for _, t in target_players.iterrows():
        for _, c in candidate_players.iterrows():
            (score, shared_notes_tags, shared_keys_tags, height_diff, stat_sim,
             evidence_coverage, comparison_method) = similarity_score(t, c)
            row = {
                "target_player": t["name"], "target_position": t["position"], "target_role": t["role"],
                "target_opponent": target_opponent, "target_game_date": scout_game_dates.get(target_opponent),
                "compared_opponent": c["opponent"], "compared_game_date": scout_game_dates.get(c["opponent"]),
                "compared_player": c["name"],
                "compared_position": c["position"], "compared_role": c["role"],
                "similarity_score": score,
                "shared_notes_tags": ", ".join(sorted(shared_notes_tags)),
                "shared_keys_tags": ", ".join(sorted(shared_keys_tags)),
                "height_diff_in": height_diff,
                "stat_similarity": stat_sim,
                "evidence_coverage": evidence_coverage,
                "comparison_method": comparison_method,
                "target_has_scouting_report": bool(t.get("has_scouting_report", True)),
            }
            for col in stat_display_cols:
                # Written on the same per-game scale the comparison ran on. These used to be copied
                # straight from player_profiles, so target_AST read as a season total (12) sitting beside
                # target_PTS as a per-game average (1.1) under matching column names.
                if col in total_cols:
                    _t_pg, _c_pg = per_game(t, col), per_game(c, col)
                    row[f"target_{col}"] = None if pd.isna(_t_pg) else round(float(_t_pg), 1)
                    row[f"compared_{col}"] = None if pd.isna(_c_pg) else round(float(_c_pg), 1)
                else:
                    row[f"target_{col}"] = t.get(col)
                    row[f"compared_{col}"] = c.get(col)
            similarity_rows.append(row)


    if similarity_rows:
        player_similarity = pd.DataFrame(similarity_rows).sort_values(
            ["target_player", "similarity_score"], ascending=[True, False]
        )
    else:
        player_similarity = pd.DataFrame()


    # CONFIRMED BUG (fixed here): this used .groupby("target_player").first(), and pandas' GroupBy.first()
    # takes the first NON-NULL value COLUMN BY COLUMN -- it does not return a row. So whenever the top-ranked
    # candidate had a null in any column, that cell was silently filled from a LOWER-ranked candidate, and
    # the exported row became a mixture of two different players under one name.
    #
    # Observed: Jack Haynes' best match is Korbin Heitzman (Alma, 9.71), whose stat columns are all null
    # because Alma has no _pbp files to back-fill from. His row in uww_player_comparisons came out carrying
    # 11.6 PTS / 8.4 REB / 1.8 AST / 46.8 FG% / 58.3 3P% and a stat_similarity of 0.443 -- every one of those
    # belonging to Vinnie Adjahoungbeta of Elmhurst, Haynes' THIRD-ranked candidate at 9.16, the first one
    # down the list with numbers in it. The row's own comparison_method still read "scouting notes, no
    # stats", which is the tell: the label was computed on the real row, the numbers were not.
    #
    # head(1) returns the actual top row, nulls included. A missing stat has to stay missing -- the app
    # renders "no season stats" from it, and a borrowed number reads as a real scouting fact.
    # kind="stable": similarity_score ties are common (Connor Mosele's top two candidates both score 12.12,
    # Juvon Crawford's both 3.25), and pandas' default quicksort is not stable, so which of two equally-good
    # comparables gets exported was down to sort internals and could differ between runs on the same data.
    # A stable sort breaks ties by player_profiles' own row order instead -- arbitrary, but at least fixed.
    best_matches = (
        player_similarity.sort_values("similarity_score", ascending=False, kind="stable")
        .groupby("target_player", as_index=False).head(1)
        .sort_values("similarity_score", ascending=False, kind="stable")
        .reset_index(drop=True)
    ) if not player_similarity.empty else pd.DataFrame()


    # --- LLM-based comparison (replaces Spark ai_query with OpenAI client) ---
    target_players_scouted = target_players[target_players["has_scouting_report"]]
    candidate_players_scouted = candidate_players[candidate_players["has_scouting_report"]]


    llm_pairs = []
    for _, t in target_players_scouted.iterrows():
        for _, c in candidate_players_scouted.iterrows():
            llm_pairs.append({
                "target_player": t["name"],
                "target_position": t["position"],
                "target_notes": (t["player_notes"] or "").strip(),
                "target_keys": (t["keys_to_defending"] or "").strip(),
                "compared_opponent": c["opponent"],
                "compared_player": c["name"],
                "compared_position": c["position"],
                "compared_notes": (c["player_notes"] or "").strip(),
                "compared_keys": (c["keys_to_defending"] or "").strip(),
            })


    def extract_dimension(parsed, key):
        node = parsed.get(key, {}) if isinstance(parsed, dict) else {}
        if not isinstance(node, dict):
            node = {}
        return {
            "similarity_score": node.get("similarity_score"),
            "shared_traits": ", ".join(node.get("shared_traits") or []),
            "rationale": node.get("rationale"),
        }


    llm_columns = [
        "target_player", "target_position", "compared_opponent", "compared_player", "compared_position",
        "target_notes", "target_keys", "compared_notes", "compared_keys",
        "llm_notes_similarity_score", "llm_notes_shared_traits", "llm_notes_rationale",
        "llm_keys_similarity_score", "llm_keys_shared_traits", "llm_keys_rationale", "llm_similarity_score",
    ]


    cached_rows = []
    pairs_to_query = []
    llm_player_comparison = pd.DataFrame(columns=llm_columns)


    if not use_llm:
        print("LLM comparison skipped (use_llm=False) -- using tag-based similarity only.")
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            print("WARNING: OPENAI_API_KEY not set -- skipping LLM comparison.")
            use_llm = False
        else:
            from openai import OpenAI
            base_url = os.environ.get("OPENAI_BASE_URL")
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(**kwargs)


            llm_cache = _load_llm_cache(cache_path)
            for pair in llm_pairs:
                pair_key = _llm_cache_key(pair)
                cached_row = llm_cache.get(pair_key)
                if cached_row is not None:
                    cached_rows.append(cached_row)
                else:
                    pairs_to_query.append(dict(pair, _cache_key=pair_key))


            fresh_rows = []
            for pair in pairs_to_query:
                try:
                    result = _llm_compare_pair(client, pair)
                    comparison = result.get("comparison", result)
                    notes_dim = extract_dimension(comparison, "notes")
                    keys_dim = extract_dimension(comparison, "keys")


                    row = {
                        "cache_key": pair["_cache_key"],
                        "target_player": pair["target_player"],
                        "target_position": pair["target_position"],
                        "compared_opponent": pair["compared_opponent"],
                        "compared_player": pair["compared_player"],
                        "compared_position": pair["compared_position"],
                        "target_notes": pair["target_notes"],
                        "target_keys": pair["target_keys"],
                        "compared_notes": pair["compared_notes"],
                        "compared_keys": pair["compared_keys"],
                        "llm_notes_similarity_score": notes_dim["similarity_score"],
                        "llm_notes_shared_traits": notes_dim["shared_traits"],
                        "llm_notes_rationale": notes_dim["rationale"],
                        "llm_keys_similarity_score": keys_dim["similarity_score"],
                        "llm_keys_shared_traits": keys_dim["shared_traits"],
                        "llm_keys_rationale": keys_dim["rationale"],
                        "llm_similarity_score": ((notes_dim["similarity_score"] or 0) + (keys_dim["similarity_score"] or 0)) / 2,
                    }
                    fresh_rows.append(row)
                except Exception as e:
                    print(f"  LLM error for {pair['target_player']} vs {pair['compared_player']}: {e}")


            _append_llm_cache(cache_path, fresh_rows)
            print(f"LLM comparison: {len(cached_rows)} cached, {len(fresh_rows)} newly queried.")


            all_llm_rows = [{col: row.get(col) for col in llm_columns} for row in cached_rows] +                            [{col: row.get(col) for col in llm_columns} for row in fresh_rows]
            if all_llm_rows:
                llm_player_comparison = pd.DataFrame(all_llm_rows, columns=llm_columns)


    notes_tag_importance_df = pd.DataFrame(
        [
            {"tag": tag, "count": notes_tag_counts[tag], "importance_weight": round(notes_tag_importance[tag], 3)}
            for tag in sorted(notes_tag_counts, key=lambda t: (-notes_tag_counts[t], t))
        ]
    )
    keys_tag_importance_df = pd.DataFrame(
        [
            {"tag": tag, "count": keys_tag_counts[tag], "importance_weight": round(keys_tag_importance[tag], 3)}
            for tag in sorted(keys_tag_counts, key=lambda t: (-keys_tag_counts[t], t))
        ]
    )


    return {
        "best_matches": best_matches,
        "player_similarity": player_similarity,
        "llm_player_comparison": llm_player_comparison,
        "target_opponent": target_opponent,
        "previous_opponents": previous_opponents,
        "scout_game_dates": scout_game_dates,
        # Additional diagnostics the calling notebook cell prints directly -- exported here since they only
        # exist as local variables inside this function otherwise (no shared notebook namespace to fall back
        # on now that this logic lives in its own module rather than a %run'd notebook).
        "scout_game_numbers": scout_game_numbers,
        "target_game_number": target_game_number,
        "notes_tag_importance_df": notes_tag_importance_df,
        "keys_tag_importance_df": keys_tag_importance_df,
        # Exported so the calling notebook cell can report how heavily the stat-similarity component was
        # weighted into each pair's overall similarity_score -- otherwise only a local variable in here.
        "stat_weight": stat_weight,
    }




