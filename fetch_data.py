"""Pull weekly scores for a public ESPN fantasy football league into data.json."""
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
    scores = {}
    for m in league.box_scores(week=wk):
        for side in ("home", "away"):
            team = getattr(m, f"{side}_team")
            if team and hasattr(team, "team_id"):  # skip byes
                scores[str(team.team_id)] = round(float(getattr(m, f"{side}_score")), 2)
    weeks.append({"week": wk, "scores": scores})

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
