#!/usr/bin/python

import os
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
import time

# Set the path to the geckodriver executable
geckodriver_path = os.path.join(os.getcwd(), 'geckodriver')

# Launch Firefox WebDriver
driver = webdriver.Firefox(executable_path=geckodriver_path)

base_url = 'https://www.tradingview.com/scripts/'
page = 1

while True:
    url = f'{base_url}page-{page}/?script_type=strategies&script_access=open&sort=month_popular&route_range=1'
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    script_items = soup.find_all('div', class_='tv-feed__item')
    if not script_items:
        break  # Break the loop if there are no more script items on the page

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

                # Create directory if it doesn't exist
                directory = 'PineScripts'
                os.makedirs(directory, exist_ok=True)

                # Replace invalid characters in script name
                invalid_characters = '/\\?%*:|"<>'
                for char in invalid_characters:
                    script_name = script_name.replace(char, '-')

                # Save PineScript to a file with .pine extension
                filename = os.path.join(directory, f"{script_name}.pine")
                with open(filename, 'w') as file:
                    file.write(f"Script Name: {script_name}\n")
                    file.write(f"Author: {script_author}\n")
                    file.write(f"Description: {script_description}\n")
                    file.write("PineScript code:\n\n")
                    file.write(script_code)

                print(f"Saved PineScript code to {filename}\n")

            except NoSuchElementException:
                print(f"Element not found. Skipping script: {script_name}")

    page += 1

# Close the WebDriver
driver.quit()
