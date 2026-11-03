'use strict';
// The approved artwork stays intact. Stop the clock when paused, hidden or covered by content.
(() => {
  const find = selector => document.querySelector(selector);
  const stage = find('#film-stage'), camera = find('.art-camera');
  const hero = find('.hero'), story = find('.paper-story');
  const intro = find('.hero-intro'), caption = find('.camera-caption');
  const pause = find('#motion-toggle'), iris = find('.iris-frame'), shade = find('.cinema-shade');
  const indicator = find('.shot-indicator small'), topFilm = find('.film-upper'), bottomFilm = find('.film-lower');
  const glints = [...document.querySelectorAll('.glint')], dust = find('.film-dust');
  if (![stage, camera, hero, story, intro, caption, pause, iris, shade, indicator, topFilm, bottomFilm, dust].every(Boolean)) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const touch = matchMedia('(hover: none) and (pointer: coarse)');
  const clamp = (n, a = 0, b = 1) => Math.max(a, Math.min(b, n));
  const ease = n => n * n * (3 - 2 * n);
  let userPaused = false, paused = reduced.matches, active = true;
  let x = 0, y = 0, sx = 0, sy = 0, time = 0, last = 0, raf = 0;
  let heroHeight = 0, storyHeight = 0, mobile = false, light = false;
  let rendered = false, push = 0, chapterMove = 0;
  let lastAperture = '';
  // Unchanged textContent recreates text nodes and can cause layout on every frame.
  const style = (node, key, value) => { if (node.style[key] !== value) node.style[key] = value; };
  const fixed = value => String(Math.round(value * 1000) / 1000);
  const data = (node, key, value) => { if (node.dataset[key] !== value) node.dataset[key] = value; };
  function playing(value) { data(stage, 'playing', String(value && !paused)); }

  function stop() { cancelAnimationFrame(raf); raf = 0; last = 0; }
  function wake() {
    if (!raf && active && !document.hidden) raf = requestAnimationFrame(render);
  }
  function measure() {
    heroHeight = hero.offsetHeight;
    storyHeight = story.offsetHeight;
    mobile = innerWidth <= 760;
    light = mobile || touch.matches;
    stage.dataset.render = document.documentElement.dataset.stageRender = light ? 'light' : 'full';
    if (light) { style(iris, 'clipPath', 'none'); lastAperture = ''; }
    wake();
  }
  function sync() {
    paused = userPaused || reduced.matches;
    document.documentElement.dataset.motion = paused ? 'paused' : 'running';
    pause.hidden = false;
    pause.textContent = reduced.matches ? '已减少动效' : paused ? '继续动效' : '暂停动效';
    pause.disabled = reduced.matches;
    pause.setAttribute('aria-pressed', String(paused));
    stage.classList.toggle('motion-paused', paused);
    playing(active && !document.hidden);
    document.dispatchEvent(new CustomEvent('site-motion-change', {detail: {paused}}));
    stop();
    wake();
  }
  pause.addEventListener('click', () => { userPaused = !userPaused; sync(); });
  reduced.addEventListener('change', () => { sync(); measure(); });
  touch.addEventListener('change', measure);
  window.addEventListener('pointermove', event => {
    if (paused || light || event.pointerType === 'touch') return;
    x = (event.clientX / innerWidth - .5) * 2;
    y = (event.clientY / innerHeight - .5) * 2;
  }, {passive: true});
  window.addEventListener('scroll', wake, {passive: true});
  window.addEventListener('resize', measure, {passive: true});
  window.addEventListener('load', measure);
  document.addEventListener('visibilitychange', () => {
    document.documentElement.dataset.pageVisibility = document.hidden ? 'hidden' : 'visible';
    stop();
    playing(!document.hidden && active);
    if (!document.hidden) wake();
  });
  if ('ResizeObserver' in window) {
    const observer = new ResizeObserver(measure);
    observer.observe(hero);
    observer.observe(story);
  }

  function render(ms) {
    raf = 0;
    if (!active || document.hidden) return;
    // The opaque closing section has covered the entire fixed artwork.
    const covered = scrollY >= heroHeight + (mobile ? 0 : storyHeight);
    data(stage, 'covered', String(covered));
    playing(!covered);
    if (covered) { last = 0; return; }
    const dt = last ? Math.min((ms - last) / 1000, .05) : 1 / 60;
    last = ms;
    const progress = clamp(scrollY / Math.max(1, heroHeight - innerHeight));
    let settling = false;
    if (!paused || !rendered) {
      time += paused ? 0 : dt;
      const targetPush = reduced.matches ? 0 : ease(clamp(progress / .75));
      const targetChapter = !paused && !mobile ? ease(clamp((scrollY - (heroHeight - innerHeight)) / Math.max(1, storyHeight))) : 0;
      const blend = rendered ? 1 - Math.exp(-dt * 12) : 1;
      push += (targetPush - push) * blend;
      chapterMove += (targetChapter - chapterMove) * blend;
      const scale = 1 + push * (mobile ? .35 : .64) - chapterMove * .08;
      const pan = push * (mobile ? -15 : -17) - chapterMove * 11;
      sx += ((!paused && !light ? x : 0) - sx) * blend;
      sy += ((!paused && !light ? y : 0) - sy) * blend;
      const transform = `translate3d(${fixed(pan + sx * .35)}%,${fixed(push * 2 + sy * .24)}%,0) scale(${fixed(scale)})`;
      style(camera, 'transform', light ? transform : `${transform} rotateY(${fixed(sx * .65)}deg) rotateX(${fixed(-sy * .4)}deg)`);
      settling = Math.abs(targetPush - push) > .0005 || Math.abs(targetChapter - chapterMove) > .0005;
      const close = reduced.matches ? 0 : ease(clamp((progress - .65) / .35));
      style(iris, 'opacity', fixed(close * .8 * (1 - chapterMove * .7)));
      if (!light) {
        if (lastAperture !== fixed(close)) {
          const aperture = Array.from({length: 9}, (_, i) => {
            const angle = -(i % 8) * Math.PI / 4 + close * .14;
            return `${fixed(69 + Math.cos(angle) * (90 - close * 53))}% ${fixed(50 + Math.sin(angle) * (125 - close * 70))}%`;
          }).join(',');
          style(iris, 'clipPath', `polygon(evenodd,0 0,100% 0,100% 100%,0 100%,0 0,${aperture})`);
          lastAperture = fixed(close);
        }
        topFilm.setAttribute('transform', `translate(${Math.sin(time * .16) * 3.8} ${Math.cos(time * .14) * 1.2})`);
        bottomFilm.setAttribute('transform', `translate(${Math.sin(time * .19 + 1) * -6.5} ${Math.sin(time * .13) * 1.6})`);
        glints.forEach((path, i) => {
          path.style.strokeDashoffset = String(-time * 35 + i * 310);
          path.style.opacity = String(.30 + Math.sin(time * .35 + i) * .2);
        });
        dust.setAttribute('transform', `translate(${Math.sin(time * .1) * 3} ${Math.sin(time * .12) * -5})`);
      }
      style(shade, 'opacity', fixed(scrollY >= heroHeight - innerHeight ? .58 : push * .32));
      rendered = true;
    }
    // Text follows the document even when the decorative scene is frozen.
    style(intro, 'opacity', fixed(reduced.matches ? 1 : 1 - clamp(progress * 3)));
    style(intro, 'visibility', !reduced.matches && progress > .34 ? 'hidden' : 'visible');
    style(caption, 'opacity', fixed(clamp((progress - .35) * 3) * (1 - clamp((progress - .85) * 5))));
    style(caption, 'transform', `translateY(${fixed((1 - push) * 30)}px)`);
    const label = progress < .35 ? 'THE OPENING' : progress < .75 ? 'DOLLY IN' : 'THE NEXT SCENE';
    if (indicator.textContent !== label) indicator.textContent = label;
    // Touch/narrow screens use compositor-only ambient motion. JS wakes for scroll,
    // eases to the requested framing, then yields entirely until the next input.
    if (!paused && (!light || settling)) wake(); else last = 0;
  }
  window.addEventListener('pagehide', () => { active = false; playing(false); stop(); });
  window.addEventListener('pageshow', () => { active = true; measure(); });
  measure();
  sync();
})();
