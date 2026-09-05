import { useCallback, useEffect, useMemo, useState } from "react";
import { createAgentKey, signAgentRequest } from "./request-signing.js";

const DEFAULT_INTENT =
  "Buy 3 chairs, max ₹25,000, from Merchant A only, no substitutions, expires in 20 minutes.";

const emptyItem = () => ({ sku: "", unit_price: 0, quantity: 1 });

const SCENARIOS = {
  allow: {
    label: "1 · ALLOW",
    title: "Valid payment",
    nonce: "abc123",
    cart: {
      merchant_id: "Merchant A",
      items: [{ sku: "CHAIR1", unit_price: 7500, quantity: 3 }],
      shipping: 1200,
      tax: 0,
      currency: "INR",
    },
  },
  reconsent: {
    label: "2 · RECONSENT",
    title: "Budget violation",
    nonce: "budget-violation-001",
    cart: {
      merchant_id: "Merchant A",
      items: [
        { sku: "CHAIR1", unit_price: 7500, quantity: 3 },
        { sku: "WARRANTY", unit_price: 2500, quantity: 1 },
      ],
      shipping: 1200,
      tax: 1000,
      currency: "INR",
    },
  },
  merchant: {
    label: "3 · BLOCK",
    title: "Wrong merchant",
    nonce: "wrong-merchant-001",
    cart: {
      merchant_id: "Merchant B",
      items: [{ sku: "CHAIR1", unit_price: 7500, quantity: 2 }],
      shipping: 0,
      tax: 0,
      currency: "INR",
    },
  },
  replay: {
    label: "4 · BLOCK REPLAY",
    title: "Replay Scenario 1",
    nonce: "abc123",
    cart: {
      merchant_id: "Merchant A",
      items: [{ sku: "CHAIR1", unit_price: 7500, quantity: 3 }],
      shipping: 1200,
      tax: 0,
      currency: "INR",
    },
  },
};

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function money(value, currency = "INR") {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(Number(value) || 0);
}

function shortHash(value) {
  if (!value) return "GENESIS";
  const text = String(value);
  return text.length > 16 ? `${text.slice(0, 8)}…${text.slice(-6)}` : text;
}

function normalizeEvents(payload) {
  if (Array.isArray(payload)) return payload;
  return payload?.events || payload?.evidence || payload?.event_log || [];
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail = body?.detail || body?.message || body || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return body;
}

function StepHeader({ number, title, detail, complete }) {
  return (
    <div className="step-header">
      <span className={`step-number ${complete ? "complete" : ""}`}>
        {complete ? "✓" : number}
      </span>
      <div>
        <h2>{title}</h2>
        <p>{detail}</p>
      </div>
    </div>
  );
}

function JsonBlock({ value, label }) {
  return (
    <div className="json-wrap">
      {label && <span className="eyebrow">{label}</span>}
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

function EvidencePanel({ authorizationId, events, error, loading, onRefresh }) {
  return (
    <aside className="evidence-panel" aria-label="Evidence chain">
      <div className="evidence-heading">
        <div>
          <span className="eyebrow">Live audit trail</span>
          <h2>Evidence chain</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          onClick={onRefresh}
          disabled={!authorizationId || loading}
          aria-label="Refresh evidence"
        >
          ↻
        </button>
      </div>

      {!authorizationId && (
        <div className="empty-state">
          <span className="chain-mark">◇</span>
          <p>Confirm a mandate to start the tamper-evident event chain.</p>
        </div>
      )}

      {authorizationId && events.length === 0 && !error && (
        <div className="empty-state compact">
          <span className="pulse-dot" />
          <p>{loading ? "Fetching evidence…" : "Waiting for the first event…"}</p>
        </div>
      )}

      {error && <p className="panel-error">Evidence unavailable: {error}</p>}

      <ol className="evidence-list">
        {events.map((event, index) => {
          const previous = event.prev_hash || event.previous_hash;
          const current = event.chain_hash || event.hash || event.event_hash;
          return (
            <li key={event.id || current || `${event.event_type}-${index}`}>
              <span className="event-node">{index + 1}</span>
              <div className="event-card">
                <div className="event-title">
                  <strong>{event.event_type || event.type || "EVENT"}</strong>
                  <span>{event.actor || event.actor_id || "system"}</span>
                </div>
                <time>{event.timestamp || event.created_at || "Timestamp pending"}</time>
                <div className="hash-chain" title={`${previous || "GENESIS"} → ${current || "pending"}`}>
                  <code>{shortHash(previous)}</code>
                  <span>→</span>
                  <code>{shortHash(current) || "pending"}</code>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}

export default function App() {
  const [intent, setIntent] = useState(DEFAULT_INTENT);
  const [mandateText, setMandateText] = useState("");
  const [confidence, setConfidence] = useState(null);
  const [authorization, setAuthorization] = useState(null);
  const [agentKey, setAgentKey] = useState(null);
  const [replayPayload, setReplayPayload] = useState(null);
  const [canonicalEnvelope, setCanonicalEnvelope] = useState(null);
  const [scenarioKey, setScenarioKey] = useState("allow");
  const [cart, setCart] = useState(clone(SCENARIOS.allow.cart));
  const [nonce, setNonce] = useState(SCENARIOS.allow.nonce);
  const [agentId, setAgentId] = useState("shopping-agent-demo");
  const [decision, setDecision] = useState(null);
  const [payment, setPayment] = useState(null);
  const [events, setEvents] = useState([]);
  const [evidenceError, setEvidenceError] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const authorizationId = authorization?.authorization_id;

  const total = useMemo(
    () =>
      cart.items.reduce(
        (sum, item) => sum + Number(item.unit_price || 0) * Number(item.quantity || 0),
        0,
      ) + Number(cart.shipping || 0) + Number(cart.tax || 0),
    [cart],
  );

  const refreshEvidence = useCallback(async () => {
    if (!authorizationId) return;
    try {
      const payload = await api(`/transactions/${authorizationId}/evidence`);
      setEvents(normalizeEvents(payload));
      setEvidenceError("");
    } catch (fetchError) {
      setEvidenceError(fetchError.message);
    }
  }, [authorizationId]);

  useEffect(() => {
    if (!authorizationId) return undefined;
    refreshEvidence();
    const timer = window.setInterval(refreshEvidence, 2500);
    return () => window.clearInterval(timer);
  }, [authorizationId, refreshEvidence]);

  function resetDownstream() {
    setAgentKey(null);
    setReplayPayload(null);
    setAuthorization(null);
    setCanonicalEnvelope(null);
    setDecision(null);
    setPayment(null);
    setEvents([]);
    setEvidenceError("");
  }

  async function compileIntent() {
    setBusy("compile");
    setError("");
    try {
      const result = await api("/intent/compile", {
        method: "POST",
        body: JSON.stringify({ intent_text: intent }),
      });
      setMandateText(JSON.stringify(result.mandate_proposal, null, 2));
      setConfidence(result.confidence);
      resetDownstream();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy("");
    }
  }

  async function confirmMandate() {
    setBusy("confirm");
    setError("");
    try {
      const mandate = JSON.parse(mandateText);
      const approvedAgentId = mandate.agent_id || agentId;
      const key = await createAgentKey();
      const result = await api("/authorization/confirm", {
        method: "POST",
        body: JSON.stringify({ mandate: { ...mandate, agent_id: approvedAgentId }, agent_public_key: key.publicKey }),
      });
      setAgentId(approvedAgentId);
      setAgentKey(key.privateKey);
      setReplayPayload(null);
      setAuthorization(result);
      let envelope = result.canonical_envelope || result.envelope;
      if (!envelope) {
        try {
          const transaction = await api(`/transactions/${result.authorization_id}`);
          envelope = transaction.mandate;
        } catch {
          envelope = {
            authorization_id: result.authorization_id,
            status: result.status,
            mandate,
            public_key: result.public_key,
            evidence_hash: result.evidence_hash,
          };
        }
      }
      setCanonicalEnvelope(envelope);
      setDecision(null);
      setPayment(null);
    } catch (requestError) {
      setError(requestError instanceof SyntaxError ? "Mandate JSON is not valid." : requestError.message);
    } finally {
      setBusy("");
    }
  }

  function chooseScenario(key) {
    const selected = SCENARIOS[key];
    setScenarioKey(key);
    setCart(clone(selected.cart));
    setNonce(selected.nonce);
    setDecision(null);
    setPayment(null);
    setError("");
  }

  function updateCartField(field, value) {
    setCart((current) => ({ ...current, [field]: value }));
  }

  function updateItem(index, field, value) {
    setCart((current) => ({
      ...current,
      items: current.items.map((item, itemIndex) =>
        itemIndex === index ? { ...item, [field]: value } : item,
      ),
    }));
  }

  function removeItem(index) {
    setCart((current) => ({
      ...current,
      items: current.items.filter((_, itemIndex) => itemIndex !== index),
    }));
  }

  async function submitCart() {
    setBusy("agent");
    setError("");
    setPayment(null);
    try {
      if (!agentKey) throw new Error("Confirm a mandate to create the agent signing key.");
      if (scenarioKey === "replay" && !replayPayload) throw new Error("Submit Scenario 1 before replaying its signed request.");
      const payload = {
        authorization_id: authorizationId,
        nonce,
        agent_id: agentId,
        cart: {
          ...cart,
          items: cart.items.map((item) => ({
            sku: item.sku,
            unit_price: Number(item.unit_price),
            quantity: Number(item.quantity),
          })),
          shipping: Number(cart.shipping),
          tax: Number(cart.tax),
          total,
        },
      };
      const signed = scenarioKey === "replay" ? replayPayload : await signAgentRequest(payload, agentKey);
      if (scenarioKey === "allow") setReplayPayload(signed);
      const result = await api("/agent/request", {
        method: "POST",
        body: JSON.stringify(signed),
      });
      setDecision(result);
      await refreshEvidence();
    } catch (requestError) {
      setDecision(null);
      setError(requestError.message);
    } finally {
      setBusy("");
    }
  }

  async function executePayment() {
    if (decision?.decision !== "ALLOW") return;
    setBusy("payment");
    setError("");
    try {
      const result = await api("/payment/execute", {
        method: "POST",
        body: JSON.stringify({
          authorization_id: authorizationId,
          request_id: decision.request_id,
        }),
      });
      setPayment(result);
      await refreshEvidence();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy("");
    }
  }

  const decisionClass = decision?.decision?.toLowerCase();

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark" aria-hidden="true"><span /></div>
        <div>
          <p className="product-name">Razorpay Agentic Firewall</p>
          <p className="product-subtitle">Transaction authority, enforced at checkout</p>
        </div>
        <div className="api-status"><span /> API · 127.0.0.1:8000</div>
      </header>

      <div className="layout">
        <main>
          <section className="hero">
            <span className="eyebrow">Live policy demo</span>
            <h1>See exactly what the agent is allowed to buy.</h1>
            <p>Turn intent into a signed mandate, inspect the cart, then let deterministic rules decide.</p>
          </section>

          {error && <div className="error-banner" role="alert"><strong>Request failed</strong><span>{error}</span></div>}

          <section className="step-card">
            <StepHeader number="1" title="State the intent" detail="Natural language becomes editable constraints." complete={Boolean(mandateText)} />
            <label htmlFor="intent">Purchase intent</label>
            <textarea id="intent" className="intent-input" rows="4" value={intent} onChange={(event) => setIntent(event.target.value)} />
            <div className="action-row">
              <button className="primary" type="button" onClick={compileIntent} disabled={!intent.trim() || Boolean(busy)}>
                {busy === "compile" ? "Compiling…" : "Compile intent"}
              </button>
              {confidence !== null && <span className="confidence">Compiler confidence {Math.round(confidence * 100)}%</span>}
            </div>
          </section>

          {mandateText && (
            <section className="step-card">
              <StepHeader number="2" title="Review and sign" detail="Edit any field before the mandate becomes binding." complete={Boolean(authorizationId)} />
              <label htmlFor="mandate">Mandate proposal · JSON</label>
              <textarea id="mandate" className="json-editor" rows="16" value={mandateText} onChange={(event) => { setMandateText(event.target.value); resetDownstream(); }} spellCheck="false" />
              <button className="primary" type="button" onClick={confirmMandate} disabled={Boolean(busy)}>
                {busy === "confirm" ? "Signing…" : "Confirm & Sign Mandate"}
              </button>

              {authorizationId && (
                <div className="signed-result">
                  <div className="auth-id-row">
                    <span className="signed-chip">Signed</span>
                    <div><span>Authorization ID</span><strong>{authorizationId}</strong></div>
                  </div>
                  <JsonBlock label="Canonical authorization envelope" value={canonicalEnvelope} />
                </div>
              )}
            </section>
          )}

          {authorizationId && (
            <section className="step-card cart-step">
              <StepHeader number="3" title="Submit the agent cart" detail="Use a demo preset or edit the request by hand." complete={Boolean(decision)} />
              <div className="preset-grid" aria-label="Demo scenarios">
                {Object.entries(SCENARIOS).map(([key, scenario]) => (
                  <button key={key} className={`preset ${scenarioKey === key ? "active" : ""}`} type="button" onClick={() => chooseScenario(key)}>
                    <strong>{scenario.label}</strong><span>{scenario.title}</span>
                  </button>
                ))}
              </div>

              <div className="form-grid">
                <label>Merchant ID<input value={cart.merchant_id} onChange={(event) => updateCartField("merchant_id", event.target.value)} /></label>
                <label>Agent ID<input value={agentId} onChange={(event) => setAgentId(event.target.value)} /></label>
                <label className="wide">Nonce<input value={nonce} onChange={(event) => setNonce(event.target.value)} /></label>
              </div>

              <div className="items-heading"><label>Line items</label><button className="text-button" type="button" onClick={() => setCart((current) => ({ ...current, items: [...current.items, emptyItem()] }))}>+ Add item</button></div>
              <div className="items-table">
                <div className="items-row items-labels"><span>SKU</span><span>Unit price</span><span>Quantity</span><span>Subtotal</span><span /></div>
                {cart.items.map((item, index) => (
                  <div className="items-row" key={`${index}-${item.sku}`}>
                    <input aria-label={`Item ${index + 1} SKU`} value={item.sku} onChange={(event) => updateItem(index, "sku", event.target.value)} />
                    <input aria-label={`Item ${index + 1} unit price`} type="number" min="0" value={item.unit_price} onChange={(event) => updateItem(index, "unit_price", event.target.value)} />
                    <input aria-label={`Item ${index + 1} quantity`} type="number" min="1" value={item.quantity} onChange={(event) => updateItem(index, "quantity", event.target.value)} />
                    <strong>{money(Number(item.unit_price) * Number(item.quantity), cart.currency)}</strong>
                    <button className="remove-button" type="button" onClick={() => removeItem(index)} disabled={cart.items.length === 1} aria-label={`Remove item ${index + 1}`}>×</button>
                  </div>
                ))}
              </div>

              <div className="totals">
                <label>Shipping<input type="number" min="0" value={cart.shipping} onChange={(event) => updateCartField("shipping", event.target.value)} /></label>
                <label>Tax<input type="number" min="0" value={cart.tax} onChange={(event) => updateCartField("tax", event.target.value)} /></label>
                <div className="grand-total"><span>Request total</span><strong>{money(total, cart.currency)}</strong></div>
              </div>

              <button className="firewall-button" type="button" onClick={submitCart} disabled={Boolean(busy) || !nonce || !agentId || cart.items.length === 0}>
                {busy === "agent" ? "Evaluating cart…" : "Submit to Agent Firewall"}<span>→</span>
              </button>
            </section>
          )}

          {decision && (
            <section className={`decision-card ${decisionClass}`} aria-live="polite">
              <span className="eyebrow">Deterministic policy decision</span>
              <div className="decision-heading">
                <span className={`decision-badge ${decisionClass}`}>{decision.decision}</span>
                <div><span>Reason code</span><strong>{decision.reason || "ALL_CHECKS_PASSED"}</strong></div>
              </div>
              <p className="decision-message">{decision.message || (decision.decision === "ALLOW" ? "The cart matches every signed constraint." : "The cart violates the signed mandate.")}</p>
              <div className="decision-footer">
                <span>Request ID · {decision.request_id}</span>
                <button className="payment-button" type="button" onClick={executePayment} disabled={decision.decision !== "ALLOW" || Boolean(busy) || Boolean(payment)}>
                  {payment ? "Order created" : busy === "payment" ? "Creating order…" : "Execute payment"}
                </button>
              </div>
              {payment && (
                <div className="payment-result"><span>Razorpay order created</span><strong>{payment.order_id}</strong><span>{money(payment.amount, payment.currency)}</span></div>
              )}
            </section>
          )}
        </main>

        <EvidencePanel authorizationId={authorizationId} events={events} error={evidenceError} loading={busy === "confirm"} onRefresh={refreshEvidence} />
      </div>
    </div>
  );
}
