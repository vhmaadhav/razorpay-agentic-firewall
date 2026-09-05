// Web Crypto keeps the private agent key in memory, never in an API body.
export async function createAgentKey() {
  const pair = await crypto.subtle.generateKey("Ed25519", false, ["sign", "verify"]);
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
  return { privateKey: pair.privateKey, publicKey: btoa(String.fromCharCode(...raw)) };
}

function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sorted(value[key])]));
  }
  return value;
}

export async function signAgentRequest(payload, privateKey) {
  const cart = {
    ...payload.cart,
    shipping: payload.cart.shipping ?? 0,
    tax: payload.cart.tax ?? 0,
    currency: payload.cart.currency ?? "INR",
    items: payload.cart.items.map((item) => ({ ...item, category: item.category ?? null })),
  };
  const signable = {
    domain: "agent-request.v1", authorization_id: payload.authorization_id,
    agent_id: payload.agent_id, nonce: payload.nonce, cart,
  };
  const encoder = new TextEncoder();
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(JSON.stringify(sorted(signable)))));
  const hex = Array.from(hash, (byte) => byte.toString(16).padStart(2, "0")).join("");
  const signature = new Uint8Array(await crypto.subtle.sign("Ed25519", privateKey, encoder.encode(hex)));
  return { ...payload, cart, agent_signature: btoa(String.fromCharCode(...signature)) };
}
