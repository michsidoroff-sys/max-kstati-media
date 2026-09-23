#!/usr/bin/env python3
"""Publish a text/image post to a VK community wall.

Secrets/environment:
  VK_GROUP_ID      numeric community id, without the leading minus
  VK_GROUP_TOKEN   community access token (recommended for wall.post)
  VK_USER_TOKEN    optional user token; currently needed when VK rejects
                   community tokens for wall photo uploads
  VK_API_VERSION   optional, defaults to 5.199

The post GUID is deterministic for the same group/message/image, so rerunning
the same payload is protected from accidental duplicate wall posts by VK.
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
DEFAULT_API_VERSION = "5.199"
TIMEOUT = 60


class VKError(RuntimeError):
    pass


def vk_call(method: str, token: str, api_version: str, **params: Any) -> Any:
    payload = {
        "access_token": token,
        "v": api_version,
        **{k: v for k, v in params.items() if v is not None and v != ""},
    }
    response = requests.post(
        f"{API_BASE}/{method}",
        data=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        err = data["error"]
        code = err.get("error_code", "?")
        message = err.get("error_msg", "VK API error")
        raise VKError(f"{method}: VK error {code}: {message}")
    return data.get("response")


def normalize_group_id(raw: str) -> int:
    value = raw.strip()
    for prefix in ("club", "public", "-"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    if not value.isdigit() or int(value) <= 0:
        raise ValueError("VK_GROUP_ID must be a positive numeric community ID.")
    return int(value)


def load_message(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Text file not found: {path}")
    message = path.read_text(encoding="utf-8").strip()
    if not message:
        raise ValueError(f"Text file is empty: {path}")
    return message


def make_guid(group_id: int, message: str, image_path: Path | None) -> str:
    digest = hashlib.sha256()
    digest.update(str(group_id).encode("utf-8"))
    digest.update(b"\0")
    digest.update(message.encode("utf-8"))
    if image_path:
        digest.update(b"\0")
        digest.update(image_path.read_bytes())
    return digest.hexdigest()[:32]


def upload_wall_photo(
    image_path: Path,
    group_id: int,
    group_token: str,
    user_token: str,
    api_version: str,
) -> str:
    if not image_path.is_file():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    # A user token is preferred for wall-photo upload. VK currently may return
    # error 27 for photos.getWallUploadServer with a community token even when
    # that token has the photos permission. We still try the available token so
    # the workflow will automatically benefit if VK changes that restriction.
    upload_token = user_token or group_token
    if not upload_token:
        raise VKError("No VK token is available for image upload.")

    try:
        server = vk_call(
            "photos.getWallUploadServer",
            upload_token,
            api_version,
            group_id=group_id,
        )
    except VKError as exc:
        if not user_token and "error 27" in str(exc).lower():
            raise VKError(
                "VK rejected the community token for wall photo upload. "
                "Add a repository secret named VK_USER_TOKEN and rerun."
            ) from exc
        raise

    upload_url = server["upload_url"]
    with image_path.open("rb") as fh:
        upload_response = requests.post(
            upload_url,
            files={"photo": (image_path.name, fh)},
            timeout=TIMEOUT,
        )
    upload_response.raise_for_status()
    uploaded = upload_response.json()

    saved = vk_call(
        "photos.saveWallPhoto",
        upload_token,
        api_version,
        group_id=group_id,
        photo=uploaded.get("photo"),
        server=uploaded.get("server"),
        hash=uploaded.get("hash"),
    )

    if not saved:
        raise VKError("photos.saveWallPhoto returned no photo.")
    photo = saved[0]
    return f"photo{photo['owner_id']}_{photo['id']}"


def append_summary(text: str) -> None:
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-file", required=True)
    parser.add_argument("--image", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    text_path = Path(args.text_file)
    image_path = Path(args.image) if args.image.strip() else None
    message = load_message(text_path)

    if image_path and not image_path.is_file():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    raw_group_id = os.getenv("VK_GROUP_ID", "").strip()

    if args.dry_run:
        image_info = str(image_path) if image_path else "(none)"
        print("DRY RUN — nothing will be published.")
        print(f"Text file: {text_path}")
        print(f"Image: {image_info}")
        print(f"Message length: {len(message)} characters")
        if raw_group_id:
            try:
                print(f"Group ID: {normalize_group_id(raw_group_id)}")
            except ValueError:
                print("Group ID secret exists but is not a valid numeric ID.")
        else:
            print("Group ID: not configured yet (allowed in dry-run)")
        append_summary(
            "### VK publish dry run ✅\n"
            f"- Text: `{text_path}`\n"
            f"- Image: `{image_info}`\n"
            f"- Message length: {len(message)} characters"
        )
        return 0

    if not raw_group_id:
        raise VKError("Missing repository secret VK_GROUP_ID.")
    group_id = normalize_group_id(raw_group_id)

    group_token = os.getenv("VK_GROUP_TOKEN", "").strip()
    user_token = os.getenv("VK_USER_TOKEN", "").strip()
    post_token = group_token or user_token
    if not post_token:
        raise VKError(
            "Missing VK token. Add VK_GROUP_TOKEN (recommended) or VK_USER_TOKEN."
        )

    api_version = os.getenv("VK_API_VERSION", DEFAULT_API_VERSION).strip()
    attachments = ""

    if image_path:
        attachments = upload_wall_photo(
            image_path,
            group_id,
            group_token,
            user_token,
            api_version,
        )
        print(f"Uploaded attachment: {attachments}")

    guid = make_guid(group_id, message, image_path)
    response = vk_call(
        "wall.post",
        post_token,
        api_version,
        owner_id=-group_id,
        from_group=1,
        signed=0,
        message=message,
        attachments=attachments,
        guid=guid,
    )

    post_id = response["post_id"]
    post_url = f"https://vk.com/wall-{group_id}_{post_id}"
    print(f"Published: {post_url}")
    print(f"GUID: {guid}")

    append_summary(
        "### VK post published ✅\n"
        f"- Post: {post_url}\n"
        f"- GUID: `{guid}`\n"
        f"- Image attached: {'yes' if image_path else 'no'}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (VKError, ValueError, FileNotFoundError, requests.RequestException, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        append_summary(f"### VK publish failed ❌\n`{exc}`")
        raise SystemExit(1)
