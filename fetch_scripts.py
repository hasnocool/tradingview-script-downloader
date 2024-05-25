import os
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.firefox.options import Options
import time

# Set the path to the geckodriver executable
geckodriver_path = os.path.join(os.getcwd(), 'geckodriver')

# Configure Firefox options for headless browsing
firefox_options = Options()
firefox_options.add_argument("--headless")

# Launch Firefox WebDriver with headless options
driver = webdriver.Firefox(executable_path=geckodriver_path, options=firefox_options)

base_url = 'https://www.tradingview.com/scripts/'

async def download_page(session, page):
    url = f'{base_url}page-{page}/?script_type=strategies&script_access=open&sort=month_popular&route_range=1'

    async with session.get(url) as response:
        content = await response.text()

    soup = BeautifulSoup(content, 'html.parser')

    script_items = soup.find_all('div', class_='tv-feed__item')
    if not script_items:
        return  # Return if there are no more script items on the page

    for item in script_items:
        if item.get('data-widget-type') == 'idea':
            script_data = item.get('data-widget-data')
            script_name = item.find('a', class_='tv-widget-idea__title').text.strip()
            script_author = item.find('span', class_='tv-card-user-info__name').text.strip()
            script_description = item.find('p', class_='tv-widget-idea__description-row').text.strip()
            print('Script Name:', script_name)
            print('Author:', script_author)
            print('Description:', script_description)
            print('---')

            # Replace invalid characters in script name
            invalid_characters = '/\\?%*:|"<>'
            for char in invalid_characters:
                script_name = script_name.replace(char, '-')

            # Create directory if it doesn't exist
            directory = 'PineScripts'
            os.makedirs(directory, exist_ok=True)

            # Check if the file already exists
            filename = os.path.join(directory, f"{script_name}.pine")
            if os.path.exists(filename):
                print(f"Skipping page {page}. File already exists: {filename}\n")
                continue

            # Extract PineScript code
            script_url = item.find('a', class_='tv-widget-idea__title').get('href')
            script_full_url = f'https://www.tradingview.com{script_url}'

            # Open the script page with Firefox
            driver.get(script_full_url)
            time.sleep(2)  # Add a delay to allow the page to fully load

            try:
                # Find and expand the collapse buttons
                collapse_buttons = driver.find_elements(By.CLASS_NAME, "collapseBtn")
                for button in collapse_buttons:
                    driver.execute_script("arguments[0].click();", button)
                    time.sleep(1)  # Add a delay after expanding each collapse button

                # Get the PineScript code element
                script_code_element = driver.find_element(By.CLASS_NAME, "tv-chart-view__script-wrap")

                # Get the PineScript code text using innerText property
                script_code = script_code_element.get_property("innerText").strip()

                # Save PineScript to a file with .pine extension
                with open(filename, 'w') as file:
                    file.write(f"Script Name: {script_name}\n")
                    file.write(f"Author: {script_author}\n")
                    file.write(f"Description: {script_description}\n")
                    file.write("PineScript code:\n")
                    file.write(script_code)

                print(f"Saved PineScript code to {filename}\n")

            except NoSuchElementException:
                print(f"Element not found. Skipping script: {script_name}")

async def process_pages():
    async with aiohttp.ClientSession() as session:
        page = 1
        while True:
            await download_page(session, page)
            page += 1

# Number of pages to download concurrently
num_concurrent_pages = 3

# Run the event loop
loop = asyncio.get_event_loop()
tasks = [process_pages() for _ in range(num_concurrent_pages)]
loop.run_until_complete(asyncio.gather(*tasks))

# Close the WebDriver
driver.quit()
