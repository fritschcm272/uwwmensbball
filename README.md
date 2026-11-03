# parser_lib

The code of `parser_nb.ipynb`, one file per notebook section (numbered in notebook order).

* Keep this folder **next to `parser_nb.ipynb`** (the notebook runs from its own folder).
* Each notebook section cell holds only its **settings**, then runs its file with `run_section("<file>")`.
  The file runs inside the notebook, exactly as if its code were still in the cell: every function and table it
  creates is available to the cells after it.
* To change a **setting**: edit it in the notebook cell. To change **how something works**: edit the `.py` file here,
  then rerun that notebook cell (no restart needed -- the file is read fresh every time).
* Errors point to the file and line in here (e.g. `parser_lib\50_player_tracking.py, line 812`).

## Tests to send back

Some features are **tested on your own player checks first** and only switch on in Player tracking if the test passes.
Each test cell prints a short report and saves files in `inputs\_tracking\`. To show Claude the results, send:
**(1)** the printed lines (copy the cell output), and **(2)** the files listed below.

| Notebook cell | Code | What it tests | Send these files | Turns on in tracking when |
|---|---|---|---|---|
| Outfit check (test) | `50c_outfit_check.py` | Can Fashion-CLIP tell players from referees / coaches / bench / fans by their clothes? | `outfit_check_test.json`, `outfit_check_scores.csv` | flagged boxes are really non-players >= `OUTFIT_MIN_PRECISION` (90%) of the time and it catches >= `OUTFIT_MIN_RECALL` (25%) of them (`TRACK_OUTFIT_CHECK = "auto"`) |
| Re-ID check (test) | `50d_reid_check.py` | Does an unnamed player look like the player you checked in the same game? (OSNet vs DINOv2) | `reid_check_test.json`, `reid_check_results.csv` | its picks are right >= `REID_MIN_PRECISION` (80%) of the time on >= `REID_MIN_COVERAGE` (15%) of the question boxes (`TRACK_REID_NAMES = "auto"`) |
| Jersey-number reader test (with `JERSEY_CROP_STYLE = "compare"`) | `48_...`, `49_...` | Fixed chest crop (`trained`) vs shoulders-to-hips crop (`trained_pose`) | the printed lines, including both per-number tables | the better reader wins automatically |

### How to read the printed reports

**Outfit check.** `AUC` = how well the score separates non-players from players (0.5 = coin flip, 1.0 = perfect).
The table lists score cutoffs: *boxes flagged* at that cutoff, how many of them *really are not players*, the share
of all non-players *caught*, and *real players lost*. `PASSED` / `NOT PASSED` says whether tracking will use it.

**Re-ID check.** One line per model: `right X% overall` (vs `guessing at random among the candidates`), then the
smallest *margin* (how much the best-matching player beat the second best) at which its picks were right >= 80%, and
on how many boxes. `CHOSEN: osnet` (or `dinov2`) = tracking will use it; names it gives show as **re-id match** in the
app's Player Number Tracking metrics, so your later checks measure it like every other naming method.

`reid_check_results.csv` has one row per question box: `model, game, clip_key, frame_file, side, true_name, picked,
right, margin, true_has_references, candidates` -- `true_has_references = False` means you hadn't checked that player in
the reference half of that game, so the model couldn't have known him.

### If a test can't run
* `transformers was installed. RESTART THE KERNEL` -> restart the kernel (Kernel > Restart) and run again.
* `boxmot is not installed` -> run `%pip install boxmot` in a new cell, restart the kernel, run again
  (or set `REID_MODELS = ["dinov2"]` to test only the model you already have).
* Any other error -> send the printed lines; nothing in tracking changes when a test fails.

## Tagging in the app (instead of Synergy's Title field)

1. **Frame capture** captures every game's clips (the upcoming opponent's first: `VISION_CAPTURE_FIRST`).
2. **Play calls** turns every captured clip into a play, even when its game isn't in `uww_plays.csv` (`PLAY_CALLS_FROM_FRAMES`).
   Clips with no tag are marked `Untagged` and stay out of the Title-based tables until they're tagged.
3. **Play review** cell builds a **Film Tagging** batch per game (`PLAY_TAG_PER_GAME` clips, in game order).
   Commit and push the data folder.
4. In the app, **Analytics > Film Tagging**: pick the game, watch each play, pick each field
   (✓ = the automatic answer), type a new answer with "other", add your name, **Save**.
5. Next parser run: the saved answers are the clips' tags in every play-call / defense / situation / game-plan table
   (`PLAY_CALLS_USE_APP_TAGS`), they train the Tag model, and the game's next batch appears.

The run prints `App tags: N clip(s) tagged in the app ...` (play-calls cell) and a per-game progress list
(`Film Tagging -- tagging progress by game`). Games still in `uww_plays.csv` keep their coach Titles; a field a coach
corrects in the app overrides that Title's field.

## Frame archive (disk space)

`_vision_frames` holds ~3 GB of tracking pictures per game. The **Frame archive** cell (before Cleanup) packs a FINISHED game's
tracking frames into one small video per clip (~10-20x smaller) and deletes the pictures, except frames with a coach check and
court-calibration frames. A game is finished when it isn't part of the current run (`FRAME_ARCHIVE_OUTSIDE_RUN`: not one of the upcoming opponent's
games or an earlier meeting with them, and not our most recent `FRAME_ARCHIVE_KEEP_RECENT` played game) -- or when it's
tracked, has no open Play review / Film Tagging batch in the app, and is tagged (up to `FRAME_ARCHIVE_MAX_UNTAGGED`
untagged clips allowed). Run it with `FRAME_ARCHIVE_DRY_RUN = True` first.

Nothing else changes: archived frames count as captured (never recaptured), and any step that reads one -- a tracking rerun,
a new review or tagging batch, the export -- unpacks that clip automatically. `FRAME_RESTORE_GAMES` unpacks whole games for good.

### Lean mode (biggest saving)
`FRAME_LEAN = True` (Frame archive cell, end of the notebook): as soon as every clip of a game is tracked, each clip keeps only
its check frame (the player-check picture), coach-check and calibration frames, and a small play video (`<game>/media/`);
the other tracking frames are deleted (~3 GB -> ~150-250 MB a game). Tracking, jersey, court and appearance results are
already saved, so reruns, reviews and Film Tagging keep working; a lean game is never recaptured. To rebuild a game in full,
delete its `_lean.json` and `media/` folder and run Frame capture for it. Dry run first (`FRAME_ARCHIVE_DRY_RUN`).

---

## Bringing a new game into the app — worked example: Carroll vs. Beloit (11/12/25)

FastScout box score for this game:
<https://fastscout.fastmodelsports.com/teams/emBh5s30TA-k_E211KwGIQ/games/9I36BUL_Rxa37scfLt6K5g/boxscore?league=NCAAB-III&season=25>

All settings below are in `parser/parser_nb.ipynb`. Save the notebook (Ctrl+S), **close it without saving again**, then run
the job notebook named in each step. After every run, commit and push the `data` folder so the app updates.

### Step 0 — check the game's files and its name

1. The parser needs the game's play-by-play and video-tagging pages in `parser\inputs`. For this game they are already there:
   * `11_12_25 Beloit Buccaneers @ Carroll (WI) Pioneers_pbp.html`
   * `11_12_25 Beloit Buccaneers @ Carroll (WI) Pioneers_video.html`

   For a game that isn't there yet, open the box score link on FastScout and save its play-by-play and video pages the
   same way the others were saved, with the same naming.
2. **The game's name** is the part of those file names before `_pbp`: **`11_12_25 Beloit Buccaneers @ Carroll (WI) Pioneers`**
   (`M_D_YY Away @ Home`). Every setting below uses this exact text.

### A) Film Tagging (coaches tag the plays in Analytics > Film Tagging)

| Setting (cell) | Set it to | Why |
|---|---|---|
| `VISION_ONLY_GAME` (frame capture, cell 108) | `"11_12_25 Beloit Buccaneers @ Carroll (WI) Pioneers"` | Frame capture normally takes only each side's 2 most recent games (`VISION_RECENT_GAMES`) and one game at a time (`VISION_WAIT_FOR_COACHES`). Naming a game captures that game only. |
| `VISION_EXPORT_AUTO` (cell 108) | `True` (already) | Exports the game through Synergy Editor on this laptop into `F:\Backups\uwwmensbball_tracking` (3–5 GB, up to `VISION_EXPORT_WAIT_MIN` = 90 min). |
| `PLAY_TAG_PER_GAME_OTHER` / `PLAY_TAG_OTHER_OFFENSE_FIRST` (cell 133) | leave as is | An opponent's game: the first batch is every play of the scouted team's (Carroll's) offense, then the rest after that batch is saved. |

1. Set `VISION_ONLY_GAME` as above, then run **`parser_tagging`**.
2. Check the log (`parser\inputs\_logs\tagging_*.log`, or the lines printed in the notebook):
   * `Frame capture ONLY '11_12_25 Beloit ...'` — the game was found.
     * If it says `no clip page found`, open the game in Synergy and paste its address into
       `VISION_PLAYLIST_URLS = [("11_12_25 Beloit Buccaneers @ Carroll (WI) Pioneers", "<address bar URL>")]`.
   * `Film Tagging: 2025-11-12 Beloit@Carroll(WI): N clip(s) to tag` — the batch is built.
   * `left out -- not part of this run` — Film Tagging only builds batches for the upcoming opponent's games and our most
     recent game (`PLAY_TAG_RUN_ONLY`). Carroll is the upcoming opponent, so this game qualifies. For a game that doesn't,
     set `PLAY_TAG_RUN_ONLY = False` (cell 133) for that run.
3. **Set `VISION_ONLY_GAME = None` again**, or every later run captures only this game.
4. Commit and push `data`. In the app: **Analytics > Film Tagging** → pick the game. 20 plays a page, **Save** each page.
5. After the coaches save, run **`parser_tagging`** again for the next batch.

Nothing here changes the games already in Film Tagging.

### B) Player Number Tracking (who is on the floor, by jersey number)

1. **List the game** in `PLAYER_TRACKING_GAMES` (cell 108):
   ```python
   PLAYER_TRACKING_GAMES = ["11_7_25 Carroll (WI) Pioneers @ Washington-St. Louis Bears",
                            "11_12_25 Beloit Buccaneers @ Carroll (WI) Pioneers"]
   ```
   * Only listed games are tracked, get starters and player checks, and show in the app's Player Number Tracking.
   * Listed games get 8 tracking frames a second (`VISION_TRACK_FPS_TRACKING = 8`).
   * Remove the WashU game from the list to work on Beloit only.
2. **Decide whether it also goes into Film Tagging:** `PLAY_TAG_INCLUDE_TRACKING_GAMES` (cell 133). It is `True` now, which
   puts listed games in Film Tagging too; `False` keeps them out.
3. **Reset the settings left over from the WashU game.** They apply to **every** listed game:
   * `TRACK_HOLD_AT_CLIP = None` (cell 120). It is `8` now, which stops tracking and checks after clip 8.
   * `PLAY_REVIEW_RECHECK_CLIPS = []` (cell 133). It is `[1]` now, which re-checks clip 1 of each listed game.
4. **Capture the game:** set `VISION_ONLY_GAME` as in A), run **`parser_models`**, then set it back to `None`.
5. **Court calibration** (Carroll's home gym, if it isn't calibrated yet): the run sends it to the app.
   * In the app: **Analytics > Court Calibration** → click the court points → save.
   * Run **`parser_models`** again. The log's `[court]` lines should say every frame is on the court.
6. **Starters check:** in the app, **Analytics > Player Number Tracking** → the game's first clip → name all ten starters →
   save → run **`parser_models`**. Until the starters are saved, only the first clip is tracked and the game gets no other
   player checks.
7. **Player checks:** each `parser_models` run builds the next batch. Check the players in the app, save, run
   **`parser_models`**, and repeat. The `[scorecard]` and `jersey vote (` lines in the log show how tracking is doing.

#### Options for how the checks come (all in `parser_nb.ipynb`)

| What you want | Settings |
|---|---|
| **20 different clips** per batch (the normal way) | `PLAY_REVIEW_PLAYS_PER_GAME = 20`, `PLAY_REVIEW_PICK = "next"` (the next unchecked clips in game order; `"random"` = a random set, `PLAY_REVIEW_SEED` = the same random set again), `PLAY_REVIEW_PICTURES = 1` (the frame with the most players; `2` = start + end) |
| **3 frames of the same play** (e.g. re-check that clip 1 carries the right players all the way through) | `PLAY_REVIEW_RECHECK_CLIPS = [1]`, `PLAY_REVIEW_RECHECK_FRAMES = 3` (start / middle / end), `PLAY_REVIEW_RECHECK_SINCE = "<now, UTC, e.g. 2026-11-04T15:00:00+00:00>"` (the clip stops coming back once you save a check of it after this time), `PLAY_REVIEW_RECHECK_GAP_S = 3.0` (new moments at least 3 s from frames already checked), `PLAY_REVIEW_RECHECK_REUSE = False` (`True` = reuse a frame you already checked). These come first in the batch. |
| **Stop moving forward** (e.g. a substitution is coming and you want to get the first clips right) | `TRACK_HOLD_AT_CLIP = 8` (no tracking or checks past clip 8; re-checks still come). `None` = move on. |
| **How fast a new game is tracked** after the starters are saved | `TRACK_NEW_GAME_PACE` (add it to cell 120 if you change it; default `"One clip at a time"`). Options: `"40 clips at a time"`, `"All Offensive Clips"`, `"All Clips"`. |
| **One game only** in the play review | `PLAY_REVIEW_ONLY_GAME = "Beloit"` (part of the game name); `None` = every listed game |

Leave these alone: the tracking files live in `TRACK_DIR` (`F:\Backups\uwwmensbball_tracking\_tracking`), and
`TRACKING_RESET_ID` must not be changed. Changing it starts all tracking over.
