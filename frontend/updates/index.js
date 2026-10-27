import { mountVersionNotice } from './version-checker.mjs';

// currentBuild/getSafetyState/saveDraft are explicit integration dependencies.
// Missing adapters fail closed; this module never infers “saved” from the DOM.
export function mount({ root, api, events, session, currentBuild, getSafetyState, saveDraft, publicBasePath = '/' }) {
  try {
    const stamp = root.ownerDocument.getElementById('asset-lab-build');
    const current = currentBuild || JSON.parse(stamp?.textContent || 'null');
    const view = mountVersionNotice(root, { current, api, basePath: publicBasePath, getSafetyState, saveDraft,
      onState: state => events?.dispatchEvent(new CustomEvent('release:changed', { detail: state })) });
    return { unmount: () => view.destroy(), checker: view.checker };
  } catch {
    const message = root.ownerDocument.createElement('p');
    message.textContent = '版本信息尚未就绪；当前工作内容会保留。'; root.append(message);
    return { unmount: () => message.remove() };
  }
}
