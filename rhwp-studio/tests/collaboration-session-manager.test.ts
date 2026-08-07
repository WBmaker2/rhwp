import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { CollaborationSessionManager } from '../src/collaboration/collaboration-session-manager.ts';

class FakeEventBus {
  private readonly handlers = new Map<string, Set<(...args: unknown[]) => void>>();

  on(event: string, handler: (...args: unknown[]) => void): () => void {
    const handlers = this.handlers.get(event) ?? new Set();
    handlers.add(handler);
    this.handlers.set(event, handlers);
    return () => handlers.delete(handler);
  }

  emit(event: string, ...args: unknown[]): void {
    for (const handler of [...(this.handlers.get(event) ?? [])]) handler(...args);
  }

  listenerCount(): number {
    let count = 0;
    for (const handlers of this.handlers.values()) count += handlers.size;
    return count;
  }
}

class FakeWindow {
  private readonly handlers = new Map<string, Set<(event: Event) => void>>();

  addEventListener(type: string, handler: EventListenerOrEventListenerObject): void {
    const handlers = this.handlers.get(type) ?? new Set();
    handlers.add(handler as (event: Event) => void);
    this.handlers.set(type, handlers);
  }

  removeEventListener(type: string, handler: EventListenerOrEventListenerObject): void {
    this.handlers.get(type)?.delete(handler as (event: Event) => void);
  }

  emit(type: string): void {
    for (const handler of [...(this.handlers.get(type) ?? [])]) handler(new Event(type));
  }

  listenerCount(): number {
    let count = 0;
    for (const handlers of this.handlers.values()) count += handlers.size;
    return count;
  }
}

function fixture(bootstrap?: () => Promise<() => void>) {
  const eventBus = new FakeEventBus();
  const windowLike = new FakeWindow();
  let bootstraps = 0;
  let destroys = 0;
  const manager = new CollaborationSessionManager({
    runtime: {
      wasm: { hasLoadedDocument: () => true },
      eventBus,
    } as never,
    environment: { documentId: 'doc-1' } as never,
    windowLike,
    bootstrap: async () => {
      bootstraps += 1;
      if (bootstrap) return bootstrap();
      return () => { destroys += 1; };
    },
  });
  return {
    eventBus,
    windowLike,
    manager,
    bootstraps: () => bootstraps,
    destroys: () => destroys,
  };
}

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

test('start creates one session and repeated or concurrent starts do not duplicate it', async () => {
  const value = fixture();
  await Promise.all([value.manager.start(), value.manager.start(), value.manager.start()]);
  assert.equal(value.bootstraps(), 1);
  assert.equal(value.manager.isRunning, true);
  assert.equal(value.manager.lastError, null);
});


test('document-ready reuses an in-flight initial start instead of duplicating bootstrap', async () => {
  let resolveBootstrap: ((destroy: () => void) => void) | undefined;
  let calls = 0;
  const eventBus = new FakeEventBus();
  const manager = new CollaborationSessionManager({
    runtime: { wasm: { hasLoadedDocument: () => true }, eventBus } as never,
    environment: { documentId: 'doc-1' } as never,
    windowLike: new FakeWindow(),
    bootstrap: async () => {
      calls += 1;
      return new Promise<() => void>((resolve) => { resolveBootstrap = resolve; });
    },
  });

  const starting = manager.start();
  await tick();
  valueAssert(resolveBootstrap);
  eventBus.emit('collaboration-document-ready');
  await tick();
  assert.equal(calls, 1);

  resolveBootstrap!(() => undefined);
  await starting;
  assert.equal(manager.isRunning, true);
});

test('restart destroys the prior session before bootstrapping the replacement', async () => {
  const order: string[] = [];
  let generation = 0;
  const eventBus = new FakeEventBus();
  const manager = new CollaborationSessionManager({
    runtime: { wasm: { hasLoadedDocument: () => true }, eventBus } as never,
    environment: { documentId: 'doc-1' } as never,
    windowLike: new FakeWindow(),
    bootstrap: async () => {
      generation += 1;
      const current = generation;
      order.push(`start:${current}`);
      return () => order.push(`stop:${current}`);
    },
  });

  await manager.start();
  await manager.restart('fingerprint-changed');

  assert.deepEqual(order, ['start:1', 'stop:1', 'start:2']);
  assert.equal(manager.isRunning, true);
});

test('document lifecycle events deactivate or restart using the safe policy', async () => {
  const value = fixture();
  await value.manager.start();

  value.eventBus.emit('collaboration-document-replacing');
  await tick();
  assert.equal(value.manager.isRunning, false);
  assert.equal(value.destroys(), 1);

  value.eventBus.emit('collaboration-document-ready');
  await tick();
  assert.equal(value.manager.isRunning, true);
  assert.equal(value.bootstraps(), 2);

  value.eventBus.emit('collaboration-fingerprint-changed');
  await tick();
  assert.equal(value.destroys(), 2);
  assert.equal(value.bootstraps(), 3);

  value.eventBus.emit('collaboration-structure-changed', 'table-row-inserted');
  await tick();
  assert.equal(value.manager.isRunning, false);
  assert.equal(value.destroys(), 3);

  value.eventBus.emit('collaboration-document-ready');
  await tick();
  assert.equal(value.manager.isRunning, true);
});

test('beforeunload destroys the session and removes lifecycle listeners', async () => {
  const value = fixture();
  await value.manager.start();
  assert(value.eventBus.listenerCount() > 0);
  assert.equal(value.windowLike.listenerCount(), 1);

  value.windowLike.emit('beforeunload');
  await tick();

  assert.equal(value.manager.isRunning, false);
  assert.equal(value.destroys(), 1);
  assert.equal(value.eventBus.listenerCount(), 0);
  assert.equal(value.windowLike.listenerCount(), 0);
});

test('bootstrap failure records lastError and leaves no active session', async () => {
  const expected = new Error('bootstrap failed');
  const value = fixture(async () => { throw expected; });

  await assert.rejects(value.manager.start(), /bootstrap failed/);

  assert.equal(value.manager.isRunning, false);
  assert.equal(value.manager.lastError, expected);
});

test('stop is idempotent and start can register a fresh lifecycle after stopping', async () => {
  const value = fixture();
  await value.manager.start();

  value.manager.stop('manual');
  value.manager.stop('manual-again');
  await tick();

  assert.equal(value.destroys(), 1);
  assert.equal(value.eventBus.listenerCount(), 0);
  assert.equal(value.windowLike.listenerCount(), 0);

  await value.manager.start();
  assert.equal(value.bootstraps(), 2);
  assert.equal(value.manager.isRunning, true);
});

test('a stale asynchronous bootstrap is destroyed instead of becoming active', async () => {
  let resolveFirst: ((destroy: () => void) => void) | undefined;
  let staleDestroy = 0;
  let currentDestroy = 0;
  let calls = 0;
  const eventBus = new FakeEventBus();
  const manager = new CollaborationSessionManager({
    runtime: { wasm: { hasLoadedDocument: () => true }, eventBus } as never,
    environment: { documentId: 'doc-1' } as never,
    windowLike: new FakeWindow(),
    bootstrap: async () => {
      calls += 1;
      if (calls === 1) {
        return new Promise<() => void>((resolve) => { resolveFirst = resolve; });
      }
      return () => { currentDestroy += 1; };
    },
  });

  const first = manager.start();
  await tick();
  valueAssert(resolveFirst);
  const restart = manager.restart('new-document');
  resolveFirst!(() => { staleDestroy += 1; });
  await Promise.all([first, restart]);

  assert.equal(calls, 2);
  assert.equal(staleDestroy, 1);
  assert.equal(currentDestroy, 0);
  assert.equal(manager.isRunning, true);
});


test('editable structure changes deactivate the active session', async () => {
  const value = fixture();
  await value.manager.start();

  value.eventBus.emit('collaboration-editable-changed', {
    kind: 'structure',
    reason: 'paragraph-added',
  });
  await tick();

  assert.equal(value.manager.isRunning, false);
  assert.equal(value.destroys(), 1);
});

test('Studio entry and document initialization use the session-manager lifecycle', () => {
  const entry = readFileSync(
    new URL('../src/collaboration-entry.ts', import.meta.url),
    'utf8',
  );
  const main = readFileSync(new URL('../src/main.ts', import.meta.url), 'utf8');

  assert.match(entry, /collaborationEnvironmentFromWindow/);
  assert.doesNotMatch(entry, /resolveCollaborationEnvironment/);
  assert.match(entry, /bootstrap: bootstrapStudioCollaboration/);
  assert.doesNotMatch(entry, /window\.addEventListener\('beforeunload'/);
  assert.match(main, /eventBus\.emit\('collaboration-document-replacing'\)/);
  assert.match(main, /eventBus\.emit\('collaboration-document-ready'\)/);
});

function valueAssert<T>(value: T | undefined): asserts value is T {
  assert.notEqual(value, undefined);
}
