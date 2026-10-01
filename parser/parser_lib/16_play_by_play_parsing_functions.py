# 16_play_by_play_parsing_functions.py -- code for the notebook section "Play-by-play (PBP) parsing functions -----------------------------------------------------"
# Runs inside the notebook via run_section("16_play_by_play_parsing_functions"); its settings are in that notebook cell.

# --- Play-by-play (PBP) parsing functions -------------------------------------------------------------------
# Each game's play-by-play is a separate MHTML snapshot of FastScout's playByPlay page (same "Save as Webpage,
# Single File" format as the season schedule), uploaded as "<date> UW-Whitewater @ <Opponent>_pbp.mhtml" (or
# "<date> <Opponent> @ UW-Whitewater_pbp.mhtml" for home games).
def parse_pbp_html(html):
    """Core play-by-play table parsing, factored out of parse_pbp_mhtml() so it can run on HTML from either
    source: a manually-exported/uploaded MHTML snapshot, OR a live Playwright page.content() capture -- see
    scrape_pbp_live() below, which the user confirmed is reachable via a small path change to a game's own
    "game_url" (already available per-game via team_schedules/opp_schedule -- see the schedule-scraping cell
    and the opponent-schedule cell)."""
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    raw_df = pd.read_html(StringIO(str(tables[0])))[0]
    # The table's own header row is "Time | <Team A> | Score | <Team B>" -- it NAMES the two teams. That
    # was being thrown away by the rename below, which is fine while there's a roster to match player
    # names against, but resolve_self_column() (opponent prior-games cell) has no roster to use when the
    # opponent has no scouting report, and with nothing to match it silently defaulted to "uww_text" --
    # a coin flip that swaps the two teams' events. Keep the original labels so that fallback has
    # something deterministic to read. Stored on .attrs rather than as columns so every existing caller
    # (which indexes by the fixed names below) is untouched.
    _pbp_header = [str(c).strip() for c in raw_df.columns]
    raw_df.columns = ["time_raw", "uww_text", "score_raw", "opp_text"]

    def _pbp_team_label(idx):
        """The header text at `idx`, or None when pandas invented one (no <th> row) -- an invented
        "Unnamed: 1"/"0" label names no team, and treating it as one would be worse than admitting we
        don't know."""
        if idx >= len(_pbp_header):
            return None
        label = _pbp_header[idx]
        if not label or label.lower().startswith("unnamed") or label.isdigit():
            return None
        return label

    raw_df.attrs["column_teams"] = {"uww_text": _pbp_team_label(1), "opp_text": _pbp_team_label(3)}
    return raw_df


def parse_pbp_mhtml(path):
    return parse_pbp_html(load_html_snapshot(path))


def scrape_pbp_live(page, game_url, timeout_ms=30000, save_path=None):
    """Navigate to a game's own FastScout play-by-play page and capture its rendered event table.

    Confirmed by a live run: the previous approach -- swap the trailing "/boxscore" segment of `game_url`
    for "/playbyplay" and goto() straight there -- does NOT work. FastScout's SPA only renders this kind of
    sub-route via an in-app tab click, exactly like the already-documented behavior in _click_tab_by_text's
    own docstring above ("Direct page.goto() to a sub-route URL ... gets silently redirected back to
    '/analytics/dashboard'"). A direct goto() to ".../playbyplay?..." gets redirected away from the game
    page entirely, so the FIRST "table" wait (8s) never found one -- and then the fallback tab click ALSO
    timed out (30s) because there was no "Play By Play" tab on whatever page it actually landed on. Always
    goto() the game's own ORIGINAL `game_url` (the boxscore URL -- a valid full-page-load entry point, same
    as every other team/opponent page navigation in this notebook) and click the "Play By Play" nav tab
    in-app from there, instead of ever attempting a direct URL swap. If save_path is given, caches the
    scraped HTML there (see _save_scraped_html in Cell 4) -- the same persist-everything-scraped pattern
    already used for scouting reports and team schedules -- so a future run can fall back to it via
    parse_pbp_mhtml (through load_html_snapshot) without needing to live-scrape again.
    """
    _goto_with_auth_retry(page, game_url, "text=Play By Play", timeout_ms)
    _click_tab_by_text(page, "Play By Play", timeout_ms)
    page.wait_for_selector("table", timeout=timeout_ms)
    html = page.content()
    if save_path:
        _save_scraped_html(html, save_path, "scraped play-by-play")
    return parse_pbp_html(html)
