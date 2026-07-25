import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  PresenceController,
  colorIndexForUser,
  isPresenceState,
} from '../src/collaboration/PresenceController.ts';

class FakeAwareness {
  readonly clientID = 1;
  readonly states = new Map<number, Record<string, unknown>>();
  private readonly listeners = new Set<() => void>();

  setLocalStateField(field: string, value: unknown): void {
    const state = this.states.get(this.clientID) ?? {};
    this.states.set(this.clientID, { ...state, [field]: value });
    for (const listener of this.listeners) listener();
  }

  getStates(): Map<number, Record<string, unknown>> {
    return this.states;
  }

  on(_event: 'change', listener: () => void): void {
    this.listeners.add(listener);
  }

  off(_event: 'change', listener: () => void): void {
    this.listeners.delete(listener);
  }
}

test('assigns a deterministic color from the ten-color palette', () => {
  const first = colorIndexForUser('user-123');
  const second = colorIndexForUser('user-123');

  assert.equal(first, second);
  assert(first >= 0 && first < 10);
});

test('publishes validated non-persistent local awareness state', () => {
  const awareness = new FakeAwareness();
  const controller = new PresenceController(awareness, {
    userId: 'owner-1',
    displayName: '문서 소유자',
    photoURL: null,
  }, () => new Date('2026-07-25T05:00:00.000Z'));

  controller.updateCursor({
    targetId: 'paragraph-1',
    targetKind: 'paragraph',
    anchorOffset: 2,
    headOffset: 5,
  });

  const state = awareness.getStates().get(1)?.presence;
  assert(isPresenceState(state));
  assert.deepEqual(state, {
    userId: 'owner-1',
    displayName: '문서 소유자',
    photoURL: null,
    colorIndex: colorIndexForUser('owner-1'),
    targetId: 'paragraph-1',
    targetKind: 'paragraph',
    anchorOffset: 2,
    headOffset: 5,
    lastActiveAt: '2026-07-25T05:00:00.000Z',
  });
  controller.destroy();
});

test('projects only valid remote participant states and excludes the local client', () => {
  const awareness = new FakeAwareness();
  const controller = new PresenceController(awareness, {
    userId: 'local-1',
    displayName: '나',
    photoURL: null,
  });
  awareness.states.set(2, {
    presence: {
      userId: 'remote-1',
      displayName: '원격 사용자',
      photoURL: null,
      colorIndex: 3,
      targetId: 'cell-1',
      targetKind: 'cell',
      anchorOffset: 1,
      headOffset: 1,
      lastActiveAt: '2026-07-25T05:00:00.000Z',
    },
  });
  awareness.states.set(3, { presence: { userId: '', colorIndex: 99 } });

  const participants = controller.getRemoteParticipants();

  assert.equal(participants.length, 1);
  assert.equal(participants[0].clientId, 2);
  assert.equal(participants[0].state.userId, 'remote-1');
  controller.destroy();
});
