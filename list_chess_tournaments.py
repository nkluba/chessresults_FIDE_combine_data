import os
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


BASE_URL = "https://chess-results.com/TurnierSuche.aspx?lan=1"
SAVE_PATH = "processed_data"
START_DATE = "01.01.2019"
END_DATE = "03.03.2019"


def get_player_html(url):
    """Fetch player HTML."""
    return requests.get(url, timeout=15).content


def fix_headers(headers):
    """Ensure Link column exists."""
    if "Link" not in headers:
        index = next((i for i, h in enumerate(headers) if "FideID" in h), None)
        if index is not None:
            headers.insert(index + 1, "Link")
    return headers


def parse_table(html_content):
    """Extract table headers and rows."""
    soup = BeautifulSoup(html_content, "html.parser")
    title = soup.title.string.strip().replace(
        "Chess-Results_Server_Chess-results.com_-_", ""
    )

    table = soup.find("table", class_="CRs1")
    headers = fix_headers([h.text.strip() for h in table.find_all("th")])

    data = []
    for row in table.find_all("tr"):
        row_data = []
        for cell in row.find_all(["td", "th"]):
            if cell.find("a"):
                row_data.append(cell.text.strip())
                row_data.append(cell.find("a")["href"])
            else:
                row_data.append(cell.text.strip())
        if row_data:
            data.append(row_data)

    return headers, data, title


def extract_info_from_html(link):
    """Extract FIDE profile metadata."""
    response = requests.get(link, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")
    profile = soup.find("div", class_="profile-top-info")

    if not profile:
        return None, None, None, None, None

    blocks = profile.find_all("div", class_="profile-top-info__block__row__data")

    federation = blocks[1].text.strip()
    birth_year = blocks[3].text.strip()
    sex = blocks[4].text.strip()
    fide_title = blocks[5].text.strip()
    world_rank = blocks[0].text.strip()

    return federation, birth_year, sex, fide_title, world_rank


def parse_fide_data(df):
    """Enrich dataframe with FIDE metadata."""
    if "Link" not in df.columns or df["Link"].isnull().all():
        return None

    df = df.dropna(subset=["Link"])
    df = df[df["Link"].str.startswith("http")]

    df[["Federation", "Birth Year", "Sex", "FIDE Title", "World Rank"]] = (
        df["Link"].apply(lambda x: pd.Series(extract_info_from_html(x)))
    )

    return df


def create_dataframe(headers, data):
    """Build dataframe from parsed table."""
    try:
        return pd.DataFrame(data, columns=headers).iloc[1:, :]
    except Exception:
        return pd.DataFrame()


def close_obstructive_elements(driver):
    """Close cookie popup."""
    try:
        driver.find_element(
            By.ID, "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"
        ).click()
        time.sleep(2)
    except Exception:
        pass


def extract_details(soup):
    """Extract tournament details."""
    details_table = soup.find("h2").find_next("table")
    if not details_table:
        return None

    data = {}
    for row in details_table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) > 1:
            data[cells[0].text.strip()] = cells[1].text.strip()

    if "Date" in data:
        data["Start Date"], data["End Date"] = data["Date"].split(" to ")
        del data["Date"]

    return data


def process_url(url, driver, query):
    """Extract tournament details and persist."""
    driver.get(url)
    close_obstructive_elements(driver)

    try:
        driver.find_element(By.ID, "cb_alleDetails").click()
    except Exception:
        return

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "CRsmall"))
        )
        driver.find_element(
            By.XPATH, '//a[contains(text(), "Show tournament details")]'
        ).click()
        time.sleep(2)
    except Exception:
        pass

    soup = BeautifulSoup(driver.page_source, "html.parser")
    tournament_data = extract_details(soup)

    if not tournament_data:
        return

    df = pd.DataFrame([tournament_data])
    csv_file = os.path.join(SAVE_PATH, f"{query}_tournament_info.csv")

    if not os.path.isfile(csv_file):
        df.to_csv(csv_file, index=False)
    else:
        df.to_csv(csv_file, mode="a", header=False, index=False)


def setup_driver():
    """Initialize Chrome driver."""
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()))


def accept_cookies(driver):
    """Accept main site cookies."""
    try:
        WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.css-47sehv"))
        ).click()
    except Exception:
        pass


def set_tournament_and_dates(driver, query):
    """Populate search fields."""
    tournament_input = WebDriverWait(driver, 5).until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "input[aria-labelledby='P1_lb_bez']")
        )
    )

    tournament_input.clear()
    tournament_input.send_keys(query)

    driver.find_element(By.ID, "P1_txt_von_tag").send_keys(START_DATE)
    driver.find_element(By.ID, "P1_txt_bis_tag").send_keys(END_DATE)


def set_max_results(driver, value):
    """Set max result size."""
    dropdown = WebDriverWait(driver, 5).until(
        EC.element_to_be_clickable((By.ID, "P1_combo_anzahl_zeilen"))
    )
    Select(dropdown).select_by_value(value)


def get_tournament_links(driver):
    """Collect result links."""
    return [
        e.get_attribute("href")
        for e in driver.find_elements(By.CSS_SELECTOR, "table.CRs2 a")
    ]


def search_and_collect_data(driver, query):
    """Execute search and return links."""
    set_tournament_and_dates(driver, query)
    set_max_results(driver, "5")

    WebDriverWait(driver, 5).until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "input[aria-labelledby='P1_lb_bez']")
        )
    ).send_keys(Keys.ENTER)

    return get_tournament_links(driver)


def main():
    """Main execution loop."""
    queries = ["European Youth", "International Open", "World Youth"]

    os.makedirs(SAVE_PATH, exist_ok=True)

    driver = setup_driver()
    driver.get(BASE_URL)
    accept_cookies(driver)

    for query in queries:
        tracking_file = f"{query}_links.csv"
        output_file = f"{query}_tournament_info.csv"

        if not os.path.exists(tracking_file):
            links = search_and_collect_data(driver, query)
            pd.DataFrame({"Link": links, "Checked": False}).to_csv(
                tracking_file, index=False
            )
        else:
            df_links = pd.read_csv(tracking_file)
            links = df_links.loc[df_links["Checked"] == False, "Link"].tolist()

        df_links = pd.read_csv(tracking_file)

        for link in links:
            process_url(link, driver, query)
            df_links.loc[df_links["Link"] == link, "Checked"] = True
            df_links.to_csv(tracking_file, index=False)


if __name__ == "__main__":
    main()
