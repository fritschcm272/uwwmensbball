# 02_parse_every_team_schedule_scrape_live_from.py -- code for the notebook section "Every team's own FastScout schedule snapshot (MHTML) lives in INPUT_DIR alongside per-game"
# Runs inside the notebook via run_section("02_parse_every_team_schedule_scrape_live_from"); its settings are in that notebook cell.

# Every team's own FastScout schedule snapshot (MHTML) lives in INPUT_DIR alongside per-game pbp/video/box
# MHTML files and scout-report PDFs -- process every "<Team> - Schedule.mhtml" file found there (not just
# UWW's). Filtering strictly on the "- Schedule.mhtml" suffix (not just "*.mhtml") matters here: INPUT_DIR is
# a single flat portable folder (unlike the original Databricks setup, which kept per-game MHTMLs in a
# separate volume from the team-schedule snapshots), so a bare "*.mhtml" glob would also match per-game files
# like "11_14_25 UW-Whitewater @ St. Thomas (TX)_box.mhtml" -- which also contains "whitewater" in its name
# and would otherwise be mistaken for UWW's own schedule snapshot below. Each real schedule file has the same
# 3 <table> structure: [0] game-by-game schedule/results, [1] season player box-score stats, [2] empty
# (template for future games).
import asyncio
import concurrent.futures
import subprocess
import time
import traceback
from urllib.parse import urljoin, urlparse, parse_qs

schedules_dir = INPUT_DIR
# Glob both ".mhtml" (a manually-exported/uploaded snapshot) and ".html" (this notebook's own live-scrape
# cache -- see _save_scraped_html) -- the same *_scout.pdf/*_scout.html duality already used for reports.
schedule_mhtml_paths = sorted(
    p for p in glob.glob(f"{schedules_dir}/*.mhtml") + glob.glob(f"{schedules_dir}/*.html")
    # "(?:_\d{4})?" makes the "_<season start year>" suffix optional, so this matches both a legacy
    # filename (no suffix) and a new one saved with _add_season_suffix_to_path.
    if re.search(r"-\s*Schedule(?:_\d{4})?\.(mhtml|html)$", os.path.basename(p), re.IGNORECASE)
)
print(f"Found {len(schedule_mhtml_paths)} schedule MHTML file(s) in {schedules_dir}:")
for p in schedule_mhtml_paths:
    print(" -", os.path.basename(p))


def load_mhtml_html(path):
    """Extract the embedded text/html part from a saved MHTML web page archive."""
    with open(path, "rb") as f:
        raw = f.read()
    msg = email.message_from_bytes(raw, policy=policy.default)
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            charset = part.get_content_charset() or "utf-8"
            return part.get_payload(decode=True).decode(charset, errors="replace")
    return None


def load_html_snapshot(path):
    """Load a saved HTML snapshot from disk, handling both a genuine MHTML web-page archive (from a
    browser's "Save as Webpage, Single File", parsed via load_mhtml_html) AND a plain rendered-HTML file (as
    saved by this notebook's own live-scrape caching -- see _save_scraped_html below) -- mirrors the same
    duality already established for scouting reports ("*_scout.pdf" vs "*_scout.html")."""
    if path.lower().endswith(".mhtml"):
        return load_mhtml_html(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _save_scraped_html(html, dest_path, label):
    """Save raw scraped HTML to disk, the same way scouting reports are already cached as "*_scout.html" --
    confirmed by the user: they want everything this notebook scrapes persisted this way, not just held in
    memory for the current run, so a future run has a local backup if live scraping is unavailable or fails.
    Read back via load_html_snapshot (NOT load_mhtml_html directly -- this is plain HTML, not a real
    multipart MHTML archive)."""
    try:
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"    [save] {label} -> {os.path.basename(dest_path)}")
    except Exception as save_error:
        print(f"    [save] Could not save {label} to {dest_path}: {type(save_error).__name__}: {save_error}")


def split_opponent(text):
    m = re.match(r"^(.*?)(\d+-\d+)$", str(text).strip())
    return (m.group(1).strip(), m.group(2)) if m else (text, None)


def split_result(text):
    m = re.match(r"^([WL])(\d+)-(\d+)$", str(text).strip())
    if not m:
        return (None, None, None)
    return (m.group(1), int(m.group(2)), int(m.group(3)))




def _resolve_team_link(href):
    """Normalize a team link href to an absolute fastscout.fastmodelsports.com URL. Live-rendered SPA pages
    often use RELATIVE hrefs (e.g. "/teams/<id>") for internal client-side-routed links, unlike an exported
    MHTML snapshot's browser-resolved absolute hrefs -- urljoin makes both cases resolve the same way."""
    return href if href.startswith("http") else urljoin(FASTSCOUT_ORIGIN, href)


# Games that have a scouting report -- one "*_scout.pdf" file per scouted matchup, named
# "<date> <Team A> @ <Team B>_scout.pdf", sitting alongside the schedule MHTMLs in INPUT_DIR. Used below
# to filter each team's own schedule down to only the games that have a matching scout report.
volume_dir = INPUT_DIR
# Confirmed by the user: no PDF is needed at all -- scouting reports auto-downloaded from FastScout are now
# saved as "*_scout.html" (the live report page's own rendered DOM) instead of trying to reproduce a PDF via
# Chromium's print pipeline, which never worked reliably across headless/headed and every print-media
# variation tried. Manually-uploaded reports stay as "*_scout.pdf" (from before this change) -- glob both so
# either format counts as "this opponent already has a report".
# Routed through find_scout_files() (Configuration cell) so the `before_scout` switch is honoured here:
# with before_scout="yes" the upcoming game's own report is left out of this list entirely, which in turn
# keeps it out of scouted_opponents_for() / _scout_pdf_already_exists() below.
scout_pdf_files = find_scout_files(volume_dir)


def scouted_opponents_for(team_name, scout_files):
    team_key = team_name.split()[0].lower()
    opponents = []
    for p in scout_files:
        # Confirmed by a live run: this only stripped "_scout.pdf" -- never updated when "*_scout.html"
        # downloads were added above, so any HTML-sourced report kept its "_scout.html" suffix baked into
        # the parsed opponent name (e.g. "Ripon Red Hawks_scout.html"). That garbled name then never matches
        # the real schedule's plain "Ripon Red Hawks" opponent text below, silently dropping that game from
        # the scouted-opponents filter -- confirmed by a live run where exactly the HTML-sourced AWAY-game
        # opponents (whose name ends up on the right side of " @ ", where the suffix lands) vanished from
        # UWW's own scouted schedule. Strip either extension.
        name = re.sub(r"_scout\.(pdf|html)$", "", os.path.basename(p), flags=re.IGNORECASE)
        name = re.sub(r"^\d+_\d+_\d+\s+", "", name)
        if " @ " not in name:
            continue
        left, right = [side.strip() for side in name.split(" @ ", 1)]
        if team_key in left.lower():
            opponents.append(right)
        elif team_key in right.lower():
            opponents.append(left)
    return opponents


# Parse the schedule dates (format from FastScout is like "Sat, Nov 16") into comparable datetimes.
# CONFIRMED CHANGE (requested): this used to hardcode "2025 if month >= 8 else 2026" -- a single
# season baked directly into the parser, silently wrong the moment a schedule snapshot from a
# DIFFERENT season is loaded (e.g. loading 2024-25 data alongside 2025-26). Confirmed live: every
# schedule page FastScout renders carries its own season directly on the page, in a "seasonDropdown"
# element showing text like "2025-2026" -- read via extract_season_start_year() below instead of
# assumed. _DEFAULT_SEASON_START_YEAR is kept as a fallback ONLY for the rare case a page's season
# text can't be found/parsed, so a run never hard-fails over this specifically.
_DEFAULT_SEASON_START_YEAR = 2025

def extract_season_start_year(soup, fallback=None):
    """Read a FastScout team page's own season-selector text (e.g. "2025-2026") directly off the page,
    via its #seasonDropdown element, instead of assuming one hardcoded season for every page. Returns
    the season's START year (e.g. 2025 for "2025-2026") as an int, or `fallback` if the element isn't
    present or its text doesn't parse -- confirmed present on both UWW's own schedule page and every
    opponent schedule page checked so far, but not asserted as always-guaranteed to exist."""
    el = soup.find(id="seasonDropdown")
    if el is not None:
        m = re.search(r"(\d{4})\s*-\s*\d{2,4}", el.get_text(" ", strip=True))
        if m:
            return int(m.group(1))
    return fallback

def parse_schedule_date(date_str, season_start_year=None):
    """`season_start_year` is the ACADEMIC year the season started in (e.g. 2025 for "2025-2026") --
    pass the value extract_season_start_year() read off the specific page this date came from, so a
    date from a 2024-25 schedule and one from a 2025-26 schedule each resolve to their own real
    calendar year rather than both being forced through the same assumption. Falls back to
    _DEFAULT_SEASON_START_YEAR when no season_start_year is given (callers that can't easily thread a
    specific one through -- see the call sites further down this notebook)."""
    try:
        parsed = datetime.strptime(date_str.strip(), "%a, %b %d")
        _syear = season_start_year if season_start_year is not None else _DEFAULT_SEASON_START_YEAR
        year = _syear if parsed.month >= 8 else _syear + 1
        return parsed.replace(year=year)
    except (ValueError, AttributeError):
        return None

def _add_season_suffix_to_path(path, html):
    """Insert "_<season start year>" before the file extension, e.g. "UW-Whitewater - Schedule.html" ->
    "UW-Whitewater - Schedule_2025.html" -- read directly from the page's own season-selector text (see
    extract_season_start_year), so a schedule snapshot saved for one season can never collide with, or
    get silently confused with, one saved for a different season under the same base filename."""
    year = extract_season_start_year(BeautifulSoup(html, "lxml"), fallback=_DEFAULT_SEASON_START_YEAR)
    root, ext = os.path.splitext(path)
    return f"{root}_{year}{ext}"


def build_team_schedule_from_html(html, source_label):
    """Parse one team's own FastScout schedule page HTML (from an MHTML snapshot OR a live scrape) into a
    cleaned schedule DataFrame."""
    page_soup = BeautifulSoup(html, "lxml")
    page_tables = page_soup.find_all("table")

    team_name_raw = page_soup.find("h1").get_text(strip=True)
    team_name = re.match(r"^([^\d]+)", team_name_raw).group(1).strip()

    sched_raw = pd.read_html(StringIO(str(page_tables[0])))[0]

    row_els = [r for r in page_tables[0].find_all("tr") if r.find_all("td")]
    opponent_urls, game_urls, video_urls = [], [], []
    for row_el in row_els:
        hrefs = [a["href"] for a in row_el.find_all("a", href=True)]
        # Match on the "/teams/" path alone (not requiring the full domain) so RELATIVE hrefs from a live
        # SPA render match too -- see _resolve_team_link.
        fastscout_team_links = [h for h in hrefs if "/teams/" in h and "identity.hudl.com" not in h]
        opponent_links = [h for h in fastscout_team_links if "/games/" not in h]
        boxscore_links = [h for h in fastscout_team_links if "/boxscore" in h]
        video_links = [h for h in hrefs if "synergysports.com/video" in h]
        opponent_urls.append(_resolve_team_link(opponent_links[0]) if opponent_links else None)
        game_urls.append(_resolve_team_link(boxscore_links[0]) if boxscore_links else None)
        video_urls.append(video_links[0] if video_links else None)
    sched_raw["opponent_url"] = opponent_urls
    sched_raw["game_url"] = game_urls
    sched_raw["video_url"] = video_urls

    team_schedule = pd.DataFrame()
    team_schedule["date"] = sched_raw["Date"]
    opp_split = sched_raw["Opponent"].apply(split_opponent)
    team_schedule["opponent"] = opp_split.apply(lambda x: x[0])
    team_schedule["team"] = team_name
    team_schedule["location"] = sched_raw["Location"]
    team_schedule["opponent_url"] = sched_raw["opponent_url"]
    team_schedule["game_url"] = sched_raw["game_url"]
    team_schedule["video_url"] = sched_raw["video_url"]
    res_split = sched_raw["Result"].apply(split_result)
    team_schedule["outcome"] = res_split.apply(lambda x: x[0])
    team_schedule["team_score"] = res_split.apply(lambda x: x[1])
    team_schedule["opponent_score"] = res_split.apply(lambda x: x[2])
    team_schedule["point_margin"] = team_schedule["team_score"] - team_schedule["opponent_score"]

    # This file's OWN real season, read from the page itself rather than assumed -- see
    # extract_season_start_year(). Stored as a real column (not just a local variable used once here) so
    # it travels with these rows through every later concat/filter, and any later code that needs to
    # resolve one of THIS team's own dates again (e.g. re-parsing a date pulled from a specific row) can
    # use the season that row actually came from, instead of falling back to a single assumed default.
    _season_start_year = extract_season_start_year(page_soup, fallback=_DEFAULT_SEASON_START_YEAR)
    team_schedule["season"] = f"{_season_start_year}-{str(_season_start_year + 1)[-2:]}"
    team_schedule["_parsed_date"] = team_schedule["date"].apply(lambda d: parse_schedule_date(d, _season_start_year))
    is_primary_team = "whitewater" in team_name.lower()

    if is_primary_team:
        scouted_opponents = scouted_opponents_for(team_name, scout_pdf_files)
        is_scouted = team_schedule["opponent"].apply(
            lambda opp: any(re.search(re.escape(short), opp, re.IGNORECASE) for short in scouted_opponents)
        )

        # Determine upcoming from the FULL schedule (not filtered to scouted-only) so that a new
        # opponent whose scout report hasn't been downloaded yet still gets flagged as upcoming and
        # triggers the live-scrape download below.
        team_schedule["Upcoming"] = "No"
        upcoming_idx = None
        upcoming_candidates = team_schedule[team_schedule["_parsed_date"] >= reference_date]
        if not upcoming_candidates.empty:
            upcoming_idx = upcoming_candidates["_parsed_date"].idxmin()
        if upcoming_idx is not None:
            team_schedule.loc[upcoming_idx, "Upcoming"] = "Yes"

        # Keep scouted opponents (played games) + the upcoming game (even if not yet scouted)
        keep_mask = (is_scouted & (team_schedule["_parsed_date"] < reference_date)) | (team_schedule.index == upcoming_idx)
        team_schedule = team_schedule[keep_mask].reset_index(drop=True)
        summary_note = f"scouted opponents: {scouted_opponents}"
    else:
        team_schedule = team_schedule[team_schedule["_parsed_date"] < reference_date].reset_index(drop=True)
        team_schedule["Upcoming"] = "No"
        summary_note = f"all games before {reference_date_str}"

    team_schedule = team_schedule.drop(columns=["_parsed_date"])

    # CONFIRMED BUG (fixed here): this nulls every column NOT in the allowlist below for the upcoming
    # (not-yet-played) row -- correct for score/outcome columns, which really would be a leak, but
    # "season" wasn't in the allowlist when it was added, so it silently got nulled out here too. Usually
    # invisible (any OTHER row's "season" value was still fine to read), but when the upcoming game is
    # the ONLY row left after filtering -- exactly the "reference_date before UWW's first game" case --
    # .iloc[0] hits this nulled row directly, and int(str(None).split("-")[0]) raised "ValueError:
    # invalid literal for int() with base 10: 'None'" two cells down. "season" isn't leaky information
    # the way a score/outcome is -- it's added to the allowlist alongside the other non-result columns.
    team_schedule.loc[
        team_schedule["Upcoming"] == "Yes",
        team_schedule.columns.difference(["date", "opponent", "Upcoming", "team", "location", "opponent_url", "game_url", "video_url", "season"]),
    ] = None

    print(f"  {team_name} ({source_label}): {len(team_schedule)} game(s) -- {summary_note}")
    return team_schedule, page_soup, page_tables


def build_team_schedule(schedule_path):
    """Parse one team's own saved FastScout schedule snapshot (a genuine ".mhtml" export OR this notebook's
    own live-scrape ".html" cache -- see load_html_snapshot) into a cleaned schedule DataFrame."""
    html = load_html_snapshot(schedule_path)
    return build_team_schedule_from_html(html, source_label=os.path.basename(schedule_path))


def login_to_fastscout(page, username, password, timeout_ms=20000):
    """Log into FastScout via Hudl's Auth0 Universal Login flow. Selectors avoid the dynamic
    React-generated ids/names seen in a saved snapshot of this flow (e.g. "uniId_:r0:") since those
    regenerate every session -- input[type=...] plus button role/name are stable across sessions instead.

    Each step is wrapped separately and re-raises with the URL at that point PLUS any visible on-page error
    text (Auth0's Universal Login shows invalid-credential/MFA/CAPTCHA errors as text on the page itself,
    not as an HTTP error or a distinct exception type) -- otherwise every failure mode collapses into the
    same generic timeout with no way to tell WHY the login didn't go through.
    """

    def _page_error_text():
        for selector in ('[role="alert"]', ".error-message", "#error-element-password", "#error-element-username"):
            try:
                text = page.locator(selector).first.inner_text(timeout=1000)
                if text and text.strip():
                    return text.strip()
            except Exception:
                continue
        return None

    try:
        email_input = page.locator('input[type="email"]')
        email_input.wait_for(timeout=timeout_ms)
        email_input.fill(username)
        # An UNANCHORED "continue" regex also matches Hudl's "Continue with Google/Facebook/Apple" social
        # login buttons on this page, which Playwright's strict mode rejects as an ambiguous match (4
        # elements). Anchoring to the exact button text disambiguates it from those.
        page.get_by_role("button", name=re.compile(r"^continue$", re.IGNORECASE)).click()
    except Exception as e:
        error_text = _page_error_text()
        raise RuntimeError(
            f"FastScout login failed at the EMAIL step (url={page.url}): {type(e).__name__}: {e}"
            + (f" -- page showed: {error_text!r}" if error_text else "")
        ) from e

    try:
        password_input = page.locator('input[type="password"]')
        password_input.wait_for(timeout=timeout_ms)
        password_input.fill(password)
        page.get_by_role("button", name=re.compile(r"^(continue|log ?in)$", re.IGNORECASE)).click()
    except Exception as e:
        error_text = _page_error_text()
        raise RuntimeError(
            f"FastScout login failed at the PASSWORD step (url={page.url}): {type(e).__name__}: {e}"
            + (f" -- page showed: {error_text!r}" if error_text else "")
        ) from e

    try:
        page.wait_for_url(re.compile(r"fastscout\.fastmodelsports\.com"), timeout=timeout_ms)
    except Exception as e:
        error_text = _page_error_text()
        raise RuntimeError(
            "FastScout login did not redirect back to fastscout.fastmodelsports.com after submitting "
            f"credentials (still at url={page.url}): {type(e).__name__}: {e}"
            + (f" -- page showed: {error_text!r}" if error_text else "")
            + " -- this usually means the username/password was rejected (wrong credentials, an MFA prompt, "
            "or a CAPTCHA), not a code bug."
        ) from e


def _goto_with_auth_retry(page, url, wait_selector, timeout_ms=30000):
    """Navigate to url and wait for wait_selector to appear. FastScout's auth-guard redirect to
    identity.hudl.com is ASYNC client-side JS -- observed to fire well AFTER "domcontentloaded" (and even
    "networkidle") have already been reached, so checking page.url immediately after goto() returns is
    unreliable and can miss it entirely (page.url still showed the ORIGINAL url right after goto(), yet
    ended up on identity.hudl.com by the time wait_for_selector's own timeout had elapsed). Instead, let
    wait_for_selector run its full course; if it fails AND we're on identity.hudl.com by then (checked AFTER
    that wait, when the async redirect has had time to actually happen), log in and retry once."""
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        page.wait_for_selector(wait_selector, timeout=timeout_ms)
        return
    except Exception:
        if "access_token=" in page.url:
            # A SILENT SSO re-auth (valid Hudl session cookies already present, so no interactive
            # email/password form was ever shown) can complete its ENTIRE identity.hudl.com -> callback ->
            # "#access_token=..." redirect dance WHILE this wait_for_selector call was already polling --
            # confirmed by a live run's own Playwright action log showing exactly that sequence happen
            # mid-wait. By the time it lands back on fastscout.fastmodelsports.com with the token in the URL
            # hash, most/all of the original timeout budget is already spent, leaving the SPA no time to
            # actually consume that token and render the page. This is NOT the "stuck needing interactive
            # login" case below (we're not on identity.hudl.com) -- just give it one more full timeout
            # window to finish rendering on its own instead of failing immediately.
            print(f"    [auth-retry] landed on an in-progress SSO callback ({page.url}) while waiting on {url} -- giving it a fresh wait instead of failing")
            page.wait_for_selector(wait_selector, timeout=timeout_ms)
            return
        if "identity.hudl.com" not in page.url:
            raise

    print(f"    [auth-retry] got redirected to identity.hudl.com while waiting on {url} -- logging in and retrying")
    login_to_fastscout(page, fastscout_username, fastscout_password, timeout_ms=timeout_ms)
    print(f"    [auth-retry] login_to_fastscout returned, now at {page.url} -- re-navigating to {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    print(f"    [auth-retry] re-navigated, now at {page.url} -- waiting for {wait_selector!r}")
    try:
        page.wait_for_selector(wait_selector, timeout=timeout_ms)
    except Exception:
        # This is the SECOND failure (after an already-completed login) -- dump whatever is actually
        # visible on screen, since a bare timeout gives no clue whether this is a stuck spinner, a repeat
        # MFA/consent prompt, or something else entirely looping back through the auth provider.
        try:
            visible_text = page.locator("body").inner_text(timeout=2000)[:800]
        except Exception as text_error:
            visible_text = f"<could not read body text: {type(text_error).__name__}: {text_error}>"
        print(
            f"    [auth-retry] STILL stuck after retry -- url={page.url}, title={page.title()!r}\n"
            f"    [auth-retry] visible body text (first 800 chars): {visible_text!r}"
        )
        raise


def _click_tab_by_text(page, label, timeout_ms=30000):
    """Click a nav tab/link by its exact visible text (case-insensitive) within the already-loaded FastScout
    SPA. Direct page.goto() to a sub-route URL (e.g. '/games', '/documents') gets silently redirected back to
    '/analytics/dashboard' -- FastScout only renders those views via client-side navigation (an in-app click
    on the corresponding nav tab), not a fresh full-page load. Confirmed by observation: navigating straight
    to '.../games?...' consistently lands on '.../analytics/dashboard' instead, showing the SAME efficiency
    panel regardless of which team's page was requested."""
    page.get_by_text(re.compile(rf"^{re.escape(label)}$", re.IGNORECASE)).first.click(timeout=timeout_ms)


def scrape_rendered_html(page, url, wait_selector="#myTeamSchedule", timeout_ms=30000, save_path=None):
    """Navigate to a FastScout team's base page, then click the 'SCHEDULE' nav tab to reach its schedule
    table client-side -- see _click_tab_by_text for why a direct URL to the schedule sub-route doesn't work.
    If save_path is given, caches the scraped HTML there (see _save_scraped_html) the same way scouting
    reports are cached."""
    print(f"    [scrape] navigating to {url}")
    try:
        _goto_with_auth_retry(page, url, "text=SCHEDULE", timeout_ms)
        print(f"    [scrape] landed on {page.url} -- clicking 'SCHEDULE' tab")
        _click_tab_by_text(page, "SCHEDULE", timeout_ms)
        page.wait_for_selector(wait_selector, timeout=timeout_ms)
        # The container can become visible before its rows finish an async data fetch triggered by the tab
        # click -- wait for an actual <tr> inside it too, not just the container itself.
        page.wait_for_selector(f"{wait_selector} tr", timeout=timeout_ms)
        # This page ALSO renders a second table just below the schedule -- the season player box-score
        # stats table (tables[1] in the next cell) -- which loads via its OWN separate async fetch that the
        # waits above don't cover at all (they only target #myTeamSchedule, i.e. tables[0]). Confirmed by a
        # live run: tables[0] came back fully populated but tables[1] had zero data rows -- same "captured
        # before the async widget finished loading" issue already seen with the ScoutBuilder boxscore Tile.
        # Each populated player row renders its name in a "<div data-id=\"...\">" cell (header cells use
        # col/label/statkey attributes instead, never data-id), so wait on that as a stable marker that this
        # second table has actually loaded before capturing the page.
        #
        # Confirmed by a live run: for 3 opponents this STILL timed out even though the selector resolved to
        # 30+ matching elements on every single poll (e.g. 32 for Aurora) -- Playwright just never considered
        # the first one "visible". That's the signature of a virtualized/lazy-rendered table (react-window
        # style): rows already exist in the DOM with real data (a data-id already set), but with a
        # collapsed/zero-size bounding box until actually scrolled into view -- the exact same lazy-render
        # behavior already confirmed for the ScoutBuilder boxscore Tile, which needed an explicit
        # scroll_into_view_if_needed() to force it to render. Scroll the stats table's own header row into
        # view first (its rows share the same "stat-table-row" class already seen on the header) to trigger
        # that, before waiting on its data cells.
        try:
            page.locator("tr.stat-table-row").first.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
    except Exception as e:
        raise RuntimeError(
            f"Could not reach the schedule view from {url} (actual url={page.url}, title={page.title()!r}): "
            f"{type(e).__name__}: {e}"
        ) from e

    # Confirmed by a live run: for EVERY opponent, this wait timed out even though the schedule table
    # ({wait_selector} and its <tr> rows, both awaited above) had already loaded successfully -- the
    # elements it found (e.g. 30 for Ripon, showing a player name like "Olin Zellmer") belong to a
    # DIFFERENT widget entirely (a roster/top-players panel elsewhere on the team page), not the schedule
    # table's own rows. This step only exists for the season player box-score STATS table (tables[1]),
    # which build_team_schedule_from_html (the only consumer of this function's result) never reads --
    # it only ever uses tables[0], the schedule table already confirmed loaded above. Making a failure here
    # non-fatal instead of raising means an opponent's schedule (already successfully captured) no longer
    # gets thrown away and replaced by a usually-nonexistent local backup file just because this unrelated,
    # unused-by-this-caller widget didn't finish loading.
    try:
        page.wait_for_selector("td div[data-id]", timeout=timeout_ms)
    except Exception as e:
        print(f"    [scrape] (non-fatal) second stats table never loaded, proceeding with schedule table only: {type(e).__name__}: {e}")
    print(f"    [scrape] landed on {page.url}")
    html = page.content()
    if save_path:
        # Same season-suffixed save as UW-Whitewater's own schedule above -- see _add_season_suffix_to_path.
        _save_scraped_html(html, _add_season_suffix_to_path(save_path, html), "scraped opponent schedule")
    return html


def _ensure_playwright_ready():
    """Import playwright.sync_api, installing the pip package and/or the Chromium browser binary first if
    either isn't already present. Both the scouting-report-PDF download step and the opponent-schedule
    scraping step below need this, so it's centralized here instead of duplicated in each."""
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "playwright"])
        from playwright.sync_api import sync_playwright

    # The "playwright" PIP PACKAGE and the actual Chromium BROWSER BINARY install separately, and can drift
    # out of sync after a fresh pip install, an environment rebuild, or a Playwright version bump -- that's
    # exactly what the "Looks like Playwright was just installed or updated -- please run playwright install"
    # message means. Running this every time is a fast no-op once the browser is already downloaded, so
    # there's no need to run it manually in a separate terminal.
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    return sync_playwright




def _ensure_fastscout_login(page, timeout_ms=30000):
    """Log into FastScout if not already authenticated. Uses a KNOWN, always-valid URL ("myTeam" is a
    literal alias FastScout resolves to whichever team the logged-in account belongs to) to reliably trigger
    Hudl's auth redirect, rather than navigating to an arbitrary opponent's page first and hoping the
    redirect behaves consistently.

    IMPORTANT: after a fresh login, FastScout always lands on
    ".../teams/myTeam/analytics/dashboard?league=...&season=..." regardless of what URL originally triggered
    it -- so callers must always explicitly (re-)navigate to wherever they actually want afterward. This
    function only guarantees the session is authenticated, not that the page is showing anything useful.

    Confirmed by the user hitting a "season=25 -> season=26" redirect on this exact "myTeam" URL: FastScout's
    "myTeam" alias appears to resolve to the ACCOUNT'S currently-active season, silently overriding whatever
    `season=` this URL requested once real-world time moves past that season (e.g. the 2025-26 season this
    notebook analyzes was already over by the time this ran). Not fatal by itself (login still succeeds),
    but risky: any view reached via "myTeam" AFTER this redirect -- e.g. scrape_uww_live_schedule's SCHEDULE
    tab click below -- could then silently show the WRONG season's data instead of raising an error. Log a
    loud, explicit warning whenever the landed season doesn't match FASTSCOUT_DOCS_SEASON, rather than
    letting that redirect pass by unnoticed in the ordinary "landed on {page.url}" print below.
    """
    known_url = f"https://fastscout.fastmodelsports.com/teams/myTeam/analytics/dashboard?league={FASTSCOUT_DOCS_LEAGUE}&season={FASTSCOUT_DOCS_SEASON}"
    print(f"    [login] navigating to {known_url}")
    _goto_with_auth_retry(page, known_url, "text=SCHEDULE", timeout_ms)
    print(f"    [login] confirmed logged in, landed on {page.url}")

    landed_season = parse_qs(urlparse(page.url).query).get("season", [None])[0]
    if landed_season is not None and landed_season != FASTSCOUT_DOCS_SEASON:
        print(
            f"    [login] WARNING: requested season={FASTSCOUT_DOCS_SEASON!r} but FastScout's \"myTeam\" "
            f"redirect landed on season={landed_season!r} instead -- this account's \"current\" season has "
            f"moved on. Any view reached via \"myTeam\" from here (e.g. the live schedule scrape below) may "
            f"now be showing season {landed_season} data instead of season {FASTSCOUT_DOCS_SEASON}. Verify "
            "the scraped schedule's games actually belong to the intended season before trusting this run's output."
        )

    # Diagnostic: persist this login's own LANDING page HTML too -- the "myTeam" analytics/dashboard view,
    # captured BEFORE any caller clicks away to another tab (e.g. scrape_uww_live_schedule's SCHEDULE click).
    # Confirmed by inspecting the already-saved SCHEDULE tab snapshot: the "Top Rebounders/Scorers/3PT/FT"
    # leaderboard tiles the user asked about do NOT appear there -- so if they exist anywhere on this account,
    # this dashboard landing page (nothing currently captures it) is the next most likely place. One-time save
    # per session bootstrap (this function only runs once per lazily-opened session -- see
    # run_in_fastscout_session) -- cheap, and gives a real snapshot to search instead of guessing selectors.
    try:
        _save_scraped_html(
            page.content(), os.path.join(schedules_dir, "myTeam - Analytics Dashboard.html"),
            "myTeam analytics dashboard (diagnostic)",
        )
    except Exception as dashboard_save_error:
        print(f"    [login] (non-fatal) could not save analytics/dashboard diagnostic snapshot: {type(dashboard_save_error).__name__}: {dashboard_save_error}")


def scrape_uww_live_schedule(page, timeout_ms=30000, save_path=None):
    """Scrape UW-Whitewater's own schedule table live from FastScout, instead of relying on a manually
    exported/uploaded schedule MHTML snapshot. Assumes the page is already on a loaded, authenticated team
    page (e.g. via _ensure_fastscout_login) -- just clicks the 'SCHEDULE' nav tab from there (see
    _click_tab_by_text for why a direct URL to this sub-route doesn't work). If save_path is given, caches
    the scraped HTML there (see _save_scraped_html) the same way scouting reports are cached."""
    print("    [scrape] clicking 'SCHEDULE' tab")
    _click_tab_by_text(page, "SCHEDULE", timeout_ms)
    page.wait_for_selector("#myTeamSchedule", timeout=timeout_ms)
    # The container can become visible before its rows finish an async data fetch triggered by the tab
    # click -- wait for an actual <tr> inside it too, not just the container itself.
    try:
        page.wait_for_selector("#myTeamSchedule tr", timeout=timeout_ms)
    except Exception as e:
        raise RuntimeError(
            f"'#myTeamSchedule' appeared but never got any <tr> rows within {timeout_ms}ms (url={page.url}): "
            f"{type(e).__name__}: {e}"
        ) from e
    print(f"    [scrape] landed on {page.url}")
    html = page.content()
    if save_path:
        # CONFIRMED CHANGE (requested): save with a "_<season start year>" suffix (e.g.
        # "..._2025.html") so a snapshot saved for one season never collides with, or gets mistaken
        # for, one saved for a different season under the exact same base filename.
        _save_scraped_html(html, _add_season_suffix_to_path(save_path, html), "UW-Whitewater's own scraped schedule")
    return html


# FastScout login lives behind Hudl's identity provider. Credentials are resolved from
# FASTSCOUT_USERNAME / FASTSCOUT_PASSWORD environment variables, optionally loaded from a local ".env"
# file (via python-dotenv) sitting next to this notebook. A ".env" file (git-ignored!) would look like:
#   FASTSCOUT_USERNAME=you@example.com
#   FASTSCOUT_PASSWORD=your-password
try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass

fastscout_username = os.environ.get("FASTSCOUT_USERNAME")
fastscout_password = os.environ.get("FASTSCOUT_PASSWORD")

if not (fastscout_username and fastscout_password):
    print(
        "No FastScout credentials found (checked FASTSCOUT_USERNAME/FASTSCOUT_PASSWORD env vars / .env) -- "
        "live scraping will be skipped and every opponent will fall back to its local backup MHTML."
    )

# Synergy Sports Tech (auth.synergysportstech.com) is a SEPARATE identity provider from FastScout/Hudl --
# confirmed by a live run that it does NOT share FastScout's username/password (login_to_synergy in the
# video-tagging helpers cell below submitted the FastScout credentials and got a real "Invalid username or
# password" back from Synergy's own server). Resolved the same way, from its own SYNERGY_USERNAME /
# SYNERGY_PASSWORD env vars / ".env" entries:
#   SYNERGY_USERNAME=you@example.com
#   SYNERGY_PASSWORD=your-synergy-password
synergy_username = os.environ.get("SYNERGY_USERNAME")
synergy_password = os.environ.get("SYNERGY_PASSWORD")

if not (synergy_username and synergy_password):
    print(
        "No Synergy credentials found (checked SYNERGY_USERNAME/SYNERGY_PASSWORD env vars / .env) -- "
        "live video-clip scraping will fail for any game not already cached locally."
    )


def find_backup_mhtml(opponent_name, schedules_dir):
    """Find a saved schedule snapshot for this opponent in schedules_dir, matched loosely by name -- either a
    genuine ".mhtml" export or this notebook's own live-scrape ".html" cache (see _save_scraped_html)."""
    for path in sorted(glob.glob(f"{schedules_dir}/*.mhtml") + glob.glob(f"{schedules_dir}/*.html")):
        base = re.sub(r"(_schedule(?:_\d{4})?\.(mhtml|html)$|\s*-\s*Schedule(?:_\d{4})?\.(mhtml|html)$)", "", os.path.basename(path), flags=re.IGNORECASE)
        if base.lower() in opponent_name.lower():
            return path
    return None


# --- One shared FastScout Playwright session, reused by every scraping step below AND by the live-scrape
# fallbacks in the opponent-pbp/video cells further down -- instead of each opening and closing its own
# browser+thread. Confirmed by the user hitting a Windows greenlet "MemoryError" inside Playwright's own
# dispatch loop after many independent open/close cycles accumulated across repeated cell re-runs in one
# long-lived kernel: this notebook previously opened up to 5 separate sessions per full run (UWW schedule,
# scout PDFs, opponent schedules, plus the 2 pbp/video live-scrape fallbacks) -- now just 1, opened lazily on
# first use and left open/reused for the rest of this kernel session (call close_fastscout_session() to
# explicitly tear it down early if needed; otherwise a kernel restart cleans it up).
_fastscout_session = {"executor": None, "playwright": None, "browser": None, "page": None}


def run_in_fastscout_session(fn):
    """Run fn(page) against the single shared, lazily-opened FastScout session. All Playwright sync-API calls
    for a given browser/page must run on the SAME thread that created them (a brand-new thread has no
    asyncio event loop of its own, sidestepping Playwright's sync API refusing to start on a thread that
    already has one -- see the historical comment this replaced, preserved in git history), so this always
    dispatches through one persistent ThreadPoolExecutor(max_workers=1) worker thread -- created once and
    reused for every call -- rather than a fresh executor + browser + login per call. The Windows
    WindowsProactorEventLoopPolicy swap (needed because Jupyter/ipykernel forces WindowsSelectorEventLoopPolicy
    process-wide, which breaks Playwright's Node-driver asyncio subprocess) only needs to happen once, at
    first-use bootstrap, and is restored immediately after -- not on every call."""
    def _bootstrap():
        original_policy = asyncio.get_event_loop_policy() if sys.platform == "win32" else None
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            sync_playwright = _ensure_playwright_ready()
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            _ensure_fastscout_login(page)
            _fastscout_session.update(playwright=playwright, browser=browser, page=page)
        finally:
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(original_policy)

    def _discard_stale_session():
        for key, closer in (("browser", "close"), ("playwright", "stop")):
            obj = _fastscout_session.get(key)
            if obj is not None:
                try:
                    getattr(obj, closer)()
                except Exception:
                    pass
        _fastscout_session.update(playwright=None, browser=None, page=None)

    def _job():
        if _fastscout_session["page"] is None:
            _bootstrap()
        # A single automatic retry wasn't always enough -- confirmed by the user hitting the SAME
        # "Page.goto: Connection closed while reading from the driver" error again right after a first
        # reopen-and-retry (a flaky Windows-side Playwright driver subprocess can take more than one restart
        # to recover). Retry up to MAX_DEAD_SESSION_RETRIES times, with a short pause before each fresh
        # bootstrap to let the OS fully release the previous browser/driver process first, instead of giving
        # up (or leaving the shared session permanently broken) after only one attempt.
        MAX_DEAD_SESSION_RETRIES = 2
        for attempt in range(MAX_DEAD_SESSION_RETRIES + 1):
            try:
                return fn(_fastscout_session["page"])
            except Exception as e:
                # The shared browser/driver can die BETWEEN calls (a crash, a timeout, or a Windows-side
                # Playwright driver subprocess issue) even though it was fine at bootstrap. There was
                # previously no liveness check at all, so once the underlying browser died, EVERY subsequent
                # call in this kernel session would keep failing the same way. Treat any exception
                # mentioning a dead connection/driver/target as that signal: discard the stale session and
                # retry against a freshly-bootstrapped one.
                msg = str(e).lower()
                is_dead_session = any(s in msg for s in ("connection closed", "target closed", "browser has been closed", "driver"))
                if is_dead_session and attempt < MAX_DEAD_SESSION_RETRIES:
                    print(f"    [session] Detected a dead FastScout browser session (attempt {attempt + 1}/{MAX_DEAD_SESSION_RETRIES}) -- reopening and retrying.")
                    _discard_stale_session()
                    time.sleep(2)
                    _bootstrap()
                    continue
                raise

    if _fastscout_session["executor"] is None:
        _fastscout_session["executor"] = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    return _fastscout_session["executor"].submit(_job).result()


def close_fastscout_session():
    """Explicitly tear down the shared session (browser + driver + worker thread) to reclaim resources
    without a full kernel restart. Not required between runs -- the session is left open and reused by
    default."""
    def _job():
        if _fastscout_session["browser"] is not None:
            _fastscout_session["browser"].close()
        if _fastscout_session["playwright"] is not None:
            _fastscout_session["playwright"].stop()
        _fastscout_session.update(playwright=None, browser=None, page=None)

    executor = _fastscout_session["executor"]
    if executor is not None:
        executor.submit(_job).result()
        executor.shutdown(wait=False)
        _fastscout_session["executor"] = None


# 1) UW-Whitewater's own schedule: try scraping it LIVE from FastScout first (via the "myTeam" alias, which
#    resolves to whichever team the logged-in account belongs to -- no need to know UWW's own team id), the
#    same live-scrape-with-MHTML-backup pattern already used for every opponent below. Falls back to the
#    local MHTML snapshot if no credentials are set or the live scrape fails for any reason.
uww_mhtml_path = next((p for p in schedule_mhtml_paths if "whitewater" in os.path.basename(p).lower()), None)

# CONFIRMED BUG (fixed here): FASTSCOUT_DOCS_SEASON was hardcoded to "25" (the 2025-26 season) in every
# live-scrape URL used to auto-download a missing scout report -- meaning the "Documents" page those
# URLs point to is ALWAYS the current season's, regardless of which season this run is actually
# processing. This is the real root cause behind two connected, real symptoms: before the game_date fix
# elsewhere in this cell, a WRONG (2025) game_date happened to coincidentally match SOMETHING on that
# same (2025) Documents page, so a scout report was downloaded and saved -- just the WRONG opponent's
# CURRENT-season report, mislabeled under the archived game's filename. After that fix, the CORRECT
# (2024) game_date can no longer match anything on a Documents page that only ever shows 2025-26, so
# nothing gets saved at all -- an honest failure instead of a silent wrong one, but still a failure.
# If a local schedule snapshot already exists for UWW, its own season (read the same way as everywhere
# else in this notebook -- see extract_season_start_year) is a far better guess than the hardcoded
# default, since it directly reflects the season this run is actually processing.
#
# IMPORTANT CAVEAT: this makes the live-scrape URL point at the RIGHT season, but it does NOT guarantee
# FastScout's live site actually serves a Documents listing for an archived past season at all -- that's
# a question about the external service's own data retention, which this notebook has no way to verify.
# If auto-download still finds nothing after this fix, the reliable path for a historical/archived
# season is to provide the scout report file directly in INPUT_DIR rather than rely on auto-download.
if uww_mhtml_path is not None:
    try:
        _fss_html = load_html_snapshot(uww_mhtml_path)
        _fss_year = extract_season_start_year(BeautifulSoup(_fss_html, "lxml"), fallback=None)
        if _fss_year is not None:
            FASTSCOUT_DOCS_SEASON = str(_fss_year)[-2:]
            print(f"Detected season {_fss_year} from UWW's local schedule snapshot -- using "
                  f"FASTSCOUT_DOCS_SEASON={FASTSCOUT_DOCS_SEASON!r} for any live-scrape URLs below "
                  f"(was hardcoded to '25').")
    except Exception as _fss_e:
        print(f"Could not read UWW's local schedule file to auto-detect FASTSCOUT_DOCS_SEASON "
              f"({type(_fss_e).__name__}: {_fss_e}) -- leaving it at the hardcoded default "
              f"({FASTSCOUT_DOCS_SEASON!r}).")
uww_html = None
if fastscout_username and fastscout_password:
    # Skip the live scrape entirely when a local schedule file already exists for UWW itself -- same
    # skip-check applied to every opponent below (see _run_fastscout_scrape_session's find_backup_mhtml
    # check), just using uww_mhtml_path (already resolved above via the same "whitewater" filename match)
    # instead of re-deriving it. Confirmed by the user: once a schedule has been captured once, there's no
    # need to pay for a fresh (slow, resource-heavy) live scrape on every subsequent run.
    if uww_mhtml_path is not None:
        print(f"Skipping live scrape for UW-Whitewater's own schedule -- a local schedule file already exists: {os.path.basename(uww_mhtml_path)}")
    else:
        try:
            _uww_save_path = os.path.join(schedules_dir, "UW-Whitewater - Schedule.html")
            uww_html = run_in_fastscout_session(lambda page: scrape_uww_live_schedule(page, save_path=_uww_save_path))
            print("Scraped UW-Whitewater's own schedule live from FastScout (teams/myTeam/games).")
        except Exception as e:
            print(f"Could not scrape UWW's own live schedule, falling back to local MHTML: {type(e).__name__}: {e}")

if uww_html is None and uww_mhtml_path is None:
    raise FileNotFoundError(
        f"No UW-Whitewater schedule MHTML found in {schedules_dir}, and live scraping was unavailable or failed."
    )

# 1b) Before building UWW's (scouted-games-only) schedule, proactively download any MISSING scouting-report
#     PDF straight from each opponent's own FastScout "documents" page, using the same authenticated session
#     -- rather than requiring these to be manually collected ahead of time. This has to run on the RAW
#     (unfiltered) schedule, since the whole point is to discover games that don't have a scout PDF locally
#     YET; build_team_schedule_from_html's own scouted-games filter can't include a game until AFTER this
#     step has filled in its missing report.
def parse_raw_schedule_rows(html):
    """Parse a team's own FastScout schedule page HTML into (date, parsed_date, opponent, location,
    opponent_url) rows, with NO scouted-games filtering applied -- unlike build_team_schedule_from_html,
    which only returns games that ALREADY have a matching scout PDF. Used solely to discover which games are
    missing a report so one can be downloaded before that filter runs for real."""
    page_soup = BeautifulSoup(html, "lxml")
    page_tables = page_soup.find_all("table")
    sched_raw = pd.read_html(StringIO(str(page_tables[0])))[0]

    # CONFIRMED BUG (fixed here): parsed_date below used to call parse_schedule_date(r["Date"]) with no
    # season_start_year override, silently falling back to _DEFAULT_SEASON_START_YEAR (2025) regardless
    # of which season this HTML actually is. build_team_schedule_from_html() already reads this page's
    # real season correctly (see extract_season_start_year()), but THIS function runs earlier -- it's
    # what discovers which games need a scout report downloaded in the first place -- and never got the
    # same fix applied. Confirmed as the root cause of a real, reported case: a 2024-25 game on 11/12/24
    # got its auto-downloaded scout report saved as "11_12_25 ..._scout.html" -- a full year off -- because
    # the date used to NAME that file came from this function's un-overridden parsed_date. Fixed the same
    # way as build_team_schedule_from_html: read this page's own season directly, from the same page_soup
    # already built two lines up.
    _season_start_year = extract_season_start_year(page_soup, fallback=_DEFAULT_SEASON_START_YEAR)

    row_els = [r for r in page_tables[0].find_all("tr") if r.find_all("td")]
    opponent_urls = []
    for row_el in row_els:
        hrefs = [a["href"] for a in row_el.find_all("a", href=True)]
        fastscout_team_links = [h for h in hrefs if "/teams/" in h and "identity.hudl.com" not in h]
        opponent_links = [h for h in fastscout_team_links if "/games/" not in h]
        opponent_urls.append(_resolve_team_link(opponent_links[0]) if opponent_links else None)
    sched_raw["opponent_url"] = opponent_urls

    rows = []
    for _, r in sched_raw.iterrows():
        opponent, _ = split_opponent(r["Opponent"])
        rows.append({
            "date": r["Date"],
            "parsed_date": parse_schedule_date(r["Date"], _season_start_year),
            "opponent": opponent,
            "location": r["Location"],
            "opponent_url": r["opponent_url"],
        })
    return pd.DataFrame(rows)


def _scout_pdf_already_exists(opponent, scout_files):
    opponent_key = opponent.split()[0].lower()
    return any(opponent_key in os.path.basename(p).lower() for p in scout_files)


def _find_matching_scout_document_row(docs_soup, game_date):
    """Within an opponent's FastScout '/documents' page HTML, find the <tr> whose 'Game Date' column matches
    game_date (comparing month/day only, since the visible text format varies). Returns (row_element,
    row_index_within_body_rows) on a match, or (None, seen_dates) with whatever date text WAS found, so a
    non-match can still be explained rather than just failing silently."""
    docs_table = docs_soup.find("table")
    if docs_table is None:
        raise RuntimeError("No <table> found on the documents page.")

    headers = [th.get_text(strip=True) for th in docs_table.find_all("th")]
    try:
        date_col_idx = next(i for i, h in enumerate(headers) if "game date" in h.lower())
    except StopIteration:
        raise RuntimeError(f"No 'Game Date' column found in the documents table headers: {headers}")

    body_rows = [r for r in docs_table.find_all("tr") if r.find_all("td")]
    seen_dates = []
    for row_idx, row_el in enumerate(body_rows):
        cells = row_el.find_all("td")
        if date_col_idx >= len(cells):
            continue
        cell_text = cells[date_col_idx].get_text(strip=True)
        seen_dates.append(cell_text)
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y", "%a, %b %d, %Y", "%a, %b %d"):
            try:
                parsed = datetime.strptime(cell_text, fmt)
            except ValueError:
                continue
            if parsed.month == game_date.month and parsed.day == game_date.day:
                return row_el, row_idx
    return None, seen_dates


def _download_matching_scout_pdf(page, docs_url, opponent, game_date, location, timeout_ms=30000):
    # docs_url's "/documents?..." deep link doesn't render directly via page.goto() (see _click_tab_by_text)
    # -- land on the opponent's own base team page first, then click through to their documents/scouts tab.
    opponent_base_url = docs_url.split("/documents")[0]
    try:
        _goto_with_auth_retry(page, opponent_base_url, "text=SCHEDULE", timeout_ms)
    except Exception as e:
        raise RuntimeError(
            f"Could not load {opponent}'s team page ({opponent_base_url}) (actual url={page.url}, "
            f"title={page.title()!r}): {type(e).__name__}: {e}"
        ) from e

    # Confirmed from saved snapshots: an opponent's tab pointing at this "/documents?..." URL is labeled
    # "SCOUTS" (MY OWN team's equivalent is "SELF SCOUTS") -- but the app ALSO has a global top-nav link
    # also labeled "SCOUTS" (pointing at a different library page), so a plain text match risks clicking the
    # wrong one. Click by href instead of by text to avoid that ambiguity -- but confirmed by an actual run
    # that an EXACT match against the absolute docs_url silently never matched (it landed on the global
    # "/library/opponents" page instead, meaning it fell through to the text-based fallback below and hit
    # the wrong "SCOUTS" link): a live SPA render authors this anchor's href ATTRIBUTE as a relative path
    # (e.g. "/teams/<id>/documents?..."), and browsers don't rewrite the raw attribute value to absolute --
    # only the resolved ".href" PROPERTY -- so an exact match against our absolute docs_url can never hit it.
    # Match on a *suffix* instead, which works whether this specific anchor's href happens to be authored as
    # relative or absolute.
    docs_path = docs_url.replace(FASTSCOUT_ORIGIN, "")
    try:
        page.locator(f'a[href$="{docs_path}"]').first.click(timeout=5000)
        clicked = True
    except Exception:
        clicked = False

    if not clicked:
        for label in ("SCOUTS", "SELF SCOUTS", "DOCUMENTS", "SCOUTING REPORTS"):
            try:
                _click_tab_by_text(page, label, timeout_ms=5000)
                break
            except Exception:
                continue
        else:
            try:
                visible_text = page.locator("body").inner_text(timeout=2000)[:800]
            except Exception:
                visible_text = "<could not read body text>"
            raise RuntimeError(
                f"Could not find a Documents/Scouts tab on {opponent}'s page (url={page.url}, "
                f"title={page.title()!r}) -- visible body text (first 800 chars): {visible_text!r}"
            )

    try:
        page.wait_for_selector("table", timeout=timeout_ms)
    except Exception as e:
        raise RuntimeError(
            f"No <table> appeared after clicking a Documents/Scouts tab for {opponent} (url={page.url}, "
            f"title={page.title()!r}): {type(e).__name__}: {e} -- this may mean no scouting reports exist "
            f"for {opponent} under league={FASTSCOUT_DOCS_LEAGUE!r} season={FASTSCOUT_DOCS_SEASON!r}."
        ) from e

    docs_soup = BeautifulSoup(page.content(), "lxml")
    try:
        matched_row_el, row_idx_or_seen_dates = _find_matching_scout_document_row(docs_soup, game_date)
    except Exception as e:
        # Surface the ACTUAL url/title Playwright ended up on, not just docs_url we asked for -- a table
        # with the wrong headers (e.g. a stats/efficiency panel instead of a documents list) usually means
        # the SPA redirected/rendered a different view than the one we navigated to, and the requested vs.
        # actual url diverging is the key signal for that.
        raise RuntimeError(
            f"Could not find a 'Game Date' column on {docs_url} (actual url={page.url}, title={page.title()!r}): "
            f"{type(e).__name__}: {e}"
        ) from e
    if matched_row_el is None:
        raise RuntimeError(
            f"No row matched game date {game_date.strftime('%b %d')} on {docs_url} -- 'Game Date' values "
            f"seen on the page: {row_idx_or_seen_dates}"
        )
    matched_row_idx = row_idx_or_seen_dates

    # Confirmed by the user: no PDF is needed at all -- auto-downloaded reports are saved as the live report
    # page's own rendered HTML instead (see below), so this filename ends in "_scout.html", not "_scout.pdf".
    matchup = f"{opponent} @ UW-Whitewater" if str(location).strip().lower() == "home" else f"UW-Whitewater @ {opponent}"
    filename = f"{game_date.month}_{game_date.day}_{game_date.strftime('%y')} {matchup}_scout.html"
    dest_path = os.path.join(schedules_dir, filename)

    # games_needing_scout_pdf was already filtered against scout_pdf_files (which now globs both "*_scout.pdf"
    # and "*_scout.html") up front, but that check is a fuzzy match on the OPPONENT'S first name-word against
    # ANY existing report filename -- it can't know the EXACT filename this specific game would produce until
    # game_date/matchup are resolved (both only available here, mid-function). Re-check the precise dest_path
    # too, as a second, exact line of defense, before doing any browser work at all.
    if os.path.exists(dest_path):
        print(f"  [{opponent}] scout report already exists in {schedules_dir} -- skipping download: {filename}")
        return dest_path

    # Prefer a direct <a href="...pdf"> link in the matched row -- fetch it with the browser context's own
    # authenticated cookies (page.context.request) rather than clicking through the UI.
    pdf_hrefs = [a["href"] for a in matched_row_el.find_all("a", href=True) if ".pdf" in a["href"].lower()]
    if pdf_hrefs:
        response = page.context.request.get(pdf_hrefs[0])
        if not response.ok:
            raise RuntimeError(f"GET {pdf_hrefs[0]} returned HTTP {response.status}")
        with open(dest_path, "wb") as f:
            f.write(response.body())
        return dest_path

    # No download button here after all (confirmed by the user) -- the team-name cell's edit icon carries
    # the report's numeric id directly, e.g. id="pencil-729471" -> https://fastscout.fastmodelsports.com/
    # report/729471. Extracting it from the already-parsed row avoids any ambiguous click target entirely.
    pencil_icon = matched_row_el.find(id=re.compile(r"^pencil-\d+$"))
    if pencil_icon is None:
        raise RuntimeError(
            f"Could not find a report id (an element with id='pencil-<id>') in the matched row for "
            f"{opponent} (url={page.url})."
        )
    report_id = pencil_icon["id"].split("-", 1)[1]
    # Confirmed the boxscore widget still stays empty no matter how long we wait, scroll it into view, or add
    # the SAME "?league=...&season=..." query params every other FastScout URL in this notebook carries --
    # none of that fixed it when reaching the report via a fresh page.goto() (a hard full-page load). That
    # matches the EXACT pattern _click_tab_by_text already documented for other sub-routes in this app: a
    # hard page load doesn't carry over whatever client-side app/router state a normal in-app navigation
    # would leave in place, and this SPA only fully renders some views when reached via an actual in-app
    # click. report_url is kept only for the direct-PDF-response check right below (a raw HTTP fetch, not a
    # page navigation, so it's unaffected either way) -- the actual navigation into the report happens further
    # down by CLICKING the pencil icon in the still-live documents-list page instead of goto()'ing this URL.
    report_url = f"{FASTSCOUT_ORIGIN}/report/{report_id}?league={FASTSCOUT_DOCS_LEAGUE}&season={FASTSCOUT_DOCS_SEASON}"

    response = page.context.request.get(report_url)
    if not response.ok:
        raise RuntimeError(f"GET {report_url} returned HTTP {response.status}")
    content_type = response.headers.get("content-type", "")
    if "pdf" in content_type.lower():
        with open(dest_path, "wb") as f:
            f.write(response.body())
        return dest_path

    # Not a direct PDF response -- the report renders as an HTML page instead, with the SAME information a
    # manually-exported PDF would have. Rather than writing a parallel HTML-parsing path, render the
    # currently-loaded page straight to a real PDF file via headless Chromium's native print engine
    # (page.pdf() always uses "print" media -- and the report's own CSS already has "hidden-print" classes
    # on UI chrome like the edit icon, so this should closely match what a real "Print"/"Export" action
    # would produce). The saved file then flows through the EXACT SAME PDF-parsing pipeline
    # (read_boxscore_table, extract_pdf_season_stats, etc.) as any manually-provided scout PDF.
    try:
        # CLICK into the report from the live documents-list page (still open in `page` from the matching
        # step above) instead of page.goto()'ing report_url -- see the comment where report_url is built for
        # why a hard full-page load leaves the boxscore widget permanently empty. This is an in-app
        # client-side navigation, exactly like a real user opening the report would trigger.
        #
        # Confirmed from a saved snapshot's own markup: the pencil <i> icon itself has NO click handler --
        # its ancestor <tr class="... scout-row cursor-pointer ..."> is the real click target (the whole row
        # is clickable; "cursor-pointer" on the row, not the icon, is the tell). A prior attempt clicked the
        # icon directly (even with force=True) and it silently did nothing -- no exception, but page.url
        # never changed, so the code went on to save the STILL-open documents-list page as the "report" HTML
        # (confirmed by the user opening the saved file and finding the reports LIST, not an actual report).
        # Click the containing row instead, and explicitly VERIFY the navigation actually happened afterward
        # -- silently saving the wrong page if it doesn't is exactly the bug just described, so this must
        # raise loudly rather than let that repeat.
        row_locator = page.locator(f"tr:has(#pencil-{report_id})").first
        try:
            row_locator.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        row_locator.click(timeout=timeout_ms)
        try:
            page.wait_for_url(re.compile(r"/report/\d+"), timeout=timeout_ms)
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        if "/report/" not in page.url:
            raise RuntimeError(
                f"Clicking the documents-list row for report {report_id} did not navigate into the report "
                f"(still at url={page.url}, title={page.title()!r}) -- refusing to save this page, since it "
                f"would silently be the wrong content (the documents list itself, not the report)."
            )

        # Confirmed by the user: no PDF is needed at all -- every attempt at reproducing a clean PDF via
        # Chromium's print pipeline (headless page.pdf() under default/print media, forcing window.print(),
        # manual CSS/JS hacks under screen media, clicking the real "#print" icon in a headed browser) failed
        # in a different way each time (blank body, leftover chrome frame, broken layout, or a blocking native
        # OS dialog Playwright can't dismiss). Save the live report's own rendered HTML directly instead --
        # parse_scout_html_elements() (Cell 8) reconstructs the same element schema straight from this DOM,
        # which is actually MORE reliable than pdfplumber's text-clustering heuristics on a printed PDF.
        #
        # The season boxscore ("Tile boxscore") specifically is populated by an async API call after the
        # initial page shell loads -- confirmed empty in a "Save Page As" MHTML snapshot for exactly that
        # reason. Wait for its actual text content to appear (there's no <table> tag anywhere in this app at
        # all, so the earlier "wait_for_selector('table')" calls above never actually caught anything real)
        # before saving.
        # Confirmed by a real live download: waiting (even 30s) without ever SCROLLING to the boxscore's
        # page did NOT populate it -- it stayed completely empty. This report renders across 5 separate
        # print-style "pages" (react-grid-layout items), with the boxscore on the LAST one -- a very common
        # pattern for this kind of layout is to lazy-load/virtualize off-screen pages and only fetch a
        # widget's data once it's actually scrolled into view (e.g. via IntersectionObserver). Explicitly
        # scroll the boxscore tile into view first to trigger that, before waiting for its content.
        try:
            page.locator(".Tile.boxscore").scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass

        # Confirmed fixed once (a real downloaded report showed real boxscore content) but NOT reliable --
        # a later 6-opponent run had this populate for only 1 of 6. Root cause: waiting for ".fa-spin" to
        # clear (below) is an ABSENCE-of-loading inference, not a positive content check -- if the scroll
        # above fires before whatever actually triggers the boxscore's async fetch (a race condition, since
        # this is a one-shot scroll immediately followed by polling), there's simply no spinner to see in the
        # first place, so that loop finds 0 spinners on its very FIRST check and declares victory even though
        # the boxscore table is still completely empty -- confirmed exactly by that run (5 of 6 opponents
        # saved with an empty boxscore, no exception, no spinner ever observed). Wait for an ACTUAL populated
        # row in the boxscore table itself instead, retrying the scroll a few times in case an earlier
        # attempt didn't land while the fetch was still in flight.
        boxscore_loaded = False
        for _scroll_attempt in range(5):
            try:
                page.wait_for_selector(".Tile.boxscore table tbody tr", timeout=6000)
                boxscore_loaded = True
                break
            except Exception:
                try:
                    page.locator(".Tile.boxscore").scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass
        if not boxscore_loaded:
            print(f"    [{opponent}] boxscore table never populated after retrying the scroll {5} times -- saving anyway (season-stat cells relying on it will be incomplete).")

        # The 4 playerStatTable tiles (Top Rebounders/Scorers/3PT/FT Shooters) each load via their OWN
        # independent async call too -- confirmed one ("Top Rebounders") was still showing its loading
        # spinner (a "<i class=\"fa fa-refresh fa-spin\">" icon, with an empty <tbody>) even after the
        # boxscore had already finished. Poll for ANY ".fa-spin" element left anywhere on the page as a
        # secondary check covering all of them at once (this absence-of-loading signal is fine here since the
        # boxscore's OWN readiness is now verified by positive content above, not inferred from this alone).
        for _attempt in range(10):
            _spinner_count = page.evaluate("document.querySelectorAll('.fa-spin').length")
            if _spinner_count == 0:
                break
            page.wait_for_timeout(3000)
        else:
            print(f"    [{opponent}] {_spinner_count} loading spinner(s) still visible after 30s -- saving anyway (some stat tiles may be incomplete).")

        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception as e:
        raise RuntimeError(
            f"GET {report_url} was not a PDF (content-type={content_type!r}), and saving its rendered HTML "
            f"also failed (url={page.url}, title={page.title()!r}): {type(e).__name__}: {e}"
        ) from e
    return dest_path


raw_uww_games = parse_raw_schedule_rows(uww_html if uww_html is not None else load_html_snapshot(uww_mhtml_path))

# Only games already played (parsed_date < reference_date) need a report for retrospective scouting, PLUS
# the single NEXT upcoming game (closest parsed_date >= reference_date) for pre-game prep -- not every game
# still remaining on the schedule after that. Mirrors the same "Upcoming" selection build_team_schedule_from_html
# uses for the primary team, computed independently here since this runs on the unfiltered raw schedule.
valid_dates = raw_uww_games.loc[raw_uww_games["parsed_date"].notna(), "parsed_date"]
upcoming_dates = valid_dates[valid_dates >= reference_date]
next_upcoming_date = upcoming_dates.min() if not upcoming_dates.empty else None


def _is_past_or_next_upcoming(d):
    if d is None:
        return False
    if d < reference_date:
        return True
    return next_upcoming_date is not None and d == next_upcoming_date


in_scope_mask = raw_uww_games["parsed_date"].apply(_is_past_or_next_upcoming)
n_future_excluded = (raw_uww_games["parsed_date"].notna() & ~in_scope_mask & (raw_uww_games["parsed_date"] >= reference_date)).sum()
if n_future_excluded:
    print(f"Excluding {n_future_excluded} game(s) scheduled beyond the next upcoming game -- not downloading those reports yet.")

# before_scout="yes" means "run as if the upcoming opponent's report doesn't exist". find_scout_files()
# already filters that report out of scout_pdf_files -- but that alone would make the upcoming game look
# MISSING to the check below and trigger a fresh download of the very report being ignored (re-creating it
# on disk, where the next re-glob would pick it back up). Drop the upcoming game from the download scope too.
if _before_scout_enabled and next_upcoming_date is not None:
    in_scope_mask = in_scope_mask & (raw_uww_games["parsed_date"] != next_upcoming_date)
    print(f"[before_scout=yes] Not downloading a scouting report for the upcoming "
          f"{next_upcoming_date:%m/%d/%y} game.")

games_needing_scout_pdf = raw_uww_games[
    raw_uww_games["opponent_url"].notna()
    & raw_uww_games["parsed_date"].notna()
    & in_scope_mask
    & ~raw_uww_games["opponent"].apply(lambda o: _scout_pdf_already_exists(o, scout_pdf_files))
]

if not fastscout_username or not fastscout_password:
    if not games_needing_scout_pdf.empty:
        print(
            f"\n{len(games_needing_scout_pdf)} game(s) are missing a local '*_scout.pdf' report and could be "
            "downloaded automatically from FastScout, but no FASTSCOUT_USERNAME/FASTSCOUT_PASSWORD were "
            "found -- skipping."
        )
elif raw_uww_games.empty:
    print("\nNo games were found in UWW's raw schedule at all (live scrape or MHTML) -- nothing to download.")
elif games_needing_scout_pdf.empty:
    n_missing_url = raw_uww_games["opponent_url"].isna().sum()
    n_missing_date = raw_uww_games["parsed_date"].isna().sum()
    print(
        f"\nEvery game already has a local scouting-report PDF, or is missing required data -- nothing to "
        f"download from FastScout. ({len(raw_uww_games)} raw game(s) found; {n_missing_url} missing "
        f"opponent_url, {n_missing_date} missing a parseable date.)"
    )
else:
    print(f"\nDownloading {len(games_needing_scout_pdf)} missing scouting-report PDF(s) from FastScout:")

    def _download_scout_pdfs(login_page):
        downloaded = {}
        for _, game_row in games_needing_scout_pdf.iterrows():
            opponent, opponent_url = game_row["opponent"], game_row["opponent_url"]
            game_date, location = game_row["parsed_date"], game_row["location"]
            # opponent_url already carries its own "?league=...&season=..." query string (e.g.
            # ".../teams/<id>?league=NCAAB-III&season=25"), so naively appending
            # "/documents?league=...&season=..." after it lands "/documents" INSIDE that first
            # query string instead of as a real path segment, producing a malformed URL. Strip
            # any existing query string before appending the documents path.
            opponent_base_url = opponent_url.split("?")[0].rstrip("/")
            docs_url = f"{opponent_base_url}/documents?league={FASTSCOUT_DOCS_LEAGUE}&season={FASTSCOUT_DOCS_SEASON}"
            try:
                saved_path = _download_matching_scout_pdf(login_page, docs_url, opponent, game_date, location)
                downloaded[opponent] = saved_path
                print(f"  [{opponent}] saved {os.path.basename(saved_path)}")
            except Exception as doc_error:
                print(f"  [{opponent}] could not download scouting report: {type(doc_error).__name__}: {doc_error}")
        return downloaded

    try:
        run_in_fastscout_session(_download_scout_pdfs)
    except Exception as download_session_error:
        print(
            "  Could not start an authenticated FastScout session for PDF downloads: "
            f"{type(download_session_error).__name__}: {download_session_error}"
        )
        traceback.print_exc()

    # Re-glob so build_team_schedule_from_html's scouted-games filter (right below) picks up whatever PDF(s)
    # were just downloaded.
    # Confirmed by the user: no PDF is needed at all -- scouting reports auto-downloaded from FastScout are now
# saved as "*_scout.html" (the live report page's own rendered DOM) instead of trying to reproduce a PDF via
# Chromium's print pipeline, which never worked reliably across headless/headed and every print-media
# variation tried. Manually-uploaded reports stay as "*_scout.pdf" (from before this change) -- glob both so
# either format counts as "this opponent already has a report".
# Routed through find_scout_files() (Configuration cell) so the `before_scout` switch is honoured here:
# with before_scout="yes" the upcoming game's own report is left out of this list entirely, which in turn
# keeps it out of scouted_opponents_for() / _scout_pdf_already_exists() below.
scout_pdf_files = find_scout_files(volume_dir)

if uww_html is not None:
    uww_team_schedule, soup, tables = build_team_schedule_from_html(uww_html, source_label="scraped live (myTeam)")
else:
    uww_team_schedule, soup, tables = build_team_schedule(uww_mhtml_path)
# The next cell (season player box-score stats) expects "soup"/"tables" for UWW specifically.
team_schedules = [uww_team_schedule]

# UWW's own real season, as a single reusable value -- every row of uww_team_schedule carries the same
# "season" (it all comes from ONE schedule snapshot, which represents one team's one season), so rather
# than thread a per-row season through every later call site that needs to re-parse one of UWW's own
# dates (the upcoming matchup date, a specific game's date when checking for a local PBP/video file,
# etc.), compute it ONCE here and reuse it everywhere below instead of the single-season assumption
# those call sites used to rely on implicitly.
# Reads the first NON-NULL "season" value rather than a bare .iloc[0] -- defensive on top of the
# allowlist fix a few lines up, rather than relying on that being the only thing standing between this
# and the same crash: any future column-nulling logic added above that forgets "season" the same way
# fails safely into the fallback below instead of crashing here again.
_uww_season_values = uww_team_schedule["season"].dropna() if "season" in uww_team_schedule.columns else pd.Series(dtype=object)
try:
    uww_season_start_year = int(str(_uww_season_values.iloc[0]).split("-")[0]) if not _uww_season_values.empty else _DEFAULT_SEASON_START_YEAR
except (ValueError, IndexError):
    uww_season_start_year = _DEFAULT_SEASON_START_YEAR
# Exposed at module level (not just inside build_team_schedule_from_html's local scope) since a later cell
# (identifying the upcoming opponent's own prior-game tendencies) also needs UWW's scouted-opponent list. The
# original notebook cell references a bare "scouted_opponents" name that was never actually assigned at module
# level either -- another pre-existing gap in the source notebook, filled in here the same way as
# opponent_from_scout_filename() above.
scouted_opponents = scouted_opponents_for(uww_team_schedule["team"].iloc[0], scout_pdf_files) if not uww_team_schedule.empty else []

# 2) For every opponent that shows up in UWW's own (scouted, date-capped) schedule, scrape their live
#    FastScout team page via opponent_url -- falling back to a local " - Schedule.mhtml" backup on failure.
opponents = (
    uww_team_schedule[["opponent", "opponent_url"]]
    .dropna(subset=["opponent_url"])
    .drop_duplicates(subset=["opponent_url"])
)
print(f"\nFetching {len(opponents)} opponent schedule(s) (scrape opponent_url, MHTML backup on failure):")

scraped_html_by_opponent = {}
if fastscout_username and fastscout_password and opponents.empty:
    print(
        f"  No opponents with a resolvable opponent_url were found in {os.path.abspath(schedules_dir)} -- "
        "skipping the authenticated FastScout session entirely (every opponent will fall back to its local "
        "backup MHTML instead, if one exists). uww_team_schedule likely ended up empty because it's filtered "
        "down to only SCOUTED games, and that filter comes from '*_scout.pdf' files found in INPUT_DIR -- if "
        "none are found there, every game gets filtered out. Double check that INPUT_DIR (the absolute path "
        "above) actually contains all the '*_scout.pdf' scouting-report files alongside the schedule "
        "MHTMLs, not just the schedule MHTMLs themselves."
    )

if fastscout_username and fastscout_password and not opponents.empty:
    def _run_fastscout_scrape_session(login_page):
        # See run_in_fastscout_session above for why this needs to run inside a dedicated worker thread
        # with a temporarily-swapped WindowsProactorEventLoopPolicy on Windows.
        session_results = {}
        for _, opp_row in opponents.iterrows():
            opponent_name, opponent_url = opp_row["opponent"], opp_row["opponent_url"]
            # Skip the live scrape entirely when a local schedule file already exists for this opponent --
            # either a genuine manually-uploaded ".mhtml" export OR this notebook's own live-scrape ".html"
            # cache from a PRIOR run (find_backup_mhtml matches both). Confirmed by the user: once a
            # schedule has been captured once, there's no need to pay for a fresh (slow, resource-heavy)
            # live scrape on every subsequent run. This only skips the ATTEMPT -- the fallback loop below
            # still loads that same file via find_backup_mhtml, so the resulting team_schedules entry is
            # unchanged either way.
            if find_backup_mhtml(opponent_name, schedules_dir):
                print(f"  Skipping live scrape for {opponent_name} -- a local schedule file already exists.")
                continue
            try:
                opp_save_path = os.path.join(schedules_dir, f"{opponent_name} - Schedule.html")
                session_results[opponent_name] = scrape_rendered_html(login_page, opponent_url, save_path=opp_save_path)
            except Exception as scrape_error:
                print(f"  Could not scrape {opponent_name} ({opponent_url}): {type(scrape_error).__name__}: {scrape_error}")
        return session_results

    try:
        scraped_html_by_opponent = run_in_fastscout_session(_run_fastscout_scrape_session)
    except Exception as session_error:
        print(f"  Could not start an authenticated FastScout browser session: {type(session_error).__name__}: {session_error}")
        traceback.print_exc()

for _, opp_row in opponents.iterrows():
    opponent_name, opponent_url = opp_row["opponent"], opp_row["opponent_url"]
    opponent_html = scraped_html_by_opponent.get(opponent_name)
    if opponent_html:
        opp_schedule, _, _ = build_team_schedule_from_html(opponent_html, source_label="scraped live")
        team_schedules.append(opp_schedule)
        continue

    backup_path = find_backup_mhtml(opponent_name, schedules_dir)
    if backup_path:
        print(f"  Falling back to local backup MHTML for {opponent_name}: {os.path.basename(backup_path)}")
        opp_schedule, _, _ = build_team_schedule(backup_path)
        team_schedules.append(opp_schedule)
    else:
        print(f"  No backup MHTML found for {opponent_name} either -- skipping this opponent.")

schedule = pd.concat(team_schedules, ignore_index=True) if team_schedules else pd.DataFrame()
print(schedule)
