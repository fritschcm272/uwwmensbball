# 22_locate_opponent_own_schedule_backup_file.py -- code for the notebook section "`schedule` only has ONE row per opponent (their single game vs UWW), so it can't tell us w"
# Runs inside the notebook via run_section("22_locate_opponent_own_schedule_backup_file"); its settings are in that notebook cell.

# `schedule` only has ONE row per opponent (their single game vs UWW), so it can't tell us what THIS
# opponent's own games looked like before they played Whitewater. Load their own FastScout team schedule page
# instead -- saved the same way as UW-Whitewater's own ("<Opponent> - Schedule.mhtml"), parsed identically to
# the schedule-parsing cell above.
def _schedule_file_for(opponent_full_name, opponent_short_hint, volume_dir):
    """Find this opponent's own '<Team> - Schedule.mhtml' backup file, tolerant of short-vs-full naming --
    confirmed by a live run: scouted_opponents (and upcoming_opponent_short derived from it) now holds FULL
    team names (e.g. 'Elmhurst Bluejays') since auto-downloaded HTML scout reports carry the schedule's full
    opponent name in their filename, but the manually-uploaded backup schedule MHTMLs predate that change and
    still use the SHORT team name (e.g. 'Elmhurst - Schedule.mhtml') -- an exact '{short} - Schedule.mhtml'
    match no longer finds them. Match on whichever side is a substring of the other instead."""
    # Glob both ".mhtml" (a manually-exported/uploaded snapshot) and ".html" (this notebook's own
    # live-scrape cache -- see _save_scraped_html in Cell 4).
    for p in glob.glob(f"{volume_dir}/* - Schedule.mhtml") + glob.glob(f"{volume_dir}/* - Schedule.html"):
        file_team = re.sub(r"\s*-\s*Schedule\.(mhtml|html)$", "", os.path.basename(p), flags=re.IGNORECASE)
        if file_team.lower() in opponent_full_name.lower() or opponent_short_hint.lower() in file_team.lower():
            return p
    return f"{volume_dir}/{opponent_short_hint} - Schedule.mhtml"  # fall back to the old guess, for the warning message below
