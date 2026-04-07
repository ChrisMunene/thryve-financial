## ADDED Requirements

### Requirement: Fixed two-level taxonomy with spend/non-spend classification
The system SHALL use a fixed taxonomy of 14 primary categories and ~50 sub-categories. Every transaction MUST be assigned exactly one primary category and exactly one sub-category. Each primary category SHALL be classified as either "spend" or "non-spend." Users SHALL NOT be able to create, rename, or delete categories.

#### Scenario: Transaction gets primary and sub-category
- **WHEN** a transaction is categorized
- **THEN** it is assigned exactly one primary category (e.g. "Food & Dining") and exactly one sub-category (e.g. "Groceries")

#### Scenario: User cannot create custom categories
- **WHEN** a user attempts to categorize a transaction
- **THEN** they can only select from the predefined taxonomy, not create new categories

#### Scenario: Spend categories included in budget totals
- **WHEN** budget totals are computed for a user
- **THEN** only transactions in "spend" categories (1-10) are included; "non-spend" categories (11-14) are excluded

### Requirement: Spend category definitions
The system SHALL define the following 10 spend categories (included in budget totals):

**1. Food & Dining** — Groceries, Restaurants, Fast Food, Coffee Shops, Food Delivery, Alcohol & Bars, Convenience Stores, Vending & Snacks

**2. Shopping** — General (Walmart, Amazon, Target), Clothing, Electronics, Home & Furniture, Pet Supplies, Sporting Goods

**3. Transportation** — Gas, Rideshare (Uber/Lyft), Public Transit, Parking & Tolls, Auto Maintenance

**4. Bills** — Rent / Mortgage, Electricity & Gas, Water & Sewer, Internet & Phone, Insurance (home, auto, life), Subscriptions (non-streaming), Other Bills (childcare, storage, etc.)

**5. Entertainment** — Streaming (Netflix, Spotify), Gaming, Events & Activities, Other Entertainment

**6. Gambling** — (single category — sportsbooks, online casinos, lottery)

**7. Health** — Pharmacy, Doctor & Dental, Gym & Fitness, Vision, Health Insurance

**8. Personal Care** — Hair & Beauty, Laundry & Dry Cleaning

**9. Travel** — Flights, Hotels & Lodging, Rental Cars, Other Travel

**10. Education** — (tuition, supplies, courses, student fees)

#### Scenario: All spend categories exist
- **WHEN** the taxonomy is loaded
- **THEN** exactly 10 spend primary categories are available, each with a unique identifier, display name, and icon

#### Scenario: Gambling is a distinct primary category
- **WHEN** a transaction from FanDuel or DraftKings is categorized
- **THEN** it is assigned to "Gambling" as its primary category, not "Entertainment"

#### Scenario: Transportation and Travel are separate
- **WHEN** a gas station transaction ($20, high frequency) is categorized
- **THEN** it is assigned to "Transportation > Gas"
- **WHEN** a hotel transaction ($137, low frequency) is categorized
- **THEN** it is assigned to "Travel > Hotels & Lodging"

### Requirement: Non-spend category definitions
The system SHALL define the following 4 non-spend categories (excluded from budget spend totals):

**11. Transfers** — Internal (own accounts), To/From Savings, Peer-to-Peer (Venmo, Zelle, Cash App), Investment & Retirement, ATM Withdrawal, Other Transfer

**12. Debt & Loans** — Credit Card Payment, Student Loan, Auto Loan, Personal Loan, Mortgage Payment, Cash Advance / EWA

**13. Income** — Paycheck, Side Income / Gig, Interest & Dividends, Refunds & Cashback

**14. Other** — Fees (ATM, overdraft, foreign transaction, interest charges), Taxes, Donations, Uncategorized

#### Scenario: Internal transfer excluded from spend
- **WHEN** a transaction is categorized as "Transfers > Internal"
- **THEN** it does not appear in the user's spend totals or budget tracking

#### Scenario: Cash advance correctly identified
- **WHEN** a transaction from Earnin, Dave, Brigit, or Cleo arrives
- **THEN** it is categorized as "Debt & Loans > Cash Advance / EWA", not as "Bills" or "Other"

#### Scenario: P2P payment defaults to Transfers
- **WHEN** a Venmo or Cash App transaction arrives with no user override
- **THEN** it is categorized as "Transfers > Peer-to-Peer" by default

### Requirement: Vendor taxonomy mapping
The system SHALL maintain mapping tables from Plaid detailedName (~106 values) and Pave tags (~100+ tags) to the internal taxonomy. These mappings SHALL be used to convert vendor-labeled training data into the internal taxonomy.

Known mapping overrides where our taxonomy intentionally disagrees with vendor labels:
- Plaid `GENERAL_MERCHANDISE_CONVENIENCE_STORES` → internal `Food & Dining > Convenience Stores`
- Plaid `GENERAL_SERVICES_ACCOUNTING_AND_FINANCIAL_PLANNING` (for EWA apps) → internal `Debt & Loans > Cash Advance / EWA`
- Plaid `ENTERTAINMENT_CASINOS_AND_GAMBLING` → internal `Gambling`
- Plaid `HOME_IMPROVEMENT_*` → internal `Shopping > Home & Furniture` (except SECURITY → `Bills > Insurance`)
- Plaid `TRAVEL_LODGING` → internal `Travel > Hotels & Lodging` (not Entertainment)
- Plaid `TRAVEL_FLIGHTS` → internal `Travel > Flights` (not Transportation)

#### Scenario: Plaid category maps to internal taxonomy
- **WHEN** a transaction has Plaid detailedName "FOOD_AND_DRINK_FAST_FOOD"
- **THEN** it maps to internal category "Food & Dining > Fast Food"

#### Scenario: EWA merchant override
- **WHEN** a transaction has Plaid detailedName "GENERAL_SERVICES_ACCOUNTING_AND_FINANCIAL_PLANNING" and merchant is "Earnin"
- **THEN** it maps to internal category "Debt & Loans > Cash Advance / EWA", overriding the Plaid label

#### Scenario: Pave tag maps to internal taxonomy
- **WHEN** a transaction has Pave tags ["Restaurant"]
- **THEN** it maps to internal category "Food & Dining > Restaurants"

#### Scenario: Pave multi-tag resolution
- **WHEN** a transaction has Pave tags ["Food Delivery", "Subscription"]
- **THEN** the first non-generic tag is used as the primary signal, mapping to "Food & Dining > Food Delivery"

### Requirement: Taxonomy versioning
The taxonomy SHALL be versioned. When the taxonomy changes (categories added, renamed, or merged), the system SHALL migrate all existing transaction categorizations to the new version. Historical categorizations SHALL remain queryable under the version they were created with.

#### Scenario: New sub-category added
- **WHEN** a new sub-category "Meal Kits" is added under "Food & Dining" in a taxonomy update
- **THEN** existing transactions are not affected, and new transactions can be categorized as "Food & Dining > Meal Kits"

#### Scenario: Sub-category merged
- **WHEN** a sub-category is merged into another in a taxonomy update
- **THEN** all existing transactions with the old sub-category are re-mapped to the merged category
