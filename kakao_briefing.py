#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
인테리어 마켓 아침 브리핑 → 카카오톡 '나에게 보내기' 자동 발송
------------------------------------------------------------------
동작 순서:
  1) refresh_token 으로 access_token 자동 갱신
  2) Google 뉴스 RSS 에서 키워드별 최신 기사 수집
  3) 브리핑 텍스트 조립
  4) 카카오 '나에게 보내기'(메모) API 로 본인 카톡에 전송

사전 준비 (자세한 건 셋업 가이드 참고):
  - 카카오 개발자 앱 생성 → REST API 키 발급
  - 카카오 로그인 동의항목에 'talk_message' 추가
  - 최초 1회 OAuth 로 refresh_token 발급 후 아래 .env 에 저장

필요 패키지:  pip install requests feedparser python-dotenv
"""

import os
import datetime
import urllib.parse
import requests
import feedparser
from dotenv import load_dotenv

load_dotenv()

REST_API_KEY  = os.getenv("KAKAO_REST_API_KEY")
REFRESH_TOKEN = os.getenv("KAKAO_REFRESH_TOKEN")
CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET")  # 클라이언트 시크릿 활성화 시 필요

# 영역별 검색 키워드 (Google 뉴스 RSS, 한국어/한국 지역)
TOPICS = {
    "🏠 국내 인테리어 시장": "인테리어 리모델링 시장 OR 한샘 OR LX하우시스",
    "🏗 부동산·건설 연계":   "리모델링 수요 OR 주택 거래량 OR 건설경기",
    "🌍 해외 트렌드":        "interior design trend 2026",
    "🧪 소재·기술·신제품":   "인테리어 친환경 자재 OR 스마트홈 신제품",
}
ARTICLES_PER_TOPIC = 3


def refresh_access_token() -> str:
    """refresh_token 으로 access_token 갱신."""
    payload = {
        "grant_type": "refresh_token",
        "client_id": REST_API_KEY,
        "refresh_token": REFRESH_TOKEN,
    }
    if CLIENT_SECRET:
        payload["client_secret"] = CLIENT_SECRET
    resp = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data=payload,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    # refresh_token 이 함께 갱신되면 .env 에 새로 저장해 두는 것이 안전
    if "refresh_token" in data:
        _update_env("KAKAO_REFRESH_TOKEN", data["refresh_token"])
    return data["access_token"]


def _update_env(key: str, value: str):
    """.env 파일의 키 값을 갱신 (refresh_token 회전 대비)."""
    path = ".env"
    lines, found = [], False
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    for i, line in enumerate(lines):
        if line.startswith(key + "="):
            lines[i] = f"{key}={value}\n"
            found = True
    if not found:
        lines.append(f"{key}={value}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def fetch_news() -> str:
    """키워드별 RSS 수집 → 브리핑 본문 조립."""
    today = datetime.date.today().strftime("%Y.%m.%d (%a)")
    parts = [f"🗞 인테리어 마켓 브리핑 — {today}\n"]
    for title, query in TOPICS.items():
        q = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(url)
        parts.append(f"\n{title}")
        if not feed.entries:
            parts.append(" • (관련 기사 없음)")
            continue
        for entry in feed.entries[:ARTICLES_PER_TOPIC]:
            parts.append(f" • {entry.title}\n   {entry.link}")
    return "\n".join(parts)


def send_to_kakao(text: str, access_token: str):
    """카카오 '나에게 보내기'(메모) API. 텍스트 템플릿은 최대 200자 본문 권장,
    길면 카카오가 자르므로 여기서는 텍스트+더보기 링크 구조로 전송."""
    # 카톡 텍스트 메시지 본문은 최대 200자. 초과분은 잘리므로 핵심 요약만 담고
    # 전체는 link 로 연결하는 것이 이상적. MVP 에서는 앞부분만 전송.
    template = {
        "object_type": "text",
        "text": text[:1000],   # 카카오 text 템플릿 한도(약 1,000자) 내로 제한
        "link": {"web_url": "https://news.google.com/",
                 "mobile_web_url": "https://news.google.com/"},
        "button_title": "뉴스 더보기",
    }
    resp = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": __import__("json").dumps(template)},
        timeout=10,
    )
    resp.raise_for_status()
    print("✅ 카카오 발송 완료:", resp.json())


def main():
    if not REST_API_KEY or not REFRESH_TOKEN:
        raise SystemExit("⚠️  .env 에 KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN 를 먼저 설정하세요.")
    token = refresh_access_token()
    briefing = fetch_news()
    print(briefing)            # 콘솔에도 출력 (디버깅용)
    send_to_kakao(briefing, token)


if __name__ == "__main__":
    main()
