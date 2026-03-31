"""
Autor: ByJhonesDev
Projeto: PocketOptionAPI – Biblioteca Python assíncrona de alto nível para integração com a corretora Pocket Option, com transporte WebSocket resiliente, orientado a eventos e preparado para payloads heterogêneos do broker.

Descrição:
Módulo responsável pela camada de transporte WebSocket da biblioteca. Implementa conexão, handshake Socket.IO, autenticação, envio e leitura contínua de mensagens, processamento de eventos brutos e normalizados, tratamento de payloads desconhecidos, batching opcional, estatísticas por endpoint e mecanismos auxiliares para suporte a reconexão e observabilidade do fluxo de comunicação.

O que ele faz:
- Estabelece conexão WebSocket com endpoints da Pocket Option
- Executa handshake inicial e autenticação via SSID
- Mantém loops de recepção e ping assíncronos
- Envia mensagens simples ou otimizadas com batching opcional
- Processa mensagens Socket.IO e payloads JSON heterogêneos
- Normaliza eventos de autenticação, saldo, ordens, candles, ativos e payouts
- Emite eventos brutos, normalizados e desconhecidos para consumidores externos
- Mantém informações de conexão e estado do transporte
- Registra estatísticas por endpoint para futura seleção otimizada de conexão
- Trata desconexões e sinaliza possibilidade de recuperação

Características:
- Cliente WebSocket assíncrono orientado a eventos
- Handshake manual compatível com Socket.IO usado pelo broker
- Suporte a payloads não padronizados e formatos mistos
- Emissão separada de eventos raw, json e normalizados
- Message batching opcional
- Pool lógico de estatísticas de conexão
- Estrutura preparada para reconexão e resiliência
- Compatibilidade com a camada superior da biblioteca

Requisitos:
- Python 3.10+
- asyncio
- websockets
- loguru
- Módulos internos do projeto:
  - constants
  - exceptions
  - models
"""

from __future__ import annotations

import asyncio
import json
import ssl
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Union

import websockets
from loguru import logger
from websockets.exceptions import ConnectionClosed
from websockets.legacy.client import WebSocketClientProtocol

from .constants import CONNECTION_SETTINGS, DEFAULT_HEADERS
from .exceptions import ConnectionError, WebSocketError
from .models import ConnectionInfo, ConnectionStatus, ServerTime

EventHandler = Callable[[Any], Union[None, Awaitable[None]]]


class MessageBatcher:
    """Agrupador simples de mensagens para uso opcional."""

    def __init__(self, batch_size: int = 10, batch_timeout: float = 0.1):
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.pending_messages: Deque[str] = deque()
        self._last_batch_time = time.time()
        self._batch_lock = asyncio.Lock()

    async def add_message(self, message: str) -> List[str]:
        async with self._batch_lock:
            self.pending_messages.append(message)
            current_time = time.time()

            if (
                len(self.pending_messages) >= self.batch_size
                or current_time - self._last_batch_time >= self.batch_timeout
            ):
                batch = list(self.pending_messages)
                self.pending_messages.clear()
                self._last_batch_time = current_time
                return batch

            return []

    async def flush_batch(self) -> List[str]:
        async with self._batch_lock:
            if not self.pending_messages:
                return []
            batch = list(self.pending_messages)
            self.pending_messages.clear()
            self._last_batch_time = time.time()
            return batch


class ConnectionPool:
    """Pool lógico de estatísticas por URL para futura seleção de melhor endpoint."""

    def __init__(self, max_connections: int = 3):
        self.max_connections = max_connections
        self.active_connections: Dict[str, WebSocketClientProtocol] = {}
        self.connection_stats: Dict[str, Dict[str, Any]] = {}
        self._pool_lock = asyncio.Lock()

    async def get_best_connection(self) -> Optional[str]:
        async with self._pool_lock:
            if not self.connection_stats:
                return None

            return min(
                self.connection_stats.keys(),
                key=lambda url: (
                    self.connection_stats[url].get("avg_response_time", float("inf")),
                    -self.connection_stats[url].get("success_rate", 0.0),
                ),
            )

    async def update_stats(self, url: str, response_time: float, success: bool) -> None:
        async with self._pool_lock:
            if url not in self.connection_stats:
                self.connection_stats[url] = {
                    "response_times": deque(maxlen=100),
                    "successes": 0,
                    "failures": 0,
                    "avg_response_time": 0.0,
                    "success_rate": 0.0,
                }

            stats = self.connection_stats[url]
            stats["response_times"].append(response_time)

            if success:
                stats["successes"] += 1
            else:
                stats["failures"] += 1

            response_times = stats["response_times"]
            if response_times:
                stats["avg_response_time"] = sum(response_times) / len(response_times)

            total_attempts = stats["successes"] + stats["failures"]
            if total_attempts > 0:
                stats["success_rate"] = stats["successes"] / total_attempts


class AsyncWebSocketClient:
    """Cliente WebSocket assíncrono principal da biblioteca."""

    def __init__(self):
        self.websocket: Optional[WebSocketClientProtocol] = None
        self.connection_info: Optional[ConnectionInfo] = None
        self.server_time: Optional[ServerTime] = None

        self._ping_task: Optional[asyncio.Task] = None
        self._receiver_task: Optional[asyncio.Task] = None
        self._running = False

        self._event_handlers: Dict[str, List[EventHandler]] = {}
        self._message_queue: asyncio.Queue = asyncio.Queue()

        self._reconnect_attempts = 0
        self._max_reconnect_attempts = CONNECTION_SETTINGS["max_reconnect_attempts"]

        self._message_batcher = MessageBatcher()
        self._connection_pool = ConnectionPool()
        self._rate_limiter = asyncio.Semaphore(10)
        self._message_cache: Dict[str, Any] = {}
        self._cache_ttl = 5.0

        self._last_raw_message_at: Optional[float] = None
        self._handshake_complete = False
        self._last_pong_at: Optional[float] = None

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def connect(self, urls: List[str], ssid: str) -> bool:
        for url in urls:
            try:
                logger.info(f"Trying websocket connection: {url}")

                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

                started_at = time.time()
                ws = await asyncio.wait_for(
                    websockets.connect(
                        url,
                        ssl=ssl_context,
                        extra_headers=DEFAULT_HEADERS,
                        ping_interval=None,
                        ping_timeout=None,
                        close_timeout=CONNECTION_SETTINGS["close_timeout"],
                    ),
                    timeout=10.0,
                )

                self.websocket = ws  # type: ignore[assignment]
                region = self._extract_region_from_url(url)

                self.connection_info = ConnectionInfo(
                    url=url,
                    region=region,
                    status=ConnectionStatus.CONNECTING,
                    connected_at=datetime.now(),
                    reconnect_attempts=self._reconnect_attempts,
                )

                await self._send_handshake(ssid)
                await self._start_background_tasks()

                elapsed = time.time() - started_at
                await self._connection_pool.update_stats(url, elapsed, True)

                self.connection_info = ConnectionInfo(
                    url=url,
                    region=region,
                    status=ConnectionStatus.CONNECTED,
                    connected_at=datetime.now(),
                    reconnect_attempts=self._reconnect_attempts,
                )

                self._running = True
                self._reconnect_attempts = 0
                logger.info(f"Connected successfully to region {region}")
                return True

            except Exception as exc:
                logger.warning(f"Connection failed for {url}: {exc}")
                try:
                    if self.websocket:
                        await self.websocket.close()
                except Exception:
                    pass
                self.websocket = None

                try:
                    await self._connection_pool.update_stats(url, 0.0, False)
                except Exception:
                    pass

                continue

        raise ConnectionError("Failed to connect to any WebSocket endpoint")

    async def disconnect(self) -> None:
        logger.info("Disconnecting websocket client...")
        self._running = False
        self._handshake_complete = False

        tasks = [self._ping_task, self._receiver_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

        if self.websocket:
            try:
                await self.websocket.close()
            finally:
                self.websocket = None

        if self.connection_info:
            self.connection_info = ConnectionInfo(
                url=self.connection_info.url,
                region=self.connection_info.region,
                status=ConnectionStatus.DISCONNECTED,
                connected_at=self.connection_info.connected_at,
                reconnect_attempts=self.connection_info.reconnect_attempts,
            )

    async def send_message(self, message: str) -> None:
        if not self.websocket or self.websocket.closed:
            raise WebSocketError("WebSocket is not connected")

        try:
            await self.websocket.send(message)
            logger.debug(f"Sent websocket message: {self._message_preview(message, 300)}")
        except Exception as exc:
            logger.error(f"Failed to send websocket message: {exc}")
            raise WebSocketError(f"Failed to send message: {exc}") from exc

    async def send_message_optimized(self, message: str) -> None:
        async with self._rate_limiter:
            if not self.websocket or self.websocket.closed:
                raise WebSocketError("WebSocket is not connected")

            try:
                start_time = time.time()
                batch = await self._message_batcher.add_message(message)

                if batch:
                    for msg in batch:
                        await self.websocket.send(msg)
                        logger.debug(f"Sent batched websocket message: {self._message_preview(msg, 200)}")

                response_time = time.time() - start_time
                if self.connection_info:
                    await self._connection_pool.update_stats(
                        self.connection_info.url,
                        response_time,
                        True,
                    )

            except Exception as exc:
                logger.error(f"Failed to send optimized websocket message: {exc}")
                if self.connection_info:
                    await self._connection_pool.update_stats(
                        self.connection_info.url,
                        0.0,
                        False,
                    )
                raise WebSocketError(f"Failed to send message: {exc}") from exc

    async def receive_messages(self) -> None:
        try:
            while self._running and self.websocket:
                try:
                    message = await asyncio.wait_for(
                        self.websocket.recv(),
                        timeout=CONNECTION_SETTINGS["message_timeout"],
                    )
                    await self._process_message(message)

                except asyncio.TimeoutError:
                    logger.debug("WebSocket receive timeout; continuing listener loop")
                    continue
                except ConnectionClosed:
                    logger.warning("WebSocket connection closed")
                    await self._handle_disconnect()
                    break

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Error in receive_messages: {exc}")
            await self._handle_disconnect()

    def add_event_handler(self, event: str, handler: EventHandler) -> None:
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        self._event_handlers[event].append(handler)

    def remove_event_handler(self, event: str, handler: EventHandler) -> None:
        if event in self._event_handlers:
            try:
                self._event_handlers[event].remove(handler)
            except ValueError:
                pass

    @property
    def is_connected(self) -> bool:
        return (
            self.websocket is not None
            and not self.websocket.closed
            and self.connection_info is not None
            and self.connection_info.status == ConnectionStatus.CONNECTED
        )

    # -------------------------------------------------------------------------
    # Handshake / background tasks
    # -------------------------------------------------------------------------

    async def _send_handshake(self, ssid: str) -> None:
        if not self.websocket:
            raise WebSocketError("WebSocket is not connected during handshake")

        try:
            logger.debug("Waiting for initial Socket.IO handshake packet...")
            initial_message = await asyncio.wait_for(self.websocket.recv(), timeout=10.0)
            initial_message = self._coerce_message_to_text(initial_message)
            await self._emit_raw_message(initial_message)

            logger.debug(f"Initial handshake packet: {self._message_preview(initial_message)}")

            if initial_message.startswith("0") and "sid" in initial_message:
                await self.websocket.send("40")
                logger.debug("Sent Socket.IO open packet: 40")

                conn_message = await asyncio.wait_for(self.websocket.recv(), timeout=10.0)
                conn_message = self._coerce_message_to_text(conn_message)
                await self._emit_raw_message(conn_message)

                logger.debug(f"Socket.IO connect response: {self._message_preview(conn_message)}")

                if conn_message.startswith("40"):
                    if self.connection_info:
                        self.connection_info = ConnectionInfo(
                            url=self.connection_info.url,
                            region=self.connection_info.region,
                            status=ConnectionStatus.AUTHENTICATING,
                            connected_at=self.connection_info.connected_at,
                            reconnect_attempts=self.connection_info.reconnect_attempts,
                        )

                    await self.websocket.send(ssid)
                    self._handshake_complete = True
                    logger.debug("SSID auth payload sent successfully")
                else:
                    raise WebSocketError(
                        f"Unexpected Socket.IO connect response: {self._message_preview(conn_message, 200)}"
                    )
            else:
                raise WebSocketError(
                    f"Unexpected initial handshake payload: {self._message_preview(initial_message, 200)}"
                )

        except asyncio.TimeoutError as exc:
            logger.error("Handshake timeout")
            raise WebSocketError("Timeout during websocket handshake") from exc
        except Exception:
            raise

    async def _start_background_tasks(self) -> None:
        self._running = True
        self._ping_task = asyncio.create_task(self._ping_loop())
        self._receiver_task = asyncio.create_task(self.receive_messages())

    async def _ping_loop(self) -> None:
        while self._running and self.websocket:
            try:
                await asyncio.sleep(CONNECTION_SETTINGS["ping_interval"])

                if self.websocket and not self.websocket.closed:
                    await self.send_message('42["ps"]')

                    if self.connection_info:
                        self.connection_info = ConnectionInfo(
                            url=self.connection_info.url,
                            region=self.connection_info.region,
                            status=self.connection_info.status,
                            connected_at=self.connection_info.connected_at,
                            last_ping=datetime.now(),
                            reconnect_attempts=self.connection_info.reconnect_attempts,
                        )

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"Ping loop failed: {exc}")
                break

    # -------------------------------------------------------------------------
    # Message processing
    # -------------------------------------------------------------------------

    async def _process_message(self, message: Any) -> None:
        try:
            text_message = self._coerce_message_to_text(message)
            self._last_raw_message_at = time.time()

            await self._emit_raw_message(text_message)
            logger.debug(f"Received websocket message: {self._message_preview(text_message, 400)}")

            # Socket.IO ping from server
            if text_message == "2":
                await self.send_message("3")
                self._last_pong_at = time.time()
                return

            # Sometimes server sends open packet again
            if text_message.startswith("0") and "sid" in text_message:
                await self.send_message("40")
                return

            # Socket.IO connected
            if text_message.startswith("40"):
                await self._emit_event("connected", {})
                return

            # Generic 451-[...] wrapper
            if text_message.startswith("451-["):
                json_part = text_message.split("-", 1)[1]
                try:
                    data = json.loads(json_part)
                    await self._handle_json_like_payload(data, raw_message=text_message)
                except Exception as exc:
                    logger.debug(f"Could not parse 451 payload: {exc}")
                return

            # Some PocketOption payloads arrive as [[5,...], [5,...]]
            if text_message.startswith("[[5,"):
                await self._handle_payout_message(text_message)
                return

            # Raw JSON object/array outside 42
            if text_message.startswith("{") or text_message.startswith("["):
                try:
                    data = json.loads(text_message)
                    await self._handle_json_like_payload(data, raw_message=text_message)
                    return
                except json.JSONDecodeError:
                    pass

            # Main socket event payload 42[...]
            if text_message.startswith("42"):
                if "NotAuthorized" in text_message:
                    logger.error("PocketOption auth failed: invalid SSID")
                    await self._emit_event("auth_error", {"message": "SSID inválido"})
                    return

                try:
                    data = json.loads(text_message[2:])
                    await self._handle_json_like_payload(data, raw_message=text_message)
                except Exception as exc:
                    logger.debug(f"Could not parse 42 payload as JSON: {exc}")
                return

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Error while processing websocket message: {exc}")

    async def _handle_json_like_payload(self, data: Any, raw_message: Optional[str] = None) -> None:
        if isinstance(data, list):
            # Standard socket event format: ["event", payload]
            if len(data) >= 1 and isinstance(data[0], str):
                await self._handle_json_message(data, raw_message=raw_message)
                return

            # Array payload that may contain multiple [5, ...] entries or mixed chunks
            if self._looks_like_payout_batch(data):
                await self._handle_payout_batch(data)
                return

            await self._emit_event(
                "json_data",
                {
                    "_event": "list_payload",
                    "payload": data,
                    "_raw_message": raw_message,
                },
            )
            return

        if isinstance(data, dict):
            payload = dict(data)
            if raw_message is not None:
                payload.setdefault("_raw_message", raw_message)

            await self._emit_event("json_data", payload)

            if "balance" in payload:
                balance_data = {
                    "balance": payload.get("balance"),
                    "currency": payload.get("currency", "USD"),
                    "is_demo": bool(payload.get("isDemo", payload.get("is_demo", 1))),
                    "uid": payload.get("uid"),
                }
                await self._emit_event("balance_data", balance_data)
                await self._emit_event("balance_updated", balance_data)

            if self._looks_like_assets_payload(payload):
                await self._emit_event("assets", payload)
                await self._emit_event("assets_received", payload)

            if self._looks_like_single_payout_payload(payload):
                await self._emit_event("payout_update", self._normalize_single_payout_payload(payload))

            return

        await self._emit_event(
            "unknown_event",
            {
                "type": "unhandled_json_payload",
                "data": data,
                "raw_message": raw_message,
            },
        )

    async def _handle_json_message(self, data: List[Any], raw_message: Optional[str] = None) -> None:
        if not data:
            return

        event_type = data[0]
        event_data = data[1] if len(data) > 1 else {}

        if isinstance(event_data, dict):
            payload = dict(event_data)
            payload.setdefault("_event", event_type)
            if raw_message is not None:
                payload.setdefault("_raw_message", raw_message)
            await self._emit_event("json_data", payload)
        else:
            await self._emit_event(
                "json_data",
                {
                    "_event": event_type,
                    "payload": event_data,
                    "_raw_message": raw_message,
                },
            )

        if event_type in {"successauth", "authenticated", "auth"}:
            await self._emit_event("authenticated", event_data)
            return

        if event_type in {"successupdateBalance", "balance_updated", "balance_data", "getBalance"}:
            await self._emit_event("balance_updated", event_data)
            await self._emit_event("balance_data", event_data)
            return

        if event_type in {"successopenOrder", "order_opened", "openOrder"}:
            await self._emit_event("order_opened", event_data)
            return

        if event_type in {"successcloseOrder", "order_closed", "closeOrder"}:
            await self._emit_event("order_closed", event_data)
            return

        if event_type in {"updateStream", "stream_update"}:
            await self._emit_event("stream_update", event_data)
            return

        if event_type in {"loadHistoryPeriod", "candles_received"}:
            await self._emit_event("candles_received", event_data)
            return

        if event_type in {"updateHistoryNew", "history_update"}:
            await self._emit_event("history_update", event_data)
            return

        if event_type in {"assets", "assets_received", "getAssets", "loadAssets"}:
            await self._emit_event("assets", event_data)
            await self._emit_event("assets_received", event_data)
            return

        # payload desconhecido, mas preservado
        await self._emit_event(
            "unknown_event",
            {
                "type": event_type,
                "data": event_data,
                "raw_message": raw_message,
            },
        )

    async def _handle_payout_message(self, message: str) -> None:
        try:
            parsed = json.loads(message)
            await self._handle_payout_batch(parsed)
        except json.JSONDecodeError as exc:
            logger.error(f"Failed to decode payout message JSON: {exc}")
        except Exception as exc:
            logger.error(f"Unexpected error while handling payout message: {exc}")

    async def _handle_payout_batch(self, parsed: Any) -> None:
        if not isinstance(parsed, list):
            return

        for item in parsed:
            normalized = self._normalize_payout_entry(item)
            if normalized is not None:
                await self._emit_event("payout_update", normalized)

    def _normalize_payout_entry(self, item: Any) -> Optional[Dict[str, Any]]:
        try:
            if not isinstance(item, list) or len(item) < 2:
                return None

            if item[0] != 5:
                return None

            inner = item[1]
            if not isinstance(inner, list) or len(inner) < 6:
                return None

            return {
                "id": inner[0],
                "symbol": inner[1] if len(inner) > 1 else None,
                "name": inner[2] if len(inner) > 2 else None,
                "type": inner[3] if len(inner) > 3 else None,
                "is_open": inner[4] if len(inner) > 4 else None,
                "payout": inner[5] if len(inner) > 5 else None,
                "raw": inner,
            }
        except Exception:
            return None

    # -------------------------------------------------------------------------
    # Heuristics for unknown payloads
    # -------------------------------------------------------------------------

    def _looks_like_assets_payload(self, payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False

        if any(key in payload for key in ("assets", "asset", "symbols", "instruments")):
            return True

        if "data" in payload and isinstance(payload["data"], list):
            sample = payload["data"][0] if payload["data"] else None
            if isinstance(sample, dict) and any(k in sample for k in ("symbol", "asset", "name", "payout")):
                return True

        return False

    def _looks_like_single_payout_payload(self, payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False

        has_asset = any(key in payload for key in ("symbol", "asset", "name"))
        has_payout = any(key in payload for key in ("payout", "profit", "rate"))
        return has_asset and has_payout

    def _normalize_single_payout_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": payload.get("id"),
            "symbol": payload.get("symbol") or payload.get("asset"),
            "name": payload.get("name"),
            "type": payload.get("type"),
            "is_open": payload.get("is_open", payload.get("open", payload.get("available"))),
            "payout": payload.get("payout", payload.get("profit", payload.get("rate"))),
            "raw": payload,
        }

    def _looks_like_payout_batch(self, data: List[Any]) -> bool:
        if not isinstance(data, list) or not data:
            return False

        first = data[0]
        return (
            isinstance(first, list)
            and len(first) >= 2
            and first[0] == 5
        )

    # -------------------------------------------------------------------------
    # Raw event emission
    # -------------------------------------------------------------------------

    async def _emit_raw_message(self, message: str) -> None:
        await self._emit_event(
            "raw_message",
            {
                "message": message,
                "preview": self._message_preview(message),
                "received_at": datetime.utcnow().isoformat(),
            },
        )

    async def _emit_event(self, event: str, data: Any) -> None:
        if event not in self._event_handlers:
            return

        for handler in list(self._event_handlers[event]):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as exc:
                logger.error(f"Error in event handler for {event}: {exc}")

    # -------------------------------------------------------------------------
    # Disconnect / recovery helpers
    # -------------------------------------------------------------------------

    async def _handle_disconnect(self) -> None:
        if self.connection_info:
            self.connection_info = ConnectionInfo(
                url=self.connection_info.url,
                region=self.connection_info.region,
                status=ConnectionStatus.DISCONNECTED,
                connected_at=self.connection_info.connected_at,
                last_ping=self.connection_info.last_ping,
                reconnect_attempts=self.connection_info.reconnect_attempts,
            )

        await self._emit_event("disconnected", {})

        if self._reconnect_attempts < self._max_reconnect_attempts:
            self._reconnect_attempts += 1
            logger.info(
                f"WebSocket disconnected. Reconnect monitor can retry "
                f"{self._reconnect_attempts}/{self._max_reconnect_attempts}"
            )
            await asyncio.sleep(CONNECTION_SETTINGS["reconnect_delay"])

    # -------------------------------------------------------------------------
    # Utility helpers
    # -------------------------------------------------------------------------

    def _coerce_message_to_text(self, message: Any) -> str:
        if isinstance(message, memoryview):
            return bytes(message).decode("utf-8", errors="ignore")
        if isinstance(message, (bytes, bytearray)):
            return message.decode("utf-8", errors="ignore")
        return str(message)

    def _message_preview(self, message: Any, limit: int = 800) -> str:
        try:
            text = str(message)
        except Exception:
            text = repr(message)

        text = text.replace("\n", " ").replace("\r", " ")
        if len(text) > limit:
            return text[:limit] + "..."
        return text

    def _extract_region_from_url(self, url: str) -> str:
        try:
            parts = url.split("//", 1)[1].split(".", 1)[0]
            if "api-" in parts:
                return parts.replace("api-", "").upper()
            if "demo" in parts:
                return "DEMO"
            return "UNKNOWN"
        except Exception:
            return "UNKNOWN"