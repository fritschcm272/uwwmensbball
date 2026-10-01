# 46_frame_capture.py -- code for the notebook section "Frame capture: 5 frames per clip from the live Synergy player ----------------------------"
# Runs inside the notebook via run_section("46_frame_capture"); its settings are in that notebook cell.

# --- Frame capture: 5 frames per clip from the live Synergy player -------------------------------------------
# CONFIRMED CHANGE (requested): the Ollama vision model is gone. The user wants a model that LEARNS from the
# coaches' tagged Titles, so this cell now only CAPTURES frames; the "Tag model" cell after the play-calls cell
# turns them into numbers and trains on them together with the Synergy description and play-by-play context.
# (Ollama models can't learn from tags -- they only answer questions.)
#   1. Open each game's Synergy clip page in a real Edge/Chrome window (Playwright's bundled Chromium can't
#      decode H.264). FastScout login cookies are copied over; a Synergy login redirect is handled with
#      login_to_synergy(), same as scrape_video_clips_live(). The user confirmed the player video is not
#      copy-protected (video.mediaKeys === null, 1024 px wide).
#   2. For each playlist row: click it, pause, and seek to VISION_FRAMES_PER_CLIP evenly spaced points inside
#      the clip (its length comes from the row's Duration). Each frame is copied off the <video> element
#      through a canvas and saved as .jpg under _vision_frames/<date>_<game>/.
#   3. Frames already on disk are reused -- the clip isn't clicked or played again (requested).
#   4. One row per clip goes to INPUT_DIR/uww_clip_frames.csv: which clip it is (date, game, position, Synergy
#      description, player) and where its frames are. The play-calls cell joins that onto each clip.
# Runs only when RUN_FRAME_CAPTURE is True; otherwise the cell just loads uww_clip_frames.csv, so training works
# on any machine that has that file and the _vision_frames folder.
# (uww_clip_frames.csv from the Ollama test runs is no longer read -- safe to delete. Its frames are reused.)

import base64 as _vis_b64
import hashlib

# Tracking frames (requested: follow players through the clip and put names on them). A second, denser set of
# smaller frames, VISION_TRACK_FPS per second through the whole clip, used only by the player-tracking cell.
# Cost: ~10 s more per clip to capture (~35 min a game) and ~200 MB of .jpg per game. 0 = don't capture them.
# CONFIRMED CHANGE: 4 frames a second (was 2). Players move half as far between frames, so tracks are far less likely
# to drift between bunched-up teammates (review: one track held #32/#21/#11/#14 at a steal). Set before the recapture
# after the clip-start fix, since everything is recaptured anyway. Doubles tracking frames (~2x detection time).



# ---- 3. Frames out of the live player ----------------------------------------------------------------------
_VIS_JS_ARM = """async () => {
  const v = document.querySelector('sn-video-player video') || document.querySelector('video');
  if (!v) return null;
  // move the video FAR from anywhere the clicked clip could start (the other end of the game video), so that
  // clicking always makes Synergy jump -- even when the video already sits at that clip's start
  if (isFinite(v.duration) && v.duration > 10) {
    const far = v.currentTime < v.duration / 2 ? v.duration - 2 : 1;
    await new Promise(res => { const done = () => { v.removeEventListener('seeked', done); res(); };
                                v.addEventListener('seeked', done); v.currentTime = far; setTimeout(done, 4000); });
    v.pause();
  }
  const st = {before: v.currentTime, src: v.currentSrc, landed: null};
  window.__visSeek = st;
  window.__visEl = v;
  const onSeeked = () => { if (st.landed === null) st.landed = v.currentTime; };
  v.addEventListener('seeked', onSeeked);
  window.__visSeekOff = () => v.removeEventListener('seeked', onSeeked);
  return st.before;
}"""
_VIS_JS_WAIT = """async () => {
  // the clicked clip's start = where the video LANDS after Synergy jumps there. A jump is seen three ways:
  //   the 'seeked' event on the armed video element; the position itself moving (polled -- no event needed);
  //   or Synergy putting a NEW video element / source on the page once it has loaded.
  // Up to 8 s; "jumped" false = it never moved, and the caller retries / skips. "diag" says what was seen.
  const q = () => document.querySelector('sn-video-player video') || document.querySelector('video');
  let v = q();
  if (!v) return {error: 'no <video> element on the page'};
  const st = window.__visSeek || {before: NaN, src: v.currentSrc, landed: null};
  const armed = window.__visEl || v;
  let how = '';
  const t0 = Date.now();
  while (Date.now() - t0 < 8000) {
    v = q();
    if (v && v !== armed && v.readyState >= 2 && v.videoWidth) { st.landed = v.currentTime; how = 'new video element'; break; }
    if (v && v.currentSrc && v.currentSrc !== st.src && v.readyState >= 2 && v.videoWidth) { st.landed = v.currentTime; how = 'new source'; break; }
    if (st.landed !== null && Math.abs(st.landed - st.before) > 0.25 && v.readyState >= 2) { how = 'seeked event'; break; }
    if (v && !v.seeking && v.readyState >= 2 && Math.abs(v.currentTime - st.before) > 0.25) {
      st.landed = v.currentTime; how = 'position moved'; break; }
    await new Promise(r => setTimeout(r, 100));
  }
  if (window.__visSeekOff) window.__visSeekOff();
  const jumped = how !== '';
  await new Promise(r => setTimeout(r, 250));
  v = q();
  if (v) v.pause();
  const diag = `before=${Number(st.before).toFixed(1)} now=${v ? v.currentTime.toFixed(1) : 'none'} ` +
               `duration=${v ? v.duration : 'none'} ready=${v ? v.readyState : 'none'} ` +
               `same element=${v === armed} same source=${v ? v.currentSrc === st.src : 'none'}`;
  if (!v || v.readyState < 2) return {error: 'clip never loaded (' + diag + ')'};
  return {start: jumped ? st.landed : v.currentTime, jumped: jumped, how: how, diag: diag,
          duration: v.duration, w: v.videoWidth, h: v.videoHeight};
}"""
_VIS_JS_WAIT_OLD = """async () => {
  const v = document.querySelector('sn-video-player video') || document.querySelector('video');
  if (!v) return {error: 'no <video> element on the page'};
  const t0 = Date.now();
  while ((v.readyState < 2 || !v.videoWidth) && Date.now() - t0 < 20000) await new Promise(r => setTimeout(r, 150));
  if (v.readyState < 2) return {error: 'clip never loaded'};
  const s0 = v.currentTime;                                   // let the player land on the clip's in-point
  const t1 = Date.now();
  while (Math.abs(v.currentTime - s0) < 0.05 && !v.paused && Date.now() - t1 < 1500) await new Promise(r => setTimeout(r, 100));
  v.pause();
  return {start: v.currentTime, duration: v.duration, w: v.videoWidth, h: v.videoHeight};
}"""
_VIS_JS_GRAB = """async ({t, maxW, q}) => {
  const v = document.querySelector('sn-video-player video') || document.querySelector('video');
  await new Promise(res => { const done = () => { v.removeEventListener('seeked', done); res(); };
                              v.addEventListener('seeked', done); v.currentTime = t; setTimeout(done, 6000); });
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const sc = Math.min(1, maxW / v.videoWidth);
  const c = document.createElement('canvas');
  c.width = Math.round(v.videoWidth * sc); c.height = Math.round(v.videoHeight * sc);
  try { c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
        return {frame: c.toDataURL('image/jpeg', q || 0.8).split(',')[1]}; }
  catch (e) { return {error: 'canvas: ' + e.message}; }
}"""
_VIS_JS_ROWS = """() => [...document.querySelectorAll('table.video-playlist tr.playlist-item')].map((r, i) => {
  const cell = c => { const el = r.querySelector('td.cdk-column-' + c); return el ? el.innerText.trim() : null; };
  return {index: i, position: cell('position'), result: cell('result'), description: cell('description'),
          player: cell('player'), team: cell('team'), duration: cell('duration'), game: cell('game'), date: cell('date')};
})"""


def _vis_seconds(hms):
    try:
        parts = [float(x) for x in str(hms).split(":")]
        return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
    except Exception:
        return None


def _vision_track_count(clip_seconds):
    return int(min(VISION_TRACK_MAX_FRAMES, max(2, int((clip_seconds or 10.0) * VISION_TRACK_FPS) + 1)))


def _vision_capture(page, row_index, clip_seconds, mode="key"):
    """Click playlist row `row_index`, then pull frames from inside that clip. mode "key": the
    VISION_FRAMES_PER_CLIP evenly spaced frames the tag model uses. mode "track": VISION_TRACK_FPS frames per
    second through the whole clip, smaller, for the player-tracking cell."""
    row = page.locator("table.video-playlist tr.playlist-item").nth(row_index)
    row.scroll_into_view_if_needed(timeout=10000)
    info = {}
    for attempt in (1, 2):
        page.evaluate(_VIS_JS_ARM)                       # note where the video is; listen for Synergy's jump
        row.locator("td.cdk-column-description").click(timeout=10000)
        info = page.evaluate(_VIS_JS_WAIT)
        if info.get("error"):
            return [], info["error"]
        if info.get("jumped"):
            break
        page.wait_for_timeout(800)
    known = globals().setdefault("_vision_row_start", {})
    if info.get("jumped"):
        known[row_index] = float(info["start"])
    elif row_index in known:
        # CONFIRMED CHANGE (full-game run: 182 of 196 clips skipped). The tracking frames need a SECOND click on the same
        # clip right after its key frames; if that click doesn't make the video jump, the start confirmed moments ago
        # for this same clip is used (it's the same clip) instead of skipping it.
        info["start"], info["jumped"] = known[row_index], True
    if not info.get("jumped"):
        # never saw the video move to this clip: better no frames than the wrong play's frames
        n_fail = globals()["_vision_n_unconfirmed"] = globals().get("_vision_n_unconfirmed", 0) + 1
        if n_fail <= 3:
            print(f"    [capture] clip {row_index + 1}: start not confirmed -- {info.get('diag', '')}", flush=True)
        return [], ("clip start not confirmed (the video never moved to the clicked clip) -- retried next run; "
                    + str(info.get("diag", "")))
    length = clip_seconds or 10.0
    if info.get("duration") and info["duration"] == info["duration"]:  # finite, not NaN
        length = max(1.0, min(length, info["duration"] - info["start"]))
    if mode == "track":
        n = _vision_track_count(clip_seconds)
        times = [info["start"] + min(length, k / VISION_TRACK_FPS) for k in range(n)]
        max_w, q = VISION_TRACK_WIDTH, 0.7
    else:
        n = VISION_FRAMES_PER_CLIP
        times = [info["start"] + length * (0.5 if n == 1 else 0.05 + 0.9 * k / (n - 1)) for k in range(n)]
        max_w, q = VISION_FRAME_MAX_WIDTH, 0.8
    globals()["_vision_last_times"] = [round(float(t), 3) for t in times]   # full-game video seconds
    frames = []
    for t in times:
        got = page.evaluate(_VIS_JS_GRAB, {"t": t, "maxW": max_w, "q": q})
        if got.get("error"):
            # Canvas refused (cross-origin video): fall back to a screenshot of the <video> element itself.
            shot = page.locator("sn-video-player video").first.screenshot(type="jpeg", quality=int(q * 100))
            frames.append(_vis_b64.b64encode(shot).decode("ascii"))
        else:
            frames.append(got["frame"])
    return frames, None


def _vision_open(page, url, timeout_ms=45000):
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        page.wait_for_selector("table.video-playlist tr.playlist-item", timeout=timeout_ms)
    except Exception:
        if "auth.synergysportstech.com" not in page.url:
            raise
        login_to_synergy(page, synergy_username, synergy_password, timeout_ms=timeout_ms)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_selector("table.video-playlist tr.playlist-item", timeout=timeout_ms)


# Saved frames live in one folder per GAME, named from the clip row's own Date + Game cells (not the page
# label, which can differ between a schedule link and a hand-listed URL), and each file name carries a short
# fingerprint of the clip's Synergy description, so a reordered playlist can never hand a clip another clip's
# frames. Folder:  _vision_frames/Jan_2_2026_UWOshkosh@UWWhitewater/   File:  12_3f9a1c2e_1.jpg
# Saved frames live in one folder per GAME, named from the clip row's own Date + Game cells (not the page
# label, which can differ between a schedule link and a hand-listed URL), and each file name carries a short
# fingerprint of the clip's Synergy description, so a reordered playlist can never hand a clip another clip's
# frames. Folder:  _vision_frames/Jan_2_2026_UWOshkosh@UWWhitewater/   File:  12_3f9a1c2e_1.jpg
def _vision_frame_dir(row):
    return os.path.join(VISION_FRAMES_DIR, re.sub(r"[^\w@.-]+", "_", f"{row.get('date')} {row.get('game')}").strip("_"))


# CONFIRMED BUG (fixed; found by the coach: clip 1's frames showed clip 2's play). Synergy plays every clip from ONE
# full-game video that stays loaded, so the old "wait until the video is ready" passed instantly and the clip's start
# was read BEFORE Synergy jumped to the clicked clip -- often wherever the previous capture had left the video. Every
# frame captured that way may show the wrong play, so frames are versioned: VISION_CAPTURE_VERSION 2 = captured
# with the fixed start. New names -> everything is recaptured and everything built from frames starts clean; the
# old files stay on disk (the court calibration and the jersey answer key still use them).


def _vision_frame_name(row, k):
    fp = hashlib.md5(str(row.get("description") or "").strip().encode("utf-8")).hexdigest()[:8]
    v = f"_v{VISION_CAPTURE_VERSION}" if VISION_CAPTURE_VERSION >= 2 else ""
    return f"{row.get('position')}_{fp}{v}_{k + 1}.jpg"


def _vision_track_folder():
    base = "track" if int(VISION_TRACK_WIDTH) == 768 else f"track{int(VISION_TRACK_WIDTH)}"
    return base + (f"v{VISION_CAPTURE_VERSION}" if VISION_CAPTURE_VERSION >= 2 else "")


def _vision_track_name(row, k):
    fp = hashlib.md5(str(row.get("description") or "").strip().encode("utf-8")).hexdigest()[:8]
    return os.path.join(_vision_track_folder(), f"{row.get('position')}_{fp}_t{k:03d}.jpg")


def _vision_times_path(row):
    """Sidecar with each tracking frame's time in the FULL-GAME video (seconds): what lets possessions be linked
    to each other later (requested: go forward and backward through the Synergy details)."""
    fp = hashlib.md5(str(row.get("description") or "").strip().encode("utf-8")).hexdigest()[:8]
    return os.path.join(_vision_frame_dir(row), _vision_track_folder(), f"{row.get('position')}_{fp}_times.json")


def _vision_saved_track(row, clip_seconds):
    """Paths of this clip's tracking frames if they're all on disk already, else []."""
    paths = [os.path.join(_vision_frame_dir(row), _vision_track_name(row, k)) for k in range(_vision_track_count(clip_seconds))]
    return paths if all(os.path.exists(p) and os.path.getsize(p) > 0 for p in paths) else []


def _vision_saved_frames(label, row):
    """Paths of all VISION_FRAMES_PER_CLIP frames for this clip if they're already on disk, else []. Also finds
    frames from the first test runs, which were saved per page label as <position>_<n>.jpg."""
    n = VISION_FRAMES_PER_CLIP
    candidates = [[os.path.join(_vision_frame_dir(row), _vision_frame_name(row, k)) for k in range(n)]]
    if VISION_CAPTURE_VERSION < 2:
        candidates.append([os.path.join(VISION_FRAMES_DIR, re.sub(r"[^\w@.-]+", "_", label), f"{row.get('position')}_{k + 1}.jpg")
                           for k in range(n)])
    for paths in candidates:
        if all(os.path.exists(p) and os.path.getsize(p) > 0 for p in paths):
            return paths
    return []


def _vision_named_game():
    """VISION_ONLY_GAME -> (date, opponent words), or None. Same name format as the _pbp/_video files."""
    if not VISION_ONLY_GAME:
        return None
    m = re.match(r"^\s*(\d{1,2})_(\d{1,2})_(\d{2,4})\s+(.*)$", str(VISION_ONLY_GAME))
    if not m:
        raise ValueError(f"VISION_ONLY_GAME should look like '1_3_26 UW-Oshkosh Titans @ UW-Whitewater', "
                         f"got {VISION_ONLY_GAME!r}")
    year = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
    words = {w for w in re.split(r"[\s@\-]+", m.group(4).lower())
             if len(w) > 2 and w not in {"uww", "whitewater", "warhawks", "the"}}
    return pd.Timestamp(year, int(m.group(1)), int(m.group(2))), words


def _vision_row_in_named_game(row):
    """True unless VISION_ONLY_GAME is set and this playlist row is from a different game. Uses the row's own
    Game cell ("UWOshkosh@UWWhitewater") and Date cell ("Jan 2, 2026"), within a day of the named date."""
    named = _vision_named_game()
    if named is None:
        return True
    ndate, words = named
    game = re.sub(r"[^a-z@]", "", str(row.get("game") or "").lower())
    if not any(w in game for w in words):
        return False
    rdate = pd.to_datetime(row.get("date"), errors="coerce")
    return pd.isna(rdate) or abs((rdate.normalize() - ndate).days) <= 1


def _vision_rel(path):
    return os.path.relpath(path, VISION_FRAMES_DIR).replace(os.sep, "/")


def _vision_tag_pages(fastscout_page, sources, cache):
    """Runs on the Playwright worker thread (via run_in_fastscout_session). Opens ONE Edge/Chrome window,
    reuses it for every page, and returns the cache with new rows appended."""
    pw = _fastscout_session["playwright"]
    browser = pw.chromium.launch(channel=VISION_BROWSER_CHANNEL, headless=VISION_HEADLESS,
                                 args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"])
    try:
        ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
        try:
            ctx.add_cookies(fastscout_page.context.cookies())  # carry the FastScout login across
        except Exception:
            pass
        page = ctx.new_page()
        new_rows = []
        for label, url in sources:
            print(f"  [frames] {label}: opening clip page")
            try:
                _vision_open(page, url)
            except Exception as e:
                print(f"    could not open ({type(e).__name__}: {e}) -- skipped")
                continue
            rows = page.evaluate(_VIS_JS_ROWS)
            todo = [r for r in rows if not re.search(VISION_SKIP_DESCRIPTION, r["description"] or "")]
            # CONFIRMED BUG (fixed earlier): a page can hold more than one game, so with VISION_ONLY_GAME set every
            # row is checked against the named game by its OWN Game and Date cells, before VISION_TEST_CLIPS.
            _before = len(todo)
            todo = [r for r in todo if _vision_row_in_named_game(r)]
            if len(todo) < _before:
                print(f"    {_before - len(todo)} clip(s) on this page belong to other games -- skipped "
                      f"(VISION_ONLY_GAME = {VISION_ONLY_GAME!r})")
            if VISION_TEST_CLIPS:
                todo = todo[:VISION_TEST_CLIPS]
            print(f"    {len(rows)} clips on the page, capturing {len(todo)}")
            t_start, n_reused = time.time(), 0
            for n_done, r in enumerate(todo, 1):
                rec = {"source_label": label, "source_url": url, "position": r["position"],
                       "clip_game": r["game"], "clip_date": r["date"], "team": r["team"], "player": r["player"],
                       "result": r["result"], "description": r["description"],
                       "duration_s": _vis_seconds(r["duration"]), "test_run": bool(VISION_TEST_CLIPS),
                       "captured_at": pd.Timestamp.now().isoformat(timespec="seconds")}
                try:
                    paths = _vision_saved_frames(label, r)
                    if paths:
                        n_reused += 1
                    else:
                        frames, err = _vision_capture(page, r["index"], rec["duration_s"])
                        if err:
                            rec["error"] = err
                        fdir = _vision_frame_dir(r)
                        os.makedirs(fdir, exist_ok=True)
                        paths = []
                        for k, fb in enumerate(frames):
                            p = os.path.join(fdir, _vision_frame_name(r, k))
                            with open(p, "wb") as fh:
                                fh.write(_vis_b64.b64decode(fb))
                            paths.append(p)
                    rec["frames_captured"] = len(paths)
                    rec["frame_files"] = ";".join(_vision_rel(p) for p in paths)
                    if VISION_TRACK_FPS:
                        tpaths = _vision_saved_track(r, rec["duration_s"])
                        if not tpaths:
                            tframes, err = _vision_capture(page, r["index"], rec["duration_s"], mode="track")
                            if err:
                                rec["error"] = err
                            tdir = os.path.join(_vision_frame_dir(r), _vision_track_folder())
                            os.makedirs(tdir, exist_ok=True)
                            for k, fb in enumerate(tframes):
                                p = os.path.join(_vision_frame_dir(r), _vision_track_name(r, k))
                                with open(p, "wb") as fh:
                                    fh.write(_vis_b64.b64decode(fb))
                                tpaths.append(p)
                            with open(_vision_times_path(r), "w") as fh:
                                json.dump(globals().get("_vision_last_times", []), fh)
                        rec["track_files"] = ";".join(_vision_rel(p) for p in tpaths)
                        try:
                            with open(_vision_times_path(r)) as fh:
                                _tt = json.load(fh)
                            rec["track_times"] = ";".join(f"{x:.3f}" for x in _tt)
                            rec["video_start_s"] = round(float(_tt[0]), 3) if _tt else None
                        except Exception:
                            pass    # frames captured before times were saved
                except Exception as e:
                    rec["error"] = f"{type(e).__name__}: {e}"[:300]
                new_rows.append(rec)
                if n_done % 10 == 0 or n_done == len(todo):
                    per = (time.time() - t_start) / n_done
                    print(f"    {n_done}/{len(todo)} clips ({per:.0f}s/clip, ~{per * (len(todo) - n_done) / 60:.0f} "
                          f"min left; {n_reused} already had frames on disk)")
                    cache = pd.concat([cache, pd.DataFrame(new_rows, columns=VISION_COLS)], ignore_index=True)
                    new_rows = []
                    cache.to_csv(VISION_CACHE, index=False)
        return cache
    finally:
        browser.close()


# ---- Run (or just load) -------------------------------------------------------------------------------
clip_frames = (pd.read_csv(VISION_CACHE) if os.path.exists(VISION_CACHE)
               else pd.DataFrame(columns=VISION_COLS))
if RUN_FRAME_CAPTURE:
    # Every played game with a clip page: UWW's own games and the upcoming opponent's prior games,
    # plus any page listed by hand in VISION_PLAYLIST_URLS.
    _vis_sources = [(lab, url, pd.Timestamp.max) for lab, url in VISION_PLAYLIST_URLS]  # hand-listed go first
    for _sched_name in ("uww_team_schedule", "prev_games"):
        _sched = globals().get(_sched_name)
        if not isinstance(_sched, pd.DataFrame) or _sched.empty or "video_url" not in _sched.columns:
            continue
        for _, _g in _sched[_sched["video_url"].notna()].iterrows():
            _gd = _g.get("game_date")
            if _gd is None or pd.isna(_gd):
                try:
                    _gd = parse_schedule_date(_g["date"], uww_season_start_year)
                except Exception:
                    _gd = None
            if _gd is not None and pd.Timestamp(_gd) >= reference_date and not VISION_ONLY_GAME:
                continue  # not played yet as of reference_date (a named test game is allowed through)
            _vis_sources.append((f"{pd.Timestamp(_gd).date() if _gd is not None else ''} "
                                 f"{_g.get('opponent', '')}".strip(), _g["video_url"],
                                 pd.Timestamp(_gd) if _gd is not None else pd.Timestamp.min))
    # VISION_ONLY_GAME (requested: test on one named game). Matched by the date in the name (within a day:
    # Synergy's clip page dates the Oshkosh game Jan 2, the export and files say 1/3) AND the opponent's
    # name. Pages listed by hand in VISION_PLAYLIST_URLS are always kept.
    if VISION_ONLY_GAME:
        _odate, _owords = _vision_named_game()
        _hand = [x for x in _vis_sources if x[2] == pd.Timestamp.max]
        _match = sorted([x for x in _vis_sources if x[2] != pd.Timestamp.max
                         and abs((x[2] - _odate).days) <= 1 and any(w in x[0].lower() for w in _owords)],
                        key=lambda x: abs((x[2] - _odate).days))
        # ONE page only: a hand-listed page wins, else the closest-dated schedule match. (The same game can
        # sit in more than one schedule with different links; only one is needed.)
        _vis_sources = (_hand or _match)[:1]
        if not _vis_sources:
            print(f"Frame capture: no clip page found for {VISION_ONLY_GAME!r} in the schedules. Open the game "
                  f"in Synergy and add it by hand: VISION_PLAYLIST_URLS = [('{VISION_ONLY_GAME}', '<address bar URL>')]")
        else:
            print(f"Frame capture ONLY {VISION_ONLY_GAME!r}: {_vis_sources[0][0]} ({_vis_sources[0][1]})")
    # A game counts as done only from a FULL run -- a VISION_TEST_CLIPS run tags a few clips and must not
    # stop the real run from doing the rest. Test rows for a page are replaced when it's fully tagged.
    _full = clip_frames[~clip_frames.get("test_run", pd.Series(False, index=clip_frames.index))
                        .astype(str).str.lower().eq("true")] if not clip_frames.empty else clip_frames
    if not VISION_RETAG and not _full.empty:
        # CONFIRMED BUG (fixed): a page counted as done even when some of its frame files had gone missing from
        # disk (the tag model reported 184 clips with frames listed but only 179 found on disk). A page with any
        # missing file is visited again; clips whose frames are still on disk are reused, so only the missing
        # ones are recaptured.
        def _vis_files_ok(ff):
            return isinstance(ff, str) and ff and all(os.path.exists(os.path.join(VISION_FRAMES_DIR, f))
                                                        for f in ff.split(";") if f)
        _bad = ~_full["frame_files"].map(_vis_files_ok)
        if VISION_CAPTURE_VERSION >= 2:   # frames from before the capture fix show the wrong play too often
            _bad |= ~_full["frame_files"].map(lambda ff: f"_v{VISION_CAPTURE_VERSION}_" in str(ff))
        if VISION_TRACK_FPS:   # turning tracking on later revisits captured games for just the tracking frames
            # ...and so does a new VISION_TRACK_WIDTH: frames from the old width (another folder) don't count
            _cur = f"/{_vision_track_folder()}/"
            _bad |= ~_full.get("track_files", pd.Series(index=_full.index, dtype=object)).map(
                lambda ff: _vis_files_ok(ff) and _cur in str(ff).replace(os.sep, "/"))
        _missing = _full[_bad]["source_url"].dropna().unique()
        if len(_missing):
            print(f"Frame capture: {len(_missing)} page(s) have clips with frame or tracking files missing on disk -- "
                  f"revisiting them to capture just what's missing.")
        _done = set(_full["source_url"].dropna()) - set(_missing)
        _vis_sources = [s for s in _vis_sources if s[1] not in _done]
    # Newest first, one entry per page, capped per run.
    _vis_sources = sorted({u: (l, u, d) for l, u, d in _vis_sources}.values(), key=lambda x: x[2], reverse=True)
    _vis_left = max(0, len(_vis_sources) - VISION_MAX_GAMES_PER_RUN)
    _vis_sources = [(l, u) for l, u, _d in _vis_sources[:VISION_MAX_GAMES_PER_RUN]]
    if not clip_frames.empty:  # anything left for these pages is a test run or a retag -- replace it
        clip_frames = clip_frames[~clip_frames["source_url"].isin([u for _l, u in _vis_sources])]
    if _vis_left:
        print(f"Frame capture: {_vis_left} more untagged game page(s) wait for later runs "
              f"(VISION_MAX_GAMES_PER_RUN = {VISION_MAX_GAMES_PER_RUN}).")
    if not _vis_sources:
        print("Frame capture: every game with a clip page is already in the cache (set VISION_RETAG = True to redo).")
    else:
        print(f"Frame capture: {len(_vis_sources)} game page(s) "
              f"({'TEST: first ' + str(VISION_TEST_CLIPS) + ' clips each' if VISION_TEST_CLIPS else 'all clips'})")
        clip_frames = run_in_fastscout_session(lambda p: _vision_tag_pages(p, _vis_sources, clip_frames))
        clip_frames.to_csv(VISION_CACHE, index=False)
        print(f"  Frames are under {VISION_FRAMES_DIR} -- open a few to check they show the play.")
print(f"Clips with frames: {int(pd.to_numeric(clip_frames.get('frames_captured'), errors='coerce').fillna(0).ge(VISION_FRAMES_PER_CLIP).sum())} "
      f"of {len(clip_frames)} in {os.path.basename(VISION_CACHE)}"
      + (f" -- {clip_frames['error'].notna().sum()} with capture errors (see the 'error' column)"
         if len(clip_frames) and "error" in clip_frames.columns and clip_frames["error"].notna().any() else ""))
if not clip_frames.empty and "error" in clip_frames.columns:
    _err = clip_frames["error"].dropna().astype(str)
    _nc = int(_err.str.contains("clip start not confirmed").sum())
    if _nc:
        print("  " + "!" * 100)
        print(f"  {_nc} clip(s) SKIPPED: the video never moved to the clicked clip, so its start couldn't be confirmed "
              f"(the capture-fix safety check). Send this printout -- the check may need adjusting for this player.")
        print("  " + "!" * 100)
    elif len(_err):
        print("  Capture errors (first 3): " + " | ".join(_err.head(3)))
