/* ============================================
   PUXA.AI — Main JavaScript
   ============================================ */

// === CONFIGURAÇÃO GLOBAL ===
const VAR_ENABLED = false; // Alterar para true para reativar a seção do VAR
const DEMO_TARGET_DATE = new Date('2026-08-01T00:00:00'); // Data-alvo da demo (configurável)

// === SUPABASE ===
const SUPABASE_URL = 'https://fiabgfgrmszbscmotjcv.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_nm7uBiownQDGqqQKZdUi6Q_mN8m6ofr';

document.addEventListener('DOMContentLoaded', () => {

  // === NAVBAR SCROLL EFFECT ===
  const navbar = document.querySelector('.navbar');
  const handleScroll = () => {
    if (window.scrollY > 80) {
      navbar.classList.add('scrolled');
    } else {
      navbar.classList.remove('scrolled');
    }
  };
  window.addEventListener('scroll', handleScroll);
  handleScroll();

  // === HAMBURGER MENU ===
  const hamburger = document.querySelector('.hamburger');
  const navMenu = document.querySelector('.nav-menu');
  if (hamburger) {
    hamburger.addEventListener('click', () => {
      hamburger.classList.toggle('active');
      navMenu.classList.toggle('active');
    });
    navMenu.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        hamburger.classList.remove('active');
        navMenu.classList.remove('active');
      });
    });
  }

  // === VAR SECTION: TEMPORARIAMENTE DESATIVADA - NÃO EXCLUIR ===
  // Para reativar: definir VAR_ENABLED = true no topo deste arquivo
  if (!VAR_ENABLED) {
    const varSection = document.getElementById('var');
    if (varSection) varSection.style.display = 'none';
    document.querySelectorAll('a[href="#var"]').forEach(link => {
      const li = link.closest('li');
      if (li) li.style.display = 'none';
      else link.style.display = 'none';
    });
  }

  // === SCROLL ANIMATIONS ===
  const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
  };

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        const children = entry.target.querySelectorAll('[data-stagger]');
        children.forEach((child, index) => {
          child.style.transitionDelay = `${index * 0.1}s`;
          child.classList.add('visible');
        });
      }
    });
  }, observerOptions);

  document.querySelectorAll('.fade-in, .fade-in-left, .fade-in-right').forEach(el => {
    observer.observe(el);
  });

  // === COUNTER ANIMATION ===
  const counterObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const counter = entry.target;
        const target = parseInt(counter.getAttribute('data-target'));
        const suffix = counter.getAttribute('data-suffix') || '';
        const prefix = counter.getAttribute('data-prefix') || '';
        const duration = 2000;
        const start = 0;
        const startTime = performance.now();

        const updateCounter = (currentTime) => {
          const elapsed = currentTime - startTime;
          const progress = Math.min(elapsed / duration, 1);
          const eased = 1 - Math.pow(1 - progress, 3);
          const current = Math.floor(start + (target - start) * eased);
          counter.textContent = prefix + current.toLocaleString('pt-BR') + suffix;
          if (progress < 1) {
            requestAnimationFrame(updateCounter);
          }
        };
        requestAnimationFrame(updateCounter);
        counterObserver.unobserve(counter);
      }
    });
  }, { threshold: 0.5 });

  document.querySelectorAll('[data-target]').forEach(el => {
    counterObserver.observe(el);
  });

  // === SMOOTH SCROLL FOR ANCHOR LINKS ===
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      e.preventDefault();
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {
        const offset = 80;
        const targetPosition = target.getBoundingClientRect().top + window.pageYOffset - offset;
        window.scrollTo({
          top: targetPosition,
          behavior: 'smooth'
        });
      }
    });
  });

  // === YOUTUBE VIDEO BACKGROUND ===
  const heroVideo = document.getElementById('hero-bg-video');
  if (heroVideo) {
    heroVideo.play && heroVideo.play().catch(() => {});
  }

  // === ODDS TABLE ANIMATION ===
  const oddsValues = document.querySelectorAll('.odds-value');
  setInterval(() => {
    oddsValues.forEach(val => {
      const current = parseFloat(val.textContent);
      if (current && !isNaN(current)) {
        const change = (Math.random() - 0.5) * 0.1;
        const newVal = Math.max(1.01, current + change).toFixed(2);
        val.textContent = newVal;
        val.style.color = change > 0 ? '#4ade80' : '#f87171';
        setTimeout(() => {
          val.style.color = '#E8722A';
        }, 500);
      }
    });
  }, 4000);

  // === HOTSPOT HEAT ANIMATION ===
  const heatDots = document.querySelectorAll('.heat-dot');
  heatDots.forEach(dot => {
    setInterval(() => {
      const scale = 0.8 + Math.random() * 0.6;
      const opacity = 0.3 + Math.random() * 0.5;
      dot.style.transform = `scale(${scale})`;
      dot.style.opacity = opacity;
    }, 1500 + Math.random() * 1000);
  });

  // === COUNTDOWN TIMER ===
  initCountdown();

  // === MULTI-STEP FORM ===
  initMultiStepForm();

});

// ============================================================
// COUNTDOWN TIMER
// ============================================================
function initCountdown() {
  const daysEl = document.getElementById('cd-days');
  const hoursEl = document.getElementById('cd-hours');
  const minutesEl = document.getElementById('cd-minutes');
  const secondsEl = document.getElementById('cd-seconds');
  const countdownSection = document.getElementById('countdown');

  if (!daysEl || !countdownSection) return;

  function pad(n) { return String(n).padStart(2, '0'); }

  function flipValue(el, newVal) {
    if (el.textContent === newVal) return;
    el.classList.add('flip');
    setTimeout(() => {
      el.textContent = newVal;
      el.classList.remove('flip');
    }, 150);
  }

  function tick() {
    const diff = DEMO_TARGET_DATE - new Date();

    if (diff <= 0) {
      countdownSection.innerHTML = `
        <div class="container">
          <div class="countdown-inner fade-in visible">
            <span class="section-label">Demo disponível</span>
            <p class="countdown-done">A plataforma está disponível. Acesse agora.</p>
          </div>
        </div>`;
      return;
    }

    const d = Math.floor(diff / 86400000);
    const h = Math.floor((diff % 86400000) / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    const s = Math.floor((diff % 60000) / 1000);

    flipValue(daysEl, pad(d));
    flipValue(hoursEl, pad(h));
    flipValue(minutesEl, pad(m));
    flipValue(secondsEl, pad(s));
  }

  tick();
  setInterval(tick, 1000);
}

// ============================================================
// MULTI-STEP FORM — Acesso Antecipado
// ============================================================
function initMultiStepForm() {
  const overlay = document.getElementById('modal-form');
  if (!overlay) return;

  const closeBtn = document.getElementById('modal-close');
  const progressFill = document.getElementById('form-progress');
  const totalSteps = 4;
  let currentStep = 1;
  const formData = {};

  document.querySelectorAll('[data-action="open-form"]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.preventDefault();
      openModal();
    });
  });

  function openModal() {
    currentStep = 1;
    document.querySelectorAll('.form-field').forEach(f => {
      f.value = '';
      f.classList.remove('error');
    });
    document.querySelectorAll('.form-error-msg').forEach(e => (e.textContent = ''));
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    showStep(1);
  }

  function closeModal() {
    overlay.classList.remove('open');
    document.body.style.overflow = '';
  }

  closeBtn && closeBtn.addEventListener('click', closeModal);
  overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && overlay.classList.contains('open')) closeModal();
  });

  const successClose = document.getElementById('success-close');
  successClose && successClose.addEventListener('click', closeModal);

  function showStep(step) {
    document.querySelectorAll('.form-step').forEach(s => s.classList.add('hidden'));
    const id = step === 'success' ? 'step-success' : `step-${step}`;
    const target = document.getElementById(id);
    if (target) {
      target.classList.remove('hidden');
      const input = target.querySelector('.form-field');
      input && setTimeout(() => input.focus(), 80);
    }
    const pct = step === 'success' ? 100 : Math.round((step / totalSteps) * 100);
    if (progressFill) progressFill.style.width = `${pct}%`;
  }

  function validateStep(step) {
    const field = document.getElementById(`field-${step}`);
    const errEl = document.getElementById(`error-${step}`);
    if (!field) return true;

    const val = field.value.trim();
    let msg = '';

    if (step === 1 && val.length < 3) {
      msg = 'Nome deve ter pelo menos 3 caracteres.';
    } else if (step === 2 && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val)) {
      msg = 'Informe um e-mail válido.';
    } else if (step === 3) {
      const digits = val.replace(/\D/g, '');
      if (digits.length < 10 || digits.length > 11) msg = 'Informe um número com DDD válido (ex: (85) 99999-0000).';
    } else if (step === 4 && val.length < 2) {
      msg = 'Informe seu @arroba ou URL do Instagram.';
    }

    if (errEl) errEl.textContent = msg;
    field.classList.toggle('error', !!msg);
    return !msg;
  }

  function advanceStep() {
    if (!validateStep(currentStep)) return;

    const field = document.getElementById(`field-${currentStep}`);
    if (field) {
      const keys = { 1: 'nome', 2: 'email', 3: 'whatsapp', 4: 'instagram' };
      formData[keys[currentStep]] = field.value.trim();
    }

    if (currentStep < totalSteps) {
      currentStep++;
      showStep(currentStep);
    } else {
      submitForm();
    }
  }

  document.querySelectorAll('.btn-form-next').forEach(btn => btn.addEventListener('click', advanceStep));
  document.querySelectorAll('.btn-form-back').forEach(btn => {
    btn.addEventListener('click', () => {
      if (currentStep > 1) { currentStep--; showStep(currentStep); }
    });
  });
  document.querySelectorAll('.form-field').forEach(field => {
    field.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); advanceStep(); } });
  });

  // Máscara WhatsApp: (XX) XXXXX-XXXX
  const wpp = document.getElementById('field-3');
  if (wpp) {
    wpp.addEventListener('input', () => {
      let v = wpp.value.replace(/\D/g, '').slice(0, 11);
      if (v.length > 7) v = `(${v.slice(0, 2)}) ${v.slice(2, 7)}-${v.slice(7)}`;
      else if (v.length > 2) v = `(${v.slice(0, 2)}) ${v.slice(2)}`;
      else if (v.length > 0) v = `(${v}`;
      wpp.value = v;
    });
  }

  async function submitForm() {
    showStep('success');
    try {
      await fetch(`${SUPABASE_URL}/rest/v1/leads`, {
        method: 'POST',
        headers: {
          'apikey': SUPABASE_ANON_KEY,
          'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
          'Content-Type': 'application/json',
          'Prefer': 'return=minimal'
        },
        body: JSON.stringify({
          nome:      formData.nome,
          email:     formData.email,
          whatsapp:  formData.whatsapp,
          instagram: formData.instagram
        })
      });
    } catch (_) {}
  }
}
