import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
} from '@firebase/rules-unit-testing'
import {
  deleteDoc,
  doc,
  getDoc,
  setDoc,
  Timestamp,
  updateDoc,
} from 'firebase/firestore'
import { getBytes, ref, uploadBytes } from 'firebase/storage'

const projectId = 'demo-rhwp-collaboration'
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const mib = 1024 * 1024
let testEnv

before(async () => {
  const [firestoreRules, storageRules] = await Promise.all([
    readFile(resolve(root, 'firestore.rules'), 'utf8'),
    readFile(resolve(root, 'storage.rules'), 'utf8'),
  ])

  testEnv = await initializeTestEnvironment({
    projectId,
    firestore: { rules: firestoreRules },
    storage: { rules: storageRules },
  })
})

after(async () => {
  await testEnv?.cleanup()
})

beforeEach(async () => {
  await Promise.all([testEnv.clearFirestore(), testEnv.clearStorage()])
})

function firestoreFor(uid) {
  return uid
    ? testEnv.authenticatedContext(uid).firestore()
    : testEnv.unauthenticatedContext().firestore()
}

function storageFor(uid) {
  return uid
    ? testEnv.authenticatedContext(uid).storage()
    : testEnv.unauthenticatedContext().storage()
}

function initialDocument(documentId, ownerId = 'owner-1') {
  return {
    ownerId,
    title: '공동 편집 문서',
    sourceFilename: 'source.hwp',
    sourceSize: 0,
    sourceStoragePath: `documents/${documentId}/source/original.hwp`,
    status: 'uploading',
    parserVersion: null,
    createdAt: Timestamp.fromMillis(1_000),
    updatedAt: Timestamp.fromMillis(1_000),
    latestSnapshotPath: null,
    latestExportPath: null,
    maxParticipants: 10,
  }
}

async function seedDocument(documentId = 'doc-1') {
  await testEnv.withSecurityRulesDisabled(async (context) => {
    const db = context.firestore()
    await setDoc(doc(db, 'documents', documentId), initialDocument(documentId))
    await setDoc(doc(db, 'documents', documentId, 'members', 'owner-1'), {
      role: 'owner',
      invitedBy: 'owner-1',
      createdAt: Timestamp.fromMillis(1_000),
    })
    await setDoc(doc(db, 'documents', documentId, 'members', 'editor-1'), {
      role: 'editor',
      invitedBy: 'owner-1',
      createdAt: Timestamp.fromMillis(1_000),
    })
    await setDoc(doc(db, 'documents', documentId, 'members', 'viewer-1'), {
      role: 'viewer',
      invitedBy: 'owner-1',
      createdAt: Timestamp.fromMillis(1_000),
    })
    await setDoc(doc(db, 'documents', documentId, 'exports', 'export-1'), {
      status: 'ready',
      storagePath: `documents/${documentId}/exports/export-1.hwpx`,
      requestedBy: 'editor-1',
      createdAt: Timestamp.fromMillis(2_000),
      completedAt: Timestamp.fromMillis(3_000),
    })
  })
}

async function seedStorageObject(path, bytes = Uint8Array.of(1, 2, 3)) {
  await testEnv.withSecurityRulesDisabled(async (context) => {
    await uploadBytes(ref(context.storage(), path), bytes, {
      contentType: 'application/octet-stream',
    })
  })
}

test('document creation is limited to a signed-in owner and canonical initial state', async () => {
  const ownerDb = firestoreFor('owner-1')
  const attackerDb = firestoreFor('attacker-1')

  await assertSucceeds(
    setDoc(doc(ownerDb, 'documents', 'new-doc'), initialDocument('new-doc')),
  )
  await assertFails(
    setDoc(
      doc(attackerDb, 'documents', 'forged-doc'),
      initialDocument('forged-doc', 'owner-1'),
    ),
  )
  await assertFails(
    setDoc(doc(ownerDb, 'documents', 'wrong-path'), {
      ...initialDocument('wrong-path'),
      sourceStoragePath: 'documents/another/source/original.hwp',
    }),
  )
})

test('only document members can read document metadata', async () => {
  await seedDocument()
  const path = 'documents/doc-1'

  await assertSucceeds(getDoc(doc(firestoreFor('owner-1'), path)))
  await assertSucceeds(getDoc(doc(firestoreFor('editor-1'), path)))
  await assertSucceeds(getDoc(doc(firestoreFor('viewer-1'), path)))
  await assertFails(getDoc(doc(firestoreFor('outsider-1'), path)))
  await assertFails(getDoc(doc(firestoreFor(null), path)))
})

test('owner may edit title but no client may alter server-managed document state', async () => {
  await seedDocument()
  const ownerRef = doc(firestoreFor('owner-1'), 'documents/doc-1')
  const editorRef = doc(firestoreFor('editor-1'), 'documents/doc-1')

  await assertSucceeds(updateDoc(ownerRef, { title: '새 제목' }))
  await assertFails(updateDoc(editorRef, { title: '탈취한 제목' }))
  await assertFails(updateDoc(ownerRef, { status: 'ready' }))
  await assertFails(
    updateDoc(ownerRef, {
      latestSnapshotPath: 'documents/doc-1/collaboration/snapshots/fake.bin',
    }),
  )
})

test('only owner can manage non-owner memberships with valid roles', async () => {
  await seedDocument()
  const ownerDb = firestoreFor('owner-1')
  const editorDb = firestoreFor('editor-1')
  const invitedRef = doc(ownerDb, 'documents/doc-1/members/invited-1')

  await assertSucceeds(
    setDoc(invitedRef, {
      role: 'viewer',
      invitedBy: 'owner-1',
      createdAt: Timestamp.fromMillis(4_000),
    }),
  )
  await assertSucceeds(updateDoc(invitedRef, { role: 'editor' }))
  await assertSucceeds(deleteDoc(invitedRef))
  await assertFails(
    setDoc(doc(editorDb, 'documents/doc-1/members/attacker-1'), {
      role: 'editor',
      invitedBy: 'editor-1',
      createdAt: Timestamp.fromMillis(4_000),
    }),
  )
  await assertFails(
    setDoc(doc(ownerDb, 'documents/doc-1/members/second-owner'), {
      role: 'owner',
      invitedBy: 'owner-1',
      createdAt: Timestamp.fromMillis(4_000),
    }),
  )
})

test('owner membership is immutable from client SDKs', async () => {
  await seedDocument()
  const ownerMembership = doc(
    firestoreFor('owner-1'),
    'documents/doc-1/members/owner-1',
  )

  await assertFails(updateDoc(ownerMembership, { role: 'viewer' }))
  await assertFails(deleteDoc(ownerMembership))
})

test('members may read export metadata but all client export writes are denied', async () => {
  await seedDocument()
  const exportPath = 'documents/doc-1/exports/export-1'

  await assertSucceeds(getDoc(doc(firestoreFor('viewer-1'), exportPath)))
  await assertFails(getDoc(doc(firestoreFor('outsider-1'), exportPath)))
  await assertFails(
    setDoc(doc(firestoreFor('owner-1'), 'documents/doc-1/exports/fake'), {
      status: 'ready',
    }),
  )
})

test('only owner may manage share links for their document', async () => {
  await seedDocument()
  const ownerLink = doc(firestoreFor('owner-1'), 'shareLinks/link-1')

  await assertSucceeds(
    setDoc(ownerLink, {
      documentId: 'doc-1',
      role: 'viewer',
      enabled: true,
      expiresAt: null,
      createdBy: 'owner-1',
    }),
  )
  await assertSucceeds(getDoc(ownerLink))
  await assertFails(getDoc(doc(firestoreFor('editor-1'), 'shareLinks/link-1')))
  await assertFails(
    setDoc(doc(firestoreFor('editor-1'), 'shareLinks/editor-link'), {
      documentId: 'doc-1',
      role: 'viewer',
      enabled: true,
      expiresAt: null,
      createdBy: 'editor-1',
    }),
  )
})

test('members can read derived and user assets while outsiders cannot', async () => {
  await seedDocument()
  const path = 'documents/doc-1/assets/imported/preview.png'
  await seedStorageObject(path)

  await assertSucceeds(getBytes(ref(storageFor('viewer-1'), path)))
  await assertFails(getBytes(ref(storageFor('outsider-1'), path)))
  await assertFails(getBytes(ref(storageFor(null), path)))
})

test('owner and editor can create validated user images but viewer cannot', async () => {
  await seedDocument()
  const bytes = Uint8Array.of(0x89, 0x50, 0x4e, 0x47)

  await assertSucceeds(
    uploadBytes(
      ref(storageFor('owner-1'), 'documents/doc-1/assets/user/img-1/owner.png'),
      bytes,
      {
        contentType: 'image/png',
        customMetadata: { uploaderId: 'owner-1' },
      },
    ),
  )
  await assertSucceeds(
    uploadBytes(
      ref(storageFor('editor-1'), 'documents/doc-1/assets/user/img-2/editor.webp'),
      bytes,
      {
        contentType: 'image/webp',
        customMetadata: { uploaderId: 'editor-1' },
      },
    ),
  )
  await assertFails(
    uploadBytes(
      ref(storageFor('viewer-1'), 'documents/doc-1/assets/user/img-3/viewer.png'),
      bytes,
      {
        contentType: 'image/png',
        customMetadata: { uploaderId: 'viewer-1' },
      },
    ),
  )
})

test('user image validation rejects spoofed uploader, bad type, oversize, and overwrite', async () => {
  await seedDocument()
  const editorStorage = storageFor('editor-1')
  const path = 'documents/doc-1/assets/user/img-4/image.png'
  const bytes = Uint8Array.of(1, 2, 3)

  await assertFails(
    uploadBytes(ref(editorStorage, path), bytes, {
      contentType: 'image/png',
      customMetadata: { uploaderId: 'owner-1' },
    }),
  )
  await assertFails(
    uploadBytes(ref(editorStorage, path), bytes, {
      contentType: 'text/plain',
      customMetadata: { uploaderId: 'editor-1' },
    }),
  )
  await assertFails(
    uploadBytes(
      ref(editorStorage, path),
      new Uint8Array(20 * mib + 1),
      {
        contentType: 'image/png',
        customMetadata: { uploaderId: 'editor-1' },
      },
    ),
  )
  await assertSucceeds(
    uploadBytes(ref(editorStorage, path), bytes, {
      contentType: 'image/png',
      customMetadata: { uploaderId: 'editor-1' },
    }),
  )
  await assertFails(
    uploadBytes(ref(editorStorage, path), bytes, {
      contentType: 'image/png',
      customMetadata: { uploaderId: 'editor-1' },
    }),
  )
})

test('only owner can upload the canonical 100 to 200 MiB HWP source', async () => {
  await seedDocument()
  const path = 'documents/doc-1/source/original.hwp'

  await assertFails(
    uploadBytes(ref(storageFor('editor-1'), path), new Uint8Array(100 * mib), {
      contentType: 'application/x-hwp',
    }),
  )
  await assertFails(
    uploadBytes(ref(storageFor('owner-1'), path), Uint8Array.of(1), {
      contentType: 'application/x-hwp',
    }),
  )
  await assertSucceeds(
    uploadBytes(ref(storageFor('owner-1'), path), new Uint8Array(100 * mib), {
      contentType: 'application/x-hwp',
    }),
  )
})

test('client SDKs cannot read snapshots or write server-managed objects', async () => {
  await seedDocument()
  const snapshotPath =
    'documents/doc-1/collaboration/snapshots/1000-checksum.bin'
  await seedStorageObject(snapshotPath)

  await assertFails(getBytes(ref(storageFor('owner-1'), snapshotPath)))
  await assertFails(
    uploadBytes(
      ref(storageFor('owner-1'), 'documents/doc-1/derived/manifest.json'),
      Uint8Array.of(1),
      { contentType: 'application/json' },
    ),
  )
  await assertFails(
    uploadBytes(
      ref(storageFor('owner-1'), 'documents/doc-1/exports/fake.hwpx'),
      Uint8Array.of(1),
      { contentType: 'application/hwp+zip' },
    ),
  )
})

test('members can download completed HWPX objects', async () => {
  await seedDocument()
  const path = 'documents/doc-1/exports/export-1.hwpx'
  await seedStorageObject(path)

  const bytes = await assertSucceeds(getBytes(ref(storageFor('viewer-1'), path)))
  assert.deepEqual(new Uint8Array(bytes), Uint8Array.of(1, 2, 3))
  await assertFails(getBytes(ref(storageFor('outsider-1'), path)))
})
