"""
Autor: ByJhonesDev
Projeto: PocketOptionAPI – Biblioteca Python assíncrona de alto nível para integração com a corretora Pocket Option, com centralização de parâmetros estáticos, mapeamentos operacionais e utilitários de normalização.

Descrição:
Módulo central de constantes e definições estruturais da biblioteca. Reúne configurações padrão de conexão, headers WebSocket, timeframes, limites operacionais, catálogo base mínimo de ativos, aliases de tipos, mapeamento de eventos do broker e endpoints regionais, servindo como base estável para os demais módulos da API.

O que ele faz:
- Centraliza headers padrão de conexão WebSocket
- Define parâmetros default de timeout, ping e reconexão
- Mapeia timeframes entre rótulos legíveis e segundos
- Define limites operacionais básicos da API
- Mantém um catálogo base mínimo de ativos e IDs
- Fornece aliases e normalização de tipos de ativos
- Mapeia eventos brutos do broker para eventos internos padronizados
- Centraliza endpoints regionais da Pocket Option
- Disponibiliza helpers de normalização para ativos, payout, status e timeframe

Características:
- Fonte central de configuração estática da biblioteca
- Redução de duplicidade e inconsistência entre módulos
- Compatibilidade com eventos brutos e aliases do broker
- Catálogo mínimo pronto para fallback e validação
- Helpers reutilizáveis de normalização sem dependência externa
- Classe dedicada para gerenciamento de regiões WebSocket
- Estrutura extensível para novos ativos, eventos e endpoints

Requisitos:
- Python 3.10+
- typing
- random
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

# -----------------------------------------------------------------------------
# Headers / connection defaults
# -----------------------------------------------------------------------------

DEFAULT_HEADERS: Dict[str, str] = {
    "Origin": "https://pocketoption.com",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}

CONNECTION_SETTINGS: Dict[str, Any] = {
    "ping_interval": 20,
    "ping_timeout": 10,
    "close_timeout": 10,
    "message_timeout": 30,
    "max_reconnect_attempts": 5,
    "reconnect_delay": 5,
    "handshake_timeout": 10,
    "connect_timeout": 10,
}

# -----------------------------------------------------------------------------
# Timeframes completos
# -----------------------------------------------------------------------------

TIMEFRAMES: Dict[str, int] = {
    "1s": 1,
    "5s": 5,
    "10s": 10,
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "2m": 120,
    "3m": 180,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "8h": 28800,
    "1d": 86400,
    "1w": 604800,
}

TIMEFRAMES_BY_SECONDS: Dict[int, str] = {value: key for key, value in TIMEFRAMES.items()}

# -----------------------------------------------------------------------------
# Limites de operação
# -----------------------------------------------------------------------------

API_LIMITS: Dict[str, Any] = {
    "min_order_amount": 1,
    "max_order_amount": 10000,
    "min_duration": 5,
    "max_duration": 3600,
    "max_concurrent_orders": 50,
}

# -----------------------------------------------------------------------------
# Catálogo base mínimo compatível
# Observação:
# - isso não deve ser tratado como catálogo completo da corretora
# - o catálogo real deve vir do WebSocket em tempo real
# -----------------------------------------------------------------------------

ASSETS: Dict[str, int] = {
 # Mercado Aberto
 # Pares Forex Principais
 "AUDCAD": 42,
 "AUDCHF": 43,
 "AUDJPY": 41,
 "AUDNZD": 44,
 "AUDUSD": 40,
 "CADCHF": 45,
 "CADJPY": 46,
 "CHFJPY": 47,
 "EURAUD": 48,
 "EURCAD": 49,
 "EURCHF": 50,
 "EURGBP": 47,
 "EURJPY": 6,
 "EURNZD": 51,
 "EURUSD": 1,
 "GBPAUD": 52,
 "GBPCAD": 53,
 "GBPCHF": 54,
 "GBPJPY": 57,
 "GBPNZD": 55,
 "GBPUSD": 56,
 "NZDCAD": 58,
 "NZDCHF": 59,
 "NZDJPY": 60,
 "NZDUSD": 90,
 "USDCAD": 61,
 "USDCHF": 62,
 "USDJPY": 63,
 # Pares Exóticos
 "CHFNOK": 457,
 "EURHUF": 461,
 "EURNOK": 456,
 "EURRUB": 201,
 "USDBRL": 97,
 "USDCNH": 94,
 "USDMXN": 95,
 "USDRUB": 199,
 "USDZAR": 96,

 # Mercado OTC
 # Pares Forex Principais OTC
 "AUDCAD_otc": 67,
 "AUDCHF_otc": 68,
 "AUDJPY_otc": 69,
 "AUDNZD_otc": 70,
 "AUDUSD_otc": 71,
 "CADCHF_otc": 72,
 "CADJPY_otc": 73,
 "CHFJPY_otc": 74,
 "EURCHF_otc": 77,
 "EURGBP_otc": 78,
 "EURJPY_otc": 79,
 "EURNZD_otc": 80,
 "EURUSD_otc": 66,
 "GBPAUD_otc": 81,
 "GBPJPY_otc": 84,
 "GBPUSD_otc": 86,
 "NZDJPY_otc": 89,
 "NZDUSD_otc": 90,
 "USDCAD_otc": 91,
 "USDCHF_otc": 92,
 "USDJPY_otc": 93,
 # Pares Exóticos OTC
 "AEDCNY_otc": 538,
 "BHDCNY_otc": 536,
 "CHFNOK_otc": 457,
 "EURHUF_otc": 460,
 "EURRUB_otc": 200,
 "IRRUSD_otc": 548,
 "JODCNY_otc": 546,
 "KESUSD_otc": 554,
 "LBPUSD_otc": 530,
 "MADUSD_otc": 534,
 "NGNUSD_otc": 552,
 "OMRCNY_otc": 544,
 "QARCNY_otc": 542,
 "SARCNY_otc": 540,
 "SYPUSD_otc": 550,
 "TNDUSD_otc": 532,
 "UAHUSD_otc": 558,
 "USDARS_otc": 506,
 "USDBDT_otc": 500,
 "USDBRL_otc": 502,
 "USDCLP_otc": 525,
 "USDCNH_otc": 467,
 "USDCOP_otc": 515,
 "USDDZD_otc": 508,
 "USDEGP_otc": 513,
 "USDIDR_otc": 504,
 "USDINR_otc": 202,
 "USDMXN_otc": 509,
 "USDMYR_otc": 523,
 "USDPHP_otc": 511,
 "USDPKR_otc": 517,
 "USDRUB_otc": 199,
 "USDTHB_otc": 521,
 "USDVND_otc": 519,
 "YERUSD_otc": 528,
 "ZARUSD_otc": 556,
 # Commodities OTC
 "UKBrent_otc": 164,
 "USCrude_otc": 165,
 "XAGUSD_otc": 167,
 "XAUUSD_otc": 169,
 "XNGUSD_otc": 399,
 "XPDUSD_otc": 401,
 "XPTUSD_otc": 400,
 # Índices OTC
 "100GBP_otc": 403,
 "AEX25_otc": 450,
 "AUS200_otc": 306,
 "D30EUR_otc": 406,
 "DJI30_otc": 409,
 "E35EUR_otc": 402,
 "E50EUR_otc": 407,
 "F40EUR_otc": 404,
 "JPN225_otc": 405,
 "NASUSD_otc": 410,
 "SP500_otc": 408,
 "VIX_otc": 560,

 # Ações
 "#AAPL": 5, # Apple
 "#AXP": 140, # American Express
 "#BA": 8, # Boeing
 "#BABA": 183, # Alibaba
 "#CITI": 326, # Citigroup
 "#CSCO": 154, # Cisco
 "#FB": 177, # Facebook (Meta)
 "#INTC": 180, # Intel
 "#JNJ": 144, # Johnson & Johnson
 "#JPM": 20, # JPMorgan
 "#MCD": 23, # McDonalds
 "#MSFT": 24, # Microsoft
 "#NFLX": 182, # Netflix
 "#PFE": 147, # Pfizer
 "#TSLA": 186, # Tesla
 "#TWITTER": 330, # Twitter (X)
 "#XOM": 153, # Exxon
 "#AAPL_otc": 170, # Apple
 "#AMD_otc": 568, # AMD
 "#AXP_otc": 291, # American Express
 "#BABA_otc": 428, # Alibaba
 "#BA_otc": 292, # Boeing
 "#CITI_otc": 413, # Citigroup
 "#COIN_otc": 570, # Coinbase
 "#CSCO_otc": 427, # Cisco
 "#FB_otc": 187, # Facebook (Meta)
 "#GME_otc": 566, # GameStop
 "#INTC_otc": 190, # Intel
 "#JNJ_otc": 296, # Johnson & Johnson
 "#MARA_otc": 572, # Marathon Digital
 "#MCD_otc": 175, # McDonalds
 "#MSFT_otc": 176, # Microsoft
 "#NFLX_otc": 429, # Netflix
 "#PFE_otc": 297, # Pfizer
 "#PLTR_otc": 562, # Palantir
 "#TSLA_otc": 196, # Tesla
 "#TWITTER_otc": 415, # Twitter (X)
 "#XOM_otc": 426, # Exxon
 "American_Express_otc": 525, # American Express
 "Boeing_otc": 524, # Boeing
 "Facebook_otc": 522, # Facebook (Meta)
 "Microsoft_otc": 521, # Microsoft
 "Tesla_otc": 523, # Tesla

 # Criptomoedas
 "AVAX_otc": 481, # Avalanche
 "BCHEUR": 450, # BCHEUR
 "BCHGBP": 451, # BCHGBP
 "BCHJPY": 452, # BCHJPY
 "BITB_otc": 494, # Bitwise Bitcoin ETF
 "BTCGBP": 453, # BTCGBP
 "BTCJPY": 454, # BTCJPY
 "BTCUSD": 197, # BTCUSD
 "BTCUSD_otc": 197, # BTCUSD
 "DASH_USD": 209, # DASH_USD
 "DOTUSD": 458, # DOTUSD
 "DOTUSD_otc": 486, # DOTUSD
 "ETHUSD": 272, # ETHUSD
 "ETHUSD_otc": 487, # ETHUSD
 "LINK_otc": 478, # Chainlink
 "LNKUSD": 464, # LNKUSD
 "LTCUSD_otc": 488, # Litecoin
 "MATIC_otc": 491, # Polygon

 # Commodities (Mercado Aberto)
 "UKBrent": 50, # Petróleo Brent
 "USCrude": 64, # Petróleo WTI
 "XAGEUR": 103, # Prata (EUR)
 "XAGUSD": 65, # Prata
 "XAUEUR": 102, # Ouro (EUR)
 "XAUUSD": 2, # Ouro
 "XNGUSD": 311, # Gás Natural
 "XPDUSD": 313, # Paládio
 "XPTUSD": 312, # Platina

 # Índices de Ações (Mercado Aberto)
 "100GBP": 315, # FTSE 100
 "AEX25": 449, # AEX
 "AUS200": 305, # ASX 200
 "CAC40": 455, # CAC 40
 "D30EUR": 318, # DAX
 "DJI30": 322, # Dow Jones
 "E35EUR": 314, # E35EUR
 "E50EUR": 319, # Euro Stoxx 50
 "F40EUR": 316, # CAC 40
 "H33HKD": 463, # Hang Seng
 "JPN225": 317, # Nikkei
 "NASUSD": 323, # NASDAQ
 "SMI20": 466, # Swiss
 "SP500": 321, # S&P 500
}

ASSET_IDS_TO_NAMES: Dict[int, str] = {v: k for k, v in ASSETS.items()}
ASSET_NAMES_TO_IDS: Dict[str, int] = {k: v for k, v in ASSETS.items()}

# -----------------------------------------------------------------------------
# Tipos de ativos / aliases
# -----------------------------------------------------------------------------

ASSET_TYPES: Dict[str, str] = {
    "forex": "forex",
    "crypto": "crypto",
    "commodity": "commodity",
    "commodities": "commodity",
    "index": "index",
    "indices": "index",
    "stock": "stock",
    "stocks": "stock",
    "otc": "otc",
    "digital": "digital",
    "cfd": "cfd",
    "etf": "etf",
    "unknown": "unknown",
}

ASSET_TYPE_ALIASES: Dict[str, str] = {
    "fx": "forex",
    "forex": "forex",
    "crypto": "crypto",
    "cryptocurrency": "crypto",
    "commodities": "commodity",
    "commodity": "commodity",
    "index": "index",
    "indices": "index",
    "stock": "stock",
    "stocks": "stock",
    "otc": "otc",
    "digital": "digital",
    "cfd": "cfd",
    "etf": "etf",
}

# -----------------------------------------------------------------------------
# Eventos do broker / aliases
# -----------------------------------------------------------------------------

BROKER_EVENT_MAP: Dict[str, str] = {
    # auth
    "successauth": "authenticated",
    "authenticated": "authenticated",
    "auth": "authenticated",

    # balance
    "successupdateBalance": "balance_updated",
    "balance_updated": "balance_updated",
    "balance_data": "balance_updated",
    "getBalance": "balance_updated",

    # order
    "successopenOrder": "order_opened",
    "order_opened": "order_opened",
    "openOrder": "order_opened",
    "successcloseOrder": "order_closed",
    "order_closed": "order_closed",
    "closeOrder": "order_closed",

    # stream / candles
    "updateStream": "stream_update",
    "stream_update": "stream_update",
    "loadHistoryPeriod": "candles_received",
    "candles_received": "candles_received",
    "updateHistoryNew": "history_update",
    "history_update": "history_update",

    # assets / payouts
    "assets": "assets",
    "assets_received": "assets",
    "getAssets": "assets",
    "loadAssets": "assets",
    "payout_update": "payout_update",

    # misc
    "server_time": "server_time",
    "news": "news_update",
    "limits": "account_limits",
    "account_config": "account_config",
}

# eventos que normalmente devem ser preservados mesmo se desconhecidos
PASS_THROUGH_EVENTS = {
    "authenticated",
    "balance_updated",
    "balance_data",
    "order_opened",
    "order_closed",
    "stream_update",
    "candles_received",
    "history_update",
    "assets",
    "assets_received",
    "payout_update",
    "unknown_event",
    "json_data",
    "raw_message",
}

# -----------------------------------------------------------------------------
# Regiões WebSocket
# -----------------------------------------------------------------------------

class Regions:
    _REGIONS: Dict[str, str] = {
        "EUROPA": "wss://api-eu.po.market/socket.io/?EIO=4&transport=websocket",
        "SEYCHELLES": "wss://api-sc.po.market/socket.io/?EIO=4&transport=websocket",
        "HONGKONG": "wss://api-hk.po.market/socket.io/?EIO=4&transport=websocket",
        "USA": "wss://api-us.po.market/socket.io/?EIO=4&transport=websocket",
        "DEMO": "wss://demo-api-eu.po.market/socket.io/?EIO=4&transport=websocket",
    }

    @classmethod
    def get_all_regions(cls) -> Dict[str, str]:
        return dict(cls._REGIONS)

    @classmethod
    def get_region(cls, name: str) -> Optional[str]:
        if not name:
            return None
        return cls._REGIONS.get(str(name).upper())

    @classmethod
    def get_all(cls, randomize: bool = True) -> List[str]:
        urls = list(cls._REGIONS.values())
        if randomize:
            random.shuffle(urls)
        return urls

    @classmethod
    def get_demo_regions(cls) -> List[str]:
        return [v for k, v in cls._REGIONS.items() if "DEMO" in k.upper()]

    @classmethod
    def get_live_regions(cls, randomize: bool = True) -> List[str]:
        urls = [v for k, v in cls._REGIONS.items() if "DEMO" not in k.upper()]
        if randomize:
            random.shuffle(urls)
        return urls

    @classmethod
    def has_region(cls, name: str) -> bool:
        if not name:
            return False
        return str(name).upper() in cls._REGIONS

REGIONS = Regions()

# -----------------------------------------------------------------------------
# Helpers de normalização
# -----------------------------------------------------------------------------

def normalize_payout(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        payout = float(value)
    except Exception:
        return None

    if 0 < payout <= 1:
        payout *= 100.0

    return round(payout, 2)


def normalize_asset_symbol(symbol: Any) -> str:
    raw = str(symbol or "").strip().upper()
    raw = raw.replace("#", "").replace("/", "")
    if " OTC" in raw:
        raw = raw.replace(" OTC", "_otc")
    elif raw.endswith("_OTC"):
        raw = raw[:-4] + "_otc"
    return raw


def normalize_asset_type(asset_type: Any) -> str:
    raw = str(asset_type or "").strip().lower()
    return ASSET_TYPE_ALIASES.get(raw, raw or "unknown")


def normalize_open_value(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in {"open", "opened", "available", "active", "tradable", "enabled", "1", "true", "yes", "on"}:
        return True
    if normalized in {"closed", "close", "unavailable", "inactive", "disabled", "0", "false", "no", "off"}:
        return False
    return None


def timeframe_to_seconds(value: Any) -> Optional[int]:
    if value is None:
        return None

    if isinstance(value, int):
        return value

    raw = str(value).strip().lower()
    return TIMEFRAMES.get(raw)


def seconds_to_timeframe(value: Any) -> Optional[str]:
    if value is None:
        return None

    try:
        seconds = int(value)
    except Exception:
        return None

    return TIMEFRAMES_BY_SECONDS.get(seconds)