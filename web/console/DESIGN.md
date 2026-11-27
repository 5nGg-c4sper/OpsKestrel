# OpsKestrel Console 2.0 Design System

## Visual reference

The existing product screenshots in `docs/assets/console.jpg`,
`docs/assets/erp-login.jpg`, and `docs/assets/invoice-report.jpg` are the
visual source of truth. The Console keeps the existing cool-white product
surface, cobalt action color, green success language, and navy operations
chrome.

## Direction

- Theme: a calm operations cockpit rather than a generic analytics dashboard.
- Background: true cool white `#f3f6fa` for the workspace.
- Chrome: deep navy `#0b1220` sidebar with restrained blue highlights.
- Surfaces: white with cool slate borders and soft, low-elevation shadows.
- Accent: cobalt `#2f74ff`; success `#138a5b`; warning `#b66a00`;
  danger `#c73e3a`.
- Type: Manrope for product UI and JetBrains Mono for logs and IDs.
- Radius: 18px for primary surfaces, 12px for controls, 999px only for
  status marks.
- Motion: short opacity/translate transitions for view changes and live
  status pulses. Reduced-motion preferences disable animation.

## App shell

- Fixed navy rail on desktop with brand, four workflow destinations, worker
  summary, and session state.
- Main workspace uses a compact header and open page canvas.
- Mobile collapses navigation into a horizontal top rail without hiding
  primary actions.

## Screens

### Overview

- Page title and one primary action.
- Four compact operational metrics.
- Current-run command surface with live state and direct actions.
- Workers and review work in a two-column operations grid.
- Recent runs and reports use tables, not repetitive card grids.

### New run

- Two run modes: built-in invoice demo and uploaded input.
- Built-in mode explains the reference scenario and safety boundary.
- Upload mode uses a focused drop zone and file constraints.

### Run detail

- Run identity, elapsed time, state, and actions in one header.
- Live log and evidence artifacts share the main canvas.
- Reconciliation summary and run timeline use open lists and tables.

### Reviews

- Operator authentication is a first-class state.
- Review runs and counts remain visible above the table.
- Differences use dense rows with inline status and notes.
- Audit history is a chronological rail below the review table.

## Component families

- `Button`: primary, secondary, quiet, danger.
- `StatusBadge`: running, passed, failed, cancelled, pending, confirmed,
  false-positive.
- `Surface`: one level of bordered white panels.
- `DataTable`: responsive horizontal scroll on narrow screens.
- `Field`: explicit label and helper text.
- `Alert`: information, warning, success.
- `EmptyState`: concise text plus a relevant action.

## Copy lock

Primary navigation: Overview, New run, Run monitor, Reviews.

Primary actions: New run, Run invoice demo, Upload and run, Stop run,
Create evidence bundle, Connect operator, Save review, Save selected,
Close review.
