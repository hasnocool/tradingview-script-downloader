# TradingView PineScript Downloader

This Python script automates the extraction of PineScript codes from the most popular strategies on TradingView using Selenium and BeautifulSoup for web scraping.

## Features

- Automatically navigates through the TradingView strategies.
- Extracts PineScript codes from each strategy.
- Saves the PineScript in a structured format with additional metadata like the script name, author, and description.
- Handles pagination to move through multiple pages of scripts.
- Robust error handling and retries for failed page loads.

## Prerequisites

Before running this script, ensure the following prerequisites are met:

- Python 3.x installed.
- Selenium WebDriver installed.
- Firefox and geckodriver installed.
- BeautifulSoup and Requests libraries installed.

## Setup

1. **Clone this repository or download the script:**

git clone https://your-repository-url.git

2. **Install the required Python packages:**

pip install selenium beautifulsoup4 requests

Ensure geckodriver is installed and correctly linked:

You can download it from Mozilla's GitHub and ensure it's in your PATH or specify the path in the script.

## Usage

Run the script using Python from your command line:

python tradingview_pinescript_downloader.py

The script will start processing pages from TradingView, downloading scripts, and saving them locally in the PineScripts directory.
Output

Scripts will be saved in the PineScripts directory with the .pine extension. Each file contains:

Script Name
Author
Description
PineScript code

## Contributing

Feel free to fork the repository, make changes, and submit pull requests. For major changes, please open an issue first to discuss what you would like to change.
License

This project is licensed under the MIT License - see the LICENSE file for details.
