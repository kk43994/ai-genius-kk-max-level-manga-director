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
  const clamp = (n, a = 0, b = 1) => Math.max(a, Math.min(b, n));
  const ease = n => n * n * (3 - 2 * n);
  let userPaused = false, paused = reduced.matches, active = true;
  let x = 0, y = 0, sx = 0, sy = 0, time = 0, last = 0, raf = 0;
  let heroHeight = 0, storyHeight = 0, mobile = false;
  let rendered = false, push = 0, chapterMove = 0;

  function stop() { cancelAnimationFrame(raf); raf = 0; last = 0; }
  function wake() {
    if (!raf && active && !document.hidden) raf = requestAnimationFrame(render);
  }
  function measure() {
    heroHeight = hero.offsetHeight;
    storyHeight = story.offsetHeight;
    mobile = innerWidth < 760;
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
    document.dispatchEvent(new CustomEvent('site-motion-change', {detail: {paused}}));
    stop();
    wake();
  }
  pause.addEventListener('click', () => { userPaused = !userPaused; sync(); });
  reduced.addEventListener('change', () => { sync(); measure(); });
  window.addEventListener('pointermove', event => {
    if (paused || mobile || event.pointerType === 'touch') return;
    x = (event.clientX / innerWidth - .5) * 2;
    y = (event.clientY / innerHeight - .5) * 2;
  }, {passive: true});
  window.addEventListener('scroll', wake, {passive: true});
  window.addEventListener('resize', measure, {passive: true});
  window.addEventListener('load', measure);
  document.addEventListener('visibilitychange', () => {
    document.documentElement.dataset.pageVisibility = document.hidden ? 'hidden' : 'visible';
    stop();
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
    if (scrollY >= heroHeight + storyHeight) { last = 0; return; }
    const dt = Math.min((ms - (last || ms)) / 1000, .05);
    last = ms;
    const progress = clamp(scrollY / Math.max(1, heroHeight - innerHeight));
    if (!paused || !rendered) {
      time += paused ? 0 : dt;
      const targetPush = reduced.matches ? 0 : ease(clamp(progress / .75));
      const targetChapter = !paused && !mobile ? ease(clamp((scrollY - (heroHeight - innerHeight)) / Math.max(1, storyHeight))) : 0;
      const blend = rendered ? 1 - Math.exp(-dt * 12) : 1;
      push += (targetPush - push) * blend;
      chapterMove += (targetChapter - chapterMove) * blend;
      const scale = 1 + push * (mobile ? .35 : .64) - chapterMove * .08;
      const pan = push * (mobile ? -15 : -17) - chapterMove * 11;
      sx += ((!paused && !mobile ? x : 0) - sx) * blend;
      sy += ((!paused && !mobile ? y : 0) - sy) * blend;
      camera.style.transform = `translate3d(${pan + sx * .35}%,${push * 2 + sy * .24}%,0) scale(${scale}) rotateY(${sx * .65}deg) rotateX(${-sy * .4}deg)`;
      const close = reduced.matches ? 0 : ease(clamp((progress - .65) / .35));
      iris.style.opacity = String(close * .8 * (1 - chapterMove * .7));
      const aperture = Array.from({length: 9}, (_, i) => {
        const angle = -(i % 8) * Math.PI / 4 + close * .14;
        return `${69 + Math.cos(angle) * (90 - close * 53)}% ${50 + Math.sin(angle) * (125 - close * 70)}%`;
      }).join(',');
      iris.style.clipPath = `polygon(evenodd,0 0,100% 0,100% 100%,0 100%,0 0,${aperture})`;
      shade.style.opacity = String(scrollY >= heroHeight - innerHeight ? .58 : push * .32);
      topFilm.setAttribute('transform', `translate(${Math.sin(time * .16) * 3.8} ${Math.cos(time * .14) * 1.2})`);
      bottomFilm.setAttribute('transform', `translate(${Math.sin(time * .19 + 1) * -6.5} ${Math.sin(time * .13) * 1.6})`);
      glints.forEach((path, i) => {
        path.style.strokeDashoffset = String(-time * 35 + i * 310);
        path.style.opacity = String(.30 + Math.sin(time * .35 + i) * .2);
      });
      dust.setAttribute('transform', `translate(${Math.sin(time * .1) * 3} ${Math.sin(time * .12) * -5})`);
      rendered = true;
    }
    // Text follows the document even when the decorative scene is frozen.
    intro.style.opacity = String(reduced.matches ? 1 : 1 - clamp(progress * 3));
    intro.style.visibility = !reduced.matches && progress > .34 ? 'hidden' : 'visible';
    caption.style.opacity = String(clamp((progress - .35) * 3) * (1 - clamp((progress - .85) * 5)));
    caption.style.transform = `translateY(${(1 - push) * 30}px)`;
    indicator.textContent = progress < .35 ? 'THE OPENING' : progress < .75 ? 'DOLLY IN' : 'THE NEXT SCENE';
    if (!paused) wake(); else last = 0;
  }
  window.addEventListener('pagehide', () => { active = false; stop(); });
  window.addEventListener('pageshow', () => { active = true; measure(); });
  measure();
  sync();
})();
