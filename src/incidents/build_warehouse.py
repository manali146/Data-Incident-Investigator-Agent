from pathlib import Path

import duckdb

DB_PATH = Path("data/warehouse.duckdb")

# Make sure the data/ folder exists (no error if it already does)
DB_PATH.parent.mkdir(exist_ok=True)

# Start from a clean slate so the script can be rerun any time
DB_PATH.unlink(missing_ok=True)

# Open (and create) the database file
con = duckdb.connect(str(DB_PATH))

# Generate TPC-H demo data (sf=0.1 is about 150k orders)
con.sql("INSTALL tpch")
con.sql("LOAD tpch")
con.sql("CALL dbgen(sf = 0.1)") # roughly 10% of the base 1 GB TPC-H dataset

# The "dashboard" metric: daily revenue per region.
# A view, so anything we break in orders shows up here automatically.
con.sql("""
    CREATE OR REPLACE VIEW daily_revenue AS
    SELECT
        o.o_orderdate       AS order_date,
        r.r_name            AS region,
        count(*)            AS n_orders,
        sum(o.o_totalprice) AS revenue
    FROM orders o
    JOIN customer c ON o.o_custkey   = c.c_custkey
    JOIN nation   n ON c.c_nationkey = n.n_nationkey
    JOIN region   r ON n.n_regionkey = r.r_regionkey
    GROUP BY order_date, region
""")

# Checks
con.sql("SHOW TABLES").show()
con.sql("""
    SELECT min(order_date) AS first_day, max(order_date) AS last_day, count(*) AS n_rows
    FROM daily_revenue
""").show()
con.sql("SELECT * FROM daily_revenue ORDER BY order_date DESC, region LIMIT 5").show()

con.close()