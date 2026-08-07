export interface CollaborationSessionEventBus {
  on(event: string, handler: (...args: unknown[]) => void): () => void;
}

export interface CollaborationSessionRuntime {
  eventBus: CollaborationSessionEventBus;
}

export type StudioCollaborationBootstrap<
  Runtime extends CollaborationSessionRuntime,
  Environment,
> = (runtime: Runtime, environment: Environment) => Promise<() => void>;

export interface CollaborationSessionWindow {
  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void;
  removeEventListener(type: string, listener: EventListenerOrEventListenerObject): void;
}

export interface CollaborationSessionManagerOptions<
  Runtime extends CollaborationSessionRuntime,
  Environment,
> {
  runtime: Runtime;
  environment: Environment;
  bootstrap: StudioCollaborationBootstrap<Runtime, Environment>;
  windowLike?: CollaborationSessionWindow;
}

/**
 * Owns one Studio collaboration runtime for the currently loaded document.
 *
 * Document replacement invalidates the current generation immediately. An
 * asynchronous bootstrap that resolves after invalidation is destroyed rather
 * than installed as the active session.
 */
export class CollaborationSessionManager<
  Runtime extends CollaborationSessionRuntime,
  Environment,
> {
  private activeDestroy: (() => void) | null = null;
  private transition: Promise<void> = Promise.resolve();
  private scheduledStart: Promise<void> | null = null;
  private generation = 0;
  private listenerDisposers: Array<() => void> = [];
  private listenersRegistered = false;
  private _lastError: unknown | null = null;

  private readonly runtime: Runtime;
  private readonly environment: Environment;
  private readonly bootstrap: StudioCollaborationBootstrap<Runtime, Environment>;
  private readonly windowLike: CollaborationSessionWindow | undefined;

  private readonly beforeUnloadHandler = (): void => {
    this.stop('beforeunload');
  };

  constructor(options: CollaborationSessionManagerOptions<Runtime, Environment>) {
    this.runtime = options.runtime;
    this.environment = options.environment;
    this.bootstrap = options.bootstrap;
    this.windowLike = options.windowLike
      ?? (typeof window === 'undefined' ? undefined : window);
  }

  get isRunning(): boolean {
    return this.activeDestroy !== null;
  }

  get lastError(): unknown | null {
    return this._lastError;
  }

  start(): Promise<void> {
    this.registerLifecycleListeners();
    if (this.activeDestroy) return Promise.resolve();
    if (this.scheduledStart) return this.scheduledStart;

    const requestedGeneration = ++this.generation;
    const run = this.enqueue(async () => {
      if (requestedGeneration !== this.generation || this.activeDestroy) return;
      await this.bootstrapGeneration(requestedGeneration);
    });
    return this.trackScheduledStart(run);
  }

  restart(_reason: string): Promise<void> {
    this.registerLifecycleListeners();
    const requestedGeneration = ++this.generation;
    this.destroyActive();

    const run = this.enqueue(async () => {
      if (requestedGeneration !== this.generation) return;
      await this.bootstrapGeneration(requestedGeneration);
    });
    return this.trackScheduledStart(run);
  }

  stop(_reason = 'manual'): void {
    ++this.generation;
    this.destroyActive();
    this.unregisterLifecycleListeners();
    this.scheduledStart = null;
  }

  private async bootstrapGeneration(requestedGeneration: number): Promise<void> {
    this._lastError = null;
    let destroy: (() => void) | null = null;
    try {
      destroy = await this.bootstrap(this.runtime, this.environment);
      if (requestedGeneration !== this.generation) {
        destroy();
        return;
      }
      this.activeDestroy = once(destroy);
    } catch (error) {
      this._lastError = error;
      if (requestedGeneration === this.generation) this.activeDestroy = null;
      throw error;
    }
  }

  private deactivateSession(_reason: string): void {
    ++this.generation;
    this.destroyActive();
    this.scheduledStart = null;
  }

  private destroyActive(): void {
    const destroy = this.activeDestroy;
    this.activeDestroy = null;
    if (!destroy) return;
    try {
      destroy();
    } catch (error) {
      this._lastError = error;
    }
  }

  private registerLifecycleListeners(): void {
    if (this.listenersRegistered) return;
    this.listenersRegistered = true;
    const { eventBus } = this.runtime;

    const on = (event: string, handler: (...args: unknown[]) => void): void => {
      this.listenerDisposers.push(eventBus.on(event, handler));
    };
    const restart = (reason: string): void => {
      void this.restart(reason).catch(() => undefined);
    };

    on('collaboration-document-replacing', () => {
      this.deactivateSession('document-replacing');
    });
    on('collaboration-document-closed', () => {
      this.deactivateSession('document-closed');
    });
    on('collaboration-document-ready', () => {
      void this.start().catch(() => undefined);
    });
    on('collaboration-fingerprint-changed', () => restart('fingerprint-changed'));
    on('collaboration-structure-changed', () => {
      this.deactivateSession('structure-changed');
    });
    on('collaboration-editable-changed', (payload) => {
      if (isStructureChange(payload)) this.deactivateSession(payload.reason);
    });

    this.windowLike?.addEventListener('beforeunload', this.beforeUnloadHandler);
  }

  private unregisterLifecycleListeners(): void {
    if (!this.listenersRegistered) return;
    this.listenersRegistered = false;
    for (const dispose of this.listenerDisposers.splice(0)) dispose();
    this.windowLike?.removeEventListener('beforeunload', this.beforeUnloadHandler);
  }

  private trackScheduledStart(run: Promise<void>): Promise<void> {
    const wrapped = run.finally(() => {
      if (this.scheduledStart === wrapped) this.scheduledStart = null;
    });
    this.scheduledStart = wrapped;
    return wrapped;
  }

  private enqueue(operation: () => Promise<void>): Promise<void> {
    const run = this.transition.then(operation, operation);
    this.transition = run.catch(() => undefined);
    return run;
  }
}

function isStructureChange(value: unknown): value is { kind: 'structure'; reason: string } {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as { kind?: unknown; reason?: unknown };
  return candidate.kind === 'structure' && typeof candidate.reason === 'string';
}

function once(callback: () => void): () => void {
  let called = false;
  return () => {
    if (called) return;
    called = true;
    callback();
  };
}
