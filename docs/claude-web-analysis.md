根據我對 Uber Eats 頁面的分析,我為您提供以下爬蟲實作方案:
🎯 核心發現
這些分類標籤(速食、早餐、珍珠奶茶、咖啡等)都有統一的 data-testid 屬性,這是最穩定的選擇器!
📋 實作方法
方法 1: 使用 data-testid (最推薦)
pythonfrom selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 初始化瀏覽器
driver = webdriver.Chrome()
driver.get("https://www.ubereats.com/tw/feed?...")

# 點擊特定分類
categories = {
    "速食": "search-home-item-速食",
    "早餐": "search-home-item-早餐和早午餐",
    "珍珠奶茶": "search-home-item-珍珠奶茶",
    "咖啡": "search-home-item-咖啡和茶",
    "披薩": "search-home-item-披薩",
    "烘焙食品": "search-home-item-烘焙食品",
    "台灣美食": "search-home-item-台灣美食"
}

# 點擊"速食"標籤
fast_food_btn = driver.find_element(By.CSS_SELECTOR, '[data-testid="search-home-item-速食"]')
fast_food_btn.click()

# 或使用迴圈點擊多個分類
for category_name, test_id in categories.items():
    element = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, f'[data-testid="{test_id}"]'))
    )
    element.click()
    print(f"已點擊: {category_name}")
    # 等待頁面加載
    time.sleep(2)
方法 2: 獲取所有可用分類
python# 獲取所有分類標籤
all_categories = driver.find_elements(By.CSS_SELECTOR, '[data-testid^="search-home-item-"]')

for category in all_categories:
    category_name = category.text
    test_id = category.get_attribute('data-testid')
    print(f"分類: {category_name}, ID: {test_id}")
方法 3: 使用 XPath
python# 使用 XPath 選擇特定分類
coffee_btn = driver.find_element(By.XPATH, '//a[@data-testid="search-home-item-咖啡和茶"]')
coffee_btn.click()
🔍 重要發現
根據我的分析,頁面上共有 25+ 個分類標籤,包括:

速食
早餐和早午餐
珍珠奶茶
咖啡和茶
烘焙食品
披薩
台灣美食
漢堡
壽司
拉麵
等等...

⚠️ 注意事項

等待元素加載: 這些標籤可能需要滾動才能看到,建議使用 WebDriverWait
動態內容: 頁面使用動態渲染,確保元素可點擊後再操作
分類名稱: 注意完整名稱是「早餐和早午餐」、「咖啡和茶」,不是單純的「早餐」、「咖啡」

這樣您的爬蟲就可以輕鬆選擇並點擊任何想要的分類標籤了! 🎉