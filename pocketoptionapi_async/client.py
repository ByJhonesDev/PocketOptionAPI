"""
Autor: ByJhonesDev
Projeto: PocketOptionAPI – Biblioteca Python assíncrona de alto nível para integração com a corretora Pocket Option, desenvolvida para fornecer uma camada confiável, extensível, resiliente e orientada a eventos para automação operacional e processamento de dados de mercado em tempo real.

Descrição:
Cliente assíncrono principal da biblioteca responsável por abstrair a comunicação com a Pocket Option via WebSocket, mantendo compatibilidade com a API existente e expandindo os recursos realtime da sessão. A implementação centraliza autenticação, sincronização de estado, gerenciamento de conexão, ordens, ativos, payouts, candles e eventos internos do broker em uma interface mais segura para consumo em automações, robôs e serviços de monitoramento.

O que ele faz:
- Autentica sessões da Pocket Option usando SSID simples ou payload completo de autenticação
- Estabelece conexão WebSocket com seleção de região, suporte a modo demo/live e keep-alive
- Mantém reconexão automática e restaura subscriptions realtime após perda de conexão
- Consulta saldo da conta e sincroniza informações básicas do estado da sessão
- Envia ordens e acompanha ciclo de vida da operação até resultado final
- Solicita candles históricos e converte os dados também para DataFrame com pandas
- Faz streaming de candles em tempo real via callback ou async generator
- Solicita snapshot de ativos e mantém cache dinâmico de ativos, status e payouts
- Permite filtros avançados de ativos por payout, abertura, OTC, tipo, busca textual, volatilidade e horário
- Expõe estado consolidado do broker, incluindo conexão, conta, ativos, candles, ordens, limites e eventos desconhecidos
- Captura payloads brutos e eventos não mapeados de forma defensiva para preservar compatibilidade futura

Características:
- Arquitetura assíncrona baseada em asyncio
- Integração orientada a eventos com callbacks síncronos e assíncronos
- Compatibilidade com interface anterior da biblioteca
- Suporte a conexão persistente e monitoramento de saúde da sessão
- Cache interno para candles, payouts, ativos e estado consolidado
- Normalização defensiva de payloads recebidos do broker
- Tratamento de reconexão com restauração automática de subscriptions
- Exposição de dados históricos e realtime em uma mesma interface
- Estrutura preparada para extensões futuras sem quebrar a API pública
- Suporte a análise tabular com pandas

Requisitos:
- Python 3.10+
- asyncio
- pandas
- loguru
- Módulos internos do projeto:
  - constants
  - exceptions
  - models
  - monitoring
  - websocket_client
  - connection_keep_alive
"""

from __future__ import annotations
import asyncio
import json
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    DefaultDict,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

import pandas as pd
from loguru import logger

from .constants import API_LIMITS, ASSET_IDS_TO_NAMES, ASSETS, REGIONS, TIMEFRAMES
from .exceptions import (
    AuthenticationError,
    ConnectionError,
    InvalidParameterError,
    OrderError,
    PocketOptionError,
)
from .models import (
    Balance,
    Candle,
    Order,
    OrderDirection,
    OrderResult,
    OrderStatus,
    ServerTime,
)
from .monitoring import ErrorCategory, ErrorSeverity, error_monitor, health_checker
from .websocket_client import AsyncWebSocketClient

EventCallback = Callable[[Any], Union[None, Awaitable[None]]]

@dataclass
class CandleQueueSubscription:
    key: str
    asset: str
    timeframe: int
    queue: asyncio.Queue
    emit_history: bool = True

def _server_ts_to_dt_utc(ts: Any) -> datetime:
    """Converte timestamp do broker para datetime UTC timezone-aware."""
    try:
        value = float(ts)
    except Exception:
        value = 0.0

    if value > 10_000_000_000:
        value /= 1000.0

    dt = datetime.fromtimestamp(value, tz=timezone.utc)
    now = datetime.now(timezone.utc)

    # Ajuste defensivo contra payloads com offset inconsistente
    if dt > now + timedelta(minutes=5):
        delta = (dt - now).total_seconds()
        hours = int(round(delta / 3600.0))
        if hours == 0:
            hours = 1
        hours = max(min(hours, 12), -12)
        dt = dt - timedelta(hours=hours)

    return dt

class AsyncPocketOptionClient:
    """Cliente async principal da PocketOption com suporte realtime expandido."""

    def __init__(
        self,
        ssid: str,
        is_demo: bool = True,
        region: Optional[str] = None,
        uid: int = 0,
        platform: int = 1,
        is_fast_history: bool = True,
        persistent_connection: bool = False,
        auto_reconnect: bool = True,
        enable_logging: bool = True,
    ):
        self.raw_ssid = ssid
        self.is_demo = is_demo
        self.preferred_region = region
        self.uid = uid
        self.platform = platform
        self.is_fast_history = is_fast_history
        self.persistent_connection = persistent_connection
        self.auto_reconnect = auto_reconnect
        self.enable_logging = enable_logging

        if not enable_logging:
            logger.remove()
            logger.add(lambda _: None, level="CRITICAL")

        self._original_demo = None
        if ssid.startswith('42["auth",'):
            self._parse_complete_ssid(ssid)
        else:
            self.session_id = ssid
            self._complete_ssid = None

        self._websocket = AsyncWebSocketClient()
        self._balance: Optional[Balance] = None
        self._orders: Dict[str, OrderResult] = {}
        self._active_orders: Dict[str, OrderResult] = {}
        self._order_results: Dict[str, OrderResult] = {}
        self._candles_cache: Dict[str, List[Candle]] = {}
        self._server_time: Optional[ServerTime] = None

        self._event_callbacks: DefaultDict[str, List[EventCallback]] = defaultdict(list)
        self._pending_event_futures: DefaultDict[str, List[asyncio.Future]] = defaultdict(list)

        self._error_monitor = error_monitor
        self._health_checker = health_checker
        self._operation_metrics: DefaultDict[str, List[float]] = defaultdict(list)
        self._last_health_check = time.time()

        self._keep_alive_manager = None
        self._ping_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._is_persistent = False

        self._connection_stats: Dict[str, Any] = {
            "total_connections": 0,
            "successful_connections": 0,
            "total_reconnects": 0,
            "last_ping_time": None,
            "messages_sent": 0,
            "messages_received": 0,
            "connection_start_time": None,
        }

        # Estado realtime expandido
        self._payouts_cache: Dict[str, float] = {}
        self._asset_status_cache: Dict[str, Dict[str, Any]] = {}
        self._assets_last_update_ts: Optional[float] = None
        self._payouts_cache_timestamp: Optional[float] = None
        self._payouts_cache_ttl: float = 30.0
        self._latest_candles: Dict[str, Candle] = {}
        self._candle_stream_subscriptions: Dict[str, Dict[str, Any]] = {}
        self._candle_queue_subscriptions: Dict[str, List[CandleQueueSubscription]] = defaultdict(list)
        self._raw_state_sections: Dict[str, Any] = {}
        self._raw_events_history: List[Dict[str, Any]] = []
        self._news_cache: List[Dict[str, Any]] = []
        self._account_config: Dict[str, Any] = {}
        self._trade_limits: List[Dict[str, Any]] = []
        self._last_unknown_events: List[Dict[str, Any]] = []
        self._last_assets_request_at: Optional[float] = None
        self._asset_request_cooldown: float = 2.0

        self._setup_event_handlers()
        self._websocket.add_event_handler("json_data", self._on_json_data)
        self._websocket.add_event_handler("raw_message", self._on_raw_message)
        self._websocket.add_event_handler("unknown_event", self._on_unknown_event)

        logger.info(
            f"Initialized PocketOption client (demo={is_demo}, uid={self.uid}, persistent={persistent_connection})"
            if enable_logging
            else ""
        )

    # -------------------------------------------------------------------------
    # Setup / connection lifecycle
    # -------------------------------------------------------------------------

    def _setup_event_handlers(self) -> None:
        self._websocket.add_event_handler("authenticated", self._on_authenticated)
        self._websocket.add_event_handler("balance_updated", self._on_balance_updated)
        self._websocket.add_event_handler("balance_data", self._on_balance_data)
        self._websocket.add_event_handler("order_opened", self._on_order_opened)
        self._websocket.add_event_handler("order_closed", self._on_order_closed)
        self._websocket.add_event_handler("stream_update", self._on_stream_update)
        self._websocket.add_event_handler("candles_received", self._on_candles_received)
        self._websocket.add_event_handler("history_update", self._on_history_update)
        self._websocket.add_event_handler("disconnected", self._on_disconnected)
        self._websocket.add_event_handler("assets", self._on_assets_event)
        self._websocket.add_event_handler("assets_received", self._on_assets_event)
        self._websocket.add_event_handler("payout_update", self._on_payout_update)

    async def connect(
        self,
        regions: Optional[List[str]] = None,
        persistent: Optional[bool] = None,
    ) -> bool:
        logger.info("Connecting to PocketOption...")

        if persistent is not None:
            self.persistent_connection = bool(persistent)

        try:
            if self.persistent_connection:
                return await self._start_persistent_connection(regions)
            return await self._start_regular_connection(regions)
        except Exception as exc:
            logger.error(f"Connection failed: {exc}")
            await self._error_monitor.record_error(
                error_type="connection_failed",
                severity=ErrorSeverity.HIGH,
                category=ErrorCategory.CONNECTION,
                message=f"Connection failed: {exc}",
            )
            return False

    async def _start_regular_connection(self, regions: Optional[List[str]] = None) -> bool:
        logger.info("Starting regular connection...")

        if not regions:
            if self.preferred_region:
                regions = [self.preferred_region]
            elif self.is_demo:
                demo_urls = REGIONS.get_demo_regions()
                all_regions = REGIONS.get_all_regions()
                regions = [name for name, url in all_regions.items() if url in demo_urls]
                logger.info(f"Demo mode: using demo regions: {regions}")
            else:
                all_regions = REGIONS.get_all_regions()
                regions = [name for name in all_regions.keys() if "DEMO" not in name.upper()]
                logger.info(f"Live mode: using non-demo regions: {regions}")

        self._connection_stats["total_connections"] += 1
        self._connection_stats["connection_start_time"] = time.time()

        for region in regions:
            try:
                region_url = REGIONS.get_region(region)
                if not region_url:
                    continue

                logger.info(f"Trying region: {region} ({region_url})")
                ssid_message = self._format_session_message()
                success = await self._websocket.connect([region_url], ssid_message)

                if success:
                    await self._wait_for_authentication()
                    await self._initialize_data()
                    await self._start_keep_alive_tasks()
                    self._connection_stats["successful_connections"] += 1
                    logger.info(f"Connected and authenticated on region: {region}")
                    await self._emit_event("connected", {"region": region, "url": region_url})
                    return True
            except Exception as exc:
                logger.warning(f"Failed to connect to region {region}: {exc}")
                continue

        return False

    async def _start_persistent_connection(self, regions: Optional[List[str]] = None) -> bool:
        logger.info("Starting persistent connection with automatic keep-alive...")

        from .connection_keep_alive import ConnectionKeepAlive

        complete_ssid = self.raw_ssid
        self._keep_alive_manager = ConnectionKeepAlive(complete_ssid, self.is_demo)

        self._keep_alive_manager.add_event_handler("connected", self._on_keep_alive_connected)
        self._keep_alive_manager.add_event_handler("reconnected", self._on_keep_alive_reconnected)
        self._keep_alive_manager.add_event_handler("message_received", self._on_keep_alive_message)
        self._keep_alive_manager.add_event_handler("balance_data", self._on_balance_data)
        self._keep_alive_manager.add_event_handler("balance_updated", self._on_balance_updated)
        self._keep_alive_manager.add_event_handler("authenticated", self._on_authenticated)
        self._keep_alive_manager.add_event_handler("order_opened", self._on_order_opened)
        self._keep_alive_manager.add_event_handler("order_closed", self._on_order_closed)
        self._keep_alive_manager.add_event_handler("stream_update", self._on_stream_update)
        self._keep_alive_manager.add_event_handler("json_data", self._on_json_data)
        self._keep_alive_manager.add_event_handler("assets", self._on_assets_event)
        self._keep_alive_manager.add_event_handler("assets_received", self._on_assets_event)
        self._keep_alive_manager.add_event_handler("payout_update", self._on_payout_update)

        success = await self._keep_alive_manager.connect_with_keep_alive(regions)
        if success:
            self._is_persistent = True
            logger.info("Persistent connection established successfully")
            await self._emit_event("connected", {"persistent": True})
            return True

        logger.error("Failed to establish persistent connection")
        return False

    async def _start_keep_alive_tasks(self) -> None:
        logger.info("Starting keep-alive tasks for regular connection...")
        self._ping_task = asyncio.create_task(self._ping_loop())
        if self.auto_reconnect:
            self._reconnect_task = asyncio.create_task(self._reconnection_monitor())

    async def _ping_loop(self) -> None:
        while self.is_connected and not self._is_persistent:
            try:
                await self._websocket.send_message('42["ps"]')
                self._connection_stats["last_ping_time"] = time.time()
                await asyncio.sleep(20)
            except Exception as exc:
                logger.warning(f"Ping failed: {exc}")
                break

    async def _reconnection_monitor(self) -> None:
        while self.auto_reconnect and not self._is_persistent:
            await asyncio.sleep(30)
            if not self.is_connected:
                logger.info("Connection lost, attempting reconnection...")
                self._connection_stats["total_reconnects"] += 1
                try:
                    success = await self._start_regular_connection()
                    if success:
                        logger.info("Reconnection successful")
                        await self._restore_realtime_subscriptions()
                        await self._emit_event("reconnected", {})
                    else:
                        logger.error("Reconnection failed")
                        await asyncio.sleep(10)
                except Exception as exc:
                    logger.error(f"Reconnection error: {exc}")
                    await asyncio.sleep(10)

    async def disconnect(self) -> None:
        logger.info("Disconnecting from PocketOption...")

        if self._ping_task:
            self._ping_task.cancel()
        if self._reconnect_task:
            self._reconnect_task.cancel()

        if self._is_persistent and self._keep_alive_manager:
            await self._keep_alive_manager.disconnect()
        else:
            await self._websocket.disconnect()

        self._is_persistent = False
        self._balance = None
        self._orders.clear()

        logger.info("Disconnected successfully")
        await self._emit_event("disconnected", {})

    async def _restore_realtime_subscriptions(self) -> None:
        """Restaura subscriptions após reconexão."""
        if not self.is_connected:
            return

        for _, sub in list(self._candle_stream_subscriptions.items()):
            try:
                await self._send_change_symbol(sub["asset"], int(sub["timeframe"]))
            except Exception as exc:
                logger.debug(f"Unable to restore candle subscription {sub}: {exc}")

        try:
            await self.request_assets_snapshot(timeout=5.0)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Public API - base compatibility
    # -------------------------------------------------------------------------

    async def get_balance(self) -> Balance:
        if not self.is_connected:
            raise ConnectionError("Not connected to PocketOption")

        if not self._balance or (datetime.now() - self._balance.last_updated).seconds > 60:
            await self._request_balance_update()
            await asyncio.sleep(1)

        if not self._balance:
            raise PocketOptionError("Balance data not available")

        return self._balance

    async def place_order(
        self,
        asset: str,
        amount: float,
        direction: OrderDirection,
        duration: int,
    ) -> OrderResult:
        if not self.is_connected:
            raise ConnectionError("Not connected to PocketOption")

        self._validate_order_parameters(asset, amount, direction, duration)

        try:
            order_id = str(uuid.uuid4())
            order = Order(
                asset=asset,
                amount=amount,
                direction=direction,
                duration=duration,
                request_id=order_id,
            )
            await self._send_order(order)
            result = await self._wait_for_order_result(order_id, order)
            logger.info(f"Order placed: {result.order_id} - {result.status}")
            return result
        except Exception as exc:
            logger.error(f"Order placement failed: {exc}")
            raise OrderError(f"Failed to place order: {exc}") from exc

    async def get_candles(
        self,
        asset: str,
        timeframe: Union[str, int],
        count: int = 100,
        end_time: Optional[datetime] = None,
    ) -> List[Candle]:
        if not self.is_connected:
            if self.auto_reconnect:
                logger.info(f"Connection lost, attempting reconnection for {asset} candles...")
                reconnected = await self._attempt_reconnection()
                if not reconnected:
                    raise ConnectionError("Not connected to PocketOption and reconnection failed")
            else:
                raise ConnectionError("Not connected to PocketOption")

        timeframe_seconds = self._normalize_timeframe(timeframe)
        normalized_asset = self._normalize_asset_name_for_payout(asset)

        if normalized_asset not in ASSETS and normalized_asset not in self._asset_status_cache:
            logger.debug(f"Asset {normalized_asset} not found in static map; continuing with realtime symbol")

        if not end_time:
            end_time = datetime.now(timezone.utc)

        max_retries = 2
        for attempt in range(max_retries):
            try:
                candles = await self._request_candles(
                    normalized_asset,
                    timeframe_seconds,
                    count,
                    end_time,
                )
                cache_key = self._make_candle_cache_key(normalized_asset, timeframe_seconds)
                self._candles_cache[cache_key] = candles
                if candles:
                    self._latest_candles[cache_key] = candles[-1]
                logger.info(f"Retrieved {len(candles)} candles for {normalized_asset}")
                return candles
            except Exception as exc:
                if "WebSocket is not connected" in str(exc) and attempt < max_retries - 1:
                    logger.warning(f"Connection lost during candle request for {normalized_asset}, trying reconnection...")
                    if self.auto_reconnect:
                        reconnected = await self._attempt_reconnection()
                        if reconnected:
                            continue
                logger.error(f"Failed to get candles for {normalized_asset}: {exc}")
                raise PocketOptionError(f"Failed to get candles: {exc}") from exc

        raise PocketOptionError(f"Failed to get candles after {max_retries} attempts")

    async def get_candles_dataframe(
        self,
        asset: str,
        timeframe: Union[str, int],
        count: int = 100,
        end_time: Optional[datetime] = None,
    ) -> pd.DataFrame:
        candles = await self.get_candles(asset, timeframe, count, end_time)
        data = [
            {
                "timestamp": candle.timestamp,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            }
            for candle in candles
        ]
        df = pd.DataFrame(data)
        if not df.empty:
            df.set_index("timestamp", inplace=True)
            df.sort_index(inplace=True)
        return df

    async def check_order_result(self, order_id: str) -> Optional[OrderResult]:
        if order_id in self._active_orders:
            return self._active_orders[order_id]
        if order_id in self._order_results:
            return self._order_results[order_id]
        return None

    async def get_active_orders(self) -> List[OrderResult]:
        return list(self._active_orders.values())

    def add_event_callback(self, event: str, callback: EventCallback) -> None:
        self._event_callbacks[event].append(callback)

    def remove_event_callback(self, event: str, callback: EventCallback) -> None:
        if event in self._event_callbacks:
            try:
                self._event_callbacks[event].remove(callback)
            except ValueError:
                pass

    @property
    def is_connected(self) -> bool:
        if self._is_persistent and self._keep_alive_manager:
            return self._keep_alive_manager.is_connected
        return self._websocket.is_connected

    @property
    def connection_info(self) -> Any:
        if self._is_persistent and self._keep_alive_manager:
            return self._keep_alive_manager.connection_info
        return self._websocket.connection_info

    async def send_message(self, message: str) -> bool:
        try:
            if self._is_persistent and self._keep_alive_manager:
                sent = await self._keep_alive_manager.send_message(message)
                if sent:
                    self._connection_stats["messages_sent"] += 1
                return sent

            await self._websocket.send_message(message)
            self._connection_stats["messages_sent"] += 1
            return True
        except Exception as exc:
            logger.error(f"Failed to send message: {exc}")
            return False

    def get_connection_stats(self) -> Dict[str, Any]:
        stats = self._connection_stats.copy()
        if self._is_persistent and self._keep_alive_manager:
            stats.update(self._keep_alive_manager.get_stats())
        else:
            stats.update(
                {
                    "websocket_connected": self._websocket.is_connected,
                    "connection_info": self._websocket.connection_info,
                }
            )
        return stats

    # -------------------------------------------------------------------------
    # Public API - realtime assets / payouts
    # -------------------------------------------------------------------------

    async def request_assets_snapshot(self, timeout: float = 8.0) -> Dict[str, Dict[str, Any]]:
        """Força um refresh best-effort do snapshot de ativos via WebSocket."""
        if not self.is_connected:
            raise ConnectionError("Not connected to PocketOption")

        now = time.time()
        if self._last_assets_request_at and (now - self._last_assets_request_at) < self._asset_request_cooldown:
            return dict(self._asset_status_cache)

        self._last_assets_request_at = now

        messages = [
            '42["assets"]',
            '42["getAssets"]',
            '42["loadAssets"]',
        ]

        for message in messages:
            try:
                await self.send_message(message)
            except Exception:
                continue

        try:
            await self._wait_for_event("assets_received", timeout=timeout)
        except Exception:
            pass

        return dict(self._asset_status_cache)

    async def get_assets(
        self,
        force_refresh: bool = False,
        timeout: float = 8.0,
        only_open: Optional[bool] = None,
        min_payout: Optional[float] = None,
        asset_type: Optional[str] = None,
        search: Optional[str] = None,
        otc: Optional[bool] = None,
        sort_by: str = "asset",
        max_payout: Optional[float] = None,
        volatility: Optional[Union[str, float]] = None,
        trading_hours: Optional[Union[str, Dict[str, Any]]] = None,
        extra_filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        if force_refresh or not self._asset_status_cache or (
            self._payouts_cache_timestamp is not None
            and (time.time() - self._payouts_cache_timestamp) > self._payouts_cache_ttl
        ):
            try:
                await self.request_assets_snapshot(timeout=timeout)
            except Exception:
                pass

        records = {k: dict(v) for k, v in self._asset_status_cache.items()}

        # Compatibilidade: completa com catálogo estático mínimo
        for asset_name, asset_id in ASSETS.items():
            normalized = self._normalize_asset_name_for_payout(asset_name)
            records.setdefault(
                normalized,
                {
                    "asset": normalized,
                    "asset_id": asset_id,
                    "symbol": normalized,
                },
            )

        def match(record: Dict[str, Any]) -> bool:
            record_asset = str(record.get("asset", "")).lower()
            record_type = str(record.get("type", "")).lower()

            if only_open is not None and bool(record.get("is_open")) is not bool(only_open):
                return False

            payout = record.get("payout")
            if min_payout is not None and (payout is None or float(payout) < float(min_payout)):
                return False
            if max_payout is not None and (payout is None or float(payout) > float(max_payout)):
                return False

            if asset_type:
                wanted = str(asset_type).lower()
                if record_type != wanted and wanted not in record_asset:
                    return False

            if search:
                haystack = " ".join(
                    [
                        str(record.get("asset", "")),
                        str(record.get("name", "")),
                        str(record.get("symbol", "")),
                        str(record.get("display_name", "")),
                    ]
                ).lower()
                if str(search).lower() not in haystack:
                    return False

            if otc is not None:
                is_otc = (
                    str(record.get("asset", "")).lower().endswith("_otc")
                    or bool(record.get("is_otc"))
                    or record_type == "otc"
                )
                if is_otc is not bool(otc):
                    return False

            if volatility is not None:
                if not self._match_volatility_filter(record.get("volatility"), volatility):
                    return False

            if trading_hours is not None:
                if not self._match_trading_hours(record, trading_hours):
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

        filtered = {k: v for k, v in records.items() if match(v)}
        if sort_by:
            filtered = dict(
                sorted(
                    filtered.items(),
                    key=lambda item: (
                        str(item[1].get(sort_by, item[0])),
                        item[0],
                    ),
                )
            )
        return filtered

    async def get_all_assets(
        self,
        force_refresh: bool = False,
        timeout: float = 8.0,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Retorna a lista completa e atualizada de ativos conhecida pela sessão.
        Alimentado por WebSocket e compatível com a API atual.
        """
        return await self.get_assets(force_refresh=force_refresh, timeout=timeout)

    async def get_assets_realtime(
        self,
        force_refresh: bool = False,
        timeout: float = 8.0,
    ) -> Dict[str, Dict[str, Any]]:
        """Alias explícito para leitura realtime de ativos."""
        return await self.get_all_assets(force_refresh=force_refresh, timeout=timeout)

    async def filter_assets(
        self,
        filters: Optional[Dict[str, Any]] = None,
        predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
        **kwargs: Any,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Filtro avançado de ativos em tempo real.

        Compatibilidade:
        - filter_assets(predicate=..., only_open=True)
        - filter_assets({"asset_type": "forex", "min_payout": 80})
        """
        combined = dict(filters or {})
        combined.update(kwargs)

        translated = {
            "asset_type": combined.pop("asset_type", None),
            "min_payout": combined.pop("min_payout", None),
            "max_payout": combined.pop("max_payout", None),
            "only_open": combined.pop("only_open", combined.pop("is_open", None)),
            "search": combined.pop("search", None),
            "otc": combined.pop("otc", None),
            "sort_by": combined.pop("sort_by", "asset"),
            "volatility": combined.pop("volatility", None),
            "trading_hours": combined.pop("trading_hours", None),
            "extra_filters": combined if combined else None,
        }

        assets = await self.get_assets(**translated)
        if predicate is None:
            return assets

        return {name: data for name, data in assets.items() if predicate(data)}

    async def filter_assets_realtime(
        self,
        *,
        only_open: Optional[bool] = None,
        min_payout: Optional[float] = None,
        asset_type: Optional[str] = None,
        search: Optional[str] = None,
        otc: Optional[bool] = None,
        sort_by: str = "asset",
        predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
        force_refresh: bool = False,
        timeout: float = 8.0,
        max_payout: Optional[float] = None,
        volatility: Optional[Union[str, float]] = None,
        trading_hours: Optional[Union[str, Dict[str, Any]]] = None,
        **extra_filters: Any,
    ) -> Dict[str, Dict[str, Any]]:
        assets = await self.get_assets(
            force_refresh=force_refresh,
            timeout=timeout,
            only_open=only_open,
            min_payout=min_payout,
            max_payout=max_payout,
            asset_type=asset_type,
            search=search,
            otc=otc,
            sort_by=sort_by,
            volatility=volatility,
            trading_hours=trading_hours,
            extra_filters=extra_filters or None,
        )
        if predicate is None:
            return assets
        return {name: data for name, data in assets.items() if predicate(data)}

    async def get_open_assets(
        self,
        *,
        min_payout: Optional[float] = None,
        asset_type: Optional[str] = None,
        search: Optional[str] = None,
        otc: Optional[bool] = None,
        sort_by: str = "asset",
        force_refresh: bool = False,
        timeout: float = 8.0,
    ) -> Dict[str, Dict[str, Any]]:
        return await self.get_assets(
            force_refresh=force_refresh,
            timeout=timeout,
            only_open=True,
            min_payout=min_payout,
            asset_type=asset_type,
            search=search,
            otc=otc,
            sort_by=sort_by,
        )

    async def get_payouts(
        self,
        assets: Optional[List[str]] = None,
        force_refresh: bool = False,
        timeout: float = 8.0,
        only_open: bool = False,
    ) -> Dict[str, float]:
        selected_assets = {self._normalize_asset_name_for_payout(a) for a in assets} if assets else None
        records = await self.get_assets(
            force_refresh=force_refresh,
            timeout=timeout,
            only_open=only_open if only_open else None,
        )
        payouts: Dict[str, float] = {}
        for asset_name, record in records.items():
            if selected_assets and asset_name not in selected_assets:
                continue
            payout = record.get("payout")
            if payout is None:
                continue
            if only_open and not bool(record.get("is_open")):
                continue
            payouts[asset_name] = float(payout)
        return payouts

    async def get_current_payouts(
        self,
        assets: Optional[List[str]] = None,
        force_refresh: bool = False,
        timeout: float = 8.0,
        only_open: bool = True,
    ) -> Dict[str, float]:
        """Alias explícito para payouts em tempo real."""
        return await self.get_payouts(
            assets=assets,
            force_refresh=force_refresh,
            timeout=timeout,
            only_open=only_open,
        )

    async def get_assets_with_min_payout(
        self,
        assets: Optional[List[str]] = None,
        min_payout: float = 90.0,
        force_refresh: bool = False,
        timeout: float = 8.0,
        only_open: bool = False,
    ) -> Dict[str, float]:
        payouts = await self.get_payouts(
            assets=assets,
            force_refresh=force_refresh,
            timeout=timeout,
            only_open=only_open,
        )
        return {asset: payout for asset, payout in payouts.items() if float(payout) >= float(min_payout)}

    async def get_open_assets_with_min_payout(
        self,
        assets: Optional[List[str]] = None,
        min_payout: float = 90.0,
        force_refresh: bool = False,
        timeout: float = 10.0,
        validate_open: bool = True,
        timeframe: Union[str, int] = "1m",
    ) -> Dict[str, float]:
        payouts = await self.get_assets_with_min_payout(
            assets=assets,
            min_payout=min_payout,
            force_refresh=force_refresh,
            timeout=timeout,
            only_open=False,
        )
        if not validate_open:
            return payouts

        selected: Dict[str, float] = {}
        for asset, payout in payouts.items():
            if await self.is_asset_open(asset, timeframe=timeframe, timeout=timeout):
                selected[asset] = payout
        return selected

    def subscribe_assets(
        self,
        callback: EventCallback,
        only_open: Optional[bool] = None,
        min_payout: Optional[float] = None,
        asset_type: Optional[str] = None,
        search: Optional[str] = None,
        otc: Optional[bool] = None,
        volatility: Optional[Union[str, float]] = None,
        trading_hours: Optional[Union[str, Dict[str, Any]]] = None,
        **extra_filters: Any,
    ) -> EventCallback:
        async def _wrapped(_data: Any) -> None:
            records = await self.get_assets(
                only_open=only_open,
                min_payout=min_payout,
                asset_type=asset_type,
                search=search,
                otc=otc,
                volatility=volatility,
                trading_hours=trading_hours,
                extra_filters=extra_filters or None,
            )
            payload = {
                "event": "assets",
                "assets": records,
                "count": len(records),
                "updated_at": datetime.now(timezone.utc),
            }
            if asyncio.iscoroutinefunction(callback):
                await callback(payload)
            else:
                callback(payload)

        self.add_event_callback("assets_received", _wrapped)
        return _wrapped

    def unsubscribe_assets(self, callback: EventCallback) -> None:
        self.remove_event_callback("assets_received", callback)

    def subscribe_payouts(
        self,
        callback: EventCallback,
        *,
        assets: Optional[List[str]] = None,
        only_open: Optional[bool] = None,
        min_payout: Optional[float] = None,
        asset_type: Optional[str] = None,
        otc: Optional[bool] = None,
    ) -> EventCallback:
        selected_assets = {self._normalize_asset_name_for_payout(asset) for asset in assets} if assets else None

        async def _wrapped(_data: Any) -> None:
            payload: Dict[str, Dict[str, Any]] = {}
            for asset_name, record in self._asset_status_cache.items():
                payout = record.get("payout")
                if payout is None:
                    continue
                if selected_assets is not None and asset_name not in selected_assets:
                    continue
                if only_open is not None and bool(record.get("is_open")) is not bool(only_open):
                    continue
                if min_payout is not None and float(payout) < float(min_payout):
                    continue
                if asset_type and str(record.get("type", "")).lower() != str(asset_type).lower():
                    continue
                if otc is not None:
                    is_otc = (
                        str(record.get("asset", asset_name)).lower().endswith("_otc")
                        or str(record.get("type", "")).lower() == "otc"
                        or bool(record.get("is_otc"))
                    )
                    if is_otc is not bool(otc):
                        continue

                payload[asset_name] = {
                    "asset": asset_name,
                    "payout": float(payout),
                    "is_open": record.get("is_open"),
                    "type": record.get("type"),
                    "asset_id": record.get("asset_id"),
                    "raw": dict(record),
                }

            event_payload = {
                "event": "payouts",
                "count": len(payload),
                "assets": payload,
                "updated_at": datetime.now(timezone.utc),
            }

            if asyncio.iscoroutinefunction(callback):
                await callback(event_payload)
            else:
                callback(event_payload)

        self.add_event_callback("assets_received", _wrapped)
        return _wrapped

    def unsubscribe_payouts(self, callback: EventCallback) -> None:
        self.remove_event_callback("assets_received", callback)

    # -------------------------------------------------------------------------
    # Public API - realtime candles
    # -------------------------------------------------------------------------

    async def subscribe_candles(
        self,
        asset: str,
        timeframe: Union[str, int] = "1m",
        callback: Optional[EventCallback] = None,
        emit_history: bool = True,
        history_count: int = 50,
        queue_maxsize: int = 100,
    ) -> Union[str, AsyncGenerator[Dict[str, Any], None]]:
        """
        Assina candles em tempo real.

        Compatibilidade:
        - Se callback for informado: retorna subscription_key (str)
        - Se callback for None: retorna async generator
        """
        normalized_asset = self._normalize_asset_name_for_payout(asset)
        timeframe_seconds = self._normalize_timeframe(timeframe)
        key = self._make_candle_cache_key(normalized_asset, timeframe_seconds)

        self._candle_stream_subscriptions[key] = {
            "asset": normalized_asset,
            "timeframe": timeframe_seconds,
            "emit_history": emit_history,
            "history_count": history_count,
        }

        if callback is not None:
            async def _wrapped(data: Any) -> None:
                if str(data.get("asset")) != normalized_asset:
                    return
                if int(data.get("timeframe", 0)) != timeframe_seconds:
                    return
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)

            self.add_event_callback("candle_update", _wrapped)
            self._candle_stream_subscriptions[key]["callback"] = _wrapped

            await self._send_change_symbol(normalized_asset, timeframe_seconds)

            if emit_history:
                candles = await self.get_candles(
                    normalized_asset,
                    timeframe_seconds,
                    count=history_count,
                )
                await self._emit_event(
                    "candle_snapshot",
                    {
                        "asset": normalized_asset,
                        "timeframe": timeframe_seconds,
                        "candles": candles,
                        "count": len(candles),
                        "subscription_key": key,
                    },
                )

            return key

        queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
        queue_subscription = CandleQueueSubscription(
            key=key,
            asset=normalized_asset,
            timeframe=timeframe_seconds,
            queue=queue,
            emit_history=emit_history,
        )
        self._candle_queue_subscriptions[key].append(queue_subscription)

        await self._send_change_symbol(normalized_asset, timeframe_seconds)

        if emit_history:
            candles = await self.get_candles(
                normalized_asset,
                timeframe_seconds,
                count=history_count,
            )
            snapshot_payload = {
                "event": "candle_snapshot",
                "asset": normalized_asset,
                "timeframe": timeframe_seconds,
                "candles": candles,
                "count": len(candles),
                "subscription_key": key,
            }
            await self._queue_put_safe(queue, snapshot_payload)

        async def _generator() -> AsyncGenerator[Dict[str, Any], None]:
            try:
                while True:
                    item = await queue.get()
                    yield item
            finally:
                self._remove_queue_subscription(key, queue_subscription)

        return _generator()

    def unsubscribe_candles(self, subscription_key: str) -> None:
        sub = self._candle_stream_subscriptions.pop(subscription_key, None)
        if sub:
            callback = sub.get("callback")
            if callback is not None:
                self.remove_event_callback("candle_update", callback)

        self._candle_queue_subscriptions.pop(subscription_key, None)

    # -------------------------------------------------------------------------
    # Public API - broker state / raw exposure
    # -------------------------------------------------------------------------

    async def get_all_broker_state(
        self,
        *,
        force_refresh_assets: bool = False,
        timeout: float = 8.0,
    ) -> Dict[str, Any]:
        if force_refresh_assets:
            try:
                await self.request_assets_snapshot(timeout=timeout)
            except Exception:
                pass

        active_orders = list(self._active_orders.values())
        completed_orders = list(self._order_results.values())

        return {
            "connection": {
                "is_connected": self.is_connected,
                "is_persistent": self._is_persistent,
                "connection_info": self.connection_info,
                "stats": self.get_connection_stats(),
            },
            "account": {
                "balance": self._balance,
                "server_time": self._server_time,
                "is_demo": self.is_demo,
                "uid": self.uid,
                "platform": self.platform,
                "config": dict(self._account_config),
            },
            "assets": {
                "count": len(self._asset_status_cache),
                "items": dict(self._asset_status_cache),
                "payouts": dict(self._payouts_cache),
                "latest_timestamp": self._payouts_cache_timestamp,
            },
            "candles": {
                "subscriptions": dict(self._candle_stream_subscriptions),
                "latest": dict(self._latest_candles),
                "cache_keys": list(self._candles_cache.keys()),
                "cache": dict(self._candles_cache),
            },
            "orders": {
                "active_count": len(active_orders),
                "completed_count": len(completed_orders),
                "active": active_orders,
                "completed": completed_orders,
            },
            "limits": list(self._trade_limits),
            "news": list(self._news_cache),
            "raw_sections": dict(self._raw_state_sections),
            "unknown_events": list(self._last_unknown_events[-100:]),
        }

    async def get_broker_state(self, force_refresh_assets: bool = False, timeout: float = 8.0) -> Dict[str, Any]:
        """Alias curto e explícito."""
        return await self.get_all_broker_state(
            force_refresh_assets=force_refresh_assets,
            timeout=timeout,
        )

    def get_raw_state_sections(self) -> Dict[str, Any]:
        return dict(self._raw_state_sections)

    def get_unknown_events(self) -> List[Dict[str, Any]]:
        return list(self._last_unknown_events)

    # -------------------------------------------------------------------------
    # Helpers - auth / initialization
    # -------------------------------------------------------------------------

    def _format_session_message(self) -> str:
        auth_data = {
            "session": self.session_id,
            "isDemo": 1 if self.is_demo else 0,
            "uid": self.uid,
            "platform": self.platform,
        }
        if self.is_fast_history:
            auth_data["isFastHistory"] = True
        return f'42["auth",{json.dumps(auth_data)}]'

    def _parse_complete_ssid(self, ssid: str) -> None:
        try:
            json_start = ssid.find("{")
            json_end = ssid.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_part = ssid[json_start:json_end]
                data = json.loads(json_part)
                self.session_id = data.get("session", "")
                self._original_demo = bool(data.get("isDemo", 1))
                self.uid = data.get("uid", 0)
                self.platform = data.get("platform", 1)
                self._complete_ssid = None
                return
        except Exception as exc:
            logger.warning(f"Failed to parse SSID: {exc}")

        self.session_id = ssid
        self._complete_ssid = None

    async def _wait_for_authentication(self, timeout: float = 10.0) -> None:
        auth_received = False

        def on_auth(_data: Any) -> None:
            nonlocal auth_received
            auth_received = True

        self._websocket.add_event_handler("authenticated", on_auth)
        try:
            start_time = time.time()
            while not auth_received and (time.time() - start_time) < timeout:
                await asyncio.sleep(0.1)

            if not auth_received:
                raise AuthenticationError("Authentication timeout")
        finally:
            self._websocket.remove_event_handler("authenticated", on_auth)

    async def _initialize_data(self) -> None:
        logger.info("Initializing broker data...")
        await self._request_balance_update()
        await self._setup_time_sync()

        try:
            await self.get_payouts(force_refresh=True)
        except Exception:
            pass

        try:
            await self.request_assets_snapshot(timeout=5.0)
        except Exception:
            pass

    async def _request_balance_update(self) -> None:
        message = '42["getBalance"]'
        if self._is_persistent and self._keep_alive_manager:
            await self._keep_alive_manager.send_message(message)
        else:
            await self._websocket.send_message(message)

    async def _setup_time_sync(self) -> None:
        local_time = datetime.now(timezone.utc).timestamp()
        self._server_time = ServerTime(
            server_timestamp=local_time,
            local_timestamp=local_time,
            offset=0.0,
        )

    # -------------------------------------------------------------------------
    # Helpers - order flow
    # -------------------------------------------------------------------------

    def _validate_order_parameters(
        self,
        asset: str,
        amount: float,
        direction: OrderDirection,
        duration: int,
    ) -> None:
        normalized_asset = self._normalize_asset_name_for_payout(asset)
        if normalized_asset not in ASSETS and normalized_asset not in self._asset_status_cache:
            logger.debug(f"Asset {normalized_asset} not found in static map; allowing realtime asset symbol")

        if amount < API_LIMITS["min_order_amount"] or amount > API_LIMITS["max_order_amount"]:
            raise InvalidParameterError(
                f"Amount must be between {API_LIMITS['min_order_amount']} and {API_LIMITS['max_order_amount']}"
            )

        if duration < API_LIMITS["min_duration"] or duration > API_LIMITS["max_duration"]:
            raise InvalidParameterError(
                f"Duration must be between {API_LIMITS['min_duration']} and {API_LIMITS['max_duration']} seconds"
            )

        if direction not in (OrderDirection.CALL, OrderDirection.PUT):
            raise InvalidParameterError("Direction must be CALL or PUT")

    async def _send_order(self, order: Order) -> None:
        asset_name = self._normalize_asset_name_for_payout(order.asset)
        message = (
            f'42["openOrder",{{"asset":"{asset_name}","amount":{order.amount},'
            f'"action":"{order.direction.value}","isDemo":{1 if self.is_demo else 0},'
            f'"requestId":"{order.request_id}","optionType":100,"time":{order.duration}}}]'
        )

        if self._is_persistent and self._keep_alive_manager:
            await self._keep_alive_manager.send_message(message)
        else:
            await self._websocket.send_message(message)

        if self.enable_logging:
            logger.debug(f"Sent order: {message}")

    async def _wait_for_order_result(
        self,
        request_id: str,
        order: Order,
        timeout: float = 30.0,
    ) -> OrderResult:
        start_time = time.time()
        while time.time() - start_time < timeout:
            if request_id in self._active_orders:
                return self._active_orders[request_id]
            if request_id in self._order_results:
                return self._order_results[request_id]
            await asyncio.sleep(0.2)

        if request_id in self._active_orders:
            return self._active_orders[request_id]
        if request_id in self._order_results:
            return self._order_results[request_id]

        fallback_result = OrderResult(
            order_id=request_id,
            asset=order.asset,
            amount=order.amount,
            direction=order.direction,
            duration=order.duration,
            status=OrderStatus.ACTIVE,
            placed_at=datetime.now(),
            expires_at=datetime.now() + timedelta(seconds=order.duration),
            error_message="Timeout waiting for server confirmation",
        )
        self._active_orders[request_id] = fallback_result
        return fallback_result

    async def check_win(
        self,
        order_id: str,
        max_wait_time: float = 300.0,
    ) -> Optional[Dict[str, Any]]:
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            if order_id in self._order_results:
                result = self._order_results[order_id]
                return {
                    "result": (
                        "win"
                        if result.status == OrderStatus.WIN
                        else "loss"
                        if result.status == OrderStatus.LOSE
                        else "draw"
                    ),
                    "profit": result.profit if result.profit is not None else 0,
                    "order_id": order_id,
                    "completed": True,
                    "status": result.status.value,
                }

            if order_id in self._active_orders:
                active_order = self._active_orders[order_id]
                time_remaining = (active_order.expires_at - datetime.now()).total_seconds()
                if time_remaining <= 0:
                    logger.debug(f"Order {order_id} expired but result has not arrived yet")

            await asyncio.sleep(1.0)

        return {
            "result": "timeout",
            "order_id": order_id,
            "completed": False,
            "timeout": True,
        }

    # -------------------------------------------------------------------------
    # Helpers - candle request / parsing
    # -------------------------------------------------------------------------

    async def _request_candles(
        self,
        asset: str,
        timeframe: int,
        count: int,
        end_time: datetime,
    ) -> List[Candle]:
        _ = end_time  # preservado para compatibilidade futura

        message_data = ["changeSymbol", {"asset": str(asset), "period": timeframe}]
        message = f"42{json.dumps(message_data)}"

        if self.enable_logging:
            logger.debug(f"Requesting candles with changeSymbol: {message}")

        candle_future = asyncio.Future()
        request_id = self._make_candle_cache_key(asset, timeframe)

        if not hasattr(self, "_candle_requests"):
            self._candle_requests: Dict[str, asyncio.Future] = {}

        self._candle_requests[request_id] = candle_future

        if self._is_persistent and self._keep_alive_manager:
            await self._keep_alive_manager.send_message(message)
        else:
            await self._websocket.send_message(message)

        try:
            candles = await asyncio.wait_for(candle_future, timeout=10.0)
            if count and isinstance(candles, list) and len(candles) > count:
                return candles[-count:]
            return candles
        except asyncio.TimeoutError:
            logger.warning(f"Candle request timed out for {asset}")
            return []
        finally:
            if request_id in getattr(self, "_candle_requests", {}):
                del self._candle_requests[request_id]

    async def _send_change_symbol(self, asset: str, timeframe: int) -> None:
        message = f'42["changeSymbol",{{"asset":"{asset}","period":{timeframe}}}]'
        await self.send_message(message)

    def _parse_candles_data(
        self,
        candles_data: List[Any],
        asset: str,
        timeframe: int,
    ) -> List[Candle]:
        candles: List[Candle] = []
        try:
            if isinstance(candles_data, list):
                for candle_data in candles_data:
                    if isinstance(candle_data, dict):
                        high = float(candle_data.get("high", candle_data.get("max", 0)))
                        low = float(candle_data.get("low", candle_data.get("min", 0)))
                        candle = Candle(
                            timestamp=_server_ts_to_dt_utc(
                                candle_data.get("time", candle_data.get("timestamp", 0))
                            ),
                            open=float(candle_data.get("open", 0)),
                            high=max(high, low),
                            low=min(high, low),
                            close=float(candle_data.get("close", 0)),
                            volume=float(candle_data.get("volume", 0) or 0.0),
                            asset=asset,
                            timeframe=timeframe,
                        )
                        candles.append(candle)

                    elif isinstance(candle_data, (list, tuple)) and len(candle_data) >= 5:
                        raw_high = float(candle_data[2])
                        raw_low = float(candle_data[3])
                        actual_high = max(raw_high, raw_low)
                        actual_low = min(raw_high, raw_low)
                        candle = Candle(
                            timestamp=_server_ts_to_dt_utc(candle_data[0]),
                            open=float(candle_data[1]),
                            high=actual_high,
                            low=actual_low,
                            close=float(candle_data[4]),
                            volume=float(candle_data[5]) if len(candle_data) > 5 else 0.0,
                            asset=asset,
                            timeframe=timeframe,
                        )
                        candles.append(candle)
        except Exception as exc:
            if self.enable_logging:
                logger.error(f"Error parsing candles data: {exc}")

        candles.sort(key=lambda c: c.timestamp)
        return candles

    def _parse_stream_candles(
        self,
        stream_data: Dict[str, Any],
        asset: str,
        timeframe: int,
    ) -> List[Candle]:
        candles: List[Candle] = []
        try:
            candle_data = stream_data.get("data") or stream_data.get("candles") or []
            if isinstance(candle_data, list):
                for item in candle_data:
                    if isinstance(item, dict):
                        high = float(item.get("high", item.get("max", 0)))
                        low = float(item.get("low", item.get("min", 0)))
                        candle = Candle(
                            timestamp=_server_ts_to_dt_utc(
                                item.get("time", item.get("timestamp", 0))
                            ),
                            open=float(item.get("open", 0)),
                            high=max(high, low),
                            low=min(high, low),
                            close=float(item.get("close", 0)),
                            volume=float(item.get("volume", 0) or 0.0),
                            asset=asset,
                            timeframe=timeframe,
                        )
                        candles.append(candle)

                    elif isinstance(item, (list, tuple)) and len(item) >= 6:
                        # formato defensivo: [ts, open, close, high, low, volume]
                        high = float(item[3])
                        low = float(item[4])
                        candle = Candle(
                            timestamp=_server_ts_to_dt_utc(item[0]),
                            open=float(item[1]),
                            high=max(high, low),
                            low=min(high, low),
                            close=float(item[2]),
                            volume=float(item[5]) if len(item) > 5 else 0.0,
                            asset=asset,
                            timeframe=timeframe,
                        )
                        candles.append(candle)

            candles.sort(key=lambda x: x.timestamp)
        except Exception as exc:
            if self.enable_logging:
                logger.error(f"Error parsing stream candles: {exc}")

        return candles

    # -------------------------------------------------------------------------
    # Event ingestion / normalization
    # -------------------------------------------------------------------------

    async def _on_json_data(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return

        self._connection_stats["messages_received"] += 1
        self._capture_raw_section("json_data", data)
        self._extract_broker_state_sections(data)
        self._extract_payouts_from_any_payload(data)

        if "server_time" in data:
            self._update_server_time(data.get("server_time"))
        elif "timestamp" in data and data.get("_event") in {"server_time"}:
            self._update_server_time(data.get("timestamp"))

        if "candles" in data and isinstance(data["candles"], list):
            asset = data.get("asset")
            period = data.get("period")
            if asset and period and hasattr(self, "_candle_requests"):
                request_id = self._make_candle_cache_key(str(asset), int(period))
                if request_id in self._candle_requests and not self._candle_requests[request_id].done():
                    candles = self._parse_candles_data(data["candles"], str(asset), int(period))
                    self._candle_requests[request_id].set_result(candles)
                    if self.enable_logging:
                        logger.success(f"Candles data received: {len(candles)} candles for {asset}")
                    del self._candle_requests[request_id]
                    return

        if "requestId" in data and "asset" in data and "amount" in data:
            request_id = str(data["requestId"])
            if request_id not in self._active_orders and request_id not in self._order_results:
                order_result = OrderResult(
                    order_id=request_id,
                    asset=data.get("asset", "UNKNOWN"),
                    amount=float(data.get("amount", 0)),
                    direction=OrderDirection.CALL if data.get("command", 0) == 0 else OrderDirection.PUT,
                    duration=int(data.get("time", 60)),
                    status=OrderStatus.ACTIVE,
                    placed_at=datetime.now(),
                    expires_at=datetime.now() + timedelta(seconds=int(data.get("time", 60))),
                    profit=float(data.get("profit", 0)) if "profit" in data else None,
                    payout=float(data.get("payout", 0) or 0) if "payout" in data else None,
                )
                self._active_orders[request_id] = order_result
                await self._emit_event("order_opened", data)

        elif "deals" in data and isinstance(data["deals"], list):
            for deal in data["deals"]:
                if not isinstance(deal, dict) or "id" not in deal:
                    continue

                order_id = str(deal["id"])
                if order_id not in self._active_orders:
                    continue

                active_order = self._active_orders[order_id]
                profit = float(deal.get("profit", 0))
                if profit > 0:
                    status = OrderStatus.WIN
                elif profit < 0:
                    status = OrderStatus.LOSE
                else:
                    status = OrderStatus.DRAW

                result = OrderResult(
                    order_id=active_order.order_id,
                    asset=active_order.asset,
                    amount=active_order.amount,
                    direction=active_order.direction,
                    duration=active_order.duration,
                    status=status,
                    placed_at=active_order.placed_at,
                    expires_at=active_order.expires_at,
                    profit=profit,
                    payout=float(deal.get("payout", 0) or 0) if "payout" in deal else None,
                )
                self._order_results[order_id] = result
                del self._active_orders[order_id]
                await self._emit_event("order_closed", result)

    async def _on_raw_message(self, data: Dict[str, Any]) -> None:
        preview = str((data or {}).get("preview") or (data or {}).get("message") or "")
        if any(marker in preview.lower() for marker in ["assets", "payout", "profit", "otc", "news", "limit"]):
            logger.debug(f"[RAW MESSAGE] {preview[:500]}")

        self._raw_events_history.append(
            {
                "type": "raw_message",
                "data": data,
                "received_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        if len(self._raw_events_history) > 1000:
            self._raw_events_history = self._raw_events_history[-1000:]

        await self._emit_event("raw_message_received", data)

    async def _on_unknown_event(self, data: Dict[str, Any]) -> None:
        self._last_unknown_events.append(
            {
                "received_at": datetime.now(timezone.utc).isoformat(),
                "data": data,
            }
        )
        if len(self._last_unknown_events) > 500:
            self._last_unknown_events = self._last_unknown_events[-500:]

        self._capture_raw_section("unknown_events", self._last_unknown_events[-100:])

        payload = data.get("data") if isinstance(data, dict) else data
        self._extract_broker_state_sections(payload)

        await self._emit_event("unknown_event", data)

    async def _emit_event(self, event: str, data: Any) -> None:
        pending = self._pending_event_futures.get(event, [])
        for future in list(pending):
            if not future.done():
                future.set_result(data)

        if event in self._pending_event_futures:
            self._pending_event_futures[event] = [
                f for f in self._pending_event_futures[event] if not f.done()
            ]

        if event in self._event_callbacks:
            for callback in list(self._event_callbacks[event]):
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(data)
                    else:
                        callback(data)
                except Exception as exc:
                    if self.enable_logging:
                        logger.error(f"Error in event callback for {event}: {exc}")

    async def _on_authenticated(self, data: Dict[str, Any]) -> None:
        if self.enable_logging:
            logger.success("Successfully authenticated with PocketOption")
        self._connection_stats["successful_connections"] += 1
        await self._emit_event("authenticated", data)

    async def _on_balance_updated(self, data: Dict[str, Any]) -> None:
        try:
            balance = Balance(
                balance=float(data.get("balance", 0)),
                currency=data.get("currency", "USD"),
                is_demo=self.is_demo,
            )
            self._balance = balance
            self._account_config["currency"] = balance.currency
            self._account_config["is_demo"] = balance.is_demo
            await self._emit_event("balance_updated", balance)
        except Exception as exc:
            if self.enable_logging:
                logger.error(f"Failed to parse balance data: {exc}")

    async def _on_balance_data(self, data: Dict[str, Any]) -> None:
        await self._on_balance_updated(data)

    async def _on_order_opened(self, data: Dict[str, Any]) -> None:
        if self.enable_logging:
            logger.info(f"Order opened: {data}")
        await self._emit_event("order_opened", data)

    async def _on_order_closed(self, data: Union[Dict[str, Any], OrderResult]) -> None:
        if self.enable_logging:
            logger.info(f"Order closed: {data}")
        await self._emit_event("order_closed", data)

    async def _on_stream_update(self, data: Dict[str, Any]) -> None:
        if isinstance(data, dict) and data.get("_placeholder") is True:
            return

        self._extract_payouts_from_any_payload(data)
        self._extract_broker_state_sections(data)

        if "asset" in data and "period" in data and ("candles" in data or "data" in data):
            await self._handle_candles_stream(data)

        await self._emit_event("stream_update", data)

    async def _on_candles_received(self, data: Dict[str, Any]) -> None:
        if hasattr(self, "_candle_requests") and self._candle_requests:
            try:
                for request_id, future in list(self._candle_requests.items()):
                    if future.done():
                        continue
                    parts = request_id.split("_")
                    if len(parts) < 2:
                        continue
                    asset = "_".join(parts[:-1])
                    timeframe = int(parts[-1])
                    candles = self._parse_candles_data(data.get("candles", []), asset, timeframe)
                    future.set_result(candles)
                    break
            except Exception as exc:
                if self.enable_logging:
                    logger.error(f"Error processing candles data: {exc}")
                for _, future in list(self._candle_requests.items()):
                    if not future.done():
                        future.set_result([])
                        break

        await self._emit_event("candles_received", data)

    async def _on_history_update(self, data: Dict[str, Any]) -> None:
        if isinstance(data, dict):
            await self._handle_candles_stream(data)
        await self._emit_event("history_update", data)

    async def _on_disconnected(self, data: Dict[str, Any]) -> None:
        if self.enable_logging:
            logger.warning("Disconnected from PocketOption")
        await self._emit_event("disconnected", data)

    async def _handle_candles_stream(self, data: Dict[str, Any]) -> None:
        try:
            asset = self._normalize_asset_name_for_payout(data.get("asset"))
            period = int(data.get("period"))
            request_id = self._make_candle_cache_key(asset, period)

            candles = self._parse_stream_candles(data, asset, period)
            if not candles:
                return

            cache_key = self._make_candle_cache_key(asset, period)
            existing = self._candles_cache.get(cache_key, [])
            merged = self._merge_candle_series(existing, candles)

            self._candles_cache[cache_key] = merged
            latest = merged[-1]
            self._latest_candles[cache_key] = latest

            if hasattr(self, "_candle_requests") and request_id in self._candle_requests:
                future = self._candle_requests[request_id]
                if not future.done():
                    future.set_result(merged)
                del self._candle_requests[request_id]

            payload = {
                "event": "candle_update",
                "asset": asset,
                "timeframe": period,
                "candle": latest,
                "candles": merged,
                "count": len(merged),
                "subscription_key": cache_key,
                "updated_at": datetime.now(timezone.utc),
            }

            await self._emit_event("candle_update", payload)

            if cache_key in self._candle_queue_subscriptions:
                for sub in list(self._candle_queue_subscriptions[cache_key]):
                    await self._queue_put_safe(sub.queue, payload)

        except Exception as exc:
            if self.enable_logging:
                logger.error(f"Error handling candles stream: {exc}")

    async def _on_keep_alive_connected(self, data: Any = None) -> None:
        logger.info("Keep-alive connection established")
        await self._initialize_data()
        await self._emit_event("connected", data or {"persistent": True})

    async def _on_keep_alive_reconnected(self, data: Any = None) -> None:
        logger.info("Keep-alive connection re-established")
        await self._initialize_data()
        await self._restore_realtime_subscriptions()
        await self._emit_event("reconnected", data or {"persistent": True})

    async def _on_keep_alive_message(self, message: Any) -> None:
        raw_message = message.get("message") if isinstance(message, dict) else message
        if not isinstance(raw_message, str):
            return

        if raw_message.startswith("42"):
            try:
                data_str = raw_message[2:]
                data = json.loads(data_str)
                if isinstance(data, list) and len(data) >= 2:
                    await self._handle_json_message(data)
            except Exception as exc:
                logger.error(f"Error processing keep-alive message: {exc}")

        await self._emit_event("message_received", message)

    async def _attempt_reconnection(self, max_attempts: int = 3) -> bool:
        logger.info(f"Attempting reconnection (max {max_attempts} attempts)...")

        for attempt in range(max_attempts):
            try:
                logger.info(f"Reconnection attempt {attempt + 1}/{max_attempts}")

                if self._is_persistent and self._keep_alive_manager:
                    await self._keep_alive_manager.disconnect()
                else:
                    await self._websocket.disconnect()

                await asyncio.sleep(2 + attempt)

                success = await (
                    self._start_persistent_connection()
                    if self.persistent_connection
                    else self._start_regular_connection()
                )

                if success:
                    logger.info(f"Reconnection successful on attempt {attempt + 1}")
                    await self._restore_realtime_subscriptions()
                    await self._emit_event("reconnected", {})
                    return True

                logger.warning(f"Reconnection attempt {attempt + 1} failed")
            except Exception as exc:
                logger.error(f"Reconnection attempt {attempt + 1} failed with error: {exc}")

        logger.error(f"All {max_attempts} reconnection attempts failed")
        return False

    async def _handle_json_message(self, data: List[Any]) -> None:
        if not data or len(data) < 1:
            return

        event_type = data[0]
        event_data = data[1] if len(data) > 1 else {}

        self._extract_broker_state_sections(event_data)
        self._extract_payouts_from_any_payload(event_data)

        if event_type == "successauth":
            await self._emit_event("authenticated", event_data)
        elif event_type == "successupdateBalance":
            await self._emit_event("balance_updated", event_data)
        elif event_type == "successopenOrder":
            await self._emit_event("order_opened", event_data)
        elif event_type == "successcloseOrder":
            await self._emit_event("order_closed", event_data)
        elif event_type == "updateStream":
            await self._emit_event("stream_update", event_data)
        elif event_type == "loadHistoryPeriod":
            await self._emit_event("candles_received", event_data)
        elif event_type == "updateHistoryNew":
            await self._emit_event("history_update", event_data)
        elif event_type in {"assets", "assets_received"}:
            await self._on_assets_event(event_data)
        else:
            await self._emit_event("unknown_event", {"type": event_type, "data": event_data})

    # -------------------------------------------------------------------------
    # Asset / payout normalization
    # -------------------------------------------------------------------------

    def _normalize_payout_value(self, value: Any) -> float:
        try:
            payout = float(value)
        except Exception:
            return 0.0

        if 0 < payout <= 1:
            payout *= 100.0

        return round(payout, 2)

    def _normalize_asset_name_for_payout(self, value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return raw

        raw = raw.replace("#", "").strip()
        upper = raw.upper()

        if "/" in upper:
            upper = upper.replace("/", "")

        if " OTC" in upper:
            upper = upper.replace(" OTC", "_otc")
        elif upper.endswith("_OTC"):
            upper = upper[:-4] + "_otc"

        return upper

    def _normalize_open_value(self, value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {
                "open", "opened", "available", "active", "tradable", "enabled", "1", "true", "yes", "on"
            }:
                return True
            if normalized in {
                "closed", "close", "unavailable", "inactive", "disabled", "0", "false", "no", "off"
            }:
                return False
        return None

    def _update_asset_cache(
        self,
        asset_name: str,
        payout: Any = None,
        is_open: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        normalized_asset = self._normalize_asset_name_for_payout(asset_name)
        if not normalized_asset:
            return

        record = dict(self._asset_status_cache.get(normalized_asset, {}))
        record["asset"] = normalized_asset
        record.setdefault("symbol", normalized_asset)
        record["updated_at"] = datetime.now(timezone.utc)

        normalized_payout = None
        if payout is not None:
            normalized_payout = self._normalize_payout_value(payout)
            if normalized_payout > 0:
                self._payouts_cache[normalized_asset] = normalized_payout
                record["payout"] = normalized_payout

        normalized_open = self._normalize_open_value(is_open)
        if normalized_open is not None:
            record["is_open"] = normalized_open

        if metadata:
            for key, value in metadata.items():
                if value is not None:
                    record[key] = value

        record["is_otc"] = (
            str(record.get("asset", "")).lower().endswith("_otc")
            or str(record.get("type", "")).lower() == "otc"
        )

        self._asset_status_cache[normalized_asset] = record
        self._assets_last_update_ts = time.time()
        self._payouts_cache_timestamp = time.time()

    async def is_asset_open(
        self,
        asset: str,
        timeframe: Union[str, int] = "1m",
        timeout: float = 8.0,
        stale_factor: float = 3.0,
    ) -> bool:
        normalized_asset = self._normalize_asset_name_for_payout(asset)
        cached = self._asset_status_cache.get(normalized_asset, {})
        if "is_open" in cached:
            return bool(cached["is_open"])

        timeframe_seconds = self._normalize_timeframe(timeframe)

        try:
            candles = await asyncio.wait_for(
                self.get_candles(normalized_asset, timeframe, count=3),
                timeout=timeout,
            )
        except Exception:
            return False

        if not candles:
            return False

        latest = candles[-1]
        candle_ts = getattr(latest, "timestamp", None)
        if candle_ts is None:
            return True

        try:
            ts_value = candle_ts.timestamp()
        except Exception:
            try:
                ts_value = float(candle_ts)
            except Exception:
                ts_value = None

        if ts_value is None:
            return True

        age = time.time() - float(ts_value)
        is_open = age <= (max(60, timeframe_seconds) * stale_factor)
        self._update_asset_cache(
            normalized_asset,
            payout=self._payouts_cache.get(normalized_asset),
            is_open=is_open,
        )
        return is_open

    def _extract_payouts_from_any_payload(self, payload: Any) -> Dict[str, float]:
        payouts: Dict[str, float] = {}

        try:
            if isinstance(payload, dict):
                # mapa por id: {"123": {...}}
                for key, value in payload.items():
                    if not isinstance(value, dict):
                        continue

                    asset_name = None
                    payout_val = None

                    if isinstance(key, str) and key.isdigit():
                        asset_name = ASSET_IDS_TO_NAMES.get(int(key))

                    if not asset_name:
                        asset_name = value.get("symbol") or value.get("asset") or value.get("name")

                    payout_val = value.get("payout")
                    if payout_val is None:
                        payout_val = value.get("profit")
                    if payout_val is None:
                        payout_val = value.get("rate")

                    is_open = (
                        value.get("is_open")
                        if value.get("is_open") is not None
                        else value.get("open")
                    )
                    if is_open is None:
                        is_open = value.get("available")
                    if is_open is None:
                        is_open = value.get("active")

                    if asset_name and payout_val is not None:
                        normalized_asset = self._normalize_asset_name_for_payout(asset_name)
                        normalized = self._normalize_payout_value(payout_val)
                        if normalized > 0:
                            payouts[normalized_asset] = normalized
                            self._update_asset_cache(
                                normalized_asset,
                                payout=normalized,
                                is_open=is_open,
                                metadata={
                                    "asset_id": key if isinstance(key, str) else None,
                                    "type": value.get("type"),
                                    "display_name": value.get("name"),
                                    "name": value.get("name"),
                                    "symbol": value.get("symbol") or normalized_asset,
                                    "volatility": value.get("volatility"),
                                    "trading_hours": value.get("trading_hours"),
                                },
                            )

                # containers conhecidos: assets/data/items/list
                for container_key in ("assets", "data", "items", "list"):
                    seq = payload.get(container_key)
                    if not isinstance(seq, list):
                        continue

                    for item in seq:
                        if not isinstance(item, dict):
                            continue

                        asset_name = item.get("symbol") or item.get("asset") or item.get("name")
                        payout_val = item.get("payout")
                        if payout_val is None:
                            payout_val = item.get("profit")
                        if payout_val is None:
                            payout_val = item.get("rate")

                        is_open = item.get("is_open")
                        if is_open is None:
                            is_open = item.get("open")
                        if is_open is None:
                            is_open = item.get("available")
                        if is_open is None:
                            is_open = item.get("active")

                        if asset_name and payout_val is not None:
                            normalized_asset = self._normalize_asset_name_for_payout(asset_name)
                            normalized = self._normalize_payout_value(payout_val)
                            if normalized > 0:
                                payouts[normalized_asset] = normalized
                                self._update_asset_cache(
                                    normalized_asset,
                                    payout=normalized,
                                    is_open=is_open,
                                    metadata={
                                        "asset_id": item.get("id"),
                                        "type": item.get("type"),
                                        "display_name": item.get("name"),
                                        "name": item.get("name"),
                                        "symbol": item.get("symbol") or normalized_asset,
                                        "volatility": item.get("volatility"),
                                        "trading_hours": item.get("trading_hours"),
                                    },
                                )

            elif isinstance(payload, list):
                for item in payload:
                    if not isinstance(item, dict):
                        continue

                    asset_name = item.get("symbol") or item.get("asset") or item.get("name")
                    payout_val = item.get("payout")
                    if payout_val is None:
                        payout_val = item.get("profit")
                    if payout_val is None:
                        payout_val = item.get("rate")

                    is_open = item.get("is_open")
                    if is_open is None:
                        is_open = item.get("open")
                    if is_open is None:
                        is_open = item.get("available")
                    if is_open is None:
                        is_open = item.get("active")

                    if asset_name and payout_val is not None:
                        normalized_asset = self._normalize_asset_name_for_payout(asset_name)
                        normalized = self._normalize_payout_value(payout_val)
                        if normalized > 0:
                            payouts[normalized_asset] = normalized
                            self._update_asset_cache(
                                normalized_asset,
                                payout=normalized,
                                is_open=is_open,
                                metadata={
                                    "asset_id": item.get("id"),
                                    "type": item.get("type"),
                                    "display_name": item.get("name"),
                                    "name": item.get("name"),
                                    "symbol": item.get("symbol") or normalized_asset,
                                    "volatility": item.get("volatility"),
                                    "trading_hours": item.get("trading_hours"),
                                },
                            )
        except Exception as exc:
            if self.enable_logging:
                logger.debug(f"Unable to extract payouts from payload: {exc}")

        if payouts:
            self._payouts_cache.update(payouts)
            self._payouts_cache_timestamp = time.time()

        return payouts

    async def _on_assets_event(self, data: Any) -> None:
        self._capture_raw_section("assets_event", data)
        self._extract_broker_state_sections(data)
        self._extract_payouts_from_any_payload(data)
        await self._emit_event("assets_received", dict(self._asset_status_cache))

    async def _on_payout_update(self, data: Dict[str, Any]) -> None:
        try:
            asset_name = data.get("symbol") or data.get("name") or data.get("asset")
            payout_val = data.get("payout")
            is_open = data.get("is_open")

            if is_open is None:
                is_open = data.get("open")
            if is_open is None:
                is_open = data.get("available")

            if asset_name is None or payout_val is None:
                return

            normalized_asset = self._normalize_asset_name_for_payout(asset_name)
            normalized_payout = self._normalize_payout_value(payout_val)

            if normalized_payout <= 0:
                return

            self._update_asset_cache(
                normalized_asset,
                payout=normalized_payout,
                is_open=is_open,
                metadata={
                    "asset_id": data.get("id"),
                    "type": data.get("type"),
                    "display_name": data.get("name"),
                    "symbol": data.get("symbol") or normalized_asset,
                },
            )

            await self._emit_event("assets_received", dict(self._asset_status_cache))

        except Exception as exc:
            if self.enable_logging:
                logger.error(f"Error updating payout cache: {exc}")

    # -------------------------------------------------------------------------
    # Broker extra sections / unknown payload capture
    # -------------------------------------------------------------------------

    def _extract_broker_state_sections(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return

        # server time
        if "server_time" in payload:
            self._update_server_time(payload.get("server_time"))
        elif payload.get("_event") == "server_time" and "timestamp" in payload:
            self._update_server_time(payload.get("timestamp"))

        # account configuration
        account_keys = {"account", "account_id", "user_id", "locale", "timezone", "currency", "is_demo"}
        if account_keys.intersection(payload.keys()):
            self._account_config.update(payload)
            self._capture_raw_section("account_config", self._account_config)

        # trade limits
        if "limits" in payload and isinstance(payload["limits"], list):
            self._trade_limits = list(payload["limits"])
            self._capture_raw_section("trade_limits", self._trade_limits)
        elif "trade_limits" in payload and isinstance(payload["trade_limits"], list):
            self._trade_limits = list(payload["trade_limits"])
            self._capture_raw_section("trade_limits", self._trade_limits)

        # news
        if "news" in payload and isinstance(payload["news"], list):
            self._news_cache = list(payload["news"])
            self._capture_raw_section("news", self._news_cache)

        # OTC flags / status
        if "otc" in payload:
            self._capture_raw_section("otc_status", payload.get("otc"))

        event_name = str(payload.get("_event", "")).lower()
        if event_name:
            self._capture_raw_section(f"event:{event_name}", payload)

    def _capture_raw_section(self, key: str, value: Any) -> None:
        self._raw_state_sections[key] = value

    def _update_server_time(self, ts: Any) -> None:
        try:
            server_dt = _server_ts_to_dt_utc(ts)
            local_ts = datetime.now(timezone.utc).timestamp()
            server_ts = server_dt.timestamp()
            self._server_time = ServerTime(
                server_timestamp=server_ts,
                local_timestamp=local_ts,
                offset=server_ts - local_ts,
            )
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Utility helpers
    # -------------------------------------------------------------------------

    async def _wait_for_event(self, event_name: str, timeout: float = 10.0) -> Any:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_event_futures[event_name].append(future)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            if event_name in self._pending_event_futures:
                self._pending_event_futures[event_name] = [
                    f for f in self._pending_event_futures[event_name] if f is not future
                ]

    def _normalize_timeframe(self, timeframe: Union[str, int]) -> int:
        if isinstance(timeframe, int):
            return timeframe
        if timeframe not in TIMEFRAMES:
            raise InvalidParameterError(f"Invalid timeframe: {timeframe}")
        return int(TIMEFRAMES[timeframe])

    def _make_candle_cache_key(self, asset: str, timeframe: int) -> str:
        return f"{asset}_{int(timeframe)}"

    def _merge_candle_series(self, existing: List[Candle], incoming: List[Candle]) -> List[Candle]:
        merged_map: Dict[Tuple[str, int, float], Candle] = {}
        for candle in existing + incoming:
            ts = candle.timestamp.timestamp()
            merged_map[(candle.asset, candle.timeframe, ts)] = candle

        merged = list(merged_map.values())
        merged.sort(key=lambda c: c.timestamp)

        # evita crescimento infinito
        if len(merged) > 2000:
            merged = merged[-2000:]
        return merged

    async def _queue_put_safe(self, queue: asyncio.Queue, item: Any) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            try:
                _ = queue.get_nowait()
            except Exception:
                pass
            try:
                queue.put_nowait(item)
            except Exception:
                pass

    def _remove_queue_subscription(
        self,
        key: str,
        subscription: CandleQueueSubscription,
    ) -> None:
        current = self._candle_queue_subscriptions.get(key, [])
        current = [sub for sub in current if sub is not subscription]
        if current:
            self._candle_queue_subscriptions[key] = current
        else:
            self._candle_queue_subscriptions.pop(key, None)

    def _match_volatility_filter(
        self,
        record_value: Any,
        filter_value: Union[str, float],
    ) -> bool:
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

        # heurística simples para baixa/média/alta
        if wanted in {"baixa", "low"}:
            return numeric < 0.33
        if wanted in {"media", "média", "medium"}:
            return 0.33 <= numeric < 0.66
        if wanted in {"alta", "high"}:
            return numeric >= 0.66

        return str(record_value).strip().lower() == wanted

    def _match_trading_hours(
        self,
        record: Dict[str, Any],
        trading_hours_filter: Union[str, Dict[str, Any]],
    ) -> bool:
        record_hours = record.get("trading_hours")
        if trading_hours_filter is None:
            return True

        if record_hours is None:
            # fallback por is_open
            if isinstance(trading_hours_filter, str) and trading_hours_filter.lower() in {"open", "aberto"}:
                return bool(record.get("is_open"))
            return False

        if isinstance(trading_hours_filter, str):
            return trading_hours_filter.lower() in str(record_hours).lower()

        if isinstance(trading_hours_filter, dict):
            for key, value in trading_hours_filter.items():
                if isinstance(record_hours, dict):
                    if record_hours.get(key) != value:
                        return False
                else:
                    return False
            return True

        return False