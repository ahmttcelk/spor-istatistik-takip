"""Read-only coverage probe: never prints raw responses or secret values."""
import datetime as dt
import json
import os
import sys
from scripts.check_connections import request_json, SafeError

def reason(payload):
    errors = payload.get("errors")
    if not errors:
        return "OK"
    text = json.dumps(errors, ensure_ascii=True).lower()
    if "free" in text and ("season" in text or "access" in text):
        return "FREE_PLAN_ACCESS_RESTRICTED"
    if "rate" in text and ("limit" in text or "too many" in text):
        return "RATE_LIMIT"
    if "quota" in text or "limit" in text and ("request" in text or "day" in text):
        return "QUOTA_LIMIT"
    if "season" in text:
        return "SEASON_PARAMETER_OR_ACCESS"
    if "token" in text or "key" in text:
        return "AUTHENTICATION"
    return "API_REJECTED"

def query(base, path, key, params):
    result = request_json(base, path, key, params)
    code = reason(result)
    if code != "OK":
        print("  Sonuc: " + code)
        return None
    data = result.get("response")
    return data if isinstance(data, list) else None

def main():
    key = os.environ.get("API_SPORTS_KEY", "").strip()
    if not key:
        print("API_SPORTS_KEY eksik")
        return 1
    today = dt.datetime.now(dt.timezone.utc).date()
    year = today.year if today.month >= 7 else today.year - 1
    print("Futbol: guncel sezon erisim kontrolu")
    query("https://v3.football.api-sports.io", "/fixtures", key,
          {"league": 39, "season": year, "date": today.isoformat()})
    host = "https://v1.basketball.api-sports.io"
    for label in ("NBA", "Euroleague"):
        print(label + ":")
        leagues = query(host, "/leagues", key, {"name": label})
        found = [x for x in (leagues or []) if str(x.get("name", "")).lower() == label.lower()]
        if not found:
            print("  Lig bulunamadi")
            continue
        league = found[0]
        league_id = league.get("id")
        if not isinstance(league_id, int):
            print("  Lig kimligi okunamadi")
            continue
        print("  Lig ID: " + str(league_id))
        seasons = league.get("seasons") or []
        # Public season names and boolean capability fields only.
        candidates = []
        for season in seasons:
            value = season.get("season") if isinstance(season, dict) else season
            if str(value) in (str(year), str(year) + "-" + str(year+1)):
                candidates.append(value)
                if isinstance(season, dict):
                    cov = season.get("coverage", {})
                    if isinstance(cov, dict):
                        for field in ("games", "statistics", "players", "teams"):
                            if isinstance(cov.get(field), bool):
                                print("  " + field + ": " + str(cov[field]))
        if not candidates:
            print("  Guncel sezon metadata listesinde bulunamadi.")
            print("  Canli oyuncu destegi DOGRULANMADI; alarm kapali.")
            continue
        value = candidates[-1]
        print("  Sezon: " + str(value))
        games = query(host, "/games", key,
                      {"league": league_id, "season": value, "date": today.isoformat()})
        if games is None:
            print("  Guncel sezon erisimi yok; alarm kapali.")
            continue
        print("  Bugunku mac sayisi: " + str(len(games)))
        live = [g for g in games if g.get("status", {}).get("short") in
                ("Q1", "Q2", "Q3", "Q4", "OT", "HT", "BT", "P", "LIVE")]
        if not live:
            print("  Su an canli mac bulunamadi; canli oyuncu destegi DOGRULANMADI.")
            continue
        game_id = live[0].get("id")
        if not isinstance(game_id, int):
            continue
        stats = query(host, "/games/statistics/players", key, {"id": game_id})
        print("  Canli macta oyuncu istatistik kaydi: " + str(len(stats or [])))
        if not stats:
            print("  Canli oyuncu destegi DOGRULANMADI; oyuncu alarmlari kapali.")
    print("Kontrol tamamlandi. Hicbir alarm veya Telegram mesaji gonderilmedi.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except SafeError as exc:
        print("Guvenli baglanti hatasi: " + str(exc))
        sys.exit(1)
    except Exception:
        print("Beklenmeyen veri bicimi. Gizli degerler ve ham yanitlar yazdirilmadi.")
        sys.exit(1)
