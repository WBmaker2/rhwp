export type ShareLinkRole = 'editor' | 'viewer';
export type RedeemedDocumentRole = 'owner' | ShareLinkRole;

export interface ShareLinkMetadata {
  shareId: string;
  role: ShareLinkRole;
  enabled: boolean;
  expiresAt: string | null;
  createdAt: string;
}

export interface CreatedShareLink extends ShareLinkMetadata {
  token: string;
}

export interface ShareLinkClientOptions {
  apiBaseUrl: string;
  getIdToken(): Promise<string>;
  fetch?: typeof globalThis.fetch;
}

export interface ShareLocationLike {
  origin: string;
  pathname: string;
  hash: string;
}

export class ShareLinkClient {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof globalThis.fetch;

  constructor(private readonly options: ShareLinkClientOptions) {
    this.apiBaseUrl = normalizeBaseUrl(options.apiBaseUrl);
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  async create(
    documentId: string,
    role: ShareLinkRole,
    expiresAt: string | null,
  ): Promise<CreatedShareLink> {
    const body = await this.request(
      `/v1/documents/${encodeURIComponent(documentId)}/share-links`,
      {
        method: 'POST',
        body: JSON.stringify({ role, expiresAt }),
      },
    );
    return parseCreatedLink(body);
  }

  async list(documentId: string): Promise<ShareLinkMetadata[]> {
    const body = await this.request(
      `/v1/documents/${encodeURIComponent(documentId)}/share-links`,
      { method: 'GET' },
    );
    if (!body || typeof body !== 'object' || !Array.isArray((body as { links?: unknown }).links)) {
      throw new Error('공유 링크 목록 응답이 올바르지 않습니다.');
    }
    return (body as { links: unknown[] }).links.map(parseLinkMetadata);
  }

  async disable(documentId: string, shareId: string): Promise<void> {
    await this.request(
      `/v1/documents/${encodeURIComponent(documentId)}/share-links/${encodeURIComponent(shareId)}`,
      { method: 'DELETE' },
    );
  }

  async redeem(token: string): Promise<{
    documentId: string;
    role: RedeemedDocumentRole;
  }> {
    const body = await this.request('/v1/share-links/redeem', {
      method: 'POST',
      body: JSON.stringify({ token }),
    });
    if (!body || typeof body !== 'object') throw new Error('공유 링크 수락 응답이 없습니다.');
    const input = body as Record<string, unknown>;
    if (
      input.status !== 'accepted'
      || typeof input.documentId !== 'string'
      || !isDocumentRole(input.role)
    ) {
      throw new Error('공유 링크 수락 응답이 올바르지 않습니다.');
    }
    return { documentId: input.documentId, role: input.role };
  }

  private async request(path: string, init: RequestInit): Promise<unknown> {
    const idToken = await this.options.getIdToken();
    const response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${idToken}`,
        ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...init.headers,
      },
      cache: 'no-store',
    });
    const body = await readJson(response);
    if (!response.ok) {
      const message = body && typeof body === 'object' && typeof (body as { error?: unknown }).error === 'string'
        ? (body as { error: string }).error
        : `HTTP ${response.status}`;
      throw new Error(`공유 링크 요청 실패: ${message}`);
    }
    return body;
  }
}

export function createShareInvitationUrl(
  token: string,
  location: Pick<ShareLocationLike, 'origin' | 'pathname'> = window.location,
): string {
  return `${location.origin}${location.pathname}#/share/${encodeURIComponent(token)}`;
}

export function shareTokenFromHash(hash: string): string | null {
  const match = /^#\/share\/([^/?#]+)$/.exec(hash.trim());
  if (!match?.[1]) return null;
  try {
    const token = decodeURIComponent(match[1]).trim();
    return /^[A-Za-z0-9_-]{32,256}$/.test(token) ? token : null;
  } catch {
    return null;
  }
}

export function collaborationUrlAfterRedemption(
  location: Pick<ShareLocationLike, 'origin' | 'pathname'>,
  documentId: string,
): string {
  const url = new URL(location.pathname, location.origin);
  url.searchParams.set('collabDocument', documentId);
  return url.toString();
}

function normalizeBaseUrl(value: string): string {
  const normalized = value.trim().replace(/\/+$/, '');
  const url = new URL(normalized);
  if (url.protocol !== 'https:' && url.hostname !== 'localhost' && url.hostname !== '127.0.0.1') {
    throw new Error('Document API URL은 HTTPS여야 합니다.');
  }
  return normalized;
}

function parseCreatedLink(value: unknown): CreatedShareLink {
  const metadata = parseLinkMetadata(value);
  const token = value && typeof value === 'object' ? (value as { token?: unknown }).token : null;
  if (typeof token !== 'string' || token.length < 32) {
    throw new Error('새 공유 링크 토큰이 없습니다.');
  }
  return { ...metadata, token };
}

function parseLinkMetadata(value: unknown): ShareLinkMetadata {
  if (!value || typeof value !== 'object') throw new Error('공유 링크 응답이 올바르지 않습니다.');
  const input = value as Record<string, unknown>;
  if (
    typeof input.shareId !== 'string'
    || !isShareRole(input.role)
    || typeof input.enabled !== 'boolean'
    || (input.expiresAt !== null && typeof input.expiresAt !== 'string')
    || typeof input.createdAt !== 'string'
  ) {
    throw new Error('공유 링크 응답이 올바르지 않습니다.');
  }
  return {
    shareId: input.shareId,
    role: input.role,
    enabled: input.enabled,
    expiresAt: input.expiresAt,
    createdAt: input.createdAt,
  };
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error('Document API가 잘못된 JSON을 반환했습니다.');
  }
}

function isShareRole(value: unknown): value is ShareLinkRole {
  return value === 'editor' || value === 'viewer';
}

function isDocumentRole(value: unknown): value is RedeemedDocumentRole {
  return value === 'owner' || isShareRole(value);
}
