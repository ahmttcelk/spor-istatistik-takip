"""Static editor syntax and public roster/CORS integration check. No secrets."""
import json
import pathlib
import subprocess
import tempfile
import urllib.request
import urllib.error

BASE="https://site.api.espn.com/apis/site/v2/sports/"
ORIGIN="https://ahmttcelk.github.io"
LEAGUES=["tur.1","eng.1","esp.1","ita.1","ger.1","uefa.champions","nba"]

def get(url):
    req=urllib.request.Request(url,headers={"Origin":ORIGIN,"User-Agent":"sports-editor-check/1"})
    with urllib.request.urlopen(req,timeout=25) as r:
        cors=r.headers.get("Access-Control-Allow-Origin")
        data=json.load(r)
    return data,cors

def athletes(value,out):
    if isinstance(value,list):
        for x in value:
            athletes(x,out)
    elif isinstance(value,dict):
        if value.get("id") and (value.get("fullName") or value.get("displayName")) and (
                value.get("position") or value.get("jersey") or value.get("firstName")):
            out.add(str(value["id"]))
        for k in ("athletes","items","athlete"):
            if k in value:
                athletes(value[k],out)

def main():
    html=pathlib.Path("docs/index.html").read_text()
    script=html.split("<script>",1)[1].split("</script>",1)[0]
    with tempfile.TemporaryDirectory() as temp:
        path=pathlib.Path(temp)/"editor.js"
        path.write_text(script)
        subprocess.run(["node","--check",str(path)],check=True)
    print("EDITOR_SYNTAX_OK",flush=True)
    for league in LEAGUES:
        sport="basketball" if league=="nba" else "soccer"
        base=BASE+sport+"/"+league
        try:
            data,cors=get(base+"/teams?limit=100")
            teams=[t["team"] for s in data.get("sports",[]) for l in s.get("leagues",[]) for t in l.get("teams",[])]
            print(league+" TEAM_COUNT "+str(len(teams))+" CORS "+str(cors in ("*",ORIGIN)),flush=True)
            if not teams:
                raise ValueError("No teams")
            roster,rcors=get(base+"/teams/"+str(teams[0]["id"])+"/roster")
            players=set()
            athletes(roster.get("athletes"),players)
            print(league+" ROSTER_COUNT "+str(len(players))+" CORS "+str(rcors in ("*",ORIGIN)),flush=True)
        except Exception:
            print(league+" EDITOR_DATA_UNAVAILABLE",flush=True)

if __name__=="__main__":
    main()
