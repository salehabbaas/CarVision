# CarVision Admin Panel — Enterprise Redesign Specification

> **Purpose:** This document defines the complete visual language, component system, layout architecture, and page-by-page redesign blueprint to elevate CarVision's admin panel from a functional dark UI into a polished, enterprise-grade operations platform.

---

## 1. Design Philosophy

### Core Principles

**Clarity over density.** Enterprise operators make time-sensitive decisions from this panel. Every pixel must earn its place — reduce visual noise, amplify signal.

**Structured hierarchy.** Information is organized into clear tiers: primary metrics → secondary context → tertiary detail. Users should never hunt for what matters most.

**Trustworthy precision.** Enterprise software communicates confidence. Tight spacing, consistent alignment, and deliberate use of color signal a system that is reliable and under control.

**Contextual feedback.** The system should always communicate its own state — loading, stale, degraded, healthy. Operators can't trust what they can't read.

---

## 2. Design Tokens

### Color System

Replace all inline color references with a structured token system. Define in `src/design-system/tokens.css`.

```css
:root {
  /* === Surface === */
  --surface-base:        #060c14;   /* Page background */
  --surface-raised:      #0b1220;   /* Card / panel background */
  --surface-overlay:     #111d2e;   /* Modal, dropdown background */
  --surface-sunken:      #040810;   /* Input fields, code blocks */
  --surface-hover:       rgba(255, 255, 255, 0.04);
  --surface-active:      rgba(255, 255, 255, 0.07);

  /* === Border === */
  --border-subtle:       rgba(120, 160, 200, 0.10);
  --border-default:      rgba(120, 160, 200, 0.18);
  --border-strong:       rgba(120, 160, 200, 0.32);
  --border-focus:        #2e8fff;

  /* === Text === */
  --text-primary:        #e8f0fb;
  --text-secondary:      #8ba4c8;
  --text-tertiary:       #516a8a;
  --text-disabled:       #374a61;
  --text-inverse:        #0b1220;
  --text-on-accent:      #ffffff;

  /* === Brand / Accent === */
  --accent-primary:      #2e8fff;   /* Primary CTA, links, active nav */
  --accent-primary-dim:  rgba(46, 143, 255, 0.15);
  --accent-primary-glow: rgba(46, 143, 255, 0.30);
  --accent-secondary:    #00d4a0;   /* Secondary accent (teal) */
  --accent-secondary-dim:rgba(0, 212, 160, 0.12);

  /* === Semantic === */
  --status-success:      #00c77a;
  --status-success-dim:  rgba(0, 199, 122, 0.12);
  --status-warning:      #f5a623;
  --status-warning-dim:  rgba(245, 166, 35, 0.12);
  --status-danger:       #f04c5f;
  --status-danger-dim:   rgba(240, 76, 95, 0.12);
  --status-info:         #2e8fff;
  --status-info-dim:     rgba(46, 143, 255, 0.12);
  --status-neutral:      #516a8a;
  --status-neutral-dim:  rgba(81, 106, 138, 0.12);

  /* === Gradient === */
  --gradient-brand:   linear-gradient(135deg, #2e8fff 0%, #00d4a0 100%);
  --gradient-danger:  linear-gradient(135deg, #f04c5f 0%, #ff8c42 100%);
  --gradient-surface: linear-gradient(160deg, #0b1220 0%, #060c14 100%);

  /* === Shadow === */
  --shadow-sm:    0 1px 3px rgba(0, 0, 0, 0.4);
  --shadow-md:    0 4px 16px rgba(0, 0, 0, 0.5);
  --shadow-lg:    0 8px 32px rgba(0, 0, 0, 0.6);
  --shadow-focus: 0 0 0 3px rgba(46, 143, 255, 0.25);
  --shadow-card:  0 1px 2px rgba(0,0,0,0.4), 0 0 0 1px var(--border-subtle);

  /* === Spacing === */
  --space-1:  4px;
  --space-2:  8px;
  --space-3:  12px;
  --space-4:  16px;
  --space-5:  20px;
  --space-6:  24px;
  --space-8:  32px;
  --space-10: 40px;
  --space-12: 48px;
  --space-16: 64px;

  /* === Radius === */
  --radius-sm:   4px;
  --radius-md:   8px;
  --radius-lg:   12px;
  --radius-xl:   16px;
  --radius-pill: 9999px;

  /* === Typography Scale === */
  --font-sans:  "Inter", "IBM Plex Sans", system-ui, sans-serif;
  --font-mono:  "JetBrains Mono", "Fira Code", monospace;

  --text-xs:   11px;
  --text-sm:   13px;
  --text-base: 14px;
  --text-md:   15px;
  --text-lg:   17px;
  --text-xl:   20px;
  --text-2xl:  24px;
  --text-3xl:  30px;

  --weight-regular:   400;
  --weight-medium:    500;
  --weight-semibold:  600;
  --weight-bold:      700;

  --leading-tight:  1.25;
  --leading-normal: 1.5;
  --leading-loose:  1.75;

  /* === Transition === */
  --ease-default:  cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in:       cubic-bezier(0.4, 0, 1, 1);
  --ease-out:      cubic-bezier(0, 0, 0.2, 1);
  --duration-fast: 120ms;
  --duration-base: 200ms;
  --duration-slow: 350ms;

  /* === Z-index === */
  --z-base:    0;
  --z-raised:  10;
  --z-dropdown:100;
  --z-sticky:  200;
  --z-overlay: 300;
  --z-modal:   400;
  --z-toast:   500;
}
```

---

## 3. Typography System

### Font Stack

Switch from the current mixed font system to a single, enterprise-grade primary font.

```
Primary:    Inter (variable font, weights 400–700)
Monospace:  JetBrains Mono (metrics, plate numbers, timestamps, code)
Fallback:   system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI"
```

### Type Scale Usage

| Token     | Size | Weight | Use Case |
|-----------|------|--------|----------|
| `text-xs` | 11px | 500 | Labels, badges, helper text |
| `text-sm` | 13px | 400/500 | Table cells, secondary content |
| `text-base` | 14px | 400 | Body text, form inputs |
| `text-md` | 15px | 500 | Section labels, list titles |
| `text-lg` | 17px | 600 | Card headings, modal titles |
| `text-xl` | 20px | 600 | Page section headers |
| `text-2xl` | 24px | 700 | Metric values, KPIs |
| `text-3xl` | 30px | 700 | Hero numbers, top-level stats |

### Rules

- **Metric numbers** always use `font-mono` with `text-2xl` or `text-3xl`
- **Plate text** always rendered in `font-mono`, uppercase, letter-spacing `0.08em`
- **Timestamps** always `font-mono`, `text-xs`, `text-tertiary`
- **Table headers** `text-xs`, `weight-semibold`, `text-tertiary`, `letter-spacing: 0.06em`, uppercase
- **Never** use font-size below 11px
- **Line-height** defaults to `leading-normal` (1.5) for body; `leading-tight` (1.25) for headings and metrics

---

## 4. Layout Architecture

### Shell Layout

The app shell is the outermost container. It defines the permanent chrome that surrounds all page content.

```
┌─────────────────────────────────────────────────────────┐
│  TOPBAR  (56px, sticky, z-sticky)                       │
├──────────┬──────────────────────────────────────────────┤
│          │                                              │
│ SIDEBAR  │           PAGE CONTENT AREA                 │
│ (240px)  │           (scrollable, flex-col)            │
│          │                                              │
│          │                                              │
└──────────┴──────────────────────────────────────────────┘
```

**Sidebar collapsed state:** 64px wide (icon-only navigation).

**Breakpoints:**
- `>= 1440px`: Full layout with sidebar expanded
- `1024px – 1439px`: Sidebar collapsed by default, expandable on hover
- `< 1024px`: Sidebar hidden, accessible via hamburger overlay

### Page Content Layout

All pages follow a consistent internal structure:

```
PAGE CONTENT
├── Page Header (title + breadcrumb + primary actions)
├── Filter / Toolbar Bar (optional, when filters apply)
├── Content Body
│   ├── Metrics Row (KPI cards)
│   ├── Primary Content (table, grid, form, charts)
│   └── Secondary Content (sidepanel, drawer, related data)
└── Empty / Error State (replaces body when no data)
```

---

## 5. Component Redesigns

### 5.1 Sidebar Navigation

**Current issues:** Items too close together, no section grouping, active state uses gradient that's too prominent, icon alignment inconsistent.

**Redesigned spec:**

```
WIDTH: 240px expanded / 64px collapsed
BACKGROUND: var(--surface-raised)
BORDER-RIGHT: 1px solid var(--border-subtle)

Header area (logo):
  height: 56px (matches topbar)
  padding: 0 16px
  border-bottom: 1px solid var(--border-subtle)
  logo: BrandLogo component, 28px height

Nav sections (group items with labels):
  Section label:
    font-size: var(--text-xs)
    font-weight: var(--weight-semibold)
    color: var(--text-tertiary)
    text-transform: uppercase
    letter-spacing: 0.08em
    padding: 20px 16px 6px

Nav item (default):
  height: 36px
  padding: 0 12px
  border-radius: var(--radius-md)
  margin: 1px 8px
  display: flex, align-items: center, gap: 10px
  color: var(--text-secondary)
  font-size: var(--text-sm)
  font-weight: var(--weight-medium)
  transition: background var(--duration-fast), color var(--duration-fast)

Nav item (hover):
  background: var(--surface-hover)
  color: var(--text-primary)

Nav item (active):
  background: var(--accent-primary-dim)
  color: var(--accent-primary)
  font-weight: var(--weight-semibold)
  icon: accent-primary color

Nav item icon:
  size: 16px
  flex-shrink: 0
  opacity: 0.7 (default), 1.0 (active/hover)

Badge (notification count):
  position: right-aligned inside item
  height: 18px, min-width: 18px
  border-radius: var(--radius-pill)
  background: var(--status-danger)
  font-size: 10px, font-weight: 700
  color: white
  padding: 0 5px

Bottom of sidebar:
  User profile section (avatar + name + role)
  Settings link
  height: 56px
  border-top: 1px solid var(--border-subtle)
```

**Navigation section grouping:**

```
MONITOR
  ├── Dashboard
  ├── Live DVR
  └── Detections

MANAGEMENT
  ├── Cameras
  ├── Allowed Plates
  └── Discovery

AI & TRAINING
  ├── Upload & Test
  ├── Dataset Import
  ├── Training Data
  ├── Trained Data
  └── Training

SYSTEM
  ├── Notifications
  └── Clips
```

---

### 5.2 Topbar

**Current issues:** Cluttered with inline metrics that don't belong in the chrome. System metrics should live on Dashboard. Topbar should be lean.

**Redesigned spec:**

```
HEIGHT: 56px
BACKGROUND: var(--surface-raised)
BORDER-BOTTOM: 1px solid var(--border-subtle)
POSITION: sticky, top: 0, z-index: var(--z-sticky)
PADDING: 0 24px
LAYOUT: space-between

Left:
  - Breadcrumb: Page name + optional parent (e.g., "Cameras / Edit")
  - Page title (text-md, weight-semibold, text-primary)

Right (ordered left to right):
  - System health pill (compact: green/yellow/red dot + "All systems operational")
  - Notification bell (Lucide Bell, 20px)
    → Badge count if unread > 0
  - Divider (1px, var(--border-subtle), height 20px)
  - User avatar (28px circle, initials fallback)
  - User name (text-sm, weight-medium) — hidden < 1280px
  - Chevron-down for user menu dropdown
```

**User dropdown menu:**
```
width: 220px
shadow: var(--shadow-lg)
border: 1px solid var(--border-default)
border-radius: var(--radius-lg)
background: var(--surface-overlay)
items: Profile, Preferences, Keyboard shortcuts, divider, Sign out
```

---

### 5.3 Metric / KPI Cards

**Current issues:** Cards feel flat, numbers lack visual weight, no trend indicators, delta changes not shown.

**Redesigned spec:**

```
STRUCTURE:
┌──────────────────────────────────┐
│ ICON  Label                TREND │
│                                  │
│ PRIMARY VALUE                    │
│ secondary context                │
└──────────────────────────────────┘

Outer container:
  background: var(--surface-raised)
  border: 1px solid var(--border-subtle)
  border-radius: var(--radius-lg)
  padding: 20px 20px 16px
  box-shadow: var(--shadow-card)
  transition: border-color var(--duration-base)
  cursor: default

  &:hover:
    border-color: var(--border-default)

Icon container (top-left):
  width: 32px, height: 32px
  border-radius: var(--radius-md)
  background: (semantic-dim color per metric type)
  display: flex, align-items: center, justify-content: center
  icon: 16px, semantic color

Label (top, next to icon):
  font-size: var(--text-xs)
  font-weight: var(--weight-semibold)
  color: var(--text-tertiary)
  text-transform: uppercase
  letter-spacing: 0.06em

Trend badge (top-right):
  font-size: var(--text-xs)
  font-weight: var(--weight-semibold)
  border-radius: var(--radius-pill)
  padding: 2px 7px
  ↑ positive: background var(--status-success-dim), color var(--status-success)
  ↓ negative: background var(--status-danger-dim), color var(--status-danger)
  → neutral: background var(--surface-active), color var(--text-secondary)
  Format: "+12%" or "−3%"

Primary value:
  font-family: var(--font-mono)
  font-size: var(--text-3xl)
  font-weight: var(--weight-bold)
  color: var(--text-primary)
  line-height: 1.1
  margin-top: 12px

Secondary context:
  font-size: var(--text-xs)
  color: var(--text-tertiary)
  margin-top: 4px
  e.g. "Last 24 hours" or "3 new since yesterday"
```

**KPI Cards for Dashboard (7 cards, 4-column grid on wide screens):**

| Card | Icon | Semantic Color | Secondary Context |
|------|------|----------------|-------------------|
| Total Detections | `ScanLine` | info | "Last 24 hours" |
| Active Cameras | `Camera` | success | "of N total" |
| Allowed | `ShieldCheck` | success | "plates whitelisted" |
| Denied | `ShieldX` | danger | "blocked events" |
| Unread Alerts | `Bell` | warning | "require attention" |
| Trained Models | `Brain` | secondary | "ready to deploy" |
| Pending Actions | `Clock` | warning | "awaiting review" |

---

### 5.4 Data Tables

**Current issues:** No consistent table component exists across pages. Each page implements its own list differently.

**Redesigned spec — universal `<DataTable>` component:**

```
TABLE LAYOUT:
  width: 100%
  border-collapse: separate
  border-spacing: 0

HEADER ROW:
  height: 36px
  background: var(--surface-sunken)
  border-bottom: 1px solid var(--border-default)

  TH:
    font-size: var(--text-xs)
    font-weight: var(--weight-semibold)
    color: var(--text-tertiary)
    text-transform: uppercase
    letter-spacing: 0.06em
    padding: 0 16px
    text-align: left
    white-space: nowrap

    Sortable TH:
      cursor: pointer
      &:hover color: var(--text-secondary)
      sort icon: ChevronUp/Down, 12px, shown on hover or active

DATA ROW:
  height: 48px
  border-bottom: 1px solid var(--border-subtle)
  transition: background var(--duration-fast)

  &:last-child border-bottom: none
  &:hover background: var(--surface-hover)

  TD:
    font-size: var(--text-sm)
    color: var(--text-primary)
    padding: 0 16px
    vertical-align: middle

TABLE WRAPPER:
  background: var(--surface-raised)
  border: 1px solid var(--border-subtle)
  border-radius: var(--radius-lg)
  overflow: hidden
  box-shadow: var(--shadow-card)

PAGINATION BAR (below table):
  height: 48px
  padding: 0 16px
  border-top: 1px solid var(--border-subtle)
  display: flex, align-items: center, justify-content: space-between
  font-size: var(--text-sm)
  color: var(--text-secondary)

  Left: "Showing 1–25 of 284 results"
  Right: prev/next page buttons + page number pills
```

**Column types:**

```
PLATE NUMBER:
  font-family: var(--font-mono)
  font-size: var(--text-sm)
  font-weight: var(--weight-semibold)
  color: var(--text-primary)
  letter-spacing: 0.08em
  text-transform: uppercase
  background: var(--surface-sunken)
  border: 1px solid var(--border-subtle)
  border-radius: var(--radius-sm)
  padding: 2px 6px

STATUS BADGE:
  height: 22px, border-radius: var(--radius-pill)
  padding: 0 8px
  font-size: var(--text-xs), font-weight: 600
  allowed:  background var(--status-success-dim), color var(--status-success)
  denied:   background var(--status-danger-dim),  color var(--status-danger)
  pending:  background var(--status-warning-dim), color var(--status-warning)
  unknown:  background var(--status-neutral-dim), color var(--status-neutral)

TIMESTAMP:
  font-family: var(--font-mono)
  font-size: var(--text-xs)
  color: var(--text-tertiary)
  white-space: nowrap

CAMERA NAME:
  display: flex, align-items: center, gap: 6px
  dot indicator: 6px circle, color based on camera status
  text: var(--text-sm)

THUMBNAIL:
  width: 64px, height: 40px
  border-radius: var(--radius-sm)
  object-fit: cover
  background: var(--surface-sunken)
  border: 1px solid var(--border-subtle)
  cursor: pointer (opens lightbox)

ROW ACTIONS:
  Visible on row hover only
  position: right column, min-width: 80px
  buttons: IconButton ghost sm
  e.g. [View] [Edit] [Delete]
```

---

### 5.5 Buttons

**Redesign — clean up variant system:**

```css
/* Base */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: var(--radius-md);
  font-family: var(--font-sans);
  font-weight: var(--weight-semibold);
  cursor: pointer;
  border: 1px solid transparent;
  transition: all var(--duration-fast) var(--ease-out);
  white-space: nowrap;
  outline: none;
}

/* Sizes */
.btn-sm  { height: 28px; padding: 0 10px; font-size: var(--text-xs); }
.btn-md  { height: 34px; padding: 0 14px; font-size: var(--text-sm); }
.btn-lg  { height: 40px; padding: 0 18px; font-size: var(--text-base); }

/* Primary */
.btn-primary {
  background: var(--accent-primary);
  color: var(--text-on-accent);
  box-shadow: 0 1px 3px rgba(46,143,255,0.3);
}
.btn-primary:hover  { background: #4a9fff; box-shadow: 0 2px 8px rgba(46,143,255,0.4); }
.btn-primary:active { background: #1a7ee8; transform: translateY(1px); }

/* Secondary */
.btn-secondary {
  background: var(--surface-active);
  color: var(--text-primary);
  border-color: var(--border-default);
}
.btn-secondary:hover { background: var(--surface-hover); border-color: var(--border-strong); }

/* Ghost */
.btn-ghost {
  background: transparent;
  color: var(--text-secondary);
}
.btn-ghost:hover { background: var(--surface-hover); color: var(--text-primary); }

/* Danger */
.btn-danger {
  background: var(--status-danger-dim);
  color: var(--status-danger);
  border-color: rgba(240, 76, 95, 0.25);
}
.btn-danger:hover { background: var(--status-danger); color: white; }

/* Focus state (all variants) */
.btn:focus-visible { box-shadow: var(--shadow-focus); }

/* Disabled */
.btn:disabled { opacity: 0.4; cursor: not-allowed; pointer-events: none; }

/* Loading */
.btn[data-loading] { pointer-events: none; opacity: 0.7; }
/* spinner: 14px white ring, replaces or precedes label */
```

---

### 5.6 Form Inputs

```css
/* Input */
.input {
  height: 34px;
  width: 100%;
  background: var(--surface-sunken);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-size: var(--text-sm);
  padding: 0 12px;
  transition: border-color var(--duration-fast), box-shadow var(--duration-fast);
}

.input::placeholder { color: var(--text-disabled); }

.input:hover  { border-color: var(--border-strong); }

.input:focus  {
  outline: none;
  border-color: var(--border-focus);
  box-shadow: var(--shadow-focus);
}

.input[data-error] {
  border-color: var(--status-danger);
  box-shadow: 0 0 0 3px rgba(240, 76, 95, 0.18);
}

/* FormField wrapper */
.form-field { display: flex; flex-direction: column; gap: 6px; }

.form-label {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-secondary);
}

.form-hint  { font-size: var(--text-xs); color: var(--text-tertiary); }
.form-error { font-size: var(--text-xs); color: var(--status-danger); }
```

---

### 5.7 Modals

```
BACKDROP:
  background: rgba(4, 8, 16, 0.7)
  backdrop-filter: blur(4px)

DIALOG:
  background: var(--surface-overlay)
  border: 1px solid var(--border-default)
  border-radius: var(--radius-xl)
  box-shadow: var(--shadow-lg)
  width: sizes (sm: 400px, md: 560px, lg: 720px, xl: 960px)
  max-height: 88vh, overflow: hidden

HEADER:
  height: 56px
  padding: 0 24px
  border-bottom: 1px solid var(--border-subtle)
  display: flex, align-items: center, justify-content: space-between
  title: text-lg, weight-semibold, text-primary
  close button: IconButton ghost sm (X icon)

BODY:
  padding: 24px
  overflow-y: auto
  flex: 1

FOOTER (optional):
  height: 64px
  padding: 0 24px
  border-top: 1px solid var(--border-subtle)
  display: flex, align-items: center, justify-content: flex-end, gap: 8px
  primary action (right), cancel (left of primary)

ANIMATION:
  enter: scale(0.96) + opacity(0) → scale(1) + opacity(1), 200ms ease-out
  exit:  scale(1) + opacity(1) → scale(0.96) + opacity(0), 150ms ease-in
```

---

### 5.8 Alert / Toast Notifications

```
TOAST CONTAINER:
  position: fixed, bottom: 24px, right: 24px
  z-index: var(--z-toast)
  display: flex, flex-direction: column-reverse, gap: 8px

TOAST:
  width: 360px
  background: var(--surface-overlay)
  border: 1px solid var(--border-default)
  border-radius: var(--radius-lg)
  box-shadow: var(--shadow-lg)
  padding: 12px 14px
  display: flex, gap: 10px

  Left icon: 18px, semantic color
  Body: title (text-sm weight-semibold) + message (text-xs text-secondary)
  Close: top-right, X 14px, ghost

  Left border accent: 3px, semantic color
    success → var(--status-success)
    warning → var(--status-warning)
    error   → var(--status-danger)
    info    → var(--status-info)

ANIMATION:
  enter: translateX(100%) → translateX(0), 300ms ease-out
  exit:  translateX(0) → translateX(110%), 200ms ease-in
  auto-dismiss: 5000ms (errors: no auto-dismiss)
```

---

### 5.9 Status Indicators

#### Camera Status Dot
```
8px circle, border-radius: 50%
live / active:   var(--status-success), box-shadow: 0 0 6px var(--status-success)
warning / stale: var(--status-warning)
offline:         var(--status-neutral)
error:           var(--status-danger), box-shadow: 0 0 6px var(--status-danger)
```

#### System Health Pill (Topbar)
```
height: 24px, border-radius: var(--radius-pill)
padding: 0 10px
font-size: var(--text-xs), font-weight: 600
healthy:   background var(--status-success-dim), color var(--status-success)
degraded:  background var(--status-warning-dim), color var(--status-warning)
outage:    background var(--status-danger-dim),  color var(--status-danger)
dot: 6px, left of text, same color with pulse animation when degraded/outage
```

#### Training Job Status Badge
```
height: 22px, border-radius: var(--radius-pill)
padding: 0 8px, font-size: var(--text-xs), font-weight: 600

running:  var(--accent-primary-dim) / var(--accent-primary), animated left border
queued:   var(--status-warning-dim) / var(--status-warning)
complete: var(--status-success-dim) / var(--status-success)
failed:   var(--status-danger-dim)  / var(--status-danger)
idle:     var(--surface-active)     / var(--text-tertiary)
```

---

## 6. Page-by-Page Redesign

### 6.1 Dashboard

**Layout:**

```
Page Header
  Title: "Operations Overview"
  Subtitle: "Live system status — refreshed every 10s"
  Actions: [Export Report] [Configure Widgets]

Metric Row (4 cols, then 3 cols)
  [Detections 24h] [Active Cameras] [Allowed] [Denied]
  [Unread Alerts] [Models Ready] [Pending Actions]

Content Grid (2-col: 65% / 35%)
  LEFT COLUMN:
    Detection Activity Chart (line, 24h rolling)
      → x-axis: time, y-axis: event count
      → two series: Allowed (success color) / Denied (danger color)
      → hover tooltip: count + breakdown
    
    Recent Detections Table (last 10)
      columns: Plate | Camera | Status | Confidence | Time
      → "View all" link → /detections

  RIGHT COLUMN:
    Camera Status Widget
      → scrollable list, each row: dot + name + status badge + last seen
      → "Manage cameras" link

    Status Distribution Donut
      → Allowed vs Denied vs Unknown
      → center: total count
      → legend: count + percentage per slice

    System Details Panel
      → API version, uptime, model version, last training run
      → monospace values, text-tertiary labels
```

---

### 6.2 Live DVR

**Layout:**

```
Page Header
  Title: "Live Monitor"
  Actions: [Layout: 1×1 | 2×2 | 3×3] [Fullscreen] [Record All]

Camera Grid (configurable: 1/4/9 cameras)
  Camera tile:
    BACKGROUND: #000000
    border-radius: var(--radius-lg)
    overflow: hidden
    aspect-ratio: 16/9
    border: 1px solid var(--border-subtle)
    
    Video stream fills tile
    
    Overlay (bottom gradient, always visible):
      camera name (text-sm, weight-semibold, white)
      status dot + live badge
      recording indicator (red dot + "REC" if recording)
      last detection badge (plate number, pill, top-right corner)
    
    Hover overlay (reveal controls):
      [Fullscreen icon] [Settings icon] [Screenshot icon]

    Error state:
      centered icon (VideoOff) + "Stream unavailable"
      retry button

Event sidebar (right, 280px):
  Header: "Recent Events"
  Scrollable list of detection thumbnails
  Each: thumbnail + plate + camera + time
  Live-updating (auto-scroll to newest)
```

---

### 6.3 Detections

**Layout:**

```
Page Header
  Title: "Detection Events"
  Actions: [Export CSV] [Filter] [Date Range Picker]

Filter Bar (collapsible):
  [Search plate...] [Camera dropdown] [Status dropdown] [Date range] [Clear filters]

Stats Row (3 mini-cards):
  Total in range | Allowed in range | Denied in range

Detections Table:
  Columns: Thumbnail | Plate | Camera | Status | Confidence | Timestamp | Actions
  
  Row actions: [View full image] [Add to allowlist] [Flag]
  
  Bulk actions bar (visible when rows selected):
    "{N} selected" → [Add to allowlist] [Export] [Delete]

Detail Drawer (right side, 400px, slides in):
  Opens on row click
  Shows: full resolution image, plate text, all metadata, detection history for this plate
```

---

### 6.4 Cameras

**Layout:**

```
Page Header
  Title: "Camera Management"
  Actions: [Discover Cameras] [Add Camera]

Camera Grid (3-col cards) or Table view (toggle):

  CARD VIEW:
    Card per camera
    ┌──────────────────────────────┐
    │  [Live thumbnail or preview] │  ← 16:9 aspect
    ├──────────────────────────────┤
    │ ● Camera Name          LIVE  │
    │   rtsp://...                 │
    │   192.168.1.x                │
    ├──────────────────────────────┤
    │ Detections: 142  │ Uptime 99%│
    └──────────────────────────────┘
    Footer actions: [Edit] [View Live] [Delete]

  TABLE VIEW:
    Columns: Status | Name | IP | Port | Protocol | Detector | Last Seen | Actions

Add/Edit Camera Modal (lg):
  Section 1: Basic Info
    Name, IP, Port, Protocol (RTSP/HTTP/ONVIF)
  Section 2: Stream Config
    RTSP URL builder with brand presets (Dahua, Hikvision, Reolink, Axis)
    Manual URL fallback
  Section 3: Behavior
    Detector mode toggle
    Save clips toggle
    Allowed plate filter
  Section 4: Test Connection
    [Test Stream] button → inline result (latency, resolution, codec)
```

---

### 6.5 Training

**Layout:**

```
Page Header
  Title: "Model Training"
  Actions: [Start Training] [View Logs]

2-Column Layout:

LEFT (training config form):
  Section: Model Configuration
    Model architecture selector (dropdown with descriptions)
    Device selector (CPU / CUDA GPU if available)
  
  Section: Training Parameters
    Epochs (number input + slider 1-500)
    Batch size (number input + presets: Small/Medium/Large)
    Learning rate (advanced, collapsible)
  
  Section: Data Configuration
    Plate region selector
    Plate pattern (regex input with examples)
    Validation split slider
  
  Section: Schedule
    Nightly training toggle
    Time picker (HH:MM)
    "Runs every day at" summary text
  
  [Save Configuration] [Start Now]

RIGHT (status panel):
  Active / Last Job Card:
    Status badge + job ID
    Progress bar (if running) with epoch count
    ETA
    Start time / Duration
    Model metrics (mAP, precision, recall)
  
  Training History Table:
    Date | Duration | Epochs | mAP | Status
    Last 10 runs
  
  Log Viewer (collapsible, monospace):
    Last 50 lines of training log
    Auto-scroll toggle
    [Download full log]
```

---

### 6.6 Notifications

**Layout:**

```
Page Header
  Title: "Notifications"
  Subtitle: "{N} unread"
  Actions: [Mark all read] [Settings]

Filter tabs: All | Unread | Alerts | System | Training

Notification List:
  Grouped by date (Today, Yesterday, Earlier)
  
  Each item:
    ┌─────────────────────────────────────────────────┐
    │ [Icon]  Title                          [Time]   │
    │         Description text                        │
    │         [Action button if applicable]  ● unread │
    └─────────────────────────────────────────────────┘
    
    Unread: left border 3px var(--accent-primary), background var(--surface-hover)
    Read: no accent, standard background
    
    Icon semantic color by type:
      Alert    → danger
      Training → secondary
      System   → info
      Success  → success
```

---

### 6.7 Login Page

**Redesigned layout:**

```
Full-screen split layout:

LEFT PANEL (45%):
  background: var(--surface-raised)
  border-right: 1px solid var(--border-subtle)
  
  Centered content (vertical + horizontal):
    BrandLogo (40px height)
    Product name: "CarVision" (text-2xl, weight-bold)
    Tagline: "Intelligent Vehicle Recognition Platform"
    
    Divider
    
    Login form:
      Label: "Sign in to your account"
      Username input (with User icon)
      Password input (with Lock icon + show/hide toggle)
      [Sign In] button (full width, primary, lg)
      
      Error state: Alert (danger) above form
    
    Footer: Version + build ID (text-xs, text-tertiary)

RIGHT PANEL (55%):
  background: var(--surface-base)
  background-image: radial-gradient(ellipse at 30% 60%, var(--accent-primary-dim) 0%, transparent 60%)
  
  Centered: stylized dashboard preview or abstract visualization
    (static SVG of camera grid / detection overlay)
  Caption: key feature highlights (3 bullet points, text-sm)
```

---

## 7. Interaction Patterns

### Loading States

**Skeleton loading** (preferred over spinners for page-level content):
```css
.skeleton {
  background: linear-gradient(
    90deg,
    var(--surface-hover) 25%,
    var(--surface-active) 50%,
    var(--surface-hover) 75%
  );
  background-size: 200% 100%;
  animation: skeleton-sweep 1.5s ease-in-out infinite;
  border-radius: var(--radius-sm);
}

@keyframes skeleton-sweep {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
```

Use skeleton shapes that match real content dimensions:
- Metric card skeleton: two lines (label + number)
- Table skeleton: N rows × M columns of shimmer blocks
- Camera tile skeleton: 16:9 shimmer block

**Spinner** (for inline actions, button loading states):
```
width/height: 14px (sm), 18px (md)
border: 2px solid rgba(255,255,255,0.2)
border-top-color: currentColor
border-radius: 50%
animation: spin 600ms linear infinite
```

---

### Empty States

Every list, table, and grid needs a designed empty state:

```
CONTAINER:
  display: flex, flex-direction: column
  align-items: center, justify-content: center
  padding: 64px 24px
  gap: 12px

ICON:
  48px Lucide icon, color: var(--text-disabled)
  
TITLE:
  text-lg, weight-semibold, text-secondary
  e.g. "No detections yet"

DESCRIPTION:
  text-sm, text-tertiary, max-width: 340px, text-align: center
  e.g. "Detections will appear here when cameras start recognizing plates."

ACTION (optional):
  btn-secondary or btn-primary
  e.g. [Add a Camera] or [Import Dataset]
```

---

### Confirmation Dialogs

Replace browser `confirm()` with a designed modal:

```
MODAL SIZE: sm (380px)
ICON: 40px semantic icon (AlertTriangle for destructive)
TITLE: Concise question ("Delete this camera?")
BODY: One sentence consequence ("This will remove all associated recordings and cannot be undone.")
FOOTER: [Cancel] [Confirm / Delete] (danger variant for destructive)
```

---

### Keyboard Shortcuts

Implement a shortcuts system:

| Shortcut | Action |
|----------|--------|
| `G D` | Go to Dashboard |
| `G L` | Go to Live |
| `G C` | Go to Cameras |
| `G T` | Go to Training |
| `G N` | Go to Notifications |
| `?` | Open keyboard shortcuts panel |
| `Esc` | Close modal / drawer |
| `/` | Focus search / filter input |
| `Cmd+K` | Open command palette |

---

## 8. Accessibility Standards

All redesigned components must meet WCAG 2.1 AA:

- **Contrast:** All text meets 4.5:1 (body) and 3:1 (large/bold) against its background
- **Focus:** Every interactive element has a visible focus ring (`var(--shadow-focus)`)
- **Keyboard:** All interactions reachable without mouse; Tab order follows visual order
- **ARIA:** Proper roles, labels, and live regions on all dynamic content
- **Motion:** Respect `prefers-reduced-motion` — disable animations when set

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## 9. Implementation Roadmap

### Phase 1 — Foundation (1–2 weeks)
1. Create `src/design-system/tokens.css` with all design tokens
2. Migrate `src/styles.css` to use token references instead of hardcoded values
3. Update `Button.jsx` to new variant system
4. Update `Input.jsx`, `Select.jsx`, `Textarea.jsx` to new input spec
5. Update `Modal.jsx` to new spec (header/body/footer structure)
6. Create `Badge.jsx` (status badges — reused everywhere)
7. Create `Skeleton.jsx` (skeleton loading shapes)
8. Create `EmptyState.jsx`
9. Create `Toast.jsx` + `ToastProvider` context

### Phase 2 — Shell (1 week)
1. Redesign `AppShell.jsx` — new sidebar with section groupings
2. Redesign topbar — remove inline metrics, add health pill, user menu
3. Add breadcrumb component
4. Implement sidebar collapse behavior (icon-only at 64px)
5. Add `KeyboardShortcuts.jsx` modal

### Phase 3 — Core Pages (2–3 weeks)
1. Dashboard — new KPI cards, chart panels, recent detections table
2. Cameras — card/table toggle view, redesigned add/edit modal
3. Detections — DataTable component, filter bar, detail drawer
4. Training — split-panel layout, config form, status panel
5. Notifications — grouped list, filter tabs

### Phase 4 — Secondary Pages (1 week)
1. Login — split-screen layout
2. Live DVR — overlay redesign, event sidebar
3. Allowed Plates — DataTable + bulk actions
4. Dataset Import, Upload, Discovery, Clips — apply tokens + DataTable

### Phase 5 — Polish (1 week)
1. Skeleton loading on all data-fetching views
2. Empty states on all lists and tables
3. Toast notification system integration
4. Confirmation dialogs for destructive actions
5. Keyboard shortcuts system
6. Accessibility audit + fixes
7. Responsive breakpoint testing

---

## 10. File Structure Changes

```
src/
├── design-system/
│   ├── tokens.css              ← NEW: all design tokens
│   ├── reset.css               ← NEW: minimal CSS reset
│   └── components/
│       ├── Button.jsx          ← REDESIGN
│       ├── Input.jsx           ← REDESIGN
│       ├── Select.jsx          ← REDESIGN
│       ├── Textarea.jsx        ← REDESIGN
│       ├── Checkbox.jsx        ← REDESIGN
│       ├── FormField.jsx       ← UPDATE
│       ├── FormSection.jsx     ← UPDATE
│       ├── Modal.jsx           ← REDESIGN
│       ├── Alert.jsx           ← REDESIGN
│       ├── FileDropZone.jsx    ← UPDATE
│       ├── Badge.jsx           ← NEW: status/tag badges
│       ├── Skeleton.jsx        ← NEW: loading skeletons
│       ├── EmptyState.jsx      ← NEW: empty state template
│       ├── Toast.jsx           ← NEW: toast notifications
│       ├── DataTable.jsx       ← NEW: universal table
│       ├── IconButton.jsx      ← NEW: icon-only button
│       ├── Drawer.jsx          ← NEW: side drawer panel
│       ├── Tooltip.jsx         ← NEW: hover tooltips
│       ├── Dropdown.jsx        ← NEW: dropdown menus
│       └── CommandPalette.jsx  ← NEW: Cmd+K palette
├── components/
│   ├── AppShell.jsx            ← REDESIGN
│   ├── Topbar.jsx              ← NEW (extracted from AppShell)
│   ├── Sidebar.jsx             ← NEW (extracted from AppShell)
│   ├── Breadcrumb.jsx          ← NEW
│   ├── PageHeader.jsx          ← NEW: page title + actions
│   ├── ProtectedRoute.jsx      ← KEEP
│   ├── BrandLogo.jsx           ← KEEP
│   └── PageState.jsx           ← UPDATE
└── styles.css                  ← SIMPLIFY: import tokens, base only
```

---

## 11. Quick Reference — Design Decisions

| Decision | Rationale |
|----------|-----------|
| Remove glassmorphism from cards | Glassmorphism adds visual noise at enterprise scale; solid surfaces are more readable and professional |
| Sidebar section groups | Groups reduce cognitive load; operators navigate by function area, not alphabetically |
| Monospace for plates/metrics | Plate numbers need fixed-width for scanning; metrics benefit from tabular figures |
| Skeleton over spinner | Skeletons reduce perceived wait time and prevent layout shift |
| Token-based colors | Enables future theme support (light mode, high-contrast, customer branding) |
| Inter as primary font | Industry standard for SaaS/enterprise dashboards; excellent legibility at small sizes; variable font reduces load |
| Remove topbar metrics | System metrics belong on Dashboard, not in the chrome; topbar is navigation, not content |
| DataTable as universal component | Eliminates 6+ different list implementations; one place to fix, one place to improve |
| Drawer for details | Keeps context (list stays visible) without navigating to a new page; faster workflows |
| 36px nav item height | Dense enough for professional tools; spacious enough for easy targeting (Fitts's law) |
