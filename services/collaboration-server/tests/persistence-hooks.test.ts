import assert from 'node:assert/strict'
import test from 'node:test'

import { Doc, applyUpdate, encodeStateAsUpdate } from 'yjs'

import type { MembershipStore, TokenVerifier } from '../src/auth.js'
import { ParticipantRegistry } from '../src/participants.js'
import {
  YjsSnapshotPersistence,
  type SnapshotReason,
  type SnapshotRecord,
  type SnapshotRepository,
} from '../src/persistence.js'
import { createCollaborationHooks } from '../src/server.js'

class RecordingRepository implements SnapshotRepository {
  loadResult: Uint8Array | null = null
  readonly saves: Array<{
    documentId: string
    update: Uint8Array
    reason: SnapshotReason
  }> = []

  async load(): Promise<Uint8Array | null> {
    return this.loadResult?.slice() ?? null
  }

  async save(
    documentId: string,
    update: Uint8Array,
    reason: SnapshotReason,
  ): Promise<SnapshotRecord> {
    const copy = update.slice()
    this.saves.push({ documentId, update: copy, reason })
    return {
      path: `documents/${documentId}/collaboration/snapshots/fake.bin`,
      checksum: '0'.repeat(64),
      createdAt: '2026-07-25T00:00:00.000Z',
      reason,
      sizeBytes: copy.byteLength,
    }
  }
}

const tokenVerifier: TokenVerifier = {
  async verifyIdToken(idToken) {
    return {
      uid: idToken,
      displayName: idToken,
      photoURL: null,
    }
  },
}

const membershipStore: MembershipStore = {
  async getMembership() {
    return { role: 'editor' }
  },
}

function documentWithText(value: string): Doc {
  const document = new Doc()
  document.getText('body').insert(0, value)
  return document
}

function decodedText(update: Uint8Array): string {
  const document = new Doc()
  applyUpdate(document, update)
  return document.getText('body').toString()
}

test('loads a stored Yjs update during document creation', async () => {
  const repository = new RecordingRepository()
  repository.loadResult = encodeStateAsUpdate(documentWithText('복구된 문서'))
  const persistence = new YjsSnapshotPersistence(repository)
  const hooks = createCollaborationHooks({
    tokenVerifier,
    membershipStore,
    participants: new ParticipantRegistry(),
    persistence,
  })

  const update = await hooks.onLoadDocument({ documentName: 'doc-1' })

  assert.ok(update)
  assert.equal(decodedText(update), '복구된 문서')
})

test('stores debounced document state and flushes the latest state for export', async () => {
  const repository = new RecordingRepository()
  const persistence = new YjsSnapshotPersistence(repository)
  const hooks = createCollaborationHooks({
    tokenVerifier,
    membershipStore,
    participants: new ParticipantRegistry(),
    persistence,
  })
  const document = documentWithText('저장할 문서')

  hooks.afterLoadDocument({ documentName: 'doc-1', document })
  await hooks.onStoreDocument({ documentName: 'doc-1', document })
  document.getText('body').insert(document.getText('body').length, ' 최신')
  await hooks.flushForExport('doc-1')

  assert.deepEqual(
    repository.saves.map(({ reason }) => reason),
    ['debounce', 'export'],
  )
  assert.equal(decodedText(repository.saves[0]?.update ?? new Uint8Array()), '저장할 문서')
  assert.equal(
    decodedText(repository.saves[1]?.update ?? new Uint8Array()),
    '저장할 문서 최신',
  )
})

test('forces a snapshot only after the last unique user disconnects', async () => {
  const repository = new RecordingRepository()
  const persistence = new YjsSnapshotPersistence(repository)
  const participants = new ParticipantRegistry()
  const hooks = createCollaborationHooks({
    tokenVerifier,
    membershipStore,
    participants,
    persistence,
  })
  const document = documentWithText('마지막 사용자 상태')
  hooks.afterLoadDocument({ documentName: 'doc-1', document })

  const first = await hooks.onAuthenticate({
    documentName: 'doc-1',
    token: 'user-1',
    socketId: 'tab-a',
    connection: { readOnly: false },
  })
  const second = await hooks.onAuthenticate({
    documentName: 'doc-1',
    token: 'user-1',
    socketId: 'tab-b',
    connection: { readOnly: false },
  })

  await hooks.onDisconnect({
    documentName: 'doc-1',
    socketId: 'tab-a',
    context: first,
  })
  assert.equal(repository.saves.length, 0)

  await hooks.onDisconnect({
    documentName: 'doc-1',
    socketId: 'tab-b',
    context: second,
  })
  assert.equal(repository.saves.length, 1)
  assert.equal(repository.saves[0]?.reason, 'last-user')
  assert.equal(decodedText(repository.saves[0]?.update ?? new Uint8Array()), '마지막 사용자 상태')
})

test('flushes every loaded document during server shutdown', async () => {
  const repository = new RecordingRepository()
  const persistence = new YjsSnapshotPersistence(repository)
  const hooks = createCollaborationHooks({
    tokenVerifier,
    membershipStore,
    participants: new ParticipantRegistry(),
    persistence,
  })

  hooks.afterLoadDocument({
    documentName: 'doc-1',
    document: documentWithText('첫 번째'),
  })
  hooks.afterLoadDocument({
    documentName: 'doc-2',
    document: documentWithText('두 번째'),
  })

  await hooks.onDestroy()

  assert.deepEqual(
    repository.saves.map(({ documentId, reason }) => ({ documentId, reason })),
    [
      { documentId: 'doc-1', reason: 'shutdown' },
      { documentId: 'doc-2', reason: 'shutdown' },
    ],
  )
})
