# User Quality Tiers & Acquisition Analysis

**Date:** 2026-04-05  
**Analyst:** Christopher Kinyua + Claude  
**Data sources:** users, transactions, loans, subscriptionmemberships, subscriptioncharges, dailybankaccountbalances, bankaccounts, referrals, inappreviews, useracquisitionleads, userinterests, userprofiles  
**Notebook:** `notebooks/user_quality_analysis.ipynb`  
**Cohort files:** `/Volumes/SN7100-2TB/parquet/cohort_*`

---

## 1. The Funnel Problem

Of 1,252,232 total signups, 92.7% never complete onboarding. Only 78,937 users have ever transacted on the card.

| Stage | Users | % of Signups |
|---|---|---|
| Total Signups | 1,252,232 | 100% |
| Completed Signup | 91,765 | 7.3% |
| Transacted | 78,937 | 6.3% |
| Platinum + Gold | 9,185 | 0.7% |

The biggest drop is signup completion (93% loss), not post-activation churn.

---

## 2. Quality Tier Definitions

Users are scored across five dimensions: revenue generation, payment reliability, credit health, bank balance stability, and engagement.

### Tier Criteria

| Tier | Core Requirements |
|---|---|
| **Platinum** | Active sub + 6+ months transacting + no freezes/past due + median balance > $250 + overdraft < 5% + autopay + charge success >= 90% |
| **Gold** | Active sub + 3+ months transacting + no freezes/past due + median balance > $50 + overdraft < 15% |
| **Silver** | Active sub + transacting + no past due + median balance > $0 + overdraft < 25% + charge success >= 80% |
| **Low Value** | Transacting but doesn't meet Silver criteria |
| **At Risk** | Frozen, past due, or flagged for closure |
| **Struggling Good** | 2+ financial struggle signals BUT 4+ positive behavioural signals (see Section 8) |

### Tier Distribution

| Tier | Users | % of Transacting |
|---|---|---|
| Platinum | 3,363 | 4.3% |
| Gold | 5,822 | 7.4% |
| Silver | 11,027 | 14.0% |
| Low Value | 20,700 | 26.2% |
| At Risk | 38,025 | 48.2% |

---

## 3. Platinum + Gold User Profile

### Demographics
- **Age:** Platinum median 27, Gold median 30. Sweet spot is 22-30.
- **Employment:** Platinum 56% full-time + 18% part-time. Gold 70% full-time.
- **Students:** 34% are active students, overwhelmingly at online universities (SNHU, WGU, ASU Online).
- **Device:** 77-86% iOS.
- **Geography:** TX (12%), CA (12%), FL (7%), NY (5%). Major Sun Belt metros — LA, Houston, Chicago, Brooklyn, Las Vegas.

### Banking
- **90% bank exclusively with traditional institutions** (Chase, Wells Fargo, BofA, Capital One, Navy Federal). Only 10% have any neobank account.
- Primary bank: Chase (1,312 users), Wells Fargo (994), BofA (864).
- 88% connection health rate.
- Notable: USAA + Navy Federal = 718 users (~8%) — a military-connected segment.

### Financial Profile
- Median bank balance: Platinum $880, Gold $263.
- 41% paycheck-to-paycheck, 14% tight-but-stable, 6% comfortable.
- 64% financial literacy beginners, 36% intermediate.
- 52% full-time employment detected in banking data.

### What They Want
- **#1 goal: Build credit (97%)** — near-universal.
- Save money (73%), build strong credit (72%), emergency fund (43%), buy a home (36%), investment portfolio (30%).
- Product requests skew toward wealth-building: PFM tools (57%), investing (57%), savings (52%).

### Spending Patterns
- Median transaction: $14.95. Median total spend: Platinum $5,172, Gold $1,041.
- Top merchants: Walmart, Amazon, Target, McDonald's, Costco, Uber Eats.
- Budget-conscious grocery choices (Aldi, Costco, Trader Joe's) but frequent fast-food spend.
- Heavy gas station presence — car-dependent, suburban/exurban.
- Spending peaks Friday-Saturday.
- TikTok Shop appears in top merchants ($172K from 1,253 users).

---

## 4. Revenue Impact

| Tier | Users | Sub Revenue | Card Spend | Combined/User |
|---|---|---|---|---|
| Platinum | 3,363 | $440K | $27M | **$8,165** |
| Gold | 5,822 | $504K | $12.7M | **$2,268** |
| Silver | 11,027 | $637K | $3.4M | $369 |
| At Risk | 38,025 | $1.5M | $24.2M | $677 |

A single Platinum user generates **12x the value** of an At Risk user. 3,363 Platinum users produce more card spend than 38,025 At Risk users.

---

## 5. Acquisition Channel Quality

### The headline: Caleb Hammer produces high-quality users at 37x the rate of Facebook.

| Source | Signups | P+G Rate | P+G Users | At Risk Rate |
|---|---|---|---|---|
| **calebHammer** | 39,432 | **8.85%** | **3,489** | 4.53% |
| influencer | 3,186 | 2.64% | 84 | 9.73% |
| youtube | 32,236 | 1.42% | 459 | 3.55% |
| friend | 43,212 | 1.90% | 819 | 5.26% |
| tiktok | 151,226 | 0.55% | 836 | 3.66% |
| instagram | 266,402 | 0.50% | 1,331 | 3.38% |
| facebook | 332,075 | 0.24% | 786 | 2.48% |
| google | 142,823 | 0.21% | 300 | 2.00% |

- **54.5% of all Platinum users came from Caleb Hammer.**
- Paid social (FB/IG/TT/Google) brings 892K signups but only 0.24-0.55% P+G rate.
- Influencer channel stopped producing mid-2024 but produced the stickiest users (479-day median sub tenure, 14-month median transaction lifetime).

### UTM vs Self-Reported Attribution
- Meta UTM → 52% say Facebook, 36% say Instagram (reasonable alignment).
- Impact (affiliate) UTM → 57% say "other" — users don't know how they found the app. 19% say Google despite coming through affiliate links.
- TikTok has strongest self-awareness: 87% correctly identify the source.

### Paid Social User Quality
- Median balance: $0.14-$0.70 across paid channels.
- 22.9% subscription charge failure rate (vs 3.9% for influencer).
- 12.5% refund rate.
- 64% of transactors have outstanding repayments.
- Median 2 months active, 8 transactions total.

---

## 6. Referral Dynamics

### Referral rates
- Platinum refers at 5.08% (1.6x platform average of 3.08%).
- P+G referral redemption rate: 41.5% vs 26.3% platform-wide.

### Quality begets quality
- **P+G referrals → 39.2% become Platinum or Gold** (vs 3.6% from non-P+G referrers). This is an 11x multiplier.
- Non-P+G referrals → 48.4% become At Risk.
- This is the strongest argument for a P+G-specific referral program.

---

## 7. Retention

### Transaction retention (% still transacting on card)

| Tier | M1 | M3 | M6 | M12 |
|---|---|---|---|---|
| Platinum | 97.8% | 96.6% | 87.2% | 50.8% |
| Gold | 95.0% | 68.3% | 31.2% | 15.4% |
| Silver | 52.9% | 12.4% | 3.1% | 0.9% |
| At Risk | 44.3% | 14.7% | 6.8% | 3.6% |

Platinum retention is exceptional — 97% at M3, 87% at M6. The M6→M12 drop (87% → 51%) is the main risk window.

### Subscription retention
- Platinum: 96.6% active, median age 375 days. Only 3.4% ever cancel.
- Gold: 93.9% active, median age 149 days.
- When P+G users cancel, it happens in days 2-7 — instant decision, not gradual disengagement.
- Low Value/At Risk cancel after 53-61 days of declining engagement.

---

## 8. The Struggling-but-Good Cohort

24,945 users with genuine financial difficulty but strong behavioural signals. Identified by having 2+ struggle signals AND 4+ good behaviour signals.

**Struggle signals:** median balance <= $100, overdraft rate > 5%, credit limit <= $200, currently frozen.  
**Good signals:** 2+ months transacting, $100+ spend, autopay on, active subscriber, charge success >= 70%, has referred, still active in 2026.

### How they compare to other At Risk users (same financial position, different behaviour)

| Metric | Struggling Good | Other At Risk |
|---|---|---|
| Active subscriber | 92% | 36% |
| Charge success rate | 100% | 67% |
| Autopay on | 61% | 16% |
| Still active 2026 | 89% | 28% |

These users are paying for the product despite financial stress. They represent the biggest retention/uplift opportunity — small interventions could move many toward Gold.

---

## 9. Feedback & Satisfaction

- P+G review rate: 2.3% (1.7x platform average).
- **86% give 5 stars**, average rating 4.77/5. Zero 2-star reviews.
- P+G top issue: "Credit score isn't improving" (46%) — they understand the product; they want it to work better.
- Lower-tier top issue: "I don't understand Mine" (73-77%) — product comprehension, not product quality.
- P+G product requests: PFM tools & investing (57% each). Lower-tier: loan products (68-75%).

---

## 10. Platform-Wide Financial Health

The user base is overwhelmingly financially underserved:
- 71% of users have $25 or less in their connected bank accounts.
- 22.9% are overdrawn at any given time.
- 60% have been overdrawn at some point.
- Median balance platform-wide: $26.87.

### Growth drove the balance decline
- Pre-Aug 2025: ~8K new users/month, median initial balance $130+.
- Post-Aug 2025: 100K+ new users/month, median initial balance < $1.
- The inflection correlates directly with paid social scaling (Meta, Impact affiliates, Google, TikTok).
- **Not a user behaviour change — a composition change from acquisition channel mix.**

### Institution mix shifted
- Early users (pre-2025): Chase (13%), Wells Fargo (9%), BofA (7%).
- Recent users (Jul 2025+): Chime (26%), OnePay (5%), Current (4%).
- Best users bank traditional; growth brought in neobank-heavy, lower-balance users.

---

## Strategic Recommendations

1. **Double down on financial creator partnerships.** Caleb Hammer produces P+G users at 37x Facebook's rate. Even at higher CPAs, the unit economics dominate. Identify and engage similar creators.

2. **Reactivate the influencer channel.** It stopped producing mid-2024 but generated the stickiest, highest-LTV users on the platform. Find out which influencer(s) and re-engage.

3. **Build a P+G referral program.** When P+G users refer, 39% of referrals become P+G themselves. This is the cheapest high-quality acquisition channel available. Current referral rate is only 3-5% — there's significant room to incentivize.

4. **Invest in the Struggling-but-Good cohort.** 25K users who are engaged but fragile. Balance alerts, flexible repayment timing, gradual limit increases could convert many to Gold. They're already paying for the subscription.

5. **Audit paid social ROI urgently.** Facebook delivers P+G users at 0.24%. You need 422 signups to get one high-quality user. Compare the CPA × 422 against the LTV of one P+G user ($2,268-$8,165) and the CPA of one Caleb Hammer P+G user (11 signups needed).

6. **Investigate the M6-M12 Platinum retention drop.** Retention is exceptional through M6 (87%) but drops to 51% at M12. Understanding what drives this cliff could unlock significant LTV.

7. **Address "credit score not improving" for P+G users.** It's their #1 complaint and the reason they signed up. Solving this retains your most valuable users.

8. **Explore the military segment.** USAA + Navy Federal = 8% of P+G users. Military financial education creators and veteran-focused partnerships could be a high-quality channel.

9. **Target traditional bank users in ads.** 90% of best users bank with Chase/WF/BofA. Exclude neobank-heavy audiences from targeting.

10. **Fix the signup funnel.** 93% of signups never complete. Even a 1-2 percentage point improvement at current volume (150K signups/month) adds 1,500-3,000 completed users per month.
