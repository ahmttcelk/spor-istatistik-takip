"""Probe publicly reachable ESPN feeds. No credentials or alerts involved."""
import datetime as dt
import json
import sys
from scripts.check_connections import request_json, SafeError

LEAGUES = {
    "tur.1": ("soccer", "Super Lig"),
    "eng.1": ("soccer", "Premier League"),
    "esp.1": ("soccer", "La Liga"),
    "ita.1": ("soccer", "Serie A"),
    "ger.1": ("soccer", "Bundesliga"),
    "uefa.champions": ("soccer", "Champions League"),
    "nba": ("basketball", "NBA"),
}
BASE = "https://site.api.espn.com/apis/site/v2/sports"

def state(event):
    competitions = event.get("competitions") or [{}]
    status = event.get("status") or competitions[0].get("status", {})
    return status.get("type", {}).get("state", "unknown")

def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    dates = (today-dt.timedelta(days=8)).strftime("%Y%m%d") + "-" + today.strftime("%Y%m%d")
    for league, (sport, label) in LEAGUES.items():
        print("\nLEAGUE " + label, flush=True)
        try:
            base = BASE + "/" + sport + "/" + league
            payload = request_json(base, "/scoreboard", params=None)
            if not isinstance(payload.get("events"), list) or not payload.get("leagues"):
                print("FEED_UNVERIFIED")
                continue
            events = payload["events"]
            print("EVENTS " + str(len(events)))
            live = [e for e in events if state(e) == "in"]
            post = sorted([e for e in events if state(e) == "post"],
                          key=lambda e: e.get("date", ""), reverse=True)
            selected = (live or post)[:1]
            if not selected:
                calendar = payload.get("leagues", [{}])[0].get("calendar") or []
                previous = sorted([d[:10] for d in calendar if isinstance(d, str)
                                   and len(d) >= 10 and d[:10] < today.isoformat()])
                if previous:
                    prior = request_json(base, "/scoreboard",
                        params={"dates": previous[-1].replace("-", "")})
                    earlier = prior.get("events") or []
                    selected = [e for e in earlier if state(e) == "post"][:1]
            if not selected:
                print("NO_IN_PROGRESS_OR_COMPLETED_SAMPLE; PLAYER_SUPPORT_UNVERIFIED")
                continue
            event = selected[0]
            print("SAMPLE " + json.dumps({k:event.get(k) for k in ("id","name","date")}))
            print("STATE " + state(event))
            summary = request_json(base, "/summary", params={"event": event["id"]})
            print("SUMMARY_KEYS " + json.dumps(sorted(summary.keys())))
            box = summary.get("boxscore", {})
            for team in box.get("teams", [])[:1]:
                print("TEAM_STAT_KEYS " + json.dumps([
                    s.get("name") for s in team.get("statistics", [])]))
            players = box.get("players", [])
            print("BOX_PLAYER_GROUPS " + str(len(players)))
            for group in players[:1]:
                for stats in group.get("statistics", [])[:1]:
                    print("PLAYER_LABELS " + json.dumps(stats.get("labels", [])))
                    print("PLAYER_KEYS " + json.dumps(stats.get("keys", [])))
                    rows = stats.get("athletes") or []
                    print("PLAYER_ROW_COUNT " + str(len(rows)))
                    if rows:
                        print("PLAYER_SAMPLE " + json.dumps(rows[0])[:2200])
            rosters = summary.get("rosters") or []
            print("ROSTER_GROUPS " + str(len(rosters)))
            for roster in rosters[:1]:
                print("ROSTER_KEYS " + json.dumps(sorted(roster.keys())))
                entries = roster.get("roster") or []
                if entries:
                    print("ROSTER_STAT_NAMES " + json.dumps(sorted({s.get("name", "") for entry in entries for s in entry.get("stats", [])})))
            print("LIVE_DATA_VERIFIED" if live else "COMPLETED_SAMPLE_ONLY; LIVE_DATA_UNVERIFIED")
        except SafeError as exc:
            print("FEED_UNAVAILABLE " + str(exc))
    print("\nEuroLeague: NOT_VERIFIED; all alerts disabled for this competition.")
    print("No Telegram messages or alerts were sent.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("Unexpected schema; probe stopped safely.")
        sys.exit(1)
