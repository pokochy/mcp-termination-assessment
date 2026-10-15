# -*- coding: utf-8 -*-
"""
실험1(원격 서비스 인가 메타데이터 조사) 재현 파이프라인.

collect.py -> (host_url.json 생성) -> survey.py -> analyze.py 를 순서대로 실행한다.
결과는 원본 survey_results.json / survey_summary.json을 덮어쓰지 않도록
이 스크립트를 실행한 시각 기준 새 폴더(rerun_YYYYMMDD_HHMMSS/)에 저장한다.

사용법:
    python rerun_survey_pipeline.py            # 전체 호스트 대상
    python rerun_survey_pipeline.py 500        # survey.py에 호스트 수 제한 전달(테스트용)
"""
import json
import subprocess
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(script: str, args: list[str], cwd: Path) -> None:
    print(f"\n=== {script} {' '.join(args)} (cwd={cwd}) ===", flush=True)
    result = subprocess.run(
        [sys.executable, str(HERE / script), *args],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(f"{script} 실패 (exit code {result.returncode})")


def build_host_url_json(cwd: Path) -> int:
    """collect.py가 만든 registry_remote.json에서 host -> 대표 URL 맵을 만든다."""
    remote_path = cwd / "registry_remote.json"
    servers = json.loads(remote_path.read_text(encoding="utf-8"))

    host_url: dict[str, str] = {}
    for entry in servers:
        for remote in entry.get("server", {}).get("remotes", []) or []:
            url = remote.get("url")
            if not url:
                continue
            host = urllib.parse.urlparse(url).netloc
            if host and host not in host_url:
                host_url[host] = url

    (cwd / "host_url.json").write_text(
        json.dumps(host_url, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"host_url.json 생성: 고유 호스트 {len(host_url)}개")
    return len(host_url)


def main() -> None:
    survey_limit = sys.argv[1:2]  # survey.py에 그대로 전달할 선택적 인자(호스트 수 제한)

    out_dir = HERE / f"rerun_{datetime.now():%Y%m%d_%H%M%S}"
    out_dir.mkdir(parents=True, exist_ok=False)
    print(f"결과 저장 위치: {out_dir}")

    # 1. 레지스트리 수집 -> registry_raw.json, registry_remote.json
    run("collect.py", [], cwd=out_dir)

    # 2. 조사 대상 호스트 목록 생성 -> host_url.json
    n_hosts = build_host_url_json(out_dir)
    if n_hosts == 0:
        raise SystemExit("registry_remote.json에서 원격 호스트를 찾지 못했다.")

    # 3. 인가 메타데이터 조사 -> survey_full.json
    run("survey.py", survey_limit, cwd=out_dir)

    # survey_full.json을 원본과 같은 파일명(survey_results.json)으로도 남겨 비교하기 쉽게 한다
    (out_dir / "survey_results.json").write_bytes(
        (out_dir / "survey_full.json").read_bytes()
    )

    # 4. 집계 -> survey_summary.json + 콘솔 출력
    run("analyze.py", ["survey_full.json"], cwd=out_dir)

    print(f"\n완료. {out_dir} 안의 survey_summary.json을 논문 수치(표, 31.3% 등)와 비교하면 된다.")


if __name__ == "__main__":
    main()
