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
