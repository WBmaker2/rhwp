import type { WasmBridge } from '@/core/wasm-bridge';
import type { DocumentPosition } from '@/core/types';
import { NO_TEXT_MUTATION_EFFECTS } from './command';
import type { EditCommand, TextMutationEffects } from './command';

/** 스택 내 모든 명령의 discard()를 호출하여 리소스 해제 */
function discardAll(stack: EditCommand[], wasm: WasmBridge): void {
  for (const cmd of stack) {
    cmd.discard?.(wasm);
  }
}

/**
 * [Task #2328] WASM 스냅샷 저장소 상한(document.rs 의 MAX_SNAPSHOTS)과 정합시킬
 * JS 측 스냅샷 id 예산. JS 가 이 예산을 넘기 전에 undo 스택 front 를 축출해
 * 스냅샷을 discard 하므로, WASM store 는 이 값을 넘지 않고 WASM 자체의 무통보
 * 축출은 결코 발동하지 않는다(축출된 스냅샷 restore 실패로 undo 가 예외·엔트리
 * 유실되던 결함 #2328 의 근원 제거). 값 변경 시 document.rs 와 함께 갱신한다.
 */
const SNAPSHOT_ID_BUDGET = 100;

/** Undo/Redo 히스토리 관리 */
export class CommandHistory {
  private undoStack: EditCommand[] = [];
  private redoStack: EditCommand[] = [];
  private maxSize = 1000;
  private lastExecutionEffects: TextMutationEffects = NO_TEXT_MUTATION_EFFECTS;

  /** undo/redo 양 스택의 살아있는 스냅샷 id 총합. */
  private liveSnapshotIds(): number {
    let n = 0;
    for (const cmd of this.undoStack) n += cmd.snapshotResourceCount?.() ?? 0;
    for (const cmd of this.redoStack) n += cmd.snapshotResourceCount?.() ?? 0;
    return n;
  }

  /**
   * [Task #2328] 스냅샷 id 총합이 예산을 넘으면 undo 스택 front(최오래)부터
   * 연속 축출한다. front 축출은 contiguous 하므로 bounded-history 시멘틱을
   * 지키며(오래된 것부터 사라짐), 스냅샷 커맨드를 discard 해 WASM id 를 즉시
   * 반환한다. 텍스트 커맨드가 front 에 있으면 함께 밀려나지만(0 id) 오래된
   * 순서라 정합적이다. redo 스택은 새 명령 실행 시 항상 비워지므로 여기서만
   * front 를 다룬다.
   */
  private enforceSnapshotBudget(wasm: WasmBridge): void {
    while (this.liveSnapshotIds() > SNAPSHOT_ID_BUDGET && this.undoStack.length > 1) {
      const evicted = this.undoStack.shift();
      evicted?.discard?.(wasm);
    }
  }

  private captureExecutionEffects(command: EditCommand): void {
    this.lastExecutionEffects =
      command.consumeTextMutationEffects?.() ?? NO_TEXT_MUTATION_EFFECTS;
  }

  /** 직전 execute/redo의 effect를 한 번만 소비한다. */
  consumeLastExecutionEffects(): TextMutationEffects {
    const effects = this.lastExecutionEffects;
    this.lastExecutionEffects = NO_TEXT_MUTATION_EFFECTS;
    return effects;
  }

  /** 명령 실행 + 히스토리 기록. 실행 후 커서 위치 반환 */
  execute(command: EditCommand, wasm: WasmBridge): DocumentPosition {
    this.lastExecutionEffects = NO_TEXT_MUTATION_EFFECTS;
    const cursorAfter = command.execute(wasm);
    this.captureExecutionEffects(command);

    // 직전 명령과 병합 시도
    if (this.undoStack.length > 0) {
      const last = this.undoStack[this.undoStack.length - 1];
      const merged = last.mergeWith(command);
      if (merged) {
        this.undoStack[this.undoStack.length - 1] = merged;
        // redo 스택 정리 (리소스 해제 후 비움)
        discardAll(this.redoStack, wasm);
        this.redoStack = [];
        return cursorAfter;
      }
    }

    this.undoStack.push(command);
    // redo 스택 정리 (새 명령 실행 시 redo 불가)
    discardAll(this.redoStack, wasm);
    this.redoStack = [];

    // 크기 제한 — eviction 시 리소스 해제
    if (this.undoStack.length > this.maxSize) {
      const evicted = this.undoStack.shift();
      evicted?.discard?.(wasm);
    }
    // [Task #2328] 스냅샷 예산 정합 — WASM 상한 초과 전에 front 축출.
    this.enforceSnapshotBudget(wasm);

    return cursorAfter;
  }

  /** Undo — 성공 시 커서 위치 반환, 스택 비었으면 null */
  undo(wasm: WasmBridge): DocumentPosition | null {
    this.lastExecutionEffects = NO_TEXT_MUTATION_EFFECTS;
    const command = this.undoStack[this.undoStack.length - 1];
    if (!command) return null;

    // [Task #2328] op 성공 후에만 스택을 이동한다. command.undo() 가 예외를
    // 던지면(예: 축출된 스냅샷 restore 실패) 스택을 건드리지 않고 전파해
    // 엔트리 소실을 막는다 (종전 pop-먼저는 예외 시 엔트리를 유실했다).
    const cursorAfter = command.undo(wasm);
    this.undoStack.pop();
    this.redoStack.push(command);
    return cursorAfter;
  }

  /** Redo — 성공 시 커서 위치 반환, 스택 비었으면 null */
  redo(wasm: WasmBridge): DocumentPosition | null {
    this.lastExecutionEffects = NO_TEXT_MUTATION_EFFECTS;
    const command = this.redoStack[this.redoStack.length - 1];
    if (!command) return null;

    // [Task #2328] undo 와 동일 — execute() 성공 후에만 스택 이동.
    const cursorAfter = command.execute(wasm);
    this.captureExecutionEffects(command);
    this.redoStack.pop();
    this.undoStack.push(command);
    return cursorAfter;
  }

  /** execute() 없이 히스토리에만 기록 (IME compositionend용 — 텍스트가 이미 문서에 있는 경우) */
  recordWithoutExecute(command: EditCommand, wasm?: WasmBridge): void {
    this.lastExecutionEffects = NO_TEXT_MUTATION_EFFECTS;
    // 직전 명령과 병합 시도
    if (this.undoStack.length > 0) {
      const last = this.undoStack[this.undoStack.length - 1];
      const merged = last.mergeWith(command);
      if (merged) {
        this.undoStack[this.undoStack.length - 1] = merged;
        if (wasm) {
          discardAll(this.redoStack, wasm);
        }
        this.redoStack = [];
        return;
      }
    }

    this.undoStack.push(command);
    if (wasm) {
      discardAll(this.redoStack, wasm);
    }
    this.redoStack = [];

    if (this.undoStack.length > this.maxSize) {
      const evicted = this.undoStack.shift();
      if (wasm) evicted?.discard?.(wasm);
    }
  }

  canUndo(): boolean { return this.undoStack.length > 0; }
  canRedo(): boolean { return this.redoStack.length > 0; }

  /** 히스토리 초기화 (문서 로드 시). wasm이 있으면 스냅샷 리소스도 해제. */
  clear(wasm?: WasmBridge): void {
    if (wasm) {
      discardAll(this.undoStack, wasm);
      discardAll(this.redoStack, wasm);
    }
    this.undoStack = [];
    this.redoStack = [];
    this.lastExecutionEffects = NO_TEXT_MUTATION_EFFECTS;
  }
}
