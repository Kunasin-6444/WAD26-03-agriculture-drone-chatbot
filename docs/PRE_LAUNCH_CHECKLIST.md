# Pre-Launch Checklist

Created 2026-10-15, after the pipeline rewrite + same-day bug-fix round (see
`TODO.md`'s "Latency fix — 2026-10-15" section for the detailed history).
Pipeline logic is in good shape (74 unit/contract tests pass; a clean live
run scored 22/28 contract-pass, 25/28 latency-pass, mean 5.9s). This
checklist covers what's still needed before sending the bot to a real
customer — deployment and operational readiness, not RAG quality.

## 1. API capacity & resilience — highest priority

Today's testing alone exhausted the **daily quota** on three different
models on the KKU GenAI gateway (`gpt-5.6-luna`, `nova-2-lite-v1`, and even
the newly-switched default `gemini-3.5-flash-lite`), confirmed via direct
API calls (`"error": "This model reached daily limit."`, HTTP 401). If a
real customer's usage does the same thing mid-day, the bot abstains on
*everything* until the next reset, with no visibility into why.

- [ ] Find out the actual daily quota per model on the KKU gateway, and
      estimate expected customer query volume against it. If quota is too
      low for expected traffic, request a higher tier/quota from KKU, or
      plan around it explicitly.
- [ ] Add quota-usage visibility (log `response.model_quota` — already
      present in the API's raw response, e.g. `daily_remaining_tokens` —
      instead of discarding it) so you can see this coming instead of
      discovering it via a wave of abstains.
- [ ] Decide what the customer sees when the whole model pool is
      exhausted/degraded. Right now it's the same honest "evidence
      insufficient" abstain message as a real no-answer case — that's safe
      (never hallucinates) but looks identical to "the bot doesn't know
      this" to a user, which may erode trust if it happens often. Consider
      a distinct, honest "เรากำลังปรับปรุงระบบชั่วคราว" (temporarily degraded)
      message when every model attempt fails outright (not just when
      evidence is genuinely insufficient).
- [ ] Verify `qwen3.6-flash`/`qwen3.7-plus`/`qwen3.7-max` are **not** a
      viable fallback as currently architected — tested 2026-10-15: they're
      reasoning models that burn 1500+ tokens and 15s+ on internal
      chain-of-thought before producing any answer content, incompatible
      with the current 8s-per-attempt / 22s-total budget. Don't add them to
      `FALLBACK_MODELS` without redesigning the timeout budget around them.
- [ ] Decide on a longer cooldown in `_EXHAUSTED_MODELS`
      (`app/rag/rag_service.py`) specifically for a "daily limit" 401 vs. a
      transient rate-limit 401/429 — currently both get the same 60s
      cooldown, which wastes a full attempt every 60s for the rest of the
      day once a model's daily quota is hit.

## 2. Deployment & infrastructure

- [ ] Replace the ngrok dev tunnel with real hosting (ngrok free-tier URLs
      rotate and aren't meant for production).
- [ ] Register the production webhook URL in the LINE Developer Console.
- [ ] Confirm which LINE channel is configured in `.env`
      (`LINE_CHANNEL_ID`/`LINE_CHANNEL_SECRET`/`LINE_CHANNEL_ACCESS_TOKEN`)
      is the real customer-facing channel, not a dev/test channel.
- [ ] Set production environment variables on the host (not just local
      `.env`): `RAG_MODEL`, `RAG_REQUEST_TIMEOUT_SECONDS`, `API_KEY`,
      `GOOGLE_API_KEY`, `TAVILY_API_KEY`.
- [ ] Confirm `data/chroma/` (or wherever `CHROMA_PATH` points in
      production) is on persistent storage, not ephemeral — losing it means
      re-ingesting all PDFs.
- [ ] End-to-end test against the real LINE app (not just the webhook
      contract tests) — send an actual message from a phone and confirm
      the full round trip.

## 3. Final RAG validation (do this once quota resets)

- [ ] Re-run `python -m scripts.evaluate_acceptance` (all 28 cases, no
      `--limit`) with a healthy backend to get one clean, complete
      confirmation run — the last full run that included the CAAT
      prompt-scoping fix got contaminated by the quota outage partway
      through (13/28, not representative). The last *fully clean* run
      (22/28, before the CAAT fix was even applied) is in
      `docs/LIVE_ACCEPTANCE_REPORT.json` right now.
- [ ] If quota allows, investigate the remaining known failure modes from
      that 22/28 run: Q17 (weather limits for aerial photography — check
      if the PDFs genuinely lack this content, or if it's a retrieval
      miss), and confirm whether Q07/Q12's web_fallback answers (graded
      CORRECT but routed differently than the test fixture expects) should
      update the fixture or reveal a real KB-coverage gap.

## 4. Known, accepted residual risks (not blockers, but tell the customer)

- The live model is not perfectly deterministic — the same query can
  occasionally abstain on one run and answer correctly on another
  (observed with Gemini on "recommend X" / comparison-style phrasing).
  This is inherent LLM variance, not a pipeline bug, and won't be fully
  eliminated by more fixes.
- Multi-turn conversation memory is explicitly deferred (`TODO.md` P5) —
  the bot doesn't remember earlier messages in a chat.

## Sign-off

Don't call this "production-ready" until section 1 (capacity/resilience)
and section 2 (deployment) are checked off — those are the gaps between
"works well in testing" and "safe to hand to a customer." Section 3 is
about confidence/completeness of the quality signal, not a hard blocker.
