import React, { useEffect, useState } from 'react';
import axios from 'axios';
import './App.css';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const AUTH_UI_BASE_URL = import.meta.env.VITE_AUTH_UI_BASE_URL || 'http://localhost:5500';
const AUTH_UI_LOGIN_PATH = import.meta.env.VITE_AUTH_UI_LOGIN_PATH || '/templates/login.html';
const AUTH_UI_REGISTER_PATH = import.meta.env.VITE_AUTH_UI_REGISTER_PATH || '/templates/register.html';
const AUTH_UI_FORGOT_PATH = import.meta.env.VITE_AUTH_UI_FORGOT_PATH || '/templates/forgot_password.html';
const PAYMENT_UI_BASE_URL = import.meta.env.VITE_PAYMENT_UI_BASE_URL || 'http://localhost:8002';
const PAYMENT_UI_LOGIN_PATH = import.meta.env.VITE_PAYMENT_UI_LOGIN_PATH || '/wallet/login';
const PAYMENT_UI_REGISTER_PATH = import.meta.env.VITE_PAYMENT_UI_REGISTER_PATH || '/wallet/register';
const PAYMENT_UI_DASHBOARD_PATH = import.meta.env.VITE_PAYMENT_UI_DASHBOARD_PATH || '/wallet/dashboard';
const AUTH_STATE_STORAGE_KEY = 'flashsale_auth_state';
const REFRESH_TOKEN_STORAGE_KEY = 'flashsale_refresh_token';
const AUTH_EXCHANGE_PROMISE_KEY = '__flashsaleAuthExchangePromise';

const buildAuthUiUrl = (path, query = {}) => {
  const url = new URL(path, AUTH_UI_BASE_URL);
  Object.entries(query).forEach(([key, value]) => {
    if (value) {
      url.searchParams.set(key, value);
    }
  });
  return url.toString();
};

const buildPaymentUiUrl = (path) => new URL(path, PAYMENT_UI_BASE_URL).toString();

const buildApiUrl = (path) => new URL(path, API_BASE_URL || window.location.origin).toString();

const createAuthState = () => {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

const getPendingAuthStates = () => {
  const raw = localStorage.getItem(AUTH_STATE_STORAGE_KEY);
  if (!raw) return [];

  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed.map((item) => String(item || '').trim()).filter(Boolean);
    }
  } catch (_error) {
    // Legacy format used a single raw state string.
  }

  const legacy = String(raw).trim();
  return legacy ? [legacy] : [];
};

const savePendingAuthStates = (states) => {
  if (!states.length) {
    localStorage.removeItem(AUTH_STATE_STORAGE_KEY);
    return;
  }
  localStorage.setItem(AUTH_STATE_STORAGE_KEY, JSON.stringify(states));
};

const addPendingAuthState = (state) => {
  const normalized = String(state || '').trim();
  if (!normalized) return;
  const current = getPendingAuthStates();
  const next = [...current.filter((item) => item !== normalized), normalized].slice(-10);
  savePendingAuthStates(next);
};

const hasPendingAuthState = (state) => {
  const normalized = String(state || '').trim();
  if (!normalized) return false;
  return getPendingAuthStates().includes(normalized);
};

const consumePendingAuthState = (state) => {
  const normalized = String(state || '').trim();
  if (!normalized) return;
  const remaining = getPendingAuthStates().filter((item) => item !== normalized);
  savePendingAuthStates(remaining);
};

const clearPendingAuthStates = () => {
  localStorage.removeItem(AUTH_STATE_STORAGE_KEY);
};

const getOrCreateAuthExchangePromise = (code, state) => {
  const existing = window[AUTH_EXCHANGE_PROMISE_KEY];
  if (existing?.code === code && existing?.state === state && existing?.promise) {
    return existing.promise;
  }

  const promise = axios.post(`${API_BASE_URL}/api/auth/browser/exchange`, { code, state });
  window[AUTH_EXCHANGE_PROMISE_KEY] = { code, state, promise };
  return promise;
};

const extractErrorMessage = (error, fallback = 'Request failed') => {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((item) => item?.msg || JSON.stringify(item)).join('; ');
  if (detail && typeof detail === 'object') {
    return detail.detail || detail.message || JSON.stringify(detail);
  }
  return error?.message || fallback;
};

const extractErrorDetailObject = (error) => {
  const detail = error?.response?.data?.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    return detail;
  }
  return null;
};

function App() {
  const [events, setEvents] = useState([]);
  const [loadingEvents, setLoadingEvents] = useState(true);
  const [token, setToken] = useState(localStorage.getItem('flashsale_token'));
  const [user, setUser] = useState(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState('');
  const [authError, setAuthError] = useState('');
  const [flowInfo, setFlowInfo] = useState('');
  const [walletActionUrl, setWalletActionUrl] = useState('');
  const [eventsError, setEventsError] = useState('');
  const [activeTab, setActiveTab] = useState('overview');
  const [toast, setToast] = useState(null);
  const [checkoutLoadingEventId, setCheckoutLoadingEventId] = useState('');
  const [quantityByEvent, setQuantityByEvent] = useState({});
  const [authRedirectLoading, setAuthRedirectLoading] = useState(false);

  const [reservationEventId, setReservationEventId] = useState('');
  const [reservationQty, setReservationQty] = useState(1);
  const [reservationResult, setReservationResult] = useState(null);
  const [reservationStatusTicketId, setReservationStatusTicketId] = useState('');
  const [reservationStatusResult, setReservationStatusResult] = useState(null);

  const [payments, setPayments] = useState([]);
  const [paymentsLoading, setPaymentsLoading] = useState(false);
  const [paymentsError, setPaymentsError] = useState('');
  const [paymentAccount, setPaymentAccount] = useState(null);
  const [paymentAccountLoading, setPaymentAccountLoading] = useState(false);
  const [paymentAccountSetupLoading, setPaymentAccountSetupLoading] = useState(false);
  const [paymentAccountError, setPaymentAccountError] = useState('');

  const [refundPaymentId, setRefundPaymentId] = useState('');
  const [refundTicketIds, setRefundTicketIds] = useState('');
  const [refundResult, setRefundResult] = useState(null);
  const [refundError, setRefundError] = useState('');
  const [managerEventName, setManagerEventName] = useState('');
  const [managerEventDate, setManagerEventDate] = useState('');
  const [managerEventVenue, setManagerEventVenue] = useState('');
  const [managerEventDescription, setManagerEventDescription] = useState('');
  const [managerTargetEventId, setManagerTargetEventId] = useState('');
  const [managerTargetEventStatus, setManagerTargetEventStatus] = useState('published');
  const [managerBatchEventId, setManagerBatchEventId] = useState('');
  const [managerBatchCategory, setManagerBatchCategory] = useState('General');
  const [managerBatchPrice, setManagerBatchPrice] = useState('15.00');
  const [managerBatchQuantity, setManagerBatchQuantity] = useState('50');
  const [managerTicketId, setManagerTicketId] = useState('');
  const [managerError, setManagerError] = useState('');
  const [managerLoading, setManagerLoading] = useState(false);

  const isPrivilegedUser = ['admin', 'promoter'].includes(String(user?.role || '').toLowerCase());

  useEffect(() => {
    fetchEvents();
  }, []);

  useEffect(() => {
    localStorage.setItem('flashsale_token', token || '');
    if (!token) {
      localStorage.removeItem('flashsale_token');
      setUser(null);
      setWalletActionUrl('');
      setPaymentAccount(null);
      setPaymentAccountError('');
      return;
    }
    fetchProfile(token);
    fetchPayments(token);
    fetchPaymentAccount(token);
  }, [token]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('auth_callback') !== '1') return;

    const code = params.get('code');
    const state = params.get('state');
    const cleanUrl = `${window.location.origin}${window.location.pathname}`;
    const hasMatchingState = hasPendingAuthState(state);

    if (!code || !state || !hasMatchingState) {
      setAuthError('Secure login callback failed: invalid or missing state.');
      window.history.replaceState({}, document.title, cleanUrl);
      return;
    }

    let cancelled = false;

    const completeHandoff = async () => {
      setAuthRedirectLoading(true);
      setFlowInfo('Finalizing secure sign-in...');
      setAuthError('');

      try {
        const res = await getOrCreateAuthExchangePromise(code, state);
        if (cancelled) return;

        if (res.data?.refresh_token) {
          localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, res.data.refresh_token);
        } else {
          localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
        }

        consumePendingAuthState(state);
        setUser(res.data?.user || null);
        setToken(res.data?.access_token || '');
        setToast({ type: 'success', text: 'Signed in via Auth UI.' });
      } catch (error) {
        if (cancelled) return;
        consumePendingAuthState(state);
        localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
        setAuthError('Secure login callback failed: ' + extractErrorMessage(error, 'Could not finish sign-in.'));
      } finally {
        if (cancelled) return;
        setAuthRedirectLoading(false);
        setFlowInfo('');
        window.history.replaceState({}, document.title, cleanUrl);
      }
    };

    completeHandoff();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 3600);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const status = params.get('status');

    if (!status) return;

    if (status === 'success') {
      setFlowInfo('Checkout completed. Refreshing your payments history.');
      setToast({ type: 'success', text: 'Payment completed successfully.' });
      if (token) fetchPayments(token);
    } else if (status === 'cancel') {
      setFlowInfo('Checkout was canceled.');
      setToast({ type: 'warning', text: 'Checkout canceled. No payment was captured.' });
    }

    const cleanUrl = `${window.location.origin}${window.location.pathname}`;
    window.history.replaceState({}, document.title, cleanUrl);
  }, [token]);

  const fetchEvents = () => {
    setLoadingEvents(true);
    setEventsError('');
    axios.get(`${API_BASE_URL}/api/events`)
      .then((res) => {
        setEvents(res.data?.data || []);
        setLoadingEvents(false);
      })
      .catch((err) => {
        console.error('Error fetching events:', err);
        setEventsError('Could not load events: ' + extractErrorMessage(err, 'Could not load events'));
        setLoadingEvents(false);
      });
  };

  const fetchProfile = async (activeToken) => {
    setProfileLoading(true);
    setProfileError('');
    try {
      const config = { headers: { Authorization: `Bearer ${activeToken}` } };
      const res = await axios.get(`${API_BASE_URL}/api/auth/me`, config);
      setUser(res.data || null);
    } catch (error) {
      setUser(null);
      const statusCode = error?.response?.status;
      if (statusCode === 401 || statusCode === 403) {
        localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
        setToken(null);
        setAuthError('Session expired. Please login again.');
      }
      setProfileError(extractErrorMessage(error, 'Could not load profile'));
    } finally {
      setProfileLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      if (token) {
        await axios.post(
          `${API_BASE_URL}/api/auth/logout`,
          {},
          { headers: { Authorization: `Bearer ${token}` } }
        );
      }
    } catch (_error) {
      // Ignore logout errors and clear local state anyway.
    } finally {
      localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
      clearPendingAuthStates();
      setToken(null);
      setUser(null);
      setPayments([]);
      setPaymentAccount(null);
      setPaymentAccountError('');
      setReservationResult(null);
      setReservationStatusResult(null);
      setRefundResult(null);
      setRefundError('');
      setActiveTab('overview');
      setToast({ type: 'info', text: 'Session closed.' });
    }
  };

  const fetchPayments = async (activeToken = token) => {
    if (!activeToken) return;
    setPaymentsLoading(true);
    setPaymentsError('');
    try {
      const res = await axios.get(`${API_BASE_URL}/api/payments`, {
        headers: { Authorization: `Bearer ${activeToken}` },
      });
      setPayments(res.data?.items || []);
    } catch (error) {
      setPaymentsError('Could not load payments: ' + extractErrorMessage(error, 'Could not load payments'));
    } finally {
      setPaymentsLoading(false);
    }
  };

  const fetchPaymentAccount = async (activeToken = token) => {
    if (!activeToken) return;
    setPaymentAccountLoading(true);
    setPaymentAccountError('');
    try {
      const res = await axios.get(`${API_BASE_URL}/api/payment-account`, {
        headers: { Authorization: `Bearer ${activeToken}` },
      });
      setPaymentAccount(res.data || null);
      if (res.data?.exists) {
        setWalletActionUrl(buildPaymentUiUrl(PAYMENT_UI_DASHBOARD_PATH));
      } else {
        setWalletActionUrl(buildPaymentUiUrl(PAYMENT_UI_REGISTER_PATH));
      }
    } catch (error) {
      setPaymentAccount(null);
      setPaymentAccountError(extractErrorMessage(error, 'Could not load payment account status'));
    } finally {
      setPaymentAccountLoading(false);
    }
  };

  const setupPaymentAccount = async () => {
    if (!token) {
      setAuthError('Please sign in before creating a Payment account.');
      return;
    }

    const registerUrl = buildPaymentUiUrl(PAYMENT_UI_REGISTER_PATH);
    setWalletActionUrl(registerUrl);
    setFlowInfo('Redirecting to Payment register page...');
    window.location.href = registerUrl;
  };

  const reserveTickets = async () => {
    if (!reservationEventId) {
      setAuthError('Select an event to reserve tickets.');
      return;
    }
    try {
      const res = await axios.post(`${API_BASE_URL}/api/reservations`, {
        event_id: reservationEventId,
        quantity: Number(reservationQty) || 1,
      });
      setReservationResult(res.data);
      setReservationStatusTicketId(res.data?.tickets?.[0]?.id || '');
      setAuthError('');
      setToast({ type: 'success', text: `Reserved ${res.data?.tickets?.length || 0} ticket(s).` });
    } catch (error) {
      setAuthError('Reservation failed: ' + extractErrorMessage(error, 'Could not reserve tickets'));
    }
  };

  const checkReservationStatus = async () => {
    if (!reservationStatusTicketId) return;
    try {
      const res = await axios.get(`${API_BASE_URL}/api/reservations/${reservationStatusTicketId}`);
      setReservationStatusResult(res.data);
      setToast({ type: 'info', text: `Reservation status: ${res.data?.status || 'unknown'}.` });
    } catch (error) {
      setAuthError('Reservation status failed: ' + extractErrorMessage(error, 'Could not load reservation status'));
    }
  };

  const handleRefund = async () => {
    if (!token) {
      setRefundError('Login required to request refund.');
      return;
    }
    if (!refundPaymentId.trim()) {
      setRefundError('Payment ID is required.');
      return;
    }

    const ticketIds = refundTicketIds
      .split(',')
      .map((x) => x.trim())
      .filter(Boolean);

    try {
      const res = await axios.post(
        `${API_BASE_URL}/api/refund`,
        {
          payment_id: refundPaymentId.trim(),
          ticket_ids: ticketIds,
          reason: 'requested_by_customer',
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setRefundResult(res.data);
      setRefundError('');
      fetchPayments(token);
      setToast({ type: 'success', text: 'Refund requested successfully.' });
    } catch (error) {
      setRefundResult(null);
      setRefundError(extractErrorMessage(error, 'Refund failed'));
    }
  };

  const ensurePrivilegedAccess = () => {
    if (!token) {
      setManagerError('Login required.');
      return false;
    }
    if (!isPrivilegedUser) {
      setManagerError('This action is restricted to promoter/admin users.');
      return false;
    }
    return true;
  };

  const handleCreateEvent = async () => {
    if (!ensurePrivilegedAccess()) return;
    if (!managerEventName.trim() || !managerEventDate) {
      setManagerError('Event name and date are required.');
      return;
    }

    setManagerLoading(true);
    setManagerError('');
    try {
      const payload = {
        name: managerEventName.trim(),
        description: managerEventDescription.trim() || null,
        venue: managerEventVenue.trim() || null,
        date: new Date(managerEventDate).toISOString(),
      };
      const res = await axios.post(`${API_BASE_URL}/api/events`, payload, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const createdId = res.data?.id || '';
      setManagerTargetEventId(createdId);
      setManagerBatchEventId(createdId);
      setToast({ type: 'success', text: `Event created${createdId ? `: ${createdId}` : ''}.` });
      fetchEvents();
    } catch (error) {
      setManagerError('Create event failed: ' + extractErrorMessage(error, 'Could not create event'));
    } finally {
      setManagerLoading(false);
    }
  };

  const handleUpdateEventStatus = async () => {
    if (!ensurePrivilegedAccess()) return;
    if (!managerTargetEventId.trim()) {
      setManagerError('Event ID is required.');
      return;
    }

    setManagerLoading(true);
    setManagerError('');
    try {
      await axios.put(
        `${API_BASE_URL}/api/events/${managerTargetEventId.trim()}`,
        { status: managerTargetEventStatus },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setToast({ type: 'success', text: `Event status updated to ${managerTargetEventStatus}.` });
      fetchEvents();
    } catch (error) {
      setManagerError('Update event failed: ' + extractErrorMessage(error, 'Could not update event'));
    } finally {
      setManagerLoading(false);
    }
  };

  const handleDeleteEvent = async () => {
    if (!ensurePrivilegedAccess()) return;
    if (!managerTargetEventId.trim()) {
      setManagerError('Event ID is required.');
      return;
    }

    setManagerLoading(true);
    setManagerError('');
    try {
      await axios.delete(`${API_BASE_URL}/api/events/${managerTargetEventId.trim()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setToast({ type: 'success', text: 'Event deleted.' });
      fetchEvents();
    } catch (error) {
      setManagerError('Delete event failed: ' + extractErrorMessage(error, 'Could not delete event'));
    } finally {
      setManagerLoading(false);
    }
  };

  const handleCreateTicketBatch = async () => {
    if (!ensurePrivilegedAccess()) return;
    if (!managerBatchEventId.trim()) {
      setManagerError('Event ID is required for ticket batch.');
      return;
    }

    setManagerLoading(true);
    setManagerError('');
    try {
      await axios.post(
        `${API_BASE_URL}/api/events/${managerBatchEventId.trim()}/tickets`,
        {
          category: managerBatchCategory.trim() || 'General',
          price: Number(managerBatchPrice || 0),
          currency: 'EUR',
          quantity: Number(managerBatchQuantity || 1),
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setToast({ type: 'success', text: 'Ticket batch created.' });
    } catch (error) {
      setManagerError('Create tickets failed: ' + extractErrorMessage(error, 'Could not create ticket batch'));
    } finally {
      setManagerLoading(false);
    }
  };

  const handleTicketLifecycleAction = async (action) => {
    if (!ensurePrivilegedAccess()) return;
    if (!managerTicketId.trim()) {
      setManagerError('Ticket ID is required.');
      return;
    }

    setManagerLoading(true);
    setManagerError('');
    try {
      const baseUrl = `${API_BASE_URL}/api/tickets/${managerTicketId.trim()}`;
      const config = { headers: { Authorization: `Bearer ${token}` } };

      if (action === 'cancel') {
        await axios.delete(baseUrl, config);
      } else {
        await axios.put(`${baseUrl}/${action}`, {}, config);
      }

      setToast({ type: 'success', text: `Ticket action executed: ${action}.` });
    } catch (error) {
      setManagerError(`Ticket ${action} failed: ` + extractErrorMessage(error, 'Operation failed'));
    } finally {
      setManagerLoading(false);
    }
  };

  const handleCheckout = async (eventId) => {
    if (!token) {
      setAuthError('Please sign in before checkout.');
      return;
    }

    const quantity = Number(quantityByEvent[eventId] || 1);
    setCheckoutLoadingEventId(eventId);
    setFlowInfo('Redirecting to hosted checkout...');
    setWalletActionUrl('');

    try {
      const payload = {
        event_id: eventId,
        quantity,
        success_url: window.location.href.split('?')[0] + '?status=success',
        cancel_url: window.location.href.split('?')[0] + '?status=cancel',
        amount_cents: quantity * 1500,
      };

      const config = { headers: { Authorization: `Bearer ${token}` } };
      const res = await axios.post(`${API_BASE_URL}/api/checkout`, payload, config);

      if (res.data && res.data.checkout_url) {
        window.location.href = res.data.checkout_url;
      } else {
        setToast({ type: 'warning', text: 'Checkout started, but no redirect URL was returned.' });
      }
    } catch (error) {
      const detailObject = extractErrorDetailObject(error);
      if (detailObject?.code === 'wallet_setup_required') {
        const guidance = detailObject?.message || 'Wallet setup is required before checkout.';
        setFlowInfo(guidance);
        setWalletActionUrl(
          detailObject?.wallet_register_url
          || detailObject?.action_url
          || buildPaymentUiUrl(PAYMENT_UI_REGISTER_PATH)
        );
        setPaymentAccount({ exists: false, customer: null, identity_email: user?.email || '' });
        setToast({ type: 'warning', text: guidance });
      } else {
        setToast({ type: 'error', text: 'Checkout error: ' + extractErrorMessage(error, 'Could not start checkout') });
      }
    } finally {
      setCheckoutLoadingEventId('');
    }
  };

  const setEventQuantity = (eventId, value) => {
    const parsed = Math.max(1, Math.min(10, Number(value) || 1));
    setQuantityByEvent((prev) => ({ ...prev, [eventId]: parsed }));
  };

  const startAuthUiFlow = (path) => {
    const state = createAuthState();
    addPendingAuthState(state);
    setAuthError('');
    setFlowInfo('Redirecting to the Auth UI...');

    const authUrl = buildAuthUiUrl(path, {
      handoff_url: buildApiUrl('/api/auth/browser/handoff'),
      return_to: `${window.location.origin}${window.location.pathname}`,
      state,
    });
    window.location.href = authUrl;
  };

  const usePaymentInRefund = (paymentId) => {
    setRefundPaymentId(paymentId);
    setActiveTab('refund');
  };

  const useEventInReservation = (eventId) => {
    setReservationEventId(eventId);
    setActiveTab('overview');
  };

  const statusClass = (statusValue) => {
    const status = String(statusValue || '').toLowerCase();
    if (status.includes('success') || status.includes('succeeded') || status.includes('paid') || status.includes('complete')) {
      return 'badge badge-success';
    }
    if (status.includes('pending') || status.includes('open') || status.includes('processing')) {
      return 'badge badge-warning';
    }
    if (status.includes('fail') || status.includes('cancel') || status.includes('refund')) {
      return 'badge badge-danger';
    }
    return 'badge badge-neutral';
  };

  const formatDate = (value) => {
    if (!value) return 'Date TBD';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString();
  };

  const paymentItems = payments || [];

  return (
    <div className="app-shell">
      <div className="bg-orb orb-a" />
      <div className="bg-orb orb-b" />

      <header className="hero">
        <div className="hero-tag">Composer Demo Ready</div>
        <h1>FlashSale Portal</h1>
        <p className="hero-subtitle">Fast event checkout orchestration across Auth, Inventory and Payment.</p>

        <div className="hero-steps">
          <span>1. Sign in</span>
          <span>2. Pick event</span>
          <span>3. Complete checkout</span>
          <span>4. Verify payment</span>
        </div>
      </header>

      {toast && (
        <div className={`toast toast-${toast.type}`}>
          {toast.text}
        </div>
      )}

      {flowInfo && <div className="flow-note">{flowInfo}</div>}

      <section className="auth-panel">
        <div className="auth-status copy-block">
          {token ? (
            <p>Signed in as <strong>{user?.email || 'N/A'}</strong>.</p>
          ) : (
            <>
              <p>Welcome. Sign in using the Auth UI to continue.</p>
              <p className="hint">The dedicated auth frontend remains separate. Sign-in there now returns securely to the Composer with a one-time handoff code.</p>
            </>
          )}
        </div>

        <div className="auth-buttons">
          {token ? (
            <button className="btn btn-outline" onClick={handleLogout}>Logout</button>
          ) : (
            <>
              <button className="btn btn-outline" onClick={() => startAuthUiFlow(AUTH_UI_REGISTER_PATH)} disabled={authRedirectLoading}>
                Auth Register UI
              </button>
              <button className="btn btn-outline" onClick={() => startAuthUiFlow(AUTH_UI_LOGIN_PATH)} disabled={authRedirectLoading}>
                Auth Login UI
              </button>
              <a className="btn btn-outline" href={buildAuthUiUrl(AUTH_UI_FORGOT_PATH)}>
                Forgot Password UI
              </a>
            </>
          )}
        </div>
        {authError && <span className="error-msg">{authError}</span>}
      </section>

      <section className="events-section">
        <div className="section-head">
          <h2>Live Events</h2>
          <button className="btn btn-outline" onClick={fetchEvents}>Refresh Events</button>
        </div>

        {!token && <div className="login-gate">Login is required to purchase tickets.</div>}

        {loadingEvents ? (
          <div className="skeleton-grid">
            {[1, 2, 3].map((i) => <div key={i} className="skeleton-card" />)}
          </div>
        ) : (
          <div className="events-grid">
            {eventsError && <p className="error-msg wide">{eventsError}</p>}
            {events.length === 0 && <p className="hint wide">No events found.</p>}
            {events.map((ev) => {
              const qty = quantityByEvent[ev.id] || 1;
              const buyingThis = checkoutLoadingEventId === ev.id;
              return (
                <article key={ev.id} className="event-card">
                  <div className="event-header-row">
                    <h3>{ev.name || 'Unnamed Event'}</h3>
                    <span className="badge badge-neutral">{ev.status || 'draft'}</span>
                  </div>

                  <p className="event-description">{ev.description || 'No description provided.'}</p>

                  <div className="event-meta">
                    <span>{ev.venue || 'Venue TBD'}</span>
                    <span>{formatDate(ev.date)}</span>
                  </div>

                  <div className="event-action">
                    <div className="qty-row">
                      <label>Qty</label>
                      <input
                        type="number"
                        min="1"
                        max="10"
                        value={qty}
                        onChange={(e) => setEventQuantity(ev.id, e.target.value)}
                      />
                    </div>

                    <div className="event-buttons">
                      <button
                        className="btn btn-outline"
                        onClick={() => useEventInReservation(ev.id)}
                      >
                        Use Event ID
                      </button>

                      <button
                        className="btn"
                        onClick={() => handleCheckout(ev.id)}
                        disabled={!token || buyingThis}
                      >
                        {buyingThis ? 'Redirecting...' : token ? 'Buy Ticket(s)' : 'Login to Buy'}
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {token && (
        <section className="workspace">
          <div className="workspace-tabs">
            <button
              className={`tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
              onClick={() => setActiveTab('overview')}
            >
              Overview
            </button>
            <button
              className={`tab-btn ${activeTab === 'payments' ? 'active' : ''}`}
              onClick={() => setActiveTab('payments')}
            >
              Payments
            </button>
            <button
              className={`tab-btn ${activeTab === 'refund' ? 'active' : ''}`}
              onClick={() => setActiveTab('refund')}
            >
              Refund
            </button>
          </div>

          {activeTab === 'overview' && (
            <div className="panel-grid">
              <article className="panel-card reveal">
                <h2>Profile</h2>
                <p><strong>Email:</strong> {profileLoading ? 'Loading...' : (user?.email || 'N/A')}</p>
                <p><strong>Name:</strong> {profileLoading ? 'Loading...' : (user?.full_name || 'N/A')}</p>
                <p><strong>Role:</strong> {profileLoading ? 'Loading...' : (user?.role || 'N/A')}</p>
                <p>
                  <strong>Local Payment account:</strong>
                  {' '}
                  {paymentAccountLoading
                    ? 'Checking...'
                    : paymentAccount?.exists
                      ? 'ready'
                      : 'not created yet'}
                </p>
                {!paymentAccount?.exists && (
                  <button className="btn" onClick={setupPaymentAccount}>
                    Create Payment Account
                  </button>
                )}
                {profileError && <p className="error-msg">Profile error: {profileError}</p>}
                {paymentAccountError && <p className="error-msg">Payment account: {paymentAccountError}</p>}
                <button className="btn btn-outline" onClick={() => fetchProfile(token)}>Refresh Profile</button>
              </article>

              {isPrivilegedUser && (
                <article className="panel-card reveal manager-card">
                  <h2>Promoter/Admin Controls</h2>
                  <p className="hint">Manage events and tickets from one place.</p>

                  <div className="manager-section">
                    <h3>Event Creation</h3>
                    <div className="manager-grid">
                      <div>
                        <label>New Event Name</label>
                        <input
                          value={managerEventName}
                          onChange={(e) => setManagerEventName(e.target.value)}
                          placeholder="Event name"
                        />
                      </div>
                      <div>
                        <label>New Event Date</label>
                        <input
                          type="datetime-local"
                          value={managerEventDate}
                          onChange={(e) => setManagerEventDate(e.target.value)}
                        />
                      </div>
                    </div>
                    <div className="manager-grid">
                      <div>
                        <label>Venue</label>
                        <input
                          value={managerEventVenue}
                          onChange={(e) => setManagerEventVenue(e.target.value)}
                          placeholder="Venue"
                        />
                      </div>
                      <div>
                        <label>Description</label>
                        <input
                          value={managerEventDescription}
                          onChange={(e) => setManagerEventDescription(e.target.value)}
                          placeholder="Description"
                        />
                      </div>
                    </div>
                    <div className="manager-actions">
                      <button className="btn" onClick={handleCreateEvent} disabled={managerLoading}>
                        Create Event
                      </button>
                    </div>
                  </div>

                  <div className="manager-section">
                    <h3>Event Management</h3>
                    <div className="manager-grid">
                      <div>
                        <label>Target Event ID</label>
                        <input
                          value={managerTargetEventId}
                          onChange={(e) => setManagerTargetEventId(e.target.value)}
                          placeholder="Event UUID"
                        />
                      </div>
                      <div>
                        <label>Event Status</label>
                        <select
                          value={managerTargetEventStatus}
                          onChange={(e) => setManagerTargetEventStatus(e.target.value)}
                        >
                          <option value="draft">draft</option>
                          <option value="published">published</option>
                          <option value="cancelled">cancelled</option>
                          <option value="sold_out">sold_out</option>
                          <option value="completed">completed</option>
                        </select>
                      </div>
                    </div>
                    <div className="manager-actions manager-actions-split">
                      <button className="btn btn-outline" onClick={handleUpdateEventStatus} disabled={managerLoading}>
                        Update Event Status
                      </button>
                      <button className="btn btn-outline" onClick={handleDeleteEvent} disabled={managerLoading}>
                        Delete Event
                      </button>
                    </div>
                  </div>

                  <div className="manager-section">
                    <h3>Ticket Batch</h3>
                    <div className="manager-grid">
                      <div>
                        <label>Ticket Batch Event ID</label>
                        <input
                          value={managerBatchEventId}
                          onChange={(e) => setManagerBatchEventId(e.target.value)}
                          placeholder="Event UUID"
                        />
                      </div>
                      <div>
                        <label>Category</label>
                        <input
                          value={managerBatchCategory}
                          onChange={(e) => setManagerBatchCategory(e.target.value)}
                          placeholder="General / VIP"
                        />
                      </div>
                    </div>
                    <div className="manager-grid">
                      <div>
                        <label>Price (EUR)</label>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={managerBatchPrice}
                          onChange={(e) => setManagerBatchPrice(e.target.value)}
                        />
                      </div>
                      <div>
                        <label>Quantity</label>
                        <input
                          type="number"
                          min="1"
                          max="50000"
                          value={managerBatchQuantity}
                          onChange={(e) => setManagerBatchQuantity(e.target.value)}
                        />
                      </div>
                    </div>
                    <div className="manager-actions">
                      <button className="btn" onClick={handleCreateTicketBatch} disabled={managerLoading}>
                        Create Ticket Batch
                      </button>
                    </div>
                  </div>

                  <div className="manager-section">
                    <h3>Ticket Lifecycle</h3>
                    <label>Ticket ID</label>
                    <input
                      value={managerTicketId}
                      onChange={(e) => setManagerTicketId(e.target.value)}
                      placeholder="Ticket UUID"
                    />
                    <div className="manager-actions manager-actions-quad">
                      <button className="btn btn-outline" onClick={() => handleTicketLifecycleAction('reserve')} disabled={managerLoading}>
                        Reserve
                      </button>
                      <button className="btn btn-outline" onClick={() => handleTicketLifecycleAction('sell')} disabled={managerLoading}>
                        Sell
                      </button>
                      <button className="btn btn-outline" onClick={() => handleTicketLifecycleAction('use')} disabled={managerLoading}>
                        Use
                      </button>
                      <button className="btn btn-outline" onClick={() => handleTicketLifecycleAction('cancel')} disabled={managerLoading}>
                        Cancel
                      </button>
                    </div>
                  </div>

                  {managerError && <p className="error-msg">{managerError}</p>}
                </article>
              )}

              <article className="panel-card reveal">
                <h2>Reservations</h2>
                <label>Event ID</label>
                <input
                  value={reservationEventId}
                  onChange={(e) => setReservationEventId(e.target.value)}
                  placeholder="Paste event id"
                />
                <label>Quantity</label>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={reservationQty}
                  onChange={(e) => setReservationQty(e.target.value)}
                />
                <button className="btn" onClick={reserveTickets}>Reserve Tickets</button>
                <p className="hint">Reservation only holds tickets. Use Buy Ticket(s) to create a payment.</p>
                {reservationResult && (
                  <p className="hint">
                    Reserved: {reservationResult?.tickets?.length || 0} tickets
                  </p>
                )}
                <label>Reservation ticket id</label>
                <input
                  value={reservationStatusTicketId}
                  onChange={(e) => setReservationStatusTicketId(e.target.value)}
                  placeholder="Ticket id to check"
                />
                <button className="btn btn-outline" onClick={checkReservationStatus}>Check Status</button>
                {reservationStatusResult && (
                  <p className="hint">Status: <span className={statusClass(reservationStatusResult.status)}>{reservationStatusResult.status}</span></p>
                )}
              </article>
            </div>
          )}

          {activeTab === 'payments' && (
            <div className="payments-board reveal">
              <div className="section-head">
                <h2>Payments History</h2>
                <button className="btn btn-outline" onClick={() => fetchPayments(token)}>Refresh Payments</button>
              </div>

              {paymentsLoading && (
                <div className="skeleton-grid payments-skeleton">
                  {[1, 2].map((i) => <div key={i} className="skeleton-card" />)}
                </div>
              )}

              {paymentsError && <p className="error-msg wide">{paymentsError}</p>}

              {!paymentsLoading && paymentItems.length === 0 && (
                <p className="hint wide">No payments yet. Complete a checkout from an event card.</p>
              )}

              <div className="payments-grid">
                {!paymentsLoading && paymentItems.slice(0, 8).map((p) => (
                  <article key={p.id} className="payment-card">
                    <div className="payment-top">
                      <h3>{p.amount} {p.currency?.toUpperCase?.() || ''}</h3>
                      <span className={statusClass(p.status)}>{p.status}</span>
                    </div>
                    <p className="payment-id">{p.id}</p>
                    <p className="hint">Created: {formatDate(p.created_at)}</p>
                    <button className="btn btn-outline" onClick={() => usePaymentInRefund(p.id)}>
                      Use in Refund
                    </button>
                  </article>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'refund' && (
            <article className="panel-card refund-card reveal">
              <h2>Request Refund</h2>
              <label>Payment ID</label>
              <input
                value={refundPaymentId}
                onChange={(e) => setRefundPaymentId(e.target.value)}
                placeholder="Payment UUID"
              />

              <label>Ticket IDs (comma separated)</label>
              <input
                value={refundTicketIds}
                onChange={(e) => setRefundTicketIds(e.target.value)}
                placeholder="ticket-1,ticket-2"
              />

              <button className="btn" onClick={handleRefund}>Request Refund</button>

              {refundError && <p className="error-msg">{refundError}</p>}
              {refundResult && <p className="hint">Refund status: <span className={statusClass(refundResult.status)}>{refundResult.status}</span></p>}

              {paymentItems.length > 0 && (
                <div className="quick-links">
                  <p className="hint">Quick pick a recent payment:</p>
                  <div className="quick-link-list">
                    {paymentItems.slice(0, 3).map((p) => (
                      <button key={p.id} className="pill-btn" onClick={() => setRefundPaymentId(p.id)}>
                        {p.id.slice(0, 8)}...
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </article>
          )}
        </section>
      )}
    </div>
  );
}

export default App;
