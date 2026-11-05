# -*- coding: utf-8 -*-
"""백테스트에 쓰는 가격 데이터를 야후 파이낸스에서 내려받아 backtest/data/ 에 저장합니다.
실행: python backtest/fetch_data.py
저장한 파일은 저장소에 올리지 않습니다 (.gitignore). 야후 데이터는 시점에 따라 조금 달라질 수 있습니다.
"""
import json
import os
import time
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
# 이름: (야후 티커, 시작 시각(UTC 초))
SERIES = {
    "ks":    ("^KS11",   1067644800),   # 코스피 지수 (가격지수, 배당 제외)   2003-11-01~
    "spy":   ("SPY",     1067644800),   # S&P500 (분배금 재투자 수정주가)
    "gold":  ("GC=F",    1067644800),   # 금 선물
    "tlt":   ("TLT",     1067644800),   # 미국 20년+ 장기국채
    "shy":   ("SHY",     1067644800),   # 미국 1~3년 단기국채
    "ief":   ("IEF",     1067644800),   # 미국 7~10년 중기국채
    "fx":    ("KRW=X",   1067644800),   # 원/달러
    # 달러 기준 장기 비교용 (2000년대 이전부터)
    "spyF":  ("SPY",     725846400),    # 1993-01-01~
    "vustxF": ("VUSTX",  725846400),    # 뱅가드 장기국채 펀드
    "gcF":   ("GC=F",    725846400),
}


def main():
    os.makedirs(OUT, exist_ok=True)
    end = int(time.time()) + 86400
    for name, (ticker, start) in SERIES.items():
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?interval=1d&period1={start}&period2={end}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as res:
            data = res.read()
        path = os.path.join(OUT, f"d_{name}.json")
        with open(path, "wb") as f:
            f.write(data)
        n = len(json.loads(data)["chart"]["result"][0]["timestamp"])
        print(f"{name:7s} {ticker:7s} {n:5d}일 저장 → {path}")


if __name__ == "__main__":
    main()
