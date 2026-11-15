"""Cloudflare R2 uploader (S3-compatible).

Optional: if any of R2_ACCOUNT_ID / R2_BUCKET / R2_ACCESS_KEY_ID /
R2_SECRET_ACCESS_KEY / R2_PUBLIC_BASE is missing, is_configured() returns
False and callers skip R2. The cred-agent runs happily in local-only mode.

Endpoint pattern: https://<account_id>.r2.cloudflarestorage.com
Signature: AWS SigV4 via boto3 — R2 is S3-compatible.
"""
from __future__ import annotations

import os
from typing import Optional

# Cloudflare's bot-shield will 403 requests with Python's default urllib UA.
# Any non-Python UA passes. This is used nowhere inside this module but is
# exported so callers that want to immediately GET-back-fetch the uploaded
# object can reuse the same string.
VERIFY_USER_AGENT = "nova-cred/0.2"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def is_configured() -> bool:
    return all(_env(k) for k in (
        "R2_ACCOUNT_ID", "R2_BUCKET",
        "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
        "R2_PUBLIC_BASE",
    ))


def public_url(key: str) -> str:
    base = _env("R2_PUBLIC_BASE").rstrip("/")
    return f"{base}/{key.lstrip('/')}"


def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload bytes to R2. Returns the public URL. Raises on failure."""
    if not is_configured():
        raise RuntimeError("R2 not configured; set R2_* env vars first")
    # Lazy import so the service boots even if boto3 is missing until install.
    import boto3  # type: ignore
    from botocore.config import Config  # type: ignore

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{_env('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
        aws_access_key_id=_env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",  # R2 ignores region but boto3 wants one
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )
    client.put_object(
        Bucket=_env("R2_BUCKET"),
        Key=key,
        Body=data,
        ContentType=content_type,
        CacheControl="public, max-age=31536000, immutable",
    )
    return public_url(key)


def head(key: str) -> Optional[dict]:
    """Check if an object exists. Returns metadata dict or None."""
    if not is_configured():
        return None
    import boto3  # type: ignore
    from botocore.exceptions import ClientError  # type: ignore

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{_env('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
        aws_access_key_id=_env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )
    try:
        return client.head_object(Bucket=_env("R2_BUCKET"), Key=key)
    except ClientError:
        return None
