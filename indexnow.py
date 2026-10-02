#!/usr/bin/env python3
"""새 글 주소를 네이버·빙(IndexNow)에 즉시 알립니다. 실패해도 배포는 계속됩니다."""
import json, os, sys
from pathlib import Path
from urllib.parse import quote
import requests

ROOT = Path(__file__).resolve().parent.parent
site = json.loads((ROOT / "data/site.json").read_text(encoding="utf-8"))
base = (os.environ.get("SITE_URL") or site["site_url"]).rstrip("/")
key = site.get("indexnow_key")
if not key or "YOUR-GITHUB-ID" in base:
    print("IndexNow: 키 또는 SITE_URL 미설정 → 건너뜀"); sys.exit(0)
urls = [base + "/", base + "/guide/", base + "/sitemap.xml"]
for slug in sys.argv[1:]:
    if slug:
        urls.append(base + "/guide/" + quote(slug) + "/")
host = base.split("//", 1)[1].split("/")[0]
payload = {"host": host, "key": key, "keyLocation": f"{base}/{key}.txt", "urlList": urls}
for ep in ["https://searchadvisor.naver.com/indexnow", "https://api.indexnow.org/indexnow"]:
    try:
        r = requests.post(ep, json=payload, timeout=20)
        print(f"IndexNow {ep} → {r.status_code}")
    except Exception as e:
        print(f"IndexNow {ep} 실패: {e}")
