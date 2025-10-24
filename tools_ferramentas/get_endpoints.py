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
  - GET_SSID/CF_COOKIES.txt
  - Atualiza .env com pares PO_DEMO_* e PO_REAL_*.
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

# Valores “com aspas” como solicitado
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
def _collect_context_for(driver, label: str, target_url: str) -> Dict[str, str]:
    """
    Navega até 'target_url', espera carregar e coleta logs+cookies.
    Retorna dict de pares já prontos p/ .env com prefixo PO_{LABEL}_*.
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

    # cookies (apenas grava uma vez fora; aqui devolvemos a linha)
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

def main():
    out_dir = Path("GET_SSID"); out_dir.mkdir(exist_ok=True)
    env_path = Path(".env")
    snapshot_demo = out_dir / "ENDPOINTS_DEMO.env"
    snapshot_real = out_dir / "ENDPOINTS_REAL.env"
    cookies_file = out_dir / "CF_COOKIES.txt"

    driver = None
    try:
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
        demo_pairs, cookie_line_demo = _collect_context_for(driver, "DEMO", DEMO_URL)

        # ===== REAL =====
        real_pairs, cookie_line_real = _collect_context_for(driver, "REAL", REAL_URL)

        # cookies (provavelmente iguais, mas preferimos o mais completo)
        cookie_line = cookie_line_real or cookie_line_demo or ""
        cookies_file.write_text(cookie_line, encoding="utf-8")
        log.info(f"💾 Cookies salvos: {cookies_file} -> {cookie_line if cookie_line else '(vazio)'}")

        # Monta blocos com defaults comuns "com aspas"
        common_defaults = {
            "WAIT_WS_MAX": ENV_QUOTED_DEFAULTS["WAIT_WS_MAX"],
            "PO_VERIFY_SSL": ENV_QUOTED_DEFAULTS["PO_VERIFY_SSL"],
            "PO_WS_RESOLVE_IP": ENV_QUOTED_DEFAULTS["PO_WS_RESOLVE_IP"],
            "PO_WS_SNI_HOST": ENV_QUOTED_DEFAULTS["PO_WS_SNI_HOST"],
            "BROWSER": ENV_QUOTED_DEFAULTS["BROWSER"],
            "HEADLESS": ENV_QUOTED_DEFAULTS["HEADLESS"],
            "PO_EXTRA_COOKIES": cookie_line,
        }

        # UA genérica (p/ requests HTTP) + tempos
        with contextlib.suppress(Exception):
            ua_any = driver.execute_script("return navigator.userAgent") or ""
        common_runtime = {
            "USER_AGENT": ua_any,
            "WAIT_WS_SECONDS": str(WAIT_WS_SECONDS),
        }

        # Snapshots separados
        def _fmt_snapshot(pairs: Dict[str, str]) -> str:
            return "\n".join(f"{k}={v}" for k, v in pairs.items()) + "\n"

        snapshot_demo.write_text(
            _fmt_snapshot({**demo_pairs, **common_defaults, **common_runtime}), encoding="utf-8"
        )
        log.info(f"💾 Snapshot DEMO salvo: {snapshot_demo}")

        snapshot_real.write_text(
            _fmt_snapshot({**real_pairs, **common_defaults, **common_runtime}), encoding="utf-8"
        )
        log.info(f"💾 Snapshot REAL salvo: {snapshot_real}")

        # Atualiza .env → grava TODOS os pares (com aspas nos defaults)
        # 1) comuns
        _write_env_pairs(common_defaults, env_path)
        _write_env_pairs(common_runtime, env_path)
        # 2) DEMO/REAL
        _write_env_pairs(demo_pairs, env_path)
        _write_env_pairs(real_pairs, env_path)

        # Logs bonitinhos dos candidatos
        for tag, pairs in (("DEMO", demo_pairs), ("REAL", real_pairs)):
            cands = pairs.get(f"PO_{tag}_WS_CANDIDATES", "")
            log.info(f"🔌 WS Candidates [{tag}] (*.po.market):")
            for u in (cands.split(",") if cands else []):
                if u.strip():
                    log.info(f"  • {u.strip()}")

        log.info("✅ Arquivo .env gerado e atualizado com DEMO e REAL + Cookies/REST/WS/Navegador com Sucesso")

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
