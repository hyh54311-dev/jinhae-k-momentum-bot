# -*- coding: utf-8 -*-
"""4자산 동일비중 계획(plan_equal_weight)과 전략/계좌 설정 단위 테스트 (네트워크·실계좌 호출 없음).
실행: python -m unittest test_equal_weight_plan -v
"""
import os
import unittest
from unittest import mock

import kis_bot_multi as bot

K, S, G, T, SAFE = bot.TICKER_KOSPI, bot.TICKER_SP500, bot.TICKER_GOLD, bot.TICKER_TLT, bot.TICKER_SAFE


def hold(**vals):
    return {t: {"qty": 1, "price": 0.0, "eval_amt": v} for t, v in vals.items()}


class PlanEqualWeight(unittest.TestCase):
    def test_snapshot_2026_11_conversion_is_full_rebalance(self):
        # 2026-11 계좌 스냅샷: KODEX200 1,290,825 / 달러단기채 727,320 / 예수금 11,738
        h = {K: {"qty": 15, "price": 86055.0, "eval_amt": 1290825},
             SAFE: {"qty": 57, "price": 12760.0, "eval_amt": 727320}}
        w, no_sell, why = bot.plan_equal_weight(h, 11738)
        self.assertFalse(no_sell)
        self.assertEqual(set(w), set(bot.EQ_TICKERS))
        for v in w.values():
            self.assertAlmostEqual(v, 0.25)
        self.assertIn("전략 외 보유", why)

    def test_cashflow_mode_within_band_never_sells_and_fills_underweights(self):
        h = hold(**{K: 260, S: 250, G: 240, T: 250})      # 합 1000, 모두 25% 근처
        w, no_sell, _ = bot.plan_equal_weight(h, 100)      # 납입금 100
        self.assertTrue(no_sell)
        total = 1100
        self.assertAlmostEqual(sum(w.values()), 1.0)
        cur = {K: 260, S: 250, G: 240, T: 250}
        for t in bot.EQ_TICKERS:
            self.assertGreaterEqual(w[t] * total + 1e-9, cur[t])   # 어떤 자산도 목표 금액이 줄지 않는다
        # 가장 모자란 자산(금)이 가장 많이 받는다
        adds = {t: w[t] * total - cur[t] for t in bot.EQ_TICKERS}
        self.assertEqual(max(adds, key=adds.get), G)

    def test_band_breach_triggers_full_rebalance(self):
        h = hold(**{K: 600, S: 150, G: 150, T: 100})       # 코스피 60% → 큰 이탈
        w, no_sell, why = bot.plan_equal_weight(h, 0)
        self.assertFalse(no_sell)
        self.assertIn("전체 재조정", why)
        for v in w.values():
            self.assertAlmostEqual(v, 0.25)

    def test_cash_can_repair_small_drift_without_selling(self):
        # 코스피가 30%(5%p 이탈 직전)여도, 납입금으로 채운 뒤 5%p 이내면 매도하지 않는다
        h = hold(**{K: 300, S: 230, G: 230, T: 240})
        w, no_sell, _ = bot.plan_equal_weight(h, 200)
        self.assertTrue(no_sell)

    def test_all_cash_account(self):
        w, no_sell, _ = bot.plan_equal_weight({}, 500000)
        self.assertTrue(no_sell)                            # 매도할 것이 없고 균등 배분
        for t in bot.EQ_TICKERS:
            self.assertAlmostEqual(w[t], 0.25)

    def test_zero_total(self):
        w, no_sell, why = bot.plan_equal_weight({}, 0)
        self.assertFalse(no_sell)
        self.assertIn("0원", why)

    def test_weights_always_sum_to_one(self):
        import random
        rnd = random.Random(1)
        for _ in range(300):
            h = hold(**{t: rnd.uniform(0, 500) for t in bot.EQ_TICKERS})
            w, _, _ = bot.plan_equal_weight(h, rnd.uniform(0, 300))
            self.assertAlmostEqual(sum(w.values()), 1.0, places=9)
            self.assertTrue(all(v >= 0 for v in w.values()))


class ConfigAndStrategy(unittest.TestCase):
    ENV_KEYS = ("KIS_STRATEGY", "KIS_STOCK_ENABLED", "KIS_MOCK", "KIS_PENSION_CANO", "KIS_STOCK_CANO")

    def _init(self, **env):
        base = {k: "" for k in self.ENV_KEYS}
        base.update({"KIS_PENSION_CANO": "11112222", "KIS_STOCK_CANO": "33334444"})
        base.update(env)
        with mock.patch.dict(os.environ, base, clear=False), mock.patch.object(bot, "load_dotenv"):
            for k, v in base.items():
                if v == "":
                    os.environ.pop(k, None)
            bot.init_config()
        return bot.STRATEGY, [a["name"] for a in bot.ACCOUNTS]

    def test_default_is_equal_weight_and_pension_only(self):
        strategy, accounts = self._init()
        self.assertEqual(strategy, "equal_weight")
        self.assertEqual(accounts, ["연금저축계좌"])

    def test_rollback_to_momentum_via_env(self):
        strategy, _ = self._init(KIS_STRATEGY="Momentum ")
        self.assertEqual(strategy, "momentum")

    def test_invalid_strategy_fails_loudly(self):
        with self.assertRaises(ValueError):
            self._init(KIS_STRATEGY="equal-weight")

    def test_stock_account_only_when_enabled(self):
        _, accounts = self._init(KIS_STOCK_ENABLED="1")
        self.assertEqual(accounts, ["연금저축계좌", "개인주식계좌"])

    def test_account_targets_momentum_passthrough(self):
        self._init(KIS_STRATEGY="momentum")
        base = {K: 0.5, SAFE: 0.5}
        w, no_sell, why = bot.account_targets(None, bot.ACCOUNTS[0], base)
        self.assertEqual(w, base)
        self.assertFalse(no_sell)

    def test_equal_weight_base_targets(self):
        self._init()
        tw, reason = bot.get_strategy_targets(None)
        self.assertEqual(set(tw), set(bot.EQ_TICKERS))
        self.assertAlmostEqual(sum(tw.values()), 1.0)


if __name__ == "__main__":
    unittest.main()
