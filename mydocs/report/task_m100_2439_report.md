# M100 #2439 완료 보고 — HWP 반복 표 겹침과 overflow 수정

- 이슈: [#2439](https://github.com/edwardkim/rhwp/issues/2439)
- 브랜치: `codex/task2439`
- 작성일: 2026-07-19

## 결과

같은 visible host에 묶인 반복 표가 fresh page로 이월될 때 이전 페이지 좌표를 유지하던
결함과 zero-offset 선행 표의 exclusion 누락을 수정했다. 사용자 제공 HWP에서 반복 표의
행·라벨·서명 겹침과 3.8px `LAYOUT_OVERFLOW`가 사라졌다.

## 변경 요약

- 이월된 RowBreak float의 placement/exclusion 기준을 fresh page-local 좌표로 재설정.
- zero-offset/positive-offset co-anchored 표 쌍의 전체 exclusion과 순차 배치 보존.
- 같은 host의 표 뒤 텍스트는 마지막 표 아래에서 시작하도록 보정.
- 최소 HWP/HWPX fixture와 render-tree bbox 회귀 테스트 2건 추가.

## 검증

- 신규 #2439 테스트 2/2 통과.
- 관련 #1510, #1535, #1549, #1663, #2322 focused 테스트 11/11 통과.
- 원본 HWP PDF/SVG 재출력: 9쪽, `LAYOUT_OVERFLOW` 없음, 문제 페이지 포함 시각 확인 통과.

## 남은 호환성 항목

한컴 2024 편집 화면은 10쪽이고 rhwp는 9쪽이다. 차이는 다음 양식 제목의 페이지 나눔에
있으며 표 겹침 결함과 독립적이다. 가로가 정상인 Microsoft Print to PDF 결과 파일을
확보하면 별도 페이지 나눔 호환성 작업에서 정밀 비교할 수 있다. 현재 한컴 PDF 내보내기
파일은 세로/가로 출력 설정 차이로 오른쪽 열이 잘려 가로 배치 오라클에는 사용하지 않았다.

## 배포 상태

로컬 브랜치에서 구현·focused 검증까지 완료했다. 전체 CI, push, PR 생성은 수행하지 않았다.
