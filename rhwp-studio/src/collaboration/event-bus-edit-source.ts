import type { EventBus } from '../core/event-bus.ts';
import type { CollaborationEditableChange, CollaborationEditSource } from './editable-change.ts';
export const COLLABORATION_EDITABLE_CHANGED_EVENT = 'collaboration-editable-changed';
export class EventBusCollaborationEditSource implements CollaborationEditSource {
  private readonly eventBus: EventBus;
  constructor(eventBus: EventBus) { this.eventBus = eventBus; }
  subscribe(handler: (change: CollaborationEditableChange) => void): () => void {
    return this.eventBus.on(COLLABORATION_EDITABLE_CHANGED_EVENT, (value) => handler(value as CollaborationEditableChange));
  }
}
