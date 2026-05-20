# Black Glass Widget — Claude Code Spec

## Overview

A floating overlay widget with a black glass aesthetic inspired by iOS dark materials. It sits positioned over page content. The glass effect uses a two-layer shell technique to achieve true black transparency rather than grey.

---

## Structure

Two nested elements are required — a shell and a face. Never collapse these into one.

```html
<div class="widget-shell">
  <div class="widget-face">
    <!-- content -->
  </div>
</div>
```

---

## CSS

```css
/* ── Shell: provides the dark floor behind the blur ── */
.widget-shell {
  position: fixed; /* or absolute depending on context */
  top: 28px;
  right: 24px;
  width: 268px;
  border-radius: 22px;
  background: rgba(0, 0, 0, 0.70);
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.10),
    0 2px 0 0 rgba(255, 255, 255, 0.18) inset,
    0 -1px 0 0 rgba(0, 0, 0, 0.60) inset,
    0 20px 60px rgba(0, 0, 0, 0.50);
  z-index: 9999;
}

/* ── Face: frosted glass layer on top of the dark floor ── */
.widget-face {
  background: rgba(255, 255, 255, 0.03);
  border-radius: 22px;
  padding: 18px;
  backdrop-filter: blur(40px) saturate(150%);
  -webkit-backdrop-filter: blur(40px) saturate(150%);
}

/* ── Typography ── */
.widget-title {
  font-size: 14px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  letter-spacing: -0.01em;
  margin-bottom: 2px;
}

.widget-subtitle {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.32);
  margin-bottom: 14px;
  letter-spacing: 0.01em;
}

/* ── Stat bead panels ── */
.stat-row {
  display: flex;
  gap: 7px;
  margin-bottom: 12px;
}

.stat-bead {
  flex: 1;
  border-radius: 12px;
  padding: 10px 8px 9px;
  background: linear-gradient(
    160deg,
    rgba(255, 255, 255, 0.14) 0%,
    rgba(255, 255, 255, 0.04) 40%,
    rgba(0, 0, 0, 0.20) 100%
  );
  box-shadow:
    0 1.5px 0 rgba(255, 255, 255, 0.22) inset,  /* top specular highlight */
    0 -1px 0 rgba(0, 0, 0, 0.50) inset,          /* bottom shadow — gives convex depth */
    1px 0 0 rgba(255, 255, 255, 0.06) inset,      /* left edge catch light */
    0 0 0 0.5px rgba(255, 255, 255, 0.10),        /* outer border */
    0 4px 12px rgba(0, 0, 0, 0.30);               /* drop shadow */
}

.stat-number {
  font-size: 19px;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: -0.03em;
  line-height: 1;
  margin-bottom: 4px;
  text-shadow: 0 0 12px rgba(255, 255, 255, 0.40);
}

.stat-label {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.30);
  letter-spacing: 0.02em;
}

/* ── Text input ── */
.glass-input {
  width: 100%;
  border: none;
  border-radius: 12px;
  padding: 9px 13px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.85);
  font-family: inherit;
  outline: none;
  margin-bottom: 10px;
  background: linear-gradient(
    170deg,
    rgba(255, 255, 255, 0.09) 0%,
    rgba(255, 255, 255, 0.02) 50%,
    rgba(0, 0, 0, 0.15) 100%
  );
  box-shadow:
    0 1.5px 0 rgba(255, 255, 255, 0.18) inset,
    0 -1px 0 rgba(0, 0, 0, 0.45) inset,
    0 0 0 0.5px rgba(255, 255, 255, 0.11),
    0 3px 10px rgba(0, 0, 0, 0.25);
}

.glass-input::placeholder {
  color: rgba(255, 255, 255, 0.18);
}

/* ── Buttons ── */
/* IMPORTANT: Use <div> not <button> to avoid browser colour overrides */

.btn-row {
  display: flex;
  gap: 7px;
}

.btn-primary {
  flex: 1;
  border-radius: 100px;
  padding: 9px 0;
  font-size: 12px;
  font-weight: 600;
  color: #ffffff !important;
  -webkit-text-fill-color: #ffffff;
  cursor: pointer;
  font-family: inherit;
  text-align: center;
  border: none;
  letter-spacing: 0.01em;
  user-select: none;
  background: linear-gradient(
    160deg,
    rgba(255, 255, 255, 0.22) 0%,
    rgba(255, 255, 255, 0.08) 50%,
    rgba(0, 0, 0, 0.15) 100%
  );
  box-shadow:
    0 1.5px 0 rgba(255, 255, 255, 0.40) inset,
    0 -1px 0 rgba(0, 0, 0, 0.50) inset,
    0 0 0 0.5px rgba(255, 255, 255, 0.20),
    0 4px 18px rgba(255, 255, 255, 0.08),
    0 1px 3px rgba(0, 0, 0, 0.40);
  text-shadow: 0 0 14px rgba(255, 255, 255, 0.60);
}

.btn-ghost {
  border-radius: 100px;
  padding: 9px 16px;
  font-size: 12px;
  font-weight: 500;
  color: #ffffff !important;
  -webkit-text-fill-color: #ffffff;
  cursor: pointer;
  font-family: inherit;
  border: none;
  user-select: none;
  background: linear-gradient(
    160deg,
    rgba(255, 255, 255, 0.08) 0%,
    rgba(255, 255, 255, 0.02) 50%,
    rgba(0, 0, 0, 0.20) 100%
  );
  box-shadow:
    0 1.5px 0 rgba(255, 255, 255, 0.14) inset,
    0 -1px 0 rgba(0, 0, 0, 0.45) inset,
    0 0 0 0.5px rgba(255, 255, 255, 0.08),
    0 3px 10px rgba(0, 0, 0, 0.25);
}

/* ── Divider ── */
.widget-divider {
  height: 0.5px;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.10), transparent);
  margin: 13px 0;
}

/* ── Status row ── */
.status-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 35%, rgba(255, 255, 255, 0.95), rgba(180, 255, 200, 0.70));
  box-shadow: 0 0 6px rgba(255, 255, 255, 0.45), 0 0 2px rgba(255, 255, 255, 0.80);
}

.status-text {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.25);
}
```

---

## Full HTML example

```html
<div class="widget-shell">
  <div class="widget-face">

    <div class="widget-title">GroundedAnswers</div>
    <div class="widget-subtitle">3 sources active</div>

    <div class="stat-row">
      <div class="stat-bead">
        <div class="stat-number">12</div>
        <div class="stat-label">Queries</div>
      </div>
      <div class="stat-bead">
        <div class="stat-number">94%</div>
        <div class="stat-label">Grounded</div>
      </div>
      <div class="stat-bead">
        <div class="stat-number">1.2s</div>
        <div class="stat-label">Latency</div>
      </div>
    </div>

    <input class="glass-input" placeholder="Ask something…" />

    <div class="btn-row">
      <div class="btn-primary">Ask</div>
      <div class="btn-ghost">Clear</div>
    </div>

    <div class="widget-divider"></div>

    <div class="status-row">
      <div class="status-dot"></div>
      <div class="status-text">Verified · 2 sec ago</div>
    </div>

  </div>
</div>
```

---

## Key principles — do not deviate

### Two-layer shell is mandatory
The dark floor (`widget-shell`) and the frosted face (`widget-face`) must remain as separate elements. Collapsing them into one will cause the blur to sample the light page background, making the widget look grey instead of black.

### Never use `<button>` elements
Browsers apply their own colour stylesheets to `<button>`. Use `<div>` with `cursor: pointer` instead. If `<button>` must be used for accessibility reasons, add both `color: #ffffff !important` and `-webkit-text-fill-color: #ffffff` to override.

### 3D bead effect requires all four shadow layers
Each interactive element (stat beads, input, buttons) gets its physical depth from a specific combination of inset shadows:
- `0 1.5px 0 rgba(255,255,255,0.22) inset` — top specular highlight (light hitting the top curve)
- `0 -1px 0 rgba(0,0,0,0.50) inset` — bottom shadow (underside of the convex surface)
- A diagonal gradient from light top-left to dark bottom-right
- An outer drop shadow beneath the element

Remove any of these and the element goes flat.

### All text and glows are white only
No colour is used anywhere in the widget. Hierarchy is achieved purely through white opacity:
- Primary text: `rgba(255,255,255,0.95)` or `#ffffff`
- Secondary text: `rgba(255,255,255,0.32)`
- Tertiary / metadata: `rgba(255,255,255,0.25)`
- Glows and text-shadows: `rgba(255,255,255,N)`

### Transparency level
The shell background is `rgba(0,0,0,0.70)`. This is deliberately opaque enough to keep the widget readable while the blur creates the sense of depth. Do not reduce below `0.60` or the black glass effect is lost.
