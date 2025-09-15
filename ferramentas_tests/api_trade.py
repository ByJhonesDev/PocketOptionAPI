"""
# Autor: ByJhonesDev
# Projeto: Exemplo de Ordem — API Async PocketOption
# Função: Inicialização simples do cliente e envio de 1 ordem (CALL/PUT)
# Descrição:
# - Solicita SSID, conecta via `AsyncPocketOptionClient` (conta demo por padrão)
# - Lê do usuário o valor a investir, o símbolo (ex.: EURUSD_otc) e a direção (CALL/PUT)
# - Envia a ordem com duração de 60s e exibe o resultado
# - Mensagens (logs) em PT-BR, incluindo sucesso e tratamento de erros
#
# Entradas/I/O:
# - Entrada: SSID (stdin), valor a investir (float), símbolo/ativo (string), direção (CALL/PUT)
# - Saída: prints em PT-BR sobre conexão, resultado da ordem e desconexão
#
# Dependências:
# - Python 3.10+
# - pocketoptionapi_async (AsyncPocketOptionClient, OrderDirection)
#
# Observações:
# - SSID é sensível: NÃO faça commit de SSIDs em repositórios.
# - `enable_logging=False` no cliente para reduzir verbosidade do SDK (padrão aqui).
# - Use conta demo para testes antes de operar com conta real.
"""

from pocketoptionapi_async import AsyncPocketOptionClient, OrderDirection

def _parse_direction(user_text: str):
    """
    Converte a entrada do usuário para OrderDirection.
    Aceita: CALL, PUT, COMPRA, VENDA, C, P, BUY, SELL (case-insensitive).
    """
    t = user_text.strip().upper()
    if t in {"CALL", "COMPRA", "C", "BUY"}:
        return OrderDirection.CALL
    if t in {"PUT", "VENDA", "P", "SELL"}:
        return OrderDirection.PUT
    return None

async def main():
    # --- Entradas do usuário (mensagens/logs traduzidas) ---
    SSID = input("Digite seu SSID: ").strip()
    if not SSID:
        print("SSID Vazio. Encerrando.")
        return

    client = AsyncPocketOptionClient(SSID, is_demo=True, enable_logging=False)

    # Conexão
    print("Conectando à PocketOption...")
    await client.connect()

    # Exemplo de envio de uma ordem CALL/PUT
    try:
        amount_str = input("Digite o valor a investir: ").strip()
        try:
            amount = float(amount_str.replace(",", "."))
        except ValueError:
            print("Valor inválido. Use números (Ex.: 1.0).")
            return

        symbol = input("Digite o símbolo (Ex.: 'EURUSD_otc'): ").strip()
        if not symbol:
            print("Símbolo vazio. Encerrando.")
            return

        dir_text = input("Digite a direção (CALL/PUT ou COMPRA/VENDA): ").strip()
        direction = _parse_direction(dir_text)
        if direction is None:
            print("Direção inválida. Use CALL/PUT, COMPRA/VENDA, C/P, BUY/SELL.")
            return

        print(f"Enviando Ordem: Ativo={symbol}, Valor={amount}, Direção={direction.name}, Duração= 60s...")

        order = await client.place_order(
            asset=symbol,
            amount=amount,
            direction=direction,
            duration=60
        )

        if order:
            print(
                f"✅ Ordem Enviada com Sucesso! "
                f"id={order.order_id}, valor={order.amount}, direção={order.direction}, duração={order.duration}s"
            )
        else:
            print("⚠️ Falha: A Plataforma não retornou os Dados da ordem.")
    except Exception as e:
        print(f"❌ Ocorreu um erro ao Enviar a Ordem: {e}")
    finally:
        # Desconexão
        print("Desconectando...")
        await client.disconnect()
        print("Conexão encerrada.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
