---
name: quantic-design-language
description: Deep-dark glass-morphism design language inspired by Quantic. Rich gradients, generous spacing, refined motion, premium SaaS aesthetic.
version: 1.0
---

# Quantic Design Language

A premium dark-mode design system for web UIs. Inspired by [Quantic](https://quantic-251aea.webflow.io) — deep backgrounds, glass-morphism, gradient accents, generous spacing, refined spring animations.

## Design Tokens

```css
:root {
  /* Palette */
  --bg-deep:     #06060a;
  --bg:          #0a0a0f;
  --surface:     #12121a;
  --surface-2:   #1a1a25;
  --glass:       rgba(255,255,255,0.04);
  --glass-border:rgba(255,255,255,0.08);
  --glass-hover: rgba(255,255,255,0.07);

  /* Accent triad */
  --accent:      #7c5cfc;
  --accent-light:#a78bfa;
  --cyan:        #22d3ee;
  --pink:        #f472b6;
  --gradient:    linear-gradient(135deg, #7c5cfc 0%, #22d3ee 50%, #f472b6 100%);

  /* Text */
  --text-1:      #f0f0f5;
  --text-2:      #9494a5;
  --text-3:      #5a5a6e;

  /* 8px spacing scale */
  --s1:8px;--s2:16px;--s3:24px;--s4:32px;--s5:40px;
  --s6:48px;--s8:64px;--s10:80px;--s12:96px;

  /* Radius */
  --r-sm:8px;--r-md:12px;--r-lg:16px;--r-xl:24px;--r-full:9999px;

  /* Shadows */
  --shadow-glow:0 0 40px rgba(124,92,252,0.15);
  --shadow-md:0 4px 20px rgba(0,0,0,0.4);

  /* Motion */
  --ease-out:cubic-bezier(0.16,1,0.3,1);
  --ease-spring:cubic-bezier(0.34,1.56,0.64,1);
  --duration:0.4s;
}
```

## Key Patterns

### Ambient Background
Deep background with 3 blurred gradient orbs + subtle dot grid:
- Orb 1: purple (#7c5cfc), top-left, 600px, blur 120px
- Orb 2: cyan (#22d3ee), bottom-right, 500px
- Orb 3: pink (#f472b6), center, 400px, low opacity
- Grid: 60px lines at 0.02 opacity, radial-gradient mask

### Glass-Morphism Cards
```
background: var(--glass)
border: 1px solid var(--glass-border)
border-radius: var(--r-lg)
backdrop-filter: none (container only)
hover → border-color: rgba(124,92,252,0.3), box-shadow: var(--shadow-glow)
```

### Gradient Text
```
background: var(--gradient);
-webkit-background-clip: text;
-webkit-text-fill-color: transparent;
```

### Shine-Sweep Button
Gradient button with `::before` pseudo-element — white gradient sweep on hover (translateX -100% → 100%).

### Staggered Card Entrance
Each card: `animation: cardIn 0.5s ease-out both; animation-delay: index * 0.05s`

### Navigation
`position:sticky; backdrop-filter: blur(20px) saturate(180%); background: rgba(6,6,10,0.7);`

### Toggle Pills
3px padded container with rounded-full buttons — active state gets accent bg + glow.

## Typography
- Font: Inter
- Hero: 48px/800 weight, -1.5px tracking
- Section title: 24px/700, -0.5px tracking
- Body: 17px/400
- Meta: 12-13px
- Gradient text for hero headlines only

## What Makes It Premium
1. Deep background (#06060a not #000) — less harsh
2. Generous padding (80px hero, 64px sections)
3. Subtle glow on hover, never loud
4. Spring easing (overshoot) on modal/button entries
5. Glass borders at 8% white — barely visible but adds depth
6. Triad accent (purple-cyan-pink) instead of single accent
7. Status dot with pulsing glow — always feels alive