# 🤖 K-Dual Momentum Quant Bot (GitHub Actions 무인 자동화)

한국투자증권(KIS) API와 텔레그램 실시간 알림 엔진을 결합하여 매달 **K-듀얼 모멘텀 자산배분 전략**으로 계좌를 무인 리밸런싱하는 파이썬 봇입니다.  
GCP(구글 클라우드) 서버 없이 **GitHub Actions (100% 무료 서버리스 스케줄러)** 환경에서 완벽히 구동되도록 패키징되었습니다.

---

## 📂 폴더 구조

```text
github_actions_quant_bot/
├── .github/
│   └── workflows/
│       └── quant_rebalance.yml   # 깃허브 액션 무인 스케줄러 (매달 17~31일 15:15 KST)
├── kis_bot_multi.py             # K-듀얼 모멘텀 퀀트 자동매매 메인 파이썬 스크립트
├── requirements.txt             # 파이썬 필수 의존성 패키지 (requests, python-dotenv 등)
├── .env.example                 # 환경 변수 및 GitHub Secrets 설정 샘플 파일
└── README.md                    # 사용 및 배포 가이드 문서
```

---

## 🔑 GitHub Secrets 설정 (필수 6종)

깃허브 저장소(Repository) ➔ **Settings** ➔ **Secrets and variables** ➔ **Actions** ➔ **New repository secret** 버튼을 눌러 다음 키를 등록합니다.

| Secret 이름 | 설명 | 예시 |
| :--- | :--- | :--- |
| `KIS_MOMENTUM_APP_KEY` | 한국투자증권 Open API AppKey | `PSxxxxxx...` |
| `KIS_MOMENTUM_APP_SECRET` | 한국투자증권 Open API AppSecret | `eyJhbGci...` |
| `KIS_PENSION_CANO` | 연금저축펀드 계좌 8자리 | `12345678` |
| `KIS_STOCK_CANO` | 개인주식 계좌 8자리 | `87654321` |
| `TELEGRAM_TOKEN` | 텔레그램 봇 토큰 (`@BotFather`) | `123456789:ABC...` |
| `TELEGRAM_CHAT_ID` | 텔레그램 본인 Chat ID (`@userinfobot`) | `123456789` |

*(옵션: `KIS_DRY_RUN` = `True` 로 설정하면 실제 주문 없이 계산 및 텔레그램 보고만 수행합니다.)*

---

## 🚀 깃허브 올리는 방법 (업로드 절차)

이 폴더(`github_actions_quant_bot`)를 새로운 깃허브 저장소로 업로드할 때 아래 명령어를 실행합니다.

```bash
cd github_actions_quant_bot
git init
git add .
git commit -m "Feat: Initial commit for K-Dual Momentum GitHub Actions Quant Bot"
git branch -M main
git remote add origin https://github.com/사용자계정/저장소이름.git
git push -u origin main
```

---

## ⏱️ 자동 실행 및 수동 테스트 (Workflow Run)

1. **자동 실행**: 매달 17일~31일 한국시간 **오후 3시 15분 (15:15 KST)**에 깃허브 액션이 자동으로 실행되어 휴장일/주말 이월 알고리즘에 따라 무인 리밸런싱을 수행합니다.
2. **수동 테스트**: GitHub 웹페이지 ➔ **Actions** 탭 ➔ **K-Dual Momentum Quant Bot Auto Rebalance** 클릭 ➔ **Run workflow** 버튼 클릭 (필요시 Dry-run / Force 옵션 체크).

---

## 🔀 전략 선택과 되돌리기 (2026-11 추가)

기본 전략은 **4자산 동일비중**입니다. 기존 K-듀얼모멘텀 코드는 그대로 보존되어 있어 환경 변수 하나로 되돌릴 수 있습니다.

| 설정 (GitHub ▸ Settings ▸ Secrets and variables ▸ Actions ▸ **Variables**) | 값 | 의미 |
| :--- | :--- | :--- |
| `KIS_STRATEGY` | (미설정) 또는 `equal_weight` | 4자산 동일비중 (기본) |
| `KIS_STRATEGY` | `momentum` | 기존 K-듀얼모멘텀으로 **되돌리기** (코드 수정·재배포 불필요, 다음 실행부터 적용) |
| `KIS_STOCK_ENABLED` | (미설정) 또는 `0` | 연금저축계좌만 운용 (기본) |
| `KIS_STOCK_ENABLED` | `1` | 개인주식계좌도 함께 운용 |

값이 `equal_weight`/`momentum` 이외이면 매매하지 않고 오류로 중단되어 텔레그램 경보가 갑니다.

### 4자산 동일비중 규칙
- 대상: KODEX 200(069500), TIGER 미국S&P500(360750), ACE KRX금현물(411060), ACE 미국30년국채액티브(476760) 각 25%
- **평소(납입금 매수)**: 예수금(월 납입금)을 비중이 낮은 자산부터 배분해 매수하며 **매도하지 않습니다.**
- **전체 재조정**: ① 4자산 외 보유 종목(예: 달러단기채)이 남아 있거나 ② 납입금 배분 후에도 어떤 자산이든 목표(25%)에서 **5%p 넘게** 벗어나면, 4자산을 25%씩으로 한 번에 맞춥니다.
- 백테스트(2004-12 ~ 2026-11, 월 50만 원 적립)에서 21년간 전체 재조정은 13회였습니다. 코드의 계획 함수는 같은 백테스트와 결과가 일치함을 확인했습니다.
- 단위 테스트: `python -m unittest test_equal_weight_plan -v` (네트워크·실계좌 호출 없음)
