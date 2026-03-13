"""
oauth.py — TikTok Login Kit OAuth 2.0 (PKCE)
Handles the full authorization flow:
  1. Generate PKCE code_verifier / code_challenge
  2. Build authorization URL → redirect user to TikTok
  3. Exchange authorization code for access_token + refresh_token
  4. Fetch user basic info (open_id, display_name, avatar)
  5. Refresh access_token when expired
  6. Revoke tokens on logout
"""

import hashlib
import base64
import secrets
import time
import json
import os
import requests
from pathlib import Path

# ── TikTok endpoints ────────────────────────────────────────────────────────────
TIKTOK_AUTH_URL   = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL  = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"
TIKTOK_USER_URL   = "https://open.tiktokapis.com/v2/user/info/"

# Scopes required for Content Posting API (Direct Post)
REQUIRED_SCOPES = "user.info.basic,video.upload,video.publish"

# Sandbox flag — set to True during TikTok app review / sandbox testing
SANDBOX_MODE = False  # toggle via config["sandbox_mode"]


# ── PKCE helpers ────────────────────────────────────────────────────────────────
def generate_code_verifier(length: int = 64) -> str:
    """Generate a PKCE code_verifier using only TikTok-allowed chars:
    [A-Z] / [a-z] / [0-9] / - / . / _ / ~  (min 43, max 128 chars)
    """
    import random
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    length = max(43, min(128, length))
    return "".join(secrets.choice(allowed) for _ in range(length))


def generate_code_challenge(code_verifier: str) -> str:
    """Derive code_challenge = HEX(SHA256(code_verifier)).
    TikTok Desktop Login Kit requires hex encoding, NOT base64url.
    Ref: https://developers.tiktok.com/doc/login-kit-desktop
    """
    return hashlib.sha256(code_verifier.encode("ascii")).hexdigest()


# ── Auth URL builder ────────────────────────────────────────────────────────────
def build_auth_url(
    client_key: str,
    redirect_uri: str,
    code_verifier: str,
    state: str | None = None,
    sandbox: bool = False,
) -> str:
    """
    Build the full TikTok Login Kit authorization URL.
    User is redirected here to grant permissions.
    """
    code_challenge = generate_code_challenge(code_verifier)
    if state is None:
        state = secrets.token_urlsafe(16)

    params = {
        "client_key":             client_key,
        "redirect_uri":           redirect_uri,
        "response_type":          "code",
        "scope":                  REQUIRED_SCOPES,
        "state":                  state,
        "code_challenge":         code_challenge,
        "code_challenge_method":  "S256",
    }
    if sandbox:
        params["environment"] = "sandbox"

    from urllib.parse import urlencode
    return f"{TIKTOK_AUTH_URL}?{urlencode(params)}"


# ── Token exchange ──────────────────────────────────────────────────────────────
def exchange_code_for_tokens(
    client_key: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict:
    """
    Exchange an authorization code for access_token + refresh_token.

    Returns dict with keys:
      access_token, refresh_token, open_id, scope,
      expires_in, refresh_expires_in, token_type,
      error (if failed), error_description
    """
    payload = {
        "client_key":    client_key,
        "client_secret": client_secret,
        "code":          code,
        "grant_type":    "authorization_code",
        "redirect_uri":  redirect_uri,
        "code_verifier": code_verifier,
    }
    try:
        resp = requests.post(
            TIKTOK_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=payload,
            timeout=20,
        )
        data = resp.json()
        if resp.status_code == 200 and "access_token" in data:
            # Compute absolute expiry timestamps
            now = int(time.time())
            data["access_token_expires_at"]  = now + data.get("expires_in", 86400)
            data["refresh_token_expires_at"] = now + data.get("refresh_expires_in", 2592000)
            data["error"] = None
        else:
            data.setdefault("error", f"HTTP {resp.status_code}")
            data.setdefault("error_description", resp.text[:200])
        return data
    except requests.exceptions.ConnectionError:
        return {"error": "connection_error", "error_description": "Sem ligação à internet"}
    except requests.exceptions.Timeout:
        return {"error": "timeout", "error_description": "TikTok não respondeu em 20s"}
    except Exception as exc:
        return {"error": "exception", "error_description": str(exc)}


# ── Token refresh ───────────────────────────────────────────────────────────────
def refresh_access_token(
    client_key: str,
    client_secret: str,
    refresh_token: str,
) -> dict:
    """
    Obtain a new access_token using refresh_token.
    Returns same structure as exchange_code_for_tokens.
    """
    payload = {
        "client_key":    client_key,
        "client_secret": client_secret,
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
    }
    try:
        resp = requests.post(
            TIKTOK_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=payload,
            timeout=20,
        )
        data = resp.json()
        if resp.status_code == 200 and "access_token" in data:
            now = int(time.time())
            data["access_token_expires_at"]  = now + data.get("expires_in", 86400)
            data["refresh_token_expires_at"] = now + data.get("refresh_expires_in", 2592000)
            data["error"] = None
        else:
            data.setdefault("error", f"HTTP {resp.status_code}")
            data.setdefault("error_description", resp.text[:200])
        return data
    except Exception as exc:
        return {"error": "exception", "error_description": str(exc)}


# ── Token revocation ────────────────────────────────────────────────────────────
def revoke_token(client_key: str, client_secret: str, token: str) -> bool:
    """Revoke an access or refresh token. Returns True on success."""
    try:
        resp = requests.post(
            TIKTOK_REVOKE_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"client_key": client_key, "client_secret": client_secret, "token": token},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ── User info ───────────────────────────────────────────────────────────────────
def get_user_info(access_token: str) -> dict:
    """
    Fetch basic user info from TikTok.
    Returns dict with open_id, display_name, avatar_url or error.
    """
    try:
        resp = requests.get(
            TIKTOK_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "open_id,union_id,avatar_url,display_name,profile_deep_link"},
            timeout=10,
        )
        data = resp.json()
        err = data.get("error", {})
        if err.get("code") == "ok":
            return {"ok": True, **data.get("data", {}).get("user", {})}
        return {"ok": False, "error": err.get("message", "Erro desconhecido")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Config helpers ───────────────────────────────────────────────────────────────
def save_tokens_to_config(config_path: str | Path, token_data: dict, user_info: dict) -> dict:
    """
    Persist access_token, refresh_token, open_id etc. into config.json.
    Returns the updated config dict.
    """
    config_path = Path(config_path)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}

    cfg["access_token"]               = token_data.get("access_token", "")
    cfg["refresh_token"]              = token_data.get("refresh_token", "")
    cfg["open_id"]                    = token_data.get("open_id", user_info.get("open_id", ""))
    cfg["token_scope"]                = token_data.get("scope", REQUIRED_SCOPES)
    cfg["access_token_expires_at"]    = token_data.get("access_token_expires_at", 0)
    cfg["refresh_token_expires_at"]   = token_data.get("refresh_token_expires_at", 0)
    cfg["connected_display_name"]     = user_info.get("display_name", "")
    cfg["connected_avatar_url"]       = user_info.get("avatar_url", "")
    cfg["connected_at"]               = int(time.time())
    cfg["auth_method"]                = "oauth_login_kit"  # audit flag

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def is_token_valid(cfg: dict, buffer_seconds: int = 300) -> bool:
    """Returns True if access_token exists and is not expiring within buffer_seconds."""
    if not cfg.get("access_token"):
        return False
    expires_at = cfg.get("access_token_expires_at", 0)
    if expires_at == 0:
        return True  # legacy token with no expiry stored — assume valid
    return int(time.time()) < (expires_at - buffer_seconds)


def is_refresh_token_valid(cfg: dict) -> bool:
    """Returns True if refresh_token exists and has not expired."""
    if not cfg.get("refresh_token"):
        return False
    expires_at = cfg.get("refresh_token_expires_at", 0)
    if expires_at == 0:
        return True
    return int(time.time()) < expires_at


def token_expires_in_human(cfg: dict) -> str:
    """Returns human-readable expiry string like '23h 45m' or 'Expirado'."""
    expires_at = cfg.get("access_token_expires_at", 0)
    if expires_at == 0:
        return "Token sem data de expiração"
    remaining = expires_at - int(time.time())
    if remaining <= 0:
        return "Expirado ⚠️"
    h = remaining // 3600
    m = (remaining % 3600) // 60
    if h > 24:
        d = h // 24
        return f"{d}d {h % 24}h"
    return f"{h}h {m}m"
