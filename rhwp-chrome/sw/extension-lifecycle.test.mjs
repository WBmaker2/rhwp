import assert from 'node:assert/strict';
import test from 'node:test';

import { createChromeStorageMock } from '../test/extension-storage-mock.mjs';
import { LIFECYCLE_KEY, handleExtensionInstalled } from './extension-lifecycle.js';

for (const reason of ['install', 'update', 'chrome_update']) {
  test(`${reason} records diagnostics without writing sync preferences`, async () => {
    const env = createChromeStorageMock({
      sync: { autoOpen: false },
      version: '0.2.9',
    });

    await handleExtensionInstalled(
      env.chrome,
      { reason, previousVersion: reason === 'update' ? '0.2.8' : undefined },
      { now: () => 400 },
    );

    assert.deepEqual(env.syncArea.dump(), { autoOpen: false });
    assert.deepEqual(env.syncArea.calls.set, []);
    assert.deepEqual(env.localArea.dump()[LIFECYCLE_KEY], {
      reason,
      previousVersion: reason === 'update' ? '0.2.8' : null,
      currentVersion: '0.2.9',
      recordedAt: 400,
    });
  });
}
