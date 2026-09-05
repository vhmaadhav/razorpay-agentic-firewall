# Agentic Authorization Firewall dashboard

This React app runs the four demo scenarios from `docs/spec.md` against the local FastAPI service. It does not contain mocked API data.

## Run locally

Start the backend from the repository root:

```powershell
uvicorn app.main:app --reload
```

In a second terminal:

```powershell
cd apps/dashboard
npm install
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Vite proxies requests under `/api` to `http://127.0.0.1:8000`, which avoids a separate CORS setup.

To point the app at another API, create `apps/dashboard/.env.local`:

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
```

The backend must allow the dashboard origin when a full URL is used instead of the Vite proxy.

## Demo sequence

1. Compile the default chair-purchase intent and review the generated mandate.
2. Confirm and sign the mandate.
3. Submit preset 1. It should return `ALLOW`; then execute the payment.
4. Submit preset 2 for `RECONSENT`, preset 3 for a wrong-merchant `BLOCK`, and preset 4 to replay preset 1 with nonce `abc123` for another `BLOCK`.

Preset 2 includes ₹1,000 tax because the amounts written in the demo script otherwise total ₹26,200, not its stated ₹27,200. The preset keeps the documented ₹22,500 chair subtotal, ₹1,200 shipping, and ₹2,500 warranty while matching the script's final total.

## Build

```powershell
npm run build
```

The production output is written to `apps/dashboard/dist/`.
