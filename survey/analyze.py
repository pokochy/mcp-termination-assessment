# -*- coding: utf-8 -*-
"""조사 결과 집계"""
import json, sys
from collections import Counter

src = sys.argv[1] if len(sys.argv) > 1 else "survey_full.json"
d = json.load(open(src, encoding="utf-8"))
n_total = len(d)

# 인가 메타데이터를 공개한 서비스 (RFC 8414)
has_as = [x for x in d if isinstance(x.get("as"), dict) and x["as"].get("issuer")]
# 보호 자원 메타데이터 (RFC 9728)
has_pr = [x for x in d if isinstance(x.get("pr"), dict) and x["pr"].get("resource")]
# 인가를 적용한 서비스 = AS 또는 PR 메타데이터 중 하나라도 공개
authz = {x["host"] for x in has_as} | {x["host"] for x in has_pr}

rev = [x for x in has_as if x["as"].get("revocation_endpoint")]
intro = [x for x in has_as if x["as"].get("introspection_endpoint")]
reg = [x for x in has_as if x["as"].get("registration_endpoint")]
same = [x for x in rev if x["as"]["revocation_endpoint"] == x["as"].get("token_endpoint")]
refresh = [x for x in has_as if "refresh_token" in (x["as"].get("grant_types_supported") or [])]

print(f"조사 대상 호스트            : {n_total}")
print(f"인가 적용 (AS 또는 PR 공개) : {len(authz)}")
print(f"인가 서버 메타데이터 공개   : {len(has_as)}")
print(f"보호 자원 메타데이터 공개   : {len(has_pr)}")
print()
B = len(has_as)
def pct(k): return f"{k}/{B} ({100*k/B:.1f}%)" if B else "-"
print(f"  폐기 종단점 제공          : {pct(len(rev))}")
print(f"  조사 종단점 제공          : {pct(len(intro))}")
print(f"  동적 등록 종단점 제공     : {pct(len(reg))}")
print(f"  갱신 토큰 지원            : {pct(len(refresh))}")
print(f"  폐기 종단점 = 토큰 종단점 : {len(same)}/{len(rev)}"
      f" ({100*len(same)/len(rev):.1f}%)" if rev else "")
print()
print("조사 종단점 제공 호스트:")
for x in intro:
    print("   ", x["host"], "->", x["as"]["introspection_endpoint"])
print()
# 응답 상태 분포
print("AS 메타데이터 응답 상태 분포:", Counter(str(x.get("as_status")) for x in d).most_common(8))
print("PR 메타데이터 응답 상태 분포:", Counter(str(x.get("pr_status")) for x in d).most_common(8))

json.dump({
    "n_total": n_total, "n_authz": len(authz), "n_as": len(has_as), "n_pr": len(has_pr),
    "revocation": len(rev), "introspection": len(intro), "registration": len(reg),
    "refresh": len(refresh), "rev_eq_token": len(same),
    "intro_hosts": [x["host"] for x in intro],
}, open("survey_summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n-> survey_summary.json 저장")
