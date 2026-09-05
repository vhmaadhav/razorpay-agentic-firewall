# Research Task: Verify & Refresh Competitive/Protocol Claims

You have web browsing access. This is a research task — produce a written report, not code.

## Context

I'm building a hackathon/buildathon project called the "Agentic Authorization
Firewall" for Razorpay: a PSP-level policy engine that checks an AI shopping
agent's final cart against a user-signed spending mandate (max amount,
allowed merchants/SKUs, expiry) before letting a payment go through. The
design doc makes a lot of specific factual claims about competing/adjacent
protocols and products — AP2, ACP, UCP, Visa's Trusted Agent Protocol,
Mastercard's Agent Pay / Verifiable Intent, UPI Reserve Pay, Stripe Issuing
for agents, PayPal Agentic Payments, Adyen, Pine Labs P3P. These claims were
written into the doc with citation markers like `[59][60]` that don't
actually resolve to anything I can check, so I have no idea if they're
accurate, outdated, or fabricated by whatever process produced the doc.

Full doc for context: `docs/spec.md` in
https://github.com/vhmaadhav/razorpay-agentic-firewall — specifically:
- §06 `06-protocol-mapping.md` (the protocol claims)
- §14 `14-competitive-validation.md` (the competitive comparison table)

## What I need

For each of these, tell me: **is this still accurate as of today, and what's
the actual primary source?**

1. **AP2 (Agent Payments Protocol)** — Google's spec for agent payments with
   "Checkout Mandate" / "Payment Mandate" verifiable credentials. Confirm it
   exists, who publishes it, what the actual mandate structure looks like,
   and whether "open" vs "closed" mandate terminology is real or something
   the doc invented.
2. **ACP (Agentic Commerce Protocol)** — attributed to OpenAI/Meta. Confirm
   this exists under this name, what it actually specifies re: payment
   delegation, and how mature it is (spec published? pilots running? just
   an announcement?).
3. **Visa Trusted Agent Protocol / Visa Intelligent Commerce** — confirm
   what's actually shipped vs. announced, and whether "agent signs an
   RFC9421 signature" is accurate or invented detail.
4. **Mastercard Agent Pay / Verifiable Intent** — same treatment: what's
   real, what's roadmap, what's the actual mechanism.
5. **UPI Reserve Pay** (NPCI/RBI, India) — confirm this is a real, named
   product/feature (not confused with UPI Autopay or something else), what
   it actually does, and current rollout status.
6. **Razorpay's own agent-commerce products** — the doc claims Razorpay has
   "UPI Reserve Pay, Agent Studio, Vulcan AI" (footnotes [59][60], unresolved).
   Verify which of these are real Razorpay products, find primary sources
   (Razorpay blog/docs/press), and flag anything that looks made up.
7. **Competitors' actual capabilities** — Stripe Issuing for AI agents,
   PayPal Agentic Payments, Adyen's AP2/UCP/ACP support, Pine Labs P3P.
   The doc's comparison table (§14) makes specific claims about what each
   does and doesn't do (e.g. "Stripe Issuing: no built-in intent payload").
   Spot-check the ones you can verify.

## Output format

A markdown report, one section per numbered item above, each with:
- **Verdict**: Confirmed accurate / Partially accurate (explain what's wrong) / Outdated / Unverifiable / Likely fabricated
- **What's actually true**, in 2-4 sentences
- **Primary source(s)**: real URLs (official docs, press releases, reputable trade press — not random blogspam)

End with a short "Corrections needed" list: the specific sentences in
`06-protocol-mapping.md` or `14-competitive-validation.md` that should be
rewritten or removed because they're wrong or unverifiable, so I can fix the
doc directly.

## Non-goals

- Don't touch the code or the repo — this is a standalone research output.
- Don't speculate about future roadmap items as if they were current fact.
- If something is genuinely unverifiable (vague/rare enough that search
  turns up nothing credible), say so plainly rather than guessing.
