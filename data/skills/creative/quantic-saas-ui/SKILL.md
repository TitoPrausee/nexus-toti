---
name: quantic-saas-ui
description: "Builds premium landing pages using Quantic + Central design systems. NOT just SaaS — adapts for private tools, internal apps, and personal projects too. Key lesson: always clarify the PRODUCT CONTEXT (commercial vs private/internal) BEFORE building, because it radically changes content strategy (no pricing, no signup CTAs, no business metrics for private tools)."
---

# SaaS Landing Page Skill — Quantic + Central Design System

This skill synthesizes two reference-quality SaaS design languages:

**Quantic** (quantic-251aea.webflow.io):
- Crisp white hero + dark feature sections
- Floating dashboard UI mockups at ~10deg tilt
- Sketch/doodle illustrations mixed with real UI
- Gradient color blobs (purple/blue/orange)
- Pill-style trust badges + logo bars
- Animated feature tabs with panel swap

**Central** (central-website-template.webflow.io):
- Split-screen hero: large media left (50vw) | dark text panel right (50vw)
- Floating tilted phone/device mockup on warm gradient bg
- Dual CTA button pair: light outline + dark fill, side by side
- Kinetic text marquee (infinite horizontal scroll strip)
- Bento-style benefits grid (alternating image/text cards)
- Accordion-style feature section with sub-item lists
- Testimonial + metric combo block
- Mega footer CTA: huge display text, stacked word-by-word
- All systems operational status indicator in footer
- Minimal monochrome color system (black/white/gray only)

Read references/components.md for detailed HTML/CSS patterns.
Read references/animations.md for all GSAP animation code.

---

## Step 0 — Brief Collection

| Question | Default if skipped |
|---|---|
| Product name + tagline | Use placeholder |
| Style mode | See options below |
| Primary CTA text | Get Started |
| Secondary CTA text | Book a demo |
| Feature list (3-5 items) | Smart Triggers, Dynamic Content, Deliverability Shield |
| Brand accent color | #6C63FF (purple) or none (monochrome) |
| Dark section background | #0D0D0D |

## Context Adaptation (Critical)

**Always clarify the product context before building.** The same Quantic+Central visual design system serves fundamentally different content:

| | Commercial SaaS | Private Tool / Internal App |
|---|---|---|
| CTA | "Kostenlos starten", "Pro werden" | "Im Netzwerk öffnen", "Jetzt nutzen" |
| Pricing | Tiered pricing section (Starter/Pro/Team) | NO pricing — access/network section instead |
| Metrics | "2M+ Bilder", "99.9% Verfügbarkeit" | NO vanity metrics — show network status, connected devices |
| Benefits | Business ROI, scalability, ROI | Privacy, self-hosted, no accounts, friends & family |
| Marquee | Feature slogans | "Private By Design", "Kein Abo", "0 Tracking" |
| Hero badge | "Jetzt mit Aurora-Modell" | "Privates Netzwerk" |
| Footer | Multi-column, legal links | Minimal, network status dot |

**Pitfall:** Building a full SaaS landing page with pricing for a private tool is a total waste — requires complete content rebuild. Ask "Is this commercial or private?" first.

## Style Modes

| Mode | Source | When to use |
|---|---|---|
| Quantic | Quantic template | Product has illustration mascot, colorful blobs, dashboard UI to show off |
| Central | Central template | App product, minimal brand, phone mockup, wants dark+light split-screen feel |
| Hybrid | Both | Use Central hero + Quantic features, or mix freely |

Central key differences vs. Quantic:
- Hero is SPLIT-SCREEN (50/50), not centered
- Color palette is monochrome (black + white, no colored blobs)
- Device mockup (phone) instead of dashboard UI cards
- Dual CTA buttons (outline + filled) instead of single pill
- Kinetic marquee strip replaces static logo bar
- Font: Neue Haas Grotesk / DM Sans / Inter
- No sketch illustrations — photography or device renders instead

---

## Step 1 — Page Architecture

### Quantic Layout (7 sections)

1. NAVBAR — light, minimal, pill CTA button
2. HERO — light bg, centered headline, floating mockups left/right, trust badge + logos
3. FEATURES DARK — dark bg, tabbed feature list left, animated product UI right
4. SOCIAL PROOF — metric cards or testimonials
5. HOW IT WORKS — numbered steps or timeline
6. PRICING — 2-3 plan cards with annual/monthly toggle
7. FOOTER CTA — dark, bold headline, single CTA button

### Central Layout (8 sections)

1. NAVBAR — minimal, logo left, links center, dual CTAs right
2. HERO SPLIT — light left panel (device mockup on gradient) | dark right panel (headline + CTAs)
3. KINETIC MARQUEE — dark strip, infinite scrolling text
4. BENEFITS BENTO — alternating image/text grid cards
5. FEATURES ACCORDION — headline + 4 expandable feature categories with sub-item lists
6. SOCIAL PROOF — testimonial quote + avatar + 4 metric stats in a row
7. PRICING — yearly/monthly toggle, 2 plan cards + 3 feature callout badges
8. FAQ + FOOTER — accordion FAQ, then mega CTA + footer columns

### Hybrid: Central HERO SPLIT + Quantic FEATURES DARK + KINETIC MARQUEE anywhere as separator.

### Design Tokens — Quantic (colorful)

```css
:root {
  --bg-light: #FFFFFF;
  --bg-dark: #0D0D0D;
  --bg-dark-surface: #141414;
  --bg-card: #1A1A1A;
  --accent-primary: #6C63FF;
  --accent-secondary: #FF6B35;
  --accent-green: #4ADE80;
  --accent-warm: #F59E0B;
  --text-dark: #0D0D0D;
  --text-light: #FFFFFF;
  --text-muted-dark: #6B7280;
  --text-muted-light: rgba(255,255,255,0.55);
  --border-light: #E5E7EB;
  --border-dark: rgba(255,255,255,0.08);
  --blob-purple: rgba(108, 99, 255, 0.18);
  --blob-orange: rgba(255, 107, 53, 0.15);
  --blob-pink: rgba(236, 72, 153, 0.12);
  --font-display: 'Bricolage Grotesque', 'DM Sans', sans-serif;
  --font-body: 'Inter', system-ui, sans-serif;
  --container: 1200px;
  --section-pad-y: clamp(80px, 10vw, 140px);
  --radius-card: 20px;
  --radius-pill: 999px;
}
```

### Design Tokens — Central (monochrome)

```css
:root {
  --bg-light: #F5F4F0;
  --bg-dark: #0D0D0D;
  --bg-split-left: #F0EDE6;
  --bg-card: #1A1A1A;
  --accent-none: transparent;
  --text-dark: #0D0D0D;
  --text-light: #FFFFFF;
  --text-muted-dark: #6B7280;
  --text-muted-light: rgba(255,255,255,0.5);
  --border-light: rgba(0,0,0,0.08);
  --border-dark: rgba(255,255,255,0.08);
  --font-display: 'DM Sans', 'Inter', system-ui, sans-serif;
  --font-body: 'Inter', system-ui, sans-serif;
  --container: 1280px;
  --section-pad-y: clamp(80px, 10vw, 140px);
  --radius-card: 16px;
  --radius-btn: 999px;
}
```

---

## Step 2 — Component Vocabulary

### Shared Components (2.1-2.7)

| Component | Quantic | Central | Animation |
|---|---|---|---|
| Navbar | White, single pill CTA | Minimal, dual CTAs right | Slide in from top |
| Hero | Centered text, floating mockups, blobs | Split 50/50, device mockup left, dark text right | Word-split stagger, mockup slide, parallax |
| Features | Dark bg, tabbed list, warm panel | Accordion with sub-items | Scroll reveal, tab/accordion click swaps |
| Social Proof | Metric counters or testimonial cards | Quote + avatar + 4 metrics row | Count up on scroll, stagger |
| Pricing | 3-tier cards, popular highlighted | 2-tier + feature badges | Button magnetic hover |
| Footer CTA | Dark bg, large headline, pill button | Mega stacked title, 100px+ font | Fade in / word stagger |
| Footer | Logo + link columns | Same + status indicator | — |

### Central-Specific Components (2.8-2.14)

**2.8 Split-Screen Hero:**
- Left 50vw: warm cream gradient (#F0EDE6), tilted phone mockup with 3D perspective
- Right 50vw: near-black (#0D0D0D), left-aligned text, dual CTA buttons
- Device: transform perspective(1000px) rotateY(-12deg) rotateX(3deg)
- Dual CTA: btn-outline-light (white bg, dark text) + btn-filled-dark (dark bg, white text, border)

**2.9 Kinetic Text Marquee:**
- Dark strip (~80px), infinite right-to-left scroll
- Text: uppercase, wide tracking, muted white
- Duplicate content 3x for seamless loop
- Pause on hover

**2.10 Benefits Bento Grid:**
- Alternating full-width + 2-column cards
- Light gray bg, border-radius 20px
- Label + title + description + image per card

**2.11 Accordion Feature Section:**
- Expandable categories with + icon (rotates to x)
- Sub-list: 2-column grid of items in light gray badges

**2.12 Testimonial + Metrics Combo:**
- Large pull quote + avatar + name
- 4 metric stats in horizontal row below

**2.13 Mega Footer CTA:**
- Stacked word-per-line headline, font-size clamp(72px, 12vw, 160px)
- Words reveal from below with stagger on scroll

**2.14 Footer Status Indicator:**
- Green pulsing dot + "All systems operational" text

---

## Step 3 — Animation Patterns

See references/animations.md for full GSAP code.

- **Hero entrance**: word-split stagger (0.04s per word), trust pill scale, mockup slide
- **Parallax**: mockups drift opposite directions on scroll (scrub 1.5)
- **Feature tabs/accordion**: click crossfade panels, expand/collapse description
- **Counters**: scroll enter animate from 0 to target
- **Magnetic hover**: CTA buttons follow cursor with dampened offset
- **Smooth scroll**: Lenis + ScrollTrigger pipeline
- **Mega CTA**: words slide up from below with 0.12s stagger
- **Marquee**: CSS infinite scroll, pauses on hover
- **Status dot**: CSS pulse animation
- **Reduced motion**: kill all animations for prefers-reduced-motion

---

## Step 4 — Frontend Developer Rules

### Critical CSS

- Pill buttons: border-radius 999px, black bg, white text, scale on hover
- Trust pills: white bg, light border, inline-flex, stars orange
- Floating mockups: transform rotate(-10deg), absolute, box-shadow 0 20px 60px
- Dark panels: background linear-gradient(135deg, #F59E0B, #FCD34D)
- Feature tabs: border-top 1px solid rgba(255,255,255,0.08), active shows desc
- H1: clamp(44px, 6vw, 72px), weight 800 (Quantic) or 600-700 (Central)
- Split hero: display grid, grid-template-columns 1fr 1fr
- Device mockup: perspective(1000px) rotateY(-12deg) rotateX(3deg)
- Marquee: duplicate content 3x, CSS animation translateX(-50%) infinite
- Mega CTA: font-size clamp(72px, 12vw, 160px), flex-direction column

---

## Step 5 — QA Checklist

**Design Quantic:**
- Hero: left float | center text | right float
- Blobs behind content (z-index 0)
- Mockup cards tilted
- Trust pill above H1
- Pill CTA
- Dark section: green highlighted text
- Feature tabs: separator lines, not boxes

**Design Central:**
- Split hero: true 50/50 grid
- Left panel: warm gradient (cream/peach)
- Phone mockup: 3D CSS perspective
- Right panel: near-black, text left-aligned
- Dual CTA: outline-light + filled-dark
- Marquee: content duplicated 3x
- Mega CTA: stacked word-per-line, 100px+ font
- Footer: status indicator with pulsing green dot

**Animations:**
- H1 word-split stagger
- Mockups parallax on scroll
- Feature tabs crossfade panels
- CTA magnetic hover
- Counters count up on scroll
- Mega CTA words reveal from below with stagger
- Marquee pauses on hover

**Typography:**
- H1: clamp(44px, 6vw, 72px), weight 800 (Quantic) / 600-700 (Central)
- Mega CTA: clamp(72px, 12vw, 160px), weight 700
- Body: Inter, 15-17px, line-height 1.6

**Responsive:**
- Floating mockups hidden on mobile
- Split hero stacks vertically on mobile
- Feature section stacks on mobile
- Pricing cards stack on mobile
- Marquee: always full-width

---

## Output Format

Single self-contained HTML file. CSS in style tag, JS at bottom of body.

CDN:
- Google Fonts: Bricolage Grotesque + Inter (Quantic) or DM Sans + Inter (Central)
- GSAP 3.12.5 + ScrollTrigger
- Lenis smooth scroll