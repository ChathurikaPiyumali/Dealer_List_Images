# Autostream Dealer Image Scraper – Setup & Run Guide


#1. Install Prerequisites
a) Python
- Download Python 3.11 or 3.12 (64-bit) from https://www.python.org/downloads/windows/
- Run installer:
  * Check "Add Python to PATH"
  * Select "Install for all users"
- Verify installation in PowerShell:
  python --version


------------------------------------------------------------

#2. Prepare Project Folder
- Create a folder, e.g. E:\Downloader
- Open it in VS Code (File → Open Folder…)

------------------------------------------------------------

#3. Add the Script
- Inside the folder, create a new file called:
  dealers_scrape_selenium.py
- Paste the full script (latest fixed version with Show more support).

------------------------------------------------------------

#4. Create Virtual Environment
Open VS Code terminal (View → Terminal) and run:

  python -m venv venv

  .\venv\Scripts\activate

You should see (venv) in front of your prompt.

------------------------------------------------------------

#5. Install Dependencies
With venv active, run:

  pip install selenium webdriver-manager requests beautifulsoup4

------------------------------------------------------------

#6. Run the Scraper
Run in headed mode (to watch Chrome work):

  python dealers_scrape_clickhard_v5.py --headed --dealers https://autostream.lk/dealers-list/ --out autostream_dealers --slow-wait 75

- --headed → runs with a visible Chrome window
- --dealers → starting URL
- --out → folder where images are saved

After completion, check the folder:
  autostream_dealers/
    Dealer_A/
      1/
        01.jpg
        02.jpg
    Dealer_B/
      1/
      2/



