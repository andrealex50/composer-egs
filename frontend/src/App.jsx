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
const AUTH_EXCHANGE_PROMISE_KEY = '__flashsaleAuthExchangePromise';
const CART_STORAGE_KEY = 'flashsale_cart_v1';
const WISHLIST_STORAGE_KEY = 'flashsale_wishlist_v1';
const PENDING_CHECKOUT_STORAGE_KEY = 'flashsale_pending_checkout';

const buildAuthUiUrl = (path, query = {}) => {
  const url = new URL(path, AUTH_UI_BASE_URL);
  Object.entries(query).forEach(([key, value]) => { if (value) url.searchParams.set(key, value); });
  return url.toString();
};
const buildPaymentUiUrl = (path) => new URL(path, PAYMENT_UI_BASE_URL).toString();
const buildApiUrl = (path) => new URL(path, API_BASE_URL || window.location.origin).toString();
const createAuthState = () => window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;

const getPendingAuthStates = () => {
  const raw = localStorage.getItem(AUTH_STATE_STORAGE_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.map((item) => String(item || '').trim()).filter(Boolean);
  } catch (_) {}
  const legacy = String(raw).trim();
  return legacy ? [legacy] : [];
};

const savePendingAuthStates = (states) => {
  if (!states.length) { localStorage.removeItem(AUTH_STATE_STORAGE_KEY); return; }
  localStorage.setItem(AUTH_STATE_STORAGE_KEY, JSON.stringify(states));
};

const addPendingAuthState = (state) => {
  const normalized = String(state || '').trim();
  if (!normalized) return;
  const current = getPendingAuthStates();
  savePendingAuthStates([...current.filter((item) => item !== normalized), normalized].slice(-10));
};

const hasPendingAuthState = (state) => {
  const normalized = String(state || '').trim();
  return normalized ? getPendingAuthStates().includes(normalized) : false;
};

const consumePendingAuthState = (state) => {
  const normalized = String(state || '').trim();
  if (!normalized) return;
  savePendingAuthStates(getPendingAuthStates().filter((item) => item !== normalized));
};

const clearPendingAuthStates = () => localStorage.removeItem(AUTH_STATE_STORAGE_KEY);

const getOrCreateAuthExchangePromise = (code, state) => {
  const existing = window[AUTH_EXCHANGE_PROMISE_KEY];
  if (existing?.code === code && existing?.state === state && existing?.promise) return existing.promise;
  const promise = axios.post(`${API_BASE_URL}/api/auth/browser/exchange`, { code, state }, { withCredentials: true });
  window[AUTH_EXCHANGE_PROMISE_KEY] = { code, state, promise };
  return promise;
};

const refreshAccessToken = async () => {
  const res = await axios.post(`${API_BASE_URL}/api/auth/refresh`, {}, { withCredentials: true });
  return String(res.data?.access_token || '').trim();
};

const extractErrorMessage = (error, fallback = 'Request failed') => {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((item) => item?.msg || JSON.stringify(item)).join('; ');
  if (detail && typeof detail === 'object') return detail.detail || detail.message || JSON.stringify(detail);
  return error?.message || fallback;
};

const extractErrorDetailObject = (error) => {
  const detail = error?.response?.data?.detail;
  return (detail && typeof detail === 'object' && !Array.isArray(detail)) ? detail : null;
};

// ─── Event banner gradient palette ─────────────────────────────────────────
const BANNER_GRADIENTS = [
  'linear-gradient(135deg, #0a2040 0%, #0d3b2a 100%)',
  'linear-gradient(135deg, #1a0a30 0%, #0a1f40 100%)',
  'linear-gradient(135deg, #0f2a1a 0%, #0a2030 100%)',
  'linear-gradient(135deg, #200a0a 0%, #0a1530 100%)',
  'linear-gradient(135deg, #101a30 0%, #0a2820 100%)',
  'linear-gradient(135deg, #1a1000 0%, #0a2020 100%)',
];

const getBannerGradient = (seed) => {
  const idx = seed ? seed.charCodeAt(0) % BANNER_GRADIENTS.length : 0;
  return BANNER_GRADIENTS[idx];
};

// ─── Icons ──────────────────────────────────────────────────────────────────
const IconPin = () => (
  <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
    <path d="M8 1a4 4 0 1 0 0 8A4 4 0 0 0 8 1zM6 5a2 2 0 1 1 4 0 2 2 0 0 1-4 0zm2 4.5c-3 0-5 1.3-5 2.5v.5h10v-.5c0-1.2-2-2.5-5-2.5z"/>
  </svg>
);

const IconCal = () => (
  <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
    <path d="M3.5 0a.5.5 0 0 1 .5.5V1h8V.5a.5.5 0 0 1 1 0V1H14a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2h1.5V.5a.5.5 0 0 1 .5-.5zM1 6v8a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V6H1z"/>
  </svg>
);

const IconCart = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
    <path d="M0 1a1 1 0 0 1 1-1h1.4a1 1 0 0 1 .98.804L3.6 2H15a1 1 0 0 1 .97 1.242l-1.2 5A1 1 0 0 1 13.8 9H4a1 1 0 0 1-.98-.804L1.63 1H1a1 1 0 0 1-1-1zm4.2 10a1.6 1.6 0 1 0 0 3.2 1.6 1.6 0 0 0 0-3.2zm7.2 0a1.6 1.6 0 1 0 0 3.2 1.6 1.6 0 0 0 0-3.2z"/>
  </svg>
);

const IconHeart = ({ filled = false }) => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <path
      d="M8 14.2 2.3 8.7A3.7 3.7 0 0 1 7.6 3.5L8 4l.4-.5a3.7 3.7 0 0 1 5.3 5.2L8 14.2z"
      fill={filled ? 'currentColor' : 'transparent'}
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinejoin="round"
    />
  </svg>
);

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
  const [activeTab, setActiveTab] = useState('orders');
  const [toast, setToast] = useState(null);
  const [checkoutLoadingEventId, setCheckoutLoadingEventId] = useState('');
  const [quantityByEvent, setQuantityByEvent] = useState({});
  const [cartByEvent, setCartByEvent] = useState(() => {
    const raw = localStorage.getItem(CART_STORAGE_KEY);
    if (!raw) return {};
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (_) {
      return {};
    }
  });
  const [cartCheckoutLoading, setCartCheckoutLoading] = useState(false);
  const [wishlistByEvent, setWishlistByEvent] = useState(() => {
    const raw = localStorage.getItem(WISHLIST_STORAGE_KEY);
    if (!raw) return {};
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (_) {
      return {};
    }
  });
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

  useEffect(() => { fetchEvents(); }, []);

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
    if (token) return undefined;
    let cancelled = false;
    const restoreSession = async () => {
      try {
        const restoredToken = await refreshAccessToken();
        if (cancelled || !restoredToken) return;
        setToken(restoredToken);
      } catch (_) {
        // No persisted session cookie is available, continue as logged out.
      }
    };
    restoreSession();
    return () => { cancelled = true; };
  }, [token]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('auth_callback') !== '1') return;
    const code = params.get('code');
    const state = params.get('state');
    const cleanUrl = `${window.location.origin}${window.location.pathname}`;
    if (!code || !state || !hasPendingAuthState(state)) {
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
        consumePendingAuthState(state);
        setUser(res.data?.user || null);
        setToken(res.data?.access_token || '');
        setToast({ type: 'success', text: 'Welcome back! You are signed in.' });
      } catch (error) {
        if (cancelled) return;
        consumePendingAuthState(state);
        setAuthError('Sign-in failed: ' + extractErrorMessage(error, 'Could not finish sign-in.'));
      } finally {
        if (cancelled) return;
        setAuthRedirectLoading(false);
        setFlowInfo('');
        window.history.replaceState({}, document.title, cleanUrl);
      }
    };
    completeHandoff();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 3600);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(cartByEvent || {}));
  }, [cartByEvent]);

  useEffect(() => {
    localStorage.setItem(WISHLIST_STORAGE_KEY, JSON.stringify(wishlistByEvent || {}));
  }, [wishlistByEvent]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const status = params.get('status');
    if (!status) return;
    const pendingCheckout = localStorage.getItem(PENDING_CHECKOUT_STORAGE_KEY);
    if (status === 'success') {
      setFlowInfo('');
      setToast({ type: 'success', text: 'Payment completed! Check your orders.' });
      if (pendingCheckout === 'cart') {
        setCartByEvent({});
      }
      if (token) fetchPayments(token);
    } else if (status === 'cancel') {
      setToast({ type: 'warning', text: 'Checkout cancelled. No payment was taken.' });
    }
    localStorage.removeItem(PENDING_CHECKOUT_STORAGE_KEY);
    window.history.replaceState({}, document.title, `${window.location.origin}${window.location.pathname}`);
  }, [token]);

  const fetchEvents = () => {
    setLoadingEvents(true);
    setEventsError('');
    axios.get(`${API_BASE_URL}/api/events`)
      .then((res) => { setEvents(res.data?.data || []); setLoadingEvents(false); })
      .catch((err) => { setEventsError(extractErrorMessage(err, 'Could not load events')); setLoadingEvents(false); });
  };

  const fetchProfile = async (activeToken) => {
    setProfileLoading(true);
    setProfileError('');
    try {
      const res = await axios.get(`${API_BASE_URL}/api/auth/me`, { headers: { Authorization: `Bearer ${activeToken}` } });
      setUser(res.data || null);
    } catch (error) {
      const statusCode = error?.response?.status;
      if (statusCode === 401 || statusCode === 403) {
        try {
          const restoredToken = await refreshAccessToken();
          if (restoredToken) {
            setToken(restoredToken);
            return;
          }
        } catch (_) {
          // Ignore and continue with sign-out flow below.
        }
        setToken(null);
        setAuthError('Session expired. Please sign in again.');
      }
      setUser(null);
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
          { headers: { Authorization: `Bearer ${token}` }, withCredentials: true }
        );
      }
    } catch (_) {}
    finally {
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
      setActiveTab('orders');
      setToast({ type: 'info', text: 'Signed out successfully.' });
    }
  };

  const fetchPayments = async (activeToken = token) => {
    if (!activeToken) return;
    setPaymentsLoading(true);
    setPaymentsError('');
    try {
      const res = await axios.get(`${API_BASE_URL}/api/payments`, { headers: { Authorization: `Bearer ${activeToken}` } });
      setPayments(res.data?.items || []);
    } catch (error) {
      setPaymentsError(extractErrorMessage(error, 'Could not load orders'));
    } finally {
      setPaymentsLoading(false);
    }
  };

  const cancelTicket = async (ticketId) => {
    try {
      await axios.post(`${API_BASE_URL}/api/tickets/${ticketId}/cancel`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      fetchProfile(token);
      setToast({ type: 'success', text: 'Ticket canceled successfully' });
    } catch (error) {
      setToast({ type: 'error', text: extractErrorMessage(error, 'Could not cancel ticket') });
    }
  };

  const downloadReceipt = async (paymentId) => {
    if (!token) return;
    try {
      setToast({ type: 'info', text: 'Generating receipt...' });
      const res = await axios.get(`${API_BASE_URL}/api/payments/${paymentId}/receipt`, {
        headers: { Authorization: `Bearer ${token}` },
        responseType: 'blob'
      });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `receipt-${paymentId.slice(0, 8)}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.parentNode.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      setToast({ type: 'error', text: extractErrorMessage(error, 'Could not download receipt') });
    }
  };

  const fetchPaymentAccount = async (activeToken = token) => {
    if (!activeToken) return;
    setPaymentAccountLoading(true);
    setPaymentAccountError('');
    try {
      const res = await axios.get(`${API_BASE_URL}/api/payment-account`, { headers: { Authorization: `Bearer ${activeToken}` } });
      setPaymentAccount(res.data || null);
      if (res.data?.exists) {
        setWalletActionUrl(buildPaymentUiUrl(PAYMENT_UI_DASHBOARD_PATH));
      } else {
        setWalletActionUrl(buildPaymentUiUrl(PAYMENT_UI_REGISTER_PATH));
      }
    } catch (error) {
      setPaymentAccount(null);
      setPaymentAccountError(extractErrorMessage(error, 'Could not load wallet status'));
    } finally {
      setPaymentAccountLoading(false);
    }
  };

  const setupPaymentAccount = async () => {
    if (!token) { setAuthError('Please sign in before setting up a wallet.'); return; }
    const registerUrl = buildPaymentUiUrl(PAYMENT_UI_REGISTER_PATH);
    setWalletActionUrl(registerUrl);
    setFlowInfo('Redirecting to wallet setup...');
    window.location.href = registerUrl;
  };

  const reserveTickets = async (eventId, qty) => {
    if (!eventId) return;
    try {
      const res = await axios.post(`${API_BASE_URL}/api/reservations`, { event_id: eventId, quantity: Number(qty) || 1 });
      setReservationResult(res.data);
      setReservationStatusTicketId(res.data?.tickets?.[0]?.id || '');
      setToast({ type: 'success', text: `Reserved ${res.data?.tickets?.length || 0} ticket(s) — complete payment via Buy Now.` });
    } catch (error) {
      setToast({ type: 'error', text: 'Reservation failed: ' + extractErrorMessage(error) });
    }
  };

  const handleRefund = async () => {
    if (!token) { setRefundError('Sign in to request a refund.'); return; }
    if (!refundPaymentId.trim()) { setRefundError('Please select an order to refund.'); return; }
    const ticketIds = refundTicketIds.split(',').map((x) => x.trim()).filter(Boolean);
    try {
      const res = await axios.post(
        `${API_BASE_URL}/api/refund`,
        { payment_id: refundPaymentId.trim(), ticket_ids: ticketIds, reason: 'requested_by_customer' },
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
    if (!token) { setManagerError('Sign in required.'); return false; }
    if (!isPrivilegedUser) { setManagerError('Restricted to promoter / admin accounts.'); return false; }
    return true;
  };

  const handleCreateEvent = async () => {
    if (!ensurePrivilegedAccess()) return;
    if (!managerEventName.trim() || !managerEventDate) { setManagerError('Event name and date are required.'); return; }
    setManagerLoading(true); setManagerError('');
    try {
      const res = await axios.post(`${API_BASE_URL}/api/events`, {
        name: managerEventName.trim(),
        description: managerEventDescription.trim() || null,
        venue: managerEventVenue.trim() || null,
        date: new Date(managerEventDate).toISOString(),
      }, { headers: { Authorization: `Bearer ${token}` } });
      const id = res.data?.id || '';
      setManagerTargetEventId(id);
      setManagerBatchEventId(id);
      setToast({ type: 'success', text: `Event created${id ? `: ${id.slice(0, 8)}…` : ''}.` });
      fetchEvents();
    } catch (error) {
      setManagerError('Create event failed: ' + extractErrorMessage(error));
    } finally { setManagerLoading(false); }
  };

  const handleUpdateEventStatus = async () => {
    if (!ensurePrivilegedAccess()) return;
    if (!managerTargetEventId.trim()) { setManagerError('Event ID is required.'); return; }
    setManagerLoading(true); setManagerError('');
    try {
      await axios.put(`${API_BASE_URL}/api/events/${managerTargetEventId.trim()}`, { status: managerTargetEventStatus }, { headers: { Authorization: `Bearer ${token}` } });
      setToast({ type: 'success', text: `Status updated to ${managerTargetEventStatus}.` });
      fetchEvents();
    } catch (error) {
      setManagerError('Update failed: ' + extractErrorMessage(error));
    } finally { setManagerLoading(false); }
  };

  const handleDeleteEvent = async () => {
    if (!ensurePrivilegedAccess()) return;
    if (!managerTargetEventId.trim()) { setManagerError('Event ID is required.'); return; }
    setManagerLoading(true); setManagerError('');
    try {
      await axios.delete(`${API_BASE_URL}/api/events/${managerTargetEventId.trim()}`, { headers: { Authorization: `Bearer ${token}` } });
      setToast({ type: 'success', text: 'Event deleted.' });
      fetchEvents();
    } catch (error) {
      setManagerError('Delete failed: ' + extractErrorMessage(error));
    } finally { setManagerLoading(false); }
  };

  const handleCreateTicketBatch = async () => {
    if (!ensurePrivilegedAccess()) return;
    if (!managerBatchEventId.trim()) { setManagerError('Event ID is required for ticket batch.'); return; }
    setManagerLoading(true); setManagerError('');
    try {
      await axios.post(`${API_BASE_URL}/api/events/${managerBatchEventId.trim()}/tickets`, {
        category: managerBatchCategory.trim() || 'General',
        price: Number(managerBatchPrice || 0),
        currency: 'EUR',
        quantity: Number(managerBatchQuantity || 1),
      }, { headers: { Authorization: `Bearer ${token}` } });
      setToast({ type: 'success', text: 'Ticket batch created.' });
    } catch (error) {
      setManagerError('Create tickets failed: ' + extractErrorMessage(error));
    } finally { setManagerLoading(false); }
  };

  const handleTicketLifecycleAction = async (action) => {
    if (!ensurePrivilegedAccess()) return;
    if (!managerTicketId.trim()) { setManagerError('Ticket ID is required.'); return; }
    setManagerLoading(true); setManagerError('');
    try {
      const baseUrl = `${API_BASE_URL}/api/tickets/${managerTicketId.trim()}`;
      const config = { headers: { Authorization: `Bearer ${token}` } };
      if (action === 'cancel') await axios.delete(baseUrl, config);
      else await axios.put(`${baseUrl}/${action}`, {}, config);
      setToast({ type: 'success', text: `Ticket action: ${action}.` });
    } catch (error) {
      setManagerError(`Ticket ${action} failed: ` + extractErrorMessage(error));
    } finally { setManagerLoading(false); }
  };

  const handleCheckout = async (eventId) => {
    if (!token) { setAuthError('Please sign in to buy tickets.'); return; }
    const quantity = Number(quantityByEvent[eventId] || 1);
    setCheckoutLoadingEventId(eventId);
    setFlowInfo('Redirecting to checkout...');
    setWalletActionUrl('');
    try {
      const payload = {
        event_id: eventId,
        quantity,
        success_url: window.location.href.split('?')[0] + '?status=success',
        cancel_url: window.location.href.split('?')[0] + '?status=cancel',
        amount_cents: quantity * 1500,
      };
      const res = await axios.post(`${API_BASE_URL}/api/checkout`, payload, { headers: { Authorization: `Bearer ${token}` } });
      if (res.data?.checkout_url) {
        localStorage.setItem(PENDING_CHECKOUT_STORAGE_KEY, 'single');
        window.location.href = res.data.checkout_url;
      } else {
        setToast({ type: 'warning', text: 'Checkout started, but no redirect URL was returned.' });
      }
    } catch (error) {
      const detailObject = extractErrorDetailObject(error);
      if (detailObject?.code === 'wallet_setup_required') {
        const guidance = detailObject?.message || 'Wallet setup required before checkout.';
        setFlowInfo(guidance);
        setWalletActionUrl(detailObject?.wallet_register_url || detailObject?.action_url || buildPaymentUiUrl(PAYMENT_UI_REGISTER_PATH));
        setPaymentAccount({ exists: false, customer: null, identity_email: user?.email || '' });
        setToast({ type: 'warning', text: guidance });
      } else {
        setToast({ type: 'error', text: 'Checkout error: ' + extractErrorMessage(error) });
      }
    } finally {
      setCheckoutLoadingEventId('');
      setFlowInfo('');
    }
  };

  const addToCart = (eventObj) => {
    const eventId = String(eventObj?.id || '').trim();
    if (!eventId) return;
    const qtyToAdd = Number(quantityByEvent[eventId] || 1);
    const normalizedQty = Number.isFinite(qtyToAdd) ? Math.max(1, Math.min(20, qtyToAdd)) : 1;
    setCartByEvent((prev) => {
      const existing = prev[eventId];
      const nextQty = Math.max(1, Math.min(50, Number(existing?.quantity || 0) + normalizedQty));
      return {
        ...prev,
        [eventId]: {
          event_id: eventId,
          name: eventObj?.name || existing?.name || 'Unnamed event',
          quantity: nextQty,
          amount_cents_per_ticket: Number(existing?.amount_cents_per_ticket || 1500),
          currency: String(existing?.currency || 'EUR').toUpperCase(),
        },
      };
    });
    setToast({ type: 'success', text: `Added ${normalizedQty} ticket(s) to cart.` });
  };

  const toggleWishlist = (eventObj) => {
    const eventId = String(eventObj?.id || '').trim();
    if (!eventId) return;
    setWishlistByEvent((prev) => {
      if (prev[eventId]) {
        const next = { ...prev };
        delete next[eventId];
        return next;
      }
      return {
        ...prev,
        [eventId]: {
          event_id: eventId,
          name: eventObj?.name || 'Unnamed event',
          venue: eventObj?.venue || '',
          date: eventObj?.date || '',
          status: eventObj?.status || 'draft',
        },
      };
    });
  };

  const removeWishlistItem = (eventId) => {
    setWishlistByEvent((prev) => {
      if (!prev[eventId]) return prev;
      const next = { ...prev };
      delete next[eventId];
      return next;
    });
  };

  const moveWishlistItemToCart = (item) => {
    addToCart({ id: item.event_id, name: item.name });
    removeWishlistItem(item.event_id);
  };

  const setCartItemQuantity = (eventId, quantity) => {
    const normalized = Math.max(1, Math.min(50, Number(quantity) || 1));
    setCartByEvent((prev) => {
      if (!prev[eventId]) return prev;
      return {
        ...prev,
        [eventId]: { ...prev[eventId], quantity: normalized },
      };
    });
  };

  const removeCartItem = (eventId) => {
    setCartByEvent((prev) => {
      if (!prev[eventId]) return prev;
      const next = { ...prev };
      delete next[eventId];
      return next;
    });
  };

  const handleCartCheckout = async () => {
    if (!token) {
      setAuthError('Please sign in to checkout your cart.');
      return;
    }

    const items = Object.values(cartByEvent || {})
      .map((entry) => ({
        event_id: String(entry?.event_id || '').trim(),
        quantity: Number(entry?.quantity || 0),
      }))
      .filter((entry) => entry.event_id && entry.quantity > 0);

    if (!items.length) {
      setToast({ type: 'warning', text: 'Your cart is empty.' });
      return;
    }

    setCartCheckoutLoading(true);
    setFlowInfo('Redirecting your cart to checkout...');
    setWalletActionUrl('');
    try {
      const payload = {
        items,
        success_url: window.location.href.split('?')[0] + '?status=success',
        cancel_url: window.location.href.split('?')[0] + '?status=cancel',
      };
      const res = await axios.post(`${API_BASE_URL}/api/checkout/cart`, payload, { headers: { Authorization: `Bearer ${token}` } });
      if (res.data?.checkout_url) {
        localStorage.setItem(PENDING_CHECKOUT_STORAGE_KEY, 'cart');
        window.location.href = res.data.checkout_url;
      } else {
        setToast({ type: 'warning', text: 'Cart checkout started, but no redirect URL was returned.' });
      }
    } catch (error) {
      const detailObject = extractErrorDetailObject(error);
      if (detailObject?.code === 'wallet_setup_required') {
        const guidance = detailObject?.message || 'Wallet setup required before checkout.';
        setFlowInfo(guidance);
        setWalletActionUrl(detailObject?.wallet_register_url || detailObject?.action_url || buildPaymentUiUrl(PAYMENT_UI_REGISTER_PATH));
        setPaymentAccount({ exists: false, customer: null, identity_email: user?.email || '' });
        setToast({ type: 'warning', text: guidance });
      } else {
        setToast({ type: 'error', text: 'Cart checkout error: ' + extractErrorMessage(error) });
      }
    } finally {
      setCartCheckoutLoading(false);
      setFlowInfo('');
    }
  };

  const stepQty = (eventId, delta) => {
    setQuantityByEvent((prev) => {
      const current = Number(prev[eventId] || 1);
      const next = Math.max(1, Math.min(10, current + delta));
      return { ...prev, [eventId]: next };
    });
  };

  const startAuthUiFlow = (path) => {
    const state = createAuthState();
    addPendingAuthState(state);
    setAuthError('');
    setFlowInfo('Redirecting to sign in...');
    const authUrl = buildAuthUiUrl(path, {
      handoff_url: buildApiUrl('/api/auth/browser/handoff'),
      return_to: `${window.location.origin}${window.location.pathname}`,
      state,
    });
    window.location.href = authUrl;
  };

  const triggerRefund = (paymentId) => {
    setRefundPaymentId(paymentId);
    setActiveTab('refunds');
  };

  const statusClass = (statusValue) => {
    const status = String(statusValue || '').toLowerCase();
    if (status.includes('success') || status.includes('succeeded') || status.includes('paid') || status.includes('complete')) return 'badge badge-success';
    if (status.includes('pending') || status.includes('open') || status.includes('processing')) return 'badge badge-warning';
    if (status.includes('fail') || status.includes('cancel') || status.includes('refund')) return 'badge badge-danger';
    return 'badge badge-neutral';
  };

  const formatDate = (value) => {
    if (!value) return 'Date TBD';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  const copyEventUuid = async (eventId) => {
    const value = String(eventId || '').trim();
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setToast({ type: 'success', text: `UUID copied: ${value.slice(0, 8)}...` });
    } catch (_) {
      setToast({ type: 'error', text: 'Could not copy UUID. Clipboard permission may be blocked.' });
    }
  };

  const paymentItems = payments || [];
  const cartItems = Object.values(cartByEvent || {});
  const wishlistItems = Object.values(wishlistByEvent || {});
  const cartTicketCount = cartItems.reduce((sum, item) => sum + Number(item?.quantity || 0), 0);
  const wishlistCount = wishlistItems.length;
  const cartTotalCents = cartItems.reduce(
    (sum, item) => sum + (Number(item?.quantity || 0) * Number(item?.amount_cents_per_ticket || 0)),
    0,
  );
  const cartTotalLabel = `€${(cartTotalCents / 100).toFixed(2)}`;
  const firstName = (user?.full_name || user?.email || '').split(/[\s@]/)[0] || 'there';
  const initials = firstName.slice(0, 2).toUpperCase();
  const managerEventChoices = events
    .filter((ev) => ev?.id)
    .map((ev) => ({ id: String(ev.id), label: `${ev.name || 'Unnamed event'} (${String(ev.id).slice(0, 8)}...)` }));

  return (
    <>
      {/* ── NAV ─────────────────────────────────── */}
      <nav className="nav">
        <div className="nav-logo">
          ⚡ FlashSale
        </div>
        <div className="nav-right">
          <button
            className="btn btn-ghost btn-sm cart-nav-btn"
            onClick={() => document.getElementById('wishlist')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            type="button"
          >
            <IconHeart />
            Wishlist
            {wishlistCount > 0 && <span className="nav-cart-count">{wishlistCount}</span>}
          </button>
          <button
            className="btn btn-ghost btn-sm cart-nav-btn"
            onClick={() => document.getElementById('cart')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            type="button"
          >
            <IconCart />
            Cart
            {cartTicketCount > 0 && <span className="nav-cart-count">{cartTicketCount}</span>}
          </button>
          {authError && <span className="error-msg" style={{ fontSize: '0.82rem', maxWidth: 260 }}>{authError}</span>}
          {token ? (
            <>
              <div className="nav-user">
                <div className="nav-avatar">{initials}</div>
                <span>Hello, <strong>{firstName}</strong></span>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={handleLogout}>Sign out</button>
            </>
          ) : (
            <>
              <button className="btn btn-ghost btn-sm" onClick={() => startAuthUiFlow(AUTH_UI_LOGIN_PATH)} disabled={authRedirectLoading}>
                Sign in
              </button>
              <button className="btn btn-primary btn-sm" onClick={() => startAuthUiFlow(AUTH_UI_REGISTER_PATH)} disabled={authRedirectLoading}>
                Get started
              </button>
            </>
          )}
        </div>
      </nav>

      {/* ── PAGE ────────────────────────────────── */}
      <div className="page">

        {/* ── FLOW INFO ───────────────────────── */}
        {flowInfo && <div className="flow-info" style={{ marginTop: '1rem' }}>{flowInfo}</div>}

        {/* ── HERO ────────────────────────────── */}
        <section className="hero">
          <div className="hero-glow hero-glow-a" />
          <div className="hero-glow hero-glow-b" />
          <div className="hero-content">
            <div className="hero-eyebrow">
              <span />
              🎶 Concerts · Festivals · Sports · Theatre
            </div>
            <h1>
              {token ? (
                <>Welcome back,<br /><em>{firstName}.</em></>
              ) : (
                <>Find events<br />you'll <em>love.</em></>
              )}
            </h1>
            <p className="hero-sub">
              {token
                ? 'Your tickets and orders are all here. Browse what\'s coming up!'
                : 'Browse, buy tickets, and go — it\'s that simple.'}
            </p>
            {!token && (
              <div className="hero-cta">
                <button className="btn btn-primary" onClick={() => startAuthUiFlow(AUTH_UI_REGISTER_PATH)} disabled={authRedirectLoading}>
                  Get started — it's free
                </button>
                <button className="btn btn-ghost" onClick={() => startAuthUiFlow(AUTH_UI_LOGIN_PATH)} disabled={authRedirectLoading}>
                  Sign in
                </button>
              </div>
            )}
          </div>
        </section>



        {/* ── EVENTS ──────────────────────────── */}
        <section className="events-section" id="events">
          <div className="section-header">
            <div>
              <h2>What's On 🔥</h2>
              <p>{events.length > 0 ? `${events.length} events to explore` : 'Check out what\'s coming up'}</p>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={fetchEvents}>↻ Refresh</button>
          </div>

          {loadingEvents ? (
            <div className="skeleton-grid">
              {[1, 2, 3].map((i) => <div key={i} className="skeleton-card" />)}
            </div>
          ) : (
            <div className="events-grid">
              {eventsError && <p className="error-msg">{eventsError}</p>}
              {events.length === 0 && !eventsError && (
                <div className="empty-state empty-state-card">
                  <div className="empty-state-emoji">🎪</div>
                  <p className="empty-state-title">No events yet</p>
                  <p>Something epic is coming soon — stay tuned!</p>
                </div>
              )}
              {events.slice(0, 9).map((ev) => {
                const qty = quantityByEvent[ev.id] || 1;
                const buyingThis = checkoutLoadingEventId === ev.id;
                const eventStatus = String(ev.status || '').toLowerCase();
                const isBuyableEvent = eventStatus === 'published';
                const inWishlist = Boolean(wishlistByEvent[ev.id]);
                return (
                  <article key={ev.id} className="event-card">
                    <div className="event-card-banner">
                      <div className="event-card-banner-bg" style={{ background: getBannerGradient(ev.id || ev.name) }} />
                      <div className="event-card-banner-overlay" />
                      <div className="event-card-status">
                        <span className={statusClass(ev.status)}>{ev.status || 'draft'}</span>
                      </div>
                    </div>

                    <div className="event-card-body">
                      <div className="event-card-title-row">
                        <div className="event-card-title">{ev.name || 'Unnamed Event'}</div>
                        <button
                          className={`wishlist-toggle ${inWishlist ? 'active' : ''}`}
                          onClick={() => toggleWishlist(ev)}
                          type="button"
                          title={inWishlist ? 'Remove from wishlist' : 'Add to wishlist'}
                        >
                          <IconHeart filled={inWishlist} />
                        </button>
                      </div>
                      {ev.description && <p className="event-card-desc">{ev.description}</p>}

                      <div className="event-card-meta">
                        {ev.venue && (
                          <div className="event-card-meta-row">
                            <IconPin />
                            {ev.venue}
                          </div>
                        )}
                        <div className="event-card-meta-row">
                          <IconCal />
                          {formatDate(ev.date)}
                        </div>
                        {isPrivilegedUser && ev.id && (
                          <div className="event-card-meta-row" style={{ display: 'block', wordBreak: 'break-all', fontFamily: 'monospace' }}>
                            UUID: {ev.id}
                            <button
                              className="btn btn-ghost btn-sm"
                              style={{ marginLeft: '0.5rem', padding: '0.2rem 0.45rem', fontSize: '0.7rem' }}
                              onClick={() => copyEventUuid(ev.id)}
                              type="button"
                            >
                              Copy
                            </button>
                          </div>
                        )}
                      </div>

                      <div className="event-card-footer">
                        <div className="event-price">
                          <span className="event-price-label">From</span>
                          <span className="event-price-value">€15.00</span>
                        </div>

                        <div className="event-buy-group">
                          <div className="qty-stepper">
                            <button onClick={() => stepQty(ev.id, -1)}>−</button>
                            <span>{qty}</span>
                            <button onClick={() => stepQty(ev.id, +1)}>+</button>
                          </div>
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => addToCart(ev)}
                            disabled={!isBuyableEvent}
                            title={!isBuyableEvent ? `Event status: ${eventStatus || 'unknown'} (not purchasable)` : 'Add selected quantity to cart'}
                          >
                            Add
                          </button>
                          <button
                            className="btn btn-primary btn-sm"
                            onClick={() => handleCheckout(ev.id)}
                            disabled={!token || buyingThis || !isBuyableEvent}
                            title={!token ? 'Sign in to buy' : (!isBuyableEvent ? `Event status: ${eventStatus || 'unknown'} (not purchasable)` : undefined)}
                          >
                            {buyingThis ? '…' : token ? 'Buy' : '🔒'}
                          </button>
                        </div>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}


        </section>

        {/* ── WISHLIST ───────────────────────── */}
        <section className="wishlist-section" id="wishlist">
          <div className="section-header">
            <div>
              <h2>Your Wishlist ♡</h2>
              <p>{wishlistCount > 0 ? `${wishlistCount} saved event(s)` : 'Save events and come back later'}</p>
            </div>
          </div>

          {wishlistItems.length === 0 ? (
            <div className="empty-state empty-state-card">
              <div className="empty-state-emoji">💫</div>
              <p className="empty-state-title">No wishlist items yet</p>
              <p>Tap the heart on an event card to save it.</p>
            </div>
          ) : (
            <div className="wishlist-list">
              {wishlistItems.map((item) => {
                const itemStatus = String(item?.status || '').toLowerCase();
                const canMoveToCart = itemStatus === 'published';
                return (
                  <div className="wishlist-item" key={item.event_id}>
                    <div className="wishlist-item-main">
                      <div className="wishlist-item-title">{item.name || 'Unnamed event'}</div>
                      <div className="wishlist-item-meta">
                        {item.venue ? `${item.venue} · ` : ''}
                        {formatDate(item.date)}
                      </div>
                    </div>
                    <div className="wishlist-item-actions">
                      <span className={statusClass(item.status)}>{item.status || 'draft'}</span>
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => moveWishlistItemToCart(item)}
                        disabled={!canMoveToCart}
                        title={!canMoveToCart ? `Event status: ${itemStatus || 'unknown'} (not purchasable)` : 'Move to cart'}
                      >
                        Move to Cart
                      </button>
                      <button className="btn btn-ghost btn-sm" onClick={() => removeWishlistItem(item.event_id)}>Remove</button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* ── CART ───────────────────────────── */}
        <section className="cart-section" id="cart">
          <div className="section-header">
            <div>
              <h2>Your Cart 🛒</h2>
              <p>{cartTicketCount > 0 ? `${cartTicketCount} ticket(s) selected` : 'Add events to start your checkout'}</p>
            </div>
          </div>

          {cartItems.length === 0 ? (
            <div className="empty-state empty-state-card">
              <div className="empty-state-emoji">🧺</div>
              <p className="empty-state-title">Your cart is empty</p>
              <p>Pick an event and click Add to Cart to build your order.</p>
            </div>
          ) : (
            <div className="cart-card">
              <div className="cart-list">
                {cartItems.map((item) => {
                  const lineTotal = Number(item.quantity || 0) * Number(item.amount_cents_per_ticket || 0);
                  return (
                    <div className="cart-item" key={item.event_id}>
                      <div className="cart-item-main">
                        <div className="cart-item-title">{item.name || 'Unnamed event'}</div>
                        <div className="cart-item-meta">Event ID: {item.event_id?.slice(0, 8)}…</div>
                      </div>
                      <div className="cart-item-actions">
                        <div className="qty-stepper">
                          <button onClick={() => setCartItemQuantity(item.event_id, Number(item.quantity || 1) - 1)}>−</button>
                          <span>{item.quantity}</span>
                          <button onClick={() => setCartItemQuantity(item.event_id, Number(item.quantity || 1) + 1)}>+</button>
                        </div>
                        <div className="cart-item-price">€{(lineTotal / 100).toFixed(2)}</div>
                        <button className="btn btn-ghost btn-sm" onClick={() => removeCartItem(item.event_id)}>Remove</button>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="cart-footer">
                <div className="cart-total">
                  <span>Total</span>
                  <strong>{cartTotalLabel}</strong>
                </div>
                <button className="btn btn-primary" onClick={handleCartCheckout} disabled={cartCheckoutLoading || !token}>
                  {cartCheckoutLoading ? 'Redirecting…' : (token ? 'Proceed to Payment' : 'Sign in to checkout')}
                </button>
              </div>
            </div>
          )}
        </section>

        {/* ── ACCOUNT (logged in) ──────────────── */}
        {token && (
          <section className="account-section reveal">
            <div className="section-header">
              <div><h2>My Account</h2></div>
            </div>

            <div className="account-tabs">
              <button className={`account-tab ${activeTab === 'profile' ? 'active' : ''}`} onClick={() => setActiveTab('profile')}>Profile</button>
              <button className={`account-tab ${activeTab === 'orders' ? 'active' : ''}`} onClick={() => setActiveTab('orders')}>Orders</button>
              <button className={`account-tab ${activeTab === 'refunds' ? 'active' : ''}`} onClick={() => setActiveTab('refunds')}>Refunds</button>
              {isPrivilegedUser && (
                <button className={`account-tab ${activeTab === 'manage' ? 'active' : ''}`} onClick={() => setActiveTab('manage')}>Manage</button>
              )}
            </div>

            {/* ── PROFILE TAB ─────────────── */}
            {activeTab === 'profile' && (
              <div className="profile-grid reveal">
                <div className="account-card">
                  <h3>Your Info</h3>
                  <div className="profile-identity">
                    <div className="profile-avatar">{initials}</div>
                    <div>
                      <div className="profile-name">{profileLoading ? 'Loading…' : (user?.full_name || firstName)}</div>
                      <div className="profile-email">{user?.email || '—'}</div>
                    </div>
                  </div>
                  <div className="info-row">
                    <span>Role</span>
                    <strong style={{ textTransform: 'capitalize' }}>{user?.role || '—'}</strong>
                  </div>
                  {profileError && <p className="error-msg" style={{ marginTop: '0.5rem' }}>{profileError}</p>}
                  <div style={{ marginTop: '0.75rem' }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => fetchProfile(token)}>↻ Refresh</button>
                  </div>
                </div>

                <div className="account-card">
                  <h3>Payment Wallet</h3>
                  <div className={`wallet-status ${!paymentAccount?.exists ? 'wallet-not-ready' : ''}`}>
                    <div className="wallet-status-text">
                      <p>{paymentAccountLoading ? 'Checking…' : paymentAccount?.exists ? '✓ Wallet active' : 'Wallet not set up'}</p>
                      <small>{paymentAccount?.exists ? 'Ready for checkout' : 'Set up your wallet at APalPay to buy tickets'}</small>
                    </div>
                    {paymentAccount?.exists && walletActionUrl && (
                      <a className="btn btn-ghost btn-sm" href={walletActionUrl}>Open wallet →</a>
                    )}
                  </div>
                  {paymentAccountError && <p className="error-msg" style={{ marginTop: '0.5rem' }}>{paymentAccountError}</p>}
                </div>
              </div>
            )}

            {/* ── ORDERS TAB ──────────────── */}
            {activeTab === 'orders' && (
              <div className="reveal">
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '0.9rem' }}>
                  <button className="btn btn-ghost btn-sm" onClick={() => fetchPayments(token)}>↻ Refresh orders</button>
                </div>
                {paymentsLoading && (
                  <div className="skeleton-grid" style={{ gridTemplateColumns: '1fr' }}>
                    {[1, 2].map((i) => <div key={i} className="skeleton-card" style={{ height: 80 }} />)}
                  </div>
                )}
                {paymentsError && <p className="error-msg">{paymentsError}</p>}
                {!paymentsLoading && paymentItems.length === 0 && (
                  <div className="empty-state">No orders yet. Buy tickets from the events above.</div>
                )}
                <div className="orders-list">
                  {paymentItems.slice(0, 8).map((p) => (
                    <div key={p.id} className="order-card">
                      <div className="order-main">
                        <div className="order-amount">{p.amount} {p.currency?.toUpperCase?.() || ''}</div>
                        <div className="order-date">{formatDate(p.created_at)}</div>
                        <div className="order-id">{p.id?.slice(0, 8)}…</div>
                      </div>
                      <div className="order-actions">
                        <span className={statusClass(p.status)}>{p.status}</span>
                        {p.status === 'succeeded' && (
                          <button className="btn btn-ghost btn-sm" onClick={() => downloadReceipt(p.id)}>📄 Receipt</button>
                        )}
                        <button className="btn btn-ghost btn-sm" onClick={() => triggerRefund(p.id)}>Refund</button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── REFUNDS TAB ─────────────── */}
            {activeTab === 'refunds' && (
              <div className="reveal">
                <div className="refund-form">
                  <h3>Request a Refund</h3>
                  <div className="form-field">
                    <label>Order ID</label>
                    <input
                      value={refundPaymentId}
                      onChange={(e) => setRefundPaymentId(e.target.value)}
                      placeholder="Select from Orders tab or paste here"
                    />
                  </div>
                  <div className="form-field">
                    <label>Ticket IDs (optional, comma-separated)</label>
                    <input
                      value={refundTicketIds}
                      onChange={(e) => setRefundTicketIds(e.target.value)}
                      placeholder="Leave blank to refund all tickets"
                    />
                    <span className="form-hint">Leave blank to refund the full order.</span>
                  </div>
                  <button className="btn btn-primary" onClick={handleRefund} style={{ width: '100%' }}>
                    Request refund
                  </button>
                  {refundError && <p className="error-msg" style={{ marginTop: '0.6rem' }}>{refundError}</p>}
                  {refundResult && (
                    <p className="form-hint" style={{ marginTop: '0.6rem' }}>
                      Refund status: <span className={statusClass(refundResult.status)}>{refundResult.status}</span>
                    </p>
                  )}
                  {paymentItems.length > 0 && (
                    <div className="quick-pick" style={{ marginTop: '1rem' }}>
                      <p>Quick select a recent order:</p>
                      <div className="quick-pick-list">
                        {paymentItems.slice(0, 4).map((p) => (
                          <button key={p.id} className="chip-btn" onClick={() => setRefundPaymentId(p.id)}>
                            {p.id.slice(0, 8)}… · {p.amount} {p.currency?.toUpperCase?.() || ''}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ── MANAGE TAB (admin/promoter) ─ */}
            {activeTab === 'manage' && isPrivilegedUser && (
              <div className="reveal" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <details className="manager-section">
                  <summary>Create Event</summary>
                  <div className="manager-inner">
                    <div className="manager-block">
                      <div className="manager-grid">
                        <div className="form-field" style={{ marginBottom: 0 }}>
                          <label>Event name</label>
                          <input value={managerEventName} onChange={(e) => setManagerEventName(e.target.value)} placeholder="Summer Concert" />
                        </div>
                        <div className="form-field" style={{ marginBottom: 0 }}>
                          <label>Date & time</label>
                          <input type="datetime-local" value={managerEventDate} onChange={(e) => setManagerEventDate(e.target.value)} />
                        </div>
                        <div className="form-field" style={{ marginBottom: 0 }}>
                          <label>Venue</label>
                          <input value={managerEventVenue} onChange={(e) => setManagerEventVenue(e.target.value)} placeholder="Lisbon Arena" />
                        </div>
                        <div className="form-field" style={{ marginBottom: 0 }}>
                          <label>Description</label>
                          <input value={managerEventDescription} onChange={(e) => setManagerEventDescription(e.target.value)} placeholder="Short description…" />
                        </div>
                      </div>
                      <div className="btn-row">
                        <button className="btn btn-primary btn-sm" onClick={handleCreateEvent} disabled={managerLoading}>
                          {managerLoading ? 'Creating…' : 'Create event'}
                        </button>
                      </div>
                    </div>
                  </div>
                </details>

                <details className="manager-section">
                  <summary>Manage Event</summary>
                  <div className="manager-inner">
                    <div className="manager-block">
                      <div className="form-field" style={{ marginBottom: '0.75rem' }}>
                        <label>Pick Existing Event</label>
                        <select
                          value={managerTargetEventId}
                          onChange={(e) => {
                            setManagerTargetEventId(e.target.value);
                            if (!managerBatchEventId) setManagerBatchEventId(e.target.value);
                          }}
                        >
                          <option value="">Select event…</option>
                          {managerEventChoices.map((choice) => (
                            <option key={choice.id} value={choice.id}>{choice.label}</option>
                          ))}
                        </select>
                      </div>
                      <div className="manager-grid">
                        <div className="form-field" style={{ marginBottom: 0 }}>
                          <label>Event ID</label>
                          <input value={managerTargetEventId} onChange={(e) => setManagerTargetEventId(e.target.value)} placeholder="Event UUID" />
                        </div>
                        <div className="form-field" style={{ marginBottom: 0 }}>
                          <label>Status</label>
                          <select value={managerTargetEventStatus} onChange={(e) => setManagerTargetEventStatus(e.target.value)}>
                            <option value="draft">Draft</option>
                            <option value="published">Published</option>
                            <option value="cancelled">Cancelled</option>
                            <option value="sold_out">Sold out</option>
                            <option value="completed">Completed</option>
                          </select>
                        </div>
                      </div>
                      <div className="btn-row">
                        <button className="btn btn-ghost btn-sm" onClick={handleUpdateEventStatus} disabled={managerLoading}>Update status</button>
                        <button className="btn btn-sm" style={{ background: 'rgba(248,113,113,0.15)', color: '#fca5a5', border: '1px solid rgba(248,113,113,0.3)' }} onClick={handleDeleteEvent} disabled={managerLoading}>Delete event</button>
                      </div>
                    </div>
                  </div>
                </details>

                <details className="manager-section">
                  <summary>Ticket Batch</summary>
                  <div className="manager-inner">
                    <div className="manager-block">
                      <div className="form-field" style={{ marginBottom: '0.75rem' }}>
                        <label>Pick Existing Event</label>
                        <select value={managerBatchEventId} onChange={(e) => setManagerBatchEventId(e.target.value)}>
                          <option value="">Select event…</option>
                          {managerEventChoices.map((choice) => (
                            <option key={choice.id} value={choice.id}>{choice.label}</option>
                          ))}
                        </select>
                      </div>
                      <div className="manager-grid">
                        <div className="form-field" style={{ marginBottom: 0 }}>
                          <label>Event ID</label>
                          <input value={managerBatchEventId} onChange={(e) => setManagerBatchEventId(e.target.value)} placeholder="Event UUID" />
                        </div>
                        <div className="form-field" style={{ marginBottom: 0 }}>
                          <label>Category</label>
                          <input value={managerBatchCategory} onChange={(e) => setManagerBatchCategory(e.target.value)} placeholder="General / VIP" />
                        </div>
                        <div className="form-field" style={{ marginBottom: 0 }}>
                          <label>Price (EUR)</label>
                          <input type="number" min="0" step="0.01" value={managerBatchPrice} onChange={(e) => setManagerBatchPrice(e.target.value)} />
                        </div>
                        <div className="form-field" style={{ marginBottom: 0 }}>
                          <label>Quantity</label>
                          <input type="number" min="1" max="50000" value={managerBatchQuantity} onChange={(e) => setManagerBatchQuantity(e.target.value)} />
                        </div>
                      </div>
                      <div className="btn-row">
                        <button className="btn btn-primary btn-sm" onClick={handleCreateTicketBatch} disabled={managerLoading}>Create batch</button>
                      </div>
                    </div>
                  </div>
                </details>

                <details className="manager-section">
                  <summary>Ticket Lifecycle</summary>
                  <div className="manager-inner">
                    <div className="manager-block">
                      <div className="form-field" style={{ marginBottom: 0 }}>
                        <label>Ticket ID</label>
                        <input value={managerTicketId} onChange={(e) => setManagerTicketId(e.target.value)} placeholder="Ticket UUID" />
                      </div>
                      <div className="btn-row">
                        {['reserve', 'sell', 'use', 'cancel'].map((action) => (
                          <button key={action} className="btn btn-ghost btn-sm" onClick={() => handleTicketLifecycleAction(action)} disabled={managerLoading} style={{ textTransform: 'capitalize' }}>
                            {action}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </details>

                {managerError && <p className="error-msg">{managerError}</p>}
              </div>
            )}
          </section>
        )}

        {/* ── SIGN IN GATE (logged out) ────────── */}
        {!token && (
          <section style={{ marginBottom: '3rem' }}>
            <div className="signin-gate">
              <div className="signin-gate-emoji">🎉</div>
              <div>
                <p className="signin-gate-title">
                  Don't miss out!
                </p>
                <p>Join thousands of fans — create your free account and never miss an event.</p>
              </div>
              <div className="signin-gate-btns">
                <button className="btn btn-primary btn-lg" onClick={() => startAuthUiFlow(AUTH_UI_REGISTER_PATH)} disabled={authRedirectLoading}>
                  Join FlashSale — it's free
                </button>
                <button className="btn btn-ghost" onClick={() => startAuthUiFlow(AUTH_UI_LOGIN_PATH)} disabled={authRedirectLoading}>
                  Already have an account? Sign in
                </button>
              </div>
            </div>
          </section>
        )}
      </div>

      {/* ── TOAST ───────────────────────────────── */}
      {toast && (
        <div className="toast-wrap">
          <div className={`toast toast-${toast.type}`}>{toast.text}</div>
        </div>
      )}
    </>
  );
}

export default App;