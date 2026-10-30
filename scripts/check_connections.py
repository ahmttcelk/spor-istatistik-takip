"""Kurulum kontrolü. Gizli degerleri veya ham API yanitlarini yazdirmaz."""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

FOOTBALL = [(203, "Super Lig"), (39, "Premier League"), (140, "La Liga"),
            (135, "Serie A"), (78, "Bundesliga"), (2, "Champions League")]

class SafeError(Exception):
    pass

def request_json(base, path, key=None, params=None, body=None):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": "sports-alert-setup/1"}
    if key:
        headers["x-apisports-key"] = key
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=25) as res:
            result = json.load(res)
    except urllib.error.HTTPError as exc:
        raise SafeError("HTTP " + str(exc.code)) from None
    except Exception:
        raise SafeError("Baglanti veya JSON yaniti alinamadi") from None
    if not isinstance(result, dict):
        raise SafeError("Beklenmeyen yanit bicimi")
    return result

def valid_api(payload):
    if payload.get("errors"):
        # API error messages can contain account information; never echo them.
        raise SafeError("API erisimi reddedildi: plan, sezon veya kota kisiti olabilir")
    return payload.get("response", [])

def check_status(base, key):
    payload = request_json(base, "/status", key)
    result = valid_api(payload)
    if not isinstance(result, dict) or not result.get("subscription", {}).get("active"):
        raise SafeError("API aboneligi etkin degil")
    return result.get("requests", {}).get("limit_day", "?")

def run():
    key = os.environ.get("API_SPORTS_KEY", "").strip()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    missing = [name for name in ("API_SPORTS_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
               if not os.environ.get(name, "").strip()]
    if missing:
        print("Eksik Secret adlari: " + ", ".join(missing))
        return 1
    today = dt.datetime.now(dt.timezone.utc).date()
    season = today.year if today.month >= 7 else today.year - 1
    problems = 0
    for sport, host in (("Football", "https://v3.football.api-sports.io"),
                        ("Basketball", "https://v1.basketball.api-sports.io")):
        try:
            limit = check_status(host, key)
            print(sport + ": API baglantisi basarili. Gunluk kota: " + str(limit))
        except SafeError as exc:
            print(sport + ": " + str(exc))
            problems += 1
            continue
        if sport == "Football":
            for league_id, label in FOOTBALL:
                try:
                    games = valid_api(request_json(host, "/fixtures", key, {
                        "league": league_id, "season": season, "date": today.isoformat()}))
                    print(label + ": guncel sezon sorgusu kabul edildi; bugun " +
                          str(len(games)) + " mac. Canli oyuncu kapsami henuz dogrulanmadi.")
                except SafeError as exc:
                    print(label + ": " + str(exc) + ". Bu kapsam icin alarm etkinlestirilmeyecek.")
        else:
            for label in ("NBA", "Euroleague"):
                try:
                    leagues = valid_api(request_json(host, "/leagues", key, {"name": label}))
                    found = [x for x in leagues if str(x.get("name", "")).casefold() == label.casefold()]
                    if not found:
                        print(label + ": lig bulunamadi; alarm etkinlestirilmeyecek.")
                        continue
                    print(label + ": lig bulundu. Sezon erisimi ve canli oyuncu verisi henuz dogrulanmadi.")
                    # Coverage flags are public metadata, never account or secret data.
                    coverage = found[0].get("coverage")
                    if coverage is not None:
                        print(label + " coverage: " + json.dumps(coverage, ensure_ascii=True))
                except SafeError as exc:
                    print(label + ": " + str(exc))
    try:
        result = request_json("https://api.telegram.org", "/bot" + token + "/sendMessage",
            body={"chat_id": chat, "text": "Spor Alarm: Telegram baglantisi basarili. Bu bir kurulum testidir; canli istatistik alarmlari henuz etkin degil."})
        if result.get("ok") is not True:
            raise SafeError("Telegram mesaji kabul edilmedi")
        print("Telegram test mesaji gonderildi.")
    except SafeError as exc:
        print("Telegram: " + str(exc))
        problems += 1
    return int(problems > 0)

if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:
        print("Beklenmeyen hata. Gizli degerleri korumak icin ayrintilar gizlendi.")
        sys.exit(1)
