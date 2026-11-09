"""Read-only Cockpit quota-cache bridge; cache age and explicit bucket identity gate ingestion."""
import hashlib
import argparse
import json
import math
import re
import time
from pathlib import Path
from .native_meter import MeterStore, normalize


def _cache_path(path):
    path = Path(path).resolve()
    if (path.parent.name != 'authorized' or path.parent.parent.name not in
            ('quota_api_v1_plugin', 'quota_api_v1_desktop') or path.parent.parent.parent.name != 'cache'
            or not re.fullmatch(r'[a-f0-9]{64}\.json', path.name)):
        raise ValueError('QUOTA_CACHE_PATH_REQUIRED')
    return path


def _timestamp(value):
    # Cockpit's QuotaApiCacheRecord.updated_at is Unix milliseconds, not file mtime.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('SOURCE_TIME_REQUIRED')
    return value / 1000


def _explicit_buckets(payload, bindings):
    quota = {}
    groups = payload.get('groups')
    if not isinstance(groups, list):
        raise ValueError('INVALID_BUCKET_GROUPS')
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get('buckets'), list):
            raise ValueError('INVALID_BUCKET_GROUPS')
        for bucket in group['buckets']:
            if not isinstance(bucket, dict):
                raise ValueError('INVALID_BUCKET')
            key = bucket.get('bucketId')
            if key:
                if key in quota:
                    raise ValueError('DUPLICATE_BUCKET')
                quota[key] = {'remaining_fraction': bucket.get('remainingFraction'),
                              'reset_time': bucket.get('resetTime')}
    return quota


def _bound_models(payload, bindings):
    quota = {}
    for model_key, bucket_id in bindings.items():
        model = payload.get('models', {}).get(model_key)
        if not isinstance(model, dict):
            raise ValueError('BOUND_MODEL_MISSING')
        info = model.get('quotaInfo')
        if not isinstance(info, dict):
            raise ValueError('BOUND_QUOTA_MISSING')
        row = {'remaining_fraction': info.get('remainingFraction'), 'reset_time': info.get('resetTime')}
        if bucket_id in quota and quota[bucket_id] != row:
            raise ValueError('CONFLICTING_POOL_OBSERVATIONS')
        quota[bucket_id] = row
    return quota


def _validated_record(path, now, max_age_s):
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('version') != 1 or data.get('source') != 'authorized':
        raise ValueError('CACHE_SCHEMA_OR_SOURCE')
    email = data.get('email')
    if not isinstance(email, str) or hashlib.sha256(email.strip().lower().encode()).hexdigest() != path.stem:
        raise ValueError('CACHE_ACCOUNT_BINDING_MISMATCH')
    observed = _timestamp(data.get('updatedAt'))
    if observed > now or now - observed > max_age_s:
        raise ValueError('STALE_OR_FUTURE_SOURCE')
    payload = data.get('payload')
    if not isinstance(payload, dict) or payload.get('quota_summary_stale') is True:
        raise ValueError('INVALID_OR_STALE_SUMMARY')
    return payload, observed, hashlib.sha256(raw).hexdigest()


def ingest_cache(path, store, *, now, max_age_s, bindings=None):
    """Ingest explicit quota identities only; caller bindings require independently verified provenance."""
    path = _cache_path(path)
    for value in (now, max_age_s):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('INVALID_CLOCK_OR_AGE')
    if max_age_s <= 0:
        raise ValueError('INVALID_CLOCK_OR_AGE')
    payload, observed, digest = _validated_record(path, now, max_age_s)
    quota = _explicit_buckets(payload, {}) if 'groups' in payload else _bound_models(payload, bindings or {})
    if not quota:
        raise ValueError('EXPLICIT_WINDOW_BINDING_REQUIRED')
    return _ingest_validated(store, path.stem, quota, observed, now, digest)


def _ingest_validated(store, account, quota, observed, now, digest):
    event = {'quota': quota}
    rows = normalize('antigravity', event, account=account, observed_at=observed, received_at=now)
    if any(row['window'] not in ('5h', '7d') or row['reset_at'] is None or row['reset_at'] <= now
           or row['remaining_pct'] is None for row in rows):
        raise ValueError('UNBOUND_WINDOW_OR_ELAPSED_RESET')
    count = store.ingest('antigravity', event, account=account, observed_at=observed, received_at=now)
    return {'ok': True, 'inserted': count, 'source_sha256': digest, 'source_observed_at': observed,
            'account': account, 'windows': sorted({row['window'] for row in rows}),
            'source': 'cockpit_quota_cache', 'automatic_refresh': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--max-age-s', type=float, required=True)
    args = parser.parse_args()
    try:
        result = ingest_cache(args.cache, MeterStore(args.db), now=time.time(), max_age_s=args.max_age_s)
    except (ValueError, OSError, TypeError, AttributeError) as error:
        reason = str(error)
        result = {'ok': False, 'reason': reason if re.fullmatch('[A-Z_]+', reason) else 'INVALID_CACHE',
                  'source': 'cockpit_quota_cache', 'automatic_refresh': False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
