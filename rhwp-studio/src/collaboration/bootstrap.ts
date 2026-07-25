import type { EventBus } from '@/core/event-bus';
import type { WasmBridge } from '@/core/wasm-bridge';
import type { InputHandler } from '@/engine/input-handler';
import { CursorState } from '@/engine/cursor';

import { CollaborationController } from './CollaborationController';
import { FirebaseAuthProvider } from './FirebaseAuthProvider';
import { PresenceView } from './PresenceView';
import { RemoteCursorLayer } from './RemoteCursorLayer';
import {
  StudioCursorSource,
  createRemoteCursorResolver,
  type StudioCursorSnapshot,
} from './StudioCursorSource';
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

  try {
    view.setConnected(await controller.connect());
  } catch (error) {
    view.setError(error);
    window.clearInterval(cursorTimer);
    unsubscribeParticipants();
    unsubscribeZoom();
    unsubscribeView();
    layer.destroy();
    controller.destroy();
    throw error;
  }

  return () => {
    window.clearInterval(cursorTimer);
    unsubscribeParticipants();
    unsubscribeZoom();
    unsubscribeView();
    layer.destroy();
    view.destroy();
    controller.destroy();
  };
}

export function collaborationEnvironmentFromWindow(): CollaborationEnvironment | null {
  const params = new URLSearchParams(window.location.search);
  const documentId = params.get('collabDocument')?.trim() ?? '';
  const collaborationUrl = import.meta.env.VITE_COLLABORATION_URL?.trim() ?? '';
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
  const firestorePort = Number(import.meta.env.VITE_FIRESTORE_EMULATOR_PORT ?? '');
  return {
    documentId,
    collaborationUrl,
    firebase,
    authEmulatorUrl: import.meta.env.VITE_AUTH_EMULATOR_URL || undefined,
    firestoreEmulatorHost: import.meta.env.VITE_FIRESTORE_EMULATOR_HOST || undefined,
    firestoreEmulatorPort: Number.isInteger(firestorePort) && firestorePort > 0
      ? firestorePort
      : undefined,
  };
}

async function waitForDocument(wasm: WasmBridge): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (!wasm.hasLoadedDocument()) {
    if (Date.now() >= deadline) throw new Error('공동 편집 문서 로드를 기다리는 중 시간 초과');
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }
}
