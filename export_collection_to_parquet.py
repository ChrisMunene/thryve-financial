from datetime import datetime
from pathlib import Path
import math
import sys
import re

from bson import ObjectId
from pymongo import MongoClient
import pyarrow as pa
import pyarrow.parquet as pq

MONGO_URI = "mongodb://127.0.0.1:37018"
DB_NAME = "work"
BATCH_SIZE = 50000
DEFAULT_OUT_ROOT = "/Volumes/SN7100-2TB/parquet"

# Per-collection projections: only these fields will be exported.
# If a collection is not listed here, all fields are exported.

PROJECTIONS = {
    # "my_collection": ["field1", "field2", "nested.field"],
    "users": [
        "isAutopayOn",
        "isFrozenUntilSuccessfulRepayment",
        "isFrozenIndefinitely",
        "isFrozenByUsBecauseLatePayment",
        "isCardLockedByUser",
        "graduationDate",
        "isSafeFreezeOn",
        "phoneNumber",
        "createdAt",
        "signUpStage",
        "firstName",
        "lastName",
        "email",
        "birthdate",
        "address",
        "universityId",
        "notificationAuthStatus",
        "referralCode",
        "shippingAddress",
        "riskLevel",
        "hasEnabledBiometricAuth",
        "hasEnabledNotifications",
        "points",
        "hasMadeFirstTransaction",
        "risk",
        "isReferringOthersBlocked",
        "isActiveStudent",
        "activeSubscriptionTier",
        "isFizzEmployee",
        "totalXp",
        "activeDevice",
        "onboardingStates",
        "signUpVersion",
        "lastSubscribedAt",
        "lastGlobalTransactionUpdateAt",
        "currentTimezone",
        "startedSignUpOnWeb",
        "attribution",
        "jobStatus",
        "lastConnectedBankAccountAt",
        "footprint",
        "alloy",
        "completedSignUpAt",
        "activeRewardsRotatingCategoryId",
    ],
    "bankaccounts": [
        "userId",
        "type",
        "subtype",
        "name",
        "connectionStatus",
        "isPrimary",
        "isNonDebitable",
        "institutionName",
        "passedKycCheck",
        "createdAt"
    ],
    "globaltransactions": [
        "userId",
        "source",
        "amount",
        "isoCurrencyCode",
        "name",
        "prettyName",
        "logoUrl",
        "paymentChannel",
        "category",
        "location",
        "website",
        "counterparties",
        "authorizedAt",
        "transactionMadeAtProxy",
        "isTimeApproximated",
        "createdAt",
        "settledAt",
        "necessityLevel",
        "pavePrettyName",
        "paveWebsite",
        "paveLogoUrl"
    ],
    
}

ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def maybe_parse_datetime_string(v):
    if not isinstance(v, str):
        return v
    if not ISO_DATETIME_RE.match(v):
        return v
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return v


def normalize_value(v):
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        return maybe_parse_datetime_string(v)
    if isinstance(v, dict):
        return {k: normalize_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [normalize_value(x) for x in v]
    return v

def normalize_doc(doc, fields=None):
    normalized = {k: normalize_value(v) for k, v in doc.items()}
    if fields:
        for f in fields:
            if f not in normalized:
                normalized[f] = None
    return normalized

def write_batch(rows, out_dir: Path, part_num: int):
    if not rows:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    out_file = out_dir / f"part-{part_num:06d}.parquet"
    pq.write_table(table, out_file, compression="zstd")

def export_collection(collection_name: str, out_root: str):
    client = MongoClient(MONGO_URI)
    coll = client[DB_NAME][collection_name]

    fields = PROJECTIONS.get(collection_name, [])
    projection = {field: 1 for field in fields} if fields else None

    out_dir = Path(out_root) / collection_name
    cursor = coll.find({}, projection, no_cursor_timeout=True).batch_size(BATCH_SIZE)

    rows = []
    part_num = 1
    count = 0

    try:
        for doc in cursor:
            rows.append(normalize_doc(doc, fields or None))
            count += 1

            if len(rows) >= BATCH_SIZE:
                write_batch(rows, out_dir, part_num)
                print(f"{collection_name}: wrote part {part_num}, rows={len(rows)}, total={count}")
                part_num += 1
                rows = []

        if rows:
            write_batch(rows, out_dir, part_num)
            print(f"{collection_name}: wrote part {part_num}, rows={len(rows)}, total={count}")

        print(f"{collection_name}: done, total rows={count}")
    finally:
        cursor.close()

if __name__ == "__main__":
    out_root = DEFAULT_OUT_ROOT
    args = sys.argv[1:]

    if "--out" in args:
        idx = args.index("--out")
        if idx + 1 >= len(args):
            print("Error: --out requires a path argument")
            sys.exit(1)
        out_root = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    collections = args
    if not collections:
        client = MongoClient(MONGO_URI)
        collections = client[DB_NAME].list_collection_names()
        collections.sort()
        print(f"No collections specified, exporting all {len(collections)}: {', '.join(collections)}")

    for name in collections:
        print(f"--- Exporting {name} ---")
        export_collection(name, out_root)
