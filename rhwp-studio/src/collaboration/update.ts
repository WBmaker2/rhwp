import { CollaborationContractError } from './errors.ts';
import type { CollaborationContext } from './collaboration-context.ts';
export const COLLABORATION_UPDATE_VERSION = 1 as const;
export const MAX_COLLABORATION_TEXT_BYTES = 1024 * 1024;
export interface CollaborationTextUpdate { version: 1; updateId: string; documentFingerprint: string; nodeId: string; nodeKind: 'paragraph'|'cell'; text: string; clientId: string; sequence: number; }
export function validateCollaborationTextUpdate(value: unknown, context: CollaborationContext): CollaborationTextUpdate {
  if (!value || typeof value !== 'object') throw new CollaborationContractError('update must be an object');
  const u=value as Record<string, unknown>;
  if (u.version !== 1) throw new CollaborationContractError('unsupported update version');
  for (const key of ['updateId','documentFingerprint','nodeId','clientId'] as const) if (typeof u[key] !== 'string' || !(u[key] as string).trim()) throw new CollaborationContractError(`${key} must be non-empty`);
  if (u.documentFingerprint !== context.sourceFingerprint) throw new CollaborationContractError('document fingerprint mismatch');
  if (u.nodeKind !== 'paragraph' && u.nodeKind !== 'cell') throw new CollaborationContractError('unsupported node kind');
  if (typeof u.text !== 'string') throw new CollaborationContractError('text must be a string');
  if (new TextEncoder().encode(u.text).byteLength > MAX_COLLABORATION_TEXT_BYTES) throw new CollaborationContractError('text exceeds maximum size');
  if (!Number.isSafeInteger(u.sequence) || (u.sequence as number) < 0) throw new CollaborationContractError('sequence must be a non-negative safe integer');
  const loc=context.registry.get(u.nodeId as string); if (!loc) throw new CollaborationContractError('unknown collaboration node');
  if (loc.kind !== u.nodeKind) throw new CollaborationContractError('node kind mismatch');
  return u as unknown as CollaborationTextUpdate;
}
