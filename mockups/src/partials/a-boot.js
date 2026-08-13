/* Shared page bootstrap for the mockup A family: palette / theme / typeface defaults,
   the circuit traces, the header state and menu, and the sliver of raster behind the
   header bar. Pages add their own behavior after this. */

document.documentElement.dataset.palette = 'teal';
document.documentElement.dataset.theme = 'dark';
document.documentElement.dataset.font = 'plex';
document.documentElement.classList.add('js');

(() => {
  const sel = document.getElementById('fontSel');
  if (sel) {
    sel.addEventListener('change', () => {
      document.documentElement.dataset.font = sel.value;
      dispatchEvent(new Event('resize'));   // PCB rules are sized to their label
    });
  }
  const themeBtn = document.getElementById('themeBtn');
  if (themeBtn) {
    const apply = (t) => {
      document.documentElement.dataset.theme = t;
      themeBtn.textContent = t === 'light' ? 'Light' : 'Dark';
      themeBtn.setAttribute('aria-pressed', String(t === 'dark'));
    };
    themeBtn.addEventListener('click', () =>
      apply(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'));
  }
  SL.initPaletteSwitch();
})();

/* the raster ribbon behind the header, once scrolled */
(() => {
  const cv = document.getElementById('hdRaster');
  if (!cv || typeof RASTER === 'undefined') return;
  SL.raster(cv, SL.decodeRaster(RASTER), {
    mode: 'sweep', spanS: 14, speed: 0.85, dotW: 1.2, fade: false,
    barEl: document.getElementById('hdBar'),
  });
})();

/* circuit traces */
(() => {
  document.querySelectorAll('.eyebrow .trace').forEach((el) => SL.pcbRule(el));
  document.querySelectorAll('.has-corner').forEach((el) => SL.pcbCorner(el, 'bl', 54));
})();

/* header state, menu, scroll reveals */
(() => {
  const hd = document.getElementById('hd');
  const onScroll = () => hd.classList.toggle('is-stuck', scrollY > 40);
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  const burger = document.getElementById('burger');
  const nav = document.getElementById('nav');
  if (burger && nav) {
    const setOpen = (open) => {
      nav.classList.toggle('is-open', open);
      burger.setAttribute('aria-expanded', String(open));
    };
    burger.addEventListener('click', () =>
      setOpen(burger.getAttribute('aria-expanded') !== 'true'));
    nav.addEventListener('click', (e) => { if (e.target.tagName === 'A') setOpen(false); });
    addEventListener('keydown', (e) => { if (e.key === 'Escape') setOpen(false); });
  }
  SL.reveal();
})();
