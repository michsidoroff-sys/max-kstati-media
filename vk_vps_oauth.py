#!/usr/bin/env python3
"""One-time VK ID OAuth bootstrap for the VPS.

prepare: generate PKCE/state on the VPS and print an authorization URL.
finish:  paste code/device_id/state from the registered callback page; the
         authorization code is exchanged on the VPS so the user token is
         issued for the server IP. Refresh credentials are stored locally.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

import requests

APP_ID = 54786572
REDIRECT_URI = "https://michsidoroff-sys.github.io/max-kstati-media/vk-callback-v2.html"
SCOPES = "vkid.personal_info photos wall"
OAUTH_URL = "https://id.vk.com/oauth2/auth"
AUTHORIZE_URL = "https://id.vk.com/authorize"

CONFIG_DIR = Path(os.getenv("VK_AUTH_DIR", Path.home() / ".config" / "kstati-vk"))
PENDING_FILE = CONFIG_DIR / "oauth-pending.json"
AUTH_FILE = CONFIG_DIR / "auth.json"
TIMEOUT = 45


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass


def write_private(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def prepare() -> int:
    ensure_dir()
    verifier = b64url(secrets.token_bytes(64))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    state = b64url(secrets.token_bytes(24))

    write_private(PENDING_FILE, {
        "app_id": APP_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_verifier": verifier,
    })

    from urllib.parse import urlencode
    params = {
        "response_type": "code",
        "client_id": str(APP_ID),
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "scope": SCOPES,
    }

    print("\nОткройте эту ссылку в браузере:\n")
    print(AUTHORIZE_URL + "?" + urlencode(params))
    print("\nПосле подтверждения VK ID вернёт на callback-страницу.")
    print("На ней будут code, device_id и state. Затем выполните:")
    print("  python3 vk_vps_oauth.py finish")
    return 0


def finish() -> int:
    ensure_dir()
    if not PENDING_FILE.exists():
        raise RuntimeError("Сначала выполните: python3 vk_vps_oauth.py prepare")

    pending = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    print("Вставьте значения с callback-страницы. Они не будут выведены повторно.")
    code = input("code: ").strip()
    device_id = input("device_id: ").strip()
    returned_state = input("state: ").strip()

    if not code or not device_id:
        raise RuntimeError("code и device_id обязательны.")
    if returned_state != pending["state"]:
        raise RuntimeError("state не совпадает. Начните авторизацию заново.")

    payload = {
        "grant_type": "authorization_code",
        "client_id": str(APP_ID),
        "redirect_uri": REDIRECT_URI,
        "code_verifier": pending["code_verifier"],
        "device_id": device_id,
        "code": code,
        "state": pending["state"],
    }
    response = requests.post(OAUTH_URL, data=payload, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise RuntimeError(f"VK ID OAuth error: {data}")

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    if not access_token or not refresh_token:
        raise RuntimeError(f"VK ID did not return required tokens: {data}")

    write_private(AUTH_FILE, {
        "app_id": APP_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": data.get("scope", SCOPES),
        "device_id": device_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": data.get("expires_in"),
    })
    try:
        PENDING_FILE.unlink()
    except OSError:
        pass

    print("\nГотово ✅")
    print(f"Данные авторизации сохранены локально: {AUTH_FILE}")
    print("Токены в GitHub добавлять не нужно.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "finish"])
    args = parser.parse_args()
    return prepare() if args.command == "prepare" else finish()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, requests.RequestException, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
