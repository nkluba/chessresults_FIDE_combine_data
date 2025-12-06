import os
import time
import duckdb
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
DB_PATH = "chess_data.duckdb"
START_DATE = "01.01.2008"
END_DATE = "01.01.2009"


def init_db():
    """Initialize DuckDB database."""
    conn = duckdb.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tournaments (
            query TEXT,
            link TEXT UNIQUE,
            checked BOOLEAN DEFAULT FALSE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            tournament TEXT,
            Name TEXT,
            FideID TEXT,
            Link TEXT,
            Federation TEXT,
            "Birth Year" TEXT,
            Sex TEXT,
            "FIDE Title" TEXT,
            "World Rank" TEXT,
            UNIQUE(tournament, Link)
        )
    """)

    return conn


def get_player_html(url):
    """Fetch player HTML."""
    response = requests.get(url, timeout=15)
    return response.content


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
    soup = BeautifulSoup(requests.get(link, timeout=15).text, "html.parser")

    federation = soup.select_one(".profile-info-country")
    birth_year = soup.select_one(".profile-info-byear")
    sex = soup.select_one(".profile-info-sex")
    fide_title = soup.select_one(".profile-info-title p")

    world_rank = None
    rank_block = soup.find("h5", string="World Rank")
    if rank_block:
        world_rank = rank_block.find_next("h6", string="All players").find_next("p").text.strip()

    return (
        federation.get_text(strip=True) if federation else None,
        birth_year.get_text(strip=True) if birth_year else None,
        sex.get_text(strip=True) if sex else None,
        fide_title.get_text(strip=True) if fide_title else None,
        world_rank,
    )


def parse_fide_data(df):
    """Enrich dataframe with FIDE metadata."""
    if "Link" not in df.columns:
        return df

    df = df.dropna(subset=["Link"])
    df = df[df["Link"].str.startswith("http")]

    df[["Federation", "Birth Year", "Sex", "FIDE Title", "World Rank"]] = (
        df["Link"].apply(lambda x: pd.Series(extract_info_from_html(x)))
    )

    return df


def create_dataframe(headers, data):
    """Build dataframe from parsed table."""
    return pd.DataFrame(data, columns=headers).iloc[1:, :]


def store_players(conn, tournament, df):
    """Persist players into DuckDB."""
    for _, row in df.iterrows():
        conn.execute("""
            INSERT OR IGNORE INTO players (
                tournament, Name, FideID, Link,
                Federation, "Birth Year", Sex,
                "FIDE Title", "World Rank"
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tournament,
            row.get("Name"),
            row.get("FideID"),
            row.get("Link"),
            row.get("Federation"),
            row.get("Birth Year"),
            row.get("Sex"),
            row.get("FIDE Title"),
            row.get("World Rank"),
        ))


def process_url(conn, url):
    """Extract players and persist."""
    html_content = get_player_html(url)
    headers, table_data, title = parse_table(html_content)

    if not table_data:
        return

    df = create_dataframe(headers, table_data)
    df = parse_fide_data(df)
    df = df[df["Link"].notna()]

    store_players(conn, title, df)


def setup_driver():
    """Initialize Chrome driver."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )


def accept_cookies(driver):
    """Accept site cookies."""
    try:
        WebDriverWait(driver, 10).until(
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
    """Collect tournament links."""
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


def run_data_collection():
    """Main execution loop."""
    queries = ["European Youth", "International Open", "World Youth"]

    conn = init_db()
    driver = setup_driver()
    driver.get(BASE_URL)
    accept_cookies(driver)

    for query in queries:
        pending_links = conn.execute(
            "SELECT link FROM tournaments WHERE query = ? AND checked = FALSE",
            (query,)
        ).fetchall()

        pending_links = [r[0] for r in pending_links]

        if not pending_links:
            links = search_and_collect_data(driver, query)
            for link in links:
                conn.execute(
                    "INSERT OR IGNORE INTO tournaments (query, link, checked) VALUES (?, ?, FALSE)",
                    (query, link)
                )
            pending_links = links

        for link in pending_links:
            process_url(conn, link)
            conn.execute(
                "UPDATE tournaments SET checked = TRUE WHERE link = ?",
                (link,)
            )

    driver.quit()
    conn.close()


run_data_collection()