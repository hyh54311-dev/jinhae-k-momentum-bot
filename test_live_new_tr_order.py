# -*- coding: utf-8 -*-
"""
=============================================================================
 [실전 검증 도구 2] KIS 신규 주문 TR ID (TTTC0012U / TTTC0011U) 1주 실체결 검증기
=============================================================================
 * 검증 목적:
   1. 실전 연금저축 계좌(prdt_cd="22")에서 신TR ID 정상 주문 접수 여부
   2. 매수 신TR: TTTC0012U (지정가 ORD_DVSN="00", 5원 호가)
   3. 매도 신TR: TTTC0011U (시장가 ORD_DVSN="01", 단가="0")
 * 대상 종목: TIGER 미국달러단기채권액티브 (329750, 1주 약 1.1만 원)
 * 주의: 평일 장중(09:00 ~ 15:30)에 실행 시 실제 1주 매수 및 매도가 집행됩니다.
=============================================================================
"""
import os
import sys
import datetime
import json
import time
import math
import requests
from dotenv import load_dotenv

# .env 로드
load_dotenv()
if not os.getenv("KIS_MOMENTUM_APP_KEY") and not os.getenv("KIS_APP_KEY"):
    parent_env = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(parent_env):
        load_dotenv(parent_env)

APP_KEY = os.getenv("KIS_MOMENTUM_APP_KEY") or os.getenv("KIS_APP_KEY")
APP_SECRET = os.getenv("KIS_MOMENTUM_APP_SECRET") or os.getenv("KIS_APP_SECRET")
CANO = os.getenv("KIS_PENSION_CANO") or os.getenv("KIS_STOCK_CANO")
PRDT_CD = "22"  # 연금저축펀드 계좌 전용
URL_BASE = "https://openapi.koreainvestment.com:9443"

# 테스트 대상 저가 안전자산 ETF (약 1.1만 원)
TEST_TICKER = "329750"
TEST_NAME = "TIGER 미국달러단기채권액티브"

print("====================================================================")
print("🔍 [도구 2] KIS 신규 주문 TR ID (TTTC0012U / TTTC0011U) 1주 실체결 검증")
print("====================================================================")

if not APP_KEY or not APP_SECRET or not CANO:
    print("❌ [.env 오류] APP_KEY, APP_SECRET, 또는 CANO 설정이 누락되었습니다.")
    sys.exit(1)

# 1. 접근 토큰 발급
print(f"1. 토큰 발급 및 계좌 확인 (대상 계좌: {CANO}-{PRDT_CD})...")
token_url = f"{URL_BASE}/oauth2/tokenP"
token_res = requests.post(token_url, json={
    "grant_type": "client_credentials",
    "appkey": APP_KEY,
    "appsecret": APP_SECRET
}, timeout=10)

if token_res.status_code != 200:
    print(f"❌ 토큰 발급 실패: {token_res.text}")
    sys.exit(1)

token = token_res.json().get("access_token")
print("✅ 토큰 발급 성공!")

# 2. 현재가 및 호가 조회 (FHKST01010100)
price_url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-price"
headers_price = {
    "content-type": "application/json; charset=utf-8",
    "authorization": f"Bearer {token}",
    "appkey": APP_KEY,
    "appsecret": APP_SECRET,
    "tr_id": "FHKST01010100",
    "custtype": "P"
}
params_price = {
    "FID_COND_MRKT_DIV_CODE": "J",
    "FID_INPUT_ISCD": TEST_TICKER
}
price_res = requests.get(price_url, headers=headers_price, params=params_price, timeout=10)
curr_price = float(price_res.json().get("output", {}).get("stck_prpr", 0))

# 5원 호가 올림 적용
buy_price = int(math.ceil(curr_price / 5) * 5)
print(f"2. {TEST_NAME}({TEST_TICKER}) 현재가: {curr_price:,.0f}원 ➔ 5원 호가 매수 지정가: {buy_price:,}원")

# 3. [1단계] 1주 지정가 매수 실체결 테스트 (TTTC0012U)
print("\n" + "="*68)
print(f"👉 [1단계: 매수 검증] 신TR 'TTTC0012U'로 1주 지정가({buy_price:,}원) 매수")
print("="*68)
confirm_buy = input("정말 1주 매수 주문을 KIS 실전 서버로 전송하시겠습니까? (y/N): ").strip().lower()

if confirm_buy == "y":
    order_url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/order-cash"
    headers_buy = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "TTTC0012U",
        "custtype": "P"
    }
    body_buy = {
        "CANO": CANO,
        "ACNT_PRDT_CD": PRDT_CD,
        "PDNO": TEST_TICKER,
        "ORD_DVSN": "00",             # 00 = 지정가
        "ORD_QTY": "1",               # 1주 (문자열)
        "ORD_UNPR": str(buy_price)    # 지정가 단가 (문자열)
    }
    res_buy = requests.post(order_url, headers=headers_buy, data=json.dumps(body_buy), timeout=10)
    data_buy = res_buy.json()
    
    print(f"\n[매수 응답 결과]")
    print(f" - rt_cd : {data_buy.get('rt_cd')}")
    print(f" - msg_cd: {data_buy.get('msg_cd')}")
    print(f" - msg1  : {data_buy.get('msg1')}")
    if data_buy.get("rt_cd") == "0":
        odno = data_buy.get("output", {}).get("ODNO", "")
        print(f" 🎉 [매수 신TR 검증 성공] 주문번호: {odno} (정상 접수 완료!)")
    else:
        print(f" ❌ [매수 실패] 서버 응답 오류 확인 필요")
else:
    print("ℹ️ 1단계 매수 테스트를 건너뛰었습니다.")

# 4. [2단계] 1주 시장가 매도 실체결 테스트 (TTTC0011U)
print("\n" + "="*68)
print(f"👉 [2단계: 매도 검증] 신TR 'TTTC0011U'로 1주 시장가(ORD_DVSN='01') 매도")
print("="*68)
confirm_sell = input("방금 매수된(또는 보유 중인) 1주를 시장가로 즉시 매도하시겠습니까? (y/N): ").strip().lower()

if confirm_sell == "y":
    headers_sell = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "TTTC0011U",
        "custtype": "P"
    }
    body_sell = {
        "CANO": CANO,
        "ACNT_PRDT_CD": PRDT_CD,
        "PDNO": TEST_TICKER,
        "ORD_DVSN": "01",             # 01 = 시장가
        "ORD_QTY": "1",               # 1주 (문자열)
        "ORD_UNPR": "0"               # 시장가 단가 0 고정
    }
    res_sell = requests.post(order_url, headers=headers_sell, data=json.dumps(body_sell), timeout=10)
    data_sell = res_sell.json()
    
    print(f"\n[매도 응답 결과]")
    print(f" - rt_cd : {data_sell.get('rt_cd')}")
    print(f" - msg_cd: {data_sell.get('msg_cd')}")
    print(f" - msg1  : {data_sell.get('msg1')}")
    if data_sell.get("rt_cd") == "0":
        odno = data_sell.get("output", {}).get("ODNO", "")
        print(f" 🎉 [매도 신TR 검증 성공] 주문번호: {odno} (정상 시장가 매도 완료!)")
    else:
        print(f" ❌ [매도 실패] 서버 응답 오류 확인 필요")
else:
    print("ℹ️ 2단계 매도 테스트를 건너뛰었습니다.")

print("\n====================================================================")
print("🏁 신규 TR ID 실체결 검증 테스트 종료")
print("====================================================================")
