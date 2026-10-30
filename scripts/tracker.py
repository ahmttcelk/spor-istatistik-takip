"""Private configuration, public data, fail-closed alerts and durable at-most-once delivery."""
import base64
import datetime as dt
import hashlib
import json
import math
import operator
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from cryptography.fernet import Fernet, InvalidToken

UTC = dt.timezone.utc
LEAGUES = {
    "tur.1": ("soccer", "Super Lig"), "eng.1": ("soccer", "Premier League"),
    "esp.1": ("soccer", "La Liga"), "ita.1": ("soccer", "Serie A"),
    "ger.1": ("soccer", "Bundesliga"),
    "uefa.champions": ("soccer", "Champions League"), "nba": ("basketball", "NBA"),
}
OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le,
       "<": operator.lt, "==": operator.eq}
SOCCER = {"goals": "totalGoals", "assists": "goalAssists",
          "shots": "totalShots", "shots_on_target": "shotsOnTarget",
          "corners": "wonCorners", "yellow_cards": "yellowCards",
          "red_cards": "redCards", "fouls": "foulsCommitted",
          "saves": "saves", "offsides": "offsides", "possession": "possessionPct"}
NBA = {"points": "points", "rebounds": "rebounds", "assists": "assists",
       "steals": "steals", "blocks": "blocks", "turnovers": "turnovers",
       "fouls": "fouls", "three_pointers": "threePointFieldGoalsMade-threePointFieldGoalsAttempted"}
TEAM_NBA = dict(NBA, rebounds="totalRebounds")
class SafeError(Exception):
    pass

def http_json(url, token=None, method="GET", body=None, allow404=False):
    headers = {"Accept": "application/json", "User-Agent": "sports-personal-tracker/1"}
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    data = None if body is None else json.dumps(body).encode()
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        req = urllib.request.Request(url, headers=headers, data=data, method=method)
        with urllib.request.urlopen(req, timeout=25) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise SafeError("Beklenmeyen yanit bicimi")
        return payload
    except urllib.error.HTTPError as exc:
        if allow404 and exc.code == 404:
            return None
        raise SafeError("Servis HTTP " + str(exc.code)) from None
    except SafeError:
        raise
    except Exception:
        raise SafeError("Servise ulasilamadi veya yanit okunamadi") from None

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

def cipher_for(secret):
    key = hashlib.sha256(("sports-state-v1:" + secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))

class Store:
    BRANCH = "sports-private-state"
    PATH = "tracker-state.enc"
    def __init__(self, repo, token, encryption_secret, initial_sha):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise SafeError("Depo kimligi gecersiz")
        self.base = "https://api.github.com/repos/" + repo
        self.token = token
        self.cipher = cipher_for(encryption_secret)
        self.initial_sha = initial_sha
        self.sha = None
        self.state = {}
        self.last = ""
    def api(self, path, **kwargs):
        return http_json(self.base + path, token=self.token, **kwargs)
    def load(self):
        branch = self.api("/git/ref/heads/" + self.BRANCH, allow404=True)
        if branch is None:
            self.api("/git/refs", method="POST",
                body={"ref": "refs/heads/" + self.BRANCH, "sha": self.initial_sha})
            self.state = {"version": 1, "fixtures": {}, "delivered": {},
                          "budget": {}, "completed": {}}
            self.save()
            return self.state
        file = self.api("/contents/" + self.PATH + "?ref=" + self.BRANCH, allow404=True)
        if file is None:
            raise SafeError("Kalici kayit eksik; tekrar bildirimi onlemek icin duruldu")
        try:
            encrypted = base64.b64decode(file["content"])
            self.state = json.loads(self.cipher.decrypt(encrypted))
            if self.state.get("version") != 1:
                raise ValueError()
            for key in ("fixtures", "delivered", "budget", "completed"):
                if not isinstance(self.state.get(key), dict):
                    raise ValueError()
            self.sha = file["sha"]
            self.last = canonical(self.state)
        except Exception:
            raise SafeError("Kalici kayit acilamadi; sifirlama ve bildirim yapilmadi") from None
        return self.state
    def save(self):
        plain = canonical(self.state)
        if plain == self.last:
            return
        encrypted = self.cipher.encrypt(plain.encode())
        body = {"message": "Persist encrypted tracker state [skip ci]",
                "branch": self.BRANCH,
                "content": base64.b64encode(encrypted).decode()}
        if self.sha:
            body["sha"] = self.sha
        # A conflicting SHA fails closed. Never retry with a blind overwrite.
        result = self.api("/contents/" + self.PATH, method="PUT", body=body)
        self.sha = result["content"]["sha"]
        self.last = plain

def number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+(\.\d+)?%?", value.strip()):
        result = float(value.strip().rstrip("%"))
    else:
        return None
    return result if math.isfinite(result) else None

def folded(value):
    # Deterministic exact name matching: never guess from a partial player name.
    value = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(c for c in value if not unicodedata.combining(c)).replace("ı", "i").strip()

def load_alerts(raw):
    try:
        alerts = json.loads(raw)
        if not isinstance(alerts, list) or len(alerts) > 30:
            raise ValueError()
        result = []
        ids = set()
        for item in alerts:
            if not isinstance(item, dict):
                raise ValueError()
            if not isinstance(item.get("enabled", True), bool):
                raise ValueError()
            if item.get("enabled") is False:
                continue
            if set(item) - {"id","enabled","league","scope","team_id","team_name",
                            "player_id","player_name","stat","op","threshold"}:
                raise ValueError()
            ident = item.get("id")
            if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", ident) or ident in ids:
                raise ValueError()
            ids.add(ident)
            league = item["league"]
            if league not in LEAGUES:
                raise ValueError()
            scope = item["scope"]
            if scope not in ("team", "player"):
                raise ValueError()
            if not item.get("team_id") and not item.get("team_name"):
                raise ValueError()
            for field in ("team_name", "player_name"):
                if field in item and (not isinstance(item[field], str) or not 1 <= len(item[field]) <= 100):
                    raise ValueError()
            for field in ("team_id", "player_id"):
                if field in item and not re.fullmatch(r"\d+", str(item[field])):
                    raise ValueError()
            if scope == "player" and not item.get("player_id") and not item.get("player_name"):
                raise ValueError()
            available = NBA if league == "nba" else SOCCER
            if item["stat"] not in available or item["op"] not in OPS or number(item["threshold"]) is None:
                raise ValueError()
            if league != "nba" and scope == "player" and item["stat"] in ("corners","possession"):
                raise ValueError()
            result.append(dict(item, threshold=number(item["threshold"])))
        return result
    except Exception:
        raise SafeError("ALERTS_JSON bicimi veya secimi gecersiz; degerler gizlendi") from None

def instant(value):
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return None

def event_state(event):
    status = event.get("status") or (event.get("competitions") or [{}])[0].get("status", {})
    return status.get("type", {}).get("state")

def in_window(event, now, league):
    date = instant(event.get("date"))
    if date is None:
        return False
    return date - dt.timedelta(minutes=15) <= now <= date + dt.timedelta(hours=6 if league == "nba" else 4)

def matches_team(team, alert):
    if alert.get("team_id"):
        return str(team.get("id")) == str(alert["team_id"])
    names = [team.get(k, "") for k in ("displayName", "name", "shortDisplayName")]
    return folded(alert.get("team_name", "")) in [folded(n) for n in names if n]

def find_team(competitors, alert):
    matches = [c for c in competitors if matches_team(c.get("team", {}), alert)]
    return matches[0] if len(matches) == 1 else None

def matches_player(athlete, alert):
    if alert.get("player_id"):
        return str(athlete.get("id")) == str(alert["player_id"])
    return folded(athlete.get("displayName", athlete.get("fullName", ""))) == folded(alert.get("player_name", ""))

def stat_value(stats, key, made=False):
    matches = [s for s in stats if s.get("name") == key]
    if len(matches) != 1:
        return None
    row = matches[0]
    raw = row["value"] if "value" in row else row.get("displayValue")
    if made and isinstance(raw, str) and re.fullmatch(r"\d+-\d+", raw):
        raw = raw.split("-")[0]
    return number(raw)

def metric(summary, alert):
    header = summary.get("header", {})
    competitions = header.get("competitions") or []
    if len(competitions) != 1:
        return None
    comp = competitions[0]
    competitor = find_team(comp.get("competitors", []), alert)
    if competitor is None:
        return None
    team_id = str(competitor.get("team", {}).get("id"))
    stat = alert["stat"]
    nba = alert["league"] == "nba"
    if alert["scope"] == "team":
        if (nba and stat == "points") or (not nba and stat == "goals"):
            return number(competitor.get("score"))
        teams = [t for t in summary.get("boxscore", {}).get("teams", [])
                 if str(t.get("team", {}).get("id")) == team_id]
        if len(teams) != 1:
            return None
        key = (TEAM_NBA if nba else SOCCER)[stat]
        return stat_value(teams[0].get("statistics", []), key, made=(stat == "three_pointers"))
    if not nba:
        groups = [r for r in summary.get("rosters", []) if str(r.get("team", {}).get("id")) == team_id]
        if len(groups) != 1:
            return None
        rows = [r for r in groups[0].get("roster", []) if matches_player(r.get("athlete", {}), alert)]
        if len(rows) != 1:
            return None
        row = rows[0]
        # Unused substitutes must not produce false zero-valued threshold alerts.
        if row.get("didNotPlay") or (row.get("starter") is not True and row.get("subbedIn") is not True):
            return None
        return stat_value(row.get("stats", []), SOCCER[stat])
    groups = [g for g in summary.get("boxscore", {}).get("players", [])
              if str(g.get("team", {}).get("id")) == team_id]
    rows = []
    for group in groups:
        for table in group.get("statistics", []):
            keys = table.get("keys") or []
            key = NBA[stat]
            if key not in keys:
                continue
            index = keys.index(key)
            for row in table.get("athletes", []):
                if row.get("didNotPlay") or not matches_player(row.get("athlete", {}), alert):
                    continue
                values = row.get("stats") or []
                if index >= len(values):
                    continue
                value = values[index]
                if stat == "three_pointers" and isinstance(value, str) and re.fullmatch(r"\d+-\d+", value):
                    value = value.split("-")[0]
                rows.append(number(value))
    return rows[0] if len(rows) == 1 else None

def delivery_key(alert, event_id):
    return hashlib.sha256((alert["league"] + ":" + str(event_id) + ":" + alert["id"]).encode()).hexdigest()

def deliver_once(store, alert, event_id, text, send):
    key = delivery_key(alert, event_id)
    if key in store.state["delivered"]:
        return False
    # Reserve DURABLY before the external side effect. If send times out, DO NOT retry.
    store.state["delivered"][key] = "reserved"
    store.save()
    send(text)
    store.state["delivered"][key] = "sent"
    store.save()
    return True

class Feed:
    def __init__(self, store, now):
        self.store, self.now = store, now
        self.day = now.date().isoformat()
    def get(self, league, endpoint, params=None):
        budget = self.store.state["budget"]
        if budget.get("date") != self.day:
            budget.clear()
            budget.update(date=self.day, used=0)
        if budget["used"] >= 450:
            raise SafeError("Gunluk dahili istek sinirina ulasildi")
        budget["used"] += 1
        self.store.save()
        sport = LEAGUES[league][0]
        url = "https://site.api.espn.com/apis/site/v2/sports/" + sport + "/" + league + "/" + endpoint
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return http_json(url)
    def fixtures(self, league):
        key = league + ":" + self.day
        cache = self.store.state["fixtures"]
        if key in cache:
            return cache[key]
        events = {}
        for delta in (-1, 0, 1):
            day = self.now.date() + dt.timedelta(days=delta)
            data = self.get(league, "scoreboard", {"dates": day.strftime("%Y%m%d")})
            source_leagues = data.get("leagues") or []
            if not source_leagues or source_leagues[0].get("slug") != league or not isinstance(data.get("events"), list):
                raise SafeError("Fikstur kapsami dogrulanamadi")
            for event in data["events"]:
                ident = str(event.get("id", ""))
                if ident.isdigit():
                    comp = (event.get("competitions") or [{}])[0]
                    events[ident] = {"id": ident, "date": event.get("date"),
                                    "status": event.get("status") or comp.get("status", {}),
                                    "competitions": [{"competitors": [
                                        {"team": c.get("team", {})} for c in comp.get("competitors", [])]}]}
        for old in list(cache):
            if old.rsplit(":", 1)[-1] != self.day:
                del cache[old]
        cache[key] = list(events.values())
        self.store.save()
        return cache[key]
    def summary(self, league, ident):
        return self.get(league, "summary", {"event": ident})

def run_tracking(store, alerts, now, feed, send, dry_run=False):
    for league in sorted({a["league"] for a in alerts}):
        rules = [a for a in alerts if a["league"] == league]
        try:
            events = feed.fixtures(league)
        except SafeError:
            print("Bir lig icin fikstur alinamadi; o kapsamda bildirim uretilmedi.")
            continue
        for event in events:
            ident = str(event["id"])
            completed_key = league + ":" + ident
            competitors = (event.get("competitions") or [{}])[0].get("competitors", [])
            relevant = [a for a in rules if find_team(competitors, a) is not None and
                        delivery_key(a, ident) not in store.state["delivered"]]
            if (not relevant or not in_window(event, now, league) or
                event_state(event) == "post" or completed_key in store.state["completed"]):
                continue
            try:
                summary = feed.summary(league, ident)
            except SafeError:
                print("Mac verisi alinamadi; onbellekten istatistik veya alarm uretilmedi.")
                continue
            header = summary.get("header", {})
            comp = (header.get("competitions") or [{}])[0]
            actual = {"date": comp.get("date") or event.get("date"), "status": comp.get("status", {})}
            if str(header.get("id", comp.get("id", ""))) != ident:
                continue
            if event_state(actual) == "post":
                store.state["completed"][completed_key] = now.date().isoformat()
                store.save()
                continue
            if event_state(actual) != "in" or not in_window(actual, now, league):
                continue
            for alert in relevant:
                value = metric(summary, alert)
                if value is None or not OPS[alert["op"]](value, alert["threshold"]):
                    continue
                if dry_run:
                    print("Deneme: gercek veride bir esik kosulu saglandi; mesaj gonderilmedi.")
                    continue
                names = [c.get("team", {}).get("displayName", "") for c in comp.get("competitors", [])]
                who = alert.get("player_name") or alert.get("team_name") or "Secili takim/oyuncu"
                text = ("Spor Alarm\n" + " - ".join(names) + "\n" + who + "\n" +
                        alert["stat"] + ": " + format(value, "g") + " " + alert["op"] + " " +
                        format(alert["threshold"], "g") + "\nKaynak: ESPN | " +
                        now.astimezone(dt.timezone(dt.timedelta(hours=3))).strftime("%d.%m %H:%M") +
                        "\nhttps://www.espn.com/" + ("nba" if league == "nba" else "soccer") +
                        "/game/_/gameId/" + ident)
                deliver_once(store, alert, ident, text, send)

def main():
    required = ("ALERTS_JSON","TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID","GITHUB_TOKEN","GITHUB_REPOSITORY","GITHUB_SHA")
    if any(not os.environ.get(k, "").strip() for k in required):
        raise SafeError("Gerekli Secret veya GitHub calisma degiskeni eksik")
    alerts = load_alerts(os.environ["ALERTS_JSON"])
    store = Store(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"],
                  os.environ["TELEGRAM_BOT_TOKEN"], os.environ["GITHUB_SHA"])
    store.load()
    dry = os.environ.get("DRY_RUN", "false").lower() == "true"
    if not alerts:
        print("Bos alarm listesi dogrulandi. Sifreli kalici kayit hazir; spor sorgusu ve bildirim yapilmadi.")
        return 0
    now = dt.datetime.now(UTC)
    def send(text):
        result = http_json("https://api.telegram.org/bot" + os.environ["TELEGRAM_BOT_TOKEN"] + "/sendMessage",
            method="POST", body={"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                                "text": text, "link_preview_options": {"is_disabled": True}})
        if result.get("ok") is not True:
            raise SafeError("Telegram mesaji kabul edilmedi; otomatik tekrar yapilmayacak")
    run_tracking(store, alerts, now, Feed(store, now), send, dry)
    store.save()
    print("Kontrol tamamlandi. Tercihler, istatistik degerleri ve gizli bilgiler loglara yazilmadi.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except SafeError as exc:
        print("Kontrol guvenli olarak durdu: " + str(exc))
        sys.exit(1)
    except Exception:
        print("Beklenmeyen hata; gizli degerleri korumak icin ayrintilar yazdirilmadi.")
        sys.exit(1)
