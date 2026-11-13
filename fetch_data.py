"""Pull weekly scores and matchups for a public ESPN fantasy football league into data.json."""
import json
from datetime import datetime, timezone

from espn_api.football import League

LEAGUE_ID = 104163
YEAR = 2026

league = League(league_id=LEAGUE_ID, year=YEAR)

# Weeks 1 through the last completed regular-season week.
last_reg_week = league.settings.reg_season_count
completed = min(league.current_week - 1, last_reg_week)

teams = [{"id": str(t.team_id), "name": t.team_name} for t in league.teams]

weeks = []
for wk in range(1, completed + 1):
    scores, matchups = {}, []
    for m in league.box_scores(week=wk):
        ids = []
        for side in ("home", "away"):
            team = getattr(m, f"{side}_team")
            if team and hasattr(team, "team_id"):  # skip byes
                tid = str(team.team_id)
                scores[tid] = round(float(getattr(m, f"{side}_score")), 2)
                ids.append(tid)
        if len(ids) == 2:
            matchups.append(ids)
    weeks.append({"week": wk, "scores": scores, "matchups": matchups})

data = {
    "leagueName": league.settings.name,
    "season": YEAR,
    "updated": datetime.now(timezone.utc).isoformat(),
    "teams": teams,
    "weeks": weeks,
}

with open("data.json", "w") as f:
    json.dump(data, f, indent=1)

print(f"Saved {len(weeks)} completed weeks for {len(teams)} teams.")

# Sanity check: compare our W-L-T (head-to-head + top-5 bonus) with ESPN's standings.
mine = {t["id"]: [0, 0, 0] for t in teams}
for wk in weeks:
    vals = sorted(wk["scores"].values(), reverse=True)
    if not vals:
        continue
    cutoff = vals[min(4, len(vals) - 1)]
    for tid, s in wk["scores"].items():
        mine[tid][0 if s >= cutoff else 1] += 1
    for a, b in wk["matchups"]:
        sa, sb = wk["scores"][a], wk["scores"][b]
        if sa > sb:
            mine[a][0] += 1; mine[b][1] += 1
        elif sa < sb:
            mine[b][0] += 1; mine[a][1] += 1
        else:
            mine[a][2] += 1; mine[b][2] += 1
for t in league.teams:
    espn = [t.wins, t.losses, t.ties]
    if mine[str(t.team_id)] != espn:
        print(f"CHECK: {t.team_name} calculated {mine[str(t.team_id)]} vs ESPN {espn}")
