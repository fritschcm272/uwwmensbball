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

### Repo layout (Windows, on the external F: drive -- moved off C:/OneDrive 11/17)
```
F:\uwwmensbball\                 (was C:\Users\frits\OneDrive\Documents\GitHub\uwwmensbball)
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


### The whole project moved to F: (11/17)
After the C: drive filled (see above), Corey moved the repo to **F:\uwwmensbball** -- an EXTERNAL drive, so nothing runs
while it is unplugged -- and out of OneDrive, which had been syncing a 9+ GB repo full of clip video. Done by him in
GitHub Desktop: tmp_pack files and leftover temp folders deleted first, "Always keep on this device" + pause sync, move
the folder, then Remove repository and File > Add local repository on the new path. History, branches and remote all came
with it; `.git` is 5.8 GB there with no tmp_pack files left. Nothing in the code needed repathing: INPUT_DIR/OUTPUT_DIR
are relative and SYNERGY_EXPORT_DIR / TRACK_DIR were already on F:. The only absolute C: paths left are in old logs and
`.ipynb_checkpoints`.
Still on C: and deliberately left there: anaconda3, the Playwright browsers and Synergy Editor's own cache.
Changed with the move:
- `_pm_scratch()` in `00_parser_modes.py`, called at the top of every `run_parser`: sets `tempfile.tempdir` and TMP/TEMP
  to `PARSER_TEMP_DIR` (default `uwwmensbball_temp` at the top of the data drive, so F:), clears the parser's own
  leftovers (`play_tag_*`, `play_review_*`, `lean_*`) older than `PARSER_TEMP_KEEP_HOURS` (6) in both the new scratch
  folder and the system temp folder, and prints free space for the data and scratch drives -- a `!!` line below
  `PARSER_MIN_FREE_GB` (10). This is what stops a repeat: the clip videos for the app were always written to the system
  temp folder on C: first, whatever drive the data was on.
- `55c_play_review.py`: the Film Tagging video loop checks free space every 20 clips and STOPS the batch with a `!!` line
  ("stopped at N of M") instead of writing hundreds of failed clips, as the 11/16 run did.
Not done, still open: the `videos` branch history only grows (5.75 GB of packs; every run re-makes the batch videos, so
each push adds blobs nothing will reach again). Resetting that branch to a single orphan commit was offered and NOT
approved -- do not touch git history without Corey asking.


### First run on F: -- what the move cost (11/17 05:10 models run)
The run finished (119 min) and made the Film Tagging batches for Thiel (196) and Franklin@Hope (212), but two things did
not come across with the folder:
1. **`parser\.env` is gone.** The log opens with "No FastScout credentials found" / "No Synergy credentials found" and
   "APP_BASE_URL is blank", so there was no live scraping at all this run -- rosters and schedules came from the local
   backup pages, one UWW game's play-by-play was skipped, and the brief's app links would render dead. A dot-file is easy
   to miss in a move and it is not in git. `parser\.env.example` now lists the keys the parser reads (UWW_APP_URL,
   FASTSCOUT_USERNAME/PASSWORD, SYNERGY_USERNAME/PASSWORD, and the optional AI_MODEL / OPENAI_BASE_URL /
   PLAYWRIGHT_BROWSERS_PATH); Corey has to fill in a real `.env` beside it.
2. **`inputs\_season.json` kept absolute C: paths** (`data_archive`, `inputs_archive`), so the run printed
   "last season 2025-26: None" and lost last season's tables. Both values were repointed at F:, and `00b_season_switch.py`
   now has `_ss_archive()`: when the stored path is gone it looks for the same folder name beside this season's, says so,
   and rewrites the marker -- so the next move heals itself.
Also: `_pm_scratch`'s `[disk]` lines run before the log file is opened, so they were only in the notebook. run_parser now
copies them into the log as soon as it names it (`_PM_SCRATCH_LINES`).

### Why nothing showed up in the app's Court Calibration (11/17)
Not a path problem and nothing to do with the move: `parser_nb` cell 125 has `RUN_COURT_MAPPING = False`, and the models
mode uses the notebook's own flags (`"flags": {}`), so the whole block at the end of `51_court_mapping.py` is skipped --
including the part that writes `data/court_calibration/<gym>/request.json` and its frame pictures, which is exactly what
Analytics > Court Calibration reads. The run says so twice: "[reuse] court mapping (switched off this run)" and "Court
insights: nothing on the court yet (court mapping needs a calibration)". `data/court_calibration` is empty. Set
`RUN_COURT_MAPPING = True` in cell 125 and run parser_models to get the packages (the block also needs `player_tracks`
non-empty; the 179 clips / 1,212 tracks carried over from earlier runs satisfy that even when nothing is tracked anew).


### The clip-video push goes one game at a time (11/17)
Two runs in a row ended with `[videos] push failed -- ... RPC failed; HTTP 500 ... the remote end hung up` on 1,952 clip
files (~5.5 GB in one transfer). The branch is a single orphan commit holding every open batch's clips, so it can be
built up a game at a time instead. `_push_clip_videos()` in `55c_play_review.py` now:
- fetches `origin/videos` and lists its paths, so it knows which GAMES have clips GitHub doesn't have yet;
- with more than one such game (`VIDEOS_PUSH_PER_GAME`, default True), adds the already-pushed clips to the index first
  (they upload nothing), then one game per step: add -> write-tree -> commit-tree -> `push --force`, each push about
  400 MB. The branch ends on the same full-tree commit as before, so everything after the push is unchanged.
- Every step is a superset of the one before, so no batch already on GitHub disappears mid-way, and a failure leaves the
  games already pushed ON GitHub: the run stops there, main is left alone, and the next run carries on with the rest
  instead of starting the 5 GB over.
- One new game, or `VIDEOS_PUSH_PER_GAME = False`, keeps the old single push.
Not fixed by this: the branch still grows every run (each run re-makes the batch videos as new blobs). Pruning it, or
moving clip hosting off git, is still open -- offered twice, not approved. Do not touch git history without Corey asking.


### Why the clip-video push kept failing: the commit had no parent (11/17)
Chunking alone did not fix it. One game per push still died ("2 of 2: Ripon_UWWhitewater, 270 new clip file(s), 389 MB"
-> HTTP 500), and by hand every push enumerated the WHOLE branch: "Enumerating objects: 1714 ... Writing objects: 100%
(1714/1714), 2.06 GiB" -> 500 again, three times. The cause is the parentless commit the branch is built from: git has no
shared history to diff against, so it offers every object in the tree however much GitHub already holds. GitHub takes the
whole 2 GB upload and then refuses the pack.
Proved by hand: with `commit-tree -p refs/remotes/origin/videos`, the same files went up as four fast-forward pushes of
"74 objects, 95 MB" each, in about a minute apiece. Ripon@UWWhitewater's 270 files landed at 0da82b4.
In `_push_clip_videos()` now:
- `_base` = what GitHub has (`refs/remotes/origin/videos`). If that ref exists but its tree is NOT in the videos git
  folder -- which is what the run's own `git prune --expire=now` causes -- the ref is deleted and re-fetched, so git can
  tell what is already up there. (A plain `git fetch` does NOT repair this: the ref looks current, so nothing downloads.)
- every push, chunked or not, is a child of what GitHub has, so only the new clips go up;
- when the pushes are done the branch is flattened back to ONE parentless commit with the same tree (that push carries a
  single commit object), so the branch still never builds up history and GitHub can still collect the old blobs. If the
  flattening push is refused the clips are all there anyway and the next run flattens it again.
Settings: VIDEOS_PUSH_PER_GAME (True), VIDEOS_PUSH_CHUNK_MB (120), VIDEOS_PUSH_FIRST ([] -- the game(s) the coaches are
waiting on go first).
NOTE for editing the job notebooks: JupyterLab holds its own copy of an open notebook. After any edit to
parser_tagging.ipynb / parser_models.ipynb on disk, use File > Reload Notebook from Disk before running it -- on 11/17
VIDEOS_PUSH_FIRST was set on disk, the browser ran the old cell, and the setting never reached the kernel.


### The parser publishes the app's data itself now (11/17)
Corey: "When running the parser_models, can't it push this stuff for me?" -> "Yes, both and the default." The
court-calibration stop made the case: the run writes data/court_calibration/<gym>/ and then CANNOT go on until that
folder is in the app, which until now meant remembering to open GitHub Desktop.
`_pm_push_data(mode)` in `00_parser_modes.py`, and `run_parser` is wrapped so it runs in a `finally` -- the data goes up
whether the run finished or stopped on the way (CourtCalibrationNeeded, an error). What it does:
- `git add -A -- data` and `git commit -- data`, both limited to that one path, so streamlit_app.py, the parser's own
  files and anything else in flight are never touched. The clip videos are .gitignore'd in data/ and still go to the
  videos branch on their own.
- pushes to APP_BRANCH ("main"). If the repo is on another branch it says so and stops. If the push is refused the
  commit is still made and the message says to push it in GitHub Desktop. Nothing is pulled, merged, forced or rewritten.
- `PUSH_DATA_TO_MAIN = False` goes back to pushing everything by hand.
This is the one place the parser writes to GitHub on its own besides the videos branch. The standing rule otherwise
stands: no pulls, no history, no pushes of anything but data/ -- and never on another branch.


### Naming players at UWW home games: the baseline to beat (11/17)
Corey, on the Starters check crops: "extremely zoomed out video and very blurry zoomed in photos of jerseys." He is
right, and it is the camera, not the pipeline. Measured from the detector's own boxes (median person height in a
native 1920x1080 frame): Thiel@UWPlatteville 151 px; UWW@Carroll 145; Elmhurst@Hope 137; UWW@Wash(StL) 128;
**Ripon@UWWhitewater 102** -- UWW's home camera is ~30% further out than any other venue, so a jersey number is ~15 px.
The source really is the best there is: the Synergy export is 1920x1080 30 fps 8 Mbps, every game captures at
track1920v2 (native width), and no better home angle exists. OCR needs ~20-25 px; it is not coming back.
Why nothing gets named today (from uww_player_tracks.csv, 1,609 tracks / 14 clips):
- `anchored` is 0 on EVERY track -- no clip's Synergy anchor is ever attached to a track;
- names come only from `coach checked` (50) and `followed player` (38); `evidence` and `elimination`: never;
- **46 player-side tracks per clip for 10 players** (4.6 fragments each, median 11 frames; worst clip 118 tracks);
- and it is configured that way: TRACK_USE_RIM_ANCHORS / TRACK_USE_POSE_ANCHORS were False, the ball anchor only fires
  on Turnover|Foul clips, and TRACK_ANCHOR_WEIGHT (0.3) sits BELOW TRACK_MIN_NAME_EVIDENCE (0.5), so an anchor alone
  can never name anyone. Both audits in the notebook explain why: Synergy anchors were right 0 of 10, the late ball
  holder 3 of 14. With fragments this short an anchor names a 2-second sliver, which is probably why.
Set up for the measurement run: TRACK_USE_RIM_ANCHORS = True (cell 120) and PLAYER_TRACKING_TYPE = "20 Clips"
(parser_models). Weights untouched ON PURPOSE -- the run NAMES NOBODY, it only reports how often the rim anchor agrees
with the coach-checked name ("agreement with Synergy anchors (anchor hidden)" + tracking_anchor_audit.csv).
The courts were calibrated 11/17 (UWWhitewater from Ripon 11/14, Hope from Elmhurst 11/14, 8 frames each, in
data/play_review_saves). That matters twice: the rim anchor needs the homography, AND `_trk_link` gates association by
REAL FEET (TRACK_MAX_SPEED_FTS) once a frame has court coordinates, instead of falling back to "less than 2 box widths"
in the picture. At 102 px and 4 fps a sprinting player moves about 1.5 box widths a frame, right at that gate -- so the
calibration may cut the fragmentation on its own. Compare the next run against: 46 player tracks a clip, median 11
frames, 0 anchored, 0 named by evidence or elimination.


### Offensive roles were being decided with NO film at all (11/17)
Corey, on Kelton McEwen's player card: "Do you believe that he is really a Primary Ball Handler?" His row in
uww_offensive_roles.csv: role_basis "play-by-play only", video_possessions 0, every play-type share 0%, onball 0.42,
ast_per_poss 0.30, 20 poss -- the role came from SIX ASSISTS. The Tendencies box right under it (spot-up 40%, off a
screen 30%, 67% of shots from three) said the opposite, because the two halves read different sources.
Root cause: `41b_offensive_roles` takes its play types from `pbp_events["video_description"]`, which cells 28 and 41
fill from saved "<game>_video.html" pages. Since the move to Synergy Editor exports those pages are not saved -- the run
says "Found 0 video-tagging file(s)" and "pbp_events rows with a matched video description: 0 of 946" -- so EVERY
player this season was typed from assists alone. Not McEwen's problem: everyone's.
Fixed, three ways:
1. `_or_clip_chains()` in 41b reads the same Synergy strings from the clip rows (`inputs/uww_plays.csv`, the Export.csv
   columns) and stands in wherever the play-by-play has none (`role_basis` then reads "Synergy clips"). A name that
   appears for two teams is skipped. Checked on McEwen: 24 chains -> spot-up 33%, off screen 21%, transition 21%,
   PnR 12% -> **Off Screen Shooter**, which is what the film and the 67% 3PA rate say.
2. ROLE_MIN_POSS 20 -> 40 (cell 97), so two games no longer earn an unqualified role; the brief already prints
   "(low sample)" from role_basis.
3. In `_or_decide`, PRIMARY Ball Handler now needs MEASURED on-ball play: with the play-by-play-only stand-in (onball
   invented from assists) the most a player can be is Secondary. The brief also prints "(box score only)" next to a
   role that had no film behind it (`_q` in 87).
Worth doing later, bigger: have cells 28/41 attach the export's Synergy strings onto pbp_events directly, which would
fix every other consumer of video_description (29, 31, the weakness diagnostics) the same way. They run before 47,
which is where clips are matched onto the play-by-play clock, so it is a real reordering job, not a one-liner.


## 2026-11-17 -- Offensive roles were computed with zero film all season (the "deeper fix")

**Symptom.** Kelton McEwen's brief card said **Primary Ball Handler** while the Tendencies box right underneath it --
built from the same games -- said spot-up 40%, off a screen 30%, 67% of his shots from three.

**Cause.** `41b_offensive_roles.py` reads play types from `pbp_events["video_description"]`, which cells **28** and **41**
fill by matching saved `<game>_video.html` pages. Since the move to Synergy Editor exports those pages are not saved any
more, so the logs read `Found 0 video-tagging file(s)` and `pbp_events rows with a matched video description: 0 of 946`.
With no play types, every player this season was typed from **assists alone** (McEwen: 6 assists in 20 possessions ->
on-ball 0.42 -> Primary). Nothing crashed, which is why it went unnoticed.

**Fix, in three layers.**

1. **Attach layer (the deeper fix).** New `clips_from_synergy_export(game_date, players=None)` in
   `27_shared_video_tagging_helper_functions.py` builds the `parse_video_mhtml` clip schema
   (`["No.","Result","Description","player","Team","Duration"]`) straight out of `inputs/uww_clip_frames.csv`
   (falling back to `inputs/uww_plays.csv`), so the exports feed `video_description` with no `_video.html` page at all.
   Wired into `41_attach_video_tagging_clip_descriptions_2.py` (UWW games -- synthesized `_vt_sources` entries for games
   with no `_video` file, gated by `VIDEO_EXPORT_MIN_CLIPS = 10`) and `28_attach_video_tagging_clip_descriptions.py`
   (opponents' prior games, labelled `video_file = "(Synergy export)"`).
   Measured end-to-end against the real `uww_pbp_events.csv`:
   `2026-11-07 vs Carroll 149 of 232 events matched (190 clips)`, `2026-11-14 vs Ripon 148 of 213 (175 clips)` --
   from 0 of 946. The unmatched third is events with no clip (extra free throws, fouls, team turnovers).
   This also repairs the other consumers of `video_description`: 29 (opponent tendencies) and 31 (weak-spot diagnosis).
2. **Role layer (fallback).** `_or_features` falls back to `_or_clip_chains()` when fewer than `ROLE_MIN_VIDEO_POSS`
   possessions carry a chain, and marks `f["source"] = "Synergy clips"`; `_or_decide` now only allows
   **Primary Ball Handler** when the on-ball share was actually measured (`source` not starting with `play-by-play`),
   and 87's `_q` appends " (box score only)" to `role_basis` when it wasn't.
3. **`_or_clip_chains` bugs found while testing it.**
   - *Date-only filtering.* My first version matched clips by date, so 2026-11-07 returned **581** clips from the three
     games exported that day and each game's clip numbers restart at 1 -- which breaks the order-preserving
     `global_align`. Fixed with the `players` filter: 190 and 175, correct.
   - *One source only.* It read `uww_plays.csv` alone, which only gets games whose Titles are coach tags (the 11/14
     games are not in it). It now reads **both** files and concatenates -- `uww_clip_frames.csv` adds the recent games,
     `uww_plays.csv` adds 77 players the frames file lacks. 162 -> **300** players with clip play types.
   - *Team-alias guard (this was the one that mattered).* The same-name-on-two-teams guard dropped any player whose name
     appeared under two team labels. The clip rows spell our own team both `Wisconsin-(Whitewater) Warhawks` and `WWW`,
     so **every UWW player was thrown away** -- McEwen had 0 chains. New `_or_team_akin(a, b)` treats two labels as one
     team when one normalised label is a prefix of the other (`_or_team_canon`'s rule) or when the short one is the
     initials of the long one (`WWW` = Wisconsin Whitewater Warhawks). McEwen: 0 -> **59 chains**.

**Verification.** McEwen's 59 chains: spot-up 29%, off screen 24%, transition 15%, P&R ball handler 10%, 58% of shots
from three -- i.e. the Tendencies box, not a ball handler. 67 players now clear 20 clip chains.

Files touched: `parser_lib/27_shared_video_tagging_helper_functions.py` (22,701 b),
`parser_lib/41_attach_video_tagging_clip_descriptions_2.py` (19,251 b),
`parser_lib/28_attach_video_tagging_clip_descriptions.py` (13,171 b),
`parser_lib/41b_offensive_roles.py` (26,280 b),
`parser_lib/87_build_html_scouting_brief_for_upcoming.py` (425,735 b).

**Still open:** the one-page "what matters" top of the brief (#4, deferred); the tracking measurement run
(rim anchors on, `PLAYER_TRACKING_TYPE = "20 Clips"`); `_trk_link` fragmentation (46 tracks/clip vs 10 players).


## 2026-11-17 -- WHAT MATTERS: the one-page digest under KEYS TO VICTORY

Requested: "Create the one-page 'what matters' right under the keys to victory. I may want to combine them after
seeing your first example." Built in `87_build_html_scouting_brief_for_upcoming.py` as `_wm_what_matters()`, called
immediately after the KTV card closes, so it is the next thing on the page.

**The split that makes it combinable.** KEYS TO VICTORY are the INSTRUCTIONS. This page is the EVIDENCE under them:
what each instruction is worth, who makes it happen, and which key covers it. It introduces no new analysis -- every
number comes from tables already printed further down the brief (`uww_pbp_box_score`,
`uww_opponent_prior_games_box_score`, `uww_offensive_roles`, `uww_player_tendencies`), so the two can never disagree
and merging them later is a layout change, not a data change.

**What's on it.**
1. One-sentence verdict: the biggest factor and the man to take away.
2. The four factors as **points per game**, biggest first, us vs them, with a plain-English "why" per row.
   A point of eFG% = 2 points on every FGA; a turnover = one possession at that team's own PPP; an offensive rebound
   = a fresh possession at 0.30 of a normal one (the standard second-chance discount, since it is a putback into a
   set defense); extra free-throw trips at that team's own FT%. The same stat is one team's offense and the other's
   defense, so the two rates are blended 50/50 rather than trusting either. NET is us minus them.
3. WHO DECIDES IT: their three leading scorers -- box-score line, the first clause of their film tendencies, and
   their offensive role (carrying the "(box score only)" tag when the role had no film).
4. THE KEY THAT COVERS IT: each top factor matched to a brief key by keyword, so the page points at the instruction
   instead of restating it.
5. A confidence line naming the sample ("Built on 2 UW-Whitewater games and 3 Elmhurst games").

New CSS lives in `_SB_CSS` under the `.wm-` prefix. `WHAT MATTERS` was added to `_AN_DROP` so `ANALYSIS_MODE`
(parser_analysis, no UWW information) leaves the page out -- it compares the two teams.

**Elmhurst, Nov 18 (real output, preview at `what_matters_preview.html` in the repo root).**
Shot quality +7.0 a game to us (52.8 vs 48.9) | Free-throw rate +2.3 (51.4 vs 30.4) | Offensive boards +1.4
(37.3 vs 33.3) | Turnovers -0.9 (18.6 vs 15.9). Trelenberg 16.0 a game on 7.7 threes at 43%.

**Two bugs found while building it.**
- `_KEYWORD` for the free-throw row was `line`, which matches "lineup" -- the row pointed at "Attack lineup of
  Boone, Ketchum, ...". Fixed with word boundaries.
- **CONFIRMED BUG (fixed): every three-pointer was filed as "Other 2" in `player_shot_zones()`
  (`85_scouting_notes_and_keys_to_defending.py`).** `shot_type` arrives NUMERIC from the play-by-play parser, so
  `s["shot_type"].astype(str) == "3"` compared against `"3.0"` and was never true. `uww_player_shot_profile.csv`
  had `three_att = 0` for all 19 players while the box scores showed Trelenberg at 23 attempts; the brief's WHERE
  THEY SHOOT table called him 81% mid-range twos, and the roster's Driver read keys off the same numbers. Fixed to
  compare numerically; Trelenberg now reads 23 threes at 43.5%, Boone 16 at 43.8% -- matching the box score exactly.
  (This is why the new page takes its three-point numbers from the box score, not from the shot profile.)

**DECIDED (11/17):** keep the two sections as they are -- KEYS TO VICTORY (instructions) then WHAT MATTERS
(evidence). Corey reviewed the Elmhurst example and said to keep it as is; do not merge them into one section.


## 2026-11-17 (later) -- WHAT MATTERS: the net ratings were wrong (fixed)

Corey, on the first Elmhurst page: "Do these net ratings look correct?" They did not. **Three faults, all in
`_wm_what_matters()`'s points conversion. If a brief was produced between the two entries above, its WHAT MATTERS
numbers are wrong -- re-run it.**

1. **Baseline (the one that mattered).** Each team was compared with the OTHER TEAM'S SCHEDULE -- our 52.8 eFG
   against "Elmhurst allow 43.0" -- and both halves were then ADDED. Elmhurst's 43.0 was earned against DePauw,
   Hope and Ripon; our 51.6 allowed came from Carroll and Ripon. The two halves are the same schedule comparison
   from opposite ends, so adding them counts it twice instead of cancelling it. Shot quality printed **+7.0 for
   us** when the matchup estimate is **-2.8 against us** -- a sign error in the headline verdict -- and the page
   totalled +9.8, a blowout nothing in the data supports.
2. **Free throws counted double.** `... * fga_g * 2 * ftpct`: a free throw is worth about 0.66 points, not 1.3.
3. **Offensive boards against the wrong denominator.** `poss_g * 0.30` stood in for rebound chances. The chances
   are the missed shots (33.4 a game here), and the board is a fresh possession at the going PPP.

**The fix.** What a team should do IN THIS GAME is the midpoint of its own rate and the other team's matching
defensive rate -- the usual matchup estimate with no league average to divide by. The two midpoints are compared,
which takes both schedules out of it. The US / THEM columns now show those expectations (header: "Us here" /
"Them here"), not season averages, and the verdict ends with what the four rows add up to.

**Cross-check** (this is the test to repeat if the conversion is ever touched again): expected points built
independently from the same rates give 72.3 us / 68.6 them, a +3.7 margin from shooting and free throws -- exactly
what the shot-quality and free-throw rows sum to. Season averages are 75.5 and 72.7, so the level is right too.

**Elmhurst, Nov 18, corrected:** free-throw rate **+6.5** (44.0 vs 27.0) | shot quality **-2.8** (47.9 vs 50.3) |
turnovers **-1.1** (18.1 vs 16.5) | offensive boards **-0.7** (30.3 vs 32.3). Total **+1.9**, a one-possession
game. The real edge is the line, not shooting -- and the three negative rows agree with the staff's own keys
("BE STRONG & PHYSICAL V. THEIR PRESSURE", "WIN THE GLASS & TURNOVER BATTLES!"), which the broken version
contradicted.

Preview regenerated at `what_matters_preview.html` (repo root, 42,190 b).


## 2026-11-17 -- the upcoming opponent's FastScout report must match the game date

Requested, with FastScout showing Elmhurst twice -- "Nov 18, 2026" (Andy Fitzgerald) and "Dec 02, 2025" (Luke
Freitag, last modified Nov 16, 2026, so it sorts near the top): "make sure that our scouting reports are pulling
only coaching scouting reports from FastScout that match the Game Date. I don't want it using the one from the
game from 2025-2026."

**Checked first: today's brief is already correct.** `uww_opponent_game_plans` has Carroll 2026-11-07, Ripon
2026-11-14 and Elmhurst **2026-11-18** -- each opponent's plan from the report written for that game. The
download end was already strict: `_find_matching_scout_document_row` (02) matches the documents page's Game Date
column including the year, which was fixed earlier when Ripon's brief picked up St. Thomas's 11/14/**25** report.

**What was NOT checked -- the other end.** When no report for the upcoming game is on disk, `_hist_paths` falls
back to the most recent OLDER report and every downstream cell treats its keys, strengths and schemes as the plan
for THIS game. Nothing fails; the only sign is a small "2025-26" tag beside the keys on the brief. That is exactly
the case Corey was worried about, and it would have happened the moment the 11/18 download failed.

**The guard** (`08_parse_each_opponent_fastscout_scoutbuilder.py`): the upcoming game's date and opponent come from
the schedule built in 02 (`Upcoming == "Yes"`, `_parsed_date`, else `parse_schedule_date`). The report chosen for the
upcoming opponent must carry that date. If it doesn't, it goes into `scout_report_stale[opp] = (filename, the date
it was written for, the date it had to match)`, is dropped from `scout_reports_upcoming`, and prints a `!!` line
naming both dates. `10_extract_uw_whitewater_offensive_and.py` then drops that opponent's rows from
`all_game_plans` -- what the app, the keys to victory and the brief read -- while `all_game_plans_history` keeps
them, since 11 / 12 need those keys paired with the game they were written for. The report also stays in
`scout_reports`: the roster and the season stats are its own game's and are still right.

`SCOUT_REPORT_MUST_MATCH_GAME` (default **True**) turns the enforcement off; the `!!` line prints either way.

**Known consequence -- preseason and season-opener briefs.** When the only report for the upcoming opponent is
last season's, that is now a stale report and its staff keys are dropped, so a preseason brief comes through with
data-driven keys only instead of last season's staff keys tagged "2025-26". If that is not wanted for a
scrimmage or an opener, set `SCOUT_REPORT_MUST_MATCH_GAME = False` for that run.

Tested offline against the real inputs folder, four cases: this game's report present (passes, named in the log);
only the Dec 02 2025 report (flagged, dropped); both present (the 11/18 one is used); a report for a LATER game
(11/21) with this game's missing (flagged, dropped).


## 2026-11-17 -- WHAT MATTERS: the man named in the verdict follows the factor

Corey, reading "This game turns on free-throw rate ... and Dominic Trelenberg is the one to take away (16.0 a
game)": "Why is the Dominic Trelenberg comment in there? Shouldn't it list out which player of theirs gets to the
free throw line the most?" Right -- the verdict named the LEADING SCORER whatever the factor was, so the sentence
read as a non sequitur unless shot quality happened to win.

`_wm_face(k, net)` now picks the opponent player the winning factor actually runs through, and the clause says
what he does about it:

| factor | net our way | net their way |
|---|---|---|
| Shot quality | the leading scorer, with his three-point percentage ("the one to take away") | same |
| Free-throw rate | **who fouls the most** -- we are the ones getting there, so the man is the one to go at | who draws the most attempts ("lives at the line") |
| Offensive boards | the offensive-rebound leader ("the one to box out") | same |
| Turnovers | their most turnover-prone ("gives it away most") | their steals leader ("takes it off us") |

**Ties.** `idxmax()` hands a tie to whoever sorts first -- the same fault as the 11/14 `_pn_sole_leader` bug (Jose
Gonzales called "primary creator" over three players with the same 2 assists). Two tied are both named, with the
verb and "each" adjusted; three or more and no one is named, the clause is simply left off. An 8-minutes-a-game
floor keeps a 4-minute player with 2 fouls from topping a per-game rate.

Elmhurst now reads: "... and **Aidyn Boone** and **Vinnie Adjahoungbeta** foul the most (3.3 a game each) -- go at
them." Both branches of all four factors were run against the real box score: Trelenberg (16.0, 43% from three) /
Boone + Adjahoungbeta (3.3 fouls) / Trelenberg (4.7 attempts) / Adjahoungbeta (3.7 offensive boards) / Cherry (2.0
turnovers) / steals correctly left unnamed -- Ketchum, Adjahoungbeta and Marshall are all on 1.7.


## 2026-11-17 (third pass) -- the net ratings, again: free throws are not free

Corey: "I also am not sure that the net ratings are correct yet." He was right again. The 11/17 fix corrected the
BASELINE (midpoints instead of each team against the other's schedule) but kept converting each factor to points
on its own, and the free-throw row was still badly wrong.

**The fault.** Extra trips to the line were counted as pure added points: 9.8 extra attempts x 66% = +6.5 a game.
But a trip to the line USES UP the possession it came from -- the possession identity says so outright
(`P = FGA - OREB + TO + 0.475*FTA`) -- so those trips replace field-goal attempts worth about a point each. The
free-throw edge is worth about **+0.9**, not +6.5, and the error was large enough to flip the page's verdict: it
called the game "+1.9 to us" when the model says we should expect to trail by about four.

**The fix: one scoring model instead of four conversions.** FGA is solved out of the possession identity, with
`TO = TOV*P`, `FTA = FTR*FGA`, `OREB = ORB*(1-FG%)*FGA`:

    FGA    = P * (1 - TOV) / (1 + 0.475*FTR - ORB*(1 - FG%))
    points = 2*eFG*FGA + FTR*FGA*FT%

Each factor is then worth what we lose by playing it at their rate with everything else held (swap one,
recompute, difference). The rows add up to the expected margin because they are differences of one model rather
than four separate conversions.

**VALIDATION -- repeat this if any of it is touched.** Fed a team's own rates and pace, the engine must return
that team's real scoring. UW-Whitewater: 75.5 points on 54.5 attempts vs 75.5 on 54.5 actual -- exact. Elmhurst:
74.7 on 63.1 vs 72.7 on 61.3, about two points high because ORB% has its own denominator (offensive over
offensive plus defensive rebounds, not over missed shots). The old per-factor conversions passed no such test.

**Elmhurst, Nov 18, third version:** shot quality **-2.6** | turnovers **-1.3** | free-throw rate **+0.9** |
offensive boards **-0.8**. Expected here: UW-Whitewater 70, Elmhurst 74. The page now leads with shot quality and
names Trelenberg, which is the right man for that factor.

**The three versions, for the record:** +7.0 / +2.3 / +1.4 / -0.9 (schedule double-counted), then
+6.5 / -2.8 / -1.1 / -0.7 (baseline fixed, free throws still free), now -2.6 / -1.3 / +0.9 / -0.8. Any brief
produced before this entry has the wrong numbers on that page.


## 2026-11-17 -- WHAT MATTERS: the countable version of each row, and where this sits next to Dean Oliver

Corey: "I don't understand how 44.0 is +.9 compared to 27." Fair -- the rate columns showed a 17-point gap beside
a net under a point. A new **IN THIS GAME** column now carries the countable thing behind each rate, us v them,
from the same model: points from the floor, giveaways, second shots, free throws. The footnote explains the one
thing a reader has to know: those counts carry every factor at once, while NET moves one factor and holds the
rest, so the two can differ without contradicting each other. Free throws spelled out: 25 trips against 17 is
worth about +5.4, the ~5 shots from the floor those possessions cost is about -4.5, net about +0.9 -- roughly a
third of a point a trip, not the whole trip.

**Against Oliver.** Same four factors, same definitions for eFG% and ORB%. Two deliberate departures, both
already in the code: free-throw rate is FTA/FGA (the Basketball-Reference convention) where Oliver's original is
FTM/FGA, and possessions use 0.475 (Ken Pomeroy's college coefficient, a change Corey requested) where Oliver
uses 0.44.

**The real difference is the weighting, and the two sections of the brief disagree because of it.** Oliver's
40 / 25 / 20 / 15 are fixed league-average importance weights, and `_SB_FF_WEIGHTS` (section 87, line ~881) uses
them for the app's Four Factors dialog. WHAT MATTERS does not weight at all -- it prices each factor through the
scoring model for THIS matchup, so a factor's value depends on how big that particular gap is and what the
possessions around it are worth.

For Elmhurst the two orderings disagree at the top. Oliver's weights on the unadjusted season rates:
FT Rate +3.15, eFG +1.56, ORB +0.80, TOV -0.68 -- free throws first. WHAT MATTERS: shot quality -2.6, turnovers
-1.3, free throws +0.9, boards -0.8 -- shooting first. Both are "the four factors"; they answer different
questions (fixed importance on raw season edges vs what each is worth in this matchup once free throws are
charged for the possessions they use). Worth knowing before a coach puts the two side by side.


**Labelled, both sides (11/17, "Leave them and label them").** The two rankings stay as they are, each saying
what it answers:
* `streamlit_app.py`, the Four Factors dialog (~line 14410): a second `st.caption` -- this ranks by Oliver's
  fixed weights on season rates, the brief's WHAT MATTERS prices each factor for this opponent with free throws
  charged for the possessions they use, so the two can lead with different factors and neither is wrong.
* `87`, WHAT MATTERS: a visible `mini` line under the table saying the same thing from the other side, with a
  link to the app's dialog -- on the page, not only in the footnote, since nobody opens a footnote mid-practice.
  The footnote also now states plainly that these ARE Oliver's four factors, names the two definition
  departures (FTA/FGA rather than FTM/FGA; 0.475 rather than 0.44) and says the ranking is the part that is not
  his.


## 2026-11-17 -- WHAT MATTERS: the duplicated blocks taken out

Corey, on the player cards and the key list: "I think we need to remove this part of that section because it's
duplicated throughout the scouting report." Removed from `_wm_what_matters()`:

* **WHO DECIDES IT** (three player cards) -- the same tendencies line and the same offensive role the personnel
  section prints further down, in its own cards. With it went `_wm_player_card()`, `_agg`, and the
  `uww_offensive_roles` / `uww_player_tendencies` reads that only fed it.
* **THE KEY THAT COVERS IT** -- it restated keys printed a few inches above it. With it went `_KEYWORD` and
  `_wm_key_for()`.
* Their CSS (`.wm-who`, `.wm-p*`, `.wm-swing*`).

What is left is only what appears nowhere else on the brief: the verdict, the four factors priced for this
matchup with the countable column, the Oliver label, and the expected score. The man named in the verdict stays
-- that is one name tied to the deciding factor, not a roster block, and `_wm_face` still needs `_all`.

87: 453,097 -> 448,323 b. The page is now about half a page, which is what a one-pager under the keys should be.


**Column renamed (11/17, requested): "Net" -> "PPG difference"**, in the table header and everywhere the
footnote referred to it. Both say the same thing -- the points a game that factor is worth to us -- and the new
label says it without a coach having to work out what "net" is the net OF.


## 2026-11-18 -- "FOUR FACTORS", and every section behind an expander

Two requests: rename the section, and "I'm looking for the scouting briefs to show the most important
information and then hide the rest of it behind an expander", with Streamlit's lazy-loading `st.expander`
example as the model.

**Renamed.** WHAT MATTERS -> **FOUR FACTORS** (the scales icon, matching the app's own Four Factors dialog).
`_AN_DROP` updated with it, or `parser_analysis` would stop leaving the section out.

**Expanders.** The brief is a file that gets emailed and printed, so the HTML equivalent of `st.expander` is
`<details>`, which the brief already uses for the play-call tables. `_sb_collapse()` runs over the output chunks
just before they are joined: every run from one section header to the next becomes
`<details class="secdet"><summary>` + that section's own header bar + `</summary>` + its content. The header bar
IS the summary, so the brief opens as a page of headings with a chevron on each.

* `BRIEF_OPEN_SECTIONS` (notebook cell) decides what starts open; default `("KEYS TO VICTORY", "FOUR FACTORS")`,
  matched case-insensitively against the title, so "KEYS" is enough.
* `BRIEF_COLLAPSE_SECTIONS = False` turns the whole thing off and prints the brief as one long page again.
* Banners, dividers and the footer are left alone -- they are not sections and are needed on sight. A section
  header with no body under it is left alone too.
* **Printing is already handled**: the `<head>` script opens every `<details>` on `beforeprint` and closes them
  again on `afterprint`. That was added for the collapsed play-call tables and covers this for free -- a printed
  or PDF'd brief is still the whole brief.

Checked against the brief Corey generated at 10:26 UTC: 12 sections, every one wrapped, KEYS TO VICTORY open.
FOUR FACTORS will join it once the brief is run again (that copy still has the old section title).


## 2026-11-18 -- the Four Factors header IS the verdict

Corey: "Instead of 'FOUR FACTORS', I want it to say 'This game turns on shot quality: ...' before it is
expanded. Expanding the section will give the full Four Factors table."

The section's header bar is now the verdict sentence itself, so closed it already answers the question and
opening it is for the table behind the answer. The verdict is therefore built BEFORE `section()` is called --
`_wm_face`, `_top` and the `_v` string all moved above it -- and the separate `<p class="wm-verdict">` is gone.
`.sect .t .wm-sumline` styles that one header as a sentence (weight 600, normal letter-spacing, body colour)
with the bolded parts in Warhawk purple.

**`<!-- FOUR FACTORS -->` inside the title is load-bearing**, and invisible to a reader. Two things match on
section titles: `_AN_DROP` (ANALYSIS_MODE decides what to leave out) and `BRIEF_OPEN_SECTIONS`. With the title
now a sentence about us and them, neither had anything to match, and `parser_analysis` would have started
printing a UW-Whitewater comparison into a no-UWW brief. `_sb_collapse` strips `<!--` / `-->` before matching so
the name still works for both.

`BRIEF_OPEN_SECTIONS` default is now `("KEYS TO VICTORY",)` alone -- Four Factors starts closed by design.

Demo rebuilt from Corey's 10:26 brief: 12 sections, KEYS TO VICTORY open, the Four Factors bar reading
"This game turns on shot quality: ..." and opening to the table.


## 2026-11-18 -- starters across the top of each roster, and the expander icon

**The five starters, in a row.** Requested: "Just put the 5 starters in a horizontal line with their photos,
offensive and defensive roles and main information (one to two sentences) about them. Then there should be a
collapsible section underneath that opens the current roster section." New `_starter_strip(side, names,
stats_df)` in 87 draws photo, name (linked into the app), bio, the per-game line, Off and Def roles and one or
two sentences per starter, five across. **It reads everything from `_roster_player()`** -- the same builder the
roster table underneath uses -- so the strip can never say something different from the card it sits above.
The sentences are his lead notes first (the 2-for-1 call, a transfer line, the coaches' own read), then whatever
the Offense and Defense columns lead with, de-duplicated, two at most.

Under the strip, everything that was the roster section -- every starter's card, every bench tier, the notes --
is inside `<details class="rosdet">` ("Full roster"). `BRIEF_OPEN_SECTIONS` default is now `("ROSTER",)`, so a roster
section opens to its strip with the rest one click down.

**KEYS TO VICTORY is not collapsible at all** (requested: "can be kept out of a collapsible section and should
always be visible") -- not an expander that starts open, no expander: `_SB_FIXED` / `BRIEF_FIXED_SECTIONS`
(default `("KEYS TO VICTORY",)`) makes `_sb_collapse` emit those sections exactly as they were built, so there is
no chevron to click and no way for anyone to collapse the one section that has to be read.

Tested in isolation against six fake players: 5 drawn and the 6th cut, balanced divs, a missing photo, NaN and
None stats, a dict instead of a Series, tuple and plain-string read items, a line repeated between lead and
offense (de-duplicated to one), and an empty starter list (nothing emitted at all).

**CONFIRMED BUG (fixed) -- the expander icon was a tofu box.** Corey: "I don't think the icon for the expander
is working." `content: "\25b8"` (and `\25be`): Montserrat has neither glyph, so the browser drew its .notdef
box with the codepoint inside, and the open-state `rotate(90deg)` turned that box on its side -- which is what
the screenshot showed. Both are now triangles **drawn with CSS borders** (`border-left` solid, top and bottom
transparent), rotated 90 degrees when open. A border triangle is a shape, not a character, so no font can fail
to render it. The rule holds for anything added to this brief later: it is printed and PDF'd on machines whose
font fallback is unknown, so symbols get drawn, not typed.


## 2026-11-18 -- Expand all

Requested: "Create an expand all button or option somewhere." One button, top right of the page, above the
banner. It opens EVERY `<details>` in the brief -- the section expanders, the full-roster blocks and the
play-call tables that were already collapsible (15 of them on the Elmhurst brief) -- and re-labels itself
"Collapse all" once everything is open.

* It stays in step with the chevrons: opening or closing any single section re-labels the button. `toggle` does
  not bubble, so the listener is registered on `document` with capture, which is how one listener hears all of
  them.
* Built in the final assembly rather than through `add()`. It belongs to the page, not to a section, and
  `add()` would have dropped it in ANALYSIS_MODE, where everything before the first section is skipped.
* `.xall` is `display: none` until the script sets `.js` on `<html>`, so nobody is shown a button that cannot
  work, and `@media print` hides it -- printing already opens everything by itself.
* Not emitted at all when `BRIEF_COLLAPSE_SECTIONS` is False: with nothing collapsed there is nothing to expand.


## 2026-11-18 -- the starters row is always on the page

Requested, looking at the rendered strip: "I want these removed from the roster collapsible section. So the five
starters row should always be visible." Both ROSTER sections join KEYS TO VICTORY in `_SB_FIXED` --
`BRIEF_FIXED_SECTIONS` now defaults to `("KEYS TO VICTORY", "ROSTER")`, so neither is wrapped in a section
expander at all and neither can be collapsed by anyone.

The rosters keep their own inner **Full roster** expander: the five-across strip is always on the page, and the
cards, the bench and the reads are behind that one click. `BRIEF_OPEN_SECTIONS` now defaults to empty -- with
Keys and the rosters always on, everything that is still an expander starts closed.

So the brief reads, top to bottom: banner -> Keys to Victory (fixed) -> the Four Factors verdict in one line,
openable -> the opponent's five starters (fixed) with the full roster one click down -> our five -> every other
section closed -> Expand all, top right, for the whole lot at once.


## 2026-11-18 -- recent results gets the same treatment

Requested: "I want to do something similar with the recent results section." It was five chips and nothing else,
so the shape is: the last five games always on the page, the rest of their season behind one expander.

* The section joins `_SB_FIXED`, under both of its titles -- "RECENT RESULTS" and, on a preseason brief,
  "HOW THEY FINISHED LAST SEASON" -- so it can never be collapsed.
* A record line above the chips: `5-3 so far - 3-1 at home - 2-2 away`, from `opp_before`'s own outcomes, with
  the home and away halves left out when there are none.
* Games older than the last five go into `<details class="rosdet">` ("Every other game -- N earlier games this
  season"), the same control the roster uses. `_rs_chip()` builds a chip for both lists, so the two can't drift.

Tested against 0, 1, 3, 5 and 8 games: nothing at all for 0; chips only up to 5; at 8, five chips and an
expander holding the other three; balanced markup and a correct record line in every case. Elmhurst has three
prior games, so right now it shows the record and three chips with no expander.

`BRIEF_FIXED_SECTIONS` default is now
`("KEYS TO VICTORY", "ROSTER", "RECENT RESULTS", "HOW THEY FINISHED LAST SEASON")`.


## 2026-11-18 -- every section: a real headline, the rest behind one expander

Requested: "Do the same with all other sections as well", and, asked whether to write a real headline per
section or just hide the body behind a generic bar, Corey chose the real headline.

**The mechanism.** `_sb_sechead(html)` emits a `<div class="sechead">` straight after a section header.
`_sb_collapse` recognises it: header and headline stay on the page, everything after them goes into one
`<details>` ("Show the detail -- tables, reads and notes"), and the section is never wrapped in a section
expander of its own. A section that emits no headline keeps the old behaviour and collapses whole. Each
headline is computed from the very data that section is about to render, so the two cannot disagree, and each
prints nothing when its data is missing.

| section | headline | source |
| --- | --- | --- |
| TEAM STATS | Biggest gap: FT Rate -- us 51.4, them 30.4 (ours) | `_ff_top`, already ranked for the Bottom Line |
| TOP LINEUPS (theirs) | Most minutes: Boone / Trelenberg / Cherry / Pearson / Adjahoungbeta -- 37 min, -3 net | `lineups` |
| OUR TOP LINEUPS | Most minutes: Madson / Robinson / McEwen / Rogers / Teague-Johnson -- 25 min, -5 net | `_uww_lu` |
| HOW THEY GUARD SCREENS | Against the ball screen they mostly flat hedge -- 1 of 3 tagged (+ "thin sample, confirm on film" under `_scv_thin_n`) | `_scv_t` |
| WHAT TO PLAY THEM IN | Play them in <defense> -- N.NN points a possession on N tagged | `_pf_opp`, 3+ clips |
| HOW THEY RUN OFFENSE | Most-used set: Motion -- 14 tagged possessions, 0.43 points each | `uww_play_call_summary` |
| HOW WE RUN OFFENSE | Most-used set: Motion -- 24 tagged possessions, 0.77 points each | same |

`_lu_short()` turns "Aidyn Boone, Dominic Trelenberg, ..." into "Boone / Trelenberg / ..." -- five full names do
not fit on one line and the surnames are what a coach says out loud.

Tested: the collapse pass against a section with a headline (header + headline out, rest behind the expander),
one without (collapses whole) and a fixed one; and every headline computation above run against the real CSVs,
which is where the table's example values come from.

**Still collapsing whole, having no headline yet:** THIS SEASON vs LAST SEASON, LATE-GAME FOUL LIST, WHEN WE'VE
PLAYED <OPP>, TWO-FOR-ONE, NEEDS TAGGING OR STAFF INPUT, SELF-SCOUT FROM THE FILM. They are situational or
list-shaped; say the word and they get headlines too.


## 2026-11-18 -- TEAM COMPARISON, and the headline that named our own set as theirs

**Combined (requested): "Combine these two sections into a 'Team Comparison' section."** FOUR FACTORS and TEAM
STATS are one section now, `📊 TEAM COMPARISON`: the section header, then the verdict sentence as its headline
line (`_sb_sechead`, the same treatment every other section got), then behind "Show the detail" the four-factors
table, the Oliver label, the expected score and -- under a "Season averages, per game" sub-heading -- the strip
that used to be TEAM STATS. The old TEAM STATS section is gone. `_AN_DROP` now matches TEAM COMPARISON, or
`parser_analysis` would start printing a UWW comparison into a no-UWW brief.

Its old headline went with it, and that is a relief: it read **"Biggest gap: FT Rate -- us 51.4, them 30.4"**
off `_ff_top`, which is Dean Oliver's FIXED weighting, while the table two inches above it had free throws
FOURTH at +0.9 and shot quality first. Two rankings of the same four factors contradicting each other on one
page -- the exact confusion the 11/17 labels were written to keep apart. Combining the sections removes it.

**CONFIRMED BUG (fixed) -- "HOW ELMHURST RUNS OFFENSE" was headlined with OUR set.** Corey: "something doesn't
seem correct with the headlines that were created." `_sb_pc_top()` read `uww_play_call_summary` directly, and
`side` there names the FILE a clip came from, not whose possession it was: the Opponent file carries our own
offensive possessions from that game as `possession_side = "Defense"`. The headline therefore read
**"Most-used set: Motion -- 14 tagged possessions, 0.43 points each"**, which is OUR Motion run against them
(hence the key "Feature our best look: Motion"). This is the same class of fault `_offense_rows()` was written
for -- its docstring records a SLOB finished by a Ripon player turning up under our own sets.

Fixed by going through `_offense_rows()`, the filter the section's own tables use, and dropping the
"unspecified" bucket as they do. Elmhurst now reads **"Most-used set: Flow -- 7 tagged possessions, 1.43 points
each"**, which agrees with the key "Take away their go-to set: Flow". Ours is unchanged at Motion, 24 at 0.77,
though its third row moves, so the filter mattered on both sides.

**Rule for any future headline: compute it through the section's own selection, never from the CSV directly.**


## 2026-11-18 -- lineup cards, and the two foul flags on the starter cards

**OUR TOP LINEUPS & 3-MAN COMBOS, in the roster's shape** (requested: "three cards always visible which show
the top lineups by MIN, +/-, and PPP. Then have the expandable full table below. Do this for 5 and 3 man
lineups"). `_lu_cards(side, five_df)` draws a row of cards for the five-man units and another for the trios,
then the existing `lineups_table` / `combos_table` sit behind one "Full tables" expander. The section joins
`_SB_FIXED` ("OUR TOP LINEUPS"), so the cards cannot be collapsed, and the one-line headline it had is gone --
the cards say it with the numbers attached.

* **One implementation, shared.** `_unit_clips()`, `_unit_on()` and `_unit_ppp()` were lifted out of
  `combos_table` into the enclosing scope and `combos_table` now calls them, so a card and the table row it
  stands for match possessions to units the same way -- that function's own note demanded no duplicate clip
  matching. Five-man PPP comes from `_five_ppp_map()`, the same "Personnel grouping" rows the table's PPP
  column ranks on; PPP needs 3+ tagged possessions, as there.
* **CONFIRMED CHANGE -- minutes floors on the cards.** Without them "Best +/-" and "Best points per
  possession" both landed on a five-man unit that had played FOUR minutes (+9, 1.71 PPP). They now rank only
  units clearing the same floor the tables use (`five_min_minutes` 8.0; our trios `uww_three_min_minutes` 40),
  and if nothing clears it the best of what exists shows with a `*` and a line saying so -- the convention the
  lineup tables already use.
* **Merged titles.** One unit often tops more than one column early in a season, and three identical cards
  read as a rendering fault. Titles merge onto a single card instead: our trios currently show one card,
  "Most minutes, best +/- and best points per possession -- Madson / McEwen / Rogers, 43 min".
* Current output: five-man "Most minutes: Madson / Robinson / McEwen / Rogers / Teague-Johnson, 25 min" and
  "Best +/- and best points per possession: Madson / Robinson / Lukenbill / McEwen / Teague-Johnson, +6 in 8
  min".

**The two late-foul flags on the starter cards** (requested: "Add the foul late and don't foul late flags to
the bottom of the starters cards. But only those 2 flags."). Same source, wording and styling as the player
card's own flag -- `_foul_by`, from the late-game foul list -- and **no neutral chip**: a card shows one of the
two calls or nothing at all. Opponent side only; those calls are about fouling THEM. Checked against the real
table: Cherry "Don't foul late" (87.5% FT), Ketchum "Foul him late" (25%), Boone neutral so nothing, a player
missing from the table nothing, and our own side nothing.


## 2026-11-18 -- lineup cards: three always, no headers, both teams

Requested: "Don't dynamically group the top lineups by MIN, +/-, and PPP even if they are the same lineups.
List all three of them separately. Remove the 'OUR TOP LINEUPS & 3-MAN COMBOS' header. And this also needs to
be done for their top lineups."

* **No grouping.** The merge-identical-titles behaviour from an hour ago is out: three cards, in that order,
  always. A unit that tops two or three columns simply appears on each of them.
* **No section header, either side.** Neither `section("TOP LINEUPS & 3-MAN COMBOS")` nor its OUR counterpart
  is emitted. The cards are the heading. The methodology footnote that hung off each title now rides on that
  side's "Full tables" bar (`_lu_note`), so the link to the notes page is not lost with the header. With no
  header of their own, both blocks ride inside the roster section above them, which is itself always visible,
  and "OUR TOP LINEUPS" came out of `_SB_FIXED` as a title that no longer exists.
* **Theirs now matches ours**: `_lu_cards("Opponent", lineups)` above a "Full tables" expander holding
  `lineups_table` and `combos_table`, and their old one-line headline is gone.
* **PPP says how many possessions it rests on.** Their most-used five showed "1.83 PPP" -- true, and on SIX
  tagged possessions. The card's sub-line now reads "37 min - -3 - 1.83 PPP on 6 tagged" so the number cannot
  look better founded than it is.

Both sides run against the real tables. Theirs: five-man most minutes Boone / Trelenberg / Cherry / Pearson /
Adjahoungbeta (37 min), best +/- Boone / Trelenberg / Marshall / Cherry / Adjahoungbeta (+5 in 9), best PPP the
most-used five (1.83 on 6); trios most minutes Boone / Trelenberg / Cherry (60 min), best +/- Colvin / Ketchum
/ Smith (+11 in 16), best PPP Boone / Pearson / Adjahoungbeta (1.83). Ours: 25-minute five, the 8-minute five
at +6 for both +/- and PPP, and one trio (Madson / McEwen / Rogers, 43 min) on all three cards.


## 2026-11-18 -- the 3-man table picked like the 5-man one, surnames in both

Requested: "The 3 man lineup table should be formatted similar to the 5 man lineup with the top 2 of each of
the 3 metrics. Remove first names to make it cleaner."

`combos_table` no longer ranks every trio by shrunk margin per 40 and prints the best three. It is picked the
way `lineups_table` picks fives: **the top 2 in MINUTES, in +/- and in PPP**, each trio listed once however
many columns it tops, with its top-2 values bold. PPP still needs 3+ tagged possessions to be ranked on, the
`*` still marks a trio under the minutes floor, and trios with identical numbers still collapse to one row
with "(+N identical)" -- that was `_rank_units(collapse_twins=True)` and is now inline, since the new
selection does not go through `_rank_units`.

Our side keeps the "Feature the ... combo" key's own bar (games played, on/off positive), but only when at
least one trio clears it -- with two games played nobody has 3 GP yet, and without that guard the table would
have come out empty.

**Surnames in both tables.** "Collin Madson, Kelton McEwen, Rashad Rogers" is now "Madson / McEwen / Rogers",
in the five-man table too, with the full names on the cell's tooltip so nothing is lost.

Checked against the real tables, both sides. Ours: 5 rows, 6 bolded cells -- Madson / McEwen / Rogers 42.8 min
and Madson / McEwen / Teague-Johnson 42.4 for minutes, Madson / Rogers / Castillo +13 and Madson / Lukenbill /
McEwen +12 for +/-, 1.47 and 1.33 for PPP. Theirs: 6 rows, 6 bolded -- Boone / Trelenberg / Cherry 60.3 and
Boone / Trelenberg / Adjahoungbeta 57.9, +12 and +11, and two trios tied at 1.83 PPP.


## 2026-11-18 -- validating the lineup minutes: the number was right, the heading was wrong

Corey: "Validate that this data is being calculated correctly. I don't think a 3 man lineup can be averaging
this many minutes per game." Right to ask, wrong culprit: **MIN in the lineup tables is a SEASON TOTAL**, not a
per-game average. Boone / Trelenberg / Cherry's 60.3 is 20.1 a game across three games, which is ordinary for
three starters.

**Validated four ways before changing anything** (repeat these if the lineup tables are ever reworked):
1. The five-man units sum to **118.6** minutes against **120** of game time (40 x 3 games) -- one unit is on
   the floor at a time, so the total has to land there.
2. The trios sum to **1186** against the **1200** expected: every five contains C(5,3) = 10 trios, so the trio
   total must be ten times game time.
3. No trio exceeds the season minutes of its own least-used player -- 60.3 against Cherry's 66.7, the tightest
   of them, and every one of the top trios passed.
4. Elmhurst's player-minutes sum to 592.8 against 600 (40 x 5 x 3), so the box score behind all of it is sound.

The gap between 118.6 and 120 (and 592.8 against 600) is stint rounding in the play-by-play, not a fault.

**Fixed: the heading.** `MIN` now reads `MIN (3 g)` -- `_min_head(side)` from `_side_games(side)`, counted off
the same box scores TEAM COMPARISON uses -- in the five-man and 3-man tables, both sides. The cards say it in
words: "60 min over 3 games". A per-game reading is no longer available to a tired reader at 6am.


**Minutes now read per game (requested, same morning).** `MIN` became `MIN/G` in both lineup tables, both
sides, and the cards say "21.4 Min/G" -- the column name itself rather than a sentence (requested). Only the DISPLAY divides by games on file (`_min_pg`); the stored
number stays the season total, because the ranking, the minutes floors and the **per 40** column are all
computed from it -- dividing before per 40 would have quietly broken that column. Each minutes cell carries
the total on its tooltip ("42.8 minutes in all"), and the below-floor note now reads in the same units:
"under 20.0 minutes a game together (40 in all)".

Elmhurst's trios now read 20.1 / 19.3 / 14.8 a game instead of 60.3 / 57.9 / 44.3 in all -- the number Corey
expected to see when he challenged it.


**"on N tagged" off the cards (requested: "No where in the scouting brief does it need to say '...on 85
tagged'").** The lineup cards read "0.88 PPP" now. The possession count is still kept in the data -- the
3-possession floor before a PPP can be ranked on still uses it -- and still sits on the table cell's tooltip,
so the sample is one hover away without spending card space on it.

Two other places still put a count in visible text, both older than these cards and both left alone for now:
the WHAT TO PLAY THEM IN headline ("N.NN points a possession on N tagged") and a game-plan sentence that reads
"(1.23 PPP on 7)".


**All of them, then (requested: "Remove those as well").** No possession counts anywhere in the brief's
visible text:
* WHAT TO PLAY THEM IN headline -> "Play them in <defense> -- N.NN points a possession". The 3-clip floor
  still decides whether the line prints at all; it just no longer says so out loud.
* the game-plan sentence under that table -> "They struggle most against X (0.83 PPP) and hurt you most
  against Y (1.42 PPP)".
* HOW THEY / WE RUN OFFENSE headline -> "Most-used set: Flow -- 1.43 points a possession".
* the player card's film line -> "Tagged film: featured in 5 Out Motion (14x), Flow (6x), Cheetah (4x) --
  1.06 PPP." The per-set (14x) counts stay: those are the content, not a sample-size disclaimer.

Every floor and minimum behind these lines is unchanged -- 3 tagged possessions before a PPP is ranked on,
3 clips before a defense family is named, 3 uses before a set is listed. What changed is that the brief no
longer narrates its own sample size; the counts remain in the tables, the tooltips and the app.


## 2026-11-18 -- the lineup cards say what the unit is

Corey picked option B from three mock-ups and asked to fold in two clauses from the others: "31% of their floor
time", who the shooters are, and "Five out, no true big. Adjahoungbeta is the only one on the glass."

A card now reads:

    Most minutes - 31% of their floor time
    Boone / Trelenberg / Cherry / Pearson / Adjahoungbeta
    12.4 Min/G
    12.4 Min/G - -3 - 1.83 PPP
    Four of five take threes: Trelenberg 7.7 3PA (43%), Boone 5.3 3PA (44%), Pearson 3.7 3PA (27%),
                              Cherry 2.7 3PA (50%)
    Five out, no true big. Adjahoungbeta leads the group on the glass (3.7 offensive boards a game).

`_lu_read(side, lineup, grouping)` builds the two lines, `_lu_box(side)` the per-player totals behind them,
`_lu_groupings(side)` the shape. Every clause is read off tables the brief already prints, and any clause
whose data is missing is simply left out -- a trio has no grouping row, so it gets no shape sentence.

Rules, each chosen so the line cannot overstate what is behind it:
* **Shooters**: 1.5+ three-point attempts a game, most first, **four names at most**. A fifth name is the man
  nobody is closing out on, and the line stops being a list of who to chase -- it was listing Adjahoungbeta at
  2.0 attempts and 17% alongside Trelenberg at 7.7 and 43%.
* **Shape**: "Five out, no true big" only when the lineup's own position grouping (3G-2B, 2G-3W ...) carries no
  B. It is the parser's own shape string, not a guess from heights.
* **Glass**: "is the only one on the glass" only when the next man has a third of his boards or fewer;
  otherwise "leads the group on the glass". Per game, like everything else on the card.
* The share is minutes over 40 x games -- the floor time there is to take.

Wording bugs caught in the same pass: "One of 3 take threes" (now "One of three takes threes"), the mixed
word-and-digit counts, and "leads them on the glass" printing on our own cards about our own players.


## 2026-11-18 -- what each lineup struggles with, per card, and the footer collapsed

**Offense and defense on the lineup cards** (requested: "include what each lineup has struggled with
defensively and offensively", then "Make that based on which card is shown"). Each card gets the end of the
floor its own metric is about:

| card | line |
| --- | --- |
| Most minutes | "With them out there: 0.78 (team 0.88) scored, 0.91 (team 0.89) allowed" |
| Best +/- | "That margin is the defense: ... scored, ... allowed" -- or "Neither end stands out" |
| Best PPP | "Offense with them out there: 0.88 (team 0.88) a possession" |

Both numbers are points per tagged possession with those players on the floor, against the same team's own
rate. The defensive half is new: `_unit_clips_def()` matches the DEFENDING five. Checked on the data before
relying on it -- on a defensive row `on_court_lineup` is the defending team's five (UWW defending Alma lists
our five, Elmhurst defending DePauw lists theirs), so the same matching works for points allowed.

**CONFIRMED BUG caught before shipping -- thin pools.** With a 5-possession floor this printed
**"0.14 allowed (team 0.61)"** for Elmhurst. Their whole tagged pool is 38 offensive and 38 defensive
possessions with a lineup attached: 0.61 allowed is not a defensive rate, it is a team whose film is barely
tagged, and a unit's slice of 38 is a handful of clips. Then at a 10-possession floor one of OUR
four-minute fives "allowed 0.31" -- four points across a dozen possessions, not a defensive identity.
Final gate: **100+ possessions in that side's pool on that end, 20+ for the unit itself.** Ours clears it
(706 offensive, 564 defensive; 85-115 per unit), so the line shows for us now; Elmhurst's cards carry no
two-way line at all until more of their film is tagged. A missing line is the honest output here.
Also: the +/- card only credits an end that beats the team rate by 0.05 or more, instead of crediting one
that wins only after rounding.

**The footer is collapsed** (requested: "This information should be in a collapsible section as well and be
collapsed by default"). "How this brief was built -- sources, the film tagged behind it, methodology" wraps
the generated-from paragraph, the Built from list and the methodology link. It still prints in full, since the
`beforeprint` handler opens every `<details>`.


**Card layout (requested 11/18):** the share of floor time came out of the card's title and sits with the
minutes it belongs to; the margin and PPP moved to a line of their own under it.

    MOST MINUTES
    Boone / Trelenberg / Cherry / Pearson / Adjahoungbeta
    12.4 Min/G
    12.4 Min/G - 31% of their floor time
    -3 +/- - 1.83 PPP
    Four of five take threes: ...
    Five out, no true big. ...


## 2026-11-18 -- TEAM COMPARISON opens with cards, not a sentence

Requested: replace the section's one-sentence verdict header with "3 to 5 card style pieces of important
information similar to the other sections we've edited recently". Four cards now, built from the same numbers
the sentence carried:

| card | Elmhurst, tonight |
| --- | --- |
| Expected here | UW-Whitewater 70 -- Elmhurst 74 &middot; **~4.2 to them** &middot; about two possessions &middot; built on 2 of our games and 3 of theirs |
| What decides it | Shot quality &middot; **-2.6 PPG** &middot; 53 v 63 points from the floor |
| Where we gain | Free-throw rate &middot; **+0.9 PPG** &middot; 25 v 17 free throws |
| The man | **Dominic Trelenberg** &middot; the one to take away (16.0 a game, 43% from three) |

The third card is "Where we gain" when any factor other than the deciding one is in our favour, and "And
after that" when none is -- it then shows the next biggest problem rather than inventing an edge. The fourth
only appears when `_wm_face` has a man for the deciding factor. `_wm_face` writes its clause to follow a name
("is the one to take away ..."), so on a card, where the name is the line above, the leading verb is dropped.

The cards go through `_sb_sechead`, so they are the always-visible part and the table, the Oliver label, the
expected score line and the season averages stay behind "Show the detail".


**Five cards now (requested): "The man" out, two season-average cards in.** TEAM COMPARISON opens with
Expected here / What decides it / Where we gain / **What we do better** / **What they do better**. The last
two name the biggest season-average edge each way, from the per-game strip that sits inside the same section.

* The rows are collected **as that strip is built** (`_TEAM_STAT_ROWS`), not re-derived, so a card and the row
  it came from cannot disagree -- including on which direction is better, which only that loop knows (points
  allowed and turnovers are won by the LOWER number).
* Ranked by gap **relative to the larger of the two numbers**. A raw gap would hand it to points every time,
  where three points apart is nothing, over steals, where two apart is enormous.
* A percentage row says "by 4.6 percentage points", everything else "by 4.3 a game".

The man card is gone, and with it the only card that depended on `_wm_face` -- that function is still used
for the trailing clause of nothing now, so it stays only as the source of the deciding-factor player if we
want it back.


## 2026-11-18 -- Film Tagging keeps the play videos it makes (clip cache)

**What happened.** The 11/18 `parser_models` spent 18.5 min "making the video of each of 138 play(s)" for
2026-11-14 Elmhurst@Hope and then 1085s pushing clips, on a game that was already in the app with 40 plays
tagged. Nothing was wrong with what it picked. The chain, from `models_20261118_090811.log`:

* line 2195 -- `2026-11-14|Elmhurst@Hope: 2 file(s) by JT (latest 2026-11-18 04:42 UTC) -- 40 play(s) with
  coach answers`. That save carries a `titles` part.
* `55c_play_review.py`, the open-batch check: `_tag_titles_saved(slug_game, old_run)` is tested FIRST, and
  when the coach has saved titles for the run the batch was built from, the batch is finished -- `shutil.rmtree(pkg)`,
  silently (no "rebuilt to the new order" line; that is why Elmhurst@Ripon, UWW@Carroll and DePauw@Elmhurst got
  `open batch -- offense / defense and lineups updated` on lines 2641-2643 and Elmhurst@Hope did not).
* line 2692 -- the new batch is `138 clip(s) to tag -- every untagged possession, both teams (of 138 untagged)`.
  178 clips in the game - 40 answered = 138. No tagged clip's video was re-made.

**The full game is going in, and should stay that way.** `PLAY_TAG_ALL_POSSESSIONS` (default True) and no cap --
`PLAY_TAG_UWW_MAX = None` in parser_nb cell 133, `PLAY_TAG_OTHER_MAX` never set (default None). Note
`PLAY_TAG_PER_GAME_OTHER = 40` in that cell is dead code under the current rule: it only applies on the
`PLAY_TAG_ALL_POSSESSIONS = False` branch. **Do not cap the batch to shorten the run** (I suggested it once;
it is wrong -- the coach is meant to get the whole game).

**CONFIRMED CHANGE (requested).** The cost is real, though: with `PLAY_TAG_REQUIRE_SAVED = True`, every partial
save means the next run rebuilds the batch and re-encodes every clip still untagged. So every play video is now
kept and reused -- `55c_play_review.py` (170,417 b):

* `_pr_clip_cache_dir()` -> `PLAY_TAG_CLIP_CACHE_DIR` or `INPUT_DIR/_clip_cache` (added to `.gitignore`, 693 b).
* `_pr_clip_cache_key(files, fps)` -> sha1 of: `PLAY_REVIEW_VIDEO`, `PLAY_REVIEW_EXPORT_WIDTH` / `_FPS` / `_CRF`,
  the frame rate, the clip's frame file names, and the size + mtime of the file the video is made from (the lean
  mode media, the export clip via `_fx_lookup`, else the first frame). A settings change or a re-exported game
  therefore re-encodes instead of serving a stale-looking video.
* `_pr_clip_cached(files, rows, numtxt, out_base, fps=None)` wraps `_pr_clip` with the same signature and return
  value: a hit is `shutil.copy2` of the video and its poster into the batch; a miss encodes, then copies into the
  cache as `.part` and `os.replace`s it, so a run stopped halfway never leaves a half-written video behind.
  `PLAY_TAG_CLIP_CACHE = False` turns it off; failures to cache print `[clip cache] ... not kept` and are not fatal.
* Both batch builders use it (the Film Tagging batch and `_tag_reopen`'s fix batch). The Play review build
  (line ~1497) still calls `_pr_clip` directly -- it draws number overlays per run and is one play, not 138.
* Each game now prints `[clip cache] <game>: N play video(s) copied from the cache, M newly made`, and the
  "making the video of each" line says the earlier ones are copied.
* The cache is additive -- the parser never deletes from it. A whole season of captured clips (2,271 on 11/18,
  ~2.8 MB each) is single-digit GB against 1.6 TB free on F:. Deleting the folder is safe: it is rebuilt from film.
* The `videos` branch push does not need a matching change: it is a git tree, so a byte-identical video under a
  different `fid` is the same blob and is not uploaded again. The cache makes "byte-identical" certain, where
  re-encoding only made it likely.

**Validation** (`~/wmtest/cache_t.py`, the three functions pulled out by AST with a stub `_pr_clip` that counts
calls): a first request encodes; the batch folder wiped and the same clip requested under a different `fid`
copies from the cache with the right bytes and poster and does not encode; changing `PLAY_REVIEW_EXPORT_CRF`
re-encodes; rewriting the source frame re-encodes; `PLAY_TAG_CLIP_CACHE = False` passes straight through; an
empty file list passes straight through; no `.part` files are left. All pass.


## 2026-11-18 -- CONFIRMED BUG: every "skip" a coach saved was being ignored (Thiel@UWPlatteville)

**What happened.** JT skipped the WHOLE 2026-11-06 Thiel@UWPlatteville game in the app at 11:11 (save
`play_review_tag_2026_11_06_Thiel_UWPlatteville_..._tag_skipgame_JT_20261118_171110.json`, `"skipped_game": true`).
The 11:39 `parser_models` then started building a 196-clip Film Tagging batch for it anyway
(`Thiel@UWPlatteville play videos made: 20 / 196`).

**Why.** The two halves of the skip feature were fine; the column carrying it was thrown away between them.

* `47_play_calls.py` `title_review_answers()` read the save into `_title_review_game_skips`, and
  `_pl_apply_app_tags()` set `skipped = True` on all 196 rows -- the log even says so:
  `Skipped in the app: 196 clip(s) ... (196 of them from 1 whole game(s) skipped)`.
* Then `_f.reindex(columns=PLAY_CALL_COLS)` (47:3755) built each side's frame for `play_calls`, and
  **`"skipped"` was not in `PLAY_CALL_COLS`** -- so the flag was dropped on the way into `play_calls`
  (that is also why `data/uww_play_calls.csv` had no `skipped` column).
* `55c_play_review.py` `tag_queue()` reads
  `skipped = g["skipped"]... if "skipped" in g.columns else pd.Series(False, index=g.index)`. With the column
  gone it took the all-False fallback, so `bool(skipped.all())` was False and the whole-game branch never fired,
  and `todo = g[untagged & ~skipped & ...]` kept every skipped clip.

So **no skip had any effect since the feature went in on 11/15** -- not the whole-game skip, and not the 14
single-clip skips (`Skipped in the app: 14 clip(s)` in the same run). They were saved, counted, printed, and
then re-offered on the next run. The symptom looked like wasted encoding time; the cause was a dropped column.

**Fix.** `"skipped"` added to `PLAY_CALL_COLS` (`47_play_calls.py`, 369,811 b), with the explanation above in
place. Nothing else changes: 47 already filled the column and 55c already read it.

**What the next run does.** The whole-game branch fires for Thiel@UWPlatteville: its batch is removed from the
app and it prints `a coach skipped the whole game in the app, so it has no batch (196 clip(s) left untagged on
purpose; PLAY_TAG_UNSKIP brings it back)`. The games holding the 14 single-clip skips lose those clips from
their batches, so those batches rebuild -- nothing saved is lost, and with the clip cache (same date, above)
the rebuild copies the videos instead of re-encoding them. `PLAY_TAG_UNSKIP` (clip keys) and a save with
`"unskipped_game": true` are still the ways back.

**Validation** (`~/wmtest/skip_t.py`, `PLAY_CALL_COLS` read out of the file by AST): the list has 70 columns, no
duplicates, `skipped` present; a flagged frame survives the reindex; `skipped.all()` is True and
`f"{gd}|{gc}".lower()` matches the saved `2026-11-06|thiel@uwplatteville`, so the whole-game branch fires; 0 of
3 clips are still offered; and a frame with one skipped clip keeps that one flag and offers the other two.


## 2026-11-18 -- CONFIRMED BUG: two of Elmhurst's games were routed as OURS in parser_brief

**What Corey saw.** "Whitewater should not have any offensive plays called 'Ripon Motion #2'" in the Play Call
Summary. He was right, and the leak was 356 clips wide.

**It is job-dependent** -- the same inputs, two different answers, from `Play clips by game type`:

| job | UWW | Opponent |
|---|---|---|
| `parser_models` 09:08 and 11:39 | 1,616 clip(s) / 13 game(s) | 711 / 4 |
| `parser_brief` 07:13 and 07:39 | 1,972 / **15** | 355 / **2** |

The 356-clip gap is exactly two games: **Elmhurst@Ripon (11/07, 178)** and **Elmhurst@Hope (11/14, 178)**. The
two that stayed right are DePauw@Elmhurst (195) + Carroll(WI)@Elmhurst (160) = 355. The brief builds the brief,
so the brief was the broken one. In `uww_play_call_summary.csv` that shows up as
`side=UWW, possession_side=Offense, level=Play call, name=Ripon Motion #2, uses=5, top_player=Jack Field,
game_codes=Elmhurst@Ripon` -- Ripon's set, Ripon's and Elmhurst's players, filed under our offense.

**Why those two and no others.** In `_pl_untagged_from_frames` (47), a captured page's side comes from `_urls`
(which schedule the clip page was found on). `parser_brief` runs frame capture with `RUN_FRAME_CAPTURE = False`,
so no page is registered, `hint` is None and `_sd0` is None, and the code fell to its last resort: the nearest
play-by-play within a day, then `hint = "UWW" if (e_["_src"] == "pbp_events").mean() >= 0.5`. Elmhurst played at
Ripon on 11/07, the day we played Carroll; Elmhurst played at Hope on 11/14, the day we played Ripon. Both
matched OUR play-by-play and were stamped UWW. Elmhurst's two home games fall on dates we did not play, so they
were unaffected. Same family as the MarianWI@MSOE bug already noted in that function.

**Fix (`47_play_calls.py`, 371,117 b).** The clip page's own Game cell decides, in two places:

* the no-schedule-date branch matches a page against ONE side's play-by-play when the Game cell names exactly
  one of the two teams (`_pg_uww != _pg_opp`) -- `pbp_events` for ours, `pbp_events_upcoming` for theirs, with no
  fallback: no match at all beats a match to the wrong game (it also stops the wrong game donating its half,
  clock and lineups);
* `hint = "UWW" if _pg_uww else "Opponent"` in that same case, before the `_src`-majority rule, so routing no
  longer depends on which play-by-play a job happens to have loaded.

A page naming BOTH teams (us against the upcoming opponent) is untouched and still sees both sides' events.

**The consumers were already right** and needed no change: 47 splits `play_call_summary` by `possession_side`
and stamps every row, and the brief's `_offense_rows(side)` drops `possession_side == "Defense"` (fixed earlier
on 11/18 for the headline bug). Routing was the last hole.

**Validation** (`~/wmtest/route_t.py`, both edited blocks lifted verbatim out of the file by string slice, then
exec'd): with our game and theirs on the SAME date, a page naming Elmhurst only routes `Opponent` and sees only
`pbp_events_upcoming`; a page naming Whitewater only routes `UWW` and sees only `pbp_events`; a page naming both
still sees both; with the opponent's play-by-play absent it routes `Opponent` and matches nothing rather than
matching ours; and a side already known from the schedule page still wins. All pass.

**Still open (small, 2 clips).** Ripon@UWWhitewater clips 88 and 95 are `Non Possession > Non Shooting Foul` by
Joey Daun and Michael Asman -- both Ripon players -- yet carry `offense_team = UW-Whitewater`, so they come out
`possession_side = Offense` and put "Ripon Motion #1" (2 uses) under our offense. The foul was drawn by their
player, so Ripon had the ball and these should be our Defense; `_pl_fill_blank_team` filled the Team cell with
ours instead. Not fixed -- `possession_side` also feeds Film Tagging's lineup options, so it needs Corey's go-ahead.


## 2026-11-18 -- Film Tagging no longer asks who is tagging

**CONFIRMED CHANGE (requested:** "I would like to remove the name requirement from saving within the
film_tagging. I don't need to know which coach made the saves.") `streamlit_app.py` (1,239,394 b):

* `FT_GUEST_COACH = "Guest"` beside `FT_SAVE_EVERY`. Every Film Tagging save is stamped with it.
* The "Your name (required to save)" box above the clips is gone (`_coach = FT_GUEST_COACH`), and so is the
  `st.error("Add your name at the top...")` gate -- Save now just saves.
* "Skip this whole game" lost its name box too; the "Yes -- skip this whole game" tick box is the whole
  confirmation, and `_ft_skip_game_save(d, FT_GUEST_COACH, on=True)`.
* Nothing else changed: the `coach` field is still written into the save file and into its name
  (`play_review_<slug>_<run>_titles_Guest_<utc>.json`), so `_pr_commit`, the save merge (latest save wins, by
  time -- never by who), `_ft_saved_clip_keys`, `_ft_skipped_clip_keys` and 47's `title_review_answers` all work
  unchanged. The accuracy report's "Games / reviewers" will simply read 1 reviewer from now on.
* The OTHER sections still ask for a name on purpose: Player Number Tracking checks (`pr_coach_players`),
  the starters check (`pr_coach_starters`), coverage plans (`cp_coach`), court calibration (`cc_coach`),
  play diagrams (`pd_coach`), KTV feedback.
* Saves already on the `saves` branch keep the names they were saved with (Corey, JT); this is not retroactive.

**Watch out.** 47's `_pl_title_save_ok` throws away any save whose coach name CONTAINS "test"
(`if "test" in str(d.get("coach")).lower()`), which is how CoreyTEST's saves are ignored. "Guest" does not
contain it -- but "Guest Tester", "Tester" or "Test User" would be silently dropped, so do not change
`FT_GUEST_COACH` to anything with "test" in it without first making that rule a whole-word match.

**Validation** (`~/wmtest/`-style check run inline): `FT_GUEST_COACH` read back out of the file is "Guest";
`"test" not in "guest"`; the Film Tagging name widgets and the name-gate message are absent from the file; the
five other sections' name keys are still present; the module parses and byte-compiles.


## 2026-11-18 -- clutch on every roster card, and the metric definitions in the footer

**CONFIRMED CHANGE (requested:** "I want the roster sections to have a subsection under Offense that says how
well they do during 'Clutch' moments based on our definition" ... "Also add information for each player that was
on the court on defense during clutch moments" ... "add a part in 'How this brief was built' that shows our
metric definitions.") `87_build_html_scouting_brief_for_upcoming.py` (510,328 b).

**Our definition, not a new one.** 47's `_gs_situation` already stamps every clip with `game_situation`, and
clutch is `_GS_CLUTCH_SECONDS = 300` / `_GS_CLUTCH_MARGIN = 8`: not the first half, 5:00 or less, margin 8 or
fewer. It runs over `pbp_events` AND `pbp_events_upcoming`, so a scouted opponent's clutch comes from THEIR
games. Nothing new was computed in the brief.

* `_clutch_tbl(side, poss="Offense")` -- clutch clips of one side, one possession side. `side` alone is never
  enough (it names the file a clip came from), hence the `possession_side` filter.
* `_clutch_of(name, side)` -> under **Offense**, "In the clutch (last 5 min, margin &le; 8)": the possessions
  where he was the man in the possession. The count leads; the rate appears only at 3+ (a game has a handful of
  clutch trips); the team's rate rides along once the pool is 8+. **Fouls drawn are named** because a trip that
  ends at the line scores nothing on the clip itself -- Cargill's 3 clutch trips are 0.00 a trip and 3 fouls
  drawn, which without the second line would read as three wasted possessions.
* `_clutch_def_of(name, side)` -> under **Defense**, same heading: defense has no man in the possession, so it
  goes by `defense_lineup` -- "On the floor for 17 of the team's 19 clutch defensive possessions -- 18 points
  allowed, 1.06 a trip (the team 1.11)", then "8 of 13 shooting against, 2 turnovers forced, 2 fouls given up".
  The team's number is left off when he was on the floor for all of them (`_team_n > n`).
* Both are omitted entirely for a player with no clutch possessions, and both carry on `_roster_player`'s dict
  (`clutch`, `clutch_def`), so the starters strip can use them later if asked.

**What the numbers mean** -- a 15-item list in "How this brief was built": Possession (and why 0.475, not
Oliver's 0.44), PPP, Clutch, clutch on offense, clutch on defense, Leading / Trailing by 10+, eFG%, TOV%, ORB%,
FT Rate (ours is FTA/FGA, Oliver's is FTM/FGA -- said so), the Four Factors ranking, PPG difference, Min/G,
the shot-clock buckets, and what "on film / tagged" means. The weights are interpolated from `_SB_FF_WEIGHTS`
at build time, so that line cannot drift from the table it describes, and it says plainly that TEAM COMPARISON
prices each factor for THIS matchup instead -- which is why the two sections can disagree.

**Validation** (`~/wmtest/clutch_t.py`, `clutchdef_t.py`, `defs_t.py` -- each pulls the functions and the
`_defs` list out of the file by AST and runs them against `data/uww_play_calls.csv`):
`_clutch_tbl` returns 20 offensive and 19 defensive clutch possessions for UWW, 16 and 6 for Elmhurst, all
`Clutch`, all the right possession side; an unknown name and an empty frame both return nothing; 2 possessions
show a count and no rate, 5 show count + rate + team rate; a defender on the floor for every one of them gets no
redundant team figure; across both sides every player's on-floor count is <= the team's total; and every
definition is asserted against the constant it describes (0.475, the eFG and FT Rate formulas, the four weights,
300 / 8 / 10, and 47's shot-clock bins).


## 2026-11-18 -- five cards above both offense sections (Motion / Plays / Actions / BLOB-SLOB / Tempo)

**CONFIRMED CHANGE (requested:** "format the 'HOW ELMHURST RUNS OFFENSE' and 'HOW WE RUN OFFENSE' sections the
same way with 5 of the most important pieces of information as cards above an expandable section ... Motion,
Plays, Actions, BLOB/SLOB and Tempo.") `87_build_html_scouting_brief_for_upcoming.py` (518,290 b).

`_off_cards(side)` is new, and the four `_sb_sechead(_sb_pc_top(...))` calls in `offense_section_test2`
(opponent) and `offense_section_test_uww` (ours) -- the main path and the `_extra_only` path of each -- now call
it instead. Riding in the `_sb_sechead` slot is what makes the layout work: `_sb_collapse` keeps that chunk
beside the header and puts everything after it behind one "Show the detail" expander, the same shape as TEAM
COMPARISON and the lineup sections. Same `lc` / `lcards wm-cards` markup as those, so no new CSS.

The five, all from `_offense_rows(side)` -- **the same rows the section's own tables use**, so a card can never
contradict the table under it (the 11/18 headline bug was exactly that):

| card | built from | reads |
|---|---|---|
| Motion | `Series` rows matching motion / flow / 5-out / four-out / open post, as one number | `Motion · 30 possessions, 0.97 a trip · our average 0.88 · "How we play without a call. 4 variations of it on film."` |
| Plays | `Play call` rows that are NOT motion and NOT an inbounds | `Zona · 6 possessions, 1.00 a trip · 21 named set(s) on film · "Best of them: Cheetah at 1.80."` |
| Actions | `Primary action` | `Ball Screen · 21 possessions, 0.76 a trip · "Then Down Screen (6), Offensive Rebound (6)."` |
| BLOB / SLOB | `Situation` rows that are exactly BLOB or SLOB | `BLOB 8 · SLOB 11 / BLOB 1.43 · SLOB 1.10 · "BLOB is the better of the two."` |
| Tempo | `Shot clock` buckets + the `Transition` situation | `Organized offense · 64 possessions spent there · 38 in transition · "Best clock: late clock at 1.00."` |

Rules it follows:

* rates are weighted by uses (`_rate`), and compared only to the side's OWN average (`team_ppp`) -- never a
  league number;
* no card quotes a tagged-possession denominator (requested earlier: nothing reads "... on 85 tagged");
* thin samples say so instead of hiding: "None run more than 2 time(s) yet", and BLOB/SLOB at 0.00 for both
  reads "No points off either on film yet" rather than "Both score about the same";
* a card with no data is dropped, and with fewer than two cards the section falls back to the old one-line
  `_sb_pc_top` headline, so a barely-tagged opponent still gets a headline rather than an empty card row.

**Validation** (`~/wmtest/offcards_t.py`, `_off_cards` pulled out by AST and run against
`data/uww_play_call_summary.csv` with a stub `_offense_rows`): both sides produce five parsed cards; no card
contains "unspecified", "nan" or the words "tagged possession"; an empty frame returns "" and a
single-level frame returns the headline fallback.

**Note on the numbers above:** they come from the summary CSV the 07:39 brief wrote, which still had the
Elmhurst@Ripon routing bug, so Elmhurst's figures will move (mostly grow) on the next `parser_brief`.


## 2026-11-18 -- the five offense cards say something, and the clutch cards say whose number it is

Two follow-ups to the same afternoon's work. `87_build_html_scouting_brief_for_upcoming.py` (523,404 b).

### 1. CONFIRMED CHANGE (requested): "make each of those 5 cards be actually informative for coaches and not
just how many possessions and PPP"

`_off_cards` was rewritten. Every card now answers who it runs through, what it turns into, what shape they are
in, what shots come out of it and what it costs -- all of it columns the summary already carries
(`top_player` / `top_player_uses`, `top_action`, `personnel_grouping_mode`, `fga` / `fg3a` / `fg_pct`,
`turnovers`, `fouls_drawn`), nothing recomputed here. Helpers: `_who` (surname + how many, the way it is said
out loud), `_into`, `_shape`, `_shots`, `_cost`, `_vs` (against that side's own average).

What it reads like now:

* **Motion** -- `Motion / 30 possessions - 0.97 a trip / Madson in 7 - into Ball Screen - 3G-2W / 7 of 14 shots
  from three, 43% overall - 5 turnovers, 5 fouls drawn - above our average (0.88).`
* **Plays** -- the most-used called set (motion and inbounds excluded), who runs it, how many named sets there
  are, and **which one actually scores**: `Cheetah scores best (1.80 on 5)`.
* **Actions** -- the top action plus **how it has gone against each coverage**, from `Ball screen coverage
  faced`: `Against over | high hedge 0.33 on 6, switch 0.00 on 1 - then down screen (6), offensive rebound (6)`.
  The coverage line only prints when the action is a ball screen / DHO.
* **BLOB / SLOB** -- `BLOB 8 - SLOB 11 / BLOB 1.43 - SLOB 1.10 / BLOB to Mcewen - 3, into Down Screen ... /
  BLOB is the one that hurts (1.43 against 1.10).`
* **Tempo** -- the whole clock distribution (`Early 56 - Organized 64 - Late 46`), where they are best, how much
  is transition and at what rate, and the worst bucket.

Rules kept from the first pass: no tagged-possession denominators, rates only against the side's own
`team_ppp`, empty cards dropped, fewer than two cards -> the old `_sb_pc_top` headline.

### 2. CONFIRMED CHANGE (requested): "Defensive clutch information needs to be clear what are things the player
did and things the team did"

The defensive card read like a personal stat line ("On the floor for 19 ... 21 points allowed ... 9 of 14
shooting against"), and none of it except the first clause is his. There is no individual defensive box score
in this data, so the card now labels the two parts outright:

* `HIM: on the floor for 19 of the team's 19 clutch defensive possessions -- every one of them.`
* `THE FIVE HE WAS IN (team numbers, not his): 21 points allowed on 19 possessions, 1.11 a trip: 9 of 14
  shooting against, 2 turnovers forced, 3 fouls given up.` (plus `-- the team allowed 1.11 across all 19` when
  he was not on for all of them)

The offensive card had the same ambiguity and got the same treatment: `HIM: the ball on 4 clutch possessions on
film -- they produced 5 points, 1.25 a trip` and `ON THOSE TRIPS: 1 of 3 from the floor, 1 foul drawn.` The
points are the POSSESSION'S points, not his own scoring -- a kick-out someone else finishes counts -- and the
footer definitions for both now say so in those words.

**Validation**: `~/wmtest/offcards_t.py` (five parsed cards a side, no "unspecified" / "nan" / "tagged
possession", empty frame -> "", single level -> headline fallback), `clutch_t.py` and `clutchdef_t.py` updated
to the new wording (HIM / THE FIVE HE WAS IN / ON THOSE TRIPS, "every one of them" only when he was on for all
of them, the team's rate only when he was not, every on-floor count <= the team's total). All pass.

**Note:** the 12:02 `parser_tagging` run rewrote `data/uww_play_calls.csv` with the `skipped` fix in place, so
Elmhurst's clutch defensive sample moved from 6 possessions to 4 between runs. The numbers above are from the
current file.


## 2026-11-18 -- clutch flags on the roster cards

**CONFIRMED CHANGE (requested:** "Put a flag on the players that are the best clutch offensive and defensive
players.") `87_build_html_scouting_brief_for_upcoming.py` (527,538 b). `_clutch_best(side)` (cached per side)
picks at most one of each, `_clutch_flags(name, side)` turns that into chips, and both roster layouts render
them: `pc-chip clutch` in the table layout's chip row, `ph-foul ph-clutch` in the stacked header beside the
late-foul call. Gold chips, with the detail in the tooltip.

* **Best with the ball** -- highest points a trip among players with 3+ clutch possessions of their own, and
  only when at least two players clear that bar.
* **Best five on defense** -- fewest points allowed a trip with him on the floor, among players on for at least
  3 AND 40% of the team's clutch defensive possessions. It is a FIVE-MAN number and the tooltip says so
  ("a five-man number, not his alone"), the same attribution rule as the cards.
* Neither flag is given when the pool is too thin or when every qualifier has the same rate -- which is why
  Elmhurst currently gets an offensive flag (Trelenberg, 1.25 on 4) and no defensive one: their four clutch
  defensive possessions were defended by the same five, so "best" would have been meaningless.
* A 16th definition in "What the numbers mean" spells both rules out.

**Known sharp edge:** the offensive flag is a rate with a 3-possession minimum, so it can favour a small
sample -- today Madson (1.67 on 3) over Lukenbill (1.17 on 6). Raise the minimum in `_clutch_best` if that
reads wrong once more film is tagged.

**Validation** (`~/wmtest/clutchflag_t.py`, functions lifted by AST, run against `data/uww_play_calls.csv`):
the offensive pick really is the max rate among those with 3+; the defensive pick clears the 3-and-40% floor;
at most one of each flag exists per side; an unknown name and an empty frame flag nobody.


## 2026-11-18 -- rate first, sample in brackets: "0.97 PPP (30 Poss)"

**CONFIRMED CHANGE (requested:** "Instead of '30 possessions - 0.97 a trip' it should be '0.97 PPP (30 Poss)'.")
`_poss(n, p)` in `_off_cards` now returns `f"{p:.2f} PPP ({int(n)} Poss)"` (and `"{n} Poss"` with no rate), and
every other rate inside those cards follows the same words: BLOB / SLOB values, the best clock bucket,
transition, "scores best (1.80 PPP on 5)" and the coverage line ("Against Jam 1.50 PPP on 2"). The clutch
cards and the clutch flag tooltips say PPP too, so one vocabulary runs through the brief.

**CONFIRMED BUG (fixed in the same pass).** The card notes were built with `str.capitalize()`, which uppercases
the first letter and LOWERCASES everything after it -- so the new wording came out as "1.80 ppp on 5",
"Against jam ... then dho (2), down screen (2)". Replaced with `_cap1` (first character only). Acronyms and set
names now survive: "Against Jam 1.50 PPP on 2, Drop 0.00 PPP on 1 - then DHO (2), Down Screen (2)."

**Validation**: `~/wmtest/offcards_t.py` re-run (five cards a side, both now reading "x.xx PPP (N Poss)"),
`clutch_t.py`, `clutchdef_t.py` and `clutchflag_t.py` all still pass.


## 2026-11-18 -- CONFIRMED BUG: the Plays and Actions cards disagreed with the bullets under them

**What Corey saw.** The PLAYS card said "Cheetah scores best (1.80 on 5)" while the bullet two inches below
said "Our most successful play calls: BLOB (2x, 2.50 PPP) · Cheetah (5x, 1.80 PPP) · Zoom (3x, 1.67 PPP)",
and the ACTIONS card led with Ball Screen (the most-used) while the bullet named "DHO / handoff (5x, 2.00 PPP)"
as the most successful. Two different tables, two different answers, stacked on each other.

**Why.** The cards ranked `uww_play_call_summary` rows; the bullets come from `uww_offense_summary`, which 47
builds from the clips with its OWN grouping -- `ACTION_GROUPS` folds "DHO / handoff" into one label,
`OB_SUMMARY_MIN_POSS` gates the sample, and BLOB counts as a play call there while the card excluded inbounds.
Neither was wrong; they answered different questions from different pools.

**Fix (requested: "We should probably list out what is used most often and what has been most successful").**
Both cards now carry both halves, labelled, and the most-successful half is **lifted from the bullet's own
text** -- `_best_from_bullets(kind)` parses `uww_offense_summary`'s `success` / `success_actions` row for this
side and opponent with `([^·:]+?)\s*\((\d+)x,\s*([\d.]+)\s*PPP\)`, so the card quotes the bullet's own
names and numbers. `_best_line` falls back to the summary table's best when that row doesn't exist yet.

* **Plays** -- `Zona / 1.00 PPP (6 Poss) / Most used · Madson in 3 · into Ball Screen · 21 named sets /
  Most successful: BLOB 2.50 PPP (2 Poss), Cheetah 1.80 PPP (5 Poss), Zoom 1.67 PPP (3 Poss).`
* **Actions** -- `Ball Screen / 0.76 PPP (21 Poss) / Most used · Madson runs it 9 · 3G-2W / Most successful:
  DHO / handoff 2.00 PPP (5 Poss) · Against Over | High Hedge 0.33 PPP on 6, Switch 0.00 PPP on 1 · then
  Down Screen (6 Poss), Offensive Rebound (6 Poss).`

**Worth knowing:** "most used" on the Plays card still excludes motion and inbounds (they have cards of their
own), while the bullet's "most successful" list does not -- which is why Elmhurst's card reads "DHO set, most
used" and then names Motion and Flow as their most successful. It is faithful to the bullet; say the word if
the two pools should be aligned instead.

**Validation** (`~/wmtest/offcards_t.py`, extended): a new `must_match_bullets` check re-parses
`uww_offense_summary` and asserts every name/count/PPP the card quotes as "Most successful" appears verbatim in
the bullet it came from, for both sides. Passes, alongside the existing five-card / no-"unspecified" /
empty-frame / headline-fallback checks.


## 2026-11-18 -- clutch flags on the starters strip, and American spelling

**CONFIRMED CHANGE (requested:** "Add the clutch flags also to the starters list. Make sure it is spelled
'defense' not 'defence'.") `87_build_html_scouting_brief_for_upcoming.py` (530,620 b).

* `_starter_strip` now renders the same chips, from the same `_clutch_flags(name, side)` -- one source, so the
  strip and the roster card can never disagree -- in a `sf-clutch` row above the late-foul flag, with CSS that
  lets them wrap on a narrow card (`white-space: normal`, 0.62rem). **Both sides get them**, unlike the foul
  flags, which are opponent-only: who to have on the floor late is a question about our five too.
* Every "defence" / "offence" in the brief is now "defense" / "offense" -- the clutch flag text, the two footer
  definitions, and the older prose in the possession-model and Team Comparison notes that already had the
  British spelling. Zero left in that file.
* Deliberately NOT changed: `47_play_calls.py` line 999 maps `"bad offence": "BO"` -- that is an INPUT
  spelling the decoder accepts from a coach's tag, not display text, and dropping it would stop reading tags
  that are already saved. `41b_offensive_roles.py` line 268 is a code comment.
* `_starter_strip` and `_clutch_flags` are both nested in `_sb_build_html` (lines 3630 and 3171), so the call
  resolves -- checked with an AST parent walk, since py_compile cannot catch a missing closure name.

**Validation**: `clutchflag_t.py`, `clutchdef_t.py`, `clutch_t.py`, `offcards_t.py` and `defs_t.py` all pass
(the first two updated for the new wording: "five on defense", and "PPP" where they still asserted "a trip").


## 2026-11-18 -- "(low sample)" and "(box score only)" dropped from the role lines

**CONFIRMED CHANGE (requested:** "For the scouting briefs, I don't think you need to mention '(low sample)' or
'(box score only)'.") `87_build_html_scouting_brief_for_upcoming.py` (530,802 b). `_q(bb)` in `_roster_player`
returned one of three parenthetical qualifiers after every Off / Def role; it now returns `" (position only)"`
and nothing else. That one stays because it says the label has NO data behind it, which is a different claim
from "a bit thin". The ROSTER footnote that explained the three was rewritten to match.

It fed every surface at once -- the role line on the roster card, the stacked card header and the `Off` / `Def`
lines on the starters strip (all read `role_off` / `role_def`), so dropping it at the source clears all three.
How thin the evidence is still lives where it belongs: the methodology footnote and "How this brief was built".


## 2026-11-18 -- "30 Snap" is "Snap 30", and the same rule for every re-ordered call

**CONFIRMED CHANGE (requested:** '"Snap 30" and "30 Snap" should always be made "Snap 30". Anything similar
should follow the same rules.') `47_play_calls.py` (373,016 b), in `_pl_merge_spellings`.

* The grouping key kept WORD ORDER (`"[^a-z0-9#]+" -> ""`), so the two were different calls. The key is now the
  call's words **sorted**, so any re-ordering of the same words is one call.
* `_canon_pick(vc)` chooses the spelling to keep. Most-used, exactly as before -- **except** where the only
  difference is a bare number that moved from the front to the back, and then the name leads and the number
  follows however the coaches typed it most often. The test is deliberately narrow: strip the bare numbers
  (`#?\d+`) and what is left must be identical AND in the same order in every spelling. So "Snap 30" wins over
  "30 Snap" even at 1-vs-3, while "5 Out Motion" vs "Motion 5 Out" (where "Out" moves too) is still settled by
  usage, and a formation number that leads a call and never moves is left alone.

**CONFIRMED BUG (fixed in the same pass).** `play_series` and `play_set` are written at decode time (~444 /
~938), BEFORE this function runs at 4462, so they kept the raw spelling -- which is why the brief's Series
tables listed "Flow" and "flow", "Stagger" and "stagger", "Ripon Motion" and "ripon motion" as separate rows
next to each other. Both columns are now in the default `cols`, which normalises 51 clips on the current file
on top of the one play-call change.

**Worth knowing:** the most-used rule decides capitalisation, so "RIPON MOTION" (5 uses) beats "Ripon Motion"
(3). Ugly but consistent, and it is the pre-existing rule -- say so if title case should win ties or outrank
usage.

**Validation** (`~/wmtest/spell_t.py`, `_pl_merge_spellings` lifted by AST): "Snap 30" / "30 Snap" collapse to
"Snap 30", and still do when "30 Snap" is three times as common; "Zoom #2" / "#2 Zoom" and "41 Flare" /
"Flare 41" follow the same rule; "5 Out Motion" keeps its name against "Motion 5 Out"; bracket notes, "option",
punctuation and case grouping all behave as before; "Snap", "Snap 30" and "30 Gold" stay three different calls;
and on the real file the only play-call change is "30 Snap" -> "Snap 30", with "Snap 10" untouched.


## 2026-11-18 -- the brief never read the trigger / screener split

**CONFIRMED BUG (requested:** "The scouting brief, and maybe the data in the application, are not splitting
actions into trigger and screen actions.") `87_build_html_scouting_brief_for_upcoming.py` (533,992 b).

**The split is in the data and always was.** Film Tagging's Actions table writes the two halves of every action
to their own columns on the clip: `trigger_actions` ("Ball Screen (#3): Use Ball Screen", 87 clips today) and
`screener_actions` ("Ball Screen (#35): Roll", 84 clips). Nothing in the brief read either one -- the Actions
card, the offense-breakdown table and the "most successful actions" bullet all counted the action TYPE (Ball
Screen, DHO) and stopped. `uww_action_reads` does carry the split per player, and both the brief's reads card
and the app's READS OFF ACTIONS render it, but it is gated at 2+ uses and 47 of its 58 rows sit at 1 use, so
almost none of it reached the page.

**Fix.** `_role_reads(side)` in `_off_cards` parses the two clip columns directly
(`^\s*(.*?)\s*(?:\(#(\d{1,2})\))?\s*:\s*(.+?)\s*$`, the same shape 47's `_pl_reads` uses for its fallback)
and the Actions card carries the result on a line of its own (`lc-split`, a dotted rule above it). `_card` took
a sixth argument rather than smuggling markup through `sub`, which `_sb_esc` would have escaped. Today it reads:

* ours -- `Ball handler: Use Ball Screen 35 (0.89 PPP) \u00b7 Reject Ball Screen 4 \u00b7 Cobra 2 \u2014 Screener:
  Roll 32 (0.88 PPP) \u00b7 Pop 16 \u00b7 Fox 2`
* theirs -- `Ball handler: Use Ball Screen 3 (0.00 PPP) \u00b7 Reject 1 \u00b7 USe DHO 1 \u2014 Screener: Roll 5
  (0.80 PPP) \u00b7 Pop 3 \u00b7 Ghost 1`

PPP rides on the top read only, and only at 3+. A bare "Trigger" read (the box ticked with nothing behind it)
is skipped. No minimum uses: reading the clip columns means the split shows from the first tagged possession
instead of waiting for a player to repeat a read twice.

**Also seen, not a new bug:** `data/uww_action_reads.csv` currently files #34 Jackson Flowers and #35 Michael
Asman under `side = UWW`. Neither is on our roster -- it is the Elmhurst@Ripon routing bug from this morning,
baked into a file written before the fix. It clears on the next full run.

**Validation**: `~/wmtest/offcards_t.py` extended with a real `_pcc_all`; the split line parses out of the card
as its own `lc-s lc-split` div for both sides, and the existing checks (five cards, bullet-matching,
no "unspecified" / "nan", empty-frame and headline fallbacks) still pass.


## 2026-11-18 (late afternoon) -- reads without a floor, their own section, a trailing action, KTV cards

Four requested changes, plus one correction to the entry above.

### 1. The reads' 2+ uses floor is a setting, default 1
`87` (540,012 b). `_READS_MIN = int(globals().get("BRIEF_READS_MIN_USES", 1))` replaces the hard-coded `>= 2`
in `_reads_of` (the roster card's Tendencies lines) and in `_reads_card`. 47 of `uww_action_reads`' 58 rows sit
at 1 use, so the old floor hid most of the trigger / screener split. **The app was never gating** --
`render_action_reads` has always shown every row -- so nothing changed there.

### 2. TRIGGER & SCREENER READS, its own section, player by player
`_trigger_screen_section()` runs after HOW WE RUN OFFENSE: one card per team, two role groups inside
("Trigger -- the man with the ball", "Screener"), each row player / action / what he did / uses (share) / PPP.
Offense only -- the defenders' reactions stay in the app, which shows them with no minimum. Players with no
jersey (`(no number)`) are left out. With `BRIEF_READS_MIN_USES = 5` the section disappears rather than
printing an empty shell.

### 3. CONFIRMED CHANGE: "Twins Right Twirl" = "Twins Right" + Twirl
`47` (375,633 b), in `_pl_merge_spellings` ahead of the renames. A call ending in a word from
`PLAY_CALL_TRAILING_ACTIONS` (default `["Twirl", "Swirl"]`) loses that word from `play_call`,
`play_call_detail`, `play_set`, `play_series` and `play_call_base`, and gains it in `play_actions` --
`primary_action` too, but only when the clip has none, so an action a coach actually tagged is never
overwritten. Only listed words move: "Motion" and "Zoom" are known actions AND calls in their own right, so a
blanket "last word is an action" rule would take apart "5 Out Motion" and "Zoom". On the current file it
changes three clips: Twins Right Twirl, Twins Left Swirl, and **"Over Twirl" -> "Over"** -- "Over" is a
ball-screen coverage, so that one may be a coverage typed into the play-call field. Flagged, not fixed.

### 4. CONFIRMED CHANGE: KEYS TO VICTORY as cards
The keys were numbered sentences; they are now the brief's own cards (`lcards ktv-cards`), three to a row,
each with "Key N" plus the priority score and source badge on the top strip, the instruction in bold, and the
reasoning under a rule. `BRIEF_KTV_CARDS = False` restores the sentence list. Which keys appear, their order,
their links and their scoring are untouched -- layout only. A staff key with no reasoning renders as a
headline-only card, which is correct.

### 5. CORRECTION to the "trigger / screener split" entry above
That entry says `uww_action_reads.csv` files Jackson Flowers and Michael Asman under `side = UWW` and calls it
routing contamination. **It is not.** `side` names the FILE a clip came from, so a Ripon possession inside our
own 11/14 game is legitimately `side = UWW`; `team` and `offense_team` both read "Ripon Red Hawks", and every
consumer (the new section included) filters on `offense_team`. Nothing to fix. The lesson is the one this file
keeps relearning: `side` is the file, not the team.

**Validation**: `~/wmtest/trail_t.py` (the Twins pair splits both ways, an existing `primary_action` survives,
5 Out Motion / Zoom / Snap 30 untouched, three real-file changes), `tsread_t.py` (the section emits once with
both role groups, single-use reads appear, no `(no number)` rows, a 5-use floor suppresses the section), and a
replay of the KTV card loop against `uww_ktv_keys.csv` (6 cards, every one with a title strip and a headline).

**Runs**: the 14:58 and 15:18 `parser_brief` runs both routed correctly (UWW 1,616 / 13 games, Opponent 711 /
4) and wrote the brief clean -- the 07:39 run was the only broken one. The brief on disk already carries the
clutch sections, the flags, the PPP format and the split line; the new section and the KTV cards land on the
next run.


## 2026-11-18 -- every key behind an expander under the KTV cards

**CONFIRMED CHANGE (requested:** "Make a table of keys to victory that can be expanded with all of them
available.") `87` (542,819 b). Under the six cards sits one `<details class="rosdet">` -- "All 19 keys / every
key the parser built for this game, best first" -- holding the whole `ktv` frame, not just the brief's
selection: Area (category), the key in bold with its reasoning (or its evidence line when it has no reasoning,
which is what the app shows when you click a key), the 0-100 priority score, and the source badge. Sorted by
score, and the six already on a card are marked "\u2605 on a card above" and tinted, so it is obvious what is
new below the fold. Being an ordinary `<details>`, "Expand all" opens it and the print handler unfolds it.

It only renders when there is more to show (`len(_ktv_all) > len(ktv_brief)`) -- with six keys and six cards
there would be nothing behind the expander.

**Two Python 3.10 traps hit on the way in**, both caught by `ast.parse` before anything was written, worth
remembering for the next patch to this file: a stray `")` closing an f-string that opened with `'`, and
`f'...{x or "\u2014"}...'` -- a backslash escape inside an f-string EXPRESSION is a SyntaxError before 3.12
(the same trap the `_foul` block already carries a comment about). Build the value into a variable first.

**Validation** (`~/wmtest/ktvtbl_t.py`, the block lifted verbatim out of the file and run against
`uww_ktv_keys.csv`): 19 rows for 19 keys, exactly one `<details>`, scores strictly descending, exactly six rows
flagged as on a card, and no "nan" anywhere in the markup.


## 2026-11-18 -- the KTV cards are one row

**CONFIRMED CHANGE (requested:** "I only want one row of cards.") `87` (543,539 b). The six keys wrapped onto a
second row at three a row; now `BRIEF_KTV_CARDS_MAX` (default **5**) caps the cards at one row and the CSS no
longer wraps on a wide screen -- `.lcards.ktv-cards .lc { flex: 1 1 0; min-width: 0 }`, the same shape as the
offense sections' five-card row. The base `.lcards` media query still wraps them on a narrow screen.

Two knock-ons handled rather than left to rot:

* the "\u2605 on a card above" marks in the All-keys table are now driven by `ktv_brief.head(_ktv_row)`, not by
  `ktv_brief` -- otherwise the 6th key, selected but no longer carded, would be flagged as already seen when it
  is the first genuinely new row in the table;
* the expander's "is there anything more to show" test compares against the number CARDED, not the number
  selected, so the table still appears when the brief selects exactly as many keys as the row holds.

Nothing is lost by the cap: every key, the carded five included, is in the expander directly below.

**Validation**: `~/wmtest/ktvtbl_t.py` updated -- 19 rows for 19 keys, exactly five flagged as on the row, the
6th key ("Counter with Madson, Chestnut, Lukenbill, McEwen, Rogers") correctly unflagged, scores descending.


**CONFIRMED BUG (fixed 11/18, same file, 543,860 b).** On the starters strip the role labels ran into the role:
"OFFStationary Shooter", "DEFHelper". The markup has no space between `<span class="sf-k">Off</span>` and the
role text by design -- the gap was supposed to come from the label's `min-width: 1.9em`, which is narrower than
"OFF" renders at 0.6rem. Now `min-width: 2.2em` plus `margin-right: 5px`, so the gap holds whatever the font
does. CSS only; no markup change.


## 2026-11-19 -- the Ripon brief stop, the Hope brief, and a check that didn't know about cards

**Corey:** "I tried to use an old reference date to get a scouting report for the Ripon game and it errored out."

### What happened, from the logs

* **20:59 run, `Reference date: 2026-11-13`** (so the next game is Ripon, 11/14). It did not crash -- it hit the
  frames-vs-plays guard in 47 and stopped on purpose:
  `STOPPED: the captured frames and uww_plays.csv don't line up yet` naming
  `2026-11-14 Elmhurst Bluejays vs Hope Flying Dutchmen: 178 clip(s) captured, none in uww_plays.csv` and
  `2026-11-14 Ripon Red Hawks: 175 clip(s)`. With the clock rolled back to 11/13 both 11/14 games are in the
  FUTURE, so they belong to no side of this run (`Play clips by game type: UWW 1441 / 12 games, Opponent 353 /
  2, Other 2610 / 14` against the usual 1616 / 13, 711 / 4, 2430 / 13) -- their captured frames look orphaned
  and the guard fires. `inputs/_upcoming_game.json` still says `"REFERENCE_DATE": "2026-11-15"`, so this is the
  same failure the 11/14 note in `00_parser_modes.py` describes: **the brief ran on an older date than the one
  parser_models prepared the film for.**
  Ways round it: run `parser_models` with the old date first (what the warning says), or for a one-off
  historical brief set `FRAMES_STOP_FOR_GAPS = False`, or name the two games in `FRAMES_STOP_IGNORE_GAMES`.
  **Fixed the same morning (requested): the guard now skips captured games dated after `REFERENCE_DATE`** --
  see the entry below -- so an old-date brief runs without any of those workarounds.
* **21:05 run, `Reference date: 2026-11-19`**: this one worked. It picked **Hope Flying Dutchmen** -- not a
  mistake, UWW play them **Tue, Nov 24** -- and wrote a 4.9 MB brief. No FastScout report exists for Hope yet
  (`No scout report on file for the next scheduled opponent`), so the scouting-report-sourced output is thin.

### CONFIRMED BUG (fixed): the brief check didn't know the keys had become cards
That run ended `!! [keys] no Keys to Victory are printed` on a brief that printed five. `87b_brief_check.py`
scrapes the printed keys out of `<div class="ktv-sentence">`, which the 11/18 card change replaced with
`lcards ktv-cards` / `lc-n`. So the check reported a false problem AND silently stopped doing its real job --
verifying every printed key exists in `uww_ktv_keys.csv`. It now reads the card markup when no sentences are
found (`87b_brief_check.py`, 12,812 b). The lesson for the next layout change in 87: **87b scrapes the brief's
own HTML, so changing markup there can blind a check without failing anything.**

**Validation** (`~/wmtest/briefchk_t.py`, the block lifted out of 87b and run against the real Hope brief):
five keys read from the cards, zero problems raised, the old sentence markup still read, and a brief with
neither shape still flagged "no Keys to Victory are printed".


## 2026-11-19 -- the frames guard respects the reference date

**CONFIRMED CHANGE (requested:** "make the guard skip captured games dated after the reference date.")
`47_play_calls.py` (377,337 b). In the frames-vs-plays check, a captured game whose own date is AFTER
`REFERENCE_DATE` can't belong to that run, so it is noted and skipped instead of stopping the run:

    (frame check: 2026-11-14 Ripon Red Hawks: played after this run's reference date (2026-11-13)
     -- not part of this run, so its 175 captured clip(s) are not a gap)

`_fr_game_date(lab, rows)` takes the date from the label, which always starts with one
("2026-11-14 Ripon Red Hawks"), and falls back to the rows' `clip_date`. Only the FIRST loop (captured games
with no play-call rows) is affected; tagged plays missing frames are checked as before, and a game ON the
reference date is still checked -- the guard is unchanged for any run whose date is today's.

**Validation** (`~/wmtest/frguard_t.py`, the helper lifted by AST, run against the real
`parser/inputs/uww_clip_frames.csv`): all 22 captured games yield a date; the no-date-in-label path falls back
to `clip_date`; at `REFERENCE_DATE = 2026-11-13` exactly the two games that stopped the 20:59 run are skipped
(2026-11-14 Ripon, 2026-11-14 Elmhurst vs Hope) and nothing else; at 2026-11-19 nothing is skipped at all.


## 2026-11-19 -- a date mismatch now runs parser_models, or stops the notebook

**CONFIRMED CHANGE (requested:** "have it stop the notebook and explain that I should run parser_models with
that reference date ... or better yet, have it automatically call out and run parser_models with that
reference date.") `00_parser_modes.py` (57,014 b), in the `brief` / `tagging` branch that reads
`inputs/_upcoming_game.json`.

A warning line was never enough: on 11/18 the brief ran on 2026-11-13 while the film and tagging had been
prepared for 2026-11-15, printed one `!!`, and stopped forty minutes later inside 47 with a message about
captured frames. The mismatch is known HERE, before a single section runs, so it is settled here:

* **`BRIEF_AUTORUN_MODELS = True` (the default)** -- a banner explains the mismatch, says the models job is
  long (~50 min) and pushes data when it finishes, then
  `run_parser("models", notebook=notebook, options={**own, "REFERENCE_DATE": <the notebook's date>})` runs and
  the job carries on: `=== back in BRIEF: parser_models has prepared 2026-11-13; carrying on ===`.
  The job's own `_PM_OPTIONS` are saved and restored around the nested run (in a `finally`), so the brief sees
  its own options afterwards.
* **`BRIEF_AUTORUN_MODELS = False`** -- raises before anything runs, with the reason and the exact line to run:
  `run_parser("models", options={"REFERENCE_DATE": "2026-11-13"})`, plus the two other ways out (turn the
  setting on, or clear the notebook's own REFERENCE_DATE to use the prepared one).

Nothing happens when the dates match, or when no `_upcoming_game.json` exists (nothing to compare).

**Worth knowing:** a brief run can now become a models run, which pushes `data/**` on the way out. The banner
says so before it starts; `BRIEF_AUTORUN_MODELS = False` is the switch for anyone who would rather be told.

**Validation** (`~/wmtest/autorun_t.py`, the block lifted out of the file and exec'd with a stub `run_parser`):
differing dates call `("models", "2026-11-13")` exactly once and restore `_PM_OPTIONS`; equal dates do nothing
and print no `!!`; with the setting off a RuntimeError carries the runnable line; a missing
`_upcoming_game.json` neither stops nor auto-runs.


## 2026-11-19 -- CONFIRMED BUG: Ripon players in UWW's roster (a whole game's teams reversed)

**Corey:** "something is wrong with the Hope scouting brief because now there are Ripon players in UWW's
roster." They were, and it was not the roster -- `data/uww_live_rosters.csv` is clean (18 UWW, 22 Ripon).
`data/uww_pbp_box_score.csv` had the 2026-11-14 game **completely inverted**: our nine (Madson 28 pts,
Chestnut, Robinson, Lukenbill, McEwen, Rogers, Vann, Teague-Johnson, Paddock) filed under `Ripon Red Hawks`,
and thirteen Ripon players (Flowers, Asman, Daun, Leoni, Gonzales, Bunders, Rahn ...) filed under
`UW-Whitewater`. The 11/07 Carroll game in the same file is correct, which is the tell.

**Why.** FastScout's play-by-play is `Time | LeftTeam | Score | RightTeam` and which side is UWW depends on
home/away. `36_parse_play_by_play_mhtml_files_into.py` already detects that: it pulls player names out of both
columns and compares them with `uww_roster_names`. But that set is built from `stats`, the UWW SEASON-STATS
scrape -- and on the 11/19 run that scrape timed out ("second stats table never loaded, proceeding with
schedule table only", three times in the log). Empty set -> `0 > 0` is False -> the file was taken as
un-swapped. 11/14 Ripon @ UW-Whitewater is the one game this season where UWW is HOME, so its columns really
were reversed, and every event, the box score, the roster the brief draws from, the lineups and the minutes
went to the wrong team. No warning was printed because the check "succeeded".

**Fix** (`36_...py`, 13,768 b), three ways to decide, in order:

1. **roster names, case-insensitively, from the live roster pages as well as season stats.** `live_rosters`
   (built in 21, two cells earlier) is ALL CAPS and the play-by-play is not, which is why it could not simply
   be added to the old exact-match set. Both sides are normalised (`[^a-z ]` stripped) before comparing.
2. **the table's own header**, when no name matched: `raw_df.attrs["column_teams"]` -- which `parse_pbp_html`
   has always set and section 25 already uses -- reads `{'uww_text': 'Ripon', 'opp_text': 'UW-Whitewater'}` for
   this file. Decisive on its own.
3. **the file name**, when the header is no help: it names the away team first, so
   "11_14_26 Ripon Red Hawks @ UW-Whitewater" means UWW were home and the right column is ours.

The warning now says which of the three caught it. If none can (no roster anywhere, no header), that is printed
as a warning rather than passing silently.

**Validation** (`~/wmtest/pbpswap_t.py`, `parse_pbp_mhtml` / `classify_event` lifted out of 16 and 17 and run
against the real input files): for 11/14 Ripon, column 2 holds 13 players and none of ours while column 4 holds
10 of which 9 are ours -- swap detected both with a roster and, by the header, with **no roster at all** (the
11/19 case); for 11/07 at Carroll, no swap either way.

**Still to do: the data on disk is wrong until the sections from 36 down are re-run.** Everything derived from
that game -- box score, minutes, lineups, clutch, the brief's roster -- carries the flip. The 11/19 models run
finished before this fix, so the Hope brief it produced should not be trusted on anything involving 11/14.


## 2026-11-19 -- a fourth lineup card: best in the clutch

**CONFIRMED CHANGE (requested:** "add a card for best clutch group for 5 and 3 man lineups.")
`87_build_html_scouting_brief_for_upcoming.py` (548,233 b). `_lu_cards` now builds a fourth card beside Most
minutes / Best +/- / Best PPP, for the five-man units and again for the 3-man combos.

* `_clutch_units(three)` walks this run's clutch clips (`game_situation` starts "Clutch" -- 47's shared rule:
  not the first half, 5:00 or less, margin 8 or fewer) and tallies, per group, offensive possessions and
  points FOR from `offense_lineup`, defensive possessions and points AGAINST from `defense_lineup`. For trios
  every three-player combination of each lineup on the floor is counted, so a trio collects far more
  possessions than its fives do.
* **Judged on both ends.** The ranking is points a possession scored MINUS points a possession allowed, since
  a clutch five that scores and gives it straight back is not the five to close with. Today:
  `Madson / Robinson / Lukenbill / McEwen / Teague-Johnson -- +0.60 PPP net (17 Poss) -- 1.22 scored, 0.62
  allowed -- 9 with the ball, 8 defending`, and the trio `Madson / Robinson / McEwen` at +0.67 on 21.
* **CONFIRMED BUG (caught before shipping):** with "at least one possession at each end" as the floor,
  Elmhurst's five read "+1.00 PPP net" off TWO offensive possessions -- 2.00 scored is a single three. Each
  end now needs **3** (the floor the lineup tables' own PPP column already ranks on) and 6 in total for a five,
  8 for a trio. Their five correctly drops off; their trio (4 with the ball, 12 defending) stays.
* A side with no clutch film gets no card, and an empty lineup table still prints the clutch card alone if
  there is one.

**Validation** (`~/wmtest/cluunit_t.py`, both functions lifted by AST and run against the live
`uww_play_calls.csv`): for each side and both sizes the card's possession counts add up (`with the ball` +
`defending` = the bracketed total), `scored - allowed` equals the stated net to two decimals, every group shown
has possessions at both ends, and an empty frame produces no card and no error.


**CONFIRMED CHANGE (requested 11/19, same file, 548,670 b):** "Move the link to the application into the
expandable section right after the table." The "All N keys with evidence and reasoning" link was sitting loose
under the closed expander bar, which read as a second, redundant way in. It is built once (`_ktv_link`) and
emitted inside the `<details>` straight after `</tbody></table>`. It still prints outside when there is no
expander to put it in (`_ktv_expander` false -- every key already on a card).

**Validation**: `~/wmtest/ktvtbl_t.py` extended -- the link is inside the `<details>`, after the `</table>`, and
nothing after `</details>` mentions it. (The test's opponent was also moved to Hope, since `uww_ktv_keys.csv`
is Hope-only now: 11 keys, 5 carded.)


## 2026-11-19 -- the KTV cards group the way the app does

**CONFIRMED CHANGE (requested:** "I want the Keys to Victory cards to better match the Keys to Victory section
in the application. So maybe three cards for Offense, Defense and Personnel, Rotation & Intangibles.")
`87_build_html_scouting_brief_for_upcoming.py` (552,213 b).

The row was five cards, one key each, ranked by score. It is now **three cards, one per group**, built on the
SAME `category` column the app groups on, so the brief and the app sort the keys the same way:

* **Offense** -- `category == "offense"`
* **Defense** -- `category == "defense"`
* **Personnel, rotation & intangibles** -- everything else, which picks up Personnel and the odd "General" key,
  the way the app's own catch-all bucket behaves.

Each card carries its group's key count on the top strip, leads with that group's best-scoring key (linked to
the app, with its score and source badge), lists the rest beneath it, and ends with "+N more in the table
below" when the group is longer than `BRIEF_KTV_KEYS_PER_CARD` (4). The cards are built from the WHOLE `ktv`
frame, not the brief's six-key selection, because a group can easily have no key in that selection -- the
expander below still holds every key, and the "\u2605 on a card above" marks now follow `_ktv_on_card`, the keys
actually shown.

Today: Offense 2 keys, Defense 5 (one spilling to "+1 more"), Personnel 4.

`BRIEF_KTV_CARDS = False` still gives the old numbered sentences, and if the keys file ever has no categories
at all the card path stands down and the sentences print instead.

**Validation** (`~/wmtest/ktvgrp_t.py`, the block lifted out of the file and run against `uww_ktv_keys.csv`):
three cards in the expected order, every key in the file lands in exactly one group (counts sum to 11), no card
shows more than four keys, and the group with more than four reports the remainder. `ktvtbl_t.py` and
`briefchk_t.py` still pass against the new markup.


**CONFIRMED CHANGE (requested 11/19, same file, 553,003 b):** under the lead key on each KTV card goes its
REASONING, not its score and source tag -- "Finish every defensive possession with a box-out / They get 46% of
their own misses back -- a stop isn't a stop until we secure the rebound; find Orion Yant on every shot",
where it used to read "90 Data-Driven". The number and the tag say where a key came from; the reasoning says
what to do about it, which is what a coach reads a card for. Both are still on every row of the table below.
Falls back to the key's `evidence` line when it has no reasoning, the same fallback the table uses. The
remaining keys on a card stay headline-only -- three cards of four full reasons would be a page, not a row.

**Validation**: `~/wmtest/ktvgrp_t.py` now asserts the lead key carries a reasoning line and that no score or
source badge survives above the first `ktv-more` line.


**CONFIRMED BUG (fixed 11/19, same file, 553,853 b): "All keys table is way too wide."** The page's own cell
rule is `td { ... white-space: nowrap }` -- right for a stat cell, wrong for a sentence. Each key's reasoning
sat on one unbroken line and dragged the table far past the 1000px page. `table.ktv-tbl` now sets
`table-layout: fixed`, `white-space: normal` with `overflow-wrap: anywhere`, and fixed column widths
(Area 11%, Key 64%, Score 7%, Source 18%) so the text column takes the room rather than the badges. The global
nowrap is left alone for every other table, which wants it.

Worth remembering: this file's tables inherit `white-space: nowrap`, so any NEW table that puts prose in a cell
needs its own `white-space: normal` or it will blow the page width the same way.


**CONFIRMED CHANGE (11/19, 87_..._brief_for_upcoming.py): "I don't need the '7 KEYS' or the '+3 More in the
Table' notes."** The KTV group cards dropped the `N keys` badge in `lc-t` and the `+N more in the table below`
line. Both described the card rather than the game, and the All-keys table directly below already lists every
key. The card is now: group name, lead key, its reasoning, the other keys. `~/wmtest/ktvgrp_t.py` had been
counting keys per group off that badge -- it now checks the grouping against `_KTV_GROUPS` on the data and
asserts the badge and overflow line are gone.

**CONFIRMED CHANGE (11/19, same file): more explanation on "Expected here".** Two scores with no account of
where they come from read as a prediction. The line now says it is a projection off season rates; that each
team gets the midpoint of its own rate and the other's matching defensive rate across the four factors at the
average of the two paces (`_pos_g`); that points come through the possession identity, so free throws are
charged for the possessions they use; and that measuring the two teams against each other rather than a league
average means it says nothing about schedule strength. When either side has fewer than 6 games the "Built on
N and M games" clause adds that one outlier still moves it several points and the gap should be read as a
range; at 6+ games each it ends plainly.


**CONFIRMED BUG (fixed 11/19, 18_turn_raw_4_column_play_by_play_table_into.py -- SIGN FLIP ON EVERY SCOUTED
OPPONENT'S PRIOR GAMES).** Found from the brief: Hope's last-five-minute possessions against Franklin were
labelled "Trailing by 10+" in a game Hope won 79-59.

The play-by-play table is `Time | <Team A> | Score | <Team B>` and the score cell is `<A>-<B>` -- it follows
COLUMN ORDER. `build_pbp_events` took `score_m.group(1)` as `uww_score` and `group(2)` as `opp_score`
positionally, no matter which column `self_column` pointed at. For UWW's own files that was right: 36_ detects
a swapped file, swaps the text columns AND reverses the score string, then calls with the default
`self_column="uww_text"`. But an opponent's own file puts their events in whichever column their FastScout
account captured, 26_ resolves that empirically and passes it -- and the score was never swapped to match.
Three of Hope's four prior games (Elmhurst, Anderson, Franklin) have them in the SECOND column, so on those
games everything reading `uww_score` as the self team's score was inverted:
 - `game_situation`: Leading/Trailing by 10+ backwards (the clutch test is `abs(margin)`, so clutch itself was
   never affected -- that is why this hid for so long).
 - **45_aggregate_upcoming_opponent_5_man_lineup.py**: `end_self_score=("uww_score","last")` -> the scouted
   opponent's whole lineup +/- was negated. `uww_opponent_prior_games_lineup_stints.csv` had Hope at -6 and
   -20 in games they won by 6 and 20. That number drives `uww_opp_lineup_season_box`, which feeds the keys
   ("their worst net-rating units"), the brief's lineup cards and the app -- so the units we were being told
   to ATTACK were in fact their best, and the ones to counter were their worst.
 - 70_'s expected box score and 75_'s back-fill read the same column.

Fix: `build_pbp_events` now swaps the two scores when `self_column != "uww_text"`, at the source, so every
caller is right at once. 36_ and 79_ pass no `self_column`, so the new branch cannot fire on UWW's own games.
Harness `~/wmtest/pbpscore_t.py` parses all four Hope files and checks the self team's margin against the
header plus the final score cell (+6, -5, +27, +20 -- the -5 at North Central is genuine, Hope are in the
first column of that file), and asserts 36_/79_ still call with the default column.

**THE DATA ON DISK IS STILL FLIPPED** until a full `parser_models` run regenerates it. Anything read off the
opponent lineup tables before that run is backwards.

**CONFIRMED CHANGE (11/19, 87_..._brief_for_upcoming.py): the clutch card prints even when nothing
qualifies.** "Leave the card empty and note that there isn't a 5 man lineup." Returning "" left a hole in the
row that looked identical to a rendering fault. The card now says `No five qualifies`, whether the cause is no
clutch film at all or no group with 3 possessions at each end, and names the closest group with its own counts
(Hope: Sanchez/Miller/Cargill/Yant/Wesolek, 2 with the ball and 5 defending, out of 19 clutch possessions of
which only 4 are offensive). Their 3-man card still qualifies, because a trio collects possessions from every
five it sits in -- that asymmetry is expected, not a bug. `.lc-empty` dims the headline. `cluunit_t.py` now
asserts the card always renders.


**OPEN (11/19): the 11/18 UWW @ Elmhurst game has no film, because Synergy will not let the parser log in.**
Everything from the play-by-play is in (schedule L 65-73, 474 pbp events, box score, 58 lineup stints, 23
clutch events). Nothing from Synergy is: no clips, no frames, no play calls, no tracking, no Film Tagging
batch. The run picks the game correctly -- "game pages still to capture -- 1 of UWW's" -- then:

    [export] 2026-11-18 Elmhurst Bluejays: no Synergy export yet -- exporting it with Synergy Editor ...
    [editor] signing in to Synergy...
    [synergy-login] username field matched: name='Username' id='Username' type='text'
    [synergy-login] password field matched: name='Password' id='Password'
    [export] 2026-11-18 Elmhurst Bluejays: export failed (RuntimeError: Synergy login did not leave the
             login page ... Timeout 60000ms exceeded)

Both fields are found and filled and the Login button clicks without error; the page simply never leaves
/Account/Login. Login timeouts appear in every log since 11/17, but cost nothing until 11/19, the first run
needing a NEW export (every other game already had its export folder). There is no
`UWWhitewater@Elmhurst - Nov 18, 2026` folder in F:\Backups\uwwmensbball_tracking to fall back on.

The login page carries a hidden `DeviceHash` (empty, filled by the page's own script) and a "Setup phone
number for MFA code via text (SMS)" link, so an unrecognised device raising an MFA challenge is as likely as
a wrong password -- and the logs could not tell them apart, because the saved diagnostic HTML is the PRISTINE
page, captured before anything is typed.

Fixed that blind spot in 27_shared_video_tagging_helper_functions.py (24,661 b): `_page_error_text()` now also
reads `.validation-summary-errors` / `.field-validation-error` / `.text-danger` (ASP.NET Identity's own
rejection markup, which none of the three original selectors matched), and the failure branch saves
`Synergy - Login Page (after submit).html` and appends to the error whether a one-time-code field has appeared
and whether DeviceHash is still empty. The next failed run should name the cause instead of only the symptom.

Workaround meanwhile: export the game by hand in Synergy Editor (Ctrl+E) into
F:\Backups\uwwmensbball_tracking as `UWWhitewater@Elmhurst - Nov 18, 2026`. With the folder present the
parser uses it and never logs in -- the same path the Thiel message recommends.


**RESOLVED (11/19): Synergy turned on two-factor by email, and the parser could not answer it.** Corey's
screenshot: "Two Factor Authentication -- We sent a security code by email to F***@gmail.com", with a Code
box and LOGIN / RESEND CODE / CANCEL. That form POSTS BACK TO THE SAME /Account/Login URL, which is why
`wait_for_url("/Account/Login" not in url)` could only sit there for 60s and report "did not leave the login
page". Correct credentials the whole time.

Two things were needed, because either alone is useless:

1. **A browser profile that survives between runs** (02_parse_every_team_schedule_scrape_live_from.py,
   118,962 b). `_bootstrap` used `chromium.launch(headless=True)` + `new_page()` -- a throwaway profile every
   run, so Synergy saw an unrecognised device every run and emailed a new code every run. It now opens
   `launch_persistent_context(FASTSCOUT_PROFILE_DIR or INPUT_DIR/_browser_profile)`. If the profile can't be
   opened (a second run holds the Chromium lock) it falls back to the old throwaway browser and SAYS so, so
   the run still happens. This is the session EVERY FastScout step shares -- schedules, rosters,
   play-by-play, the editor export -- so watch it after the first few runs.
2. **Answering the code once** (27_shared_video_tagging_helper_functions.py, 29,225 b). `login_to_synergy`
   now ticks **Remember My Login** before submitting (without it no device token is issued at all, so a kept
   profile would still be challenged forever), then waits for EITHER outcome -- leaving the login URL, or a
   code field appearing. On a code field it takes the digits from `SYNERGY_MFA_CODE` if the notebook set one,
   otherwise polls `inputs/_synergy_code.txt` for `SYNERGY_MFA_WAIT_S` seconds (default 300), submits, and
   renames the file to `.used` so a stale code is never replayed. A FILE and not `input()`: this runs on the
   Playwright worker thread, where the notebook's stdin is not reliable.

`~/wmtest/synmfa_t.py` drives the function against a stub page through all four endings: plain sign-in
(Remember ticked), two-factor answered from the file, two-factor answered from `SYNERGY_MFA_CODE`,
two-factor with no code (its own error), and refused credentials (the old error, with the DeviceHash/MFA
clues). .gitignore now excludes the profile folder and the code file.

Expectation worth recording: the first run after this still asks for a code. Later runs should not, until
Synergy expires the remembered device -- if the prompt comes back every single run, suspect the profile is
not persisting (look for the "[session] the saved browser profile ... could not be opened" line) rather than
the login code.


**CONFIRMED BUG (introduced and fixed 11/19, within the hour): the two-factor handling sent a flood of codes
and got the account locked out.** Corey: "It sent me a ton of codes and there is no file yet for me to put it
in." The 15:18 run tried ten sign-ins; `Synergy - Login Page (after submit).html` -- the diagnostic added
earlier the same day -- caught Synergy's own verdict: **"Error. Too many two-factor authentication attempts.
Please try again in 60 minutes."**

Two faults, the second being what turned one bad attempt into ten:
 1. The success test was still `"/Account/Login" not in page.url`. The two-factor form lives at its OWN
    /Account/ URL, so the moment the submit navigated there this function returned SUCCESS. The caller then
    found "0 game(s)" (never actually signed in) and tried again -- each attempt emailing a fresh code and
    walking away from it. The earlier symptom (a 60s timeout) only looked different because without
    "Remember My Login" ticked the page used to post back to the same URL.
 2. Nothing read the page's own error text during the wait, so the lockout was invisible and the retries
    kept feeding the counter that caused it.

Fixes in 27_shared_video_tagging_helper_functions.py (32,580 b):
 - The code field is looked for BEFORE any success test; a code page can never read as signed in.
 - Success means leaving the identity provider altogether (`auth.synergysportstech.com` and `/Account/` both
   gone), not leaving one page of it.
 - A lockout ("too many" / "locked" / "try again in") raises at once and is written to
   `inputs/_synergy_lockout.txt`; while that timestamp is in the future every later call -- in this process
   AND in the next run -- refuses before touching the form. Delete the file to override. The rule to keep in
   mind: an attempt made while locked out emails another code and RESTARTS their 60 minutes.
 - `inputs/_synergy_code.txt` is created empty when the wait begins, so there is something to paste into.

`~/wmtest/synmfa_t.py` now covers eight endings, including the two-factor page on its own URL (must not read
as success), the lockout (raised, persisted, and the next call submits NOTHING), and the code file being
created. A lockout file was written by hand at 15:25 local, expiring 16:22, to stop the clock being restarted
before Synergy's own window closes.


**CONFIRMED BUG (fixed 11/19, third pass -- the one that actually mattered): the code field was never found,
because the selector could not be parsed.** The 17:05 run reached the right page -- the error names it:
`https://auth.synergysportstech.com/Account/VerifyCode?userId=...&rememberLogin=True&sentTwoFactor=None` --
and the saved after-submit HTML shows the field sitting there as `<input id="Code" name="Code"
placeholder="Code" inputmode="numeric">`, with buttons Login / Resend code. The prompt to paste a code never
printed once.

Cause: the selector list was written with CSS Level 4's case-insensitivity flag, `input[name="Code" i]`.
Playwright's own selector parser rejects it, so the whole comma-joined locator raised on every call -- and
`_code_field()` swallowed that in a bare `except: return None`, reporting "no code field" sixty times while
the field was plainly on screen. The polling loop ran out, the 5s fallback raised, the caller retried, and
another code was emailed.

Fixed: no `i` flag anywhere, selectors tried ONE AT A TIME (`input#Code`, `input[name="Code"]`,
`input[autocomplete="one-time-code"]`, `input[inputmode="numeric"]`, and the TwoFactor/VerifyCode/Otp
variants), so a single bad selector cannot blind the rest, and the first failure of each prints
`the selector ... is unusable` instead of vanishing. 27_shared_video_tagging_helper_functions.py is 33,742 b.

Two rules worth keeping: **never put the `i` flag in a Playwright selector**, and **never swallow a selector
error** -- a silent `except` here cost three rounds of emailed codes and an account lockout. The
"Remember My Login" tick did work: the VerifyCode URL carries `rememberLogin=True`.

Also note for next time: a parser_lib section is exec'd when the run STARTS, so a fix landing mid-run does
not reach the run in progress. It has to be stopped and restarted.


**NEW (11/19): parser/synergy_login.ipynb -- the first-time Synergy sign-in, done by hand.** Requested after
three rounds of emailed codes: "can you just write a new notebook that does this login for the first time."
Four cells. It opens a VISIBLE Chromium on the same profile the parser uses
(`inputs/_browser_profile`, or FASTSCOUT_PROFILE_DIR), fills SYNERGY_USERNAME / SYNERGY_PASSWORD from .env
with "Remember My Login" ticked, then stops and waits up to 10 minutes while YOU type the emailed code in
the window. Cell 2 reopens the same profile HEADLESS, the way the parser does, and says whether it is still
signed in -- so the profile is proved before a parser run depends on it.

Notes worth keeping: the Playwright sync API will not run on a Jupyter kernel's main thread (it already has
an asyncio loop), so the notebook does its work on a worker thread with the Windows Proactor policy, the
same shape as run_in_fastscout_session. Closing the context is what flushes the profile to disk, so both
cells close in a `finally`. And Chromium LOCKS a profile folder: stop any parser run before using this, or
the parser falls back to a throwaway profile and the codes start again.


**RESOLVED (11/19): the Synergy sign-in works.** The 17:21 models run signed in, found the game, opened
Synergy Editor and pressed OK:

    [editor] game title on Synergy: UWWhitewater@Elmhurst - Nov 18, 2026
    [export] OK pressed -- Synergy Editor is exporting the clips to F:\Backups\uwwmensbball_tracking

**CONFIRMED BUG (fixed 11/19, 46_frame_capture.py, 200,818 b): the Export.csv wait started before Synergy
Editor was even opened.** Corey: "I don't think it waited long enough for them to be exported." In
`_vx_make_export`, `t0 = time.time()` sat ABOVE `_sst_editor_export(...)`, and the budget was a flat 180 s.
Opening the editor is the slow part -- 17 s for the window, a fixed 150 s to let the game load, then the
dialog -- so the budget was gone by the time OK was pressed: the wait looked once, printed "never wrote an
Export.csv", and returned None. Synergy wrote Export.csv about two minutes later and finished all 226 clips
(3.2 GB) ten minutes after that. A complete export the run had walked away from.

Fix: the clock starts when OK is pressed, the budget is `SYNERGY_EXPORT_CSV_WAIT_S` (default 900 s), the
wait prints "waiting for Synergy Editor to write Export.csv -- N of 15 min" as it goes, and the give-up
message now says the export may still be running and that the next run will find the folder.
`~/wmtest/vxwait_t.py` drives the function on a virtual clock: real-world timing (175 s to open, CSV 120 s
after OK) now succeeds where it used to fail at once; an 8-minute CSV is still caught; and a dead export
still gives up and registers nothing.

No re-export is needed for Elmhurst: `_vx_find_export` matches a folder by date plus team words, and
`UWWhitewater@Elmhurst - Nov 18, 2026` matches "2026-11-18 Elmhurst Bluejays" (elmh + whitewater in the
folder name, date in range), so the next run adopts the finished export.

Housekeeping noticed in passing: `parser_lib/46_frame_capture-1.py` (141 KB, 11/17) is a stray copy. Nothing
loads it -- run_section resolves "46_frame_capture" -- but it is confusing next to the real one.


**HOUSEKEEPING (11/19): the stray parser_lib copies are out.** Two of them, both dated 11/17 (the move to
F:), not one: `46_frame_capture-1.py` (141 KB against the real 200 KB) and `00_parser_modes-1.py`. Moved to
`parser/Claude outputs/_superseded_parser_lib/` rather than deleted -- git records it as a rename, so they
are recoverable.

They were inert, and it is worth knowing WHY, because the answer says what would have been dangerous:
sections are resolved by name. `run_parser` executes the notebook's cells, each naming its section through
`run_section("46_frame_capture")`, and `_pm_core_fingerprint` stats only the files those calls name. Nothing
globs `parser_lib/*.py`. A stray is therefore invisible to the run -- but a stray that someone edits by
mistake is invisible too, which is the real cost, and both these files were 1,000+ lines adrift.

Still tracked and probably shouldn't be (not touched -- say the word): `.ipynb_checkpoints/` throughout,
`__pycache__/*.pyc` (including parser_lib's, which any compile rewrites and dirties the working tree), and
the older `-1` copies already sitting in `parser/Claude outputs/`.


**NOT A BUG (11/19): Hope vs North Central (11/17) is queued, not lost.** It is the "1 of the upcoming
opponent's" page in `Frame capture: game pages still to capture`. Synergy does have the game --
`[synergy] 2026-11-17 Hope Flying Dutchmen vs North Central (IL) Cardinals: Synergy game
6ab8194c211bee6ed9ce80bc (not on FastScout yet)` -- which is why the earlier lines read
"(no video_url)" and "no _video file found": FastScout has nothing for it, but capture uses Synergy's page,
so that does not block it. `VISION_ONE_GAME_AT_A_TIME` is False, so the coaches-finish-first gate is not
holding it either. It waited purely on `VISION_MAX_GAMES_PER_RUN = 2`, and the 18:04 run spent both slots on
Thiel's missing frames and the Elmhurst export. Another run picks it up.

**Worth fixing, though: Thiel eats a slot on EVERY run.** `Thiel@UWPlatteville - Nov 6, 2026` has 235 rows
in Export.csv and 234 videos -- exactly one missing, `98.mp4` -- so the folder is permanently "some clips'
frames are missing or failed" and is re-queued for completion every single time ("nothing new for 18560 min"
and counting). One of the two slots per run is therefore spoken for before anything new is considered.
Re-export that game in Synergy Editor (Ctrl+E) into the same folder, or move the folder aside, and both
slots go to real work again.


**CONFIRMED CHANGE (11/19, 00_parser_modes.py, 60,088 b): removing a game from the cell now stops it.**
Corey: "I have removed the Thiel game from BANK_GAMES, so it should not be trying to do anything further
with it until that is put back in there. The same should be true with ADD_GAMES and EXTRA_GAMES."

Thiel WAS commented out of BANK_GAMES, and ADD_GAMES is empty; `BANK_GAMES_STICKY` (default True, added
11/15) kept it alive from `inputs/_bank_games.json` anyway, and every run spent one of its two frame-capture
slots "completing" it. But 11/15's stickiness was not pointless: it exists because emptying ADD_GAMES had
silently dropped Hope vs Franklin and taken its 212-clip Film Tagging batch out of the app.

So stickiness is now NARROW: a remembered game is kept only while it still has an OPEN BATCH --
`<data>/play_tag/tag_<date>_<teams>/review.json`, the file 55c writes with a batch and removes with it.
`_bank_batch_open()` matches on the game's date plus one team name (the loose match `_vx_find_export` uses,
since the folder spells teams its own way: "Wisconsin-(Platteville) Pioneers vs Thiel" ->
`tag_2026_11_06_Thiel_UWPlatteville`). A game with no date on file is kept rather than guessed away.

Saved answers deliberately do NOT keep a game banked. Thiel has 8 files in data/play_review_saves --
starters checks, a player review, and the `tag_skipgame` save itself -- and un-banking touches none of them;
they live on the 'saves' branch. A game whose batch a coach skipped is exactly the case this is meant to
drop.

`~/wmtest/bankstick_t.py` runs it against the real `_bank_games.json` and `data/`: Thiel -> dropped,
Hope vs Franklin -> kept, saves alone do not hold a game, a batch that reopens brings it back with no edit
to the cell, no date -> kept, missing play_tag folder -> dropped without crashing.

ADD_GAMES needs nothing of its own: entries become BANK_GAMES entries (00_parser_modes ~302-320), so the
same rule covers it. EXTRA_GAMES already behaves this way BY DESIGN -- parser_models passes its list
explicitly (so [] wins), and parser_brief's cell says `EXTRA_GAMES = None`, meaning "parser_models'
setting", which it reads from `inputs/_upcoming_game.json`; models rewrites that file every run. The only
stale path is a brief/tagging run with no models run since the change.


**CONFIRMED CHANGE (11/19): roster photos now fall back, and the fallback is labelled.** Hope found this:
all nine of their saved "headshots" were the SAME 5,637-byte grey silhouette. Their report carries no
photos, so 82_ saved the report's own no-photo avatar under every name -- a fake photo, which is worse than
no photo because it looks like the system worked. The size guard there is `len(img_bytes) > 500`, and an
avatar sails past it.

Three steps, appended to `82_extract_player_headshots_from_scouting.py` (34,114 b), in order:
 1. **Avatar sweep.** Group player_images by md5: the same bytes under two or more names is never two
    headshots. Those files move to `player_images/_placeholders/` (moved, not deleted) and the players count
    as having no photo.
 2. **Last season.** Any `data_<season>/player_images` beside `data/`, newest first.
 3. **The team's own site.** `inputs/opponent_sites.json` maps opponent -> roster URL (seeded with
    `"Hope Flying Dutchmen": "https://athletics.hope.edu/sports/mens-basketball/roster"`). The roster TABLE
    is read every run and written to `uww_opponent_web_rosters.csv` -- jersey, position, height, weight,
    class, hometown, high school, profile URL -- because none of that is in the scouting report and it is
    worth having on its own. A player still without a photo gets his profile page's `og:image`, which is
    where Sidearm sites keep the headshot (verified: Brady Miller's is
    athletics.hope.edu/images/2026/11/3/Miller_Brady.jpg). The page is cached on disk for
    OPPONENT_SITE_FRESH_HOURS (12) and saved as `<team> - Roster (web).html` so a parse failure can be
    looked at.

Provenance goes to `uww_player_image_sources.csv` (player, source, detail, opponent). The brief
(87_, 558,900 b) prints it under the face via `_photo_note()` plus a `.photo-note` style and an `img title`;
the app (1,241,270 b) shows it on the roster card and in the player dialog. "scouting report" prints
nothing -- only a photo that is NOT this season's is labelled.

Traps paid for while building it: `read_html` types a numeric column, so jersey 13 arrived as `13.0` and an
empty cell as `nan` -- hence `_pi2_txt()`; and the block was first written with a stale `_pi_pd.` prefix
(pandas is plain `pd` in these sections).

`~/wmtest/photofb_t.py` runs the whole chain against a sandbox with a Sidearm-shaped roster page over
file://: the avatar is swept, one player is restored from last season, three come from the site with the
right table fields (#13 F 6-6 210 Jr. | Zeeland, MI / Zeeland West), a genuine report photo is left alone,
and every source lands in the CSV.

Untested on the real site: this shell cannot reach athletics.hope.edu (proxy allowlist), so the first live
run is the real test. If the table does not parse, the saved HTML is in parser/inputs.


**CONFIRMED BUG (fixed 11/19, 47_play_calls.py, 380,187 b): "Ripon Motion #1 is still showing as one of UWW
plays in the Play Table."** NOT the routing this time -- the 11/18 Game-cell fix is holding. The data itself
says UWW ran it. Two clips of the 11/14 Ripon game:

    clip 88  Offense  offense_team=UW-Whitewater  player=Joey Daun     result=Non Shooting Foul
    clip 95  Offense  offense_team=UW-Whitewater  player=Michael Asman result=Non Shooting Foul
    both: offense_lineup = UWW's five, defense_lineup = Ripon's five, coach_play_call = "Ripon Motion #1"

So a coach typed Ripon's set name on two possessions the play-by-play says were ours, and the tagged player
on each is a Ripon man. Both are non-shooting fouls, which is the shape of clip where a possession boundary
is easiest to read the wrong way -- so either the call is wrong or the possession is, and from here the two
cannot be told apart.

The parser now refuses to guess: `_pl_foreign_call()` flags a row whose play call's first word names a team
that is NOT the team on offense, writes it to the new `call_names_other_team` column (added to
PLAY_CALL_COLS -- the Thiel "skipped" lesson: a column missing from that list is reindexed away), keeps it
out of `play_call_summary` for BOTH sides, and prints a "!!" line naming the game, the call and the clip
numbers so someone can re-check them in the app. The coach's answer on the clip is never rewritten.

`~/wmtest/foreign_t.py` on the real table: exactly 2 of 2,177 clips flagged (88 and 95), Ripon's own 25
"Ripon Motion" clips on Ripon possessions untouched, and our own vocabulary (Zoom, Cheetah, Pistol, Snap 30,
Motion -- 46 clips) untouched.


**CONFIRMED CHANGE (11/19, 87_..._brief_for_upcoming.py, 565,278 b): "Possibly mis-tagged" inside the
offense detail.** Requested: "create an expandable section that lists things that you believe are tagged
incorrectly like these. And if possible can you make a link to the plays in the application or in Synergy."
A `<details>` sits with the other collapsibles under HOW WE RUN OFFENSE / HOW <OPP> RUNS OFFENSE, built by
`_mistag_rows()` / `_mistag_details()` from `_pcc_all` -- so it works off the clips table as it stands and
does NOT wait for 47's new `call_names_other_team` column.

Two checks, and the table says which is which, because they are not equally sure:
 - **!!** the call's first word names a team that did not have the ball ("Ripon Motion #1" while
   UW-Whitewater had it). A contradiction.
 - **?** within ONE game, the other team ran that call 3+ times and this side has it once or twice. A
   question, not a verdict.

The second check was season-wide at first and flagged "Flow", "Set", "5 Out", "SLOB Motion" -- words every
team uses -- which is how a list stops being worth opening. Counting inside a single game cut the opponent
side from 9 to 3 and kept the real ones (Ripon ran Stagger 12 times in that game; we have it twice).

Each row links to the app (`page=analytics&game=<game_code>&clip=<n>`; the app has no per-clip route yet, so
it lands on Analytics and carries the params) and to Synergy's breakdown page for that game, from
`inputs/_synergy_ids.json` keyed on the game name, which matches game_code ("Ripon@UWWhitewater"). Nothing
is corrected: a coach's answer is only ever questioned out loud. Traps: this section has no `json` import of
its own (import it inside the function), and these helpers sit at 12-space indentation inside another
function. `~/wmtest/mistag_t.py` renders it from the real clips.


**RESOLVED (11/20): Hope vs North Central came through.** The 21:52 run exported it end to end -- Synergy
Editor came to the front, Ctrl+E landed, `Hope@NorthCentralIL - Nov 17, 2026`, 230 clips (185 after free
throws), the export box closed itself, 185 clips captured in 321 s -- and Film Tagging opened a 185-clip
batch. So the 20:55 failure ("couldn't bring Synergy Editor to the front -- Ctrl+E may go to another
window", "the export window never opened") was a one-off focus problem, not a defect: something else had
focus while the run was working. If it recurs, the parser's own advice is right -- click once inside Synergy
Editor's clip list and run again -- and the rule of thumb is to leave the machine alone while an export is
going.

uww_play_calls.csv now carries all three of Hope's scouted games (Franklin 212, Elmhurst 178, North Central
185 = 585 opponent clips, against 390 before), and the tagging queue stands at Franklin 0/212, North Central
0/185, UWW@Elmhurst 0/171, UWW@Carroll 0/24.

---

## Session roll-up -- 11/19 into 11/20

Everything above happened in one long session. What follows is the shape of it, for a future reader who does
not want to read twenty entries.

**The spine of the session.** The 11/18 UWW @ Elmhurst game would not come into Film Tagging. Chasing that
one symptom went: the game IS in (play-by-play, box score, lineups, schedule) but has no FILM -> the film
needs a Synergy export -> the export needs a login -> Synergy had turned on two-factor by email -> the
parser could not answer it -> a persistent browser profile plus a one-time code could -> my first attempt at
that flooded the account with codes and got it locked out for an hour -> a selector written with CSS's `i`
flag (which Playwright rejects) was swallowed by a bare `except` -> fixed, signed in, exported -> and then
the export's own wait was too short, because its clock started before Synergy Editor was even opened. Each
of those is a separate entry above. The lesson that ties them together: **a bare `except` that turns a real
error into "nothing here" cost three rounds of emailed codes and a lockout.**

**Files changed (sizes as of 11/20 07:21, all committed by Corey):**
 - `parser_lib/18_turn_raw_4_column_play_by_play_table_into.py` (4,387) -- the scouted-opponent score flip
 - `parser_lib/02_parse_every_team_schedule_scrape_live_from.py` (118,962) -- persistent browser profile
 - `parser_lib/27_shared_video_tagging_helper_functions.py` (33,742) -- two-factor, lockout breaker
 - `parser_lib/46_frame_capture.py` (200,818) -- Export.csv wait starts at the OK press
 - `parser_lib/00_parser_modes.py` (60,088) -- removing a game from the cell now stops it
 - `parser_lib/47_play_calls.py` (380,187) -- a call that names the other team stays out of the play tables
 - `parser_lib/82_extract_player_headshots_from_scouting.py` (34,114) -- photo fallbacks + the web roster
 - `parser_lib/87_build_html_scouting_brief_for_upcoming.py` (565,278) -- KTV cards, the All-keys table
   width, "Expected here", the empty clutch card, the photo note, "Possibly mis-tagged"
 - `streamlit_app.py` (1,241,270) -- the photo note on the roster card and in the player dialog
 - `parser/synergy_login.ipynb` (NEW) -- the first-time Synergy sign-in, by hand
 - `parser/inputs/opponent_sites.json` (NEW) -- opponent -> official roster URL
 - `.gitignore` (1,111), `CLAUDE.md`
 - moved out of parser_lib: `46_frame_capture-1.py`, `00_parser_modes-1.py`

**Offline harnesses added in ~/wmtest (each runs against the real data or a sandbox):** `pbpscore_t.py`
(the score flip, all four Hope files), `synmfa_t.py` (eight sign-in endings), `bankstick_t.py` (bank
stickiness), `vxwait_t.py` (the export wait, on a virtual clock), `photofb_t.py` (the whole photo fallback
chain), `foreign_t.py` (2 of 2,177 clips flagged), `mistag_t.py` (the new brief section), plus the earlier
`ktvgrp_t.py`, `ktvtbl_t.py`, `cluunit_t.py`, `synlogin_t.py`.

**Verified live:** the sign-in, the Elmhurst and North Central exports, the Film Tagging batches, the
play-call flag counts, the bank rule against the real `_bank_games.json`.

**NOT yet seen in a real run (the next `parser_brief` is their first test):** the photo fallbacks and the
athletics.hope.edu scrape, the "Possibly mis-tagged" section, the "Expected here" wording, the empty clutch
card, and the narrower All-keys table. The web scrape is the one most likely to need a second pass -- this
session's shell could not reach athletics.hope.edu (proxy allowlist), so the table parsing was only proved
against a Sidearm-shaped fixture. If it misses, the fetched page is saved in parser/inputs as
`<team> - Roster (web).html`.

**Open, by choice:**
 - Thiel's export is one clip short (234 of 235, `98.mp4` missing) so its folder always reads "incomplete".
   It no longer eats a capture slot, because Thiel is out of BANK_GAMES and the new rule drops a game with
   no open batch -- but a re-export in Synergy Editor would tidy it.
 - Ripon@UWWhitewater clips 88 and 95: a coach's "Ripon Motion #1" on two possessions the play-by-play says
   were ours, both non-shooting fouls, both with a Ripon player tagged. Either the call or the possession is
   wrong and the data cannot say which. They are flagged and kept out of the play tables; someone should
   open them in the app.
 - `.ipynb_checkpoints/` and `__pycache__/*.pyc` are tracked in git (including parser_lib's, which any
   compile dirties). Left alone.
 - The app has no per-clip deep link yet, so the brief's mis-tag rows land on Analytics carrying
   `game=` and `clip=` for a future jump.


## 2026-11-22 -- PLAY CALL SUMMARY: click a play call to see the plays behind it (options A + C)

**CONFIRMED CHANGE (requested:** "click on 'Zoom' and then either get information about those plays that make up the
data and see the video" -> "Yes, let's do A and C".) `87_build_html_scouting_brief_for_upcoming.py`, the Play call
summary under HOW WE RUN OFFENSE / HOW <OPP> RUNS OFFENSE (both sides, every kind of brief). The table became a list of
`<details class="pcs-r">` rows (Play call / Poss / PPP, same numbers as before). Opening a row lists its clips: game +
date, clip number, half and clock, player, result (+ points), the five on the floor (surnames), and a "Synergy ->" link
to that game's breakdown page (from `inputs/_synergy_ids.json`, the same source the "Possibly mis-tagged" table uses).
Below each list: "open the game in Synergy and go to that clip number". NOT built: video in the brief (a clip is ~3 MB
and the brief is one emailed file) and an app link (the app still has no per-clip route / viewer -- option B).

**The list has to add up to the Poss column, so `_pcs_clips()` copies the breakdown's own selection** (47
`_pl_offense_breakdown`): this season only (`season_play_calls`), possessions not on defense, `decode_quality` not
"Untagged", situation Half court / BLOB / SLOB / ATO only (transition, offensive rebounds and openers are in the app's
tables but not in this count), and for "No Play Call" (our side: "Flow") every clip with no call in those situations.
Checked against the real Hope brief: **opponent side 52 of 52 rows match exactly; our side 33 of 36** -- Flow lists 39
for 37, Gold 13 for 12, Over 2 for 1 (the breakdown drops a few clips with a rare / missing formation; not reproduced).
Do NOT add a "formation used 3+ times" filter: tried, it broke the opponent side.

**Two things the list showed about the numbers themselves (nothing changed -- Corey decides):**
1. The breakdown counts **"Non Possession" clips as possessions** (a foul with the ball kept, a violation). The list
   marks them "-- not a possession". Zoom shows it: 3 possessions / 1.67 PPP before UWW@Elmhurst clip 18 (Ketchum
   non-shooting foul) was tagged, 4 / 1.25 after.
2. **Skipped clips are still counted.** Elmhurst@Hope has clips with `skipped = True` AND decode_quality "App tag"; the
   breakdown counts them (Hope's "Motion" 6 includes five of them), against the 11/15 rule that a skipped clip is in no
   table. The list does not filter them either, so it matches the row. Worth checking why they carry both.

Harness: `~/wmtest/pcs_t.py` (block lifted out of 87, run against data/uww_play_calls.csv; compares every row with the
Hope brief on disk). Not yet seen in a real brief or in a browser -- the next parser_brief is the first test.


## 2026-11-22 (later) -- Play call summary: games list + "watch in Synergy" (builds on the entry above)

**CONFIRMED CHANGE (requested:** "when you expand the row for Zoom ... a list of different games that we ran the play, then
be able to click on that opponent name that takes you to this page. Then you auto-select the plays so they can be watched.")
Example page Corey sent: Synergy's play-by-play page for Ripon@UWWhitewater (6abc2667...). **How Synergy does it:** the page
has no "selected plays" URL -- selection is page state. But every play on it is a link to Synergy's video player,
`https://editor-web.synergysports.com/video?playlistUrl=<api>/possessionplaylists/statistics/37/clips?expression=<base64 of
"iid eq N">&sort=gameDate:desc&take=500&title=...` (the expression is double-encoded: base64 inside playlistUrl, both URL-
quoted). `iid` is Synergy's id for the play = the `iid` of `api/games/<id>/events`, which 46 already downloads for lineups.

**Built:**
- `46_frame_capture.py`: `_syn_save_lineups` now also writes an **`iid`** column to `inputs\_bank\<game id>_lineups.csv`;
  new `_syn_backfill_iids()` (called after `_syn_export_lineups`, inside the frame-capture block, so it runs in
  parser_models / parser_tagging, NOT parser_brief) loads the box score page of every game whose clips we hold and whose
  file has no `iid` yet. `SYNERGY_IID_LINKS = False` turns it off; `SYNERGY_IID_MAX_GAMES` (15) caps a run.
  Log: `[synergy] play ids ... still to fetch: N game(s)` / `play ids saved for N of M game(s)`.
- `47_play_calls.py`: `_syn_attach_iids()` (after `_syn_attach_lineups`) adds **`synergy_game_id`** and **`synergy_iid`** to every
  clip, matched by Synergy description (= `synergy_string`); identical descriptions in a game are separated by half + clock
  (<= 10 s), else by order; no iid is given twice. Both columns are in `PLAY_CALL_COLS`. Log: `[synergy] <date> <game>:
  Synergy play ids -- N of M clip(s) matched`.
- `87`: each Play call summary row now lists the GAMES it was run in. The opponent's name ("vs Ripon") is the link: with play ids
  it opens Synergy's video player on that play call's plays from that game; every play also has its own "Watch ->" link;
  without play ids the name links to the game's breakdown page (the earlier behaviour).

**Tested:** on the example page's 216 plays vs our 175 Ripon@UWWhitewater clips, all 175 matched, 175 distinct iids, and iid
order follows clip number exactly (24 clips share a description with another clip, so the order rule is doing real work);
Zoom = clips 80 / 84 / 156 -> iids 232986575 / 232986953 / 232992818. The block renders for both sides; links decode back to
"iid eq N".
**NOT tested:** (1) anything needing Synergy's login -- the built-in browser was signed out and Claude doesn't enter the
password; (2) that several plays can be joined as `iid eq A or iid eq B` in one playlist (the "watch N plays" link on the
game row). One play per link is the form Synergy itself emits. If the combined link opens empty, change `_pcs_watch` in 87
to link the game row to the first play only; (3) that the events API `iid` equals the page's iid (strongly implied by 46's
own use of `eventIid`, not seen).
**To get it live:** run parser_models (fetches the ids, up to 15 games), then parser_brief. Leftover:
`Claude outputs/syn_example_plays.json` (the example page's 216 iids + descriptions, used for the test).

**11/22 (afternoon, requested):** Play call summary -- the per-play "Video" column and "Watch ->" links are gone, and the opponent's
name is plain text. The link is now on the words **"watch N plays in Synergy"** in each game row (same combined playlist);
without play ids that spot links to the game's breakdown page ("open the game in Synergy"). Also fixed: a clip with no half
printed "nan" in the When column (now "--"). Corey's run on 11/22 already had play ids for North Central (10 plays) and the
combined link was used from the real brief.


## 2026-11-22 -- "watch all N plays (M games)" on each Play call summary row
Corey tested a 15-play link spanning Elmhurst@Hope, Franklin@Hope and Hope@NorthCentral in Synergy: cross-game `iid eq A or iid eq B` playlists WORK. 87 `_pcs_body` now starts each expanded row with an "All games" line holding one link to every play (shown only with plays from 2+ games). The per-game links are unchanged. Not seen in a real run yet.


## 2026-11-22 -- TEAM COMPARISON is three cards
Requested: no "Expected here" card, "What decides it" -> "Biggest of Four Factors", no "Where we gain" card, more information on each. Now: Biggest of Four Factors (adds the opponent player the factor runs through via `_wm_face`, and the other three factors' PPG), What we do better / What they do better (each adds the next two season-average edges). The expected score still prints in the detail. The table's own "What decides it" column header is unchanged. Not seen in a real run yet.


## 2026-11-22 -- the opponent's header, recent results and starters are one block
Requested: drop the "Scouting the opponent" line from the team divider (`divider` hides that sub-line; ANALYSIS_MODE still matches on it first); no "<OPP> RECENT RESULTS" header (`section(..., bare=True)` -- only when the brief is not on last season's numbers, where the header says the games are from last year); no "<OPP> - ROSTER" header: `_ros_sec` prints a "Starters" label in the lineup cards' own `lc-lab` style (it carries the roster footnote) straight above the five-starter strip. Opponent only -- our own roster keeps its header. With no header bars `_sb_collapse` has nothing to wrap, so all three read as one always-visible block. Not seen in a real run yet.
11/22 (later): the same treatment applies to OUR roster -- no "UW-WHITEWATER - ROSTER" header bar, a "Starters" label above the strip, and the divider's "Our own personnel, offense and week" sub-line is hidden. The page break before our divider stays.


## 2026-11-22 -- CONFIRMED BUG (fixed): the Hope headshots from athletics.hope.edu were never fetched
The 14:58 brief log: `[roster site] Hope Flying Dutchmen: 17 player(s) from athletics.hope.edu (saved page)` and no "N photo(s)", `uww_player_image_sources.csv` empty for Hope, "Opponent headshots: 1 found, 15 missing". The roster TABLE worked; the photos did not. 82 looked for each headshot in the player's PROFILE page og:image, but Sidearm's og:image is the site logo (the saved page has `<meta name="og:image">` with no content), and a bare `except: continue` hid it. The headshots are on the roster page itself: `<img data-src="/images/2026/11/3/Miller_Brady.jpg?width=80" alt="Brady Miller - View Profile">`. 82 now reads them from there (17 of 17 parse from the saved page), fetches them at `?width=400&quality=90` (then the page's own URL, then the bare path), and prints the first three fetch errors instead of swallowing them. The profile og:image step stays as a fallback. Not seen in a real run: this shell cannot reach hope.edu.


## 2026-11-22 -- "<OPP> OFFENSE" and a new "<OPP> DEFENSE" section (5 cards)
Requested: rename HOW <OPP> RUNS OFFENSE to "<OPP> OFFENSE"; create "<OPP> DEFENSE" with 5 cards, one of them the HOW <OPP> GUARDS SCREENS section. 87: the GUARDS SCREENS block is now the defense section (same position in the brief, before WHAT TO PLAY). Cards (`_def_cards`, no possession counts in the text): Base defense (`uww_opp_defense` + `uww_defense_by_situation`), Pressure, Screens (the old headline + their ball-screen coverage; the screen tables, defender tables and film cards are unchanged behind "Show the detail"), Points allowed (PPP, turnover and foul rate, best / worst situation from the opponent's own defensive clips -- possession_side Defense, side Opponent), Who closes it down (steals + blocks a game from `uww_defensive_roles`, 2+ games). Cards with no data drop out; fewer than 2 prints none. Tested against the real CSVs (all five render for Hope); full brief not rebuilt yet. Our own side has no defense section (not asked).
11/22 (later): the same for us -- "HOW WE RUN OFFENSE" is "UW-WHITEWATER OFFENSE" and `_our_def_section()` (87, right after it) adds "UW-WHITEWATER DEFENSE" with the same five cards, from OUR defensive clips (side UWW, possession_side Defense, this season): base defense by situation, pressure, screens (the "UWW defense" rows of uww_screen_coverage_summary -- only a handful tagged so far, flagged thin), points allowed, and who closes it down (current roster only, since uww_defensive_roles also holds last season's players). No screen tables behind it -- we have no "how we guard screens" section. ANALYSIS_MODE drops it (title matches WHITEWATER). Tested against the real CSVs; not seen in a brief yet.


## 2026-11-22 (evening) -- starters, five-man units and 3-man combos are ONE card, both teams
Requested: all three in the overall section (Starters, then Five-man units, then 3-man combos subsections), and no ⓘ after "Starters". 87: `_roster_card` opens the card with a "Starters" `lc-lab` inside it and ends with a marker chunk (`_RC_END`); the lineup blocks call `_open_or_join_card()`, which takes that marker back and carries on in the same card instead of opening a second one (the page_break() before each lineup block is gone, since it would have sat between them; our block also had a stray duplicate `<div class="card">`, now gone). The roster footnote moved from the "Starters" label to the "Full roster" bar (`_ros_fn`). A preseason / opener brief's two roster copies end in `<!--/NS-->`, so those keep the old separate lineup card. Not seen in a real brief yet -- check the HTML for balanced divs if the layout looks off.
11/22 (evening): spacing -- `details.rosdet` has its own margin, and the label / sub-heading spacing rules in the CSS (next to `.lc-lab`) also cover a label under cards, a note or a table, a `.pc-sub` under a table or bar, and a section's first card or bar under its headline. CSS only.


## 2026-11-22 -- Offense sections: two rows of cards, WHAT TO PLAY folded in

**CONFIRMED CHANGE (requested:** "Hope Offense ... 2 rows of cards. First row Motion, Plays, Actions. Second row
BLOB/SLOB, Tempo, What they're good at, What they struggle with. What to Play Hope In should not be its own
section.") `87` `_off_cards(side)` now returns two `lcards` rows (3 + 4). The two new cards use the old WHAT TO PLAY
data (`_pf_opp` / `_pf_uww`: PPP by defense family, pressure's effect on turnovers) plus best/worst set, action and
clock. The section itself is off unless `BRIEF_WHAT_TO_PLAY_SECTION = True`. Applies to both teams' offense sections.
Not seen in a real run yet; a failure in the new cards prints `[offense cards] ... skipped` and leaves the other five.

**11/22 (later) -- the bullets above the offense table are gone, and the defense table moved.** Requested: keep "How they
score against each defense" in the Hope offense details; the bullets "should be in the cards". `_off_cards` now folds
them in: the formation bullets become a "By formation -- 41: 41 Motion most (36%, 0.62 PPP) ..." line on the Plays card;
the BLOB / SLOB bullets ("BLOB most run: BLOB Motion (22%, 1.00 PPP)", "SLOB: no play call tagged yet") join that card's
note; the two "most successful" bullets were already the Plays / Actions cards' "Most successful" lines (same source
text). The list is no longer printed (`BRIEF_OFFENSE_BULLETS = True` brings it back). The WHAT TO PLAY block still builds
its table + notes into `_DFAM_CHUNKS`, printed at the top of the opponent offense's "Show the full table" details.
Not seen in a real run yet.

**11/22 -- TRIGGER & SCREENER READS section removed** (requested). Same data already sits on the Actions card (team
Ball handler / Screener line) and each player's roster card (`_reads_of`, top 3 reads per player).
`BRIEF_TRIGGER_SECTION = True` brings it back.

**11/22 -- All-keys table has a 'Why this score' column** (requested): rebuilds 83's priority parts (source points, edge size x40, data x15, instruction/description) per key and notes any other adjustment (e.g. the small-sample scaling) so the parts sum to the printed score.

**11/22 (later) -- All-keys table is expandable rows** (requested, replacing the extra column): pcs-r rows like the play-call summary -- key / score / area; open one for its reasoning, 'Why N' parts and source.

**11/22 -- GAMES replaces ADD_GAMES / BANK_GAMES / EXTRA_GAMES in parser_models' first cell** (requested). One list; `_pm_split_games` (00, called where run_parser stores its options) sorts each entry: FastScout link / "<m>_<d>_<yy> a @ b" name -> ADD_GAMES, 24-char Synergy ID or dict with synergy_id / fastscout_url -> BANK_GAMES, dict with "opponent" -> EXTRA_GAMES. Nothing downstream changed, and the three old option names still work (merged), so parser_brief's EXTRA_GAMES = None is untouched. Reload parser_models from disk in JupyterLab.

**11/23 -- Synergy two-factor prompt in a quiet run.** The 11/23 04:22 models run asked for an emailed code four times (game lookup, play ids, two frame-capture logins), each waiting 5 min, and the prompt was only in the log: `[synergy-login] Synergy emailed...` was not in quiet_show. Now it is (models + tagging), and after one sign-in ends with no code the rest of that run's sign-ins are skipped (`_SYNERGY_NO_CODE_THIS_RUN`, reset per run; `SYNERGY_MFA_RETRY_IN_RUN = True` undoes it). Open: Synergy still challenges every sign-in, so the remembered-device cookie isn't being kept (frame capture, 46 line ~705, launches its own throwaway browser, not the saved profile).
