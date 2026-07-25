export interface IdentityTokenProvider {
  getIdentityToken(audience: string): Promise<string>
}

export class MetadataIdentityTokenProvider implements IdentityTokenProvider {
  constructor(private readonly fetcher: typeof fetch = fetch) {}

  async getIdentityToken(audience: string): Promise<string> {
    const url = new URL(
      'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity',
    )
    url.searchParams.set('audience', audience)
    url.searchParams.set('format', 'full')
    const response = await this.fetcher(url, {
      headers: { 'Metadata-Flavor': 'Google' },
    })
    if (!response.ok) {
      throw new Error(`identity token request failed: ${response.status}`)
    }
    const token = (await response.text()).trim()
    if (!token) throw new Error('metadata server returned an empty identity token')
    return token
  }
}

export class HttpCollaborationFlushClient {
  constructor(
    private readonly baseUrl: string,
    private readonly internalToken: string,
    private readonly identityTokens: IdentityTokenProvider = new MetadataIdentityTokenProvider(),
    private readonly fetcher: typeof fetch = fetch,
  ) {
    if (!baseUrl.startsWith('https://')) throw new Error('collaboration URL must use https')
    if (!internalToken.trim()) throw new Error('internal collaboration token is required')
  }

  async flushForExport(documentId: string): Promise<{ path: string } | null> {
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(documentId)) throw new Error('invalid documentId')
    const audience = this.baseUrl.replace(/\/$/, '')
    const idToken = await this.identityTokens.getIdentityToken(audience)
    const response = await this.fetcher(
      `${audience}/internal/documents/${documentId}/flush`,
      {
        method: 'POST',
        headers: {
          authorization: `Bearer ${idToken}`,
          'x-rhwp-internal-token': this.internalToken,
          'content-type': 'application/json',
        },
        body: '{}',
      },
    )
    if (response.status === 409) return null
    if (!response.ok) throw new Error(`collaboration flush failed: ${response.status}`)
    const body = await response.json() as { path?: unknown }
    if (typeof body.path !== 'string' || !body.path.startsWith('documents/')) {
      throw new Error('collaboration flush returned an invalid snapshot path')
    }
    return { path: body.path }
  }
}
