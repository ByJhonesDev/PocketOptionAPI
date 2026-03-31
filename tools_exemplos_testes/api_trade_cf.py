"""
Autor: ByJhonesDev
Projeto: PocketOptionAPI – Biblioteca Python assíncrona de alto nível para integração com a corretora Pocket Option, desenvolvida para fornecer uma camada confiável, extensível, resiliente e orientada a eventos para automação operacional e processamento de dados de mercado em tempo real.

Descrição:
Script assíncrono de validação de conectividade avançada da PocketOptionAPI com montagem explícita de headers HTTP e cookies complementares para cenários em que a autenticação WebSocket depende não apenas do SSID, mas também de informações adicionais de navegador, origem e cookies auxiliares. O módulo é útil para depuração de sessão, compatibilidade com ambientes protegidos e testes controlados de handshake com a infraestrutura do broker.

O que ele faz:
- Carrega SSID real ou demo a partir de variáveis de ambiente ou arquivos locais
- Determina automaticamente o modo da conta com base na configuração do ambiente
- Lê cookies adicionais de apoio, incluindo dados auxiliares de Cloudflare
- Monta headers HTTP completos com User-Agent, Origin, Referer e Cookie
- Inicializa o cliente assíncrono com base e path de Socket.IO configuráveis
- Estabelece conexão WebSocket com parâmetros extras de autenticação
- Valida falha explícita de sessão quando SSID ou handshake não são aceitos
- Consulta candles de 1 minuto para validar leitura de dados após conexão
- Encerra a sessão de forma graciosa após o teste
- Facilita troubleshooting de conexão em cenários mais sensíveis de autenticação

Características:
- Arquitetura assíncrona baseada em asyncio
- Suporte a configuração por .env
- Montagem explícita de headers e cookies
- Compatibilidade com conta demo e real
- Foco em depuração e validação de handshake
- Estrutura simples e objetiva para testes de conectividade
- Reaproveitamento do cliente principal da biblioteca
- Ajuste de host HTTP base e path de Socket.IO
- Fail-fast quando credenciais ou sessão estão inválidas
- Útil para homologação e diagnóstico de bloqueios de conexão

Requisitos:
- Python 3.10+
- asyncio
- python-dotenv
- Módulos internos do projeto:
  - client
"""

import os, sys, asyncio
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(override=True)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "pocketoptionapi_async"))
from client import AsyncPocketOptionClient 

def read(p: Path) -> str:
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""

def load_ssid() -> str:
    mode = os.getenv("PO_ACCOUNT_MODE","PRACTICE").upper()
    ssid = os.getenv("POCKET_OPTION_SSID_REAL","") if mode=="REAL" else os.getenv("POCKET_OPTION_SSID_DEMO","")
    if ssid: return ssid
    fname = "SSID_REAL.txt" if mode=="REAL" else "SSID_DEMO.txt"
    return read(REPO_ROOT / "GET_SSID" / fname)

def load_headers(ssid: str) -> dict:
    origin = os.getenv("PO_WS_ORIGIN","https://pocketoption.com")
    cookies = os.getenv("PO_EXTRA_COOKIES","") or read(REPO_ROOT / "GET_SSID" / "CF_COOKIES.txt")
    cookie_line = f"ssid={ssid}" + (f"; {cookies}" if cookies else "")
    ua = os.getenv("PO_WS_UA","Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
    return {"User-Agent": ua, "Origin": origin, "Referer": origin + "/", "Cookie": cookie_line}

async def main():
    ssid = load_ssid()
    if not ssid:
        raise SystemExit("Sem SSID. Rode tools_ferramentas/get_ssid_demo.py ou get_ssid_real.py")
    headers = load_headers(ssid)
    client = AsyncPocketOptionClient(
        ssid=ssid,
        is_demo=os.getenv("PO_ACCOUNT_MODE","PRACTICE").upper()!="REAL",
        ws_http_base=os.getenv("PO_WS_HTTP_BASE","https://api-c.po.market"),
        socketio_path=os.getenv("PO_SOCKETIO_PATH","/socket.io"),
        headers_extra=headers,
        enable_logging=False,
    )
    ok = await client.connect()
    if not ok:
        raise SystemExit("Conexão falhou (verifique SSID/cookies/host).")
    symbol = "EURUSD_otc"
    candles = await client.get_candles(asset=symbol, timeframe=60)
    print(f"✅ Velas recebidas: {len(candles)} em {symbol}")
    await client.disconnect(); print("✅ Desconectado.")

if __name__ == "__main__":
    asyncio.run(main())
