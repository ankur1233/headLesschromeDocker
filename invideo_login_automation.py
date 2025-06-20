#!/usr/bin/env python3
"""
Script d'automatisation pour le login InVideo avec Google Auth et proxy
"""

import time
import logging
from selenium import webdriver as selenium_webdriver
try:
    from seleniumwire import webdriver as wire_webdriver
    SELENIUM_WIRE_AVAILABLE = True
except ImportError:
    SELENIUM_WIRE_AVAILABLE = False
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys
import json
import re
import os

# Charger les variables d'environnement depuis .env
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# --- MySQL ---------------------------------------------------
import mysql.connector
from mysql.connector import Error as MySQLError

# Configuration
PROXY_IP = "154.217.199.116"
PROXY_PORT = "5411"
PROXY_USER = "KC8CK0AVI8AEFD2S6XXV"
PROXY_PASS = "08yxk5qhfri4tufvkifz"
AUTH_URL = "https://ai.invideo.io/login"
POST_AUTH_URL_PREFIX = "https://ai.invideo.io/workspaces"

# Identifiants Google
EMAIL = "spyboxsetup@gmail.com"
PASSWORD = "gasKHg5iW6RC*xXO"

# -------------------------------------------------------------
# Paramètres base de données
# -------------------------------------------------------------
DB_HOST = "ec2-13-39-112-219.eu-west-3.compute.amazonaws.com"
DB_PORT = 3306
DB_USER = "spybox_user_6p9Ae"
DB_PASSWORD = "qj01cvXTj5WqLLzn2D2RvUCbuAYcRUKkNlasEhmvPx4dUYr8ZU"
DB_NAME = "spybox_database"
DB_COLLATION = "utf8mb4_general_ci"
DB_USER_ID = 112  # id de la ligne à mettre à jour

# Configuration du logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Définir HEADLESS via variable d'environnement (par défaut 1)
HEADLESS_DEFAULT = os.getenv("HEADLESS", "1") in ("1", "true", "True", "yes", "YES")


def setup_proxy_auth_extension():
    """Crée une extension Chrome pour l'authentification proxy"""
    import zipfile
    import os

    manifest_json = """
{
"version": "1.0.0",
"manifest_version": 3,
"name": "Chrome Proxy Auth",
"permissions": [
    "proxy",
    "tabs",
    "unlimitedStorage",
    "storage",
    "webRequest",
    "webRequestAuthProvider"

],
"host_permissions": [
    "*://*/*"
],
"background": {
    "service_worker": "background.js"
},
"minimum_chrome_version":"108"
}"""

    background_js = f"""
    console.log("Proxy Auth Extension Service Worker starting up.");

    const config = {{
        mode: "fixed_servers",
        rules: {{
            singleProxy: {{
                scheme: "http",
                host: "{PROXY_IP}",
                port: parseInt("{PROXY_PORT}")
            }},
            bypassList: ["localhost", "127.0.0.1", "httpbin.org"]
        }}
    }};

    chrome.proxy.settings.set({{value: config, scope: "regular"}}, () => {{
        if (chrome.runtime.lastError) {{
            console.error("Proxy configuration failed:", chrome.runtime.lastError);
        }} else {{
            console.log("Proxy configuration applied:", config);
        }}
    }});

    // Synchronous authentication handler (recommended approach)
    function onAuthRequiredHandler(details) {{
        console.log("Proxy authentication required for:", details.url);
        return {{
            authCredentials: {{
                username: "{PROXY_USER}",
                password: "{PROXY_PASS}"
            }}
        }};
    }}

    // Register the authentication listener
    chrome.webRequest.onAuthRequired.addListener(
        onAuthRequiredHandler,
        {{urls: ["*://*/*"]}},
        ['blocking']
    );

    console.log("Proxy auth listeners registered successfully");
    """

    # Créer le dossier pour l'extension
    extension_dir = "proxy_auth_extension"
    if not os.path.exists(extension_dir):
        os.makedirs(extension_dir)

    # Écrire les fichiers de l'extension
    with open(f"{extension_dir}/manifest.json", "w") as f:
        f.write(manifest_json)

    with open(f"{extension_dir}/background.js", "w") as f:
        f.write(background_js)

    logger.info(f"Extension proxy créée dans: {extension_dir}")
    return os.path.abspath(extension_dir)


class InVideoLoginAutomation:
    def __init__(self, headless=False):
        self.headless = headless
        self.driver = None
        self.wait = None

    def setup_driver(self):
        """Configure et initialise le driver Chrome en gérant le proxy (avec ou sans Selenium Wire)."""
        try:
            # 1) Préparer les options Chrome communes
            chrome_options = Options()
            # Définir explicitement l'emplacement du binaire Chrome (utile en container Render/Docker)
            chrome_options.binary_location = os.getenv("CHROME_BIN", "/usr/local/bin/chrome")
            if self.headless:
               chrome_options.add_argument("--headless=new")  # mode headless stable

            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--disable-web-security")
            chrome_options.add_argument("--allow-running-insecure-content")
            chrome_options.add_argument("--ignore-certificate-errors")
            chrome_options.add_argument("--ignore-ssl-errors")
            chrome_options.add_argument("--ignore-certificate-errors-spki-list")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_argument("start-maximized")
            # User-Agent réaliste pour se camoufler
            chrome_options.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")

            # 2) Préparer le proxy URL (sans credentials) pour --proxy-server
            proxy_no_auth = f"http://{PROXY_IP}:{PROXY_PORT}"

            logger.info("PROXY URL" + proxy_no_auth)

            # 3) Si Selenium Wire est disponible => configuration native
            logger.info("Selenium wire::")
            logger.info(SELENIUM_WIRE_AVAILABLE)
            if SELENIUM_WIRE_AVAILABLE:
                logger.info("Selenium Wire détecté – utilisation pour le proxy authentifié")

                seleniumwire_options = {
                    'proxy': {
                        'http': f'http://{PROXY_USER}:{PROXY_PASS}@{PROXY_IP}:{PROXY_PORT}',
                        'https': f'https://{PROXY_USER}:{PROXY_PASS}@{PROXY_IP}:{PROXY_PORT}',
                        'no_proxy': 'localhost,127.0.0.1'
                    },
                    'verify_ssl': False  # éviter les soucis certifs
                }
                # Ajouter également --proxy-server sans credentials (utile pour WebSocket etc.)
                chrome_options.add_argument(f"--proxy-server={proxy_no_auth}")

                # Installer et configurer le service ChromeDriver
                service = Service(ChromeDriverManager().install())

                # Initialiser le driver Selenium Wire
                self.driver = wire_webdriver.Chrome(service=service,
                                                    options=chrome_options,
                                                    seleniumwire_options=seleniumwire_options)
                logger.info("after  selenium driver ")
            else:
                logger.info("selenium wire not set")
                logger.warning("Selenium Wire non disponible – utilisation de l'extension pour proxy authentifié")

                # Charger l'extension basée sur Manifest V2
                extension_path = setup_proxy_auth_extension()
                chrome_options.add_argument(f"--load-extension={extension_path}")
                # Ajouter proxy sans credentials (extension gère l'auth)
                chrome_options.add_argument(f"--proxy-server={proxy_no_auth}")

                #service = Service(ChromeDriverManager().install())
                self.driver = selenium_webdriver.Chrome(options=chrome_options)

            # 4) Minimise la détection de webdriver
            try:
                self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            except Exception:
                pass

            # 5) WebDriverWait commun
            self.wait = WebDriverWait(self.driver, 25)

            # 6) Vérification de l'adresse IP via httpbin
            logger.info("Vérification de l'IP publique via httpbin.org/ip …")
            self.driver.get("https://httpbin.org/ip")
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            logger.info(f"Réponse httpbin: {body_text.strip()}")
            if PROXY_IP in body_text:
                logger.info("[OK] Proxy appliqué correctement !")
            else:
                logger.warning("[WARN] L'IP retournée ne correspond pas au proxy – proxy possiblement inactif")

            logger.info("Driver Chrome configuré avec succès")
            return True

        except Exception as e:
            logger.error(f"Erreur lors de la configuration du driver: {e}")
            return False

    def navigate_to_invideo(self):
        """Navigue vers la page de login InVideo"""
        try:
            logger.info(f"Navigation vers {AUTH_URL}")
            self.driver.get(AUTH_URL)
            time.sleep(3)

            # Vérifier que la page est chargée
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            logger.info("Page InVideo chargée avec succès")
            return True

        except TimeoutException:
            logger.error("Timeout lors du chargement de la page InVideo")
            return False
        except Exception as e:
            logger.error(f"Erreur lors de la navigation: {e}")
            return False

    def click_google_auth_button(self):
        """Clique sur le bouton 'Join with Google'"""
        try:
            logger.info("Recherche du bouton 'Join with Google'")

            # Attendre que la page soit entièrement chargée
            time.sleep(3)

            # Sélecteurs spécifiques basés sur le HTML fourni
            selectors = [
                # Sélecteurs basés sur le HTML exact fourni
                "button.c-PJLV.c-kXcFJy",
                "button[class*='c-PJLV'][class*='c-kXcFJy']",
                "div.c-PJLV button",
                "//button[contains(@class, 'c-PJLV') and contains(@class, 'c-kXcFJy')]",
                "//p[text()='Join with Google']/parent::button",
                "//p[contains(text(), 'Join with Google')]/ancestor::button",
                "//img[@src[contains(., 'google.svg')]]/following-sibling::p[text()='Join with Google']/parent::button",
                "//img[contains(@src, 'google.svg')]/parent::button",

                # Sélecteurs de fallback
                "//button[contains(text(), 'Join with Google')]",
                "//button[contains(text(), 'Continue with Google')]",
                "//button[contains(text(), 'Sign in with Google')]",
                "//a[contains(text(), 'Join with Google')]",
                "//a[contains(text(), 'Continue with Google')]",
                "//div[contains(text(), 'Join with Google')]//button",
                "[data-testid*='google']",
                ".google-auth-button",
                "#google-auth",
                "button[class*='google']"
            ]

            button_found = False

            for i, selector in enumerate(selectors):
                try:
                    logger.info(f"Test du sélecteur {i + 1}/{len(selectors)}: {selector}")

                    if selector.startswith("//"):
                        elements = self.driver.find_elements(By.XPATH, selector)
                    else:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)

                    if elements:
                        logger.info(f"Élément(s) trouvé(s) avec le sélecteur: {selector}")
                        for j, element in enumerate(elements):
                            try:
                                # Vérifier si l'élément est visible et cliquable
                                if element.is_displayed() and element.is_enabled():
                                    logger.info(f"Tentative de clic sur l'élément {j + 1}")

                                    # Faire défiler vers l'élément
                                    self.driver.execute_script("arguments[0].scrollIntoView(true);", element)
                                    time.sleep(1)

                                    # Essayer de cliquer
                                    element.click()
                                    button_found = True
                                    logger.info(f"[OK] Bouton Google cliqué avec succès (sélecteur: {selector})")
                                    break

                            except Exception as e:
                                logger.debug(f"Échec du clic sur l'élément {j + 1}: {e}")
                                continue

                    if button_found:
                        break

                except Exception as e:
                    logger.debug(f"Erreur avec le sélecteur {selector}: {e}")
                    continue

            if not button_found:
                # Recherche manuelle approfondie
                logger.info("Recherche manuelle du bouton Google dans la page")
                page_source = self.driver.page_source

                # Sauvegarder le HTML pour debug
                with open("debug_page_source.html", "w", encoding="utf-8") as f:
                    f.write(page_source)
                logger.info("HTML de la page sauvegardé: debug_page_source.html")

                if "google" in page_source.lower():
                    logger.info("Référence à Google trouvée dans la page")

                    # Essayer de chercher par le texte visible
                    try:
                        # Chercher tous les éléments contenant "Google"
                        google_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Google')]")
                        logger.info(f"Trouvé {len(google_elements)} éléments contenant 'Google'")

                        for elem in google_elements:
                            logger.info(f"Élément trouvé: {elem.tag_name} - Texte: {elem.text}")

                    except Exception as e:
                        logger.error(f"Erreur lors de la recherche d'éléments Google: {e}")

                raise Exception("Aucun bouton Google Auth trouvé")

            time.sleep(2)
            return True

        except Exception as e:
            logger.error(f"Erreur lors du clic sur le bouton Google: {e}")
            return False

    def switch_to_google_login_window(self, timeout: int = 15):
        """Bascule sur la fenêtre ou l'onglet contenant accounts.google.com"""
        original_handle = self.driver.current_window_handle
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: len(d.window_handles) > 1 or "accounts.google.com" in d.current_url)
            # Parcourir toutes les fenêtres pour trouver celle de Google
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                if "accounts.google.com" in self.driver.current_url or "signin" in self.driver.current_url:
                    logger.info(f"Fenêtre Google trouvée: {self.driver.current_url}")
                    return True
            # Si aucune trouvée revenir
            self.driver.switch_to.window(original_handle)
            logger.info("switch to original window")
            return False
        except Exception as e:
            logger.error(f"Impossible de basculer sur la fenêtre Google: {e}")
            return False

    def handle_google_login(self):
        """Gère la connexion Google"""
        try:
            # 1. Bascule sur la fenêtre Google si nécessaire
            if not self.switch_to_google_login_window():
                logger.warning("Aucune nouvelle fenêtre Google détectée, on reste sur la fenêtre courante")

            logger.info("Début de la connexion Google")

            wait_short = WebDriverWait(self.driver, 5)
            wait_long = WebDriverWait(self.driver, 30)

            # 2. Gestion éventuelle de l'écran de sélection/compte
            try:
                use_another_xpath = "//div[text()='Utiliser un autre compte' or text()='Use another account']"
                elem = wait_short.until(EC.element_to_be_clickable((By.XPATH, use_another_xpath)))
                elem.click()
                logger.info("Clique sur 'Utiliser un autre compte'")
            except Exception:
                logger.info("user does not see another account option")
                pass

            # 3. Saisie EMAIL + Next
            email_input = wait_long.until(
                EC.element_to_be_clickable((By.XPATH, "//input[@type='email' or @id='identifierId']"))
            )
            logger.info("Email popup open"+self.driver.current_url)
            logger.info("Email title " + self.driver.title)
            time.sleep(1)
            logger.info("Email " + EMAIL)
            email_input.send_keys(EMAIL)
            logger.info("Email saisi")
            time.sleep(2)

            # Cliquer sur le bouton "Suivant" plutôt qu'ENTER pour fiabilité
            try:

                next_btn = self.driver.find_element(By.ID, "identifierNext")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                next_btn.click()
                logger.info("Bouton 'Suivant' cliqué (email)")
            except Exception as e:
                logger.debug(f"Bouton identifierNext introuvable ou non cliquable ({e}), envoi ENTER")
                email_input.send_keys(Keys.ENTER)

            self.driver.save_screenshot("screenshot.png")
            logger.info("password popup open " + self.driver.current_url)
            logger.info("password popup open " + self.driver.title)
            # 4. Attente du champ MOT DE PASSE

            password_input = wait_long.until(
                EC.element_to_be_clickable((By.NAME, 'Passwd'))
            )


            logger.info("password popup loaded " )
            # Dans certains cas, le champ peut être caché: s'assurer qu'il est visible
            if not password_input.is_displayed():
                logger.info("password_input is not visible, trying to show it ")
                self.driver.execute_script("arguments[0].style.display = 'block';", password_input)

            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", password_input)
            time.sleep(0.3)
            logger.info("password popup shown " )
            password_input.clear()
            logger.info("password popup clear ")
            password_input.send_keys(PASSWORD)
            logger.info("Mot de passe saisi")

            # Cliquer sur le bouton "Suivant" du mot de passe
            try:
                pass_next = self.driver.find_element(By.ID, "passwordNext")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", pass_next)
                pass_next.click()
                logger.info("Bouton 'Suivant' cliqué (mot de passe)")
            except Exception as e:
                logger.debug(f"Bouton passwordNext introuvable ({e}), envoi ENTER")
                password_input.send_keys(Keys.ENTER)

            # Laisser un petit délai pour que la soumission soit prise en compte
            time.sleep(2)

            # 5. Attendre d'abord la fermeture éventuelle de la fenêtre Google
            wait_long.until(lambda d: len(d.window_handles) == 1 or POST_AUTH_URL_PREFIX in d.current_url)

            # Si la fenêtre Google s'est fermée, basculer sur la principale
            if len(self.driver.window_handles) == 1:
                self.driver.switch_to.window(self.driver.window_handles[0])
                logger.info("Revenu à la fenêtre principale InVideo")

            # 6. Attendre que l'URL contienne le préfixe workspace InVideo
            try:
                wait_long.until(lambda d: POST_AUTH_URL_PREFIX in d.current_url)
            except TimeoutException:
                logger.warning(
                    "La redirection vers le workspace InVideo n'est pas encore terminée, on attend 5 s de plus…")
                time.sleep(5)

            logger.info(f"URL après auth : {self.driver.current_url}")
            logger.info("Authentification Google terminée")
            return True

        except TimeoutException as te:
            logger.error(f"Timeout lors de l'authentification Google: {te}")
            return False
        except Exception as e:
            logger.error(f"Erreur lors de l'authentification Google: {e}")
            return False

    def wait_for_redirect(self):
        """Attend la redirection vers InVideo après l'authentification"""
        try:
            logger.info("Attente de la redirection vers InVideo")

            # Attendre que l'URL contienne le préfixe attendu
            self.wait.until(lambda driver: POST_AUTH_URL_PREFIX in driver.current_url)

            logger.info(f"Redirection réussie vers: {self.driver.current_url}")
            time.sleep(2)

            # 6. Récupération des tokens localStorage
            tokens = self.capture_local_storage_tokens()
            json_tokens = json.dumps(tokens, indent=2, ensure_ascii=False)
            logger.info(f"Tokens localStorage récupérés: {json_tokens}")

            # Mise à jour de la base de données
            try:
                if tokens:  # Seulement si on a des tokens
                    logger.info("[STEP 2] Mise à jour base de données...")
                    #update_db(json_tokens)
                else:
                    logger.warning("Aucun token trouvé, pas de mise à jour DB")
            except Exception as e:
                logger.error(f"Erreur lors de la mise à jour DB (non bloquant): {e}")
                print(f"[WARN] Mise à jour DB échouée: {e}")

            return True

        except TimeoutException:
            logger.error("Timeout lors de l'attente de redirection")
            logger.info(f"URL actuelle: {self.driver.current_url}")
            return False
        except Exception as e:
            logger.error(f"Erreur lors de l'attente de redirection: {e}")
            return False

    def run_automation(self):
        """Exécute le processus complet d'automatisation"""
        try:
            logger.info("=== Début de l'automatisation InVideo ===")

            # 1. Configuration du driver
            if not self.setup_driver():
                return False

            # 2. Navigation vers InVideo
            if not self.navigate_to_invideo():
                return False

            # 3. Clic sur le bouton Google Auth
            if not self.click_google_auth_button():
                return False

            # 4. Authentification Google
            if not self.handle_google_login():
                return False

            # 5. Attente de la redirection
            if not self.wait_for_redirect():
                return False

            logger.info("=== Automatisation terminée avec succès ===")
            logger.info(f"URL finale: {self.driver.current_url}")

            # Laisser le navigateur ouvert pour vérification en mode visuel uniquement
            if not self.headless:
                input("Appuyez sur Entrée pour fermer le navigateur...")

            return True

        except Exception as e:
            logger.error(f"Erreur générale dans l'automatisation: {e}")
            return False

        finally:
            if self.driver:
                self.driver.quit()
                logger.info("Driver fermé")

    TOKEN_PATTERNS = [
        re.compile(r"^ab\.storage\.messagingSessionStart\.([0-9a-f\-]+)$"),
        re.compile(r"^access_token$"),
        re.compile(r"^refresh_token$"),
        re.compile(r"^ab\.storage\.sessionId\.([0-9a-f\-]+)$"),
    ]

    def capture_local_storage_tokens(self):
        """Récupère les tokens depuis le localStorage et les renvoie sous forme de liste de dicts"""
        try:
            items = self.driver.execute_script(
                """
                const out = [];
                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    const value = localStorage.getItem(key);
                    out.push({key: key, value: value});
                }
                return out;
                """
            )
            filtered = []
            for pair in items:
                k = pair.get("key")
                v = pair.get("value")
                if any(pat.match(k) for pat in self.TOKEN_PATTERNS):
                    filtered.append({"key": k, "value": v})
            return filtered
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des tokens localStorage: {e}")
            return []


# -------------------------------------------------------------
#        FONCTION MISE À JOUR BASE DE DONNÉES
# -------------------------------------------------------------

def update_db(tokens_json: str, user_id: int = DB_USER_ID):
    """Met à jour le champ local_storages pour un utilisateur donné."""

    logger.info("Connexion à la base MySQL...")
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            collation=DB_COLLATION,
        )

        cursor = conn.cursor()

        query = "UPDATE credential SET local_storages = %s WHERE id = %s"
        cursor.execute(query, (tokens_json, user_id))
        conn.commit()

        logger.info(f"[OK] Champ 'local_storages' mis à jour pour l'utilisateur ID {user_id}")
        print(f"[OK] Base de données mise à jour pour l'utilisateur ID {user_id}")

    except MySQLError as e:
        logger.error(f"Erreur lors de la mise à jour SQL: {e}")
        print(f"[FAIL] Erreur base de données: {e}")
        raise  # Propager l'erreur pour debug éventuel
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals() and conn.is_connected():
            conn.close()
            logger.info("Connexion MySQL fermée")


def main():
    """Fonction principale"""
    automation = InVideoLoginAutomation(headless=HEADLESS_DEFAULT)
    success = automation.run_automation()

    if success:
        print("[OK] Automatisation réussie!")
    else:
        print("[FAIL] Échec de l'automatisation")

    return success


if __name__ == "__main__":
    main()