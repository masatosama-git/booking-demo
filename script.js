// ==============================
// Booking System Demo (Cuore)
// 自己完結デモ：外部ネットワークには一切アクセスしません。
// 本番GASエンドポイントへのfetchは、すべてローカルのモック関数に置換済みです。
// ==============================

// ---------------------------------------------
// MOCK BACKEND (本番のGAS Web Appを擬似化)
// ---------------------------------------------
const MockApi = (() => {
  // 日付文字列からの擬似乱数（同じ日付なら常に同じ結果になり、再描画でブレない）
  function seed(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
    return h;
  }
  function pick(s, arr) {
    return arr[s % arr.length];
  }

  // 月間空き状況：各日に am/pm/eve の ○/△/× を返す（過去日は past）
  // 汎用店：平日・土日祝とも営業（10:00〜19:00）。曜日に関わらず午前/午後/夜に空き状況を表示。
  function getMonth(key) {
    // key: "YYYY-MM"
    const [y, m] = key.split('-').map(Number);
    const daysInMonth = new Date(y, m, 0).getDate();
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const data = {};
    const marks = ['○', '○', '△', '×', '○', '△'];

    for (let day = 1; day <= daysInMonth; day++) {
      const dateStr = `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      const d = new Date(y, m - 1, day);

      if (d < today) {
        data[dateStr] = { am: 'past', pm: 'past', eve: 'past' };
        continue;
      }

      // 曜日を問わず、午前・午後・夜すべてに○△×を表示（日付シードで適度に混ぜる）
      const s = seed(dateStr);
      data[dateStr] = {
        am: pick(s, marks),
        pm: pick(s + 7, marks),
        eve: pick(s + 13, marks),
      };
    }
    return data;
  }

  // 日別スロット：選択日に対し 10:00〜18:30 のフル枠（30分刻み）を返す。
  // 一部は「埋まり」として非表示にし、リアルな空き具合を再現。曜日を問わず日中枠も出る。
  function getSlots(dateStr) {
    // 営業時間 10:00〜19:00、30分刻み（最終受付 18:30）
    const all = [];
    for (let h = 10; h < 19; h++) {
      all.push(`${String(h).padStart(2, '0')}:00`);
      all.push(`${String(h).padStart(2, '0')}:30`);
    }
    const s = seed(dateStr);
    if (s % 11 === 0) return []; // たまに「空きなし」
    // 各枠を日付＋時刻のシードで埋まり/空きに振り分け（約4割が埋まり）
    return all.filter((time, i) => {
      const ts = seed(dateStr + time);
      return ts % 5 >= 2; // 0,1=埋まり(非表示) / 2,3,4=空き(表示)
    });
  }

  // 200msほどの擬似遅延でネットワーク感を再現
  function delay(value, ms = 200) {
    return new Promise(resolve => setTimeout(() => resolve(value), ms));
  }

  return {
    fetchMonth: (key) => delay(getMonth(key)),
    fetchSlots: (dateStr) => delay(getSlots(dateStr)),
    submitForm: (data) => delay({ ok: true }, 400),
  };
})();

document.addEventListener('DOMContentLoaded', () => {

  // --- Mobile Navigation ---
  const navToggle = document.getElementById('navToggle');
  const navLinks = document.getElementById('navLinks');

  if (navToggle && navLinks) {
    navToggle.addEventListener('click', () => {
      const isOpen = navLinks.classList.toggle('active');
      navToggle.classList.toggle('active');
      navToggle.setAttribute('aria-expanded', isOpen);
    });

    navLinks.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        navLinks.classList.remove('active');
        navToggle.classList.remove('active');
        navToggle.setAttribute('aria-expanded', 'false');
      });
    });
  }

  // --- Nav scroll effect ---
  const nav = document.getElementById('nav');
  if (nav) {
    window.addEventListener('scroll', () => {
      nav.classList.toggle('scrolled', window.scrollY > 50);
    }, { passive: true });
  }

  // --- Mobile CTA bar ---
  const mobileCta = document.getElementById('mobileCta');
  if (mobileCta) {
    window.addEventListener('scroll', () => {
      mobileCta.classList.toggle('visible', window.scrollY > window.innerHeight * 0.5);
    }, { passive: true });
  }

  // --- Hero Slideshow ---
  const heroSlides = document.querySelectorAll('.hero-slide');
  const heroDots = document.querySelectorAll('.hero-dot');
  let currentHero = 0;
  let heroTimer;

  function heroGoTo(n) {
    heroSlides[currentHero].classList.remove('active');
    heroDots[currentHero].classList.remove('active');
    currentHero = (n + heroSlides.length) % heroSlides.length;
    heroSlides[currentHero].classList.add('active');
    heroDots[currentHero].classList.add('active');
  }

  function heroStartTimer() {
    heroTimer = setInterval(() => heroGoTo(currentHero + 1), 5000);
  }

  if (heroSlides.length && heroDots.length) {
    heroDots.forEach((dot, i) => dot.addEventListener('click', () => {
      clearInterval(heroTimer);
      heroGoTo(i);
      heroStartTimer();
    }));

    const heroSection = document.querySelector('.hero');
    if (heroSection) {
      heroSection.addEventListener('mouseenter', () => clearInterval(heroTimer));
      heroSection.addEventListener('mouseleave', heroStartTimer);
    }
    heroStartTimer();
  }

  // --- Fade-in on scroll ---
  const fadeEls = document.querySelectorAll('.fade-in');
  const fadeObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        fadeObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

  fadeEls.forEach(el => fadeObserver.observe(el));

  // --- Voice Carousel ---
  const track = document.querySelector('.voice-track');
  const cards = document.querySelectorAll('.voice-card');
  const dotsContainer = document.getElementById('voiceDots');
  const prevBtn = document.getElementById('voicePrev');
  const nextBtn = document.getElementById('voiceNext');
  let currentVoice = 0;

  if (track && cards.length && dotsContainer) {
    cards.forEach((_, i) => {
      const dot = document.createElement('div');
      dot.className = 'voice-dot' + (i === 0 ? ' active' : '');
      dot.addEventListener('click', () => goToVoice(i));
      dotsContainer.appendChild(dot);
    });

    function getVisibleCount() {
      const w = window.innerWidth;
      if (w >= 1024) return 3;
      if (w >= 768) return 2;
      return 1;
    }

    window.goToVoice = function goToVoice(index) {
      const visible = getVisibleCount();
      const maxIndex = Math.max(0, cards.length - visible);
      currentVoice = Math.max(0, Math.min(index, maxIndex));

      const gap = parseFloat(getComputedStyle(track).gap) || 16;
      const cardWidth = cards[0].offsetWidth + gap;
      track.style.transform = `translateX(-${currentVoice * cardWidth}px)`;

      document.querySelectorAll('.voice-dot').forEach((dot, i) => {
        dot.classList.toggle('active', i === currentVoice);
      });
    };

    if (prevBtn) prevBtn.addEventListener('click', () => goToVoice(currentVoice - 1));
    if (nextBtn) nextBtn.addEventListener('click', () => goToVoice(currentVoice + 1));

    // Swipe support
    let touchStartX = 0;
    const carousel = document.getElementById('voiceCarousel');
    if (carousel) {
      carousel.addEventListener('touchstart', e => { touchStartX = e.touches[0].clientX; }, { passive: true });
      carousel.addEventListener('touchend', e => {
        const diff = touchStartX - e.changedTouches[0].clientX;
        if (Math.abs(diff) > 50) diff > 0 ? goToVoice(currentVoice + 1) : goToVoice(currentVoice - 1);
      }, { passive: true });
    }

    window.addEventListener('resize', () => goToVoice(currentVoice));
  }

  // --- Contact form (擬似送信のみ。ネットワークには出ません) ---
  const form = document.getElementById('contactForm');
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = form.querySelector('.form-submit');
      btn.textContent = '送信中...';
      btn.disabled = true;

      const data = {
        name: (form.querySelector('#name') || {}).value || '',
        email: (form.querySelector('#email') || {}).value || '',
        category: (form.querySelector('#category') || {}).value || '',
        preferredDate: (form.querySelector('#preferredDate') || {}).value || '',
        message: (form.querySelector('#message') || {}).value || '',
      };

      // モック送信：外部送信なし
      await MockApi.submitForm(data);

      btn.textContent = '送信しました';
      btn.style.background = '#7A9E7E';
      form.reset();
      const slotContainer = document.getElementById('slotContainer');
      const slotButtons = document.getElementById('slotButtons');
      if (slotContainer) slotContainer.style.display = 'none';
      if (slotButtons) slotButtons.innerHTML = '';
      setTimeout(() => {
        btn.textContent = '送信する';
        btn.disabled = false;
        btn.style.background = '';
      }, 4000);
    });
  }

  // --- Date Slot Picker ---
  const datePicker = document.getElementById('preferredDatePicker');
  const slotContainer = document.getElementById('slotContainer');
  const slotButtons = document.getElementById('slotButtons');
  const slotLoading = document.getElementById('slotLoading');
  const slotNone = document.getElementById('slotNone');
  const preferredDateH = document.getElementById('preferredDate');

  if (datePicker) {
    const todayStr = new Date().toISOString().split('T')[0];
    datePicker.min = todayStr;

    datePicker.addEventListener('change', async () => {
      const dateStr = datePicker.value;
      if (!dateStr) { slotContainer.style.display = 'none'; return; }

      preferredDateH.value = '';
      slotButtons.innerHTML = '';
      slotNone.style.display = 'none';
      slotLoading.style.display = 'block';
      slotLoading.textContent = '空き枠を確認中...';
      slotContainer.style.display = 'block';

      // モック：ローカルで枠を生成
      const slots = await MockApi.fetchSlots(dateStr);
      slotLoading.style.display = 'none';

      if (!Array.isArray(slots)) {
        slotLoading.style.display = 'block';
        slotLoading.textContent = '空き枠の取得に失敗しました';
        return;
      }
      if (slots.length === 0) {
        slotNone.style.display = 'block';
        return;
      }

      slots.forEach(time => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'slot-btn';
        btn.textContent = time;
        btn.addEventListener('click', () => {
          slotButtons.querySelectorAll('.slot-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          preferredDateH.value = `${dateStr} ${time}`;
        });
        slotButtons.appendChild(btn);
      });
    });
  }

  // --- Availability Calendar ---
  const calContainer = document.getElementById('availabilityCalendar');

  if (calContainer) {
    const LABEL = { '○': '○', '△': '△', '×': '×', 'past': '', 'n/a': '' };
    const STATUS_CLASS = { '○': 'av-open', '△': 'av-limited', '×': 'av-busy', 'past': 'av-past', 'n/a': 'av-na' };
    const JP_WDAY = ['日', '月', '火', '水', '木', '金', '土'];

    async function fetchMonth(year, month) {
      const key = `${year}-${String(month).padStart(2, '0')}`;
      // モック：ローカルで月間データを生成
      return await MockApi.fetchMonth(key);
    }

    function renderCalendar(year, month, data) {
      const daysInMonth = new Date(year, month, 0).getDate();
      const firstDay = new Date(year, month - 1, 1).getDay();
      const title = `${year}年${month}月`;

      let html = `<div class="av-month"><div class="av-month-title">${title}</div>`;
      html += '<div class="av-grid">';
      JP_WDAY.forEach(d => { html += `<div class="av-wday${d === '日' ? ' av-sun' : d === '土' ? ' av-sat' : ''}">${d}</div>`; });
      for (let i = 0; i < firstDay; i++) html += '<div></div>';

      for (let day = 1; day <= daysInMonth; day++) {
        const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        const d = data[dateStr] || {};
        const am = d.am || 'past', pm = d.pm || 'past', eve = d.eve || 'past';
        const isPast = am === 'past' && pm === 'past' && eve === 'past';
        const isBusy = !isPast && eve === '×' && (am === 'n/a' || am === '×') && (pm === 'n/a' || pm === '×');
        const isHoliday = !!d.holiday;
        const wday = new Date(year, month - 1, day).getDay();
        const wClass = (wday === 0 || isHoliday) ? ' av-sun' : wday === 6 ? ' av-sat' : '';
        const clickable = !isPast && !isBusy ? ` av-clickable" data-date="${dateStr}` : '';
        const slotHtml = am !== 'n/a'
          ? `<span class="av-status ${STATUS_CLASS[am]}" title="午前">午前${LABEL[am]}</span><span class="av-status ${STATUS_CLASS[pm]}" title="午後">午後${LABEL[pm]}</span><span class="av-status av-eve ${STATUS_CLASS[eve]}" title="夜">夜${LABEL[eve]}</span>`
          : `<span class="av-status av-eve ${STATUS_CLASS[eve]}" title="夜">夜${LABEL[eve]}</span>`;
        html += `<div class="av-day${isPast ? ' av-past' : ''}${wClass}${clickable}">
          <span class="av-day-num">${day}${isHoliday ? '<span class="av-holiday-label">祝</span>' : ''}</span>
          ${isPast ? '' : slotHtml}
        </div>`;
      }
      html += '</div></div>';
      return html;
    }

    async function loadCalendars() {
      calContainer.innerHTML = '<p class="av-loading">空き状況を読み込み中...</p>';
      const now = new Date();
      const y0 = now.getFullYear(), m0 = now.getMonth() + 1;
      const m1 = m0 === 12 ? 1 : m0 + 1, y1 = m0 === 12 ? y0 + 1 : y0;
      const [d0, d1] = await Promise.all([fetchMonth(y0, m0), fetchMonth(y1, m1)]);
      const html = renderCalendar(y0, m0, d0) + renderCalendar(y1, m1, d1);
      calContainer.innerHTML = html;

      calContainer.querySelectorAll('.av-clickable').forEach(dayEl => {
        dayEl.addEventListener('click', () => {
          const picker = document.getElementById('preferredDatePicker');
          if (!picker) return;
          picker.value = dayEl.dataset.date;
          picker.dispatchEvent(new Event('change'));
          picker.closest('.form-group').scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
      });
    }

    loadCalendars();
  }

});
