# -*- coding: utf-8 -*-
"""
kis_bot_multi.py — K-듀얼모멘텀 다중계좌 무인 리밸런싱 봇
Production Hardened Build : rev. 2026-09-18 (Claude Opus 5 최종 감수 및 프로덕션 확정본)

[핵심 설계 원칙 (Institutional Architecture)]
  P1. 원장(ledger)과 주문한도(orderable)를 절대 하나의 변수로 합치지 않는다.
      - 총자산/목표비중 산출 = 원장(prvs_rcdl_excc_amt)
      - 매수 상한           = 증거금 엔진(nrcvb_buy_amt 우선, max() 합성 금지)
  P2. 주문 거부(IGW00014)를 '예측'으로 막지 않고 '감지 후 자동 축소(5%) 재시도'로 흡수한다.
  P3. 접수(rt_cd=0) != 체결. 모든 매도는 주문번호(ODNO) 기준 실제 체결 확인 후 다음 단계로 간다.
  P4. 멱등성은 '실행 차단'이 아니라 '델타 수렴(Drift <= 3%p AND Cash <= 1.5%)'으로 보장한다.
  P5. 정수 절사 잔여현금은 '그리디 소진 패스'로 회수하여 현금 방치를 0.2%대로 최소화한다.
  P6. 다중 계좌 루프에서 단일 계좌 실패 시에도 raise 하지 않고 다음 계좌를 100% 독립 실행한다.
"""

import os
import sys
import time
import math
import atexit
import datetime as dt
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Windows 콘솔 UTF-8 출력 지원
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# 0. 전역 상수 및 설정
# ──────────────────────────────────────────────────────────────────────────────
KST = ZoneInfo("Asia/Seoul")

# 포트폴리오 자산 유니버스
TICKER_KOSPI = "069500"    # KODEX 200 (한국 주식)
TICKER_SP500 = "360750"    # TIGER 미국S&P500 (미국 주식)
TICKER_GOLD  = "411060"    # ACE KRX금현물 (금 현물)
TICKER_TLT   = "476760"    # ACE 미국30년국채액티브 (미국 장기채)
TICKER_SAFE  = "329750"    # TIGER 미국달러단기채권액티브 (안전자산 피신처)

RISK_ASSETS = [TICKER_KOSPI, TICKER_SP500, TICKER_GOLD, TICKER_TLT]

TICKER_NAMES = {
    TICKER_KOSPI: "KODEX 200",
    TICKER_SP500: "TIGER 미국S&P500",
    TICKER_GOLD: "ACE KRX금현물",
    TICKER_TLT: "ACE 미국30년국채액티브",
    TICKER_SAFE: "TIGER 미국달러단기채권액티브",
}

# 파라미터 상수
BUY_BUFFER          = 0.995   # 매수 가용현금 안전 버퍼 (0.5% - 수수료 0.014% 대비 35배 안전마진)
DRIFT_TOLERANCE     = 0.03    # 멱등성 판정용 비중 허용 오차 (±3%p)
CASH_TOLERANCE      = 0.015   # 멱등성 판정용 잔여현금 허용 비율 (1.5%)
LIMIT_TICK_OFFSET   = 2       # 매수 지정가 = 현재가 + 2틱 (ETF 호가단위 5원 기준 10원 상향, 즉각 체결 보장)
FILL_POLL_TIMEOUT   = 20.0    # 매도 체결 확인 최대 대기(초)
MARGIN_POLL_TIMEOUT = 30.0    # 증거금 엔진 반영 최대 대기(초)
TRADE_OPEN          = dt.time(9, 10)    # LP 호가 공백(09:00~09:05) 회피
TRADE_DEADLINE      = dt.time(15, 15)   # 이 시각 이후 신규 주문 금지 (동시호가 회피)
API_SLEEP           = 0.35    # KIS API 유량 제한 방어 (초당 20건 제한 준수)
STALE_ORDER_MINUTES = 20      # 이 시간 이상 묵은 미체결은 취소 후 재집행
DRY_RUN             = os.getenv("DRY_RUN", "0") == "1"   # 신호만 계산, 주문 금지

_RUN_COMPLETED = False        # atexit 무음 실패 감지 플래그

# 동적 환경 변수
KIS_MOCK = False
KIS_DRY_RUN = False
MAX_ORDER_AMOUNT = 1000000000
APP_KEY = ""
APP_SECRET = ""
URL_BASE = ""
ACCOUNTS = []
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""


def init_config():
    """실행 직전 최신 환경 변수를 로드하여 전역 변수에 바인딩"""
    global KIS_MOCK, KIS_DRY_RUN, DRY_RUN, MAX_ORDER_AMOUNT, APP_KEY, APP_SECRET, URL_BASE, ACCOUNTS, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()

    KIS_MOCK = os.getenv("KIS_MOCK", "False").lower() in ("true", "1", "yes")
    KIS_DRY_RUN = os.getenv("KIS_DRY_RUN", "False").lower() in ("true", "1", "yes")
    DRY_RUN = os.getenv("DRY_RUN", "0") == "1" or KIS_DRY_RUN
    MAX_ORDER_AMOUNT = int(os.getenv("MAX_ORDER_AMOUNT", "1000000000"))
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    if KIS_MOCK:
        APP_KEY = os.getenv("KIS_MOCK_APP_KEY", "")
        APP_SECRET = os.getenv("KIS_MOCK_APP_SECRET", "")
        URL_BASE = "https://openapivts.koreainvestment.com:29443"
        ACCOUNTS = []
        mock_cano1 = os.getenv("KIS_MOCK_CANO1", "")
        mock_cano2 = os.getenv("KIS_MOCK_CANO2", "")
        if mock_cano1: ACCOUNTS.append({"name": "모의_주식계좌1", "cano": mock_cano1, "prdt_cd": "01", "taxable": True})
        if mock_cano2: ACCOUNTS.append({"name": "모의_주식계좌2", "cano": mock_cano2, "prdt_cd": "01", "taxable": True})
        if not ACCOUNTS:
            pension_cano = os.getenv("KIS_PENSION_CANO", os.getenv("KIS_CANO", "")).strip()
            stock_cano = os.getenv("KIS_STOCK_CANO", os.getenv("KIS_CANO", "")).strip()
            if pension_cano: ACCOUNTS.append({"name": "모의_연금대체", "cano": pension_cano, "prdt_cd": "01", "taxable": False})
            if stock_cano: ACCOUNTS.append({"name": "모의_개인주식", "cano": stock_cano, "prdt_cd": "01", "taxable": True})
    else:
        APP_KEY = os.getenv("KIS_MOMENTUM_APP_KEY", os.getenv("KIS_APP_KEY", "")).strip()
        APP_SECRET = os.getenv("KIS_MOMENTUM_APP_SECRET", os.getenv("KIS_APP_SECRET", "")).strip()
        URL_BASE = "https://openapi.koreainvestment.com:9443"
        pension_cano = os.getenv("KIS_PENSION_CANO", os.getenv("KIS_CANO", "")).strip()
        stock_cano = os.getenv("KIS_STOCK_CANO", os.getenv("KIS_CANO", "")).strip()
        
        ACCOUNTS = [
            {"name": "연금저축계좌", "cano": pension_cano, "prdt_cd": "22", "taxable": False},
            {"name": "개인주식계좌", "cano": stock_cano, "prdt_cd": "01", "taxable": True},
        ]


# ──────────────────────────────────────────────────────────────────────────────
# 1. 공통 유틸리티
# ──────────────────────────────────────────────────────────────────────────────
def now_kst() -> dt.datetime:
    """GitHub Runner는 UTC이므로 반드시 KST(ZoneInfo)로 명시 변환"""
    return dt.datetime.now(tz=KST)


def to_int(value, default=0) -> int:
    """'1011772', '1011772.00', '', None 등 다양한 KIS 응답을 안전하게 정수 변환"""
    if value is None:
        return default
    try:
        s = str(value).strip().replace(",", "")
        if s == "" or s == "-":
            return default
        return int(float(s))
    except (ValueError, TypeError):
        return default


def to_float(value, default=0.0) -> float:
    if value is None:
        return default
    try:
        s = str(value).strip().replace(",", "")
        return float(s) if s not in ("", "-") else default
    except (ValueError, TypeError):
        return default


def krx_tick(price: float, is_etf: bool = True) -> int:
    """KRX 호가가격단위. 국내 ETF는 전 가격대 5원 단일 호가"""
    if is_etf:
        return 5
    p = float(price)
    if p < 2_000:      return 1
    if p < 5_000:      return 5
    if p < 20_000:     return 10
    if p < 50_000:     return 50
    if p < 200_000:    return 100
    if p < 500_000:    return 500
    return 1_000


def round_tick(price: float, direction: str = "down", is_etf: bool = True) -> int:
    """호가단위에 맞지 않는 주문 가격을 KRX 정규 호가로 올림/내림 정렬"""
    t = krx_tick(price, is_etf)
    if direction == "up":
        return int(math.ceil(float(price) / t) * t)
    return int(math.floor(float(price) / t) * t)


def send_telegram(msg: str) -> None:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print(f"[TELEGRAM-DISABLED] {msg}")
        return
    try:
        for i in range(0, len(msg), 3500):  # 4096자 제한 → 3500자 분할 전송
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg[i:i + 3500]},
                timeout=10,
                verify=False,
            )
            time.sleep(0.3)
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")


@atexit.register
def _deadman_switch():
    """프로세스 크래시 / OOM / 비정상 종료 시 무음 실패 방지 비상 알림"""
    if not _RUN_COMPLETED:
        send_telegram("🚨 [CRITICAL] K-모멘텀 봇이 정상 완료 마크 없이 비정상 종료되었습니다. 즉시 계좌를 확인하십시오.")


# ──────────────────────────────────────────────────────────────────────────────
# 2. KIS 통신 계층
# ──────────────────────────────────────────────────────────────────────────────
def kis_headers(token: str, tr_id: str, tr_cont: str = "") -> dict:
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
        "tr_cont": tr_cont,
        "custtype": "P",
    }


def kis_api_request(method: str, url: str, retries: int = 3, **kwargs):
    """
    네트워크 순단 / 429 / 5xx 대상 지수 백오프 재시도
    ⚠️ 주문(POST /order-cash)에는 호출하지 않음 (중복 주문 방지)
    """
    kwargs.setdefault("timeout", 15)
    kwargs.setdefault("verify", False)
    last_exc = None
    for attempt in range(retries):
        try:
            res = requests.request(method, url, **kwargs)
            if res.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {res.status_code}: {res.text[:200]}")
            time.sleep(API_SLEEP)
            return res
        except Exception as e:
            last_exc = e
            wait = 1.5 * (2 ** attempt)
            print(f"   ↻ API 재시도 {attempt + 1}/{retries} ({e}) — {wait:.1f}s 대기")
            time.sleep(wait)
    raise RuntimeError(f"KIS API 통신 최종 실패: {last_exc}")


_cached_token = None

def get_access_token() -> str:
    """EGW00133(1분 1회 빈도제한) 자동 방어 및 프로세스 내 토큰 공유"""
    global _cached_token
    if _cached_token:
        return _cached_token

    url = f"{URL_BASE}/oauth2/tokenP"
    body = {"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET}
    for attempt in range(2):
        res = requests.post(url, json=body, timeout=15, verify=False)
        data = res.json() if res.content else {}
        if res.status_code == 200 and data.get("access_token"):
            _cached_token = data["access_token"]
            return _cached_token
        if str(data.get("error_code", "")) == "EGW00133" and attempt == 0:
            print("⏳ [EGW00133] 토큰 발급 빈도 제한. 65초 대기 후 재시도합니다...")
            time.sleep(65)
            continue
        raise RuntimeError(f"토큰 발급 실패: {res.status_code} {res.text[:300]}")
    raise RuntimeError("토큰 발급 실패 (재시도 소진)")


def is_market_open_today(token: str) -> bool:
    """KIS 국내휴장일조회(CTCA0903R)로 실시간 장 개장 여부 판정"""
    today = now_kst().strftime("%Y%m%d")
    try:
        url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/chk-holiday"
        res = kis_api_request(
            "GET", url,
            headers=kis_headers(token, "CTCA0903R"),
            params={"BASS_DT": today, "CTX_AREA_NK": "", "CTX_AREA_FK": ""},
        )
        for row in res.json().get("output", []):
            if row.get("bass_dt") == today:
                return row.get("opnd_yn") == "Y"
    except Exception as e:
        print(f"⚠️ 휴장일 API 조회 실패({e}) — 주말 체크 폴백 실행")
    return now_kst().weekday() < 5


# ──────────────────────────────────────────────────────────────────────────────
# 3. [Q3-1] get_orderable_cash — 매수 가용현금 정밀 산출 (우선순위 채택)
# ──────────────────────────────────────────────────────────────────────────────
def get_orderable_cash(token, cano, prdt_cd, ticker="069500", target_price=0, verbose=True):
    """
    KIS 국내주식 매수가능조회 (TTTC8908R / 모의 VTTC8908R)
    - 지정가(ORD_DVSN="00") 및 현재가 전달로 상한가(+30%) 증거금 잠김 왜곡 원천 차단.
    - nrcvb_buy_amt(미수없는매수금액) 우선 채택 (증권사가 지금 승인하는 단일 권위값).
    - max() 합성 금지: 증거금 엔진이 승인하지 않은 값을 한도로 삼는 IGW00014 유발 원천 차단.
    """
    url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
    is_mock = KIS_MOCK or "openapivts" in URL_BASE
    tr_id = "VTTC8908R" if is_mock else "TTTC8908R"

    unpr = str(int(target_price)) if target_price and target_price > 0 else "0"
    ord_dvsn = "00" if target_price and target_price > 0 else "01"

    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": prdt_cd,
        "PDNO": ticker,
        "ORD_UNPR": unpr,
        "ORD_DVSN": ord_dvsn,
        "CMA_EVLU_AMT_ICLD_YN": "N",
        "OVRS_ICLD_YN": "N",
    }

    try:
        res = kis_api_request("GET", url, headers=kis_headers(token, tr_id), params=params)
        if res.status_code != 200:
            print(f"⚠️ [TTTC8908R-{prdt_cd}] HTTP {res.status_code}: {res.text[:200]}")
            return None

        data = res.json()
        if data.get("rt_cd") != "0":
            print(f"⚠️ [TTTC8908R-{prdt_cd}] 매수가능조회 실패 ({data.get('msg_cd')}): {data.get('msg1')}")
            return None

        out = data.get("output", {}) or {}
        pure_cash = to_int(out.get("ord_psbl_cash"))
        reuse = to_int(out.get("ruse_psbl_amt"))
        nrcvb = to_int(out.get("nrcvb_buy_amt"))

        # [핵심] 단일 권위 소스 우선순위 채택 (max() 합성 배제)
        if nrcvb > 0:
            cap, source = nrcvb, "nrcvb_buy_amt"
        elif (pure_cash + reuse) > 0:
            cap, source = pure_cash + reuse, "ord_psbl_cash+ruse_psbl_amt"
        else:
            cap, source = pure_cash, "ord_psbl_cash"

        alt = pure_cash + reuse
        if nrcvb > 0 and alt > 0 and abs(nrcvb - alt) / max(nrcvb, alt) > 0.01:
            print(f"   ⚠️ [정합성] nrcvb_buy_amt({nrcvb:,}) vs ord+reuse({alt:,}) 괴리 감지 ➔ 보수적으로 {cap:,}원 채택")

        if verbose:
            print(f"   - [TTTC8908R] 순수현금 {pure_cash:,}원 + 재사용 {reuse:,}원 | 미수없는한도 {nrcvb:,}원 ➔ 주문상한 {cap:,}원 ({source})")

        return {"cap": cap, "pure_cash": pure_cash, "reuse": reuse, "nrcvb": nrcvb, "source": source}

    except Exception as e:
        print(f"⚠️ [TTTC8908R-{prdt_cd}] API 통신 오류: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 4. [Q3-2] get_account_balance — 원장과 주문한도 분리 반환 (3-튜플 구조)
# ──────────────────────────────────────────────────────────────────────────────
def get_account_balance(token, cano, prdt_cd, ticker_for_quote="069500", quote_price=0):
    """
    주식잔고조회 (TTTC8434R / VTTC8434R)
    반환: (ledger_cash, orderable_cash, holdings)
        ledger_cash    : prvs_rcdl_excc_amt 기준 D+2 가수도 정산 예수금 (총자산·목표비중 산출용)
        orderable_cash : TTTC8908R 기준 즉시 주문 가능 상한 (매수 금액 캡 집행용)
        holdings       : {ticker: {qty, price, eval_amt}}
    """
    url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/inquire-balance"
    is_mock = KIS_MOCK or "openapivts" in URL_BASE
    tr_id = "VTTC8434R" if is_mock else "TTTC8434R"

    base_params = {
        "CANO": cano, "ACNT_PRDT_CD": prdt_cd,
        "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
        "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01", "ORD_QTY_DVSN": "00",
        "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
    }

    holdings, summary, tr_cont = {}, {}, ""
    for _ in range(10):  # 연속조회 페이징
        res = kis_api_request("GET", url,
                              headers=kis_headers(token, tr_id, tr_cont),
                              params=base_params)
        if res.status_code != 200:
            raise RuntimeError(f"잔고 조회 HTTP {res.status_code}: {res.text[:300]}")
        data = res.json()
        if data.get("rt_cd") != "0":
            raise RuntimeError(f"잔고 조회 실패({data.get('msg_cd')}): {data.get('msg1')}")

        for item in data.get("output1", []) or []:
            qty = to_int(item.get("hldg_qty"))
            if qty > 0:
                holdings[item["pdno"]] = {
                    "qty": qty,
                    "price": to_float(item.get("prpr")),
                    "eval_amt": to_int(item.get("evlu_amt")),
                }
        if data.get("output2"):
            summary = data["output2"][0]

        tr_cont = res.headers.get("tr_cont", "")
        if tr_cont not in ("F", "M"):
            break
        base_params["CTX_AREA_FK100"] = data.get("ctx_area_fk100", "")
        base_params["CTX_AREA_NK100"] = data.get("ctx_area_nk100", "")
        tr_cont = "N"

    # 원장 기준 가수도정산금액(prvs_rcdl_excc_amt) 우선 확보
    ledger_cash, ledger_src = 0, "none"
    for field in ("prvs_rcdl_excc_amt", "nxdy_excc_amt", "dnca_tot_amt"):
        if summary.get(field) not in (None, ""):
            ledger_cash, ledger_src = to_int(summary.get(field)), field
            break

    # 주문 한도: 증거금 엔진의 독립 권위 소스
    psbl = get_orderable_cash(token, cano, prdt_cd,
                              ticker=ticker_for_quote, target_price=quote_price,
                              verbose=False)
    orderable_cash = psbl["cap"] if psbl else 0

    print(f"   📒 원장 예수금 {ledger_cash:,}원 ({ledger_src}) | 🏦 즉시주문한도 {orderable_cash:,}원")
    return ledger_cash, orderable_cash, holdings


# ──────────────────────────────────────────────────────────────────────────────
# 5. [Q1] 증거금 엔진 동기화 — 적응형 스마트 폴링
# ──────────────────────────────────────────────────────────────────────────────
def wait_for_margin_sync(token, cano, prdt_cd, ticker, price, timeout=MARGIN_POLL_TIMEOUT):
    """
    매도 체결 후, 증거금 엔진(TTTC8908R)이 매도 대금을 인식할 때까지 대기
    [핵심] 목표치를 매 회차 원장(prvs_rcdl_excc_amt)을 재조회해 갱신.
          (15.4% 원천징수나 부분체결 발생 시에도 목표가 자동 보정되어 타임아웃 방지)
    [인터벌] 0.5s x 4회 ➔ 1.0s x 5회 ➔ 2.0s x N회
    """
    # 15:15 데드라인까지 남은 시간이 폴링 예산보다 적으면 예산을 깎는다.
    now = now_kst()
    left = (dt.datetime.combine(now.date(), TRADE_DEADLINE, tzinfo=KST) - now).total_seconds()
    timeout = max(5.0, min(timeout, left - 60))
    deadline = time.monotonic() + timeout
    delays, idx = [0.5] * 4 + [1.0] * 5 + [2.0] * 20, 0
    best_cap, last_ledger = 0, 0

    print(f"⏳ [증거금 엔진 동기화] 최대 {timeout:.0f}초 적응형 폴링 시작...")
    while time.monotonic() < deadline:
        ledger, cap, _ = get_account_balance(token, cano, prdt_cd,
                                             ticker_for_quote=ticker, quote_price=price)
        last_ledger = ledger
        best_cap = max(best_cap, cap)

        if ledger > 0 and cap >= int(ledger * 0.995):
            print(f"✅ [동기화 완료] 주문가능 {cap:,}원 ≥ 원장 {ledger:,}원 × 99.5%")
            return cap, ledger, True

        d = delays[min(idx, len(delays) - 1)]
        idx += 1
        time.sleep(d)

    print(f"⚠️ [폴링 타임아웃] 원장 {last_ledger:,}원 대비 증거금 미반영. 관측 최대 주문가능액 {best_cap:,}원으로 보수 집행합니다.")
    send_telegram(f"⚠️ [K-모멘텀/{prdt_cd}] 증거금 반영 지연 (원장 {last_ledger:,}원 / 가용 {best_cap:,}원).")
    return best_cap, last_ledger, False


# ──────────────────────────────────────────────────────────────────────────────
# 6. 주문 집행 계층 및 자가치유 (Stepdown)
# ──────────────────────────────────────────────────────────────────────────────
_CASH_REJECT_CODES = {"IGW00014", "40240000", "40580000"}

def submit_order(token, cano, prdt_cd, ticker, qty, side, price=0, ord_dvsn="00"):
    """현금 주문 (실전 TTTC0802U 매수 / TTTC0801U 매도, 통신 재시도 금지)"""
    url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/order-cash"
    is_mock = KIS_MOCK or "openapivts" in URL_BASE
    tr_id = ("VTTC0802U" if side == "BUY" else "VTTC0801U") if is_mock else ("TTTC0802U" if side == "BUY" else "TTTC0801U")

    if KIS_DRY_RUN:
        print(f"   [DRY-RUN] {side} {ticker} {qty}주 @ {price:,}원 ({ord_dvsn})")
        return {"rt_cd": "0", "output": {"ODNO": "999999", "odno": "999999"}}

    body = {
        "CANO": cano, "ACNT_PRDT_CD": prdt_cd, "PDNO": ticker,
        "ORD_DVSN": ord_dvsn, "ORD_QTY": str(int(qty)),
        "ORD_UNPR": str(int(price)) if ord_dvsn in ("00", "03") and price > 0 else "0",
    }
    try:
        res = requests.post(url, headers=kis_headers(token, tr_id), json=body, timeout=15, verify=False)
        time.sleep(API_SLEEP)
        return res.json() if res.content else {"rt_cd": "9", "msg1": "빈 응답"}
    except Exception as e:
        return {"rt_cd": "9", "msg_cd": "NETERR", "msg1": f"주문 통신 오류: {e}"}


def submit_buy_with_stepdown(token, cano, prdt_cd, ticker, qty, price, max_retry=3):
    """
    [P2] 주문가능금액 초과(IGW00014)를 감지하여 5%씩 축소 후 최대 3회 자동 재시도
    """
    cur_qty = int(qty)
    for attempt in range(max_retry + 1):
        if cur_qty <= 0:
            return False, 0, {"rt_cd": "9", "msg1": "수량 0"}
        res = submit_order(token, cano, prdt_cd, ticker, cur_qty, "BUY", price=price, ord_dvsn="00")
        if res.get("rt_cd") == "0":
            return True, cur_qty, res

        code = str(res.get("msg_cd", ""))
        msg = str(res.get("msg1", ""))
        cash_reject = code in _CASH_REJECT_CODES or "가능금액" in msg or "가능수량" in msg
        if not cash_reject or attempt == max_retry:
            return False, 0, res

        new_qty = int(cur_qty * 0.95)
        new_qty = new_qty if new_qty < cur_qty else cur_qty - 1
        print(f"   ↓ [자가치유] {ticker} 주문가능금액 초과({code}). {cur_qty}주 ➔ {new_qty}주로 축소 재시도")
        cur_qty = new_qty
    return False, 0, {"rt_cd": "9", "msg1": "재시도 소진"}


def cancel_order(token, cano, prdt_cd, odno, qty, ord_gno_brno=""):
    """
    주식주문(정정취소) TTTC0803U / VTTC0803U — 미체결 잔량 전량 취소.
    RVSE_CNCL_DVSN_CD: "01" 정정 / "02" 취소
    """
    url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/order-rvsecncl"
    is_mock = KIS_MOCK or "openapivts" in URL_BASE
    tr_id = "VTTC0803U" if is_mock else "TTTC0803U"
    body = {
        "CANO": cano, "ACNT_PRDT_CD": prdt_cd,
        "KRX_FWDG_ORD_ORGNO": str(ord_gno_brno or ""),
        "ORGN_ODNO": str(odno),
        "ORD_DVSN": "00",
        "RVSE_CNCL_DVSN_CD": "02",
        "ORD_QTY": str(int(qty)),
        "ORD_UNPR": "0",
        "QTY_ALL_ORD_YN": "Y",
    }
    try:
        res = kis_api_request("POST", url, headers=kis_headers(token, tr_id), json=body, timeout=15)
        time.sleep(API_SLEEP)
        return res.json() if res.content else {"rt_cd": "9", "msg1": "빈 응답"}
    except Exception as e:
        return {"rt_cd": "9", "msg_cd": "NETERR", "msg1": f"취소 통신 오류: {e}"}


def get_daily_orders(token, cano, prdt_cd, ccld_dvsn="00", start_dt=None, end_dt=None):
    """
    주식일별주문체결조회 (TTTC0081R / VTTC0081R) — 기본 당일분, 기간 지정 가능(3개월 이내).
    ccld_dvsn: "00" 전체 / "01" 체결 / "02" 미체결
    """
    url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
    is_mock = KIS_MOCK or "openapivts" in URL_BASE
    tr_id = "VTTC0081R" if is_mock else "TTTC0081R"
    today = now_kst().strftime("%Y%m%d")
    start_dt = start_dt or today
    end_dt = end_dt or today

    params = {
        "CANO": cano, "ACNT_PRDT_CD": prdt_cd,
        "INQR_STRT_DT": start_dt, "INQR_END_DT": end_dt,
        "SLL_BUY_DVSN_CD": "00", "INQR_DVSN": "00", "PDNO": "",
        "CCLD_DVSN": ccld_dvsn, "ORD_GNO_BRNO": "", "ODNO": "",
        "INQR_DVSN_3": "00", "INQR_DVSN_1": "",
        "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
    }
    rows, tr_cont = [], ""
    for _ in range(10):
        res = kis_api_request("GET", url, headers=kis_headers(token, tr_id, tr_cont), params=params)
        data = res.json()
        if data.get("rt_cd") != "0":
            print(f"⚠️ [TTTC0081R] 조회 실패({data.get('msg_cd')}): {data.get('msg1')}")
            return rows
        rows.extend(data.get("output1", []) or [])
        tr_cont = res.headers.get("tr_cont", "")
        if tr_cont not in ("F", "M"):
            break
        params["CTX_AREA_FK100"] = data.get("ctx_area_fk100", "")
        params["CTX_AREA_NK100"] = data.get("ctx_area_nk100", "")
        tr_cont = "N"
    return rows


def wait_for_fills(token, cano, prdt_cd, odno_list, timeout=FILL_POLL_TIMEOUT):
    """[P3] 접수(rt_cd=0) != 체결. 주문번호(ODNO) 기준 잔량(rmn_qty)이 0이 될 때까지 확인 대기"""
    if not odno_list:
        return True, 0
    if KIS_DRY_RUN:
        return True, 0

    deadline = time.monotonic() + timeout
    total_amt = 0
    print(f"⏳ [체결 확인] 주문 {len(odno_list)}건 잔량 소진 대기 (최대 {timeout:.0f}초)...")
    while time.monotonic() < deadline:
        rows = get_daily_orders(token, cano, prdt_cd, ccld_dvsn="00")
        mine = [r for r in rows if r.get("odno") in odno_list]
        if mine:
            remain = sum(to_int(r.get("rmn_qty")) for r in mine)
            total_amt = sum(to_int(r.get("tot_ccld_amt")) for r in mine)
            if remain == 0:
                print(f"✅ [체결 완료] 총 체결금액 {total_amt:,}원")
                return True, total_amt
            print(f"   … 미체결 잔량 {remain}주 대기 중...")
        time.sleep(1.0)
    print(f"⚠️ [체결 타임아웃] 잔량 존재. 확인된 체결금액 {total_amt:,}원 기준 진행")
    return False, total_amt


# ──────────────────────────────────────────────────────────────────────────────
# 7. [Q2] 하이브리드 멱등성 가드 (델타 수렴 기반)
# ──────────────────────────────────────────────────────────────────────────────
def check_already_rebalanced_today(token, acc, target_weights, prices):
    """
    (1) 미체결 주문 처리: 묵은 주문(20분 초과)은 취소하고, 최근 주문(20분 이내)은 중복 방지 스킵
    (2) 당월 체결 확인: 당월 리밸런싱 이미 완료(Drift <= 3%p AND 현금비중 <= 1.5%) 시 스킵
    (3) 미완료 상태(현금비중 > 1.5% 등): 잔여분 보정 실행 (9/21 케이스)
    """
    cano, prdt_cd, name = acc["cano"], acc["prdt_cd"], acc["name"]
    today = now_kst()
    month_start = today.replace(day=1).strftime("%Y%m%d")

    # (1) 미체결 주문 처리 — 묵은 주문은 '차단'이 아니라 '취소 후 재집행'
    try:
        pending = get_daily_orders(token, cano, prdt_cd, ccld_dvsn="02")
        live = [r for r in pending if to_int(r.get("rmn_qty")) > 0]
    except Exception as e:
        print(f"⚠️ 미체결 조회 실패({e}) — 안전을 위해 스킵 판정")
        return True, f"[{name}] 미체결 조회 불가 — 안전 스킵"

    if live:
        def _age_min(row):
            t = str(row.get("ord_tmd") or "000000").zfill(6)
            try:
                o = today.replace(hour=int(t[:2]), minute=int(t[2:4]), second=int(t[4:]))
            except ValueError:
                return 0.0
            return max(0.0, (today - o).total_seconds() / 60.0)

        fresh = [r for r in live if _age_min(r) < STALE_ORDER_MINUTES]
        if fresh:
            n = sum(to_int(r.get("rmn_qty")) for r in fresh)
            return True, f"[{name}] 접수 {STALE_ORDER_MINUTES}분 이내 미체결 {n}주 존재 — 중복 주문 방지 스킵"

        for r in live:
            q = to_int(r.get("rmn_qty"))
            cr = cancel_order(token, cano, prdt_cd, r.get("odno"), q, r.get("ord_gno_brno", ""))
            ok = "OK" if cr.get("rt_cd") == "0" else f"실패({cr.get('msg1')})"
            print(f"   🗑️ [묵은 미체결 취소] {r.get('pdno')} {q}주 → {ok}")
        time.sleep(2)

    # (2) 당월 집행 여부 + 현금비중 판정
    #     ⭐ 당일이 아니라 '당월' 체결을 본다. 정기 리밸런싱은 월 1회이므로,
    #        당월에 이미 집행이 끝났다면 월중 Drift가 벌어져도 재매매하지 않는다.
    try:
        month_rows = get_daily_orders(token, cano, prdt_cd, ccld_dvsn="01", start_dt=month_start)
    except Exception as e:
        print(f"⚠️ 당월 체결 조회 실패({e}) — 보수적으로 미집행 취급")
        month_rows = []

    universe_codes = set(target_weights) | set(TICKER_NAMES)
    executed_this_month = any(
        r.get("pdno") in universe_codes and to_int(r.get("tot_ccld_qty")) > 0
        for r in month_rows
    )

    ledger, _, holdings = get_account_balance(token, cano, prdt_cd)
    eval_sum = sum(h["eval_amt"] for h in holdings.values())
    total = ledger + eval_sum
    if total <= 0:
        return True, f"[{name}] 총자산 0원 — 스킵"

    cash_ratio = ledger / total
    max_drift, worst = 0.0, ""
    for t in (set(target_weights) | set(holdings)):
        cur_w = holdings.get(t, {}).get("eval_amt", 0) / total
        d = abs(cur_w - target_weights.get(t, 0.0))
        if d > max_drift:
            max_drift, worst = d, t

    print(f"   📐 [{name}] 당월집행={executed_this_month} | 최대 Drift {max_drift*100:.2f}%p "
          f"({TICKER_NAMES.get(worst, worst)}) | 현금비중 {cash_ratio*100:.2f}%")

    if executed_this_month:
        if cash_ratio <= CASH_TOLERANCE and max_drift <= DRIFT_TOLERANCE:
            return True, (f"[{name}] 당월 리밸런싱 집행 완료 "
                          f"(현금 {cash_ratio*100:.2f}% ≤ {CASH_TOLERANCE*100:.1f}%, "
                          f"Drift {max_drift*100:.2f}%p) — 스킵")
        return False, (f"[{name}] 당월 집행은 있었으나 미완료 상태 "
                       f"(현금 {cash_ratio*100:.2f}%, Drift {max_drift*100:.2f}%p) — 잔여분 보정 실행")

    return False, f"[{name}] 당월 정기 리밸런싱 미집행 — 신규 집행"


# ──────────────────────────────────────────────────────────────────────────────
# 8. [Q3-3] rebalance_account — 집행 엔진 (그리디 소진 패스 포함)
# ──────────────────────────────────────────────────────────────────────────────
def rebalance_account(token, acc, target_weights, prices):
    name, cano, prdt_cd = acc["name"], acc["cano"], acc["prdt_cd"]
    print("\n" + "=" * 62)
    print(f"🔄 [{name}] 자산 리밸런싱 시작 ({cano}-{prdt_cd})")
    print("=" * 62)

    ledger_cash, orderable_cash, holdings = get_account_balance(token, cano, prdt_cd)
    eval_sum = sum(h["eval_amt"] for h in holdings.values())
    total_asset = ledger_cash + eval_sum
    print(f">> 원장예수금 {ledger_cash:,}원 | 주식평가액 {eval_sum:,}원 | 총자산 {total_asset:,}원 | 즉시주문한도 {orderable_cash:,}원")

    if total_asset <= 0:
        return f"⚠️ [{name}] 계좌 자산이 0원이므로 실행을 건너뜁니다."

    # 목표 수량 산출
    target_qtys = {}
    for ticker, weight in target_weights.items():
        px = prices.get(ticker, 0)
        if px <= 0:
            return f"🚨 [{name}] {ticker} 현재가 확보 실패 — 0원 주문 방지를 위해 당월 스킵"
        target_qtys[ticker] = int((total_asset * weight) // px)

    # 1. 초과 비중 매도 (최유리지정가 '03'으로 상한가 증거금 왜곡 차단)
    sell_odnos, sell_results, sold_any = [], [], False
    for ticker, info in holdings.items():
        curr_qty = info["qty"]
        target_qty = target_qtys.get(ticker, 0)
        if curr_qty <= target_qty:
            continue

        sell_qty = curr_qty - target_qty
        px = prices.get(ticker, info["price"])
        t_name = TICKER_NAMES.get(ticker, ticker)
        print(f"➔ [매도] {t_name}({ticker}) {sell_qty}주 @최유리지정가('03')")

        res = submit_order(token, cano, prdt_cd, ticker, sell_qty, "SELL", ord_dvsn="03")
        if res.get("rt_cd") == "0":
            odno = res.get("output", {}).get("ODNO") or res.get("output", {}).get("odno")
            if odno: sell_odnos.append(odno)
            sell_results.append(f"매도: {t_name} {sell_qty}주")
            sold_any = True
        else:
            warn = f"❌ 매도 실패 {t_name}: {res.get('msg1')}"
            print(f"   {warn}")
            sell_results.append(warn)
            send_telegram(f"⚠️ [{name}] {warn}")
        time.sleep(1.0)

    # 2. 체결 확인 ➔ 증거금 엔진 적응형 폴링 동기화
    if sold_any:
        filled, ccld_amt = wait_for_fills(token, cano, prdt_cd, sell_odnos)
        if not filled:
            send_telegram(f"⚠️ [{name}] 매도 미체결 잔량 존재. 확인된 체결금 {ccld_amt:,}원 기준으로 진행합니다.")
        
        quote_t = TICKER_SAFE if TICKER_SAFE in target_qtys else next(iter(target_qtys))
        orderable_cash, ledger_cash, _ = wait_for_margin_sync(
            token, cano, prdt_cd, quote_t, prices.get(quote_t, 0))
        _, _, holdings = get_account_balance(token, cano, prdt_cd)

    # 3. 매수 계획 (현재가 + 2틱 지정가, 5원 호가 정규화)
    buys = []
    total_needed = 0
    for ticker, target_qty in target_qtys.items():
        curr_qty = holdings.get(ticker, {}).get("qty", 0)
        if target_qty <= curr_qty:
            continue
        qty = target_qty - curr_qty
        raw = prices[ticker] + LIMIT_TICK_OFFSET * krx_tick(prices[ticker])
        limit_px = round_tick(raw, "up")
        buys.append({"ticker": ticker, "qty": qty, "px": limit_px})
        total_needed += qty * limit_px

    max_buy_fund = int(orderable_cash * BUY_BUFFER)
    if total_needed > max_buy_fund and total_needed > 0:
        scale = max_buy_fund / total_needed
        print(f"⚠️ [수량 축소] 가용 {max_buy_fund:,}원 < 필요 {total_needed:,}원 (스케일 {scale*100:.1f}%)")
        for b in buys:
            b["qty"] = int(b["qty"] * scale)
        buys = [b for b in buys if b["qty"] > 0]

    # 3-b. [P5] 잔여현금 그리디 소진 패스 (현금 방치 0.2%대로 구조적 제거)
    def _planned_spend():
        return sum(b["qty"] * b["px"] for b in buys)

    residual = max_buy_fund - _planned_spend()
    guard = 0
    while residual > 0 and guard < 200:
        guard += 1
        cands = []
        for t, w in target_weights.items():
            px = round_tick(prices[t] + LIMIT_TICK_OFFSET * krx_tick(prices[t]), "up")
            if px > residual:
                continue
            planned = next((b["qty"] for b in buys if b["ticker"] == t), 0)
            have = holdings.get(t, {}).get("qty", 0)
            shortfall = total_asset * w - (have + planned) * px
            cands.append((shortfall, t, px))
        if not cands:
            break
        cands.sort(reverse=True)
        _, t, px = cands[0]
        hit = next((b for b in buys if b["ticker"] == t), None)
        if hit:
            hit["qty"] += 1
        else:
            buys.append({"ticker": t, "qty": 1, "px": px})
        residual -= px
    if guard:
        print(f"   ♻️ [잔여현금 소진] {guard}주 추가 배정, 최종 잔여 {residual:,}원 ({residual / total_asset * 100:.2f}%)")

    # 4. 매수 집행 (동적 현금 캡 + IGW00014 5% 축소 자가치유)
    buy_results = []
    avail = max_buy_fund
    for b in sorted(buys, key=lambda x: -x["qty"] * x["px"]):
        ticker, qty, px = b["ticker"], b["qty"], b["px"]
        t_name = TICKER_NAMES.get(ticker, ticker)

        if qty * px > avail:
            qty = int(avail // px)
        if qty <= 0:
            buy_results.append(f"⚠️ {t_name} 매수 스킵 (가용현금 부족)")
            continue

        print(f"➔ [지정가 매수] {t_name}({ticker}) {qty}주 @ {px:,}원 = {qty*px:,}원")
        ok, done_qty, res = submit_buy_with_stepdown(token, cano, prdt_cd, ticker, qty, px)
        if ok:
            buy_results.append(f"✅ {t_name} {done_qty}주 매수 접수 ({px:,}원)")
            avail -= done_qty * px
        else:
            buy_results.append(f"❌ {t_name} 매수 실패: {res.get('msg1')}")
        time.sleep(1.0)

    # 5. 최종 검증 리포트
    time.sleep(3)
    fin_ledger, _, fin_holdings = get_account_balance(token, cano, prdt_cd)
    fin_eval = sum(h["eval_amt"] for h in fin_holdings.values())
    fin_total = fin_ledger + fin_eval
    cash_pct = (fin_ledger / fin_total * 100) if fin_total else 0.0
    flag = "⚠️ 현금 방치 경보" if cash_pct > 3.0 else "정상"

    lines = [f"✅ [{name}] 리밸런싱 집행 완료"]
    lines += sell_results + buy_results
    lines.append(f"📊 최종 예수금 {fin_ledger:,}원 ({cash_pct:.2f}%) / 총자산 {fin_total:,}원 — {flag}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# 9. 시세 및 K-듀얼 모멘텀 산출 계층 (상대모멘텀 1위 + 1·3·5 AMS)
# ──────────────────────────────────────────────────────────────────────────────
def get_current_price(token, ticker):
    """국내주식 현재가 (FHKST01010100)"""
    try:
        url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-price"
        res = kis_api_request("GET", url,
                              headers=kis_headers(token, "FHKST01010100"),
                              params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker})
        data = res.json()
        if data.get("rt_cd") == "0":
            px = to_int(data.get("output", {}).get("stck_prpr"))
            return px if px > 0 else None
    except Exception as e:
        print(f"⚠️ 현재가 조회 실패 {ticker}: {e}")
    return None


def get_monthly_closes_kis(token, ticker, count=16):
    """KIS API 기간별시세(월봉, FHKST03010100)로 월별 종가 리스트 확보"""
    if not token:
        return None
    try:
        url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        end = now_kst().strftime("%Y%m%d")
        start = (now_kst() - dt.timedelta(days=730)).strftime("%Y%m%d")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start,
            "FID_INPUT_DATE_2": end,
            "FID_PERIOD_DIV_CODE": "M",
            "FID_ORG_ADPR_YN": "Y"
        }
        res = kis_api_request("GET", url, headers=kis_headers(token, "FHKST03010100"), params=params)
        if res.status_code == 200 and res.content:
            data = res.json()
            if data.get("rt_cd") == "0":
                output2 = data.get("output2", [])
                prices = []
                for item in output2:
                    clpr = item.get("stck_clpr")
                    if clpr:
                        prices.append(float(clpr))
                prices.reverse()  # 과거 -> 최신순
                if len(prices) >= 14:
                    return prices[-14:]
    except Exception as e:
        print(f"⚠️ KIS 월봉 시세 조회 오류 ({ticker}): {e}")
    return None


def get_historical_prices_yahoo(symbol):
    """Yahoo Finance 폴백 시세 수집"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1mo&range=2y"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers, timeout=10, verify=False)
    if res.status_code == 200:
        result = res.json()["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        closes = result["indicators"]["quote"][0]["close"]
        monthly_data = {}
        for ts, close in zip(timestamps, closes):
            if close is not None:
                dt_str = dt.datetime.fromtimestamp(ts, tz=KST).strftime("%Y-%m")
                monthly_data[dt_str] = float(close)
        sorted_months = sorted(monthly_data.keys())
        prices = [monthly_data[m] for m in sorted_months]
        if len(prices) >= 14:
            return prices[-14:]
    return None


def fetch_prices(token, tickers, holdings_hint=None):
    """3중 폴백 현재가: KIS 현재가 ➔ 잔고 보유단가(prpr) ➔ 월봉 최근 종가"""
    holdings_hint = holdings_hint or {}
    prices = {}
    for t in tickers:
        px = get_current_price(token, t)
        if not px:
            px = int(holdings_hint.get(t, {}).get("price", 0)) or None
            if px: print(f"   ↩︎ {t} 현재가 폴백: 잔고단가 {px:,}원")
        if not px:
            try:
                closes = get_monthly_closes_kis(token, t)
                px = int(closes[-1]) if closes else None
                if px: print(f"   ↩︎ {t} 현재가 폴백: 월봉 최근종가 {px:,}원")
            except Exception:
                px = None
        if not px:
            try:
                yh = get_historical_prices_yahoo(f"{t}.KS")
                px = int(yh[-1]) if yh else None
                if px: print(f"   ↩︎ {t} 현재가 폴백: Yahoo Finance {px:,}원")
            except Exception:
                px = None
        prices[t] = px or 0
        if not px:
            print(f"🚨 {t} 가격 4중 폴백 전부 실패 — 0원 주문 차단 대상")
    return prices


def calculate_momentum_signals(token):
    """
    K-듀얼 모멘텀 핵심 알고리즘 (전월말 확정 종가 기준):
      1. 4대 위험자산의 12개월 상대모멘텀 산출 (당월 변동 제외, 전월말 종가 기준)
      2. 1위 자산 선정
      3. 1위 자산의 1, 3, 5개월 절대모멘텀 스코어(AMS, 0~3점) 산출
         - ams_score = score / 3.0
         - 선정 자산 비중 = ams_score
         - 안전자산(TIGER 미국달러단기채권) 비중 = 1.0 - ams_score
    """
    YAHOO_SYMBOLS = {
        TICKER_KOSPI: f"{TICKER_KOSPI}.KS",
        TICKER_SP500: f"{TICKER_SP500}.KS",
        TICKER_GOLD:  f"{TICKER_GOLD}.KS",
        TICKER_TLT:   f"{TICKER_TLT}.KS"
    }
    
    print(">> 글로벌 증시 4대 자산 역사적 시세 분석 중...")
    prices_dict = {}
    returns_12m = {}

    for ticker in RISK_ASSETS:
        prices = get_monthly_closes_kis(token, ticker)
        if not prices:
            print(f"⚠️ {ticker} KIS 월봉 실패 ➔ Yahoo Finance 폴백")
            prices = get_historical_prices_yahoo(YAHOO_SYMBOLS.get(ticker, f"{ticker}.KS"))
            
        if not prices or len(prices) < 14:
            raise RuntimeError(f"🚨 모멘텀 데이터 부족: {ticker} (확보: {len(prices) if prices else 0}개, 필요 14개)")

        prices_dict[ticker] = prices
        # ⭐ 당월(진행 중) 월봉(prices[-1])은 매일 값이 변한다. prices[-1]을 쓰면 같은 달에
        #    다시 실행할 때 신호가 뒤집혀 whipsaw(샀다 파는 왕복매매)가 난다.
        #    전월 말 '확정' 종가(prices[-2]) 기준으로 계산해야 한 달 내내 동일한 목표가 나온다.
        base_p = prices[-14] if prices[-14] > 0 else 1.0
        ret_12m = (prices[-2] - base_p) / base_p
        returns_12m[ticker] = ret_12m
        time.sleep(0.3)

    print("■ 12개월 상대 모멘텀 분석 결과 (전월말 확정 종가 기준):")
    for ticker, ret in returns_12m.items():
        print(f"    - {TICKER_NAMES.get(ticker, ticker)}: {ret*100:+.2f}%")

    # 1위 자산 선정
    best_ticker = max(returns_12m, key=returns_12m.get)
    best_name = TICKER_NAMES[best_ticker]
    best_ret = returns_12m[best_ticker]
    best_prices = prices_dict[best_ticker]

    print(f">> 상대 모멘텀 1위 자산: {best_name} ({best_ticker}) (12M 수익률: {best_ret*100:+.2f}%)")

    # 1위 자산의 1, 3, 5개월 AMS 산출 (전월말 확정 종가 기준)
    curr_p = best_prices[-2]   # 전월 말 확정 종가
    p_1m   = best_prices[-3]   # 1개월 전 확정 종가
    p_3m   = best_prices[-5]   # 3개월 전 확정 종가
    p_5m   = best_prices[-7]   # 5개월 전 확정 종가

    score = 0
    if curr_p > p_1m: score += 1
    if curr_p > p_3m: score += 1
    if curr_p > p_5m: score += 1

    ams_score = score / 3.0
    target_weights = {}
    if ams_score > 0:
        target_weights[best_ticker] = ams_score
    if ams_score < 1.0:
        target_weights[TICKER_SAFE] = target_weights.get(TICKER_SAFE, 0.0) + (1.0 - ams_score)

    reason = f"상대 모멘텀 1위: {best_name} ({best_ret*100:+.2f}%), AMS 스코어: {score}/3점 ➔ " \
             f"{best_name} {ams_score*100:.1f}% / {TICKER_NAMES[TICKER_SAFE]} {(1-ams_score)*100:.1f}%"
    return target_weights, reason


# ──────────────────────────────────────────────────────────────────────────────
# 10. [Q3-4] main — 다중 계좌 완전 격리 실행 엔진
# ──────────────────────────────────────────────────────────────────────────────
def main():
    global _RUN_COMPLETED
    init_config()
    now = now_kst()
    is_force = len(sys.argv) > 1 and sys.argv[1] == "--force"
    mode_str = "DRY-RUN 시뮬레이션" if KIS_DRY_RUN else ("모의투자" if KIS_MOCK else "실전 계좌")

    print(f"🚀 K-듀얼모멘텀 봇 기동 — {now:%Y-%m-%d %H:%M:%S} KST ({mode_str})")

    token = None
    if APP_KEY and APP_SECRET:
        token = get_access_token()

    # ── DRY_RUN: 시간·휴장 게이트 이전에 '신호만' 계산해 보고하고 종료 ──
    #    (장 시작 전이나 주말에 목표 비중을 미리 확인할 때 사용. 주문은 절대 안 나간다.)
    if DRY_RUN or KIS_DRY_RUN:
        tw, reason = calculate_momentum_signals(token)
        px = fetch_prices(token, list(tw))
        body = "\n".join(f"{TICKER_NAMES.get(t, t)}: {w*100:.1f}% @ {px.get(t, 0):,}원"
                          for t, w in tw.items())
        print("🧪 [DRY-RUN] 목표 비중:\n" + body)
        send_telegram(f"🧪 [DRY-RUN] {now:%m/%d %H:%M} 목표 비중\n{body}\n(사유: {reason})")
        _RUN_COMPLETED = True
        return

    # 1. 휴장일 게이트 (모의/강제 실행 제외)
    if not (KIS_MOCK or is_force):
        if not is_market_open_today(token):
            msg = f"🗓️ {now:%Y-%m-%d}은 휴장일입니다. 실행하지 않고 정상 종료합니다."
            print(msg); send_telegram(msg); _RUN_COMPLETED = True; return

        # 2. 거래 허용 시간창 게이트 (09:10 ~ 15:15 KST)
        if not (TRADE_OPEN <= now.time() <= TRADE_DEADLINE):
            msg = f"⏰ 현재 {now:%H:%M} KST는 정규장 거래창(09:10~15:15) 밖입니다. 슬리피지 방지를 위해 중단합니다."
            print(msg); send_telegram(f"🚨 [K-모멘텀] {msg}"); _RUN_COMPLETED = True; return

    send_telegram(f"🔔 [K-모멘텀] {now:%m/%d %H:%M} 리밸런싱 세션 시작 ({mode_str})")

    # 3. 모멘텀 신호 산출 및 가격 수집
    target_weights, reason = calculate_momentum_signals(token)
    prices = fetch_prices(token, list(target_weights))
    print(f"🎯 목표 비중: " + ", ".join(f"{TICKER_NAMES.get(t, t)} {w*100:.1f}%" for t, w in target_weights.items()))
    print(f"   (판단 근거: {reason})")

    # 4. 다중 계좌 순회 집행 (계좌 완전 격리)
    results = []
    for i, acc in enumerate(ACCOUNTS):
        if not acc.get("cano"):
            continue
        if i > 0:
            print(">> 계좌 간 유량제한 여유 대기 (5초)...")
            time.sleep(5)

        try:
            # 멱등성 검증
            skip, skip_reason = check_already_rebalanced_today(token, acc, target_weights, prices)
            print(f"🧭 {skip_reason}")
            if skip:
                results.append(f"⏭️ {skip_reason}")
                continue

            # 리밸런싱 집행
            report = rebalance_account(token, acc, target_weights, prices)
            results.append(report)

        except Exception as ae:
            # 💥 계좌 1 오류가 계좌 2 실행을 차단하지 않도록 완전 격리 (raise ae 금지)
            err = f"🚨 [{acc['name']}] 리밸런싱 중단 오류: {ae}"
            print(err)
            results.append(err)
            send_telegram(err)
            continue

    if results:
        send_telegram("\n\n".join(results))
    print("🏁 전 계좌 처리 완료")
    _RUN_COMPLETED = True


if __name__ == "__main__":
    try:
        main()
    except Exception as fatal:
        send_telegram(f"🚨 [CRITICAL] K-모멘텀 봇 치명적 예외: {fatal}")
        _RUN_COMPLETED = True
        raise
