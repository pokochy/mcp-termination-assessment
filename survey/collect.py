import json, urllib.request, urllib.parse, time, ssl
BASE="https://registry.modelcontextprotocol.io/v0/servers"
ctx=ssl.create_default_context()
def get(url, tries=4):
    for i in range(tries):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":"academic-survey/1.0"})
            with urllib.request.urlopen(req, timeout=25, context=ctx) as r: return json.loads(r.read())
        except Exception as e:
            if i==tries-1: raise
            time.sleep(2*(i+1))
all_s=[]; cursor=None; pages=0
while True:
    url=BASE+"?limit=100"+(f"&cursor={urllib.parse.quote(cursor,safe='')}" if cursor else "")
    d=get(url); batch=d.get("servers",[]); all_s.extend(batch); pages+=1
    cursor=d.get("metadata",{}).get("nextCursor")
    if pages%20==0: print(" page",pages,"total",len(all_s),flush=True)
    if not cursor or not batch: break
print("pages:",pages,"raw:",len(all_s))
json.dump(all_s, open("registry_raw.json","w",encoding="utf-8"), ensure_ascii=False)
off="io.modelcontextprotocol.registry/official"
latest=[s for s in all_s if s.get("_meta",{}).get(off,{}).get("isLatest")]
active=[s for s in latest if s["_meta"][off].get("status")=="active"]
remote=[s for s in active if s["server"].get("remotes")]
print("isLatest:",len(latest),"active+latest:",len(active),"REMOTE:",len(remote))
json.dump(remote, open("registry_remote.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
