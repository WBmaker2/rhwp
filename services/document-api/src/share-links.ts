import { createHash, randomBytes } from 'node:crypto'

import type { DocumentRole } from './routes/complete-upload.js'

export type ShareLinkRole = Exclude<DocumentRole, 'owner'>

export interface ShareLinkRecord {
  shareId: string
  documentId: string
  role: ShareLinkRole
  enabled: boolean
  expiresAt: string | null
  createdBy: string
  createdAt: string
}

export type ShareLinkRedemption =
  | { status: 'accepted'; documentId: string; role: DocumentRole }
  | { status: 'not-found' | 'disabled' | 'expired' }

export interface ShareLinkStore {
  create(record: ShareLinkRecord): Promise<void>
  list(documentId: string, createdBy: string): Promise<ShareLinkRecord[]>
  disable(documentId: string, createdBy: string, shareId: string): Promise<boolean>
  redeem(shareId: string, uid: string, now: Date): Promise<ShareLinkRedemption>
}

export interface CreatedShareLink {
  shareId: string
  token: string
  role: ShareLinkRole
  enabled: boolean
  expiresAt: string | null
  createdAt: string
}

export class ShareLinkService {
  constructor(
    private readonly store: ShareLinkStore,
    private readonly now: () => Date = () => new Date(),
    private readonly tokenFactory: () => string = createShareToken,
  ) {}

  async create(
    documentId: string,
    ownerUid: string,
    role: ShareLinkRole,
    expiresAt: string | null,
  ): Promise<CreatedShareLink> {
    const createdAt = this.now().toISOString()
    const token = this.tokenFactory()
    const shareId = hashShareToken(token)
    const record: ShareLinkRecord = {
      shareId,
      documentId: assertIdentifier(documentId, 'documentId'),
      role: assertShareLinkRole(role),
      enabled: true,
      expiresAt: normalizeExpiry(expiresAt, createdAt),
      createdBy: assertIdentifier(ownerUid, 'ownerUid'),
      createdAt,
    }
    await this.store.create(record)
    return {
      shareId: record.shareId,
      token,
      role: record.role,
      enabled: record.enabled,
      expiresAt: record.expiresAt,
      createdAt: record.createdAt,
    }
  }

  async list(documentId: string, ownerUid: string): Promise<ShareLinkRecord[]> {
    const records = await this.store.list(
      assertIdentifier(documentId, 'documentId'),
      assertIdentifier(ownerUid, 'ownerUid'),
    )
    return records
      .map((record) => ({ ...record }))
      .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
  }

  disable(documentId: string, ownerUid: string, shareId: string): Promise<boolean> {
    return this.store.disable(
      assertIdentifier(documentId, 'documentId'),
      assertIdentifier(ownerUid, 'ownerUid'),
      assertShareId(shareId),
    )
  }

  redeem(token: string, uid: string): Promise<ShareLinkRedemption> {
    return this.store.redeem(
      hashShareToken(assertShareToken(token)),
      assertIdentifier(uid, 'uid'),
      this.now(),
    )
  }
}

export function createShareToken(): string {
  return randomBytes(32).toString('base64url')
}

export function hashShareToken(token: string): string {
  return createHash('sha256').update(assertShareToken(token), 'utf8').digest('hex')
}

function normalizeExpiry(value: string | null, createdAt: string): string | null {
  if (value === null) return null
  const expiry = new Date(value)
  if (!Number.isFinite(expiry.getTime())) throw new Error('expiresAt must be an ISO date')
  if (expiry.getTime() <= new Date(createdAt).getTime()) {
    throw new Error('expiresAt must be in the future')
  }
  return expiry.toISOString()
}

function assertShareLinkRole(value: ShareLinkRole): ShareLinkRole {
  if (value !== 'editor' && value !== 'viewer') {
    throw new Error('role must be editor or viewer')
  }
  return value
}

function assertIdentifier(value: string, name: string): string {
  const normalized = value.trim()
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(normalized)) {
    throw new Error(`${name} is invalid`)
  }
  return normalized
}

function assertShareId(value: string): string {
  const normalized = value.trim().toLowerCase()
  if (!/^[a-f0-9]{64}$/.test(normalized)) throw new Error('shareId is invalid')
  return normalized
}

function assertShareToken(value: string): string {
  const normalized = value.trim()
  if (!/^[A-Za-z0-9_-]{32,256}$/.test(normalized)) {
    throw new Error('share token is invalid')
  }
  return normalized
}
