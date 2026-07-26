import {
  createShareInvitationUrl,
  type ShareLinkClient,
  type ShareLinkMetadata,
  type ShareLinkRole,
} from './ShareLinkClient';

export interface ShareDialogOptions {
  documentId: string;
  client: Pick<ShareLinkClient, 'create' | 'list' | 'disable'>;
  parent?: HTMLElement;
  copyText?: (value: string) => Promise<void>;
  now?: () => Date;
}

export class ShareDialog {
  readonly element: HTMLDivElement;
  private readonly panel: HTMLDivElement;
  private readonly links: HTMLDivElement;
  private readonly status: HTMLDivElement;
  private readonly role: HTMLSelectElement;
  private readonly expiry: HTMLSelectElement;
  private readonly createButton: HTMLButtonElement;
  private openGeneration = 0;

  constructor(private readonly options: ShareDialogOptions) {
    this.element = document.createElement('div');
    this.element.setAttribute('role', 'dialog');
    this.element.setAttribute('aria-modal', 'true');
    this.element.setAttribute('aria-label', '문서 공유');
    Object.assign(this.element.style, {
      position: 'fixed',
      inset: '0',
      zIndex: '13000',
      display: 'none',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'rgba(0,0,0,0.32)',
      font: '13px system-ui, sans-serif',
    });

    this.panel = document.createElement('div');
    Object.assign(this.panel.style, {
      width: 'min(520px, calc(100vw - 32px))',
      maxHeight: 'min(680px, calc(100vh - 32px))',
      overflow: 'auto',
      padding: '18px',
      borderRadius: '12px',
      background: '#fff',
      boxShadow: '0 14px 42px rgba(0,0,0,0.28)',
      color: '#202124',
    });

    const header = document.createElement('div');
    Object.assign(header.style, {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: '14px',
    });
    const title = document.createElement('strong');
    title.textContent = '문서 공유';
    title.style.fontSize = '17px';
    const close = button('닫기');
    close.addEventListener('click', () => this.close());
    header.append(title, close);

    const form = document.createElement('div');
    Object.assign(form.style, {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr auto',
      gap: '8px',
      alignItems: 'end',
      marginBottom: '12px',
    });
    this.role = selectField('권한', [
      ['viewer', '보기 전용'],
      ['editor', '편집 가능'],
    ]);
    this.expiry = selectField('만료', [
      ['none', '만료 없음'],
      ['1', '1일'],
      ['7', '7일'],
      ['30', '30일'],
    ]);
    this.createButton = button('링크 만들기');
    this.createButton.addEventListener('click', () => void this.createLink());
    form.append(this.role.parentElement!, this.expiry.parentElement!, this.createButton);

    this.status = document.createElement('div');
    this.status.setAttribute('aria-live', 'polite');
    Object.assign(this.status.style, {
      minHeight: '18px',
      marginBottom: '10px',
      color: '#5f6368',
    });

    const subheading = document.createElement('strong');
    subheading.textContent = '발급된 링크';
    this.links = document.createElement('div');
    Object.assign(this.links.style, {
      display: 'grid',
      gap: '8px',
      marginTop: '8px',
    });

    this.panel.append(header, form, this.status, subheading, this.links);
    this.element.append(this.panel);
    (options.parent ?? document.body).append(this.element);
    this.element.addEventListener('click', (event) => {
      if (event.target === this.element) this.close();
    });
  }

  async open(): Promise<void> {
    this.element.style.display = 'flex';
    const generation = ++this.openGeneration;
    this.setStatus('공유 링크를 불러오는 중…');
    try {
      const links = await this.options.client.list(this.options.documentId);
      if (generation !== this.openGeneration) return;
      this.renderLinks(links);
      this.setStatus('');
      this.createButton.focus();
    } catch (error) {
      if (generation !== this.openGeneration) return;
      this.setStatus(errorMessage(error), true);
    }
  }

  close(): void {
    this.openGeneration += 1;
    this.element.style.display = 'none';
  }

  destroy(): void {
    this.openGeneration += 1;
    this.element.remove();
  }

  private async createLink(): Promise<void> {
    this.createButton.disabled = true;
    this.setStatus('공유 링크를 만드는 중…');
    try {
      const created = await this.options.client.create(
        this.options.documentId,
        this.role.value as ShareLinkRole,
        expiryIso(this.expiry.value, this.options.now?.() ?? new Date()),
      );
      const invitationUrl = createShareInvitationUrl(created.token);
      await (this.options.copyText ?? copyText)(invitationUrl);
      this.showCreatedLink(invitationUrl);
      this.renderLinks(await this.options.client.list(this.options.documentId));
      this.setStatus('새 링크를 클립보드에 복사했습니다. 이 화면을 닫으면 원문 링크는 다시 볼 수 없습니다.');
    } catch (error) {
      this.setStatus(errorMessage(error), true);
    } finally {
      this.createButton.disabled = false;
    }
  }

  private showCreatedLink(url: string): void {
    const wrapper = document.createElement('div');
    Object.assign(wrapper.style, {
      display: 'flex',
      gap: '6px',
      marginBottom: '12px',
    });
    const input = document.createElement('input');
    input.readOnly = true;
    input.value = url;
    input.setAttribute('aria-label', '새 공유 링크');
    Object.assign(input.style, { flex: '1', minWidth: '0', padding: '7px' });
    const copy = button('복사');
    copy.addEventListener('click', async () => {
      try {
        await (this.options.copyText ?? copyText)(url);
        this.setStatus('공유 링크를 복사했습니다.');
      } catch (error) {
        this.setStatus(errorMessage(error), true);
      }
    });
    wrapper.append(input, copy);
    this.panel.insertBefore(wrapper, this.status);
    input.select();
  }

  private renderLinks(links: ShareLinkMetadata[]): void {
    const rows = links.map((link) => {
      const row = document.createElement('div');
      Object.assign(row.style, {
        display: 'grid',
        gridTemplateColumns: '1fr auto',
        alignItems: 'center',
        gap: '8px',
        padding: '8px',
        border: '1px solid #dadce0',
        borderRadius: '8px',
        opacity: link.enabled ? '1' : '0.62',
      });
      const label = document.createElement('div');
      const role = link.role === 'editor' ? '편집 가능' : '보기 전용';
      const expiry = link.expiresAt
        ? ` · ${new Date(link.expiresAt).toLocaleString()} 만료`
        : ' · 만료 없음';
      label.textContent = `${role}${expiry}${link.enabled ? '' : ' · 사용 중지됨'}`;
      const disable = button('사용 중지');
      disable.disabled = !link.enabled;
      disable.addEventListener('click', async () => {
        disable.disabled = true;
        try {
          await this.options.client.disable(this.options.documentId, link.shareId);
          this.renderLinks(await this.options.client.list(this.options.documentId));
          this.setStatus('공유 링크를 사용 중지했습니다.');
        } catch (error) {
          disable.disabled = false;
          this.setStatus(errorMessage(error), true);
        }
      });
      row.append(label, disable);
      return row;
    });
    if (rows.length === 0) {
      const empty = document.createElement('div');
      empty.textContent = '발급된 공유 링크가 없습니다.';
      empty.style.color = '#5f6368';
      rows.push(empty);
    }
    this.links.replaceChildren(...rows);
  }

  private setStatus(message: string, error = false): void {
    this.status.textContent = message;
    this.status.style.color = error ? '#b3261e' : '#5f6368';
  }
}

function button(label: string): HTMLButtonElement {
  const element = document.createElement('button');
  element.type = 'button';
  element.textContent = label;
  Object.assign(element.style, {
    padding: '7px 10px',
    border: '1px solid #dadce0',
    borderRadius: '6px',
    background: '#fff',
    cursor: 'pointer',
  });
  return element;
}

function selectField(
  labelText: string,
  options: Array<[string, string]>,
): HTMLSelectElement {
  const label = document.createElement('label');
  label.textContent = labelText;
  Object.assign(label.style, { display: 'grid', gap: '4px' });
  const select = document.createElement('select');
  select.style.padding = '7px';
  for (const [value, text] of options) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = text;
    select.append(option);
  }
  label.append(select);
  return select;
}

function expiryIso(value: string, now: Date): string | null {
  if (value === 'none') return null;
  const days = Number(value);
  if (!Number.isSafeInteger(days) || days < 1 || days > 30) {
    throw new Error('공유 링크 만료 기간이 올바르지 않습니다.');
  }
  return new Date(now.getTime() + days * 24 * 60 * 60 * 1_000).toISOString();
}

async function copyText(value: string): Promise<void> {
  if (!navigator.clipboard?.writeText) throw new Error('클립보드를 사용할 수 없습니다.');
  await navigator.clipboard.writeText(value);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
