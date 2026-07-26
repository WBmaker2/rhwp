import {
  bootstrapStudioCollaboration,
  collaborationEnvironmentFromWindow,
  type StudioCollaborationRuntime,
} from './collaboration/bootstrap';
import { CollaborationSessionManager } from './collaboration/collaboration-session-manager';
import { FirebaseAuthProvider } from './collaboration/FirebaseAuthProvider';
import {
  ShareLinkClient,
  collaborationUrlAfterRedemption,
  shareTokenFromHash,
} from './collaboration/ShareLinkClient';

declare global {
  interface Window {
    __rhwpStudioRuntime?: StudioCollaborationRuntime;
  }
}

const shareToken = shareTokenFromHash(window.location.hash);
if (shareToken) {
  void redeemInvitation(shareToken);
} else {
  const environment = collaborationEnvironmentFromWindow();
  if (environment) void start(environment);
}

async function redeemInvitation(token: string): Promise<void> {
  const documentApiUrl = import.meta.env.VITE_DOCUMENT_API_URL?.trim() ?? '';
  const firebase = {
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY?.trim() ?? '',
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN?.trim() ?? '',
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID?.trim() ?? '',
    storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET?.trim() ?? '',
    appId: import.meta.env.VITE_FIREBASE_APP_ID?.trim() ?? '',
  };
  if (!documentApiUrl || Object.values(firebase).some((value) => !value)) {
    showInvitationError('공유 링크를 열기 위한 Firebase 또는 Document API 설정이 없습니다.');
    return;
  }
  const firestorePort = Number(import.meta.env.VITE_FIRESTORE_EMULATOR_PORT ?? '');
  try {
    const auth = new FirebaseAuthProvider({
      firebase,
      authEmulatorUrl: import.meta.env.VITE_AUTH_EMULATOR_URL || undefined,
      firestoreEmulatorHost: import.meta.env.VITE_FIRESTORE_EMULATOR_HOST || undefined,
      firestoreEmulatorPort: Number.isInteger(firestorePort) && firestorePort > 0
        ? firestorePort
        : undefined,
    });
    const client = new ShareLinkClient({
      apiBaseUrl: documentApiUrl,
      getIdToken: () => auth.getIdToken(),
    });
    const redeemed = await client.redeem(token);
    const destination = collaborationUrlAfterRedemption(window.location, redeemed.documentId);
    window.history.replaceState(null, '', destination);
    window.location.reload();
  } catch (error) {
    window.history.replaceState(null, '', window.location.pathname);
    showInvitationError(error instanceof Error ? error.message : String(error));
  }
}

async function start(
  config: NonNullable<ReturnType<typeof collaborationEnvironmentFromWindow>>,
): Promise<void> {
  try {
    const runtime = await waitForRuntime();
    const manager = new CollaborationSessionManager({
      runtime,
      environment: config,
      bootstrap: bootstrapStudioCollaboration,
    });
    await manager.start();
  } catch (error) {
    console.error('[Collaboration] bootstrap failed', error);
  }
}

async function waitForRuntime(): Promise<StudioCollaborationRuntime> {
  const deadline = Date.now() + 30_000;
  while (!window.__rhwpStudioRuntime) {
    if (Date.now() >= deadline) {
      throw new Error('rhwp-studio runtime을 찾지 못했습니다.');
    }
    await new Promise((resolve) => window.setTimeout(resolve, 50));
  }
  return window.__rhwpStudioRuntime;
}

function showInvitationError(message: string): void {
  console.error('[Collaboration] share invitation failed', message);
  const element = document.createElement('div');
  element.setAttribute('role', 'alert');
  element.textContent = `공유 링크 오류: ${message}`;
  Object.assign(element.style, {
    position: 'fixed',
    inset: '16px 16px auto 16px',
    zIndex: '14000',
    padding: '12px 14px',
    borderRadius: '8px',
    background: '#fce8e6',
    color: '#b3261e',
    boxShadow: '0 3px 14px rgba(0,0,0,0.2)',
    font: '13px system-ui, sans-serif',
  });
  document.body.append(element);
}
