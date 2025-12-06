import duckdb
import pandas as pd
import streamlit as st
import altair as alt

DB_PATH = "/app/processed_data/chess_data.duckdb"


@st.cache_resource
def get_connection():
    return duckdb.connect(DB_PATH, read_only=True)


conn = get_connection()

st.set_page_config(
    page_title="Chess Data Dashboard",
    layout="wide"
)

st.title("Chess Tournament Analytics Dashboard")

# Sidebar filters
st.sidebar.header("Filters")

tournaments = conn.execute(
    "SELECT DISTINCT tournament FROM players ORDER BY tournament"
).fetchdf()["tournament"].tolist()

selected_tournament = st.sidebar.selectbox(
    "Select Tournament",
    ["All"] + tournaments
)

federations = conn.execute(
    "SELECT DISTINCT Federation FROM players WHERE Federation IS NOT NULL ORDER BY Federation"
).fetchdf()["Federation"].tolist()

selected_fed = st.sidebar.selectbox(
    "Select Federation",
    ["All"] + federations
)

# Dynamic query builder
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

# KPIs
col1, col2, col3 = st.columns(3)
col1.metric("Total Players", len(df))
col2.metric("Unique Tournaments", df["tournament"].nunique())
col3.metric("Federations", df["Federation"].nunique())

st.divider()

# Raw data view
with st.expander("Show Raw Player Table"):
    st.dataframe(df, use_container_width=True)

# Federation distribution
st.subheader("Players by Federation")

fed_dist = (
    df["Federation"]
    .value_counts()
    .reset_index()
    .rename(columns={"index": "Federation", "Federation": "Players"})
)

fed_chart = alt.Chart(fed_dist).mark_bar().encode(
    x=alt.X("Federation:N", sort="-y"),
    y="Players:Q",
    tooltip=["Federation", "Players"]
).properties(height=400)

st.altair_chart(fed_chart, use_container_width=True)

# Sex distribution
st.subheader("Gender Distribution")

sex_dist = (
    df["Sex"]
    .value_counts()
    .reset_index()
    .rename(columns={"index": "Sex", "Sex": "Players"})
)

sex_chart = alt.Chart(sex_dist).mark_arc().encode(
    theta="Players:Q",
    color="Sex:N",
    tooltip=["Sex", "Players"]
)

st.altair_chart(sex_chart, use_container_width=True)

# Title distribution
st.subheader("FIDE Title Distribution")

title_dist = (
    df["FIDE Title"]
    .fillna("None")
    .value_counts()
    .reset_index()
    .rename(columns={"index": "Title", "FIDE Title": "Players"})
)

title_chart = alt.Chart(title_dist).mark_bar().encode(
    x=alt.X("Title:N", sort="-y"),
    y="Players:Q",
    tooltip=["Title", "Players"]
).properties(height=400)

st.altair_chart(title_chart, use_container_width=True)

# Top ranked players
st.subheader("Top Ranked Players")

ranked_df = df.copy()
ranked_df["World Rank"] = pd.to_numeric(ranked_df["World Rank"], errors="coerce")
ranked_df = ranked_df.dropna(subset=["World Rank"]).sort_values("World Rank")

st.dataframe(
    ranked_df[["Name", "Federation", "World Rank", "tournament"]].head(25),
    use_container_width=True
)

st.divider()

# Tournament size analytics
st.subheader("Players per Tournament")

tournament_counts = (
    df.groupby("tournament")
    .size()
    .reset_index(name="Players")
    .sort_values("Players", ascending=False)
)

tour_chart = alt.Chart(tournament_counts).mark_bar().encode(
    x=alt.X("tournament:N", sort="-y"),
    y="Players:Q",
    tooltip=["tournament", "Players"]
).properties(height=500)

st.altair_chart(tour_chart, use_container_width=True)
