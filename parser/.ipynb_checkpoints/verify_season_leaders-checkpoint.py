#!/usr/bin/env python3
"""
Season Leaders audit -- run after every parser run, from the app's repo root
(expects ./data/*.csv). Exits non-zero if any check fails.

Checks:
  1. Every played game in uww_schedule reconciles to uww_pbp_box_score
     (catches game_date_for() collapsing rematches onto the first meeting).
  2. uww_pbp_box_score "games" per player == real schedule meetings
     (catches nunique(opponent) being used as a game count).
  3. Team minutes per game ~= 200 (5 x 40) on both sides
     (catches the stint-clock inflation).
  4. No unclassified-PBP junk strings leaking in as player names.
  5. Opponent AST/STL/BLK denominators use the player's own games played.
"""
import re, sys, os
import pandas as pd

DATA = os.environ.get("DATA_DIR", "data")
fails = []
def check(ok, msg):
    print(("  PASS  " if ok else "  FAIL  ") + msg)
    if not ok:
        fails.append(msg)

def load(n):
    p = os.path.join(DATA, f"{n}.csv")
    return pd.read_csv(p) if os.path.exists(p) else pd.DataFrame()

MONTHS = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
def sched_date(d, start_year=2025):
    m = re.match(r"^\w{3},\s+(\w{3})\s+(\d+)$", str(d).strip())
    if not m:
        return None
    mo, dy = MONTHS[m.group(1)], int(m.group(2))
    return f"{start_year if mo >= 8 else start_year + 1}-{mo:02d}-{dy:02d}"

sched  = load("uww_schedule")
box    = load("uww_pbp_box_score")
prof   = load("uww_player_profiles")
prior  = load("uww_opponent_prior_games_pbp")

uww = sched[sched["team"].astype(str).str.contains("Whitewater", case=False, na=False)].copy()
played = uww[uww["outcome"].notna()].copy()
played["gd"] = played["date"].apply(sched_date)

print("\n[1] box score reconciles to schedule finals")
side = box.groupby(["game_date", "team"])["PTS"].sum().reset_index()
mine = side[side["team"] == "UW-Whitewater"].set_index("game_date")["PTS"]
theirs = side[side["team"] != "UW-Whitewater"].groupby("game_date")["PTS"].sum()
missing = []
for _, r in played.iterrows():
    if r["gd"] not in mine.index:
        missing.append(f'{r["gd"]} {r["opponent"]}')
        continue
    got = (int(mine[r["gd"]]), int(theirs.get(r["gd"], 0)))
    want = (int(r["team_score"]), int(r["opponent_score"]))
    check(got == want, f'{r["gd"]} {r["opponent"][:26]:26} schedule {want[0]}-{want[1]} vs box {got[0]}-{got[1]}')
check(not missing, f"every played game present in box score (missing: {missing or 'none'})")

print("\n[2] per-player game counts match real schedule meetings")
meet = played["opponent"].value_counts().to_dict()
w = box[box["team"] == "UW-Whitewater"].copy()
w["real"] = w["opponent"].map(meet).fillna(1)
per = w.groupby("player").agg(app=("opponent", "nunique"), real=("real", "sum"))
bad = per[per["app"] != per["real"]]
check(bad.empty, f"nunique(opponent) == real games for all players ({len(bad)} mismatched)")
if not bad.empty:
    print(bad.head(5).to_string())

print("\n[3] team minutes ~200 per game")
for label, df, tcol in [("UWW box", box, "team")]:
    if "MIN" in df.columns:
        g = df.groupby(["game_date", tcol])["MIN"].sum()
        off = g[(g < 150) | (g > 260)]
        check(off.empty, f"{label}: all team-games within 150-260 total min ({len(off)} outliers)")
        if not off.empty:
            print(off.head(8).to_string())

print("\n[4] no unclassified PBP text leaking in as players")
PAT = re.compile(r"Commits|Turnover|Jump Ball|Subs In|Subs Out|Timeout|Rebound$", re.I)
for name, df, col in [("box", box, "player"), ("profiles", prof, "name"), ("prior_pbp", prior, "player")]:
    if df.empty or col not in df.columns:
        continue
    junk = sorted({p for p in df[col].dropna().unique() if PAT.search(str(p))})
    check(not junk, f"{name}: no junk player names ({junk[:4] or 'none'})")

print("\n[5] opponent rate stats use each player's own games played")
if not prior.empty:
    upc = uww[uww.get("Upcoming", "No").astype(str).str.strip().str.lower() == "yes"]
    if not upc.empty:
        full = str(upc.iloc[0]["opponent"])
        short = next((t for t in prior["team"].dropna().unique() if str(t) in full or full.startswith(str(t))), None)
        if short:
            own = prior[prior["team"] == short]
            team_g = own["game_date"].nunique()
            pg = own.groupby("player")["game_date"].nunique()
            partial = pg[pg < team_g]
            check(partial.empty,
                  f"{short}: all players appeared in all {team_g} games "
                  f"({len(partial)} played fewer -> their AST/STL/BLK per-game are understated)")
            if not partial.empty:
                print(partial.sort_values().head(6).to_string())

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
