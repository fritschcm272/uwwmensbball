# 68_investigate_why_guarded_catch_and_shoot.py -- code for the notebook section "Why might GUARDED catch-and-shoot jumpers outperform OPEN ones, season-wide? -------------"
# Runs inside the notebook via run_section("68_investigate_why_guarded_catch_and_shoot"); its settings are in that notebook cell.

# --- Why might GUARDED catch-and-shoot jumpers outperform OPEN ones, season-wide? ---------------------------
# Three possible explanations to test: (1) it's just small-sample noise, (2) it's driven by one game/opponent,
# or (3) it's a SHOOTER-QUALITY CONFOUND -- the defense keys on UWW's best shooters (more Guarded attempts from
# good shooters), while lesser shooters get left Open more often, so the two buckets aren't comparing the same
# shooters to begin with.
import math

# CONFIRMED BUG (fixed here): this z-test assumes BOTH a Guarded and an Open catch-and-shoot bucket
# already exist with at least one attempt each -- true "season-wide", but not necessarily true this
# early (e.g. the first game or two might have logged only Guarded looks so far, with zero Open ones,
# or vice versa). contest_all.loc[...].iloc[0] on a bucket with no rows raised "IndexError: single
# positional indexer is out-of-bounds" instead of just saying there isn't enough data yet to compare.
def _bucket_n(contest):
    rows = contest_all.loc[contest_all["contest"] == contest]
    return (int(rows["attempts"].iloc[0]), int(rows["makes"].iloc[0])) if not rows.empty else (0, 0)

guarded_n, guarded_makes_n = _bucket_n("Guarded")
open_n, open_makes_n = _bucket_n("Open")

if guarded_n == 0 or open_n == 0:
    print(f"Not enough catch-and-shoot data yet to compare Guarded (n={guarded_n}) vs. Open (n={open_n}) -- "
          f"need at least one attempt logged in each bucket. Skipping the significance test for now; the "
          f"game-by-game and shooter-quality breakdowns below still run on whatever data exists.")
else:
    p1, p2 = guarded_makes_n / guarded_n, open_makes_n / open_n
    p_pool = (guarded_makes_n + open_makes_n) / (guarded_n + open_n)
    se = (p_pool * (1 - p_pool) * (1 / guarded_n + 1 / open_n)) ** 0.5
    z = (p1 - p2) / se
    p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    print(f"Two-proportion z-test, Guarded ({p1:.1%}, n={guarded_n}) vs. Open ({p2:.1%}, n={open_n}): "
          f"z={z:.2f}, p-value={p_value:.3f}")
    print("(p > 0.05 means this gap is NOT statistically distinguishable from random chance at this sample size)\n")

by_game = (
    catch_and_shoot_all.groupby(GAME_KEYS + ["contest"])
    .agg(attempts=("made", "count"), makes=("made", "sum"))
    .reset_index()
)
by_game["fg_pct"] = (100 * by_game["makes"] / by_game["attempts"]).round(1)
print("Guarded vs. Open catch-and-shoot FG%, broken out by game:\n")
_show(by_game.sort_values(["opponent", "contest"]))

# CONFIRMED BUG (fixed here): normalize_player_name below was actually relying on the SAME-NAMED
# function accidentally left in the global namespace by the `for` loop in the earlier video-tagging
# cell (a `for` loop doesn't create its own scope in Python, so a `def` inside one leaks into module/
# global scope once the loop body has run at least once). That caused two problems, one a crash and one
# silent: (1) if that loop's file list was empty -- e.g. no video-tagging files yet for the first game
# of the season, or none passing the reference_date filter -- normalize_player_name was never defined
# at all, raising "NameError: name 'normalize_player_name' is not defined" right here. (2) even when it
# WAS defined, it only knew the roster of whichever single OPPONENT'S game that loop happened to process
# LAST -- not UWW's own roster, which is what THIS cell actually needs to match UWW player names against
# the season-stats page. That's wrong regardless of whether the loop ran, and would have been silently
# mismatching UWW players against the wrong known-name set any time it didn't happen to crash. Built
# fresh and self-contained here instead, scoped correctly to UWW's own known players across every game.
_uww_known_players = set(pbp_events.loc[pbp_events["team"] == "UW-Whitewater", "player"].dropna().unique())

def normalize_player_name(name):
    if name in _uww_known_players:
        return name
    for p in _uww_known_players:
        if p.casefold() == str(name).casefold():
            return p
    return name

season_3pt = stats[["PLAYER", "3P%"]].copy()
season_3pt["season_3p_pct"] = pd.to_numeric(season_3pt["3P%"].str.rstrip("%"), errors="coerce")
season_3pt["player_norm"] = season_3pt["PLAYER"].apply(normalize_player_name)

cs_long3 = catch_and_shoot_all[catch_and_shoot_all["distance"] == "Long/3pt"].copy()
cs_long3["player_norm"] = cs_long3["player"].apply(normalize_player_name)
cs_long3 = cs_long3.merge(season_3pt[["player_norm", "season_3p_pct"]], on="player_norm", how="left")

quality_by_contest = (
    cs_long3.groupby("contest")
    .agg(attempts=("made", "count"), avg_shooter_season_3p_pct=("season_3p_pct", "mean"))
    .reset_index()
)
quality_by_contest["avg_shooter_season_3p_pct"] = quality_by_contest["avg_shooter_season_3p_pct"].round(1)
print("\nAverage SEASON-LONG 3P% of the shooter taking the shot, by contest level (catch-and-shoot 3s only) -- "
      "tests whether the defense keys on UWW's better shooters, inflating the Guarded bucket's shooter-quality "
      "mix relative to Open:\n")
print(quality_by_contest)
