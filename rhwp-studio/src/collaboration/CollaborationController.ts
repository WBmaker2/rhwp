import { HocuspocusProvider } from '@hocuspocus/provider';
import * as Y from 'yjs';

import {
  PresenceController,
  type AwarenessPort,
  type PresenceCursor,
  type PresenceIdentity,
  type RemoteParticipant,
} from './PresenceController';
import {
  RhwpYjsAdapter,
  type CollaborationEventPort,
  type CollaborationWasmPort,
} from './RhwpYjsAdapter';

export type DocumentRole = 'owner' | 'editor' | 'viewer';

export interface CollaborationSession {
  identity: PresenceIdentity;
  role: DocumentRole;
  idToken: string;
}

export interface CollaborationAuthPort {
  requireSession(documentId: string): Promise<CollaborationSession>;
}

export interface CursorPresenceSource {
  subscribe(listener: (cursor: PresenceCursor | null) => void): () => void;
}

export interface CollaborationProvider {
  document: Y.Doc;
  awareness: AwarenessPort;
  whenSynced(): Promise<void>;
  destroy(): void;
}

export interface CollaborationProviderInput {
  url: string;
  documentId: string;
  token: string;
  document: Y.Doc;
}

export type CollaborationProviderFactory = (
  input: CollaborationProviderInput,
) => CollaborationProvider;

export interface CollaborationControllerOptions {
  documentId: string;
  collaborationUrl: string;
  auth: CollaborationAuthPort;
  bridge: CollaborationWasmPort;
  events: CollaborationEventPort;
  cursor: CursorPresenceSource;
  providerFactory?: CollaborationProviderFactory;
  syncTimeoutMs?: number;
}

export interface CollaborationConnectionState {
  documentId: string;
  role: DocumentRole;
  identity: PresenceIdentity;
  participants: RemoteParticipant[];
}

export class CollaborationController {
  private provider: CollaborationProvider | null = null;
  private adapter: RhwpYjsAdapter | null = null;
  private presence: PresenceController | null = null;
  private unsubscribeCursor: (() => void) | null = null;
  private readonly participantListeners = new Set<(
    participants: RemoteParticipant[],
  ) => void>();
  private unsubscribeParticipants: (() => void) | null = null;

  constructor(private readonly options: CollaborationControllerOptions) {
    if (!options.documentId.trim()) throw new Error('documentId must not be empty');
    if (!options.collaborationUrl.trim()) throw new Error('collaborationUrl must not be empty');
  }

  async connect(): Promise<CollaborationConnectionState> {
    this.destroy();
    const session = await this.options.auth.requireSession(this.options.documentId);
    const document = new Y.Doc();
    const provider = (this.options.providerFactory ?? createHocuspocusProvider)({
      url: this.options.collaborationUrl,
      documentId: this.options.documentId,
      token: session.idToken,
      document,
    });

    try {
      await withTimeout(
        provider.whenSynced(),
        this.options.syncTimeoutMs ?? 20_000,
        'initial collaboration sync timed out',
      );

      const manifest = this.options.bridge.getManifest();
      const adapter = new RhwpYjsAdapter(
        provider.document,
        this.options.bridge,
        this.options.events,
        { readOnly: session.role === 'viewer' },
      );
      adapter.initialize(manifest);
      const presence = new PresenceController(provider.awareness, session.identity);

      this.provider = provider;
      this.adapter = adapter;
      this.presence = presence;
      this.unsubscribeCursor = this.options.cursor.subscribe((cursor) => {
        if (cursor) presence.updateCursor(cursor);
        else presence.clearCursor();
      });
      this.unsubscribeParticipants = presence.subscribe((participants) => {
        for (const listener of this.participantListeners) listener(participants);
      });

      return {
        documentId: this.options.documentId,
        role: session.role,
        identity: session.identity,
        participants: presence.getRemoteParticipants(),
      };
    } catch (error) {
      provider.destroy();
      provider.document.destroy();
      throw error;
    }
  }

  subscribeParticipants(
    listener: (participants: RemoteParticipant[]) => void,
  ): () => void {
    this.participantListeners.add(listener);
    listener(this.presence?.getRemoteParticipants() ?? []);
    return () => this.participantListeners.delete(listener);
  }

  destroy(): void {
    this.unsubscribeCursor?.();
    this.unsubscribeParticipants?.();
    this.unsubscribeCursor = null;
    this.unsubscribeParticipants = null;
    this.presence?.destroy();
    this.adapter?.destroy();
    const provider = this.provider;
    provider?.destroy();
    provider?.document.destroy();
    this.presence = null;
    this.adapter = null;
    this.provider = null;
  }
}

function createHocuspocusProvider(
  input: CollaborationProviderInput,
): CollaborationProvider {
  let resolveSynced!: () => void;
  let rejectSynced!: (error: Error) => void;
  let settled = false;
  const synced = new Promise<void>((resolve, reject) => {
    resolveSynced = resolve;
    rejectSynced = reject;
  });
  const provider = new HocuspocusProvider({
    url: input.url,
    name: input.documentId,
    document: input.document,
    token: input.token,
    onSynced: () => {
      if (settled) return;
      settled = true;
      resolveSynced();
    },
    onAuthenticationFailed: ({ reason }) => {
      if (settled) return;
      settled = true;
      rejectSynced(new Error(`collaboration authentication failed: ${reason}`));
    },
  });
  return {
    document: input.document,
    awareness: provider.awareness as unknown as AwarenessPort,
    whenSynced: () => synced,
    destroy: () => provider.destroy(),
  };
}

async function withTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  message: string,
): Promise<T> {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1) {
    throw new Error('syncTimeoutMs must be a positive safe integer');
  }
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error(message)), timeoutMs);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
