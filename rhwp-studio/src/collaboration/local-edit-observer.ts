import type { CollaborationContext } from './collaboration-context.ts';
import type { CollaborationEditableChange, CollaborationEditSource } from './editable-change.ts';
import type { CollaborationTextReader } from './text-reader.ts';
export interface ObservedLocalEdit { nodeId: string; nodeKind: 'paragraph' | 'cell'; text: string; }
type Handler = (edit: ObservedLocalEdit) => void;
export class LocalEditObserver {
  private readonly source: CollaborationEditSource;
  private readonly reader: CollaborationTextReader;
  private readonly context: CollaborationContext;
  private readonly isApplyingRemote: () => boolean;
  private readonly debounceMs: number;
  private unsubscribe?: () => void;
  private readonly handlers = new Set<Handler>();
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly lastText = new Map<string, string>();
  private stoppedForStructure = false;
  constructor(source: CollaborationEditSource, reader: CollaborationTextReader, context: CollaborationContext, isApplyingRemote: () => boolean, debounceMs = 200) {
    this.source = source; this.reader = reader; this.context = context; this.isApplyingRemote = isApplyingRemote; this.debounceMs = debounceMs;
  }
  get isStoppedForStructureChange(): boolean { return this.stoppedForStructure; }
  start(): void { if (this.unsubscribe || this.stoppedForStructure) return; this.unsubscribe = this.source.subscribe((change) => this.onChange(change)); }
  stop(): void { this.flush(); this.unsubscribe?.(); this.unsubscribe = undefined; for (const timer of this.timers.values()) clearTimeout(timer); this.timers.clear(); }
  subscribe(handler: Handler): () => void { this.handlers.add(handler); return () => this.handlers.delete(handler); }
  flush(): void { for (const nodeId of [...this.timers.keys()]) this.emitNode(nodeId); }
  private onChange(change: CollaborationEditableChange): void {
    if (change.kind === 'structure') { this.stoppedForStructure = true; this.stop(); return; }
    if (this.isApplyingRemote()) return;
    const nodeId = this.findNodeId(change); if (!nodeId) return;
    const old = this.timers.get(nodeId); if (old) clearTimeout(old);
    this.timers.set(nodeId, setTimeout(() => this.emitNode(nodeId), this.debounceMs));
  }
  private findNodeId(change: Exclude<CollaborationEditableChange, {kind:'structure'}>): string | undefined {
    for (const [id, loc] of this.context.registry.entries()) {
      if (change.kind === 'paragraph' && loc.kind === 'paragraph' && loc.sectionIndex === change.sectionIndex && loc.paragraphIndex === change.paragraphIndex) return id;
      if (change.kind === 'cell' && loc.kind === 'cell' && loc.sectionIndex === change.sectionIndex && loc.hostParagraphIndex === change.hostParagraphIndex && loc.controlIndex === change.controlIndex && loc.cellIndex === change.cellIndex) return id;
    }
    return undefined;
  }
  private emitNode(nodeId: string): void {
    const timer = this.timers.get(nodeId); if (timer) clearTimeout(timer); this.timers.delete(nodeId);
    if (this.isApplyingRemote() || this.stoppedForStructure) return;
    const loc = this.context.registry.get(nodeId); if (!loc) return;
    const text = loc.kind === 'paragraph' ? this.reader.getParagraphText(nodeId) : this.reader.getCellText(nodeId);
    if (this.lastText.get(nodeId) === text) return;
    this.lastText.set(nodeId, text);
    for (const handler of this.handlers) handler({ nodeId, nodeKind: loc.kind, text });
  }
}
