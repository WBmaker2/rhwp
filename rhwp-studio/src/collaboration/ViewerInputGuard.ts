const MUTATING_COMMAND_PREFIXES = [
  'format:',
  'insert:',
  'table:',
  'page:',
] as const;

const MUTATING_COMMANDS = new Set([
  'edit:cut',
  'edit:paste',
  'edit:delete',
  'edit:undo',
  'edit:redo',
  'edit:find-replace',
  'file:new-doc',
]);

export function installViewerInputGuard(
  documentTarget: Document = document,
): () => void {
  const root = documentTarget.documentElement;
  root.dataset.collaborationReadOnly = 'true';

  const block = (event: Event): void => {
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  const onBeforeInput = (event: InputEvent): void => block(event);
  const onInput = (event: Event): void => {
    const target = event.target;
    if (target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement) {
      target.value = '';
    } else if (target instanceof HTMLElement && target.isContentEditable) {
      target.textContent = '';
    }
    block(event);
  };
  const onKeyDown = (event: KeyboardEvent): void => {
    if (!isViewerMutationKey(event)) return;
    block(event);
  };
  const onCommandClick = (event: MouseEvent): void => {
    const target = event.target instanceof Element
      ? event.target.closest<HTMLElement>('[data-cmd]')
      : null;
    const command = target?.dataset.cmd ?? '';
    if (!isMutatingCommand(command)) return;
    block(event);
  };

  documentTarget.addEventListener('beforeinput', onBeforeInput, true);
  documentTarget.addEventListener('input', onInput, true);
  documentTarget.addEventListener('keydown', onKeyDown, true);
  documentTarget.addEventListener('paste', block, true);
  documentTarget.addEventListener('cut', block, true);
  documentTarget.addEventListener('drop', block, true);
  documentTarget.addEventListener('click', onCommandClick, true);

  return () => {
    documentTarget.removeEventListener('beforeinput', onBeforeInput, true);
    documentTarget.removeEventListener('input', onInput, true);
    documentTarget.removeEventListener('keydown', onKeyDown, true);
    documentTarget.removeEventListener('paste', block, true);
    documentTarget.removeEventListener('cut', block, true);
    documentTarget.removeEventListener('drop', block, true);
    documentTarget.removeEventListener('click', onCommandClick, true);
    delete root.dataset.collaborationReadOnly;
  };
}

export function isViewerMutationKey(event: Pick<KeyboardEvent,
  'key' | 'ctrlKey' | 'metaKey' | 'altKey' | 'isComposing'
>): boolean {
  if (event.isComposing) return true;
  const modifier = event.ctrlKey || event.metaKey || event.altKey;
  if (!modifier && event.key.length === 1) return true;
  return event.key === 'Backspace'
    || event.key === 'Delete'
    || event.key === 'Enter';
}

export function isMutatingCommand(command: string): boolean {
  return MUTATING_COMMANDS.has(command)
    || MUTATING_COMMAND_PREFIXES.some((prefix) => command.startsWith(prefix));
}
