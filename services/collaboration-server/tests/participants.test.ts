import assert from 'node:assert/strict'
import test from 'node:test'

import { ParticipantRegistry } from '../src/participants.js'

test('counts multiple tabs from the same user as one participant', () => {
  const registry = new ParticipantRegistry()

  assert.deepEqual(registry.tryJoin('doc-1', 'user-1', 'tab-a'), {
    accepted: true,
    uniqueUsers: 1,
  })
  assert.deepEqual(registry.tryJoin('doc-1', 'user-1', 'tab-b'), {
    accepted: true,
    uniqueUsers: 1,
  })
})

test('allows ten unique users and rejects the eleventh', () => {
  const registry = new ParticipantRegistry()

  for (let index = 1; index <= 10; index += 1) {
    assert.deepEqual(
      registry.tryJoin('doc-1', `user-${index}`, `tab-${index}`),
      {
        accepted: true,
        uniqueUsers: index,
      },
    )
  }

  assert.deepEqual(registry.tryJoin('doc-1', 'user-11', 'tab-11'), {
    accepted: false,
    reason: 'participant-limit',
    uniqueUsers: 10,
  })
})

test('removes a user only after their final connection leaves', () => {
  const registry = new ParticipantRegistry()

  registry.tryJoin('doc-1', 'user-1', 'tab-a')
  registry.tryJoin('doc-1', 'user-1', 'tab-b')
  for (let index = 2; index <= 10; index += 1) {
    registry.tryJoin('doc-1', `user-${index}`, `tab-${index}`)
  }

  registry.leave('doc-1', 'user-1', 'tab-a')
  assert.deepEqual(registry.tryJoin('doc-1', 'user-11', 'tab-11'), {
    accepted: false,
    reason: 'participant-limit',
    uniqueUsers: 10,
  })

  registry.leave('doc-1', 'user-1', 'tab-b')
  assert.deepEqual(registry.tryJoin('doc-1', 'user-11', 'tab-11'), {
    accepted: true,
    uniqueUsers: 10,
  })
})
