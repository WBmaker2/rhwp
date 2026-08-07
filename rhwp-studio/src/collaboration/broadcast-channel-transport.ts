import type { CollaborationTextUpdate } from './update.ts';
import type { BroadcastChannelFactory, BroadcastChannelLike, CollaborationTransport, CollaborationUpdateHandler } from './transport.ts';
export class BroadcastChannelCollaborationTransport implements CollaborationTransport {
  private channel?: BroadcastChannelLike; private readonly handlers=new Set<CollaborationUpdateHandler>(); private readonly seen=new Set<string>();
  private readonly listener=(event:{data:unknown})=>{ const u=event.data as Partial<CollaborationTextUpdate>; if (!u || typeof u !== 'object' || u.clientId===this.clientId || typeof u.updateId!=='string' || this.seen.has(u.updateId)) return; this.seen.add(u.updateId); for (const h of this.handlers) { try { h(u as CollaborationTextUpdate); } catch {} } };
  private readonly clientId: string; private readonly factory: BroadcastChannelFactory;
  constructor(clientId:string, factory:BroadcastChannelFactory=(name)=>new BroadcastChannel(name) as unknown as BroadcastChannelLike) { this.clientId=clientId; this.factory=factory; }
  connect(sessionId:string):void { this.disconnect(); this.channel=this.factory(`rhwp-collaboration:${sessionId}`); this.channel.addEventListener('message', this.listener); }
  send(update:CollaborationTextUpdate):void { if (!this.channel) throw new Error('transport is not connected'); this.seen.add(update.updateId); this.channel.postMessage(update); }
  subscribe(handler:CollaborationUpdateHandler):()=>void { this.handlers.add(handler); return ()=>this.handlers.delete(handler); }
  disconnect():void { if (this.channel) { this.channel.removeEventListener('message', this.listener); this.channel.close(); this.channel=undefined; } this.seen.clear(); }
}
