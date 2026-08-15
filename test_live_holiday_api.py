# -*- coding: utf-8 -*-
"""
=============================================================================
 [실전 검증 도구 1] KIS 공식 국내휴장일조회 (CTCA0903R) 24일치 실호출 검증기
=============================================================================
 * 검증 목적: 
   1. 실전 도메인(:9443)에서 CTCA0903R 정상 호출 여부
   2. BASS_DT를 '해당 월 17일'로 전달 시 24일치 달력 데이터 수신 여부
   3. opnd_yn("Y"/"N") 판정으로 17일 이후 첫 개장일이 정확히 추출되는지 확인
 * 주의: 조회 전용 API이므로 실제 주문이나 계좌 변동은 일절 발생하지 않습니다.
=============================================================================
"""
import os
import sys
import datetime
import json
import requests
from dotenv import load_dotenv

# Windows 콘솔 인코딩 대응
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# .env 로드
load_dotenv()
if not os.getenv("KIS_MOMENTUM_APP_KEY") and not os.getenv("KIS_APP_KEY"):
    parent_env = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(parent_env):
        load_dotenv(parent_env)

APP_KEY = os.getenv("KIS_MOMENTUM_APP_KEY") or os.getenv("KIS_APP_KEY")
APP_SECRET = os.getenv("KIS_MOMENTUM_APP_SECRET") or os.getenv("KIS_APP_SECRET")
URL_BASE = "https://openapi.koreainvestment.com:9443"

print("====================================================================")
print("🔍 [도구 1] KIS 국내휴장일조회 (CTCA0903R) 24일치 실시간 응답 검증")
print("====================================================================")

if not APP_KEY or not APP_SECRET:
    print("❌ [.env 오류] KIS_MOMENTUM_APP_KEY 또는 KIS_APP_SECRET이 설정되지 않았습니다.")
    print("   .env 파일의 API 키 설정을 확인해 주세요.")
    sys.exit(1)

# 1. OAuth 2.0 접근 토큰 발급
print("1. KIS 실전 서버 토큰 발급 요청 (/oauth2/tokenP)...")
token_url = f"{URL_BASE}/oauth2/tokenP"
token_res = requests.post(token_url, json={
    "grant_type": "client_credentials",
    "appkey": APP_KEY,
    "appsecret": APP_SECRET
}, timeout=10)

if token_res.status_code != 200:
    print(f"❌ 토큰 발급 실패 (HTTP {token_res.status_code}): {token_res.text}")
    sys.exit(1)

token = token_res.json().get("access_token")
print("✅ 토큰 발급 완료!")

# 2. 이번 달 17일(BASS_DT) 기준 휴장일 API 호출
today = datetime.date.today()
base_date = datetime.date(today.year, today.month, 17)
base_str = base_date.strftime("%Y%m%d")

print(f"\n2. CTCA0903R API 호출 (기준일자 BASS_DT={base_str}, 실전 도메인 :9443)...")
holiday_url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/chk-holiday"
headers = {
    "content-type": "application/json; charset=utf-8",
    "authorization": f"Bearer {token}",
    "appkey": APP_KEY,
    "appsecret": APP_SECRET,
    "tr_id": "CTCA0903R",
    "custtype": "P"
}
params = {
    "BASS_DT": base_str,
    "CTX_AREA_NK": "",
    "CTX_AREA_FK": ""
}

res = requests.get(holiday_url, headers=headers, params=params, timeout=10)
print(f"   - HTTP 상태 코드: {res.status_code}")

if res.status_code == 200:
    data = res.json()
    rt_cd = data.get("rt_cd")
    msg1 = data.get("msg1")
    output = data.get("output", [])
    if isinstance(output, dict):
        output = [output]
        
    print(f"   - KIS 응답 코드 (rt_cd): {rt_cd} ({msg1.strip() if msg1 else ''})")
    print(f"   - 수신된 달력 일수: 총 {len(output)}일치\n")
    print("--------------------------------------------------------------------")
    print(f"{'날짜':^12} | {'요일':^6} | {'개장 여부 (opnd_yn)':^18} | {'영업일 (bzdy_yn)'}")
    print("--------------------------------------------------------------------")
    
    first_open_day = None
    wday_names = {"01": "일", "02": "월", "03": "화", "04": "수", "05": "목", "06": "금", "07": "토"}
    
    for item in output:
        dt = item.get("bass_dt", "")
        opnd = item.get("opnd_yn", "")
        bzdy = item.get("bzdy_yn", "")
        wcd = item.get("wday_dvsn_cd", "")
        wname = wday_names.get(wcd, "-")
        
        status_tag = "🟢 개장일 (Trading)" if opnd == "Y" else "🔴 휴장일 (Closed)"
        dt_fmt = f"{dt[:4]}-{dt[4:6]}-{dt[6:]}" if len(dt) == 8 else dt
        print(f"{dt_fmt:^12} | {wname:^6} | {status_tag:<18} | {bzdy:^8}")
        
        if opnd == "Y" and first_open_day is None:
            first_open_day = dt_fmt
            
    print("--------------------------------------------------------------------")
    print(f"🎯 [최종 판정] 당월 17일 기준 첫 번째 리밸런싱 실행일: [{first_open_day}]")
    print("====================================================================")
else:
    print(f"❌ 휴장일 API 통신 실패: {res.text}")
