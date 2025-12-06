import argparse
import sys
import duckdb
import logging
import requests
import time
import random
from requests.exceptions import RequestException, Timeout
import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC


BASE_URL = "https://chess-results.com/TurnierSuche.aspx?lan=1"
DB_PATH = "/app/processed_data/chess_data.duckdb"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)


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


def log_progress(current, total, label):
    percent = (current / total) * 100
    logging.info(f"{label} progress: {current}/{total} ({percent:.1f}%)")


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


def extract_info_from_html(link, max_retries=3, base_delay=2):
    """Extract FIDE profile metadata with retries."""
    attempt = 0

    while attempt < max_retries:
        try:
            response = requests.get(link, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            federation = soup.select_one(".profile-info-country")
            birth_year = soup.select_one(".profile-info-byear")
            sex = soup.select_one(".profile-info-sex")
            fide_title = soup.select_one(".profile-info-title p")

            world_rank = None
            rank_block = soup.find("h5", string="World Rank")
            if rank_block:
                world_rank = rank_block.find_next("h6", string="All players") \
                                         .find_next("p") \
                                         .text.strip()

            return (
                federation.get_text(strip=True) if federation else None,
                birth_year.get_text(strip=True) if birth_year else None,
                sex.get_text(strip=True) if sex else None,
                fide_title.get_text(strip=True) if fide_title else None,
                world_rank,
            )

        except (RequestException, Timeout) as e:
            attempt += 1
            wait_time = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)

            logging.warning(
                f"FIDE profile fetch failed (attempt {attempt}/{max_retries}) | "
                f"URL={link} | Error={type(e).__name__} | Retrying in {wait_time:.1f}s"
            )

            time.sleep(wait_time)

    logging.error(f"FIDE profile permanently failed after {max_retries} attempts: {link}")

    return (None, None, None, None, None)


def parse_fide_data(df):
    """Enrich dataframe with FIDE metadata safely."""
    if "Link" not in df.columns:
        return df

    df = df.dropna(subset=["Link"])
    df = df[df["Link"].str.startswith("http")]

    results = []

    for link in df["Link"]:
        try:
            result = extract_info_from_html(link)
        except Exception as e:
            logging.error(f"Unexpected failure in FIDE parsing for {link}: {e}")
            result = (None, None, None, None, None)

        results.append(result)

    df[["Federation", "Birth Year", "Sex", "FIDE Title", "World Rank"]] = pd.DataFrame(
        results, index=df.index
    )

    return df


def create_dataframe(headers, data):
    """Build dataframe from parsed table."""
    return pd.DataFrame(data, columns=headers).iloc[1:, :]


def store_players(conn, tournament, df):
    """Persist players into DuckDB."""
    inserted = 0

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
        inserted += 1

    count = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    logging.info(f"Total players now in database: {count}, inserted this batch: {inserted}")


def process_url(conn, url):
    """Extract players and persist."""
    logging.info(f"Fetching tournament page: {url}")

    try:
        html_content = get_player_html(url)
        headers, table_data, title = parse_table(html_content)

        if not table_data:
            logging.error(f"NO TABLE DATA FOUND at tournament page: {url}")
            return

        logging.info(f"Parsed tournament '{title}' with {len(table_data)} raw rows")

        df = create_dataframe(headers, table_data)

        if df.empty:
            logging.error(f"EMPTY DATAFRAME after parsing for tournament: {title}")
            return

        df = parse_fide_data(df)
        df = df[df["Link"].notna()]

        logging.info(f"Storing {len(df)} players for tournament: {title}")

        store_players(conn, title, df)
        logging.info(f"Stored tournament successfully: {title}")

    except Exception as e:
        logging.exception(f"Processing failed for tournament URL: {url}")


def setup_driver():
    """Initialize Chrome driver."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    return webdriver.Chrome(
        service=Service("/usr/bin/chromedriver"),
        options=options
    )


def accept_cookies(driver):
    """Accept site cookies."""
    try:
        WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.css-47sehv"))
        ).click()
    except Exception:
        pass


def set_tournament_and_dates(driver, query, start_date, end_date):
    """Populate search fields."""
    tournament_input = WebDriverWait(driver, 5).until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "input[aria-labelledby='P1_lb_bez']")
        )
    )

    tournament_input.clear()
    tournament_input.send_keys(query)

    driver.find_element(By.ID, "P1_txt_von_tag").clear()
    driver.find_element(By.ID, "P1_txt_von_tag").send_keys(start_date)

    driver.find_element(By.ID, "P1_txt_bis_tag").clear()
    driver.find_element(By.ID, "P1_txt_bis_tag").send_keys(end_date)


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


def search_and_collect_data(driver, query, start_date, end_date):
    """Execute search and return links."""
    logging.info(f"Submitting search: query='{query}', start={start_date}, end={end_date}")

    set_tournament_and_dates(driver, query, start_date, end_date)
    set_max_results(driver, "5")

    WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "input[aria-labelledby='P1_lb_bez']")
        )
    ).send_keys(Keys.ENTER)

    #time.sleep(1)

    links = get_tournament_links(driver)

    logging.info(f"Found {len(links)} tournament links for query '{query}'")

    if not links:
        logging.warning(f"ZERO tournament links returned for query '{query}'")

    return links


def print_tables_preview(conn):
    """Print first 30 rows of tables."""
    t_count = conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0]
    p_count = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]

    logging.info(f"FINAL TOURNAMENT ROW COUNT: {t_count}")
    logging.info(f"FINAL PLAYER ROW COUNT: {p_count}")

    print("\n===== TOURNAMENTS (FIRST 30 ROWS) =====")
    tournaments_df = conn.execute(
        "SELECT * FROM tournaments LIMIT 30"
    ).fetchdf()
    print(tournaments_df)

    print("\n===== PLAYERS (FIRST 30 ROWS) =====")
    players_df = conn.execute(
        "SELECT * FROM players LIMIT 30"
    ).fetchdf()
    print(players_df)


def run_data_collection(start_date, end_date, queries):
    """Main execution loop."""
    conn = init_db()
    driver = setup_driver()
    driver.get(BASE_URL)
    accept_cookies(driver)

    total_queries = len(queries)
    logging.info(f"Starting data collection for {total_queries} queries")

    for q_index, query in enumerate(queries, start=1):
        logging.info(f"Starting query {q_index}/{total_queries}: {query}")

        pending_links = conn.execute(
            "SELECT link FROM tournaments WHERE query = ? AND checked = FALSE",
            (query,)
        ).fetchall()

        pending_links = [r[0] for r in pending_links]

        if not pending_links:
            links = search_and_collect_data(driver, query, start_date, end_date)

            logging.info(f"Inserting {len(links)} tournament links into DB for query '{query}'")

            for link in links:
                conn.execute(
                    "INSERT OR IGNORE INTO tournaments (query, link, checked) VALUES (?, ?, FALSE)",
                    (query, link)
                )

            db_count = conn.execute(
                "SELECT COUNT(*) FROM tournaments WHERE query = ?",
                (query,)
            ).fetchone()[0]

            logging.info(f"Database now holds {db_count} tournaments for query '{query}'")
            pending_links = links

        total_tournaments = len(pending_links)
        logging.info(f"Processing {total_tournaments} tournaments for query '{query}'")

        for t_index, link in enumerate(pending_links, start=1):
            logging.info(f"Tournament {t_index}/{total_tournaments} for query '{query}'")

            process_url(conn, link)

            conn.execute(
                "UPDATE tournaments SET checked = TRUE WHERE link = ?",
                (link,)
            )

            log_progress(t_index, total_tournaments, f"Tournaments [{query}]")

        log_progress(q_index, total_queries, "Queries")

        logging.info(f"Completed query {q_index}/{total_queries}: {query}")

    driver.quit()
    print_tables_preview(conn)
    conn.close()
    logging.info("Data collection completed")


def evoke_data_collection():
    """
    Entry point for running the tournament scraping pipeline.
    No parameters; ready for Docker ENTRYPOINT execution.
    """
    parser = argparse.ArgumentParser(
        description="Run Chess Tournament Scraper with DuckDB backend."
    )

    parser.add_argument(
        "--mode",
        required=True,
        choices=["scrape", "dashboard"],
        help="Run mode: scrape or dashboard"
    )

    parser.add_argument(
        "--start-date",
        help="Start date in DD.MM.YYYY format (required for scrape mode)"
    )

    parser.add_argument(
        "--end-date",
        help="End date in DD.MM.YYYY format (required for scrape mode)"
    )

    parser.add_argument(
        "--queries",
        help="Comma-separated list of tournament queries (required for scrape mode)"
    )

    args = parser.parse_args()

    if args.mode == "dashboard":
        import os
        os.system("streamlit run dashboard.py --server.address=0.0.0.0")
        return

    if args.mode == "scrape":
        missing = []

        if not args.start_date:
            missing.append("--start-date")
        if not args.end_date:
            missing.append("--end-date")
        if not args.queries:
            missing.append("--queries")

        if missing:
            parser.error(
                f"The following arguments are required for scrape mode: {', '.join(missing)}"
            )

        queries = [q.strip() for q in args.queries.split(",") if q.strip()]

        if not queries:
            parser.error("At least one valid tournament query must be provided.")

        print("Starting chess data collection...")
        run_data_collection(args.start_date, args.end_date, queries)
        print("Data collection complete.")