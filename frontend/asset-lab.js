// Customer workflow entrypoint. The shared shell/integrator calls mount once.
// No global CLI state, legacy APIs, browser-supplied tenant or hidden auto-submit.
export {mount} from './workflow/controller.js';
