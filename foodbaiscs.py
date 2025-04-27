import time
import random
import os
import pickle
import undetected_chromedriver as uc
from urllib.parse import quote

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    ElementClickInterceptedException,
    NoSuchElementException
)

# ------------------------------------------------------------------------
# A) Firebase Setup
# ------------------------------------------------------------------------
import firebase_admin
from firebase_admin import credentials, firestore

# Path to your downloaded Firebase Service Account JSON.
FIREBASE_CREDENTIALS_PATH = "firebase_credentials.json"

# Initialize the Firebase Admin SDK using the service account.
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ------------------------------------------------------------------------
# B) State Management
# ------------------------------------------------------------------------
STATE_FILE = "scraper_state.pkl"

def load_state():
    """
    Returns a dictionary with:
      run_mode: either "append" (first pass) or "overwrite" (subsequent pass)
      current_page: the page number that is currently being scraped.
      current_item: the index of the item on the current page.
      completed_run: boolean flag signaling whether a full pass has been completed.
    """
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "rb") as f:
            return pickle.load(f)
    else:
        return {
            "run_mode": "append",   # First pass: add new items.
            "current_page": 1,
            "current_item": 0,
            "completed_run": False
        }

def save_state(state):
    with open(STATE_FILE, "wb") as f:
        pickle.dump(state, f)

def reset_state_for_overwrite(state):
    """
    Once a full pass in append mode has been completed, switch to "overwrite" mode.
    In overwrite mode the scraper will iterate from the first page again and update 
    dynamic fields for items that already exist (and add those that do not).
    """
    state["run_mode"] = "overwrite"
    state["current_page"] = 1
    state["current_item"] = 0
    state["completed_run"] = False
    save_state(state)

# ------------------------------------------------------------------------
# C) Master Category Utility
# ------------------------------------------------------------------------
def get_master_category(main_cat):
    mc = main_cat.lower().strip()
    if mc in ["organic groceries", "fruits and vegetables"]:
        return "Fruits & Vegetables"
    elif mc == "dairy and eggs":
        return "Dairy & Eggs"
    elif mc == "pantry":
        return "Ingredients & Spices"
    elif mc == "frozen":
        return "Frozen Food"
    elif mc in ["fish seafood", "deli and prepared meals", "meat and poultry", "world cuisine", "cooked meals"]:
        return "Meat, Fish & Prepared Meals"
    elif mc == "snacks":
        return "Snacks & Sweets"
    elif mc == "household cleaning":
        return "Household & Cleaning"
    elif mc == "pet care":
        return "Pet Supplies"
    elif mc == "health beauty":
        return "Health & Personal Care"
    elif mc == "beverages":
        return "Beverages"
    elif mc == "bread bakery products":
        return "Bakery Items"
    elif mc == "vegan vegetarian food":
        return "Vegan & Vegetarian"
    elif mc == "baby":
        return "Baby Items"
    elif mc == "pharmacy":
        return "Pharmacy"
    else:
        return ""

# ------------------------------------------------------------------------
# D) Firestore Write / Update Functions
# ------------------------------------------------------------------------
def add_new_item(doc_id, data):
    """
    In the first pass (append mode), if the item is not already in Firestore,
    add a full document with all fields.
    """
    db.collection("FoodBasics").document(doc_id).set(data)
    print(f"[INFO] Added new item with URL-ID: {doc_id}")

def update_dynamic_fields(doc_id, dynamic_data):
    """
    In overwrite mode, if the item exists, update only the dynamic fields.
    """
    db.collection("FoodBasics").document(doc_id).update(dynamic_data)
    print(f"[INFO] Updated dynamic fields for URL-ID: {doc_id}")

# ------------------------------------------------------------------------
# E) Main Scraper Logic
# ------------------------------------------------------------------------
uc.Chrome.__del__ = lambda self: None

def get_driver():
    options = uc.ChromeOptions()
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36"
    ]
    options.add_argument(f"--user-agent={random.choice(user_agents)}")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    # Uncomment the line below for headless mode if needed.
    # options.add_argument("--headless=new")
    driver = uc.Chrome(options=options)
    driver.maximize_window()
    return driver

def set_up_store(driver):
    """
    Configure the store selection to ensure we are scraping 'Food Basics - Oshawa'.
    """
    wait = WebDriverWait(driver, 20)
    driver.get("https://www.foodbasics.ca/search")
    time.sleep(2)
    # 1) Refuse cookies if popup.
    try:
        cookie_btn = wait.until(EC.element_to_be_clickable((By.ID, "onetrust-reject-all-handler")))
        try:
            cookie_btn.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", cookie_btn)
        print("[INFO] Cookies refused.")
        time.sleep(1)
        wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.onetrust-pc-dark-filter")))
    except TimeoutException:
        print("[INFO] No cookie popup found—maybe already dismissed?")
    # 2) Click "Change store"
    try:
        change_store_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.modal-store-selector")))
        change_store_btn.click()
        print("[INFO] Clicked 'Change store'.")
        time.sleep(1)
    except TimeoutException:
        print("[ERROR] 'Change store' button not found.")
        return False
    # 3) "Search city"
    try:
        city_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.fs--btn-search-city.openCity")))
        city_button.click()
        print("[INFO] Clicked 'Search city'.")
        time.sleep(1)
    except TimeoutException:
        print("[ERROR] 'Search city' button not found or not clickable.")
        return False
    # 4) Select "Oshawa"
    try:
        oshawa_link = wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Oshawa")))
        oshawa_link.click()
        print("[INFO] Clicked 'Oshawa'.")
        time.sleep(1)
    except TimeoutException:
        print("[ERROR] 'Oshawa' link not found.")
        return False
    # 5) Click "Find"
    try:
        find_button = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "button.cta-primary.medium.w-100.find-btn.mobile-open-selection")
        ))
        find_button.click()
        print("[INFO] Clicked 'Find'.")
        time.sleep(2)
    except TimeoutException:
        print("[ERROR] 'Find' button not clickable.")
        return False
    # 6) Wait for store list
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,
            "ul#map-results-replacement.fs--boxes-shops li.fs--box-shop.radio--standard")))
        print("[INFO] Store list loaded.")
        time.sleep(1)
    except TimeoutException:
        print("[ERROR] No store list loaded after 'Find'.")
        return False
    # 7) Find "Food Basics - Oshawa"
    store_found = False
    store_items = driver.find_elements(By.CSS_SELECTOR, "li.fs--box-shop.radio--standard")
    for li in store_items:
        try:
            store_name_el = li.find_element(By.CSS_SELECTOR, "p.store-name")
            if "Food Basics - Oshawa" in store_name_el.get_attribute("data-storename"):
                print("[INFO] Found 'Food Basics - Oshawa' store item.")
                label_for_radio = li.find_element(By.CSS_SELECTOR, "label[for='100636']")
                driver.execute_script("arguments[0].scrollIntoView(true);", label_for_radio)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", label_for_radio)
                print("[INFO] Radio button selected via label + JS click.")
                store_found = True
                break
        except NoSuchElementException:
            continue
    if not store_found:
        print("[ERROR] 'Food Basics - Oshawa' not found in store list.")
        return False
    # 8) Confirm store
    try:
        confirm_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "button.cta-primary.medium.w-100.setMyStoreButton")
        ))
        driver.execute_script("arguments[0].scrollIntoView(true);", confirm_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", confirm_btn)
        print("[INFO] Clicked 'Confirm my shopping store'.")
    except TimeoutException:
        print("[ERROR] Confirm button not found.")
        return False
    old_url = driver.current_url
    try:
        wait.until(lambda d: d.current_url != old_url)
        print("[INFO] Page URL changed => store confirmed.")
    except TimeoutException:
        print("[WARN] URL did not change. Possibly already selected or an AJAX approach.")
    print("[SUCCESS] Store is selected: 'Food Basics - Oshawa'!")
    time.sleep(2)
    return True

def go_to_page(driver, page_num):
    """Navigate to the specified Food Basics results page."""
    url = f"https://www.foodbasics.ca/search-page-{page_num}"
    print(f"[INFO] Navigating to {url} ...")
    driver.get(url)
    time.sleep(3)

def scrape_all_pages(driver, state):
    """
    Loop through pages starting from state["current_page"].
    When no items are found on a page, mark the run as complete.
    """
    while True:
        page_num = state["current_page"]
        go_to_page(driver, page_num)
        success = scrape_items_on_page(driver, state)
        if not success:
            print("[INFO] No more items => done scraping all pages.")
            state["completed_run"] = True
            save_state(state)
            break
        state["current_page"] += 1
        state["current_item"] = 0
        save_state(state)

def scrape_items_on_page(driver, state):
    """
    Locate and scrape all items on the current page,
    starting from state["current_item"]. Returns True if items are found.
    """
    wait = WebDriverWait(driver, 20)
    item_xpath = (
        "//div[contains(@class, 'default-product-tile') and "
        "contains(@class, 'tile-product') and "
        "contains(@class, 'item-addToCart')]"
    )
    try:
        wait.until(EC.presence_of_element_located((By.XPATH, item_xpath)))
        time.sleep(2)
    except TimeoutException:
        print("[ERROR] No items found on page => presumably end of pages.")
        return False
    items = driver.find_elements(By.XPATH, item_xpath)
    if not items:
        print("[ERROR] Found 0 items => presumably end of pages.")
        return False
    start_index = state["current_item"]
    for i in range(start_index, len(items)):
        items = driver.find_elements(By.XPATH, item_xpath)  # Re-locate to avoid stale references.
        if i >= len(items):
            break
        item = items[i]
        success = scrape_one_item(driver, item, i, state)
        if success:
            state["current_item"] += 1
            save_state(state)
        else:
            print(f"[WARN] Item {i} failed. Skipping and continuing.")
    return True

def scrape_one_item(driver, item, i, state):
    """
    Click on an individual item, scrape its details,
    and then either add it as a new document or update its dynamic fields.
    Uses the encoded URL as the document ID.
    """
    wait = WebDriverWait(driver, 20)
    try:
        link = item.find_element(By.TAG_NAME, "a")
        driver.execute_script("arguments[0].scrollIntoView(true);", link)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", link)
        print(f"[INFO] Page {state['current_page']}: Clicked item {i}.")
    except Exception as e:
        print(f"[ERROR] Could not click item {i} on page {state['current_page']}: {e}")
        return False

    try:
        wait.until(EC.url_contains("/p/"))
    except TimeoutException:
        print("[ERROR] Item details page didn't load in time.")
        driver.back()
        time.sleep(2)
        return False

    # Use the full URL, encoded to be a safe document ID.
    current_url = driver.current_url
    doc_id = quote(current_url, safe='')

    # Extract categories from the URL.
    parts = current_url.split('/')
    main_cat = parts[4] if len(parts) > 4 else ""
    second_cat = parts[5] if len(parts) > 5 else ""
    third_cat = parts[7] if len(parts) > 7 else (parts[6] if len(parts) > 6 else "")
    main_cat = main_cat.replace('-', ' ').strip()
    second_cat = second_cat.replace('-', ' ').strip()
    third_cat = third_cat.replace('-', ' ').strip()

    # Apply custom mapping if needed.
    mapping = {
        "dairy eggs": "dairy and eggs",
        "fruits vegetables": "fruits and vegetables",
        "meat poultry": "meat and poultry",
        "deli prepared meals": "deli and prepared meals"
    }
    if main_cat.lower() in mapping:
        main_cat = mapping[main_cat.lower()]

    try:
        product_el = driver.find_element(By.XPATH, "//h1[@class='pi--title']")
        product_name = product_el.text.strip()
    except Exception:
        product_name = "NA"

    try:
        size_el = driver.find_element(By.XPATH, "//div[contains(@class, 'pi--weight')]")
        size = size_el.text.strip()
    except Exception:
        size = "NA"

    try:
        brand_el = driver.find_element(By.XPATH, "//div[@class='pi--brand']")
        brand_name = brand_el.text.strip() if brand_el.text.strip() else "NA"
    except Exception:
        brand_name = "NA"

    try:
        price_els = driver.find_elements(By.XPATH, "//span[@class='price-update']")
        if price_els:
            default_price = " ".join(el.text.strip() for el in price_els if el.text.strip())
        else:
            default_price = "NA"
    except Exception:
        default_price = "NA"

    try:
        sale_price_el = driver.find_element(By.XPATH, "//span[@class='price-update pi-price-promo']")
        sale_price = sale_price_el.text.strip()
    except Exception:
        sale_price = None

    try:
        original_price_el = driver.find_element(By.XPATH, "//div[@class='pricing__before-price']/span[not(@class)]")
        original_price = original_price_el.text.strip()
    except Exception:
        original_price = None

    if sale_price or original_price:
        on_sale = "YES"
        price_per_unit = sale_price if sale_price else default_price
    else:
        on_sale = "NO"
        price_per_unit = default_price

    # Check stock status.
    try:
        WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'button-tile-addToCart')]"))
        )
        in_stock = "YES"
    except TimeoutException:
        in_stock = "NO"

    master_cat = get_master_category(main_cat)

    # Build the complete data document.
    full_data = {
        "Store": "FoodBasics",
        "MasterCategory": master_cat,
        "MainCategory": main_cat,
        "SecondLevel": second_cat,
        "ThirdLevel": third_cat,
        "Product": product_name,
        "URL": current_url,
        "Brand": brand_name,
        "Size": size,
        "PricePerUnit": price_per_unit,
        "OnSale": on_sale,
        "OriginalPrice": original_price if original_price else "NA",
        "SalePrice": sale_price if sale_price else "NA",
        "InStock": in_stock
    }
    # Build a subset of the data for dynamic updates.
    dynamic_data = {
        "PricePerUnit": price_per_unit,
        "OnSale": on_sale,
        "OriginalPrice": original_price if original_price else "NA",
        "SalePrice": sale_price if sale_price else "NA",
        "Size": size
    }

    # Check if the document exists.
    doc_ref = db.collection("FoodBasics").document(doc_id)
    doc = doc_ref.get()

    if state["run_mode"] == "append":
        # In append mode, add the item if it does not exist.
        if not doc.exists:
            add_new_item(doc_id, full_data)
        else:
            print(f"[INFO] Item with URL-ID {doc_id} already exists. Skipping duplicate add in append mode.")
    else:
        # In overwrite mode, update the dynamic fields if the document exists;
        # otherwise, add the item.
        if doc.exists:
            update_dynamic_fields(doc_id, dynamic_data)
        else:
            add_new_item(doc_id, full_data)

    # Navigate back to the search results.
    driver.back()
    time.sleep(2)
    return True

def main():
    global state
    state = load_state()
    print(f"[INFO] Starting run in {state['run_mode'].upper()} mode. "
          f"Page={state['current_page']}, Item={state['current_item']}, CompletedRun={state['completed_run']}")

    # If a full run was completed.
    if state["completed_run"]:
        if state["run_mode"] == "append":
            print("[INFO] Completed full pass in 'append' mode. Switching to overwrite mode for updates.")
            reset_state_for_overwrite(state)
        else:
            print("[INFO] Completed pass in 'overwrite' mode. Starting overwrite pass from the top.")
            state["current_page"] = 1
            state["current_item"] = 0
            state["completed_run"] = False
            save_state(state)

    driver = get_driver()
    try:
        ok = set_up_store(driver)
        if not ok:
            print("[ERROR] Could not set the store. Exiting.")
            return

        # Start scraping pages.
        scrape_all_pages(driver, state)
        if state["completed_run"]:
            print("[INFO] Full pass completed. Next run will update dynamic fields or add new items as needed.")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()