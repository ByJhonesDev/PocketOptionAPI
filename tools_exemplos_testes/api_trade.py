"""
Autor: ByJhonesDev
Projeto: PocketOptionAPI – Biblioteca Python assíncrona de alto nível para integração com a corretora Pocket Option, desenvolvida para fornecer uma camada confiável, extensível, resiliente e orientada a eventos para automação operacional e processamento de dados de mercado em tempo real.

Descrição:
Exemplo assíncrono de operação automatizada utilizando o cliente principal da PocketOptionAPI para autenticar uma sessão demo, consultar saldo, ler dados de mercado, enviar uma ordem e acompanhar o ciclo completo da negociação até o resultado final. O módulo demonstra, de forma prática, como consumir a biblioteca em scripts operacionais, validar conectividade da sessão e registrar resultados de trading com segurança.

O que ele faz:
- Autentica uma sessão demo da Pocket Option usando SSID fixo
- Estabelece conexão WebSocket com o broker
- Consulta saldo atual da conta
- Solicita candles do ativo configurado e obtém também DataFrame com pandas
- Coleta estatísticas de conexão e estado da sessão
- Envia uma ordem automática com ativo, valor, direção e duração configuráveis
- Aguarda a expiração da operação e consulta o resultado final
- Calcula lucro ou prejuízo real pela diferença entre saldo inicial e final
- Persiste o resultado da operação em arquivo de histórico
- Exibe um fluxo completo e legível de execução no console em PT-BR

Características:
- Arquitetura assíncrona baseada em asyncio
- Exemplo prático de uso ponta a ponta da biblioteca
- Integração com candles e análise tabular via pandas
- Registro local de resultados operacionais
- Tratamento de timeout na verificação de resultado
- Logging visual orientado a execução manual
- Conversão amigável de estados booleanos para exibição
- Estrutura útil para testes, laboratório e automações iniciais
- Foco em conta demo para validação segura
- Demonstração clara do ciclo de vida de uma ordem

Requisitos:
- Python 3.10+
- asyncio
- pandas
- Módulos internos do projeto:
  - pocketoptionapi_async
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from pocketoptionapi_async import AsyncPocketOptionClient, OrderDirection

# =========================
# Carregamento de .env
# =========================
load_dotenv()


# =========================
# Helpers de ambiente
# =========================
def env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value is not None else default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value.strip().replace(",", "."))
    except ValueError:
        return default


def parse_account_mode(raw: str) -> str:
    normalized = (raw or "").strip().lower()
    if normalized in {"real", "live"}:
        return "REAL"
    if normalized in {"demo", "demonstracao", "demonstração", "demonstration", "demostracao", "demostração"}:
        return "DEMO"
    return "DEMO"


def parse_order_direction(raw: str) -> OrderDirection:
    normalized = (raw or "COMPRAR").strip().upper()
    if normalized in {"PUT", "VENDER", "VENDA"}:
        return OrderDirection.PUT
    return OrderDirection.CALL


def parse_first_asset() -> str:
    trade_asset = env_str("PO_TRADE_ASSET", "")
    if trade_asset:
        return trade_asset

    assets_raw = env_str("PO_ASSETS", "")
    if assets_raw:
        first = assets_raw.split(",")[0].strip()
        if first:
            return first

    return "EURUSD_otc"


def parse_duration_seconds() -> int:
    raw = env_str("PO_TIMEFRAMES", "1")
    first = raw.split(",")[0].strip().lower().replace("m", "")
    minutes = int(first) if first.isdigit() else 1
    return max(5, minutes * 60)


# =========================
# Configurações vindas do .env
# =========================
ACCOUNT_MODE = parse_account_mode(env_str("PO_ACCOUNT_MODE", "DEMOSTRAÇÃO"))
IS_DEMO = ACCOUNT_MODE == "DEMO"
SSID_FIXO = env_str("POCKET_OPTION_SSID_DEMO" if IS_DEMO else "POCKET_OPTION_SSID_REAL")

LOGS_DIR = env_str("LOG_DIR", r"C:\JhonesProIABoT\Corretora\Logs")
PO_LOG_FILE = env_str("PO_LOG_FILE", os.path.join(LOGS_DIR, "jhones_pro_pocket_log.txt"))
RESULTADOS_FILE = env_str(
    "RESULTADOS_ARQUIVO_PKT",
    os.path.join(LOGS_DIR, "resultados_gerais_pkt.txt"),
)

ASSET = parse_first_asset()
AMOUNT = env_float("PO_TRADE_AMOUNT", 1.0)
DIRECTION = parse_order_direction(env_str("PO_TRADE_DIRECTION", "COMPRAR"))
DURATION = parse_duration_seconds()

MAX_RETRIES = env_int("PO_MAX_RETRIES", 3)
ORDER_RESULT_EXTRA_WAIT = env_int("PO_ORDER_RESULT_EXTRA_WAIT", 2)
RESULT_FIRST_DELAY_SEC = env_int("PO_RESULT_FIRST_DELAY_SEC", 2)
RESULT_MAX_POLL_SEC = env_int("PO_RESULT_MAX_POLL_SEC", 20)
RESULT_POLL_INTERVAL_SEC = env_int("PO_RESULT_POLL_INTERVAL_SEC", 1)
PAST_CANDLES = env_int("PO_PAST_CANDLES", 100)

Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)


# =========================
# Modelos simples auxiliares
# =========================
class SimpleBalance:
    def __init__(self, balance: float, currency: str = "USD", is_demo: bool = True):
        self.balance = balance
        self.currency = currency
        self.is_demo = is_demo


# =========================
# Utilidades de Log / Formatação
# =========================
def bool_pt(value: Any) -> Any:
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    return value


def safe_text(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def direction_to_pt(direction: Any) -> str:
    value = getattr(direction, "name", str(direction)).upper()
    if value == "PUT":
        return "VENDER"
    return "COMPRAR"


def normalize_status_pt(status: Any) -> str:
    raw = str(status or "").strip().lower()

    status_map = {
        "active": "Ativo",
        "opened": "Ativo",
        "open": "Ativo",
        "pending": "Pendente",
        "pendente": "Pendente",
        "ativa": "Ativo",
        "ativo": "Ativo",
        "closed": "Fechado",
        "close": "Fechado",
        "won": "Vitória",
        "win": "Vitória",
        "loss": "Derrota",
        "lost": "Derrota",
        "lose": "Derrota",
        "draw": "Empate",
        "equal": "Empate",
        "n/a": "N/A",
    }

    return status_map.get(raw, str(status))


def load_resultados() -> str:
    if os.path.exists(RESULTADOS_FILE):
        with open(RESULTADOS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return lines[-1].strip() if lines else "Nenhum resultado anterior."
    return "Arquivo de resultados não encontrado."


def save_resultados(resultado_str: str) -> None:
    with open(RESULTADOS_FILE, "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        f.write(f"[{timestamp}] {resultado_str}\n")
    print(f"✅ Resultados salvos em: {RESULTADOS_FILE}")


def append_runtime_log(text: str) -> None:
    timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    with open(PO_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {text}\n")


def format_dt_full(dt: Any) -> str:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%d-%m-%Y %H:%M:%S")
    return str(dt)


def mask_ssid(ssid: str) -> str:
    if not ssid:
        return "NÃO CONFIGURADO"
    if len(ssid) <= 16:
        return "***"
    return f"{ssid[:10]}...{ssid[-10:]}"


def _extract_status_from_any(obj: Any) -> str:
    if obj is None:
        return "N/A"

    if isinstance(obj, dict):
        status = obj.get("status") or obj.get("result") or obj.get("state")
        return str(status) if status is not None else "N/A"

    status = getattr(obj, "status", None)
    if status is None:
        return "N/A"

    value = getattr(status, "value", status)
    return str(value)


def _extract_profit_from_any(obj: Any) -> Optional[float]:
    if obj is None:
        return None

    keys = ("profit", "payout", "win", "amount")
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] not in (None, ""):
                try:
                    return float(obj[key])
                except Exception:
                    pass
        return None

    for key in keys:
        value = getattr(obj, key, None)
        if value not in (None, ""):
            try:
                return float(value)
            except Exception:
                pass

    return None


def _resultado_from_sources(calculated_profit: float, final_result: Any, win_result: Any) -> str:
    if calculated_profit > 0:
        return "Vitória"
    if calculated_profit < 0:
        return "Derrota"

    status = _extract_status_from_any(final_result).lower()
    if status in {"won", "win"}:
        return "Vitória"
    if status in {"loss", "lost", "lose"}:
        return "Derrota"
    if status in {"draw", "equal"}:
        return "Empate"
    if status in {"ativo", "ativa", "active", "opened", "open", "pendente", "pending"}:
        return "Pendente"

    if isinstance(win_result, dict):
        result = str(win_result.get("result", "")).lower()
        if result == "win":
            return "Vitória"
        if result == "loss":
            return "Derrota"
        if result == "draw":
            return "Empate"

        profit = win_result.get("profit")
        if profit not in (None, ""):
            try:
                if float(profit) > 0:
                    return "Vitória"
                if float(profit) < 0:
                    return "Derrota"
            except Exception:
                pass

    try:
        if win_result is not None:
            numeric = float(win_result)
            if numeric > 0:
                return "Vitória"
            if numeric < 0:
                return "Derrota"
    except Exception:
        pass

    return "Empate/Indefinido"


# =========================
# Saldo inspirado no test.py
# =========================
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


def _fallback_balance_from_client_cache(client: AsyncPocketOptionClient) -> Tuple[float, str]:
    balance_obj = getattr(client, "_balance", None)
    if balance_obj is not None:
        try:
            return float(balance_obj.balance), str(balance_obj.currency)
        except Exception:
            pass

    account_config = getattr(client, "_account_config", {}) or {}
    balance = account_config.get("balance")
    currency = account_config.get("currency", "USD")
    if balance is not None:
        try:
            return float(balance), str(currency)
        except Exception:
            pass

    return 0.0, "USD"


async def wait_for_balance(client: Any, timeout: float = 12.0) -> Any:
    started = time.time()
    captured: Dict[str, Any] = {}

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
        client.add_event_callback("raw_message", on_message_event)
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
            return SimpleBalance(
                balance=float(captured.get("balance", 0)),
                currency=safe_text(captured.get("currency"), "USD"),
                is_demo=bool(captured.get("is_demo", True)),
            )

        await asyncio.sleep(0.4)

    fallback_balance, fallback_currency = _fallback_balance_from_client_cache(client)
    if fallback_balance or fallback_currency:
        return SimpleBalance(
            balance=float(fallback_balance),
            currency=str(fallback_currency),
            is_demo=IS_DEMO,
        )

    raise RuntimeError("Saldo não ficou disponível após autenticação.")


async def get_balance(client: AsyncPocketOptionClient) -> Tuple[float, str]:
    try:
        balance = await wait_for_balance(client, timeout=12.0)
        return float(balance.balance), str(balance.currency)
    except Exception as e:
        print(f"⚠️ Falha no saldo via API/eventos: {e}")

        fallback_balance, fallback_currency = _fallback_balance_from_client_cache(client)
        print(f"💾 Usando saldo em cache da sessão: ${fallback_balance} {fallback_currency}")
        append_runtime_log(f"Fallback saldo em cache após erro: {e}")

        return fallback_balance, fallback_currency


# =========================
# Funções assíncronas de API
# =========================
async def get_candles(client: AsyncPocketOptionClient, asset: str, timeframe: int):
    try:
        candles = await client.get_candles(asset=asset, timeframe=timeframe, count=PAST_CANDLES)
        if candles:
            ultima_vela = candles[-1]
            return len(candles), ultima_vela
        return 0, None
    except Exception as e:
        print(f"❌ Erro ao obter Velas: {e}")
        append_runtime_log(f"Erro ao obter velas: {e}")
        return 0, None


async def get_candles_dataframe(
    client: AsyncPocketOptionClient,
    asset: str,
    timeframe: int,
) -> pd.DataFrame:
    try:
        return await client.get_candles_dataframe(asset=asset, timeframe=timeframe, count=PAST_CANDLES)
    except Exception as e:
        print(f"❌ Erro ao obter DataFrame de Velas: {e}")
        append_runtime_log(f"Erro ao obter DataFrame de velas: {e}")
        return pd.DataFrame()


async def get_active_orders(client: AsyncPocketOptionClient):
    try:
        return await client.get_active_orders()
    except Exception as e:
        print(f"❌ Erro ao obter Ordens Ativas: {e}")
        append_runtime_log(f"Erro ao obter ordens ativas: {e}")
        return []


async def place_order(
    client: AsyncPocketOptionClient,
    symbol: Optional[str] = None,
    amount: Optional[float] = None,
    direction: Optional[OrderDirection] = None,
    duration: Optional[int] = None,
    max_retries: Optional[int] = None,
):
    symbol = symbol or ASSET
    amount = amount if amount is not None else AMOUNT
    direction = direction or DIRECTION
    duration = duration if duration is not None else DURATION
    max_retries = max_retries if max_retries is not None else MAX_RETRIES

    for attempt in range(max_retries):
        try:
            print("\n🚀 Operações Automáticas")
            print("----------------------------------------")
            print(f"📤 Enviando Ordem Automática (Tentativa {attempt + 1}/{max_retries})")
            print(f" 💹 Ativo: {symbol}")
            print(f" 💵 Valor: ${amount}")
            print(f" 🎯 Direção: {direction_to_pt(direction)}")
            print(f" ⏱️  Duração: {duration} segundos")

            order = await client.place_order(
                asset=symbol,
                amount=amount,
                direction=direction,
                duration=duration,
            )

            if order and not getattr(order, "error_message", None):
                print("✅ Ordem Enviada com Sucesso!")
                append_runtime_log(
                    f"Ordem enviada com sucesso | ativo={symbol} valor={amount} direcao={direction_to_pt(direction)} duracao={duration}"
                )
                return order

            error_msg = getattr(order, "error_message", "Erro desconhecido")
            print(f"⚠️ Tentativa {attempt + 1} falhou: {error_msg}")
            append_runtime_log(f"Tentativa de ordem falhou: {error_msg}")

        except Exception as e:
            print(f"❌ Erro na tentativa {attempt + 1}: {e}")
            append_runtime_log(f"Erro ao enviar ordem na tentativa {attempt + 1}: {e}")

        if attempt < max_retries - 1:
            await asyncio.sleep(2)

    print("❌ Todas as tentativas de envio falharam.")
    return None


async def check_order_result_with_timeout(client: AsyncPocketOptionClient, order_id: str, timeout: int = 30):
    try:
        return await asyncio.wait_for(client.check_order_result(order_id), timeout=timeout)
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        print(f"❌ Erro no resultado de Verificação da Ordem: {e}")
        append_runtime_log(f"Erro ao verificar resultado da ordem: {e}")
        return None


async def wait_for_expiry_and_check(
    client: AsyncPocketOptionClient,
    order_id: str,
    initial_balance: float,
    duration: Optional[int] = None,
):
    duration = duration if duration is not None else DURATION

    if RESULT_FIRST_DELAY_SEC > 0:
        print(f"⏳ Esperando {RESULT_FIRST_DELAY_SEC}s antes da primeira checagem...")
        await asyncio.sleep(RESULT_FIRST_DELAY_SEC)

    wait_total = duration + ORDER_RESULT_EXTRA_WAIT
    print(f"⏳ Aguardando expiração da negociação ({wait_total}s)...")
    await asyncio.sleep(wait_total)

    print("🔄 Verificando Resultado Final...")

    final_result = None
    elapsed = 0

    while elapsed < RESULT_MAX_POLL_SEC:
        current_result = await check_order_result_with_timeout(
            client,
            order_id,
            timeout=RESULT_POLL_INTERVAL_SEC + 1,
        )

        if current_result is not None:
            final_result = current_result
            status_now = _extract_status_from_any(current_result).lower()
            if status_now not in {"n/a", "ativa", "ativo", "active", "opened", "open", "pendente", "pending"}:
                break

        await asyncio.sleep(RESULT_POLL_INTERVAL_SEC)
        elapsed += RESULT_POLL_INTERVAL_SEC

    final_balance, _ = await get_balance(client)
    calculated_profit = round(final_balance - initial_balance, 2)

    if abs(calculated_profit) < 0.01:
        extra_elapsed = 0
        while extra_elapsed < max(5, RESULT_MAX_POLL_SEC):
            await asyncio.sleep(RESULT_POLL_INTERVAL_SEC)

            final_balance, _ = await get_balance(client)
            calculated_profit = round(final_balance - initial_balance, 2)

            current_result = await check_order_result_with_timeout(
                client,
                order_id,
                timeout=RESULT_POLL_INTERVAL_SEC + 1,
            )
            if current_result is not None:
                final_result = current_result

            status_now = _extract_status_from_any(final_result).lower()
            if abs(calculated_profit) >= 0.01 or status_now in {"won", "win", "loss", "lost", "lose", "draw"}:
                break

            extra_elapsed += RESULT_POLL_INTERVAL_SEC

    win_result = None
    try:
        win_result = await asyncio.wait_for(
            client.check_win(order_id),
            timeout=max(5, RESULT_MAX_POLL_SEC),
        )
    except Exception as e:
        append_runtime_log(f"check_win indisponível/ignorado: {e}")

    print(f"💰 Saldo: Inicial= ${initial_balance} | Final= ${final_balance} | Lucro/Prejuízo= ${calculated_profit}")

    status = _extract_status_from_any(final_result)
    profit_from_result = _extract_profit_from_any(final_result)

    if profit_from_result is not None:
        print(f"💹 Lucro reportado pela ordem: ${round(profit_from_result, 2)}")
    if status != "N/A":
        print(f"📌 Status da Ordem: {normalize_status_pt(status)}")

    resultado = _resultado_from_sources(calculated_profit, final_result, win_result)
    print(f"📊 Resultado Final: {resultado} (Lucro Real: ${calculated_profit})")

    append_runtime_log(
        f"Resultado final | order_id={order_id} status={normalize_status_pt(status)} lucro={calculated_profit} resultado={resultado}"
    )
    return final_result, win_result, calculated_profit


def get_connection_stats(client: AsyncPocketOptionClient):
    try:
        return client.get_connection_stats()
    except Exception as e:
        print(f"❌ Erro nas estatísticas de conexão: {e}")
        append_runtime_log(f"Erro nas estatísticas de conexão: {e}")
        return {}


# =========================
# Impressão do Log
# =========================
def print_header() -> None:
    print("🤖 Bem-vindos ao JhonesProIA 🤖")
    print("🟢 Inicializando JhonesProPocketBoT...")
    print("✅ JhonesProPocketBoT e API PocketOption inicializados com sucesso!\n")
    print("📂 Resultados")
    print("----------------------------------------")
    prev_result = load_resultados()
    print(f"📂 Resultados carregados de: {RESULTADOS_FILE}")
    print(f"{prev_result}\n")
    print("🔐 Autenticação e Conexão")
    print("----------------------------------------")
    print(f"🔑 Conta selecionada: {'DEMO' if IS_DEMO else 'REAL'}")
    print(f"🧾 SSID: {mask_ssid(SSID_FIXO)}")
    print("🌐 Conectando à PocketOption...")


def print_saldo(saldo: float, moeda: str) -> None:
    print(f"💰 Saldo Atual: ${saldo} {moeda}")


def print_dados_mercado(total_candles: int, ultima_vela: Any) -> None:
    print("\n📊 Dados de Mercado")
    print("----------------------------------------")
    print(f"🔢 Total de Velas: {total_candles}")
    if ultima_vela:
        o = getattr(ultima_vela, "open", None)
        c = getattr(ultima_vela, "close", None)
        h = getattr(ultima_vela, "high", None)
        l = getattr(ultima_vela, "low", None)
        ts = getattr(ultima_vela, "timestamp", None)
        print("🕯️ Informações da Última Vela:")
        print(f" 📈 Abertura: {o}")
        print(f" 📉 Fechamento: {c}")
        print(f" ⤴️ Máxima: {h}")
        print(f" ⤵️ Mínima: {l}")
        print(f" 🕒 Horário: {ts}")


def print_stats(stats: dict) -> None:
    print("\n📡 Estatísticas de Conexão")
    print("----------------------------------------")
    if not stats:
        print("❌ Sem estatísticas disponíveis.")
        return

    total_connections = stats.get("total_connections", "N/A")
    successful_connections = stats.get("successful_connections", "N/A")
    total_reconnects = stats.get("total_reconnects", "N/A")
    last_ping_time = stats.get("last_ping_time", "N/A")
    messages_sent = stats.get("messages_sent", stats.get("total_messages_sent", "N/A"))
    messages_received = stats.get("messages_received", stats.get("total_messages_received", "N/A"))
    websocket_connected = bool_pt(stats.get("websocket_connected", stats.get("is_connected", "N/A")))
    conn_info = stats.get("connection_info")
    connected_at = getattr(conn_info, "connected_at", "N/A") if conn_info else "N/A"
    region = getattr(conn_info, "region", stats.get("current_region", "N/A")) if conn_info else stats.get("current_region", "N/A")

    print(f"🔗 Conexões Totais: {total_connections}")
    print(f"✅ Conexões Bem-Sucedidas: {successful_connections}")
    print(f"♻️  Total de Reconexões: {total_reconnects}")
    print(f"🕒 Horário do Último Ping: {last_ping_time}")
    print(f"✉️  Mensagens Enviadas/Recebidas: {messages_sent}/{messages_received}")
    print(f"🌐 WebSocket Conectado: {websocket_connected}")
    print(f"📅 Conectado em: {format_dt_full(connected_at)}")
    print(f"🌍 Região: {region}")


def print_operacao_registro(final_result: Any, win_result: Any, calculated_profit: float) -> None:
    resultado = _resultado_from_sources(calculated_profit, final_result, win_result)
    status = _extract_status_from_any(final_result)

    print("\n📈 Registro da Operação")
    print("----------------------------------------")
    print(f"🏁 Resultado: {resultado} | 💹 Lucro Total: ${calculated_profit}")
    if status != "N/A":
        print(f"📌 Status Final Registrado: {normalize_status_pt(status)}")

    save_resultados(
        f"Lucro= ${calculated_profit}, Resultado= {resultado}, Ativo= {ASSET}, Conta= {'DEMO' if IS_DEMO else 'REAL'}"
    )


def print_footer() -> None:
    print("\n🔚 Finalização")
    print("----------------------------------------")
    print("🔌 Desconectando...")
    print("✅ Conexão Encerrada com Sucesso.")


# =========================
# Fluxo Principal
# =========================
async def main() -> None:
    print_header()

    if not SSID_FIXO:
        print("❌ SSID não encontrado no .env.")
        print("🔍 Verifique POCKET_OPTION_SSID_DEMO / POCKET_OPTION_SSID_REAL e PO_ACCOUNT_MODE.")
        return

    client = AsyncPocketOptionClient(SSID_FIXO, is_demo=IS_DEMO, enable_logging=False)

    try:
        success = await client.connect()
        if not success:
            raise Exception("Conexão falhou após tentativa.")
        if hasattr(client, "is_connected") and not client.is_connected:
            raise Exception("Conexão reportada como inativa após connect.")
        print("✅ Conectado com Sucesso!")
        append_runtime_log(f"Conectado com sucesso | conta={'DEMO' if IS_DEMO else 'REAL'}")
    except Exception as e:
        print(f"❌ Erro na conexão: {e}")
        print("🔍 Dica: Verifique o SSID, rede ou biblioteca.")
        append_runtime_log(f"Erro na conexão: {e}")
        return

    try:
        if hasattr(client, "is_connected") and not client.is_connected:
            print("♻️ Tentando reconectar...")
            success = await client.connect()
            if not success:
                raise Exception("Reconexão falhou.")

        # Aqui está a mudança principal: usa a lógica do test.py
        balance_obj = await wait_for_balance(client, timeout=12.0)
        initial_balance = float(balance_obj.balance)
        moeda = str(balance_obj.currency)

        print_saldo(initial_balance, moeda)
        append_runtime_log(f"Saldo inicial obtido via wait_for_balance: {initial_balance} {moeda}")

    except Exception as e:
        print(f"❌ Falha ao obter saldo inicial: {e}")
        append_runtime_log(f"Falha ao obter saldo inicial: {e}")
        await client.disconnect()
        return

    total_candles, ultima_vela = await get_candles(client, asset=ASSET, timeframe=DURATION)
    print_dados_mercado(total_candles, ultima_vela)

    _ = await get_candles_dataframe(client, asset=ASSET, timeframe=DURATION)
    _ = await get_active_orders(client)

    stats = get_connection_stats(client)
    print_stats(stats)

    order = await place_order(
        client,
        symbol=ASSET,
        amount=AMOUNT,
        direction=DIRECTION,
        duration=DURATION,
        max_retries=MAX_RETRIES,
    )

    if order:
        order_id = getattr(order, "order_id", None) or getattr(order, "id", None)
        print(f"🆔 ID da ordem: {order_id}")

        final_result, win_result, calculated_profit = await wait_for_expiry_and_check(
            client,
            order_id,
            initial_balance,
            duration=DURATION,
        )
        print_operacao_registro(final_result, win_result, calculated_profit)
    else:
        print("\n🚀 Operações Automáticas")
        print("----------------------------------------")
        print("❌ Nenhuma ordem enviada.")

    print_footer()
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
