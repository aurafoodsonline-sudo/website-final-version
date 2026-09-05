# AuraFoods ERP Frontend Design System

Source: UI UX Pro Max skill query `inventory purchase ERP operations dashboard B2B admin --design-system`.

## Four-Domain UI Evidence

The installed UI/UX Pro Max skill was actively applied and its updated ERP design system persisted at `design-system/aurafoods-erp/MASTER.md`. Supplier Rate Agreements, Daily/Shift Production Logs, Customer/Distributor Master, and Scheduled Maintenance use business-readable selectors, responsive compact forms/tables, tabular numeric alignment, status text/badges, permission-aware controls, empty states, loading feedback, API errors, and confirmations for approval, locking, blocking, and manual job execution.

File evidence: `frontend/views.py`, `frontend/templates/frontend/app.html`, `frontend/static/frontend/app.css`, and `frontend/static/frontend/app.js`.

The strict compliance repair pass additionally added supplier draft editing and filters, production date/shift/operator/order filters, customer search/detail/edit workflows, permission-gated financial and inventory dashboard data, modal focus restoration, and CSP-safe external JavaScript. These behaviors are covered in `frontend/test_new_domains.py`.

## Pattern

Real-time operations dashboard for a data-dense ERP. Primary goal is operational control, reconciliation, and posting confidence rather than marketing.

## Style

Data-Dense Dashboard:

- Multiple KPI widgets, compact tables, workflow panels, and status views.
- Minimal but readable padding.
- Maximum data visibility without cramping form controls.
- Light mode first, dark-mode ready through tokens.
- Accessibility target: WCAG AA.

## Tokens

```css
--color-primary: #0F172A;
--color-on-primary: #FFFFFF;
--color-secondary: #334155;
--color-accent: #0369A1;
--color-background: #F8FAFC;
--color-foreground: #020617;
--color-muted: #E8ECF1;
--color-border: #E2E8F0;
--color-destructive: #DC2626;
--color-ring: #0F172A;
```

Typography:

- Heading and body: locally available Inter, then a CSP-safe Segoe UI/system sans stack with no third-party font dependency.
- Use tabular figures for stock, money, and report columns.

## Frontend Rules

- No emoji structural icons.
- Buttons and links have visible focus states.
- Interactive targets are at least 44px tall where practical.
- Errors appear near the relevant form or action.
- Tables must be horizontally resilient and readable at 375px.
- Motion must respect `prefers-reduced-motion`.
- Use semantic status labels, not color alone.
- No frontend action may bypass backend validation.
