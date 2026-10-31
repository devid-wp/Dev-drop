---
name: Dev-Drop
colors:
  surface: '#15121d'
  surface-dim: '#15121d'
  surface-bright: '#3b3744'
  surface-container-lowest: '#0f0d17'
  surface-container-low: '#1d1a25'
  surface-container: '#211e29'
  surface-container-high: '#2c2834'
  surface-container-highest: '#37333f'
  on-surface: '#e7dff0'
  on-surface-variant: '#cbc3d7'
  inverse-surface: '#e7dff0'
  inverse-on-surface: '#322f3b'
  outline: '#958ea0'
  outline-variant: '#494454'
  surface-tint: '#d0bcff'
  primary: '#d0bcff'
  on-primary: '#3b0091'
  primary-container: '#9f78ff'
  on-primary-container: '#340080'
  inverse-primary: '#6d3cd5'
  secondary: '#cdbdff'
  on-secondary: '#352565'
  secondary-container: '#4e3e80'
  on-secondary-container: '#bfaef8'
  tertiary: '#4de082'
  on-tertiary: '#003919'
  tertiary-container: '#00a755'
  on-tertiary-container: '#003115'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e9ddff'
  primary-fixed-dim: '#d0bcff'
  on-primary-fixed: '#23005c'
  on-primary-fixed-variant: '#5419bc'
  secondary-fixed: '#e8deff'
  secondary-fixed-dim: '#cdbdff'
  on-secondary-fixed: '#1f0c50'
  on-secondary-fixed-variant: '#4c3c7d'
  tertiary-fixed: '#6dfe9c'
  tertiary-fixed-dim: '#4de082'
  on-tertiary-fixed: '#00210c'
  on-tertiary-fixed-variant: '#005227'
  background: '#15121d'
  on-background: '#e7dff0'
  surface-variant: '#37333f'
typography:
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 26px
    fontWeight: '700'
    lineHeight: 34px
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 28px
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
  title-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 22px
  title-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  label-lg:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: 0.02em
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.04em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '400'
    lineHeight: 14px
    letterSpacing: 0.06em
rounded:
  sm: 0.5rem
  DEFAULT: 1rem
  md: 1.5rem
  lg: 2rem
  xl: 3rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-tablet: 1.5rem
  margin: 1rem
  margin-tablet: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
---

## Brand & Style

Dev-Drop is an engineering-grade, local-network file transfer application engineered specifically for developers, designers, and power users on Android. The aesthetic bridges high-performance utility with the fluid tactility of Material Design 3.

The visual direction centers on the "Midnight Violet" theme—a deep, luminous atmospheric dark mode reminiscent of modern code editors and low-latency network monitors. The design language avoids hyper-industrial harshness in favor of sculpted geometry: pill-shaped touch targets, pill badges, and layered atmospheric elevations.

Key emotional attributes:
- **Instantaneous & Reliable:** Visual responses communicate deterministic data transfer, peer discovery speeds, and zero-loss throughput.
- **Developer-Centric Focus:** Clean telemetry, explicit byte sizes, SHA checksums, and network topology indicators without unnecessary noise.
- **Deep Immersion:** Rich dark violet foundations layered with ethereal light cones, micro-glows, and tactile, rounded controls.

## Colors

The color system establishes a focused, high-contrast dark mode optimized for OLED displays and long sessions in dim work environments.

- **Background Canvas (`#14111C`):** The foundational substrate across all screens.
- **Surface Level 1 (`#211C2D`):** Primary card bodies, bottom navigation bars, bottom sheets, and grouped lists.
- **Surface Level 2 (`#2B2539`):** Elevated components, dialog modals, floating action bars, and active transfer queues.
- **Primary Accent (`#9568FF`):** Dedicated to high-emphasis actions, active navigation indicators, transfer progress bars, and positive device states.
- **Accent Highlight (`#C6B4FF`):** Used for icons on primary surfaces, focus borders, active chips, and badge text.
- **Text Layers:** Primary typography is rendered in pure clarity (`#F7F5FF`), while meta-labels, secondary details, and disabled states utilize muted violet-grey (`#AAA4BC`).
- **Semantic Feedback:** Transfer success, peer connectivity, and verified state indicators leverage `#4ADE80`. Network dropouts, connection failures, and file rejections map to `#FF6B81`.

## Typography

Typography balances fluid readability with technical precision.

- **Primary UI Type (Plus Jakarta Sans):** Handles headlines, titles, and continuous body text. Its rounded geometry complements the Material 3 corner architecture while maintaining legibility at low contrast.
- **Developer Metas & Data (JetBrains Mono):** Reserved for technical metrics including transfer speeds (`MB/s`), IP addresses, port binds, file hashes, extensions, and raw byte counts.
- **Letter Spacing:** Headlines utilize snug letter-spacing (-0.01em) to anchor scanability, while monospaced labels rely on expanded tracking to facilitate quick parsing of numerical data in active transfer feeds.

## Layout & Spacing

The layout model adapts to standard Android handheld form factors and folding devices through an 8-point baseline grid.

- **Mobile Viewport (up to 599dp):** Single-column layout with 16dp (`1rem`) outer margins. Edge-to-edge content draws behind system bars, padded explicitly at `top` (status bar) and `bottom` (gesture navigation + 80dp bottom navigation bar).
- **Tablet / Foldables (600dp+):** Expands to a multi-pane responsive layout with 32dp (`2rem`) margins and 24dp (`1.5rem`) gutters. The navigation transforms from a bottom bar into a persistent vertical navigation rail on the leading edge.
- **Rhythm & Safe Areas:** Gaps between cards and list items adhere to `space-sm` (8dp) or `space-md` (16dp). Internal component padding maintains strict alignment with touch-target minimums (48dp height for all interactive elements).

## Elevation & Depth

Visual hierarchy is constructed through M3 tonal surfaces augmented by soft violet luminous shadows rather than traditional harsh drop shadows.

- **Level 0 (Canvas):** Pure `#14111C`. Used for raw view backgrounds.
- **Level 1 (Sub-Containers):** `#211C2D` with no drop shadow. Separated from the canvas via clean contrast boundaries.
- **Level 2 (Active Cards & Items):** `#2B2539` paired with an ambient soft violet shadow (`rgba(149, 104, 255, 0.08)`, 16px blur, 4px Y-offset).
- **Level 3 (Modals, Overlays, and Sheets):** `#2B2539` overlaid with an inner border of 1px `rgba(198, 180, 255, 0.12)` and a deep blur shadow (`rgba(0, 0, 0, 0.45)`, 32px blur, 12px Y-offset).
- **Luminous Accent States:** Floating triggers and active transfer nodes emit an intentional radial violet glow (`rgba(149, 104, 255, 0.35)`, 24px spread blur) signifying active local broadcast discovery.

## Shapes

The design system embraces the expressive end of Material Design 3 shape tokens, prioritizing pill contours and exaggerated radii to reinforce touch ergonomics.

- **Pills & Full-Rounds (9999dp):** Action buttons, input search fields, bottom nav active pill pills, filter chips, and peer presence badges.
- **Extra Large Containers (24dp):** Modal dialogs, peer radar radar rings, bottom sheets, and hero cards.
- **Large Components (16dp):** Transfer queue cards, file preview blocks, and setting group containers.
- **Micro Elements (8dp):** Monospaced code snippets, progress meter tracks, and inline telemetry badges.

## Components

### Bottom Navigation Bar
- **Structure:** 80dp tall, anchored to the bottom edge with system navigation bar inset padding. Surface fill: `#211C2D`.
- **Destinations:** 4 destinations: Nearby, Send, Transfers, Settings.
- **Active State:** Material 3 pill pill (64x32dp) wrapped in `#9568FF` fill with `#14111C` icon tint. Inactive icons render in `#AAA4BC`.
- **Top Border:** 1px hairline border in `rgba(198, 180, 255, 0.08)`.

### Buttons
- **Primary FAB / Action:** Full-pill shape (minimum 48dp height), `#9568FF` background, `#F7F5FF` bold typography. Active state adds an ambient violet glow.
- **Tonal / Secondary:** Pill shape, `#2B2539` container with `#C6B4FF` text.
- **Outlined / Ghost:** Transparent background, 1px border `rgba(198, 180, 255, 0.24)`, `#F7F5FF` text.

### Chips & Peer Badges
- **Device Filter Chips:** Height 32dp, 16dp rounded radius. Inactive: `#211C2D` with `#AAA4BC` text. Active: `#9568FF` with `#F7F5FF` text and checkmark icon.
- **Technical Status Badges:** Rendered with `JetBrains Mono` (`label-sm`). Elevated on `#14111C` nested containers with status-colored indicator dots (`#4ADE80` for connected, `#FF6B81` for stalled).

### Cards & Transfer Queue Items
- **Card Base:** 16dp rounded corners, `#211C2D` surface.
- **Transfer Progress:** Nested inside the card using an 8dp pill-shaped progress track (`#14111C`) with an animated gradient bar (`#9568FF` to `#C6B4FF`).
- **Telemetry Display:** Two-column metadata grid showing transfer rate, estimated time remaining, and SHA-256 chunk verification status.

### Input Fields & Search
- **Container:** Full pill (56dp height), `#211C2D` fill, inset 16dp from sides.
- **Borders:** Borderless in rest state; 1.5px `#9568FF` border with a subtle focus glow when engaged.
- **Placeholder & Text:** Placeholder in `#AAA4BC`; active input in `#F7F5FF`.

### Lists & Dividers
- Lists utilize grouped-card containers with 16dp padding. Row items are separated by full-bleed spacing rather than high-contrast lines; dividers where necessary use 1px `rgba(255, 255, 255, 0.04)`.

### Radar / Peer Discovery Component
- Concentric pulse circles centered around the local avatar. Rings use `#9568FF` at 15%, 10%, and 5% opacity, expanding infinitely until peers are resolved. Discovered peers appear as 56dp circular avatar nodes with `#C6B4FF` outer rims.