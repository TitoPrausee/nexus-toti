---
name: ui-pattern-analysis
description: Deep web UI analysis combining code inspection with visual screenshot evaluation to identify, catalog, and remember design patterns.
version: 1.0
---

# UI Pattern Analysis

Analyzes web UIs by combining **code reading** + **visual screenshot evaluation** to identify, catalog, and remember design patterns with high precision.

## When to Use

- Analyzing a website's design system / component library
- Reverse-engineering UI patterns from reference sites
- Before building a UI: study existing patterns first
- QA: comparing implemented UI vs. intended design
- Building a personal design pattern library over time

## Process

### Step 1: Navigate & Snapshot Code

```
1. browser_navigate(url)
2. browser_snapshot(full=true) → get DOM structure, component tree, class names
3. browser_console(expression="...") → extract CSS custom properties, design tokens
```

**Extract via console:**

```javascript
// Design tokens / CSS custom properties
const styles = getComputedStyle(document.body);
const customProps = [];
for (const sheet of document.styleSheets) {
  try {
    for (const rule of sheet.cssRules) {
      if (rule.selectorText === ':root' || rule.selectorText === 'html') {
        const props = rule.cssText.match(/--[\w-]+:\s*[^;]+/g);
        if (props) customProps.push(...props);
      }
    }
  } catch(e) {} // cross-origin sheets
}

// Component inventory (tag names + classes)
const components = [...new Set([...document.querySelectorAll('[class]')]
  .map(el => el.tagName + '.' + el.className.split(' ').filter(c => !c.match(/^[a-z]{2,}$/)).join('.'))
  .filter(c => c.length < 80))];

// Layout structure
const layout = {
  fonts: [...new Set([...document.querySelectorAll('*')].map(el => getComputedStyle(el).fontFamily))],
  colors: [...new Set([...document.querySelectorAll('*')].map(el => getComputedStyle(el).color).filter(c => c !== 'rgba(0, 0, 0, 0)'))].slice(0, 20)],
  bgColors: [...new Set([...document.querySelectorAll('*')].map(el => getComputedStyle(el).backgroundColor).filter(c => c !== 'rgba(0, 0, 0, 0)'))].slice(0, 20),
  spacings: [...new Set([...document.querySelectorAll('*')].map(el => getComputedStyle(el).margin + ' / ' + getComputedStyle(el).padding))].slice(0, 30),
  borderRadii: [...new Set([...document.querySelectorAll('*')].map(el => getComputedStyle(el).borderRadius))].filter(r => r !== '0px').slice(0, 15),
  shadows: [...new Set([...document.querySelectorAll('*')].map(el => getComputedStyle(el).boxShadow))].filter(s => s !== 'none').slice(0, 15),
  transitions: [...new Set([...document.querySelectorAll('*')].map(el => getComputedStyle(el).transition))].filter(t => t !== 'all 0s ease 0s' && t !== 'none 0s ease 0s').slice(0, 15),
};

return JSON.stringify({customProps, components: components.slice(0, 50), layout}, null, 2);
```

### Step 2: Screenshot & Visual Analysis

```
1. browser_vision(question="Analyze this UI in detail: (1) Overall layout structure, (2) Visual hierarchy, (3) Color palette, (4) Typography scale, (5) Spacing rhythm, (6) Component patterns (cards, buttons, forms, nav), (7) Animation/motion cues, (8) Unique design signatures", annotate=true)
2. browser_scroll(direction="down") → repeat vision for below-fold content
3. browser_get_images() → catalog all image assets
```

**Questions to ask vision for each section:**

| Focus | Question |
|-------|----------|
| Layout | "What grid/flex pattern is used? How many columns? Sidebar width?" |
| Hierarchy | "What's the visual weight order? Which element draws the eye first?" |
| Color | "List every distinct color. What's the accent? Background? Text hierarchy?" |
| Type | "What font sizes are used? Weight variations? Line heights?" |
| Spacing | "What's the base spacing unit? How does padding scale between elements?" |
| Components | "Identify repeating UI patterns: cards, lists, modals, nav patterns" |
| Motion | "What elements suggest animation? Hover states? Transitions?" |
| Signature | "What makes this UI unique? What would you copy?" |

### Step 3: Merge Code + Vision into Pattern Report

Combine findings into a structured pattern catalog:

```markdown
# [Site Name] — UI Pattern Analysis

## Design System Summary
- **Palette:** [primary, secondary, accent, bg, surface, text1, text2, border]
- **Typography:** [font stack, scale: xs/sm/base/lg/xl/2xl/3xl/4xl]
- **Spacing:** [base unit, scale: 1x/2x/3x/4x/6x/8x]
- **Radius:** [sm/md/lg/full values]
- **Shadow:** [sm/md/lg/xl values]
- **Motion:** [duration, easing defaults]

## Component Patterns

### [Pattern Name] e.g. "Card with Meta"
- **Visual:** [screenshot or ASCII sketch]
- **Structure:** [DOM hierarchy]
- **CSS:** [key properties: padding, radius, shadow, border]
- **Variants:** [e.g. compact/expanded/loading]
- **Used at:** [URLs where found]

### [Next Pattern...]

## Layout Patterns
| Pattern | Grid | Sidebar | Breakpoints |
|---------|------|---------|-------------|
| Main | 12-col | 280px | sm/md/lg/xl |

## Unique Signatures
- [What makes this site distinctive]
- [Copy-worthy patterns]

## Quick Reference (for building)
```css
:root {
  --primary: #...;
  --surface: #...;
  /* etc */
}
```
```

### Step 4: Save to Pattern Library

Save discovered patterns for reuse:

```
Save to: ~/./ui-patterns/[site-name].md
```

Also update the master index:

```
~/./ui-patterns/INDEX.md — lists all analyzed sites with key patterns
```

## Pitfalls

- **Cross-origin stylesheets** — `document.styleSheets` throws on external CSS. Wrap in try/catch.
- **Dynamic content** — Some UI only appears on scroll/interaction. Scroll down and re-analyze.
- **Framework obfuscation** — Tailwind generates utility classes, CSS-in-JS may not show in stylesheets. Rely more on vision + computed styles.
- **Dark/light mode** — Check if site has theme toggle. Analyze both states.
- **Mobile viewport** — Resize browser or use mobile UA to see responsive patterns.
- **Lazy-loaded components** — Some sections load on scroll. Wait before screenshotting.

## Quick One-Liner Analysis

For fast analysis without full process:

```
browser_navigate(url) → browser_vision(question="Extract: colors, fonts, spacing, component patterns, design signatures") → browser_console(expression="JSON.stringify({colors:[...new Set([...document.querySelectorAll('*')].map(e=>getComputedStyle(e).color))].slice(0,10),fonts:[...new Set([...document.querySelectorAll('*')].map(e=>getComputedStyle(e).fontFamily))].slice(0,5)})")
```