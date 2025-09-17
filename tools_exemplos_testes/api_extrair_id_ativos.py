# Autor: ByJhonesDev
# Função: Extração de IDs de Ativos da PocketOption via WebSocket (Foco em Conta Real com Base64)
# Descrição:
# - Automatiza o login na plataforma PocketOption e navega até a página de negociação real.
# - Captura payloads WebSocket, detecta e decodifica base64 para extrair listas de ativos.
# - Extrai IDs e nomes de ativos (Incluindo OTC)
# - Salva os IDs extraídos em assets_ids.json e o código formatado em updated_assets.py.
# - Utiliza Selenium WebDriver com Chrome para navegação e captura de logs de performance.
# - Inclui logging estruturado em PT-BR com emojis e formato de data.
import os
import json
import time
import re
import base64
import logging
from typing import cast, List, Dict, Any
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from get_driver import get_driver
# Configura o logging com formato personalizado
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%d-%m-%Y %H:%M:%S"
)
logger = logging.getLogger(__name__)
# Filtro para personalizar mensagens do webdriver_manager
class WDMFilter(logging.Filter):
    def filter(self, record):
        if record.name.startswith("webdriver_manager"):
            if "WebDriver manager" in record.msg:
                record.msg = "🔧 Gerenciador WebDriver em Ação..."
            elif "Get LATEST chromedriver version" in record.msg:
                record.msg = "🔍 Buscando versão mais recente do chromedriver para google-chrome..."
            elif "Driver [" in record.msg:
                record.msg = f"💾 Driver [{record.msg.split('Driver [')[1]} encontrado no Cache."
        return True
# Aplica o filtro ao logger raiz
logging.getLogger().addFilter(WDMFilter())
def save_to_file(filename: str, data: Dict[str, int]):
    """
    Salva o dicionário de ativos e IDs no arquivo JSON especificado dentro da pasta GET_ASSETS.
    """
    profile_dir = os.path.join(os.getcwd(), "GET_ASSETS")
    os.makedirs(profile_dir, exist_ok=True)
    file_path = os.path.join(profile_dir, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    logger.info(f"💾 IDs de Ativos salvos com Sucesso em {file_path}")
    logger.info(f"📁 Total de ativos extraídos: {len(data)}.")
def save_payloads_to_file(payloads: List[str]):
    """
    Salva todos os payloads WebSocket em um arquivo para depuração.
    """
    profile_dir = os.path.join(os.getcwd(), "GET_ASSETS")
    os.makedirs(profile_dir, exist_ok=True)
    file_path = os.path.join(profile_dir, "websocket_payloads_assets.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        for payload in payloads:
            f.write(payload + "\n")
    logger.info(f"📝 Payloads WebSocket salvos em {file_path} para depuração.")
def save_decoded_payload(decoded_json: Any):
    """
    Salva o payload decodificado em decoded_assets_payload.json para análise.
    """
    profile_dir = os.path.join(os.getcwd(), "GET_ASSETS")
    os.makedirs(profile_dir, exist_ok=True)
    file_path = os.path.join(profile_dir, "decoded_assets_payload.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(decoded_json, f, indent=4, ensure_ascii=False)
    logger.info(f"📋 Payload decodificado salvo em {file_path}.")
def generate_formatted_assets(assets_dict: Dict[str, int]) -> str:
    """
    Gera o código Python formatado do dicionário ASSETS com comentários por categoria, mesclando com constants.py.
    Salva em updated_assets.py na pasta GET_ASSETS.
    """
    profile_dir = os.path.join(os.getcwd(), "GET_ASSETS")
    os.makedirs(profile_dir, exist_ok=True)
    file_path = os.path.join(profile_dir, "updated_assets.py")
    # Dicionário de ativos da Versão 2 (constants.py) como base
    constants_assets = {
        "EURUSD": 1, "GBPUSD": 56, "USDJPY": 63, "USDCHF": 62, "USDCAD": 61, "AUDUSD": 40, "NZDUSD": 90,
        "EURGBP": 7, "EURJPY": 6, "GBPJPY": 57, "AUDJPY": 41, "AUDCAD": 42, "AUDCHF": 43, "AUDNZD": 44,
        "CADCHF": 45, "CADJPY": 46, "CHFJPY": 47, "EURAUD": 48, "EURCAD": 49, "EURCHF": 50, "EURNZD": 51,
        "GBPAUD": 52, "GBPCAD": 53, "GBPCHF": 54, "GBPNZD": 55, "NZDCAD": 58, "NZDCHF": 59, "NZDJPY": 60,
        "EURHUF": 461, "EURNOK": 456, "CHFNOK": 457, "EURRUB": 201, "USDRUB": 199, "USDCNH": 94, "USDMXN": 95,
        "USDZAR": 96, "USDBRL": 97, "EURUSD_otc": 66, "GBPUSD_otc": 86, "USDJPY_otc": 93, "USDCHF_otc": 92,
        "USDCAD_otc": 91, "AUDUSD_otc": 71, "AUDNZD_otc": 70, "AUDCAD_otc": 67, "AUDCHF_otc": 68, "AUDJPY_otc": 69,
        "CADCHF_otc": 72, "CADJPY_otc": 73, "CHFJPY_otc": 74, "EURCHF_otc": 77, "EURGBP_otc": 78, "EURJPY_otc": 79,
        "EURNZD_otc": 80, "GBPAUD_otc": 81, "GBPJPY_otc": 84, "NZDJPY_otc": 89, "NZDUSD_otc": 90, "XAUUSD": 2,
        "XAUUSD_otc": 169, "XAGUSD": 65, "XAGUSD_otc": 167, "UKBrent": 50, "UKBrent_otc": 164, "USCrude": 64,
        "USCrude_otc": 165, "XNGUSD": 311, "XNGUSD_otc": 399, "XPTUSD": 312, "XPTUSD_otc": 400, "XPDUSD": 313,
        "XPDUSD_otc": 401, "BTCUSD": 197, "ETHUSD": 272, "DASH_USD": 209, "BTCGBP": 453, "BTCJPY": 454,
        "BCHEUR": 450, "BCHGBP": 451, "BCHJPY": 452, "DOTUSD": 458, "LNKUSD": 464, "SP500": 321, "SP500_otc": 408,
        "NASUSD": 323, "NASUSD_otc": 410, "DJI30": 322, "DJI30_otc": 409, "JPN225": 317, "JPN225_otc": 405,
        "D30EUR": 318, "D30EUR_otc": 406, "E50EUR": 319, "E50EUR_otc": 407, "F40EUR": 316, "F40EUR_otc": 404,
        "E35EUR": 314, "E35EUR_otc": 402, "100GBP": 315, "100GBP_otc": 403, "AUS200": 305, "AUS200_otc": 306,
        "CAC40": 455, "AEX25": 449, "SMI20": 466, "H33HKD": 463, "#AAPL": 5, "#AAPL_otc": 170, "#MSFT": 24,
        "#MSFT_otc": 176, "#TSLA": 186, "#TSLA_otc": 196, "#FB": 177, "#FB_otc": 187, "#AMZN_otc": 412,
        "#NFLX": 182, "#NFLX_otc": 429, "#INTC": 180, "#INTC_otc": 190, "#BA": 8, "#BA_otc": 292, "#JPM": 20,
        "#JNJ": 144, "#JNJ_otc": 296, "#PFE": 147, "#PFE_otc": 297, "#XOM": 153, "#XOM_otc": 426, "#AXP": 140,
        "#AXP_otc": 291, "#MCD": 23, "#MCD_otc": 175, "#CSCO": 154, "#CSCO_otc": 427, "#VISA_otc": 416,
        "#CITI": 326, "#CITI_otc": 413, "#FDX_otc": 414, "#TWITTER": 330, "#TWITTER_otc": 415, "#BABA": 183,
        "#BABA_otc": 428, "EURRUB_otc": 200, "USDRUB_otc": 199, "EURHUF_otc": 460, "CHFNOK_otc": 457,
        "Microsoft_otc": 521, "Facebook_otc": 522, "Tesla_otc": 523, "Boeing_otc": 524, "American_Express_otc": 525
    }
    # Limpa chaves duplicadas e normaliza (ex.: "AAPL_OTC_otc" -> "#AAPL_otc")
    cleaned_dict = {}
    for k, v in assets_dict.items():
        clean_k = k.replace("_OTC_otc", "_otc").replace("_OT C_otc", "_otc").replace("_USD_OTC_otc", "_USD_otc").replace("_USD_otc", "_USD")
        # Restaura # para ações
        if any(prefix in clean_k.replace("_otc", "") for prefix in ["AAPL", "MSFT", "TSLA", "FB", "NFLX", "INTC", "BA", "JPM", "JNJ", "PFE", "XOM", "AXP", "MCD", "CSCO", "CITI", "TWITTER", "BABA", "GOOGL", "NVDA", "META", "AMD", "GME", "COIN", "MARA", "PLTR"]):
            clean_k = f"#{clean_k}" if not clean_k.startswith("#") else clean_k
        cleaned_dict[clean_k] = v
    # Mescla com constants_assets, priorizando IDs da Versão 1 (extraídos), mas usando Versão 2 para IDs confiáveis
    merged_dict = constants_assets.copy()
    for k, v in cleaned_dict.items():
        # Corrige IDs errados (ex.: EURUSD_otc: 1 -> 66)
        if k in constants_assets and k.endswith("_otc") and v != constants_assets[k]:
            logger.warning(f"⚠️  ID de {k} diverge: Versão 1 ({v}) vs Versão 2 ({constants_assets[k]}). Usando Versão 2.")
            continue # Usa ID da Versão 2
        merged_dict[k] = v
    # Adiciona placeholder para AEX25_otc se ausente
    if "AEX25_otc" not in merged_dict:
        merged_dict["AEX25_otc"] = 450 # Placeholder
        logger.warning("⚠️  AEX25_otc não extraído. Usando placeholder ID 450.")
    # Lista de ativos por categoria
    forex_principais_list = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "AUDCAD", "AUDCHF", "AUDNZD", "CADCHF", "CADJPY", "CHFJPY", "EURAUD", "EURCAD", "EURCHF", "EURNZD", "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD", "NZDCAD", "NZDCHF", "NZDJPY"]
    forex_exoticos_list = ["EURHUF", "EURNOK", "CHFNOK", "EURRUB", "USDRUB", "USDCNH", "USDMXN", "USDZAR", "USDBRL", "USDARS", "USDBDT", "USDCLP", "USDCOP", "USDDZD", "USDEGP", "USDIDR", "USDINR", "USDMYR", "USDPHP", "USDPKR", "USDTHB", "USDVND"]
    otc_forex_principais_list = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "AUDNZD", "AUDCAD", "AUDCHF", "AUDJPY", "CADCHF", "CADJPY", "CHFJPY", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "GBPAUD", "GBPJPY", "NZDJPY", "NZDUSD"]
    otc_exoticos_list = ["MADUSD", "BHCNY", "JPYCNY", "OMRCNY", "USDBRL", "USDCNH", "USDEGP", "USDGBP", "EURHUF", "CHFNOK", "EURNOK", "EURRUB", "USDRUB", "USDMXN", "USDZAR", "NGNUSD", "KESUSD", "AEDCNY", "BHDCNY", "JODCNY", "QARCNY", "SARCNY", "IRRUSD", "LBPUSD", "SYPUSD", "TNDUSD", "UAHUSD", "YERUSD", "ZARUSD", "USDARS", "USDBDT", "USDCLP", "USDCOP", "USDDZD", "USDEGP", "USDIDR", "USDINR", "USDMYR", "USDPHP", "USDPKR", "USDTHB", "USDVND"]
    otc_commodities_list = ["XAUUSD", "XAGUSD", "UKBrent", "USCrude", "XNGUSD", "XPTUSD", "XPDUSD", "XCUUSD"]
    otc_indices_list = ["SP500", "NASUSD", "DJI30", "JPN225", "D30EUR", "E50EUR", "F40EUR", "E35EUR", "100GBP", "AUS200", "VIX", "AEX25"]
    acoes_list = ["AAPL", "MSFT", "TSLA", "FB", "NFLX", "INTC", "BA", "JPM", "JNJ", "PFE", "XOM", "AXP", "MCD", "CSCO", "CITI", "TWITTER", "BABA", "GOOGL", "NVDA", "META", "AMD", "GME", "COIN", "MARA", "PLTR"]
    crypto_list = ["BTCUSD", "ETHUSD", "DASH_USD", "BTCGBP", "BTCJPY", "BCHEUR", "BCHGBP", "BCHJPY", "DOTUSD", "LNKUSD", "ADAUSD", "LTCUSD", "XRPUSD", "SOLUSD", "CryptoIDX", "AVAX", "BNBUSD", "LINK", "MATIC", "TONUSD", "TRXUSD", "BITB"]
    commodities_aberto_list = ["XAUUSD", "XAGUSD", "UKBrent", "USCrude", "XNGUSD", "XPTUSD", "XPDUSD", "XCUUSD", "XAGEUR", "XAUEUR"]
    indices_aberto_list = ["SP500", "NASUSD", "DJI30", "JPN225", "D30EUR", "E50EUR", "F40EUR", "E35EUR", "100GBP", "AUS200", "CAC40", "AEX25", "SMI20", "H33HKD", "VIX", "CommodityIDX"]
    # Categorização automática
    forex_principais = {k: v for k, v in merged_dict.items() if k in forex_principais_list and "_otc" not in k}
    forex_exoticos = {k: v for k, v in merged_dict.items() if k in forex_exoticos_list and "_otc" not in k}
    otc_forex_principais = {k: v for k, v in merged_dict.items() if "_otc" in k and k.replace("_otc", "") in otc_forex_principais_list}
    otc_exoticos = {k: v for k, v in merged_dict.items() if "_otc" in k and k.replace("_otc", "") in otc_exoticos_list}
    otc_commodities = {k: v for k, v in merged_dict.items() if "_otc" in k and k.replace("_otc", "") in otc_commodities_list}
    otc_indices = {k: v for k, v in merged_dict.items() if "_otc" in k and k.replace("_otc", "") in otc_indices_list}
    acoes = {k: v for k, v in merged_dict.items() if k in [f"#{a}" for a in acoes_list] and "_otc" not in k}
    acoes_otc = {k: v for k, v in merged_dict.items() if "_otc" in k and k.replace("_otc", "") in [f"#{a}" for a in acoes_list] or k in ["Microsoft_otc", "Facebook_otc", "Tesla_otc", "Boeing_otc", "American_Express_otc"]}
    crypto = {k: v for k, v in merged_dict.items() if k in crypto_list or k.replace("_otc", "") in crypto_list}
    commodities_aberto = {k: v for k, v in merged_dict.items() if k in commodities_aberto_list and "_otc" not in k}
    indices_aberto = {k: v for k, v in merged_dict.items() if k in indices_aberto_list and "_otc" not in k}
    # Função para obter descrição do ativo
    def get_asset_description(asset: str) -> str:
        descriptions = {
            "AAPL": "Apple", "MSFT": "Microsoft", "TSLA": "Tesla", "FB": "Facebook (Meta)", "NFLX": "Netflix",
            "INTC": "Intel", "BA": "Boeing", "JPM": "JPMorgan", "JNJ": "Johnson & Johnson", "PFE": "Pfizer",
            "XOM": "Exxon", "AXP": "American Express", "MCD": "McDonalds", "CSCO": "Cisco", "CITI": "Citigroup",
            "TWITTER": "Twitter (X)", "BABA": "Alibaba", "GOOGL": "Google", "NVDA": "Nvidia", "META": "Meta",
            "AMD": "AMD", "GME": "GameStop", "COIN": "Coinbase", "MARA": "Marathon Digital", "PLTR": "Palantir",
            "XAUUSD": "Ouro", "XAGUSD": "Prata", "UKBrent": "Petróleo Brent", "USCrude": "Petróleo WTI",
            "XNGUSD": "Gás Natural", "XPTUSD": "Platina", "XPDUSD": "Paládio", "XCUUSD": "Cobre",
            "XAGEUR": "Prata (EUR)", "XAUEUR": "Ouro (EUR)",
            "SP500": "S&P 500", "NASUSD": "NASDAQ", "DJI30": "Dow Jones", "JPN225": "Nikkei", "D30EUR": "DAX",
            "E50EUR": "Euro Stoxx 50", "F40EUR": "CAC 40", "E35EUR": "E35EUR", "100GBP": "FTSE 100", "AUS200": "ASX 200",
            "CAC40": "CAC 40", "AEX25": "AEX", "SMI20": "Swiss", "H33HKD": "Hang Seng", "VIX": "Volatility Index",
            "CommodityIDX": "Commodity Index", "ADAUSD": "Cardano", "LTCUSD": "Litecoin", "XRPUSD": "Ripple",
            "SOLUSD": "Solana", "CryptoIDX": "Crypto Index", "AVAX": "Avalanche", "BNBUSD": "BNB", "LINK": "Chainlink",
            "MATIC": "Polygon", "TONUSD": "Toncoin", "TRXUSD": "TRON", "BITB": "Bitwise Bitcoin ETF",
            "Microsoft": "Microsoft", "Facebook": "Facebook (Meta)", "Tesla": "Tesla", "Boeing": "Boeing",
            "American_Express": "American Express"
        }
        return descriptions.get(asset.replace("#", "").replace("_otc", ""), asset.replace("#", "").replace("_otc", ""))
    # Gera o código formatado
    code = '# Mapeamento de ativos com seus respectivos IDs\nASSETS: Dict[str, int] = {\n'
    code += ' # Mercado Aberto\n'
    code += ' # Pares Forex Principais\n'
    for k, v in sorted(forex_principais.items(), key=lambda x: x[0]):
        code += f' "{k}": {v},\n'
    code += ' # Pares Exóticos\n'
    for k, v in sorted(forex_exoticos.items(), key=lambda x: x[0]):
        code += f' "{k}": {v},\n'
    code += '\n # Mercado OTC\n'
    code += ' # Pares Forex Principais OTC\n'
    for k, v in sorted(otc_forex_principais.items(), key=lambda x: x[0]):
        code += f' "{k}": {v},\n'
    code += ' # Pares Exóticos OTC\n'
    for k, v in sorted(otc_exoticos.items(), key=lambda x: x[0]):
        code += f' "{k}": {v},\n'
    code += ' # Commodities OTC\n'
    for k, v in sorted(otc_commodities.items(), key=lambda x: x[0]):
        code += f' "{k}": {v},\n'
    code += ' # Índices OTC\n'
    for k, v in sorted(otc_indices.items(), key=lambda x: x[0]):
        code += f' "{k}": {v},\n'
    code += '\n # Ações\n'
    for k, v in sorted(acoes.items(), key=lambda x: x[0]):
        desc = get_asset_description(k)
        code += f' "{k}": {v}, # {desc}\n'
    for k, v in sorted(acoes_otc.items(), key=lambda x: x[0]):
        desc = get_asset_description(k)
        code += f' "{k}": {v}, # {desc}\n'
    code += '\n # Criptomoedas\n'
    for k, v in sorted(crypto.items(), key=lambda x: x[0]):
        desc = get_asset_description(k)
        code += f' "{k}": {v}, # {desc}\n'
    code += '\n # Commodities (Mercado Aberto)\n'
    for k, v in sorted(commodities_aberto.items(), key=lambda x: x[0]):
        desc = get_asset_description(k)
        code += f' "{k}": {v}, # {desc}\n'
    code += '\n # Índices de Ações (Mercado Aberto)\n'
    for k, v in sorted(indices_aberto.items(), key=lambda x: x[0]):
        desc = get_asset_description(k)
        code += f' "{k}": {v}, # {desc}\n'
    code += '}\n'
    # Salva o arquivo
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)
    logger.info(f"📝 Código formatado do ASSETS salvo em {file_path}")
    return code
def extract_assets_from_payload(payload: str) -> Dict[str, int]:
    """
    Detecta e decodifica base64 no payload, depois parseia a lista de ativos.
    Estrutura: Lista de [ID, Nome, Descrição, Tipo, ..., is_otc (bool no índice 14), ...]
    """
    assets_dict = {}
    try:
        # Remove prefixo "42" se presente
        if payload.startswith("42"):
            payload = payload[2:]
        # Verifica se é base64 (padrão para listas de ativos)
        if re.match(r'^[A-Za-z0-9+/]+={0,2}$', payload.strip()):
            # Adiciona padding se necessário
            padding = (4 - len(payload) % 4) % 4
            payload += "=" * padding
            decoded_bytes = base64.b64decode(payload)
            json_str = decoded_bytes.decode('utf-8')
            data = json.loads(json_str)
            save_decoded_payload(data) # Salva o JSON para análise
            logger.info("🔓 Payload Base64 decodificado com sucesso!")
        else:
            # Tenta JSON direto
            data = json.loads(payload)
       
        # Parsing da lista de ativos (cada item é uma lista [ID, Nome, ... , is_otc, ...])
        if isinstance(data, list):
            for asset_list in data:
                if isinstance(asset_list, list) and len(asset_list) >= 15: # Mínimo para incluir índice 14 (is_otc)
                    asset_id = int(asset_list[0]) if isinstance(asset_list[0], (int, str)) else 0
                    asset_name_raw = asset_list[1] if isinstance(asset_list[1], str) else ""
                    # Normaliza o nome, evitando sufixo duplicado
                    asset_name = asset_name_raw.upper().replace("/", "").replace("-", "_").replace("_OTC", "_otc")
                    # Flag OTC no índice 14
                    is_otc = bool(asset_list[14]) if len(asset_list) > 14 else False
                    if is_otc and not asset_name.endswith("_otc"):
                        asset_name += "_otc"
                    if asset_id > 0 and asset_name:
                        if asset_name not in assets_dict:
                            # Restaura # para ações
                            if any(prefix in asset_name.replace("_otc", "") for prefix in ["AAPL", "MSFT", "TSLA", "FB", "NFLX", "INTC", "BA", "JPM", "JNJ", "PFE", "XOM", "AXP", "MCD", "CSCO", "CITI", "TWITTER", "BABA", "GOOGL", "NVDA", "META", "AMD", "GME", "COIN", "MARA", "PLTR"]):
                                asset_name = f"#{asset_name}" if not asset_name.startswith("#") else asset_name
                            assets_dict[asset_name] = asset_id
                            logger.debug(f"🔑 Extraído: {asset_name} -> {asset_id} (OTC: {is_otc})")
        logger.debug(f"🔍 Extraídos {len(assets_dict)} ativos deste payload.")
    except json.JSONDecodeError as e:
        logger.debug(f"⚠️  Erro JSON: {e}; pulando.")
    except base64.binascii.Error as e:
        logger.debug(f"⚠️  Erro Base64: {e}; pulando.")
    except Exception as e:
        logger.warning(f"⚠️  Erro no parsing: {e}")
    return assets_dict
def get_pocketoption_asset_ids():
    """
    Automatiza o processo de login na PocketOption, navega até a página de negociação real
    e captura/decodifica payloads base64 para extrair IDs de ativos.
    """
    driver = None
    try:
        # Configurações para captura máxima
        max_attempts = 12 # Aumentado para capturar payload completo
        attempt_interval = 25 # Aumentado para mais tempo
        driver = get_driver("chrome")
        login_url = "https://pocketoption.com/pt/login"
        cabinet_base_url = "https://pocketoption.com/pt/cabinet"
        real_url = "https://pocketoption.com/pt/cabinet/quick-high-low/" # Conta REAL
        logger.warning("⚠️  AVISO: Este script acessa a CONTA REAL. Para teste, mude 'real_url' para demo.")
        logger.info(f"🌐 Acessando página de login: {login_url}")
        driver.get(login_url)
        # Aguarda login manual
        logger.info(f"⏳ Aguardando Login do Usuário e redirecionamento para {cabinet_base_url}...")
        WebDriverWait(driver, 9999).until(EC.url_contains(cabinet_base_url))
        logger.info("🔓 Login bem-sucedido! Página principal carregada.")
        # Acessa página real
        logger.info(f"🎯 Acessando Conta Real: {real_url}")
        driver.get(real_url)
        WebDriverWait(driver, 90).until(EC.url_contains(real_url))
        logger.info("📈 Página Real carregada com Sucesso. Aguardando carregamento de ativos...")
        # Captura payloads
        all_assets = {}
        all_payloads = []
        for attempt in range(1, max_attempts + 1):
            logger.info(f"⏱️  Tentativa {attempt}/{max_attempts}: Aguardando {attempt_interval} segundos para conexões WebSocket.")
            time.sleep(attempt_interval)
            get_log = getattr(driver, "get_log", None)
            if not callable(get_log):
                raise AttributeError("Seu WebDriver não suporta get_log().")
            performance_logs = cast(List[Dict[str, Any]], get_log("performance"))
            logger.info(f"📥 Coletado {len(performance_logs)} entradas de log na tentativa {attempt}.")
            for entry in performance_logs:
                message = json.loads(entry["message"])
                if message["message"]["method"] in ["Network.webSocketFrameReceived", "Network.webSocketFrameSent"]:
                    payload_data = message["message"]["params"]["response"]["payloadData"]
                    all_payloads.append(payload_data)
                    extracted = extract_assets_from_payload(payload_data)
                    if extracted:
                        all_assets.update(extracted)
                        logger.info(f"🔑 {len(extracted)} ativos extraídos na tentativa {attempt}!")
        # Salva arquivos
        if all_payloads:
            save_payloads_to_file(all_payloads)
        if all_assets:
            save_to_file("assets_ids.json", all_assets)
            formatted_code = generate_formatted_assets(all_assets)
            logger.info("✅ Código ASSETS formatado gerado e salvo em GET_ASSETS/updated_assets.py!")
            logger.info("📋 Copie o conteúdo de updated_assets.py para o seu constants.py.")
        else:
            logger.warning("⚠️  Nenhum ativo encontrado. Rode novamente ou verifique decoded_assets_payload.json.")
    except Exception as e:
        logger.error(f"❌ Erro: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
            logger.info("🚪 WebDriver Fechado.")
if __name__ == "__main__":
    get_pocketoption_asset_ids()
