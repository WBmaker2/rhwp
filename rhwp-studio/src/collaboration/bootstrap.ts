import type { EventBus } from '@/core/event-bus';
import type { WasmBridge } from '@/core/wasm-bridge';
import type { InputHandler } from '@/engine/input-handler';
import { CursorState } from '@/engine/cursor';

import { CollaborationController, type DocumentRole } from './CollaborationController';
import { FirebaseAuthProvider } from './FirebaseAuthProvider';
import { PresenceView } from './PresenceView';
import { RemoteCursorLayer } from './RemoteCursorLayer';
import { ShareDialog } from './ShareDialog';
import { ShareLinkClient } from './ShareLinkClient';
import {
  StudioCursorSource,
  createRemoteCursorResolver,
  type StudioCursorSnapshot,
} from './StudioCursorSource';
import { installViewerInputGuard } from './ViewerInputGuard';
import { RhwpCollaborationWasmAdapter } from './wasm-adapter';

export interface StudioCollaborationRuntime {
  wasm: WasmBridge;
  eventBus: EventBus;
  inputHandler: InputHandler & {
    getCollaborationSelectionSnapshot(): StudioCursorSnapshot;
  };
  scrollContent: HTMLElement;
  virtualScroll: {
    getPageOffset(pageIndex: number): number;
    getPageLeft(pageIndex: number): number;
    getPageWidth(pageIndex: number): number;
  };
  viewportManager: {
    getZoom(): number;
  };
}

export interface CollaborationEnvironment {
  documentId: string;
  collaborationUrl: string;
  documentApiUrl?: string;
  firebase: {
    apiKey: string;
    authDomain: string;
    projectId: string;
    storageBucket: string;
    appId: string;
  };
  authEmulatorUrl?: string;
  firestoreEmulatorHost?: string;
  firestoreEmulatorPort?: number;
  emulatorTestUser?: {
    email: string;
    password: string;
  };
}

export interface CollaborationDebugApi {
  role(): DocumentRole | null;
  participants(): Array<{ userId: string; displayName: string }>;
  manifest(): ReturnType<RhwpCollaborationWasmAdapter['getManifest']>;
  firstParagraphText(): string;
  applyLocalFirstParagraphText(text: string): void;
  publishCursor(snapshot: StudioCursorSnapshot | null): void;
}

declare global {
  interface Window {
    __rhwpCollaborationDebug?: CollaborationDebugApi;
  }
}

export async function bootstrapStudioCollaboration(
  runtime: StudioCollaborationRuntime,
  environment: CollaborationEnvironment,
): Promise<() => void> {
  await waitForDocument(runtime.wasm);
  const bridge = new RhwpCollaborationWasmAdapter(runtime.wasm);
  const manifest = bridge.getManifest();
  const cursorSource = new StudioCursorSource(manifest.source_fingerprint);
  const cursorTimer = window.setInterval(() => {
    try {
      cursorSource.publish(runtime.inputHandler.getCollaborationSelectionSnapshot());
    } catch {
      cursorSource.publish(null);
    }
  }, 80);

  const auth = new FirebaseAuthProvider({
    firebase: environment.firebase,
    authEmulatorUrl: environment.authEmulatorUrl,
    firestoreEmulatorHost: environment.firestoreEmulatorHost,
    firestoreEmulatorPort: environment.firestoreEmulatorPort,
    emulatorTestUser: environment.emulatorTestUser,
  });
  const controller = new CollaborationController({
    documentId: environment.documentId,
    collaborationUrl: environment.collaborationUrl,
    auth,
    bridge,
    events: {
      on: (event, listener) => runtime.eventBus.on(event, listener),
      emit: (event) => runtime.eventBus.emit(event),
    },
    cursor: cursorSource,
  });
  const view = new PresenceView();
  const shareDialog = environment.documentApiUrl
    ? new ShareDialog({
        documentId: environment.documentId,
        client: new ShareLinkClient({
          apiBaseUrl: environment.documentApiUrl,
          getIdToken: () => auth.getIdToken(),
        }),
      })
    : null;
  const geometryCursor = new CursorState(runtime.wasm);
  const layer = new RemoteCursorLayer(
    runtime.scrollContent,
    createRemoteCursorResolver(
      manifest,
      {
        getCursorRect(position) {
          geometryCursor.moveTo(position);
          return geometryCursor.getRect();
        },
      },
      {
        getPageOffset: (pageIndex) => runtime.virtualScroll.getPageOffset(pageIndex),
        getPageLeft: (pageIndex) => runtime.virtualScroll.getPageLeft(pageIndex),
        getPageWidth: (pageIndex) => runtime.virtualScroll.getPageWidth(pageIndex),
        getZoom: () => runtime.viewportManager.getZoom(),
        getContentWidth: () => runtime.scrollContent.clientWidth,
      },
    ),
  );

  const renderParticipants = (participants: Parameters<PresenceView['renderParticipants']>[0]): void => {
    view.renderParticipants(participants);
    layer.render(participants);
  };
  const unsubscribeParticipants = controller.subscribeParticipants(renderParticipants);
  const rerender = (): void => layer.render(controller.getRemoteParticipants());
  const unsubscribeZoom = runtime.eventBus.on('zoom-changed', rerender);
  const unsubscribeView = runtime.eventBus.on('document-view-changed', rerender);
  let connectedRole: DocumentRole | null = null;
  let removeViewerInputGuard: (() => void) | null = null;

  try {
    const state = await controller.connect();
    connectedRole = state.role;
    view.setConnected(state);
    if (state.role === 'viewer') {
      removeViewerInputGuard = installViewerInputGuard();
    }
    if (state.role === 'owner' && shareDialog) {
      view.setShareAction(() => void shareDialog.open());
    }
    if (import.meta.env.DEV) {
      window.__rhwpCollaborationDebug = createDebugApi(
        bridge,
        runtime.eventBus,
        cursorSource,
        controller,
        () => connectedRole,
      );
    }
  } catch (error) {
    removeViewerInputGuard?.();
    view.setError(error);
    window.clearInterval(cursorTimer);
    unsubscribeParticipants();
    unsubscribeZoom();
    unsubscribeView();
    layer.destroy();
    shareDialog?.destroy();
    controller.destroy();
    throw error;
  }

  return () => {
    removeViewerInputGuard?.();
    window.clearInterval(cursorTimer);
    unsubscribeParticipants();
    unsubscribeZoom();
    unsubscribeView();
    layer.destroy();
    shareDialog?.destroy();
    view.destroy();
    controller.destroy();
    if (window.__rhwpCollaborationDebug) delete window.__rhwpCollaborationDebug;
  };
}

export function collaborationEnvironmentFromWindow(): CollaborationEnvironment | null {
  const params = new URLSearchParams(window.location.search);
  const documentId = params.get('collabDocument')?.trim() ?? '';
  const collaborationUrl = import.meta.env.VITE_COLLABORATION_URL?.trim() ?? '';
  const documentApiUrl = import.meta.env.VITE_DOCUMENT_API_URL?.trim() || undefined;
  const firebase = {
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY?.trim() ?? '',
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN?.trim() ?? '',
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID?.trim() ?? '',
    storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET?.trim() ?? '',
    appId: import.meta.env.VITE_FIREBASE_APP_ID?.trim() ?? '',
  };
  if (!documentId || !collaborationUrl || Object.values(firebase).some((value) => !value)) {
    return null;
  }
  const authEmulatorUrl = import.meta.env.VITE_AUTH_EMULATOR_URL || undefined;
  const firestorePort = Number(import.meta.env.VITE_FIRESTORE_EMULATOR_PORT ?? '');
  const emulatorEmail = params.get('collabE2EEmail')?.trim() ?? '';
  const emulatorPassword = params.get('collabE2EPassword') ?? '';
  const localHost = window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
  const emulatorTestUser = authEmulatorUrl && localHost && emulatorEmail && emulatorPassword
    ? { email: emulatorEmail, password: emulatorPassword }
    : undefined;
  return {
    documentId,
    collaborationUrl,
    documentApiUrl,
    firebase,
    authEmulatorUrl,
    firestoreEmulatorHost: import.meta.env.VITE_FIRESTORE_EMULATOR_HOST || undefined,
    firestoreEmulatorPort: Number.isInteger(firestorePort) && firestorePort > 0
      ? firestorePort
      : undefined,
    emulatorTestUser,
  };
}

function createDebugApi(
  bridge: RhwpCollaborationWasmAdapter,
  eventBus: EventBus,
  cursorSource: StudioCursorSource,
  controller: CollaborationController,
  role: () => DocumentRole | null,
): CollaborationDebugApi {
  return {
    role,
    participants: () => controller.getRemoteParticipants().map(({ state }) => ({
      userId: state.userId,
      displayName: state.displayName,
    })),
    manifest: () => bridge.getManifest(),
    firstParagraphText() {
      return bridge.getManifest().sections[0]?.paragraphs[0]?.text ?? '';
    },
    applyLocalFirstParagraphText(text) {
      const current = bridge.getManifest();
      const paragraph = current.sections[0]?.paragraphs[0];
      if (!paragraph) throw new Error('첫 문단을 찾지 못했습니다.');
      bridge.applyPatch(current, {
        paragraphs: [{ target_id: paragraph.id, text }],
        cells: [],
        inserted_images: [],
      });
      eventBus.emit('document-changed');
    },
    publishCursor: (snapshot) => cursorSource.publish(snapshot),
  };
}

async function waitForDocument(wasm: WasmBridge): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (!wasm.hasLoadedDocument()) {
    if (Date.now() >= deadline) throw new Error('공동 편집 문서 로드를 기다리는 중 시간 초과');
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }
}
