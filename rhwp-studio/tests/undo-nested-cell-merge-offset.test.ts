import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

// 중첩 표 셀 문단 병합의 undo 분할점 축 일치 가드.
//
// DocumentPosition 의 flat 필드(controlIndex/cellIndex)는 주석대로 "외부 표 기준" 레거시
// 좌표라(core/types.ts) 중첩 셀(cellPath.length > 1)에서는 안쪽 셀을 가리키지 못한다.
// MergeParagraphInCellCommand 는 뮤테이션을 mergeParagraphInCellByPath 로 분기하면서
// undo 가 쓸 mergePointOffset 만 flat getCellParagraphLength 로 읽고 있었다.
//
//   중첩 표 안쪽 셀의 2번째 문단 시작에서 Backspace → Ctrl+Z
//   기대: 병합 지점(안쪽 셀 1번째 문단 길이)에서 다시 분할
//   실제: 바깥 셀에서 읽은 길이로 분할 → 문단이 엉뚱한 지점에서 잘림
//
// cursor.ts 는 같은 상황에서 useCellPath 분기로 ...ByPath 를 짝지어 호출한다(:405-409,
// :686-688, :806-808). 그 축 일치를 이 커맨드에도 정적으로 핀한다.
// 행위 증명(중첩 표 왕복)은 브라우저 왕복(PR 검증).

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));
const commandSrc = readFileSync(join(rootDir, 'src/engine/command.ts'), 'utf8');

/** `export class NAME ...` 부터 다음 `export class` 전까지 클래스 본문을 추출. */
function classBlock(src: string, name: string): string {
  const start = src.indexOf(`export class ${name}`);
  assert.notEqual(start, -1, `${name} 클래스 not found`);
  const rel = src.slice(start + 1).indexOf('\nexport class ');
  return rel === -1 ? src.slice(start) : src.slice(start, start + 1 + rel);
}

const block = classBlock(commandSrc, 'MergeParagraphInCellCommand');
const executeBlock = block.slice(
  block.indexOf('execute(wasm: WasmBridge): DocumentPosition {'),
  block.indexOf('undo(wasm: WasmBridge): DocumentPosition {'),
);

test('중첩 셀 병합은 길이 조회도 ByPath 축으로 읽는다', () => {
  assert.match(executeBlock, /getCellParagraphLengthByPath\s*\(/,
    '중첩 셀에서는 ByPath 로 안쪽 셀 문단 길이를 읽어야 함');
  assert.match(executeBlock, /mergeParagraphInCellByPath\s*\(/, '중첩 뮤테이션 분기 유지');
});

test('flat 길이 조회가 중첩 분기 밖에서 무조건 실행되지 않는다', () => {
  // 무조건 실행되면 중첩 셀에서 바깥 표 기준 길이를 잡는다(회귀 형태).
  assert.doesNotMatch(
    executeBlock,
    /mergePointOffset = wasm\.getCellParagraphLength\(sec, ppi, pos\.controlIndex!, pos\.cellIndex!, cpi - 1\);\s*\n\s*if \(isNestedCell/,
    'flat 길이 조회를 isNestedCell 분기보다 앞에서 무조건 하면 중첩 셀에서 어긋난다',
  );

  // flat 조회는 비중첩(else) 분기 안에만 남아야 한다.
  const flatAt = executeBlock.search(/wasm\.getCellParagraphLength\(/);
  const byPathAt = executeBlock.search(/wasm\.getCellParagraphLengthByPath\(/);
  assert.ok(flatAt >= 0 && byPathAt >= 0, '두 조회 경로가 모두 존재해야 함');
  assert.ok(byPathAt < flatAt, 'ByPath(중첩) 분기가 flat(비중첩) 분기보다 앞에 와야 함');
});
