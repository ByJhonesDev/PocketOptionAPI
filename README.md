# 🚀 PocketOption API

[![GitHub](https://img.shields.io/badge/GitHub-ByJhonesDev-blue?style=flat-square&logo=github)](https://github.com/ByJhones)
[![Telegram](https://img.shields.io/badge/Telegram-@traderjhonesofc-blue?style=flat-square&logo=telegram)](https://t.me/jc_jhones_oficial)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/Python-3.12.7-blue?style=flat-square)](https://www.python.org)

> Uma API Python robusta e moderna para integração com a PocketOption, oferecendo uma interface limpa e eficiente para Automação de Operações.

![Preview da API](pocketoption.png)

## ✨ Destaques 

- 🔐 **Autenticação Segura**: Login Via SSID e Gerenciamento de Sessão Robusto
- 💹 **Trading Automatizado**: Operações de Compra e Venda Programáticas
- 📊 **Dados em Tempo Real**: WebSocket para Cotações e Operações
- 📈 **Análise Técnica**: Acesso a Dados Históricos e Indicadores
- 🛡️ **Estabilidade**: Reconexão Automática e Tratamento de Erros
- 🔄 **Versátil**: Suporte a Conta de Demonstração e Real

## 🛠️ Instalação

> **Nota**: Recomenda-se atualizar o `pip` antes de instalar as dependências para garantir compatibilidade:
> ```bash
> python -m pip install --upgrade pip
> ```

### Via pip (Recomendado):
```bash
pip install git+https://github.com/ByJhonesDev/PocketOptionAPI.git
```

### Para Desenvolvimento:
```bash
git clone https://github.com/ByJhonesDev/PocketOptionAPI.git
cd PocketOptionAPI
pip install -e .
```

## 📖 Uso Básico

Esta seção demonstra como integrar a API de forma assíncrona para operações essenciais no PocketOption. A API é projetada para alta performance em cenários de trading automatizado, com suporte a reconexão automática, keep-alive e monitoramento de erros — ideal para bots de scalping em MT4/MT5 ou dashboards full-stack com chatbots de IA.

### Instalação

Instale via pip diretamente do repositório GitHub:

```bash
pip install git+https://github.com/ByJhonesDev/PocketOptionAPI.git
```

### Inicialização e Conexão

Crie um cliente assíncrono com SSID (session ID). Use Modo Demo para testes. A conexão é WebSocket com fallback de regiões e reconexão automática.

```python
import asyncio
from pocketoptionapi_async.client import AsyncPocketOptionClient
from pocketoptionapi_async.utils import format_session_id  # Para formatar SSID

async def basic_connection():
    # SSID de exemplo (demo). Substitua SSID que foi gerado com tools_ferramentas - SSID_DEMO.txt
    session_id = "your_demo_session_id_here"  # Ou capture via login e-mail/senha
    ssid = format_session_id(
        session_id=session_id,
        is_demo=True,  # True para Conta Demo, False para Conta Real
        uid=0,  # Seu user ID
        platform=1,  # 1=web, 3=mobile
        is_fast_history=True  # Carregamento rápido de Histórico
    )
    
    # Inicialize o Cliente com Keep-Alive e Reconexão
    client = AsyncPocketOptionClient(
        ssid=ssid,
        is_demo=True,
        persistent_connection=True,  # Ativa Keep-Alive
        auto_reconnect=True,
        enable_logging=True  # Logs detalhados para Debug
    )
    
    # Conecte (Com Fallback de Regiões Automáticas)
    success = await client.connect()
    if success:
        print("Conectado com Sucesso!")
        # Adicione callback para eventos (Ex.: Atualizações de Saldo)
        def on_balance_update(data):
            print(f"Saldo Atualizado: {data.get('balance', 'N/A')}")
        client.add_event_callback("balance_updated", on_balance_update)
    else:
        print("Falha na Conexão. Verifique SSID e a sua Rede.")
    
    # Desconecte ao Final
    await client.disconnect()

# Rode o exemplo
asyncio.run(basic_connection())
```

**Dicas para Mercado Financeiro**: Integre com MT4/MT5 para sincronizar tempo do servidor (`await client.get_server_time()`) e evitar drifts em indicadores como RSI ou MACD.

### Obter Saldo da Conta

Recupere o Saldo Atual (Retorna objeto `Balance` com validação Pydantic).

```python
async def get_balance_example(client: AsyncPocketOptionClient):
    try:
        balance = await client.get_balance()
        print(f"Saldo Conta Real: {balance.balance} {balance.currency} (Saldo Conta Demo: {balance.is_demo})")
    except Exception as e:
        print(f"Erro ao obter saldo: {e}")

# Integre no loop principal
await get_balance_example(client)
```

### Obter Dados de Candles | Velas (Histórico OHLC | GRÁFICO)

Baixe candles | velas para análise técnica. Use timeframes em segundos (de `constants.TIMEFRAMES`).

```python
from pocketoptionapi_async.constants import ASSETS, TIMEFRAMES  # Assets e timeframes pré-definidos

async def get_candles_example(client: AsyncPocketOptionClient):
    asset = "EURUSD"  # Ou ASSETS["EURUSD_otc"] para OTC
    timeframe = TIMEFRAMES["1m"]  # 60 segundos (M1)
    count = 50  # Últimos 50 candles
    
    try:
        candles = await client.get_candles(asset, timeframe, count)
        print(f"{len(candles)} candles obtidos para {asset} (M1)")
        
        # Converta para DataFrame para análise (útil em indicadores MT5)
        from pocketoptionapi_async.utils import candles_to_dataframe
        df = candles_to_dataframe(candles)
        print(df.tail())  # Últimos 5 candles | velas
        print(f"Tendência: {df['close'].iloc[-1] > df['open'].iloc[-1] e 'Alta' ou 'Baixa'}")
        
    except Exception as e:
        print(f"Erro ao obter candles | velas: {e}")

await get_candles_example(client)
```

**Integração com Indicadores MT4/MT5**: Use `df` para calcular RSI ou Bollinger Bands via `pandas_ta` e sincronizar com `MetaTrader5.copy_rates_from_pos()`.

### Colocar Ordem (Trade | Compra ou Venda)

Simule ou execute uma ordem (Conta Demo para sua segurança). Use direção "Call" (Compra) ou "Put" (Venda).

```python
from pocketoptionapi_async.models import OrderDirection  # Ou str: ""Call" (Compra) ou "Put" (Venda)"

async def place_order_example(client: AsyncPocketOptionClient):
    asset = "EURUSD"
    amount = 5.0  # Valor em USD
    direction = "call"  # Ou OrderDirection.CALL
    duration = 60  # 1 minuto em segundos
    
    try:
        result = await client.buy(amount, asset, direction, duration)
        if result and result.get("success", False):
            print(f"Ordem Colocada! ID: {result.get('order_id')}, Profit Potencial: {result.get('payout', 0)}%")
        else:
            print(f"Falha na Ordem: {result.get('error_message', 'Desconhecido')}")
    except Exception as e:
        print(f"Erro na Ordem: {e}")

await place_order_example(client)
```

**Aviso de Risco**: Sempre teste em  Conta Demo.

### Monitoramento e Keep-Alive

Para Conexões Persistentes (Ex.: Streams em Tempo Real para Chatbots de IA):

```python
from pocketoptionapi_async.connection_keep_alive import ConnectionKeepAlive

async def keep_alive_example():
    keep_alive = ConnectionKeepAlive(ssid, is_demo=True)
    success = await keep_alive.start_persistent_connection()
    if success:
        # Envie ping periódico
        await keep_alive.send_message('42["ps"]')
        # Monitore stats
        stats = keep_alive.get_connection_stats()
        print(f"Conexão ativa: {stats['is_connected']}, Uptime: {stats['uptime']}")
    await keep_alive.stop_persistent_connection()

asyncio.run(keep_alive_example())
```

Para monitoramento avançado, use `ErrorMonitor` e `HealthChecker` de `monitoring.py` — perfeito para Dashboards full-stack com alertas em tempo real.

## 🎯 Recursos Avançados

### WebSocket em Tempo Real
```python
# Callback para Preços em Tempo Real
@api.on_price_update
def price_handler(data):
    print(f"📊 {data['asset']}: ${data['price']}")

# Callback para Resultados de Operações
@api.on_trade_complete
def trade_handler(result):
    print(f"💫 Resultado: {'✅ Vitória' if result['win'] else '❌ Derrota'}")
```

### Análise Técnica
```python
# Obter histórico de candles
candles = api.get_candles(
    asset="EURUSD_OTC",  # Note o sufixo _OTC para ativos OTC
    interval=60,         # Intervalo em segundos
    count=100           # Quantidade de candles
)

# Análise dos Dados
import pandas as pd
df = pd.DataFrame(candles)
print(f"📈 Média Móvel: {df['close'].rolling(20).mean().iloc[-1]:.5f}")
```

## 🔧 Configuração

### Dependências Principais
```txt
aiohttp>=3.8.0
certifi==2025.6.15
charset-normalizer==3.4.2
colorama==0.4.6
idna==3.10
loguru>=0.7.2
numpy==2.3.1
pandas>=2.3.0
psutil>=5.9.0
pydantic>=2.0.0
python-dateutil>=2.9.0.post0
python-dotenv>=1.0.0
pytz==2025.2
requests==2.32.4
rich>=13.0.0
selenium>=4.0.0
setuptools==80.9.0
six==1.17.0
typing-extensions>=4.0.0
tzdata==2025.2
tzlocal>=5.3.1
urllib3==2.5.0
webdriver-manager>=4.0.0
websocket-client==1.8.0
websockets>=15.0.1
wheel==0.45.1
```

### Obtendo o SSID
Para usar a API com Dados Reais, você precisa Extrair seu ID de Sessão do Navegador:

1. **Abra a PocketOption no seu navegador**
2. **Abra as Ferramentas do Desenvolvedor (F12)**
3. **Vá para a aba Network (Rede)**
4. **Filtre por WebSocket (WS)**
5. **Procure pela mensagem de Autenticação começando com `42["auth"`**
6. **Copie a mensagem completa, incluindo o formato `42["auth",{...}]`**

Exemplo de formato de SSID:
```
42["auth",{"session":"abcd1234efgh5678","isDemo":1,"uid":12345,"platform":1}]
```

Se você não conseguir encontrá-lo, tente executar o script de extração automática de SSID na pasta [tools_ferramentas](tools_ferramentas).

## 📂 Estrutura do Projeto

```
pocketoptionapi_async/
├── __init__.py            # Inicialização do pacote
├── client.py              # Cliente principal da API
├── config.py              # Configurações da API
├── connection_keep_alive.py # Manutenção de conexão
├── connection_monitor.py  # Monitoramento de conexão
├── constants.py           # Constantes da API
├── exceptions.py          # Exceções personalizadas
├── models.py              # Modelos de dados
├── monitoring.py          # Ferramentas de monitoramento
├── utils.py               # Funções utilitárias
├── websocket_client.py    # Cliente WebSocket
```

## 🤝 Contribuindo

Sua contribuição é muito bem-vinda! Siga estes passos:

1. 🍴 Fork este Repositório
2. 🔄 Crie uma branch para sua feature
   ```bash
   git checkout -b feature/MinhaFeature
   ```
3. 💻 Faça suas Alterações
4. ✅ Commit usando mensagens convencionais
   ```bash
   git commit -m "feat: Adiciona nova funcionalidade"
   ```
5. 📤 Push para sua branch
   ```bash
   git push origin feature/MinhaFeature
   ```
6. 🔍 Abra um Pull Request

## 📜 Licença

Este projeto está licenciado sob a MIT License - veja o arquivo [LICENSE](LICENSE) para detalhes.

## ⚠️ Aviso Legal

Este projeto é uma implementação não oficial e não possui vínculo com a PocketOption. Use por sua conta e risco. O desenvolvedor não se responsabiliza por perdas financeiras ou outros danos.

## 📞 Suporte

- 💬 Telegram: [ByJhonesDev](https://t.me/jc_jhones_oficial)
- 🌐 Website: [ByJhonesDev](https://github.com/ByJhonesDev)

---

<p align="center">
  Desenvolvido com ❤️ por <a href="https://github.com/ByJhonesDev">ByJhonesDev</a>
</p>