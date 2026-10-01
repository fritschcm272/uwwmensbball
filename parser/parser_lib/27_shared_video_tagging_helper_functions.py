# 27_shared_video_tagging_helper_functions.py -- code for the notebook section "Shared video-tagging helper functions, hoisted here so cell run-order doesn't matter -----"
# Runs inside the notebook via run_section("27_shared_video_tagging_helper_functions"); its settings are in that notebook cell.

# --- Shared video-tagging helper functions, hoisted here so cell run-order doesn't matter -------------------
# Self-contained imports -- this cell is meant to work regardless of run order (see title above), so it
# shouldn't rely on another cell (e.g. the Configuration cell) having already run and left these in the
# global namespace. Confirmed by a live run: this cell raised "NameError: name 're' is not defined" during a
# fresh top-to-bottom run of the whole notebook.
import os
import re
from io import StringIO

import pandas as pd
from bs4 import BeautifulSoup

RESULT_TO_KEY = {
    "Make 2 Pts": "made_shot", "Make 3 Pts": "made_shot",
    "Miss 2 Pts": "missed_shot", "Miss 3 Pts": "missed_shot",
    "Turnover": "turnover",
    "Free Throw": "free_throw",
    "Foul": "foul", "Non Shooting Foul": "foul",
}



def expand_clip_to_subevents(row):
    """One video clip can represent more than one real pbp event (an \"And-1\" makes a shot + a free throw) --
    return a list of event_type sub-events (made_shot/missed_shot/turnover/free_throw) for this clip, in the
    order they happened."""
    if row["Result"] in RESULT_TO_KEY:
        return [RESULT_TO_KEY[row["Result"]]]
    if row["Result"] in ("1 Pts", "0 Pts"):
        events = ["made_shot"] if AND1_SHOT_RE.search(row["Description"]) else []
        events.append("free_throw")
        return events
    return []


def global_align(n, m, compatible, pos_cost):
    """pbp side has n items (indices 0..n-1, already sorted by event_order), video side has m items (indices
    0..m-1, already sorted by video_clip_number). Returns {pbp_index: video_index} for the order-preserving
    pairing that maximizes total match count (a huge fixed bonus per match dominates the DP), using summed
    `pos_cost` only as a tiebreaker among otherwise-equally-good maximal alignments."""
    BIG_BONUS = 1000.0
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    choice = [[0] * (m + 1) for _ in range(n + 1)]  # 0=matched (diagonal), 1=skip pbp item, 2=skip video item
    for i in range(1, n + 1):
        choice[i][0] = 1
    for j in range(1, m + 1):
        choice[0][j] = 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best, best_choice = score[i - 1][j], 1
            if score[i][j - 1] > best:
                best, best_choice = score[i][j - 1], 2
            if compatible(i - 1, j - 1):
                diag = score[i - 1][j - 1] + BIG_BONUS - pos_cost(i - 1, j - 1)
                if diag >= best:  # ties prefer matching over skipping
                    best, best_choice = diag, 0
            score[i][j], choice[i][j] = best, best_choice

    pairs = {}
    i, j = n, m
    while i > 0 and j > 0:
        c = choice[i][j]
        if c == 0:
            pairs[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif c == 1:
            i -= 1
        else:
            j -= 1
    return pairs


def parse_video_mhtml_html(html):
    """Core clip-table parsing logic, factored out of parse_video_mhtml() so it can run on HTML from either
    source: a manually-exported/uploaded MHTML snapshot, OR a live Playwright page.content() capture --
    confirmed by the user: a game's own "video_url" (already available per-game via team_schedules/
    opp_schedule -- see the schedule-scraping cell and the opponent-schedule cell above) renders this EXACT
    same clip-tagging table when opened, so a live scrape of that URL is a drop-in replacement for the
    manual "_video.mhtml" export/upload step. See scrape_video_clips_live() below for the live-scrape path.
    """
    soup = BeautifulSoup(html, "lxml")
    parsed_tables = [pd.read_html(StringIO(str(t)))[0] for t in soup.find_all("table")]
    # The file also contains a saved "Edit"/playlist metadata table with no "Description" column -- skip it.
    clips = next(t for t in parsed_tables if "Description" in t.columns)
    clips = clips.copy()
    clips["player"] = clips["Player"].astype(str).str.strip()
    return clips[["No.", "Result", "Description", "player", "Team", "Duration"]]


def parse_video_mhtml(path):
    return parse_video_mhtml_html(load_html_snapshot(path))


def login_to_synergy(page, username, password, timeout_ms=30000):
    """Log into Synergy Sports Tech's own identity provider (auth.synergysportstech.com) -- a separate login
    from FastScout/Hudl with its OWN credentials (see synergy_username/synergy_password in the
    schedule-scraping cell above; confirmed NOT the same as FastScout's). Selectors are best-effort guesses
    at a single-page username+password form; errors include the actual url/visible-error-text to help
    correct them if needed.
    """
    def _page_error_text():
        for sel in ["[class*='error' i]", "[class*='alert' i]", "[role='alert']"]:
            try:
                text = page.locator(sel).first.inner_text(timeout=1000)
                if text and text.strip():
                    return text.strip()
            except Exception:
                continue
        return None

    # Diagnostic: save the pristine login page HTML so its real form markup can be inspected directly if a
    # selector below turns out to be wrong, instead of guessing blindly from a bare timeout.
    try:
        _save_scraped_html(
            page.content(), os.path.join(schedules_dir, "Synergy - Login Page (diagnostic).html"),
            "Synergy login page (diagnostic)",
        )
    except Exception:
        pass

    try:
        username_input = page.locator(
            'input[type="email"], input[name="Username"], input[name="username"], input[id*="username" i], '
            'input[id*="email" i]'
        ).first
        username_input.wait_for(timeout=timeout_ms)
        # Log which field actually got matched (name/id/type only -- never the credential value itself) so a
        # wrong-field match is distinguishable from a genuine server-side credential rejection.
        print(f"    [synergy-login] username field matched: name={username_input.get_attribute('name')!r} id={username_input.get_attribute('id')!r} type={username_input.get_attribute('type')!r}")
        username_input.fill(username)
    except Exception as e:
        error_text = _page_error_text()
        raise RuntimeError(
            f"Synergy login failed finding the username field (url={page.url}): {type(e).__name__}: {e}"
            + (f" -- page showed: {error_text!r}" if error_text else "")
        ) from e

    try:
        password_input = page.locator('input[type="password"]').first
        password_input.wait_for(timeout=timeout_ms)
        print(f"    [synergy-login] password field matched: name={password_input.get_attribute('name')!r} id={password_input.get_attribute('id')!r}")
        password_input.fill(password)
    except Exception as e:
        error_text = _page_error_text()
        raise RuntimeError(
            f"Synergy login failed finding the password field (url={page.url}): {type(e).__name__}: {e}"
            + (f" -- page showed: {error_text!r}" if error_text else "")
        ) from e

    try:
        page.get_by_role("button", name=re.compile(r"^(log ?in|sign ?in|continue|submit)$", re.IGNORECASE)).first.click(timeout=timeout_ms)
    except Exception as e:
        error_text = _page_error_text()
        raise RuntimeError(
            f"Synergy login failed clicking the submit button (url={page.url}): {type(e).__name__}: {e}"
            + (f" -- page showed: {error_text!r}" if error_text else "")
        ) from e

    try:
        page.wait_for_url(lambda url: "/Account/Login" not in url, timeout=timeout_ms)
    except Exception as e:
        error_text = _page_error_text()
        raise RuntimeError(
            f"Synergy login did not leave the login page after submitting credentials (still at "
            f"url={page.url}): {type(e).__name__}: {e}" + (f" -- page showed: {error_text!r}" if error_text else "")
        ) from e


def scrape_video_clips_live(page, video_url, timeout_ms=30000, save_path=None):
    """Navigate to a game's own FastScout "video_url" (the Synergy-embedded clip-tagging player) and parse
    its rendered clip table -- a live-scrape replacement for a manually-exported "_video.mhtml" snapshot.
    Expects an already-authenticated FastScout Playwright `page`. If save_path is given, caches the scraped
    HTML there (see _save_scraped_html) so a future run can fall back to it via parse_video_mhtml instead of
    live-scraping again.

    Navigating here can redirect to Synergy's own login (auth.synergysportstech.com), a separate identity
    provider from FastScout/Hudl -- _attempt() detects that and logs in via login_to_synergy using Synergy's
    own synergy_username/synergy_password before retrying. Media-blocking (_attempt(block_media=True)/False)
    is a separate defensive measure against the video-editor SPA buffering full-game video in the background.
    """
    def _attempt(block_media):
        handler = None
        if block_media:
            def handler(route):
                req = route.request
                if req.resource_type == "media" or re.search(r"\.(mp4|m3u8|ts|webm|mov)(\?|$)", req.url, re.IGNORECASE):
                    route.abort()
                else:
                    route.continue_()
            page.route("**/*", handler)
        try:
            page.goto(video_url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_selector("table", timeout=timeout_ms)
            except Exception:
                if "auth.synergysportstech.com" not in page.url:
                    raise
                print(f"    [video] Redirected to Synergy's own login ({page.url}) -- logging in with Synergy's own credentials and retrying.")
                login_to_synergy(page, synergy_username, synergy_password, timeout_ms=timeout_ms)
                page.goto(video_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_selector("table", timeout=timeout_ms)
            return page.content()
        finally:
            if handler is not None:
                page.unroute("**/*", handler)

    try:
        html = _attempt(block_media=True)
    except Exception as block_error:
        # Only reached if the media-blocked attempt itself failed -- retry once, fully unblocked, rather than
        # let a media-blocking regression silently break every video-clip scrape. If the underlying browser/
        # driver is actually dead (the connection-closed case this function was written to avoid), this
        # unblocked retry will fail the same way and its exception still propagates up to
        # run_in_fastscout_session's own dead-session retry logic, same as before this fallback existed.
        print(f"    [video] Media-blocked scrape failed ({type(block_error).__name__}: {block_error}) -- retrying without blocking media.")
        html = _attempt(block_media=False)

    if save_path:
        _save_scraped_html(html, save_path, "scraped video-tagging clips")
    return parse_video_mhtml_html(html)


# ---- Speed-ups shared by both "Attach video-tagging clip descriptions" cells ---------------------------------
# CONFIRMED CHANGE (requested: the UWW attach cell "takes a really long time"). Two things were redone on every
# run even though nothing had changed:
#   1. A game whose clip page couldn't be scraped (no clips on the page yet, a page that never renders its
#      table, a login hiccup) was tried again EVERY run. Each try waits out the page timeouts twice (once with
#      video blocked, once without) -- about a minute per game, per run, for nothing. Failures are now logged
#      to <volume_dir>/_video_scrape_failures.csv and not retried for VIDEO_SCRAPE_RETRY_DAYS days.
#      Delete that file (or set the days to 0) to force a retry now.
#   2. Every saved _video file was re-parsed from its full HTML on every run -- twice in the UWW cell. Parsed
#      clip tables are now cached in <volume_dir>/_video_parsed_cache.pkl, keyed by file size + modified time,
#      so a file is parsed again only if it changes.


def _video_cache_dir():
    return globals().get("volume_dir") or globals().get("INPUT_DIR") or "."


def _video_scrape_failures():
    path = os.path.join(_video_cache_dir(), "_video_scrape_failures.csv")
    return (pd.read_csv(path) if os.path.exists(path)
            else pd.DataFrame(columns=["url", "label", "error", "failed_at"])), path


def video_scrape_recently_failed(url):
    """The logged failure for this clip page if it failed within VIDEO_SCRAPE_RETRY_DAYS, else None."""
    if not VIDEO_SCRAPE_RETRY_DAYS:
        return None
    log, _ = _video_scrape_failures()
    hit = log[log["url"] == url]
    if hit.empty:
        return None
    last = hit.iloc[-1]
    when = pd.to_datetime(last["failed_at"], errors="coerce")
    if pd.notna(when) and (pd.Timestamp.now() - when).days < VIDEO_SCRAPE_RETRY_DAYS:
        return last
    return None


def video_scrape_log(url, label, error=None):
    """error=None records a success (clears the page's failures); otherwise logs the failure."""
    log, path = _video_scrape_failures()
    log = log[log["url"] != url]
    if error is not None:
        log = pd.concat([log, pd.DataFrame([{"url": url, "label": label, "error": str(error)[:300],
                                             "failed_at": pd.Timestamp.now().isoformat(timespec="seconds")}])],
                        ignore_index=True)
    log.to_csv(path, index=False)


_VIDEO_PARSED_MEMO = {}


def parse_video_mhtml_cached(path):
    """parse_video_mhtml, but each file is parsed only once until it changes (size + modified time)."""
    st = os.stat(path)
    stamp = (st.st_size, int(st.st_mtime))
    cache_path = os.path.join(_video_cache_dir(), "_video_parsed_cache.pkl")
    if not _VIDEO_PARSED_MEMO and os.path.exists(cache_path):
        try:
            _VIDEO_PARSED_MEMO.update(pd.read_pickle(cache_path))
        except Exception:
            pass  # a damaged cache just means re-parsing
    key = os.path.abspath(path)
    hit = _VIDEO_PARSED_MEMO.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1].copy()
    clips = parse_video_mhtml(path)
    _VIDEO_PARSED_MEMO[key] = (stamp, clips)
    try:
        pd.to_pickle(dict(_VIDEO_PARSED_MEMO), cache_path)
    except Exception:
        pass
    return clips.copy()
