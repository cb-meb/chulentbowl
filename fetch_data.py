"""Pull weekly scores and matchups for a public ESPN fantasy football league into data.json,
and simulate playoff odds as of each completed week."""
import json
from datetime import datetime, timezone

import numpy as np

LEAGUE_ID = 104163
YEAR = 2026
PLAYOFF_TEAMS = 6   # teams that make the playoffs
BYES = 2            # top seeds that get a first-round bye
BONUS_N = 5         # top weekly scorers who earn a bonus win
SIMS = 10000        # simulated seasons per week
PRIOR_WEEKS = 4     # how strongly early-season team averages are pulled toward the league average


def official_state(weeks, upto, tids):
    """Official win points (head-to-head + bonus, ties = half) and points for through `upto` weeks."""
    wins = {t: 0.0 for t in tids}
    pf = {t: 0.0 for t in tids}
    for wk in weeks[:upto]:
        vals = sorted(wk["scores"].values(), reverse=True)
        if not vals:
            continue
        cutoff = vals[min(BONUS_N - 1, len(vals) - 1)]
        for tid, s in wk["scores"].items():
            pf[tid] += s
            if s >= cutoff:
                wins[tid] += 1
        for a, b in wk["matchups"]:
            sa, sb = wk["scores"][a], wk["scores"][b]
            if sa > sb:
                wins[a] += 1
            elif sa < sb:
                wins[b] += 1
            else:
                wins[a] += 0.5
                wins[b] += 0.5
    return wins, pf


def simulate(weeks, schedule, upto, tids, last_reg, seed):
    """Probability each team finishes in each place, as of `upto` completed weeks."""
    idx = {t: i for i, t in enumerate(tids)}
    T = len(tids)
    w0, pf0 = official_state(weeks, upto, tids)
    W = np.array([w0[t] for t in tids])
    PF = np.array([pf0[t] for t in tids])

    scores = np.array([[weeks[j]["scores"][t] for t in tids] for j in range(upto)])
    mean_all, sd_all = scores.mean(), scores.std(ddof=1)
    mean_i = scores.mean(axis=0)
    sd_i = scores.std(axis=0, ddof=1) if upto >= 2 else np.full(T, sd_all)
    wn = upto / (upto + PRIOR_WEEKS)
    mu = wn * mean_i + (1 - wn) * mean_all
    sd = np.maximum(wn * sd_i + (1 - wn) * sd_all, 1.0)

    rng = np.random.default_rng(seed)
    wins = np.tile(W, (SIMS, 1))
    pf = np.tile(PF, (SIMS, 1))
    for wk in range(upto + 1, last_reg + 1):
        pairs = schedule[wk]
        sc = np.clip(rng.normal(mu, sd, (SIMS, T)), 0, None)
        pf += sc
        for a, b in pairs:
            ia, ib = idx[a], idx[b]
            wins[:, ia] += sc[:, ia] > sc[:, ib]
            wins[:, ib] += sc[:, ib] > sc[:, ia]
        ranks = sc.argsort(axis=1).argsort(axis=1)
        wins += ranks >= T - BONUS_N  # top scorers of the week get the bonus win

    order = np.argsort(-(wins * 100000 + pf), axis=1, kind="stable")
    probs = np.zeros((T, T))
    for p in range(T):
        probs[:, p] = np.bincount(order[:, p], minlength=T) / SIMS
    return {t: [round(float(x), 4) for x in probs[idx[t]]] for t in tids}


def main():
    from espn_api.football import League

    league = League(league_id=LEAGUE_ID, year=YEAR)

    last_reg_week = league.settings.reg_season_count
    completed = min(league.current_week - 1, last_reg_week)

    teams = [{"id": str(t.team_id), "name": t.team_name} for t in league.teams]
    tids = [t["id"] for t in teams]

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
        "playoffTeams": PLAYOFF_TEAMS,
        "byes": BYES,
        "teams": teams,
        "weeks": weeks,
        "odds": [],
    }

    # Playoff odds: needs the full regular-season schedule.
    try:
        schedule = {wk: set() for wk in range(1, last_reg_week + 1)}
        for t in league.teams:
            for i, opp in enumerate(t.schedule):
                wk = i + 1
                if wk <= last_reg_week:
                    oid = getattr(opp, "team_id", opp)
                    schedule[wk].add(tuple(sorted((str(t.team_id), str(oid)))))
        for w in range(1, completed + 1):
            data["odds"].append({"week": w, "p": simulate(weeks, schedule, w, tids, last_reg_week, 1000 + w)})
        print(f"Simulated playoff odds for {len(data['odds'])} weeks.")
    except Exception as e:  # keep the rest of the site working if the simulation fails
        data["odds"] = []
        print(f"WARNING: playoff odds skipped: {e!r}")

    with open("data.json", "w") as f:
        json.dump(data, f, indent=1)

    print(f"Saved {len(weeks)} completed weeks for {len(teams)} teams.")

    # Sanity check: compare our W-L-T (head-to-head + top-5 bonus) with ESPN's standings.
    mine = {t: [0, 0, 0] for t in tids}
    for wk in weeks:
        vals = sorted(wk["scores"].values(), reverse=True)
        if not vals:
            continue
        cutoff = vals[min(BONUS_N - 1, len(vals) - 1)]
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


if __name__ == "__main__":
    main()
