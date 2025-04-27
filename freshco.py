import time
import random
import os
import pickle
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver import ActionChains

# --------------------------
# Firebase Setup (FreshCo)
# --------------------------
import firebase_admin
from firebase_admin import credentials, firestore

FIREBASE_CREDENTIALS_PATH = "firebase_credentials.json"
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
    firebase_admin.initialize_app(cred)
db = firestore.client()
COLLECTION_NAME = "FreshCo"

# --------------------------
# State Management
# --------------------------
# We'll use a separate state file for FreshCo
STATE_FILE = "freshco_state.pkl"

def load_state():
    """
    Returns a dictionary with:
      run_mode: "append" for first full pass or "overwrite" for subsequent passes.
      current_department: index of the current department.
      current_product: index of the current product on the department page.
      completed_run: True if a full pass is finished.
    """
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "rb") as f:
            return pickle.load(f)
    else:
        return {"run_mode": "append", "current_department": 0, "current_product": 0, "completed_run": False}

def save_state(state):
    with open(STATE_FILE, "wb") as f:
        pickle.dump(state, f)

def reset_state_for_overwrite(state):
    """
    Once a full pass in append mode is done, switch to overwrite mode.
    In overwrite mode, the scraper will run from the beginning of the department list,
    and for each product it will check the URL—if a document exists, update its dynamic fields;
    otherwise, add a new document.
    """
    state["run_mode"] = "overwrite"
    state["current_department"] = 0
    state["current_product"] = 0
    state["completed_run"] = False
    save_state(state)

freshco_state = load_state()

# --------------------------
# Firebase Write Functions
# --------------------------
def add_new_freshco_item(data):
    """
    Adds a new FreshCo item document to the COLLECTION_NAME using an auto‑generated ID.
    """
    write_time, doc_ref = db.collection(COLLECTION_NAME).add(data)
    print(f"[INFO] Added new FreshCo item with auto-generated id: {doc_ref.id}")

def update_freshco_dynamic_fields(doc_id, dynamic_data):
    """
    Updates dynamic fields of an existing FreshCo item.
    """
    db.collection(COLLECTION_NAME).document(doc_id).update(dynamic_data)
    print(f"[INFO] Updated dynamic fields for FreshCo doc id: {doc_id}")

# --------------------------
# Selenium Helper Functions
# --------------------------
def human_typing(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.1, 0.4))

def human_delay(min_sec=2.0, max_sec=5.0):
    time.sleep(random.uniform(min_sec, max_sec))

def robust_click(driver, element):
    """Attempts normal click, then JS click, then ActionChains click."""
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

def ensure_driver_focus(driver):
    """
    Bring the driver window into focus.
    This can help when the window is minimized or obscured.
    """
    driver.switch_to.window(driver.current_window_handle)
    driver.execute_script("window.focus();")
    driver.set_window_position(0, 0)

# --------------------------
# Browser Configuration
# --------------------------
chrome_options = webdriver.ChromeOptions()
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("--window-size=1920,1080")
# Do NOT add --headless so the window is visible.
# Optionally, you may remove "--start-maximized" so that the window does not always forcefully maximize.
driver = webdriver.Chrome(options=chrome_options)
driver.execute_cdp_cmd(
    "Page.addScriptToEvaluateOnNewDocument",
    {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
)
wait = WebDriverWait(driver, 30)

# --------------------------
# FreshCo Scraper Logic
# --------------------------
def main():
    global freshco_state
    print(f"[INFO] Starting FreshCo run in {freshco_state['run_mode'].upper()} mode. Department {freshco_state['current_department']}, Product {freshco_state['current_product']}, CompletedRun {freshco_state['completed_run']}")
    
    if freshco_state["completed_run"]:
        if freshco_state["run_mode"].lower() == "append":
            print("[INFO] Completed full pass in 'append' mode. Switching to overwrite mode for updates.")
            reset_state_for_overwrite(freshco_state)
        else:
            print("[INFO] Completed pass in 'overwrite' mode. Restarting overwrite from the top.")
            freshco_state["current_department"] = 0
            freshco_state["current_product"] = 0
            freshco_state["completed_run"] = False
            save_state(freshco_state)
    
    try:
        # 1. Sign in & set address
        print("[STEP] Opening FreshCo homepage")
        homepage_url = "https://www.instacart.ca/store/freshco-ca/storefront?guest=true"
        driver.get(homepage_url)
        human_delay(2,4)
        
        print("[STEP] Clicking 'Sign in with Google'")
        google_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@role='button' and @aria-labelledby='button-label']")))
        robust_click(driver, google_button)
        human_delay()
        
        print("[STEP] Switching to Google sign-in window")
        original_window = driver.current_window_handle
        WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > 1)
        for handle in driver.window_handles:
            if handle != original_window:
                driver.switch_to.window(handle)
                break
        human_delay()
        
        print("[STEP] Entering email")
        email_input = wait.until(EC.visibility_of_element_located((By.ID, "identifierId")))
        human_typing(email_input, "pantrylistapp@gmail.com")
        human_delay()
        
        print("[STEP] Next after email")
        next_email_button = wait.until(EC.element_to_be_clickable((By.ID, "identifierNext")))
        robust_click(driver, next_email_button)
        human_delay()
        
        print("[STEP] Entering password")
        password_input = wait.until(EC.visibility_of_element_located((By.XPATH, "//input[@type='password']")))
        human_typing(password_input, "Hello@123")
        human_delay()
        
        print("[STEP] Next after password")
        next_password_button = wait.until(EC.element_to_be_clickable((By.ID, "passwordNext")))
        robust_click(driver, next_password_button)
        human_delay(5,7)
        
        print("[STEP] Switching back to main window")
        orig_handles = driver.window_handles
        if original_window not in orig_handles:
            original_window = orig_handles[0]
        driver.switch_to.window(original_window)
        print("Switched to main window after authentication.")
        
        print("[STEP] Waiting for potential popup...")
        time.sleep(10)
        close_buttons = driver.find_elements(By.XPATH, "//button[@aria-label='close']")
        if close_buttons:
            for idx, button in enumerate(close_buttons):
                try:
                    wait.until(EC.element_to_be_clickable((By.XPATH, f"(//button[@aria-label='close'])[{idx+1}]")))
                    driver.execute_script("arguments[0].scrollIntoView(true);", button)
                    time.sleep(1)
                    robust_click(driver, button)
                    break
                except Exception as e:
                    print(f"[POPUP] Error clicking close button #{idx+1}: {e}")
        print("[STEP] Setting address to OSHAWA")
        header_button_xpath = "//header[@id='commonHeader']//button[@class='e-1e9xs4d' and @aria-haspopup='dialog']"
        header_button = wait.until(EC.element_to_be_clickable((By.XPATH, header_button_xpath)))
        robust_click(driver, header_button)
        human_delay()
        address_box_xpath = "/html/body/div/div/div/div[2]/div/div/div/div/div/input[@id='streetAddress']"
        address_input = wait.until(EC.visibility_of_element_located((By.XPATH, address_box_xpath)))
        address_input.clear()
        address_input.send_keys("OSHAWA")
        human_delay()
        first_suggestion_xpath = "//ul[@id='address-suggestion-list']//li[@id='address-suggestion-list_0']//button[@class='e-s5poa1']/div[@class='e-0']"
        first_suggestion = wait.until(EC.element_to_be_clickable((By.XPATH, first_suggestion_xpath)))
        robust_click(driver, first_suggestion)
        human_delay()
        save_address_button_xpath = "//form[@aria-label='form']//button[@type='submit' and contains(@class, 'e-1yr5kx3')]"
        save_button = wait.until(EC.element_to_be_clickable((By.XPATH, save_address_button_xpath)))
        robust_click(driver, save_button)
        human_delay(5,7)
        
        # 2. Process Departments and Products
        print("[STEP] Processing departments")
        driver.get(homepage_url)
        human_delay(2,4)
        departments_xpath = "//a[contains(@href, '/store/freshco-ca/collections/') and contains(@class, 'e-v0wv1')]"
        department_elements = wait.until(EC.visibility_of_all_elements_located((By.XPATH, departments_xpath)))
        num_departments = len(department_elements)
        print(f"[DEPT] Found {num_departments} departments.")
        
        # Process each department starting from state
        for dept_index in range(freshco_state.get("current_department", 0), num_departments):
            try:
                print(f"\n[DEPT] Processing department {dept_index+1}/{num_departments}")
                driver.get(homepage_url)
                human_delay(2,4)
                department_elements = wait.until(EC.visibility_of_all_elements_located((By.XPATH, departments_xpath)))
                department_element = department_elements[dept_index]
                department_name = department_element.text.strip() or f"Dept_{dept_index+1}"
                print(f"[DEPT] Clicking department: {department_name}")
                driver.execute_script("arguments[0].scrollIntoView(true);", department_element)
                human_delay(1,2)
                try:
                    driver.execute_script("var overlay = document.querySelector('div.e-1vd4sb7'); if(overlay) overlay.remove();")
                    print("[DEPT] Removed interfering overlay if present.")
                except Exception as e:
                    print("[DEPT] Error removing overlay:", e)
                robust_click(driver, department_element)
                human_delay(3,5)
                wait.until(lambda d: "/store/freshco-ca/collections/" in d.current_url)
                print(f"[DEPT] Department page loaded: {driver.current_url}")
                
                # Infinite scroll for products
                products_xpath = "//div[@class='e-13udsys']"
                while True:
                    old_height = driver.execute_script("return document.body.scrollHeight")
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(3)
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    if new_height == old_height:
                        print("[SCROLL] No new items; waiting 30s...")
                        time.sleep(30)
                        check_height = driver.execute_script("return document.body.scrollHeight")
                        if check_height == new_height:
                            print("[SCROLL] No additional items. Done scrolling.")
                            break
                        else:
                            print("[SCROLL] More items loaded after wait. Continuing.")
                    else:
                        print("[SCROLL] New items loaded; continuing scroll.")
                
                product_elems = driver.find_elements(By.XPATH, products_xpath)
                total_products = len(product_elems)
                print(f"[DEPT] Found {total_products} products in dept '{department_name}'.")
                
                for prod_index in range(freshco_state.get("current_product", 0), total_products):
                    try:
                        print(f"  [PRODUCT] Processing product {prod_index+1}/{total_products} in '{department_name}'")
                        product_xpath = f"({products_xpath})[{prod_index+1}]"
                        product_el = wait.until(EC.element_to_be_clickable((By.XPATH, product_xpath)))
                        driver.execute_script("arguments[0].scrollIntoView(true);", product_el)
                        human_delay(1,2)
                        robust_click(driver, product_el)
                        human_delay(2,3)
                        
                        ensure_driver_focus(driver)
                        
                        product_url = driver.current_url
                        try:
                            name_xpath = "//div[@id='item_details']//span[@class='e-6vf2xs']"
                            name_el = wait.until(EC.visibility_of_element_located((By.XPATH, name_xpath)))
                            product_name = name_el.text
                        except:
                            product_name = "Name not found"
                        
                        try:
                            price_xpath = "//span[@class='e-jln0k3']//span[@class='e-0' and contains(text(), '$')]"
                            price_el = wait.until(EC.visibility_of_element_located((By.XPATH, price_xpath)))
                            product_price = price_el.text
                        except:
                            product_price = "Price not found"
                        
                        try:
                            size_xpath = "//div[@class='e-k008qs']//span[@class='e-f17zur']"
                            size_el = wait.until(EC.visibility_of_element_located((By.XPATH, size_xpath)))
                            product_size = size_el.text
                        except:
                            product_size = "Size not found"
                        
                        try:
                            # Determine availability by looking for buttons labelled "Request" or "Add to cart"
                            request_btn_xpath = "//button[@data-testid='submit-button' and .//span[text()='Request']]"
                            add_btn_xpath = "//button[@data-testid='submit-button' and .//span[text()='Add to cart']]"
                            request_buttons = driver.find_elements(By.XPATH, request_btn_xpath)
                            add_buttons = driver.find_elements(By.XPATH, add_btn_xpath)
                            if len(request_buttons) > 0:
                                availability = "Out of Stock"
                            elif len(add_buttons) > 0:
                                availability = "In Stock"
                            else:
                                availability = "Unknown"
                        except:
                            availability = "Unknown"
                        
                        print(f"    URL:   {product_url}")
                        print(f"    Name:  {product_name}")
                        print(f"    Price: {product_price}")
                        print(f"    Size:  {product_size}")
                        print(f"    Availability: {availability}")
                        
                        master_category = get_master_category(department_name)
                        
                        # Build document data for FreshCo
                        freshco_data = {
                            "Store": "FreshCo",
                            "MasterCategory": master_category,
                            "MainCategory": department_name,
                            "SecondLevel": "",
                            "ThirdLevel": "",
                            "Product": product_name,
                            "URL": product_url,
                            "Brand": "",
                            "Size": product_size,
                            "PricePerUnit": product_price,
                            "OnSale": "No",
                            "OriginalPrice": "NA",
                            "SalePrice": "NA",
                            "InStock": availability
                        }
                        dynamic_data = {
                            "PricePerUnit": product_price,
                            "Size": product_size,
                            "OnSale": "No",
                            "OriginalPrice": "NA",
                            "SalePrice": "NA"
                        }
                        
                        # Firebase integration: check by URL.
                        query = db.collection(COLLECTION_NAME).where("URL", "==", product_url).get()
                        if freshco_state["run_mode"].lower() == "append":
                            if len(query) == 0:
                                add_new_freshco_item(freshco_data)
                            else:
                                print(f"[INFO] Item with URL {product_url} already exists. Skipping duplicate add.")
                        else:
                            if len(query) > 0:
                                for doc in query:
                                    update_freshco_dynamic_fields(doc.id, dynamic_data)
                            else:
                                add_new_freshco_item(freshco_data)
                        
                        driver.back()
                        human_delay(2,3)
                    except Exception as prod_exc:
                        print(f"  [PRODUCT] Error processing product {prod_index+1}/{total_products}: {prod_exc}")
                
                freshco_state["current_product"] = 0
                freshco_state["current_department"] = dept_index + 1
                save_state(freshco_state)
            except Exception as dept_exc:
                print(f"[DEPT] Error processing department {dept_index+1}: {dept_exc}")
        
        freshco_state["completed_run"] = True
        save_state(freshco_state)
        print("[INFO] Full pass completed. Next run will update dynamic fields or add new items as needed.")
    
    except Exception as main_exc:
        print("[ERROR] Error during FreshCo execution:", main_exc)
    
try:
    main()
except Exception as e_main:
    print("[ERROR] Fatal error:", e_main)
finally:
    driver.quit()
