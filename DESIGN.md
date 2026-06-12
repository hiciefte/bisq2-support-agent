---
name: "Bisq 2 Support Agent"
description: "Operator-grade support automation for Bisq 2 with reviewable knowledge and source-backed answers."
colors:
  background: "#ffffff"
  foreground: "#0a0a0a"
  card: "#ffffff"
  card-foreground: "#0a0a0a"
  primary-green: "#25b13c"
  primary-foreground: "#fafafa"
  secondary-green-surface: "#f2f7f3"
  secondary-green-foreground: "#12541c"
  muted-green-surface: "#f3f6f3"
  muted-foreground: "#737373"
  accent-green-surface: "#dceddf"
  accent-green-foreground: "#12541c"
  border-green-gray: "#dee5df"
  destructive-red: "#ef4444"
  bisq-orange: "#f7931a"
  dark-background: "#1a1a1a"
  dark-card: "#242424"
  dark-border: "#383838"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.01em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "0.01em"
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  xl: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary-green}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
    height: "36px"
    typography: "{typography.body}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.muted-foreground}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
    height: "36px"
    typography: "{typography.body}"
  card-default:
    backgroundColor: "{colors.card}"
    textColor: "{colors.card-foreground}"
    rounded: "{rounded.xl}"
    padding: "24px"
  input-default:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    padding: "8px 12px"
    height: "40px"
    typography: "{typography.body}"
  badge-default:
    backgroundColor: "{colors.secondary-green-surface}"
    textColor: "{colors.secondary-green-foreground}"
    rounded: "{rounded.md}"
    padding: "2px 10px"
    typography: "{typography.label}"
---

# Design System: Bisq 2 Support Agent

## 1. Overview

**Creative North Star: "The Operator's Desk"**

The interface should feel like a quiet, well-labeled operations desk for a privacy-sensitive support system. It is not a marketing surface and it is not a playful chatbot shell. It should help a support admin understand what happened, what needs review, what source proves it, and what action is safe.

The visual system is restrained: neutral surfaces, Bisq green for primary action and active selection, orange only for deployment or progress accents, and semantic colors only when state requires them. Admin screens can be dense, but every dense region must have an obvious reading order and a clear primary job.

**Key Characteristics:**

- Review-first: generated answers, sources, diffs, and decisions stay visible in one workflow.
- Calm density: compact enough for support operations, never crowded without hierarchy.
- Source-backed: links, badges, and evidence states are first-class UI elements.
- Familiar product UI: shadcn `new-york`, Radix primitives, Lucide icons, and predictable navigation.
- Privacy-aware: avoid making private support evidence look permanent or public.

## 2. Colors

The palette is a restrained green-neutral system. Bisq green is reserved for primary actions, active navigation, source confidence, and clear positive state. It is not decorative wallpaper.

### Primary

- **Bisq Support Green**: The main action and active-selection color. Use for primary buttons, selected queue tabs, focus rings, active sidebar links, chart primary series, and safe positive state.
- **Primary Foreground**: Text and icon color on green-filled controls.

### Secondary

- **Quiet Green Surface**: Low-emphasis surface for secondary buttons, selected badges, source capsules, and reviewed content that should read as calm rather than urgent.
- **Deep Green Foreground**: Text on quiet green surfaces. Use when a green-tinted surface needs WCAG-safe readability.
- **Bisq Orange**: Deployment progress and top-loader accent only. Do not use it as a general warning color unless the context is explicitly deployment or Bisq brand progress.

### Neutral

- **Paper Background**: Main app background for light mode.
- **Ink Foreground**: Primary text.
- **Card Surface**: Panels, review containers, and admin cards.
- **Muted Green Surface**: Low-emphasis row hovers, secondary blocks, input hover surfaces, and compact preview regions.
- **Muted Foreground**: Secondary labels, timestamps, helper copy, and metadata.
- **Green-Gray Border**: Form borders, card borders, separators, and low-emphasis structure.
- **Dark Graphite Background**: Dark-mode app background.
- **Dark Graphite Card**: Dark-mode elevated surface.
- **Dark Graphite Border**: Dark-mode borders and separators.

### Semantic

- **Destructive Red**: Reject, delete, failure, critical security, and hard validation errors. Do not use red for ordinary review attention.

### Named Rules

**The Green Earns Its Place Rule.** Green means primary action, selected state, or verified positive state. If everything is green, nothing is important.

**The Evidence Is Not Decoration Rule.** Source badges and evidence states use color only to clarify trust and review state, never to create ornamental variety.

## 3. Typography

**Display Font:** System sans stack with platform-native rendering.

**Body Font:** System sans stack with platform-native rendering.

**Label/Mono Font:** Use the system monospace stack only for code, identifiers, hashes, room IDs, API paths, and durable refs.

**Character:** The type system is compact, native, and operational. It favors readable UI density over expressive brand type.

### Hierarchy

- **Display** (700, 1.875rem, 1.2): Admin page titles and major route headings.
- **Headline** (700, 1.5rem, 1.25): Section-level headers, dashboards, and important empty states.
- **Title** (600, 1rem, 1): Card titles, queue item titles, panel titles, and decision labels.
- **Body** (400, 0.875rem, 1.5): Default admin text, chat markdown, descriptions, and review guidance. Keep prose at 65 to 75 characters when it is meant to be read linearly.
- **Label** (600, 0.75rem, 1.25): Badges, metadata, keyboard hints, compact status labels, and table-like values.

### Named Rules

**The Labels Must Explain the Job Rule.** Do not expose pipeline categories such as calibration or knowledge gap without explaining what the support admin should do next.

**The Native Tool Rule.** Product screens use the system sans stack. Do not introduce display fonts into buttons, labels, data, or admin navigation.

## 4. Elevation

Depth is conveyed through tonal layering, borders, and small shadows. Cards and controls may lift slightly, but the system should never look like stacked glass panes. Most surfaces are flat at rest; state changes use background tint, border contrast, focus rings, or a short transition before using stronger elevation.

### Shadow Vocabulary

- **Card Resting Shadow** (`shadow` from Tailwind): Default shadcn card elevation for primary panels.
- **Control Shadow** (`shadow-sm`): Outline and secondary buttons where the control needs separation from the background.
- **Primary Button Shadow** (`shadow`): Filled primary actions only.

### Named Rules

**The Flat Until It Acts Rule.** Resting admin UI is quiet. Hover, focus, active, and selected states may gain emphasis because the user is interacting with them.

**The No Glass Rule.** Do not use decorative blur, translucent panels, or glassmorphism in operator surfaces.

## 5. Components

### Buttons

- **Shape:** Gently curved product controls (6px radius) with compact height (36px default).
- **Primary:** Bisq Support Green fill, Primary Foreground text, medium weight, subtle shadow, 150ms transition, and active scale feedback.
- **Hover / Focus:** Primary hover darkens by opacity. Focus uses the ring token and must remain visible on light and dark backgrounds.
- **Secondary / Ghost:** Secondary uses Quiet Green Surface. Ghost is transparent at rest and uses Accent Green Surface on hover.
- **Destructive:** Destructive Red is reserved for rejection, deletion, and critical failure actions.

### Badges and Chips

- **Style:** Rounded 6px capsules, small label typography, border by default, green fill only for selected or primary meaning.
- **State:** Source badges must be clickable when they represent verifiable evidence. Queue count badges should stay visually secondary unless the tab is selected.
- **Icons:** Use Lucide icons consistently at 16px in compact controls and badges.

### Cards and Containers

- **Corner Style:** 12px card radius for primary panels, 8px for nested compact panels.
- **Background:** Card Surface on Paper Background. Use Muted Green Surface for low-emphasis nested content, previews, and hover rows.
- **Shadow Strategy:** Resting card shadow is allowed on major panels only. Avoid nested card stacks.
- **Border:** Green-Gray Border for structure. Do not use thick colored side borders.
- **Internal Padding:** 24px for full cards, 16px for compact cards, 8px for dense internal rows.

### Inputs and Text Areas

- **Style:** 40px input height, 8px radius, Green-Gray Border, subtle background, muted placeholder text.
- **Focus:** Ring token with 2px ring on primary form controls. Do not remove focus outlines.
- **Error / Disabled:** Error uses Destructive Red with explicit helper text. Disabled uses opacity and cursor state, not color alone.

### Navigation

- **Admin Sidebar:** 256px desktop sidebar with card background and right border. Active items use Bisq Support Green fill and Primary Foreground text. Inactive items use Muted Foreground and hover into Accent Green Surface.
- **Mobile Admin:** Sidebar collapses behind a menu affordance. Page content keeps the same route hierarchy and spacing rhythm.
- **Top Loader:** Bisq Orange top-loader is a deployment and route-progress signal. Keep it thin and spinner-free.

### Queues and Review Lanes

- **Tabs:** Queue tabs are task filters, not decorative cards. The first tab should represent the highest manual-review burden. Labels must be action-oriented and explain what the admin does in that lane.
- **Counts:** High backlog counts are normal during initial bootstrapping, but the UI must explain whether counts are raw candidates, deduplicated knowledge proposals, or reviewed items.
- **Keyboard Footer:** Shortcut hints are compact operator affordances. They should not replace visible buttons for primary actions.

### Source Badges

- **Role:** A source badge is an invitation to verify a claim. It should show compact source count first and reveal details only when needed.
- **Links:** Public FAQs and durable knowledge pages should open as normal links. Private or temporary support evidence must be clearly labeled as private, temporary, or unavailable.
- **Placement:** In review workflows, sources should appear after the proposed document or answer, not before the admin understands what claim is being reviewed.

### Markdown and LLM Wiki Review

- **Diff & Edit:** The LLM Wiki file is the primary object of review. The admin should be able to read the full page, see proposed changes in context, and edit the document without switching mental models.
- **Preview:** Rendered preview exists to catch formatting and readability issues, not to hide the source document.
- **Review Notes:** Review notes are an audit trail for future reviewers. They are not model instructions unless explicitly promoted into a knowledge field.

## 6. Do's and Don'ts

### Do:

- **Do** make the support admin's next action explicit on every queue screen.
- **Do** put source-backed evidence near the claim it verifies, with clickable links when a durable public link exists.
- **Do** preserve the shadcn `new-york` component vocabulary unless there is a concrete usability reason to diverge.
- **Do** use Bisq Support Green for active navigation, selected tabs, primary actions, and verified positive state.
- **Do** keep operator copy concise, factual, and specific about impact.
- **Do** explain initial bootstrap states, high raw candidate counts, and deduplication so admins do not interpret normal backlog as data corruption.
- **Do** keep destructive actions visibly distinct, reversible when possible, and explicit about what data changes.

### Don't:

- **Don't** build generic AI SaaS dashboards with decorative gradients, vague confidence badges, and unclear automation.
- **Don't** use dark neon crypto dashboards, purple default palettes, or glassmorphism used for decoration.
- **Don't** create FAQ sprawl where every support discussion becomes a separate public answer.
- **Don't** hide automation decisions behind labels like "Calibration" or "Knowledge Gap" without explaining the human task.
- **Don't** use dense admin screens that expose internal pipeline terms before explaining the operator's job.
- **Don't** use playful copy in operator surfaces when the task involves security, trust monitoring, support escalation, or production health.
- **Don't** duplicate evidence lists, badges, or source blocks across columns.
- **Don't** use colored side-stripe borders, gradient text, or modal-first workflows.
