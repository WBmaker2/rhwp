export type PresenceTargetKind = 'paragraph' | 'cell';

export interface PresenceIdentity {
  userId: string;
  displayName: string;
  photoURL: string | null;
}

export interface PresenceCursor {
  targetId: string;
  targetKind: PresenceTargetKind;
  anchorOffset: number;
  headOffset: number;
}

export interface PresenceState extends PresenceIdentity, PresenceCursor {
  colorIndex: number;
  lastActiveAt: string;
}

export interface RemoteParticipant {
  clientId: number;
  state: PresenceState;
}

export interface AwarenessPort {
  clientID: number;
  setLocalStateField(field: string, value: unknown): void;
  getStates(): Map<number, Record<string, unknown>>;
  on(event: 'change', listener: () => void): void;
  off(event: 'change', listener: () => void): void;
}

export function colorIndexForUser(userId: string): number {
  let hash = 2166136261;
  for (let index = 0; index < userId.length; index += 1) {
    hash ^= userId.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) % 10;
}

export function isPresenceState(value: unknown): value is PresenceState {
  if (!value || typeof value !== 'object') return false;
  const state = value as Partial<PresenceState>;
  return typeof state.userId === 'string'
    && state.userId.length > 0
    && typeof state.displayName === 'string'
    && (state.photoURL === null || typeof state.photoURL === 'string')
    && Number.isInteger(state.colorIndex)
    && Number(state.colorIndex) >= 0
    && Number(state.colorIndex) < 10
    && typeof state.targetId === 'string'
    && state.targetId.length > 0
    && (state.targetKind === 'paragraph' || state.targetKind === 'cell')
    && Number.isSafeInteger(state.anchorOffset)
    && Number(state.anchorOffset) >= 0
    && Number.isSafeInteger(state.headOffset)
    && Number(state.headOffset) >= 0
    && typeof state.lastActiveAt === 'string'
    && !Number.isNaN(Date.parse(state.lastActiveAt));
}

export class PresenceController {
  private readonly listeners = new Set<(participants: RemoteParticipant[]) => void>();

  private readonly onAwarenessChange = (): void => {
    const participants = this.getRemoteParticipants();
    for (const listener of this.listeners) listener(participants);
  };

  constructor(
    private readonly awareness: AwarenessPort,
    private readonly identity: PresenceIdentity,
    private readonly now: () => Date = () => new Date(),
  ) {
    if (!identity.userId.trim()) throw new Error('presence userId must not be empty');
    awareness.on('change', this.onAwarenessChange);
  }

  updateCursor(cursor: PresenceCursor): void {
    const state: PresenceState = {
      ...this.identity,
      colorIndex: colorIndexForUser(this.identity.userId),
      targetId: cursor.targetId,
      targetKind: cursor.targetKind,
      anchorOffset: normalizeOffset(cursor.anchorOffset),
      headOffset: normalizeOffset(cursor.headOffset),
      lastActiveAt: this.now().toISOString(),
    };
    if (!isPresenceState(state)) throw new Error('invalid collaboration presence state');
    this.awareness.setLocalStateField('presence', state);
  }

  clearCursor(): void {
    this.awareness.setLocalStateField('presence', null);
  }

  getRemoteParticipants(): RemoteParticipant[] {
    const participants: RemoteParticipant[] = [];
    for (const [clientId, awarenessState] of this.awareness.getStates()) {
      if (clientId === this.awareness.clientID) continue;
      const state = awarenessState.presence;
      if (isPresenceState(state)) participants.push({ clientId, state });
    }
    return participants.sort((left, right) => {
      const byName = left.state.displayName.localeCompare(right.state.displayName, 'ko');
      return byName || left.state.userId.localeCompare(right.state.userId);
    });
  }

  subscribe(listener: (participants: RemoteParticipant[]) => void): () => void {
    this.listeners.add(listener);
    listener(this.getRemoteParticipants());
    return () => this.listeners.delete(listener);
  }

  destroy(): void {
    this.clearCursor();
    this.awareness.off('change', this.onAwarenessChange);
    this.listeners.clear();
  }
}

function normalizeOffset(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.trunc(value));
}
