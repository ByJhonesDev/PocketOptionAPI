"""
Autor: ByJhonesDev
Função: Abrir Chrome (UC se disponível), aguardar login manual no PocketOption e
capturar endpoints WebSocket/REST + cookies para DEMO e REAL, gravando em .env
com prefixos separados (PO_DEMO_* / PO_REAL_*) e Snapshots em GET_SSID/.

Destaques:
- Logger silencioso, UC fallback p/ Selenium, CDP habilitado, webdriver "disfarçado".
- Fluxo guiado: /login → /cabinet → DEMO → coleta → REAL → coleta.
- Heurísticas de descoberta de WS/REST, coleta de cookies (Cloudflare) e UA.
- Gera:
  - GET_SSID/ENDPOINTS_DEMO.env
  - GET_SSID/ENDPOINTS_REAL.env
  - Atualiza .env com pares PO_DEMO_* e PO_REAL_* (e PO_EXTRA_COOKIES).
"""

from __future__ import annotations
import os, re, json, time, contextlib, gc, sys, logging
from pathlib import Path
from typing import Dict, List, Set, Tuple
from urllib.parse import urlparse
from dotenv import set_key

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
    handler = logging.StreamHandler(sys.stdout)
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
    import undetected_chromedriver as uc  # type: ignore
    USE_UC = True
    with contextlib.suppress(Exception):
        uc.Chrome.__del__ = lambda self: None  # monkey-patch p/ silenciar __del__
except Exception:
    USE_UC = False

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

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
            req = msg.get("params", {}).get("request", {})
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

def _write_env_pairs(pairs: Dict[str, str], env_path: Path):
    env_path = env_path.resolve()
    if not env_path.exists():
        env_path.write_text("", encoding="utf-8")
    for k, v in pairs.items():
        set_key(str(env_path), k, v)

def _collect_cf_cookie_line(driver) -> str:
    cookies = driver.get_cookies()
    ck_domain = {}
    for c in cookies:
        dom = (c.get("domain") or "").lstrip(".").lower()
        if "pocketoption.com" in dom:
            ck_domain[c["name"]] = c.get("value") or ""
    if not ck_domain:
        return ""
    parts = []
    if "cf_clearance" in ck_domain:
        parts.append(f"cf_clearance={ck_domain['cf_clearance']}")
    if "_cfuvid" in ck_domain:
        parts.append(f"_cfuvid={ck_domain['_cfuvid']}")
    for k, v in ck_domain.items():
        if k not in ("cf_clearance", "_cfuvid"):
            parts.append(f"{k}={v}")
    return "; ".join(parts)

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

# ==============
# Coleta por "label" (DEMO/REAL)
# ==============
def _collect_context_for(driver, label: str, target_url: str) -> Tuple[Dict[str, str], str]:
    """
    Navega até 'target_url', espera carregar e coleta logs+cookies.
    Retorna dict de pares já prontos p/ .env com prefixo PO_{LABEL}_* e a linha de cookies.
    """
    U = label.upper()
    log.info(f"🎯 [{U}] Acessando: {target_url}")
    driver.get(target_url)
    WebDriverWait(driver, 90).until(lambda d: d.current_url.startswith(target_url))

    log.info(f"⏱️  [{U}] Aguardando {WAIT_WS_SECONDS}s para tráfego WS/REST…")
    time.sleep(WAIT_WS_SECONDS)

    perf = _get_performance_logs(driver)
    log.info(f"📥 [{U}] Eventos de Performance: {len(perf)}")

    ws_urls, rest_hosts, rest_paths = _extract_ws_and_http_from_logs(perf)
    ws_candidates_all = sorted(ws_urls)
    ws_candidates = _filter_ws_candidates(ws_candidates_all)

    ws_http_base, socketio_path = _choose_ws_http_base_and_path(ws_candidates)
    rest_base = _pick_rest_base(rest_hosts)
    assets_path, history_path = _guess_rest_paths(rest_paths)
    origin = "https://pocketoption.com"
    ua = driver.execute_script("return navigator.userAgent") or ""

    cookie_line = _collect_cf_cookie_line(driver)

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
    return env_pairs, cookie_line

# ==============
# Renderização de Snapshot (formato solicitado)
# ==============
def _render_snapshot(
    *,
    cookie_line: str,
    generic_ws: Dict[str, str],
    demo_pairs: Dict[str, str],
    real_pairs: Dict[str, str],
    rest_common: Dict[str, str],
    wait_ws_max: str,
    verify_ssl: str,
    ws_resolve_ip: str,
    ws_sni_host: str,
    browser: str,
    headless: str,
    user_agent: str,
    wait_ws_seconds: str
) -> str:
    """
    Monta o arquivo .env snapshot com o formato solicitado (blocos/cabeçalhos).
    As chaves genéricas (PO_WS_*) são baseadas na priorização REAL e união de candidatos.
    """
    def g(d, k, default=""):
        return d.get(k, default)

    # GENÉRICO (comuns)
    PO_WS_HTTP_BASE   = generic_ws.get("PO_WS_HTTP_BASE", "")
    PO_SOCKETIO_PATH  = generic_ws.get("PO_SOCKETIO_PATH", "")
    PO_WS_ORIGIN      = generic_ws.get("PO_WS_ORIGIN", "")
    PO_WS_UA          = generic_ws.get("PO_WS_UA", "")
    PO_WS_CANDIDATES  = generic_ws.get("PO_WS_CANDIDATES", "")

    # DEMO
    PO_DEMO_WS_HTTP_BASE  = g(demo_pairs, "PO_DEMO_WS_HTTP_BASE")
    PO_DEMO_SOCKETIO_PATH = g(demo_pairs, "PO_DEMO_SOCKETIO_PATH")
    PO_DEMO_WS_ORIGIN     = g(demo_pairs, "PO_DEMO_WS_ORIGIN")
    PO_DEMO_WS_UA         = g(demo_pairs, "PO_DEMO_WS_UA")
    PO_DEMO_WS_CANDIDATES = g(demo_pairs, "PO_DEMO_WS_CANDIDATES")

    # REAL
    PO_REAL_WS_HTTP_BASE  = g(real_pairs, "PO_REAL_WS_HTTP_BASE")
    PO_REAL_SOCKETIO_PATH = g(real_pairs, "PO_REAL_SOCKETIO_PATH")
    PO_REAL_WS_ORIGIN     = g(real_pairs, "PO_REAL_WS_ORIGIN")
    PO_REAL_WS_UA         = g(real_pairs, "PO_REAL_WS_UA")
    PO_REAL_WS_CANDIDATES = g(real_pairs, "PO_REAL_WS_CANDIDATES")

    # REST comuns (duplicado DEMO/REAL para espelhar o exemplo)
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
        if USE_UC:
            log.info("➡️  Iniciando Navegador Chrome . . .")
            driver = _build_driver_uc()
        else:
            log.info("➡️  Iniciando Chrome com Selenium padrão (profilo temporário)…")
            driver = _build_driver_selenium()

        # login
        log.info(f"🌐 Acessando página de login: {LOGIN_URL}")
        driver.get(LOGIN_URL)
        log.info(f"⏳ Aguardando login manual e redirecionamento para {CABINET_BASE}…")
        WebDriverWait(driver, 9999).until(lambda d: CABINET_BASE in d.current_url)
        log.info("🔓 Login Bem Sucedido! Página carregada com Sucesso.")

        # ===== DEMO =====
        demo_pairs, cookie_line_demo = _collect_context_for(driver, "DEMO", DEMO_URL)

        # ===== REAL =====
        real_pairs, cookie_line_real = _collect_context_for(driver, "REAL", REAL_URL)

        # cookies (preferimos o mais completo)
        cookie_line = cookie_line_real or cookie_line_demo or ""
        log.info(f"🍪 Linha de cookies coletada: {cookie_line if cookie_line else '(vazio)'}")

        # Monta defaults comuns (para o .env manteremos com aspas conforme política)
        common_defaults = {
            "WAIT_WS_MAX": ENV_QUOTED_DEFAULTS["WAIT_WS_MAX"],
            "PO_VERIFY_SSL": ENV_QUOTED_DEFAULTS["PO_VERIFY_SSL"],
            "PO_WS_RESOLVE_IP": ENV_QUOTED_DEFAULTS["PO_WS_RESOLVE_IP"],
            "PO_WS_SNI_HOST": ENV_QUOTED_DEFAULTS["PO_WS_SNI_HOST"],
            "BROWSER": ENV_QUOTED_DEFAULTS["BROWSER"],
            "HEADLESS": ENV_QUOTED_DEFAULTS["HEADLESS"],
            "PO_EXTRA_COOKIES": cookie_line,  # sem aspas
        }

        # UA genérica + tempos
        with contextlib.suppress(Exception):
            ua_any = driver.execute_script("return navigator.userAgent") or ""
        common_runtime = {
            "USER_AGENT": ua_any,
            "WAIT_WS_SECONDS": str(WAIT_WS_SECONDS),
        }

        # ---------- GENÉRICOS (PO_WS_*) ----------
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
            "PO_HTTP_API_BASE": _get("PO_REAL_HTTP_API_BASE", real_pairs, _get("PO_DEMO_HTTP_API_BASE", demo_pairs, "https://api.pocketoption.com")),
            "PO_HTTP_ASSETS_PATH": _get("PO_REAL_HTTP_ASSETS_PATH", real_pairs, _get("PO_DEMO_HTTP_ASSETS_PATH", demo_pairs, "/api/v1/assets")),
            "PO_HTTP_HISTORY_PATH": _get("PO_REAL_HTTP_HISTORY_PATH", real_pairs, _get("PO_DEMO_HTTP_HISTORY_PATH", demo_pairs, "/api/v1/history")),
            "PO_DEMO_HTTP_API_BASE":  _get("PO_DEMO_HTTP_API_BASE", demo_pairs, "https://api.pocketoption.com"),
            "PO_DEMO_HTTP_ASSETS_PATH": _get("PO_DEMO_HTTP_ASSETS_PATH", demo_pairs, "/api/v1/assets"),
            "PO_DEMO_HTTP_HISTORY_PATH": _get("PO_DEMO_HTTP_HISTORY_PATH", demo_pairs, "/api/v1/history"),
            "PO_REAL_HTTP_API_BASE":  _get("PO_REAL_HTTP_API_BASE", real_pairs, "https://api.pocketoption.com"),
            "PO_REAL_HTTP_ASSETS_PATH": _get("PO_REAL_HTTP_ASSETS_PATH", real_pairs, "/api/v1/assets"),
            "PO_REAL_HTTP_HISTORY_PATH": _get("PO_REAL_HTTP_HISTORY_PATH", real_pairs, "/api/v1/history"),
        }

        # ---------- Snapshots (com cabeçalhos e PO_EXTRA_COOKIES) ----------
        snapshot_demo.write_text(
            _render_snapshot(
                cookie_line=cookie_line,
                generic_ws=generic_ws,
                demo_pairs=demo_pairs,
                real_pairs=real_pairs,
                rest_common=rest_common,
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

        # Logs bonitinhos dos candidatos
        for tag, pairs in (("DEMO", demo_pairs), ("REAL", real_pairs)):
            cands = pairs.get(f"PO_{tag}_WS_CANDIDATES", "")
            log.info(f"🔌 WS Candidates [{tag}] (*.po.market):")
            for u in (cands.split(",") if cands else []):
                if u.strip():
                    log.info(f"  • {u.strip()}")

        log.info("✅ .env atualizado e snapshots com PO_EXTRA_COOKIES + WS/REST gerados com sucesso")

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
