# Frontend End-to-End Verification Checklist

This manual checklist ensures that the frontend integration with Composer and Inventory services for event management works correctly from the user's perspective, avoiding false positives from API-only smoke tests.

## 1. Login as Promoter Works
- **Steps:**
  1. Open the frontend in the browser (`http://localhost:5173` or Traefik domain).
  2. Click "Conta" or "Sign in" to go to the Auth UI.
  3. Register or sign in using an email ending in `@prom.pt` (e.g. `test@prom.pt`).
  4. Once redirected back, ensure the user profile loads successfully via `GET /api/auth/me`.
  5. The "KPIs" and "Create Event" UI sections should now be visible (because the user has the `promoter` role).

## 2. Event Creation via Frontend Works
- **Steps:**
  1. In the "Manage" tab, fill out "Create Event".
  2. Provide Name, Date, Venue, Description.
  3. For "Image URL", either leave blank or paste a valid web image link (e.g., `https://images.unsplash.com/photo-1540039155732-d02ee07e60bf`).
  4. Submit. The frontend sends `POST /api/events` WITH the `Authorization` header.
  5. **Expected:** Success toast message appears, and `managerTargetEventId` updates with the new event UI.

## 3. Event Appears in List
- **Steps:**
  1. Go to the "Eventos" tab.
  2. **Expected:** The newly created event appears in the grid immediately (as `fetchEvents` is called with the auth token, fetching `draft` and `published` if admin) or after being published.

## 4. Featured Hero Image and Fallbacks are Robust
- **Steps:**
  1. Check the very first event (Hero area). It should display the real image provided, or default cleanly to a fallback (like `/images/concert.png`) without leaving a black screen.
  2. For invalid/broken `image_url` strings (like `hello` or a 404 URL), CSS `background-image: url("remote"), url("fallback")` automatically prevents ugly broken icons and guarantees the local fallback displays seamlessly.
