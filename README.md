# Chess Tournament Data Pipeline

Automated data extraction pipeline for youth chess tournaments and FIDE profile enrichment per participant from chess-results.com.

The script performs browser-driven tournament search, link collection, player table extraction, and FIDE profile parsing.

---

## Pipeline Overview

1. Executes tournament search on chess-results.com using Selenium.
2. Applies tournament name filters and date range filters.
3. Collects tournament result page links.
4. Tracks processed tournament links to avoid duplicates.
5. Downloads each tournament player table via HTTP.
6. Parses player tables using BeautifulSoup.
7. Normalizes table headers and injects missing player profile links.
8. Visits each player FIDE profile page.
9. Enriches player records with FIDE metadata.
10. Persists tournament-level player datasets into CSV files.

---

## Data Collected

### Tournament-Level Player Tables
For each tournament:
- Rank
- Player name
- Federation code
- FIDE ID
- Player profile link
- All original tournament table columns

### Player Data (from FIDE profiles)
For each player:
- Federation (full country name)
- Birth year
- Sex
- FIDE title
- World rank

All data is written as structured CSV tables per tournament.

---

## Output Structure

Each search query generates:

- `<query>.csv`  
  Link tracking file with processing state.

Each processed tournament generates:

- `processed_data/<tournament_name>.csv`  
  Fully enriched tournament player dataset.

---

## Project Structure

```text
.
├── list_chess_tournaments.py
├── requirements.txt
├── Dockerfile
├── README.md
├── European Youth.csv
├── International Open.csv
├── World Youth.csv
└── processed_data/
    ├── Tournament_1.csv
    ├── Tournament_2.csv
    └── ...