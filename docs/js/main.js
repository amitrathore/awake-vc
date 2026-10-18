
// Art is an optional enhancement; the document remains usable without it.
(function () {
  var dialog = document.querySelector('.art-splash');
  var trigger = document.querySelector('.brand-art');
  if (!dialog || !trigger || typeof dialog.showModal !== 'function') return;
  var art = dialog.querySelector('.art-splash-image');
  var caption = dialog.querySelector('.art-edition');
  var editions = ['Dali', 'Kandinsky', 'Monet', 'Picasso', 'Warhol'];
  var sessionKey = 'awakevc-art-seen-v1';
  var pending = false;
  var closeTimer;
  var fadeTimer;
  var loadTimer;
  var returnFocus;
  var previousOverflow;
  var clickTimes = [];
  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  trigger.hidden = false;

  function closeArt() {
    clearTimeout(closeTimer);
    clearTimeout(fadeTimer);
    if (dialog.open) dialog.close();
  }
  dialog.addEventListener('close', function () {
    clearTimeout(closeTimer);
    clearTimeout(fadeTimer);
    document.body.style.overflow = previousOverflow;
    dialog.classList.remove('is-entering', 'is-closing');
    if (returnFocus && returnFocus.isConnected) returnFocus.focus({ preventScroll: true });
  });
  dialog.addEventListener('cancel', function (event) { event.preventDefault(); closeArt(); });
  dialog.querySelector('.art-skip').addEventListener('click', closeArt);
  dialog.addEventListener('click', function (event) { if (event.target === dialog) closeArt(); });

  function showArt() {
    if (pending || dialog.open) return;
    pending = true;
    var edition = editions[Math.floor(Math.random() * editions.length)];
    var duration = 3000 + Math.random() * 4000;
    var image = new Image();
    function failed() { clearTimeout(loadTimer); pending = false; image.onload = image.onerror = null; }
    image.onerror = failed;
    loadTimer = setTimeout(failed, 8000);
    image.onload = function () {
      clearTimeout(loadTimer);
      pending = false;
      image.onload = image.onerror = null;
      returnFocus = document.activeElement === document.body ? document.querySelector('.brand-lockup .brand') : document.activeElement;
      art.src = image.src;
      art.alt = 'AwakeVC eye logo, ' + edition + ' edition';
      caption.textContent = 'AwakeVC \u00b7 ' + edition + ' edition';
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      dialog.classList.add('is-entering');
      dialog.showModal();
      try { sessionStorage.setItem(sessionKey, '1'); } catch (error) { /* Manual replay still works. */ }
      var fade = reducedMotion.matches ? 0 : 180;
      closeTimer = setTimeout(function () {
        dialog.classList.remove('is-entering');
        dialog.classList.add('is-closing');
        fadeTimer = setTimeout(closeArt, fade);
      }, duration - fade);
    };
    image.src = dialog.dataset.assets + '/' + edition.toLowerCase() + '.webp';
  }

  trigger.addEventListener('click', function (event) {
    if (event.detail === 0) { showArt(); return; }
    var now = performance.now();
    clickTimes = clickTimes.filter(function (time) { return now - time <= 900; });
    clickTimes.push(now);
    if (clickTimes.length >= 3) { clickTimes = []; showArt(); }
  });
  try { if (!sessionStorage.getItem(sessionKey)) showArt(); } catch (error) { /* Skip automatic art when storage is unavailable. */ }
})();

// Mobile nav toggle — tiny and dependency-free.
(function () {
  var toggle = document.querySelector('.nav-toggle');
  var nav = document.querySelector('.site-nav');
  if (!toggle || !nav) return;
  toggle.addEventListener('click', function () {
    var open = nav.classList.toggle('open');
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  // Close on link click.
  nav.querySelectorAll('a').forEach(function (a) {
    a.addEventListener('click', function () {
      nav.classList.remove('open');
      toggle.setAttribute('aria-expanded', 'false');
    });
  });
})();
