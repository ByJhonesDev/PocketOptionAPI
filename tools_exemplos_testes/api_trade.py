r"""
# Autor: ByJhonesDev
#
# Projeto: Exemplo de Ordem — API Async PocketOption
#
# Função Geral:
# - Conecta em conta DEMO usando SSID 
# - Obter saldo e dados de mercado (velas)
# - Enviar 1 ordem automática (CALL por padrão) com duração de 60s, aguardar expiração e calcular lucro real.
# - Salvar o resultado no arquivo de histórico.
# - Converter automaticamente booleanos para “Sim/Não” nas Estatísticas de Conexão.
#
# Principais Características do Log:
# - Sessões: Resultados anteriores, Autenticação e Conexão, Dados de Mercado (Última Vela),
#   Estatísticas de Conexão (True/False → Sim/Não), Operações Automáticas e Finalização.
#
# Entradas/Saídas:
# - Entradas: nenhuma via stdin (SSID é fixo no código; ativo, valor, direção e duração via constantes).
# - Saídas: prints estruturados em PT-BR e gravação de uma linha por operação no arquivo de resultados.
#
# Configurações Importantes:
# - SSID_FIXO: SSID DEMO já definido no código.
# - LOGS_DIR / RESULTADOS_FILE: caminhos de logs/resultados.
# - ASSET, AMOUNT, DIRECTION, DURATION, MAX_RETRIES: parâmetros da ordem.
#
# Dependências:
# - Python 3.10+
# - pocketoptionapi_async (AsyncPocketOptionClient, OrderDirection)
# - pandas
#
# Segurança:
# - SSID é sensível. Evite publicar/commitar este arquivo com SSID real.
# - Operar sempre em conta DEMO para testes antes de qualquer uso real.
#
# Observações:
# - O SDK interno do cliente foi mantido com enable_logging=False para reduzir ruído.
# - O cálculo de lucro real usa a diferença de saldo após a expiração.
# - Caso o check_win atinja timeout, o log informa e mantém o fluxo com o lucro calculado.
"""

from pocketoptionapi_async import AsyncPocketOptionClient, OrderDirection
import asyncio
import pandas as pd
import os
from datetime import datetime

# =========================
# Configurações Fixas
# =========================
SSID_FIXO = '42["auth",{"session":"h9gku7n5qesi0ashsfop829bc5","isDemo":1,"uid":80056933,"platform":2,"isFastHistory":true,"isOptimized":true}]'  # SSID da conta DEMO
LOGS_DIR = r'C:\JhonesProIABoT\Logs'  # Pasta onde os logs serão salvos
RESULTADOS_FILE = os.path.join(LOGS_DIR, 'resultados_gerais_pkt.txt')
ASSET = 'AUDCAD_otc'
AMOUNT = 1000.0         # Valor da entrada (USD)
DIRECTION = OrderDirection.CALL
DURATION = 60           # em segundos
MAX_RETRIES = 3

# Cria diretório se não existir
os.makedirs(LOGS_DIR, exist_ok=True)

# =========================
# Utilidades de Log / Formatação
# =========================
def bool_pt(v):
    """Converte True/False para Sim/Não, preservando outros valores."""
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    return v

def load_resultados():
    """Carrega resultado anterior (última linha) para exibir no cabeçalho."""
    if os.path.exists(RESULTADOS_FILE):
        with open(RESULTADOS_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return lines[-1].strip() if lines else "Nenhum resultado anterior."
    return "Arquivo de resultados não encontrado."

def save_resultados(resultado_str):
    """Salva novo resultado no arquivo (append)."""
    with open(RESULTADOS_FILE, 'a', encoding='utf-8') as f:
        timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        f.write(f"[{timestamp}] {resultado_str}\n")
    print(f"✅ Resultados salvos em: {RESULTADOS_FILE}")

def get_resultado_final(calculated_profit, win_result, status):
    """Determina Vitória/Derrota baseado no lucro calculado, win_result ou status."""
    if calculated_profit > 0:
        return "Vitória"
    elif calculated_profit < 0:
        return "Derrota"
    elif status in ('won', 'win'):
        return "Vitória"
    elif status in ('loss', 'lost'):
        return "Derrota"
    elif status in ('active', 'pending'):
        return "Pendente"
    else:
        # win_result pode ser numérico em algumas libs
        try:
            if win_result is not None:
                if float(win_result) > 0:
                    return "Vitória"
                if float(win_result) < 0:
                    return "Derrota"
        except Exception:
            pass
        return "Empate/Indefinido"

def format_dt_full(dt):
    """Formata datetime para DD-MM-YYYY HH:MM:SS; aceita datetime ou texto."""
    if isinstance(dt, datetime):
        return dt.strftime("%d-%m-%Y %H:%M:%S")
    return str(dt)

# =========================
# Funções assíncronas de API
# =========================
async def get_balance(client):
    try:
        balance = await client.get_balance()
        return balance.balance, balance.currency
    except Exception as e:
        print(f"❌ Erro ao obter saldo: {e}")
        return 0.0, 'USD'

async def get_candles(client, asset=ASSET, timeframe=60):
    try:
        candles = await client.get_candles(asset=asset, timeframe=timeframe)
        if candles:
            ultima_vela = candles[0]  # geralmente a mais recente
            return len(candles), ultima_vela
        return 0, None
    except Exception as e:
        print(f"❌ Erro ao obter velas: {e}")
        return 0, None

async def get_candles_dataframe(client, asset=ASSET, timeframe=60):
    try:
        df = await client.get_candles_dataframe(asset=asset, timeframe=timeframe)
        return df
    except Exception as e:
        print(f"❌ Erro ao obter DataFrame de velas: {e}")
        return pd.DataFrame()

async def get_active_orders(client):
    try:
        orders = await client.get_active_orders()
        return orders
    except Exception as e:
        print(f"❌ Erro ao obter ordens ativas: {e}")
        return []

async def place_order(client, symbol=ASSET, amount=AMOUNT, direction=DIRECTION, duration=DURATION, max_retries=MAX_RETRIES):
    for attempt in range(max_retries):
        try:
            print("\n🚀 Operações Automáticas")
            print("----------------------------------------")
            print(f"📤 Enviando Ordem Automática (Tentativa {attempt+1}/{max_retries})")
            print(f"   💹 Ativo: {symbol}")
            print(f"   💵 Valor: ${amount}")
            print(f"   🎯 Direção: {direction.name}")
            print(f"   ⏱️  Duração: {duration} Segundos")
            order = await client.place_order(asset=symbol, amount=amount, direction=direction, duration=duration)
            if order and not getattr(order, 'error_message', None):
                print("✅ Ordem Enviada com Sucesso!")
                return order
            else:
                error_msg = getattr(order, 'error_message', 'Erro desconhecido')
                print(f"⚠️ Tentativa {attempt+1} falhou: {error_msg}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
        except Exception as e:
            print(f"❌ Erro na tentativa {attempt+1}: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
    print("❌ Todas as tentativas de envio falharam.")
    return None

async def check_order_result_with_timeout(client, order_id, timeout=30):
    try:
        result = await asyncio.wait_for(client.check_order_result(order_id), timeout=timeout)
        return result
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        print(f"❌ Erro no check_order_result: {e}")
        return None

async def wait_for_expiry_and_check(client, order_id, initial_balance, duration=DURATION):
    """Espera expirar + buffer, checa resultado e calcula lucro via diferença de saldo."""
    buffer_s = 30
    print(f"⏳ Aguardando Expiração da Negociação ({duration + buffer_s}s)...")
    await asyncio.sleep(duration + buffer_s)

    print("🔄 Verificando Resultado Final...")
    final_result = await check_order_result_with_timeout(client, order_id)

    win_result = None
    try:
        win_result = await asyncio.wait_for(client.check_win(order_id), timeout=30)
        if win_result is not None:
            print(f"🏁 Verificação de Win concluída: {win_result}")
    except asyncio.TimeoutError:
        print(" ")
    except Exception as e:
        print(f"❌ Erro no check_win: {e}")

    # Calcula lucro real via variação de saldo
    final_balance, _ = await get_balance(client)
    calculated_profit = round(final_balance - initial_balance, 2)
    print(f"💰 Saldo: Inicial=${initial_balance} | Final=${final_balance} | Lucro/Prejuízo=${calculated_profit}")

    status = getattr(final_result, 'status', 'N/A') if final_result else 'N/A'
    resultado = get_resultado_final(calculated_profit, win_result, status)
    print(f"📊 Resultado Final: {resultado} (Lucro Real: ${calculated_profit})")

    return final_result, win_result, calculated_profit

def get_connection_stats(client):
    try:
        stats = client.get_connection_stats()
        return stats
    except Exception as e:
        print(f"❌ Erro nas estatísticas de conexão: {e}")
        return {}

# =========================
# Impressão do Log (Formato PT-BR com Emojis)
# =========================
def print_header():
    print("🤖 Bem-vindos ao JhonesProIA 🤖")
    print("🟢 Inicializando JhonesProPocketBoT...")
    print("✅ JhonesProPocketBoT e API PocketOption inicializados com sucesso!\n")

    print("📂 Resultados")
    print("----------------------------------------")
    prev_result = load_resultados()
    print(f"📂 Resultados carregados de: {RESULTADOS_FILE}")
    # Se a última linha já incluir timestamp, mantenha como está; caso contrário, apresente simples:
    print(f"{prev_result}\n")

    print("🔐 Autenticação e Conexão")
    print("----------------------------------------")
    print(f"🔑 SSID Utilizado: CONTA DEMO")
    print("🌐 Conectando à PocketOption...")
    print("✅ Conectado com Sucesso!")

def print_saldo(saldo, moeda):
    print(f"💰 Saldo Atual: ${saldo} {moeda}")

def print_dados_mercado(total_candles, ultima_vela):
    print("\n📊 Dados de Mercado")
    print("----------------------------------------")
    print(f"🔢 Total de Velas: {total_candles}")
    if ultima_vela:
        # Algumas libs usam atributos diferentes; ajuste se necessário
        o = getattr(ultima_vela, 'open', None)
        c = getattr(ultima_vela, 'close', None)
        h = getattr(ultima_vela, 'high', None)
        l = getattr(ultima_vela, 'low', None)
        ts = getattr(ultima_vela, 'timestamp', None)
        print("🕯️ Informações da Última Vela:")
        print(f"   📈 Abertura: {o}")
        print(f"   📉 Fechamento: {c}")
        print(f"   ⤴️  Máxima: {h}")
        print(f"   ⤵️  Mínima: {l}")
        print(f"   🕒 Horário: {ts}")

def print_stats(stats):
    print("\n📡 Estatísticas de Conexão")
    print("----------------------------------------")
    if not stats:
        print("❌ Sem estatísticas disponíveis.")
        return

    total_connections = stats.get('total_connections', 'N/A')
    successful_connections = stats.get('successful_connections', 'N/A')
    total_reconnects = stats.get('total_reconnects', 'N/A')
    last_ping_time = stats.get('last_ping_time', 'N/A')
    messages_sent = stats.get('messages_sent', 'N/A')
    messages_received = stats.get('messages_received', 'N/A')
    websocket_connected = bool_pt(stats.get('websocket_connected', 'N/A'))
    conn_info = stats.get('connection_info')

    connected_at = getattr(conn_info, 'connected_at', 'N/A') if conn_info else 'N/A'
    region = getattr(conn_info, 'region', 'N/A') if conn_info else 'N/A'

    print(f"🔗 Conexões Totais: {total_connections}")
    print(f"✅ Conexões Bem-Sucedidas: {successful_connections}")
    print(f"♻️  Total de Reconexões: {total_reconnects}")
    print(f"🕒 Horário do Último Ping: {last_ping_time}")
    print(f"✉️  Mensagens Enviadas/Recebidas: {messages_sent}/{messages_received}")
    print(f"🌐 WebSocket Conectado: {websocket_connected}")
    print(f"📅 Conectado em: {format_dt_full(connected_at)}")
    print(f"🌍 Região: {region}")

def print_operacao_registro(final_result, win_result, calculated_profit):
    status = getattr(final_result, 'status', 'N/A') if final_result else 'N/A'
    resultado = get_resultado_final(calculated_profit, win_result, status)
    print(f"\n📈 Registro da Operação")
    print("----------------------------------------")
    print(f"🏁 Resultado: {resultado} | 💹 Lucro Total: ${calculated_profit}")
    save_resultados(f"Lucro= ${calculated_profit}, Resultado= {resultado}")

def print_footer():
    print("\n🔚 Finalização")
    print("----------------------------------------")
    print("🔌 Desconectando...")
    print("✅ Conexão Encerrada com Sucesso.")

# =========================
# Fluxo Principal
# =========================
async def main():
    print_header()

    # Cliente com DEMO habilitado e logging interno desativado (logs customizados nossos)
    client = AsyncPocketOptionClient(SSID_FIXO, is_demo=True, enable_logging=False)

    # Conexão
    try:
        await client.connect()
    except Exception as e:
        print(f"❌ Erro na conexão: {e}")
        return

    # Saldo inicial
    initial_balance, moeda = await get_balance(client)
    print_saldo(initial_balance, moeda)

    # Dados de mercado
    total_candles, ultima_vela = await get_candles(client)
    print_dados_mercado(total_candles, ultima_vela)

    # (Opcional) DataFrame completo — não exibimos para não poluir o log
    _ = await get_candles_dataframe(client)

    # (Opcional) Ordens ativas — não exibidas
    _ = await get_active_orders(client)

    # Estatísticas de conexão
    stats = get_connection_stats(client)
    print_stats(stats)

    # Envio da ordem
    order = await place_order(client)
    if order:
        order_id = getattr(order, 'order_id', None) or getattr(order, 'id', None)
        final_result, win_result, calculated_profit = await wait_for_expiry_and_check(client, order_id, initial_balance)
        print_operacao_registro(final_result, win_result, calculated_profit)
    else:
        print("\n🚀 Operações Automáticas")
        print("----------------------------------------")
        print("❌ Nenhuma ordem enviada.")

    # Finalização
    print_footer()
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
