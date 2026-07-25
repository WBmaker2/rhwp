export class CollaborationManifestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CollaborationManifestError';
  }
}

export class CollaborationContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CollaborationContractError';
  }
}
