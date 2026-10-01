# 52_validation_pictures.py -- code for the notebook section "Validation pictures: one picture per clip with every player's assigned number, and a page "
# Runs inside the notebook via run_section("52_validation_pictures"); its settings are in that notebook cell.

# --- Validation pictures: one picture per clip with every player's assigned number, and a page to check them --------
# CONFIRMED CHANGE (requested: "note on the video screen captures which number you assigned to each player, so I can
# look at 1 clip per possession and validate the 10 players on the court"). For every tracked clip:
#   * ONE picture, at the moment the most players are visible and named: every player boxed with a letter and his
#     assigned number + name ("C  #21 Marino"); offense ORANGE, defense BLUE; a BEST GUESS is drawn DASHED with a "?";
#     boxes left unnamed (extras beyond five -- referees, sideline) thin grey. Header: clip, clock, play, both lineups.
#   * review.html next to the pictures: each picture with a row per box -- correct / who it really is (that team's five)
#     / not a player. "Save" downloads track_validation_<game>.json; the parser picks it up from Downloads (like the
#     court calibration). Next run your marks are CERTAIN names (they outrank everything and teach each player's look),
#     and the run prints how often each naming method was actually right on the players you checked.
import base64 as _val_b64
import os
import re
import glob
import json as _trk_json
import html as _val_html

# CONFIRMED CHANGE (requested: "review 2 frames per play -- the first one and the last one"). Each play gets TWO pictures:
# near its START (the first quarter of the clip) and at its END -- the moment the play ends (shot / turnover / foul),
# because clips run on past the play, often into the next possession. "clip_end" = the clip's very last frames instead.
# In each window the picture is the frame where the most players are visible.


def _val_frame_pick(tr_rows, lo, hi, prefer_late=False):
    """The frame in [lo, hi] where the most players are visible (ties -> the earliest, or the latest)."""
    count = {}
    for r in tr_rows:
        if r.get("side") not in ("offense", "defense"):
            continue
        for p in _trk_json.loads(r["path"]):
            t = int(p[0])
            if lo <= t <= hi:
                count[t] = count.get(t, 0) + 1
    if not count:
        return None
    return max(count, key=lambda t: (count[t], t if prefer_late else -t))


def _val_font(size):
    from PIL import ImageFont
    for f in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _val_draw(img_path, boxes, header_lines, out_path, scale=1.6):
    """Picture enlarged (scale), bigger font, labels that would overlap stacked upward with a line to their box."""
    from PIL import Image, ImageDraw
    im = Image.open(img_path).convert("RGB")
    W, H = im.size
    im = im.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
    fh, fl = _val_font(18), _val_font(17)
    head_h = 24 * len(header_lines) + 10
    canvas = Image.new("RGB", (im.size[0], im.size[1] + head_h), (20, 20, 20))
    canvas.paste(im, (0, head_h))
    d = ImageDraw.Draw(canvas)
    for n_, line in enumerate(header_lines):
        d.text((8, 5 + 24 * n_), line, fill=(255, 255, 255), font=fh)
    placed = []                                            # label rectangles already drawn
    for b in sorted(boxes, key=lambda b: b["box"][1]):     # top-most players first
        x1, y1, x2, y2 = [c * scale for c in b["box"]]
        y1 += head_h
        y2 += head_h
        col = {"offense": (255, 150, 0), "defense": (60, 170, 255)}.get(b["side"], (150, 150, 150))
        if b["guess"]:
            for yy in range(int(y1), int(y2), 10):
                d.line([(x1, yy), (x1, min(yy + 5, y2))], fill=col, width=3)
                d.line([(x2, yy), (x2, min(yy + 5, y2))], fill=col, width=3)
            for xx in range(int(x1), int(x2), 10):
                d.line([(xx, y1), (min(xx + 5, x2), y1)], fill=col, width=3)
                d.line([(xx, y2), (min(xx + 5, x2), y2)], fill=col, width=3)
        else:
            d.rectangle([x1, y1, x2, y2], outline=col, width=1 if not b["label"] else 4)
        tag = f"{b['id']}  {b['label']}" if b["label"] else b["id"]
        tw = int(d.textlength(tag, font=fl)) + 10
        th = 22
        lx, ly = x1, y1 - th - 2
        # move up until it no longer overlaps an earlier label
        for _ in range(12):
            if not any(lx < px2 and lx + tw > px1 and ly < py2 and ly + th > py1 for px1, py1, px2, py2 in placed):
                break
            ly -= th + 2
        ly = max(head_h, ly)
        placed.append((lx, ly, lx + tw, ly + th))
        if ly + th < y1 - 2:
            d.line([(lx + 6, ly + th), (x1 + 6, y1)], fill=col, width=2)
        d.rectangle([lx, ly, lx + tw, ly + th], fill=col if b["label"] else (90, 90, 90))
        d.text((lx + 5, ly + 2), tag, fill=(0, 0, 0) if b["label"] else (235, 235, 235), font=fl)
    canvas.save(out_path, quality=90)


def validation_pictures():
    os.makedirs(VALIDATION_DIR, exist_ok=True)
    pt = player_tracks if isinstance(globals().get("player_tracks"), pd.DataFrame) else pd.DataFrame()
    if pt.empty or "clip_key" not in pt.columns:
        print("Validation pictures: no player tracks yet.")
        return
    pc = play_calls[play_calls["track_files"].notna()].copy()
    if VALIDATION_ONLY_GAME:
        pc = pc[pc["game_code"].astype(str).str.contains(VALIDATION_ONLY_GAME, regex=False)]
    num_of = {}
    for team_book in (_pl_jersey_book() if "_pl_jersey_book" in globals() else {}).values():
        for j_, n_ in team_book.items():
            num_of.setdefault(str(n_).strip().lower(), str(j_).strip())
    for ss in play_calls["synergy_string"].dropna().astype(str):
        for j_, n_ in re.findall(r"(?:^|>)\s*(\d{1,2})\s+([A-Za-z][^>]*?)\s*(?=>|$)", ss):
            num_of[n_.strip().lower()] = j_
    numtxt = lambda n: f"#{_gnums.get(str(n).lower(), '?')} {str(n).split()[-1]}"
    pages = {}
    for (gd, gc), g in pc.groupby(["game_date", "game_code"], dropna=False):
        g = g.sort_values("clip_number")
        if VALIDATION_MAX_CLIPS:
            g = g.head(VALIDATION_MAX_CLIPS)
        game_key = f"{gd}|{gc}"
        _gnums = _trk_numbers_for_game(gd, gc)             # this game's numbers (Madson #15, not a stray #0)
        slug = re.sub(r"[^A-Za-z0-9]+", "_", game_key).strip("_")
        gdir = os.path.join(VALIDATION_DIR, slug)
        os.makedirs(gdir, exist_ok=True)
        clips_out = []
        for _, r in g.iterrows():
            files = [f for f in str(r["track_files"]).split(";") if f]
            rows = pt[pt["clip_key"] == r["track_clip_key"]].to_dict("records")
            n = len(files)
            fps = float(globals().get("VISION_TRACK_FPS") or 2.0)
            t_end = pd.to_numeric(r.get("track_finish_frame"), errors="coerce")
            if VALIDATION_LAST == "clip_end" or pd.isna(t_end):
                end_lo, end_hi = int(0.75 * n), n - 1
            else:
                end_hi = int(min(n - 1, t_end))
                end_lo = int(max(0, end_hi - 2 * fps))
            picks = [("start", _val_frame_pick(rows, 0, max(1, int(0.25 * n)))),
                     ("end", _val_frame_pick(rows, end_lo, end_hi, prefer_late=True))]
            clock = r.get("time_remaining_seconds")
            clock_txt = f"{r.get('period', '')} {int(clock // 60)}:{int(clock % 60):02d}" if pd.notna(clock) else "(no clock)"
            lu = lambda side: ", ".join(numtxt(nm) for nm in _trk_five(r.get(f"{side}_lineup"))) or "(lineup unknown)"
            pics = []
            for which, t in picks:
                if t is None or t >= n or any(p_["t"] == t for p_ in pics):
                    continue
                img_path = os.path.join(VISION_FRAMES_DIR, files[t])
                if not os.path.exists(img_path):
                    continue
                from PIL import Image
                Hpx = Image.open(img_path).size[1]
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
                                  "box": [x - 0.21 * hh, y - hh, x + 0.21 * hh, y],
                                  "px": round(x, 1), "py": round(y, 1),
                                  "name": rr.get("name") if named else None, "how": rr.get("name_how") if named else None,
                                  "label": (numtxt(rr["name"]) + ("?" if rr.get("name_how") == "best guess" else "")) if named else "",
                                  "guess": named and rr.get("name_how") == "best guess"})
                secs = t / fps
                header = [f"Clip {r['clip_number']}  {clock_txt}  {str(r.get('synergy_string'))[:100]}",
                          f"{'START' if which == 'start' else 'END'} of the play -- {secs:.1f} s into the clip",
                          f"OFFENSE (orange) {r.get('offense_team')}: {lu('offense')}",
                          f"DEFENSE (blue)  {r.get('defense_team')}: {lu('defense')}",
                          "Solid box = identified from evidence; DASHED box with ? = best guess; grey = not named"]
                fname = f"clip_{int(r['clip_number']):03d}_{'a_start' if which == 'start' else 'b_end'}.jpg"
                _val_draw(img_path, boxes, header, os.path.join(gdir, fname))
                pics.append({"which": which, "image": fname, "frame_file": files[t], "t": int(t), "boxes": boxes})
            if pics:
                clips_out.append({"clip_key": r["track_clip_key"], "clip_number": int(r["clip_number"]), "pictures": pics,
                                  "five": {"offense": _trk_five(r.get("offense_lineup")),
                                           "defense": _trk_five(r.get("defense_lineup"))}})
        page = os.path.join(gdir, "review.html")
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(_VAL_PAGE.replace("__DATA__", _trk_json.dumps({"game": game_key, "slug": slug, "clips": clips_out}))
                     .replace("__TITLE__", _val_html.escape(game_key)))
        pages[game_key] = (page, len(clips_out))
    for gk, (page, n) in pages.items():
        print(f"Validation pictures: {gk}: {n} play(s), a START and an END picture each -- open {page} to check them")


_VAL_PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Check the players -- __TITLE__</title>
<style>body{font-family:Arial,sans-serif;margin:14px;background:#f4f4f4}.clip{background:#fff;margin:14px 0;padding:10px;
border:1px solid #ccc}img{max-width:100%;border:1px solid #999}table{border-collapse:collapse;margin-top:6px;font-size:13px}
td,th{border:1px solid #ddd;padding:3px 6px}.off{color:#c66a00;font-weight:bold}.def{color:#1e7fc8;font-weight:bold}
#bar{position:sticky;top:0;background:#4E2A84;color:#fff;padding:8px;z-index:5}button{padding:6px 12px}</style></head><body>
<div id="bar">Check the players -- __TITLE__ &nbsp; <button id="save">Save my checks</button> <span id="cnt"></span></div>
<p>For every box: leave <b>correct</b> if the number/name is right, pick who it really is, or <b>not a player</b>. You don't
have to check every box -- save any time; the parser uses whatever you marked. Dashed boxes with "?" are best guesses.</p>
<div id="clips"></div>
<script>
const D = __DATA__; const marks = {};
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const root = document.getElementById('clips');
D.clips.forEach((c, ci) => {
  let h = `<div class="clip"><h3>Clip ${c.clip_number}</h3>`;
  c.pictures.forEach((pic, pi) => {
    h += `<div style="margin:6px 0 14px 0"><b>${pic.which === 'start' ? 'START of the play' : 'END of the play'}</b><br>` +
         `<img src="${pic.image}"><table><tr><th>Box</th><th>Side</th><th>Assigned</th><th>Your check</th></tr>`;
    pic.boxes.forEach((b, bi) => {
      const opts = ['<option value="">-- not checked --</option>', '<option value="correct">correct</option>']
        .concat((c.five[b.side] || []).filter(n => n !== b.name).map(n => `<option value="${esc(n)}">really ${esc(n)}</option>`))
        .concat(['<option value="__not_a_player__">not a player</option>']);
      h += `<tr><td>${b.id}</td><td class="${b.side === 'offense' ? 'off' : 'def'}">${b.side}</td>` +
           `<td>${b.label ? esc(b.label) + ' <small>(' + esc(b.how || '') + ')</small>' : '<i>not named</i>'}</td>` +
           `<td><select data-c="${ci}" data-p="${pi}" data-b="${bi}">${opts.join('')}</select></td></tr>`;
    });
    h += '</table></div>';
  });
  root.insertAdjacentHTML('beforeend', h + '</div>');
});
document.querySelectorAll('select').forEach(s => s.onchange = () => {
  const k = s.dataset.c + '_' + s.dataset.p + '_' + s.dataset.b; if (s.value) marks[k] = s.value; else delete marks[k];
  document.getElementById('cnt').textContent = Object.keys(marks).length + ' box(es) checked';
});
document.getElementById('save').onclick = () => {
  const out = {game: D.game, saved: new Date().toISOString(), checks: []};
  for (const [k, v] of Object.entries(marks)) {
    const [ci, pi, bi] = k.split('_').map(Number); const c = D.clips[ci], pic = c.pictures[pi], b = pic.boxes[bi];
    out.checks.push({clip_key: c.clip_key, clip_number: c.clip_number, frame_file: pic.frame_file, t: pic.t,
      px: b.px, py: b.py, side: b.side, assigned: b.name, assigned_how: b.how,
      verdict: v === 'correct' ? 'correct' : (v === '__not_a_player__' ? 'not a player' : 'wrong'),
      true_name: v === 'correct' ? b.name : (v === '__not_a_player__' ? null : v)});
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {type: 'application/json'}));
  a.download = 'track_validation_' + D.slug + '.json'; a.click();
};
</script></body></html>"""

if RUN_VALIDATION_PICTURES:
    try:
        validation_pictures()
    except Exception as _e:
        print(f"Validation pictures skipped: {type(_e).__name__}: {_e}")
