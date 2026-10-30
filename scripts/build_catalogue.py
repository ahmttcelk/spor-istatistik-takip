"""Build only public team catalogue for the static tablet editor."""
import datetime as dt
import json
import pathlib
import urllib.request

LEAGUES=("tur.1","eng.1","esp.1","ita.1","ger.1","uefa.champions","nba")
def build():
    result={"generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"leagues":{}}
    for league in LEAGUES:
        sport="basketball" if league=="nba" else "soccer"
        url="https://site.api.espn.com/apis/site/v2/sports/"+sport+"/"+league+"/teams?limit=100"
        req=urllib.request.Request(url,headers={"User-Agent":"sports-catalogue/1"})
        with urllib.request.urlopen(req,timeout=25) as response:
            data=json.load(response)
        teams=[]
        for sport_data in data.get("sports",[]):
            for league_data in sport_data.get("leagues",[]):
                for row in league_data.get("teams",[]):
                    team=row.get("team",{})
                    ident=str(team.get("id",""))
                    name=team.get("displayName")
                    if ident.isdigit() and isinstance(name,str) and name:
                        teams.append({"id":ident,"displayName":name})
        if not teams:
            raise RuntimeError("Public team catalogue unavailable")
        result["leagues"][league]=teams
        print(league+": public catalogue ready ("+str(len(teams))+" teams)",flush=True)
    pathlib.Path("docs/teams.json").write_text(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":
    build()
