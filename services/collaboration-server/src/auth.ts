import type { Auth } from 'firebase-admin/auth'
import type { Firestore } from 'firebase-admin/firestore'

export type DocumentRole = 'owner' | 'editor' | 'viewer'
export type AuthorizationErrorCode =
  | 'invalid-request'
  | 'unauthenticated'
  | 'forbidden'

export interface VerifiedIdentity {
  uid: string
  displayName: string | null
  photoURL: string | null
}

export interface TokenVerifier {
  verifyIdToken(idToken: string): Promise<VerifiedIdentity>
}

export interface DocumentMembership {
  role: DocumentRole
}

export interface MembershipStore {
  getMembership(
    documentId: string,
    userId: string,
  ): Promise<DocumentMembership | null>
}

export interface ConnectionAuthInput {
  documentId: string
  idToken: string
  tokenVerifier: TokenVerifier
  membershipStore: MembershipStore
}

export interface AuthorizedConnection {
  documentId: string
  userId: string
  role: DocumentRole
  displayName: string
  photoURL: string | null
}

export class ConnectionAuthorizationError extends Error {
  constructor(readonly code: AuthorizationErrorCode, message: string) {
    super(message)
    this.name = 'ConnectionAuthorizationError'
  }
}

export async function verifyConnection(
  input: ConnectionAuthInput,
): Promise<AuthorizedConnection> {
  const documentId = input.documentId.trim()
  if (documentId.length === 0) {
    throw new ConnectionAuthorizationError(
      'invalid-request',
      'documentId must not be empty',
    )
  }

  if (input.idToken.trim().length === 0) {
    throw new ConnectionAuthorizationError(
      'unauthenticated',
      'Firebase ID token is required',
    )
  }

  let identity: VerifiedIdentity
  try {
    identity = await input.tokenVerifier.verifyIdToken(input.idToken)
  } catch (error) {
    if (error instanceof ConnectionAuthorizationError) {
      throw error
    }
    throw new ConnectionAuthorizationError(
      'unauthenticated',
      'Firebase ID token verification failed',
    )
  }

  if (identity.uid.trim().length === 0) {
    throw new ConnectionAuthorizationError(
      'unauthenticated',
      'verified Firebase identity has no uid',
    )
  }

  const membership = await input.membershipStore.getMembership(
    documentId,
    identity.uid,
  )
  if (!membership) {
    throw new ConnectionAuthorizationError(
      'forbidden',
      'user is not a member of this document',
    )
  }

  return {
    documentId,
    userId: identity.uid,
    role: membership.role,
    displayName: identity.displayName ?? '',
    photoURL: identity.photoURL,
  }
}

export function createFirebaseTokenVerifier(
  auth: Pick<Auth, 'verifyIdToken'>,
): TokenVerifier {
  return {
    async verifyIdToken(idToken) {
      const decodedToken = await auth.verifyIdToken(idToken)
      return {
        uid: decodedToken.uid,
        displayName:
          typeof decodedToken.name === 'string' ? decodedToken.name : null,
        photoURL:
          typeof decodedToken.picture === 'string' ? decodedToken.picture : null,
      }
    },
  }
}

export function createFirestoreMembershipStore(
  firestore: Pick<Firestore, 'doc'>,
): MembershipStore {
  return {
    async getMembership(documentId, userId) {
      const snapshot = await firestore
        .doc(`documents/${documentId}/members/${userId}`)
        .get()
      if (!snapshot.exists) {
        return null
      }

      const role = snapshot.get('role')
      return isDocumentRole(role) ? { role } : null
    },
  }
}

function isDocumentRole(value: unknown): value is DocumentRole {
  return value === 'owner' || value === 'editor' || value === 'viewer'
}
