export const LIFECYCLE_KEY = 'rhwpSettingsLifecycle';

/**
 * 사용자 설정과 분리된 최소 수명주기 진단만 local storage 에 기록한다.
 * install/update/chrome_update 어느 경로에서도 sync 사용자 설정은 수정하지 않는다.
 */
export async function handleExtensionInstalled(chromeApi = globalThis.chrome, details = {}, options = {}) {
  const now = options.now ?? Date.now;
  const record = {
    reason: details.reason ?? 'unknown',
    previousVersion: details.previousVersion ?? null,
    currentVersion: chromeApi.runtime.getManifest().version,
    recordedAt: now(),
  };
  await chromeApi.storage.local.set({ [LIFECYCLE_KEY]: record });
  return record;
}
