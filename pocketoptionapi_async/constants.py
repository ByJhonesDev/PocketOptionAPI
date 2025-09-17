"""
# Autor: ByJhonesDev
# Função: Configurações e Constantes
# Descrição:
# - Define constantes para a API da PocketOption
# - Inclui mapeamento de ativos, regiões WebSocket e prazos
# - Configura limites da API e cabeçalhos padrão
"""
from typing import Dict, List, Optional
import random
# Mapeamento de ativos com seus respectivos IDs
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

# Regiões WebSocket com suas URLs
class Regions:
    """Endpoints de regiões WebSocket"""
    _REGIONS = {
        "EUROPA": "wss://api-eu.po.market/socket.io/?EIO=4&transport=websocket",
        "SEYCHELLES": "wss://api-sc.po.market/socket.io/?EIO=4&transport=websocket",
        "HONGKONG": "wss://api-hk.po.market/socket.io/?EIO=4&transport=websocket",
        "SERVER1": "wss://api-spb.po.market/socket.io/?EIO=4&transport=websocket",
        "FRANCE2": "wss://api-fr2.po.market/socket.io/?EIO=4&transport=websocket",
        "UNITED_STATES4": "wss://api-us4.po.market/socket.io/?EIO=4&transport=websocket",
        "UNITED_STATES3": "wss://api-us3.po.market/socket.io/?EIO=4&transport=websocket",
        "UNITED_STATES2": "wss://api-us2.po.market/socket.io/?EIO=4&transport=websocket",
        "DEMO": "wss://demo-api-eu.po.market/socket.io/?EIO=4&transport=websocket",
        "DEMO_2": "wss://try-demo-eu.po.market/socket.io/?EIO=4&transport=websocket",
        "UNITED_STATES": "wss://api-us-north.po.market/socket.io/?EIO=4&transport=websocket",
        "RUSSIA": "wss://api-msk.po.market/socket.io/?EIO=4&transport=websocket",
        "SERVER2": "wss://api-l.po.market/socket.io/?EIO=4&transport=websocket",
        "INDIA": "wss://api-in.po.market/socket.io/?EIO=4&transport=websocket",
        "FRANCE": "wss://api-fr.po.market/socket.io/?EIO=4&transport=websocket",
        "FINLAND": "wss://api-fin.po.market/socket.io/?EIO=4&transport=websocket",
        "SERVER3": "wss://api-c.po.market/socket.io/?EIO=4&transport=websocket",
        "ASIA": "wss://api-asia.po.market/socket.io/?EIO=4&transport=websocket",
        "SERVER4": "wss://api-us-south.po.market/socket.io/?EIO=4&transport=websocket",
    }
    @classmethod
    def get_all(cls, randomize: bool = True) -> List[str]:
        """Obter todas as URLs de regiões"""
        urls = list(cls._REGIONS.values())
        if randomize:
            random.shuffle(urls)
        return urls
    @classmethod
    def get_all_regions(cls) -> Dict[str, str]:
        """Obter todas as regiões como dicionário"""
        return cls._REGIONS.copy()
    from typing import Optional
    @classmethod
    def get_region(cls, region_name: str) -> Optional[str]:
        """Obter URL de uma região específica"""
        return cls._REGIONS.get(region_name.upper())
    @classmethod
    def get_demo_regions(cls) -> List[str]:
        """Obter URLs de regiões demo"""
        return [url for name, url in cls._REGIONS.items() if "DEMO" in name]
# Constantes globais
REGIONS = Regions()
# Prazos (em segundos)
TIMEFRAMES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
}
# Configurações de conexão
CONNECTION_SETTINGS = {
    "ping_interval": 20, # segundos
    "ping_timeout": 10, # segundos
    "close_timeout": 10, # segundos
    "max_reconnect_attempts": 5,
    "reconnect_delay": 5, # segundos
    "message_timeout": 30, # segundos
}
# Limites da API
API_LIMITS = {
    "min_order_amount": 1.0,
    "max_order_amount": 50000.0,
    "min_duration": 5, # segundos
    "max_duration": 43200, # 12 horas em segundos
    "max_concurrent_orders": 10,
    "rate_limit": 100, # requisições por minuto
}
# Cabeçalhos padrão
DEFAULT_HEADERS = {
    "Origin": "https://pocketoption.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}