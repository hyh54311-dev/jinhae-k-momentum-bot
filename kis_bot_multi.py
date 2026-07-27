# -*- coding: utf-8 -*-
"""
K-Dual Momentum Multi-Account Rebalancing Bot
Supports: Personal Stock Account (01) & Retirement Savings Account (22)
Enhanced with KIS_MOCK and KIS_DRY_RUN for institutional-grade safety.
"""
import os
import sys
import time
import datetime
import requests
import json
import math
from dotenv import load_dotenv
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Windows 콘솔 유니코드/이모지 출력 지원 설정 (cp949 인코딩 에러 방지)
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# .env 파일에서 계좌 정보 및 API 키 로드용 전역 변수 기본 설정
KIS_MOCK = False
KIS_DRY_RUN = False
MAX_ORDER_AMOUNT = 100000000
APP_KEY = ""
APP_SECRET = ""
URL_BASE = ""
ACCOUNTS = []
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# 포트폴리오 티커 설정
TICKER_KOSPI = "069500"    # KODEX 200 (한국 대표 주식)
TICKER_SP500 = "360750"    # TIGER 미국S&P500 (미국 대표 주식)
TICKER_GOLD  = "411060"    # ACE KRX금현물 (금 현물)
TICKER_TLT   = "476760"    # ACE 미국30년국채액티브 (미국 장기채)
TICKER_SAFE  = "329750"    # TIGER 미국달러단기채권액티브 (안전자산 피신처)

TICKER_NAMES = {
    TICKER_KOSPI: "KODEX 200 (한국 대표 주식)",
    TICKER_SP500: "TIGER 미국S&P500 (미국 대표 주식)",
    TICKER_GOLD: "ACE KRX금현물 (금 현물)",
    TICKER_TLT: "ACE 미국30년국채액티브 (미국 장기채)",
    TICKER_SAFE: "TIGER 미국달러단기채권액티브 (안전자산 피신처)"
}

# 한국거래소(KRX) 휴장일 목록 (YYYY-MM-DD)
KRX_HOLIDAYS = {
    # 2026년
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-03-01", "2026-03-02", "2026-05-05", "2026-05-25",
    "2026-06-06", "2026-07-17", "2026-08-15", "2026-08-17", "2026-09-24",
    "2026-09-25", "2026-09-26", "2026-09-28", "2026-10-03",
    "2026-10-05", "2026-10-09", "2026-12-25", "2026-12-31",
    # 2027년
    "2027-01-01", "2027-02-05", "2027-02-06", "2027-02-07",
    "2027-02-08", "2027-03-01", "2027-05-05", "2027-05-13",
    "2027-06-06", "2027-06-07", "2027-07-17", "2027-08-15", "2027-08-16",
    "2027-10-03", "2027-10-04", "2027-10-09", "2027-10-11",
    "2027-12-25", "2027-12-31"
}

def init_config():
    """실행 직전 최신 환경 변수를 읽어 동적 전역 변수를 완벽히 바인딩하는 함수"""
    global KIS_MOCK, KIS_DRY_RUN, MAX_ORDER_AMOUNT, APP_KEY, APP_SECRET, URL_BASE, ACCOUNTS, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()

    KIS_MOCK = os.getenv("KIS_MOCK", "False").lower() in ("true", "1", "yes")
    KIS_DRY_RUN = os.getenv("KIS_DRY_RUN", "False").lower() in ("true", "1", "yes")
    MAX_ORDER_AMOUNT = int(os.getenv("MAX_ORDER_AMOUNT", "100000000"))
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    if KIS_MOCK:
        APP_KEY = os.getenv("KIS_MOCK_APP_KEY", "")
        APP_SECRET = os.getenv("KIS_MOCK_APP_SECRET", "")
        URL_BASE = "https://openapivts.koreainvestment.com:29443"
        
        ACCOUNTS = []
        mock_cano1 = os.getenv("KIS_MOCK_CANO1", "")
        mock_cano2 = os.getenv("KIS_MOCK_CANO2", "")
        if mock_cano1:
            ACCOUNTS.append({"name": "모의_주식계좌1", "cano": mock_cano1, "prdt_cd": "01"})
        if mock_cano2:
            ACCOUNTS.append({"name": "모의_주식계좌2", "cano": mock_cano2, "prdt_cd": "01"})
        if not ACCOUNTS:
            pension_cano = os.getenv("KIS_PENSION_CANO", "")
            stock_cano = os.getenv("KIS_STOCK_CANO", "")
            if pension_cano: ACCOUNTS.append({"name": "모의_연금대체계좌", "cano": pension_cano, "prdt_cd": "01"})
            if stock_cano: ACCOUNTS.append({"name": "모의_개인주식계좌", "cano": stock_cano, "prdt_cd": "01"})
    else:
        APP_KEY = os.getenv("KIS_MOMENTUM_APP_KEY", os.getenv("KIS_APP_KEY", ""))
        APP_SECRET = os.getenv("KIS_MOMENTUM_APP_SECRET", os.getenv("KIS_APP_SECRET", ""))
        
        if not APP_KEY or not APP_SECRET:
            raise ValueError("🚨 [.env 설정 오류] 실전 투자용 KIS API Key/Secret이 설정되지 않았습니다.")

        URL_BASE = "https://openapi.koreainvestment.com:9443"
        ACCOUNTS = [
            {"name": "연금저축계좌", "cano": os.getenv("KIS_PENSION_CANO", "").strip(), "prdt_cd": "22"},
            {"name": "개인주식계좌", "cano": os.getenv("KIS_STOCK_CANO", "").strip(), "prdt_cd": "01"}
        ]

init_config()

def send_telegram(msg):
    prefix = ""
    if KIS_DRY_RUN:
        prefix = "[Dry-run 시뮬레이션] "
    elif KIS_MOCK:
        prefix = "[모의투자 테스트] "
    else:
        prefix = "[실전 리밸런싱] "
        
    full_msg = f"{prefix}{msg}"
    print(f"[TELEGRAM] {full_msg}")
    
    # 텔레그램 API 4096자 제한 대응 (안전 자름)
    if len(full_msg) > 4000:
        full_msg = full_msg[:3900] + "\n\n... (메시지 길이 초과로 이하 생략)"
    
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try:
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": full_msg}, timeout=5, verify=False)
        except Exception as e:
            print(f"텔레그램 메시지 발송 실패: {e}")

def kis_api_request(method, url, headers, params=None, data=None, max_retries=5, initial_backoff=1.5):
    backoff = initial_backoff
    last_res = None
    for attempt in range(max_retries):
        time.sleep(0.2)
        try:
            if method.upper() == "GET":
                res = requests.get(url, headers=headers, params=params, timeout=10, verify=False)
            else:
                res = requests.post(url, headers=headers, data=data, timeout=10, verify=False)
            
            last_res = res
            if res.status_code == 200:
                try:
                    res_data = res.json()
                    msg_cd = res_data.get("msg_cd", "")
                    rt_cd = res_data.get("rt_cd", "")
                    
                    if rt_cd != "0" and msg_cd in ("EGW00215", "EGW00201"):
                        print(f"⚠️ KIS API 빈도 제한/일시 오류 감지 (코드: {msg_cd}, 내용: {res_data.get('msg1')}). {backoff}초 후 재시도합니다. (시도 {attempt+1}/{max_retries})")
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                except Exception:
                    pass
                return res
            elif res.status_code in (429, 500, 502, 503, 504):
                print(f"⚠️ KIS API HTTP 오류 감지 (상태 코드: {res.status_code}). {backoff}초 후 재시도합니다. (시도 {attempt+1}/{max_retries})")
                time.sleep(backoff)
                backoff *= 2
                continue
            else:
                return res
        except requests.exceptions.RequestException as e:
            print(f"⚠️ KIS API 네트워크 통신 에러: {e}. {backoff}초 후 재시도합니다. (시도 {attempt+1}/{max_retries})")
            time.sleep(backoff)
            backoff *= 2
            
    if last_res is not None:
        return last_res
    raise Exception(f"KIS API 요청 실패 (최대 재시도 {max_retries}회 초과)")

def is_market_open():
    """주식시장 정규장 운영 시간 여부 판단 (평일 09:00 ~ 15:30 KST & 거래소 휴장일 검사)"""
    kst_tz = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(kst_tz)
    
    # 1. 주말 검사
    if now.weekday() >= 5:
        return False
        
    # 2. 거래소 공휴일 검사
    if now.strftime("%Y-%m-%d") in KRX_HOLIDAYS:
        return False
        
    # 3. 시간 검사 (09:00 ~ 15:30)
    start_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start_time <= now <= end_time

def get_access_token():
    url = f"{URL_BASE}/oauth2/tokenP"
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    res = kis_api_request("POST", url, headers=headers, data=json.dumps(body))
    if res.status_code == 200:
        return res.json()["access_token"]
    else:
        raise Exception(f"토큰 발급 오류 (모드_모의={KIS_MOCK}): {res.text}")

def get_orderable_cash(token, cano, prdt_cd, ticker="069500"):
    url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
    is_mock = KIS_MOCK or "openapim" in URL_BASE
    tr_id = "VTTC8908R" if is_mock else "TTTC8908R"
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P"
    }
    # [보완] 시장가(01) 조회 시 ORD_UNPR은 0 전달
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": prdt_cd,
        "PDNO": ticker,
        "ORD_UNPR": "0",
        "ORD_DVSN": "01",
        "CMA_EVLU_AMT_ICLD_YN": "N",
        "OVRS_ICLD_YN": "N"
    }
    try:
        res = kis_api_request("GET", url, headers=headers, params=params)
        if res.status_code == 200:
            data = res.json()
            if data.get("rt_cd") == "0":
                output = data.get("output", {})
                cash = int(output.get("ord_psbl_cash", 0))
                print(f"    - [TTTC8908R] 주문가능현금 조회 성공: {cash:,}원")
                return cash
            else:
                err_msg = f"⚠️ [TTTC8908R - {prdt_cd}] 주문가능현금 조회 실패 ({data.get('msg_cd')}): {data.get('msg1')}"
                print(err_msg)
                send_telegram(err_msg)
        else:
            err_msg = f"⚠️ [TTTC8908R - {prdt_cd}] HTTP 오류: {res.status_code}"
            print(err_msg)
            send_telegram(err_msg)
    except Exception as e:
        err_msg = f"⚠️ [TTTC8908R - {prdt_cd}] API 호출 에러: {e}"
        print(err_msg)
        send_telegram(err_msg)
    return None

def get_account_balance(token, cano, prdt_cd):
    url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/inquire-balance"
    is_mock = KIS_MOCK or "openapim" in URL_BASE
    tr_id = "VTTC8434R" if is_mock else "TTTC8434R"
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id
    }
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": prdt_cd,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "ORD_QTY_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    res = kis_api_request("GET", url, headers=headers, params=params)
    if res.status_code != 200:
        raise Exception(f"잔고 조회 API 호출 실패: {res.text}")
        
    data = res.json()
    if data.get("rt_cd") != "0":
        raise Exception(f"잔고 조회 API 실패 ({data.get('msg_cd')}): {data.get('msg1')}")
    
    cash = None
    if "output2" in data and len(data["output2"]) > 0:
        summary = data["output2"][0]
        
        debug_msg = (
            f"🔍 [계좌 잔고 API 디버깅 - {prdt_cd}]\n"
            f"- ord_psbl_cash(주문가능현금): {summary.get('ord_psbl_cash')} 원\n"
            f"- prvs_rcdl_excc_amt(당일정산금액): {summary.get('prvs_rcdl_excc_amt')} 원\n"
            f"- nxdy_excc_amt(익일정산금액): {summary.get('nxdy_excc_amt')} 원\n"
            f"- dnca_tot_amt(D+2예수금): {summary.get('dnca_tot_amt')} 원\n"
        )
        send_telegram(debug_msg)
        
        # [핵심 수정] 0원이라도 주문가능현금(ord_psbl_cash)이 반환되면 우선 채택
        # D+2 예수금(dnca_tot_amt)으로 스킵되어 과다 주문되는 오류 방지
        for field in ["ord_psbl_cash", "prvs_rcdl_excc_amt", "nxdy_excc_amt"]:
            if field in summary and summary[field] is not None:
                try:
                    cash = int(summary[field])
                    print(f"    - 예수금 최우선 필드({field}) 적용: {cash:,}원")
                    break
                except (ValueError, TypeError):
                    pass

        if cash is None:
            cash = int(summary.get("dnca_tot_amt", 0))

    # 매수가능조회 API(TTTC8908R) 교차 검증
    psbl_cash = get_orderable_cash(token, cano, prdt_cd)
    if psbl_cash is not None:
        print(f"    - [교차검증] TTTC8908R 주문가능현금: {psbl_cash:,}원 (기존 잔고조회 cash: {cash}원)")
        cash = psbl_cash

    if cash is None:
        cash = 0

    holdings = {}
    for item in data.get("output1", []):
        ticker = item["pdno"]
        qty = int(item["hldg_qty"])
        if qty > 0:
            holdings[ticker] = {
                "qty": qty,
                "price": float(item["prpr"]),
                "eval_amt": int(item["evlu_amt"])
            }
    return cash, holdings

def submit_order(token, cano, prdt_cd, ticker, qty, order_type="BUY", price=0, ord_dvsn="00"):
    is_mock = KIS_MOCK or "openapim" in URL_BASE
    
    if order_type == "BUY":
        tr_id = "VTTC0012U" if is_mock else "TTTC0012U"
    else:
        tr_id = "VTTC0011U" if is_mock else "TTTC0011U"
        
    url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/order-cash"
    
    if KIS_DRY_RUN:
        dry_msg = f"[DRY-RUN 시뮬레이션] {order_type} | 티커: {ticker} | 수량: {qty}주 | 구분: {ord_dvsn} | 지정가: {price:,}원 | 계좌: {cano}"
        print(dry_msg)
        return {
            "rt_cd": "0",
            "msg1": "[Dry-run] 시뮬레이션 주문이 정상 검증되었습니다.",
            "msg_cd": "DRY00000",
            "output": {"ODNO": "999999", "ORD_TMD": "090000"}
        }
        
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id
    }
    
    unpr = "0" if ord_dvsn == "01" else str(int(price))
    
    body = {
        "CANO": cano,
        "ACNT_PRDT_CD": prdt_cd,
        "PDNO": ticker,
        "ORD_DVSN": ord_dvsn,
        "ORD_QTY": str(qty),
        "ORD_UNPR": unpr
    }
    
    res = kis_api_request("POST", url, headers=headers, data=json.dumps(body))
    if res.status_code != 200:
        safe_headers = headers.copy()
        safe_headers["appkey"] = "MASKED"
        safe_headers["appsecret"] = "MASKED"
        safe_headers["authorization"] = "Bearer MASKED"
        
        err_msg = (
            f"🚨 [주문 API 에러 (HTTP {res.status_code})]\n"
            f"- 응답내용: {res.text}\n"
            f"- Body: {json.dumps(body, ensure_ascii=False)}"
        )
        send_telegram(err_msg)
        raise Exception(f"주문 통신 오류: {res.text}")
        
    return res.json()

def get_historical_prices_kis(ticker, token):
    url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHKST03010100"
    }
    
    kst_tz = datetime.timezone(datetime.timedelta(hours=9))
    today = datetime.datetime.now(kst_tz)
    date_2 = today.strftime("%Y%m%d")
    date_1 = (today - datetime.timedelta(days=730)).strftime("%Y%m%d")
    
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": ticker,
        "FID_INPUT_DATE_1": date_1,
        "FID_INPUT_DATE_2": date_2,
        "FID_PERIOD_DIV_CODE": "M",
        "FID_ORG_ADPR_YN": "Y"
    }
    
    res = kis_api_request("GET", url, headers=headers, params=params)
    if res.status_code == 200:
        data = res.json()
        if data.get("rt_cd") == "0":
            output2 = data.get("output2", [])
            prices = []
            for item in output2:
                clpr = item.get("stck_clpr")
                if clpr:
                    prices.append(float(clpr))
            
            prices.reverse()
            if len(prices) >= 13:
                print(f"    - [KIS API] 시세 조회 성공: {ticker} -> {len(prices)}개 데이터 확보 (최근가: {prices[-1]:,}원)")
                return prices[-13:]
            else:
                raise Exception(f"KIS API 월별 데이터 개수 부족: {len(prices)}개")
        else:
            raise Exception(f"KIS API 응답 에러 ({data.get('msg_cd')}): {data.get('msg1')}")
    else:
        raise Exception(f"KIS HTTP 에러: {res.status_code}")

def calculate_momentum_signals(token):
    def get_historical_prices(symbol, ticker):
        try:
            return get_historical_prices_kis(ticker, token)
        except Exception as ke:
            print(f"⚠️ KIS API 과거 시세 조회 실패 ({ticker}): {ke}. Yahoo Finance 폴백 실행.")
            
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1mo&range=2y"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=10, verify=False)
        if res.status_code != 200:
            raise Exception(f"Yahoo Finance API 연동 실패: {symbol} (HTTP {res.status_code})")
        result = res.json()["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        closes = result["indicators"]["quote"][0]["close"]
        
        monthly_data = {}
        kst_tz = datetime.timezone(datetime.timedelta(hours=9))
        for ts, close in zip(timestamps, closes):
            if close is not None:
                dt_str = datetime.datetime.fromtimestamp(ts, tz=kst_tz).strftime("%Y-%m")
                monthly_data[dt_str] = close
                
        sorted_months = sorted(monthly_data.keys())
        prices = [monthly_data[m] for m in sorted_months]
        if len(prices) < 13:
            raise Exception(f"데이터 개수 부족: {symbol}")
        return prices[-13:]

    print(">> 글로벌 증시 역사적 가격 데이터 분석 중...")
    ETF_TICKERS = {
        "KOSPI200": f"{TICKER_KOSPI}.KS",
        "SP500": f"{TICKER_SP500}.KS",
        "GOLD": f"{TICKER_GOLD}.KS",
        "TLT": f"{TICKER_TLT}.KS"
    }
    
    SHORT_SYMBOLS = {
        "KOSPI200": TICKER_KOSPI,
        "SP500": TICKER_SP500,
        "GOLD": TICKER_GOLD,
        "TLT": TICKER_TLT
    }
    
    prices_dict = {}
    returns_12m = {}
    
    for name, symbol in ETF_TICKERS.items():
        try:
            ticker = SHORT_SYMBOLS[name]
            prices = get_historical_prices(symbol, ticker)
            prices_dict[name] = prices
            returns_12m[name] = (prices[-1] - prices[-13]) / prices[-13]
        except Exception as e:
            raise Exception(f"🚨 모멘텀 계산 중 {name}({symbol}) 분석 실패: {e}")
        time.sleep(0.5)
        
    print(f"■ 모멘텀 데이터 분석 결과 (12개월 수익률):")
    for name, ret in returns_12m.items():
        print(f"    - {name}: {ret*100:.2f}%")
        
    best_asset = max(returns_12m, key=returns_12m.get)
    chosen_symbol = SHORT_SYMBOLS[best_asset]
    chosen_prices = prices_dict[best_asset]
    chosen_name = TICKER_NAMES[chosen_symbol]
    chosen_ret = returns_12m[best_asset]
    
    print(f">> 상대 모멘텀 1위 선정 자산: {chosen_name} ({chosen_symbol})")
    
    curr_price = chosen_prices[-1]
    p_1m = chosen_prices[-2]
    p_3m = chosen_prices[-4]
    p_5m = chosen_prices[-6]
    
    score = 0
    if curr_price > p_1m: score += 1
    if curr_price > p_3m: score += 1
    if curr_price > p_5m: score += 1
    
    ams_score = score / 3.0
    
    target_weights = {}
    if ams_score > 0:
        target_weights[chosen_symbol] = ams_score
    if ams_score < 1.0:
        target_weights[TICKER_SAFE] = target_weights.get(TICKER_SAFE, 0.0) + (1.0 - ams_score)
        
    reason = f"상대 모멘텀 우수 자산: {chosen_name} (12m 수익률: {chosen_ret*100:.2f}%), " \
             f"1·3·5 AMS 스코어: {score}점/3점 (선정 자산 비중: {ams_score*100:.1f}% / 안전 자산 비중: {(1-ams_score)*100:.1f}%)"
             
    return target_weights, reason

def rebalance_account(token, acc, target_weights):
    name, cano, prdt_cd = acc["name"], acc["cano"], acc["prdt_cd"]
    print(f"\n=========================================")
    print(f"🔄 [{name}] 자산 리밸런싱 시작 ({cano}-{prdt_cd})")
    print(f"=========================================")
    
    valid_tickers = [TICKER_KOSPI, TICKER_SP500, TICKER_GOLD, TICKER_TLT, TICKER_SAFE]
    for ticker in target_weights.keys():
        if (prdt_cd == "22" or "연금" in name) and ticker not in valid_tickers:
            raise ValueError(f"🚨 [보안 예방] 연금계좌[{name}] 유효하지 않은 자산 매수 시도 차단: {ticker}")
            
    cash, holdings = get_account_balance(token, cano, prdt_cd)
    total_holdings_eval = sum(info["eval_amt"] for info in holdings.values())
    total_asset = cash + total_holdings_eval
    print(f">> 예수금: {cash:,}원 | 주식평가액: {total_holdings_eval:,}원 | 총자산: {total_asset:,}원")
    
    if total_asset == 0:
        print(f">> [{name}] 계좌 자산이 0원이므로 건너끁니다.")
        return f"⚠️ [{name}] 자산 없음 실행 스킵"

    def get_current_price(ticker):
        price = 0.0
        tick_size = 5
        try:
            url_price = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-price"
            headers = {
                "authorization": f"Bearer {token}",
                "appkey": APP_KEY,
                "appsecret": APP_SECRET,
                "tr_id": "FHKST01010100"
            }
            params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker}
            res_price = kis_api_request("GET", url_price, headers=headers, params=params)
            if res_price.status_code == 200:
                price_data = res_price.json()
                if price_data.get("rt_cd") == "0":
                    output = price_data.get("output", {})
                    price = float(output.get("stck_prpr", 0))
                    aspr_unit = output.get("aspr_unit")
                    if aspr_unit:
                        try: tick_size = int(aspr_unit)
                        except (ValueError, TypeError): pass
        except Exception as e:
            print(f"⚠️ KIS 현재가 조회 실패: {e}")
            
        if price <= 0:
            fallback_prices = {
                TICKER_KOSPI: 137000.0, TICKER_SP500: 18000.0,
                TICKER_GOLD: 140000.0, TICKER_TLT: 10000.0, TICKER_SAFE: 11000.0
            }
            price = fallback_prices.get(ticker, 10000.0)
            
        stock_tick = 5
        if price < 2000: stock_tick = 1
        elif price < 5000: stock_tick = 5
        elif price < 20000: stock_tick = 10
        elif price < 50000: stock_tick = 50
        elif price < 100000: stock_tick = 100
        else: stock_tick = 1000
            
        final_tick = max(tick_size, stock_tick)
        return price, final_tick

    # 1. 1단계: 초과 비중 매도
    sold_any = False
    target_qtys = {}
    prices = {}
    
    for ticker, weight in target_weights.items():
        price, tick_size = get_current_price(ticker)
        price = math.ceil(price / tick_size) * tick_size
        prices[ticker] = price
        target_val = total_asset * weight
        target_qtys[ticker] = int(target_val // price)
        
    for ticker, info in holdings.items():
        curr_qty = info["qty"]
        target_qty = target_qtys.get(ticker, 0)
        
        if target_qty == 0:
            print(f"➔ [전량 매도] {ticker} ({curr_qty}주)")
            res = submit_order(token, cano, prdt_cd, ticker, curr_qty, "SELL", ord_dvsn="01")
            if res.get("rt_cd") != "0":
                raise Exception(f"🚨 [매도 실패] {ticker}: {res.get('msg1')}")
            sold_any = True
            time.sleep(1.5)
            
        elif curr_qty > target_qty:
            sell_qty = curr_qty - target_qty
            print(f"➔ [부분 매도] {ticker} ({sell_qty}주)")
            res = submit_order(token, cano, prdt_cd, ticker, sell_qty, "SELL", ord_dvsn="01")
            if res.get("rt_cd") != "0":
                raise Exception(f"🚨 [매도 실패] {ticker}: {res.get('msg1')}")
            sold_any = True
            time.sleep(1.5)

    if sold_any:
        print(">> 매도 정산 및 예수금 갱신 대기 (15초)...")
        time.sleep(15)
        cash, holdings = get_account_balance(token, cano, prdt_cd)

    # 2. 2단계: 매수 진입
    buys = []
    total_buy_needed = 0.0
    
    for ticker, target_qty in target_qtys.items():
        curr_qty = holdings.get(ticker, {}).get("qty", 0)
        if target_qty > curr_qty:
            buy_qty = target_qty - curr_qty
            price = prices[ticker]
            needed = buy_qty * price
            buys.append((ticker, buy_qty, price, needed))
            total_buy_needed += needed

    max_buy_fund = cash * 0.98
    if total_buy_needed > max_buy_fund and total_buy_needed > 0:
        scale = max_buy_fund / total_buy_needed
        print(f"⚠️ [수량 축소 조율] 가용금액({max_buy_fund:,}원) < 필요금액({total_buy_needed:,}원). 스케일: {scale*100:.1f}%")
        
        adjusted_buys = []
        for ticker, buy_qty, price, needed in buys:
            adj_qty = int(buy_qty * scale)
            if adj_qty > 0:
                adjusted_buys.append((ticker, adj_qty, price, adj_qty * price))
        buys = adjusted_buys

    buy_results = []
    current_avail_cash = max_buy_fund
    
    for ticker, buy_qty, price, amount in buys:
        # [핵심 보완] 실시간 남은 가용 현금 추적하여 2차 매수 수량 동적 재조율
        if buy_qty * price > current_avail_cash:
            adj_qty = int(current_avail_cash // price)
            print(f"⚠️ [실시간 현금 조율] {ticker} 수량 변경: {buy_qty}주 ➔ {adj_qty}주 (가용현금: {current_avail_cash:,}원)")
            buy_qty = adj_qty
            amount = buy_qty * price

        if buy_qty <= 0:
            buy_results.append(f"⚠️ {ticker} 매수 스킵 (가용 예수금 부족)")
            continue

        if amount > MAX_ORDER_AMOUNT:
            raise ValueError(f"🚨 [Fat Finger 차단] 주문금액 {amount:,}원 > 최대 제한 금액 {MAX_ORDER_AMOUNT:,}원")
            
        print(f"➔ [지정가 매수] {ticker} ({buy_qty}주, 단가: {price:,}원, 금액: {amount:,}원)")
        res = submit_order(token, cano, prdt_cd, ticker, buy_qty, "BUY", price=price, ord_dvsn="00")
        
        if res.get("rt_cd") == "0":
            buy_results.append(f"✅ {ticker} {buy_qty}주 매수 성공 ({price:,}원)")
            current_avail_cash -= amount
        else:
            buy_results.append(f"❌ {ticker} {buy_qty}주 매수 실패! ({res.get('msg1')})")
        time.sleep(1.5)

    status_summary = []
    for ticker, weight in target_weights.items():
        curr_qty = holdings.get(ticker, {}).get("qty", 0)
        status_summary.append(f"{ticker}(목표비중 {weight*100:.0f}%, 현재수량 {curr_qty}주)")
        
    msg = f"🔄 [{name}] 리밸런싱 완료\n- 목표 분할: {', '.join(status_summary)}\n"
    if buy_results:
        msg += "- 매수 결과:\n  " + "\n  ".join(buy_results)
    else:
        msg += "- 추가 매수 거래 없음 (목표 비중 충족)"
        
    print(msg)
    return msg

def get_actual_rebalance_date(year, month):
    if year == 2026 and month == 5:
        return datetime.date(2026, 5, 29)
        
    target_day = 17
    check_date = datetime.date(year, month, target_day)
    while True:
        if check_date.weekday() >= 5:
            check_date += datetime.timedelta(days=1)
            continue
        if check_date.strftime("%Y-%m-%d") in KRX_HOLIDAYS:
            check_date += datetime.timedelta(days=1)
            continue
        return check_date

def main():
    init_config()
    kst_tz = datetime.timezone(datetime.timedelta(hours=9))
    today = datetime.datetime.now(kst_tz).date()
    actual_rebalance_date = get_actual_rebalance_date(today.year, today.month)
    
    print(f">> [실행일 점검] 이번 달 리밸런싱 예정일: {actual_rebalance_date} (오늘: {today})")
    
    is_force = len(sys.argv) > 1 and sys.argv[1] == "--force"
    
    # [핵심 복구] 7월 17일 제헌절 미집행 건 ➔ 7월 21일~31일 이월 자동 실행 허용
    is_special_july = (datetime.date(2026, 7, 21) <= today <= datetime.date(2026, 7, 31))
    
    if today != actual_rebalance_date and not is_special_july:
        if not (KIS_DRY_RUN or KIS_MOCK or is_force):
            msg = (
                f"ℹ️ [가동 중단] 오늘은 실전 리밸런싱 실행일이 아닙니다.\n"
                f"   - 이번 달 예정일: {actual_rebalance_date}\n"
                f"   - 오늘 날짜: {today}\n"
                f"   - 강제 가동: 'python kis_bot_multi.py --force'"
            )
            print(msg)
            if __name__ == "__main__": sys.exit(0)
            else: return
        else:
            print("⚠️ [스케줄 우회] 시뮬레이션/모의투자/강제실행 옵션으로 진행합니다.")
    elif is_special_july:
        print(f"🎯 [특별 이월 실행 적용] 7월 17일 미집행 건으로 오늘({today}) 리밸런싱을 수행합니다.")

    start_time = datetime.datetime.now(kst_tz).strftime("%Y-%m-%d %H:%M:%S")
    mode_str = "Dry-run 시뮬레이션" if KIS_DRY_RUN else ("모의투자" if KIS_MOCK else "실전 자동 거래")
    send_telegram(f"🤖 K-듀얼 모멘텀 통합 리밸런싱 로봇 가동 시작 ({mode_str})\n가동 시간: {start_time}")
    
    if not is_market_open():
        if not (KIS_DRY_RUN or KIS_MOCK):
            closed_msg = "🚨 [가동 중단] 현재 주식시장 정규 운영시간이 아니거나 휴장일입니다."
            print(closed_msg)
            send_telegram(closed_msg)
            if __name__ == "__main__": sys.exit(1)
            else: raise ValueError(closed_msg)
        else:
            print("⚠️ [영업시간 외 우회] 장이 닫혀 있으나 테스트 모드이므로 계속 진행합니다.")

    try:
        token = get_access_token()
        target_weights, reason = calculate_momentum_signals(token)
        
        weights_detail = [f"{TICKER_NAMES.get(t, t)} ({t}): {w*100:.0f}%" for t, w in target_weights.items()]
        summary_msg = f"📈 금월 투자 대상 및 비중 선정:\n- 비중: {', '.join(weights_detail)}\n- 판단 근거: {reason}\n"
        send_telegram(summary_msg)
        
        results = []
        for i, acc in enumerate(ACCOUNTS):
            if not acc["cano"]:
                print(f">> 계좌 번호가 설정되지 않은 {acc['name']}를 생략합니다.")
                continue
            
            if i > 0:
                print(">> 다음 계좌 처리 전 대기 (3초)...")
                time.sleep(3)
                
            try:
                res_msg = rebalance_account(token, acc, target_weights)
                results.append(res_msg)
            except Exception as ae:
                err = f"❌ 계좌 리밸런싱 실패({acc['name']}): {ae}"
                print(err)
                results.append(err)
                raise ae
                
        if results:
            send_telegram("📊 [작업 수행 리포트]\n" + "\n".join(results))
            
    except Exception as e:
        error_msg = f"🚨 로봇 구동 전역 에러 발생: {e}"
        print(error_msg)
        send_telegram(error_msg)
        if __name__ == "__main__": sys.exit(1)
        else: raise e

if __name__ == "__main__":
    main()
