/* ============================================
   PUXA.AI — Main JavaScript
   ============================================ */

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
    // Close menu on link click
    navMenu.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        hamburger.classList.remove('active');
        navMenu.classList.remove('active');
      });
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
        // Stagger children if they have data-stagger
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
          // Ease out cubic
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

  // === YOUTUBE VIDEO BACKGROUND (mute & autoplay) ===
  const heroVideo = document.getElementById('hero-bg-video');
  if (heroVideo) {
    // For YouTube iframe, we handle via URL params
    // For HTML5 video, ensure autoplay
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

});
