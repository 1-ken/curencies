# Finance Observer - Modern UI Development Prompt

## Project Overview
Build a modern, fully-featured web UI for **Finance Observer**, a real-time forex currency pair price monitoring system with intelligent price alert management. The application tracks live forex prices, manages price-based alerts, and delivers notifications via email, SMS, or voice calls.

## API Endpoints Reference

### Alert Management Endpoints
1. **GET /api/v1/alerts**
   - Retrieves all alerts with categorization
   - Response: `{ "total": number, "active": Alert[], "triggered": Alert[], "all": Alert[] }`
   - Use case: Display alert dashboard/list

2. **GET /api/v1/alerts/{alert_id}**
   - Retrieves a specific alert by ID
   - Response: Full alert object with all details
   - Use case: Alert detail view

3. **POST /api/v1/alerts**
   - Creates a new price alert
   - Body: `{ "pair": string, "target_price": number, "condition": "above"|"below"|"equal", "channel": "email"|"sms"|"call", "email": string, "phone": string, "custom_message": string }`
   - Response: `{ "success": true, "alert": AlertObject }`
   - Validation: Condition must be one of three values; channel determines required contact field
   - Use case: Create new alert form

4. **DELETE /api/v1/alerts/{alert_id}**
   - Deletes an alert
   - Response: `{ "success": true, "message": "Alert deleted" }`
   - Use case: Alert removal action

### Data Streaming Endpoints

5. **GET /snapshot**
   - Single forex market snapshot
   - Response: `{ "market_status": "open"|"closed", "pairs": [{ "pair": string, "bid": number, "ask": number, "spread": number }], "ts": ISO8601 timestamp }`
   - Use case: Initial data load, manual refresh

6. **WebSocket /ws/observe**
   - Real-time streaming of forex data
   - Message structure: Same as /snapshot plus `"alerts": { "active": Alert[], "triggered": Alert[] }`
   - Frequency: Configurable (typically 1-5 second intervals)
   - Use case: Live price updates, real-time dashboard
   - Market-Hours-aware: Only streams when forex market is open (Sunday 22:00 UTC - Friday 22:00 UTC)

7. **GET /stream-health**
   - Stream health/status monitoring
   - Response: `{ "status": "healthy"|"degraded"|"stale", "stream_interval_seconds": number, "snapshot_timeout_seconds": number, "max_snapshot_failures": number, "consecutive_snapshot_failures": number, "last_snapshot_ts": ISO8601, "last_snapshot_age_seconds": number, "subscriber_count": number }`
   - Use case: System status indicator, debug information

8. **GET /client-config**
   - Client runtime configuration
   - Response: `{ "wsUrl": string }` (WebSocket URL override for proxy scenarios)
   - Use case: Dynamic WebSocket URL configuration

## Alert Data Model
```javascript
{
  "id": "uuid-string",
  "pair": "EURUSD",  // e.g., EURUSD, GBPUSD, etc.
  "target_price": 1.0850,
  "condition": "above|below|equal",
  "status": "active|triggered|disabled",
  "channel": "email|sms|call",
  "email": "user@example.com",  // Required if channel='email'
  "phone": "+1234567890",  // Required if channel='sms' or 'call'
  "custom_message": "String up to 255 chars",
  "created_at": "ISO8601 timestamp",
  "triggered_at": "ISO8601 timestamp or null",
  "last_checked_price": 1.0872  // Current price when last checked
}
```

## Forex Pair Data Model
```javascript
{
  "pair": "EURUSD",
  "bid": 1.08450,  // Buy price
  "ask": 1.08475,  // Sell price
  "spread": 0.00025  // Ask - Bid difference
}
```

## UI Requirements

### Core Sections

#### 1. **Dashboard / Real-time Monitor** (Primary View)
- Live price ticker/grid showing all major forex pairs (EUR, USD, JPY, GBP, AUD, CAD, CHF, NZD)
- Real-time updates via WebSocket
- Price change indicators (↑ green for increases, ↓ red for decreases)
- Visual pulse/animation on price changes
- Market status badge (🟢 Open / 🔴 Closed)
- Time until next market open when closed
- Bid/Ask/Spread display for each pair
- Quick-action alert creation buttons per pair
- Search/filter functionality for pairs

#### 2. **Alerts Management**
- **Alerts List View:**
  - Tabbed interface: "Active" | "Triggered" | "All"
  - Card/table layout showing:
    - Pair name
    - Target price
    - Condition (above/below/equal)
    - Current price vs target
    - Alert status indicator
    - Channel icons (📧 email, 📱 SMS, ☎️ call)
    - Created date
    - Triggered date (if applicable)
    - Action buttons (View Details, Edit*, Delete)
  - Sort options: by pair, by target price, by creation date, by status
  - Filter: by channel type, by status, by price range
  - Bulk delete functionality

- **Create/Edit Alert Modal:**
  - Pair selector (searchable dropdown)
  - Target price input (with decimal precision)
  - Condition selector (radio buttons: Above / Below / Equal To)
  - Notification channel selector (Email / SMS / Call)
  - Dynamic fields based on channel selection:
    - Email: Email input with validation
    - SMS/Call: Phone number input with validation
  - Custom message field (optional, 255 char limit)
  - Form validation with inline error messages
  - Submission button with loading state
  - Success/error toast notifications

- **Alert Detail View:**
  - Full alert information
  - Price comparison chart (target vs current)
  - Status history timeline (created → triggered → disabled)
  - Last check time
  - Retry notification button (if triggered)
  - Delete confirmation dialog

#### 3. **System Status & Health**
- Stream health indicator in header/footer
- Live subscriber count
- Last snapshot time
- Consecutive failures counter
- Status colors: Green (healthy) → Yellow (degraded) → Red (stale)
- Clickable status panel for detailed health information
- Auto-refresh health data every 30 seconds

#### 4. **Header/Navigation**
- App logo/title: "Finance Observer"
- Theme toggle (Light/Dark mode button)
- Market status indicator with countdown timer
- Health status indicator (clickable for details)
- Navigation menu: Dashboard | Alerts | Settings
- User feedback section (toast notifications for all CRUD operations)

#### 5. **Settings (Optional but Recommended)**
- Theme preference (Light / Dark / Auto)
- Default alert channel preference
- Price update frequency display
- WebSocket connection status
- Data export (JSON/CSV)
- About/Help section

### Design & UX Requirements

#### Visual Design
- **Modern, professional aesthetic** with clean spacing and typography
- **Color palette:**
  - Light mode: White backgrounds, dark text, accent colors (blue/green for actions, red for alerts)
  - Dark mode: Dark grey/charcoal backgrounds, light text, proper contrast ratios
  - Alert states: Green (above threshold), Red (danger/triggered), Yellow (warning), Blue (info)
- **Component library ready:** Use consistent button styles, input fields, cards, badges, modals
- **Icons:** Use consistent icon set (SVG recommended) for channels, status, actions
- **Typography:** Clear hierarchy with appropriate font sizes and weights
- **Spacing:** Consistent padding/margins following 8px or similar grid system

#### Responsiveness
- Desktop-first design
- Responsive breakpoints: Desktop (1440px+) → Laptop (1024px-1439px) → Tablet (768px-1023px) → Mobile (< 768px)
- Mobile-optimized:
  - Stack layouts vertically on small screens
  - Floating action buttons for primary actions
  - Collapsible menus
  - Readable touch targets (min 44px)

#### Light & Dark Mode
- **Toggle:** Button in header to switch modes immediately
- **Persistence:** Save user preference to localStorage
- **CSS Variables or Tailwind:** Use CSS custom properties for theme colors
- **Contrast:** Maintain WCAG AA contrast ratios in both modes
- **Status indicators:** Adapt colors for accessibility (not color-only distinction)
- **Charts/visualizations:** Adjust for dark background (if any charts are used)

#### Accessibility
- Semantic HTML (`<button>`, `<form>`, `<table>`, etc.)
- Proper `aria-labels` and `aria-describedby` attributes
- Keyboard navigation support (Tab, Enter, Escape)
- Focus indicators visible in both themes
- Screen reader friendly content
- Form labels properly associated with inputs

#### Performance & UX
- Lazy load alerts (pagination or virtual scrolling for large lists)
- Debounce search/filter inputs (300ms)
- Optimistic UI updates for alert creation/deletion (update immediately, confirm with server)
- Error boundaries and graceful fallbacks
- Loading skeletons for list items during WebSocket reconnection
- Retry logic with exponential backoff for WebSocket
- Toast notifications with auto-dismiss (5 seconds) for feedback
- Prevent duplicate submissions with loading states

### Real-time Streaming Behavior
- WebSocket automatic reconnection with exponential backoff (1s, 2s, 4s, 8s max)
- Graceful degradation: If WebSocket fails, fallback to polling /snapshot every 5 seconds
- Display connection status: "Live" (green dot) / "Reconnecting" (yellow spinner) / "Offline" (red)
- Queue data during reconnection, apply updates when connection restored
- Show "last updated X seconds ago" when offline

### Form Validation
- **Client-side validation:**
  - Pair: Required, must be valid forex pair code (3-4 uppercase letters pattern)
  - Target price: Required, must be positive number, max 2 decimal places
  - Condition: Required, must be one of three options
  - Channel: Required, must be one of three options
  - Email: Required if channel='email', must be valid email format
  - Phone: Required if channel='sms' or 'call', must be valid phone (international format recommended)
  - Custom message: Optional, max 255 characters
- **Error messages:** Clear, specific, and actionable
- **Server-side errors:** Display in toast with retry option

### Key Interactions
1. **Price ticker updates:** Smooth animations on value changes, highlighting for emphasis
2. **Create alert:** Click price → autofill pair → open modal → fill details → submit
3. **Manage alerts:** View list → filter/sort → click for details → edit/delete with confirmation
4. **Market closed:** Show countdown timer to market open, disable new alert creation with explanation
5. **Alert triggered:** Highlight in list, show visual indication, prevent deletion until resolved
6. **Connection loss:** Show banner, attempt auto-reconnect, allow manual refresh

## Technical Stack Recommendations
- **Framework:** React, Vue 3, or Svelte (modern, component-based)
- **State Management:** React Context/useReducer, Pinia (Vue), or simple hooks
- **WebSocket:** ws library or built-in WebSocket API with reconnection logic
- **Styling:** Tailwind CSS (for light/dark mode support) or CSS-in-JS (styled-components)
- **UI Component Library:** HeadlessUI, Shadcn/ui, Radix UI, or similar (accessibility-focused)
- **Forms:** React Hook Form or VeeValidate (lightweight, performant)
- **HTTP Client:** Fetch API or axios
- **Icons:** Heroicons, Feather Icons, or SVG
- **Charts (Optional):** Recharts or Chart.js for price history visualization

## Acceptance Criteria
✅ All 8 API endpoints are fully integrated and functional
✅ Real-time WebSocket streaming displays live price updates (sub-second latency visible)
✅ Create/read/update/delete operations for alerts work seamlessly
✅ Light and dark mode toggle works perfectly with persistent preference
✅ Responsive design works flawlessly on mobile, tablet, and desktop
✅ All form validations are in place and user-friendly
✅ WebSocket reconnection handles gracefully
✅ Market status (open/closed) is prominently displayed and accurate
✅ No console errors or warnings
✅ Accessibility standards met (keyboard navigation, screen reader compatible)
✅ Toast notifications provide clear feedback for all user actions
✅ Performance: WebSocket updates render within 100ms

## Notes
- The API respects **forex market hours (24/5)**: Data only streams Sunday 22:00 UTC - Friday 22:00 UTC
- When market is closed, the WebSocket still connects but may not receive frequent updates
- Alert triggers only check prices when market is open
- Consider showing "Market Closed" state with countdown to next open time for better UX
- The WS_URL can be overridden via /client-config endpoint for proxy scenarios
- Assume base API URL is the same domain/port as the UI (or configurable via environment)
