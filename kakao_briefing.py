#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
아침 마켓 브리핑 → 카카오톡 '나에게 보내기' 자동 발송
------------------------------------------------------------------
구성(섹션별로 여러 건 나눠 발송 — 카톡 텍스트 1건 200자 제한 대응):
  1) 📊 지수·환율 (코스피/코스닥/환율/다우/나스닥/S&P500)
  2) 🏢 인테리어 관련주 (한샘/LX하우시스/KCC/현대리바트)
  3) 🏠 인테리어 시장 뉴스
  4) 🏗 부동산·건설·정책 뉴스
  5) 💰 경제·금융 뉴스
  6) 📰 종합 헤드라인
  7) 🧰 소상공인 이슈

동작:
  - refresh_token 으로 access_token 자동 갱신
  - 주가/지수: Yahoo Finance 공개 차트 API
  - 뉴스: Google 뉴스 RSS
  - 카카오 '나에게 보내기'(메모) API 로 본인 카톡에 섹션별 전송

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

TEXT_LIMIT = 190          # 카톡 텍스트 템플릿 안전 한도
ARTICLES_PER_TOPIC = 3
TITLE_MAX = 45            # 기사 제목 표시 길이
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ── 지수·환율 / 종목 (Yahoo Finance 심볼) ───────────────────────────
INDICES = {
    "코스피": "^KS11", "코스닥": "^KQ11", "원/달러": "KRW=X",
    "다우": "^DJI", "나스닥": "^IXIC", "S&P500": "^GSPC",
}
INTERIOR_STOCKS = {
    "한샘": "009240.KS", "LX하우시스": "108670.KS",
    "KCC": "002380.KS", "현대리바트": "079430.KS",
}

# ── 뉴스 섹션 (Google 뉴스 RSS 검색어) ──────────────────────────────
NEWS_SECTIONS = {
    "🏠 인테리어 시장": "인테리어 리모델링 시장 OR 한샘 OR LX하우시스",
    "🏗 부동산·건설·정책": "부동산 정책 OR 주택 거래량 OR 재건축 OR 건설경기",
    "💰 경제·금융": "금리 OR 환율 OR 한국경제 OR 코스피 전망",
    "🧰 소상공인": "소상공인 OR 자영업 지원 OR 최저임금 OR 인건비",
}
HEADLINE_RSS = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"  # 종합 헤드라인


# ── 카카오 토큰 ────────────────────────────────────────────────────
def refresh_access_token() -> str:
    payload = {
        "grant_type": "refresh_token",
        "client_id": REST_API_KEY,
        "refresh_token": REFRESH_TOKEN,
    }
    if CLIENT_SECRET:
        payload["client_secret"] = CLIENT_SECRET
    resp = requests.post("https://kauth.kakao.com/oauth/token",
                         data=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
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


# ── 시세 조회 ──────────────────────────────────────────────────────
def quote(symbol: str):
    """Yahoo 차트 API로 현재가/전일대비% 반환. 실패 시 None."""
    try:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
               f"{urllib.parse.quote(symbol)}?interval=1d&range=2d")
        r = requests.get(url, headers=UA, timeout=10)
        m = r.json()["chart"]["result"][0]["meta"]
        price = m.get("regularMarketPrice")
        prev = m.get("chartPreviousClose") or m.get("previousClose")
        if price is None or not prev:
            return None
        pct = (price - prev) / prev * 100
        return price, pct
    except Exception:
        return None


def fmt_quote(name, q):
    if q is None:
        return f"{name} n/a"
    price, pct = q
    p = f"{price:,.0f}" if price >= 100 else f"{price:,.1f}"
    sign = "▲" if pct > 0 else ("▼" if pct < 0 else "-")
    return f"{name} {p} {sign}{abs(pct):.1f}%"


def build_market_blocks():
    idx = " / ".join(fmt_quote(n, quote(s)) for n, s in INDICES.items())
    stk = " / ".join(fmt_quote(n, quote(s)) for n, s in INTERIOR_STOCKS.items())
    return ["📊 지수·환율\n" + idx, "🏢 인테리어 관련주\n" + stk]


# ── 뉴스 조회 ──────────────────────────────────────────────────────
def news_block(header: str, rss_url: str):
    feed = feedparser.parse(rss_url)
    lines = [header]
    for e in feed.entries[:ARTICLES_PER_TOPIC]:
        t = e.title.split(" - ")[0][:TITLE_MAX]
        lines.append(f"• {t}")
    if len(lines) == 1:
        lines.append("• (관련 기사 없음)")
    return "\n".join(lines)


def build_news_blocks():
    blocks = []
    for header, query in NEWS_SECTIONS.items():
        q = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
        blocks.append(news_block(header, url))
    blocks.append(news_block("📰 종합 헤드라인", HEADLINE_RSS))
    return blocks


# ── 발송 ───────────────────────────────────────────────────────────
def send_memo(text: str, token: str):
    template = {
        "object_type": "text",
        "text": text[:TEXT_LIMIT],
        "link": {"web_url": "https://news.google.com/",
                 "mobile_web_url": "https://news.google.com/"},
        "button_title": "뉴스 더보기",
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
    blocks = [f"🗞 오늘의 마켓 브리핑 — {today}"]
    blocks += build_market_blocks()
    blocks += build_news_blocks()

    for i, b in enumerate(blocks, 1):
        res = send_memo(b, token)
        print(f"[{i}/{len(blocks)}] sent:", res)
        time.sleep(0.6)   # 연속 발송 간 간격


if __name__ == "__main__":
    main()
