"""
Autor: ByJhonesDev
Função:
- Carrega o SSID (REAL/DEMO) do ambiente ou dos arquivos GET_SSID/SSID_REAL.txt ou
  GET_SSID/SSID_DEMO.txt, monta os headers (User-Agent, Origin, Referer e Cookie com
  ssid + cookies do Cloudflare) e estabelece uma conexão WebSocket (Socket.IO) com a
  PocketOption usando AsyncPocketOptionClient. Após conectar, consulta velas de 1m
  (EURUSD_otc) e encerra a sessão.

Destaques:
- Usa dotenv (load_dotenv) para ler variáveis do .env com override=True.
- Determina o modo da conta via PO_ACCOUNT_MODE (REAL/PRACTICE) e seleciona o SSID
  pelas variáveis POCKET_OPTION_SSID_REAL/POCKET_OPTION_SSID_DEMO ou arquivos fallback.
- Injeta cookies extras do Cloudflare via PO_EXTRA_COOKIES ou arquivo GET_SSID/CF_COOKIES.txt.
- Constrói headers HTTP completos: User-Agent (PO_WS_UA), Origin/Referer (PO_WS_ORIGIN) e Cookie.
- Parâmetros do cliente configuráveis por ambiente:
  - ws_http_base (PO_WS_HTTP_BASE, padrão https://api-c.po.market)
  - socketio_path (PO_SOCKETIO_PATH, padrão /socket.io)
  - is_demo deduzido de PO_ACCOUNT_MODE
  - headers_extra com SSID + cookies
- Fluxo com validações explícitas:
  - Aborta se não houver SSID (orienta rodar get_ssid_demo.py/real.py).
  - Aborta se connect() retornar falso (indica revisar SSID/cookies/host).
- Consulta de dados:
  - Busca candles de 60s para o ativo "EURUSD_otc" e informa a quantidade recebida.
- Organização do projeto:
  - Ajusta REPO_ROOT e sys.path para importar client (pocketoptionapi_async/client.py).
- Assíncrono/limpeza:
  - Usa asyncio.run(main()), desconecta de forma graciosa e imprime status final.
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
