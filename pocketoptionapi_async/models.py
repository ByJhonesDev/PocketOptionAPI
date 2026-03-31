"""
Autor: ByJhonesDev
Projeto: PocketOptionAPI – Biblioteca Python assíncrona de alto nível para integração com a corretora Pocket Option, com tipagem forte, validação estruturada e tolerância a payloads variáveis do broker.

Descrição:
Módulo responsável pela modelagem central de dados da biblioteca usando Pydantic v2. Define enums, entidades operacionais, envelopes de eventos, snapshots de estado e modelos auxiliares para ativos, payouts, candles, ordens, conexão, configurações de conta e estado consolidado do broker, com validações e normalizações defensivas para preservar compatibilidade diante de mudanças nos payloads recebidos.

O que ele faz:
- Define enums principais de direção, status, timeframe, tipo de ativo e eventos
- Modela ativos simples e enriquecidos
- Modela saldo, candles, payouts e ordens
- Modela resultados de ordens e sincronização de tempo do servidor
- Modela limites operacionais e notícias do broker
- Modela configuração de conta e conexão
- Modela envelopes de socket e eventos internos
- Modela snapshots consolidados do estado do broker
- Normaliza símbolos, timestamps, payout, tipo de ativo e status de mercado

Características:
- Base comum com tolerância a campos extras
- Compatibilidade com Pydantic v2
- Validação defensiva e normalização automática
- Modelos imutáveis nos pontos críticos
- Estrutura rica para uso em runtime, análise e serialização
- Preparado para mudanças futuras do broker sem quebra imediata

Requisitos:
- Python 3.10+
- pydantic v2
- typing
- enum
- datetime
- uuid
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# -----------------------------------------------------------------------------
# Base helpers
# -----------------------------------------------------------------------------


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PocketBaseModel(BaseModel):
    """
    Base comum para todos os modelos da biblioteca.

    - extra='allow' para tolerar mudanças do broker sem quebrar parsing
    - populate_by_name=True para facilitar aliases
    """

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        arbitrary_types_allowed=True,
        use_enum_values=False,
    )


# -----------------------------------------------------------------------------
# Enums principais
# -----------------------------------------------------------------------------


class OrderDirection(str, Enum):
    CALL = "call"
    PUT = "put"


class OrderStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    WIN = "win"
    LOSE = "lose"
    DRAW = "draw"
    ERROR = "error"


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    RECONNECTING = "reconnecting"
    AUTHENTICATING = "authenticating"


class TimeFrame(int, Enum):
    S1 = 1
    S5 = 5
    S10 = 10
    S15 = 15
    S30 = 30
    M1 = 60
    M2 = 120
    M3 = 180
    M5 = 300
    M10 = 600
    M15 = 900
    M30 = 1800
    H1 = 3600
    H2 = 7200
    H4 = 14400
    H8 = 28800
    D1 = 86400
    W1 = 604800


class AssetType(str, Enum):
    FOREX = "forex"
    STOCK = "stock"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    INDEX = "index"
    ETF = "etf"
    DIGITAL = "digital"
    OTC = "otc"
    CFD = "cfd"
    UNKNOWN = "unknown"


class MarketStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    PAUSED = "paused"
    OTC = "otc"
    UNKNOWN = "unknown"


class BrokerEventType(str, Enum):
    AUTHENTICATED = "authenticated"
    BALANCE_UPDATED = "balance_updated"
    ORDER_OPENED = "order_opened"
    ORDER_CLOSED = "order_closed"
    STREAM_UPDATE = "stream_update"
    CANDLE_SNAPSHOT = "candle_snapshot"
    CANDLE_UPDATE = "candle_update"
    PAYOUT_UPDATE = "payout_update"
    ASSET_SNAPSHOT = "asset_snapshot"
    NEWS_UPDATE = "news_update"
    SERVER_TIME = "server_time"
    ACCOUNT_CONFIG = "account_config"
    ACCOUNT_LIMITS = "account_limits"
    RAW = "raw"
    UNKNOWN = "unknown"


# -----------------------------------------------------------------------------
# Compatibilidade / modelos principais
# -----------------------------------------------------------------------------


class Asset(PocketBaseModel):
    """
    Modelo mínimo compatível com a versão atual.
    """

    id: Union[str, int]
    name: str
    symbol: str
    is_active: bool = True
    payout: Optional[float] = None

    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        populate_by_name=True,
    )

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: Any) -> str:
        return str(value or "").strip().upper()


class AssetInfo(PocketBaseModel):
    """
    Modelo completo de ativo vindo/derivado do broker.
    """

    asset: str
    symbol: Optional[str] = None
    display_name: Optional[str] = None
    asset_id: Optional[Union[int, str]] = None
    type: AssetType = AssetType.UNKNOWN
    market_status: MarketStatus = MarketStatus.UNKNOWN
    is_open: Optional[bool] = None
    is_otc: bool = False
    payout: Optional[float] = None
    payout_source: Optional[str] = None
    schedule_open: Optional[datetime] = None
    schedule_close: Optional[datetime] = None
    trading_hours: Optional[Union[str, Dict[str, Any]]] = None
    volatility: Optional[Union[float, str]] = None
    tags: List[str] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: Any) -> str:
        raw = str(value or "").strip().upper()
        raw = raw.replace("/", "")
        if " OTC" in raw:
            raw = raw.replace(" OTC", "_otc")
        elif raw.endswith("_OTC"):
            raw = raw[:-4] + "_otc"
        return raw

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value).strip().upper().replace("/", "")

    @field_validator("payout", mode="before")
    @classmethod
    def normalize_payout(cls, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            payout = float(value)
        except Exception:
            return None
        if 0 < payout <= 1:
            payout *= 100.0
        return round(payout, 2)

    @field_validator("is_open", mode="before")
    @classmethod
    def normalize_is_open(cls, value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"open", "opened", "available", "active", "tradable", "enabled", "1", "true", "yes", "on"}:
                return True
            if normalized in {"closed", "close", "unavailable", "inactive", "disabled", "0", "false", "no", "off"}:
                return False
        return None

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: Any) -> AssetType:
        if isinstance(value, AssetType):
            return value
        if value is None:
            return AssetType.UNKNOWN
        normalized = str(value).strip().lower()
        for asset_type in AssetType:
            if asset_type.value == normalized:
                return asset_type
        return AssetType.UNKNOWN

    @model_validator(mode="after")
    def derive_fields(self) -> "AssetInfo":
        if not self.symbol:
            self.symbol = self.asset

        if not self.display_name:
            self.display_name = self.symbol or self.asset

        if not self.is_otc:
            asset_lower = (self.asset or "").lower()
            symbol_lower = (self.symbol or "").lower()
            self.is_otc = (
                asset_lower.endswith("_otc")
                or symbol_lower.endswith("_otc")
                or self.type == AssetType.OTC
            )

        if self.market_status == MarketStatus.UNKNOWN:
            if self.is_otc:
                self.market_status = MarketStatus.OTC
            elif self.is_open is True:
                self.market_status = MarketStatus.OPEN
            elif self.is_open is False:
                self.market_status = MarketStatus.CLOSED

        if not self.raw:
            self.raw = {}

        return self


class AssetFilter(PocketBaseModel):
    """
    Filtro estruturado opcional para ativos.
    """

    type: Optional[AssetType] = None
    only_open: Optional[bool] = None
    min_payout: Optional[float] = None
    max_payout: Optional[float] = None
    is_otc: Optional[bool] = None
    search: Optional[str] = None
    min_volatility: Optional[float] = None
    max_volatility: Optional[float] = None
    volatility: Optional[Union[float, str]] = None
    trading_hours: Optional[Union[str, Dict[str, Any]]] = None
    tags: List[str] = Field(default_factory=list)


class Balance(PocketBaseModel):
    balance: float
    currency: str = "USD"
    is_demo: bool = True
    last_updated: datetime = Field(default_factory=utc_now)

    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        populate_by_name=True,
    )

    @field_validator("balance", mode="before")
    @classmethod
    def normalize_balance(cls, value: Any) -> float:
        return float(value or 0.0)


class Candle(PocketBaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    asset: str
    timeframe: int
    is_closed: Optional[bool] = None
    source: Optional[str] = None

    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        populate_by_name=True,
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def normalize_timestamp(cls, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        try:
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000.0
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except Exception:
            return utc_now()

    @field_validator("open", "high", "low", "close", mode="before")
    @classmethod
    def normalize_price(cls, value: Any) -> float:
        return float(value or 0.0)

    @field_validator("volume", mode="before")
    @classmethod
    def normalize_volume(cls, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        return float(value)

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: Any) -> str:
        raw = str(value or "").strip().upper()
        raw = raw.replace("/", "")
        if " OTC" in raw:
            raw = raw.replace(" OTC", "_otc")
        elif raw.endswith("_OTC"):
            raw = raw[:-4] + "_otc"
        return raw

    @model_validator(mode="after")
    def validate_ohlc(self) -> "Candle":
        actual_high = max(self.open, self.high, self.low, self.close)
        actual_low = min(self.open, self.high, self.low, self.close)
        self.high = actual_high
        self.low = actual_low
        return self


class CandleStreamUpdate(PocketBaseModel):
    asset: str
    timeframe: int
    candle: Optional[Candle] = None
    candles: List[Candle] = Field(default_factory=list)
    count: int = 0
    subscription_key: Optional[str] = None
    updated_at: datetime = Field(default_factory=utc_now)
    raw: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def fill_count(self) -> "CandleStreamUpdate":
        if self.count == 0 and self.candles:
            self.count = len(self.candles)
        return self


class PayoutInfo(PocketBaseModel):
    asset: str
    payout: float
    asset_id: Optional[Union[int, str]] = None
    type: Optional[AssetType] = None
    is_open: Optional[bool] = None
    updated_at: datetime = Field(default_factory=utc_now)
    raw: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: Any) -> str:
        raw = str(value or "").strip().upper()
        raw = raw.replace("/", "")
        if " OTC" in raw:
            raw = raw.replace(" OTC", "_otc")
        elif raw.endswith("_OTC"):
            raw = raw[:-4] + "_otc"
        return raw

    @field_validator("payout", mode="before")
    @classmethod
    def normalize_payout(cls, value: Any) -> float:
        payout = float(value or 0.0)
        if 0 < payout <= 1:
            payout *= 100.0
        return round(payout, 2)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: Any) -> Optional[AssetType]:
        if value is None:
            return None
        if isinstance(value, AssetType):
            return value
        normalized = str(value).strip().lower()
        for asset_type in AssetType:
            if asset_type.value == normalized:
                return asset_type
        return AssetType.UNKNOWN


class Order(PocketBaseModel):
    asset: str
    amount: float
    direction: OrderDirection
    duration: int
    request_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: Any) -> str:
        raw = str(value or "").strip().upper()
        raw = raw.replace("/", "")
        if " OTC" in raw:
            raw = raw.replace(" OTC", "_otc")
        elif raw.endswith("_OTC"):
            raw = raw[:-4] + "_otc"
        return raw

    @field_validator("amount", mode="before")
    @classmethod
    def amount_must_be_positive(cls, value: Any) -> float:
        amount = float(value or 0.0)
        if amount <= 0:
            raise ValueError("Amount must be positive")
        return amount

    @field_validator("duration", mode="before")
    @classmethod
    def duration_must_be_valid(cls, value: Any) -> int:
        duration = int(value or 0)
        if duration < 5:
            raise ValueError("Duration must be at least 5 seconds")
        return duration


class OrderResult(PocketBaseModel):
    order_id: str
    asset: str
    amount: float
    direction: OrderDirection
    duration: int
    status: OrderStatus
    placed_at: datetime
    expires_at: datetime
    profit: Optional[float] = None
    payout: Optional[float] = None
    error_message: Optional[str] = None

    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        populate_by_name=True,
    )

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: Any) -> str:
        raw = str(value or "").strip().upper()
        raw = raw.replace("/", "")
        if " OTC" in raw:
            raw = raw.replace(" OTC", "_otc")
        elif raw.endswith("_OTC"):
            raw = raw[:-4] + "_otc"
        return raw

    @field_validator("placed_at", "expires_at", mode="before")
    @classmethod
    def normalize_datetime(cls, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        try:
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000.0
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except Exception:
            return utc_now()

    @field_validator("profit", "payout", mode="before")
    @classmethod
    def normalize_numeric_optional(cls, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        return float(value)


class ServerTime(PocketBaseModel):
    server_timestamp: float
    local_timestamp: float
    offset: float
    last_sync: datetime = Field(default_factory=utc_now)

    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        populate_by_name=True,
    )

    @field_validator("server_timestamp", "local_timestamp", "offset", mode="before")
    @classmethod
    def normalize_float(cls, value: Any) -> float:
        return float(value or 0.0)


# -----------------------------------------------------------------------------
# Broker extra sections
# -----------------------------------------------------------------------------


class TradeLimit(PocketBaseModel):
    asset: Optional[str] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    min_duration: Optional[int] = None
    max_duration: Optional[int] = None
    max_concurrent_orders: Optional[int] = None
    raw: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        raw = str(value).strip().upper().replace("/", "")
        if " OTC" in raw:
            raw = raw.replace(" OTC", "_otc")
        elif raw.endswith("_OTC"):
            raw = raw[:-4] + "_otc"
        return raw

    @field_validator("min_amount", "max_amount", mode="before")
    @classmethod
    def normalize_amount(cls, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        return float(value)

    @field_validator("min_duration", "max_duration", "max_concurrent_orders", mode="before")
    @classmethod
    def normalize_ints(cls, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        return int(value)


class BrokerNewsItem(PocketBaseModel):
    news_id: Optional[Union[int, str]] = None
    title: str
    body: Optional[str] = None
    category: Optional[str] = None
    published_at: Optional[datetime] = None
    importance: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("published_at", mode="before")
    @classmethod
    def normalize_published_at(cls, value: Any) -> Optional[datetime]:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        try:
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000.0
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except Exception:
            try:
                parsed = datetime.fromisoformat(str(value))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except Exception:
                return None


class AccountConfiguration(PocketBaseModel):
    account_id: Optional[Union[int, str]] = None
    user_id: Optional[Union[int, str]] = None
    is_demo: Optional[bool] = None
    currency: Optional[str] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    server_time: Optional[float] = None
    trade_limits: List[TradeLimit] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("server_time", mode="before")
    @classmethod
    def normalize_server_time(cls, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        return float(value)

    @field_validator("trade_limits", mode="before")
    @classmethod
    def normalize_trade_limits(cls, value: Any) -> List[TradeLimit]:
        if value is None:
            return []
        if isinstance(value, list):
            return [v if isinstance(v, TradeLimit) else TradeLimit.model_validate(v) for v in value]
        return []


# -----------------------------------------------------------------------------
# Conexão / envelopes / eventos
# -----------------------------------------------------------------------------


class ConnectionInfo(PocketBaseModel):
    url: str
    region: str
    status: ConnectionStatus
    connected_at: Optional[datetime] = None
    last_ping: Optional[datetime] = None
    reconnect_attempts: int = 0

    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        populate_by_name=True,
    )

    @field_validator("connected_at", "last_ping", mode="before")
    @classmethod
    def normalize_datetimes(cls, value: Any) -> Optional[datetime]:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        try:
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000.0
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except Exception:
            try:
                parsed = datetime.fromisoformat(str(value))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except Exception:
                return None


class RawSocketEnvelope(PocketBaseModel):
    event: str
    payload: Any
    received_at: datetime = Field(default_factory=utc_now)
    raw_message: Optional[str] = None


class BrokerEvent(PocketBaseModel):
    type: BrokerEventType
    name: str
    payload: Any
    received_at: datetime = Field(default_factory=utc_now)
    envelope: Optional[RawSocketEnvelope] = None


# -----------------------------------------------------------------------------
# Estado consolidado do broker
# -----------------------------------------------------------------------------


class BrokerStateSnapshot(PocketBaseModel):
    server_time: Optional[ServerTime] = None
    balance: Optional[Balance] = None
    assets: Dict[str, AssetInfo] = Field(default_factory=dict)
    payouts: Dict[str, PayoutInfo] = Field(default_factory=dict)
    limits: List[TradeLimit] = Field(default_factory=list)
    news: List[BrokerNewsItem] = Field(default_factory=list)
    account: Optional[AccountConfiguration] = None
    raw_sections: Dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)


# -----------------------------------------------------------------------------
# Modelos utilitários para payloads do client realtime
# -----------------------------------------------------------------------------


class AssetSnapshot(PocketBaseModel):
    event: str = "assets"
    assets: Dict[str, AssetInfo] = Field(default_factory=dict)
    count: int = 0
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def fill_count(self) -> "AssetSnapshot":
        if self.count == 0:
            self.count = len(self.assets)
        return self


class PayoutSnapshot(PocketBaseModel):
    event: str = "payouts"
    assets: Dict[str, PayoutInfo] = Field(default_factory=dict)
    count: int = 0
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def fill_count(self) -> "PayoutSnapshot":
        if self.count == 0:
            self.count = len(self.assets)
        return self