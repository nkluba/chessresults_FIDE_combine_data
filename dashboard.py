import duckdb
import pandas as pd
import streamlit as st
import altair as alt

DB_PATH = "/app/processed_data/chess_data.duckdb"


@st.cache_resource
def get_connection():
    return duckdb.connect(DB_PATH, read_only=True)


conn = get_connection()

total_tournaments_global = conn.execute(
    "SELECT COUNT(DISTINCT tournament) FROM players"
).fetchone()[0]

st.set_page_config(
    page_title="Chess Data Dashboard",
    layout="wide"
)

st.title("Chess Tournament Analytics Dashboard")

# Sidebar filters
st.sidebar.header("Filters")

# Load available values
all_tournaments = conn.execute(
    "SELECT DISTINCT tournament FROM players ORDER BY tournament"
).fetchdf()["tournament"].dropna().tolist()

all_federations = conn.execute(
    "SELECT DISTINCT Federation FROM players WHERE Federation IS NOT NULL ORDER BY Federation"
).fetchdf()["Federation"].dropna().tolist()

selected_tournament = st.sidebar.selectbox(
    "Select Tournament",
    ["All"] + all_tournaments,
    index=0
)

selected_fed = st.sidebar.selectbox(
    "Select Federation",
    ["All"] + all_federations,
    index=0
)

# Build dynamic query safely
where_clauses = []
params = []

if selected_tournament != "All":
    where_clauses.append("tournament = ?")
    params.append(selected_tournament)

if selected_fed != "All":
    where_clauses.append("Federation = ?")
    params.append(selected_fed)

where_sql = ""
if where_clauses:
    where_sql = "WHERE " + " AND ".join(where_clauses)

query = f"""
    SELECT *
    FROM players
    {where_sql}
"""

df = conn.execute(query, params).fetchdf()

# HARD SAFETY CHECK
if df.empty:
    st.warning("No data matched the selected filters. Showing full dataset.")
    df = conn.execute("SELECT * FROM players").fetchdf()

# KPIs
col1, col2, col3 = st.columns(3)
col1.metric("Total Players (Filtered)", len(df))
col2.metric("Unique Tournaments (Total)", total_tournaments_global)
col3.metric("Federations (Filtered)", df["Federation"].nunique())

st.divider()

# Raw data view
with st.expander("Show Raw Player Table"):
    st.dataframe(df, use_container_width=True)

# Federation distribution
st.subheader("Players by Federation")

if not df.empty and "Federation" in df.columns:
    fed_dist = (
        df.groupby("Federation", dropna=False)
        .size()
        .reset_index(name="Players")
        .sort_values("Players", ascending=False)
    )

    if not fed_dist.empty:
        fed_dist["Federation"] = fed_dist["Federation"].fillna("Unknown").astype(str)
        fed_dist["Players"] = fed_dist["Players"].astype(int)

        fed_chart = (
            alt.Chart(fed_dist)
            .mark_bar()
            .encode(
                x=alt.X("Federation:N", sort="-y", title="Federation"),
                y=alt.Y("Players:Q", title="Players"),
                tooltip=[
                    alt.Tooltip("Federation:N"),
                    alt.Tooltip("Players:Q")
                ]
            )
            .properties(height=400)
        )

        st.altair_chart(fed_chart, use_container_width=True)
    else:
        st.info("No federation data available for the selected filters.")
else:
    st.info("Federation column not present in dataset.")

# Sex distribution
st.subheader("Gender Distribution")

if not df.empty and "Sex" in df.columns:
    sex_dist = (
        df.groupby("Sex", dropna=False)
        .size()
        .reset_index(name="Players")
        .sort_values("Players", ascending=False)
    )

    if not sex_dist.empty:
        sex_dist["Sex"] = sex_dist["Sex"].fillna("Unknown").astype(str)
        sex_dist["Players"] = sex_dist["Players"].astype(int)

        sex_chart = (
            alt.Chart(sex_dist)
            .mark_arc()
            .encode(
                theta=alt.Theta("Players:Q"),
                color=alt.Color("Sex:N"),
                tooltip=[
                    alt.Tooltip("Sex:N"),
                    alt.Tooltip("Players:Q")
                ]
            )
        )

        st.altair_chart(sex_chart, use_container_width=True)
    else:
        st.info("No gender data available for the selected filters.")
else:
    st.info("Sex column not present in dataset.")

# Title distribution
st.subheader("FIDE Title Distribution")

if not df.empty and "FIDE Title" in df.columns:
    title_dist = (
        df.groupby("FIDE Title", dropna=False)
        .size()
        .reset_index(name="Players")
        .sort_values("Players", ascending=False)
    )

    if not title_dist.empty:
        title_dist["Title"] = title_dist["FIDE Title"].fillna("None").astype(str)
        title_dist["Players"] = title_dist["Players"].astype(int)

        title_chart = (
            alt.Chart(title_dist)
            .mark_bar()
            .encode(
                x=alt.X("Title:N", sort="-y", title="FIDE Title"),
                y=alt.Y("Players:Q", title="Players"),
                tooltip=[
                    alt.Tooltip("Title:N"),
                    alt.Tooltip("Players:Q")
                ]
            )
            .properties(height=400)
        )

        st.altair_chart(title_chart, use_container_width=True)
    else:
        st.info("No title data available for the selected filters.")
else:
    st.info("FIDE Title column not present in dataset.")

# Top ranked players
st.subheader("Top Ranked Players")

if not df.empty and {"Name", "Federation", "World Rank", "tournament"}.issubset(df.columns):

    ranked_df = df.copy()

    ranked_df["World Rank"] = pd.to_numeric(
        ranked_df["World Rank"], errors="coerce"
    )

    ranked_df = ranked_df.dropna(subset=["World Rank"])

    if not ranked_df.empty:
        grouped = (
            ranked_df
            .groupby(["Name", "Federation"], as_index=False)
            .agg(
                Best_Rank=("World Rank", "min"),
                Tournaments=("tournament", lambda x: ", ".join(sorted(set(x))))
            )
            .sort_values("Best_Rank")
        )

        st.dataframe(
            grouped.head(25),
            use_container_width=True
        )
    else:
        st.info("No ranked players available after filtering.")
else:
    st.info("Required columns for ranking are not present in the dataset.")


st.divider()

# Tournament size analytics
st.subheader("Players per Tournament")

if not df.empty and "tournament" in df.columns:
    tournament_counts = (
        df.groupby("tournament")
        .size()
        .reset_index(name="Players")
        .sort_values("Players", ascending=False)
    )

    if not tournament_counts.empty:
        tour_chart = (
            alt.Chart(tournament_counts)
            .mark_bar()
            .encode(
                x=alt.X("tournament:N", sort="-y"),
                y=alt.Y("Players:Q"),
                tooltip=[
                    alt.Tooltip("tournament:N"),
                    alt.Tooltip("Players:Q")
                ]
            )
            .properties(height=500)
        )

        st.altair_chart(tour_chart, use_container_width=True)
    else:
        st.info("No tournament data available.")
else:
    st.info("Tournament column not present in dataset.")
