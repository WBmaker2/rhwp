import type { RemoteParticipant } from './PresenceController';

const PALETTE = [
  '#d32f2f', '#7b1fa2', '#303f9f', '#1976d2', '#00796b',
  '#388e3c', '#f57c00', '#e64a19', '#5d4037', '#455a64',
] as const;

export interface RemoteCursorRect {
  left: number;
  top: number;
  height: number;
}

export type RemoteCursorResolver = (
  participant: RemoteParticipant,
) => RemoteCursorRect | null;

export class RemoteCursorLayer {
  readonly element: HTMLDivElement;

  constructor(
    parent: HTMLElement,
    private readonly resolve: RemoteCursorResolver,
  ) {
    this.element = document.createElement('div');
    this.element.id = 'collaboration-remote-cursors';
    Object.assign(this.element.style, {
      position: 'absolute',
      inset: '0',
      pointerEvents: 'none',
      zIndex: '9000',
    });
    if (getComputedStyle(parent).position === 'static') parent.style.position = 'relative';
    parent.append(this.element);
  }

  render(participants: RemoteParticipant[]): void {
    const cursors: HTMLElement[] = [];
    for (const participant of participants) {
      const rect = this.resolve(participant);
      if (!rect) continue;
      const cursor = document.createElement('div');
      const color = PALETTE[participant.state.colorIndex];
      Object.assign(cursor.style, {
        position: 'absolute',
        left: `${rect.left}px`,
        top: `${rect.top}px`,
        width: '2px',
        height: `${Math.max(12, rect.height)}px`,
        background: color,
      });
      const label = document.createElement('span');
      label.textContent = participant.state.displayName || participant.state.userId;
      Object.assign(label.style, {
        position: 'absolute',
        left: '0',
        top: '-18px',
        padding: '1px 4px',
        borderRadius: '3px 3px 3px 0',
        color: '#fff',
        background: color,
        font: '11px system-ui, sans-serif',
        whiteSpace: 'nowrap',
      });
      cursor.append(label);
      cursors.push(cursor);
    }
    this.element.replaceChildren(...cursors);
  }

  destroy(): void {
    this.element.remove();
  }
}
