"""
테스트베드 실험 실행기
=====================
E1 : 상태 비저장 접근 토큰 폐기 후 잔존 접근 구간
E2 : 세션 종료 요청 거부(405) 이후 세션 존속
E3 : 상위 토큰 폐기 및 조사 확인 이후 하위 위임 자격을 통한 자원 접근 성립

실행:  python run_experiments.py [반복횟수]
결과:  results.json
"""
import json, sys, time
import testbed as T


def boot():
    T.serve(T.UpperAS, T.UPPER_PORT)
    T.serve(T.LowerAS, T.LOWER_PORT)
    T.serve(T.Docs, T.DOCS_PORT)
    T.serve(T.MCP, T.MCP_PORT)
    time.sleep(0.4)
    T.acquire_lower_credential()


MCP_URL = f"http://127.0.0.1:{T.MCP_PORT}/mcp"
UP = f"http://127.0.0.1:{T.UPPER_PORT}"


def issue():
    _, tok, _ = T.post(f"{UP}/token", {})
    return tok


def call_tool(token, sid=None):
    """MCP 도구 호출. 성공 여부를 반환한다."""
    hdr = {"Mcp-Session-Id": sid} if sid else {}
    st, body, _ = T.post(MCP_URL, {"jsonrpc": "2.0", "id": 1, "method": "tools/call"},
                         token=token, headers=hdr)
    return st == 200 and "result" in body


def init_session(token):
    st, _, hdrs = T.post(MCP_URL, {"jsonrpc": "2.0", "id": 0, "method": "initialize"}, token=token)
    return hdrs.get("Mcp-Session-Id")


# ---------------------------------------------------------------------------
# E1 : 상태 비저장 접근 토큰 폐기 후 잔존 접근 구간
# ---------------------------------------------------------------------------
def e1():
    tk = issue()
    at = tk["access_token"]
    assert call_tool(at), "발급 직후 접근이 성립해야 한다"

    st_rev, _, _ = T.post(f"{UP}/revoke", {"token": at, "token_type_hint": "access_token"})
    t_rev = time.time()

    # 폐기 직후 인가 서버의 조사 응답은 비활성이다.
    _, ins, _ = T.post(f"{UP}/introspect", {"token": at})

    # 그럼에도 자원 서버(MCP)는 서명만으로 검증하므로 접근이 계속 성립한다.
    ok_after = call_tool(at)

    # 접근이 실제로 차단될 때까지의 구간을 측정한다.
    last_ok = None
    while time.time() - t_rev < T.ACCESS_TTL + 3:
        if call_tool(at):
            last_ok = time.time()
        else:
            break
        time.sleep(0.2)
    residual = (last_ok - t_rev) if last_ok else 0.0

    # 갱신 토큰의 존속 여부: 접근 토큰만 폐기한 경우 갱신 토큰 폐기는 선택(MAY)이다.
    _, ins_rt, _ = T.post(f"{UP}/introspect", {"token": tk["refresh_token"]})

    return {
        "revocation_status": st_rev,
        "introspection_active_after_revoke": ins.get("active"),
        "access_succeeded_after_revoke": ok_after,
        "residual_access_seconds": round(residual, 2),
        "token_lifetime_seconds": T.ACCESS_TTL,
        "refresh_token_still_active": ins_rt.get("active"),
    }


# ---------------------------------------------------------------------------
# E2 : 세션 종료 요청 거부(405) 이후 세션 존속
# ---------------------------------------------------------------------------
def e2():
    at = issue()["access_token"]
    sid = init_session(at)
    assert sid, "세션 식별자가 부여되어야 한다"

    code = T.delete(MCP_URL, at, sid)          # 서버가 거부한다
    alive_after = call_tool(at, sid)           # 같은 세션으로 호출이 계속 성립한다

    # 서버가 종료를 허용하도록 구성을 바꾼 경우와 대조한다.
    T.ALLOW_DELETE = True
    sid2 = init_session(at)
    code2 = T.delete(MCP_URL, at, sid2)
    alive2 = call_tool(at, sid2)
    T.ALLOW_DELETE = False

    return {
        "delete_status_when_refused": code,
        "session_alive_after_refusal": alive_after,
        "delete_status_when_allowed": code2,
        "session_alive_after_allowed": alive2,
    }


# ---------------------------------------------------------------------------
# E3 : 상위 토큰 폐기 및 조사 확인 이후 하위 위임 자격을 통한 접근
# ---------------------------------------------------------------------------
def e3():
    tk = issue()
    at, rt = tk["access_token"], tk["refresh_token"]
    assert call_tool(at), "초기 접근이 성립해야 한다"

    # 조직이 상위 계층에서 수행 가능한 최대치를 수행한다.
    # 갱신 토큰을 제출하여 동일 인가의 접근 토큰까지 무효화한다(SHOULD).
    T.post(f"{UP}/revoke", {"token": rt, "token_type_hint": "refresh_token"})
    time.sleep(T.ACCESS_TTL + 0.5)             # 상태 비저장 구간이 지나기를 기다린다

    _, ins_at, _ = T.post(f"{UP}/introspect", {"token": at})
    _, ins_rt, _ = T.post(f"{UP}/introspect", {"token": rt})
    upper_clean = (ins_at.get("active") is False) and (ins_rt.get("active") is False)

    # 조직 경로의 접근은 차단된다.
    client_blocked = not call_tool(at)

    # 그러나 MCP 서버가 하위 시스템에 대해 보유한 자격은 그 조치의 대상이 아니다.
    import urllib.request, urllib.error
    req = urllib.request.Request(
        f"http://127.0.0.1:{T.DOCS_PORT}/doc",
        headers={"Authorization": f"Bearer {T.SERVER_CREDENTIAL['token']}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            downstream_ok = (r.status == 200)
    except urllib.error.HTTPError:
        downstream_ok = False

    # 하위 자격은 제공자가 폐기해야 비로소 회수된다.
    T.post(f"http://127.0.0.1:{T.LOWER_PORT}/revoke",
           {"token": T.SERVER_CREDENTIAL["token"]})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            downstream_after_provider = (r.status == 200)
    except urllib.error.HTTPError:
        downstream_after_provider = False

    T.acquire_lower_credential()               # 후속 반복을 위해 자격을 재취득한다

    return {
        "upper_layer_fully_revoked": upper_clean,
        "client_path_blocked": client_blocked,
        "downstream_access_via_server_credential": downstream_ok,
        "downstream_access_after_provider_revocation": downstream_after_provider,
    }


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    boot()
    out = {"repetitions": n, "token_lifetime_seconds": T.ACCESS_TTL, "runs": {}}
    for name, fn in (("E1", e1), ("E2", e2), ("E3", e3)):
        runs = []
        for i in range(n):
            r = fn()
            runs.append(r)
            print(f"{name} run {i+1}/{n}: {json.dumps(r, ensure_ascii=False)}", flush=True)
        out["runs"][name] = runs
    json.dump(out, open("results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 요약
    e1r = out["runs"]["E1"]
    res = [r["residual_access_seconds"] for r in e1r]
    print("\n===== 요약 =====")
    print(f"E1 폐기 후 접근 성공: {sum(r['access_succeeded_after_revoke'] for r in e1r)}/{n}"
          f" | 잔존 구간 평균 {sum(res)/len(res):.2f}s (최대 {max(res):.2f}s, 토큰 수명 {T.ACCESS_TTL}s)"
          f" | 조사 응답 active={e1r[0]['introspection_active_after_revoke']}"
          f" | 갱신 토큰 존속 {sum(bool(r['refresh_token_still_active']) for r in e1r)}/{n}")
    e2r = out["runs"]["E2"]
    print(f"E2 405 거부 후 세션 존속: {sum(r['session_alive_after_refusal'] for r in e2r)}/{n}"
          f" | 허용 구성에서 종료 성립: {sum(not r['session_alive_after_allowed'] for r in e2r)}/{n}")
    e3r = out["runs"]["E3"]
    print(f"E3 상위 완전 폐기 확인: {sum(r['upper_layer_fully_revoked'] for r in e3r)}/{n}"
          f" | 조직 경로 차단: {sum(r['client_path_blocked'] for r in e3r)}/{n}"
          f" | 하위 자격 접근 성립: {sum(r['downstream_access_via_server_credential'] for r in e3r)}/{n}"
          f" | 제공자 폐기 후 접근: {sum(r['downstream_access_after_provider_revocation'] for r in e3r)}/{n}")


if __name__ == "__main__":
    main()
