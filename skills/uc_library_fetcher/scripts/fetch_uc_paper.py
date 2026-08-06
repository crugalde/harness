import sys
import asyncio
import os
from pathlib import Path
from urllib.parse import quote
from playwright.async_api import async_playwright

# El .env vive fuera del repo (~/.config/harness/.env) y hay que cargarlo
# explícitamente: os.getenv solo ve lo que ya está exportado en el shell.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try:
    from tools.env_loader import load_env
except ImportError:  # ejecutado fuera del árbol del harness
    load_env = None


async def main():
    if len(sys.argv) < 3:
        print("Usage: uv run fetch_uc_paper.py <doi_or_url> <output_pdf_path>")
        sys.exit(1)

    target = sys.argv[1]
    out_path = sys.argv[2]

    if load_env is not None:
        ruta = load_env()
        if ruta:
            print(f"[*] Credenciales cargadas desde {ruta}")

    uc_user = os.getenv("UC_USER")
    uc_pass = os.getenv("UC_PASSWORD")

    if not uc_user or not uc_pass:
        env_file = os.environ.get("HARNESS_ENV_FILE", "~/.config/harness/.env")
        print(f"Error: UC_USER o UC_PASSWORD no encontradas.\n"
              f"       Se buscaron en el entorno y en {env_file}.\n"
              f"       Guárdalas con los comandos de skills/uc_library_fetcher/SKILL.md\n"
              f"       (nunca las escribas en un chat ni las pases por argumento).",
              file=sys.stderr)
        sys.exit(1)

    async with async_playwright() as p:
        # Lanzamos SIEMPRE en headless=False para permitir la red de seguridad manual
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            accept_downloads=True
        )
        page = await context.new_page()

        url = f"https://doi.org/{target}" if target.startswith("10.") else target
        
        # Dejar que Playwright resuelva el DOI primero para evadir el antibot 403 de doi.org
        print(f"[*] Resolviendo DOI a través de navegador real para: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded")
            final_url = page.url
            print(f"[+] URL resuelta por Playwright: {final_url}")
        except Exception as e:
            print(f"[-] Error navegando al DOI, usando original. ({e})")
            final_url = url

        print(f"[*] Transformando a formato Zotero (EZproxy wildcard) para evadir menú por defecto...")
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(final_url)
        # Zotero: www.nejm.org -> www-nejm-org.pucdechile.idm.oclc.org
        domain_rewritten = parsed.netloc.replace(".", "-") + ".pucdechile.idm.oclc.org"
        proxy_login_url = urlunparse((parsed.scheme, domain_rewritten, parsed.path, parsed.params, parsed.query, parsed.fragment))

        print(f"[*] Navegando al proxy CAS: {proxy_login_url}")
        try:
            await page.goto(proxy_login_url, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[-] Error de red al navegar: {e}")

        try:
            print("[*] Verificando login CAS UC...")
            await page.wait_for_selector('input[type="password"]', timeout=5000)
            print("[+] Login detectado. Inyectando credenciales silenciosamente...")
            
            await page.fill('input[type="text"], input[type="email"], input[name="username"]', uc_user)
            await page.fill('input[type="password"]', uc_pass)
            
            await page.click('button[type="submit"], input[type="submit"], input.btn-submit, .login-btn')
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            print("[!] No se detectó login o ya estaba autenticado.")

        print("[*] Analizando la página de la revista en busca del PDF...")
        await page.wait_for_timeout(3000)

        pdf_selectors = [
            "a:has-text('Download PDF')", "a:has-text('PDF')", "span:has-text('Download PDF')",
            "a[title='Download PDF']", "a[href$='.pdf']", "a[data-test='pdf-link']",
            "a.pdf-link", "button:has-text('PDF')", "#pdfLink", ".article-tools__pdf"
        ]

        download_started = False
        for selector in pdf_selectors:
            try:
                if await page.locator(selector).count() > 0:
                    print(f"[+] Botón de PDF encontrado ({selector}). Intentando descarga automática...")
                    async with page.expect_download(timeout=15000) as download_info:
                        await page.locator(selector).first.click()
                    download = await download_info.value
                    print(f"[*] Descarga interceptada. Guardando en: {out_path}")
                    await download.save_as(out_path)
                    download_started = True
                    break
            except Exception:
                continue

        if download_started:
            print("[+] ÉXITO: PDF descargado de forma 100% automática. Cerrando navegador.")
            await browser.close()
            return

        # FALLBACK: RED DE SEGURIDAD MANUAL
        print("\n" + "=" * 60)
        print("[-] FALLO HEURÍSTICO: El bot inyectó tus claves exitosamente, pero")
        print("    no logró localizar el botón del PDF en este diseño de página.")
        print("=" * 60)
        print(f"[!] ACCIÓN REQUERIDA: El navegador está abierto frente a ti.")
        print(f"    Busca el botón 'PDF', descárgalo y guárdalo exactamente en:\n    {out_path}")
        print("=" * 60)
        print("[!] Tienes 2 minutos antes de que el script se cierre por seguridad...")
        
        await page.wait_for_timeout(120000)
        print("[*] Tiempo agotado. Cerrando navegador.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
