from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


MODEL = os.environ.get("COREWEAVER_MODEL") or "gemini-flash-latest"
API_KEY = os.environ.get("GEMINI_API_KEY")


def main() -> int:
    if not API_KEY:
        print(json.dumps({"ok": False, "error": "missing GEMINI_API_KEY"}, indent=2))
        return 1

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": "Reply with exactly: COREWEAVER_GEMINI_OK"},
                ],
            }
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": API_KEY},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - public Gemini API smoke endpoint.
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            error = json.loads(body).get("error", body)
        except json.JSONDecodeError:
            error = body[:1000]
        print(json.dumps({"ok": False, "http_status": exc.code, "error": error}, indent=2, ensure_ascii=False))
        return 1
    except urllib.error.URLError as exc:
        print(json.dumps({"ok": False, "error": f"network error: {exc.reason}"}, indent=2))
        return 1

    text = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
        .strip()
    )
    print(json.dumps({"ok": bool(text), "model": MODEL, "text": text}, indent=2, ensure_ascii=False))
    return 0 if text else 1


if __name__ == "__main__":
    raise SystemExit(main())
