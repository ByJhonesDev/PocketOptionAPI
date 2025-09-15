"""
# Autor: ByJhonesDev
# Projeto: Testes de Performance — API Async PocketOption
# Função: Benchmark de conexão, ordens, leitura de dados e concorrência
# Descrição:
# - Cria a classe `PerformanceTester` para medir tempos e taxa de sucesso em:
#   1) Estabelecimento de conexão (várias iterações)
#   2) Colocação de ordens (mock real via conta demo/real)
#   3) Recuperação de dados (saldo, candles, ordens ativas)
#   4) Operações concorrentes (várias conexões em paralelo)
# - Gera um relatório consolidado (médias, mínimos, máximos, desvio padrão,
#   operações/segundo e taxa de sucesso) e salva em arquivo de texto.
# - Usa `loguru` para logging detalhado em PT-BR, com mensagens de sucesso/erro.
#
# Entradas/I/O:
# - SSID é carregado automaticamente de ./GET_SSID/SSID_DEMO.txt (ou outro nome),
#   com fallback hardcoded APENAS para testes locais (NÃO usar em produção).
# - Saída: Relatório salvo como "performance_da_api.txt" no diretório atual.
#
# Dependências:
# - Python 3.10+
# - loguru
# - pocketoptionapi_async  (AsyncPocketOptionClient, OrderDirection)
#
# Configurações principais:
# - `is_demo` (bool): define conta demo (True) ou real (False)
# - Iterações e níveis de concorrência são parametrizados nos métodos
#   (ex.: `test_connection_performance(iterations=5)`,
#         `test_order_placement_performance(iterations=10)`,
#         `test_concurrent_operations(concurrency_level=5)`).
#
# Observações importantes:
# - O SSID é sensível. Não faça commit do arquivo GET_SSID/* nem de fallbacks.
# - Testes de ordens em conta real podem gerar custos — use demo enquanto valida.
# - O ativo padrão do teste de ordens é "EURUSD_otc"; ajuste conforme necessário.
"""

import asyncio
import time
import statistics
import os
import sys
from typing import List, Dict, Any, Optional
from loguru import logger
from pocketoptionapi_async import AsyncPocketOptionClient, OrderDirection

# -------------------------
# Configurações de Teste de Ordem (fáceis de editar)
# -------------------------
ORDER_ASSET = "EURUSD_otc"
ORDER_AMOUNT = 1.0
ORDER_DURATION = 60  # segundos
ORDER_DIRECTION = OrderDirection.CALL


class PerformanceTester:
    """Ferramentas de teste de performance para a API async"""

    def __init__(self, ssid: str, is_demo: bool = True):
        self.ssid = ssid
        self.is_demo = is_demo
        self.results: Dict[str, List[float]] = {}

    async def test_connection_performance(
        self, iterations: int = 5
    ) -> Dict[str, float]:
        """Testa a performance de estabelecimento de conexão"""
        logger.info(f"Testando performance de conexão ({iterations} iterações)")
        connection_times: List[float] = []

        for i in range(iterations):
            start_time = time.time()
            client = AsyncPocketOptionClient(ssid=self.ssid, is_demo=self.is_demo)
            try:
                await client.connect()
                if getattr(client, "is_connected", False):
                    connection_time = time.time() - start_time
                    connection_times.append(connection_time)
                    logger.success(f"Conexão {i + 1}: {connection_time:.3f}s")
                else:
                    logger.warning(f"Conexão {i + 1}: Falhou")
            except Exception as e:
                logger.error(f"Conexão {i + 1}: Erro - {e}")
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                await asyncio.sleep(1)  # Pausa para resfriamento

        if connection_times:
            return {
                "avg_time": statistics.mean(connection_times),
                "min_time": min(connection_times),
                "max_time": max(connection_times),
                "std_dev": statistics.stdev(connection_times)
                if len(connection_times) > 1
                else 0.0,
                "success_rate": len(connection_times) / iterations * 100.0,
            }
        else:
            return {"success_rate": 0.0}

    async def test_order_placement_performance(
        self, iterations: int = 10
    ) -> Dict[str, float]:
        """Testa a performance de colocação de ordens"""
        logger.info(
            f"Testando performance de colocação de ordens ({iterations} iterações)"
        )
        client = AsyncPocketOptionClient(ssid=self.ssid, is_demo=self.is_demo)
        order_times: List[float] = []
        successful_orders = 0

        try:
            await client.connect()
            if not getattr(client, "is_connected", False):
                logger.error("Falha ao conectar para testes de ordens")
                return {"success_rate": 0.0}

            # Aguarda o saldo/handshake
            await asyncio.sleep(2)

            for i in range(iterations):
                start_time = time.time()
                try:
                    order = await client.place_order(
                        asset=ORDER_ASSET,
                        amount=ORDER_AMOUNT,
                        direction=ORDER_DIRECTION,
                        duration=ORDER_DURATION,
                    )
                    if order:
                        order_time = time.time() - start_time
                        order_times.append(order_time)
                        successful_orders += 1
                        logger.success(f"Ordem {i + 1}: {order_time:.3f}s")
                    else:
                        logger.warning(f"Ordem {i + 1}: Falhou (sem resposta)")
                except Exception as e:
                    logger.error(f"Ordem {i + 1}: Erro - {e}")
                await asyncio.sleep(0.1)  # Pequeno atraso entre ordens
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

        if order_times:
            mean_time = statistics.mean(order_times)
            return {
                "avg_time": mean_time,
                "min_time": min(order_times),
                "max_time": max(order_times),
                "std_dev": statistics.stdev(order_times) if len(order_times) > 1 else 0.0,
                "success_rate": successful_orders / iterations * 100.0,
                "orders_per_second": (1.0 / mean_time) if mean_time > 0 else 0.0,
            }
        else:
            return {"success_rate": 0.0}

    async def test_data_retrieval_performance(self) -> Dict[str, Dict[str, float]]:
        """Testa a performance de recuperação de dados"""
        logger.info("Testando performance de recuperação de dados")
        client = AsyncPocketOptionClient(ssid=self.ssid, is_demo=self.is_demo)

        async def _get_balance():
            return await client.get_balance()

        async def _get_candles():
            return await client.get_candles(ORDER_ASSET, 60, 100)

        async def _get_active_orders():
            return await client.get_active_orders()

        operations = {
            "balance": _get_balance,
            "candles": _get_candles,
            "active_orders": _get_active_orders,
        }
        results: Dict[str, Dict[str, float]] = {}

        try:
            await client.connect()
            if not getattr(client, "is_connected", False):
                logger.error("Falha ao conectar para testes de dados")
                return {}

            await asyncio.sleep(2)  # Aguarda inicialização

            for operation_name, operation in operations.items():
                times: List[float] = []
                for i in range(5):  # 5 iterações por operação
                    start_time = time.time()
                    try:
                        await operation()
                        operation_time = time.time() - start_time
                        times.append(operation_time)
                        logger.success(f"{operation_name} {i + 1}: {operation_time:.3f}s")
                    except Exception as e:
                        logger.error(f"{operation_name} {i + 1}: Erro - {e}")
                    await asyncio.sleep(0.1)

                if times:
                    results[operation_name] = {
                        "avg_time": statistics.mean(times),
                        "min_time": min(times),
                        "max_time": max(times),
                    }
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

        return results

    async def test_concurrent_operations(
        self, concurrency_level: int = 5
    ) -> Dict[str, Any]:
        """Testa a performance de operações concorrentes"""
        logger.info(
            f"Testando operações concorrentes (nível de concorrência: {concurrency_level})"
        )

        async def perform_operation(operation_id: int) -> Dict[str, Any]:
            client = AsyncPocketOptionClient(ssid=self.ssid, is_demo=self.is_demo)
            start_time = time.time()
            try:
                await client.connect()
                if getattr(client, "is_connected", False):
                    balance = await client.get_balance()
                    operation_time = time.time() - start_time
                    return {
                        "operation_id": operation_id,
                        "success": True,
                        "time": operation_time,
                        "balance": getattr(balance, "balance", None) if balance else None,
                    }
                else:
                    return {
                        "operation_id": operation_id,
                        "success": False,
                        "time": time.time() - start_time,
                        "error": "Conexão falhou",
                    }
            except Exception as e:
                return {
                    "operation_id": operation_id,
                    "success": False,
                    "time": time.time() - start_time,
                    "error": str(e),
                }
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass

        start_time = time.time()
        tasks = [perform_operation(i) for i in range(concurrency_level)]
        results: List[Any] = await asyncio.gather(*tasks, return_exceptions=True)
        total_time = time.time() - start_time

        successful_operations = [
            r for r in results if isinstance(r, dict) and r.get("success")
        ]
        failed_operations = [
            r for r in results if not (isinstance(r, dict) and r.get("success"))
        ]

        if successful_operations:
            operation_times = [r["time"] for r in successful_operations]
            return {
                "total_time": total_time,
                "success_rate": len(successful_operations) / concurrency_level * 100.0,
                "avg_operation_time": statistics.mean(operation_times),
                "min_operation_time": min(operation_times),
                "max_operation_time": max(operation_times),
                "std_dev_operation_time": statistics.stdev(operation_times)
                if len(operation_times) > 1
                else 0.0,
                "operations_per_second": len(successful_operations) / total_time
                if total_time > 0
                else 0.0,
                "failed_count": len(failed_operations),
            }
        else:
            return {
                "total_time": total_time,
                "success_rate": 0.0,
                "failed_count": len(failed_operations),
            }

    async def generate_performance_report(self) -> str:
        """Gera relatório abrangente de performance"""
        logger.info("Iniciando testes de performance abrangentes...")
        report: List[str] = []
        report.append("=" * 60)
        report.append("RELATÓRIO DE PERFORMANCE DA API ASYNC DA POCKETOPTION")
        report.append("=" * 60)
        report.append("")

        # Teste 1: Performance de Conexão
        report.append("Conexão: PERFORMANCE DE CONEXÃO")
        report.append("-" * 30)
        try:
            conn_results = await self.test_connection_performance()
            if conn_results.get("success_rate", 0.0) > 0.0:
                report.append(
                    f"Sucesso: Tempo Médio de Conexão: {conn_results['avg_time']:.3f}s"
                )
                report.append(
                    f"Sucesso: Tempo Mínimo de Conexão: {conn_results['min_time']:.3f}s"
                )
                report.append(
                    f"Sucesso: Tempo Máximo de Conexão: {conn_results['max_time']:.3f}s"
                )
                report.append(
                    f"Sucesso: Desvio Padrão: {conn_results['std_dev']:.3f}s"
                )
                report.append(
                    f"Sucesso: Taxa de Sucesso: {conn_results['success_rate']:.1f}%"
                )
            else:
                report.append("Erro: Testes de conexão falharam")
        except Exception as e:
            report.append(f"Erro: Erro no teste de conexão: {e}")
        report.append("")

        # Teste 2: Performance de Recuperação de Dados
        report.append("Estatísticas: PERFORMANCE DE RECUPERAÇÃO DE DADOS")
        report.append("-" * 35)
        try:
            data_results = await self.test_data_retrieval_performance()
            op_translations = {
                "balance": "BALANÇO",
                "candles": "CANDLES | VELAS",
                "active_orders": "ORDENS ATIVAS",
            }
            for operation, stats in data_results.items():
                translated_op = op_translations.get(operation, operation.upper())
                report.append(f" {translated_op}:")
                report.append(f"  Média: {stats['avg_time']:.3f}s")
                report.append(
                    f"  Faixa: {stats['min_time']:.3f}s - {stats['max_time']:.3f}s"
                )
        except Exception as e:
            report.append(f"Erro: Erro no teste de recuperação de dados: {e}")
        report.append("")

        # Teste 3: Operações Concorrentes
        report.append("Performance: OPERAÇÕES CONCORRENTES")
        report.append("-" * 25)
        try:
            concurrent_results = await self.test_concurrent_operations()
            if concurrent_results.get("success_rate", 0.0) > 0.0:
                report.append(
                    f"Sucesso: Taxa de Sucesso: {concurrent_results['success_rate']:.1f}%"
                )
                report.append(
                    f"Sucesso: Operações/Segundo: {concurrent_results['operations_per_second']:.2f}"
                )
                report.append(
                    f"Sucesso: Tempo Médio de Operação: {concurrent_results['avg_operation_time']:.3f}s"
                )
                report.append(
                    f"Sucesso: Desvio Padrão das Operações: {concurrent_results['std_dev_operation_time']:.3f}s"
                )
                report.append(
                    f"Sucesso: Tempo Total: {concurrent_results['total_time']:.3f}s"
                )
                report.append(f"Falhas: {concurrent_results['failed_count']}")
            else:
                report.append("Erro: Operações concorrentes falharam")
        except Exception as e:
            report.append(f"Erro: Erro no teste concorrente: {e}")
        report.append("")
        report.append("=" * 60)
        report.append(
            f"Relatório gerado com sucesso em: {time.strftime('%d-%m-%Y %H:%M:%S')}"
        )
        report.append("=" * 60)
        return "\n".join(report)


def load_ssid_from_file(filename: str, is_demo: bool) -> str:
    """
    Carrega o SSID do arquivo especificado na pasta GET_SSID.

    Args:
        filename: Nome do arquivo (ex: 'SSID_DEMO.txt' ou 'SSID_REAL.txt').
        is_demo: Indica se é para conta demo (True) ou real (False).

    Returns:
        str: O conteúdo do SSID extraído do arquivo.

    Raises:
        FileNotFoundError: Se o arquivo não existir.
        ValueError: Se o arquivo estiver vazio ou inválido.
    """
    profile_dir = os.path.join(os.getcwd(), "GET_SSID")
    file_path = os.path.join(profile_dir, filename)

    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"Arquivo SSID não encontrado: {file_path}. Execute o script de extração primeiro!"
        )

    with open(file_path, "r", encoding="utf-8") as f:
        ssid_content = f.read().strip()

    if not ssid_content:
        raise ValueError(
            f"Arquivo {filename} está vazio. Verifique a extração do SSID."
        )

    logger.info(
        f"SSID carregado com sucesso de {filename} para {'conta demo' if is_demo else 'conta real'}."
    )
    return ssid_content


async def main():
    """Executa testes de performance"""
    # Configurações para carregar SSID dos arquivos extraídos - APENAS PARA CONTA DEMO
    is_demo = True
    filename = "SSID_DEMO.txt"

    try:
        ssid = load_ssid_from_file(filename, is_demo)
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"Erro ao carregar SSID: {e}")
        logger.warning(
            "Usando SSID hardcoded de fallback para testes (não recomendado para produção)."
        )
        # Fallback para demo
        ssid = r'42["auth",{"session":"","isDemo":1,"uid":,"platform":,"isFastHistory":,"isOptimized":}]' # Coloque aqui seu SSID_DEMO

    tester = PerformanceTester(
        ssid=ssid,
        is_demo=is_demo,
    )
    report = await tester.generate_performance_report()

    # Print com encoding UTF-8 e flush para console limpo
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Python 3.7+
    except Exception:
        pass
    print(report, flush=True)

    # Salva relatório em arquivo com UTF-8 (nome corrigido)
    with open("performance_da_api.txt", "w", encoding="utf-8") as f:
        f.write(report)
    logger.success("Arquivo salvo com sucesso em performance_da_api.txt")


if __name__ == "__main__":
    asyncio.run(main())
