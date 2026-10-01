(function () {
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Nav: borde al hacer scroll
  var nav = $('#nav');
  if (nav) {
    var onScroll = function () { nav.classList.toggle('scrolled', window.scrollY > 8); };
    window.addEventListener('scroll', onScroll, { passive: true }); onScroll();
  }

  // Dropdowns
  var dds = $$('.has-dd');
  function closeAll(except) {
    dds.forEach(function (li) {
      if (li !== except) { li.classList.remove('open'); var b = $('button', li); if (b) b.setAttribute('aria-expanded', 'false'); }
    });
  }
  dds.forEach(function (li) {
    var btn = $('button', li);
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = !li.classList.contains('open');
      closeAll(li);
      li.classList.toggle('open', open);
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    li.addEventListener('mouseenter', function () { if (window.matchMedia('(hover: hover)').matches) { closeAll(li); li.classList.add('open'); btn.setAttribute('aria-expanded', 'true'); } });
    li.addEventListener('mouseleave', function () { if (window.matchMedia('(hover: hover)').matches) { li.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); } });
  });
  document.addEventListener('click', function () { closeAll(null); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closeAll(null); closeM(); } });

  // Menú móvil
  var mnav = $('#mnav'), burger = $('#burger'), mclose = $('#mclose');
  function closeM() { if (mnav) { mnav.classList.remove('open'); document.body.style.overflow = ''; } }
  if (mnav && burger) {
    burger.addEventListener('click', function () { mnav.classList.add('open'); document.body.style.overflow = 'hidden'; });
    if (mclose) mclose.addEventListener('click', closeM);
    $$('a', mnav).forEach(function (a) { a.addEventListener('click', closeM); });
  }

  // Caja de regalo (sección La experiencia)
  var stage = $('#stage'), burst = $('#burst');
  if (stage && burst) {
    var toggle = function () { var o = stage.classList.toggle('open'); stage.setAttribute('aria-pressed', o ? 'true' : 'false'); };
    stage.addEventListener('click', toggle);
    stage.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
    var ITEMS = [
      ['i-plane', 'Viajes', ''], ['i-cart', 'Supermercado', 'alt'], ['i-bike', 'Deporte', 'dk'], ['i-dine', 'Gastronomía', ''],
      ['i-spa', 'Bienestar', 'alt'], ['i-book', 'Libros', 'dk'], ['i-ticket', 'Espectáculos', ''], ['i-music', 'Música', 'alt'],
      ['i-shirt', 'Moda', 'dk'], ['i-camera', 'Experiencias', ''], ['i-wine', 'Vinos', 'alt'], ['i-suitcase', 'Escapadas', 'dk'],
      ['i-coffee', 'Cafeterías', ''], ['i-ball', 'Fútbol', 'alt'], ['i-plant', 'Hogar', 'dk'], ['i-card', 'Gift cards', ''], ['i-gamepad', 'Juegos', 'alt']
    ];
    ITEMS.forEach(function (it, i) {
      var d = document.createElement('div'); d.className = 'item ' + it[2]; d.style.setProperty('--i', i);
      d.style.setProperty('--rot', ((i % 3) - 1) * 6 + 'deg');
      d.innerHTML = '<div class="in"><div class="tile"><svg><use href="#' + it[0] + '"/></svg></div><span class="lb">' + it[1] + '</span></div>';
      burst.appendChild(d);
    });
    var layout = function () {
      var W = stage.clientWidth, H = stage.clientHeight, small = W < 520;
      var rowsDesk = [[9, [-34, -11, 11, 34]], [26, [-40, -20, 0, 20, 40]], [44, [-34, -11, 11, 34]], [61, [-40, -24, 24, 40]]];
      var rowsMob = [[11, [-34, -11, 11, 34]], [27, [-34, -11, 11, 34]], [43, [-34, -11, 11, 34]], [59, [-37, -14, 14, 37]]];
      var rows = small ? rowsMob : rowsDesk, pos = [];
      rows.forEach(function (r) { r[1].forEach(function (x) { pos.push([x, r[0]]); }); });
      var items = burst.children, jit = [[1.5, -1], [-1, 1.5], [0.5, -1.5], [-1.5, 0.5], [1, 1], [-0.5, -1.5], [1.5, 0.5], [-1, -0.5]];
      for (var i = 0; i < items.length; i++) {
        var el = items[i], p = pos[i];
        if (!p) { el.style.display = 'none'; continue; }
        var j = jit[i % jit.length]; p = [p[0] + j[0], p[1] + j[1]];
        el.style.display = '';
        el.style.setProperty('--x', (p[0] / 100 * W).toFixed(1) + 'px');
        el.style.setProperty('--y', (p[1] / 100 * H - (H - 150)).toFixed(1) + 'px');
        el.style.setProperty('--s', (small ? 44 : 54) + 'px');
      }
    };
    layout(); window.addEventListener('resize', layout);
  }

  // Hero: total que avanza (ilustrativo)
  var amtEl = $('#amt'), arc = $('#ringArc');
  if (amtEl && arc) {
    var steps = [18400, 19200, 20400, 21200, 22600, 24600], goal = 28000, k = 0;
    var show = function (n) { amtEl.textContent = '$ ' + n.toLocaleString('es-UY'); arc.setAttribute('stroke-dashoffset', String(402 * (1 - n / goal))); };
    show(steps[0]);
    arc.style.transition = 'stroke-dashoffset 1.2s cubic-bezier(.22,1,.36,1)';
    if (!reduce) setInterval(function () { k = (k + 1) % steps.length; show(steps[k]); }, 2600);
  }

  // Aparición suave al hacer scroll
  if ('IntersectionObserver' in window && !reduce) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
    }, { rootMargin: '0px 0px -8% 0px' });
    $$('.reveal').forEach(function (el) { io.observe(el); });
  } else {
    $$('.reveal').forEach(function (el) { el.classList.add('in'); });
  }
})();
