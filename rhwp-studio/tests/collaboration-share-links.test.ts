import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  ShareLinkClient,
  collaborationUrlAfterRedemption,
  createShareInvitationUrl,
  shareTokenFromHash,
} from '../src/collaboration/ShareLinkClient.ts';

const token = 'abcdefghijklmnopqrstuvwxyzABCDE_1234567890-xyz';

function clientFixture() {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const responses: Response[] = [];
  const client = new ShareLinkClient({
    apiBaseUrl: 'https://document-api.example/',
    getIdToken: async () => 'firebase-token',
    fetch: async (input, init) => {
      calls.push({ url: String(input), init: init ?? {} });
      const response = responses.shift();
      if (!response) throw new Error('missing fake response');
      return response;
    },
  });
  return { client, calls, responses };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

test('creates a link with bearer authentication and never places the raw token in the request URL', async () => {
  const fixture = clientFixture();
  fixture.responses.push(jsonResponse({
    shareId: 'a'.repeat(64),
    token,
    role: 'viewer',
    enabled: true,
    expiresAt: null,
    createdAt: '2026-07-26T01:00:00.000Z',
  }, 201));

  const created = await fixture.client.create('doc-1', 'viewer', null);

  assert.equal(created.token, token);
  assert.equal(fixture.calls.length, 1);
  assert.equal(fixture.calls[0]!.url, 'https://document-api.example/v1/documents/doc-1/share-links');
  assert.equal(fixture.calls[0]!.url.includes(token), false);
  assert.equal((fixture.calls[0]!.init.headers as Record<string, string>).Authorization, 'Bearer firebase-token');
  assert.deepEqual(JSON.parse(String(fixture.calls[0]!.init.body)), {
    role: 'viewer',
    expiresAt: null,
  });
})

test('lists and disables share links without exposing a token field', async () => {
  const fixture = clientFixture();
  fixture.responses.push(jsonResponse({
    links: [{
      shareId: 'a'.repeat(64),
      role: 'editor',
      enabled: true,
      expiresAt: null,
      createdAt: '2026-07-26T01:00:00.000Z',
    }],
  }));
  fixture.responses.push(jsonResponse({ status: 'disabled' }));

  const links = await fixture.client.list('doc-1');
  await fixture.client.disable('doc-1', links[0]!.shareId);

  assert.equal(links.length, 1);
  assert.equal('token' in links[0]!, false);
  assert.match(fixture.calls[1]!.url, /\/share-links\/[a-f0-9]{64}$/);
  assert.equal(fixture.calls[1]!.init.method, 'DELETE');
})

test('redeems a raw token only in a protected POST body', async () => {
  const fixture = clientFixture();
  fixture.responses.push(jsonResponse({
    status: 'accepted',
    documentId: 'doc-1',
    role: 'editor',
  }));

  const redeemed = await fixture.client.redeem(token);

  assert.deepEqual(redeemed, { documentId: 'doc-1', role: 'editor' });
  assert.equal(fixture.calls[0]!.url, 'https://document-api.example/v1/share-links/redeem');
  assert.equal(fixture.calls[0]!.url.includes(token), false);
  assert.deepEqual(JSON.parse(String(fixture.calls[0]!.init.body)), { token });
})

test('surfaces server errors without echoing the raw token', async () => {
  const fixture = clientFixture();
  fixture.responses.push(jsonResponse({ error: 'share-link-expired' }, 410));

  await assert.rejects(fixture.client.redeem(token), /share-link-expired/);
})

test('builds and parses route-safe fragment invitation URLs', () => {
  const url = createShareInvitationUrl(token, {
    origin: 'https://rhwp.example',
    pathname: '/editor/',
  });

  assert.equal(url, `https://rhwp.example/editor/#/share/${token}`);
  assert.equal(shareTokenFromHash(`#/share/${token}`), token);
  assert.equal(shareTokenFromHash('#/share/not valid'), null);
  assert.equal(shareTokenFromHash('#/other/value'), null);
})

test('redemption redirect removes the raw token and retains only the document ID', () => {
  const url = collaborationUrlAfterRedemption({
    origin: 'https://rhwp.example',
    pathname: '/editor/',
  }, 'doc-1');

  assert.equal(url, 'https://rhwp.example/editor/?collabDocument=doc-1');
  assert.equal(url.includes(token), false);
})
