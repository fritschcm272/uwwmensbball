# 55c_play_review.py -- code for the notebook section "Play review"
# Runs inside the notebook via run_section("55c_play_review"); its settings are in that notebook cell.

# --- Play review: the player checks and the Title review together, on 20 random plays per game ------------------------
# CONFIRMED CHANGE (requested: "combine the player-number review and the Title review into one file and do both at the
# same time; only 20 plays per game, a random set -- a different 20 when I run it again; a 'wrong team' option; and a
# gif of the play, the clip, or a link to Synergy").
#
# One page per game and run: INPUT_DIR/play_review/<game>/run_<date_time>/review.html. For each of the 20 plays:
#   * an animated GIF of the play -- the tracking frames at real speed, every player's box and assigned number drawn on;
#   * a link to the game on Synergy with the clip's number and where it starts in the game video;
#   * the START and END pictures with a row per box: correct / really <player on his team> / really <player on the OTHER
#     team> / wrong team (don't know who) / not a player;
#   * the Title review: the coach's Title, the automatic Title (held-out for tagged plays) and right / wrong / can't tell
#     per field, with a box for the right answer.
# ONE "Save" downloads play_review_<game>_<run>.json holding both the player checks and the Title answers; the parser
# picks it up from Downloads next run (player checks -> certain names, "wrong team" moves the player to the other team;
# Title answers -> scored, and labels for the Tag model on untagged plays).
import os
import re
import sys
import json
import random
import subprocess
import datetime as _pr_dt     # NOT "import datetime": the notebook's datetime is the class (section 01)
import html as _pr_html
import pandas as pd
import numpy as np


def _pr_reviewed_keys():
    """Clip keys already reviewed (any player check or Title answer saved)."""
    keys = set()
    try:
        for ch in coach_checks_all()[0]:
            keys.add(ch.get("clip_key"))
    except Exception:
        pass
    try:
        title_review_answers()
        keys |= {ck for (ck, _f) in (globals().get("_title_review_marks") or {})}
    except Exception:
        pass
    return keys


def _pr_boxes(rows, t, Hpx, numtxt):
    boxes = []
    for rr in sorted(rows, key=lambda x: (str(x.get("side")), str(x.get("name")))):
        p = next((p for p in _trk_json.loads(rr["path"]) if int(p[0]) == t and len(p) >= 6), None)
        if p is None or rr.get("side") not in ("offense", "defense"):
            continue
        hh = float(p[3]) * Hpx
        x, y = float(p[4]), float(p[5])
        named = isinstance(rr.get("name"), str)
        boxes.append({"id": chr(65 + len(boxes)) if len(boxes) < 26 else str(len(boxes)),
                      "track": int(rr["track"]), "side": rr["side"],
                      "box": [x - 0.21 * hh, y - hh, x + 0.21 * hh, y], "px": round(x, 1), "py": round(y, 1),
                      "name": rr.get("name") if named else None, "how": rr.get("name_how") if named else None,
                      "label": (numtxt(rr["name"]) + ("?" if rr.get("name_how") == "best guess" else "")) if named else "",
                      "guess": named and rr.get("name_how") == "best guess"})
    return boxes


def _pr_frames(files, rows, numtxt, every=1):
    """The play's tracking frames with every player's box and assigned number drawn on (PIL images)."""
    from PIL import Image, ImageDraw
    fps = float(globals().get("VISION_TRACK_FPS") or 2.0)
    font = _val_font(13) if "_val_font" in globals() else None
    out = []
    for t in range(0, len(files), every)[:400]:
        p_ = os.path.join(VISION_FRAMES_DIR, files[t])
        if not os.path.exists(p_):
            continue
        im = Image.open(p_).convert("RGB")
        W, H = im.size
        sc = PLAY_REVIEW_VIDEO_WIDTH / float(W)
        im = im.resize((PLAY_REVIEW_VIDEO_WIDTH // 2 * 2, int(H * sc) // 2 * 2))      # even sizes (video needs them)
        d = ImageDraw.Draw(im)
        for b in _pr_boxes(rows, t, H, numtxt):
            x1, y1, x2, y2 = [c * sc for c in b["box"]]
            col = (255, 150, 0) if b["side"] == "offense" else (60, 170, 255)
            d.rectangle([x1, y1, x2, y2], outline=col, width=1 if b["guess"] else 2)
            if b["label"]:
                d.text((x1, max(0, y1 - 13)), b["label"], fill=col, font=font)
        d.text((4, 2), f"{t / fps:4.1f} s", fill=(255, 255, 255), font=font)
        out.append(im)
    return out


def _pr_mp4_ok():
    """imageio + imageio-ffmpeg (a bundled ffmpeg) for small, browser-playable MP4s -- installed once if missing."""
    import importlib
    if importlib.util.find_spec("imageio_ffmpeg") is None or importlib.util.find_spec("imageio") is None:
        try:
            print("  [play review] installing imageio-ffmpeg (small videos of each play, one time)...", flush=True)
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "imageio", "imageio-ffmpeg"])
            importlib.invalidate_caches()
        except Exception as e:
            print(f"  [play review] couldn't install imageio-ffmpeg ({type(e).__name__}: {e}) -- using GIFs", flush=True)
            return False
    return importlib.util.find_spec("imageio_ffmpeg") is not None


def _pr_clip(files, rows, numtxt, out_base):
    """The play as a video (MP4, real speed, with play/pause) or an animated GIF -> file name, or None.
    CONFIRMED CHANGE: GIFs of a play were 3-7 MB each (~100 MB for 20 plays); an MP4 of the same frames is a small
    fraction of that and plays with a scrubber. GIF stays as the fallback (PLAY_REVIEW_VIDEO = "gif")."""
    fps = float(globals().get("VISION_TRACK_FPS") or 2.0)
    kind = PLAY_REVIEW_VIDEO
    if kind == "mp4" and not globals().setdefault("_pr_mp4_ready", _pr_mp4_ok()):
        kind = "gif"
    if kind == "mp4":
        frames = _pr_frames(files, rows, numtxt, every=1)
        if not frames:
            return None
        import imageio.v2 as imageio
        path = out_base + ".mp4"
        # crf 28: ~1 MB for a 45-second play -- for watching the play and the labels move (numbers are read in the
        # enlarged pictures below it)
        w = imageio.get_writer(path, fps=fps, codec="libx264", quality=None, macro_block_size=2, pixelformat="yuv420p",
                               ffmpeg_params=["-crf", "28", "-preset", "medium", "-movflags", "+faststart"])
        for im in frames:
            w.append_data(np.asarray(im))
        w.close()
        return os.path.basename(path)
    if kind == "gif":
        every = max(1, int(round(fps / 2.0)))                   # 2 frames a second, shown at real speed
        frames = _pr_frames(files, rows, numtxt, every=every)
        if not frames:
            return None
        from PIL import Image
        path = out_base + ".gif"
        pal = [im.convert("P", palette=Image.ADAPTIVE, colors=64) for im in frames]
        pal[0].save(path, save_all=True, append_images=pal[1:], duration=int(1000 * every / fps), loop=0, optimize=True)
        return os.path.basename(path)
    return None


def _pr_synergy(r):
    """(Synergy page link, clip position on that page) from the capture log."""
    cf = globals().get("clip_frames")
    if not isinstance(cf, pd.DataFrame) or cf.empty or "source_url" not in cf.columns:
        return None, None
    ff = str(r.get("frame_files") or "")
    hit = cf[cf.get("frame_files", pd.Series("", index=cf.index)).astype(str) == ff] if ff else cf.iloc[0:0]
    if hit.empty and "description" in cf.columns:
        hit = cf[cf["description"].astype(str).str.strip() == str(r.get("synergy_string") or "").strip()]
    if hit.empty:
        return None, None
    h = hit.iloc[0]
    return h.get("source_url"), h.get("position")


def play_review():
    pt = player_tracks if isinstance(globals().get("player_tracks"), pd.DataFrame) else pd.DataFrame()
    if pt.empty or "clip_key" not in pt.columns:
        print("Play review: no player tracks yet -- run Player tracking first.")
        return
    pc = play_calls[play_calls["track_files"].notna()].copy()
    if PLAY_REVIEW_ONLY_GAME:
        pc = pc[pc["game_code"].astype(str).str.contains(PLAY_REVIEW_ONLY_GAME, regex=False)]
    done = _pr_reviewed_keys() if PLAY_REVIEW_SKIP_REVIEWED else set()
    # how the automatic Title did on everything reviewed so far
    marks = globals().get("_title_review_marks") or {}
    rep = {}
    for (_ck, f), a in marks.items():
        if a.get("verdict") in ("right", "wrong"):
            rep.setdefault(f, [0, 0])
            rep[f][1] += 1
            rep[f][0] += int(a["verdict"] == "right")
    if rep:
        lab = dict(_TR_FIELDS) if "_TR_FIELDS" in globals() else {}
        print("Play review -- how often each field of the automatic Title was RIGHT on the plays reviewed so far: "
              + "; ".join(f"{lab.get(f, f)} {r_}/{n} ({100 * r_ / n:.0f}%)" for f, (r_, n) in rep.items()), flush=True)
    rng = random.Random(PLAY_REVIEW_SEED)
    stamp = _pr_dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    fps = float(globals().get("VISION_TRACK_FPS") or 2.0)
    min_c = float(globals().get("TAG_MODEL_MIN_CONFIDENCE", 0.6))
    for (gd, gc), g in pc.groupby(["game_date", "game_code"], dropna=False):
        g = g.assign(_key=[f"{r.get('game_date')}|{r.get('clip_number')}|{r.get('synergy_string')}" for _, r in g.iterrows()])
        fresh = g[~g["_key"].isin(done)]
        pool = fresh if len(fresh) else g
        pick = pool.loc[rng.sample(list(pool.index), min(PLAY_REVIEW_PLAYS_PER_GAME, len(pool)))].sort_values("clip_number")
        slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{gd}|{gc}").strip("_")
        rdir = os.path.join(INPUT_DIR, "play_review", slug, f"run_{stamp}")
        os.makedirs(rdir, exist_ok=True)
        gnums = _trk_numbers_for_game(gd, gc)
        numtxt = lambda n: f"#{gnums.get(str(n).lower(), '?')} {str(n).split()[-1]}"
        plays = []
        for _, r in pick.iterrows():
            files = [f for f in str(r["track_files"]).split(";") if f]
            rows = pt[pt["clip_key"] == r["track_clip_key"]].to_dict("records")
            n = len(files)
            cn = int(r["clip_number"])
            # pictures: the start and the end of the play, most players visible
            t_end = pd.to_numeric(r.get("track_finish_frame"), errors="coerce")
            end_hi = int(min(n - 1, t_end)) if pd.notna(t_end) else n - 1
            picks_ = [("start", _val_frame_pick(rows, 0, max(1, int(0.25 * n)))),
                      ("end", _val_frame_pick(rows, int(max(0, end_hi - 2 * fps)), end_hi, prefer_late=True))]
            clock = r.get("time_remaining_seconds")
            clock_txt = f"{r.get('period', '')} {int(clock // 60)}:{int(clock % 60):02d}" if pd.notna(clock) else "(no clock)"
            lu = lambda side: ", ".join(numtxt(nm) for nm in _trk_five(r.get(f"{side}_lineup"))) or "(lineup unknown)"
            pics = []
            for which, t in picks_:
                if t is None or t >= n or any(p_["t"] == t for p_ in pics):
                    continue
                img_path = os.path.join(VISION_FRAMES_DIR, files[t])
                if not os.path.exists(img_path):
                    continue
                from PIL import Image
                boxes = _pr_boxes(rows, t, Image.open(img_path).size[1], numtxt)
                header = [f"Clip {cn}  {clock_txt}  {str(r.get('synergy_string'))[:100]}",
                          f"{'START' if which == 'start' else 'END'} of the play -- {t / fps:.1f} s into the clip",
                          f"OFFENSE (orange) {r.get('offense_team')}: {lu('offense')}",
                          f"DEFENSE (blue)  {r.get('defense_team')}: {lu('defense')}",
                          "Solid box = identified from evidence; DASHED box with ? = best guess; grey = not named"]
                fname = f"clip_{cn:03d}_{'a_start' if which == 'start' else 'b_end'}.jpg"
                _val_draw(img_path, boxes, header, os.path.join(rdir, fname))
                pics.append({"which": which, "image": fname, "frame_file": files[t], "t": int(t), "boxes": boxes})
            clip_file = _pr_clip(files, rows, numtxt, os.path.join(rdir, f"clip_{cn:03d}")) if PLAY_REVIEW_VIDEO else None
            # the Title review part (same logic as the Auto-Title review)
            tagged = any(_tr_val(r.get(f"coach_{f}")) is not None for f, _ in _TR_FIELDS) if "_TR_FIELDS" in globals() else False
            fields = []
            for f, label in (_TR_FIELDS if "_TR_FIELDS" in globals() else []):
                cv = _tr_val(r.get(f"coach_{f}"))
                av, ac, note = _tr_auto(r, f, tagged)
                if cv is None and av is None:
                    continue
                sure = av is not None and ac is not None and ac >= min_c
                fields.append({"field": f, "label": label, "coach": cv, "auto": av, "conf": round(ac, 2) if ac is not None else None,
                               "sure": sure, "same": (_tr_same(cv, av) if cv is not None and sure else None), "note": note})
            url, pos = _pr_synergy(r)
            vs = pd.to_numeric(r.get("video_start_s"), errors="coerce")
            plays.append({"clip_key": r["_key"], "clip_number": cn, "clock": clock_txt,
                          "synergy": str(r.get("synergy_string") or ""), "coach_title": _tr_val(r.get("play_title")),
                          "auto_title": _tr_title(r, tagged) if "_tr_title" in globals() else None,
                          "film": _tr_film(r.get("track_clip_key")) if "_tr_film" in globals() else None,
                          "validation": bool(r.get("tag_validation")) if pd.notna(r.get("tag_validation")) else False,
                          "clip": clip_file, "synergy_url": url,
                          "synergy_pos": int(pos) if pd.notna(pos) else None,
                          "video_at": (f"{int(vs // 60)}:{int(vs % 60):02d}" if pd.notna(vs) else None),
                          "pictures": pics, "fields": fields,
                          "five": {"offense": _trk_five(r.get("offense_lineup")), "defense": _trk_five(r.get("defense_lineup"))}})
        page = os.path.join(rdir, "review.html")
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(_PR_PAGE.replace("__DATA__", json.dumps({"game": f"{gd}|{gc}", "slug": slug, "run": stamp,
                                                             "plays": plays}, default=str))
                     .replace("__TITLE__", _pr_html.escape(f"{gd} {gc}")))
        print(f"Play review: {gd} {gc}: {len(plays)} random play(s) ({len(g) - len(fresh)} already reviewed, left out) "
              f"-- open {page}", flush=True)


_PR_PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Play review -- __TITLE__</title>
<style>body{font-family:Arial,sans-serif;margin:14px;background:#f4f4f4}.play{background:#fff;margin:16px 0;padding:10px;
border:1px solid #ccc}img{max-width:100%;border:1px solid #999}table{border-collapse:collapse;font-size:13px;margin-top:6px}
td,th{border:1px solid #ddd;padding:3px 6px;vertical-align:top}.off{color:#c66a00;font-weight:bold}.def{color:#1e7fc8;font-weight:bold}
.t{font-family:Consolas,monospace;font-size:14px}.ok{background:#e3f4e3}.no{background:#fbe3e3}.uns{color:#888}
#bar{position:sticky;top:0;background:#4E2A84;color:#fff;padding:8px;z-index:5}button{padding:6px 12px}
.film{background:#eef3fb;padding:4px 6px;margin-top:4px;font-size:13px}h4{margin:12px 0 2px 0}
.nav a{margin-right:8px}</style></head><body>
<div id="bar">Play review -- __TITLE__ &nbsp; <button id="save">Save my review</button> <span id="cnt"></span></div>
<p>20 random plays. For each: watch the GIF (or open it on Synergy), check the players in the pictures, and check the
automatic Title. You don't have to finish -- save any time; everything you marked counts.</p>
<div class="nav" id="nav"></div><div id="plays"></div>
<script>
const D = __DATA__; const marks = {}, fixes = {};
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
document.getElementById('nav').innerHTML = 'Plays: ' + D.plays.map((p, i) => `<a href="#p${i}">#${p.clip_number}</a>`).join('');
const root = document.getElementById('plays');
D.plays.forEach((p, pi) => {
  let h = `<div class="play" id="p${pi}"${p.validation ? ' style="border:3px solid #4E2A84"' : ''}><h3>Clip ${p.clip_number} &nbsp; <small>${esc(p.clock)} &nbsp; ${esc(p.synergy)}</small>` +
          (p.validation ? ' <span style="background:#4E2A84;color:#fff;padding:2px 6px;font-size:12px">VALIDATION PLAY</span>' : '') + '</h3>';
  if (p.clip && p.clip.endsWith('.mp4')) h += `<video src="${esc(p.clip)}" controls loop muted playsinline style="max-width:560px;width:100%"></video>`;
  else if (p.clip) h += `<img src="${esc(p.clip)}" style="max-width:560px">`;
  h += '<div>';
  if (p.synergy_url) h += `<a href="${esc(p.synergy_url)}" target="_blank">Open the game on Synergy</a> -- clip #${p.clip_number}` +
                          (p.synergy_pos ? ` (row ${p.synergy_pos} of the clip list)` : '') + (p.video_at ? `, starts ${esc(p.video_at)} into the game video` : '');
  h += '</div><h4>Players</h4>';
  p.pictures.forEach((pic, ki) => {
    h += `<div><b>${pic.which === 'start' ? 'START of the play' : 'END of the play'}</b><br><img src="${esc(pic.image)}">` +
         '<table><tr><th>Box</th><th>Side</th><th>Assigned</th><th>Your check</th></tr>';
    pic.boxes.forEach((b, bi) => {
      const mine = (p.five[b.side] || []), other = (p.five[b.side === 'offense' ? 'defense' : 'offense'] || []);
      const opts = ['<option value="">-- not checked --</option>', '<option value="correct">correct</option>']
        .concat(mine.filter(n => n !== b.name).map(n => `<option value="same:${esc(n)}">really ${esc(n)}</option>`))
        .concat(other.map(n => `<option value="other:${esc(n)}">really ${esc(n)} (other team)</option>`))
        .concat(['<option value="__wrong_team__">wrong team (don\'t know who)</option>', '<option value="__not_a_player__">not a player</option>']);
      h += `<tr><td>${b.id}</td><td class="${b.side === 'offense' ? 'off' : 'def'}">${b.side}</td>` +
           `<td>${b.label ? esc(b.label) + ' <small>(' + esc(b.how || '') + ')</small>' : '<i>not named</i>'}</td>` +
           `<td><select data-k="pl_${pi}_${ki}_${bi}">${opts.join('')}</select></td></tr>`;
    });
    h += '</table></div>';
  });
  h += `<h4>Title</h4><table><tr><td><b>Coach's Title</b></td><td class="t">${p.coach_title ? esc(p.coach_title) : '<i>not tagged</i>'}</td></tr>` +
       `<tr><td><b>Automatic Title</b></td><td class="t">${p.auto_title ? esc(p.auto_title) : '<i>nothing confident enough yet</i>'}</td></tr></table>`;
  if (p.film) h += `<div class="film"><b>Seen on the film:</b> ${esc(p.film)}</div>`;
  if (p.fields.length) {
    h += '<table><tr><th>Field</th><th>Coach</th><th>Automatic</th><th>Your answer</th></tr>';
    p.fields.forEach((f, fi) => {
      const cls = f.same === true ? 'ok' : (f.same === false ? 'no' : '');
      const auto = f.auto == null ? `<i class="uns">${esc(f.note || 'no answer')}</i>` :
                   (f.sure ? `${esc(f.auto)} <small>(${Math.round(100*f.conf)}%)</small>` : `<span class="uns">unsure: ${esc(f.auto)} (${Math.round(100*(f.conf||0))}%)</span>`);
      h += `<tr class="${cls}"><td>${esc(f.label)}</td><td>${f.coach == null ? '' : esc(f.coach)}</td><td>${auto}</td>` +
           `<td><select data-k="ti_${pi}_${fi}"><option value="">--</option><option value="right">right</option>` +
           `<option value="wrong">wrong</option><option value="cant">can't tell</option></select> ` +
           `<input size="18" placeholder="right answer" data-k="ti_${pi}_${fi}"></td></tr>`;
    });
    h += '</table>';
  }
  root.insertAdjacentHTML('beforeend', h + '</div>');
});
const upd = () => document.getElementById('cnt').textContent = Object.keys(marks).length + ' answer(s) marked';
document.querySelectorAll('select').forEach(s => s.onchange = () => { if (s.value) marks[s.dataset.k] = s.value; else delete marks[s.dataset.k]; upd(); });
document.querySelectorAll('input').forEach(i => i.oninput = () => { fixes[i.dataset.k] = i.value; });
document.getElementById('save').onclick = () => {
  const out = {game: D.game, run: D.run, saved: new Date().toISOString(), checks: [], answers: []};
  for (const [k, v] of Object.entries(marks)) {
    const parts = k.split('_');
    if (parts[0] === 'pl') {
      const [pi, ki, bi] = parts.slice(1).map(Number); const p = D.plays[pi], pic = p.pictures[ki], b = pic.boxes[bi];
      let verdict, name = null;
      if (v === 'correct') { verdict = 'correct'; name = b.name; }
      else if (v === '__not_a_player__') verdict = 'not a player';
      else if (v === '__wrong_team__') verdict = 'wrong team';
      else if (v.startsWith('same:')) { verdict = 'wrong'; name = v.slice(5); }
      else if (v.startsWith('other:')) { verdict = 'wrong team'; name = v.slice(6); }
      out.checks.push({clip_key: p.clip_key, clip_number: p.clip_number, frame_file: pic.frame_file, t: pic.t, px: b.px, py: b.py,
                       side: b.side, assigned: b.name, assigned_how: b.how, verdict: verdict, true_name: name});
    } else {
      const [pi, fi] = parts.slice(1).map(Number); const p = D.plays[pi], f = p.fields[fi];
      out.answers.push({clip_key: p.clip_key, clip_number: p.clip_number, field: f.field, coach: f.coach, auto: f.auto,
                        auto_conf: f.conf, verdict: v === 'cant' ? "can't tell" : v, correct: fixes[k] || null});
    }
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {type: 'application/json'}));
  a.download = 'play_review_' + D.slug + '_' + D.run + '.json'; a.click();
};
</script></body></html>"""

if RUN_PLAY_REVIEW:
    try:
        play_review()
    except Exception as _e:
        print(f"Play review skipped: {type(_e).__name__}: {_e}")
