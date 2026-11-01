
// Art is an optional enhancement; the document remains usable without it.
(function () {
  var dialog = document.querySelector('.art-splash');
  var trigger = document.querySelector('.brand-art');
  if (!dialog || !trigger || typeof dialog.showModal !== 'function') return;
  var art = dialog.querySelector('.art-splash-image');
  var caption = dialog.querySelector('.art-edition');
  var editions = [
    {"file": "dali.webp", "label": "Inspired by Dalí · Eye logo", "alt": "AwakeVC eye logo, Dali edition", "width": 640, "height": 640},
    {"file": "kandinsky.webp", "label": "Inspired by Kandinsky · Eye logo", "alt": "AwakeVC eye logo, Kandinsky edition", "width": 640, "height": 640},
    {"file": "monet.webp", "label": "Inspired by Monet · Eye logo", "alt": "AwakeVC eye logo, Monet edition", "width": 640, "height": 640},
    {"file": "picasso.webp", "label": "Inspired by Picasso · Eye logo", "alt": "AwakeVC eye logo, Picasso edition", "width": 640, "height": 640},
    {"file": "warhol.webp", "label": "Inspired by Warhol · Eye logo", "alt": "AwakeVC eye logo, Warhol edition", "width": 640, "height": 640},
    {"file": "eye-world-magritte.webp", "label": "Inspired by Magritte · Eye world", "alt": "AwakeVC eye-shaped world with shared intelligence, inspired by Magritte", "width": 1200, "height": 629},
    {"file": "eye-world-de-chirico.webp", "label": "Inspired by de Chirico · Eye world", "alt": "AwakeVC eye-shaped world with shared intelligence, inspired by de Chirico", "width": 1200, "height": 629},
    {"file": "eye-world-klee.webp", "label": "Inspired by Klee · Eye world", "alt": "AwakeVC eye-shaped world with shared intelligence, inspired by Klee", "width": 1200, "height": 628},
    {"file": "eye-world-kandinsky.webp", "label": "Inspired by Kandinsky · Eye world", "alt": "AwakeVC eye-shaped world with shared intelligence, inspired by Kandinsky", "width": 1200, "height": 629},
    {"file": "eye-world-miro.webp", "label": "Inspired by Miró · Eye world", "alt": "AwakeVC eye-shaped world with shared intelligence, inspired by Miró", "width": 1200, "height": 629}
  ];
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
    restorePage();
  }
  function restorePage() {
    clearTimeout(closeTimer);
    clearTimeout(fadeTimer);
    document.body.style.overflow = previousOverflow;
    dialog.classList.remove('is-entering', 'is-closing');
    if (returnFocus && returnFocus.isConnected) returnFocus.focus({ preventScroll: true });
  }
  dialog.addEventListener('close', restorePage);
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
      art.alt = edition.alt;
      art.width = edition.width;
      art.height = edition.height;
      art.style.setProperty('--art-ratio', edition.width / edition.height);
      art.style.setProperty('--art-max-width', edition.width > edition.height ? '900px' : '440px');
      caption.textContent = 'AwakeVC \u00b7 ' + edition.label;
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
    image.src = dialog.dataset.assets + '/' + edition.file;
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

// Autonomy scorecard — fetches /data/scorecard.json and renders if ready.
(function () {
  var section = document.getElementById('scorecard');
  if (!section) return;

  function isValid(data) {
    if (!data || data.visible !== true || !data.updated) return false;
    if (!Array.isArray(data.stages)) return false;
    return data.stages.every(function (s) {
      return typeof s.level === 'number' && Number.isInteger(s.level) && s.level >= 0 && s.level <= 5;
    });
  }

  function formatDate(iso) {
    try {
      var d = new Date(iso + 'T00:00:00');
      return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    } catch (e) { return iso; }
  }

  function render(data) {
    var tbody = document.getElementById('scorecard-tbody');
    var updatedEl = document.getElementById('scorecard-updated');
    var overdueEl = document.getElementById('scorecard-overdue');
    if (!tbody) return;

    data.stages.forEach(function (s) {
      var tr = document.createElement('tr');
      var tdStage = document.createElement('td');
      var tdCovers = document.createElement('td');
      var tdLevel = document.createElement('td');
      tdStage.textContent = s.stage;
      tdCovers.textContent = s.covers;
      tdLevel.textContent = 'L' + s.level;
      tr.appendChild(tdStage);
      tr.appendChild(tdCovers);
      tr.appendChild(tdLevel);
      tbody.appendChild(tr);
    });

    if (updatedEl) updatedEl.textContent = 'Last updated: ' + formatDate(data.updated);

    var updated = new Date(data.updated + 'T00:00:00');
    var now = new Date();
    var diffDays = (now - updated) / (1000 * 60 * 60 * 24);
    if (overdueEl && diffDays > 45) overdueEl.hidden = false;

    section.hidden = false;

    // Add Scorecard nav item
    var nav = document.getElementById('site-nav');
    if (nav) {
      var a = document.createElement('a');
      a.href = '/#scorecard';
      a.textContent = 'Scorecard';
      nav.appendChild(a);
    }

    // Update hero lede with full sentence
    var lede = document.getElementById('hero-lede');
    if (lede) {
      lede.innerHTML = 'AmitAvatar co-founds AI-native companies with domain experts and operates AwakeVC. Trained on everything I’ve built, it coordinates the studio’s agents and shared systems. I’m Amit Rathore, AwakeVC’s owner and human overseer. The autonomy scorecard shows how much of the work agents do today.';
    }

    // Update "Who runs AwakeVC" item 3
    var item3 = document.getElementById('who-runs-item-3');
    if (item3) {
      item3.querySelector('p').innerHTML = '<strong>The line between us moves.</strong> The autonomy scorecard below shows exactly where it is today.';
    }
  }

  fetch('/data/scorecard.json')
    .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
    .then(function (data) { if (isValid(data)) render(data); })
    .catch(function () { /* silently stay hidden */ });
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
