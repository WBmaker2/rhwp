import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

// [Task #2327] 계급 1(기록 옵트인) 회귀를 저작 시점에 차단하는 소스 가드.
//
// 두 정적 검사:
//  (1) 드리프트 — WasmBridge 의 문서-변경형 공개 메서드는 wasm-mutation-guard.ts 의
//      MUTATING_METHODS 또는 EXCLUDED_NON_DOCUMENT 중 하나에 반드시 분류돼야 한다.
//      새 뮤테이터가 목록에 안 잡히면 DEV 가드도 그 호출을 못 잡으므로, 분류 누락을
//      실패로 만든다.
//  (2) 원장 트립와이어 — ui/ + command/ 에서 뮤테이터를 직접 호출하는 표면(파일별
//      호출 수)을 동결한다. 신규 파일·증가는 실패 → 의식적 baseline 갱신 + 리뷰 강제.
//      (라우팅 경유 여부의 실제 판정은 런타임 DEV MutationGuard 가 담당한다 —
//      텍스트 카운트는 executeOperation 콜백 내부 호출도 세므로 이관해도 줄지 않는다.
//      따라서 이 원장은 "라우팅 여부"가 아니라 "뮤테이션 표면 증가"의 트립와이어다.)

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));

function source(rel: string): string {
  return readFileSync(join(rootDir, rel), 'utf8');
}

/** wasm-mutation-guard.ts 의 배열 상수를 단일 권위원으로 파싱한다. */
function parseStringArray(guardSrc: string, name: string): string[] {
  // `export const NAME ...= [ ... ];` 선언에 앵커(상단 주석의 이름 언급 회피).
  const m = guardSrc.match(new RegExp(`export const ${name}\\b[^=]*=\\s*\\[([\\s\\S]*?)\\];`));
  assert.ok(m, `${name} 상수를 파싱하지 못함`);
  return [...m![1].matchAll(/'([A-Za-z0-9_]+)'/g)].map((x) => x[1]);
}

const guardSrc = source('src/core/wasm-mutation-guard.ts');
const MUTATING = parseStringArray(guardSrc, 'MUTATING_METHODS');
const EXCLUDED = parseStringArray(guardSrc, 'EXCLUDED_NON_DOCUMENT');

// ── (1) 드리프트: 브리지 공개 메서드 분류 강제 ──────────────────────────────

/** WasmBridge 클래스 본문의 공개 메서드 이름을 추출한다(2칸 들여쓰기 최상위). */
function bridgePublicMethods(): string[] {
  const src = source('src/core/wasm-bridge.ts');
  const names = new Set<string>();
  const priv = new Set<string>();
  const re = /^ {2}(public |private |protected )?(async )?([a-zA-Z_]\w*)\s*\(/gm;
  for (const m of src.matchAll(re)) {
    const name = m[3];
    if (['constructor', 'if', 'for', 'while', 'switch', 'catch', 'return'].includes(name)) continue;
    if (m[1] === 'private ' || m[1] === 'protected ') priv.add(name);
    else names.add(name);
  }
  return [...names].filter((n) => !priv.has(n));
}

// 문서 변경을 시사하는 동사 접두어.
const MUTATING_VERB = /^(insert|delete|create|apply|add|remove|move|resize|merge|split|update|toggle|replace|paste|assign|group|ungroup|change|clear|evaluate|equalize|transpose|setPage|setSection|setColumn|setCell|setTable|setPicture|setShape|setEquation|setNote|setChar|setPara|setField|setForm|setNumbering|setHeaderFooter|setActiveField|renameBookmark|reflowLinesegs)/;

test('드리프트: 문서-변경형 브리지 공개 메서드는 모두 분류돼야 한다', () => {
  const classified = new Set([...MUTATING, ...EXCLUDED]);
  const unclassified = bridgePublicMethods()
    .filter((n) => MUTATING_VERB.test(n))
    .filter((n) => !classified.has(n));
  assert.deepEqual(
    unclassified,
    [],
    `WasmBridge 신규(?) 뮤테이터가 분류되지 않음: ${unclassified.join(', ')}\n` +
      `→ wasm-mutation-guard.ts 의 MUTATING_METHODS(기록 강제) 또는 ` +
      `EXCLUDED_NON_DOCUMENT(문서 비변경 사유)에 추가하라.`,
  );
});

test('MUTATING_METHODS / EXCLUDED_NON_DOCUMENT 는 서로 겹치지 않는다', () => {
  const dup = MUTATING.filter((m) => EXCLUDED.includes(m));
  assert.deepEqual(dup, [], `양쪽에 중복 분류됨: ${dup.join(', ')}`);
});

test('MUTATING_METHODS 는 모두 실제 브리지 공개 메서드여야 한다(rename 무통보 skip 방지)', () => {
  // installMutationGuard 는 `typeof original !== 'function'` 이면 조용히 건너뛴다.
  // 브리지에서 메서드가 rename/제거되면 목록의 옛 이름은 가드에서 무통보로
  // 비활성화되므로(가드 사각), 목록 항목이 전부 실재하는지 역방향으로 강제한다.
  const bridge = new Set(bridgePublicMethods());
  const missing = MUTATING.filter((m) => !bridge.has(m));
  assert.deepEqual(
    missing,
    [],
    `MUTATING_METHODS 에 브리지에 없는 이름: ${missing.join(', ')}\n` +
      `→ 브리지에서 rename/제거된 메서드. 목록을 갱신하라(방치 시 가드 무통보 비활성).`,
  );
});

// ── (2) 원장 트립와이어: 뮤테이션 표면 동결 ─────────────────────────────────

/** ui/ + command/ 하위 .ts 파일 나열(테스트 제외). */
function scanFiles(): string[] {
  const out: string[] = [];
  const walk = (rel: string) => {
    for (const ent of readdirSync(join(rootDir, rel), { withFileTypes: true })) {
      const child = `${rel}/${ent.name}`;
      if (ent.isDirectory()) walk(child);
      else if (ent.name.endsWith('.ts') && !ent.name.endsWith('.test.ts')) out.push(child);
    }
  };
  walk('src/ui');
  walk('src/command');
  return out.sort();
}

function mutatorCallCount(src: string): number {
  const re = new RegExp(`\\bwasm\\s*\\.\\s*(${MUTATING.join('|')})\\s*\\(`, 'g');
  return [...src.matchAll(re)].length;
}

// 뮤테이션 표면 원장 (2026-07-17 동결). 이관/추가 시 이 표를 의식적으로 갱신한다.
// 값을 낮추는 방향(이관)만 무해하며, 높이거나 신규 키 추가는 리뷰 대상이다.
const BASELINE: Readonly<Record<string, number>> = {
  'src/command/commands/edit.ts': 1,
  'src/command/commands/format.ts': 1,
  'src/command/commands/insert.ts': 19,
  'src/command/commands/page.ts': 13,
  'src/command/commands/table.ts': 33,
  'src/ui/bookmark-dialog.ts': 3,
  'src/ui/cell-border-bg-dialog.ts': 5,
  'src/ui/column-settings-dialog.ts': 1,
  'src/ui/endnote-shape-dialog.ts': 1,
  'src/ui/equation-editor-dialog.ts': 2,
  'src/ui/equation-props-dialog.ts': 2,
  'src/ui/find-dialog.ts': 4,
  'src/ui/formula-dialog.ts': 3,
  'src/ui/new-number-dialog.ts': 1,
  'src/ui/numbering-dialog.ts': 1,
  'src/ui/page-border-dialog.ts': 1,
  'src/ui/page-setup-dialog.ts': 1,
  'src/ui/picture-props-dialog.ts': 5,
  'src/ui/section-settings-dialog.ts': 2,
  'src/ui/style-dialog.ts': 1,
  'src/ui/style-edit-dialog.ts': 6,
  'src/ui/table-cell-props-dialog.ts': 2,
  'src/ui/toolbar.ts': 4,
};

test('뮤테이션 표면 원장: 신규·증가 사이트는 baseline 갱신을 강제한다', () => {
  const current: Record<string, number> = {};
  for (const rel of scanFiles()) {
    const n = mutatorCallCount(source(rel));
    if (n > 0) current[rel] = n;
  }

  const violations: string[] = [];
  for (const [rel, n] of Object.entries(current)) {
    const base = BASELINE[rel];
    if (base === undefined) {
      violations.push(`  + ${rel}: ${n} (신규 뮤테이션 파일 — executeOperation 라우팅 또는 baseline 등재 필요)`);
    } else if (n > base) {
      violations.push(`  ↑ ${rel}: ${base} → ${n} (뮤테이션 사이트 증가 — 라우팅 확인 또는 baseline 갱신)`);
    }
  }
  // 이관으로 값이 줄면 baseline 을 낮추라고 안내(실패는 아님 — 진행을 막지 않음).
  const stale: string[] = [];
  for (const [rel, base] of Object.entries(BASELINE)) {
    const n = current[rel] ?? 0;
    if (n < base) stale.push(`  ↓ ${rel}: ${base} → ${n} (이관 완료 — baseline 을 ${n}${n === 0 ? ' 로 낮추거나 키 제거' : ''} 로 갱신 권장)`);
  }

  assert.deepEqual(
    violations,
    [],
    `뮤테이션 표면이 baseline 을 초과했습니다:\n${violations.join('\n')}\n\n` +
      `새 문서 변경은 InputHandler.executeOperation 라우팅으로 undo 에 기록돼야 합니다(#2327).` +
      (stale.length ? `\n\n참고(이관 진행 — 실패 아님):\n${stale.join('\n')}` : ''),
  );

  if (stale.length) {
    // 진행 상황 가시화 — 실패시키지 않고 로그만.
    console.log(`[mutation-routing] 이관 진행:\n${stale.join('\n')}`);
  }
});
