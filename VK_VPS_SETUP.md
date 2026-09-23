# VK publishing through the VPS

Why: VK ID user tokens used by photo upload can be bound to the IP from which
the token was issued. GitHub Actions runs on changing runner IPs, so a token
issued in a browser can fail there with VK error 5.

The stable design is:

GitHub (content) → VPS (OAuth refresh + photo upload) → VK API.

## Files

- `vk_vps_oauth.py` — one-time OAuth bootstrap on the VPS.
- `vk_vps_publish.py` — refreshes user OAuth on the VPS, uploads a photo and
  publishes a post with the existing community token.
- `vk-callback.html` — registered callback page that only displays
  `code`, `device_id`, and `state`; it does NOT exchange tokens.

## Initial OAuth on VPS

Install dependency:

```bash
python3 -m pip install requests
```

Run:

```bash
python3 vk_vps_oauth.py prepare
```

Open the printed URL locally, approve VK ID, and copy the three callback values.

Then on the VPS:

```bash
python3 vk_vps_oauth.py finish
```

Paste `code`, `device_id`, and `state` when prompted.

Credentials are stored under `~/.config/kstati-vk/auth.json` with mode 600.

## VPS environment

Keep the community credentials in a root/user-readable env file, not in the
public repository:

```
VK_GROUP_ID=123456789
VK_GROUP_TOKEN=...
VK_API_VERSION=5.199
```

## Test publish on VPS

```bash
set -a
source /path/to/private.env
set +a
python3 vk_vps_publish.py --text-file vk/posts/api-test-image.txt --image coverstest-cover-01.png
```

Once this succeeds, wire GitHub Actions to SSH into this VPS and run the
publisher there. The OAuth tokens should not be stored in GitHub Secrets.
