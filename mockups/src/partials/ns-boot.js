/* The personal site runs the same design in the cyan palette rather than the lab's teal.
   a-boot.js has already set the defaults, so this just overrides the one that differs and
   tells anything already drawn to repaint. */
document.documentElement.dataset.palette = 'indigo';
SL.firePalette();
