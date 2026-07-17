import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

// [Task #2328] 스냅샷 상한 정합 + 예외 안전 스택 이동 소스 가드.
//
// node --test 는 strip-only TS 라 engine 클래스(parameter property 포함)를
// 실행할 수 없어, 이 저장소의 undo 테스트 관례대로 소스 배선을 검증한다.
// 행위 증명은 브라우저 실동작(수정 전/후 60회 스냅샷 + 오래된 undo 무예외)으로
// 별도 수행한다 (PR 검증 섹션).

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));
const source = (rel: string): string => readFileSync(join(rootDir, rel), 'utf8');

/** `undo(...) {` ~ 다음 메서드 전까지의 블록을 추출한다. */
function methodBlock(src: string, signature: string): string {
  const start = src.indexOf(signature);
  assert.notEqual(start, -1, `${signature} not found`);
  // 다음 최상위 메서드( '\n  ' 들여쓰기 + 식별자() ) 또는 클래스 끝까지.
  const next = src.slice(start + signature.length).search(/\n {2}[a-zA-Z][\w]*\(/);
  return next === -1 ? src.slice(start) : src.slice(start, start + signature.length + next);
}

const history = source('src/engine/history.ts');
const commandFull = source('src/engine/command.ts');
// execute/undo 시그니처가 커맨드 클래스마다 반복되므로 SnapshotCommand 클래스
// 본문으로 범위를 좁힌다(다음 export class 경계까지 — 뒤 클래스로의 누출 방지).
const snapClassStart = commandFull.indexOf('export class SnapshotCommand');
assert.notEqual(snapClassStart, -1, 'SnapshotCommand 클래스 not found');
const snapClassEndRel = commandFull.slice(snapClassStart + 1).indexOf('\nexport class ');
const command = snapClassEndRel === -1
  ? commandFull.slice(snapClassStart)
  : commandFull.slice(snapClassStart, snapClassStart + 1 + snapClassEndRel);

test('[결함2] undo 는 op-우선 + 실패시-드롭 하이브리드다(pop-먼저 금지, 락업 금지)', () => {
  const block = methodBlock(history, 'undo(wasm: WasmBridge): DocumentPosition | null {');
  // 성공 경로: peek → try{command.undo} → pop → redo.push.
  const idxPeek = block.indexOf('this.undoStack[this.undoStack.length - 1]');
  const idxUndoCall = block.indexOf('command.undo(wasm)');
  const idxRedoPush = block.indexOf('this.redoStack.push(command)');
  assert.ok(idxPeek !== -1 && idxUndoCall !== -1 && idxRedoPush !== -1);
  assert.ok(idxPeek < idxUndoCall && idxUndoCall < idxRedoPush,
    'peek → command.undo → redo.push 순서여야 함');
  // op 전에 pop 하지 않는다(성공 엔트리 무손실).
  assert.ok(!/const command = this\.undoStack\.pop\(\);[\s\S]*command\.undo/.test(block),
    'pop-먼저(pop 후 undo) 패턴 잔존');
  // 실패 경로: try/catch 로 오염 엔트리를 pop+discard 후 전파(락업 방지).
  assert.match(block, /try\s*\{[\s\S]*command\.undo\(wasm\)[\s\S]*\}\s*catch[\s\S]*this\.undoStack\.pop\(\)[\s\S]*discard\?\.\(wasm\)[\s\S]*throw/,
    'undo 실패 시 오염 엔트리 드롭(pop+discard+throw)이 없으면 세션 undo 락업');
});

test('[결함2] redo 도 execute-우선 + 실패시-드롭 하이브리드다', () => {
  const block = methodBlock(history, 'redo(wasm: WasmBridge): DocumentPosition | null {');
  const idxPeek = block.indexOf('this.redoStack[this.redoStack.length - 1]');
  const idxExec = block.indexOf('command.execute(wasm)');
  const idxUndoPush = block.indexOf('this.undoStack.push(command)');
  assert.ok(idxPeek < idxExec && idxExec < idxUndoPush,
    'peek → execute → undo.push 순서여야 함');
  assert.match(block, /try\s*\{[\s\S]*command\.execute\(wasm\)[\s\S]*\}\s*catch[\s\S]*this\.redoStack\.pop\(\)[\s\S]*discard\?\.\(wasm\)[\s\S]*throw/,
    'redo 실패 시 오염 엔트리 드롭이 없으면 락업');
});

test('[결함3] SnapshotCommand.execute 는 operation throw 시 before 스냅샷을 해제한다', () => {
  const block = methodBlock(command, 'execute(wasm: WasmBridge): DocumentPosition {');
  assert.match(block, /this\.beforeId = wasm\.saveSnapshot\(\);/, 'before 저장이 있어야 함');
  // saveSnapshot(before) 이후 operation 을 try/catch 로 감싸 discard + rethrow.
  assert.match(block, /try\s*\{[\s\S]*this\.operation\(wasm\)[\s\S]*\}\s*catch[\s\S]*discardSnapshot\(this\.beforeId\)[\s\S]*throw/,
    'operation 을 try/catch 로 감싸 throw 시 beforeId discard 후 rethrow 해야 함');
});

test('[결함1] 스냅샷 예산은 WASM 상한에서 순간 +2 여유를 뺀 값이다', () => {
  // 새 SnapshotCommand.execute 는 before/after 2개를 예산 강제 이전에 저장하므로,
  // 예산 == MAX 면 그 순간 store 가 MAX 초과 → WASM 무통보 축출 → orphan.
  // 예산 = MAX - 2 여야 순간 +2 가 MAX 를 넘지 않는다(인터리브 회귀 근절).
  assert.match(history, /const WASM_MAX_SNAPSHOTS = 100;/,
    'WASM MAX_SNAPSHOTS(document.rs) 미러 상수가 있어야 함');
  assert.match(history, /const SNAPSHOT_ID_BUDGET = WASM_MAX_SNAPSHOTS - 2;/,
    '예산은 MAX - 2 (순간 +2 여유) 여야 함 — MAX 와 같으면 orphan 회귀');
  // 예산 강제 헬퍼: 예산 초과 시 undo 스택 front 를 shift + discard.
  const block = methodBlock(history, 'enforceSnapshotBudget(wasm: WasmBridge): void {');
  assert.match(block, /liveSnapshotIds\(\)\s*>\s*SNAPSHOT_ID_BUDGET/, '예산 초과 판정');
  assert.match(block, /this\.undoStack\.shift\(\)/, 'front 축출(shift)');
  assert.match(block, /discard\?\.\(wasm\)/, '축출 시 스냅샷 discard');
  // execute 경로가 예산을 강제해야 한다.
  const exec = methodBlock(history, 'execute(command: EditCommand, wasm: WasmBridge): DocumentPosition {');
  assert.match(exec, /this\.enforceSnapshotBudget\(wasm\)/, 'execute 가 예산을 강제해야 함');
});

test('SnapshotCommand 는 점유 스냅샷 id 수를 보고한다(예산 계산용)', () => {
  const block = methodBlock(command, 'snapshotResourceCount(): number {');
  assert.match(block, /beforeId !== null[\s\S]*afterId !== null/, 'before/after 살아있는 id 수 반환');
});
