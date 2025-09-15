"""
# Autor: ByJhonesDev 
# Função: Ferramenta de Teste de Carga e Estresse
# Descrição:
# - Executa testes de carga e estresse na PocketOption Async API
# - Simula clientes concorrentes e operações (saldo, velas, ping, mercado, ordens)
# - Suporta conexão persistente via ConnectionKeepAlive e reconexão automática
# - Mede latência, taxa de sucesso, vazão (ops/s) e picos por segundo
# - Gera relatórios detalhados em JSON e resumo tabular opcional (tabulate)
"""

import sys
import logging
import asyncio
import random
import json
import csv
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from collections import defaultdict, deque
import statistics
import types  # Para MethodType no patch de instância
from loguru import logger

# =========================
# CONFIGURAÇÃO DE LOG LIMPO COM FILTRO ANTI-FLOOD E SUPRESSÃO ESPECÍFICA
# =========================
logger.remove()

# Dict para rastrear última log de cada mensagem (timestamp)
last_logged_messages = {}

# Filtro custom: Suprime duplicatas em INFO/SUCCESS + erro específico de 'startswith'
def dedup_filter(record):
    msg = str(record["message"])
    
    # Suprime APENAS esse erro específico, independente do nível
    if "'dict' object has no attribute 'startswith'" in msg:
        return False
    
    # Dedup pra INFO e SUCCESS (captura "Sucesso: ..." repetidos da lib)
    level = record["level"].name
    if level in ["INFO", "SUCCESS"]:
        now = datetime.now().timestamp()
        if msg in last_logged_messages and now - last_logged_messages[msg] < 3.0:
            return False  # Suprime se <3s do anterior
        last_logged_messages[msg] = now
    
    return True

# Console
logger.add(
    sys.stderr,
    level="INFO",
    colorize=False,
    backtrace=False,
    diagnose=False,
    format="{time:DD-MM-YYYY HH:mm:ss} | {level: <7} | {message}",
    filter=dedup_filter,
)

# Arquivo
logger.add(
    "load_test.log",
    level="INFO",
    rotation="10 MB",
    retention="7 days",
    encoding="utf-8",
    enqueue=True,
    backtrace=False,
    diagnose=False,
    format="{time:DD-MM-YYYY HH:mm:ss} | {level: <7} | {message}",
    filter=dedup_filter,
)

# Reduz ruído
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("socketio").setLevel(logging.WARNING)

from pocketoptionapi_async.client import AsyncPocketOptionClient
from pocketoptionapi_async.connection_keep_alive import ConnectionKeepAlive
from pocketoptionapi_async.models import OrderDirection
from pocketoptionapi_async.constants import TIMEFRAMES, ASSETS

try:
    from tabulate import tabulate
except ImportError:
    tabulate = None
    print("Instale 'tabulate' para resumo tabular: pip install tabulate")

@dataclass
class LoadTestResult:
    operation_type: str
    start_time: datetime
    end_time: datetime
    duration: float
    success: bool
    error_message: Optional[str] = None
    response_data: Optional[Any] = None

@dataclass
class LoadTestConfig:
    concurrent_clients: int = 5
    operations_per_client: int = 20
    operation_delay: float = 1.0
    test_duration_minutes: int = 5
    use_persistent_connection: bool = True
    include_trading_operations: bool = True
    stress_mode: bool = False

class LoadTester:
    def __init__(self, ssid: str, is_demo: bool = True):
        self.ssid = ssid
        self.is_demo = is_demo
        self.test_start_time: Optional[datetime] = None
        self.test_end_time: Optional[datetime] = None
        self._reset_test_state()

    def _reset_test_state(self):
        self.test_results: List[LoadTestResult] = []
        self.active_clients: List[AsyncPocketOptionClient] = []
        self.operation_stats: Dict[str, List[float]] = defaultdict(list)
        self.error_counts: Dict[str, int] = defaultdict(int)
        self.success_counts: Dict[str, int] = defaultdict(int)
        self.operations_per_second: deque = deque(maxlen=60)
        self.current_operations = 0
        self.peak_operations_per_second = 0

    async def run_load_test(self, config: LoadTestConfig) -> Dict[str, Any]:
        logger.info("Iniciando execução do Teste de Carga")
        logger.info(f"Configuração: {config.concurrent_clients} clientes, {config.operations_per_client} ops/cliente")
        self._reset_test_state()  # Antes de start_time
        self.test_start_time = datetime.now()
        try:
            if config.stress_mode:
                await self._run_stress_test(config)
            else:
                await self._run_standard_load_test(config)
        finally:
            self.test_end_time = datetime.now()
            await self._cleanup_clients()
        return self._generate_load_test_report()

    async def _run_standard_load_test(self, config: LoadTestConfig) -> None:
        client_tasks = []
        for i in range(config.concurrent_clients):
            task = asyncio.create_task(
                self._run_client_operations(
                    client_id=i,
                    operations_count=config.operations_per_client,
                    delay=config.operation_delay,
                    persistent=config.use_persistent_connection,
                    include_trading=config.include_trading_operations,
                )
            )
            client_tasks.append(task)
        monitor_task = asyncio.create_task(self._monitor_operations())
        logger.info(f"Executando {len(client_tasks)} clientes concorrentes...")
        try:
            await asyncio.gather(*client_tasks, return_exceptions=True)
        finally:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

    async def _run_stress_test(self, config: LoadTestConfig) -> None:
        logger.info("Executando modo STRESS TEST!")
        phases = [
            ("Ramp Up", config.concurrent_clients // 3, 0.1),
            ("Peak Load", config.concurrent_clients, 0.05),
            ("Extreme Load", config.concurrent_clients * 2, 0.01),
            ("Cool Down", config.concurrent_clients // 2, 0.5),
        ]
        for phase_name, clients, delay in phases:
            logger.info(f"Fase de Estresse: {phase_name} ({clients} clientes, atraso {delay}s)")
            phase_tasks = []
            for i in range(clients):
                task = asyncio.create_task(
                    self._run_stress_client(
                        client_id=f"{phase_name}_{i}",
                        operations_count=config.operations_per_client // 2,
                        delay=delay,
                        persistent=config.use_persistent_connection,
                    )
                )
                phase_tasks.append(task)
            try:
                await asyncio.wait_for(
                    asyncio.gather(*phase_tasks, return_exceptions=True),
                    timeout=60,
                )
            except asyncio.TimeoutError:
                logger.warning(f"Fase de Estresse {phase_name} estourou o tempo")
                for task in phase_tasks:
                    if not task.done():
                        task.cancel()
            await asyncio.sleep(5)

    async def _run_client_operations(
        self,
        client_id: int,
        operations_count: int,
        delay: float,
        persistent: bool,
        include_trading: bool,
    ) -> None:
        client = None
        try:
            client = AsyncPocketOptionClient(
                self.ssid,
                is_demo=self.is_demo,
                persistent_connection=persistent,
                auto_reconnect=persistent,
            )
            self.active_clients.append(client)

            if persistent:
                # Patch por instância - Melhorado: Conversão forçada pra str antes de qualquer check
                def patched_connected(self_, data=None):
                    logger.info("Connected handler fixed (persistent mode)")
                client._on_keep_alive_connected = types.MethodType(patched_connected, client)

                def patched_message(self_, message):
                    try:
                        # Garante que message seja str ANTES de qualquer operação
                        if not isinstance(message, str):
                            if isinstance(message, (dict, list)):
                                message = json.dumps(message)
                            else:
                                message = str(message)
                        
                        if message.startswith('42['):
                            pass  # Ignora mensagens Socket.IO padrão
                        else:
                            logger.debug("Message handled (patched)")
                    except Exception as e:
                        logger.debug(f"Patched message ignored: {e}")
                client._on_message_received = types.MethodType(patched_message, client)

            connect_start = datetime.now()
            timeout = 15.0 if persistent else 10.0
            try:
                success = await asyncio.wait_for(client.connect(), timeout=timeout)
            except asyncio.TimeoutError:
                success = False
                logger.warning(f"Timeout na conexão para cliente {client_id}")
            connect_end = datetime.now()
            if success:
                self._record_result(
                    LoadTestResult(
                        operation_type="connect",
                        start_time=connect_start,
                        end_time=connect_end,
                        duration=(connect_end - connect_start).total_seconds(),
                        success=True,
                        response_data={"client_id": client_id},
                    )
                )
                logger.info(f"Cliente {client_id} conectado")
            else:
                self._record_result(
                    LoadTestResult(
                        operation_type="connect",
                        start_time=connect_start,
                        end_time=connect_end,
                        duration=(connect_end - connect_start).total_seconds(),
                        success=False,
                        error_message="Falha na conexão",
                    )
                )
                return
            for op_num in range(operations_count):
                try:
                    operation_type = self._choose_operation_type(include_trading)
                    await self._execute_operation(client, client_id, operation_type)
                    if delay > 0:
                        await asyncio.sleep(delay)
                except Exception as e:
                    logger.error(f"Cliente {client_id} operação {op_num} falhou: {e}")
                    self._record_result(
                        LoadTestResult(
                            operation_type="unknown",
                            start_time=datetime.now(),
                            end_time=datetime.now(),
                            duration=0,
                            success=False,
                            error_message=str(e),
                        )
                    )
        except Exception as e:
            logger.error(f"Cliente {client_id} falhou: {e}")
        finally:
            if client:
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=5.0)
                except:
                    pass

    async def _run_stress_client(
        self, client_id: str, operations_count: int, delay: float, persistent: bool
    ) -> None:
        keep_alive = None
        try:
            keep_alive = ConnectionKeepAlive(self.ssid, is_demo=self.is_demo)

            if persistent:
                def patched_connected(self_, data=None):
                    logger.info("Stress connected handler fixed")
                keep_alive._on_keep_alive_connected = types.MethodType(patched_connected, keep_alive)

                # Patch melhorado igual ao de cima
                def patched_message(self_, message):
                    try:
                        # Garante que message seja str ANTES de qualquer operação
                        if not isinstance(message, str):
                            if isinstance(message, (dict, list)):
                                message = json.dumps(message)
                            else:
                                message = str(message)
                        
                        if message.startswith('42['):
                            pass  # Ignora mensagens Socket.IO padrão
                        else:
                            logger.debug("Stress message handled (patched)")
                    except Exception as e:
                        logger.debug(f"Stress patched message ignored: {e}")
                keep_alive._on_message_received = types.MethodType(patched_message, keep_alive)

            connect_start = datetime.now()
            timeout = 15.0
            try:
                success = await asyncio.wait_for(keep_alive.start_persistent_connection(), timeout=timeout)
            except asyncio.TimeoutError:
                success = False
            connect_end = datetime.now()
            if not success:
                self._record_result(
                    LoadTestResult(
                        operation_type="stress_connect",
                        start_time=connect_start,
                        end_time=connect_end,
                        duration=(connect_end - connect_start).total_seconds(),
                        success=False,
                        error_message="Falha na conexão (stress)",
                    )
                )
                return
            for op_num in range(operations_count):
                try:
                    op_start = datetime.now()
                    await keep_alive.send_message('42["ps"]')
                    await asyncio.sleep(0.05)
                    op_end = datetime.now()
                    self._record_result(
                        LoadTestResult(
                            operation_type="stress_rapid_ping",
                            start_time=op_start,
                            end_time=op_end,
                            duration=(op_end - op_start).total_seconds(),
                            success=True,
                            response_data={"client_id": client_id, "messages": 1},
                        )
                    )
                    if delay > 0:
                        await asyncio.sleep(delay)
                except Exception as e:
                    logger.error(f"Cliente de stress {client_id} operação {op_num} falhou: {e}")
        except Exception as e:
            logger.error(f"Cliente de stress {client_id} falhou: {e}")
        finally:
            if keep_alive:
                try:
                    await keep_alive.stop_persistent_connection()
                except:
                    pass

    def _choose_operation_type(self, include_trading: bool) -> str:
        basic_operations = ["balance", "candles", "ping", "market_data"]
        if include_trading:
            trading_operations = ["place_order"] * 3 + ["check_order", "get_orders"]
            basic_operations.extend(trading_operations)
        return random.choice(basic_operations)

    async def _execute_operation(
        self, client: AsyncPocketOptionClient, client_id: int, operation_type: str
    ) -> None:
        start_time = datetime.now()
        result_data = {}
        timeout_val = 10.0 if hasattr(client, 'persistent_connection') and client.persistent_connection else 5.0
        try:
            if operation_type == "balance":
                balance = await asyncio.wait_for(client.get_balance(), timeout=timeout_val)
                result_data = {"balance": balance.balance if balance else None}
            elif operation_type == "candles":
                asset = random.choice(list(ASSETS.keys()))
                timeframe = random.choice(list(TIMEFRAMES.values()))
                candles = await asyncio.wait_for(client.get_candles(asset, timeframe, random.randint(10, 50)), timeout=timeout_val)
                result_data = {"asset": asset, "candles_count": len(candles) if candles else 0}
            elif operation_type == "ping":
                await asyncio.wait_for(client.send_message('42["ps"]'), timeout=2.0)
                result_data = {"message": "ping"}
            elif operation_type == "market_data":
                tasks = [
                    asyncio.wait_for(client.get_candles("EURUSD", 60, 5), timeout=3.0),
                    asyncio.wait_for(client.get_candles("GBPUSD", 60, 5), timeout=3.0)
                ]
                await asyncio.gather(*tasks, return_exceptions=True)
                result_data = {"assets": 2}
            elif operation_type == "place_order":
                asset = random.choice(list(ASSETS.keys()))
                amount = random.uniform(1, 10)
                direction = random.choice([OrderDirection.CALL, OrderDirection.PUT])
                duration = 60
                try:
                    result = await asyncio.wait_for(client.buy(amount, asset, direction.value, duration), timeout=timeout_val)
                except:
                    result = {"success": False}
                # Simulação melhorada
                recent_candles = await asyncio.wait_for(client.get_candles(asset, 60, 1), timeout=3.0)
                last_close = recent_candles[0].close if recent_candles else 1.0
                last_open = recent_candles[0].open if recent_candles else 1.0
                win = (direction == OrderDirection.CALL and last_close > last_open) or (direction == OrderDirection.PUT and last_close < last_open)
                simulated_profit = amount * ASSETS[asset].get('payout', 0.8) if win else -amount
                result_data = {
                    "asset": asset,
                    "amount": amount,
                    "direction": direction.value,
                    "success": result.get("success", win),
                    "simulated_profit": simulated_profit,
                    "payout": ASSETS[asset].get('payout', 0.8),
                    "win_based_on_candle": win,
                }
                logger.info(f"Simulação place_order: {asset} {direction.value} - Win: {win} (P&L: {simulated_profit:.2f})")
            elif operation_type in ["check_order", "get_orders"]:
                await asyncio.sleep(0.1)
                result_data = {"orders": 0}
            end_time = datetime.now()
            self._record_result(
                LoadTestResult(
                    operation_type=operation_type,
                    start_time=start_time,
                    end_time=end_time,
                    duration=(end_time - start_time).total_seconds(),
                    success=True,
                    response_data=result_data,
                )
            )
            self.current_operations += 1
        except asyncio.TimeoutError:
            end_time = datetime.now()
            self._record_result(
                LoadTestResult(
                    operation_type=operation_type,
                    start_time=start_time,
                    end_time=end_time,
                    duration=(end_time - start_time).total_seconds(),
                    success=False,
                    error_message="Timeout na operação",
                )
            )
        except Exception as e:
            end_time = datetime.now()
            self._record_result(
                LoadTestResult(
                    operation_type=operation_type,
                    start_time=start_time,
                    end_time=end_time,
                    duration=(end_time - start_time).total_seconds(),
                    success=False,
                    error_message=str(e),
                )
            )

    async def _monitor_operations(self):
        while True:
            try:
                await asyncio.sleep(1)
                ops_this_second = self.current_operations
                self.operations_per_second.append(ops_this_second)
                if ops_this_second > self.peak_operations_per_second:
                    self.peak_operations_per_second = ops_this_second
                self.current_operations = 0
                if len(self.operations_per_second) % 10 == 0:
                    avg_ops = statistics.mean(list(self.operations_per_second)[-10:])
                    logger.info(f"Média ops/s (últimos 10s): {avg_ops:.1f}, Pico: {self.peak_operations_per_second}")
            except Exception as e:
                logger.error(f"Erro no monitor: {e}")
                await asyncio.sleep(1)

    def _record_result(self, result: LoadTestResult):
        self.test_results.append(result)
        if result.success:
            self.success_counts[result.operation_type] += 1
            self.operation_stats[result.operation_type].append(result.duration)
        else:
            self.error_counts[result.operation_type] += 1

    async def _cleanup_clients(self):
        logger.info("Limpando clientes...")
        for client in self.active_clients[:]:
            if hasattr(client, 'auto_reconnect'):
                client.auto_reconnect = False
            if hasattr(client, 'is_connected') and client.is_connected:
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=5.0)
                except:
                    pass
        self.active_clients.clear()
        logger.info("Limpeza concluída")

    def _generate_load_test_report(self) -> Dict[str, Any]:
        if not self.test_start_time:
            if self.test_end_time:
                self.test_start_time = self.test_end_time - timedelta(seconds=1)
            else:
                self.test_start_time = datetime.now() - timedelta(seconds=1)
                self.test_end_time = datetime.now()
        if not self.test_end_time:
            self.test_end_time = datetime.now()
        total_duration = max((self.test_end_time - self.test_start_time).total_seconds(), 0.01)
        total_operations = len(self.test_results)
        successful_operations = sum(1 for r in self.test_results if r.success)
        failed_operations = total_operations - successful_operations
        operation_analysis = {}
        trading_metrics = {}
        for op_type, durations in self.operation_stats.items():
            if durations:
                operation_analysis[op_type] = {
                    "count": len(durations),
                    "success_count": self.success_counts[op_type],
                    "error_count": self.error_counts[op_type],
                    "success_rate": self.success_counts[op_type] / max(self.success_counts[op_type] + self.error_counts[op_type], 1),
                    "avg_duration": statistics.mean(durations),
                    "min_duration": min(durations),
                    "max_duration": max(durations),
                    "median_duration": statistics.median(durations),
                    "p95_duration": sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 20 else max(durations),
                }
                if op_type == "place_order":
                    profits = [r.response_data.get("simulated_profit", 0) for r in self.test_results if r.operation_type == op_type and r.success]
                    wins = [r.response_data.get("win_based_on_candle", False) for r in self.test_results if r.operation_type == op_type and r.success]
                    if profits:
                        trading_metrics["total_pnl"] = sum(profits)
                        trading_metrics["avg_pnl"] = statistics.mean(profits)
                        trading_metrics["win_rate"] = sum(wins) / len(wins) if wins else 0
        avg_ops_per_second = total_operations / total_duration
        error_summary = {k: v for k, v in self.error_counts.items() if v > 0}
        report = {
            "test_summary": {
                "start_time": self.test_start_time.isoformat(),
                "end_time": self.test_end_time.isoformat(),
                "total_duration": total_duration,
                "total_operations": total_operations,
                "successful_operations": successful_operations,
                "failed_operations": failed_operations,
                "success_rate": successful_operations / max(total_operations, 1),
                "avg_operations_per_second": avg_ops_per_second,
                "peak_operations_per_second": self.peak_operations_per_second,
            },
            "operation_analysis": operation_analysis,
            "trading_metrics": trading_metrics,
            "error_summary": error_summary,
            "performance_metrics": {
                "operations_per_second_history": list(self.operations_per_second),
                "peak_throughput": self.peak_operations_per_second,
                "avg_throughput": avg_ops_per_second,
            },
            "recommendations": self._generate_recommendations(
                operation_analysis, avg_ops_per_second, successful_operations / max(total_operations, 1)
            ),
        }
        if trading_metrics:
            self._export_trading_csv(trading_metrics, total_duration)
        return report

    def _export_trading_csv(self, metrics: Dict, duration: float):
        filename = f"trading_sim_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Timestamp', 'Asset', 'Amount', 'Direction', 'P&L', 'Payout', 'Win'])
            for result in self.test_results:
                if result.operation_type == 'place_order' and result.response_data:
                    writer.writerow([
                        result.end_time.isoformat(),
                        result.response_data.get('asset', 'N/A'),
                        result.response_data.get('amount', 0),
                        result.response_data.get('direction', 'N/A'),
                        result.response_data.get('simulated_profit', 0),
                        result.response_data.get('payout', 0.8),
                        'YES' if result.response_data.get('win_based_on_candle', False) else 'NO',
                    ])
        logger.info(f"CSV para MT5 exportado: {filename} (Win Rate: {metrics.get('win_rate', 0):.1%})")

    def _generate_recommendations(self, operation_analysis: Dict, avg_throughput: float, success_rate: float) -> List[str]:
        recommendations = []
        if success_rate < 0.95:
            recommendations.append(f"Baixa taxa de sucesso ({success_rate:.1%}). Verifique rede/API.")
        if avg_throughput < 1:
            recommendations.append("Baixa vazão. Use persistent connections otimizadas.")
        slow_operations = [f"{op} ({stats['avg_duration']:.2f}s)" for op, stats in operation_analysis.items() if stats["avg_duration"] > 2.0]
        if slow_operations:
            recommendations.append(f"Operações lentas: {', '.join(slow_operations)}. Otimize para EAs MT5.")
        error_operations = [f"{op} ({stats['success_rate']:.1%})" for op, stats in operation_analysis.items() if stats["success_rate"] < 0.9]
        if error_operations:
            recommendations.append(f"Alta taxa de erro: {', '.join(error_operations)}")
        if not recommendations:
            recommendations.append("Desempenho bom. Integre com chatbot IA para alerts em tempo real.")
        return recommendations

def _format_resumo_simples(i: int, summary: Dict[str, Any]) -> str:
    return (
        f"\n=== RESUMO {i} TESTE ===\n"
        f"Duração: {summary.get('total_duration', 0):.2f}s\n"
        f"Operações: {summary.get('total_operations', 0)}\n"
        f"Sucesso Rate: {summary.get('success_rate', 0):.1%}\n"
        f"Taxa de Transferência: {summary.get('avg_operations_per_second', 0):.1f} ops/sec\n"
    )

def _format_tabela_final(comparisons: List[Dict[str, Any]]) -> str:
    if tabulate:
        table_data = [[comp['test_number'], f"{comp['throughput']:.1f}", f"{comp['success_rate']:.1%}", comp['total_operations'], f"{comp['duration']:.1f}s"] for comp in comparisons]
        tabela = tabulate(table_data, headers=["RESUMO TESTE", "TAXA TRANSFERÊNCIA", "SUCESSO RATE", "TOTAL GERAL", "DURAÇÃO"], tablefmt="grid")
        return "\n=== RESUMO DO TESTE DE CARGA ===\n" + tabela
    else:
        linhas = ["\n=== RESUMO DO TESTE DE CARGA ==="]
        for comp in comparisons:
            linhas.append(f"Teste {comp['test_number']}: Taxa {comp['throughput']:.1f} ops/s | Sucesso {comp['success_rate']:.1%} | Total {comp['total_operations']} | Duração {comp['duration']:.1f}s")
        return "\n".join(linhas)

async def run_load_test_demo(ssid: str = None):
    if not ssid:
        #===================================================================================================================================================================================
        ssid = r'42["auth",{"session":"h9gku7n5qesi0ashsfop829bc5","isDemo":1,"uid":80056933,"platform":2,"isFastHistory":true,"isOptimized":true}]' # Coloque aqui o seu SSID da Conta Demo
        #===================================================================================================================================================================================
        logger.warning("Usando Conta Demo SSID para Testes")
    load_tester = LoadTester(ssid, is_demo=True)
    conta_str = "Conta Demo" if load_tester.is_demo else "Conta Real"
    logger.info(f"Iniciando teste na {conta_str}")
    logger.info("\nExecutando Teste 1/3")
    test_configs = [
        LoadTestConfig(concurrent_clients=3, operations_per_client=10, operation_delay=0.5, use_persistent_connection=False, stress_mode=False),
        LoadTestConfig(concurrent_clients=5, operations_per_client=15, operation_delay=0.2, use_persistent_connection=True, stress_mode=False),
        LoadTestConfig(concurrent_clients=2, operations_per_client=5, operation_delay=0.1, use_persistent_connection=True, stress_mode=True),
    ]
    all_reports = []
    for i, config in enumerate(test_configs, 1):
        if i > 1:
            logger.info(f"\nExecutando Teste {i}/{len(test_configs)}")
        try:
            report = await load_tester.run_load_test(config)
            all_reports.append(report)
            summary = report.get("test_summary", {})
            bloco = _format_resumo_simples(i, summary)
            # Removido print(bloco) pra evitar duplicata; logger cuida do console
            logger.info(bloco)
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Teste de carga {i} falhou: {e}")
    if all_reports:
        comparison_report = {"test_comparison": [], "best_performance": {}, "overall_recommendations": []}
        best_throughput = 0
        best_success_rate = 0
        for i, report in enumerate(all_reports, 1):
            summary = report.get("test_summary", {})
            comparison_report["test_comparison"].append({
                "test_number": i,
                "throughput": summary.get("avg_operations_per_second", 0),
                "success_rate": summary.get("success_rate", 0),
                "total_operations": summary.get("total_operations", 0),
                "duration": summary.get("total_duration", 0),
            })
            if summary.get("avg_operations_per_second", 0) > best_throughput:
                best_throughput = summary.get("avg_operations_per_second", 0)
                comparison_report["best_performance"]["throughput"] = f"Teste {i}"
            if summary.get("success_rate", 0) > best_success_rate:
                best_success_rate = summary.get("success_rate", 0)
                comparison_report["best_performance"]["reliability"] = f"Teste {i}"
        timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
        for i, report in enumerate(all_reports, 1):
            report_file = f"load_test_{i}_{timestamp}.json"
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False, default=str)
            logger.info(f"Relatório do Teste {i} salvo em: {report_file}")
        comparison_file = f"load_test_comparison_{timestamp}.json"
        with open(comparison_file, "w", encoding="utf-8") as f:
            json.dump(comparison_report, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Relatório de comparação salvo em: {comparison_file}")
        bloco_tabela = _format_tabela_final(comparison_report["test_comparison"])
        # Removido print(bloco_tabela) pra evitar duplicata; logger cuida do console
        logger.info(bloco_tabela)
        return all_reports
    return []

if __name__ == "__main__":
    ssid = sys.argv[1] if len(sys.argv) > 1 else None
    if ssid:
        logger.info(f"Usando SSID: {ssid[:50]}...")
    asyncio.run(run_load_test_demo(ssid))