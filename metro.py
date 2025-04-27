import time
import random
import re
import os
import pickle
import undetected_chromedriver as uc

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    TimeoutException,
    StaleElementReferenceException
)
from selenium.webdriver import ActionChains

# -----------------------------
# Checkpoint File
# -----------------------------
CHECKPOINT_FILE = "checkpoint.txt"

def save_checkpoint(page_num, tile_index):
    try:
        with open(CHECKPOINT_FILE, "w") as f:
            f.write(f"{page_num},{tile_index}")
    except Exception as e:
        print("[WARN] Could not save checkpoint:", e)

def load_checkpoint():
    if not os.path.exists(CHECKPOINT_FILE):
        return (1, 0)
    try:
        with open(CHECKPOINT_FILE, "r") as f:
            line = f.read().strip()
            if line:
                parts = line.split(",")
                resume_page = int(parts[0])
                resume_tile = int(parts[1])
                print(f"[INFO] Resuming from page {resume_page}, tile {resume_tile}.")
                return resume_page, resume_tile
    except Exception as e:
        print("[WARN] Could not load checkpoint:", e)
    return 1, 0

# -----------------------------
# Firebase Setup
# -----------------------------
import firebase_admin
from firebase_admin import credentials, firestore

FIREBASE_CREDENTIALS_PATH = "firebase_credentials.json"
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()
# 1) CHANGED collection name from "metro" to "Products"
FIREBASE_COLLECTION = "Products"

# -----------------------------
# Human-Like Delay + Behavior
# -----------------------------
def human_delay(min_sec=2.0, max_sec=5.0):
    """Random delay for anti-detection."""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)

def simulate_human_behavior(driver):
    """Random short pause + random scroll, to mimic user actions."""
    human_delay(2,4)
    scroll_offset = random.randint(300, 900)
    driver.execute_script(f"window.scrollBy(0, {scroll_offset});")
    human_delay(2,4)

# -----------------------------
# Utility for focusing window
# -----------------------------
def ensure_driver_focus(driver):
    """Bring browser window to front and reposition at (0,0)."""
    try:
        driver.switch_to.window(driver.current_window_handle)
        driver.execute_script("window.focus();")
        driver.set_window_position(0, 0)
    except Exception as e:
        print("[ensure_driver_focus] Warning:", e)

def robust_click(driver, element):
    """Attempt normal click, JS click, ActionChains click."""
    try:
        element.click()
        return
    except Exception as e_normal:
        print(f"[robust_click] Normal click failed: {e_normal}")
    try:
        driver.execute_script("arguments[0].click();", element)
        print("[robust_click] JS click succeeded.")
        return
    except Exception as e_js:
        print(f"[robust_click] JS click failed: {e_js}")
    try:
        ActionChains(driver).move_to_element(element).click(element).perform()
        print("[robust_click] ActionChains click succeeded.")
        return
    except Exception as e_act:
        print(f"[robust_click] ActionChains click failed: {e_act}")
        raise

# -----------------------------
# Slug Helper
# -----------------------------
def extract_slug(text):
    """Converts product name to slug format (lowercase, hyphens, no punctuation)."""
    slug = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[\s_]+', '-', slug)

# -----------------------------
# The Scraper Class
# -----------------------------
class MetroAllScraper:
    """
    1) Each page is expected to have 30 items (except final page may have fewer).
    2) We do a first pass by tiles:
       - If sign-up or detection => skip that item after a single driver restart.
       - If normal error => up to 5 tries for that tile.
    3) Then second pass:
       - Directly open missed item URLs.
       - If sign-up/detection => skip that item.
       - If normal error => up to 5 tries.
    4) Move on to next page once the page's items are done.
    5) Restart driver after 20 pages or upon detection.
    """

    def __init__(self, total_pages=466):
        self.total_pages = total_pages
        self.current_page, self.tile_index = load_checkpoint()
        self.current_row = 2  # For ordering if needed

        # store sign-up/detected URLs
        self.detected_urls = []

        options = uc.ChromeOptions()
        prefs = {"translate_whitelists": {"fr": "en"}, "translate": {"enabled": True}}
        options.add_experimental_option("prefs", prefs)
        # Non-headless => visible
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-dev-shm-usage")

        self.driver = uc.Chrome(options=options)
        try:
            self.driver.maximize_window()
        except:
            pass
        time.sleep(2)
        self.base_url = "https://www.metro.ca/en/online-grocery/search"

    def close_driver(self):
        """Closes the driver, freeing resources."""
        try:
            self.driver.quit()
        except Exception as e:
            print("[ERROR] in driver.quit():", e)
        finally:
            import gc
            del self.driver
            gc.collect()

    def restart_driver(self):
        """Restart with new user agent."""
        print("[INFO] Restarting driver for new IP / user-agent.")
        self.close_driver()
        time.sleep(5)
        options = uc.ChromeOptions()
        prefs = {"translate_whitelists": {"fr": "en"}, "translate": {"enabled": True}}
        options.add_experimental_option("prefs", prefs)
        # Non-headless => visible
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-dev-shm-usage")

        fake_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/90.0.4430.93 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/91.0.4472.77 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/92.0.4515.107 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/93.0.4577.82 Safari/537.36"
        ]
        chosen_agent = random.choice(fake_agents)
        options.add_argument(f"--user-agent={chosen_agent}")
        self.driver = uc.Chrome(options=options)
        try:
            self.driver.maximize_window()
        except:
            pass
        time.sleep(2)
        self.driver.get("https://www.metro.ca/en/online-grocery/search")
        time.sleep(6)
        self._dismiss_cookie_popup()
        self._set_store_location()

    def _dismiss_cookie_popup(self):
        """Dismiss cookie popup if present."""
        try:
            cookie_btn = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.ID, "onetrust-reject-all-handler"))
            )
            cookie_btn.click()
            time.sleep(2)
            print("  [INFO] Cookie popup dismissed.")
        except:
            pass

    def _maybe_select_ontario(self):
        """Clicks 'Ontario' if that popup appears."""
        try:
            ontario_button = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, '//button[contains(text(), "Ontario")]'))
            )
            ontario_button.click()
            time.sleep(1)
            print("[INFO] Ontario popup button clicked.")
        except:
            pass

    def _set_store_location(self):
        """Select store location to ensure we get consistent results."""
        time.sleep(10)
        try:
            cookie_btn = self.driver.find_element(By.ID, "onetrust-reject-all-handler")
            if cookie_btn.is_displayed() and cookie_btn.is_enabled():
                cookie_btn.click()
        except:
            pass
        time.sleep(2)
        self._maybe_select_ontario()
        time.sleep(2)
        try:
            modal_btn = WebDriverWait(self.driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "(//button[contains(@class, 'modal-store-selector')])[1]"))
            )
            modal_btn.click()
        except:
            pass
        time.sleep(10)
        try:
            province_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.fs--btn-search-province.openProvince"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView(true);", province_btn)
            time.sleep(1)
            province_btn.click()
        except:
            pass
        time.sleep(3)
        try:
            actives = self.driver.find_elements(By.CSS_SELECTOR, "a.active")
            if len(actives) >= 2:
                actives[1].click()
        except:
            pass
        time.sleep(3)
        try:
            city_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.fs--btn-search-city.openCity"))
            )
            city_btn.click()
        except:
            pass
        time.sleep(2)
        try:
            first_city = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//ul[@class="fs--city-items   fs--location-items"]//li[1]//a'))
            )
            first_city.click()
        except:
            pass
        time.sleep(2)
        try:
            final_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.cta-basic-primary.medium.w-100.find-btn.mobile-open-selection"))
            )
            final_btn.click()
        except:
            pass
        time.sleep(2)
        try:
            store_item = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '(//li[@class="fs--box-shop radio--standard"])[1]'))
            )
            store_item.click()
        except:
            pass
        time.sleep(2)
        try:
            confirm_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '(//button[@class="cta-basic-primary medium w-100 setMyStoreButton"])[1]'))
            )
            confirm_btn.click()
        except:
            pass
        time.sleep(5)

    def _get_master_category(self, main_category):
        main_cat = main_category.replace('-', ' ').strip().lower()
        if main_cat in ["fruits", "fruits vegetables", "vegetables", "organic groceries", "nature s signature"]:
            return "Fruits & Vegetables"
        elif main_cat in ["dairy", "eggs", "dairy eggs"]:
            return "Dairy & Eggs"
        elif main_cat == "pantry":
            return "Ingredients & Spices"
        elif main_cat == "frozen":
            return "Frozen Food"
        elif main_cat in ["fish", "seafood", "deli prepared meals", "meat", "poultry", "world cuisine", "cooked meals", "meat poultry", "fish seafood"]:
            return "Meat, Fish & Prepared Meals"
        elif main_cat == "snacks":
            return "Snacks & Sweets"
        elif main_cat == "household cleaning":
            return "Household & Cleaning"
        elif main_cat == "pet care":
            return "Pet Supplies"
        elif main_cat == "health beauty":
            return "Health & Personal Care"
        elif main_cat == "beverages":
            return "Baverages"
        elif main_cat in ["bread", "bakery products", "bread bakery products"]:
            return "Bakery Items"
        elif main_cat == "baby":
            return "Baby Items"
        elif main_cat == "vegan vegetarian food":
            return "Vegan & Vegetarian"
        elif main_cat == "pharmacy":
            return "Pharmacy"
        else:
            return "N/A"

    def _update_or_add_product(self, product_data):
        """
        2) If doc with same 'URL' already exists, update its Price/Size/OnSale fields.
           Otherwise, add a new doc to 'Products' collection.
        """

        product_url = product_data.get('url','NA').strip()

        # Check if doc with same URL exists
        existing = db.collection(FIREBASE_COLLECTION).where("URL","==",product_url).limit(1).get()

        if existing:
            doc_id = existing[0].id
            print(f"       [INFO] Found existing doc => updating {product_url}")
            # We only update these fields
            fields_to_update = {
                "Size": product_data.get('size','NA'),
                "PricePerUnit": product_data.get('price_per_unit','NA'),
                "OnSale": "YES" if product_data.get('on_sale',False) else "NO",
                "Original Price": product_data.get('original_price','NA'),
                "SalePrice": product_data.get('sale_price','NA'),
            }
            try:
                db.collection(FIREBASE_COLLECTION).document(doc_id).update(fields_to_update)
                print(f"       [INFO] Updated doc for URL: {product_url}")
            except Exception as e:
                print(f"       [ERROR] Updating doc => {e}")
        else:
            # If not found => create new doc
            doc_data = {
                "Brand": product_data.get('brand',''),
                "InStock": "YES" if product_data.get('in_stock',False) else "NO",
                "MainCategory": product_data.get('main_category','N/A').replace('-',' '),
                "MasterCategory": self._get_master_category(product_data.get('main_category','N/A')),
                "OnSale": "YES" if product_data.get('on_sale',False) else "NO",
                "Original Price": product_data.get('original_price','NA'),
                "PricePerUnit": product_data.get('price_per_unit','NA'),
                "Product": product_data.get('title','NA'),
                "SalePrice": product_data.get('sale_price','NA'),
                "SecondLevel": product_data.get('second_level','NA').replace('-',' '),
                "Size": product_data.get('size','NA'),
                "Store": "Metro",
                "ThirdLevel": product_data.get('third_level','NA').replace('-',' '),
                "URL": product_url
            }
            try:
                db.collection(FIREBASE_COLLECTION).add(doc_data)
                print(f"       [INFO] Added new doc for product: {product_data.get('title','(No Title)')}")
            except Exception as e:
                print("[ERROR] writing doc =>", e)

    def _scrape_detail_page(self, product_url):
        cur_url = self.driver.current_url
        if "b2c-sign-up" in cur_url:
            print("[WARN] sign-up => None.")
            return None

        data = {
            'main_category': 'N/A',
            'second_level': 'N/A',
            'third_level': 'N/A',
            'sku': 'N/A',
            'url': product_url,
            'brand': '',
            'title': '',
            'size': 'N/A',
            'price_per_unit': '',
            'on_sale': False,
            'original_price': '',
            'sale_price': '',
            'in_stock': False,
        }
        if product_url and "/aisles/" in product_url:
            splitted = product_url.split("/aisles/")[1].split("/")
            if "p" in splitted:
                p_index = splitted.index("p")
                if p_index+1 < len(splitted):
                    data['sku'] = splitted[p_index+1]
            cat_segments = splitted if "p" not in splitted else splitted[:splitted.index("p")]
            if len(cat_segments) >= 1:
                data['main_category'] = cat_segments[0]
            if len(cat_segments) >= 2:
                data['second_level'] = cat_segments[1]
            if len(cat_segments) >= 3:
                data['third_level'] = cat_segments[-1]

        # brand
        try:
            brand_el = self.driver.find_element(By.CSS_SELECTOR, ".pi--brand")
            data['brand'] = brand_el.text.strip()
        except:
            pass
        # title
        try:
            name_el = self.driver.find_element(By.CSS_SELECTOR, ".pi--product-main-info__name")
            data['title'] = name_el.text.strip()
        except:
            try:
                name_el2 = self.driver.find_element(By.CSS_SELECTOR, ".pi--title")
                data['title'] = name_el2.text.strip()
            except:
                pass
        if not data['title']:
            print("[WARN] No title => detection => None.")
            return None

        # size
        try:
            size_el = self.driver.find_element(By.CSS_SELECTOR, ".pi--weight")
            data['size'] = size_el.text.strip()
        except:
            try:
                unit_update_el = self.driver.find_element(By.CSS_SELECTOR, ".unit-update")
                factor_el = unit_update_el.find_element(By.CSS_SELECTOR, ".unit-factor")
                factor = factor_el.text.strip()
                unit = self.driver.execute_script("return arguments[0].nextSibling.textContent;", factor_el).strip()
                data['size'] = factor + unit
            except:
                pass

        # original / sale
        try:
            wait_local = WebDriverWait(self.driver, 2)
            orig_el = wait_local.until(EC.presence_of_element_located(
                (By.XPATH, "//div[not(ancestor::header)][contains(@class, 'pricing__before-price')]/span[2]")
            ))
            original_price = orig_el.get_attribute("textContent").strip()
            if original_price:
                data['original_price'] = original_price
                data['on_sale'] = True
                try:
                    sale_el = self.driver.find_element(
                        By.XPATH,
                        "//div[not(ancestor::header)][contains(@class, 'pricing__sale-price') and contains(@class, 'promo-price')]/span[1]"
                    )
                    sale_price = sale_el.get_attribute("textContent").strip()
                    if sale_price:
                        data['sale_price'] = sale_price
                        data['price_per_unit'] = sale_price
                except:
                    pass
        except:
            try:
                reg_el = self.driver.find_element(
                    By.XPATH, "//div[not(ancestor::header)][contains(@class, 'price-update')]"
                )
                reg_price = reg_el.get_attribute("textContent").strip()
                if reg_price:
                    data['price_per_unit'] = reg_price
            except:
                pass

        if "/" in data.get('price_per_unit', ""):
            try:
                container = self.driver.find_element(By.CSS_SELECTOR, "div.pi--prices.pt__content--wrap")
                promo_el = container.find_element(By.CSS_SELECTOR, "div.pricing__secondary-price.promo-price span")
                promo_text = promo_el.text.strip()
                final_price = promo_text.split("/")[0].strip()
                if final_price:
                    data['price_per_unit'] = final_price
            except:
                pass

        # in stock
        try:
            add_btn = self.driver.find_element(
                By.CSS_SELECTOR, ".debounce-250.button-tile-addToCart.action__add-to-cart.add-to-cart-pdp"
            )
            data['in_stock'] = add_btn.is_enabled() and add_btn.is_displayed()
        except:
            pass
        return data

    def _extract_url_from_tile(self, tile):
        cat_url = tile.get_attribute("data-category-url") or ""
        prod_name = tile.get_attribute("data-product-name") or ""
        prod_code = tile.get_attribute("data-product-code") or ""

        slug = extract_slug(prod_name)
        if cat_url.startswith("/"):
            cat_url = cat_url[1:]

        full_url = f"https://www.metro.ca/en/online-grocery/{cat_url}/{slug}/p/{prod_code}"
        return full_url.strip()

    def _scrape_single_tile(self, tile):
        brand_txt, name_txt, tile_price = "", "", ""
        try:
            brand_el = tile.find_element(By.CSS_SELECTOR, ".head__brand")
            brand_txt = brand_el.text.strip()
        except:
            pass
        try:
            name_el = tile.find_element(By.CSS_SELECTOR, ".head__title")
            name_txt = name_el.text.strip()
        except:
            pass
        try:
            price_el = tile.find_element(By.CSS_SELECTOR, ".price-update")
            tile_price = price_el.text.strip()
        except:
            pass

        final_url = self._extract_url_from_tile(tile)
        if not final_url:
            print("[ERROR] tile => missing data-cat-url => skip.")
            return None

        if final_url in self.detected_urls:
            print(f"[INFO] {final_url} was previously sign-up/detected => skip.")
            return None

        self.driver.get(final_url)
        human_delay(3,5)
        cur_url = self.driver.current_url
        if "b2c-sign-up" in cur_url:
            print(f"[DEBUG] Skipped item => sign-up. URL was {final_url}")
            self.detected_urls.append(final_url)
            print("[INFO] sign-up => restart => skip => None.")
            self.restart_driver()
            return None

        dd = self._scrape_detail_page(final_url)
        if not dd or not dd.get('title'):
            print(f"[DEBUG] Skipped item => detection. URL was {final_url}")
            self.detected_urls.append(final_url)
            print("[WARN] detection => restart => skip => None.")
            self.restart_driver()
            return None

        # fill brand/price if empty
        if not dd.get('brand'):
            dd['brand'] = brand_txt
        if not dd.get('price_per_unit'):
            dd['price_per_unit'] = tile_price

        return dd

    def scrape_all_products(self):
        resume_page, resume_tile = load_checkpoint()
        if resume_page == 1 and resume_tile == 0:
            print("[INFO] No checkpoint => new run.")

        self.driver.get("https://www.metro.ca/en/online-grocery/search")
        time.sleep(6)
        self._dismiss_cookie_popup()
        self._set_store_location()

        while self.current_page <= self.total_pages:
            listing_url = (self.base_url if self.current_page == 1
                           else f"{self.base_url}-page-{self.current_page}")
            print(f"[INFO] Detected/skipped so far => {len(self.detected_urls)} => {self.detected_urls}")
            print(f"\n[INFO] Now scraping page {self.current_page}/{self.total_pages}: {listing_url}")

            self.driver.get(listing_url)
            time.sleep(random.uniform(6,8))
            self._dismiss_cookie_popup()
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(random.uniform(3,5))

            product_tiles = self.driver.find_elements(
                By.XPATH,
                "//div[contains(@class,'products-search--grid')]/div[contains(@class,'default-product-tile') and "
                "contains(@class,'tile-product') and contains(@class,'item-addToCart')]"
            )
            tile_count = len(product_tiles)
            print(f"  Found {tile_count} product tiles on this page (expected 30?).")

            page_urls = []
            for tile in product_tiles:
                try:
                    purl = self._extract_url_from_tile(tile)
                    if purl:
                        page_urls.append(purl)
                except:
                    pass

            print("[INFO] The 30 (or so) product URLs for this page:")
            unique_urls = []
            for idx, u in enumerate(page_urls, start=1):
                if u not in unique_urls:
                    unique_urls.append(u)
            for idx, uu in enumerate(unique_urls, start=1):
                print(f"   {idx}. {uu}")

            scraped_urls = set()

            # first pass
            tile_index = resume_tile if self.current_page == resume_page else 0
            while tile_index < tile_count:
                print(f"    -> Attempt tile #{tile_index+1}/{tile_count}")
                fail_count = 0
                item_done = False
                while (fail_count < 5) and (not item_done):
                    try:
                        product_tiles = self.driver.find_elements(
                            By.XPATH,
                            "//div[contains(@class,'products-search--grid')]/div[contains(@class,'default-product-tile') and "
                            "contains(@class,'tile-product') and contains(@class,'item-addToCart')]"
                        )
                        if tile_index >= len(product_tiles):
                            print("       [WARN] tile_index OOB => break tile loop.")
                            break
                        tile = product_tiles[tile_index]
                        dd = self._scrape_single_tile(tile)
                        if dd:
                            # 2) If doc with same URL => update price fields, else new doc
                            self._update_or_add_product(dd)
                            scraped_urls.add(dd['url'])
                            item_done = True
                            save_checkpoint(self.current_page, tile_index+1)
                        else:
                            fail_count = 5
                            save_checkpoint(self.current_page, tile_index)
                            print("       [INFO] Skipped item => next tile.")
                    except (StaleElementReferenceException, TimeoutException, ElementClickInterceptedException) as e:
                        fail_count += 1
                        print(f"       [WARN] Retry {fail_count}/5 => {e}")
                        save_checkpoint(self.current_page, tile_index)
                        self.driver.get(listing_url)
                        time.sleep(random.uniform(4,6))
                        self._dismiss_cookie_popup()
                        simulate_human_behavior(self.driver)

                tile_index += 1
                self.driver.get(listing_url)
                time.sleep(random.uniform(4,6))
                self._dismiss_cookie_popup()
                simulate_human_behavior(self.driver)

            # second pass for missed
            missed = [u for u in page_urls
                      if (u not in scraped_urls)
                      and (u not in self.detected_urls)]
            print(f"[INFO] Missed items from page => {len(missed)}. {missed}")

            if missed:
                print(f"[INFO] Second pass => {len(missed)} missed item(s).")
                for mu in missed:
                    tries = 0
                    success = False
                    while (tries < 5) and (not success):
                        tries += 1
                        try:
                            if mu in self.detected_urls:
                                print(f"[INFO] skip second pass for {mu}, sign-up/detected.")
                                break
                            self.driver.get(listing_url)
                            time.sleep(random.uniform(4,6))
                            self.driver.get(mu)
                            time.sleep(random.uniform(3,5))
                            if "b2c-sign-up" in self.driver.current_url:
                                print(f"[DEBUG] Skipped item => sign-up. URL was {mu}")
                                self.detected_urls.append(mu)
                                print("[WARN] sign-up => skip.")
                                break
                            detail_data = self._scrape_detail_page(mu)
                            if not detail_data or not detail_data.get('title'):
                                print(f"[DEBUG] Skipped item => detection. URL was {mu}")
                                self.detected_urls.append(mu)
                                print("[WARN] detection => skip.")
                                break
                            # again, update or add
                            self._update_or_add_product(detail_data)
                            scraped_urls.add(mu)
                            success = True
                        except Exception as e:
                            print(f"[WARN] second pass => {e}")
                            self.restart_driver()

            self.tile_index = 0
            self.current_page += 1
            save_checkpoint(self.current_page, 0)

            if (self.current_page % 20 == 0) and (self.current_page != self.total_pages):
                print("[INFO] 20 pages => restart driver.")
                self.restart_driver()

        print("[INFO] All pages done => removing checkpoint.")
        try:
            if os.path.exists(CHECKPOINT_FILE):
                os.remove(CHECKPOINT_FILE)
        except:
            pass

# -----------------------------
# Main
# -----------------------------
def main():
    scraper = MetroAllScraper(total_pages=466)
    scraper.scrape_all_products()
    scraper.close_driver()

if __name__ == "__main__":
    main()
