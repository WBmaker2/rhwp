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
- 정상 Microsoft Print to PDF 정답지와 1~9쪽 양식 순서 및 문제 6쪽의 두 표·라벨·서명
  비겹침을 대조해 일치 확인.

## 남은 호환성 항목

정상 Microsoft Print to PDF는 10쪽이지만 실제 양식은 rhwp와 동일하게 1~9쪽에 있고
10쪽은 완전히 비어 있다. 양식 누락은 없다. 4쪽 이후 한컴은 앞 양식 안내문의 마지막
1~2줄을 다음 쪽 상단에 두고 다음 양식 제목·메타데이터와 함께 배치하지만, rhwp는 안내문
전체와 다음 제목을 앞쪽에 유지할 수 있다. 이 제목/표 그룹 pagination과 trailing blank
page 보존은 표 겹침 결함과 독립적이므로 별도 호환성 항목으로 다룬다.

## 배포 상태

로컬 브랜치에서 구현·focused 검증까지 완료했다. 전체 CI, push, PR 생성은 수행하지 않았다.
