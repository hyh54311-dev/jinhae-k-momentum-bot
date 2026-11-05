# -*- coding: utf-8 -*-
"""4자산 동일비중 vs 모멘텀 백테스트 (원고 수치 재현용)

실행 순서
    python backtest/fetch_data.py      # 가격 데이터 내려받기
    python backtest/backtest.py        # 결과 표를 출력하고 backtest/RESULTS.md 로 저장

핵심 가정 (결과 해석 전에 꼭 읽어 주세요)
  * 월말 종가 기준, 월 1회 판단. 마지막 달은 데이터 마지막 날까지의 미완성 월입니다.
  * 연금계좌라 매매세금은 없다고 보고, ETF 매매비용은 편도 0.05% 를 모든 전략에 똑같이 적용합니다.
  * 실제 국내 ETF 대신 대용 자료를 씁니다 (상장 전 기간을 이어 붙이기 위함).
      코스피 -> ^KS11 지수 (가격지수라 배당 제외, 연 1.5%p 정도 낮게 계산됨)
      S&P500 -> SPY (분배금 재투자 수정주가), 미국 장기채 -> TLT, 단기채 -> SHY, 중기채 -> IEF
      금 -> GC=F 금 선물,  미국 자산은 원/달러(KRW=X)로 환산한 환노출 수익률
  * 모멘텀은 실제 봇과 같은 방식입니다: 전월 말 확정 종가로 신호를 내고 당월 말에 체결 (한 달 지연).
  * 과거 한 번의 경로일 뿐이며 미래 수익을 보장하지 않습니다.
"""
import copy
import datetime as dt
import json
import math
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
COST = 0.0005          # 편도 매매비용
TARGET = 0.25          # 4자산 목표 비중
BAND = 0.05            # 5%p 이탈 규칙
RISK = ["KOSPI", "SPX", "GOLD", "TLT"]
SAFE = "SHY"
NAMES = {"KOSPI": "코스피", "SPX": "S&P500", "GOLD": "금", "TLT": "미국장기채", "SHY": "달러단기채", "IEF": "미국중기채"}

MONTHS, P = [], {}


# ───────────────────────── 데이터 ─────────────────────────
def _load(name, adj=True, lo=None, hi=None):
    """일봉 -> {'YYYY-MM': 월말(마지막 거래일) 종가}. 거래소 현지 날짜 기준."""
    with open(os.path.join(DATA, f"d_{name}.json"), encoding="utf-8") as f:
        r = json.load(f)["chart"]["result"][0]
    off = r["meta"].get("gmtoffset", 0)
    ind = r["indicators"]
    c = (ind.get("adjclose") or [{}])[0].get("adjclose") if adj else None
    c = c or ind["quote"][0]["close"]
    out = {}
    for ts, px in zip(r["timestamp"], c):
        if px is None or (lo is not None and not lo <= px <= hi):
            continue
        out[dt.datetime.fromtimestamp(ts + off, dt.timezone.utc).strftime("%Y-%m")] = px
    return out


def init():
    """원화 환산 월별 가격 P[자산][월] 과 공통 월 목록 MONTHS 를 만든다."""
    global MONTHS, P
    fx = _load("fx", False, 700, 1800)
    raw = {"KOSPI": _load("ks", False), "SPX": _load("spy"), "GOLD": _load("gold", False, 200, 6000),
           "TLT": _load("tlt"), "SHY": _load("shy"), "IEF": _load("ief")}
    P = {k: {m: (v if k == "KOSPI" else v * fx[m]) for m, v in d.items() if m in fx} for k, d in raw.items()}
    MONTHS = sorted(set.intersection(*[set(d) for d in P.values()]))
    return fx


def R(t, i):
    """i월 말 -> i+1월 말 수익률"""
    return P[t][MONTHS[i + 1]] / P[t][MONTHS[i]] - 1


# ───────────────────────── 전략 비중 ─────────────────────────
def _score(t, si):
    p = lambda k: P[t][MONTHS[si - k]]
    return sum([p(0) > p(1), p(0) > p(3), p(0) > p(5)])      # 1·3·5개월 전 종가와 비교 (0~3점)


def _rel12(si):
    return {t: P[t][MONTHS[si]] / P[t][MONTHS[si - 12]] - 1 for t in RISK}


def w_momentum(si):
    """현재 K-듀얼모멘텀: 12개월 1위 자산 1개 + AMS 점수 비중, 나머지 단기채"""
    r = _rel12(si)
    best = max(r, key=r.get)
    s = _score(best, si)
    w = {}
    if s > 0:
        w[best] = s / 3
    if s < 3:
        w[SAFE] = 1 - s / 3
    return w


def w_top2(si):
    """개선안 A: 상위 2개 각 50% x AMS 점수 비중, 나머지 단기채"""
    r = _rel12(si)
    w = {}
    for t in sorted(r, key=r.get, reverse=True)[:2]:
        a = 0.5 * _score(t, si) / 3
        if a > 0:
            w[t] = w.get(t, 0) + a
    rest = 1 - sum(w.values())
    if rest > 1e-12:
        w[SAFE] = w.get(SAFE, 0) + rest
    return w


def w_filter(si):
    """개선안 B: 4자산 25% x 각 자산 AMS 점수 비중, 나머지 단기채"""
    w = {}
    for t in RISK:
        a = 0.25 * _score(t, si) / 3
        if a > 0:
            w[t] = a
    rest = 1 - sum(w.values())
    if rest > 1e-12:
        w[SAFE] = rest
    return w


EQ = {t: 0.25 for t in RISK}
AW = {"KOSPI": .15, "SPX": .15, "TLT": .40, "IEF": .15, "GOLD": .15}     # 올웨더형 (국내 상장 ETF로 만들 수 있는 구성)
STRATS = [
    ("올웨더형(주30/장기채40/중기채15/금15)", lambda i: AW),
    ("4자산 동일비중(월 리밸런싱)", lambda i: EQ),
    ("K-듀얼모멘텀(현재 봇 로직)", lambda i: w_momentum(i - 1)),
    ("개선안 A 상위2개 분산", lambda i: w_top2(i - 1)),
    ("개선안 B 동일비중+AMS필터", lambda i: w_filter(i - 1)),
    ("코스피 보유", lambda i: {"KOSPI": 1.0}),
    ("S&P500 보유(환노출)", lambda i: {"SPX": 1.0}),
]


# ───────────────────────── 시뮬레이션과 지표 ─────────────────────────
def simulate(wf, i0, i1, cost=COST):
    """i0..i1-1 월 말마다 목표 비중으로 맞추고(드리프트 반영) 순수익률 리스트와 평균 편도 회전율을 돌려준다."""
    out, turns, drift = [], [], None
    for i in range(i0, i1):
        w = wf(i)
        turn = sum(w.values()) if drift is None else sum(abs(w.get(k, 0) - drift.get(k, 0)) for k in set(w) | set(drift))
        gross = sum(x * R(t, i) for t, x in w.items())
        out.append(gross - cost * turn)
        turns.append(turn / 2)
        drift = {t: x * (1 + R(t, i)) / (1 + gross) for t, x in w.items()}
    return out, sum(turns[1:]) / max(1, len(turns) - 1)


def irr_monthly_dca(final, n, c=50.0):
    """매월 초 c 만원씩 n 번 넣어 final 이 되는 연환산 수익률(%)"""
    lo, hi = -0.02, 0.05
    for _ in range(80):
        mid = (lo + hi) / 2
        if sum(c * (1 + mid) ** (n - k) for k in range(n)) < final:
            lo = mid
        else:
            hi = mid
    return ((1 + mid) ** 12 - 1) * 100


def stats(r, c=50.0):
    eq = [1.0]
    for x in r:
        eq.append(eq[-1] * (1 + x))
    pk = m = 0.0
    for e in eq:
        pk = max(pk, e)
        m = min(m, e / pk - 1)
    w12 = min(eq[i + 12] / eq[i] - 1 for i in range(len(eq) - 12)) if len(eq) > 13 else float("nan")
    v = 0.0
    for x in r:
        v = (v + c) * (1 + x)
    return dict(cagr=(eq[-1] ** (12 / len(r)) - 1) * 100, mdd=m * 100, w12=w12 * 100,
                vol=st.pstdev(r) * 12 ** .5 * 100, dca=v / 10000, inv=c * len(r) / 10000,
                irr=irr_monthly_dca(v, len(r), c))


def windows():
    last = len(MONTHS) - 1
    return [("최장", 12, last), ("최근 20년", last - 240, last), ("최근 10년", last - 120, last),
            ("전반부", 12, (12 + last) // 2), ("후반부", (12 + last) // 2, last)]


def mdd_between(r, dates, a, b):
    eq = pk = 1.0
    m = 0.0
    for v, d in zip(r, dates):
        if a <= d <= b:
            eq *= 1 + v
            pk = max(pk, eq)
            m = min(m, eq / pk - 1)
    return m * 100


# ───────────────────────── 납입금 매수 + 5%p 규칙 (봇 코드와 같은 규칙) ─────────────────────────
def run_dca(i0, i1, policy, band=BAND, c=50.0, cost=COST):
    """policy: monthly(월 전체 재조정) | semi(반기) | band(5%p 이탈 시, 납입금은 균등 배분)
               cf(납입금 매수만) | cf_band(납입금 매수 + 5%p 규칙, 봇 방식) | none(안 함)"""
    h = {t: 0.0 for t in RISK}
    twr, nav_sum, sell_sum, nrb = [], 0.0, 0.0, 0
    for i in range(i0, i1):
        tot = sum(h.values()) + c
        if policy in ("cf", "cf_band"):
            gap = {t: max(0, TARGET * tot - h[t]) for t in RISK}
            sg = sum(gap.values())
            buy = {t: (c * gap[t] / sg if sg > c else gap[t] + (c - sg) / len(RISK)) for t in RISK}
        else:
            buy = {t: c / len(RISK) for t in RISK}
        for t in RISK:
            h[t] += buy[t]
        fees, sell = cost * c, 0.0
        rb = (policy == "monthly") or (policy == "semi" and MONTHS[i][-2:] in ("06", "12")) or \
             (policy in ("band", "cf_band") and max(abs(h[t] / tot - TARGET) for t in RISK) > band)
        if rb:
            for t in RISK:
                d = TARGET * tot - h[t]
                fees += cost * abs(d)
                sell += max(0, -d)
                h[t] = TARGET * tot
            nrb += 1
        h = {t: x * (1 + R(t, i)) for t, x in h.items()}
        end = sum(h.values()) - fees
        s = sum(h.values())
        h = {t: x * end / s for t, x in h.items()}
        twr.append(end / tot - 1)
        nav_sum += tot
        sell_sum += sell
    n, final = i1 - i0, sum(h.values())
    x = stats(twr)
    return dict(final=final / 10000, paid=c * n / 10000, irr=irr_monthly_dca(final, n, c), cagr=x["cagr"],
                mdd=x["mdd"], w12=x["w12"], sell=sell_sum / nav_sum * 12 * 100, nrb=nrb)


# ───────────────────────── 세금 비교 (연금저축 vs 일반계좌) ─────────────────────────
SALE_TAX = {"KOSPI": 0.0, "SPX": 0.154, "GOLD": 0.154, "TLT": 0.154}   # 일반계좌 매매차익세 (국내주식형 ETF 는 비과세로 가정)
DIV_YIELD = {"KOSPI": 0.0, "SPX": 0.013, "GOLD": 0.0, "TLT": 0.035}    # 분배금 수익률 가정 (수익률 시리즈에는 이미 포함)
DIV_TAX = 0.154


def run_account(i0, i1, taxed, policy="cf_band", c=50.0, refund=0.0, cost=COST):
    h = {t: 0.0 for t in RISK}
    b = {t: 0.0 for t in RISK}
    paid_tax = 0.0
    for i in range(i0, i1):
        add = c + (refund if MONTHS[i][-2:] == "12" else 0.0)
        tot = sum(h.values()) + add
        if policy == "cf_band" or policy == "cf":
            gap = {t: max(0, TARGET * tot - h[t]) for t in RISK}
            sg = sum(gap.values())
            buy = {t: (add * gap[t] / sg if sg > add else gap[t] + (add - sg) / len(RISK)) for t in RISK}
        else:
            buy = {t: add / len(RISK) for t in RISK}
        for t in RISK:
            h[t] += buy[t]
            b[t] += buy[t]
        fee = cost * add
        if policy == "cf_band" and max(abs(h[t] / tot - TARGET) for t in RISK) > BAND:
            d = {t: TARGET * tot - h[t] for t in RISK}
            S = tx = 0.0
            for t in RISK:
                if d[t] < 0:
                    s = -d[t]
                    gain = max(0, 1 - b[t] / h[t]) if taxed else 0
                    tx += SALE_TAX[t] * s * gain
                    b[t] *= 1 - s / h[t]
                    h[t] -= s
                    S += s
            need = {t: d[t] for t in RISK if d[t] > 0}
            sn = sum(need.values())
            B = (S * (1 - cost) - tx) / (1 + cost)
            for t, nd in need.items():
                h[t] += B * nd / sn
                b[t] += B * nd / sn
            fee += cost * (S + B)
            paid_tax += tx
        s_ = sum(h.values())
        for t in RISK:
            h[t] *= 1 - fee / s_
            b[t] *= 1 - fee / s_
        for t in RISK:
            v = h[t]
            h[t] = v * (1 + R(t, i))
            if taxed and DIV_YIELD[t] > 0:
                dv = DIV_YIELD[t] / 12 * v
                td = DIV_TAX * dv
                h[t] -= td
                b[t] += dv - td
                paid_tax += td
    F = sum(h.values())
    unreal = sum(SALE_TAX[t] * max(0, h[t] - b[t]) for t in RISK) if taxed else 0.0
    return F, unreal, paid_tax


# ───────────────────────── 달러 기준 장기 비교 (2000년대 이전부터) ─────────────────────────
def usd_longrun():
    spy, vu, gc = _load("spyF"), _load("vustxF"), _load("gcF", False, 200, 6000)
    ms = sorted(set(spy) & set(vu) & set(gc))

    def seg(a, b, wts):
        i0, i1 = ms.index(a), ms.index(b)
        r = [sum(w * (d[ms[i + 1]] / d[ms[i]] - 1) for d, w in wts) for i in range(i0, i1)]
        x = stats(r)
        return x["cagr"], x["mdd"]
    rows = []
    for a, b, lab in (("2000-08", "2009-12", "2000-08~2009-12"), ("2000-08", "2012-12", "2000-08~2012-12"),
                      ("2010-01", "2026-10", "2010-01~2026-10"), ("2000-08", "2026-10", "2000-08~2026-10 전체")):
        s = seg(a, b, [(spy, 1)])
        e = seg(a, b, [(spy, 1 / 3), (vu, 1 / 3), (gc, 1 / 3)])
        rows.append((lab, s, e))
    return rows


# ───────────────────────── 보고서 ─────────────────────────
def build_report():
    fx = init()
    last = len(MONTHS) - 1
    out = []
    pr = out.append
    pr("# 백테스트 결과 (자동 생성)\n")
    pr(f"데이터: {MONTHS[0]} ~ {MONTHS[-1]} ({len(MONTHS)}개월, 마지막 달은 미완성), 매매비용 편도 {COST*100:.2f}%. 가정과 한계는 backtest.py 머리말을 보세요.\n")

    # 1) 전략 x 기간
    for lab, i0, i1 in windows():
        pr(f"\n## {lab}: {MONTHS[i0]} → {MONTHS[i1]} ({i1-i0}개월)\n")
        pr("| 전략 | 연평균 | 최대 낙폭 | 최악 12개월 | 변동성 | 월 회전율 | 월 50만 원 적립 최종 (원금) | 적립식 연환산 |")
        pr("|---|---|---|---|---|---|---|---|")
        for nm, wf in STRATS:
            r, tv = simulate(wf, i0, i1)
            x = stats(r)
            pr(f"| {nm} | {x['cagr']:.1f}% | {x['mdd']:.1f}% | {x['w12']:.1f}% | {x['vol']:.1f}% | {tv*100:.0f}% | "
               f"{x['dca']:.2f}억 ({x['inv']:.2f}억) | {x['irr']:.1f}% |")

    # 2) 위기 구간 / 연도별
    dates = MONTHS[13:last + 1]
    series = {nm: simulate(wf, 12, last)[0] for nm, wf in STRATS}
    crisis = [("2008 금융위기", "2007-10", "2009-03"), ("2018 하락", "2018-01", "2018-12"),
              ("2020 코로나", "2020-01", "2020-06"), ("2022 긴축", "2021-12", "2022-12")]
    pr("\n## 위기 구간의 최대 낙폭 (구간 안 고점 대비)\n")
    keys = ["4자산 동일비중(월 리밸런싱)", "K-듀얼모멘텀(현재 봇 로직)", "코스피 보유", "S&P500 보유(환노출)"]
    pr("| 구간 | " + " | ".join(keys) + " |")
    pr("|---|" + "---|" * len(keys))
    for lab, a, b in crisis:
        pr(f"| {lab} | " + " | ".join(f"{mdd_between(series[k], dates, a, b):.1f}%" for k in keys) + " |")
    pr("\n## 연도별 수익률 (%)\n")
    pr("| 연도 | " + " | ".join(keys) + " |")
    pr("|---|" + "---|" * len(keys))
    for y in sorted(set(d[:4] for d in dates)):
        pr(f"| {y} | " + " | ".join(f"{(math.prod(1+v for v, d in zip(series[k], dates) if d[:4]==y)-1)*100:.1f}" for k in keys) + " |")

    # 2-a) 최대 낙폭이 언제 생겼나 (고점 월 -> 저점 월), -15% 넘는 낙폭 구간 전부
    pr("\n## 낙폭 -15%를 넘은 구간 (최장 구간, 고점 월 → 저점 월 / 깊이)\n")
    pr("| 전략 | 낙폭 구간 |")
    pr("|---|---|")
    for k in keys:
        r = series[k]
        eqv, pk, pkd = 1.0, 1.0, MONTHS[12]
        eps, cur = [], None
        for v, d in zip(r, dates):
            eqv *= 1 + v
            if eqv >= pk:
                if cur and cur[2] <= -0.15:
                    eps.append(cur)
                pk, pkd, cur = eqv, d, None
            else:
                dd = eqv / pk - 1
                if cur is None or dd < cur[2]:
                    cur = (pkd, d, dd)
        if cur and cur[2] <= -0.15:
            eps.append(cur)
        txt = ", ".join(f"{a}→{b} {c*100:.1f}%" for a, b, c in eps) or "없음"
        pr(f"| {k} | {txt} |")

    # 2-c) 매매비용 민감도 (최장 구간)
    pr("\n## 매매비용 민감도 (최장 구간, 연평균 / 최대 낙폭)\n")
    pr("| 전략 | 편도 0.05% (기본) | 편도 0.15% | 편도 0.30% |")
    pr("|---|---|---|---|")
    for nm, wf in STRATS[1:5]:
        cells = []
        for c in (0.0005, 0.0015, 0.003):
            x = stats(simulate(wf, 12, last, cost=c)[0])
            cells.append(f"{x['cagr']:.2f}% / {x['mdd']:.1f}%")
        pr(f"| {nm} | " + " | ".join(cells) + " |")
    for c in (0.0005, 0.0015, 0.003):
        x = run_dca(12, last, "cf_band", cost=c)
        pr(f"| 4자산 납입금 매수 + 5%p (적립식, 편도 {c*100:.2f}%) | 최종 {x['final']:.2f}억, 시간가중 {x['cagr']:.2f}% | | |")

    # 2-b) 2026년 6월 시작 시나리오 (6월 말에 첫 매매 -> 7월부터 수익 반영, 전월 말 신호 사용)
    i0 = MONTHS.index("2026-06")
    pr("\n## 2026년 6월 말에 한꺼번에 투자했다면 (일시 투자, 월별 수익률 %)\n")
    cols = [("K-듀얼모멘텀(현재 봇 로직)", lambda i: w_momentum(i - 1)), ("4자산 동일비중", lambda i: EQ),
            ("코스피 보유", lambda i: {"KOSPI": 1.0})]
    rs = {nm: simulate(wf, i0, last)[0] for nm, wf in cols}
    pr("| 월 | " + " | ".join(n for n, _ in cols) + " | K-듀얼모멘텀 보유 비중 |")
    pr("|---|" + "---|" * (len(cols) + 1))
    for k, i in enumerate(range(i0, last)):
        wt = w_momentum(i - 1)
        wtxt = ", ".join(f"{NAMES[t]} {x*100:.0f}%" for t, x in sorted(wt.items(), key=lambda kv: -kv[1]))
        pr(f"| {MONTHS[i+1]} | " + " | ".join(f"{rs[n][k]*100:.1f}" for n, _ in cols) + f" | {wtxt} |")
    pr("| 누적 | " + " | ".join(f"{(math.prod(1+v for v in rs[n])-1)*100:.1f}" for n, _ in cols) + " | |")

    # 3) 리밸런싱 방식 (월 50만 원 적립)
    for lab, i0, i1 in windows()[:3]:
        pr(f"\n## 리밸런싱 방식 비교 / {lab} ({MONTHS[i0]} → {MONTHS[i1]}, 원금 {50*(i1-i0)/10000:.2f}억)\n")
        pr("| 방식 | 최종 | 적립식 연환산 | 시간가중 연평균 | 최대 낙폭 | 연 매도량 | 전체 재조정 |")
        pr("|---|---|---|---|---|---|---|")
        for nm, p in (("월 리밸런싱", "monthly"), ("반기 리밸런싱", "semi"), ("5%p 이탈 규칙만", "band"),
                      ("납입금 매수만(매도 없음)", "cf"), ("납입금 매수 + 5%p 규칙 (봇 방식)", "cf_band"), ("리밸런싱 안 함", "none")):
            x = run_dca(i0, i1, p)
            pr(f"| {nm} | {x['final']:.2f}억 | {x['irr']:.1f}% | {x['cagr']:.2f}% | {x['mdd']:.1f}% | {x['sell']:.1f}% | {x['nrb']}회 |")

    # 4) 일부 자산이 약해지면 (수익 깎기 스트레스)
    pr("\n## 금·S&P500 수익을 인위적으로 깎았을 때 (최장 구간, 연평균 / 최대 낙폭)\n")
    pr("| 시나리오 | 4자산 동일비중 | K-듀얼모멘텀 | 개선안 A |")
    pr("|---|---|---|---|")
    P0 = copy.deepcopy(P)
    global RISK, EQ
    risk0, eq0 = RISK, EQ
    for lab, hg, hs in (("기준", 0, 0), ("금·S&P500 각 연 3%p 약화", .03, .03), ("금·S&P500 각 연 5%p 약화", .05, .05),
                        ("금만 연 5%p 약화", .05, 0), ("S&P500만 연 5%p 약화", 0, .05)):
        for t in P:
            P[t] = dict(P0[t])
        for t, h in (("GOLD", hg), ("SPX", hs)):
            for m in P0[t]:
                P[t][m] = P0[t][m] * (1 - h) ** (MONTHS.index(m) / 12) if m in MONTHS else P0[t][m]
        cells = []
        for wf in (lambda i: EQ, lambda i: w_momentum(i - 1), lambda i: w_top2(i - 1)):
            x = stats(simulate(wf, 12, last)[0])
            cells.append(f"{x['cagr']:.1f}% / {x['mdd']:.1f}%")
        pr(f"| {lab} | " + " | ".join(cells) + " |")
    for t in P:
        P[t] = P0[t]
    RISK, EQ = risk0, eq0

    # 5) 세금: 연금저축 vs 일반계좌 (최근 20년, 월 50만 원)
    i0, i1 = last - 240, last
    paid = 50 * 240 / 10000
    Fg, ug, tg = run_account(i0, i1, True, "cf_band")
    net_g = Fg - ug - COST * Fg
    Fp, _, _ = run_account(i0, i1, False, "cf_band")
    Fr1, _, _ = run_account(i0, i1, False, "cf_band", refund=79.2)
    Fr2, _, _ = run_account(i0, i1, False, "cf_band", refund=99.0)
    pr(f"\n## 연금저축 vs 일반계좌 (최근 20년, 월 50만 원, 원금 {paid:.2f}억)\n")
    pr("가정: 일반계좌는 해외·금·채권 ETF 매매차익과 분배금에 15.4%, 코스피 ETF 매매차익은 비과세. 연금저축은 연금 수령 5.5% / 일시금 16.5%, "
       "세액공제 환급금은 매년 12월 같은 계좌에 재투자. 금융소득종합과세와 개인별 세율 차이는 반영하지 않음.\n")
    pr("| 구분 | 세전 평가액 | 세후 최종 | 원금 대비 | 세후 연환산 |")
    pr("|---|---|---|---|---|")
    for nm, F, net in (("일반계좌 (정리 시 과세 포함)", Fg, net_g), ("연금저축 세전(세액공제 제외)", Fp, Fp),
                       ("연금저축 -> 연금 수령(5.5%)", Fp, Fp * .945), ("연금저축 -> 일시금(16.5%)", Fp, Fp * .835),
                       ("연금저축 + 세액공제 13.2% 재투자 -> 연금 수령", Fr1, Fr1 * .945),
                       ("연금저축 + 세액공제 13.2% 재투자 -> 일시금(16.5%)", Fr1, Fr1 * .835),
                       ("연금저축 + 세액공제 16.5% 재투자 -> 연금 수령", Fr2, Fr2 * .945)):
        pr(f"| {nm} | {F/10000:.2f}억 | {net/10000:.2f}억 | {net/(paid*10000):.2f}배 | {irr_monthly_dca(net, 240):.1f}% |")
    gain_tax_base = ug / 0.154
    net_hi = Fg - gain_tax_base * 0.242 - COST * Fg
    pr(f"\n일반계좌를 한 번에 정리해 종합과세로 실효 24.2%가 적용되면 세후 {net_hi/10000:.2f}억 (연환산 {irr_monthly_dca(net_hi, 240):.1f}%).")

    # 6) 달러 기준 장기 비교
    pr("\n## 달러 기준 장기 비교: S&P500 단독 vs 주식·장기채·금 동일비중 (연평균 / 최대 낙폭)\n")
    pr("| 구간 | S&P500 보유 | 주식·장기채·금 동일비중 |")
    pr("|---|---|---|")
    for lab, s, e in usd_longrun():
        pr(f"| {lab} | {s[0]:.1f}% / {s[1]:.1f}% | {e[0]:.1f}% / {e[1]:.1f}% |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    text = build_report()
    print(text)
    path = os.path.join(HERE, "RESULTS.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"-> 저장: {path}", file=sys.stderr)
