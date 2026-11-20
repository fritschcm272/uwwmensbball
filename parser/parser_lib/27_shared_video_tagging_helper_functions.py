# 27_shared_video_tagging_helper_functions.py -- code for the notebook section "Shared video-tagging helper functions, hoisted here so cell run-order doesn't matter -----"
# Runs inside the notebook via run_section("27_shared_video_tagging_helper_functions"); its settings are in that notebook cell.

# --- Shared video-tagging helper functions, hoisted here so cell run-order doesn't matter -------------------
# Self-contained imports -- this cell is meant to work regardless of run order (see title above), so it
# shouldn't rely on another cell (e.g. the Configuration cell) having already run and left these in the
# global namespace. Confirmed by a live run: this cell raised "NameError: name 're' is not defined" during a
# fresh top-to-bottom run of the whole notebook.
import os
import re
import time
from io import StringIO

import pandas as pd
from bs4 import BeautifulSoup

# ---- cache files that survive a full disk (shared helper; the same copy is in every section that uses them) ---------
# CONFIRMED BUG (fixed; "Jersey-number recognizer skipped: EOFError: Ran out of input", and tracking's "jersey numbers not
# read this run (EOFError ...)"): a run that filled the disk left a cache file empty / cut short, and loading it stopped the
# section. A damaged cache is now set aside as "<name>.broken" (it's rebuilt), and caches are written to a temporary file
# first and swapped in only when complete, so a full disk can no longer leave a half-written cache behind.
def _safe_read_pickle(path, default=None):
    try:
        return pd.read_pickle(path)
    except Exception as _e:
        try:
            if os.path.isfile(path):
                os.replace(path, path + ".broken")
        except Exception:
            pass
        print(f"  [cache] {os.path.basename(str(path))} was damaged ({type(_e).__name__}) -- set aside as .broken and "
              f"rebuilt (a disk that filled up mid-save does this)", flush=True)
        return {} if default is None else default


def _safe_read_latest(paths, default=None):
    """The newest readable file of several (e.g. detections_*.pkl), newest first; damaged ones are set aside."""
    for p_ in sorted(paths, key=lambda q: os.path.getmtime(q) if os.path.exists(q) else 0, reverse=True):
        d_ = _safe_read_pickle(p_, default=False)
        if d_ is not False:
            return d_
    return {} if default is None else default


def _safe_to_pickle(obj, path):
    if not isinstance(path, (str, bytes, os.PathLike)):
        return pd.to_pickle(obj, path)                    # an in-memory buffer
    root, ext = os.path.splitext(str(path))
    tmp = f"{root}.tmp{ext}"
    try:
        pd.to_pickle(obj, tmp)
    except OSError as _e:
        try:
            os.remove(tmp)
        except Exception:
            pass
        print(f"  [cache] {os.path.basename(str(path))} NOT saved ({type(_e).__name__}: {_e}) -- free disk space; the "
              f"previous copy is kept", flush=True)
        return
    # CONFIRMED BUG (fixed; "PermissionError: [WinError 5] Access is denied: ...jersey_numbers.tmp.pkl -> jersey_numbers.pkl"):
    # on Windows, OneDrive or antivirus holds a file open for a moment while it syncs / scans it, and swapping the new copy in
    # fails then. It's retried for a few seconds; if the file stays locked, it's written in place instead.
    import time as _sp_time
    for _try in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            _sp_time.sleep(0.25 * (_try + 1))
        except OSError:
            break
    try:
        pd.to_pickle(obj, path)
    except OSError as _e:
        print(f"  [cache] {os.path.basename(str(path))} NOT saved -- the file is locked by another program (OneDrive sync or "
              f"antivirus?) ({type(_e).__name__}); the previous copy is kept and it's saved again on the next save", flush=True)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass



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
    parsed_tables = []
    for t in soup.find_all("table"):
        try:
            parsed_tables.append(pd.read_html(StringIO(str(t)))[0])
        except Exception:
            continue                          # an empty / layout table
    # The file also contains a saved "Edit"/playlist metadata table with no "Description" column -- skip it.
    # CONFIRMED BUG (fixed; scrimmage-opponent run: StopIteration in the video-tagging cell). A _video file with NO clip
    # table at all -- a page saved before it finished loading, a login page, or an empty playlist -- crashed the whole run.
    # It now gives an empty clip list (with the usual columns); the caller reports which file it was.
    clips = next((t for t in parsed_tables if "Description" in t.columns), None)
    if clips is None:
        return pd.DataFrame(columns=["No.", "Result", "Description", "player", "Team", "Duration"])
    clips = clips.copy()
    clips["player"] = clips["Player"].astype(str).str.strip()
    return clips[["No.", "Result", "Description", "player", "Team", "Duration"]]


def parse_video_mhtml(path):
    return parse_video_mhtml_html(load_html_snapshot(path))


def clips_from_synergy_export(game_date, players=None, _cache={}):
    """One game's clip log from the SYNERGY EDITOR EXPORT, in the same shape parse_video_mhtml() returns
    ("No.", "Result", "Description", "player", "Team", "Duration") -- so it can go through the same alignment.
    CONFIRMED BUG (fixed; Corey: "Do you believe that he is really a Primary Ball Handler?"). The cells that attach
    clip descriptions onto pbp_events read saved "<game>_video.html" pages. Since the move to Synergy Editor exports
    nobody saves those any more, so the 11/17 run printed "Found 0 video-tagging file(s)" and "pbp_events rows with a
    matched video description: 0 of 946" -- every consumer of video_description (offensive roles in 41b, the
    opponent's own tendencies in 29, the weak-spot diagnosis in 31) was running on nothing for the whole season.
    The export holds the same Synergy strings, one row per clip, already in clip order: inputs/uww_clip_frames.csv
    (every captured game, description + player + result per clip), or inputs/uww_plays.csv (the raw Export.csv
    columns) for a game that only got that far. Returns an empty frame when the game has neither."""
    import os as _os
    cols = ["No.", "Result", "Description", "player", "Team", "Duration"]
    want = pd.to_datetime(game_date, errors="coerce")
    if pd.isna(want):
        return pd.DataFrame(columns=cols)
    want = want.date()
    # CONFIRMED BUG (fixed before it shipped; 2026-11-07 has THREE exported games -- Elmhurst@Ripon, Franklin@Hope and
    # UWWhitewater@Carroll -- so the date alone returned all 581 clips at once, and each game's clip numbers start at 1
    # again, which breaks the order-preserving alignment). The caller passes the players in the game's play-by-play;
    # only their clips are kept, which picks out the one game.
    _pl = {str(x).strip().casefold() for x in (players or []) if isinstance(x, str) and str(x).strip()}
    key = (str(want), tuple(sorted(_pl)))
    if key in _cache:
        return _cache[key]
    base = str(globals().get("INPUT_DIR") or "./inputs")
    out = pd.DataFrame(columns=cols)
    for fn, c_no, c_res, c_desc, c_pl, c_team, c_date in (
            ("uww_clip_frames.csv", "position", "result", "description", "player", "team", "clip_date"),
            ("uww_plays.csv", "#", "Result", "Synergy String", "Player", "Team", "Date")):
        try:
            df = pd.read_csv(_os.path.join(base, fn), low_memory=False)
        except Exception:
            continue
        if not {c_no, c_res, c_desc, c_pl, c_date} <= set(df.columns):
            continue
        d = pd.to_datetime(df[c_date], errors="coerce").dt.date
        g = df[(d == want) & df[c_desc].notna() & df[c_pl].notna()]
        if _pl:
            g = g[g[c_pl].astype(str).str.strip().str.casefold().isin(_pl)]
        if g.empty:
            continue
        out = pd.DataFrame({
            "No.": pd.to_numeric(g[c_no], errors="coerce"),
            "Result": g[c_res].astype(str).str.strip(),
            "Description": g[c_desc].astype(str),
            "player": g[c_pl].astype(str).str.strip(),
            "Team": g[c_team].astype(str) if c_team in g.columns else "",
            "Duration": "",
        }).dropna(subset=["No."]).sort_values("No.").reset_index(drop=True)
        break
    _cache[key] = out
    return out


def login_to_synergy(page, username, password, timeout_ms=30000):
    """Log into Synergy Sports Tech's own identity provider (auth.synergysportstech.com) -- a separate login
    from FastScout/Hudl with its OWN credentials (see synergy_username/synergy_password in the
    schedule-scraping cell above; confirmed NOT the same as FastScout's). Selectors are best-effort guesses
    at a single-page username+password form; errors include the actual url/visible-error-text to help
    correct them if needed.
    """
    def _page_error_text():
        # CONFIRMED CHANGE (11/19): the three original selectors found nothing on three days of failed
        # logins, so the error line said only "did not leave the login page" -- true but useless. ASP.NET
        # Identity renders its rejection in a validation summary, which matches none of them.
        for sel in [".validation-summary-errors", ".field-validation-error", ".text-danger",
                    "[class*='error' i]", "[class*='alert' i]", "[role='alert']"]:
            try:
                text = page.locator(sel).first.inner_text(timeout=1000)
                if text and text.strip():
                    return text.strip()
            except Exception:
                continue
        return None

    # CONFIRMED BUG (fixed 11/19, same hour it was introduced). The first run with two-factor handling sent
    # Corey "a ton of codes" and ended at Synergy's own wall: "Too many two-factor authentication attempts.
    # Please try again in 60 minutes." Two faults, and the second is what made it a flood:
    #   1. The success test was `"/Account/Login" not in page.url`. The two-factor form lives at a DIFFERENT
    #      /Account/ URL, so the moment the submit moved there this function declared victory and returned.
    #      The caller then found 0 games (not actually signed in) and tried again -- ten times, each one
    #      emailing a fresh code and abandoning it.
    #   2. Nothing read the page's own error, so the lockout was invisible and the retries kept coming.
    # Now: the code field is looked for BEFORE any success test, success means leaving the identity provider
    # entirely, and a lockout stops every further attempt -- in this process and in the next run, through
    # _synergy_lockout.txt -- rather than feeding the counter that caused it.
    _lock_path = os.path.join(schedules_dir, "_synergy_lockout.txt")

    def _locked_until():
        _t = float(globals().get("_SYNERGY_LOGIN_BLOCKED_UNTIL") or 0)
        try:
            if os.path.exists(_lock_path):
                _t = max(_t, float(open(_lock_path, encoding="utf-8").read().strip() or 0))
        except Exception:
            pass
        return _t

    def _mark_locked(why, seconds=3600):
        _until = time.time() + seconds
        globals()["_SYNERGY_LOGIN_BLOCKED_UNTIL"] = _until
        try:
            open(_lock_path, "w", encoding="utf-8").write(str(_until))
        except Exception:
            pass
        raise RuntimeError(
            f"Synergy has locked this account out of two-factor: {why!r}. No further sign-in will be "
            f"attempted for 60 minutes (delete {_lock_path} to override). Every attempt while locked out "
            f"emails another code and restarts their clock.")

    _until = _locked_until()
    if time.time() < _until:
        raise RuntimeError(
            f"Synergy two-factor is locked out for about {int((_until - time.time()) / 60) + 1} more "
            f"minute(s) -- not signing in, so the lockout can expire (see {_lock_path}).")

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

    # CONFIRMED CHANGE (11/19): tick "Remember My Login" before submitting. Without it Synergy issues no
    # device token at all, so even a browser profile that survives between runs is challenged for an emailed
    # code every single time. Harmless where the box isn't there.
    try:
        _remember = page.locator('input[type="checkbox"][name="RememberLogin"], '
                                 'input[type="checkbox"][id*="remember" i]').first
        if _remember.count() and not _remember.is_checked():
            _remember.check(timeout=5000)
    except Exception:
        pass

    try:
        page.get_by_role("button", name=re.compile(r"^(log ?in|sign ?in|continue|submit)$", re.IGNORECASE)).first.click(timeout=timeout_ms)
    except Exception as e:
        error_text = _page_error_text()
        raise RuntimeError(
            f"Synergy login failed clicking the submit button (url={page.url}): {type(e).__name__}: {e}"
            + (f" -- page showed: {error_text!r}" if error_text else "")
        ) from e

    # CONFIRMED CHANGE (11/19): Synergy now emails a six-digit code ("Two Factor Authentication ... We sent a
    # security code by email"). That form POSTS BACK TO THE SAME URL, so the old wait_for_url could only sit
    # there until it timed out -- which is exactly what every run since 11/17 did. Wait for EITHER outcome:
    # the page leaving the login URL, or the code field appearing. The code is read from
    # SYNERGY_MFA_CODE if the notebook set one, otherwise from inputs/_synergy_code.txt, which can be
    # written while the run waits. A file rather than input(): this runs on the Playwright worker thread,
    # where reading the notebook's stdin is not reliable.
    # CONFIRMED BUG (fixed 11/19, third pass). The first version of this list wrote the attribute matches
    # with CSS Level 4's case-insensitivity flag -- input[name="Code" i] -- which Playwright's own selector
    # parser rejects. The whole comma-joined locator was therefore unusable, .count() raised every time, and
    # a bare "except: return None" turned that into "no code field here" sixty times in a row while
    # /Account/VerifyCode sat on screen with id="Code" name="Code" plainly in its markup. Two lessons, both
    # paid for: no `i` flag in a selector, and never swallow a selector error silently. The selectors are now
    # tried ONE AT A TIME, so a bad one cannot blind the others, and the first failure of each is printed.
    _CODE_SELS = ('input#Code', 'input[name="Code"]', 'input[autocomplete="one-time-code"]',
                  'input[inputmode="numeric"]', 'input[name*="TwoFactor"]', 'input[name*="VerifyCode"]',
                  'input[name*="OtpCode"]', 'input[name*="VerificationCode"]')
    _bad_sel = set()

    def _code_field():
        for _sel in _CODE_SELS:
            try:
                f_ = page.locator(_sel).first
                if f_.count() and f_.is_visible():
                    return f_
            except Exception as _se:
                if _sel not in _bad_sel:
                    _bad_sel.add(_sel)
                    print(f"    [synergy-login] the selector {_sel!r} is unusable "
                          f"({type(_se).__name__}: {_se}) -- skipping it", flush=True)
        return None

    def _mfa_code():
        """The emailed code: a value the notebook set, else inputs/_synergy_code.txt, waited for."""
        _g = str(globals().get("SYNERGY_MFA_CODE") or "").strip()
        if _g:
            globals()["SYNERGY_MFA_CODE"] = ""      # one code, one use
            return _g
        _path = os.path.join(schedules_dir, "_synergy_code.txt")
        if not os.path.exists(_path):               # "there is no file yet for me to put it in" -- make one
            try:
                open(_path, "w", encoding="utf-8").close()
            except Exception:
                pass
        _wait_s = int(globals().get("SYNERGY_MFA_WAIT_S", 300))
        _how_long = f"{_wait_s // 60} min" if _wait_s >= 60 else f"{_wait_s} sec"
        print(f"  [synergy-login] Synergy emailed a security code. Put it in {_path} (just the digits) "
              f"and save -- waiting up to {_how_long}.", flush=True)
        _end = time.time() + _wait_s
        while time.time() < _end:
            try:
                if os.path.exists(_path):
                    _txt = re.sub(r"\D", "", open(_path, encoding="utf-8", errors="replace").read())
                    if len(_txt) >= 4:
                        try:
                            os.replace(_path, _path + ".used")   # never reuse a stale code
                        except Exception:
                            pass
                        return _txt
            except Exception:
                pass
            time.sleep(3)
        return ""

    def _on_identity_provider():
        try:
            _u = page.url
        except Exception:
            return True
        return ("auth.synergysportstech.com" in _u) or ("/Account/" in _u)

    page.wait_for_timeout(1000)                     # let the response render before reading it
    _err0 = _page_error_text()
    if _err0 and re.search(r"(?i)too many|locked|try again in", _err0):
        _mark_locked(_err0)

    _deadline = time.time() + timeout_ms / 1000.0
    _twofa = None
    while time.time() < _deadline:
        _twofa = _code_field()                      # BEFORE the success test: the code page is not success
        if _twofa is not None:
            break
        if not _on_identity_provider():
            return
        page.wait_for_timeout(500)

    if _twofa is not None:
        _code = _mfa_code()
        if not _code:
            raise RuntimeError(
                "Synergy asked for the security code it emailed, and none arrived: set SYNERGY_MFA_CODE in "
                f"the notebook, or write the digits into {os.path.join(schedules_dir, '_synergy_code.txt')} "
                "while the run waits.")
        _twofa.fill(_code)
        try:
            page.get_by_role("button", name=re.compile(r"^(log ?in|sign ?in|verify|submit|continue)$",
                                                       re.IGNORECASE)).first.click(timeout=timeout_ms)
        except Exception:
            _twofa.press("Enter")
        try:
            page.wait_for_url(lambda url: "auth.synergysportstech.com" not in url and "/Account/" not in url,
                              timeout=timeout_ms)
            print("  [synergy-login] signed in with the emailed code; this profile should be remembered "
                  "next time.", flush=True)
            return
        except Exception as e:
            _why = _page_error_text()
            if _why and re.search(r"(?i)too many|locked|try again in", _why):
                _mark_locked(_why)
            raise RuntimeError(
                f"Synergy did not accept the security code (still at url={page.url}): {type(e).__name__}: {e}"
                + (f" -- page showed: {_why!r}" if _why else "")) from e

    try:
        page.wait_for_url(lambda url: "auth.synergysportstech.com" not in url and "/Account/" not in url,
                          timeout=5000)
    except Exception as e:
        # CONFIRMED CHANGE (11/19): the diagnostic above is the PRISTINE page, saved before anything is
        # typed, so it can never show why a submit was refused -- and every run since 11/17 has failed here
        # with no reason attached. Save the page AS IT STANDS AFTER THE SUBMIT too, and say in the error
        # itself what the form looks like now: whether a one-time-code field has appeared (MFA, which this
        # automation cannot answer), and whether the DeviceHash the page expects its own script to fill is
        # still empty (an unrecognised device, which is what triggers MFA). Those three facts separate a
        # wrong password from a blocked device without another day of guessing.
        error_text = _page_error_text()
        _clues = []
        try:
            _after = page.content()
            _save_scraped_html(_after, os.path.join(schedules_dir, "Synergy - Login Page (after submit).html"),
                               "Synergy login page after the submit (diagnostic)")
            if re.search(r"(?i)name=.(?:Code|OtpCode|TwoFactorCode|VerificationCode)", _after):
                _clues.append("a one-time-code field is now on the page (MFA) -- this login cannot answer it")
            _dh = re.search(r"(?i)<input[^>]*DeviceHash[^>]*>", _after)
            if _dh and not re.search(r"(?i)value=.[^\"']", _dh.group(0)):
                _clues.append("DeviceHash is still empty (the page's own script never filled it)")
        except Exception:
            pass
        raise RuntimeError(
            f"Synergy login did not leave the login page after submitting credentials (still at "
            f"url={page.url}): {type(e).__name__}: {e}" + (f" -- page showed: {error_text!r}" if error_text else "")
            + ("" if not _clues else " -- " + "; ".join(_clues))
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

    clips = parse_video_mhtml_html(html)
    # CONFIRMED BUG (fixed): a page saved before its clip table had filled in became a _video file with no clips, which
    # then counted as "already have this game's video" on every later run. Only a page WITH clips is saved; an empty
    # one raises, so it's logged as a failed scrape and tried again later.
    if clips.empty:
        raise RuntimeError("the clip page loaded but had no clip table (not finished loading, or no clips tagged yet)")
    if save_path:
        _save_scraped_html(html, save_path, "scraped video-tagging clips")
    return clips


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
            _VIDEO_PARSED_MEMO.update(_safe_read_pickle(cache_path))
        except Exception:
            pass  # a damaged cache just means re-parsing
    key = os.path.abspath(path)
    hit = _VIDEO_PARSED_MEMO.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1].copy()
    clips = parse_video_mhtml(path)
    _VIDEO_PARSED_MEMO[key] = (stamp, clips)
    try:
        _safe_to_pickle(dict(_VIDEO_PARSED_MEMO), cache_path)
    except Exception:
        pass
    return clips.copy()
