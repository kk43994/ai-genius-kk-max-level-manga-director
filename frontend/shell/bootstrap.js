// Baseline-only bootstrap. Integration can import mount() with its shared EventTarget.
// Re-mounting disposes this baseline controller. No window globals or network requests.
import { mount } from './index.js';
export const events = new EventTarget();
export const shell = mount({ root: document, events });
