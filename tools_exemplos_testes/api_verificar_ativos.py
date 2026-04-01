"""
Autor: ByJhonesDev
Projeto: PocketOptionAPI – Monitor assíncrono de saldo e ativos da Pocket Option com bootstrap local da biblioteca, coleta em tempo real via WebSocket e exibição interativa em terminal.

Descrição:
Módulo executável responsável por autenticar na Pocket Option usando SSID, carregar dinamicamente os módulos locais da biblioteca, conectar via WebSocket, capturar saldo e ativos em tempo real, reconstruir snapshots de mercado a partir dos eventos recebidos e apresentar os dados no terminal com filtros de payout e separação entre mercado Regular e OTC.

O que ele faz:
- Carrega credenciais e parâmetros via .env
- Normaliza o modo de conta (REAL ou DEMOSTRAÇÃO)
- Extrai e valida automaticamente o valor de session a partir de SSID completo ou payload Socket.IO
- Faz bootstrap interno dos módulos locais do projeto para compatibilidade com imports relativos e absolutos
- Estabelece conexão assíncrona com a Pocket Option com timeout e tratamento de falhas
- Obtém saldo com fallback resiliente via eventos e estado interno do client
- Coleta ativos em tempo real a partir de eventos como payout_update e raw_message
- Reconstrói e mantém cache local de ativos mesmo quando o snapshot tradicional falha ou vem incompleto
- Normaliza ativos, payout e status de abertura dos instrumentos
- Filtra ativos por payout mínimo configurável
- Classifica automaticamente os ativos entre mercado Regular e OTC
- Exibe painel rico no terminal com saldo, status da conexão, região e tabelas de ativos
- Suporta execução única ou atualização contínua em intervalo configurável

Características:
- Arquitetura assíncrona baseada em asyncio
- Compatibilidade com bibliotecas locais carregadas dinamicamente
- Estratégia resiliente para captura de saldo e ativos
- Coleta orientada a eventos WebSocket
- Filtro operacional por payout mínimo
- Interface de terminal rica com rich
- Suporte a refresh em tempo real
- Tratamento de erros de autenticação, conexão e API

Requisitos:
- Python 3.10+
- asyncio
- python-dotenv
- rich
- Módulos locais do projeto:
  - client
  - exceptions
  - models
  - constants
  - websocket_client

Observações:
- Requer SSID válido da Pocket Option
- Depende da estrutura interna e dos eventos emitidos pela corretora, sujeitos a mudança
- Não executa ordens nem manipula login/senha diretamente
- Foi projetado para monitoramento, inspeção operacional e servir de base para futuras automações
"""

from __future__ import annotations
import argparse
import asyncio
import importlib.util
import json
import os
import re
import sys
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv

try:
    from rich import box
    from rich.align import Align
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except Exception as exc:
    raise SystemExit("Dependência ausente: rich. Instale com: pip install rich") from exc

console = Console()


# -----------------------------------------------------------------------------
# Bootstrap dos módulos locais
# -----------------------------------------------------------------------------

def _load_module_as_package(module_name: str, file_path: Path, package_name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        module_name,
        file_path,
        submodule_search_locations=[str(file_path.parent)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Não foi possível carregar o módulo: {file_path}")

    module = importlib.util.module_from_spec(spec)
    module.__package__ = package_name
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def bootstrap_local_package(base_dir: Path) -> Dict[str, types.ModuleType]:
    package_name = "po_localpkg"

    if package_name not in sys.modules:
        pkg = types.ModuleType(package_name)
        pkg.__path__ = [str(base_dir)]  # type: ignore[attr-defined]
        sys.modules[package_name] = pkg

    ordered_modules = [
        "constants.py",
        "exceptions.py",
        "models.py",
        "monitoring.py",
        "utils.py",
        "websocket_client.py",
        "config.py",
        "connection_keep_alive.py",
        "client.py",
        "connection_monitor.py",
    ]

    loaded: Dict[str, types.ModuleType] = {}
    for filename in ordered_modules:
        file_path = base_dir / filename
        if not file_path.exists():
            continue

        module_basename = file_path.stem
        full_name = f"{package_name}.{module_basename}"
        module = _load_module_as_package(full_name, file_path, package_name)

        # Compatibilidade com imports absolutos locais tipo: from client import ...
        sys.modules[module_basename] = module
        loaded[module_basename] = module

    required = {"client", "exceptions", "models", "constants", "websocket_client"}
    missing = sorted(required - set(loaded))
    if missing:
        raise ImportError("Arquivos essenciais ausentes: " + ", ".join(missing))

    return loaded


# -----------------------------------------------------------------------------
# Configuração
# -----------------------------------------------------------------------------

@dataclass
class AppConfig:
    account_mode: str
    is_demo: bool
    raw_ssid: str
    connect_timeout: float
    min_payout: float
    refresh_enabled: bool
    refresh_seconds: int


class SimpleBalance:
    def __init__(self, balance: float, currency: str = "USD", is_demo: bool = True):
        self.balance = balance
        self.currency = currency
        self.is_demo = is_demo


class AssetStreamCollector:
    """
    Monta cache de ativos a partir dos eventos reais recebidos no websocket.
    Isso resolve o caso em que a biblioteca não preenche get_assets(), mas o
    stream [[5, ...]] já traz payout e status dos pares.
    """

    def __init__(self) -> None:
        self.assets: Dict[str, Dict[str, Any]] = {}
        self.last_update: float = 0.0

    def merge_snapshot(self, snapshot: Dict[str, Dict[str, Any]]) -> None:
        for name, record in snapshot.items():
            merged = dict(record)
            merged.setdefault("asset", name)
            self._upsert(merged)

    def handle_payout_event(self, data: Any) -> None:
        if not isinstance(data, dict):
            return

        record = {
            "asset": data.get("symbol") or data.get("asset") or data.get("name"),
            "symbol": data.get("symbol") or data.get("asset"),
            "display_name": data.get("name"),
            "type": data.get("type"),
            "is_open": self._normalize_open(data.get("is_open")),
            "payout": self._normalize_payout(data.get("payout")),
            "raw": data,
        }
        self._upsert(record)

    def handle_raw_message(self, raw_data: Any) -> None:
        if not isinstance(raw_data, dict):
            return
        message = raw_data.get("message")
        if not isinstance(message, str):
            return

        message = message.strip()
        if not message:
            return

        if message.startswith("[["):
            self._parse_stream_array(message)
            return

        if message.startswith("451-"):
            maybe_json = message.split("-", 1)[1]
            if maybe_json.startswith("["):
                try:
                    parsed = json.loads(maybe_json)
                    if isinstance(parsed, list) and len(parsed) >= 2:
                        event_name = parsed[0]
                        payload = parsed[1]
                        if event_name in {"assets", "assets_received", "updateAssets"}:
                            self._parse_generic_payload(payload)
                except Exception:
                    return
            return

        if message.startswith("{") or message.startswith("["):
            try:
                parsed = json.loads(message)
                self._parse_generic_payload(parsed)
            except Exception:
                return

    def get_assets(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in self.assets.items()}

    def wait_count(self) -> int:
        return len(self.assets)

    def _parse_stream_array(self, text: str) -> None:
        try:
            parsed = json.loads(text)
        except Exception:
            return

        if not isinstance(parsed, list):
            return

        for item in parsed:
            if not isinstance(item, list) or len(item) < 6:
                continue

            # Formato observado no log:
            # [170, "#AAPL_otc", "Apple OTC", "stock", 3, 92, ..., true, [...], ...]
            if not isinstance(item[1], str):
                continue

            is_open = None
            for idx in (14, 10, 9, 4):
                if idx < len(item) and isinstance(item[idx], bool):
                    is_open = item[idx]
                    break

            asset = self._normalize_asset(item[1])
            record = {
                "asset": asset,
                "symbol": asset,
                "display_name": item[2] if len(item) > 2 else asset,
                "type": item[3] if len(item) > 3 else None,
                "is_open": is_open,
                "payout": self._normalize_payout(item[5] if len(item) > 5 else None),
                "raw": item,
            }
            self._upsert(record)

    def _parse_generic_payload(self, payload: Any) -> None:
        if isinstance(payload, dict):
            if self._looks_like_asset_record(payload):
                self._upsert(payload)
                return

            for key in ("assets", "data", "symbols", "instruments"):
                value = payload.get(key)
                if isinstance(value, list):
                    for item in value:
                        self._parse_generic_payload(item)
                elif isinstance(value, dict):
                    for _, item in value.items():
                        self._parse_generic_payload(item)
            return

        if isinstance(payload, list):
            for item in payload:
                self._parse_generic_payload(item)

    def _looks_like_asset_record(self, payload: Dict[str, Any]) -> bool:
        has_name = any(k in payload for k in ("asset", "symbol", "name"))
        has_payout = any(k in payload for k in ("payout", "profit", "rate"))
        return has_name and has_payout

    def _upsert(self, record: Dict[str, Any]) -> None:
        asset = self._normalize_asset(record.get("asset") or record.get("symbol") or record.get("name"))
        if not asset:
            return

        current = dict(self.assets.get(asset, {}))
        current["asset"] = asset
        current.setdefault("symbol", asset)
        current["display_name"] = safe_text(record.get("display_name") or record.get("name") or current.get("display_name"), asset)

        payout = self._normalize_payout(
            record.get("payout", record.get("profit", record.get("rate")))
        )
        if payout is not None:
            current["payout"] = payout

        is_open = self._normalize_open(
            record.get("is_open", record.get("open", record.get("available", record.get("active"))))
        )
        if is_open is not None:
            current["is_open"] = is_open

        if record.get("type") is not None:
            current["type"] = record.get("type")

        current["is_otc"] = asset.lower().endswith("_otc") or str(current.get("type", "")).lower() == "otc"
        current["updated_at"] = time.time()
        current["raw"] = record.get("raw", record)

        self.assets[asset] = current
        self.last_update = time.time()

    @staticmethod
    def _normalize_asset(value: Any) -> str:
        raw = str(value or "").strip().replace("#", "")
        if not raw:
            return ""
        raw = raw.replace("/", "")
        upper = raw.upper()
        if upper.endswith("_OTC"):
            return upper[:-4] + "_otc"
        if upper.endswith(" OTC"):
            return upper[:-4] + "_otc"
        return upper

    @staticmethod
    def _normalize_payout(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            payout = float(value)
        except Exception:
            return None
        if 0 < payout <= 1:
            payout *= 100.0
        return round(payout, 2)

    @staticmethod
    def _normalize_open(value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            norm = value.strip().lower()
            if norm in {"open", "opened", "available", "active", "tradable", "enabled", "1", "true", "yes", "on"}:
                return True
            if norm in {"closed", "close", "unavailable", "inactive", "disabled", "0", "false", "no", "off"}:
                return False
        return None


def normalize_account_mode(value: Optional[str]) -> Tuple[str, bool]:
    raw = (value or "DEMOSTRAÇÃO").strip().upper()

    aliases = {
        "DEMOSTRAÇÃO": "DEMOSTRAÇÃO",
        "DEMONSTRACAO": "DEMOSTRAÇÃO",
        "DEMO": "DEMOSTRAÇÃO",
        "PRACTICE": "DEMOSTRAÇÃO",   # compatibilidade
        "REAL": "REAL",
        "LIVE": "REAL",
    }

    mode = aliases.get(raw)
    if not mode:
        raise ValueError("PO_ACCOUNT_MODE inválido. Use REAL ou DEMOSTRAÇÃO.")
    return mode, mode == "DEMOSTRAÇÃO"


def extract_session_value(ssid_or_payload: str) -> str:
    value = (ssid_or_payload or "").strip()
    if not value:
        return ""

    if value.startswith("42") and "auth" in value and "session" in value:
        try:
            json_start = value.find("{")
            json_end = value.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                payload = json.loads(value[json_start:json_end])
                return str(payload.get("session", "")).strip()
        except Exception:
            pass

    match = re.search(r'"session"\s*:\s*"([^"]+)"', value)
    if match:
        return match.group(1).strip()

    return value


def validate_ssid_value(ssid_or_payload: str) -> None:
    value = (ssid_or_payload or "").strip()
    if not value:
        raise ValueError("SSID vazio. Verifique o .env.")

    session = extract_session_value(value)
    if not session:
        raise ValueError(
            "Não foi possível extrair a session do SSID informado. "
            "Copie novamente o frame 42[\"auth\", {...}] ou apenas o valor de session."
        )


def load_app_config(args: argparse.Namespace) -> AppConfig:
    load_dotenv(override=False)

    account_mode, is_demo = normalize_account_mode(os.getenv("PO_ACCOUNT_MODE", "DEMOSTRAÇÃO"))
    ssid_real = os.getenv("POCKET_OPTION_SSID_REAL", "").strip()
    ssid_demo = os.getenv("POCKET_OPTION_SSID_DEMO", "").strip()
    raw_ssid = ssid_demo if is_demo else ssid_real

    if not raw_ssid:
        missing_name = "POCKET_OPTION_SSID_DEMO" if is_demo else "POCKET_OPTION_SSID_REAL"
        raise ValueError(f"A variável {missing_name} não foi encontrada ou está vazia no .env.")

    validate_ssid_value(raw_ssid)

    min_payout = float(os.getenv("PO_MIN_PAYOUT", "85"))
    connect_timeout = float(os.getenv("PO_CONNECT_TIMEOUT", "20"))
    refresh_seconds = int(args.interval or os.getenv("PO_REFRESH_SECONDS", "30"))
    refresh_enabled = bool(args.refresh) and not bool(args.once)

    return AppConfig(
        account_mode=account_mode,
        is_demo=is_demo,
        raw_ssid=raw_ssid,
        connect_timeout=connect_timeout,
        min_payout=min_payout,
        refresh_enabled=refresh_enabled,
        refresh_seconds=max(5, refresh_seconds),
    )


# -----------------------------------------------------------------------------
# Helpers de parsing e exibição
# -----------------------------------------------------------------------------

def safe_text(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def fmt_money(value: Any, currency: str = "USD") -> str:
    try:
        num = float(value)
    except Exception:
        num = 0.0
    return f"{currency} {num:,.2f}"


def fmt_pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "-"


def extract_balance_from_event_payload(data: Any) -> Optional[Dict[str, Any]]:
    try:
        if hasattr(data, "balance"):
            return {
                "balance": float(getattr(data, "balance")),
                "currency": safe_text(getattr(data, "currency", "USD"), "USD"),
                "is_demo": bool(getattr(data, "is_demo", True)),
            }
    except Exception:
        pass

    if isinstance(data, dict):
        if "balance" in data:
            try:
                return {
                    "balance": float(data.get("balance", 0)),
                    "currency": safe_text(data.get("currency"), "USD"),
                    "is_demo": bool(data.get("isDemo", data.get("is_demo", True))),
                }
            except Exception:
                return None

        message = data.get("message")
        if isinstance(message, str):
            try:
                parsed = json.loads(message)
                if isinstance(parsed, dict) and "balance" in parsed:
                    return {
                        "balance": float(parsed.get("balance", 0)),
                        "currency": safe_text(parsed.get("currency"), "USD"),
                        "is_demo": bool(parsed.get("isDemo", parsed.get("is_demo", True))),
                    }
            except Exception:
                pass

    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict) and "balance" in parsed:
                return {
                    "balance": float(parsed.get("balance", 0)),
                    "currency": safe_text(parsed.get("currency"), "USD"),
                    "is_demo": bool(parsed.get("isDemo", parsed.get("is_demo", True))),
                }
        except Exception:
            pass

    return None


async def wait_for_balance(client: Any, timeout: float = 12.0) -> Any:
    started = time.time()
    captured: Dict[str, Any] = {}

    BalanceModel = None
    try:
        BalanceModel = getattr(sys.modules.get("po_localpkg.models"), "Balance", None)
    except Exception:
        BalanceModel = None

    async def on_balance_event(data: Any) -> None:
        parsed = extract_balance_from_event_payload(data)
        if parsed:
            captured.update(parsed)

    async def on_message_event(data: Any) -> None:
        parsed = extract_balance_from_event_payload(data)
        if parsed:
            captured.update(parsed)

    try:
        client.add_event_callback("balance_updated", on_balance_event)
        client.add_event_callback("balance_data", on_balance_event)
        client.add_event_callback("message_received", on_message_event)
        client.add_event_callback("raw_message_received", on_message_event)
    except Exception:
        pass

    while time.time() - started < timeout:
        try:
            balance = await client.get_balance()
            if balance:
                return balance
        except Exception:
            pass

        internal_balance = getattr(client, "_balance", None)
        if internal_balance is not None:
            return internal_balance

        if captured:
            if BalanceModel is not None:
                try:
                    return BalanceModel(**captured)
                except Exception:
                    pass
            return SimpleBalance(
                balance=float(captured.get("balance", 0)),
                currency=safe_text(captured.get("currency"), "USD"),
                is_demo=bool(captured.get("is_demo", True)),
            )

        await asyncio.sleep(0.4)

    raise RuntimeError("Saldo não ficou disponível após autenticação.")


def market_type_from_record(record: Dict[str, Any]) -> str:
    asset = str(record.get("asset", "")).lower()
    rec_type = str(record.get("type", "")).lower()
    is_otc = bool(record.get("is_otc")) or asset.endswith("_otc") or rec_type == "otc"
    return "OTC" if is_otc else "Regular"


def availability_text(record: Dict[str, Any]) -> str:
    for key in ("schedule_close", "schedule_open", "trading_hours", "market_status"):
        value = record.get(key)
        if value not in (None, "", {}, []):
            return safe_text(value)

    is_open = record.get("is_open")
    if is_open is True:
        return "Disponível"
    if is_open is False:
        return "Fechado"
    return "-"


def sort_assets_desc(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        records,
        key=lambda x: (float(x.get("payout", 0) or 0), str(x.get("asset", ""))),
        reverse=True,
    )


def classify_assets(all_assets: Dict[str, Dict[str, Any]], min_payout: float) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    regular: List[Dict[str, Any]] = []
    otc: List[Dict[str, Any]] = []

    for asset_name, record in all_assets.items():
        try:
            payout_f = float(record.get("payout"))
        except Exception:
            continue

        if payout_f < min_payout:
            continue

        if record.get("is_open") is False:
            continue

        normalized = dict(record)
        normalized.setdefault("asset", asset_name)
        normalized["market_type"] = market_type_from_record(normalized)
        normalized["availability"] = availability_text(normalized)
        normalized["payout"] = payout_f

        if normalized["market_type"] == "OTC":
            otc.append(normalized)
        else:
            regular.append(normalized)

    return sort_assets_desc(regular), sort_assets_desc(otc)


def build_header_panel(balance: Any, config: AppConfig, stats: Dict[str, Any]) -> Panel:
    bal_value = getattr(balance, "balance", 0.0)
    currency = getattr(balance, "currency", "USD")
    account_text = "DEMOSTRAÇÃO" if getattr(balance, "is_demo", config.is_demo) else "REAL"

    left = Text()
    left.append("💰 Saldo atual\n", style="bold green")
    left.append(f"{fmt_money(bal_value, currency)}\n", style="bold white")
    left.append(f"Modo da conta: {account_text}\n", style="cyan")
    left.append(f"Moeda: {currency}\n", style="cyan")
    left.append(f"Filtro payout: >= {config.min_payout:.2f}%", style="yellow")

    right = Text()
    right.append("📡 Conexão\n", style="bold magenta")
    right.append(f"Status: {safe_text(stats.get('status', 'Conectado'))}\n", style="white")
    right.append(f"Região: {safe_text(stats.get('region', '-'))}\n", style="white")
    right.append(f"Ativos encontrados: {stats.get('assets_total', 0)}\n", style="white")
    right.append(f"Atualizado em: {time.strftime('%H:%M:%S')}", style="white")

    table = Table.grid(expand=True)
    table.add_column(ratio=1)
    table.add_column(ratio=1)
    table.add_row(left, Align.right(right))

    return Panel(table, border_style="green", title="Pocket Option", box=box.ROUNDED)


def build_assets_table(title: str, rows: List[Dict[str, Any]], empty_message: str) -> Panel:
    table = Table(box=box.SIMPLE_HEAVY, expand=True, show_lines=False)
    table.add_column("Ativo / Pair", style="bold white")
    table.add_column("Payout (%)", justify="right", style="bold green")
    table.add_column("Tipo de Mercado", style="cyan")
    table.add_column("Disponibilidade / Horário", style="yellow")

    if not rows:
        table.add_row(empty_message, "-", "-", "-")
    else:
        for row in rows:
            emoji = "✅" if float(row.get("payout", 0)) >= 90 else "📊"
            table.add_row(
                f"{emoji} {safe_text(row.get('asset'))}",
                fmt_pct(row.get("payout")),
                safe_text(row.get("market_type")),
                safe_text(row.get("availability")),
            )

    return Panel(table, title=title, border_style="blue", box=box.ROUNDED)


def build_layout(balance: Any, config: AppConfig, regular: List[Dict[str, Any]], otc: List[Dict[str, Any]], region: str) -> Table:
    total_assets = len(regular) + len(otc)
    header = build_header_panel(
        balance,
        config,
        {"status": "Conectado", "region": region, "assets_total": total_assets},
    )
    regular_panel = build_assets_table(
        "🌍 Mercado Regular (Aberto)",
        regular,
        "Nenhum ativo regular aberto com payout dentro do filtro.",
    )
    otc_panel = build_assets_table(
        "🕘 Mercado OTC",
        otc,
        "Nenhum ativo OTC com payout dentro do filtro.",
    )

    grid = Table.grid(expand=True)
    grid.add_row(header)
    grid.add_row(regular_panel)
    grid.add_row(otc_panel)
    return grid


# -----------------------------------------------------------------------------
# Coleta de dados
# -----------------------------------------------------------------------------

async def connect_with_timeout(client: Any, timeout: float) -> bool:
    return await asyncio.wait_for(client.connect(), timeout=timeout)


async def fetch_snapshot(client: Any, collector: AssetStreamCollector, config: AppConfig) -> Dict[str, Any]:
    await asyncio.sleep(0.3)
    balance = await wait_for_balance(client, timeout=max(8.0, config.connect_timeout))

    # Dispara pedidos de snapshot, mas o resultado principal vem do collector.
    merged_assets: Dict[str, Dict[str, Any]] = {}
    deadline = time.time() + 10.0

    while time.time() < deadline:
        try:
            await client.send_message('42["assets"]')
            await asyncio.sleep(0.10)
            await client.send_message('42["getAssets"]')
            await asyncio.sleep(0.10)
            await client.send_message('42["loadAssets"]')
        except Exception:
            pass

        try:
            snapshot = await client.get_assets(force_refresh=True, timeout=3.0)
            if isinstance(snapshot, dict) and snapshot:
                collector.merge_snapshot(snapshot)
        except Exception:
            pass

        merged_assets = collector.get_assets()
        if merged_assets:
            break

        await asyncio.sleep(0.8)

    regular, otc = classify_assets(merged_assets, config.min_payout)

    region = "-"
    conn_info = getattr(client, "connection_info", None)
    if conn_info is not None:
        region = safe_text(getattr(conn_info, "region", "-"))

    return {
        "balance": balance,
        "all_assets": merged_assets,
        "regular": regular,
        "otc": otc,
        "region": region,
    }


# -----------------------------------------------------------------------------
# Execução principal
# -----------------------------------------------------------------------------

async def run_once(config: AppConfig, modules: Dict[str, types.ModuleType]) -> None:
    AsyncPocketOptionClient = modules["client"].AsyncPocketOptionClient
    AuthenticationError = modules["exceptions"].AuthenticationError
    PocketConnectionError = modules["exceptions"].ConnectionError
    PocketOptionError = modules["exceptions"].PocketOptionError

    collector = AssetStreamCollector()
    client = AsyncPocketOptionClient(
        config.raw_ssid,
        is_demo=config.is_demo,
        persistent_connection=False,
        auto_reconnect=True,
        enable_logging=True,
    )

    auth_error_holder: Dict[str, str] = {"message": ""}

    async def on_auth_error(data: Any) -> None:
        auth_error_holder["message"] = safe_text(
            data.get("message") if isinstance(data, dict) else data,
            "SSID inválido",
        )

    async def on_payout_update(data: Any) -> None:
        collector.handle_payout_event(data)

    async def on_raw_message(data: Any) -> None:
        collector.handle_raw_message(data)

    client.add_event_callback("auth_error", on_auth_error)
    client.add_event_callback("payout_update", on_payout_update)
    client.add_event_callback("raw_message_received", on_raw_message)
    client.add_event_callback("raw_message", on_raw_message)

    try:
        console.print(
            Panel(
                Text(
                    f"Iniciando conexão na Pocket Option em modo {config.account_mode}...",
                    justify="center",
                    style="bold white",
                ),
                border_style="magenta",
                box=box.ROUNDED,
            )
        )

        try:
            connected = await connect_with_timeout(client, config.connect_timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"Tempo limite excedido ao conectar ({config.connect_timeout:.0f}s).") from exc

        if not connected:
            detail = auth_error_holder["message"] or "Falha de conexão ou autenticação não confirmada."
            raise RuntimeError(detail)

        snapshot = await fetch_snapshot(client, collector, config)
        console.print(build_layout(snapshot["balance"], config, snapshot["regular"], snapshot["otc"], snapshot["region"]))

    except AuthenticationError as exc:
        console.print(f"[bold red]Erro de autenticação:[/bold red] {exc}")
        console.print("[yellow]Revise o SSID no .env. Ele pode estar vencido ou inválido.[/yellow]")
    except PocketConnectionError as exc:
        console.print(f"[bold red]Erro de conexão:[/bold red] {exc}")
        console.print("[yellow]Verifique internet, firewall, WebSocket e disponibilidade do endpoint.[/yellow]")
    except PocketOptionError as exc:
        console.print(f"[bold red]Erro da API Pocket Option:[/bold red] {exc}")
    except Exception as exc:
        message = str(exc)
        if auth_error_holder["message"]:
            message = f"{message} | detalhe: {auth_error_holder['message']}"
        console.print(f"[bold red]Falha:[/bold red] {message}")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def run_refresh(config: AppConfig, modules: Dict[str, types.ModuleType]) -> None:
    AsyncPocketOptionClient = modules["client"].AsyncPocketOptionClient

    collector = AssetStreamCollector()
    client = AsyncPocketOptionClient(
        config.raw_ssid,
        is_demo=config.is_demo,
        persistent_connection=False,
        auto_reconnect=True,
        enable_logging=True,
    )

    auth_error_holder: Dict[str, str] = {"message": ""}

    async def on_auth_error(data: Any) -> None:
        auth_error_holder["message"] = safe_text(
            data.get("message") if isinstance(data, dict) else data,
            "SSID inválido",
        )

    async def on_payout_update(data: Any) -> None:
        collector.handle_payout_event(data)

    async def on_raw_message(data: Any) -> None:
        collector.handle_raw_message(data)

    client.add_event_callback("auth_error", on_auth_error)
    client.add_event_callback("payout_update", on_payout_update)
    client.add_event_callback("raw_message_received", on_raw_message)
    client.add_event_callback("raw_message", on_raw_message)

    try:
        connected = await connect_with_timeout(client, config.connect_timeout)
        if not connected:
            detail = auth_error_holder["message"] or "Falha de conexão ou autenticação não confirmada."
            raise RuntimeError(detail)

        with Live(console=console, refresh_per_second=2, screen=True) as live:
            while True:
                snapshot = await fetch_snapshot(client, collector, config)
                live.update(build_layout(snapshot["balance"], config, snapshot["regular"], snapshot["otc"], snapshot["region"]))
                await asyncio.sleep(config.refresh_seconds)

    except KeyboardInterrupt:
        console.print("\n[cyan]Atualização automática interrompida pelo usuário.[/cyan]")
    except Exception as exc:
        message = str(exc)
        if auth_error_holder["message"]:
            message = f"{message} | detalhe: {auth_error_holder['message']}"
        console.print(f"[bold red]Falha:[/bold red] {message}")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def main() -> None:
    parser = argparse.ArgumentParser(description="Consulta saldo e ativos da Pocket Option com filtro de payout.")
    parser.add_argument("--refresh", action="store_true", help="Atualiza automaticamente em loop.")
    parser.add_argument("--once", action="store_true", help="Executa só uma vez.")
    parser.add_argument("--interval", type=int, default=None, help="Intervalo do refresh em segundos. Padrão: 30")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    modules = bootstrap_local_package(base_dir)
    config = load_app_config(args)

    if config.refresh_enabled:
        await run_refresh(config, modules)
    else:
        await run_once(config, modules)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[cyan]Execução interrompida pelo usuário.[/cyan]")