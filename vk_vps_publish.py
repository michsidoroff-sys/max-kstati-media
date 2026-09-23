#!/usr/bin/env python3
"""Publish VK community posts from the VPS.

User OAuth is refreshed on this same server IP before uploading wall photos,
avoiding VK error 5 ('access_token was given to another ip address').
The community token is used for wall.post; user OAuth is used only for photo
upload methods that require a user token.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

import requests

API_BASE = "https://api.vk.com/method"
OAUTH_URL = "https://id.vk.com/oauth2/auth"
API_VERSION = os.getenv("VK_API_VERSION", "5.199")
TIMEOUT = 60
AUTH_DIR = Path(os.getenv("VK_AUTH_DIR", Path.home() / ".config" / "kstati-vk"))
AUTH_FILE = AUTH_DIR / "auth.json"


class VKError(RuntimeError):
    pass


def vk_call(method: str, token: str, **params: Any) -> Any:
    data = {"access_token": token, "v": API_VERSION, **params}
    r = requests.post(f"{API_BASE}/{method}", data=data, timeout=TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    if "error" in payload:
        e = payload["error"]
        raise VKError(f"{method}: VK error {e.get('error_code')}: {e.get('error_msg')}")
    return payload.get("response")


def load_auth() -> dict:
    if not AUTH_FILE.exists():
        raise VKError(f"OAuth data not found: {AUTH_FILE}. Run vk_vps_oauth.py first.")
    return json.loads(AUTH_FILE.read_text(encoding="utf-8"))


def save_auth(auth: dict) -> None:
    tmp = AUTH_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(auth, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(AUTH_FILE)


def refresh_user_token(auth: dict) -> str:
    state = hashlib.sha256(os.urandom(32)).hexdigest()
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": auth["refresh_token"],
        "client_id": str(auth["app_id"]),
        "device_id": auth["device_id"],
        "redirect_uri": auth["redirect_uri"],
        "state": state,
        "scope": auth.get("scope", "vkid.personal_info photos wall"),
    }
    r = requests.post(OAUTH_URL, data=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise VKError(f"VK ID refresh error: {data}")

    token = data.get("access_token")
    if not token:
        raise VKError(f"VK ID refresh returned no access_token: {data}")

    auth["access_token"] = token
    if data.get("refresh_token"):
        auth["refresh_token"] = data["refresh_token"]
    if data.get("scope"):
        auth["scope"] = data["scope"]
    auth["expires_in"] = data.get("expires_in")
    save_auth(auth)
    return token


def upload_photo(path: Path, group_id: int, user_token: str) -> str:
    server = vk_call("photos.getWallUploadServer", user_token, group_id=group_id)
    with path.open("rb") as fh:
        r = requests.post(server["upload_url"], files={"photo": (path.name, fh)}, timeout=TIMEOUT)
    r.raise_for_status()
    up = r.json()

    saved = vk_call(
        "photos.saveWallPhoto",
        user_token,
        group_id=group_id,
        photo=up.get("photo"),
        server=up.get("server"),
        hash=up.get("hash"),
    )
    if not saved:
        raise VKError("photos.saveWallPhoto returned no photo")
    p = saved[0]
    return f"photo{p['owner_id']}_{p['id']}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-file", required=True)
    parser.add_argument("--image", default="")
    args = parser.parse_args()

    group_id_raw = os.getenv("VK_GROUP_ID", "").lstrip("-")
    group_token = os.getenv("VK_GROUP_TOKEN", "").strip()
    if not group_id_raw.isdigit() or not group_token:
        raise VKError("Set VK_GROUP_ID and VK_GROUP_TOKEN in the VPS environment.")
    group_id = int(group_id_raw)

    text_path = Path(args.text_file)
    if not text_path.is_file():
        raise FileNotFoundError(text_path)
    message = text_path.read_text(encoding="utf-8").strip()
    if not message:
        raise VKError("Post text is empty.")

    attachment = ""
    image_path = Path(args.image) if args.image else None
    if image_path:
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        auth = load_auth()
        user_token = refresh_user_token(auth)
        attachment = upload_photo(image_path, group_id, user_token)
        print(f"Uploaded {attachment}")

    digest = hashlib.sha256()
    digest.update(str(group_id).encode())
    digest.update(b"\0")
    digest.update(message.encode())
    if image_path:
        digest.update(b"\0")
        digest.update(image_path.read_bytes())
    guid = digest.hexdigest()[:32]

    response = vk_call(
        "wall.post",
        group_token,
        owner_id=-group_id,
        from_group=1,
        message=message,
        attachments=attachment,
        guid=guid,
    )
    post_id = response["post_id"]
    print(f"Published: https://vk.com/wall-{group_id}_{post_id}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (VKError, FileNotFoundError, requests.RequestException, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
