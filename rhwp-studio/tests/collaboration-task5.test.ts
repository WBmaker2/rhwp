import test from 'node:test';
import assert from 'node:assert/strict';
import { CollaborationUpdateFactory } from '../src/collaboration/update-factory.ts';
import { LocalEditObserver } from '../src/collaboration/local-edit-observer.ts';
import { LocalCollaborationController } from '../src/collaboration/local-collaboration-controller.ts';
import { CollaborationNodeRegistry } from '../src/collaboration/node-registry.ts';

const paragraphLocation = { kind: 'paragraph' as const, sectionIndex: 0, paragraphIndex: 0 };
const cellLocation = { kind: 'cell' as const, sectionIndex: 0, hostParagraphIndex: 1, controlIndex: 0, cellIndex: 0, rowIndex: 0, columnIndex: 0 };
const registry = new CollaborationNodeRegistry(new Map([['p1', paragraphLocation], ['c1', cellLocation]]));
const context = { sourceFingerprint: 'sha256:task5', manifest: {} as never, registry };

test('update factory creates monotonic deterministic ids', () => {
  const factory = new CollaborationUpdateFactory('client-a', 'sha256:task5');
  const a = factory.create('p1', 'paragraph', 'one');
  const b = factory.create('c1', 'cell', 'two');
  assert.equal(a.updateId, 'client-a:0');
  assert.equal(a.sequence, 0);
  assert.equal(b.updateId, 'client-a:1');
  assert.equal(b.sequence, 1);
});

test('local observer debounces and suppresses duplicate text', async () => {
  let text = 'one';
  const source = new FakeEditSource();
  const reader = { getParagraphText: () => text, getCellText: () => '' };
  const observer = new LocalEditObserver(source, reader, context, () => false, 10);
  const seen: unknown[] = [];
  observer.subscribe((change) => seen.push(change));
  observer.start();
  source.emit({ kind: 'paragraph', sectionIndex: 0, paragraphIndex: 0 });
  source.emit({ kind: 'paragraph', sectionIndex: 0, paragraphIndex: 0 });
  await delay(20);
  assert.equal(seen.length, 1);
  source.emit({ kind: 'paragraph', sectionIndex: 0, paragraphIndex: 0 });
  await delay(20);
  assert.equal(seen.length, 1);
  text = 'two';
  source.emit({ kind: 'paragraph', sectionIndex: 0, paragraphIndex: 0 });
  await delay(20);
  assert.equal(seen.length, 2);
  observer.stop();
});

test('observer suppresses remote apply and stops on structure change', async () => {
  let remote = true;
  const source = new FakeEditSource();
  const observer = new LocalEditObserver(source, { getParagraphText: () => 'x', getCellText: () => '' }, context, () => remote, 5);
  let count = 0;
  observer.subscribe(() => count++);
  observer.start();
  source.emit({ kind: 'paragraph', sectionIndex: 0, paragraphIndex: 0 });
  await delay(10);
  assert.equal(count, 0);
  remote = false;
  source.emit({ kind: 'structure', reason: 'paragraph-added' });
  source.emit({ kind: 'paragraph', sectionIndex: 0, paragraphIndex: 0 });
  await delay(10);
  assert.equal(count, 0);
  assert.equal(observer.isStoppedForStructureChange, true);
});

test('controller sends local updates and applies remote updates', async () => {
  const source = new FakeEditSource();
  const sent: unknown[] = [];
  let subscribed: ((value: unknown) => void) | undefined;
  const transport = { connect() {}, send(v: unknown) { sent.push(v); }, subscribe(h: (v: unknown) => void) { subscribed = h; return () => { subscribed = undefined; }; }, disconnect() {} };
  let applied = 0;
  const adapter = { isApplyingRemoteUpdate: false, applyRemoteUpdate() { applied++; return true; } };
  const observer = new LocalEditObserver(source, { getParagraphText: () => 'local', getCellText: () => '' }, context, () => adapter.isApplyingRemoteUpdate, 5);
  const controller = new LocalCollaborationController(observer, new CollaborationUpdateFactory('client-a', 'sha256:task5'), transport, adapter);
  controller.start('session');
  source.emit({ kind: 'paragraph', sectionIndex: 0, paragraphIndex: 0 });
  await delay(10);
  assert.equal(sent.length, 1);
  subscribed?.({});
  assert.equal(applied, 1);
  controller.stop();
});

class FakeEditSource {
  private handlers = new Set<(value: any) => void>();
  subscribe(handler: (value: any) => void) { this.handlers.add(handler); return () => this.handlers.delete(handler); }
  emit(value: any) { for (const handler of this.handlers) handler(value); }
}
function delay(ms: number) { return new Promise((resolve) => setTimeout(resolve, ms)); }
