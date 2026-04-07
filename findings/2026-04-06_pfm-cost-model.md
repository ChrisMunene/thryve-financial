# PFM App Cost Model & Unit Economics

**Date:** 2026-04-06
**Context:** Cost model for the new consumer PFM app, built on the categorization engine with LLM-powered categorization, RLHF flywheel, and Plaid bank connections. Target user: 25-30 year old financial beginner (Platinum/Gold profile from Mine data).

---

## Assumptions

- Pricing: $9.99/month subscription
- Average connected accounts per user: 2
- Average transactions per user per month: ~250 (card + connected accounts)
- Deterministic layer hit rate: 85%
- LLM invocations: 15% of transactions (~38/month), ~50% cached = ~19 actual LLM calls
- LLM model: Claude Haiku with dynamic few-shot selection (~700 input tokens, ~100 output tokens per call)
- App Store: Apple Small Business Program (15%), blended with Google Play (15%)
- Plaid pricing: per-item-per-month model (confirmed)

---

## Plaid Costs (Confirmed Pricing)

### Per User Per Month (2 connected accounts)

| Component | Rate | Monthly Cost |
|---|---|---|
| Auth & Identity (one-time) | 2 × $0.99 = $1.98 | $0.17 (amortized /12mo) |
| Transactions | 2 × $0.131 | $0.262 |
| Balance | 2 × $0.022 | $0.044 |
| Recurring Transactions | 2 × $0.050 | $0.100 |
| **Total Plaid** | | **$0.57/user/month** |

### At Volume (50K+ items, lower tiers)

| Component | Rate | Monthly Cost |
|---|---|---|
| Auth & Identity (one-time) | 2 × $0.79 = $1.58 | $0.13 (amortized /12mo) |
| Transactions | 2 × $0.120 | $0.240 |
| Balance | 2 × $0.017 | $0.034 |
| Recurring Transactions | 2 × $0.050 | $0.100 |
| **Total Plaid at Volume** | | **$0.50/user/month** |

---

## LLM Costs (Categorization Engine)

| Metric | Value |
|---|---|
| Transactions per user/month | ~250 |
| Deterministic hit rate | 85% |
| LLM invocations before cache | ~38/month |
| Redis cache hit rate | ~50% |
| **Actual LLM calls** | **~19/month** |
| Input tokens per call | ~700 |
| Output tokens per call | ~100 |
| Haiku input pricing | $0.25/M tokens |
| Haiku output pricing | $1.25/M tokens |
| Cost per call | $0.0003 |
| **LLM cost per user/month** | **$0.006-0.012** |

The entire AI categorization engine — the core product differentiator — costs less than a penny per user per month.

---

## Infrastructure Costs

### Railway (MVP, 1K-10K users)

| Component | Spec | Monthly Cost |
|---|---|---|
| API Server | 1 vCPU, 2GB RAM | $10-20 |
| Celery Worker | 1 vCPU, 1GB RAM | $5-10 |
| Celery Beat | 0.5 vCPU, 512MB | $3-5 |
| Temporal Worker | 1 vCPU, 1GB RAM | $5-10 |
| Postgres | 2GB RAM, 10GB storage | $15-25 |
| Redis | 256MB | $5-10 |
| **Total** | | **$43-80/month** |

Per-user at 1K users: $0.04-0.08. At 10K users: $0.004-0.008. Negligible.

### AWS (SOC 2, 10K-100K users)

| Component | Spec | Monthly Cost |
|---|---|---|
| ECS (API + workers) | 2 tasks, 1 vCPU each | $60-80 |
| RDS Postgres | db.t4g.medium | $50-70 |
| ElastiCache Redis | cache.t4g.micro | $15-25 |
| Temporal Cloud | ~100K actions/month | $25-50 |
| Load Balancer | ALB | $20-25 |
| Data Transfer | | $10-20 |
| **Total** | | **$180-270/month** |

Per-user at 50K users: $0.004-0.005. Negligible.

---

## External Services

| Service | Cost at <10K users | Cost at 50K users |
|---|---|---|
| Supabase Auth | Free (50K MAU) | ~$0.003/user |
| Sentry | Free (5K events) | $26/month |
| PostHog | Free (1M events) | ~$0.0005/event |
| Datadog | Free (basic) | $15/host |
| Firebase (push) | Free | Free |
| Resend (email) | Free (3K/month) | $20/month |
| **Total per user** | **~$0.00** | **~$0.02-0.03** |

---

## Unit Economics Summary

### Per User Per Month

| Cost Center | 1K users | 10K users | 50K users |
|---|---|---|---|
| Revenue ($9.99/mo) | $9.99 | $9.99 | $9.99 |
| | | | |
| Plaid | $0.57 | $0.57 | $0.50 |
| App Store (15%) | $1.50 | $1.50 | $1.50 |
| LLM | $0.01 | $0.01 | $0.01 |
| Infrastructure | $0.08 | $0.02 | $0.005 |
| External services | $0.00 | $0.02 | $0.03 |
| **Total Cost** | **$2.16** | **$2.12** | **$2.05** |
| | | | |
| **Net Margin/User** | **$7.83** | **$7.87** | **$7.94** |
| **Gross Margin** | **78.4%** | **78.8%** | **79.5%** |

### Cost Breakdown at Scale

- App Store fee: **71%** of all costs
- Plaid: **27%** of all costs
- LLM: **0.5%** of all costs
- Infrastructure: **1%** of all costs
- External services: **1%** of all costs

### Annual Revenue & Profit

| Users | Annual Revenue | Annual Profit | Margin |
|---|---|---|---|
| 1,000 | $119,880 | $93,960 | 78.4% |
| 5,000 | $599,400 | $471,600 | 78.7% |
| 10,000 | $1,198,800 | $944,400 | 78.8% |
| 25,000 | $2,997,000 | $2,364,000 | 78.9% |
| 50,000 | $5,994,000 | $4,764,000 | 79.5% |

---

## Acquisition Economics

From the Mine user quality analysis, acquisition channel directly determines business viability:

| Channel | CPA per HQ User | LTV ($7.87 × 10mo) | LTV/CAC | Payback |
|---|---|---|---|---|
| Caleb Hammer | ~$22 | $78.70 | 3.6x | 3 months |
| Referral (P+G) | ~$5 | $78.70 | 15.7x | <1 month |
| YouTube (organic) | ~$50 | $78.70 | 1.6x | 6 months |
| Friend referral | ~$40 | $78.70 | 2.0x | 5 months |
| Paid social (FB) | ~$800 | $78.70 | 0.1x | 100 months |
| Paid social (Google) | ~$900 | $78.70 | 0.09x | 114 months |

**Referral programs are the growth flywheel.** Mine data shows P+G referrals produce 39% HQ users. At near-zero CAC, this is a 15.7x LTV/CAC ratio.

**Paid social does not work** for this product. The conversion funnel is too leaky (0.24% HQ rate from Facebook).

---

## Sensitivity Analysis

### LLM costs if deterministic layer underperforms

| Deterministic Hit Rate | LLM calls/user/mo | LLM cost/user/mo |
|---|---|---|
| 85% (target) | 19 (with cache) | $0.006 |
| 70% | 38 | $0.011 |
| 60% | 50 | $0.015 |
| 50% | 63 | $0.019 |

**LLM cost is not a risk.** Even if the deterministic layer handles only 50% of transactions, LLM cost is under 2 cents/user/month.

### Plaid costs with more connected accounts

| Accounts | Plaid cost/user/mo | Margin |
|---|---|---|
| 1 account | $0.30 | 80.6% |
| 2 accounts | $0.57 | 78.8% |
| 3 accounts | $0.84 | 77.1% |
| 5 accounts | $1.38 | 73.7% |

Each additional connected account adds ~$0.27/month. Still healthy up to 5 accounts.

---

## Margin Optimization Levers

| Lever | Impact | Effort |
|---|---|---|
| Web-based subscription (bypass App Store) | +$1.12/user (save 15%, pay Stripe 2.9%) | Medium — Stripe integration, web checkout flow |
| Plaid startup program | -20-40% on Plaid costs | Low — application only |
| Plaid volume tiers | Auto at 5K+ items | Free |
| Annual subscription pricing ($99/yr vs $120/yr) | Improves retention, reduces churn cost | Low — pricing change |
| Referral-driven growth | Near-zero CAC | Medium — referral program design |

### Optimized Scenario (web checkout + Plaid startup discount)

| | Current | Optimized |
|---|---|---|
| Revenue | $9.99 | $12.99 (web, no App Store) |
| Plaid | $0.57 | $0.34 (40% startup discount) |
| App Store | $1.50 | $0.00 (web checkout) |
| Stripe | $0.00 | $0.38 (2.9% + $0.30) |
| Other costs | $0.05 | $0.05 |
| **Net Margin** | **$7.87** | **$12.22** |
| **Gross Margin** | **78.8%** | **94.1%** |

---

## Key Takeaway

The product economics are strong at 79% gross margin. The categorization engine — the most complex and differentiating part of the product — is the cheapest component to run ($0.01/user/month). The real costs are distribution (App Store: 71% of costs) and data access (Plaid: 27% of costs). The real economic risk is acquisition cost, not operational cost. Channel choice (content creators + referrals vs paid social) is the single most important business decision.
