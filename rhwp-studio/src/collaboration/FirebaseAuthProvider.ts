import { initializeApp, type FirebaseApp, type FirebaseOptions } from 'firebase/app';
import {
  GoogleAuthProvider,
  connectAuthEmulator,
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  type Auth,
  type User,
} from 'firebase/auth';
import {
  connectFirestoreEmulator,
  doc,
  getDoc,
  getFirestore,
  type Firestore,
} from 'firebase/firestore';

import type {
  CollaborationAuthPort,
  CollaborationSession,
  DocumentRole,
} from './CollaborationController';

export interface FirebaseAuthProviderOptions {
  firebase: FirebaseOptions;
  authEmulatorUrl?: string;
  firestoreEmulatorHost?: string;
  firestoreEmulatorPort?: number;
  emulatorTestUser?: {
    email: string;
    password: string;
  };
  app?: FirebaseApp;
  auth?: Auth;
  firestore?: Firestore;
}

export class FirebaseAuthProvider implements CollaborationAuthPort {
  readonly app: FirebaseApp;
  readonly auth: Auth;
  readonly firestore: Firestore;
  private readonly emulatorTestUser: FirebaseAuthProviderOptions['emulatorTestUser'];

  constructor(options: FirebaseAuthProviderOptions) {
    this.app = options.app ?? initializeApp(options.firebase);
    this.auth = options.auth ?? getAuth(this.app);
    this.firestore = options.firestore ?? getFirestore(this.app);
    this.emulatorTestUser = options.emulatorTestUser;

    if (this.emulatorTestUser && !options.authEmulatorUrl) {
      throw new Error('Emulator test user requires Auth Emulator');
    }
    if (options.authEmulatorUrl) {
      connectAuthEmulator(this.auth, options.authEmulatorUrl, {
        disableWarnings: true,
      });
    }
    if (options.firestoreEmulatorHost && options.firestoreEmulatorPort) {
      connectFirestoreEmulator(
        this.firestore,
        options.firestoreEmulatorHost,
        options.firestoreEmulatorPort,
      );
    }
  }

  async requireSession(documentId: string): Promise<CollaborationSession> {
    const authenticated = await this.requireUser();
    const role = await this.loadRole(documentId, authenticated.uid);
    if (!role) throw new Error('이 문서의 공동 편집 멤버가 아닙니다.');

    return {
      identity: {
        userId: authenticated.uid,
        displayName: authenticated.displayName ?? authenticated.email ?? '',
        photoURL: authenticated.photoURL,
      },
      role,
      idToken: await authenticated.getIdToken(),
    };
  }

  async getIdToken(): Promise<string> {
    return (await this.requireUser()).getIdToken();
  }

  async signIn(): Promise<User> {
    if (this.emulatorTestUser) {
      const result = await signInWithEmailAndPassword(
        this.auth,
        this.emulatorTestUser.email,
        this.emulatorTestUser.password,
      );
      return result.user;
    }
    const result = await signInWithPopup(this.auth, new GoogleAuthProvider());
    return result.user;
  }

  private async requireUser(): Promise<User> {
    const user = this.auth.currentUser ?? await this.waitForInitialUser();
    return user ?? this.signIn();
  }

  private async loadRole(
    documentId: string,
    userId: string,
  ): Promise<DocumentRole | null> {
    const snapshot = await getDoc(
      doc(this.firestore, 'documents', documentId, 'members', userId),
    );
    if (!snapshot.exists()) return null;
    const role = snapshot.get('role');
    return isDocumentRole(role) ? role : null;
  }

  private waitForInitialUser(): Promise<User | null> {
    return new Promise((resolve) => {
      const unsubscribe = onAuthStateChanged(this.auth, (user) => {
        unsubscribe();
        resolve(user);
      });
    });
  }
}

function isDocumentRole(value: unknown): value is DocumentRole {
  return value === 'owner' || value === 'editor' || value === 'viewer';
}
