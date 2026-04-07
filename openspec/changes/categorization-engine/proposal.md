## Why

Transaction categorization is the root node of any personal finance app — when it's wrong, budgets are wrong, insights are wrong, and users have to do manual work to fix it. This is the #1 reason users abandon incumbent PFM apps within 2-3 months. LLMs now make it possible to build a categorization engine that is accurate enough to run on autopilot, and improves over time through a human-in-the-loop flywheel. Building this engine first establishes the foundation that powers every downstream feature (budgets, insights, alerts, coaching).

## What Changes

- Introduce a two-layer transaction categorization engine: a fast deterministic layer (lookup tables, pattern rules, MCC mappings) for high-confidence cases, and an LLM-powered layer for ambiguous/novel transactions
- Define a 12-primary / ~45-sub-category taxonomy optimized for user comprehension and budgeting
- Build a promotion mechanism where high-confidence LLM results auto-promote to the deterministic layer, reducing inference costs over time
- Implement a three-tier correction generalization system: user overrides → candidate rules (threshold-based) → universal rules, with ambiguous merchant detection
- Create a weekly recap feature that serves as both a retention mechanic and an RLHF labeling pipeline — users review transactions, confirm or correct categories, and that data feeds back into both layers
- Seed the engine from 460M pre-labeled transactions (dual-vendor labels from Plaid and Pave) for day-one accuracy

## Capabilities

### New Capabilities
- `transaction-categorization`: The two-layer categorization engine — deterministic fast path + LLM fallback, confidence scoring, and the promotion mechanism between layers
- `category-taxonomy`: The 12-primary / ~45-sub-category taxonomy definition, mapping tables from Plaid/Pave taxonomies, and taxonomy versioning
- `correction-flywheel`: User correction handling — personal overrides, threshold-based promotion to candidate/universal rules, ambiguous merchant detection, and feedback into model training
- `weekly-recap`: The weekly transaction review experience — surfacing transactions for user review, collecting confirmations/corrections, and integrating with the correction flywheel
- `training-pipeline`: Data pipeline for seeding the engine from the 460M transaction corpus, defining gold/silver/hard-case label splits from vendor agreement, and ongoing retraining from user corrections

### Modified Capabilities

(none — greenfield project)

## Impact

- **Data dependencies**: Requires access to the 460M globaltransactions corpus (Plaid + Pave labeled) for training and the 6.6M Mine card transactions for validation
- **Infrastructure**: Needs a merchant lookup store (fast reads), an LLM inference endpoint, and a correction/feedback data store
- **External services**: Plaid (or equivalent) for bank connection and raw transaction data in production; LLM API (Claude or similar) for the intelligent layer
- **Cost considerations**: LLM inference costs scale with the percentage of transactions hitting Layer 2 — the promotion mechanism is critical for keeping this at 10-15% of volume at scale
