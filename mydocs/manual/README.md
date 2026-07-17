---
kind: guide
status: active
canonical: mydocs/manual/README.md
last_verified: 2026-07-17
---

# manual 문서 지도

`mydocs/manual/`은 rhwp를 **어떻게 수행하고 운영하는지**를 설명하는 문서 공간이다.
기술 사실, 설계 결정, 이슈별 원인 분석은 [tech 문서 지도](../tech/README.md)에서 찾는다.

## 먼저 읽을 문서

| 상황 | 권위 문서 | 보조 문서 |
| --- | --- | --- |
| 이슈 작업의 문서·브랜치·커밋 흐름 | [문서와 Git 워크플로우](codex/docs_and_git_workflow.md) | [하이퍼 워터폴 문서 가이드](hyper_waterfall_docs_guide.md) |
| Codex 저장소 부트스트랩 | [Codex 문서 지도](codex/README.md) | [문서와 Git 워크플로우](codex/docs_and_git_workflow.md) |
| 외부 PR 검토, collaborator 처리, merge 후속 | [PR 리뷰·통합 워크플로우](pr_review_workflow.md) | [개발 환경 가이드](dev_environment_guide.md) |
| 로컬 빌드, 테스트, WASM 검증 | [개발 환경 가이드](dev_environment_guide.md) | [CLI 명령어 매뉴얼](cli_commands.md) |
| 신규 기여자 시작 | [온보딩 가이드](onboarding_guide.md) | [문서와 Git 워크플로우](codex/docs_and_git_workflow.md) |
| `rhwp` CLI 전체 옵션과 동작 | [CLI 명령어 매뉴얼](cli_commands.md) | [rhwp-cli Skill 사용 가이드](rhwp_cli_skill_guide.md), [dump 명령 가이드](dump_command.md), [PNG 내보내기 가이드](export_png_command.md) |
| 로컬 OWPML XML 스키마 자산 | [OWPML XML 스키마 reference](owpml_schema_reference.md) | [한컴 공식 OWPML 모델 참조 가이드](../tech/hwpx_hancom_reference.md) |
| PDF/SVG 기준 비교의 정책 | [시각 검증 문서 지도](verification/README.md) | [시각 검증 거버넌스](verification/visual_verification_governance.md), [PDF/SVG visual sweep 가이드](verification/visual_sweep_guide.md) |
| 한컴 기준 PDF 산출을 위한 MCP 사용 | [HWP 2020 MCP 사용법](mcp_hwp2020Convert_usage.md) | [PR 리뷰·통합 워크플로우](pr_review_workflow.md)의 기준 PDF 절 |
| 브라우저 확장 개발·배포 | [브라우저 확장 개발 가이드](browser_extension_dev_guide.md) | [Chrome/Edge 확장 빌드·배포](chrome_edge_extension_build_deploy.md) |
| release 준비와 배포 | [배포 가이드](publish_guide.md) | [개발 환경 가이드](dev_environment_guide.md) |
| rhwp-studio UI 명칭·CSS 접두어 | [rhwp-studio UI 명칭과 CSS 접두어](rhwp_studio_ui_conventions.md) | [개발 환경 가이드](dev_environment_guide.md) |

## 문서 경계

- `manual/`: 사람이 반복 수행하는 절차, 명령, 검증, 배포, 운영 규칙
- `manual/codex/`: Codex 부트스트랩과 현행 문서·Git 절차. 종료 세션과 task memory는 `archive/`의
  historical snapshot이며 현재 절차의 근거로 사용하지 않는다.
- `manual/memory/`: 과거 사용자 피드백과 프로젝트 memory의 출처를 보존하는 historical 색인이다.
  현행 규칙은 canonical manual에서 확인한다.
- `tech/`: 포맷 사실, 아키텍처, 설계 결정, 이슈 조사 근거
- `tech/investigations/`: 특정 이슈의 가설·실험·관찰을 보존한다. 미확정 또는 기각 결론을 포함할 수 있으며
  반복 작업의 지침이나 장기 계약의 권위 문서는 아니다.
- `troubleshootings/`: 재현 가능한 증상, 확정 원인, 적용 가능한 대응과 검증 방법을 보존한다. 이후 작업의
  사전 점검 자료로 사용한다.

조사 또는 트러블슈팅에서 장기 계약·스펙 정정·운영 절차가 확정되면 각각의 canonical 문서에 반영하고,
원 문서는 근거 링크로 남긴다.

## 문서 역할과 생명주기

문서의 역할과 생명주기를 한 `상태` 값으로 섞지 않는다. 메타 블록을 추가하거나 갱신할 때는 아래 값을
사용한다.

| 필드 | 허용 값 | 의미 |
| --- | --- | --- |
| `kind` | `canonical`, `guide`, `reference`, `investigation`, `decision`, `snapshot`, `memory` | 문서가 수행하는 역할 |
| `status` | `active`, `historical`, `superseded` | 현재 사용 가능성 |
| `canonical` | 저장소 상대 경로 | 더 상세한 문서가 따르는 권위 문서 |
| `last_verified` | `YYYY-MM-DD` | 사실 또는 절차를 마지막으로 확인한 날짜 |

canonical manifest, CLI·시각 검증 클러스터와 분류가 끝난 조사·보관·트러블슈팅 문서는 이 메타를
CI에서 검사한다. 나머지 legacy 문서는 클러스터별 현행성 감사에서 실제 내용과 참조 관계를 확인한 뒤
검사 범위에 추가한다.

## CLI 문서 역할

- [CLI 명령어 매뉴얼](cli_commands.md)은 명령·옵션의 canonical reference다. 옵션 추가·변경 시
  `rhwp --help`와 함께 현행화한다.
- [rhwp-cli Skill 사용 가이드](rhwp_cli_skill_guide.md)는 자연어 요청, Skill 호출, 대표 예제와
  디버깅 순서를 설명한다. 전체 옵션을 다시 열거하지 않는다.
- [dump](dump_command.md), [export-png](export_png_command.md), [ir-diff](ir_diff_command.md) 매뉴얼은
  각 명령의 출력 형식·환경·트러블슈팅을 상세화한다.

## 링크와 이동 규칙

파일 이동 전과 후에 다음 명령으로 루트 안내 문서와 `mydocs/manual`·`mydocs/tech`의 상대 Markdown·이미지
링크를 점검한다.

```bash
python3 scripts/check_markdown_links.py
```

이 검사는 외부 URL과 같은 문서 안의 앵커를 검사하지 않는다. 저장소 내부 링크는 이동 PR에서 모두 새 경로로
갱신하며, redirect stub은 GitHub 이슈·PR 같은 외부 이력에서 자주 참조되는 문서만 별도 allowlist로 유지한다.
이동 stage에서는 `--forbid-path <이전-경로>`로 재참조가 없는지 일회성 검증한다. 새 문서 추가나 이전
경로 검증 때문에 workflow YAML을 수정하지 않는다.
