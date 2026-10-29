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

# CONFIRMED CHANGE (frame archive): finished games' tracking frames may be packed into clip videos -- load the archive index
# and its hooks FIRST, so archived frames count as captured (never recaptured) and unpack themselves when read.
# (always on with VISION_SOURCE = "export": an exported game's tracking frames are read from its clip videos through these hooks)
if (globals().get("FRAME_ARCHIVE_HOOKS", True) or str(globals().get("VISION_SOURCE", "export")).lower() == "export") \
        and os.path.exists(os.path.join(PARSER_LIB, "46a_frame_archive.py")):
    FRAME_ARCHIVE_STEP = "hooks"
    run_section("46a_frame_archive")

# ---- Starting player and play tracking over (TRACKING_RESET_ID) -----------------------------------------------------------
# CONFIRMED CHANGE (requested: "fully start over with player and play tracking using the new videos at the 1920 wide").
# Runs ONCE per TRACKING_RESET_ID (it writes inputs/_tracking/_reset.json; leaving the setting on doesn't redo it):
#   * deletes everything tracking learned from the old web frames: inputs/_tracking (detections, tracks, jersey reads,
#     fingerprints, court positions, check pictures), the trained play models and their frame caches in inputs/_tag_model
#     (history.csv -- the model-version log the app shows -- is kept), and the jersey reader's model files and its own
#     reads (jersey_training/reads*). The reader retrains from the crops that are KEPT: jersey_training/coach* (cut from
#     the coaches' player checks) and extra/ (requested: keep them -- they still show what each number looks like).
#   * court calibrations were clicked on the old frames (another size): moved to court_calibration/_before_reset, not used.
#   * player checks saved in the app BEFORE the reset were made on the old frames: from now on tracking, the reader test and
#     the review queues ignore them (coach_checks_all, Play calls section). Their crops stay in the training set. Film Tagging
#     answers (Titles) are about plays, not frames -- they all stay.
#   * every game is redone from its Synergy export at VISION_EXPORT_TRACK_WIDTH (VISION_EXPORT_REPLACE_CAPTURED).
def _tracking_reset():
    import shutil as _sh
    rid = globals().get("TRACKING_RESET_ID")
    if not rid:
        return
    tdir = os.path.join(INPUT_DIR, "_tracking")
    marker = os.path.join(tdir, "_reset.json")
    try:
        with open(marker, encoding="utf-8") as fh:
            if json.load(fh).get("id") == rid:
                return
    except Exception:
        pass
    print(f"Tracking reset ({rid}): starting player and play tracking over on the Synergy exports...", flush=True)
    gone = {"tracking": 0, "play models": 0, "jersey reader": 0}

    def _rm(p, kind):
        try:
            _sh.rmtree(p) if os.path.isdir(p) else os.remove(p)
            gone[kind] += 1
        except Exception as e:
            print(f"  [reset] couldn't delete {p}: {type(e).__name__}: {e}", flush=True)
    for p in glob.glob(os.path.join(tdir, "*")):
        if os.path.basename(p) != "_reset.json":
            _rm(p, "tracking")
    tm = globals().get("TAG_MODEL_DIR") or os.path.join(INPUT_DIR, "_tag_model")
    for p in glob.glob(os.path.join(tm, "*")):
        if os.path.basename(p) != "history.csv":
            _rm(p, "play models")
    jd = globals().get("JERSEY_TRAIN_DIR") or os.path.join(INPUT_DIR, "jersey_training")
    for p in [os.path.join(jd, "reads"), os.path.join(jd, "reads_pose")] + glob.glob(os.path.join(jd, "*.pt")) \
            + glob.glob(os.path.join(jd, "_last_inputs*.json")):
        if os.path.exists(p):
            _rm(p, "jersey reader")
    cal = globals().get("COURT_CAL_DIR") or os.path.join(INPUT_DIR, "court_calibration")
    n_cal = 0
    for f in glob.glob(os.path.join(cal, "court_calibration_*.json")) + glob.glob(os.path.join(cal, "calibrate_*.html")):
        os.makedirs(os.path.join(cal, "_before_reset"), exist_ok=True)
        _sh.move(f, os.path.join(cal, "_before_reset", os.path.basename(f)))
        n_cal += 1
    os.makedirs(tdir, exist_ok=True)
    with open(marker, "w", encoding="utf-8") as fh:
        json.dump({"id": rid, "at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")}, fh)
    _kept = len(glob.glob(os.path.join(jd, "coach*", "*", "*"))) + len(glob.glob(os.path.join(jd, "extra", "*", "*")))
    print(f"  [reset] deleted: {gone['tracking']} tracking file(s)/folder(s), {gone['play models']} play-model file(s), "
          f"{gone['jersey reader']} jersey-reader file(s); kept {_kept:,} jersey crops for retraining"
          + (f"; {n_cal} court calibration file(s) moved to court_calibration/_before_reset" if n_cal else "")
          + ". Player checks saved before now are set aside (made on the old frames).", flush=True)


_tracking_reset()

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
    if not globals().get("_vision_size_shown") and info.get("w"):
        globals()["_vision_size_shown"] = True
        # CONFIRMED CHANGE (user asked "is this what we want?" -- the old line only described the 5 tag-model frames, which
        # stay 1024 on purpose): says what happens to BOTH kinds of frames.
        _tw = int(globals().get("_vision_cur_width") or VISION_TRACK_WIDTH)
        _kw = int(VISION_FRAME_MAX_WIDTH)
        print(f"    [quality] video stream: {info['w']}x{info.get('h')} -- tracking frames (players, jersey numbers) saved "
              f"{min(info['w'], _tw)} wide; the 5 tag-model frames per clip stay {min(info['w'], _kw)} wide (what that model was "
              f"trained on)" + (f" -- NOTE: the stream is smaller than {_tw}, so the High setting probably didn't take"
                                if info['w'] < _tw else ""), flush=True)
    length = clip_seconds or 10.0
    if info.get("duration") and info["duration"] == info["duration"]:  # finite, not NaN
        length = max(1.0, min(length, info["duration"] - info["start"]))
    if mode == "track":
        n = _vision_track_count(clip_seconds)
        times = [info["start"] + min(length, k / VISION_TRACK_FPS) for k in range(n)]
        # CONFIRMED CHANGE (requested: much clearer images for the player-number tracking). Tracking frames were saved at JPEG
        # quality 0.70 -- blocky compression right on the small jersey digits the readers have to read. Now
        # VISION_TRACK_JPEG_QUALITY (default 0.95) for frames captured from now on; frames already on disk are reused as
        # they are (delete a game's track folder under _vision_frames to recapture it at the new quality).
        max_w, q = int(globals().get("_vision_cur_width") or VISION_TRACK_WIDTH), float(globals().get("VISION_TRACK_JPEG_QUALITY", 0.95))
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


_VIS_JS_SIZE = """() => { const v = document.querySelector('sn-video-player video') || document.querySelector('video');
  return v ? {w: v.videoWidth, h: v.videoHeight, src: (v.currentSrc || '').slice(-80)} : null; }"""
_VIS_JS_CONTROLS = """() => [...document.querySelectorAll('sn-video-player button, sn-video-player [role=button], sn-video-player mat-select,'
  + ' sn-video-player select, sn-video-player [aria-label], button[aria-label], [mattooltip]')]
  .filter(e => e.offsetParent !== null).slice(0, 60)
  .map(e => (e.getAttribute('aria-label') || e.getAttribute('mattooltip') || e.getAttribute('title') || e.innerText || e.tagName)
  .replace(/\\s+/g, ' ').trim().slice(0, 40)).filter(Boolean)"""


_VIS_JS_UI = r"""() => {
  if (window.__visUI) return true;
  const vis = e => !!e && e.offsetParent !== null && getComputedStyle(e).visibility !== 'hidden';
  const outside = e => !e.closest('table.video-playlist');
  const press = e => {                       // a full pointer/mouse sequence: Angular / CDK widgets listen to different ones
    for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup'])
      e.dispatchEvent(new (t.startsWith('pointer') ? PointerEvent : MouseEvent)(t, {bubbles: true, cancelable: true, view: window}));
    e.click();
  };
  const clickable = e => e.closest('button, [role=menuitem], [role=menuitemradio], [role=tab], [role=option], [role=radio], a, label, li') || e;
  window.__visUI = {
    clickText(src, overlayOnly) {             // the smallest visible element whose own text matches, outside the clip list
      const rx = new RegExp(src, 'i');
      const root = overlayOnly ? '.cdk-overlay-container *, [role=dialog] *, .modal *, sn-dialog *' : 'body *';
      const hits = [...document.querySelectorAll(root)].filter(e => vis(e) && outside(e) && rx.test((e.innerText || '').trim()))
        .sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length);
      if (!hits.length) return null;
      press(clickable(hits[0]));
      return (hits[0].innerText || '').trim().slice(0, 40);
    },
    gear() {
      const bs = [...document.querySelectorAll('sn-video-player button')].filter(vis);
      const g = bs.find(b => /settings/i.test(b.getAttribute('sntooltip') || '') || /fa-cog|fa-gear/.test(b.innerHTML));
      if (!g) return false;
      press(g);
      return true;
    },
    selectNative(src) {
      const rx = new RegExp(src, 'i');
      for (const s of [...document.querySelectorAll('select')].filter(vis)) {
        const o = [...s.options].find(o => rx.test(o.text.trim()));
        if (o) { s.value = o.value; s.dispatchEvent(new Event('input', {bubbles: true}));
                 s.dispatchEvent(new Event('change', {bubbles: true})); return o.text.trim(); }
      }
      return null;
    },
    openDropdown(otherSrc) {                  // a dropdown showing the current value: open it
      const rx = new RegExp(otherSrc, 'i');
      const c = [...document.querySelectorAll('mat-select, ng-select, sn-select, [role=combobox], [aria-haspopup=listbox], .dropdown-toggle')]
        .filter(e => vis(e) && outside(e));
      const e = c.find(x => rx.test(x.innerText || '')) || c[0];
      if (!e) return false;
      press(e);
      return true;
    },
    overlays() {
      return [...document.querySelectorAll('.cdk-overlay-backdrop, [role=dialog], [role=menu], .modal.show, sn-dialog')].filter(vis).length;
    },
    texts() {
      return [...document.querySelectorAll('.cdk-overlay-container *, [role=dialog] *, [role=menu] *, .modal *')]
        .filter(e => vis(e) && e.children.length === 0)
        .map(e => (e.innerText || e.value || '').trim()).filter(Boolean).slice(0, 40);
    },
  };
  return true;
}"""


def _vision_close_overlays(page):
    """Close any menu / settings window left open -- an open one sits over the clip list and blocks every row click."""
    for _ in range(5):
        try:
            if not page.evaluate("() => window.__visUI ? window.__visUI.overlays() : 0"):
                return
        except Exception:
            return
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    try:
        page.evaluate("() => { const b = document.querySelector('.cdk-overlay-backdrop'); if (b) b.click(); }")
    except Exception:
        pass


def _vision_set_quality(page, want):
    """CONFIRMED CHANGE (requested: the Synergy player has a playback-quality setting, Standard / High, defaulting to
    Standard). CONFIRMED (user): it lives at the player's gear (Settings) -> Options -> General. Picks `want`
    (VISION_PLAYBACK_QUALITY) once per page before any frames are taken, closes the settings window, then reports the
    video's size. CONFIRMED BUG (fixed; quality test): Playwright's own click on the gear timed out, and a settings
    window left open blocked every clip-row click afterwards -- the clicks are now plain page events, and every menu or
    window is closed before capturing. If it can't pick it and the window is visible, waits VISION_QUALITY_MANUAL_WAIT
    seconds so you can pick it by hand."""
    if not want:
        return
    want = str(want)
    want_src = rf"^\s*{re.escape(want)}\b"
    other = "Standard" if want.lower().startswith("h") else "High"
    page.evaluate(_VIS_JS_UI)
    before = page.evaluate(_VIS_JS_SIZE) or {}
    _ls = "() => { const o = {}; try { for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); o[k] = String(localStorage.getItem(k)).slice(0, 300); } } catch (e) {} return o; }"
    ls_before = page.evaluate(_ls) or {}
    steps, done = [], False
    try:
        page.hover("sn-video-player", timeout=3000)          # the control bar shows on hover
    except Exception:
        pass
    if page.evaluate("() => window.__visUI.gear()"):
        steps.append("gear")
        page.wait_for_timeout(700)
        if page.evaluate("s => window.__visUI.clickText(s)", r"^\s*Options\s*$"):
            steps.append("Options")
            page.wait_for_timeout(900)
            if page.evaluate("s => window.__visUI.clickText(s)", r"^\s*General\s*$"):
                steps.append("General")
                page.wait_for_timeout(900)
            hit = page.evaluate("s => window.__visUI.selectNative(s)", want_src)
            if not hit:
                hit = page.evaluate("s => window.__visUI.clickText(s)", want_src)
            if not hit and page.evaluate("s => window.__visUI.openDropdown(s)", rf"{other}|quality"):
                page.wait_for_timeout(500)
                hit = page.evaluate("s => window.__visUI.clickText(s)", want_src)
            if hit:
                steps.append(f"'{hit}'")
                done = True
            else:
                print(f"    [quality] gear > Options > General opened but '{want}' wasn't found; the window shows: "
                      + (" | ".join(page.evaluate("() => window.__visUI.texts()")) or "(nothing)"), flush=True)
            page.wait_for_timeout(500)
            for btn in (r"^\s*(Save|Apply)\s*$", r"^\s*(OK|Done|Close)\s*$"):
                if page.evaluate("s => window.__visUI.clickText(s, true)", btn):
                    steps.append("saved/closed")
                    break
        else:
            print("    [quality] gear menu opened but no 'Options' in it; it shows: "
                  + (" | ".join(page.evaluate("() => window.__visUI.texts()")) or "(nothing)"), flush=True)
    else:
        print("    [quality] the player's gear (Settings) button wasn't found", flush=True)
    page.wait_for_timeout(600)
    _vision_close_overlays(page)
    wait_s = int(globals().get("VISION_QUALITY_MANUAL_WAIT", 20))
    if not done and not VISION_HEADLESS and wait_s > 0:
        print(f"    [quality] pick '{want}' by hand in the Synergy window now (gear > Options > General), then close that "
              f"window -- waiting {wait_s} s", flush=True)
        page.wait_for_timeout(wait_s * 1000)
        _vision_close_overlays(page)
    # CONFIRMED BUG (fixed; quality test: Standard and High gave identical frames). The setting says "* requires app
    # reload" -- it's saved, but the player keeps its current stream until the page is loaded again. So after picking it the
    # page is reloaded (same browser window, so the choice is kept) before any frame is taken.
    if done or not VISION_HEADLESS:
        try:
            ls_after = page.evaluate(_ls) or {}
            changed = {k: v for k, v in ls_after.items() if ls_before.get(k) != v}
            if changed:
                print("    [quality] saved in the browser as: " + "; ".join(f"{k} = {v[:120]}" for k, v in list(changed.items())[:4]),
                      flush=True)
            _url = page.url
            page.reload(wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_selector("table.video-playlist tr.playlist-item", timeout=45000)
            except Exception:
                _vision_open(page, _url)
            steps.append("page reloaded")
            # CONFIRMED BUG (fixed; quality test: clip 1 after the reload was skipped -- "start not confirmed", the video sat at
            # the end of the game video). Right after a reload the game video isn't loaded yet, so the click on the first clip
            # was "armed" before the player could jump. Wait until the video has loaded (up to 20 s) before the first click.
            page.evaluate("""async () => { const t0 = Date.now();
              while (Date.now() - t0 < 20000) { const v = document.querySelector('sn-video-player video') || document.querySelector('video');
                if (v && v.readyState >= 2 && isFinite(v.duration) && v.duration > 10) break;
                await new Promise(r => setTimeout(r, 200)); } }""")
            page.wait_for_timeout(1000)
            globals()["_vision_row_start"] = {}
        except Exception as _re:
            print(f"    [quality] reload after the setting failed ({type(_re).__name__}: {_re})", flush=True)
    page.wait_for_timeout(1000)
    after = page.evaluate(_VIS_JS_SIZE) or {}
    globals()["_vision_quality_set"] = done
    print(f"    [quality] playback quality '{want}': {'selected (' + ' > '.join(steps) + ')' if done else 'NOT picked automatically'}; "
          f"video {before.get('w')}x{before.get('h')} before -> {after.get('w')}x{after.get('h')} now "
          f"(the size can update only when the next clip loads)", flush=True)


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


# CONFIRMED CHANGE (requested after the Standard vs High test: High at 1280 wide gave ~6% more sure jersey reads on the
# same players; shrunk to 1024 it gave nothing). New games are captured at VISION_TRACK_WIDTH (1280) from the High stream;
# games ALREADY captured at a width in VISION_TRACK_KEEP_WIDTHS (1024) keep those frames and are never recaptured -- and a
# game that already has frames at a kept width stays at that width for its remaining clips, so one game is never mixed.
def _vision_track_widths():
    out = [int(VISION_TRACK_WIDTH)]
    for w in list(globals().get("VISION_TRACK_KEEP_WIDTHS", []) or []) + [globals().get("VISION_EXPORT_TRACK_WIDTH", 1920)]:
        if w and int(w) not in out:
            out.append(int(w))
    return out


def _vision_track_folder(width=None):
    w = int(width or globals().get("_vision_cur_width") or VISION_TRACK_WIDTH)
    base = "track" if w == 768 else f"track{w}"
    return base + (f"v{VISION_CAPTURE_VERSION}" if VISION_CAPTURE_VERSION >= 2 else "")


def _vision_track_folders():
    """Every tracking-frame folder name that counts: the current width's and each kept width's."""
    return [_vision_track_folder(w) for w in _vision_track_widths()]


def _vision_width_for_game(row):
    """The width this game's tracking frames are captured at: a kept (older) width if the game already has frames there."""
    gdir = _vision_frame_dir(row)
    for w in _vision_track_widths()[1:]:
        if glob.glob(os.path.join(gdir, _vision_track_folder(w), "*.jpg")):
            return w
    return int(VISION_TRACK_WIDTH)


def _vision_track_name(row, k):
    fp = hashlib.md5(str(row.get("description") or "").strip().encode("utf-8")).hexdigest()[:8]
    return os.path.join(_vision_track_folder(), f"{row.get('position')}_{fp}_t{k:03d}.jpg")


def _vision_times_path(row):
    """Sidecar with each tracking frame's time in the FULL-GAME video (seconds): what lets possessions be linked
    to each other later (requested: go forward and backward through the Synergy details)."""
    fp = hashlib.md5(str(row.get("description") or "").strip().encode("utf-8")).hexdigest()[:8]
    return os.path.join(_vision_frame_dir(row), _vision_track_folder(), f"{row.get('position')}_{fp}_times.json")


def _vis_present(p):
    """A tracking frame counts as captured when it's on disk (or packed by the frame archive) -- or when lean mode deleted it
    on purpose after the game was tracked (that game is never recaptured)."""
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return True
    return bool(globals().get("vision_frame_leaned") and vision_frame_leaned(p))


def _vision_saved_track(row, clip_seconds):
    """Paths of this clip's tracking frames if they're all on disk already, else []."""
    paths = [os.path.join(_vision_frame_dir(row), _vision_track_name(row, k)) for k in range(_vision_track_count(clip_seconds))]
    return paths if all(_vis_present(p) for p in paths) else []


def _vision_saved_frames(label, row):
    """Paths of all VISION_FRAMES_PER_CLIP frames for this clip if they're already on disk, else []. Also finds
    frames from the first test runs, which were saved per page label as <position>_<n>.jpg."""
    n = VISION_FRAMES_PER_CLIP
    candidates = [[os.path.join(_vision_frame_dir(row), _vision_frame_name(row, k)) for k in range(n)]]
    if VISION_CAPTURE_VERSION < 2:
        candidates.append([os.path.join(VISION_FRAMES_DIR, re.sub(r"[^\w@.-]+", "_", label), f"{row.get('position')}_{k + 1}.jpg")
                           for k in range(n)])
    for paths in candidates:
        if all(_vis_present(p) for p in paths):
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
            globals()["_vision_size_shown"] = False
            try:
                _vision_set_quality(page, globals().get("VISION_PLAYBACK_QUALITY", "High"))
            except Exception as _qe:
                print(f"    [quality] not set ({type(_qe).__name__}: {_qe})", flush=True)
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
            # CONFIRMED CHANGE (a run filled the disk: "No space left on device" on 15 clips). Stop capturing while there's
            # still room for the rest of the run (VISION_MIN_FREE_GB); finished clips are kept and the rest wait for a later run.
            _min_gb = float(globals().get("VISION_MIN_FREE_GB", 2))
            for n_done, r in enumerate(todo, 1):
                try:
                    import shutil as _sh_
                    _free = _sh_.disk_usage(VISION_FRAMES_DIR).free / 1e9
                except Exception:
                    _free = None
                if _free is not None and _free < _min_gb:
                    print(f"    !! only {_free:.1f} GB free on the disk (VISION_MIN_FREE_GB = {_min_gb:g}) -- capture stopped at clip "
                          f"{n_done} of {len(todo)}. Free space (Frame archive cell: lean mode), then run this cell again; "
                          f"it continues where it stopped.", flush=True)
                    break
                rec = {"source_label": label, "source_url": url, "position": r["position"],
                       "clip_game": r["game"], "clip_date": r["date"], "team": r["team"], "player": r["player"],
                       "result": r["result"], "description": r["description"],
                       "duration_s": _vis_seconds(r["duration"]), "test_run": bool(VISION_TEST_CLIPS),
                       "page_clips": len(todo),
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
                        globals()["_vision_cur_width"] = _vision_width_for_game(r)
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
            if new_rows:                                   # (stopped early, e.g. low disk space): keep what was captured
                cache = pd.concat([cache, pd.DataFrame(new_rows, columns=VISION_COLS)], ignore_index=True)
                new_rows = []
            cache = _vis_dedupe(cache)                     # a revisit replaces the clips it reached; the rest are kept
            cache.to_csv(VISION_CACHE, index=False)
        return cache
    finally:
        globals()["_vision_cur_width"] = None
        browser.close()


# ---- Run (or just load) -------------------------------------------------------------------------------
# CONFIRMED BUG (fixed; WashU stopped at clip 91 of 159 for low disk space, and the next run said "every game ... is already
# in the cache" and never captured the other 68). Each row now records how many clips its page had (page_clips), so a page
# that stopped partway is visited again and only the clips it's missing are captured. A revisit no longer throws away the
# page's earlier rows first: rows are replaced clip by clip (same page + clip number), so stopping again loses nothing.
if "page_clips" not in VISION_COLS:
    VISION_COLS = list(VISION_COLS) + ["page_clips"]


def _vis_dedupe(df):
    if df is None or df.empty or "source_url" not in df.columns or "position" not in df.columns:
        return df
    _k = df["source_url"].astype(str) + "|" + pd.to_numeric(df["position"], errors="coerce").astype("Int64").astype(str)
    return df[~_k.duplicated(keep="last")].reset_index(drop=True)


# ---- Synergy Editor test: open a game's FULL GAME VIDEO in the Synergy Editor app ---------------------------------------
# CONFIRMED CHANGE (requested: test sending a game to the Synergy Editor Basketball app from the frame-capture cell -- the
# first step toward exporting a game's clips as real 1080p video). What Synergy's own FULL GAME VIDEO button does with
# Playback = "Editor" (read from the page's code, Oct 2026):
#   1. PUT https://basketball.synergysportstech.com/api/games/<game id>/fullgamevideo/playlist  ->  {"result": {"id": <playlist id>}}
#   2. opens  sst-editor://OpenEdit?playlistId=<playlist id>&maxclips=500&bFullGame=1&title=<game title>
#      -- a link Windows hands to the Synergy Editor app (the browser pane in Claude can't open it, so the click there did nothing).
# This does the same from the notebook: signs in to Synergy, makes the playlist, and opens that link with Windows
# (os.startfile), so Synergy Editor opens on the game. SYNERGY_EDITOR_TEST = the game, in the _pbp/_video file-name format
# ("3_7_26 UW-Whitewater @ Washington-St. Louis Bears") or its 24-character Synergy game ID.
_SST_API = "https://basketball.synergysportstech.com/api"
_SST_BOXSCORE = "https://apps.synergysports.com/basketball/games/{gid}/boxscore"


def _sst_game_id_of(url):
    if "synergy_game_id" in globals():
        return synergy_game_id(url)
    m = re.search(r"games(?:/|%2f)([0-9a-f]{24})(?![0-9a-f])", str(url or ""), re.I)
    return m.group(1).lower() if m else None


def _sst_find_game(spec):
    """SYNERGY_EDITOR_TEST -> (game id, label). A 24-character ID is used as is; a file-name style game name is looked up
    in the schedules (date within a day + a word of the opponent's name) and its ID taken from the game's video link."""
    spec = str(spec or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{24}", spec):
        return spec.lower(), spec
    m = re.match(r"^\s*(\d{1,2})_(\d{1,2})_(\d{2,4})\s+(.*)$", spec)
    if not m:
        raise ValueError(f"SYNERGY_EDITOR_TEST should be a Synergy game ID or look like "
                         f"'3_7_26 UW-Whitewater @ Washington-St. Louis Bears', got {spec!r}")
    when = pd.Timestamp(int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0), int(m.group(1)), int(m.group(2)))
    words = {w for w in re.split(r"[\s@\-().]+", m.group(4).lower()) if len(w) > 2
             and w not in {"uww", "whitewater", "warhawks", "the", "st."}}
    best = None
    for name in ("schedule", "uww_team_schedule", "prev_games"):
        df = globals().get(name)
        if not isinstance(df, pd.DataFrame) or df.empty or "video_url" not in df.columns:
            continue
        for _, r in df[df["video_url"].notna()].iterrows():
            gd = r.get("game_date")
            if gd is None or pd.isna(gd):
                try:
                    gd = parse_schedule_date(r.get("date"), uww_season_start_year)
                except Exception:
                    gd = None
            if gd is None or pd.isna(pd.Timestamp(gd)) or abs((pd.Timestamp(gd).normalize() - when).days) > 1:
                continue
            who = f"{r.get('opponent', '')} {r.get('team', '')}".lower()
            if not any(w in who for w in words):
                continue
            gid = _sst_game_id_of(r.get("video_url"))
            if gid:
                days = abs((pd.Timestamp(gd).normalize() - when).days)
                if best is None or days < best[0]:
                    best = (days, gid, f"{pd.Timestamp(gd).date()} {r.get('team', '')} vs {r.get('opponent', '')}")
    if best is None:
        raise LookupError(f"no game in the schedules matches {spec!r} (or it has no Synergy video link). Use its Synergy "
                          f"game ID instead -- the 24 characters after /games/ in its Synergy address.")
    return best[1], best[2]


def _sst_editor_handler():
    """Which program Windows opens sst-editor:// links with (None = no program registered for them)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"sst-editor\shell\open\command") as k:
            return str(winreg.QueryValueEx(k, "")[0])
    except Exception:
        return None


def _sst_editor_open(page, game_id, label="", launch=True):
    """Synergy's FULL GAME VIDEO > Editor, from the notebook. Returns the sst-editor:// link (None if it failed)."""
    from urllib.parse import urlparse, parse_qs, quote
    box = _SST_BOXSCORE.format(gid=game_id)
    api_reqs = []
    on_req = lambda r: api_reqs.append(r) if "synergysportstech.com/api/" in r.url else None
    page.on("request", on_req)
    try:
        link = page.locator("a.ts-playlist-link", has_text=re.compile(r"full\s*game\s*video", re.I)).first
        page.goto(box, wait_until="domcontentloaded", timeout=60000)
        for _try in range(2):                      # the page sends a signed-out visitor to Synergy's login a moment later
            t0 = time.time()
            while time.time() - t0 < 30 and "auth.synergysportstech.com" not in page.url and not link.count():
                page.wait_for_timeout(500)
            if "auth.synergysportstech.com" not in page.url:
                break
            print("  [editor] signing in to Synergy...", flush=True)
            login_to_synergy(page, synergy_username, synergy_password, timeout_ms=60000)
            page.goto(box, wait_until="domcontentloaded", timeout=60000)
        link.wait_for(state="attached", timeout=60000)
        page.wait_for_timeout(1500)
        href = link.get_attribute("href") or ""
    finally:
        try:
            page.remove_listener("request", on_req)
        except Exception:
            pass
    title = (parse_qs(urlparse(href).query).get("title") or [label or game_id])[0]
    print(f"  [editor] box score open: {page.url}\n  [editor] game title on Synergy: {title}", flush=True)
    playlist_id, how = None, ""
    # (1) the same request the page makes, with the page's own sign-in header
    auth = None
    for r in api_reqs:
        try:
            h = r.all_headers()
        except Exception:
            continue
        if h.get("authorization"):
            auth = {k: v for k, v in h.items() if k == "authorization" or k.startswith("x-")}
            break
    if auth:
        try:
            resp = page.request.put(f"{_SST_API}/games/{game_id}/fullgamevideo/playlist",
                                    headers={**auth, "content-type": "application/json"}, data="{}", timeout=60000)
            if resp.ok:
                j = resp.json()
                playlist_id = ((j.get("result") or {}).get("id") if isinstance(j, dict) else None) or (j.get("id") if isinstance(j, dict) else None)
                how = "made directly"
            else:
                print(f"  [editor] playlist request answered {resp.status} -- trying the page's own buttons", flush=True)
        except Exception as e:
            print(f"  [editor] playlist request failed ({type(e).__name__}: {e}) -- trying the page's own buttons", flush=True)
    else:
        print("  [editor] couldn't read the page's sign-in header -- using the page's own buttons", flush=True)
    # (2) fallback: click FULL GAME VIDEO, pick Editor, OK -- and read the playlist id from the page's own request
    if not playlist_id:
        try:
            with page.expect_response(lambda r: "/fullgamevideo/playlist" in r.url and r.request.method == "PUT",
                                      timeout=60000) as ri:
                link.click()
                page.get_by_text("Video playback parameters").first.wait_for(timeout=20000)
                page.get_by_text("In Browser Player", exact=True).first.click()
                opt = page.locator("[role=option]", has_text=re.compile(r"^\s*Editor\s*$"))
                (opt.first if opt.count() else page.get_by_text("Editor", exact=True).last).click()
                page.get_by_role("button", name=re.compile(r"^\s*OK\s*$", re.I)).first.click()
            j = ri.value.json()
            playlist_id = (j.get("result") or {}).get("id") if isinstance(j, dict) else None
            how = "made by the page's FULL GAME VIDEO > Editor > OK"
        except Exception as e:
            print(f"  [editor] the page's buttons didn't work either ({type(e).__name__}: {e})", flush=True)
    if not playlist_id:
        print("  [editor] NO playlist id -- Synergy Editor can't be opened. Send this printout.", flush=True)
        return None
    _q = lambda v: quote(str(v), safe="@:$,;=?/()!*'~")
    params = [("playlistId", playlist_id), ("maxclips", int(globals().get("SYNERGY_EDITOR_MAX_CLIPS", 500))),
              ("bFullGame", "1"), ("title", title)]
    url = "sst-editor://OpenEdit?" + "&".join(f"{k}={_q(v)}" for k, v in params)
    print(f"  [editor] full-game playlist {playlist_id} ({how})\n  [editor] link: {url}", flush=True)
    if launch:
        handler = _sst_editor_handler()
        if sys.platform == "win32":
            print(f"  [editor] Windows opens sst-editor:// links with: {handler or '(no program registered -- is Synergy Editor installed?)'}",
                  flush=True)
            try:
                os.startfile(url)
                print("  [editor] sent to Synergy Editor -- it should open on this game in a few seconds.", flush=True)
            except OSError as e:
                print(f"  [editor] Windows couldn't open the link ({e}). Press Win+R, paste the link above, and press Enter.", flush=True)
        else:
            print("  [editor] not on Windows -- open the link above on the laptop that has Synergy Editor.", flush=True)
    return url


# ---- Synergy Editor: export the opened game (Ctrl+E > Location > OK) ------------------------------------------------------
# CONFIRMED CHANGE (requested: after the game opens in Synergy Editor, press Ctrl+E to open the export window, change Location to
# the _vision_frames folder and press OK). Synergy Editor is a Windows program, not a web page, so this drives it through Windows
# UI Automation with the "uiautomation" package (installed automatically the first time).
# CONFIRMED BUG (fixed; first test: "ImportError: DLL load failed while importing win32api"). The first version used pywinauto,
# which needs pywin32 -- and pywin32 doesn't load in this Anaconda kernel. uiautomation only needs comtypes (no pywin32).
# Steps: find the Editor's window (by its program, Synergy.Editor.Basketball.exe), wait for the game to load, bring it to the
# front, Ctrl+E, find the Location box, put the folder in it and read it back, then OK. OK is only pressed when the Location box
# really shows the folder AND the disk has room for the export (an estimate from this game's clip lengths) -- an export into the
# wrong place, or one that fills the disk, is worse than none. Every control in the export window is written to
# inputs/_synergy_export_window.txt, so a box or button with an unexpected name can be fixed from that file.
SYNERGY_EXPORT_MB_PER_S = 1.06       # Synergy's 1080p export: ~1.06 MB per second of video (the 18-s sample clip was 18.8 MB)


def _sst_uia():
    import importlib.util as _ilu
    if _ilu.find_spec("uiautomation") is None:
        print("  [export] installing uiautomation (one time)...", flush=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "uiautomation"])
    import uiautomation as auto
    auto.SetGlobalSearchTimeout(5)
    return auto


def _sst_editor_pids(exe_name):
    pids = set()
    try:
        import psutil
        for pr in psutil.process_iter(["name"]):
            if (pr.info.get("name") or "").lower() == exe_name.lower():
                pids.add(pr.pid)
    except Exception:
        try:
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=20).stdout
            for line in out.splitlines():
                parts = [x.strip('"') for x in line.split('","')]
                if len(parts) > 1 and parts[1].isdigit():
                    pids.add(int(parts[1]))
        except Exception:
            pass
    return pids


def _sst_editor_windows(auto, pids):
    out = []
    for w in auto.GetRootControl().GetChildren():
        try:
            if (pids and w.ProcessId in pids) or (not pids and re.search(r"(?i)synergy", w.Name or "")):
                out.append(w)
        except Exception:
            continue
    return out


def _sst_bring_to_front(auto, w):
    try:
        w.SetActive()
    except Exception:
        pass
    try:
        if auto.GetForegroundControl().ProcessId != w.ProcessId:
            import ctypes
            auto.SendKey(auto.Keys.VK_MENU)                  # an Alt press lets a background program take the foreground
            ctypes.windll.user32.SetForegroundWindow(w.NativeWindowHandle)
            time.sleep(0.5)
    except Exception:
        pass
    try:
        w.SetFocus()
    except Exception:
        pass
    try:
        return auto.GetForegroundControl().ProcessId == w.ProcessId
    except Exception:
        return False


def _sst_walk(auto, ctrl, depth=40):
    try:
        return [c for c, _d in auto.WalkControl(ctrl, includeTop=False, maxDepth=depth)]
    except Exception:
        return []


def _sst_value(c):
    try:
        return str(c.GetValuePattern().Value)
    except Exception:
        return str(getattr(c, "Name", "") or "")


def _sst_dump(auto, dlg, path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Export window: {dlg.ControlTypeName} name={dlg.Name!r} class={dlg.ClassName!r}\n")
            for c, d in auto.WalkControl(dlg, includeTop=False, maxDepth=40):
                r = c.BoundingRectangle
                extra = f" value={_sst_value(c)!r}" if c.ControlTypeName in ("EditControl", "ComboBoxControl") else ""
                f.write(f"{'  ' * d}{c.ControlTypeName} name={c.Name!r} id={c.AutomationId!r} class={c.ClassName!r} "
                        f"rect=({r.left},{r.top},{r.right},{r.bottom}){extra}\n")
    except Exception as e:
        print(f"  [export] (control list not written: {type(e).__name__}: {e})", flush=True)


def _sst_find_location_box(auto, dlg):
    """The export window's Location text box: a box named Location, else the box beside/below the "Location" label."""
    ctrls = _sst_walk(auto, dlg)
    for c in ctrls:
        if c.ControlTypeName in ("EditControl", "ComboBoxControl") and re.match(r"(?i)^\s*location", c.Name or ""):
            if c.ControlTypeName == "ComboBoxControl":
                ed = [x for x in _sst_walk(auto, c, 3) if x.ControlTypeName == "EditControl"]
                return ed[0] if ed else c
            return c
    labels = [c for c in ctrls if c.ControlTypeName in ("TextControl", "GroupControl")
              and re.match(r"(?i)^\s*location\b", c.Name or "")]
    edits = [c for c in ctrls if c.ControlTypeName == "EditControl"]
    if not labels or not edits:
        return None
    lr = labels[0].BoundingRectangle

    def score(e):
        r = e.BoundingRectangle
        same_row = r.top < lr.bottom and r.bottom > lr.top and r.left >= lr.left
        below = r.top >= lr.top - 5
        return (0 if same_row else 1 if below else 2, abs(r.top - lr.top) + abs(r.left - lr.right))
    return sorted(edits, key=score)[0]


def _sst_default_export_gb():
    """A whole game's export when its clip lengths aren't known: the biggest export on disk so far (most clips), at least
    SYNERGY_EXPORT_DEFAULT_GB (5.5)."""
    best = float(globals().get("SYNERGY_EXPORT_DEFAULT_GB", 5.5))
    try:
        for f in [v for r in _vx_roots() for v in glob.glob(os.path.join(r, "*", "video"))]:
            vids = glob.glob(os.path.join(f, "*.mp4"))
            try:
                n_rows = len(pd.read_csv(os.path.join(os.path.dirname(f), "Export.csv"), dtype=str))
            except Exception:
                n_rows = len(vids)
            if vids:
                best = max(best, sum(os.path.getsize(v) for v in vids) / len(vids) * max(n_rows, len(vids)) / 1024 ** 3)
    except Exception:
        pass
    return best


def _sst_export_estimate_gb(game_id):
    """Rough size of the game's export: its clips' lengths (from uww_clip_frames.csv) x SYNERGY_EXPORT_MB_PER_S. None = unknown."""
    try:
        cf = pd.read_csv(VISION_CACHE, low_memory=False)
        g = cf[cf["source_url"].astype(str).str.contains(str(game_id), regex=False)]
        dur = pd.to_numeric(g.get("duration_s"), errors="coerce").dropna()
        if dur.empty:
            return None
        n_page = pd.to_numeric(g.get("page_clips", pd.Series(dtype=float)), errors="coerce").max()
        n = int(n_page) if pd.notna(n_page) and n_page > len(dur) else len(dur)
        secs = float(dur.clip(upper=120).sum()) + max(0, n - len(dur)) * float(dur.median())
        est = secs * float(globals().get("SYNERGY_EXPORT_MB_PER_S", 1.06)) / 1024.0
        # CONFIRMED BUG (fixed; WashU: estimated 1.8 GB from the 90 clips captured so far, the export was ~3 GB for 185 clips):
        # a short clip list on file means a partial capture -- a whole game exports to about 3-3.5 GB
        # CONFIRMED BUG (fixed; Wheaton @ North Park ran out of disk at 233 of 321 clips): a game with more clips is bigger --
        # Synergy's full-game exports have run ~15 MB a clip, so a 321-clip game is ~5 GB, not 3.5
        return est if n >= 150 else max(est, _sst_default_export_gb())
    except Exception:
        return None


def _sst_editor_export(link, export_dir, game_id=None):
    from urllib.parse import urlparse, parse_qs
    import shutil as _sh
    auto = _sst_uia()
    export_dir = os.path.abspath(export_dir)
    os.makedirs(export_dir, exist_ok=True)
    # room on the disk for the export?
    free_gb = _sh.disk_usage(export_dir).free / 1024 ** 3
    est = _sst_export_estimate_gb(game_id) if game_id else None
    keep = float(globals().get("SYNERGY_EXPORT_MIN_FREE_GB", globals().get("VISION_MIN_FREE_GB", 2)))
    need = (est if est is not None else _sst_default_export_gb()) + keep
    print(f"  [export] disk: {free_gb:.1f} GB free; this game's export is about "
          f"{f'{est:.1f} GB' if est is not None else f'? GB (no clip lengths on file -- assuming {_sst_default_export_gb():.1f} GB, the biggest whole game so far)'}, "
          f"+ {keep:.0f} GB kept free = {need:.1f} GB needed", flush=True)
    if free_gb < need:
        print("  [export] NOT enough room -- export not started. Free up space or export to another drive "
              "(SYNERGY_EXPORT_DIR).", flush=True)
        return False
    title = (parse_qs(urlparse(link).query).get("title") or [""])[0]
    cmd = _sst_editor_handler() or ""
    m = re.match(r'^\s*"([^"]+)"|^\s*(\S+)', cmd)
    exe_name = os.path.basename((m.group(1) or m.group(2)) if m else "Synergy.Editor.Basketball.exe")
    # the Editor's window (its title is just "Synergy Editor" -- the game's name only shows in the export window), then give the
    # game SYNERGY_EDITOR_LOAD_WAIT seconds to load. The export window's title is checked below, so a game that loaded slowly
    # (still the previous edit on screen) is caught there.
    wait_max = float(globals().get("SYNERGY_EDITOR_LOAD_WAIT", 20))
    main, wins, pids, t0 = None, [], set(), time.time()
    while time.time() - t0 < 30 and not wins:
        pids = _sst_editor_pids(exe_name)
        wins = _sst_editor_windows(auto, pids)
        if not wins:
            time.sleep(1)
    if not wins:
        print(f"  [export] Synergy Editor ({exe_name}) has no open window -- is it running?", flush=True)
        return False
    main = max(wins, key=lambda w: (w.BoundingRectangle.width() * w.BoundingRectangle.height()))
    # CONFIRMED BUG (fixed; Wheaton @ North Park: "giving the game 0 s more to load"). When Synergy Editor had to START, its
    # window took longer than SYNERGY_EDITOR_LOAD_WAIT to appear, so the whole wait was used up before the game began loading
    # and Ctrl+E went to an empty editor. A cold start (window took more than a few seconds) now gets the full wait AFTER the
    # window appears; an editor that was already open keeps the old timing.
    _startup = time.time() - t0
    left = wait_max if _startup > 3 else wait_max - _startup
    print(f"  [export] Synergy Editor window: {main.Name.strip()!r}"
          + (f" (took {_startup:.0f} s to start)" if _startup > 3 else "")
          + f" -- giving the game {max(0, left):.0f} s more to load", flush=True)
    if left > 0:
        time.sleep(left)
    wins = _sst_editor_windows(auto, pids)
    before = {w.NativeWindowHandle for w in wins}
    ident = lambda c: (c.ControlTypeName, c.Name, c.AutomationId, tuple((c.BoundingRectangle.left, c.BoundingRectangle.top)))
    before_inner = {ident(c) for c in _sst_walk(auto, main, 6) if c.ControlTypeName == "WindowControl"}
    dlg = None
    for attempt in range(2):
        front = _sst_bring_to_front(auto, main)
        if not front:
            print("  [export] (couldn't bring Synergy Editor to the front -- Ctrl+E may go to another window)", flush=True)
        time.sleep(0.5)
        auto.SendKeys("{Ctrl}e", waitTime=0.5)
        t1 = time.time()
        while time.time() - t1 < 15 and dlg is None:
            time.sleep(0.5)
            # CONFIRMED BUG (fixed; the "export window" it found was a ToolTip -- PopupRoot, a timeline timecode "02:02:58:46",
            # see _synergy_export_window.txt): tooltips and other popups are not the export window, so they're skipped
            _popup = lambda w: str(getattr(w, "ClassName", "") or "") in ("PopupRoot", "ToolTip")
            for w in _sst_editor_windows(auto, pids):              # a new top-level window (the export window) ...
                if not _popup(w) and (w.NativeWindowHandle not in before or re.search(r"(?i)export", w.Name or "")):
                    dlg = w
                    break
            if dlg is None:                                        # ... or a new dialog inside the main window
                inner = [c for c in _sst_walk(auto, main, 6) if c.ControlTypeName == "WindowControl"
                         and ident(c) not in before_inner and not _popup(c)]
                dlg = inner[0] if inner else None
        if dlg is not None:
            break
        print("  [export] Ctrl+E didn't open a window -- trying once more", flush=True)
    if dlg is None:
        print("  [export] the export window never opened. Click once inside Synergy Editor's clip list and run the cell again.",
              flush=True)
        return False
    print(f"  [export] export window open: {dlg.Name!r}", flush=True)
    dump = os.path.join(INPUT_DIR, "_synergy_export_window.txt")
    _sst_dump(auto, dlg, dump)
    # the export window names the edit it exports ("Export - Edit - UWWhitewater@Wash(StLouis) - Mar 7, 2026"): it must be this game
    _norm = lambda x: re.sub(r"\s+", " ", str(x or "")).strip().lower()
    if title and _norm(title) not in _norm(dlg.Name):
        print(f"  [export] the export window is for {dlg.Name!r}, not this game ({title!r}) -- the game may still be loading. "
              f"OK NOT pressed; raise SYNERGY_EDITOR_LOAD_WAIT and run again.", flush=True)
        return False
    box = _sst_find_location_box(auto, dlg)
    if box is None:
        print(f"  [export] couldn't find the Location box -- OK NOT pressed. Send {dump}.", flush=True)
        return False
    print(f"  [export] Location was: {_sst_value(box)!r}", flush=True)
    try:
        box.GetValuePattern().SetValue(export_dir)
    except Exception:
        try:
            box.Click(simulateMove=False)
            auto.SendKeys("{Ctrl}a{Delete}", waitTime=0.2)
            auto.SendKeys(export_dir.replace("{", "{{}").replace("}", "{}}"), interval=0.01, waitTime=0.3)
        except Exception as e:
            print(f"  [export] couldn't type into the Location box ({type(e).__name__}: {e}) -- OK NOT pressed. Send {dump}.",
                  flush=True)
            return False
    time.sleep(0.5)
    now = _sst_value(box)
    if os.path.normcase(now.strip().rstrip("\\/")) != os.path.normcase(export_dir.rstrip("\\/")):
        print(f"  [export] the Location box shows {now!r}, not {export_dir!r} -- OK NOT pressed. Send {dump}.", flush=True)
        return False
    print(f"  [export] Location set: {now}", flush=True)
    # the export window's other choices (first test, Oct 2026: MP4 + CSV / CSV only / Copy of Edit, Include Text Overlay,
    # Combine into single file). One .mp4 per clip plus Synergy's CSV of the clips, no text drawn on the video.
    ctrls = _sst_walk(auto, dlg)
    want_type = str(globals().get("SYNERGY_EXPORT_TYPE", "MP4 + CSV"))
    for c in ctrls:
        if c.ControlTypeName == "RadioButtonControl" and _norm(c.Name) == _norm(want_type):
            try:
                sp = c.GetSelectionItemPattern()
                if not sp.IsSelected:
                    sp.Select()
            except Exception:
                c.Click(simulateMove=False)
    for pat, key, dflt in ((r"text overlay", "SYNERGY_EXPORT_TEXT_OVERLAY", False),
                           (r"combine into single file", "SYNERGY_EXPORT_COMBINE", False)):
        want = bool(globals().get(key, dflt))
        for c in ctrls:
            if c.ControlTypeName == "CheckBoxControl" and re.search(pat, c.Name or "", re.I):
                try:
                    tp = c.GetTogglePattern()
                    if bool(tp.ToggleState) != want:
                        tp.Toggle()
                except Exception:
                    pass
    time.sleep(0.3)
    ctrls = _sst_walk(auto, dlg)

    def _state(c):
        try:
            return "on" if (c.GetSelectionItemPattern().IsSelected if c.ControlTypeName == "RadioButtonControl"
                            else c.GetTogglePattern().ToggleState) else "off"
        except Exception:
            return "?"
    opts = [f"{c.Name}: {_state(c)}" for c in ctrls if c.ControlTypeName in ("RadioButtonControl", "CheckBoxControl")]
    clips = next((_sst_value(c) for c in ctrls if c.ControlTypeName == "ComboBoxControl"), "?")
    print(f"  [export] options: {'; '.join(opts)}; clips: {clips}", flush=True)
    sel = next((c for c in ctrls if c.ControlTypeName == "RadioButtonControl" and _norm(c.Name) == _norm(want_type)), None)
    if sel is None or _state(sel) != "on":
        print(f"  [export] couldn't select {want_type!r} -- OK NOT pressed. Send {dump}.", flush=True)
        return False
    # OK sits deep inside the window's button bar (an ItemsControl); a button's text can be its own name or its child's
    def _btn_text(c):
        if (c.Name or "").strip():
            return c.Name.strip()
        for x in _sst_walk(auto, c, 6):
            if x.ControlTypeName == "TextControl" and (x.Name or "").strip():
                return x.Name.strip()
        return ""
    buttons = [(c, _btn_text(c)) for c in ctrls if c.ControlTypeName in ("ButtonControl", "ListItemControl")]
    ok = (next((c for c, t in buttons if re.match(r"^\s*OK\s*$", t, re.I)), None)
          or next((c for c, t in buttons if re.match(r"(?i)^\s*(export|save)\s*$", t)), None))
    if ok is None:
        _sst_dump(auto, dlg, dump)
        print(f"  [export] couldn't find the OK button (buttons: {[t for _c, t in buttons]}) -- not pressed. Send {dump}.",
              flush=True)
        return False
    before_files = set(os.listdir(export_dir))
    try:
        ok.GetInvokePattern().Invoke()
    except Exception:
        ok.Click(simulateMove=False)
    print(f"  [export] OK pressed -- Synergy Editor is exporting the clips to {export_dir}", flush=True)
    t2 = time.time()
    new = []
    while time.time() - t2 < float(globals().get("SYNERGY_EXPORT_WATCH", 30)) and not new:
        time.sleep(2)
        new = sorted(set(os.listdir(export_dir)) - before_files)
    print(f"  [export] new in the folder after {time.time() - t2:.0f} s: {new[:5] if new else 'nothing yet'}"
          + (" (the export keeps going in Synergy Editor)" if new else
             " -- check Synergy Editor for an export progress window"), flush=True)
    return True


# =====================================================================================================================
# FRAMES FROM SYNERGY EXPORTS (VISION_SOURCE = "export", the default)
# CONFIRMED CHANGE (requested: "build everything to use these [Synergy Editor exports] instead of the web scraping"). For each
# game the frame-capture cell picks (same choice as before: each side's most recent game the coaches haven't finished), this:
#   1. finds the game's Synergy export -- a folder under SYNERGY_EXPORT_DIR made by Synergy Editor, named after the game
#      ("UWWhitewater@Wash(StLouis) - Mar 7, 2026"), with Export.csv (one row per clip) and video/<#>.mp4 (one 1080p clip each);
#   2. if there isn't one: signs in to Synergy, sends the game to Synergy Editor (FULL GAME VIDEO > Editor), and exports it
#      (Ctrl+E > Location > OK), then waits until every clip video is written (VISION_EXPORT_WAIT_MIN);
#   3. registers every clip in uww_clip_frames.csv exactly like a captured clip -- same columns, same clip numbers (Export.csv's
#      "#" is the clip page's position), same frame names -- so play calls, the tag model, tracking, the jersey reader, Play
#      review and Film Tagging work as before. The 5 tag-model frames are written as small JPEGs (1024 wide, what that model
#      learned from); the tracking frames (VISION_TRACK_FPS a second, VISION_EXPORT_TRACK_WIDTH wide) are read straight from
#      the clip videos when a step needs them (section 46a), so they take no disk space of their own. Times come from Synergy's
#      own in/out points, so every frame is inside its play (the web capture's clip starts were off by ~2 s, up to 9 s).
# A game that was already partly captured from the web keeps those clips as they are (their player checks stay lined up) and
# gets its missing clips from the export at the SAME width; VISION_EXPORT_REPLACE_CAPTURED = True redoes the whole game from
# the export instead. VISION_SOURCE = "web" brings back the old live-player capture.
_VX_REGISTRY = "_synergy_exports.json"


# CONFIRMED CHANGE (requested: "I have a different drive ... F:\Backups\uwwmensbball_tracking ... How could you use this so
# that storage space is not an issue?"). A game's export is the big part (3-5 GB); everything the parser keeps per game in
# _vision_frames is small (the tag-model JPEGs, tracks, _export.json -- the tracking frames are read from the export's clip
# videos). So:
#   * SYNERGY_EXPORT_DIR = the big drive -> new exports are written straight there (the space check measures THAT drive);
#   * exports are looked for on every storage folder (SYNERGY_EXPORT_DIR, _vision_frames, VISION_STORAGE_DIRS), so an export
#     made on C: and later moved to the big drive is still found, and its frames still read (section 46a);
#   * game folders moved out of _vision_frames to a storage folder (same folder name) are still read: coach-checked frames,
#     the jersey reader's training crops, archived clips (section 46a);
#   * the export registry (_synergy_exports.json) stays in _vision_frames, so it's there even when the drive isn't;
#   * the drive not plugged in: nothing new is exported this run (it says so) -- exports already found are used as usual.
def vision_storage_dirs():
    """The storage folders reachable right now, besides _vision_frames: VISION_STORAGE_DIRS (a folder or a list) and
    SYNERGY_EXPORT_DIR. A drive that isn't plugged in is left out."""
    v = globals().get("VISION_STORAGE_DIRS") or []
    v = [v] if isinstance(v, (str, os.PathLike)) else list(v)
    if globals().get("SYNERGY_EXPORT_DIR"):
        v.append(globals()["SYNERGY_EXPORT_DIR"])
    home = os.path.normcase(os.path.abspath(VISION_FRAMES_DIR))
    out, seen = [], {home}
    for d in v:
        d = os.path.abspath(str(d))
        if os.path.normcase(d) not in seen and os.path.isdir(d):
            seen.add(os.path.normcase(d))
            out.append(d)
    return out


def _vx_root():
    """Where NEW exports go."""
    return os.path.abspath(globals().get("SYNERGY_EXPORT_DIR") or VISION_FRAMES_DIR)


def _vx_roots():
    """Every folder an export can be in: the export folder, _vision_frames, then the other storage folders."""
    out, seen = [], set()
    for d in [_vx_root(), VISION_FRAMES_DIR] + vision_storage_dirs():
        d = os.path.abspath(d)
        if os.path.normcase(d) not in seen and os.path.isdir(d):
            seen.add(os.path.normcase(d))
            out.append(d)
    return out


def _vx_registry(update=None):
    p = os.path.join(os.path.abspath(VISION_FRAMES_DIR), _VX_REGISTRY)
    reg = {}
    for q in [os.path.join(d, _VX_REGISTRY) for d in vision_storage_dirs()] + [p]:   # _vision_frames' copy wins
        try:
            with open(q, encoding="utf-8") as fh:
                reg.update(json.load(fh))
        except Exception:
            pass
    if update:
        reg.update(update)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(reg, fh, indent=1)
    return reg


def _vx_secs(t):
    try:
        return sum(float(x) * 60 ** i for i, x in enumerate(reversed(str(t).strip().split(":"))))
    except Exception:
        return None


def _vx_date_txt(d):
    """2026-03-07 -> 'Mar 7, 2026' (how Synergy writes dates in clip pages and export names)."""
    d = pd.Timestamp(d)
    return f"{d:%b} {d.day}, {d.year}"


def _vx_find_export(game_id, label, url, cache):
    """The game's export folder (with Export.csv), or None. The registry first; else a folder named for the game's date whose
    game part matches the clip page's Game cell (exports made before the registry, e.g. by the Synergy Editor test)."""
    roots = _vx_roots()
    reg = _vx_registry()
    hit = reg.get(game_id)
    if hit and hit.get("folder"):
        for root in roots:                                 # wherever the export is now (made on C:, moved to the big drive)
            if os.path.isfile(os.path.join(root, hit["folder"], "Export.csv")):
                return os.path.join(root, hit["folder"])
    m = re.match(r"^\s*(\d{4}-\d{2}-\d{2})", str(label))
    if not m:
        return None
    dates = {_vx_date_txt(pd.Timestamp(m.group(1)) + pd.Timedelta(days=dd)) for dd in (0, -1, 1)}
    games = set()
    if isinstance(cache, pd.DataFrame) and not cache.empty and "clip_game" in cache.columns:
        games = {str(x) for x in cache.loc[cache["source_url"] == url, "clip_game"].dropna().unique()}
    # CONFIRMED BUG (fixed; "it didn't add any film tagging for the most recent Carroll games" -- Carroll @ Elmhurst, Feb 24,
    # was given the Wheaton @ North Park export because it was the only export dated Feb 24, so Wheaton's clips were
    # registered as Carroll's game). With no clips of the game captured yet, an export now also has to name BOTH teams of
    # the clip page's label ("2026-02-24 Carroll (WI) Pioneers vs Elmhurst Bluejays" -> carroll + elmhurst).
    _lab_teams = re.split(r"\s+vs\.?\s+|\s+@\s+", re.sub(r"^\s*\d{4}-\d{2}-\d{2}\s*", "", str(label)), maxsplit=1)
    _first = lambda t: next((w for w in re.split(r"[^a-z]+", t.lower()) if len(w) > 2 and w not in ("the", "university")), "")
    _team_words = [w for w in (_first(t) for t in _lab_teams) if w]
    cands, seen = [], set()
    for d in [f for root in roots for f in glob.glob(os.path.join(root, "*", "Export.csv"))]:
        name = os.path.basename(os.path.dirname(d))
        if name in seen:                                   # the same export in two places: the first root's copy
            continue
        seen.add(name)
        if " - " not in name:
            continue
        g, dt = name.rsplit(" - ", 1)
        _gl = re.sub(r"[^a-z]", "", g.lower())
        # (4-letter starts: "Washington-St. Louis" is "Wash(StLouis)" in an export name; a UWW game's label names only the
        # opponent, so UWW itself must be in the export name)
        _names_teams = bool(_team_words) and all(w[:4] in _gl for w in _team_words) and (
            len(_team_words) >= 2 or "whitewater" in _gl or "www" in _gl)
        if dt.strip() in dates and ((g.strip() in games) if games else _names_teams):
            cands.append(os.path.dirname(d))
    if len(cands) == 1 or (cands and games):
        _vx_registry({game_id: {"folder": os.path.basename(cands[0]), "found": pd.Timestamp.now().isoformat(timespec="seconds")}})
        return cands[0]
    return None


def _vx_make_export(game_id, label):
    """Synergy Editor: open the game and export it. -> the export folder, or None."""
    from urllib.parse import urlparse, parse_qs
    try:
        os.makedirs(_vx_root(), exist_ok=True)
    except OSError:
        print(f"  [export] {label}: no Synergy export yet, and the export folder {_vx_root()} isn't reachable -- is that "
              f"drive plugged in? Not exported this run (plug the drive in and rerun).", flush=True)
        return None
    print(f"  [export] {label}: no Synergy export yet -- exporting it with Synergy Editor into {_vx_root()}", flush=True)
    link = run_in_fastscout_session(lambda p: _sst_editor_open(p, game_id, label))
    if not link:
        return None
    title = (parse_qs(urlparse(link).query).get("title") or [""])[0]
    t0 = time.time()
    if not _sst_editor_export(link, _vx_root(), game_id):
        return None
    folder = None
    while time.time() - t0 < 180 and folder is None:          # the folder Synergy Editor made (named after the game)
        exact = os.path.join(_vx_root(), title)
        if title and os.path.isfile(os.path.join(exact, "Export.csv")):
            folder = exact
            break
        new = [os.path.dirname(f) for f in glob.glob(os.path.join(_vx_root(), "*", "Export.csv"))
               if os.path.getmtime(f) >= t0 - 5]
        folder = max(new, key=os.path.getmtime) if new else None
        if folder is None:
            time.sleep(3)
    if folder is None:
        print("  [export] Synergy Editor never wrote an Export.csv -- check the export in Synergy Editor.", flush=True)
        return None
    _vx_registry({game_id: {"folder": os.path.basename(folder), "title": title, "label": label,
                            "exported": pd.Timestamp.now().isoformat(timespec="seconds")}})
    return folder


def _vx_wait_done(folder):
    """Wait until every clip in Export.csv has its video, and the newest video stopped growing. -> True when complete."""
    wait_s = float(globals().get("VISION_EXPORT_WAIT_MIN", 90)) * 60
    # CONFIRMED BUG (fixed; Wheaton @ North Park: "233 of 321 clip videos written..." for 90 minutes). The export had stopped the
    # night before (the disk filled up: a 321-clip game is ~5 GB, the space check assumed 3.5 GB), and every later run sat
    # waiting the full VISION_EXPORT_WAIT_MIN for an export that wasn't running. An export with no new clip video for
    # VISION_EXPORT_STALL_MIN minutes has stopped: its clips so far are used, and the run says why the rest are missing.
    stall_s = float(globals().get("VISION_EXPORT_STALL_MIN", 5)) * 60
    t0, last_say = time.time(), 0
    import shutil as _sh_
    while True:
        try:
            n_rows = len(pd.read_csv(os.path.join(folder, "Export.csv"), dtype=str))
        except Exception:
            n_rows = None
        vids = glob.glob(os.path.join(folder, "video", "*.mp4"))
        newest = max((os.path.getmtime(v) for v in vids + [os.path.join(folder, "Export.csv")] if os.path.exists(v)),
                     default=0)
        _tmp = glob.glob(os.path.join(folder, "video_temp", "*"))
        newest = max([newest] + [os.path.getmtime(v) for v in _tmp if os.path.exists(v)])
        if n_rows and len(vids) >= n_rows and time.time() - newest > 20:
            return True
        if n_rows and len(vids) < n_rows and time.time() - newest > stall_s:
            try:
                _free = _sh_.disk_usage(folder).free / 1024 ** 3
            except Exception:
                _free = None
            _avg = (sum(os.path.getsize(v) for v in vids) / len(vids) / 1024 ** 3) if vids else None
            print(f"  [export] {os.path.basename(folder)}: the export STOPPED at {len(vids)} of {n_rows} clip videos (nothing new "
                  f"for {(time.time() - newest) / 60:.0f} min) -- using the {len(vids)} there."
                  + (f" Disk: {_free:.1f} GB free" if _free is not None else "")
                  + (f"; the other {n_rows - len(vids)} clips need about {(n_rows - len(vids)) * _avg:.1f} GB" if _avg else "")
                  + ". Most likely the disk filled up: free space (or set SYNERGY_EXPORT_DIR to the big drive), then export "
                    "the game again in Synergy Editor (Ctrl+E) into the same folder, or move this folder away so the next "
                    "run exports it again.", flush=True)
            return False
        if time.time() - t0 > wait_s:
            print(f"  [export] {os.path.basename(folder)}: still {len(vids)} of {n_rows} clip videos after "
                  f"{wait_s / 60:.0f} min -- using what's there; the rest are picked up on the next run.", flush=True)
            return False
        if time.time() - last_say > 60:
            print(f"  [export] {os.path.basename(folder)}: {len(vids)} of {n_rows or '?'} clip videos written...", flush=True)
            last_say = time.time()
        time.sleep(10)


def _vx_game_width(cache, url, gdir):
    """The tracking width a game uses: the width of frames it already has (web capture or export), else
    VISION_EXPORT_TRACK_WIDTH -- one game is never mixed."""
    if isinstance(cache, pd.DataFrame) and not cache.empty and "track_files" in cache.columns:
        tf = cache.loc[cache["source_url"] == url, "track_files"].dropna().astype(str)
        for x in tf:
            m = re.search(r"/track(\d+)?(?:v\d+)?/", "/" + x.split(";")[0].replace("\\", "/"))
            if m:
                return int(m.group(1) or 768)
    for w in _vision_track_widths():
        f = os.path.join(gdir, _vision_track_folder(w))
        if os.path.isdir(f) and (glob.glob(os.path.join(f, "*.jpg")) or glob.glob(os.path.join(f, "_*.json"))):
            return int(w)
    return int(globals().get("VISION_EXPORT_TRACK_WIDTH", 1920))


def _vx_ingest(label, url, folder, cache):
    """Register every clip of one export in the clip-frames table. -> the updated table."""
    import cv2
    ex = pd.read_csv(os.path.join(folder, "Export.csv"), dtype=str)
    name = os.path.basename(folder)
    game_part = name.rsplit(" - ", 1)[0].strip() if " - " in name else name
    mine = cache[cache["source_url"] == url] if not cache.empty else cache
    have = {}
    for _, r in mine.iterrows():
        pos = pd.to_numeric(r.get("position"), errors="coerce")
        if pd.notna(pos):
            have[int(pos)] = r
    replace = bool(globals().get("VISION_EXPORT_REPLACE_CAPTURED", True))
    # the game's date as the clip page wrote it (keeps an already-captured game in its folder); else the export's own date
    if not replace and not mine.empty and mine["clip_date"].notna().any():
        clip_date = str(mine["clip_date"].dropna().mode().iloc[0])
    else:
        clip_date = _vx_date_txt(pd.to_datetime(ex["Date"].dropna().iloc[0]))
    todo = ex[~ex["Synergy String"].fillna("").str.contains(VISION_SKIP_DESCRIPTION, regex=True)]
    if VISION_TEST_CLIPS:
        todo = todo.head(int(VISION_TEST_CLIPS))
    row0 = {"date": clip_date, "game": game_part}
    gdir = _vision_frame_dir(row0)
    width = int(globals().get("VISION_EXPORT_TRACK_WIDTH", 1920)) if replace else _vx_game_width(cache, url, gdir)
    globals()["_vision_cur_width"] = width
    tdir = os.path.join(gdir, _vision_track_folder(width))
    os.makedirs(tdir, exist_ok=True)
    man = os.path.join(tdir, "_export.json")
    try:
        with open(man, encoding="utf-8") as fh:
            index = json.load(fh)
    except Exception:
        index = {"clips": {}}
    index["export"] = os.path.abspath(folder)
    fps = float(VISION_TRACK_FPS or 4)
    n_new = n_kept = n_err = 0
    rows = []
    t0 = time.time()
    print(f"  [export] {label}: {len(ex)} clips in the export ({len(todo)} after skipping free throws); tracking frames "
          f"{width} wide, {fps:g} a second", flush=True)
    for _, e in todo.iterrows():
        pos = int(pd.to_numeric(e["#"], errors="coerce"))
        desc = str(e.get("Synergy String") or "")
        # the team's full name ("Washington (St. Louis) Bears") -- Play calls matches it to the play-by-play by its words
        # (a 3-letter code like "WAS" matched nothing, and every clip was counted as ours)
        team = str(e.get("Team") or "").strip() or None
        rec = {"source_label": label, "source_url": url, "position": pos, "clip_game": game_part, "clip_date": clip_date,
               "team": team, "player": str(e.get("Title") or "").strip(), "result": e.get("Result"), "description": desc,
               "duration_s": _vx_secs(e.get("Duration")), "test_run": bool(VISION_TEST_CLIPS), "page_clips": len(todo),
               "captured_at": pd.Timestamp.now().isoformat(timespec="seconds"), "frame_source": "synergy export"}
        old = have.get(pos)
        if old is not None and not replace and isinstance(old.get("frame_files"), str) and old.get("frame_files") \
                and isinstance(old.get("track_files"), str) and old.get("track_files") \
                and not (isinstance(old.get("error"), str) and old.get("error")):
            n_kept += 1                                    # captured from the web already: kept (its checks stay lined up)
            continue
        vid = os.path.join(folder, "video", f"{pos}.mp4")
        if not os.path.exists(vid):
            rec["error"] = "clip video not in the export (the export stopped before it, or it is still being written)"
            rows.append(rec)
            n_err += 1
            continue
        try:
            cap = cv2.VideoCapture(vid)
            vfps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
            nfr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            cap.release()
            length = (nfr / vfps) if nfr else (rec["duration_s"] or 10.0)
            rec["duration_s"] = round(length, 2)
            r = {"date": clip_date, "game": game_part, "position": pos, "description": desc}
            fdir = _vision_frame_dir(r)
            os.makedirs(fdir, exist_ok=True)
            # the 5 tag-model frames: real JPEGs, 1024 wide (what the tag model learned from)
            n = VISION_FRAMES_PER_CLIP
            kt = [length * (0.5 if n == 1 else 0.05 + 0.9 * k / (n - 1)) for k in range(n)]
            kpaths = []
            for k, t in enumerate(kt):
                pth = os.path.join(fdir, _vision_frame_name(r, k))
                if not (os.path.exists(pth) and os.path.getsize(pth) > 1):
                    fr = _fx_decode(vid, min(max(nfr - 1, 0), int(round(t * vfps))), int(VISION_FRAME_MAX_WIDTH))
                    if fr is None:
                        raise RuntimeError(f"couldn't read frame {k} of {os.path.basename(vid)}")
                    _FA_ORIG["imwrite"](pth, fr, [cv2.IMWRITE_JPEG_QUALITY, 85])
                kpaths.append(pth)
            # the tracking frames: listed in _export.json, read from the clip video when needed
            nt = _vision_track_count(length)
            tt = [min(max(length - 1.0 / vfps, 0), k / fps) for k in range(nt)]
            tnames = [_vision_track_name(r, k) for k in range(nt)]
            stem = re.sub(r"_t\d{3,}\.jpg$", "", os.path.basename(tnames[0]))
            try:
                vrel = os.path.relpath(vid, tdir)
            except ValueError:                             # the export is on another drive
                vrel = os.path.abspath(vid)
            index["clips"][stem] = {"video": vrel, "frames": [os.path.basename(x) for x in tnames],
                                    "src": [min(max(nfr - 1, 0), int(round(t * vfps))) for t in tt], "w": width, "fps": fps}
            t_in = _vx_secs(e.get("Media In Point")) or 0.0
            full_t = [round(t_in + t, 3) for t in tt]
            with open(_vision_times_path(r), "w") as fh:
                json.dump(full_t, fh)
            rec.update(frames_captured=len(kpaths), frame_files=";".join(_vision_rel(x) for x in kpaths),
                       track_files=";".join(_vision_rel(os.path.join(fdir, x)) for x in tnames),
                       track_times=";".join(f"{x:.3f}" for x in full_t), video_start_s=round(t_in, 3))
            n_new += 1
        except Exception as ex_:
            rec["error"] = f"{type(ex_).__name__}: {ex_}"[:300]
            n_err += 1
        rows.append(rec)
        if (n_new + n_err) % 25 == 0:
            print(f"    {n_new + n_err} clip(s) registered ({time.time() - t0:.0f}s)", flush=True)
    with open(man, "w", encoding="utf-8") as fh:
        json.dump(index, fh)
    if "_fx_load_index" in globals():
        _fx_load_index()                                   # the new frames are readable right away
    globals()["_vision_cur_width"] = None
    if rows:
        cols = list(dict.fromkeys(list(VISION_COLS) + ["frame_source"]))
        cache = pd.concat([cache, pd.DataFrame(rows).reindex(columns=cols)], ignore_index=True)
    # CONFIRMED BUG (fixed; "1 page(s) with clips whose files are missing or failed" on every run, and the Wash U export
    # registered again each time): the page kept 2 rows from the old web capture for clips the export doesn't have (their
    # frames were deleted at the restart), so the page always looked unfinished. When the export replaces the page, those
    # rows go.
    if replace and not cache.empty:
        _keep_pos = {int(p_) for p_ in pd.to_numeric(todo["#"], errors="coerce").dropna()}
        _stale = (cache["source_url"] == url) & ~pd.to_numeric(cache["position"], errors="coerce").isin(_keep_pos)
        if _stale.any():
            print(f"  [export] {label}: {int(_stale.sum())} clip(s) from the old web capture that the export doesn't have "
                  f"(free throws / not exported) -- removed", flush=True)
            cache = cache[~_stale].reset_index(drop=True)
    print(f"  [export] {label}: {n_new} clip(s) from the export, {n_kept} kept from the earlier web capture"
          + (f", {n_err} with errors (see the 'error' column)" if n_err else "") + f" ({time.time() - t0:.0f}s)", flush=True)
    return cache


def _vision_from_exports(sources, cache):
    """VISION_SOURCE = "export": every game in `sources` from its Synergy export (exported first if needed)."""
    if "_fx_decode" not in globals():                      # the frame reader lives in section 46a
        globals()["FRAME_ARCHIVE_STEP"] = "hooks"
        run_section("46a_frame_archive")
    for label, url in sources:
        gid = _sst_game_id_of(url)
        if not gid:
            print(f"  [export] {label}: no Synergy game ID in its video link -- skipped", flush=True)
            continue
        folder = _vx_find_export(gid, label, url, cache)
        if folder is None:
            if not globals().get("VISION_EXPORT_AUTO", True) or sys.platform != "win32":
                print(f"  [export] {label}: no Synergy export in {_vx_root()} -- export the game from Synergy Editor "
                      f"(FULL GAME VIDEO > Editor, then Ctrl+E) into that folder and run again.", flush=True)
                continue
            try:
                folder = _vx_make_export(gid, label)
            except Exception as e:
                print(f"  [export] {label}: export failed ({type(e).__name__}: {e})", flush=True)
                folder = None
            if folder is None:
                continue
        print(f"  [export] {label}: export {os.path.basename(folder)!r}", flush=True)
        _vx_wait_done(folder)
        cache = _vis_dedupe(_vx_ingest(label, url, folder, cache))
        cache.to_csv(VISION_CACHE, index=False)
    return cache


SYNERGY_EDITOR_TEST = globals().get("SYNERGY_EDITOR_TEST")
SYNERGY_EDITOR_TEST_ONLY = globals().get("SYNERGY_EDITOR_TEST_ONLY", True)
synergy_editor_link = None
if SYNERGY_EDITOR_TEST:
    print(f"Synergy Editor test: {SYNERGY_EDITOR_TEST}", flush=True)
    try:
        _sst_gid, _sst_lab = _sst_find_game(SYNERGY_EDITOR_TEST)
        print(f"  [editor] {_sst_lab} -> Synergy game {_sst_gid}", flush=True)
        synergy_editor_link = run_in_fastscout_session(lambda p: _sst_editor_open(p, _sst_gid, _sst_lab))
    except Exception as _sst_e:
        print(f"  [editor] test failed: {type(_sst_e).__name__}: {_sst_e}", flush=True)
    if synergy_editor_link and globals().get("SYNERGY_EDITOR_EXPORT", True) and sys.platform == "win32":
        try:
            if _sst_editor_export(synergy_editor_link, globals().get("SYNERGY_EXPORT_DIR") or VISION_FRAMES_DIR, _sst_gid):
                from urllib.parse import urlparse as _up, parse_qs as _pq
                _t = (_pq(_up(synergy_editor_link).query).get("title") or [""])[0]
                _vx_registry({_sst_gid: {"folder": _t, "title": _t, "label": _sst_lab,
                                         "exported": pd.Timestamp.now().isoformat(timespec="seconds")}})
        except Exception as _sst_x:
            print(f"  [export] failed: {type(_sst_x).__name__}: {_sst_x}", flush=True)
    if SYNERGY_EDITOR_TEST_ONLY and RUN_FRAME_CAPTURE:
        print("  (SYNERGY_EDITOR_TEST_ONLY = True: frame capture skipped this run -- set SYNERGY_EDITOR_TEST = None to capture again)",
              flush=True)


clip_frames = (_vis_dedupe(pd.read_csv(VISION_CACHE, low_memory=False)) if os.path.exists(VISION_CACHE)
               else pd.DataFrame(columns=VISION_COLS))
if RUN_FRAME_CAPTURE and not (SYNERGY_EDITOR_TEST and SYNERGY_EDITOR_TEST_ONLY):
    # Every played game with a clip page: UWW's own games and the upcoming opponent's prior games,
    # plus any page listed by hand in VISION_PLAYLIST_URLS.
    _vis_sources = [(lab, url, pd.Timestamp.max) for lab, url in VISION_PLAYLIST_URLS]  # hand-listed go first
    # CONFIRMED CHANGE (requested: "why is it only capturing our games and not the opponent's games? I need it to do both").
    # Both were always in the list, but newest-first across everything, 2 a run -- so our own late-season games came first.
    # VISION_CAPTURE_FIRST = "opponent" now captures the UPCOMING OPPONENT's games (prev_games: theirs before facing us)
    # first, then UWW's; VISION_CAPTURE_WHICH limits it to one side ("both" / "opponent" / "uww").
    _vis_kind = {}
    _vis_recent_idx = {}                                   # page -> 0 = that side's most recent game, 1 = the one before ...
    _which = str(globals().get("VISION_CAPTURE_WHICH", "both")).lower()
    for _sched_name in [n for n, k in (("uww_team_schedule", "uww"), ("prev_games", "opponent")) if _which in ("both", k)]:
        _sched = globals().get(_sched_name)
        if not isinstance(_sched, pd.DataFrame) or _sched.empty or "video_url" not in _sched.columns:
            continue
        # CONFIRMED CHANGE (requested: "Why did it try to capture the MSOE game on 2-21-2026 when that is the third previous
        # game"). Only each side's VISION_RECENT_GAMES most recent PLAYED games are captured -- ours before the run's date, and
        # the upcoming opponent's before facing us -- not every game of the season. None = every game (the old behaviour).
        _cand = []
        for _, _g in _sched[_sched["video_url"].notna()].iterrows():
            _gd = _g.get("game_date")
            if _gd is None or pd.isna(_gd):
                try:
                    _gd = parse_schedule_date(_g["date"], uww_season_start_year)
                except Exception:
                    _gd = None
            if _gd is not None and pd.Timestamp(_gd) >= reference_date and not VISION_ONLY_GAME:
                continue  # not played yet as of reference_date (a named test game is allowed through)
            _cand.append((pd.Timestamp(_gd) if _gd is not None else pd.Timestamp.min, _g))
        _nrec = globals().get("VISION_RECENT_GAMES", 2)
        _cand.sort(key=lambda x: x[0], reverse=True)
        if _nrec and not VISION_ONLY_GAME:
            _cand = _cand[:int(_nrec)]
        for _ri, (_gts, _g) in enumerate(_cand):
            _vis_recent_idx[_g["video_url"]] = _ri
            _gd = None if _gts == pd.Timestamp.min else _gts
            _opp_side = _sched_name == "prev_games"
            _lab_ = (f"{pd.Timestamp(_gd).date() if _gd is not None else ''} "
                     + (f"{globals().get('upcoming_opponent_short') or 'opponent'} vs {_g.get('opponent', '')}" if _opp_side
                        else f"{_g.get('opponent', '')}")).strip()
            _vis_kind[_g["video_url"]] = "opponent" if _opp_side else "uww"
            _vis_sources.append((_lab_, _g["video_url"], pd.Timestamp(_gd) if _gd is not None else pd.Timestamp.min))
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
            return isinstance(ff, str) and ff and all(_vis_present(os.path.join(VISION_FRAMES_DIR, f))
                                                        for f in ff.split(";") if f)
        _bad = ~_full["frame_files"].map(_vis_files_ok)
        if VISION_CAPTURE_VERSION >= 2:   # frames from before the capture fix show the wrong play too often
            _bad |= ~_full["frame_files"].map(lambda ff: f"_v{VISION_CAPTURE_VERSION}_" in str(ff))
        if VISION_TRACK_FPS:   # turning tracking on later revisits captured games for just the tracking frames
            # ...and so does a new VISION_TRACK_WIDTH: frames from the old width (another folder) don't count
            # (CONFIRMED CHANGE: frames at a width in VISION_TRACK_KEEP_WIDTHS count too -- not recaptured)
            _curs = [f"/{f_}/" for f_ in _vision_track_folders()]
            _bad |= ~_full.get("track_files", pd.Series(index=_full.index, dtype=object)).map(
                lambda ff: _vis_files_ok(ff) and any(c_ in str(ff).replace(os.sep, "/") for c_ in _curs))
        _gap_urls = set(_full[_bad]["source_url"].dropna())           # captured, but some clips' files are missing / failed
        # pages that stopped partway: fewer clips than the page had (page_clips). Pages captured before page_clips was
        # recorded can't tell, so they're checked once (a quick visit: clips already on disk are reused, not recaptured).
        _pc = pd.to_numeric(_full.get("page_clips", pd.Series(index=_full.index, dtype=float)), errors="coerce")
        _incomplete = set()
        for _u, _g in _full.assign(_pc=_pc).groupby("source_url"):
            _n_page = _g["_pc"].max()
            if pd.isna(_n_page) or len(_g) < int(_n_page):
                _incomplete.add(_u)
        _missing = _gap_urls | _incomplete
        _in_run = {x[1] for x in _vis_sources}
        _n_inc = len(_incomplete & _in_run)
        _n_gap = len((_gap_urls - _incomplete) & _in_run)
        if False and (_n_inc or _n_gap):              # printed below, for the pages this run actually works on
            print(f"Frame capture: " + ", ".join(x for x in (
                f"{_n_inc} page(s) not fully captured (stopped partway, or captured before the page's clip count was "
                f"recorded -- checked once)" if _n_inc else "",
                f"{_n_gap} page(s) with clips whose files are missing or failed" if _n_gap else "") if x)
                + " -- each is completed (only what's missing) before its side moves on to another game.")
        _done = set(_full["source_url"].dropna()) - _missing
        _vis_sources = [s for s in _vis_sources if s[1] not in _done]
    else:
        _gap_urls, _incomplete = set(), set()
    # CONFIRMED CHANGE (requested: "only capture one game at a time since I need the coaches to analyze those games before
    # doing the 2nd most recent game"). Order: each side's MOST RECENT game first (the opponent's, then ours -- VISION_CAPTURE_FIRST),
    # then each side's second most recent, and so on. With VISION_WAIT_FOR_COACHES, a NEW game is only captured once every
    # captured game in the window has been worked through by the coaches: its clips are play calls and no more than
    # VISION_WAIT_MAX_UNTAGGED of them are still untagged (from the last run's uww_play_calls.csv). Pages of captured games with
    # missing frames are always finished first.
    _first = str(globals().get("VISION_CAPTURE_FIRST", "opponent")).lower()
    # CONFIRMED CHANGE (requested: "set it so that we get the 2nd most recent Wheaton game to test this on" -- the starters
    # check). VISION_ALSO_GAMES: games captured NOW, on top of the usual pick, without waiting for the coaches to finish the
    # side's current game (VISION_WAIT_FOR_COACHES) -- same name format as VISION_ONLY_GAME ("2_21_26 Millikin @ Wheaton",
    # matched by the date within a day and a team word in the game's label). Only games in each side's VISION_RECENT_GAMES
    # window. A game already captured is skipped as usual. [] / None = off.
    _also = globals().get("VISION_ALSO_GAMES", [])
    _force = set()
    for _nm in ([_also] if isinstance(_also, str) else list(_also or [])):
        _m = re.match(r"^\s*(\d{1,2})_(\d{1,2})_(\d{2,4})\s+(.*)$", str(_nm))
        if not _m:
            print(f"Frame capture: VISION_ALSO_GAMES entry {_nm!r} not understood (like '2_21_26 Millikin @ Wheaton')", flush=True)
            continue
        _fd = pd.Timestamp(int(_m.group(3)) + (2000 if len(_m.group(3)) == 2 else 0), int(_m.group(1)), int(_m.group(2)))
        _fw = {w for w in re.split(r"[\s@\-]+", _m.group(4).lower()) if len(w) > 2 and w not in {"uww", "whitewater", "warhawks", "the"}}
        _hit = [x for x in _vis_sources if x[2] not in (pd.Timestamp.max, pd.Timestamp.min)
                and abs((x[2] - _fd).days) <= 1 and any(w in x[0].lower() for w in _fw)]
        if _hit:
            _force.add(_hit[0][1])
            print(f"Frame capture: also capturing {_hit[0][0]} now (VISION_ALSO_GAMES)", flush=True)
        else:
            print(f"Frame capture: VISION_ALSO_GAMES {_nm!r} -- already captured, or not one of the games in the window", flush=True)
    _rank = lambda u: 0 if u not in _vis_kind else (1 if _vis_kind[u] == _first else 2)   # hand-listed, chosen side, other
    _vis_sources = sorted({u: (l, u, d) for l, u, d in _vis_sources}.values(),
                          key=lambda x: (0 if x[1] not in _vis_kind or x[1] in _force else 1, _vis_recent_idx.get(x[1], 0),
                                         _rank(x[1]), -x[2].value))
    _captured_urls = set(clip_frames["source_url"].dropna()) if not clip_frames.empty and "source_url" in clip_frames.columns else set()
    # CONFIRMED CHANGE (requested: "it should be the most previous unfinished UWW game and most previous unfinished opponent's
    # game"). Each side works on ONE game at a time: its most recent game that the coaches haven't finished. That game is
    # captured (or its missing frames filled in); the side's next game only comes once it's finished -- its clips are play
    # calls and no more than VISION_WAIT_MAX_UNTAGGED are still untagged (from the last run's uww_play_calls.csv).
    if globals().get("VISION_WAIT_FOR_COACHES", True) and not VISION_ONLY_GAME and not VISION_RETAG:
        _pcp = os.path.join(globals().get("APP_DATA_DIR") or OUTPUT_DIR, "uww_play_calls.csv")
        _pc_last = pd.read_csv(_pcp, low_memory=False) if os.path.exists(_pcp) else pd.DataFrame()
        _max_u = int(globals().get("VISION_WAIT_MAX_UNTAGGED", 10))

        def _game_state(_u):
            """(finished?, note) for a captured page."""
            _ff = set(f for x in clip_frames.loc[clip_frames["source_url"] == _u, "frame_files"].dropna().astype(str)
                      for f in x.split(";") if f)
            if _pc_last.empty or "frame_files" not in _pc_last.columns:
                return False, "no play calls from it yet -- run the notebook through the Play review"
            _mine = _pc_last[_pc_last["frame_files"].astype(str).map(lambda x: any(f in _ff for f in x.split(";") if f))]
            if _mine.empty:
                return False, "no play calls from it yet -- run the notebook through the Play review"
            _nu = int((_mine.get("decode_quality", pd.Series(dtype=object)) == "Untagged").sum())
            if _nu > _max_u:
                return False, f"{_nu} of {len(_mine)} clips still untagged -- Analytics > Film Tagging"
            return True, ""

        _pending = {x[1]: x for x in _vis_sources}         # pages that need capturing (new, or frames missing)
        _keep = [x for x in _vis_sources if x[1] not in _vis_kind or x[1] in _force]   # hand-listed / VISION_ALSO_GAMES always go
        # CONFIRMED CHANGE (requested: "just do one of them at a time -- don't do the opponent's current game until after UWW's
        # most recent game is done"). VISION_ONE_GAME_AT_A_TIME: the sides take turns -- VISION_CAPTURE_FIRST's side first; the
        # other side's game is only captured once the first side's current game is captured AND finished by the coaches.
        _one = bool(globals().get("VISION_ONE_GAME_AT_A_TIME", True))
        _order = ("uww", "opponent") if _first == "uww" else ("opponent", "uww")
        for _side in _order:
            _side_open = False
            _pages = sorted([u for u, k in _vis_kind.items() if k == _side], key=lambda u: _vis_recent_idx.get(u, 0))
            for _u in _pages:
                _lab_u = next((x[0] for x in _vis_sources if x[1] == _u), None)
                if _lab_u is None and not clip_frames.empty:
                    _l = clip_frames.loc[clip_frames["source_url"] == _u, "source_label"].dropna()
                    _lab_u = str(_l.iloc[0]) if len(_l) else _u
                if _u in _pending:                         # this side's current game: capture it / fill it in
                    _keep.append(_pending[_u])
                    if _u in _gap_urls and _u not in _incomplete and _game_state(_u)[0]:
                        continue                           # failed clips of a game the coaches already finished: fill
                                                           # them in and keep going to this side's current game
                    _side_open = True
                    break
                _fin, _note = _game_state(_u)
                if not _fin:
                    print(f"Frame capture: {'opponent' if _side == 'opponent' else 'UWW'} -- working on {_lab_u} ({_note}); "
                          f"its next game waits until the coaches finish it.", flush=True)
                    _side_open = True
                    break
            if _one and _side_open:
                _other = [k for k in _order if k != _side][0]
                if any(k == _other for k in _vis_kind.values()):
                    print(f"Frame capture: one game at a time (VISION_ONE_GAME_AT_A_TIME) -- "
                          f"{'the opponent' if _other == 'opponent' else 'UWW'}'s game waits until this "
                          f"{'UWW' if _side == 'uww' else 'opponent'} game is finished by the coaches.", flush=True)
                break
        _vis_sources = sorted({x[1]: x for x in _keep}.values(),
                              key=lambda x: (0 if x[1] not in _vis_kind or x[1] in _force else 1, _vis_recent_idx.get(x[1], 0),
                                             _rank(x[1]), -x[2].value))
    _n_by = {k: sum(1 for x in _vis_sources if _vis_kind.get(x[1]) == k) for k in ("opponent", "uww")}
    print(f"Frame capture: game pages still to capture -- {_n_by['opponent']} of the upcoming opponent's "
          f"({globals().get('upcoming_opponent_short') or '?'}), {_n_by['uww']} of UWW's; "
          f"{'opponent' if _first == 'opponent' else 'UWW'} games first (VISION_CAPTURE_FIRST), newest first.")
    _vis_left = max(0, len(_vis_sources) - VISION_MAX_GAMES_PER_RUN)
    _vis_sources = [(l, u) for l, u, _d in _vis_sources[:VISION_MAX_GAMES_PER_RUN]]
    # CONFIRMED BUG (fixed; the same "2 page(s) not fully captured ... checked once" note on every run): it counted pages in
    # the window that one-game-at-a-time keeps WAITING, so they were never visited and the note never went away. It now
    # names only the pages this run is completing.
    _now = {u: l for l, u in _vis_sources}
    _inc_now = [l for u, l in _now.items() if u in _incomplete]
    _gap_now = [l for u, l in _now.items() if u in _gap_urls and u not in _incomplete]
    if _inc_now or _gap_now:
        print("Frame capture: completing " + "; ".join(
            [f"{l} (stopped partway, or captured before its clip count was recorded)" for l in _inc_now]
            + [f"{l} (some clips' frames are missing or failed)" for l in _gap_now]) + " -- only what's missing is captured.")
    if not clip_frames.empty and VISION_RETAG:  # a retag starts these pages over (otherwise rows are replaced clip by clip)
        clip_frames = clip_frames[~clip_frames["source_url"].isin([u for _l, u in _vis_sources])]
    if _vis_left:
        print(f"Frame capture: {_vis_left} more untagged game page(s) wait for later runs "
              f"(VISION_MAX_GAMES_PER_RUN = {VISION_MAX_GAMES_PER_RUN}).")
    if not _vis_sources:
        print("Frame capture: every game with a clip page is already in the cache (set VISION_RETAG = True to redo).")
    else:
        print(f"Frame capture: {len(_vis_sources)} game page(s) "
              f"({'TEST: first ' + str(VISION_TEST_CLIPS) + ' clips each' if VISION_TEST_CLIPS else 'all clips'})")
        if str(globals().get("VISION_SOURCE", "export")).lower() == "export":
            clip_frames = _vision_from_exports(_vis_sources, clip_frames)
        else:
            clip_frames = run_in_fastscout_session(lambda p: _vision_tag_pages(p, _vis_sources, clip_frames))
        clip_frames.to_csv(VISION_CACHE, index=False)
        print(f"  Frames are under {VISION_FRAMES_DIR} -- open a few to check they show the play.")
# CONFIRMED CHANGE (the "15 with capture errors ... No space left on device" line on every run): those were rows of an early
# TEST capture (VISION_TEST_CLIPS) of one game that failed on a full disk -- they're replaced when that game is captured. They
# are listed on their own line now, so the errors line only shows real captures.
_test_rows = (clip_frames.get("test_run", pd.Series(False, index=clip_frames.index)).astype(str).str.lower().eq("true")
              if not clip_frames.empty else pd.Series(dtype=bool))
_err_all = clip_frames["error"].notna() if (not clip_frames.empty and "error" in clip_frames.columns) else _test_rows & False
print(f"Clips with frames: {int(pd.to_numeric(clip_frames.get('frames_captured'), errors='coerce').fillna(0).ge(VISION_FRAMES_PER_CLIP).sum())} "
      f"of {len(clip_frames)} in {os.path.basename(VISION_CACHE)}"
      + (f" -- {int((_err_all & ~_test_rows).sum())} with capture errors (see the 'error' column)"
         if (_err_all & ~_test_rows).any() else ""))
if (_err_all & _test_rows).any():
    _tl = clip_frames.loc[_err_all & _test_rows, "source_label"].dropna().astype(str).unique().tolist()
    print(f"  ({int((_err_all & _test_rows).sum())} more row(s) with errors are from an old TEST capture of "
          f"{', '.join(_tl) or 'a game'} -- replaced when that game is captured)")
if not clip_frames.empty and "error" in clip_frames.columns:
    _err = clip_frames.loc[_err_all & ~_test_rows, "error"].dropna().astype(str)
    _nc = int(_err.str.contains("clip start not confirmed").sum())
    if _nc:
        print("  " + "!" * 100)
        print(f"  {_nc} clip(s) SKIPPED: the video never moved to the clicked clip, so its start couldn't be confirmed "
              f"(the capture-fix safety check). Send this printout -- the check may need adjusting for this player.")
        print("  " + "!" * 100)
    elif len(_err):
        print("  Capture errors (first 3): " + " | ".join(_err.head(3)))
