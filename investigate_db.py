import duckdb
import pandas as pd

DB_PATH = "processed_data/chess_data.duckdb"

def explore_database():
    print(f"Opening database at: {DB_PATH}\n")

    conn = duckdb.connect(DB_PATH, read_only=True)

    # Table list
    print("=== TABLES ===")
    tables = conn.execute("SHOW TABLES").fetchall()
    print(pd.DataFrame(tables, columns=["table_name"]))

    # Row counts
    print("=== ROW COUNTS ===")
    players_count = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    tournaments_count = conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0]

    print(f"players: {players_count}")
    print(f"tournaments: {tournaments_count}")

    # Schema check
    print("=== PLAYERS TABLE SCHEMA ===")
    schema = conn.execute("DESCRIBE players").fetchdf()
    print(schema)

    # Sample rows
    print("=== SAMPLE PLAYERS ROWS (20) ===")
    sample_players = conn.execute("SELECT * FROM players LIMIT 20").fetchdf()
    print(sample_players)
    with pd.option_context('display.max_rows', None, 'display.max_columns', None):
        print(sample_players)

    # Federation diagnostics
    print("=== FEDERATION DISTRIBUTION ===")
    fed_dist = conn.execute("""
        SELECT Federation, COUNT(*) AS cnt
        FROM players
        GROUP BY Federation
        ORDER BY cnt DESC
        LIMIT 20
    """).fetchdf()
    print(fed_dist)

    # Sex diagnostics
    print("=== SEX DISTRIBUTION ===")
    sex_dist = conn.execute("""
        SELECT Sex, COUNT(*) AS cnt
        FROM players
        GROUP BY Sex
        ORDER BY cnt DESC
        LIMIT 20
    """).fetchdf()
    print(sex_dist)

    # Title diagnostics
    print("=== FIDE TITLE DISTRIBUTION ===")
    title_dist = conn.execute("""
        SELECT "FIDE Title", COUNT(*) AS cnt
        FROM players
        GROUP BY "FIDE Title"
        ORDER BY cnt DESC
        LIMIT 20
    """).fetchdf()
    print(title_dist)

    # World rank diagnostics
    print("=== WORLD RANK SAMPLE ===")
    rank_sample = conn.execute("""
        SELECT Name, Federation, "World Rank"
        FROM players
        WHERE "World Rank" IS NOT NULL
        ORDER BY CAST("World Rank" AS INTEGER)
        LIMIT 20
    """).fetchdf()
    print(rank_sample)

    conn.close()