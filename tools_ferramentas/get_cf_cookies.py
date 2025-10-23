"""
Autor: ByJhonesDev
Função:
- Acessa o domínio alvo (PO_WS_HTTP_BASE ou https://api-c.po.market), coleta os cookies do Cloudflare
  (cf_clearance e _cfuvid) via Selenium/Chrome e:
  1) Grava a linha de cookies em GET_SSID/CF_COOKIES.txt; e
  2) Atualiza o arquivo .env com a variável PO_EXTRA_COOKIES contendo a mesma linha.

Destaques:
- Usa Selenium com Chrome + webdriver_manager (baixa e gerencia o ChromeDriver automaticamente).
- Opções do Chrome para reduzir detecção de automação (disable-blink-features, excludeSwitches, etc.).
- Base configurável via variável de ambiente PO_WS_HTTP_BASE; fallback para https://api-c.po.market.
- Tentativa com espera fixa (8s) e retry com refresh caso os cookies não apareçam na primeira vez.
- Persistência dos cookies em arquivo (GET_SSID/CF_COOKIES.txt) e no .env (PO_EXTRA_COOKIES).
- Cria automaticamente a pasta GET_SSID e o .env (se não existir).
- Falha explícita com SystemExit se não obtiver cf_clearance/_cfuvid (instruindo abrir o domínio no Chrome).
- Encerra o driver com segurança no bloco finally, mesmo em caso de erro.
"""

import os
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import dotenv_values, set_key

DEFAULT_BASE = os.environ.get("PO_WS_HTTP_BASE", "https://api-c.po.market")

def update_env_cookie_line(env_path: Path, cookie_line: str):
    env_path = env_path.resolve()
    if not env_path.exists():
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("")
    set_key(str(env_path), "PO_EXTRA_COOKIES", cookie_line)

def main(base: str = DEFAULT_BASE):
    base = (base or DEFAULT_BASE).rstrip("/")
    out_dir = Path("GET_SSID")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "CF_COOKIES.txt"

    chrome_opts = Options()
    chrome_opts.add_argument("--disable-blink-features=AutomationControlled")
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_opts.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_opts)

    try:
        driver.get(base)
        time.sleep(8)
        cookies = driver.get_cookies()
        ck = {}
        for c in cookies:
            if c.get("name") in ("cf_clearance", "_cfuvid"):
                ck[c["name"]] = c.get("value")

        if not ck:
            driver.refresh()
            time.sleep(8)
            for c in driver.get_cookies():
                if c.get("name") in ("cf_clearance", "_cfuvid"):
                    ck[c["name"]] = c.get("value")

        if not ck:
            raise SystemExit("Falha ao obter cookies CF. Abra o domínio no Chrome e tente novamente.")

        parts = []
        if "cf_clearance" in ck: parts.append(f"cf_clearance={ck['cf_clearance']}")
        if "_cfuvid" in ck: parts.append(f"_cfuvid={ck['_cfuvid']}")
        line = "; ".join(parts)

        out_file.write_text(line, encoding="utf-8")
        print(f"✅ Cookies CF salvos em: {out_file} -> {line}")

        env_path = Path(".env")
        update_env_cookie_line(env_path, line)
        print("✅ .env atualizado com PO_EXTRA_COOKIES.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    main()
