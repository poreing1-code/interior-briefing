#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
아침 마켓 브리핑(핵심판) → 카카오톡 '나에게 보내기' 자동 발송
------------------------------------------------------------------
핵심 4건으로 압축 발송:
  1) 📊 지수·환율 (코스피/코스닥/원·달러/다우/나스닥/S&P500)
  2) 🏢 인테리어 관련주 (한샘/LX하우시스/KCC/현대리바트)
  3) 📰 핵심 뉴스 (인테리어·부동산정책·경제 각 1건)
  4) 🏛 정부 지원사업·소상공인 공고

필요 패키지:  pip install requests feedparser python-dotenv
"""

import os
import time
import json
import datetime
import urllib.parse
import requests
import feedparser
from dotenv import load_dotenv

load_dotenv()

REST_API_KEY  = os.getenv("KAKAO_REST_API_KEY")
REFRESH_TOKEN = os.getenv("KAKAO_REFRESH_TOKEN")
CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET")

TEXT_LIMIT = 195
TITLE_MAX = 48
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

INDICES = {
    "코스피": "^KS11", "코스닥": "^KQ11", "원/달러": "KRW=X",
    "다우": "^DJI", "나스닥": "^IXIC", "S&P500": "^GSPC",
}
INTERIOR_STOCKS = {
    "한샘": "009240.KS", "LX하우시스": "108670.KS",
    "KCC": "002380.KS", "현대리바트": "079430.KS",
}

# 핵심 뉴스: (라벨, 검색어, 건수)
CORE_NEWS = [
    ("🏠인테리어", "인테리어 리모델링 시장 OR 한샘 OR LX하우시스", 1),
    ("🏗부동산정책", "부동산 정책 OR 주택 거래량 OR 재건축 OR 건설경기", 1),
    ("💰경제금융", "금리 OR 환율 OR 한국경제 OR 코스피 전망", 1),
]
# 정부 지원사업·소상공인 공고
GOV_QUERY = ("소상공인 지원사업 공고 OR 정부 지원금 공고 OR "
             "창업지원 공고 OR 보조금 공고 OR 소상공인 지원")
GOV_COUNT = 3


# ── 카카오 토큰 ────────────────────────────────────────────────────
def refresh_access_token() -> str:
    payload = {"grant_type": "refresh_token", "client_id": REST_API_KEY,
               "refresh_token": REFRESH_TOKEN}
    if CLIENT_SECRET:
        payload["client_secret"] = CLIENT_SECRET
    r = requests.post("https://kauth.kakao.com/oauth/token",
                      data=payload, timeout=10)
    r.raise_for_status()
    data = r.json()
    if "refresh_token" in data:
        _update_env("KAKAO_REFRESH_TOKEN", data["refresh_token"])
    return data["access_token"]


def _update_env(key: str, value: str):
    path = ".env"
    lines, found = [], False
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    for i, line in enumerate(lines):
        if line.startswith(key + "="):
            lines[i] = f"{key}={value}\n"; found = True
    if not found:
        lines.append(f"{key}={value}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


# ── 시세 ───────────────────────────────────────────────────────────
def quote(symbol: str):
    try:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
               f"{urllib.parse.quote(symbol)}?interval=1d&range=2d")
        m = requests.get(url, headers=UA, timeout=10).json()
        m = m["chart"]["result"][0]["meta"]
        price = m.get("regularMarketPrice")
        prev = m.get("chartPreviousClose") or m.get("previousClose")
        if price is None or not prev:
            return None
        return price, (price - prev) / prev * 100
    except Exception:
        return None


def fmt_quote(name, q):
    if q is None:
        return f"{name} n/a"
    price, pct = q
    p = f"{price:,.0f}" if price >= 100 else f"{price:,.1f}"
    sign = "▲" if pct > 0 else ("▼" if pct < 0 else "-")
    return f"{name} {p} {sign}{abs(pct):.1f}%"


# ── 뉴스 ───────────────────────────────────────────────────────────
def rss_titles(query: str, count: int):
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(url)
    out = []
    for e in feed.entries[:count]:
        out.append(e.title.split(" - ")[0][:TITLE_MAX])
    return out


# ── 발송 ───────────────────────────────────────────────────────────
def send_memo(text: str, token: str, link_url="https://news.google.com/"):
    template = {
        "object_type": "text",
        "text": text[:TEXT_LIMIT],
        "link": {"web_url": link_url, "mobile_web_url": link_url},
        "button_title": "더보기",
    }
    r = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {token}"},
        data={"template_object": json.dumps(template)},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def main():
    if not REST_API_KEY or not REFRESH_TOKEN:
        raise SystemExit("⚠️  .env 에 KAKAO 키/토큰을 먼저 설정하세요.")
    token = refresh_access_token()
    today = datetime.date.today().strftime("%Y.%m.%d (%a)")

    # 1) 지수·환율
    idx = " / ".join(fmt_quote(n, quote(s)) for n, s in INDICES.items())
    msg1 = f"🗞 마켓 브리핑 {today}\n📊 지수·환율\n{idx}"

    # 2) 인테리어 관련주
    stk = " / ".join(fmt_quote(n, quote(s)) for n, s in INTERIOR_STOCKS.items())
    msg2 = f"🏢 인테리어 관련주\n{stk}"

    # 3) 핵심 뉴스 (분야별 1건)
    lines = ["📰 핵심 뉴스"]
    for label, query, cnt in CORE_NEWS:
        for t in rss_titles(query, cnt):
            lines.append(f"[{label}] {t}")
    msg3 = "\n".join(lines)

    # 4) 정부 지원사업·소상공인 공고
    gov = rss_titles(GOV_QUERY, GOV_COUNT)
    glines = ["🏛 정부지원·소상공인 공고"]
    glines += [f"• {t}" for t in gov] or ["• (관련 공고 없음)"]
    gov_link = "https://www.bizinfo.go.kr/"   # 기업마당(지원사업 포털)
    msg4 = "\n".join(glines)

    messages = [(msg1, "https://news.google.com/"),
                (msg2, "https://finance.naver.com/"),
                (msg3, "https://news.google.com/"),
                (msg4, gov_link)]

    for i, (m, link) in enumerate(messages, 1):
        res = send_memo(m, token, link)
        print(f"[{i}/{len(messages)}] sent:", res)
        time.sleep(0.6)


if __name__ == "__main__":
    main()
