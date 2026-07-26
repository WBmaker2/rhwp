import type { CollaborationConnectionState } from './CollaborationController';
import type { RemoteParticipant } from './PresenceController';

const PALETTE = [
  '#d32f2f', '#7b1fa2', '#303f9f', '#1976d2', '#00796b',
  '#388e3c', '#f57c00', '#e64a19', '#5d4037', '#455a64',
] as const;

export class PresenceView {
  readonly element: HTMLDivElement;
  private readonly status: HTMLSpanElement;
  private readonly participants: HTMLDivElement;
  private readonly shareButton: HTMLButtonElement;
  private shareAction: (() => void) | null = null;
  private role: CollaborationConnectionState['role'] | null = null;

  constructor(parent: HTMLElement = document.body) {
    this.element = document.createElement('div');
    this.element.id = 'collaboration-presence';
    this.element.dataset.testid = 'collaboration-presence';
    Object.assign(this.element.style, {
      position: 'fixed',
      top: '8px',
      right: '12px',
      zIndex: '12000',
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      padding: '6px 8px',
      borderRadius: '8px',
      background: 'rgba(255,255,255,0.96)',
      boxShadow: '0 2px 10px rgba(0,0,0,0.18)',
      font: '12px system-ui, sans-serif',
    });
    this.status = document.createElement('span');
    this.status.dataset.testid = 'collaboration-status';
    this.participants = document.createElement('div');
    this.participants.dataset.testid = 'collaboration-participants';
    this.participants.setAttribute('aria-label', '공동 편집 접속자');
    Object.assign(this.participants.style, { display: 'flex', gap: '4px' });
    this.shareButton = document.createElement('button');
    this.shareButton.type = 'button';
    this.shareButton.textContent = '공유';
    this.shareButton.dataset.testid = 'collaboration-share';
    this.shareButton.setAttribute('aria-label', '공유 링크 관리');
    Object.assign(this.shareButton.style, {
      display: 'none',
      padding: '3px 7px',
      border: '1px solid #dadce0',
      borderRadius: '5px',
      background: '#fff',
      cursor: 'pointer',
    });
    this.shareButton.addEventListener('click', () => this.shareAction?.());
    this.element.append(this.status, this.participants, this.shareButton);
    parent.append(this.element);
    this.setPending();
  }

  setPending(): void {
    this.status.textContent = '공동 편집 연결 중…';
  }

  setError(error: unknown): void {
    this.status.textContent = `공동 편집 오류: ${error instanceof Error ? error.message : String(error)}`;
  }

  setShareAction(action: (() => void) | null): void {
    this.shareAction = action;
    this.updateShareButton();
  }

  setConnected(state: CollaborationConnectionState): void {
    this.role = state.role;
    this.element.dataset.role = state.role;
    const roleLabel = state.role === 'owner' ? '소유자' : state.role === 'editor' ? '편집자' : '열람자';
    this.status.textContent = `${state.identity.displayName || state.identity.userId} · ${roleLabel}`;
    this.renderParticipants(state.participants);
    this.updateShareButton();
  }

  renderParticipants(participants: RemoteParticipant[]): void {
    this.participants.replaceChildren(...participants.map((participant) => {
      const chip = document.createElement('span');
      chip.dataset.testid = 'collaboration-participant';
      chip.dataset.userId = participant.state.userId;
      chip.textContent = participant.state.displayName || participant.state.userId;
      chip.title = participant.state.userId;
      Object.assign(chip.style, {
        borderLeft: `4px solid ${PALETTE[participant.state.colorIndex]}`,
        padding: '2px 5px',
        borderRadius: '4px',
        background: '#f4f4f4',
        whiteSpace: 'nowrap',
      });
      return chip;
    }));
  }

  destroy(): void {
    this.shareAction = null;
    this.element.remove();
  }

  private updateShareButton(): void {
    this.shareButton.style.display = this.role === 'owner' && this.shareAction ? 'inline-block' : 'none';
  }
}
