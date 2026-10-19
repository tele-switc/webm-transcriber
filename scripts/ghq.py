"""走 Clash 代理查 GitHub API，带重试（这台机器到 GitHub 的连接会间歇性被掐）。

用法：python scripts/ghq.py <API 路径> [jq 风格字段]
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

TOKEN = os.environ.get("GH_PAT", "")


def token() -> str:
    """优先用 GH_PAT；否则从本机 git 凭据里取（已 store 过）。"""
    global TOKEN
    if TOKEN:
        return TOKEN
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True, timeout=20).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            TOKEN = line[9:]
            break
    return TOKEN
PROXY = "http://127.0.0.1:7890"


OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def get(path: str, tries: int = 6):
    url = f"https://api.github.com{path}"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {token()}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "qoder-ghq",
                "X-GitHub-Api-Version": "2022-11-28",
            })
            with OPENER.open(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"  retry {i + 1}: {type(e).__name__} {e}", file=sys.stderr)
            time.sleep(2 + i * 2)
    return None


if __name__ == "__main__":
    if not token():
        print(json.dumps({"error": "no token"}))
        sys.exit(2)
    data = get(sys.argv[1])
    print(json.dumps(data if data is None else data, ensure_ascii=False)[: int(sys.argv[2])
          if len(sys.argv) > 2 else 4000])
