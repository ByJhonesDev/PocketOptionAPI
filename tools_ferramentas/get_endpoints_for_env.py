"""
Autor: ByJhonesDev 
Função: Abrir Navegador Chrome, aguardar login manual no PocketOption e
capturar endpoints WebSocket/REST + cookies para DEMO e REAL, gravando em .env
com prefixos separados (PO_DEMO_* / PO_REAL_*) e Snapshots em GET_SSID/.
Agora também captura os SSIDs (payload "42[\"auth\",{...}]") para DEMO e REAL.

Saídas:
  - GET_SSID/ENDPOINTS_DEMO.env 
  - GET_SSID/ENDPOINTS_REAL.env
  - GET_SSID/SSID_DEMO.txt
  - GET_SSID/SSID_REAL.txt
  - .env com todas as Informações Atualizadas acima.
"""

from __future__ import annotations
import os, re, json, time, contextlib, gc, sys, logging
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from urllib.parse import urlparse

# =========================================================
# Silenciar ruídos do python-dotenv em libs de terceiros
# (webdriver_manager chama load_dotenv() no import)
# =========================================================
os.environ.setdefault("DOTENV_SILENT", "true")  # suprime mensagens do python-dotenv

# =========================================================
# Utilitários de silêncio (stdout/stderr)
# =========================================================
@contextlib.contextmanager
def _silence_stdout_stderr():
    _old_out, _old_err = sys.stdout, sys.stderr
    try:
        with open(os.devnull, "w") as devnull:
            sys.stdout = devnull  # type: ignore
            sys.stderr = devnull  # type: ignore
            yield
    finally:
        sys.stdout, sys.stderr = _old_out, _old_err

@contextlib.contextmanager
def _silence_stdout_only():
    _old_out = sys.stdout
    try:
        with open(os.devnull, "w") as devnull:
            sys.stdout = devnull  # type: ignore
            yield
    finally:
        sys.stdout = _old_out

# =======================
# LOGGING ISOLADO (sem root)
# =======================
def _make_logger(name: str) -> logging.Logger:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.WARNING)

    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    # 1) LOG agora sai no STDERR (não é afetado quando calamos o STDOUT)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%d-%m-%Y %H:%M:%S"))
    lg.addHandler(handler)

    for noisy in (
        "undetected_chromedriver",
        "webdriver_manager",
        "selenium.webdriver.remote.remote_connection",
        "urllib3",
        "filelock",
        "WDM",
    ):
        nlg = logging.getLogger(noisy)
        nlg.propagate = False
        nlg.handlers.clear()
        nlg.setLevel(logging.CRITICAL)

    os.environ.setdefault("WDM_LOG_LEVEL", "0")
    return lg

log = _make_logger("po-env")

# ===== preferir undetected_chromedriver se disponível =====
USE_UC = False
try:
    # o UC não usa dotenv; não precisa silenciar, mas deixamos protegido
    with _silence_stdout_stderr():
        import undetected_chromedriver as uc  # type: ignore
    USE_UC = True
    with contextlib.suppress(Exception):
        uc.Chrome.__del__ = lambda self: None  # silenciar __del__
except Exception:
    USE_UC = False

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
# IMPORTANTE: não importar webdriver_manager no topo (gera prints do dotenv)
# from webdriver_manager.chrome import ChromeDriverManager  # <- removido
from selenium.webdriver.chrome.service import Service

# ===== constantes =====
LOGIN_URL         = "https://pocketoption.com/pt/login"
CABINET_BASE      = "https://pocketoption.com/pt/cabinet"
DEMO_URL          = "https://pocketoption.com/pt/cabinet/demo-quick-high-low/"
REAL_URL          = "https://pocketoption.com/pt/cabinet/quick-high-low/"
WAIT_WS_SECONDS   = int(os.environ.get("WAIT_WS_SECONDS", "15"))

# Valores “com aspas” para gravar no .env (mantidos)
ENV_QUOTED_DEFAULTS = {
    "WAIT_WS_MAX": "'600'",
    "PO_HTTP_API_BASE": "'https://api.pocketoption.com'",
    "PO_HTTP_ASSETS_PATH": "'/api/v1/assets'",
    "PO_HTTP_HISTORY_PATH": "'/api/v1/history'",
    "PO_VERIFY_SSL": "'false'",
    "PO_WS_RESOLVE_IP": "''",
    "PO_WS_SNI_HOST": "''",
    "BROWSER": "'chrome'",
    "HEADLESS": "'false'",
}

# ===== helpers =====
def _enable_cdp(driver):
    with contextlib.suppress(Exception):
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Page.enable", {})
        driver.execute_cdp_cmd("Log.enable", {})

def _build_driver_uc():
    import undetected_chromedriver as uc  # type: ignore
    opts = uc.ChromeOptions()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=pt-BR")
    opts.add_argument("--window-size=1280,900")
    with contextlib.suppress(Exception):
        opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = uc.Chrome(options=opts, use_subprocess=True)
    _enable_cdp(driver)
    return driver

def _build_driver_selenium():
    # importar webdriver_manager aqui, silenciando stdout/stderr
    with _silence_stdout_stderr():
        from webdriver_manager.chrome import ChromeDriverManager  # type: ignore

    chrome_opts = Options()
    chrome_opts.add_argument("--disable-blink-features=AutomationControlled")
    chrome_opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_opts.add_experimental_option("useAutomationExtension", False)
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_argument("--lang=pt-BR")
    chrome_opts.add_argument("--window-size=1280,900")
    chrome_opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    # também silenciamos o download/instalação do driver
    with _silence_stdout_stderr():
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=chrome_opts)
    with contextlib.suppress(Exception):
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"}
        )
    _enable_cdp(driver)
    return driver

def _get_performance_logs(driver) -> List[Dict]:
    with contextlib.suppress(Exception):
        return driver.get_log("performance")
    return []

# =========================
# SSID: extração a partir dos perf logs (WebSocket frames 42["auth", {...}])
# =========================
_SSID_PATTERN_DEMO = re.compile(r'(42\["auth",\{.*"session":"[^"]+",.*"isDemo":\s*1.*\}\])')
_SSID_PATTERN_REAL = re.compile(r'(42\["auth",\{.*"session":"[^"]+".*\}\])')

def _extract_ssid_from_perf_logs(perf_logs: List[Dict], *, expect_demo: Optional[bool]) -> str:
    if not perf_logs:
        return ""
    for entry in perf_logs:
        try:
            msg = json.loads(entry["message"])["message"]
        except Exception:
            continue
        method = msg.get("method")
        if method not in ("Network.webSocketFrameReceived", "Network.webSocketFrameSent"):
            continue
        payload = (msg.get("params", {}).get("response", {}) or {}).get("payloadData", "")
        if not isinstance(payload, str) or "42[\"auth\"" not in payload:
            continue
        if expect_demo is True:
            m = _SSID_PATTERN_DEMO.search(payload)
            if m:
                return m.group(1)
        elif expect_demo is False:
            m = _SSID_PATTERN_REAL.search(payload)
            if m:
                return m.group(1)
        else:
            m = _SSID_PATTERN_DEMO.search(payload) or _SSID_PATTERN_REAL.search(payload)
            if m:
                return m.group(1)
    return ""

def _validate_ssid(ssid: str, *, expect_demo: Optional[bool]) -> bool:
    try:
        if not ssid or not ssid.startswith("42["):
            return False
        data = json.loads(ssid[2:])[1]  # 0 = "auth", 1 = { ... }
        if "session" not in data:
            return False
        if expect_demo is True and data.get("isDemo") != 1:
            return False
        if expect_demo is False and data.get("isDemo") == 1:
            return False
        return True
    except Exception:
        return False

def _save_ssid_file(label: str, ssid: str, out_dir: Path):
    fname = "SSID_DEMO.txt" if label.upper() == "DEMO" else "SSID_REAL.txt"
    out_dir.mkdir(exist_ok=True)
    (out_dir / fname).write_text(ssid, encoding="utf-8")

def _extract_ws_and_http_from_logs(perf_logs: List[Dict]) -> Tuple[Set[str], Set[str], Set[str]]:
    ws_urls, rest_hosts, rest_paths = set(), set(), set()
    for entry in perf_logs:
        try:
            msg = json.loads(entry["message"])["message"]
        except Exception:
            continue
        method = msg.get("method")
        if method in ("Network.webSocketCreated", "Network.webSocketWillSendHandshakeRequest"):
            params = msg.get("params", {})
            url = params.get("url") or params.get("request", {}).get("url")
            if url and url.startswith("wss://") and "/socket.io" in url:
                ws_urls.add(url)
        elif method == "Network.requestWillBeSent":
            req = msg.get("params", {}).get("request", {}) or {}
            url = req.get("url") or ""
            if url.startswith("https://"):
                m = re.match(r"^https://([^/]+)(/.*)?$", url)
                if m:
                    host = m.group(1).lower()
                    path = (m.group(2) or "/").split("?")[0]
                    if "pocketoption.com" in host or "po.market" in host:
                        if "api" in host:
                            rest_hosts.add(f"https://{host}")
                    if "/api/" in path:
                        rest_paths.add(path)
    return ws_urls, rest_hosts, rest_paths

def _filter_ws_candidates(ws_urls: List[str]) -> List[str]:
    keep, seen = [], set()
    for u in ws_urls:
        try:
            p = urlparse(u); host = (p.hostname or "").lower()
            if host.endswith(".po.market") and "/socket.io" in p.path:
                if u not in seen:
                    keep.append(u); seen.add(u)
        except Exception:
            continue
    return keep

def _choose_ws_http_base_and_path(filtered_ws: List[str]) -> Tuple[str, str]:
    if not filtered_ws:
        return "", "/socket.io"
    p = urlparse(filtered_ws[0])
    base = f"https://{p.hostname}"
    m = re.search(r"(/socket\.io)", p.path)
    path = m.group(1) if m else "/socket.io"
    return base, path

def _pick_rest_base(rest_hosts: Set[str]) -> str:
    if not rest_hosts:
        return "https://api.pocketoption.com"
    pref = [h for h in rest_hosts if "api.pocketoption.com" in h]
    return sorted(pref)[0] if pref else sorted(rest_hosts)[0]

def _guess_rest_paths(rest_paths: Set[str]) -> Tuple[str, str]:
    assets, history = "/api/v1/assets", "/api/v1/history"
    for p in sorted(rest_paths):
        if "assets" in p:  assets = p; break
    for p in sorted(rest_paths):
        if "history" in p: history = p; break
    return assets, history

# ========= escrita do .env sem “spam” do python-dotenv
def _write_env_pairs(pairs: Dict[str, str], env_path: Path):
    """
    Atualiza o arquivo .env usando python-dotenv.set_key, com:
      - import tardio do set_key (evita logs precoces)
      - stdout/stderr silenciados apenas durante as operações
    Assim somem as linhas 'python-dotenv could not parse statement ...'
    """
    env_path = env_path.resolve()
    if not env_path.exists():
        env_path.write_text("", encoding="utf-8")

    # Import tardio do set_key com stdout/stderr silenciados
    with _silence_stdout_stderr():
        from dotenv import set_key as _dotenv_set_key  # type: ignore

    for k, v in pairs.items():
        with _silence_stdout_stderr():
            _dotenv_set_key(str(env_path), k, v)

# =========================
# COOKIES (CDP + Driver)
# =========================
def _collect_cf_cookie_line(driver, perf_logs: List[Dict]) -> str:
    jar = {}
    with contextlib.suppress(Exception):
        cookies = driver.get_cookies()
        for c in cookies:
            dom = (c.get("domain") or "").lstrip(".").lower()
            if ("pocketoption.com" in dom) or (dom.endswith("po.market")):
                name = c.get("name")
                if name:
                    jar[name] = c.get("value") or ""

    line_from_driver = ""
    if jar:
        ordered = []
        for key in ("cf_clearance", "_cfuvid"):
            if key in jar:
                ordered.append(f"{key}={jar[key]}")
        for k, v in jar.items():
            if k not in ("cf_clearance", "_cfuvid"):
                ordered.append(f"{k}={v}")
        line_from_driver = "; ".join(ordered)

    line_from_cdp = ""
    try:
        last_cookie_line = None
        last_ts = -1
        for entry in perf_logs:
            try:
                msg = json.loads(entry["message"])["message"]
            except Exception:
                continue
            if msg.get("method") != "Network.requestWillBeSent":
                continue
            params = msg.get("params", {})
            req = params.get("request", {}) or {}
            url = (req.get("url") or "").lower()
            if not (url.startswith("https://api.pocketoption.com") or ".po.market" in url):
                continue
            headers = req.get("headers") or {}
            cookie_hdr = headers.get("Cookie") or headers.get("cookie")
            if cookie_hdr:
                ts = params.get("timestamp") or 0
                if ts > last_ts:
                    last_ts = ts
                    last_cookie_line = str(cookie_hdr)
        if last_cookie_line:
            line_from_cdp = last_cookie_line.strip()
    except Exception:
        pass

    return line_from_cdp or line_from_driver

# =========================
# POKE nos endpoints
# =========================
def _poke_endpoints(driver, rest_base: str, assets_path: str, ws_http_base: str, socketio_path: str, wait_s: float = 3.0):
    try:
        api_url = rest_base.rstrip("/")
        assets_url = f"{api_url}{assets_path if assets_path.startswith('/') else '/'+assets_path}"
        driver.switch_to.new_window("tab")
        try:
            driver.get(api_url)
        except Exception:
            pass
        with contextlib.suppress(Exception):
            driver.get(assets_url)
        if ws_http_base and socketio_path:
            poll = f"{ws_http_base.rstrip('/')}{socketio_path}?EIO=4&transport=polling"
            with contextlib.suppress(Exception):
                driver.get(poll)
        time.sleep(wait_s)
    except Exception:
        pass
    finally:
        with contextlib.suppress(Exception):
            driver.close()
            driver.switch_to.window(driver.window_handles[0])

# ==============
# Coleta por "label" (DEMO/REAL)
# ==============
def _collect_context_for(driver, label: str, target_url: str) -> Tuple[Dict[str, str], str, str]:
    U = label.upper()
    log.info(f"🎯 [{U}] Acessando: {target_url}")
    driver.get(target_url)
    WebDriverWait(driver, 90).until(lambda d: d.current_url.startswith(target_url))

    log.info(f"⏱️  [{U}] Aguardando {WAIT_WS_SECONDS}s para tráfego WS/REST…")
    time.sleep(WAIT_WS_SECONDS)

    perf1 = _get_performance_logs(driver)
    log.info(f"📥 [{U}] Eventos de Performance (pré-poke): {len(perf1)}")

    ws_urls, rest_hosts, rest_paths = _extract_ws_and_http_from_logs(perf1)
    ws_candidates_all = sorted(ws_urls)
    ws_candidates = _filter_ws_candidates(ws_candidates_all)

    ws_http_base, socketio_path = _choose_ws_http_base_and_path(ws_candidates)
    rest_base = _pick_rest_base(rest_hosts)
    assets_path, history_path = _guess_rest_paths(rest_paths)
    origin = "https://pocketoption.com"
    ua = driver.execute_script("return navigator.userAgent") or ""

    _poke_endpoints(driver, rest_base, assets_path, ws_http_base, socketio_path, wait_s=3.0)

    perf2 = _get_performance_logs(driver)
    perf_all = (perf1 or []) + (perf2 or [])
    log.info(f"📥 [{U}] Eventos de Performance (pós-poke): {len(perf2)} | total: {len(perf_all)}")

    cookie_line = _collect_cf_cookie_line(driver, perf_all)

    expect_demo = True if U == "DEMO" else False
    ssid = _extract_ssid_from_perf_logs(perf_all, expect_demo=expect_demo)
    if ssid and _validate_ssid(ssid, expect_demo=expect_demo):
        log.info(f"🔐 [{U}] SSID capturado com sucesso.")
    else:
        log.warning(f"⚠️ [{U}] Não foi possível capturar um SSID válido.")
        ssid = ""

    env_pairs = {
        f"PO_{U}_WS_HTTP_BASE": ws_http_base,
        f"PO_{U}_SOCKETIO_PATH": socketio_path or "/socket.io",
        f"PO_{U}_WS_ORIGIN": origin,
        f"PO_{U}_WS_UA": ua,
        f"PO_{U}_WS_CANDIDATES": ",".join(ws_candidates),
        # REST
        f"PO_{U}_HTTP_API_BASE": rest_base if rest_base else ENV_QUOTED_DEFAULTS["PO_HTTP_API_BASE"].strip("'"),
        f"PO_{U}_HTTP_ASSETS_PATH": assets_path if assets_path else ENV_QUOTED_DEFAULTS["PO_HTTP_ASSETS_PATH"].strip("'"),
        f"PO_{U}_HTTP_HISTORY_PATH": history_path if history_path else ENV_QUOTED_DEFAULTS["PO_HTTP_HISTORY_PATH"].strip("'"),
    }
    return env_pairs, cookie_line, ssid

# ==============
# Renderização de Snapshot
# ==============
def _render_snapshot(
    *,
    cookie_line: str,
    generic_ws: Dict[str, str],
    demo_pairs: Dict[str, str],
    real_pairs: Dict[str, str],
    rest_common: Dict[str, str],
    mode: str,
    ssid_demo: str,
    ssid_real: str,
    wait_ws_max: str,
    verify_ssl: str,
    ws_resolve_ip: str,
    ws_sni_host: str,
    browser: str,
    headless: str,
    user_agent: str,
    wait_ws_seconds: str
) -> str:
    def g(d, k, default=""):
        return d.get(k, default)

    PO_WS_HTTP_BASE   = generic_ws.get("PO_WS_HTTP_BASE", "")
    PO_SOCKETIO_PATH  = generic_ws.get("PO_SOCKETIO_PATH", "")
    PO_WS_ORIGIN      = generic_ws.get("PO_WS_ORIGIN", "")
    PO_WS_UA          = generic_ws.get("PO_WS_UA", "")
    PO_WS_CANDIDATES  = generic_ws.get("PO_WS_CANDIDATES", "")

    PO_DEMO_WS_HTTP_BASE  = g(demo_pairs, "PO_DEMO_WS_HTTP_BASE")
    PO_DEMO_SOCKETIO_PATH = g(demo_pairs, "PO_DEMO_SOCKETIO_PATH")
    PO_DEMO_WS_ORIGIN     = g(demo_pairs, "PO_DEMO_WS_ORIGIN")
    PO_DEMO_WS_UA         = g(demo_pairs, "PO_DEMO_WS_UA")
    PO_DEMO_WS_CANDIDATES = g(demo_pairs, "PO_DEMO_WS_CANDIDATES")

    PO_REAL_WS_HTTP_BASE  = g(real_pairs, "PO_REAL_WS_HTTP_BASE")
    PO_REAL_SOCKETIO_PATH = g(real_pairs, "PO_REAL_SOCKETIO_PATH")
    PO_REAL_WS_ORIGIN     = g(real_pairs, "PO_REAL_WS_ORIGIN")
    PO_REAL_WS_UA         = g(real_pairs, "PO_REAL_WS_UA")
    PO_REAL_WS_CANDIDATES = g(real_pairs, "PO_REAL_WS_CANDIDATES")

    PO_HTTP_API_BASE      = g(rest_common, "PO_HTTP_API_BASE", "https://api.pocketoption.com")
    PO_HTTP_ASSETS_PATH   = g(rest_common, "PO_HTTP_ASSETS_PATH", "/api/v1/assets")
    PO_HTTP_HISTORY_PATH  = g(rest_common, "PO_HTTP_HISTORY_PATH", "/api/v1/history")
    PO_DEMO_HTTP_API_BASE     = g(rest_common, "PO_DEMO_HTTP_API_BASE", PO_HTTP_API_BASE)
    PO_DEMO_HTTP_ASSETS_PATH  = g(rest_common, "PO_DEMO_HTTP_ASSETS_PATH", PO_HTTP_ASSETS_PATH)
    PO_DEMO_HTTP_HISTORY_PATH = g(rest_common, "PO_DEMO_HTTP_HISTORY_PATH", PO_HTTP_HISTORY_PATH)
    PO_REAL_HTTP_API_BASE     = g(rest_common, "PO_REAL_HTTP_API_BASE", PO_HTTP_API_BASE)
    PO_REAL_HTTP_ASSETS_PATH  = g(rest_common, "PO_REAL_HTTP_ASSETS_PATH", PO_HTTP_ASSETS_PATH)
    PO_REAL_HTTP_HISTORY_PATH = g(rest_common, "PO_REAL_HTTP_HISTORY_PATH", PO_HTTP_HISTORY_PATH)

    lines = []
    lines += [
        "###########################",
        "# MODO DE CONTA ",
        "###########################",
        "# PRACTICE | REAL",
        f"PO_ACCOUNT_MODE={mode}",
        "",
        "###########################",
        "# CREDENCIAIS / SESSÕES",
        "###########################",
    ]
    if mode == "PRACTICE" and ssid_demo:
        lines.append(f'POCKET_OPTION_SSID_DEMO="{ssid_demo}"')
    if mode == "REAL" and ssid_real:
        lines.append(f'POCKET_OPTION_SSID_REAL="{ssid_real}"')
    lines += [
        "",
        "###########################",
        "# COOKIES CLOUDFLARE",
        "###########################",
        f"PO_EXTRA_COOKIES={cookie_line}",
        "",
        "###########################",
        "# ENDPOINTS / WEBSOCKET",
        "###########################",
        f"PO_WS_HTTP_BASE={PO_WS_HTTP_BASE}",
        f"PO_SOCKETIO_PATH={PO_SOCKETIO_PATH}",
        f"PO_WS_ORIGIN={PO_WS_ORIGIN}",
        f"PO_WS_UA={PO_WS_UA}",
        f"PO_WS_CANDIDATES={PO_WS_CANDIDATES}",
        f"WAIT_WS_MAX={wait_ws_max}",
        "########################################################",
        "# PERFIL DEMO (USADO QUANDO PO_ACCOUNT_MODE=PRACTICE)",
        "########################################################",
        f"PO_DEMO_WS_ORIGIN={PO_DEMO_WS_ORIGIN}",
        f"PO_DEMO_WS_UA={PO_DEMO_WS_UA}",
        f"PO_DEMO_WS_CANDIDATES={PO_DEMO_WS_CANDIDATES}",
        f"PO_DEMO_WS_HTTP_BASE={PO_DEMO_WS_HTTP_BASE}",
        f"PO_DEMO_SOCKETIO_PATH={PO_DEMO_SOCKETIO_PATH}",
        "",
        "########################################################",
        "# PERFIL REAL (USADO QUANDO PO_ACCOUNT_MODE=REAL)",
        "########################################################",
        f"PO_REAL_WS_ORIGIN={PO_REAL_WS_ORIGIN}",
        f"PO_REAL_WS_UA={PO_REAL_WS_UA}",
        f"PO_REAL_WS_CANDIDATES={PO_REAL_WS_CANDIDATES}",
        f"PO_REAL_WS_HTTP_BASE={PO_REAL_WS_HTTP_BASE}",
        f"PO_REAL_SOCKETIO_PATH={PO_REAL_SOCKETIO_PATH}",
        "",
        "##############",
        "# HTTP REST ",
        "##############",
        f"PO_HTTP_API_BASE={PO_HTTP_API_BASE}",
        f"PO_HTTP_ASSETS_PATH={PO_HTTP_ASSETS_PATH}",
        f"PO_HTTP_HISTORY_PATH={PO_HTTP_HISTORY_PATH}",
        f"PO_DEMO_HTTP_API_BASE={PO_DEMO_HTTP_API_BASE}",
        f"PO_DEMO_HTTP_ASSETS_PATH={PO_DEMO_HTTP_ASSETS_PATH}",
        f"PO_DEMO_HTTP_HISTORY_PATH={PO_DEMO_HTTP_HISTORY_PATH}",
        f"PO_REAL_HTTP_API_BASE={PO_REAL_HTTP_API_BASE}",
        f"PO_REAL_HTTP_ASSETS_PATH={PO_REAL_HTTP_ASSETS_PATH}",
        f"PO_REAL_HTTP_HISTORY_PATH={PO_REAL_HTTP_HISTORY_PATH}",
        "",
        "#####################",
        "# SSL / Diagnóstico",
        "#####################",
        "# Em produção, ideal é true. Use false só para depurar.",
        f"PO_VERIFY_SSL={verify_ssl}",
        "",
        "#####################",
        "# Overrides DNS/SNI",
        "#####################",
        f"PO_WS_RESOLVE_IP={ws_resolve_ip}",
        f"PO_WS_SNI_HOST={ws_sni_host}",
        "",
        "#########################",
        "# Navegador / WebDriver",
        "#########################",
        f"BROWSER={browser}",
        f"HEADLESS={headless}",
        f"USER_AGENT={user_agent}",
        f"WAIT_WS_SECONDS={wait_ws_seconds}",
        "",
    ]
    return "\n".join(lines)

# ==============
# MAIN
# ==============
def main():
    out_dir = Path("GET_SSID"); out_dir.mkdir(exist_ok=True)
    env_path = Path(".env")
    snapshot_demo = out_dir / "ENDPOINTS_DEMO.env"
    snapshot_real = out_dir / "ENDPOINTS_REAL.env"

    driver = None
    try:
        # 3) Silencia apenas o STDOUT de libs barulhentas;
        #    o nosso log vai para STDERR e continua aparecendo.
        with _silence_stdout_only():
            if USE_UC:
                log.info("➡️  Iniciando Navegador Chrome . . .")
                driver = _build_driver_uc()
            else:
                log.info("➡️  Iniciando Chrome com Selenium padrão (perfil temporário)…")
                driver = _build_driver_selenium()

            # login
            log.info(f"🌐 Acessando página de login: {LOGIN_URL}")
            driver.get(LOGIN_URL)
            log.info(f"⏳ Aguardando login manual e redirecionamento para {CABINET_BASE}…")
            WebDriverWait(driver, 9999).until(lambda d: CABINET_BASE in d.current_url)
            log.info("🔓 Login Bem Sucedido! Página carregada com Sucesso.")

            # ===== DEMO =====
            demo_pairs, cookie_line_demo, ssid_demo = _collect_context_for(driver, "DEMO", DEMO_URL)

            # ===== REAL =====
            real_pairs, cookie_line_real, ssid_real = _collect_context_for(driver, "REAL", REAL_URL)

            # cookies (preferimos o mais completo)
            cookie_line = cookie_line_real or cookie_line_demo or ""
            log.info(f"🍪 Linha de cookies coletada: {cookie_line if cookie_line else '(vazio)'}")

            # Salva SSIDs em arquivos (se capturados)
            if ssid_demo:
                _save_ssid_file("DEMO", ssid_demo, out_dir)
            if ssid_real:
                _save_ssid_file("REAL", ssid_real, out_dir)

            # Defaults comuns
            common_defaults = {
                "WAIT_WS_MAX": ENV_QUOTED_DEFAULTS["WAIT_WS_MAX"],
                "PO_VERIFY_SSL": ENV_QUOTED_DEFAULTS["PO_VERIFY_SSL"],
                "PO_WS_RESOLVE_IP": ENV_QUOTED_DEFAULTS["PO_WS_RESOLVE_IP"],
                "PO_WS_SNI_HOST": ENV_QUOTED_DEFAULTS["PO_WS_SNI_HOST"],
                "BROWSER": ENV_QUOTED_DEFAULTS["BROWSER"],
                "HEADLESS": ENV_QUOTED_DEFAULTS["HEADLESS"],
                "PO_EXTRA_COOKIES": cookie_line,
            }

            # UA genérica + tempos
            with contextlib.suppress(Exception):
                ua_any = driver.execute_script("return navigator.userAgent") or ""
            common_runtime = {
                "USER_AGENT": ua_any,
                "WAIT_WS_SECONDS": str(WAIT_WS_SECONDS),
            }

            def _get(key, dct, default=""):
                return dct.get(key, default)

            demo_cands = _get("PO_DEMO_WS_CANDIDATES", demo_pairs, "")
            real_cands = _get("PO_REAL_WS_CANDIDATES", real_pairs, "")

            def _union_csv(a: str, b: str) -> str:
                seen, out = set(), []
                for s in (a.split(",") + b.split(",")):
                    s = s.strip()
                    if s and s not in seen:
                        out.append(s); seen.add(s)
                return ",".join(out)

            generic_ws = {
                "PO_WS_HTTP_BASE":  _get("PO_REAL_WS_HTTP_BASE", real_pairs) or _get("PO_DEMO_WS_HTTP_BASE", demo_pairs) or "https://api-eu.po.market",
                "PO_SOCKETIO_PATH": _get("PO_REAL_SOCKETIO_PATH", real_pairs) or _get("PO_DEMO_SOCKETIO_PATH", demo_pairs) or "/socket.io",
                "PO_WS_ORIGIN":     _get("PO_REAL_WS_ORIGIN", real_pairs) or _get("PO_DEMO_WS_ORIGIN", demo_pairs) or "https://pocketoption.com",
                "PO_WS_UA":         _get("PO_REAL_WS_UA", real_pairs) or _get("PO_DEMO_WS_UA", demo_pairs) or ua_any,
                "PO_WS_CANDIDATES": _union_csv(real_cands, demo_cands),
            }

            # ---------- REST comuns ----------
            rest_common = {
                "PO_HTTP_API_BASE": _get(
                    "PO_REAL_HTTP_API_BASE",
                    real_pairs,
                    _get("PO_DEMO_HTTP_API_BASE", demo_pairs, "https://api.pocketoption.com"),
                ),
                "PO_HTTP_ASSETS_PATH": _get(
                    "PO_REAL_HTTP_ASSETS_PATH",
                    real_pairs,
                    _get("PO_DEMO_HTTP_ASSETS_PATH", demo_pairs, "/api/v1/assets"),
                ),
                "PO_HTTP_HISTORY_PATH": _get(
                    "PO_REAL_HTTP_HISTORY_PATH",
                    real_pairs,
                    _get("PO_DEMO_HTTP_HISTORY_PATH", demo_pairs, "/api/v1/history"),
                ),
                "PO_DEMO_HTTP_API_BASE":  _get("PO_DEMO_HTTP_API_BASE", demo_pairs, "https://api.pocketoption.com"),
                "PO_DEMO_HTTP_ASSETS_PATH": _get("PO_DEMO_HTTP_ASSETS_PATH", demo_pairs, "/api/v1/assets"),
                "PO_DEMO_HTTP_HISTORY_PATH": _get("PO_DEMO_HTTP_HISTORY_PATH", demo_pairs, "/api/v1/history"),
                "PO_REAL_HTTP_API_BASE":  _get("PO_REAL_HTTP_API_BASE", real_pairs, "https://api.pocketoption.com"),
                "PO_REAL_HTTP_ASSETS_PATH": _get("PO_REAL_HTTP_ASSETS_PATH", real_pairs, "/api/v1/assets"),
                "PO_REAL_HTTP_HISTORY_PATH": _get("PO_REAL_HTTP_HISTORY_PATH", real_pairs, "/api/v1/history"),
            }

            # ---------- Snapshots ----------
            snapshot_demo.write_text(
                _render_snapshot(
                    cookie_line=cookie_line,
                    generic_ws=generic_ws,
                    demo_pairs=demo_pairs,
                    real_pairs=real_pairs,
                    rest_common=rest_common,
                    mode="PRACTICE",
                    ssid_demo=ssid_demo or "",
                    ssid_real="",
                    wait_ws_max="600",
                    verify_ssl="false",
                    ws_resolve_ip="",
                    ws_sni_host="",
                    browser="chrome",
                    headless="false",
                    user_agent=ua_any,
                    wait_ws_seconds=str(WAIT_WS_SECONDS),
                ),
                encoding="utf-8"
            )
            log.info(f"💾 Snapshot DEMO salvo: {snapshot_demo}")

            snapshot_real.write_text(
                _render_snapshot(
                    cookie_line=cookie_line,
                    generic_ws=generic_ws,
                    demo_pairs=demo_pairs,
                    real_pairs=real_pairs,
                    rest_common=rest_common,
                    mode="REAL",
                    ssid_demo="",
                    ssid_real=ssid_real or "",
                    wait_ws_max="600",
                    verify_ssl="false",
                    ws_resolve_ip="",
                    ws_sni_host="",
                    browser="chrome",
                    headless="false",
                    user_agent=ua_any,
                    wait_ws_seconds=str(WAIT_WS_SECONDS),
                ),
                encoding="utf-8"
            )
            log.info(f"💾 Snapshot REAL salvo: {snapshot_real}")

            # ---------- Atualiza .env ----------
            _write_env_pairs(common_defaults, env_path)
            _write_env_pairs(common_runtime, env_path)
            _write_env_pairs(demo_pairs, env_path)
            _write_env_pairs(real_pairs, env_path)
            # Grava SSIDs no .env (entre aspas)
            if ssid_demo:
                _write_env_pairs({"POCKET_OPTION_SSID_DEMO": f'"{ssid_demo}"'}, env_path)
            if ssid_real:
                _write_env_pairs({"POCKET_OPTION_SSID_REAL": f'"{ssid_real}"'}, env_path)

            # Logs bonitinhos dos candidatos
            for tag, pairs in (("DEMO", demo_pairs), ("REAL", real_pairs)):
                cands = pairs.get(f"PO_{tag}_WS_CANDIDATES", "")
                log.info(f"🔌 WS Candidates [{tag}] (*.po.market):")
                for u in (cands.split(",") if cands else []):
                    if u.strip():
                        log.info(f"  • {u.strip()}")

            log.info("✅ Arquivo .env capturado, atualizado e snapshots com PO_EXTRA_COOKIES + WS/REST gerados com Sucesso")
            if ssid_demo or ssid_real:
                log.info("✅ SSIDs (DEMO/REAL) capturados, atualizados e salvos em GET_SSID/SSID_*.txt e no teu arquivo .env com Sucesso")

    finally:
        if driver:
            with _silence_stdout_stderr():
                with contextlib.suppress(Exception):
                    driver.quit()
        driver = None
        time.sleep(0.2)
        gc.collect()
        log.info("🚪 WebDriver Fechado.")

if __name__ == "__main__":
    main()
