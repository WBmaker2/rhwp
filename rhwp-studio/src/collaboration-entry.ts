import {
  bootstrapStudioCollaboration,
  collaborationEnvironmentFromWindow,
  type StudioCollaborationRuntime,
} from './collaboration/bootstrap';
import { CollaborationSessionManager } from './collaboration/collaboration-session-manager';

declare global {
  interface Window {
    __rhwpStudioRuntime?: StudioCollaborationRuntime;
  }
}

const environment = collaborationEnvironmentFromWindow();
if (environment) {
  void start(environment);
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
