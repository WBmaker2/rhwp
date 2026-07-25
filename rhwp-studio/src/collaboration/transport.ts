import type { CollaborationTextUpdate } from './update.ts';
export type CollaborationUpdateHandler=(update: CollaborationTextUpdate)=>void;
export interface CollaborationTransport { connect(sessionId:string):void; send(update:CollaborationTextUpdate):void; subscribe(handler:CollaborationUpdateHandler):()=>void; disconnect():void; }
export interface BroadcastChannelLike { postMessage(value:unknown):void; close():void; addEventListener(type:'message', handler:(event:{data:unknown})=>void):void; removeEventListener(type:'message', handler:(event:{data:unknown})=>void):void; }
export type BroadcastChannelFactory=(name:string)=>BroadcastChannelLike;
