# 55b_auto_title_review.py -- code for the notebook section "Auto-Title review"
# Runs inside the notebook via run_section("55b_auto_title_review"); its settings are in that notebook cell.

# --- Auto-Title review: the coaches' Title next to the Title the parser builds on its own, play by play ---------------
# CONFIRMED CHANGE (requested: "replace the Title column with something an algorithm creates from the video frames --
# and a review, like the player tagging, showing the coaches' Title and what you came up with for each play").
#
# The automatic Title is built from what the parser can see WITHOUT the coach's Title:
#   * the Tag model's predictions -- formation, play call, situation, main action, defense, press, coverages, screener,
#     screen defender -- learned from Synergy's description of the play, the 5 key frames and the players' positions.
#     For a clip the coaches tagged it shows the HELD-OUT prediction (made while that clip was left out of training), so
#     the comparison is honest -- a model that saw the clip's Title would just repeat it.
#   * what tracking saw on the film: the screen (type, screener, player screened, both defenders) and the coverage the
#     players' movements suggest.
# Only predictions at TAG_MODEL_MIN_CONFIDENCE or above go into the automatic Title; the rest show as "unsure".
#
# review_titles.html (INPUT_DIR/title_review/<game>/) shows each play's picture, the coach's Title, the automatic Title,
# and a field-by-field table with a right / wrong / can't-tell control and a box for the right answer. "Save" downloads
# title_review_<game>.json -- picked up from Downloads like the player checks. Next run your answers are:
#   * scored: how often each field of the automatic Title was right (printed here),
#   * labels for the Tag model on clips the coaches never tagged -- reviewing works like tagging, faster.
import os
import re
import json
import html as _tr_html
import pandas as pd
import numpy as np

_TR_FIELDS = [("situation", "Situation"), ("formation", "Formation"), ("play_call", "Play call"),
              ("primary_action", "Main action"), ("defense", "Defense"), ("press", "Press"),
              ("ball_screen_coverage", "Ball-screen coverage"), ("offball_coverage", "Off-ball coverage"),
              ("screener", "Screener"), ("screen_defender", "Screen defender")]


def _tr_val(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    s = str(v).strip()
    return None if s in ("", "None", "nan") else s


def _tr_same(a, b):
    norm = lambda x: re.sub(r"[^a-z0-9#]+", "", str(x).lower())
    return norm(a) == norm(b)


def _tr_auto(r, f, tagged):
    """The automatic answer for one field: (value, confidence, note)."""
    if tagged:
        v, c = _tr_val(r.get(f"heldout_{f}")), r.get(f"heldout_{f}_conf")
        if v is None and _tr_val(r.get(f"pred_{f}")) is not None:
            return None, None, "held-out answer not available until the Tag model retrains"
        return v, (float(c) if pd.notna(c) else None), ""
    v, c = _tr_val(r.get(f"pred_{f}")), r.get(f"pred_{f}_conf")
    return v, (float(c) if pd.notna(c) else None), ""


def _tr_title(r, tagged):
    """The automatic Title in the coaches' shorthand -- the Tag model's own builder, fed the (held-out) answers."""
    rr = dict(r)
    for f, _lab in _TR_FIELDS:
        v, c, _n = _tr_auto(r, f, tagged)
        rr[f"pred_{f}"], rr[f"pred_{f}_conf"] = v, (c if c is not None else np.nan)
    try:
        return _tm_suggest(rr) if "_tm_suggest" in globals() else None
    except Exception:
        return None


def _tr_film(key):
    """What tracking saw on the film for this clip: a sentence, or None."""
    scr = (globals().get("_ti_tables") or {}).get("uww_trk_screens")
    if not isinstance(scr, pd.DataFrame) or scr.empty or "clip_key" not in scr.columns:
        return None
    rows = scr[scr["clip_key"] == key]
    if rows.empty:
        return None
    s = rows.iloc[0]
    who = lambda x: x if isinstance(x, str) and x else "an unnamed player"
    txt = f"{s.get('screen_type') or 'Screen'}: {who(s.get('screener'))} screened for {who(s.get('screened'))}"
    d1, d2 = s.get("screened_defender"), s.get("screener_defender")
    if isinstance(d1, str) or isinstance(d2, str):
        txt += f"; defended by {who(d1)} (on the player screened) and {who(d2)} (on the screener)"
    est = s.get("coverage_tracking_estimate")
    if isinstance(est, str) and est:
        txt += f"; coverage from the players' movement: {est}"
    conf = s.get("confidence")
    if pd.notna(conf):
        txt += f" (screen confidence {float(conf):.0%})"
    return txt


def _tr_picture(r, gdir):
    """The play's START picture from the validation pictures (boxes and numbers), else its first key frame."""
    vdir = os.path.join(INPUT_DIR, "track_validation", re.sub(r"[^A-Za-z0-9]+", "_",
                                                            f"{r.get('game_date')}|{r.get('game_code')}").strip("_"))
    for name in (f"clip_{int(r['clip_number']):03d}_a_start.jpg", f"clip_{int(r['clip_number']):03d}.jpg"):
        p = os.path.join(vdir, name)
        if os.path.exists(p):
            return os.path.relpath(p, gdir).replace("\\", "/")
    ff = [f for f in str(r.get("frame_files") or "").split(";") if f]
    ver = int(globals().get("VISION_CAPTURE_VERSION", 1))
    if ff and ver >= 2 and f"_v{ver}_" not in ff[0]:
        return None                                   # captured before the clip-start fix: may show a different play
    if ff:
        p = os.path.join(globals().get("VISION_FRAMES_DIR") or os.path.join(INPUT_DIR, "_vision_frames"), ff[0])
        if os.path.exists(p):
            return os.path.relpath(p, gdir).replace("\\", "/")
    return None


def auto_title_review():
    pc = play_calls.copy()
    if not any(c.startswith("pred_") for c in pc.columns):
        print("Auto-Title review: no Tag model predictions yet -- run the Tag model section first.")
        return
    if TITLE_REVIEW_ONLY_GAME:
        pc = pc[pc["game_code"].astype(str).str.contains(TITLE_REVIEW_ONLY_GAME, regex=False)
                | pc.get("game", pd.Series("", index=pc.index)).astype(str).str.contains(TITLE_REVIEW_ONLY_GAME, regex=False)]
    # --- last run's review answers: how often each field was right ---
    title_review_answers()
    marks = globals().get("_title_review_marks", {})
    if marks:
        rep = {}
        for (_ck, f), a in marks.items():
            if a.get("verdict") in ("right", "wrong"):
                rep.setdefault(f, [0, 0])
                rep[f][1] += 1
                rep[f][0] += int(a["verdict"] == "right")
        lab = dict(_TR_FIELDS)
        print("Auto-Title review -- how often each field of the automatic Title was RIGHT on the plays you reviewed: "
              + "; ".join(f"{lab.get(f, f)} {r_}/{n} ({100 * r_ / n:.0f}%)" for f, (r_, n) in rep.items()), flush=True)
    min_c = float(globals().get("TAG_MODEL_MIN_CONFIDENCE", 0.6))
    out_dir = os.path.join(INPUT_DIR, "title_review")
    for (gd, gc), g in pc.groupby(["game_date", "game_code"], dropna=False):
        g = g.sort_values("clip_number")
        slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{gd}|{gc}").strip("_")
        gdir = os.path.join(out_dir, slug)
        os.makedirs(gdir, exist_ok=True)
        clips, agree = [], {f: [0, 0] for f, _ in _TR_FIELDS}
        agree_v = {f: [0, 0] for f, _ in _TR_FIELDS}
        for _, r in g.iterrows():
            coach_title = _tr_val(r.get("play_title"))
            tagged = any(_tr_val(r.get(f"coach_{f}")) is not None for f, _ in _TR_FIELDS)
            is_valid = bool(r.get("tag_validation")) if pd.notna(r.get("tag_validation")) else False
            if not tagged and not TITLE_REVIEW_INCLUDE_UNTAGGED:
                continue
            if globals().get("TITLE_REVIEW_ONLY_VALIDATION") and not is_valid:
                continue
            key = f"{r.get('game_date')}|{r.get('clip_number')}|{r.get('synergy_string')}"
            fields = []
            for f, label in _TR_FIELDS:
                cv = _tr_val(r.get(f"coach_{f}"))
                av, ac, note = _tr_auto(r, f, tagged)
                sure = av is not None and ac is not None and ac >= min_c
                same = None
                if cv is not None and sure:
                    same = _tr_same(cv, av)
                    agree[f][1] += 1
                    agree[f][0] += int(same)
                    if is_valid:
                        agree_v[f][1] += 1
                        agree_v[f][0] += int(same)
                if cv is None and av is None:
                    continue
                fields.append({"field": f, "label": label, "coach": cv, "auto": av,
                               "conf": round(ac, 2) if ac is not None else None, "sure": sure, "same": same, "note": note})
            clips.append({"clip_key": key, "clip_number": int(r["clip_number"]),
                          "clock": (f"{r.get('period', '')} {int(r['time_remaining_seconds'] // 60)}:"
                                    f"{int(r['time_remaining_seconds'] % 60):02d}")
                          if pd.notna(r.get("time_remaining_seconds")) else "(no clock)",
                          "synergy": _tr_val(r.get("synergy_string")) or "", "coach_title": coach_title,
                          "auto_title": _tr_title(r, tagged), "tagged": tagged, "film": _tr_film(r.get("track_clip_key") or key),
                          "picture": _tr_picture(r, gdir), "fields": fields, "validation": is_valid,
                          "old_frames": bool(str(r.get("frame_files") or "")) and int(globals().get("VISION_CAPTURE_VERSION", 1)) >= 2
                                        and f"_v{int(globals().get('VISION_CAPTURE_VERSION', 1))}_" not in str(r.get("frame_files"))})
            if TITLE_REVIEW_MAX_CLIPS and len(clips) >= TITLE_REVIEW_MAX_CLIPS:
                break
        if not clips:
            continue
        score = [{"label": lab, "agree": a, "compared": n} for (f, lab) in _TR_FIELDS for a, n in [agree[f]] if n]
        score_v = [{"label": lab, "agree": a, "compared": n} for (f, lab) in _TR_FIELDS for a, n in [agree_v[f]] if n]
        page = os.path.join(gdir, "review_titles.html")
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(_TR_PAGE.replace("__DATA__", json.dumps({"game": f"{gd}|{gc}", "slug": slug, "clips": clips,
                                                             "score": score, "score_v": score_v}, default=str))
                     .replace("__TITLE__", _tr_html.escape(f"{gd} {gc}")))
        n_tag = sum(c["tagged"] for c in clips)
        print(f"Auto-Title review: {gd} {gc}: {len(clips)} play(s) ({n_tag} tagged by a coach, {len(clips) - n_tag} not) "
              f"-- open {page}", flush=True)
        if score_v:
            print(f"  VALIDATION plays ({sum(c['validation'] for c in clips)}, never trained on) -- automatic vs the coaches' "
                  "Title: " + "; ".join(f"{s['label']} {s['agree']}/{s['compared']}" for s in score_v), flush=True)
        if score:
            print("  automatic vs the coaches' Title (confident answers only): "
                  + "; ".join(f"{s['label']} {s['agree']}/{s['compared']} ({100 * s['agree'] / s['compared']:.0f}%)"
                              for s in score), flush=True)


_TR_PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Automatic Titles -- __TITLE__</title>
<style>body{font-family:Arial,sans-serif;margin:14px;background:#f4f4f4}.clip{background:#fff;margin:14px 0;padding:10px;
border:1px solid #ccc}img{max-width:100%;border:1px solid #999}table{border-collapse:collapse;font-size:13px;margin-top:6px}
td,th{border:1px solid #ddd;padding:3px 6px;vertical-align:top}.t{font-family:Consolas,monospace;font-size:14px}
.ok{background:#e3f4e3}.no{background:#fbe3e3}.uns{color:#888}#bar{position:sticky;top:0;background:#4E2A84;color:#fff;
padding:8px;z-index:5}button{padding:6px 12px}.film{background:#eef3fb;padding:4px 6px;margin-top:4px;font-size:13px}
.score td{text-align:center}</style></head><body>
<div id="bar">Automatic Titles -- __TITLE__ &nbsp; <button id="save">Save my answers</button> <span id="cnt"></span></div>
<p>Each play: the coach's Title, the Title the parser built on its own, and every field side by side. For plays a coach
tagged, the automatic answer was made <b>without</b> learning from that play's Title. Mark each automatic answer
<b>right</b> or <b>wrong</b> (and type the right one), or <b>can't tell</b>. Save any time -- partial reviews count.</p>
<div id="score"></div><div id="clips"></div>
<script>
const D = __DATA__; const marks = {}, fixes = {};
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
if (D.score.length) {
  let h = '<table class="score"><tr><th>Field</th>' + D.score.map(s => `<th>${esc(s.label)}</th>`).join('') + '</tr>' +
          '<tr><td>automatic = coach</td>' + D.score.map(s => `<td>${s.agree}/${s.compared} (${Math.round(100*s.agree/s.compared)}%)</td>`).join('') + '</tr></table>';
  document.getElementById('score').innerHTML = '<b>How often the automatic answer matches the coaches\' Title</b> (confident answers only)' + h;
}
if (D.score_v && D.score_v.length) {
  const nv = D.clips.filter(c => c.validation).length;
  let h = '<table class="score"><tr><th>Field</th>' + D.score_v.map(s => `<th>${esc(s.label)}</th>`).join('') + '</tr>' +
          '<tr><td>automatic = coach</td>' + D.score_v.map(s => `<td>${s.agree}/${s.compared} (${Math.round(100*s.agree/s.compared)}%)</td>`).join('') + '</tr></table>';
  document.getElementById('score').insertAdjacentHTML('beforeend', `<p><b>VALIDATION plays only</b> (${nv} tagged plays the model has NEVER trained on -- the fairest test)</p>` + h);
}
const root = document.getElementById('clips');
D.clips.forEach((c, ci) => {
  let h = `<div class="clip"${c.validation ? ' style="border:3px solid #4E2A84"' : ''}><h3>Clip ${c.clip_number} &nbsp; <small>${esc(c.clock)} &nbsp; ${esc(c.synergy)}</small>` +
          (c.validation ? ' <span style="background:#4E2A84;color:#fff;padding:2px 6px;font-size:12px">VALIDATION PLAY -- never trained on</span>' : '') + '</h3>';
  if (c.picture) h += `<img src="${esc(c.picture)}">`;
  else if (c.old_frames) h += '<p><i>No picture: this game\'s frames were captured before the clip-start fix and may show a different play -- recapture the game to see it.</i></p>';
  h += `<table><tr><td><b>Coach's Title</b></td><td class="t">${c.coach_title ? esc(c.coach_title) : '<i>not tagged</i>'}</td></tr>` +
       `<tr><td><b>Automatic Title</b></td><td class="t">${c.auto_title ? esc(c.auto_title) : '<i>nothing confident enough yet</i>'}</td></tr></table>`;
  if (c.film) h += `<div class="film"><b>Seen on the film:</b> ${esc(c.film)}</div>`;
  h += '<table><tr><th>Field</th><th>Coach</th><th>Automatic</th><th>Your answer</th></tr>';
  c.fields.forEach((f, fi) => {
    const cls = f.same === true ? 'ok' : (f.same === false ? 'no' : '');
    const auto = f.auto == null ? `<i class="uns">${esc(f.note || 'no answer')}</i>` :
                 (f.sure ? `${esc(f.auto)} <small>(${Math.round(100*f.conf)}%)</small>` : `<span class="uns">unsure: ${esc(f.auto)} (${Math.round(100*(f.conf||0))}%)</span>`);
    h += `<tr class="${cls}"><td>${esc(f.label)}</td><td>${f.coach == null ? '' : esc(f.coach)}</td><td>${auto}</td>` +
         `<td><select data-c="${ci}" data-f="${fi}"><option value="">--</option><option value="right">right</option>` +
         `<option value="wrong">wrong</option><option value="cant">can't tell</option></select> ` +
         `<input size="18" placeholder="right answer" data-c="${ci}" data-f="${fi}"></td></tr>`;
  });
  root.insertAdjacentHTML('beforeend', h + '</table></div>');
});
const upd = () => document.getElementById('cnt').textContent = Object.keys(marks).length + ' answer(s) marked';
document.querySelectorAll('select').forEach(s => s.onchange = () => {
  const k = s.dataset.c + '_' + s.dataset.f; if (s.value) marks[k] = s.value; else delete marks[k]; upd(); });
document.querySelectorAll('input').forEach(i => i.oninput = () => { fixes[i.dataset.c + '_' + i.dataset.f] = i.value; });
document.getElementById('save').onclick = () => {
  const out = {game: D.game, saved: new Date().toISOString(), answers: []};
  for (const [k, v] of Object.entries(marks)) {
    const [ci, fi] = k.split('_').map(Number); const c = D.clips[ci], f = c.fields[fi];
    out.answers.push({clip_key: c.clip_key, clip_number: c.clip_number, field: f.field, coach: f.coach, auto: f.auto,
                      auto_conf: f.conf, verdict: v === 'cant' ? "can't tell" : v, correct: fixes[k] || null});
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {type: 'application/json'}));
  a.download = 'title_review_' + D.slug + '.json'; a.click();
};
</script></body></html>"""

if RUN_TITLE_REVIEW:
    try:
        auto_title_review()
    except Exception as _e:
        print(f"Auto-Title review skipped: {type(_e).__name__}: {_e}")
