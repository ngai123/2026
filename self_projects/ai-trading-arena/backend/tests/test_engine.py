"""Regression tests for the perp engine money-math and the LLM turn parser.

Run: .venv/bin/python -m pytest tests/ -q
Slippage/commission are zeroed so quantities and P&L assert cleanly.
"""
import math

import pytest
from sqlalchemy import create_engine as _ce
from sqlalchemy.orm import sessionmaker

from app import engine
from app.database import Base
from app.llm_client import parse_turn
from app.models import Model, Portfolio, Position, TradeLog
from app.schemas import CoinDecision


@pytest.fixture(autouse=True)
def _settings():
    s = engine.settings
    s.slippage_bps = 0.0
    s.commission_rate = 0.0
    s.allow_short = True
    s.max_leverage = 10.0
    s.maintenance_margin = 0.05
    s.tickers = "BTC-USD,ETH-USD"
    yield


@pytest.fixture
def db():
    eng = _ce("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


def _model(db, cash=100_000.0):
    m = Model(name="T", slug="test/x", memory="")
    db.add(m)
    db.flush()
    db.add(Portfolio(model_id=m.id, cash=cash, starting_cash=cash))
    db.flush()
    return m


def _d(**kw):
    base = dict(coin="BTC-USD", signal="hold", quantity=0.0, leverage=1.0, confidence=0.5)
    base.update(kw)
    return CoinDecision(**base)


def _nav(m, prices):
    return m.portfolio.cash + engine.marked_positions_value(m.portfolio, prices)


# ---------------- pure helpers ----------------
def test_position_upnl_long_and_short():
    long = Position(ticker="BTC-USD", shares=2, avg_price=100, margin=200, leverage=1)
    assert engine.position_upnl(long, 110) == pytest.approx(20)
    short = Position(ticker="BTC-USD", shares=-2, avg_price=100, margin=200, leverage=1)
    assert engine.position_upnl(short, 90) == pytest.approx(20)  # short profits on drop


def test_liquidation_price_long():
    pos = Position(ticker="BTC-USD", shares=10, avg_price=1000, margin=1000, leverage=10)
    # (s*avg - margin)/(s - mm*|s|) = (10000-1000)/(10-0.5) = 947.37
    assert engine.liquidation_price(pos) == pytest.approx(947.37, abs=0.1)


# ---------------- execution: open / pnl / close ----------------
def test_open_long_and_nav(db):
    m = _model(db)
    engine.execute_coin_decision(db, m, _d(signal="buy_to_enter", quantity=1, leverage=1), {"BTC-USD": 1000})
    pos = m.portfolio.positions[0]
    assert pos.shares == pytest.approx(1)
    assert pos.margin == pytest.approx(1000)
    assert m.portfolio.cash == pytest.approx(99_000)
    assert _nav(m, {"BTC-USD": 1000}) == pytest.approx(100_000)


def test_long_profit_then_close(db):
    m = _model(db)
    engine.execute_coin_decision(db, m, _d(signal="buy_to_enter", quantity=1, leverage=1), {"BTC-USD": 1000})
    assert _nav(m, {"BTC-USD": 1200}) == pytest.approx(100_200)
    engine.execute_coin_decision(db, m, _d(signal="close"), {"BTC-USD": 1200})
    assert m.portfolio.positions[0].shares == 0
    assert m.portfolio.cash == pytest.approx(100_200)


def test_leverage_amplifies(db):
    m = _model(db)
    engine.execute_coin_decision(db, m, _d(signal="buy_to_enter", quantity=10, leverage=10), {"BTC-USD": 1000})
    assert m.portfolio.positions[0].margin == pytest.approx(1000)  # 10*1000/10
    # 1% price move -> 10% equity move on the deployed margin
    assert _nav(m, {"BTC-USD": 1100}) == pytest.approx(101_000)


def test_short_profits_on_drop(db):
    m = _model(db)
    engine.execute_coin_decision(db, m, _d(signal="sell_to_enter", quantity=1, leverage=1), {"BTC-USD": 1000})
    assert m.portfolio.positions[0].shares == pytest.approx(-1)
    assert _nav(m, {"BTC-USD": 800}) == pytest.approx(100_200)


def test_opposite_side_rejected(db):
    m = _model(db)
    engine.execute_coin_decision(db, m, _d(signal="buy_to_enter", quantity=1, leverage=1), {"BTC-USD": 1000})
    log = engine.execute_coin_decision(db, m, _d(signal="sell_to_enter", quantity=1, leverage=1), {"BTC-USD": 1000})
    assert log.status == "rejected"
    assert m.portfolio.positions[0].shares == pytest.approx(1)  # unchanged


def test_margin_clamped_to_cash(db):
    m = _model(db, cash=1000)
    engine.execute_coin_decision(db, m, _d(signal="buy_to_enter", quantity=100, leverage=1), {"BTC-USD": 1000})
    # Only ~1 BTC affordable at 1x with $1000.
    assert m.portfolio.positions[0].shares == pytest.approx(1, abs=0.01)
    assert m.portfolio.cash >= 0


def test_leverage_capped(db):
    m = _model(db)
    engine.execute_coin_decision(db, m, _d(signal="buy_to_enter", quantity=1, leverage=50), {"BTC-USD": 1000})
    assert m.portfolio.positions[0].leverage == pytest.approx(10)  # max_leverage


def test_liquidation_closes_position(db):
    m = _model(db)
    engine.execute_coin_decision(db, m, _d(signal="buy_to_enter", quantity=10, leverage=10), {"BTC-USD": 1000})
    engine.check_liquidations(db, m, {"BTC-USD": 940})  # below ~947 liq price
    assert m.portfolio.positions[0].shares == 0
    assert db.query(TradeLog).filter_by(status="liquidated").count() >= 1


def test_exit_plan_take_profit_long(db):
    m = _model(db)
    engine.execute_coin_decision(
        db, m, _d(signal="buy_to_enter", quantity=1, leverage=1, profit_target=1200), {"BTC-USD": 1000}
    )
    engine.check_exit_plans(db, m, {"BTC-USD": 1250})  # >= TP
    assert m.portfolio.positions[0].shares == 0


def test_partial_close(db):
    m = _model(db)
    engine.execute_coin_decision(db, m, _d(signal="buy_to_enter", quantity=4, leverage=1), {"BTC-USD": 1000})
    engine.execute_coin_decision(db, m, _d(signal="close", quantity=1), {"BTC-USD": 1000})
    assert m.portfolio.positions[0].shares == pytest.approx(3)


def test_buy_and_hold_equal_weight(db):
    m = _model(db)
    engine.execute_buy_and_hold(db, m, {"BTC-USD": 1000, "ETH-USD": 2000})
    assert _nav(m, {"BTC-USD": 1000, "ETH-USD": 2000}) == pytest.approx(100_000, abs=1)
    assert all(p.leverage == 1 for p in m.portfolio.positions if p.shares)


# ---------------- parse_turn ----------------
def test_parse_object_with_decisions():
    turn, err = parse_turn('{"memory":"n","decisions":[{"coin":"BTC-USD","signal":"buy_to_enter","quantity":1}]}')
    assert err is None and len(turn.decisions) == 1 and turn.memory == "n"


def test_parse_bare_list():
    turn, err = parse_turn('[{"coin":"BTC-USD","signal":"hold"}]')
    assert err is None and len(turn.decisions) == 1


def test_parse_single_decision_dict():
    turn, err = parse_turn('{"coin":"ETH-USD","signal":"close"}')
    assert err is None and turn.decisions[0].signal == "close"


def test_parse_fenced_json():
    turn, err = parse_turn('```json\n{"decisions":[{"coin":"BTC-USD","signal":"hold"}]}\n```')
    assert err is None and len(turn.decisions) == 1


def test_parse_prose_then_json():
    turn, err = parse_turn('Here is my call:\n{"decisions":[{"coin":"BTC-USD","signal":"hold"}]}')
    assert err is None and len(turn.decisions) == 1


def test_parse_garbage_returns_error():
    turn, err = parse_turn("not json at all")
    assert turn is None and err


def test_parse_confidence_normalized():
    turn, _ = parse_turn('{"decisions":[{"coin":"BTC-USD","signal":"hold","confidence":75}]}')
    assert turn.decisions[0].confidence == pytest.approx(0.75)
