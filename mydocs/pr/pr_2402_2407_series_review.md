# kevin9327 studio 연작 검토 — #2402 → #2404~#2407

문서 기여(#2380/#2381)에서 studio 코드 기여로 확장한 연작 5건. 전부 독립
파일축(공유: mutation-routing-guard baseline·command.ts 2건 인접).

## #2402 — 계산식 쉼표 겹침 (closes #2367)

- 원인 정확: evaluateTableFormula(write_result=true)가 원시 결과 선기록 →
  쉼표 포맷이 offset 0 삽입으로 겹침("6,9126912"). #2344 "delete 누락"
  동형으로 delete→insert, 같은 commit() 클로저 = snapshot 원자화 유지.
- 원장 3→4 사유 주석 — 이관 연작 규율을 외부 기여자가 그대로 따름.
- 재실증: tsc OK / npm test 367/367 / red→green(원복 시 2 FAIL) / CI green.
- **merge 권고.**

(후속 4건은 순서대로 개별 검증 후 이 문서에 추가)
