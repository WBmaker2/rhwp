// Chrome/Edge 확장 사용자 설정의 단일 저장소 adapter.
// storage.sync 를 key별 권위 저장소로 사용하고, 누락/일시 실패 시 storage.local snapshot 으로 복구한다.

export const SETTINGS_SCHEMA_VERSION = 1;
export const LOCAL_BACKUP_KEY = 'rhwpSettingsBackup';
export const SYNC_META_KEY = 'rhwpSettingsMeta';

export const SETTINGS_KEYS = Object.freeze([
  'autoOpen',
  'showBadges',
  'hoverPreview',
  'disableExternalWebFonts',
]);

export const DEFAULT_SETTINGS = Object.freeze({
  autoOpen: true,
  showBadges: true,
  hoverPreview: true,
  disableExternalWebFonts: false,
});

/**
 * sync 값을 우선하고, 유효한 boolean sync key 가 없을 때만 local snapshot 을 사용한다.
 * sync 를 읽을 수 없는 동시에 local snapshot 도 없으면 기본값으로 조용히 진행하지 않고 실패한다.
 */
export async function loadSettings(chromeApi = globalThis.chrome, options = {}) {
  const now = options.now ?? Date.now;
  const syncArea = requireStorageArea(chromeApi, 'sync');
  const localArea = requireStorageArea(chromeApi, 'local');
  const [syncResult, localResult] = await Promise.all([
    readStorage(syncArea, [...SETTINGS_KEYS, SYNC_META_KEY]),
    readStorage(localArea, LOCAL_BACKUP_KEY),
  ]);

  const localSnapshot = localResult.ok
    ? normalizeSnapshot(localResult.items[LOCAL_BACKUP_KEY])
    : null;

  if (!syncResult.ok && !localSnapshot) {
    throw new Error('확장 설정을 불러오지 못했습니다.', { cause: syncResult.error ?? localResult.error });
  }

  const settings = {};
  for (const key of SETTINGS_KEYS) {
    if (syncResult.ok && typeof syncResult.items[key] === 'boolean') {
      settings[key] = syncResult.items[key];
    } else if (localSnapshot && typeof localSnapshot.settings[key] === 'boolean') {
      settings[key] = localSnapshot.settings[key];
    } else {
      settings[key] = DEFAULT_SETTINGS[key];
    }
  }

  if (localResult.ok && !snapshotMatches(localSnapshot, settings)) {
    const syncMeta = syncResult.ok ? normalizeMeta(syncResult.items[SYNC_META_KEY]) : null;
    const snapshot = createSnapshot(settings, syncMeta?.updatedAt ?? now());
    try {
      await localArea.set({ [LOCAL_BACKUP_KEY]: snapshot });
    } catch (error) {
      console.warn('[rhwp-settings] local backup 갱신 실패:', error);
    }
  }

  return settings;
}

/**
 * local snapshot 을 먼저 기록한 뒤 호환 가능한 flat sync key 를 저장한다.
 * 어느 단계에서든 실패하면 호출자가 성공 UI를 표시하지 않도록 rejection 을 전달한다.
 */
export async function saveSettings(chromeApi = globalThis.chrome, candidate, options = {}) {
  const now = options.now ?? Date.now;
  const settings = normalizeCompleteSettings(candidate);
  const updatedAt = now();
  const localArea = requireStorageArea(chromeApi, 'local');
  const syncArea = requireStorageArea(chromeApi, 'sync');

  await localArea.set({ [LOCAL_BACKUP_KEY]: createSnapshot(settings, updatedAt) });
  await syncArea.set({
    ...settings,
    [SYNC_META_KEY]: {
      schemaVersion: SETTINGS_SCHEMA_VERSION,
      updatedAt,
    },
  });

  return settings;
}

function requireStorageArea(chromeApi, name) {
  const area = chromeApi?.storage?.[name];
  if (!area || typeof area.get !== 'function' || typeof area.set !== 'function') {
    throw new Error(`chrome.storage.${name}을 사용할 수 없습니다.`);
  }
  return area;
}

async function readStorage(area, keys) {
  try {
    return { ok: true, items: (await area.get(keys)) ?? {}, error: null };
  } catch (error) {
    return { ok: false, items: {}, error };
  }
}

function normalizeCompleteSettings(candidate) {
  const settings = {};
  for (const key of SETTINGS_KEYS) {
    settings[key] = typeof candidate?.[key] === 'boolean'
      ? candidate[key]
      : DEFAULT_SETTINGS[key];
  }
  return settings;
}

function normalizeSnapshot(value) {
  if (!value || value.schemaVersion !== SETTINGS_SCHEMA_VERSION || !Number.isFinite(value.updatedAt)) {
    return null;
  }
  if (!value.settings || typeof value.settings !== 'object') return null;
  return {
    schemaVersion: SETTINGS_SCHEMA_VERSION,
    updatedAt: value.updatedAt,
    settings: normalizeCompleteSettings(value.settings),
  };
}

function normalizeMeta(value) {
  if (!value || value.schemaVersion !== SETTINGS_SCHEMA_VERSION || !Number.isFinite(value.updatedAt)) {
    return null;
  }
  return { schemaVersion: SETTINGS_SCHEMA_VERSION, updatedAt: value.updatedAt };
}

function createSnapshot(settings, updatedAt) {
  return {
    schemaVersion: SETTINGS_SCHEMA_VERSION,
    updatedAt,
    settings: { ...settings },
  };
}

function snapshotMatches(snapshot, settings) {
  if (!snapshot) return false;
  return SETTINGS_KEYS.every((key) => snapshot.settings[key] === settings[key]);
}
