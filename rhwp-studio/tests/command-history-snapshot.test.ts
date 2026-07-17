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
// 본문으로 범위를 좁힌다.
const snapClassStart = commandFull.indexOf('export class SnapshotCommand');
assert.notEqual(snapClassStart, -1, 'SnapshotCommand 클래스 not found');
const command = commandFull.slice(snapClassStart);

test('[결함2] undo 는 op 성공 후에만 스택을 이동한다(pop-먼저 금지)', () => {
  const block = methodBlock(history, 'undo(wasm: WasmBridge): DocumentPosition | null {');
  // 참조 읽기(peek) → command.undo → pop → redo.push 순서.
  const idxPeek = block.indexOf('this.undoStack[this.undoStack.length - 1]');
  const idxUndoCall = block.indexOf('command.undo(wasm)');
  const idxPop = block.indexOf('this.undoStack.pop()');
  const idxRedoPush = block.indexOf('this.redoStack.push(command)');
  assert.ok(idxPeek !== -1 && idxUndoCall !== -1 && idxPop !== -1 && idxRedoPush !== -1,
    'undo 가 peek/undo/pop/redo.push 를 모두 포함해야 함');
  assert.ok(idxPeek < idxUndoCall && idxUndoCall < idxPop && idxPop < idxRedoPush,
    'undo 예외 안전 순서 위반: peek → command.undo → pop → redo.push 여야 함');
  assert.ok(!/const command = this\.undoStack\.pop\(\);[\s\S]*command\.undo/.test(block),
    'pop-먼저(pop 후 undo) 패턴이 남아있음 — 예외 시 엔트리 유실');
});

test('[결함2] redo 도 execute 성공 후에만 스택을 이동한다', () => {
  const block = methodBlock(history, 'redo(wasm: WasmBridge): DocumentPosition | null {');
  const idxPeek = block.indexOf('this.redoStack[this.redoStack.length - 1]');
  const idxExec = block.indexOf('command.execute(wasm)');
  const idxPop = block.indexOf('this.redoStack.pop()');
  const idxUndoPush = block.indexOf('this.undoStack.push(command)');
  assert.ok(idxPeek < idxExec && idxExec < idxPop && idxPop < idxUndoPush,
    'redo 예외 안전 순서 위반: peek → execute → pop → undo.push 여야 함');
});

test('[결함3] SnapshotCommand.execute 는 operation throw 시 before 스냅샷을 해제한다', () => {
  const block = methodBlock(command, 'execute(wasm: WasmBridge): DocumentPosition {');
  assert.match(block, /this\.beforeId = wasm\.saveSnapshot\(\);/, 'before 저장이 있어야 함');
  // saveSnapshot(before) 이후 operation 을 try/catch 로 감싸 discard + rethrow.
  assert.match(block, /try\s*\{[\s\S]*this\.operation\(wasm\)[\s\S]*\}\s*catch[\s\S]*discardSnapshot\(this\.beforeId\)[\s\S]*throw/,
    'operation 을 try/catch 로 감싸 throw 시 beforeId discard 후 rethrow 해야 함');
});

test('[결함1] CommandHistory 는 WASM 상한과 정합된 스냅샷 예산으로 front 를 축출한다', () => {
  assert.match(history, /const SNAPSHOT_ID_BUDGET = 100;/,
    'WASM MAX_SNAPSHOTS(100) 와 정합된 JS 예산 상수가 있어야 함');
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
