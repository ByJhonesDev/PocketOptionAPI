"""
Autor: ByJhonesDev
Projeto: PocketOptionAPI – Biblioteca Python assíncrona de alto nível para integração com a corretora Pocket Option, com funções auxiliares reutilizáveis para autenticação, normalização, análise de dados de mercado e controle operacional.

Descrição:
Módulo utilitário da biblioteca que concentra helpers transversais usados em múltiplas camadas do projeto. Inclui funções de formatação de sessão, extração de session_id, normalização de ativos, payout, timeframes e status, análise de candles, conversão para DataFrame, filtros avançados de ativos, cálculo de expiração, decoradores de retry e monitoramento de performance, além de componentes simples como rate limiter e gerenciador de ordens.

O que ele faz:
- Formata e extrai payloads de autenticação Socket.IO
- Normaliza símbolos, payout, timeframes, tipos e status
- Normaliza registros de ativos recebidos do broker
- Analisa candles e calcula métricas básicas de mercado
- Mescla séries de candles sem duplicação
- Converte candles, ativos e payouts para DataFrame
- Aplica filtros avançados em registros de ativos
- Calcula expiração de ordens
- Fornece decoradores assíncronos de retry e monitoramento de performance
- Implementa um limitador de taxa simples
- Implementa um gerenciador simples de ordens ativas e concluídas

Características:
- Funções reutilizáveis e desacopladas
- Suporte a análise básica de mercado
- Integração nativa com pandas
- Helpers voltados a compatibilidade e saneamento de dados
- Componentes leves para controle operacional
- Utilitário central para reduzir duplicação de lógica

Requisitos:
- Python 3.10+
- asyncio
- pandas
- loguru
- Módulos internos do projeto:
  - constants
  - models
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Union

import pandas as pd
from loguru import logger

from .constants import (
    ASSETS,
    TIMEFRAMES,
    normalize_asset_symbol,
    normalize_asset_type,
    normalize_open_value,
    normalize_payout,
    seconds_to_timeframe,
    timeframe_to_seconds,
)
from .models import Candle, OrderResult


# -----------------------------------------------------------------------------
# Auth / session helpers
# -----------------------------------------------------------------------------

def format_session_id(
    session_id: str,
    is_demo: bool = True,
    uid: int = 0,
    platform: int = 1,
    is_fast_history: bool = True,
) -> str:
    """
    Formata a mensagem de autenticação Socket.IO usada pela PocketOption.
    """
    auth_data: Dict[str, Any] = {
        "session": session_id,
        "isDemo": 1 if is_demo else 0,
        "uid": uid,
        "platform": platform,
    }

    if is_fast_history:
        auth_data["isFastHistory"] = True

    return f'42["auth",{json.dumps(auth_data)}]'


def extract_session_id(auth_payload: str) -> str:
    """
    Extrai o session_id de uma string auth completa, quando possível.

    Exemplo:
    42["auth",{"session":"abc","isDemo":1,"uid":0,"platform":1}]
    """
    try:
        start = auth_payload.find("{")
        end = auth_payload.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(auth_payload[start:end])
            return str(data.get("session", "")).strip()
    except Exception:
        pass
    return str(auth_payload or "").strip()


# -----------------------------------------------------------------------------
# Normalização genérica
# -----------------------------------------------------------------------------

def ensure_utc_datetime(value: Any) -> datetime:
    """
    Converte timestamps / datetimes / isoformat para datetime UTC timezone-aware.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    if value is None or value == "":
        return datetime.now(timezone.utc)

    try:
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except Exception:
        pass

    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def normalize_asset(value: Any) -> str:
    return normalize_asset_symbol(value)


def normalize_payout_value(value: Any) -> Optional[float]:
    return normalize_payout(value)


def normalize_asset_kind(value: Any) -> str:
    return normalize_asset_type(value)


def normalize_open_status(value: Any) -> Optional[bool]:
    return normalize_open_value(value)


def normalize_timeframe(value: Union[str, int]) -> int:
    """
    Normaliza timeframe para segundos.
    """
    if isinstance(value, int):
        return value

    seconds = timeframe_to_seconds(value)
    if seconds is None:
        raise ValueError(f"Invalid timeframe: {value}")
    return seconds


def format_timeframe(seconds: int) -> str:
    """
    Converte segundos para label amigável.
    """
    mapped = seconds_to_timeframe(seconds)
    if mapped:
        return mapped

    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def normalize_broker_asset_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza um registro de ativo/payout vindo do broker.
    """
    normalized = dict(record)

    asset = (
        normalized.get("asset")
        or normalized.get("symbol")
        or normalized.get("name")
        or ""
    )
    normalized["asset"] = normalize_asset(asset)
    normalized["symbol"] = normalize_asset(
        normalized.get("symbol") or normalized["asset"]
    )

    if "type" in normalized:
        normalized["type"] = normalize_asset_kind(normalized.get("type"))

    if "payout" in normalized:
        normalized["payout"] = normalize_payout_value(normalized.get("payout"))
    elif "profit" in normalized:
        normalized["payout"] = normalize_payout_value(normalized.get("profit"))
    elif "rate" in normalized:
        normalized["payout"] = normalize_payout_value(normalized.get("rate"))

    open_candidate = normalized.get("is_open")
    if open_candidate is None:
        open_candidate = normalized.get("open")
    if open_candidate is None:
        open_candidate = normalized.get("available")
    if open_candidate is None:
        open_candidate = normalized.get("active")

    normalized["is_open"] = normalize_open_status(open_candidate)
    normalized["is_otc"] = (
        normalized["asset"].lower().endswith("_otc")
        or str(normalized.get("type", "")).lower() == "otc"
    )

    normalized.setdefault("display_name", normalized.get("name"))
    normalized.setdefault("raw", dict(record))
    normalized.setdefault("updated_at", datetime.now(timezone.utc))

    return normalized


# -----------------------------------------------------------------------------
# Candles / análise
# -----------------------------------------------------------------------------

def calculate_payout_percentage(
    entry_price: float,
    exit_price: float,
    direction: str,
    payout_rate: float = 0.8,
) -> float:
    """
    Calcula retorno simples de uma ordem binária.
    """
    if direction.lower() == "call":
        win = exit_price > entry_price
    else:
        win = exit_price < entry_price

    return payout_rate if win else -1.0


def analyze_candles(candles: Sequence[Candle]) -> Dict[str, Any]:
    """
    Analisa candles e retorna estatísticas básicas.
    """
    if not candles:
        return {}

    prices = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    opens = [c.open for c in candles]
    volumes = [float(c.volume or 0.0) for c in candles]

    first_price = prices[0]
    last_price = prices[-1]
    price_change = last_price - first_price
    price_change_percent = ((price_change / first_price) * 100) if first_price else 0.0

    return {
        "count": len(candles),
        "asset": candles[0].asset,
        "timeframe": candles[0].timeframe,
        "first_timestamp": candles[0].timestamp,
        "last_timestamp": candles[-1].timestamp,
        "first_price": first_price,
        "last_price": last_price,
        "price_change": price_change,
        "price_change_percent": price_change_percent,
        "highest": max(highs),
        "lowest": min(lows),
        "average_open": sum(opens) / len(opens),
        "average_close": sum(prices) / len(prices),
        "average_volume": (sum(volumes) / len(volumes)) if volumes else 0.0,
        "total_volume": sum(volumes),
        "volatility": calculate_volatility(prices),
        "trend": determine_trend(prices),
        "support_resistance": calculate_support_resistance(list(candles)),
    }


def calculate_volatility(prices: Sequence[float], periods: int = 14) -> float:
    """
    Desvio padrão simples dos últimos preços.
    """
    if not prices:
        return 0.0

    periods = min(periods, len(prices))
    recent_prices = list(prices)[-periods:]
    mean = sum(recent_prices) / len(recent_prices)
    variance = sum((price - mean) ** 2 for price in recent_prices) / len(recent_prices)
    return variance ** 0.5


def determine_trend(prices: Sequence[float], periods: int = 10) -> str:
    """
    Determina tendência simplificada: bullish / bearish / sideways.
    """
    if not prices:
        return "sideways"

    periods = min(periods, len(prices))
    if periods < 2:
        return "sideways"

    recent_prices = list(prices)[-periods:]
    midpoint = max(1, periods // 2)

    first_half = recent_prices[:midpoint]
    second_half = recent_prices[midpoint:]

    if not second_half:
        return "sideways"

    first_avg = sum(first_half) / len(first_half)
    second_avg = sum(second_half) / len(second_half)

    if first_avg == 0:
        return "sideways"

    change_percent = ((second_avg - first_avg) / first_avg) * 100

    if change_percent > 0.1:
        return "bullish"
    if change_percent < -0.1:
        return "bearish"
    return "sideways"


def calculate_support_resistance(
    candles: Sequence[Candle],
    periods: int = 20,
) -> Dict[str, float]:
    """
    Calcula suporte e resistência simples.
    """
    if not candles:
        return {"support": 0.0, "resistance": 0.0, "range": 0.0}

    periods = min(periods, len(candles))
    recent = list(candles)[-periods:]

    highs = [c.high for c in recent]
    lows = [c.low for c in recent]

    resistance = max(highs)
    support = min(lows)

    return {
        "support": support,
        "resistance": resistance,
        "range": resistance - support,
    }


def merge_candles(
    existing: Sequence[Candle],
    incoming: Sequence[Candle],
    max_length: int = 2000,
) -> List[Candle]:
    """
    Mescla candles sem duplicar timestamp+asset+timeframe.
    """
    merged_map: Dict[tuple, Candle] = {}

    for candle in list(existing) + list(incoming):
        key = (
            candle.asset,
            candle.timeframe,
            candle.timestamp.timestamp(),
        )
        merged_map[key] = candle

    merged = list(merged_map.values())
    merged.sort(key=lambda c: c.timestamp)

    if len(merged) > max_length:
        merged = merged[-max_length:]

    return merged


def candles_to_dataframe(candles: Sequence[Candle]) -> pd.DataFrame:
    """
    Converte candles para DataFrame pandas.
    """
    data = []
    for candle in candles:
        data.append(
            {
                "timestamp": candle.timestamp,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "asset": candle.asset,
                "timeframe": candle.timeframe,
            }
        )

    df = pd.DataFrame(data)
    if not df.empty:
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)

    return df


# -----------------------------------------------------------------------------
# Ativos / filtros
# -----------------------------------------------------------------------------

def validate_asset_symbol(symbol: str, available_assets: Optional[Dict[str, int]] = None) -> bool:
    """
    Valida se um ativo existe no catálogo base.
    Observação: o catálogo real pode vir do WebSocket.
    """
    catalog = available_assets or ASSETS
    return normalize_asset(symbol) in catalog


def filter_asset_records(
    assets: Dict[str, Dict[str, Any]],
    *,
    asset_type: Optional[str] = None,
    min_payout: Optional[float] = None,
    max_payout: Optional[float] = None,
    is_open: Optional[bool] = None,
    otc: Optional[bool] = None,
    search: Optional[str] = None,
    volatility: Optional[Union[str, float]] = None,
    trading_hours: Optional[Union[str, Dict[str, Any]]] = None,
    extra_filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Aplica filtro avançado em registros de ativos já carregados.
    """
    normalized_asset_type = normalize_asset_kind(asset_type) if asset_type else None

    def match_volatility(record_value: Any, filter_value: Union[str, float]) -> bool:
        if filter_value is None:
            return True

        if isinstance(filter_value, (int, float)):
            try:
                return float(record_value) >= float(filter_value)
            except Exception:
                return False

        if record_value is None:
            return False

        try:
            numeric = float(record_value)
        except Exception:
            numeric = None

        wanted = str(filter_value).strip().lower()

        if numeric is None:
            return str(record_value).strip().lower() == wanted

        if wanted in {"baixa", "low"}:
            return numeric < 0.33
        if wanted in {"media", "média", "medium"}:
            return 0.33 <= numeric < 0.66
        if wanted in {"alta", "high"}:
            return numeric >= 0.66

        return str(record_value).strip().lower() == wanted

    def match_trading_hours(record: Dict[str, Any], wanted: Union[str, Dict[str, Any]]) -> bool:
        record_hours = record.get("trading_hours")
        if wanted is None:
            return True

        if record_hours is None:
            if isinstance(wanted, str) and wanted.lower() in {"open", "aberto"}:
                return bool(record.get("is_open"))
            return False

        if isinstance(wanted, str):
            return wanted.lower() in str(record_hours).lower()

        if isinstance(wanted, dict):
            if not isinstance(record_hours, dict):
                return False
            for key, value in wanted.items():
                if record_hours.get(key) != value:
                    return False
            return True

        return False

    def match(record: Dict[str, Any]) -> bool:
        payout = record.get("payout")
        record_type = normalize_asset_kind(record.get("type"))
        record_asset = str(record.get("asset", "")).lower()

        if normalized_asset_type:
            if record_type != normalized_asset_type and normalized_asset_type not in record_asset:
                return False

        if min_payout is not None:
            if payout is None or float(payout) < float(min_payout):
                return False

        if max_payout is not None:
            if payout is None or float(payout) > float(max_payout):
                return False

        if is_open is not None:
            if bool(record.get("is_open")) is not bool(is_open):
                return False

        if otc is not None:
            is_otc = (
                bool(record.get("is_otc"))
                or record_asset.endswith("_otc")
                or record_type == "otc"
            )
            if is_otc is not bool(otc):
                return False

        if search:
            haystack = " ".join(
                [
                    str(record.get("asset", "")),
                    str(record.get("symbol", "")),
                    str(record.get("name", "")),
                    str(record.get("display_name", "")),
                ]
            ).lower()
            if str(search).lower() not in haystack:
                return False

        if volatility is not None:
            if not match_volatility(record.get("volatility"), volatility):
                return False

        if trading_hours is not None:
            if not match_trading_hours(record, trading_hours):
                return False

        if extra_filters:
            for key, expected in extra_filters.items():
                if key not in record:
                    return False
                if isinstance(expected, (list, tuple, set)):
                    if record.get(key) not in expected:
                        return False
                else:
                    if record.get(key) != expected:
                        return False

        return True

    return {name: data for name, data in assets.items() if match(data)}


# -----------------------------------------------------------------------------
# Tempo / expiração
# -----------------------------------------------------------------------------

def calculate_order_expiration(
    duration_seconds: int,
    current_time: Optional[datetime] = None,
) -> datetime:
    """
    Calcula expiração da ordem.
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    elif current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    return current_time + timedelta(seconds=duration_seconds)


# -----------------------------------------------------------------------------
# Retry / performance decorators
# -----------------------------------------------------------------------------

def retry_async(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
) -> Callable:
    """
    Decorador para retry assíncrono.
    """

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_attempts - 1:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {exc}"
                        )
                        raise

                    logger.warning(
                        f"Attempt {attempt + 1} failed for {func.__name__}: {exc}"
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff_factor

        return wrapper

    return decorator


def performance_monitor(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """
    Decorador simples de monitoramento de performance.
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.debug(f"{func.__name__} executed in {elapsed:.3f}s")
            return result
        except Exception as exc:
            elapsed = time.time() - start_time
            logger.error(f"{func.__name__} failed after {elapsed:.3f}s: {exc}")
            raise

    return wrapper


# -----------------------------------------------------------------------------
# Rate limiter
# -----------------------------------------------------------------------------

class RateLimiter:
    """
    Limitador de taxa assíncrono simples.
    """

    def __init__(self, max_calls: int = 100, time_window: int = 60):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls: List[float] = []

    async def acquire(self) -> bool:
        now = time.time()

        self.calls = [
            call_time
            for call_time in self.calls
            if now - call_time < self.time_window
        ]

        if len(self.calls) < self.max_calls:
            self.calls.append(now)
            return True

        wait_time = self.time_window - (now - self.calls[0])
        if wait_time > 0:
            logger.warning(f"Rate limit exceeded, waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
            return await self.acquire()

        return True


# -----------------------------------------------------------------------------
# Order manager simples
# -----------------------------------------------------------------------------

class OrderManager:
    """
    Gerenciador simples de ordens ativas/concluídas.
    """

    def __init__(self):
        self.active_orders: Dict[str, OrderResult] = {}
        self.completed_orders: Dict[str, OrderResult] = {}
        self.order_callbacks: Dict[str, List[Callable[[OrderResult], None]]] = {}

    def add_order(self, order: OrderResult) -> None:
        self.active_orders[order.order_id] = order

    def complete_order(self, order_id: str, result: OrderResult) -> None:
        if order_id in self.active_orders:
            del self.active_orders[order_id]

        self.completed_orders[order_id] = result

        if order_id in self.order_callbacks:
            for callback in self.order_callbacks[order_id]:
                try:
                    callback(result)
                except Exception as exc:
                    logger.error(f"Order callback error: {exc}")
            del self.order_callbacks[order_id]

    def add_order_callback(self, order_id: str, callback: Callable[[OrderResult], None]) -> None:
        if order_id not in self.order_callbacks:
            self.order_callbacks[order_id] = []
        self.order_callbacks[order_id].append(callback)

    def get_order_status(self, order_id: str) -> Optional[OrderResult]:
        if order_id in self.active_orders:
            return self.active_orders[order_id]
        if order_id in self.completed_orders:
            return self.completed_orders[order_id]
        return None

    def get_active_count(self) -> int:
        return len(self.active_orders)

    def get_completed_count(self) -> int:
        return len(self.completed_orders)


# -----------------------------------------------------------------------------
# DataFrame / export helpers
# -----------------------------------------------------------------------------

def asset_records_to_dataframe(assets: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    """
    Converte registros de ativos para DataFrame.
    """
    rows: List[Dict[str, Any]] = []
    for asset_name, record in assets.items():
        row = dict(record)
        row.setdefault("asset", asset_name)
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty and "asset" in df.columns:
        df.sort_values(by=["asset"], inplace=True)
        df.reset_index(drop=True, inplace=True)

    return df


def payouts_to_dataframe(payouts: Dict[str, Any]) -> pd.DataFrame:
    """
    Converte payouts para DataFrame.
    Aceita:
    - {"EURUSD": 92}
    - {"EURUSD": {"payout": 92, ...}}
    """
    rows: List[Dict[str, Any]] = []

    for asset_name, value in payouts.items():
        if isinstance(value, dict):
            row = dict(value)
            row.setdefault("asset", asset_name)
            rows.append(row)
        else:
            rows.append(
                {
                    "asset": asset_name,
                    "payout": value,
                }
            )

    df = pd.DataFrame(rows)
    if not df.empty and "asset" in df.columns:
        df.sort_values(by=["asset"], inplace=True)
        df.reset_index(drop=True, inplace=True)

    return df