"""
원격 MCP 서비스 종료 판정 테스트베드
=====================================
논문의 세 가지 주장을 재현 측정한다. 표준 라이브러리만 사용한다.

구성 요소
  AS_upper   : 상위 인가 서버 (조직 <-> MCP 서버). RFC 7009 폐기 / RFC 7662 조사 지원
  MCP        : 원격 MCP 서버. Streamable HTTP. 클라이언트에 대해 자원 서버이며
               하위 시스템에 대해서는 독립적인 인가 클라이언트로 자체 자격을 보유
  AS_lower   : 하위 인가 서버 (MCP 서버 <-> 문서 저장소)
  DOCS       : 하위 문서 저장소 (보호 자원)

측정 항목
  E1 : 상태 비저장 접근 토큰 폐기 후 잔존 접근 구간
  E2 : 세션 종료 요청(HTTP DELETE) 거부(405) 이후 세션 존속
  E3 : 상위 토큰 폐기 및 조사 확인 이후 하위 위임 자격을 통한 자원 접근 성립
"""
import base64, hashlib, hmac, json, threading, time, urllib.request, urllib.error, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPPER_PORT, MCP_PORT, LOWER_PORT, DOCS_PORT = 9101, 9102, 9103, 9104
UPPER_SECRET, LOWER_SECRET = b"upper-signing-key", b"lower-signing-key"

# 상태 비저장 접근 토큰의 수명(초). 실측 구간을 짧게 관찰하기 위한 값이며
# 실제 서비스의 토큰 수명은 통상 수십 분에서 수 시간이다.
ACCESS_TTL = 6


# --------------------------------------------------------------------------
# JWT (HS256) 최소 구현
# --------------------------------------------------------------------------
def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jwt_sign(payload: dict, secret: bytes) -> str:
    head = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64u(json.dumps(payload, separators=(",", ":")).encode())
    sig = b64u(hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def jwt_verify(token: str, secret: bytes):
    """서명과 만료만 검사한다. 인가 서버에 조회하지 않는 상태 비저장 검증이다."""
    try:
        head, body, sig = token.split(".")
    except ValueError:
        return None
    want = b64u(hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, want):
        return None
    payload = json.loads(b64u_dec(body))
    if payload.get("exp", 0) < time.time():
        return None
    return payload


# --------------------------------------------------------------------------
# 공통 HTTP 헬퍼
# --------------------------------------------------------------------------
class Base(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, headers=None):
        body = b"" if obj is None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        ctype = self.headers.get("Content-Type", "")
        if "json" in ctype:
            try:
                return json.loads(raw or b"{}")
            except Exception:
                return {}
        return dict(urllib.parse.parse_qsl(raw.decode() or ""))

    def _bearer(self):
        h = self.headers.get("Authorization", "")
        return h[7:] if h.startswith("Bearer ") else None


# --------------------------------------------------------------------------
# 상위 인가 서버 : RFC 7009 폐기 / RFC 7662 조사
# --------------------------------------------------------------------------
UPPER_REVOKED = set()      # 폐기된 jti 집합 (인가 서버가 보유하는 상태)
UPPER_REFRESH = {}         # refresh_token -> {"jti":..., "revoked":bool}


class UpperAS(Base):
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        d = self._read()

        if path == "/token":
            jti = hashlib.sha1(f"{time.time()}".encode()).hexdigest()[:12]
            now = int(time.time())
            at = jwt_sign({"sub": "org-client", "jti": jti, "iat": now,
                           "exp": now + ACCESS_TTL, "aud": "mcp-server"}, UPPER_SECRET)
            rt = "rt-" + jti
            UPPER_REFRESH[rt] = {"jti": jti, "revoked": False}
            return self._send(200, {"access_token": at, "refresh_token": rt,
                                    "token_type": "Bearer", "expires_in": ACCESS_TTL})

        if path == "/revoke":
            # RFC 7009: 유효한 토큰을 폐기한 경우와 이미 유효하지 않은 토큰을
            # 수신한 경우 모두 HTTP 200을 반환한다.
            tok = d.get("token", "")
            hint = d.get("token_type_hint", "")
            if tok.startswith("rt-"):
                rec = UPPER_REFRESH.get(tok)
                if rec:
                    rec["revoked"] = True
                    # 갱신 토큰 제출 시 동일 인가의 접근 토큰도 무효화한다(SHOULD).
                    UPPER_REVOKED.add(rec["jti"])
            else:
                p = None
                try:
                    p = json.loads(b64u_dec(tok.split(".")[1]))
                except Exception:
                    pass
                if p and p.get("jti"):
                    UPPER_REVOKED.add(p["jti"])
                    # 접근 토큰 제출 시 갱신 토큰의 폐기는 선택이다(MAY).
                    # 본 구현은 규격이 허용하는 범위에서 갱신 토큰을 존속시킨다.
            return self._send(200, None)

        if path == "/introspect":
            # RFC 7662: 토큰의 현재 유효 상태를 조회한다.
            tok = d.get("token", "")
            if tok.startswith("rt-"):
                rec = UPPER_REFRESH.get(tok)
                return self._send(200, {"active": bool(rec and not rec["revoked"])})
            p = jwt_verify(tok, UPPER_SECRET)
            active = bool(p) and p.get("jti") not in UPPER_REVOKED
            out = {"active": active}
            if active:
                out.update({"sub": p["sub"], "exp": p["exp"], "jti": p["jti"]})
            return self._send(200, out)

        self._send(404, {"error": "not_found"})

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path == "/.well-known/oauth-authorization-server":
            b = f"http://127.0.0.1:{UPPER_PORT}"
            return self._send(200, {"issuer": b, "token_endpoint": f"{b}/token",
                                    "revocation_endpoint": f"{b}/revoke",
                                    "introspection_endpoint": f"{b}/introspect"})
        self._send(404, {"error": "not_found"})


# --------------------------------------------------------------------------
# 하위 인가 서버 : MCP 서버가 하위 시스템에 대해 보유하는 자격을 발급
# --------------------------------------------------------------------------
LOWER_REVOKED = set()


class LowerAS(Base):
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/token":
            now = int(time.time())
            jti = "low-" + hashlib.sha1(f"{now}".encode()).hexdigest()[:8]
            at = jwt_sign({"sub": "mcp-server", "jti": jti, "iat": now,
                           "exp": now + 3600, "aud": "docs"}, LOWER_SECRET)
            return self._send(200, {"access_token": at, "expires_in": 3600})
        if path == "/revoke":
            # 하위 자격의 폐기는 제공자(MCP 서버 운영자)의 권한에 속한다.
            d = self._read()
            try:
                p = json.loads(b64u_dec(d.get("token", "").split(".")[1]))
                LOWER_REVOKED.add(p.get("jti"))
            except Exception:
                pass
            return self._send(200, None)
        self._send(404, {"error": "not_found"})


# --------------------------------------------------------------------------
# 하위 문서 저장소 : 보호 자원
# --------------------------------------------------------------------------
class Docs(Base):
    def do_GET(self):
        tok = self._bearer()
        p = jwt_verify(tok or "", LOWER_SECRET)
        if not p or p.get("jti") in LOWER_REVOKED:
            return self._send(401, {"error": "invalid_token"})
        self._send(200, {"document": "confidential-report.docx", "served_at": time.time()})


# --------------------------------------------------------------------------
# 원격 MCP 서버 : Streamable HTTP
# --------------------------------------------------------------------------
SESSIONS = {}          # sid -> {"created":ts, "alive":bool}
ALLOW_DELETE = False   # 규격은 서버가 클라이언트 주도 종료를 거부할 수 있도록 허용한다
SERVER_CREDENTIAL = {"token": None}   # MCP 서버가 하위 시스템에 대해 보유한 자격


def acquire_lower_credential():
    """MCP 서버가 하위 인가 서버로부터 자체 자격을 취득한다."""
    req = urllib.request.Request(f"http://127.0.0.1:{LOWER_PORT}/token", data=b"",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=5) as r:
        SERVER_CREDENTIAL["token"] = json.loads(r.read())["access_token"]


class MCP(Base):
    def do_POST(self):
        # 클라이언트에 대해서는 보호된 자원 서버로 동작한다.
        # 상태 비저장 검증: 서명과 만료만 확인하고 인가 서버에 조회하지 않는다.
        tok = self._bearer()
        claims = jwt_verify(tok or "", UPPER_SECRET)
        if not claims:
            return self._send(401, {"error": "invalid_token"})

        d = self._read()
        method = d.get("method", "")

        if method == "initialize":
            sid = hashlib.sha1(f"s{time.time()}".encode()).hexdigest()[:16]
            SESSIONS[sid] = {"created": time.time(), "alive": True}
            return self._send(200, {"jsonrpc": "2.0", "id": d.get("id"),
                                    "result": {"protocolVersion": "2025-06-18"}},
                              headers={"Mcp-Session-Id": sid})

        sid = self.headers.get("Mcp-Session-Id")
        if sid and not SESSIONS.get(sid, {}).get("alive"):
            return self._send(404, {"error": "session_not_found"})

        if method == "tools/call":
            # 하위 시스템 접근에는 클라이언트 토큰이 아니라
            # MCP 서버가 보유한 자체 자격을 사용한다(자격 격리).
            req = urllib.request.Request(
                f"http://127.0.0.1:{DOCS_PORT}/doc",
                headers={"Authorization": f"Bearer {SERVER_CREDENTIAL['token']}"})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return self._send(200, {"jsonrpc": "2.0", "id": d.get("id"),
                                            "result": json.loads(r.read())})
            except urllib.error.HTTPError as e:
                return self._send(200, {"jsonrpc": "2.0", "id": d.get("id"),
                                        "error": {"code": e.code, "message": "downstream_denied"}})

        self._send(200, {"jsonrpc": "2.0", "id": d.get("id"), "result": {"ok": True}})

    def do_DELETE(self):
        # 규격은 서버가 클라이언트 주도의 세션 종료를 허용하지 않고
        # 405 Method Not Allowed로 응답할 수 있음을 명시한다.
        if not ALLOW_DELETE:
            return self._send(405, {"error": "method_not_allowed"})
        sid = self.headers.get("Mcp-Session-Id")
        if sid in SESSIONS:
            SESSIONS[sid]["alive"] = False
        self._send(200, None)


# --------------------------------------------------------------------------
# 서버 기동
# --------------------------------------------------------------------------
def serve(handler, port):
    s = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def post(url, data, token=None, headers=None):
    hdr = {"Content-Type": "application/x-www-form-urlencoded"}
    if isinstance(data, dict) and headers is None:
        body = urllib.parse.urlencode(data).encode()
    else:
        body = json.dumps(data).encode()
        hdr = {"Content-Type": "application/json"}
    if token:
        hdr["Authorization"] = f"Bearer {token}"
    hdr.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=hdr, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {}), dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else {}), dict(e.headers)


def delete(url, token, sid):
    req = urllib.request.Request(url, method="DELETE", headers={
        "Authorization": f"Bearer {token}", "Mcp-Session-Id": sid})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
