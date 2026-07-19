# M100 #2439 완료 보고 — HWP 반복 표·페이지 흐름·번호 들여쓰기 정합

- 이슈: [#2439](https://github.com/edwardkim/rhwp/issues/2439)
- 브랜치: `codex/task2439`
- 작성일: 2026-07-20
- 코드 커밋: `64138965`
- 재현 HWP SHA-256: `674eabe66ea0ba783ad2cd398519c9893ba94956a22d9cb94b084db00d4d2c3d`
- 정답 PDF SHA-256: `f36a747c5f848d90e755abe2e730d932429a324fad9b7e822964934cd8f8eca4`

## 결과

사용자 제공 HWP의 반복 표 행·라벨·서명 겹침과 3.8px `LAYOUT_OVERFLOW`를 제거하고,
정상 한컴 2024 PDF와 같은 10쪽 흐름을 복원했다. 표 하단과 서명문은 겹치지 않으며,
번호 줄글은 저장 LineSeg 시작점에 맞게 들여쓰기된다. 마지막 10쪽에는 정답지와 같이
`5.응급 및 긴급한 상황시 7920으로 연락한다.` 한 줄이 배치된다.

## 오라클 정정

정답지는 `Microsoft: Print To PDF`가 생성한 A4 landscape 841.92×595.32pt, 10쪽
PDF다. Stage 4에서 “10쪽은 빈 페이지이고 rhwp 9쪽과 내용이 일치한다”고 판정했으나,
10쪽 텍스트를 다시 확인해 이 결론을 철회했다. 8쪽 baseline에서 최초 표 겹침을 제거한
9쪽 출력은 중간 결과였고, 문서 전체 pagination은 아직 정답지와 달랐다.

정정 과정과 페이지별 오라클은
[Stage 5](../working/task_m100_2439_stage5.md), 최종 구현·검증은
[Stage 6](../working/task_m100_2439_stage6.md)에 기록했다.

## 변경 요약

### 단일 positive-offset 빈 host RowBreak 표

구조 조건이 일치하는 native HWP5 경로에서 실제 painted bottom, outer bottom, 저장
LineSeg 진행량을 flow에 반영했다. 다음 일반 문단에는 strict fit을 한 번만 전달하고
실제로 그려진 행 하단을 fragment fit 기준으로 사용한다.

### native HWP5 두 표 visible host

fresh page-local placement 교정을 유지하면서 zero-offset/positive-offset 두 표의 outer
top/bottom과 host LineSeg 간격을 순차 소비한다. typeset과 layout이 같은 하단을 사용해
표 그룹 뒤 서명문이 마지막 표 아래에서 시작한다.

### native HWP5 저장 LineSeg 들여쓰기

비합성 full-width 일반 본문 줄의 저장 `LineSeg.column_start`를 권위 시작점으로 사용한다.
표 셀, wrap/control, 번호 control, 합성 LineSeg, HWP3/HWPX는 제외한다.

- 제목 줄: `1900HU` → 63.09px ≈ 47.32pt
- 번호 줄글: `10320HU` → 175.36px = 131.52pt

## 검증

- 최종 `dump-pages`: 10쪽
  - 4쪽 마지막 `pi=19`
  - 5쪽 시작 `pi=20`
  - 10쪽 `pi=90`과 마지막 5번 문장
- focused: 16개 대상, 60 tests, 0 failed, 0 ignored
- `cargo fmt --all -- --check`: 통과
- `wasm-pack build --target web --out-dir pkg`: 통과
- Studio: PID `81399`, cwd `rhwp-studio`, `http://127.0.0.1:7700` HTTP 200

PDF visual sweep 결과는
`/private/tmp/rhwp-issue2439-sweep-final-20260720`에 있다.

- 10/10쪽, 자동 후보 0/10
- 평균 `pixel_match_percent`: 89.15839%
- 평균 `visual_accuracy_proxy_percent`: 6.21195%
- 최저 `visual_accuracy_proxy_percent`: 2.6602% (3쪽)
- 사람 직접 review 1~10쪽 통과: 표-서명 겹침 없음, 번호 들여쓰기 적용, 10쪽 문장 확인

환경은 macOS Darwin 25.5.0 arm64, 별도 `--font-path` 없이 실행했다. fontconfig에서
`MS바탕`/`바탕`이 Verdana로 fallback되어 자동 잉크 지표에는 한컴 전용 폰트 부재의
영향이 포함된다.

코멘트: 내용 픽셀 중심 자동 일치율 보조값 = 평균 약 6.21%.
높을수록 좋음: 기준 PDF와 rhwp PNG가 더 비슷함
낮을수록 나쁨/검토 필요: 잉크 위치나 형태 차이가 큼
단, 사람 판정 정확도가 아니라 내용 픽셀 중심 자동 일치율 보조값입니다

페이지별 `compare`, `overlay`, `review` 절대 경로와 보조값은
[Stage 6](../working/task_m100_2439_stage6.md)에 기록했다.

## 배포 상태

로컬 코드 커밋과 문서 갱신까지 완료했다. 전체 CI, remote push, PR 생성은 수행하지
않았다.
