import type { CollaborationDocumentAdapter } from './document-adapter.ts';
import type { LocalEditObserver } from './local-edit-observer.ts';
import type { CollaborationTransport } from './transport.ts';
import type { CollaborationUpdateFactory } from './update-factory.ts';
export class LocalCollaborationController {
  private readonly observer: LocalEditObserver;
  private readonly factory: CollaborationUpdateFactory;
  private readonly transport: CollaborationTransport;
  private readonly adapter: Pick<CollaborationDocumentAdapter, 'applyRemoteUpdate'>;
  private stopLocal?: () => void;
  private stopRemote?: () => void;
  private running = false;
  constructor(observer: LocalEditObserver, factory: CollaborationUpdateFactory, transport: CollaborationTransport, adapter: Pick<CollaborationDocumentAdapter, 'applyRemoteUpdate'>) { this.observer=observer; this.factory=factory; this.transport=transport; this.adapter=adapter; }
  start(sessionId: string): void { if (this.running) throw new Error('collaboration controller already started'); this.running=true; this.transport.connect(sessionId); this.stopLocal=this.observer.subscribe((edit)=>this.transport.send(this.factory.create(edit.nodeId, edit.nodeKind, edit.text))); this.stopRemote=this.transport.subscribe((update)=>this.adapter.applyRemoteUpdate(update)); this.observer.start(); }
  stop(): void { if (!this.running) return; this.observer.stop(); this.stopLocal?.(); this.stopRemote?.(); this.transport.disconnect(); this.stopLocal=undefined; this.stopRemote=undefined; this.running=false; }
}
