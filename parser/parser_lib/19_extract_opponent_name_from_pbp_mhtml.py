# 19_extract_opponent_name_from_pbp_mhtml.py -- code for the notebook section "A GAME IS (opponent, game_date), NEVER opponent ALONE ------------------------------------"
# Runs inside the notebook via run_section("19_extract_opponent_name_from_pbp_mhtml"); its settings are in that notebook cell.

def opponent_from_pbp_filename(path):
    """Home/away-aware opponent extraction -- mirrors opponent_from_scout_filename() used for the scout PDFs.
    Filenames are "<date> <Away> @ <Home>_pbp.mhtml" (or "..._pbp.html" for a live-scraped/cached file -- see
    _save_scraped_html), so the correct opponent is whichever side of "@" ISN'T "UW-Whitewater", not simply
    "everything after @" -- that naive approach is right for away games ("UW-Whitewater @ Ripon" -> "Ripon")
    but wrong for home games ("Aurora @ UW-Whitewater" would otherwise extract "UW-Whitewater" itself as the
    opponent).

    CONFIRMED BUG (fixed here): this only ever stripped the "_pbp.mhtml" suffix, never "_pbp.html" -- so for
    every ".html"-sourced file (any auto-downloaded/live-scraped PBP, which is most of them going forward)
    the extension silently rode along attached to whichever side of "@" this function returns. For an AWAY
    game specifically, that's the side actually returned (left == "UW-Whitewater", so `right` -- e.g. "Ripon
    Red Hawks_pbp.html" -- comes back instead of "Ripon Red Hawks"), corrupting the opponent name used to key
    every downstream table (pbp_events, pbp_box_score, lineup_stints, etc.) for that game. HOME games
    happened to come out clean by accident (the garbage suffix landed on `right`, which isn't the branch
    returned when left != "UW-Whitewater"), which is why this only ever broke away games -- confirmed via the
    box-score reconciliation diagnostic above flagging every single away game and zero home games."""
    name = re.sub(r"_pbp\.(mhtml|html)$", "", os.path.basename(path))
    name = re.sub(r"^\d+_\d+_\d+\s+", "", name)
    left, right = [side.strip() for side in name.split(" @ ", 1)]
    return right if left == "UW-Whitewater" else left


# --- A GAME IS (opponent, game_date), NEVER opponent ALONE ---------------------------------------
# CONFIRMED BUG (fixed here): every table below used the short opponent name as a game's identity.
# That silently merges a home-and-home (or a third conference meeting) into ONE game: box-score
# stats get summed across both meetings, the games-played denominator counts them once, and the
# lineup-stint clock -- diffed within ("opponent", "period") while `event_order` restarts at 0 each
# game -- interleaves the two meetings and re-counts the same seconds, inflating minutes many-fold.
# Reconciling uww_pbp_box_score against uww_schedule showed this exactly: UW-La Crosse came out
# 206-209 (63+65+78 vs 60+68+81), i.e. three real games stacked into one row.
#
# GAME_KEYS is the grouping/merge key every per-game computation must use from here on.


def game_date_from_pbp_filename(path):
    """The game's own date, read from the '<m>_<d>_<yy> ' prefix these files are named with.

    This is the ONLY per-file source of truth for WHICH meeting a play-by-play file covers.
    game_date_for() cannot answer that -- it fuzzy-matches the schedule on opponent name and takes
    .iloc[0], so for a rematch it always returns the FIRST meeting's date. Returns None when a file
    carries no date prefix, so the caller can fall back (loudly) rather than guessing silently.
    """
    from datetime import date as _date
    m = re.match(r"^(\d+)_(\d+)_(\d+)\s", os.path.basename(path))
    if not m:
        return None
    month, day, yy = (int(g) for g in m.groups())
    return _date(2000 + yy, month, day)
