"""
Vendor taxonomy mappings: Plaid detailedName → internal, Pave tags → internal.
EWA and gambling merchant explicit lists.

These mappings are the bridge between vendor labels (training data) and our taxonomy.
"""

# =============================================================================
# PLAID detailedName → (primary_id, sub_id)
#
# Covers all 106 Plaid detailedName values observed in the 460M corpus.
# Where our taxonomy intentionally disagrees with Plaid, a comment explains why.
# =============================================================================

PLAID_DETAILED_TO_INTERNAL: dict[str, tuple[str, str]] = {
    # --- Food & Dining ---
    "FOOD_AND_DRINK_RESTAURANT": ("food_and_dining", "restaurants"),
    "FOOD_AND_DRINK_FAST_FOOD": ("food_and_dining", "fast_food"),
    "FOOD_AND_DRINK_GROCERIES": ("food_and_dining", "groceries"),
    "FOOD_AND_DRINK_COFFEE": ("food_and_dining", "coffee_shops"),
    "FOOD_AND_DRINK_VENDING_MACHINES": ("food_and_dining", "vending_and_snacks"),
    "FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR": ("food_and_dining", "alcohol_and_bars"),
    "FOOD_AND_DRINK_OTHER_FOOD_AND_DRINK": ("food_and_dining", "restaurants"),

    # --- Shopping ---
    "GENERAL_MERCHANDISE_SUPERSTORES": ("shopping", "general"),
    "GENERAL_MERCHANDISE_ONLINE_MARKETPLACES": ("shopping", "general"),
    "GENERAL_MERCHANDISE_ELECTRONICS": ("shopping", "electronics"),
    "GENERAL_MERCHANDISE_CLOTHING_AND_ACCESSORIES": ("shopping", "clothing"),
    "GENERAL_MERCHANDISE_DISCOUNT_STORES": ("shopping", "general"),
    "GENERAL_MERCHANDISE_DEPARTMENT_STORES": ("shopping", "general"),
    "GENERAL_MERCHANDISE_GIFTS_AND_NOVELTIES": ("shopping", "general"),
    "GENERAL_MERCHANDISE_SPORTING_GOODS": ("shopping", "sporting_goods"),
    "GENERAL_MERCHANDISE_BOOKSTORES_AND_NEWSSTANDS": ("shopping", "general"),
    "GENERAL_MERCHANDISE_OFFICE_SUPPLIES": ("shopping", "general"),
    "GENERAL_MERCHANDISE_PET_SUPPLIES": ("shopping", "pet_supplies"),
    "GENERAL_MERCHANDISE_TOBACCO_AND_VAPE": ("shopping", "general"),
    "GENERAL_MERCHANDISE_OTHER_GENERAL_MERCHANDISE": ("shopping", "general"),
    # Override: convenience stores → Food (primary use is food/drink purchases)
    "GENERAL_MERCHANDISE_CONVENIENCE_STORES": ("food_and_dining", "convenience_stores"),

    # --- Transportation ---
    "TRANSPORTATION_GAS": ("transportation", "gas"),
    "TRANSPORTATION_TAXIS_AND_RIDE_SHARES": ("transportation", "rideshare"),
    "TRANSPORTATION_PUBLIC_TRANSIT": ("transportation", "public_transit"),
    "TRANSPORTATION_PARKING": ("transportation", "parking_and_tolls"),
    "TRANSPORTATION_TOLLS": ("transportation", "parking_and_tolls"),
    "TRANSPORTATION_BIKES_AND_SCOOTERS": ("transportation", "public_transit"),
    "TRANSPORTATION_OTHER_TRANSPORTATION": ("transportation", "public_transit"),

    # --- Bills (was Housing in Plaid) ---
    "RENT_AND_UTILITIES_RENT": ("bills", "rent_mortgage"),
    "RENT_AND_UTILITIES_GAS_AND_ELECTRICITY": ("bills", "electricity_and_gas"),
    "RENT_AND_UTILITIES_WATER": ("bills", "water_and_sewer"),
    "RENT_AND_UTILITIES_INTERNET_AND_CABLE": ("bills", "internet_and_phone"),
    "RENT_AND_UTILITIES_TELEPHONE": ("bills", "internet_and_phone"),
    "RENT_AND_UTILITIES_SEWAGE_AND_WASTE_MANAGEMENT": ("bills", "water_and_sewer"),
    "RENT_AND_UTILITIES_OTHER_UTILITIES": ("bills", "other_bills"),

    # --- Entertainment ---
    "ENTERTAINMENT_TV_AND_MOVIES": ("entertainment", "streaming"),
    "ENTERTAINMENT_VIDEO_GAMES": ("entertainment", "gaming"),
    "ENTERTAINMENT_MUSIC_AND_AUDIO": ("entertainment", "streaming"),
    "ENTERTAINMENT_SPORTING_EVENTS_AMUSEMENT_PARKS_AND_MUSEUMS": ("entertainment", "events_and_activities"),
    "ENTERTAINMENT_OTHER_ENTERTAINMENT": ("entertainment", "other_entertainment"),
    # Override: gambling → own primary category
    "ENTERTAINMENT_CASINOS_AND_GAMBLING": ("gambling", "gambling"),

    # --- Health ---
    "MEDICAL_PHARMACIES_AND_SUPPLEMENTS": ("health", "pharmacy"),
    "MEDICAL_PRIMARY_CARE": ("health", "doctor_and_dental"),
    "MEDICAL_DENTAL_CARE": ("health", "doctor_and_dental"),
    "MEDICAL_EYE_CARE": ("health", "vision"),
    "MEDICAL_VETERINARY_SERVICES": ("health", "doctor_and_dental"),
    "MEDICAL_NURSING_CARE": ("health", "doctor_and_dental"),
    "MEDICAL_OTHER_MEDICAL": ("health", "doctor_and_dental"),

    # --- Health (from Personal Care) ---
    "PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS": ("health", "gym_and_fitness"),

    # --- Personal Care ---
    "PERSONAL_CARE_HAIR_AND_BEAUTY": ("personal_care", "hair_and_beauty"),
    "PERSONAL_CARE_LAUNDRY_AND_DRY_CLEANING": ("personal_care", "laundry_and_dry_cleaning"),
    "PERSONAL_CARE_OTHER_PERSONAL_CARE": ("personal_care", "hair_and_beauty"),

    # --- Travel (separated from Transportation) ---
    "TRAVEL_LODGING": ("travel", "hotels_and_lodging"),
    "TRAVEL_FLIGHTS": ("travel", "flights"),
    "TRAVEL_RENTAL_CARS": ("travel", "rental_cars"),
    "TRAVEL_OTHER_TRAVEL": ("travel", "other_travel"),

    # --- Education (promoted to own category) ---
    "GENERAL_SERVICES_EDUCATION": ("education", "education"),

    # --- Bills (from General Services) ---
    "GENERAL_SERVICES_INSURANCE": ("bills", "insurance"),
    "GENERAL_SERVICES_CONSULTING_AND_LEGAL": ("bills", "other_bills"),
    "GENERAL_SERVICES_STORAGE": ("bills", "other_bills"),
    "GENERAL_SERVICES_OTHER_GENERAL_SERVICES": ("bills", "other_bills"),
    "GENERAL_SERVICES_CHILDCARE": ("bills", "other_bills"),

    # --- Transportation (from General Services) ---
    "GENERAL_SERVICES_AUTOMOTIVE": ("transportation", "auto_maintenance"),

    # --- Shopping (from General Services / Home Improvement) ---
    "GENERAL_SERVICES_POSTAGE_AND_SHIPPING": ("shopping", "general"),
    "HOME_IMPROVEMENT_HARDWARE": ("shopping", "home_and_furniture"),
    "HOME_IMPROVEMENT_FURNITURE": ("shopping", "home_and_furniture"),
    "HOME_IMPROVEMENT_REPAIR_AND_MAINTENANCE": ("shopping", "home_and_furniture"),
    "HOME_IMPROVEMENT_OTHER_HOME_IMPROVEMENT": ("shopping", "home_and_furniture"),

    # --- Bills (from Home Improvement) ---
    "HOME_IMPROVEMENT_SECURITY": ("bills", "insurance"),

    # --- Bills (EWA — Plaid mislabels these as "accounting") ---
    # Note: These are overridden by the EWA merchant list at runtime,
    # but the mapping here ensures training data is labeled correctly.
    "GENERAL_SERVICES_ACCOUNTING_AND_FINANCIAL_PLANNING": ("bills", "other_bills"),

    # --- Debt & Loans ---
    "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT": ("debt_and_loans", "credit_card_payment"),
    "LOAN_PAYMENTS_STUDENT_LOAN_PAYMENT": ("debt_and_loans", "student_loan"),
    "LOAN_PAYMENTS_CAR_PAYMENT": ("debt_and_loans", "auto_loan"),
    "LOAN_PAYMENTS_PERSONAL_LOAN_PAYMENT": ("debt_and_loans", "personal_loan"),
    "LOAN_PAYMENTS_MORTGAGE_PAYMENT": ("debt_and_loans", "mortgage_payment"),
    "LOAN_PAYMENTS_OTHER_PAYMENT": ("debt_and_loans", "personal_loan"),

    # --- Transfers ---
    "TRANSFER_OUT_ACCOUNT_TRANSFER": ("transfers", "internal"),
    "TRANSFER_OUT_SAVINGS": ("transfers", "to_from_savings"),
    "TRANSFER_OUT_WITHDRAWAL": ("transfers", "atm_withdrawal"),
    "TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS": ("transfers", "investment"),
    "TRANSFER_OUT_OTHER_TRANSFER_OUT": ("transfers", "other_transfer"),
    "TRANSFER_IN_ACCOUNT_TRANSFER": ("transfers", "internal"),
    "TRANSFER_IN_SAVINGS": ("transfers", "to_from_savings"),
    "TRANSFER_IN_DEPOSIT": ("transfers", "other_transfer"),
    "TRANSFER_IN_CASH_ADVANCES_AND_LOANS": ("debt_and_loans", "cash_advance_ewa"),
    "TRANSFER_IN_INVESTMENT_AND_RETIREMENT_FUNDS": ("transfers", "investment"),
    "TRANSFER_IN_OTHER_TRANSFER_IN": ("transfers", "other_transfer"),

    # --- Income ---
    "INCOME_WAGES": ("income", "paycheck"),
    "INCOME_INTEREST_EARNED": ("income", "interest_and_dividends"),
    "INCOME_DIVIDENDS": ("income", "interest_and_dividends"),
    "INCOME_TAX_REFUND": ("income", "refunds_and_cashback"),
    "INCOME_OTHER_INCOME": ("income", "side_income_gig"),
    "INCOME_UNEMPLOYMENT": ("income", "paycheck"),
    "INCOME_RETIREMENT_PENSION": ("income", "paycheck"),

    # --- Other (fees, taxes, government) ---
    "BANK_FEES_ATM_FEES": ("other", "fees"),
    "BANK_FEES_OVERDRAFT_FEES": ("other", "fees"),
    "BANK_FEES_INSUFFICIENT_FUNDS": ("other", "fees"),
    "BANK_FEES_FOREIGN_TRANSACTION_FEES": ("other", "fees"),
    "BANK_FEES_OTHER_BANK_FEES": ("other", "fees"),
    "BANK_FEES_INTEREST_CHARGE": ("other", "fees"),
    "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT": ("other", "taxes"),
    "GOVERNMENT_AND_NON_PROFIT_DONATIONS": ("other", "donations"),
    "GOVERNMENT_AND_NON_PROFIT_GOVERNMENT_DEPARTMENTS_AND_AGENCIES": ("other", "taxes"),
    "GOVERNMENT_AND_NON_PROFIT_OTHER_GOVERNMENT_AND_NON_PROFIT": ("other", "taxes"),

    # --- Catch-all ---
    "OTHER": ("other", "uncategorized"),
    "Other": ("other", "uncategorized"),
}


# =============================================================================
# PAVE primary tag → (primary_id, sub_id)
#
# Pave tags are multi-label. Resolution: use the first non-generic tag.
# "Miscellaneous" and "Retail" are generic — skip to the next tag.
# =============================================================================

PAVE_TAG_TO_INTERNAL: dict[str, tuple[str, str]] = {
    # Food & Dining
    "Restaurant": ("food_and_dining", "restaurants"),
    "Grocery": ("food_and_dining", "groceries"),
    "Cafe": ("food_and_dining", "coffee_shops"),
    "Food Delivery": ("food_and_dining", "food_delivery"),
    "Liquor Store": ("food_and_dining", "alcohol_and_bars"),
    "Convenience Store": ("food_and_dining", "convenience_stores"),
    "Vending Machine": ("food_and_dining", "vending_and_snacks"),

    # Shopping
    "Retail": ("shopping", "general"),
    "Marketplace": ("shopping", "general"),
    "Shipping": ("shopping", "general"),
    "Pet": ("shopping", "pet_supplies"),

    # Transportation
    "Gas Station": ("transportation", "gas"),
    "Transportation": ("transportation", "public_transit"),
    "Taxi": ("transportation", "rideshare"),
    "Parking": ("transportation", "parking_and_tolls"),
    "Toll": ("transportation", "parking_and_tolls"),
    "Auto": ("transportation", "auto_maintenance"),

    # Bills
    "Utility": ("bills", "other_bills"),
    "Electric": ("bills", "electricity_and_gas"),
    "Gas": ("bills", "electricity_and_gas"),
    "Telecom": ("bills", "internet_and_phone"),
    "Insurance": ("bills", "insurance"),
    "Life Insurance": ("bills", "insurance"),
    "Rent": ("bills", "rent_mortgage"),
    "Bill": ("bills", "other_bills"),
    "Housing": ("bills", "rent_mortgage"),
    "SaaS": ("bills", "subscriptions"),

    # Entertainment
    "Streaming": ("entertainment", "streaming"),
    "Entertainment": ("entertainment", "other_entertainment"),
    "Gambling": ("gambling", "gambling"),

    # Health
    "Pharmacy": ("health", "pharmacy"),
    "Health": ("health", "doctor_and_dental"),
    "Health Insurance": ("health", "health_insurance"),
    "Gym": ("health", "gym_and_fitness"),

    # Personal Care
    "Personal Care": ("personal_care", "hair_and_beauty"),

    # Travel
    "Air Travel": ("travel", "flights"),
    "Hotel": ("travel", "hotels_and_lodging"),
    "Lodging": ("travel", "hotels_and_lodging"),
    "Car Rental": ("travel", "rental_cars"),
    "Travel": ("travel", "other_travel"),

    # Education
    "Tuition": ("education", "education"),

    # Transfers
    "Transfer": ("transfers", "internal"),
    "Transfer to Savings": ("transfers", "to_from_savings"),
    "Transfer From Savings": ("transfers", "to_from_savings"),
    "Transfer to Checking": ("transfers", "internal"),
    "Transfer From Checking": ("transfers", "internal"),
    "Round Up Transfer": ("transfers", "to_from_savings"),
    "Overdraft Protection Transfer": ("transfers", "internal"),
    "Payment App": ("transfers", "peer_to_peer"),
    "P2P Transfer": ("transfers", "peer_to_peer"),
    "Remittance App": ("transfers", "peer_to_peer"),
    "International Transfer": ("transfers", "other_transfer"),
    "Wire Transfer": ("transfers", "other_transfer"),
    "ACH": ("transfers", "other_transfer"),
    "ATM Withdrawal": ("transfers", "atm_withdrawal"),
    "ATM Deposit": ("transfers", "other_transfer"),
    "Branch Withdrawal": ("transfers", "atm_withdrawal"),
    "Branch Deposit": ("transfers", "other_transfer"),
    "Other Deposit": ("transfers", "other_transfer"),
    "Other Withdrawal": ("transfers", "other_transfer"),
    "Check": ("transfers", "other_transfer"),
    "Investment": ("transfers", "investment"),
    "Crypto": ("transfers", "investment"),

    # Debt & Loans
    "Loan": ("debt_and_loans", "personal_loan"),
    "Student Loan": ("debt_and_loans", "student_loan"),
    "Auto Loan": ("debt_and_loans", "auto_loan"),
    "Mortgage": ("debt_and_loans", "mortgage_payment"),
    "Personal Loan": ("debt_and_loans", "personal_loan"),
    "Title Loan": ("debt_and_loans", "personal_loan"),
    "Credit Card Payment": ("debt_and_loans", "credit_card_payment"),
    "BNPL": ("debt_and_loans", "personal_loan"),
    "Lease to Own": ("debt_and_loans", "personal_loan"),
    "Cash Advance": ("debt_and_loans", "cash_advance_ewa"),
    "Earned Wage Access": ("debt_and_loans", "cash_advance_ewa"),
    "Credit Builder": ("debt_and_loans", "cash_advance_ewa"),
    "Debt Collection": ("debt_and_loans", "personal_loan"),
    "Debt Relief": ("debt_and_loans", "personal_loan"),

    # Income
    "Payroll": ("income", "paycheck"),
    "Direct Deposit": ("income", "paycheck"),
    "Gig Income": ("income", "side_income_gig"),
    "Creator Income": ("income", "side_income_gig"),
    "E-Commerce Revenue": ("income", "side_income_gig"),
    "Interest": ("income", "interest_and_dividends"),
    "Dividend": ("income", "interest_and_dividends"),
    "Pension": ("income", "paycheck"),
    "Benefits": ("income", "paycheck"),
    "Reimbursement": ("income", "refunds_and_cashback"),
    "Cashback": ("income", "refunds_and_cashback"),
    "Rewards": ("income", "refunds_and_cashback"),
    "Refund": ("income", "refunds_and_cashback"),

    # Other
    "ATM Fee": ("other", "fees"),
    "NSF Fee": ("other", "fees"),
    "Overdraft Fee": ("other", "fees"),
    "Account Service Fee": ("other", "fees"),
    "Money Transfer Fee": ("other", "fees"),
    "Foreign Exchange Fee": ("other", "fees"),
    "Tax": ("other", "taxes"),
    "Donation": ("other", "donations"),
    "Government Services": ("other", "taxes"),
    "Professional Services": ("bills", "other_bills"),

    # Generic / skip tags (used in multi-tag resolution)
    "Miscellaneous": ("other", "uncategorized"),
    "Subscription": ("bills", "subscriptions"),
    "Digital Services": ("bills", "subscriptions"),
    "Banking": ("transfers", "internal"),
}

# Tags to skip during multi-tag resolution (too generic to be useful as primary)
PAVE_GENERIC_TAGS: set[str] = {"Miscellaneous", "Retail", "Subscription", "ACH"}


def resolve_pave_tags(tags: list[str]) -> tuple[str, str] | None:
    """Resolve a list of Pave tags to an internal (primary_id, sub_id).

    Priority: first non-generic tag that has a mapping.
    """
    # First pass: skip generic tags
    for tag in tags:
        if tag not in PAVE_GENERIC_TAGS and tag in PAVE_TAG_TO_INTERNAL:
            return PAVE_TAG_TO_INTERNAL[tag]
    # Second pass: accept generic tags
    for tag in tags:
        if tag in PAVE_TAG_TO_INTERNAL:
            return PAVE_TAG_TO_INTERNAL[tag]
    return None


# =============================================================================
# EWA (Earned Wage Access) MERCHANT LIST
#
# These merchants are ALWAYS categorized as "Debt & Loans > Cash Advance / EWA"
# regardless of what Plaid or Pave says. Plaid commonly mislabels these as
# "GENERAL_SERVICES_ACCOUNTING_AND_FINANCIAL_PLANNING".
# =============================================================================

EWA_MERCHANTS: set[str] = {
    "Earnin",
    "Dave Inc",
    "Dave",
    "Brigit",
    "Cleo",
    "Albert Cash",
    "Albert",
    "Floatme",
    "Klover",
    "MoneyLion",
    "MoneyLion Instacash",
    "Chime MyPay",
    "Credit Genie",
    "Flex Finance",
    "Ava Finance",
    "Vola Finance",
    "True Finance",
    "Tilt Finance (formerly Empower)",
    "Tilt Finance",
}

# Normalized lowercase set for case-insensitive matching
EWA_MERCHANTS_LOWER: set[str] = {m.lower() for m in EWA_MERCHANTS}

EWA_CATEGORY: tuple[str, str] = ("debt_and_loans", "cash_advance_ewa")


def is_ewa_merchant(merchant_key: str) -> bool:
    return merchant_key.lower() in EWA_MERCHANTS_LOWER


# =============================================================================
# GAMBLING MERCHANT LIST
#
# These merchants are ALWAYS categorized as "Gambling > Gambling".
# Built from the top gambling merchants in the 460M corpus (18.4M transactions).
# =============================================================================

GAMBLING_MERCHANTS: set[str] = {
    "FanDuel",
    "FanDuel Sportsbook",
    "DraftKings",
    "Draft Kings",
    "Crown Coins Casino",
    "Hard Rock Bet",
    "BetMGM",
    "Bet MGM",
    "PrizePicks",
    "Prizepicks",
    "Chumba Casino",
    "Fanatics Sportsbook",
    "Fanatics",
    "Funzpoints",
    "Caesars Palace",
    "bet365",
    "BetRivers",
    "Golden Nugget Casino",
    "Pulsz.com",
    "LuckyLand Slots",
    "Myprize Games",
    "Modo.us",
    "Sorcery Reels",
    "Betfair",
    "Jackpocket",
}

GAMBLING_MERCHANTS_LOWER: set[str] = {m.lower() for m in GAMBLING_MERCHANTS}

GAMBLING_CATEGORY: tuple[str, str] = ("gambling", "gambling")


def is_gambling_merchant(merchant_key: str) -> bool:
    return merchant_key.lower() in GAMBLING_MERCHANTS_LOWER
