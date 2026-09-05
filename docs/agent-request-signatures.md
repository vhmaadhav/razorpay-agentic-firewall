# Agent request signatures

`POST /authorization/confirm` now requires `agent_public_key`, a base64 encoded
32-byte Ed25519 public key. The approved `mandate.agent_id` defaults to
`demo-agent`. Confirmation embeds the request key in `agent.request_public_key`
and covers it with the mandate signature. `agent.public_key` continues to be
the mandate verification key. The keys are separate so possession of the agent
key cannot grant permission to change the mandate.

Every `/agent/request` must carry `agent_signature`. Missing signatures, invalid
signatures, and mismatched agent IDs return HTTP 401 with a `detail` object
containing `decision: BLOCK`, `reason`, and `message`. These requests append
`AGENT_REQUEST_REJECTED` evidence under the verifier's identity without consuming
the nonce, using the mandate, creating a payment, or changing a prior decision.
Valid signed requests continue to receive the existing policy response.

## Signing protocol

1. Normalize the cart with the `Cart` schema, including defaults for shipping,
   tax, currency, and `category: null` on items without a category.
2. Serialize this object as UTF-8 JSON with recursively sorted object keys,
   no whitespace, and Unicode characters unescaped. Preserve array order.

   ```json
   {
     "domain": "agent-request.v1",
     "authorization_id": "auth-...",
     "agent_id": "demo-agent",
     "nonce": "unique-per-authorization",
     "cart": {}
   }
   ```

3. Compute SHA-256 and encode the digest as lowercase hexadecimal.
4. Sign the ASCII hex string using Ed25519. Send the base64 signature in
   `agent_signature`. The signature itself is excluded from the signed object.

Python callers can use `app.crypto.agent_request.sign_request(payload, private_key)`.
The dashboard implements the same protocol with Web Crypto. It generates an
agent key on confirmation, keeps the private key in browser memory, and sends
only the public key to the server. Refreshing the page requires confirmation of
a new mandate. Replay resends the saved signed Scenario 1 payload exactly.

## Compatibility and trust boundary

Existing clients must enroll a public key at confirmation and sign requests.
Existing mandates must be confirmed again. There is no unsigned compatibility
bypass. The dashboard requires a browser with Ed25519 Web Crypto support on
localhost or HTTPS.

Confirmation remains the MVP's trusted operator endpoint. This change does not
add operator authentication or make that endpoint safe to expose publicly.
`/policy/evaluate` remains a stateless diagnostic and cannot create the persisted
decision required for payment execution.
