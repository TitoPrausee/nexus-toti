# Animations Reference — Quantic + Central SaaS UI

All GSAP patterns for both design systems. [Q] = Quantic-specific, [C] = Central-specific, [S] = Shared.

---

## Bootstrap (always include)

```js
// Smooth scroll with Lenis
const lenis = new Lenis({
  duration: 1.2,
  easing: t => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
  smoothWheel: true
});
lenis.on('scroll', ScrollTrigger.update);
gsap.ticker.add(time => lenis.raf(time * 1000));
gsap.ticker.lagSmoothing(0);

gsap.registerPlugin(ScrollTrigger);

// Reduced motion fallback
const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
if (prefersReduced) {
  gsap.set('[data-animate]', { opacity: 1, y: 0, x: 0, scale: 1 });
}

// Sticky navbar
window.addEventListener('scroll', () => {
  document.getElementById('navbar').classList.toggle('scrolled', window.scrollY > 20);
});
```

---

## [Q] HERO ENTRANCE SEQUENCE

```js
function initHeroAnimations() {
  if (prefersReduced) return;

  const headline = document.querySelector('.hero-headline');
  const words = headline.innerText.split(' ');
  headline.innerHTML = words.map(w =>
    `<span class="word" style="display:inline-block;overflow:hidden"><span class="word-inner" style="display:inline-block">${w}</span></span>`
  ).join(' ');

  const tl = gsap.timeline({ delay: 0.1 });

  tl.from('#navbar', { y: -30, opacity: 0, duration: 0.5, ease: 'power2.out' })
    .from('.trust-pill', { scale: 0.85, opacity: 0, duration: 0.4, ease: 'back.out(2)' }, '-=0.1')
    .from('.hero-headline .word-inner', {
      y: '100%', opacity: 0, duration: 0.6, stagger: 0.04, ease: 'power3.out'
    }, '-=0.2')
    .from('.hero-sub', { y: 20, opacity: 0, duration: 0.5, ease: 'power2.out' }, '-=0.3')
    .from('.hero-cta', { scale: 0.95, opacity: 0, duration: 0.4, ease: 'back.out(1.5)' }, '-=0.2')
    .from('.mockup-left', { x: -80, opacity: 0, duration: 0.8, ease: 'power3.out' }, '-=0.6')
    .from('.mockup-right', { x: 80, opacity: 0, duration: 0.8, ease: 'power3.out' }, '-=0.8')
    .from('.illustration-rocket', { y: 30, opacity: 0, duration: 0.6, ease: 'power2.out' }, '-=0.7')
    .from('.logos-section', { y: 20, opacity: 0, duration: 0.5, ease: 'power2.out' }, '-=0.3')
    .from('.logo-item', { y: 10, opacity: 0, duration: 0.4, stagger: 0.07, ease: 'power2.out' }, '-=0.3');
}
```

---

## [C] SPLIT HERO ENTRANCE

```js
function initSplitHeroAnimations() {
  if (prefersReduced) return;

  const headline = document.querySelector('.hero-headline');
  const words = headline.innerText.split(' ');
  headline.innerHTML = words.map(w =>
    `<span class="word" style="display:inline-block;overflow:hidden"><span class="word-inner" style="display:inline-block">${w}</span></span>`
  ).join(' ');

  const tl = gsap.timeline({ delay: 0.1 });

  tl.from('#navbar', { y: -30, opacity: 0, duration: 0.5, ease: 'power2.out' })
    .from('.device-mockup', {
      scale: 0.85, rotateY: -20, opacity: 0, duration: 1, ease: 'power3.out'
    }, '-=0.1')
    .from('.hero-headline .word-inner', {
      y: '100%', opacity: 0, duration: 0.6, stagger: 0.05, ease: 'power3.out'
    }, '-=0.7')
    .from('.hero-sub', { y: 20, opacity: 0, duration: 0.5, ease: 'power2.out' }, '-=0.3')
    .from('.cta-pair', { y: 20, opacity: 0, duration: 0.5, ease: 'power2.out' }, '-=0.2');
}
```

---

## [Q] HERO PARALLAX (scroll-linked)

```js
gsap.to('.mockup-left', {
  scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 1.5 },
  y: -50, ease: 'none'
});
gsap.to('.mockup-right', {
  scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 1.5 },
  y: 50, ease: 'none'
});
gsap.to('.blob-purple', {
  scrollTrigger: { trigger: '.hero', scrub: 2 },
  y: -80, x: 30, ease: 'none'
});
gsap.to('.blob-orange', {
  scrollTrigger: { trigger: '.hero', scrub: 2 },
  y: 60, x: -20, ease: 'none'
});
```

---

## [S] DARK FEATURE SECTION REVEAL

```js
const featureTitle = document.querySelector('.features-title');
if (featureTitle) {
  gsap.from(featureTitle, {
    scrollTrigger: { trigger: '.features-dark', start: 'top 80%' },
    y: 40, opacity: 0, duration: 0.7, ease: 'power2.out'
  });
}
gsap.from('.feature-tab', {
  scrollTrigger: { trigger: '.features-dark', start: 'top 75%' },
  y: 20, opacity: 0, duration: 0.5, stagger: 0.1, ease: 'power2.out'
});
gsap.from('.feature-panel.active', {
  scrollTrigger: { trigger: '.features-dark', start: 'top 70%' },
  x: 60, opacity: 0, duration: 0.8, ease: 'power3.out'
});
```

---

## [S] FEATURE TAB INTERACTION

```js
const featureTabs = document.querySelectorAll('.feature-tab');
const featurePanels = document.querySelectorAll('.feature-panel');
let activeIndex = 0;

function activateTab(index) {
  if (index === activeIndex) return;
  featureTabs[activeIndex].classList.remove('active');
  featureTabs[index].classList.add('active');

  const oldDesc = featureTabs[activeIndex].querySelector('.tab-desc');
  const oldLink = featureTabs[activeIndex].querySelector('.tab-link');
  const newDesc = featureTabs[index].querySelector('.tab-desc');
  const newLink = featureTabs[index].querySelector('.tab-link');

  gsap.to([oldDesc, oldLink], {
    opacity: 0, height: 0, marginTop: 0, duration: 0.2, ease: 'power2.in',
    onComplete: () => { oldDesc.style.display = 'none'; oldLink.style.display = 'none'; }
  });

  newDesc.style.display = 'block';
  newDesc.style.height = '0';
  newLink.style.display = 'inline-flex';

  gsap.fromTo(newDesc,
    { opacity: 0, height: 0 },
    { opacity: 1, height: 'auto', marginTop: 10, duration: 0.3, ease: 'power2.out', delay: 0.15 }
  );
  gsap.fromTo(newLink,
    { opacity: 0 },
    { opacity: 1, duration: 0.3, ease: 'power2.out', delay: 0.25 }
  );

  const currentPanel = featurePanels[activeIndex];
  const nextPanel = featurePanels[index];

  gsap.timeline()
    .to(currentPanel, {
      opacity: 0, y: 12, duration: 0.2, ease: 'power2.in',
      onComplete: () => {
        currentPanel.classList.remove('active');
        currentPanel.style.display = 'none';
        nextPanel.style.display = 'block';
        nextPanel.classList.add('active');
      }
    })
    .fromTo(nextPanel,
      { opacity: 0, y: -12 },
      { opacity: 1, y: 0, duration: 0.35, ease: 'power2.out' }
    );

  activeIndex = index;
}

featureTabs.forEach((tab, i) => {
  tab.addEventListener('click', () => activateTab(i));
});
```

---

## [S] METRIC COUNTERS

```js
document.querySelectorAll('.counter').forEach(el => {
  const target = parseFloat(el.dataset.target);
  const prefix = el.dataset.prefix || '';
  const suffix = el.dataset.suffix || '';
  const decimals = el.dataset.decimals ? parseInt(el.dataset.decimals) : 0;

  gsap.fromTo({ val: 0 }, { val: target },
    {
      scrollTrigger: { trigger: el, start: 'top 80%', once: true },
      duration: 1.8, ease: 'power2.out',
      onUpdate() {
        const v = this.targets()[0].val;
        el.textContent = prefix + v.toFixed(decimals).toLocaleString() + suffix;
      }
    }
  );
});
```

---

## [S] MICRO-INTERACTIONS

### CTA Button Magnetic Hover

```js
document.querySelectorAll('.btn-pill-dark, .btn-pill-light, .btn-outline-light, .btn-filled-dark').forEach(btn => {
  btn.addEventListener('mousemove', e => {
    const rect = btn.getBoundingClientRect();
    const x = (e.clientX - rect.left - rect.width / 2) * 0.15;
    const y = (e.clientY - rect.top - rect.height / 2) * 0.15;
    gsap.to(btn, { x, y, duration: 0.3, ease: 'power2.out' });
  });
  btn.addEventListener('mouseleave', () => {
    gsap.to(btn, { x: 0, y: 0, duration: 0.6, ease: 'elastic.out(1, 0.5)' });
  });
});
```

### Card Lift on Hover

```js
document.querySelectorAll('.pricing-card, .testimonial-card, .bento-card').forEach(card => {
  card.addEventListener('mouseenter', () =>
    gsap.to(card, { y: -6, boxShadow: '0 24px 48px rgba(0,0,0,0.15)', duration: 0.3, ease: 'power2.out' })
  );
  card.addEventListener('mouseleave', () =>
    gsap.to(card, { y: 0, boxShadow: '0 2px 8px rgba(0,0,0,0.06)', duration: 0.4, ease: 'power2.out' })
  );
});
```

---

## [S] GENERAL SCROLL REVEALS

```js
gsap.utils.toArray('[data-reveal]').forEach(el => {
  const delay = parseFloat(el.dataset.delay || 0);
  gsap.from(el, {
    scrollTrigger: { trigger: el, start: 'top 85%', once: true },
    y: 30, opacity: 0, duration: 0.65, delay, ease: 'power2.out'
  });
});

gsap.utils.toArray('[data-stagger-group]').forEach(group => {
  const children = group.querySelectorAll('[data-stagger-item]');
  gsap.from(children, {
    scrollTrigger: { trigger: group, start: 'top 80%', once: true },
    y: 20, opacity: 0, duration: 0.5, stagger: 0.08, ease: 'power2.out'
  });
});
```

---

## [S] LOGO BAR AUTO-SCROLL (optional)

```js
const marquee = document.querySelector('.logos-marquee');
if (marquee) {
  const content = marquee.innerHTML;
  marquee.innerHTML = content + content;
  gsap.to(marquee, { x: '-50%', duration: 20, ease: 'none', repeat: -1 });
  marquee.addEventListener('mouseenter', () => gsap.globalTimeline.pause());
  marquee.addEventListener('mouseleave', () => gsap.globalTimeline.resume());
}
```

---

## [S] PRICING TOGGLE ANIMATION

```js
const toggle = document.querySelector('.toggle-pill');
const prices = document.querySelectorAll('.plan-price');
let isAnnual = false;

const monthlyPrices = ['$19', '$49', 'Custom'];
const annualPrices  = ['$15', '$39', 'Custom'];

toggle.addEventListener('click', () => {
  isAnnual = !isAnnual;
  toggle.classList.toggle('active', isAnnual);
  prices.forEach((price, i) => {
    gsap.to(price, {
      opacity: 0, y: -8, duration: 0.15, ease: 'power2.in',
      onComplete: () => {
        price.querySelector('.amount').textContent = isAnnual ? annualPrices[i] : monthlyPrices[i];
        gsap.fromTo(price, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.2, ease: 'power2.out' });
      }
    });
  });
});
```

---

## [C] MEGA CTA WORD REVEAL

```js
gsap.utils.toArray('.mega-title span').forEach((word, i) => {
  gsap.from(word, {
    scrollTrigger: { trigger: '.mega-cta', start: 'top 75%', once: true },
    y: '100%', opacity: 0, duration: 0.8, delay: i * 0.12, ease: 'power3.out'
  });
});
```

---

## [C] ACCORDION INTERACTION

```js
document.querySelectorAll('.feature-accordion-header').forEach(header => {
  header.addEventListener('click', () => {
    const item = header.parentElement;
    const wasOpen = item.classList.contains('open');
    
    document.querySelectorAll('.feature-accordion-item').forEach(i => i.classList.remove('open'));
    
    if (!wasOpen) {
      item.classList.add('open');
      gsap.from(item.querySelector('.feature-sub-list'), {
        height: 0, opacity: 0, duration: 0.3, ease: 'power2.out'
      });
    }
  });
});
```

---

## [S] MOBILE ADAPTATIONS

```js
gsap.matchMedia().add('(max-width: 768px)', () => {
  ScrollTrigger.getAll()
    .filter(st => st.vars.scrub)
    .forEach(st => st.kill());
});
```