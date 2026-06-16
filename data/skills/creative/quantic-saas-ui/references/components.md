# Component Reference — Quantic + Central SaaS UI

Full HTML/CSS patterns for all components. Quantic [Q], Central [C], shared [S].

---

## [S] NAVBAR

```html
<nav class="navbar" id="navbar">
  <div class="nav-inner">
    <a href="#" class="nav-logo">
      <svg class="logo-icon" ...></svg>
      <span class="logo-text">BrandName</span>
    </a>
    <ul class="nav-links" role="list">
      <li><a href="#" class="nav-link">Home</a></li>
      <li><a href="#" class="nav-link">Pricing</a></li>
      <li><a href="#" class="nav-link">About us</a></li>
      <li><a href="#" class="nav-link">Blog</a></li>
      <li><a href="#" class="nav-link">Contact</a></li>
    </ul>
    <!-- Quantic: single pill CTA -->
    <a href="#" class="btn-pill-dark nav-cta">Get Started <span aria-hidden="true">›</span></a>
    <!-- Central: dual CTA pair -->
    <div class="cta-pair">
      <a href="#" class="btn-outline-light">Get started</a>
      <a href="#" class="btn-filled-dark">Book a demo</a>
    </div>
    <button class="nav-hamburger" aria-label="Menu" aria-expanded="false">
      <span></span><span></span><span></span>
    </button>
  </div>
</nav>
```

```css
.navbar {
  position: fixed; top: 0; left: 0; right: 0; z-index: 100;
  background: rgba(255,255,255,0.9);
  backdrop-filter: blur(0px);
  transition: backdrop-filter 0.3s ease, box-shadow 0.3s ease;
}
.navbar.scrolled { backdrop-filter: blur(12px); box-shadow: 0 1px 0 rgba(0,0,0,0.08); }
.nav-inner {
  max-width: var(--container); margin: 0 auto;
  padding: 0 clamp(20px, 4vw, 48px); height: 64px;
  display: flex; align-items: center; gap: 40px;
}
.cta-pair { display: flex; gap: 12px; align-items: center; }
```

---

## [Q] HERO (Centered with floating mockups)

```html
<section class="hero" id="hero">
  <div class="blob blob-purple" aria-hidden="true"></div>
  <div class="blob blob-orange" aria-hidden="true"></div>
  <div class="mockup-wrap mockup-left" aria-hidden="true">
    <div class="mockup-card">
      <div class="mock-ui">
        <div class="mock-tabs">
          <span class="mock-tab active">Ready</span>
          <span class="mock-tab">Scheduled</span>
          <span class="mock-tab">Paid</span>
        </div>
        <div class="mock-field"><label>Amount</label><input type="text" value="$90.00 USD" disabled></div>
        <button class="mock-btn">Suggested</button>
      </div>
    </div>
  </div>
  <div class="hero-center">
    <div class="trust-pill">
      <span class="trust-icon">G</span>
      <span class="stars">&#9733;&#9733;&#9733;&#9733;&#9733;</span>
      <span class="trust-text">4.9 rating</span>
    </div>
    <h1 class="hero-headline">Supercharge your<br>inbox with <em>Brand</em></h1>
    <p class="hero-sub">Create stunning campaigns, automate customer<br>journeys, and land in the primary tab.</p>
    <a href="#" class="btn-pill-dark hero-cta">Get Started Now <span class="arrow">›</span></a>
    <div class="logos-section">
      <p class="logos-bar-label">TRUSTED BY EXPERTS AT</p>
      <div class="logos-bar">
        <div class="logo-item">&#9889; Sailwind</div>
        <div class="logo-item">&#9881; Stremax</div>
        <div class="logo-item">&#10037; Be-tech</div>
        <div class="logo-item">&#9744; Minibox</div>
        <div class="logo-item">&#9889; Superneon</div>
      </div>
    </div>
  </div>
  <div class="mockup-wrap mockup-right" aria-hidden="true">
    <div class="mockup-card">
      <div class="mock-ui">
        <div class="mock-label">Business Growth</div>
        <div class="mock-gauge">40%</div>
      </div>
    </div>
  </div>
</section>
```

```css
.hero {
  position: relative; min-height: 100vh;
  display: flex; align-items: center; justify-content: center;
  overflow: hidden; padding: 100px clamp(20px,4vw,48px) 80px;
  background: var(--bg-light);
}
.hero-center { position: relative; z-index: 2; text-align: center; max-width: 660px; }
.hero-headline {
  font-family: var(--font-display);
  font-size: clamp(44px, 6vw, 72px); font-weight: 800;
  line-height: 1.08; letter-spacing: -0.02em; color: var(--text-dark); margin: 16px 0 20px;
}
.blob { position: absolute; border-radius: 50%; filter: blur(80px); pointer-events: none; z-index: 0; }
.blob-purple { width: 500px; height: 500px; background: var(--blob-purple); }
.blob-orange { width: 400px; height: 400px; background: var(--blob-orange); }
.mockup-card {
  background: #FFFFFF; border-radius: 16px; border: 1px solid #E5E7EB;
  box-shadow: 0 20px 60px rgba(0,0,0,0.10); overflow: hidden; position: absolute;
}
.mockup-card.left { transform: rotate(-10deg); left: -60px; }
.mockup-card.right { transform: rotate(10deg); right: -60px; }
.trust-pill {
  display: inline-flex; align-items: center; gap: 8px;
  background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 999px;
  padding: 6px 14px 6px 10px; font-size: 13px; font-weight: 500; color: #374151;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.trust-pill .stars { color: #F59E0B; font-size: 14px; letter-spacing: 1px; }
```

---

## [C] SPLIT-SCREEN HERO (50/50)

```html
<section class="hero-split" id="hero">
  <div class="hero-left">
    <div class="device-mockup">
      <div class="phone-frame">
        <div class="phone-screen"><!-- App screenshot --></div>
      </div>
    </div>
  </div>
  <div class="hero-right">
    <div class="hero-text">
      <h1 class="hero-headline">Run your daily<br>tasks, all in<br>one place</h1>
      <p class="hero-sub">Simplify your workflow with smart automation,<br>real-time collaboration, and insights that matter.</p>
      <div class="cta-pair">
        <a href="#" class="btn-outline-light">Get started</a>
        <a href="#" class="btn-filled-dark">Book a demo</a>
      </div>
    </div>
  </div>
</section>
```

```css
.hero-split { display: grid; grid-template-columns: 1fr 1fr; min-height: 100vh; }
.hero-left {
  background: radial-gradient(ellipse at 60% 60%, #F5C5A3 0%, #F0E6D8 40%, #EDE0D4 100%);
  display: flex; align-items: center; justify-content: center;
  position: relative; overflow: hidden;
}
.hero-right {
  background: #0D0D0D; display: flex; align-items: center;
  padding: clamp(40px, 6vw, 80px);
}
.hero-text { max-width: 520px; }
.device-mockup {
  transform: perspective(1000px) rotateY(-12deg) rotateX(3deg) rotate(-2deg);
  transform-style: preserve-3d;
  filter: drop-shadow(0 40px 80px rgba(0,0,0,0.25));
  max-width: 320px; width: 60%;
}
.phone-frame {
  background: #1A1A1A; border-radius: 32px; padding: 12px;
  box-shadow: 0 4px 0 #0D0D0D, 0 0 0 2px #333;
}
.phone-screen {
  background: #FFFFFF; border-radius: 20px;
  aspect-ratio: 9/19.5; overflow: hidden;
}
```

---

## [C] KINETIC TEXT MARQUEE

```html
<section class="marquee-strip">
  <div class="marquee-track">
    <span class="marquee-item">Run your daily tasks</span>
    <span class="marquee-sep">&times;</span>
    <span class="marquee-item">All in one place</span>
    <span class="marquee-sep">&times;</span>
    <span class="marquee-item">Streamline your workflow</span>
    <span class="marquee-sep">&times;</span>
    <span class="marquee-item">Stay organized</span>
    <span class="marquee-sep">&times;</span>
    <!-- Duplicate 3x for seamless loop -->
    <span class="marquee-item">Run your daily tasks</span>
    <span class="marquee-sep">&times;</span>
    <span class="marquee-item">All in one place</span>
    <span class="marquee-sep">&times;</span>
    <span class="marquee-item">Streamline your workflow</span>
    <span class="marquee-sep">&times;</span>
    <span class="marquee-item">Stay organized</span>
    <span class="marquee-sep">&times;</span>
  </div>
</section>
```

```css
.marquee-strip {
  background: #0D0D0D; overflow: hidden; padding: 20px 0;
  border-top: 1px solid rgba(255,255,255,0.06);
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.marquee-track {
  display: flex; gap: 48px; width: max-content;
  animation: marquee 18s linear infinite;
}
.marquee-track:hover { animation-play-state: paused; }
.marquee-item {
  font-size: 13px; font-weight: 500; letter-spacing: 0.08em;
  text-transform: uppercase; color: rgba(255,255,255,0.6); white-space: nowrap;
}
.marquee-sep { color: rgba(255,255,255,0.25); font-size: 16px; }
@keyframes marquee {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }
}
```

---

## [Q] DARK FEATURE SECTION

```html
<section class="features-dark" id="features">
  <div class="section-inner">
    <div class="features-left">
      <h2 class="features-title">Automate the perfect<br><span class="title-highlight">customer journey</span></h2>
      <div class="feature-tabs">
        <div class="feature-tab active" data-index="0">
          <div class="tab-header"><span class="tab-icon">&#8695;</span><span class="tab-name">Smart Triggers</span></div>
          <p class="tab-desc">Identify and resolve inefficiencies with comprehensive performance analytics.</p>
          <a href="#" class="tab-link">Learn more &#8594;</a>
        </div>
        <div class="feature-tab" data-index="1">
          <div class="tab-header"><span class="tab-icon">&#9673;</span><span class="tab-name">Dynamic Content</span></div>
          <p class="tab-desc">Personalize every message with real-time user data.</p>
          <a href="#" class="tab-link">Learn more &#8594;</a>
        </div>
      </div>
    </div>
    <div class="features-right">
      <div class="feature-panel active" data-index="0">
        <div class="feature-panel-wrap">
          <div class="panel-ui-card"><!-- simulated product UI --></div>
          <div class="panel-overlay-card"><!-- floating overlay --></div>
        </div>
      </div>
    </div>
  </div>
</section>
```

```css
.features-dark { background: var(--bg-dark); padding: var(--section-pad-y) clamp(20px, 4vw, 48px); }
.section-inner {
  max-width: var(--container); margin: 0 auto;
  display: grid; grid-template-columns: 5fr 6fr;
  gap: clamp(40px, 6vw, 80px); align-items: start;
}
.features-title {
  font-family: var(--font-display); font-size: clamp(36px, 4vw, 54px);
  font-weight: 800; line-height: 1.15; color: #FFFFFF; margin-bottom: 40px;
}
.title-highlight { color: var(--accent-green); display: block; }
.feature-panel-wrap {
  background: linear-gradient(135deg, #F59E0B 0%, #FCD34D 100%);
  border-radius: 24px; padding: 32px; position: relative;
  overflow: hidden; min-height: 480px;
}
.feature-tab {
  border-top: 1px solid rgba(255,255,255,0.08);
  padding: 20px 0; cursor: pointer; transition: opacity 0.2s ease;
}
.feature-tab .tab-desc { display: none; }
.feature-tab .tab-link { display: none; }
.feature-tab.active .tab-desc, .feature-tab.active .tab-link { display: block; }
.feature-tab:not(.active) { opacity: 0.5; }
```

---

## [C] BENEFITS BENTO GRID

```html
<section class="benefits" id="benefits">
  <div class="benefits-inner">
    <div class="benefits-label">Benefits</div>
    <h2 class="benefits-title">Everything you need to<br>manage your workflow</h2>
    <div class="bento-grid">
      <div class="bento-card wide">
        <div class="bento-card-label">Collaboration</div>
        <h3>Work together, seamlessly</h3>
        <p>Real-time collaboration across teams with shared visibility and context.</p>
      </div>
      <div class="bento-card">
        <div class="bento-card-label">Security</div>
        <h3>Enterprise-grade protection</h3>
        <p>SOC 2 compliant, end-to-end encrypted, role-based access.</p>
      </div>
      <div class="bento-card">
        <div class="bento-card-label">Automation</div>
        <h3>Set it and forget it</h3>
        <p>Smart triggers handle repetitive tasks so you focus on what matters.</p>
      </div>
    </div>
  </div>
</section>
```

```css
.bento-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.bento-card {
  background: #F5F5F5; border-radius: 20px; overflow: hidden; padding: 32px;
}
.bento-card.wide { grid-column: 1 / -1; }
.bento-card-label {
  font-size: 11px; font-weight: 700; letter-spacing: 0.1em;
  text-transform: uppercase; color: #9CA3AF; margin-bottom: 12px;
}
.bento-card h3 { font-size: clamp(22px, 2.5vw, 32px); font-weight: 700; line-height: 1.2; margin-bottom: 12px; }
```

---

## [C] ACCORDION FEATURES

```html
<section class="features-accordion">
  <div class="section-inner">
    <div class="features-accordion-left">
      <h2>Built for teams that<br>move fast</h2>
      <div class="feature-accordion">
        <div class="feature-accordion-item open" data-index="0">
          <div class="feature-accordion-header"><span>Smart Triggers</span></div>
          <div class="feature-sub-list">
            <div class="feature-sub-item">Event-based automation</div>
            <div class="feature-sub-item">Conditional branching</div>
            <div class="feature-sub-item">Real-time alerts</div>
            <div class="feature-sub-item">Custom workflows</div>
          </div>
        </div>
      </div>
    </div>
    <div class="features-accordion-right"><!-- Switching product UI image --></div>
  </div>
</section>
```

```css
.feature-accordion-item { border-top: 1px solid #E5E7EB; padding: 20px 0; cursor: pointer; }
.feature-accordion-header {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 20px; font-weight: 700;
}
.feature-accordion-header::after {
  content: '+'; font-size: 24px; color: #9CA3AF; transition: transform 0.3s ease;
}
.feature-accordion-item.open .feature-accordion-header::after { transform: rotate(45deg); }
.feature-sub-list {
  display: none; padding: 16px 0 8px;
  grid-template-columns: 1fr 1fr; gap: 8px;
}
.feature-accordion-item.open .feature-sub-list { display: grid; }
.feature-sub-item {
  font-size: 14px; color: #374151; padding: 8px 12px;
  background: #F9FAFB; border-radius: 8px;
}
```

---

## [C] TESTIMONIAL + METRICS

```html
<section class="social-proof-central">
  <div class="testimonial-block">
    <blockquote class="testimonial-quote">
      "The platform is clear and reliable. It reduced manual work and made our processes easier to manage."
    </blockquote>
    <div class="testimonial-author">
      <img src="avatar.jpg" alt="James B." width="40" height="40">
      <div><div class="author-name">James B.</div><div class="author-role">Product Manager</div></div>
    </div>
  </div>
  <div class="metrics-row">
    <div class="metric"><span class="metric-value" data-target="95" data-suffix="%">0%</span><span class="metric-label">On-time completion</span></div>
    <div class="metric"><span class="metric-value">$2M</span><span class="metric-label">Value delivered</span></div>
    <div class="metric"><span class="metric-value">70+</span><span class="metric-label">Cross-team initiatives</span></div>
    <div class="metric"><span class="metric-value">30K</span><span class="metric-label">Tasks coordinated</span></div>
  </div>
</section>
```

---

## [C] MEGA FOOTER CTA

```html
<section class="mega-cta">
  <h2 class="mega-title"><span>Simplify</span><span>your</span><span>workflow</span></h2>
  <div class="mega-cta-buttons">
    <a href="#" class="btn-outline-light">Get started</a>
    <a href="#" class="btn-ghost">Watch video</a>
  </div>
</section>
```

```css
.mega-cta { background: #0D0D0D; padding: clamp(80px, 12vw, 160px) clamp(24px, 5vw, 80px); text-align: left; }
.mega-title {
  display: flex; flex-direction: column;
  font-size: clamp(72px, 12vw, 160px); font-weight: 700;
  line-height: 0.95; color: #FFFFFF; letter-spacing: -0.03em; margin-bottom: 48px;
}
.mega-title span { display: block; overflow: hidden; }
```

---

## [S] SHARED BUTTON STYLES

```css
.btn-pill-dark {
  display: inline-flex; align-items: center; gap: 8px;
  background: #0D0D0D; color: #FFFFFF; border: none; border-radius: 999px;
  padding: 12px 24px; font-family: var(--font-body);
  font-size: 15px; font-weight: 600; cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.btn-pill-dark:hover { transform: scale(1.03); box-shadow: 0 8px 24px rgba(0,0,0,0.20); }

.btn-pill-outline {
  display: inline-flex; align-items: center; gap: 8px;
  background: transparent; color: #0D0D0D; border: 1.5px solid #0D0D0D; border-radius: 999px;
  padding: 12px 24px; font-family: var(--font-body);
  font-size: 15px; font-weight: 600; cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.btn-pill-outline:hover { transform: scale(1.03); box-shadow: 0 4px 16px rgba(0,0,0,0.10); }

.btn-outline-light {
  background: #FFFFFF; color: #0D0D0D; border: none; border-radius: 999px;
  padding: 12px 28px; font-weight: 600; font-size: 15px;
}
.btn-filled-dark {
  background: #1A1A1A; color: #FFFFFF; border: 1px solid rgba(255,255,255,0.15); border-radius: 999px;
  padding: 12px 28px; font-weight: 600; font-size: 15px;
}
.btn-ghost {
  background: transparent; color: rgba(255,255,255,0.6); border: none;
  font-weight: 600; font-size: 15px; text-decoration: underline; cursor: pointer;
}
```