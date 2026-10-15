# -*- coding: utf-8 -*-
"""
원격 MCP 서비스 인가 메타데이터 전수 조사
공개된 표준 메타데이터 종단점(RFC 8414 / RFC 9728)만 조회한다.
호스트당 최대 2회 GET. 인증 시도나 상태 변경 요청은 하지 않는다.
"""
import json, urllib.request, urllib.parse, ssl, socket, concurrent.futures as cf, time, sys

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
UA = "KIISC-academic-survey/1.0 (MCP authorization metadata study; contact: kiisc paper)"
TIMEOUT = 7

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            return r.status, r.read(300000)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:
        return None, type(e).__name__.encode()

def probe(host):
    out = {"host": host}
    base = "https://" + host
    st, body = fetch(base + "/.well-known/oauth-authorization-server")
    out["as_status"] = st
    if st == 200:
        try:
            out["as"] = json.loads(body)
        except Exception:
            out["as_parse_error"] = True
    st2, body2 = fetch(base + "/.well-known/oauth-protected-resource")
    out["pr_status"] = st2
    if st2 == 200:
        try:
            out["pr"] = json.loads(body2)
        except Exception:
            out["pr_parse_error"] = True
    return out

def main():
    hosts = list(json.load(open("host_url.json", encoding="utf-8")).keys())
    bad = lambda h: ("{" in h or "}" in h or h.startswith("localhost")
                     or h.startswith("127.") or h.startswith("0.0.0.0") or "." not in h)
    hosts = [h for h in hosts if not bad(h)]
    if len(sys.argv) > 1:
        hosts = hosts[:int(sys.argv[1])]
    print("targets:", len(hosts), flush=True)
    res = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=48) as ex:
        for i, r in enumerate(ex.map(probe, hosts), 1):
            res.append(r)
            if i % 500 == 0:
                json.dump(res, open("survey_full.json","w",encoding="utf-8"), ensure_ascii=False)
                ok = sum(1 for x in res if "as" in x)
                print(f"  {i}/{len(hosts)}  as200={ok}  {time.time()-t0:.0f}s", flush=True)
    json.dump(res, open("survey_full.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("done", len(res), f"{time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
