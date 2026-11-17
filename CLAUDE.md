# CLAUDE.md — handoff notes for a new chat

Read this first in any new chat about the UW-Whitewater (UWW) men's basketball scouting project.
Last updated: Nov 14, 2026. Owner: Corey. (Sections 0, 4, 7, 9 and 10 are current; section 8 is the Nov 2 history.)

---

## 0. "Update all scouting briefs" -- what that means (READ THIS)

There are several kinds of scouting brief. When Corey asks to **update all scouting briefs** (or to change something "in the
briefs"), every one of them must be updated / re-run, and a change to the brief code (`87_build_html_scouting_brief_for_upcoming.py`)
must work for all of them:

| Brief | Built by | Output |
|---|---|---|
| **Upcoming opponent brief** -- our next game. Its *type* is picked automatically (`brief_type_for`, `BRIEF_TYPE = "auto"`): **preseason** (scrimmage / exhibition before the season, on last season's numbers), **first games** (either team has played < `BRIEF_FIRST_GAMES_MIN` = 3 games this season: small samples shown next to last season), **regular** | `parser_brief.ipynb` (`run_parser("brief")`; `REFERENCE_DATE` / `EXTRA_GAMES` in its first cell) | `data\scouting_briefs\scouting_brief_<team>.html` |
| **No-seniors copy** of a preseason / season-opener brief (last season's seniors removed instead of struck through, projected starters) | same run, automatically whenever a strike plan exists | `..._<team>_no_seniors.html` |
| **Team analysis** -- ANY team, this season, NO UW-Whitewater sections (no banner/matchup, keys to victory, head-to-head, team-stat comparison, what-to-play, two-for-one, needs-tagging, and nothing after the UW-WHITEWATER divider; the late-game foul list stays) | `parser_analysis.ipynb` (`run_parser("analysis")`; `TEAM`, `SEASON`, `REFERENCE_DATE`, `TEAM_URL`) -- one run per team | `F:\Backups\uwwmensbball_analysis\<Team>\scouting_briefs\scouting_brief_<team>.html` (fallback `data_analysis\<Team>\`; `ANALYSIS_DIR` overrides). Works on a copy of `data\` (table files + saves, logos, photos, brand), so the app's data is never touched |

So "update all briefs" = run `parser_brief` for the upcoming game AND re-run `parser_analysis` for every team that has a
folder under the analysis directory (list the folders; ask Corey if unsure which teams he still wants). Run
`parser_models` first if film/tags changed. Analysis mode is `ANALYSIS_MODE` in 87 (`_an` state in `add` / `section` /
`divider`) and `_pm_analysis_setup` in `00_parser_modes.py`; only the parser's CURRENT season works (past seasons stop
with a message -- their FastScout files are in `inputs_<season>`).

Brief data rule (11/9): once the season has switched, every table built from tagged clips (play calls, situations, the
offense breakdowns, screen coverage, ball-screen defense, coach notes, passing) uses **this season's clips only**
(`season_play_calls` in 47, `BRIEF_THIS_SEASON_ONLY = True`). `play_calls` itself keeps every season for Film Tagging,
tracking and the models.

---

## 1. What the project is

- **Parser** (`parser/`): reads FastScout pages, play-by-play, Synergy exports and the coaches' tags, then writes CSVs and the HTML scouting brief into `data/`.
- **Streamlit app** (`streamlit_app.py`, repo root): the coaches' app, deployed on Streamlit Community Cloud straight from GitHub. It shows only what's in `data/`, so **nothing changes in the app until Corey commits and pushes**.
- **Coaches**: Corey, plus Coach Jake, who does most of the Film Tagging in the app.

### Repo layout (Windows, inside OneDrive)
```
C:\Users\frits\OneDrive\Documents\GitHub\uwwmensbball\
  streamlit_app.py            the app (~1.2 MB)
  data\                       everything the app reads (CSVs, play_tag\, play_review\, scouting_briefs\)
  data\play_review_saves\     coaches' saved answers (also on the git branch 'saves')
  parser\
    parser_nb.ipynb           ALL settings + one cell per section (Corey never opens it directly)
    parser_models.ipynb       job: run_parser("models")  -- tracking, court, jersey reader, tag model, checks
    parser_tagging.ipynb      job: run_parser("tagging") -- new Film Tagging batches, fast
    parser_brief.ipynb        job: run_parser("brief")   -- scouting brief + app data (game from parser_models' saved REFERENCE_DATE)
    parser_analysis.ipynb     job: run_parser("analysis") -- team analysis brief, no UWW sections (see section 0)
    parser_lib\NN_*.py        the code for each section (run_section("NN_name"))
    parser_lib\00_parser_modes.py   the job definitions (which sections each job runs, quiet mode)
    inputs\                   FastScout pages, rosters, logs (inputs\_logs\<job>_<time>.log)
F:\Backups\uwwmensbball_tracking\           Synergy Editor exports (one folder per game, 3-5 GB each)
F:\Backups\uwwmensbball_tracking\_tracking\ tracking files (TRACK_DIR) -- moved off C: on 11/2
```

### How Corey runs things
- He runs **only the three job notebooks** (models / tagging / brief). They execute `parser_nb.ipynb`'s cells from disk, so a setting change goes into `parser_nb.ipynb`. Don't tell him to open or reload it.
- All three jobs run in **quiet mode**: one "done" line per section, one live status line, and lines matching the job's `quiet_show` printed as they happen. Everything else goes to `parser\inputs\_logs\<job>_<YYYYMMDD_HHMMSS>.log`. **To analyze a run, stage the newest log and read it.**
- Sections 01-45 (the "core") are skipped on a re-run in the same kernel when nothing they read changed. The fingerprint includes the date and each section file's mtime.
- After a run: commit and push `data/` (plus `streamlit_app.py` when it changed) in GitHub Desktop.

---

## 2. How to work on his files (important)

- Corey's computer is reached through the `mcp__remote-devices__*` tools. **`device_bash` IS available now** (since 11/3):
  his repo is mounted at `$HOME/mnt/uwwmensbball`. Edit files IN PLACE there with a python read-modify-write
  (`assert s.count(old) == 1`), then check syntax with `python3 -c "import ast; ast.parse(open(f).read())"`
  (`py_compile` can fail with an I/O error writing `__pycache__` on the mount). Don't stage files just to edit them.
- `F:\Backups\uwwmensbball_tracking` is connected but often does NOT mount in `device_bash`; use `device_list_dir` /
  `device_stage_files` for it.
- Deleting needs Corey's approval (`device_request_delete_permission`); otherwise `mv -n` into a `_to_delete` / `_wrong_season_scrapes` folder.
- To analyze a run: newest `parser\inputs\_logs\<job>_<YYYYMMDD_HHMMSS>.log`, grep it (see section 6).
- Write `CONFIRMED CHANGE (requested: "...")` or `CONFIRMED BUG (fixed; ...)` comments at each change, quoting Corey. The whole code base does this; keep it up.
- Prefer verifying against real data (the log, the CSVs in `data\`, `inputs\`) over guessing.

### Standing rules from Corey
- **"I do not want anything you do to effect the games and clips that are currently in the film tagging section."** Never break or rebuild existing Film Tagging batches or saved answers. Saves on the `saves` branch must still count.
- Keep answers concise. Explain what changed and what he needs to run.
- Derived content is computed in the parser and exported as CSVs; the app only renders it.

---

## 3. The 11/2 incident (know this so it never repeats)

- `parser_nb.ipynb` on his computer got replaced by a **weeks-old copy**, probably from an editor tab holding a stale buffer. That copy had no `TRACK_DIR` and the Wheaton scrimmage as the upcoming opponent.
- The tagging run then:
  - looked for tracking files on C:, didn't find the `_reset.json` marker, and **re-ran the one-time tracking reset**;
  - deleted the tag-model files in `inputs\_tag_model` and the jersey-reader `.pt` / `reads`;
  - moved the court calibrations to `_before_reset`;
  - wrote a new reset time, so all Film Tagging saves were "set aside";
  - emptied the Carroll@Elmhurst batch.
- Restored:
  - the notebook (good copy committed);
  - `inputs\_tracking\_reset.json` → `{"id": "2026-10 restart on 1920 Synergy exports", "at": "2026-10-14T02:47:38+00:00"}`;
  - 8 court calibrations moved back.
- Corey discarded the `data/` changes in GitHub Desktop.
- **The tag model and the jersey reader need to retrain** on the next `parser_models` run. It's slower once.
- If anything looks like a reset happened again, check the `Tracking reset (` line in the log and the `_reset.json` files on both C: and F:.

---

## 4. Current state (Nov 9, 2026 -- see section 10 for Nov 14: the upcoming opponent is now Elmhurst, REFERENCE_DATE 2026-11-15)

### Season / opponent
- **Season 2026-27** (`SEASON = "2026-27"` in parser_nb; the switch moved 2025-26 FastScout files to `parser\inputs_2025-26`
  and copied last season's tables to `data_2025-26`). `REFERENCE_DATE = "2026-11-8"` in parser_nb AND in parser_models' first
  cell -> upcoming game **Ripon Red Hawks, Home, Nov 14 2026**. `EXTRA_GAMES = []`.
- UWW's first game: **@ Carroll, Nov 7 2026** (Synergy game `6ac6ee2d34559f81e3ab11c7`). FastScout had not posted its score /
  play-by-play as of 11/9, so the brief has no UWW season stats yet (many sections were made to handle empty tables).
- Ripon's first game: vs Elmhurst Nov 7 (Synergy `6abc2667a50466db6de75137`) -- exported from Synergy 11/9 for Film Tagging.
- Ripon's scout report not posted on FastScout yet.
- `FRAMES_STOP_IGNORE_GAMES = ["2025-11-07 WWW@RIP"]` (last season's Ripon game: Synergy page has only 175 clips).

### parser_models first cell (options passed to run_parser)
`TRAIN_MODELS`, `DO_PLAYER_TRACKING`, **`PLAYER_TRACKING_TYPE`** ("Starters" = 3 frames of the first clip until all 10
starters are placed; "5 Clips" / "20 Clips" per run after that), **`PLAYER_TRACKING_GAMES`** (replaces parser_nb's list;
currently WashU 11/7/25, Beloit@Carroll 11/12/25, `"11_7_26 UW-Whitewater @ Carroll (WI) Pioneers"` -- add each new game
here), `DO_FILM_TAGGING`, `FILM_TAGGING_SUGGESTIONS`, `ADD_GAMES`, `REOPEN_PLAYS`, `BANK_GAMES` (Platteville vs Thiel
`6aee1d6c9e04633c52349e89`; La Crosse vs St. John's commented out).

---

## 5. Key settings (parser_nb.ipynb)

| Cell | Settings |
|---|---|
| 2 | `EXTRA_GAMES` (upcoming game), `SEASON` |
| 108 (46 frame capture) | `TRACKING_RESET_ID`, `SYNERGY_EXPORT_DIR = F:\Backups\uwwmensbball_tracking`, `TRACK_DIR = F:\...\_tracking`, `PLAYER_TRACKING_GAMES`, `VISION_TRACK_FPS_TRACKING = 8` |
| 120 (50 tracking) | `TRACK_*` settings, `TRACK_HOLD_AT_CLIP = 8`, `TRACK_DIR = globals().get("TRACK_DIR") or ...` |
| 125 | `COURT_*` |
| 133 (55c play review / tagging) | `PLAY_REVIEW_*`, `PLAY_TAG_*`, `PLAY_TAG_INCLUDE_TRACKING_GAMES = True` |
| 202 (87 brief) | `ROSTER_LAYOUT = "table"`; optional `BRIEF_FILM_ON_FILE`, `BRIEF_FULL_BENCH_OPENER`, `PROJ_STARTER_POS_PENALTY` |

---

## 6. Useful log lines to grep

- `Film Tagging:` and the indented `YYYY-MM-DD ... clip(s) tagged` lines: batches and progress.
- `[saves]`: which saved review files were read.
- `Film on <team>:` (55e): film quality.
- `Tracking reset (` — **should never appear again**.
- `Struck through N ... senior(s)` and `Wrote ...scouting_brief_...html` (87).
- `[roster] <team>: 2026-27 roster -- N returning player(s) updated, M new player(s) added` (21).
- `[synergy]` (lookup, lineups), `[bank]`, `[export]` (Synergy Editor), `[export lineups]` (FastScout fallback).
- `This season only (2026-27): N of M clip(s)` (47), `ANALYSIS:` (parser_analysis setup).
- `[tracking] player model bank:` / `player-model backfill:` / `TRACK_NEW_GAME_PACE =`.


---

## 7. What was built Nov 3-9, 2026

**Synergy (no FastScout needed)** -- `46_frame_capture.py`
- `_syn_lookup` / `_syn_fill_video_urls`: a played game with no video link on FastScout is found on **Synergy's Games page**
  (`apps.synergysports.com/basketball/games?leagueId=...&seasonId=...&competitionKeys=<league>:ALL&teamAId=<team>&view=1`):
  our team id from `/api/users/getme`, season id from the seasons list, opponent team ids from UWW's games. Cache:
  `inputs\_synergy_ids.json`. `SYNERGY_LOOKUP = False` turns it off. Nothing is hard-coded (Corey: don't hard-code games).
- Every looked-up / banked game saves **both fives on every possession** from Synergy's `api/games/<id>/events`
  (`offensiveLineup` / `defensiveLineup`) to `inputs\_bank\<id>_lineups.csv`; starters = first possession's fives.
  47 attaches them (`_syn_attach_lineups`, matched by Synergy description, else half + clock + team).
- **Coach-tagged Export.csv games with no video** (e.g. `F:\...\STOUT\Export.csv` = Calvin @ UW-Stout 11/7/26): merged into
  `uww_plays.csv`; `_syn_export_lineups` gets their fives from Synergy; FastScout play-by-play fallback in 47
  (`_export_pbp_lineups`). They count for an opponent's brief when that team is upcoming.
- Banked games (`BANK_GAMES`, ID only): date / label / "for" looked up; Synergy starters + lineups; FastScout pbp fallback.
- Synergy Editor export box close (`_sst_close_export_box`) and cache clear (`_sst_clear_cache`, `SYNERGY_CACHE_DIR`) were
  still NOT confirmed working on 11/9: the close now searches inside the Editor window and dumps
  `inputs\_synergy_export_done_window.txt` on failure; the cache step prints Synergy folder sizes. Check after the next export.

**Season switch to 2026-27** -- 02 now switches FastScout's season selector when a team page opens on the wrong season
(`season=26` asked, `25` served); `_extra_find_team_url` forces the current season on links from old schedule files.
Bad wrong-season files went to `inputs_2025-26\_wrong_season_scrapes`.

**Player Number Tracking**
- Starters check: `PLAY_REVIEW_STARTERS` now defaults True (it was off while tracking waited on it -> stuck at clip 2);
  `STARTERS_PICTURES` (3 frames); Synergy starters prefilled for banked games; named "no box" rows count.
- `_NameNums`: jersey lookup ignores punctuation ("Greg Smith, Jr." = "Greg Smith Jr." = #42).
- Roster lists ignore Synergy's "1 Pts" (and-one) as a fake player.
- Player / not-a-player model now trains on **every game's checks ever** (`_tracking\player_model_bank.csv`); old checked
  clips are backfilled ONLY when their detections are already saved (`TRACK_BANK_BACKFILL`, `_MAX` 150) -- the first version
  ran the CPU detector on 8,589 frames (~3 h); don't repeat that.
- Jersey reader: `JERSEY_READER_MIN_ANSWERS` 6 -> 20 (it named players wrongly on 9 answers), `JERSEY_TRAIN_MIN_NEW` 150 -> 40.
- Detection runs on CPU (~1.5 s/frame); Corey's PC has 8 GB RAM (kernel died at 96% memory; he raised the page file).

**Brief / app data**
- Empty-season fixes (no UWW pbp/stats yet): 36 typed empty pbp, 44 numeric clock, 70 expected box skipped (empty
  projected tables), 80 `reindex`, 86 empty player lines, 11 margin "n/a".
- Offense breakdown / coverage tables, passing card, reads-to-roster etc. from earlier in the week (see the code comments).
- (SUPERSEDED 11/14, see section 10: the save / read code was missing and parser_brief now has its own REFERENCE_DATE.) `REFERENCE_DATE` / `EXTRA_GAMES` are set ONLY in `parser_models`' first cell (11/12, Corey's request). parser_models saves them to `parser\inputs\_upcoming_game.json`; parser_brief / parser_tagging read that file (00 `run_parser`), applied at 00b, replacing parser_nb's. parser_analysis still sets its own team.
- Offense tables (11/9, Corey: "All of the offensive tables within briefs needs to also include the 5 person lineup that runs it most and any players that are best at scoring off of it"): `uww_offense_breakdown` has `top_lineup` / `top_scorers` on every situation / formation / play-call row (47 `_top_lineup`, `_top_scorers`); 87 `_offense_breakdown_card` shows them under each PLAY-CALL row ("Runs it:" / "Scores:") -- never on the "All" rows: Corey wants the All rows' Actions column empty. Applies to every brief kind (ours, theirs, analysis). Any NEW offensive table in a brief must carry the same two lines.
- Offense-table play-call flags (11/10, Corey: "Flag based on that row's own numbers"): 87 `_row_flag` rates each play-call row on its own possessions / PPP -- often = at least the median possessions of the table's play-call rows, efficient = >= the table's own team PPP (from its situation rows); 2+ possessions theirs, 3+ ours. The season-wide flags (`_SB_PC_FLAGS`) and the "Scored here" flag are no longer used in that table.
- Offense tables are collapsible (11/11): the full situation > formation > play-call table sits in `<details class="ob-det">` ("Show the full table"), closed by default; the summary bullets stay visible above it. A small script in the brief's <head> opens every <details> before printing.
- TEAM STATS (11/11): on preseason / first-games briefs, "UWW last season" and "<OPP> last season" rows (grey italics, from LAST_SEASON_DATA_DIR via `_sc_line`) under this season's two rows; the separate THIS SEASON vs LAST SEASON section is off (`BRIEF_SEASON_COMPARE_TABLE = True` brings it back). TEAM STATS now shows even when one team has no stats yet.
- TOP LINEUPS (11/11): five-man table = top 2 by each of MIN, +/-, per 40, PPP, 3P% (+ the five on the floor for the most tagged possessions, which replaced the "Be aware of" bullet), top-2 values bold (no "Why" column) (87 `lineups_table`, `_picks`); top scorers on tagged plays printed under it (`uww_offense_summary` kind "scorers"). 86 `_gp_pc` ("What they run") is this season only. `PLAY_CALL_RENAMES` also has "Ripon Motion #2".
- Offense summary bullets (11/10): above every offense table, a few bullets -- each of the 3 most-used half-court formations (top play call, main action, best play call), most successful play calls / actions (2+ poss, above team PPP), the five to be aware of + top scorers, the ball-screen defense their opponents played with PPP, and "do the same / do differently" (lowest / highest PPP coverage). Built in 47 `_summary` -> `uww_offense_summary.csv` (`OB_SUMMARY_MIN_POSS` = 2); 87 prints them (`ul.ob-sum`). Every brief kind gets them. 87 prints ONLY the formation and success bullets (Corey removed the "players", "defense" and "advice" lines, 11/11).
- Offense table coverage lines (11/10): no separate coverage rows -- every coverage folds into its play-call row as "Switch 2 (1.50) · Drop 1 (0.00) · No coverage tagged 6 (0.67)" in the ball-screen / off-ball columns (87 `_onecov`).
- **Play calls stay exactly what the coaches tagged** (11/10, Corey: "remove any of that code so that it stays what the coaches tagged it. I will find a different way to group them later"): 47 `_pl_motion_detail` no longer renames Motion calls ("RIPON MOTION #3" stays); it only fills `play_call_family` for the Motion breakdown table. 53 `label_play_call` = the coaches' play_set; 55c no longer turns predictions / the answer list into "Motion". Don't re-add grouping unless Corey asks.
- Play-call names that differ only by capitals / spacing ("BLOB #1" vs "Blob #1") are merged to the most-used spelling for every season (47 `_pl_merge_spellings`, before all summaries). Since 11/10 it also covers FORMATIONS and matches ignoring capitals, spaces and hyphens/punctuation ("I Form" = "I-Form" = "Iform"; "41" = "4 1" = "4-1" = "4- 1"); a formation of only dashes / "none" = No Formation. A note in brackets and the word "option"/"opt" are ignored too ("Ripon Motion #2" = "Ripon Motion Option #2" = "RIPON MOTION #2 (RICKY)"); ties go to the spelling without brackets. Corey's own renames go in `PLAY_CALL_RENAMES` (47; override in parser_nb): {"RIPON MOTION": "Ripon Motion #1", "Ripon Motion left": "Ripon Motion #1"} -- add new ones there when he asks. Corey wants such near-duplicates always combined in the briefs.

**App -- Film Tagging (11/9)**: blocks of `FT_SAVE_EVERY` = 10 clips drawn ONCE in one form (`st.container(key="ftclip_<n>")`); a script in the browser shows one clip at a time with a floating purple Previous / Next bar, Enter = next, space = play / pause -- NO server rerun between clips (Corey: Enter must not refresh). The 10th clip's Next clicks "Save clips a-b" (the only refresh) and opens the next 10. "Clips" list picks a group (\u2705 = saved).

**Corey's open items (11/9)**: Ripon brief needs UWW + Ripon this-season film tagged; Carroll player checks at "5 Clips";
delete the old `data_analysis\UW_Stout_Blue_Devils` folder in the repo (superseded by F:); first `parser_analysis` run for
UW-Stout not finished yet.

---

## 8. History: state on Nov 2, 2026 (superseded by sections 4 and 7)

### Season / opponent
- The parser is on the **2025-26** data (SEASON "auto"; UWW hasn't played 2026-27 yet). `EXTRA_GAMES` sets the upcoming game: **Carroll (WI) Pioneers, Away, real date Nov 7 2026** (UWW's 2026-27 opener). Run date is 2026-3-8.
- The brief type is **first_games → "SEASON OPENER BRIEF — FIRST GAMES"**, with last season's seniors struck through (`strike_seniors_plan`, `STRIKE_LAST_SEASON_SENIORS = "auto"`).
- Rosters: Carroll's 2026-27 roster page has been merged (`source = "... (new season)"`, `class_year_prev`). **UWW's 2026-27 roster is NOT merged yet**, so only graduated seniors can be dropped for UWW.

### Player Number Tracking — PAUSED
Corey said it's "good enough" for now; don't test more unless he asks.
- Game: `PLAYER_TRACKING_GAMES = ["11_7_25 Carroll (WI) Pioneers @ Washington-St. Louis Bears"]`. It gets 8 fps frames.
- Held at clip 8 (`TRACK_HOLD_AT_CLIP = 8`). Re-check pictures exist for clip 1.
- Last results:
  - jersey vote 10/11;
  - following 9/9;
  - all 1,072 frames on the court;
  - guess accuracy about 61%;
  - player model still needs 15 not-a-player labels (has 10).
- Main tracking code: `50_player_tracking.py` (~390 KB), `51_court_mapping.py`, `55c_play_review.py` (play review + Film Tagging), `48`/`49` (jersey reader), `46` (frames / exports).

### Beloit @ Carroll (11/12/25) — set up 11/3 for Film Tagging + Player Number Tracking
- `PLAYER_TRACKING_GAMES` now lists WashU AND `"11_12_25 Beloit Buccaneers @ Carroll (WI) Pioneers"`. Being listed is what gets it captured and exported, even outside the `VISION_RECENT_GAMES` window; `VISION_ONLY_GAME` stays None.
- New `ptg_setting()` in 46: `TRACK_HOLD_AT_CLIP` and `PLAY_REVIEW_RECHECK_CLIPS` can be dicts per game. They are now `{WashU: 8}` and `{WashU: [1]}`, so WashU stays paused and Beloit moves on.
- `PLAY_TAG_INCLUDE_TRACKING_GAMES = True`, so Beloit also gets a Film Tagging batch (Carroll's offense first).
- Next steps for Corey: run `parser_models` (Synergy export up to 90 min) → court calibration in the app if asked → starters check on clip 1 → player checks (one clip at a time, `TRACK_NEW_GAME_PACE`).

- 11/3 fixes:
  - A `_scout` file no longer counts as a played UWW game in `01._auto_reference_after_last_game` or `00b._ss_data_season`. The new 11_7_26 report had made the run date 11/8/26, shown "Season: 2026-27" and dropped EXTRA_GAMES. No files were moved; there is no `_season.json`.
  - 11: a report with "-" totals (written before any games) is skipped instead of crashing.
  - The Beloit export worked (178 clips, `Beloit@Carroll(WI) - Nov 12, 2025` on F:).

### Film Tagging
- Built by `parser_tagging` (55c `tag_queue`). Only "this run's" games get batches (`PLAY_TAG_RUN_ONLY`): the upcoming opponent's games plus our most recent game.
- Opponent games: the scouted team's offense first, then the rest once saved. UWW games: offense, then defense. The app shows 20 plays per page.
- `PLAY_TAG_INCLUDE_TRACKING_GAMES = True` (cell 133) now puts Carroll@WashU into Film Tagging too.
- Latest progress:
  - Carroll@WashU 0/221 (105 Carroll offensive plays in the batch);
  - Carroll@Elmhurst 82/160 (1 offensive play left, then 78 more);
  - UWW@WashU (3/7/26) 122/167.

### Scouting brief (`87_build_html_scouting_brief_for_upcoming.py`, ~335 KB) — what changed on 11/2
1. **"Film on file" line removed** from page 1. `BRIEF_FILM_ON_FILE = True` brings it back.
2. **"Who to attack"** (2-for-1 Attack/Avoid, `uww_two_for_one_attack`) moved from the Two-for-One section to the first read line of each opponent player in the roster. Struck seniors are skipped.
3. **Two copies for scrimmage / season-opener briefs** (whenever a strike plan exists):
   - `scouting_brief_<team>.html`: unchanged, seniors struck through.
   - `scouting_brief_<team>_no_seniors.html`: made by `_sb_drop_struck()`. It removes struck rows, items, keys (renumbered) and names with their "(n)", and changes the banner to "left out".
   - The app's Game Plan tab has two download buttons.
4. **Whole bench** in those briefs (`_sb_full_bench`, `BRIEF_FULL_BENCH_OPENER`). Adds "Bench — limited minutes", "Bench — no minutes" and "Bench — never played" (names from `uww_roster_no_minutes`).
5. **No-seniors copy always shows 5 starters** (`_no_senior_roster`):
   - Returning starters are untagged.
   - Each graduated starter's spot goes to the returning player of the **same kind** (guard / wing G/F / forward / big). Big = C, or a Post Scorer / Roll & Cut Big / Anchor Big role.
   - The best mpg wins, minus `PROJ_STARTER_POS_PENALTY = 6` minutes per step away from the right kind.
   - Tagged with a yellow **Projected starter** chip; first read "Projected starter — X minutes a game last season".
   - Players not on a new-season roster are treated as gone.
   - Drawn twice in the HTML between `<!--NS:strike-->` / `<!--NS:remove-->` markers; the run block keeps the right one in each file.
   - Carroll: McKenna, McNabb, Estepp + Tarjan (for Lamar Smith) + Greg Smith (for Naber). UWW: Madson, Marino + McEwen, Chestnut, Lukenbill.
6. **Roster table layout**: each player gets a purple **bio bar** row (#, pos, height, class, Off/Def roles; his name is hidden in it so strike / remove handle both rows), then his row with the **photo above the name**. No Bio column. **UWW has no Late game foul column** (10 columns vs the opponent's 11).
7. **Below-minimum lines** ("under the 6-attempt minimum for a shooting read") replaced by a red `*` after the name and one legend line at the bottom of the roster.
8. **Opponent bios / photos** fall back to the live roster (`_opp_ros_bio`) when a player isn't in `uww_opp_personnel` (fixed Nolan Groh and other freshmen with no photo).

### Other fixes on 11/2
- `21_roster_pages.py`: roster lines with a comma in the name ("GREG SMITH, JR.") were skipped entirely. Now commas are allowed and new/old seasons match ignoring Jr./Sr./II/III (`_ros_match_key`).
- `00_parser_modes.py`: `parser_tagging` now runs quiet like the other two jobs.
- `README.md` (repo root) now has step-by-step instructions for bringing a new game into Film Tagging and Player Number Tracking (worked example: Beloit @ Carroll, 11/12/25), including the player-check options.
- `41b_offensive_roles.py` (offensive roles):
  - A ball handler must also create for others: `ROLE_BALLHANDLER_MIN_AST` = 0.15 assists per possession. Non-creators go on through the scoring roles (Madson → Slasher, Bara → Off Screen Shooter; 11 players changed in total).
  - One team under two names ("UW-Whitewater" / "UW-Whitewater Warhawks") is merged when the names overlap and they share players (`_or_team_canon`). Possessions and assists in a game that's in both files are counted once.
  - Not seen in a real run yet.
- **Upcoming game's own scouting report** (Carroll 2026-27):
  - `BEFORE_SCOUT` setting (cell 2, now "no"; it was hard-coded "yes" in 01).
  - `02._extra_game_scout_report()` downloads the EXTRA_GAMES game's report from the opponent's NEXT-season documents page, matched on `real_date`, as `11_7_26 UW-Whitewater @ Carroll (WI) Pioneers_scout.html`. If none is posted yet it re-checks after `EXTRA_SCOUT_CHECK_HOURS` (6; cache `inputs\_extra_scout_check.json`).
  - 08 keeps two reports per opponent:
    - `scout_reports` = the past game's report, so 11 / 12 pair keys with that game via `all_game_plans_history`;
    - `scout_reports_upcoming` = the new one.
  - 10: `all_game_plans` (uww_opponent_game_plans) uses the new report and gains a `report_date` column.
  - 09: player notes and keys to defending come from the new report, matched by name; new players are added with no jersey.
  - 87: no "2025-26" tag on staff keys when `report_date` is this season.
  - Not seen in a real run yet.
- Known cosmetic issue: the quiet `!!` match also shows the coaches' "ATTACK THE PAINT!!!" key lines. Harmless; could use `^\s*!!`.

### Not verified yet / waiting on Corey
- Corey had not yet re-run `parser_brief` after the last three brief changes (asterisk legend, Groh photo, UWW foul column). Check the next brief log and HTML.
- UWW's own tracked game (3/7/26) shows "players named <NA>%" in the film quality line since the reset. It was noted to Corey but not fixed.

---

## Play diagrams (app upload → brief)
- App: Analytics > Play Diagrams lists this season's tagged play calls per team; coaches upload one image per play. Saved to the saves branch as `data/play_diagrams/<teamkey>__<playkey>__<YYYYmmdd_HHMMSS>.<ext>` (newest wins).
- Parser: the saves fetch in 47 copies new files into `<data>/play_diagrams`.
- Briefs (87, every kind incl. no-seniors and analyses): collapsed "Play diagrams (N)" `<details>` under each offense table, most-run play first, images embedded as JPEG base64.
- Key rule must match in both places: app `_pd_key` == brief `_sb_pd_key` (lowercase, drop bracket note and "option/opt", keep a-z0-9#, `#`→`n`).

## Synergy-tagged UWW titles (47 `_pt_normalize`)
- A title starting with a play-call word (motion/flow) then "-" pieces = no formation, that play call, every piece an action: "motion-ds-straight cut-ghost: m2m" → Motion(ds, straight cut, ghost). "Straight Cut" added to `_PT_EXTRA_ACTIONS`.
- Offense table: 47 writes level="action" rows after each play call (own poss, PPP, top_lineup, top_scorers, cov_ball, cov_offball). 87 shows the play-call row as "All" (poss, PPP, flag only) and lineup/scorers/coverages on the action rows.
- Same rule for a named set first ("snap 30-bs", "twins left-bs" -> Snap / Twins + Ball Screen, No Formation) when every piece is a known action. "Twins" is a set (play call), not a formation, in _PD_SETS.
- Above the full table: collapsed "Play call summary" (play call, poss, PPP over all situations/formations).
- UWW: "No Play Call" is reported as "Flow" (47 offense breakdown; only for Whitewater rows).

---

## 9. What was done Nov 13-14, 2026

### Season / opponent
- `REFERENCE_DATE = "2026-11-15"` in parser_models -> the upcoming opponent is **Elmhurst (Nov 18)**, on purpose. Corey: "we
  have done enough scouting for Ripon". So the Ripon game (Nov 14) counts as played; its Synergy export fails until it is.
- Film Tagging batches dropped because they weren't "this run's" games (UW-Oshkosh@UWW, Carroll@Elmhurst 2/24/26,
  UWW@WashU 3/7/26, UWW@Ripon 11/7/25): Corey said that's fine ("we have moved on"). Saved answers are kept. Don't restore them.

### ADD_GAMES takes a FastScout link (00_parser_modes.py, 46_frame_capture.py)
- `ADD_GAMES = ["https://fastscout.fastmodelsports.com/teams/<team>/games/<game>/boxscore?..."]` (or `"fastscout:<game>"`)
  becomes a BANK_GAMES entry `{"fastscout_url": ...}` (`_fs_game_key`). 46 `_bank_resolve_fastscout()` opens the page once a
  run, takes the Synergy ID from a Synergy video link, or -- FastScout box scores usually have NONE -- reads the two teams and
  date from the page and finds the game with `_syn_lookup`. Kept in `inputs\_bank_games.json` under `"_fastscout"`.
- Bugs fixed: the options run before EVERY section, so the link was appended 33 times (run looked stuck at 46) -> de-duplicated;
  `bank_game_for` only matched a banked game's "for" team, so a game between two teams we don't play (no "for") got no
  Film Tagging batch -> with no "for", either team in its label matches; `_bank_fill` overwrote the Synergy starters -> merges.
- Used for **Franklin @ Hope, Nov 7 2026** (Synergy `6ab818207c04d5284e260158`): exported, 212 clips, Film Tagging batch.
  It is "Other" (no brief) since neither team is on our schedule.

### Synergy export box (46 `_sst_close_export_box`)
- The box is its own window "Export: <game>" (class `ExportMediaDialog`) whose buttons are an unnamed X
  ("Avalonia.Controls.StackPanel") and "Cancel" -- no "Close" button, which is why it never closed. Now: once no
  "Processing: Clip a of b" with a != b is shown, the window is closed (WindowPattern.Close, else the X). NOT yet seen working:
  check the next export's log for `[export] closed Synergy Editor's export box`. Corey closes Synergy himself otherwise.

### App -- Film Tagging (streamlit_app.py)
- `FT_SAVE_EVERY = 20` (was 10): Enter / Next goes through 20 clips, the 20th saves them and opens the next 20.
- Hot keys (browser script in the Film Tagging block): Enter = next (save on the last); Space = play / pause (stops a rewind);
  **M = 2x speed toggle; N = rewind at 2x toggle** (N again or Space stops); speed resets on a new clip; keys ignored while
  typing in a box or with a dropdown open. The purple bar shows "2x >>" / "<< 2x". No key for Previous (Corey may want one, e.g. B).

### C: drive full -> clip videos moved off main, history cleaned
- C: filled during a run: the repo's `.git` (OneDrive, on C:) was ~10 GB because every batch's clip .mp4s were committed and
  kept in history (+ ~4.8 GB of leftover `.git\objects\pack\tmp_pack_*`). The parser's own folders are small
  (data\ ~0.65 GB, frames 0.1-0.3 GB a game).
- **`videos` branch** (Corey: "build option 1"): `data/play_tag/*/` and `data/play_review/*/` `*.mp4` + `*_poster.jpg` are in
  `.gitignore`. 55c `_push_clip_videos()` (end of 55c, every models / tagging run) force-pushes the current ones to branch
  `videos` as ONE parentless commit (no history), using a separate git folder `F:\Backups\uwwmensbball_tracking\_videos.git`
  (`VIDEOS_GIT_DIR`), prunes old objects there, and only after `ls-remote` confirms the push does `git rm --cached` them in
  main. `VIDEOS_BRANCH = ""` turns it off. First push 11/13: 936 files, 806 s; later runs upload only new clips.
- App: `_clip_here()` downloads a clip from the branch (secret `videos_branch`, default "videos"; [github] token) into the same
  data/ path the first time it's shown; `_clip_prefetch` loads a 20-clip block in parallel; `_has_vid` counts clips on the branch
  (`_vid_remote_list`, cached 5 min). Corey confirmed clips play.
- **History rewritten 11/13** with `C:\Users\frits\uww_git_cleanup.py` (git-filter-repo, branches main + saves only, the
  `videos` branch untouched; force-with-lease push; local repo reset --soft to the new main + gc). Packed .git 5.4 GB -> 1.9 GB.
  New main tip 8a2a57e ("clipvideosmoved"). **Any other clone of the repo must be re-cloned** -- pushing an old copy brings the
  videos back. If GitHub Desktop ever offers to pull / says diverged right after this, don't -- check first.
- Undo / leftovers on F:\Backups\uwwmensbball_tracking\: `_history_cleanup_backup_<time>` (keep the newest a couple of weeks),
  older backups, `_history_cleanup_old_*` and `_history_cleanup` can be deleted. Keep `_videos.git`.
- C: still showed ~5.8 GB free right after; OneDrive / Recycle Bin may hold the deleted packs. Other big things NOT yet measured:
  anaconda3, Windows / pagefile, `$WINDOWS.~BT`.

### Lessons for next time
- `device_bash` du on the OneDrive mount is very slow -- measure folder by folder with timeouts, or use `device_list_dir`.
- The device_bash VM can't reach GitHub; git pushes must run on Windows (a script Corey runs in Anaconda Prompt, or the parser).
- Don't use `gc --aggressive` on a repo copy with videos (ran for an hour); a `--mirror` clone needs
  `git config --unset remote.origin.mirror` before pushing named branches.

---

## 10. What was done Nov 14, 2026 (brief quality: contradictions, sample size, keys, brief check)

Corey asked what a stronger model could add to the briefs and approved four of the suggestions ("everything except #4" --
#4, a one-page "what matters" top, is NEXT; it needs his OK because he removed the players / defense / advice bullets on
11/11). All of it is in brief-only sections (83, 85, 87): parser_models / parser_tagging don't run them, Film Tagging is
untouched. **First real run: parser_brief 11/14 10:37 (Elmhurst), finished** -- log `brief_20261114_103722.log`: `Small sample:
Elmhurst Bluejays has played 2 game(s) ... last season's numbers added for 7 returning player(s)`; `Read check: 2
reworded` (Boone, Marshall "Driver"); `Brief check: 3 problem(s)` = false alarms on Bottom Line keys (fixed after).
The later changes (the new "Built from:", the brief-check fix, the set-key coverage sentence, the "Check:" flag line) have
NOT been seen in a real run -- check the next brief.

- **One sample rule: `READ_MIN_GAMES` = 3** (85; same number as `BRIEF_FIRST_GAMES_MIN`; set it in parser_nb to change).
  A player read needs 3 games AND the attempt floor. While the opponent has played < 3 games this season, returning
  players' numbers are this season + last season (`LAST_SEASON_DATA_DIR` box scores / pbp; `_pn_last_season_rows`) and
  their reads end in "-- incl. last season". A player still under 3 games: leader lines say "so far (..., 1 game)",
  percentage / rate reads move to `below_minimum` (the roster `*`), and no box-score key is written (the tagged-film
  "Know <set>" key stays). Log: `Small sample: <team> has played N game(s) ...`.
- **Ties are not leaders** (85 `_pn_sole_leader`): "Leading scorer" / "Primary creator" need ONE leader; a rebounding tie
  reads "Tied for their lead on the glass". (Ripon had two "Leads them on the glass" and a 4-way assist tie.)
- **Contradiction pass: `85b_read_reconcile.py`**, run from 85's last line (no notebook cell). Sources ranked film >
  coaches' report > box-score rules. `reword` a numbers line the film contradicts ("Driver" with < 15% drives on 8+ film
  finishes); `drop` a numbers key opposite to the coaches' key, or one of two numbers lines that disagree (FG% vs true
  shooting; "Top priority" + "Let him be the one who shoots it"); `flag` a line of the coaches' report the film / numbers
  contradict -- **the coaches' words are never changed**: the roster card gets a yellow "Check: ..." line (87
  `_read_flags`, in `lead`, max 2). Every change with the original line -> `uww_read_conflicts.csv`. Film needs
  `READ_FILM_MIN_POSS` = 8. Log: `Read check (<team>): N reworded, N dropped, N flagged`.
- **Keys to Victory (83, block after `ktv_select_for_brief`)**: (1) a computed key on < 3 games ends with "Small sample:
  N game(s)." and its confidence is scaled by games / 3; (2) the set keys ("Take away their go-to set" / "Know their best
  set" / "Call our best set") end with what coverage worked, from `uww_offense_breakdown` coverage rows
  (`_ktv_set_how`; a coverage needs `KTV_HOW_MIN_POSS` = 2 trips; all coverages go in the key's evidence) -- right now
  almost no coverage has 2 trips on one play call, so it mostly says nothing until more defense is tagged; (3) a staff
  key with no reason carries the computed key on the same topic ("From the numbers: ..."; evidence "Linked data key:
  ..."), shortened to "see key N: ..." when that key is also printed.
- **Brief check: `87b_brief_check.py`**, run from 87's last line. Reads the finished HTML: leftovers ("<NA>", "nan"),
  empty / missing sections, tables in the data folder that are for a different opponent (`scouted_opponent`), keys not
  in `uww_ktv_keys.csv`, a player drawn twice, more than one "Leading scorer", percentages outside 0-100, dead links.
  Problems print with `!!` (shown under "done 87_..."), everything -> `uww_brief_check.csv`. Changes nothing.
- 87: the `*` legend said "last season" in every brief -> "Too few attempts or games on file".

- **`_upcoming_game.json` save / read restored (00 `run_parser`)**: parser_brief on 11/14 ran on parser_nb's
  `REFERENCE_DATE = "2026-11-8"` (Ripon) and stopped in 47 (`FramesNotReady`: DePauw@Elmhurst "captured, none in
  uww_plays.csv") because the code section 7 describes -- models saves REFERENCE_DATE / EXTRA_GAMES to
  `inputs\_upcoming_game.json`, brief / tagging read it -- was NOT in `00_parser_modes.py` (not on disk, not in any
  commit; the json was last written 11/12). Now: models writes it, brief / tagging print `Upcoming game from
  parser_models: REFERENCE_DATE = ...` and use it. If a file ever "loses" documented code again, suspect a stale copy.

- **parser_brief has its own `REFERENCE_DATE`** (first cell, Corey's request; `None` = use parser_models' saved one). The
  run's first line warns when it differs from the date parser_models last ran on.
- **"Built from:" rewritten (87, Corey's review of the Elmhurst brief)**: tagged offense is split into "used in this brief
  (this season)" by game, "tagged last season, not used in the tables", and "still untagged this season"; Player Number
  Tracking / film tracking are listed only when 55e's `names_ok` / `court_ok` let film into the brief; the "Not available
  for this build: uww_..." table-name line is removed (still in the log). Brief check no longer flags Bottom Line
  ("Game Plan") keys. First real run 11/14 10:37 (Elmhurst) worked: blend for 7 players, 2 "Driver" lines reworded.

### 11/15 -- Film Tagging keeps every UWW game of this season
- `PLAY_TAG_ALL_UWW_THIS_SEASON = True` (parser_nb cell 133; 55c `_tag_run_reason`): every UW-Whitewater game of the
  CURRENT season keeps its batch, not just our most recent one. Why: after the 11/14 Ripon game the 11/7 Carroll batch
  was removed ("not part of this run") and the Ripon film could not be exported, so the app had NO UWW clips to tag.
  False = back to our most recent game only. Not seen in a real run yet.
- What a blank save counts as (checked in the code, 11/15): the app writes a row per (clip, field) only when the field has
  a verdict or an answer (`_pr_title_default` -> "--" means no row). With `FILM_TAGGING_SUGGESTIONS = False` every field
  starts blank, so clicking Next through a block and saving writes NOTHING: the clips stay `Untagged` and come back in the
  next batch. With suggestions ON, an untouched field starts on the automatic answer and IS saved
  (`prefilled`/`accepted_default` = True), so a click-through accepts the model's guesses as the tag. A clip saved with
  only, say, defense / situation (no formation / play call / primary action) becomes `decode_quality = "No call"`: it
  counts as tagged, is never offered again, and adds nothing to the play-call tables.

### 11/15 -- "Skip this clip" in Film Tagging, and banked games stay banked
- **Skip (requested: coaches don't want to tag certain parts of a game).** App: a "Skip this clip -- don't show it again"
  box on every clip of a Film Tagging block; save the group as usual. The save carries `skipped` / `unskipped` clip keys
  (`_pr_payload`), the box starts ticked for a clip already skipped (`_ft_skipped_clip_keys`), a skipped clip counts as
  saved (the green check), and its header shows "skipped". Parser: 47 `title_review_answers` merges skips in save order
  (latest wins) into `_title_review_skips`, `_pl_apply_app_tags` writes a **`skipped`** column on uww_play_calls.csv and
  prints "Skipped in the app: N clip(s)". A skipped clip is NOT tagged -- decode_quality stays `Untagged` and nothing
  about it reaches any table; it is only never offered again (55c `tag_queue` leaves it out of `todo` and says
  "(N skipped by a coach)"), and 46's "have the coaches finished this game" gate ignores it so it can't block the next
  game's capture. **To bring clips back: `PLAY_TAG_UNSKIP`** (parser_nb cell 133) = "all", a game ("Elmhurst") or one
  clip ("Elmhurst 44"). Tested against copies of the data; not seen in a real run.
- **A banked game stays banked (00 `bank_games`).** It listed only what parser_models' cell held, so emptying `ADD_GAMES`
  on 11/15 dropped Franklin @ Hope (a LATER opponent's game Corey added on purpose) and 55c deleted its 212-clip batch.
  Now every game remembered in `inputs\_bank_games.json` stays listed; `BANK_GAMES_DROP = ["<synergy id>"]` (or "all")
  forgets one, `BANK_GAMES_STICKY = False` goes back to the old behaviour. The next run rebuilds the Franklin @ Hope
  batch (212 clips, ~25 min of play videos). Its `"for"` is still blank in the json -- fill it in when Hope is scheduled.

### 11/15 -- the UWW @ Ripon (11/14) export: Synergy had the video but had NOT coded the game
- Symptom: `parser_models` stopped twice with `FramesNotReady` -- "2026-11-14 Ripon Red Hawks: 224 clip(s) captured, none
  in uww_plays.csv". Cause: the Synergy Editor export worked (224 clips), but EVERY row of its Export.csv has a blank
  `Title` and `Synergy String`, so the clip rows in `uww_clip_frames.csv` have no player and no description. 47's
  `_pl_untagged_from_frames` needs the description, so the game could not become play calls, and the gap check asked
  Corey to "export its tagged clips from Synergy" -- which no export could give.
- Fixes: 46 `_vx_ingest` now checks Export.csv first and leaves an UNCODED export alone (nothing registered, so the game
  is just "not captured yet" and the run goes on); `VISION_EXPORT_UNCODED_OK = True` captures it anyway, without
  descriptions. 47's gap check turns the "captured but not in uww_plays.csv" stop into a note when the game's clips have
  no description at all.
- Still to do for that game: Synergy has to finish coding 11/14, then the export must be redone -- the existing folder
  `F:\Backups\uwwmensbball_tracking\Ripon@UWWhitewater - Nov 14, 2026` has to be renamed or removed first (ask Corey),
  and its 224 rows in `inputs\uww_clip_frames.csv` go away by themselves on the next run (46 drops them). The ~1,100
  JPEGs in `inputs\_vision_frames\Nov_14_2026_Ripon@UWWhitewater` are then orphaned.
- Do NOT make blank-description clips taggable: the app's clip key is `date|clip number|synergy string`, so coach answers
  saved against a blank string would stop matching the moment a coded export replaced them.

### 11/15 -- the two export guards (both requested after the 11/14 Ripon mess)
Confirmed in the browser on 11/15: Synergy has the 11/14 game as **partially logged**. Its Game Breakdown shows only
"All Clips 224" plus the situational rows (out of bounds, after time outs, push ball, live free throws) and a single
ALL CLIPS link. A fully logged game (Elmhurst @ Ripon 11/7) shows "All Play Clips", "All Possessions",
"Possessions + Assists" and the SHOTS / SETS / TRANSITION / PRESS OFFENSE sections. UWW won 73-70.
- **`VISION_EXPORT_REQUIRE_LOGGED = True`** (parser_nb cell 108; 46 `_syn_game_logged`): before exporting a game the run
  opens its Game Breakdown page and looks for those markers. "Not logged yet" -> the export is skipped with a message and
  tried again on a later run. Anything unclear (page didn't load, no Synergy login, an error) answers None and the export
  goes ahead as before -- the check never blocks on doubt. A True is remembered in `inputs\_synergy_logged.json`; a
  False is re-checked every run. Set it False to export regardless.
- **`VISION_REEXPORT_GAMES = []`** (same cell; 46 `_vx_reexport_wanted` / `_vx_set_aside`): names games whose export
  should be thrown away and done again -- "Ripon 11/14", "Ripon@UWWhitewater", "2026-11-14", "Nov 14", or "all". The old
  export is MOVED (never deleted) to `<SYNERGY_EXPORT_DIR>\_uncoded\<name>` (two levels down, where `_vx_find_export`
  does not look), the registry forgets the game and its clips are dropped from uww_clip_frames.csv, so the next export
  starts clean. A date in an entry is compared as a date, so "Ripon 11/11" does not match the 11/14 game.
- **To get the 11/14 game in once Synergy finishes logging it:** put `VISION_REEXPORT_GAMES = ["Ripon 11/14"]` in
  parser_models' cell... no -- it lives in parser_nb cell 108; set it there, run parser_models, then empty it again.
  With both guards on, a run before Synergy is done just says so and changes nothing.
- Tested: the matcher on 12 entry forms (including the near-miss "Ripon 11/11"), the move / registry / clip-drop on a
  copy of the folder layout, and the logged-check rules against the real page text of both games. No real run yet.

### 11/16 -- VISION_REEXPORT_GAMES moved to where the games are CHOSEN (it could never have fired)
Corey: "Couldn't I just delete the export in F drive". Answer: no, and the setting as written on 11/15 had the same hole.
- A game whose clips are ALL captured with frames and no errors (the 11/14 Ripon game: 224 rows) is filtered out of
  `_vis_sources` before `_vision_from_exports` runs, and that function is where the setting was being read. So neither
  the setting nor deleting the export on F: would have put the game back: **the clip rows alone keep a game "captured"**.
- Fixed in 46: the VISION_REEXPORT_GAMES request is now handled where `_done` is computed (the selection step), so the
  game goes back in the queue. The rows are dropped from `clip_frames` itself, never from `_full` (which is only that
  block's view and leaves out test_run rows -- assigning it back would have deleted those rows).
- `_vx_set_aside` now copes with an export folder that is already gone (deleted by hand): it skips the move, still
  forgets the registry entry and still drops the clips, and says so.
- Tested on a copy of the folder layout: export present -> moved to `_uncoded\` + 224 rows dropped + other games' rows
  kept + the export is no longer found (so it is exported again); folder already deleted -> same minus the move; setting
  empty -> nothing touched.
- So to redo that game: set `VISION_REEXPORT_GAMES = ["Ripon 11/14"]` in parser_nb cell 108 and run parser_models.
  Deleting the folder on F: first is optional and changes nothing -- the setting is what drops the clip rows.

### 11/16 -- "Skip this whole game" in Film Tagging
Requested after the per-clip skip: coaches don't want to tag every game at all.
- **Saving a clip with nothing on it = "nothing to tag"** (11/16, Corey: "What if they click the Next button and then save
  the clips" -> option A). In a Film Tagging batch (`actions=True`), a clip that is saved with no answer and no action row
  is recorded in the save's `skipped` list: not tagged, nothing of it in any table, never offered again, and
  PLAY_TAG_UNSKIP brings it back. Before this such a clip wrote NOTHING -- it came back in the next batch, the group
  never showed as saved (the saved-clips set counts answers / actions / skips), and an empty file went to the saves
  branch. The save message now says how many clips were taken that way. Title checks (`actions=False`) are not affected,
  and with FILM_TAGGING_SUGGESTIONS on an untouched clip still saves the model's answers as accepted, as before.
  Tested on a stand-in of the app's state: all three clips skipped when nothing was filled in; only the two passed over
  when one was tagged; nothing skipped on a Title check or with suggestions on.
- **There is NO per-clip skip control in the app** (11/16, Corey: "remove the 'Skip this Clip' button because it does the
  same thing as just doing the 'Next Clip' button"). It was a checkbox, then briefly a third button beside "Clear
  suggestions" / "Fill forward"; both are gone. Next leaves a clip untagged and it comes back in the game's next batch;
  a coach who wants a game gone for good uses "Skip this whole game". The parser side of the per-clip skip is still
  there and still read from save files (47's `skipped` column, 55c, 46's gate), so older saves keep working and the
  control can come back as one button if it is ever wanted.
- **App**: under the Game picker in Analytics > Film Tagging, an expander "Skip this whole game" -- name + a confirm tick
  + a button. It saves one small file (`..._skipgame_<coach>_<time>.json`, `{"game": "<date>|<code>", "skipped_game":
  true}`) straight to the saves branch, and the game leaves the list right away (`_ft_skipped_games`, used to filter the
  picker; the skipped games are named in a caption). An `unskipped_game` save undoes it; the latest save for a game wins.
- **Parser**: 47 `title_review_answers` reads the game skips into `_title_review_game_skips`, and `_pl_apply_app_tags`
  marks EVERY clip of such a game `skipped` -- so everything built for the per-clip skip applies unchanged (no tags, out
  of every table, never offered again, and 46's "have the coaches finished this game" gate ignores it). 55c additionally
  removes the game's batch folder and says "a coach skipped the whole game in the app, so it has no batch".
- **To bring a game back**: `PLAY_TAG_UNSKIP = ["Thiel"]` (parser_nb cell 133) -- the game name is enough.
- Tested against a copy of the data: a game skip marks all 196 of its clips and removes its batch; a later
  `unskipped_game` save un-skips the game (Franklin@Hope stayed); single-clip skips and other games are untouched;
  PLAY_TAG_UNSKIP with the game name brings every clip back. Not seen in a real run yet.

### 11/16 -- Film Tagging opens fast (requested: "it is kind of slow when you first click on the Film Tagging tab")
- The Game list now starts on **"-- choose a game --"**: opening the tab draws no clips, fetches no clip videos from the
  videos branch and reads no saved answers. It lists the games with their clip counts and waits for the coach to pick
  one. A `ft_game` value that is no longer in the list (the game got tagged, or skipped whole) is dropped instead of
  raising -- which the new "skip this whole game" button made possible.
- The saved review files were being re-read once per batch: `_pr_save_docs()` reads all 109 files (3.1 MB) and was called
  about 9 times per page load. The tab now reads them ONCE and hands the list to `_ft_saved_clip_keys`,
  `_ft_skipped_games`, `_ft_skipped_clip_keys` and `_ft_seed_from_saves` (each takes an optional `docs`; passing nothing
  keeps the old behaviour for other callers). Measured on the OneDrive mount: one pass = 1.7 s, so ~15 s -> ~1.7 s there;
  Streamlit Cloud's own disk is faster but the 9x stands.
- Not seen in the app yet -- needs a commit and push.

### 87 audit findings (11/14) -- listed for Corey, NOTHING changed yet
Static scan of all of 87 + close reading of the roster, keys, matchup and team-stat code (not every line).
1. `_sb_has_text` is defined twice (lines ~759 and ~777); the second silently wins.
2. Six functions are never called: `name_link_lines`, `two_up`, `foul_cell`, `pc_table`, `foul_list_block`, `_reads_card`.
3. `offense_section_test2` (theirs) and `offense_section_test_uww` (ours) are two near-copies -- every offense-table
   change has to be made twice (the "any NEW offensive table must carry the same two lines" rule depends on it).
4. Twelve switches exist only in code, not in the notebook cell: `BRIEF_TYPE`, `BRIEF_HEAD_TO_HEAD`, `BRIEF_TWO_FOR_ONE`,
   `BRIEF_QUADRANT`, `BRIEF_ACTION_TABLES`, `BRIEF_CONFIRM_ON_FILM`, `BRIEF_COVERAGE_COUNTERS`, `BRIEF_SELF_SCOUT_FILM`,
   `BRIEF_SEASON_COMPARE_TABLE`, `BRIEF_FILM_ON_FILE`, `BRIEF_FULL_BENCH_OPENER`, `PROJ_STARTER_POS_PENALTY`.
5. Legends restate rules by hand (late foul "62% / 8+ / 75% / 85% on 4" = 86's `_GP_FOUL_*`; "averaging 8+ minutes";
   "3+ tagged uses"; "2+ uses"). In sync today; they drift the day a rule changes.
6. Today's real date is used instead of the run date: ~line 6140 labels a scouting report "the upcoming game's report"
   when it is within 30 days of NOW (wrong on a re-run of an old game / an analysis); ~line 299 falls back to now().
7. 32 `except` blocks: 9 are a bare `pass`, 18 fall back to a default without printing. A broken section just
   disappears (the brief check now catches the empty / missing section, not the cause).
8. ~line 3664: `int(them.get("games") or players["games"].max() or 1)` -- a silent default of 1 game.
9. `_SB_PC_FLAGS` / `_SB_TEAM_PPP` are still computed and passed through globals (set ~5494 / ~5883, read ~5080)
   although the 11/10 note says the season-wide flags are no longer used in that table.
10. 87 also writes data (`uww_film_ai_status.csv`, `uww_brief_notes.csv`) -- the brief builder is a producer too.
11. Old copies that could be opened by mistake (the 11/2 incident was a stale copy): `parser_lib\00_parser_modes-1.py`,
    `46_frame_capture-1.py`, `parser_lib\.ipynb_checkpoints\`, `parser\Untitled.ipynb`; `data\scouting_briefs` has 12
    dated / "before..." copies (8 MB, deployed with the app). Ask before deleting.

### Open from the 11/13 models log (told Corey 11/14)
- UWW@Carroll is in Film Tagging twice: `WWW@CAR` 167/167 tagged and `UWWhitewater@Carroll(WI)` 0/24 (a new 24-clip batch).
  Looks like one game under two codes. NOT investigated (it is an open batch: read only, ask first).
- Franklin@Hope still prints "couldn't tell which team we play: add 'for'" (it got its batch); 2 clips out of clock order.
- 83 Elmhurst clips with no Team value assumed offense; Elmhurst@Ripon Synergy lineups 0 of 86.
- Elmhurst brief built 11/14 10:42 (`data\\scouting_briefs\\scouting_brief_Elmhurst_Bluejays.html`); it needs one more
  parser_brief run to pick up the new "Built from:".
- Elmhurst's offense in the brief rests on 44 tagged possessions (DePauw@Elmhurst). Untagged Elmhurst offense on film:
  Elmhurst@Ripon 11/7 (89), DePauw@Elmhurst (52) -- tagging those is the fastest way to a better brief.

### How this chat went (11/14) and what is next
1. Start-of-chat summary + review of `models_20261113_183205.log`.
2. Corey asked what a stronger model could add to the briefs; six suggestions; he approved all but #4.
3. Built #1 contradiction pass, #2 sample rule, #3 keys, #6 brief check; #5 = the audit list below (nothing changed).
4. parser_brief stopped (`FramesNotReady`) -> wrong REFERENCE_DATE -> restored `_upcoming_game.json`, then (his request)
   REFERENCE_DATE in parser_brief's first cell.
5. He asked whether "Built from:" was correct and useful -> rewritten.
NEXT, in his order: **#4 the one-page "what matters" top** (he said "I want to come back to that next"). Waiting on his
answers: which audit items to fix (suggested: silent excepts, real-date uses); OK to look (read only) at the duplicate
UWW@Carroll Film Tagging batch. Files changed today, for his commit: `00_parser_modes.py`, `83_...`, `85_...`,
`85b_read_reconcile.py` (new), `87_...`, `87b_brief_check.py` (new), `parser_brief.ipynb`, `CLAUDE.md`. After the brief
runs, `data\\` gains `uww_read_conflicts.csv` and `uww_brief_check.csv`.


### Synergy export wrote Export.csv and no clip videos (11/16)
Elmhurst@Hope - Nov 14, 2026 failed the same way on two runs in a row: Synergy Editor jumped straight to
"Export is available.", wrote `Export.csv` (223 rows) into the export folder and NO `video\` folder at all, so the run
logged `0 of 223 clip videos written...` for 5 minutes, said so, closed the export box and carried on (0 clips captured,
178 rows with errors). This is the Beloit @ Ripon bug again: the game's video had not loaded in Synergy Editor when the
run pressed Ctrl+E. That bug's fix raised the wait to 60 s **in the code's default only** -- `parser_nb.ipynb` pinned
`SYNERGY_EDITOR_LOAD_WAIT = 20`, so the fix never applied. Checked and ruled out: the export window read
`MP4 + CSV: on; CSV only: off` on both failed runs and on all ten successful exports, and the failed `Export.csv` matches
a good one column for column (`In Point`/`Out Point` are `N/A` in every export, good and bad).

Changed: `SYNERGY_EDITOR_LOAD_WAIT = 150` in parser_nb cell 108; `_sst_export_edit` now CLICKS the MP4 + CSV radio and
reads it back (up to three tries, Select() as the fallback) instead of calling Select() once -- a UIA Select() can leave
Synergy's own setting on the old choice -- and still refuses to press OK unless it reads "on"; the no-clip-videos message
now names SYNERGY_EDITOR_LOAD_WAIT and its current value. A videoless export folder is NOT reused: keep
`VISION_REEXPORT_GAMES = ["Hope 11/14"]` for the next run so the folder is set aside and the game exported again.


### Film Tagging: the wait between each block of 20 clips (11/16)
Corey: "The saving between the 20 clips takes very long." The save itself (one PUT to GitHub) was never the problem.
Every save called `_pr_remote_save_docs.clear()` (twice -- in `_pr_github_save` and `_pr_commit`), and that cache held
EVERY save file on the `saves` branch, fetched ONE REQUEST PER FILE. So the next render after each save made 1 listing +
112 file downloads = 113 round trips (25-50 s), growing by one file per save. Worse, the deployed `data/play_review_saves`
folder already had all 112 of those files, so they were downloaded and then dropped as duplicates.
Changed in `streamlit_app.py`: `_pr_remote_save_list` (names + git shas, one request, ttl 120) and `_pr_remote_save_blob`
(one file by its sha, cached for good -- a save file never changes; a failed read RAISES so the failure is not cached)
replace the old single cached function; `_pr_remote_save_docs(token, repo, sb, folder, skip=())` builds the same
{name: document} from them and skips names handed to it; `_pr_save_docs` passes `skip=seen` (the deployed folder's names);
`_pr_remote_save_docs.clear = _pr_remote_save_list.clear` so the five `.clear()` calls in the app still work and now clear
only the cheap listing. A save is 2 requests instead of 113. Nothing else about saving, the answers or the batches changed.


### Film Tagging: the next block's clips download in the background (11/16)
Corey asked whether 30 clips a block instead of 20 would be slower. Saving no longer cares (2 requests either way), but a
block's clips are pulled from the `videos` branch when the block OPENS (`_clip_prefetch`, 6 at a time; ~2.9 MB a clip, so
~57 MB for 20 and ~85 MB for 30, and `st.video` holds each one in the app's memory -- Community Cloud gives about 1 GB).
So 30 would mean 6 longer waits instead of 9 shorter ones, with more memory per block. Built instead: `_ft_prefetch_next`
(beside `_clip_prefetch`) starts a daemon thread that downloads the NEXT block's clips while the coach tags this one, so
the block boundary stops being a wait at either size. It runs once per block per app process (`_FT_PREFETCHED`, a
module-level set shared by every session), skips clips already in the folder, makes no Streamlit calls in the thread
(`add_script_run_ctx` only keeps the "missing ScriptRunContext" warning out of the logs), and is started right after the
current block's own blocking prefetch, so the two never compete. FT_SAVE_EVERY is still 20 (line 8194): with this in
place 30 is a real option, at ~85 MB of video per block.
