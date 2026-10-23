from pathlib import Path
import shutil

import duckdb

SRC_PATH = Path("data/warehouse.duckdb")
CASES_DIR = Path("data/cases")
TODAY = "1998-08-02"

# Subquery: all customer keys in one region (orders has no region column)
REGION_CUSTOMERS = """
    SELECT c.c_custkey FROM customer c
    JOIN nation n ON c.c_nationkey = n.n_nationkey
    JOIN region r ON n.n_regionkey = r.r_regionkey
    WHERE r.r_name = '{region}'
"""


def make_case(name: str, sql: str) -> None:
    """Copy the clean warehouse and plant one incident in the copy."""
    dest_path = CASES_DIR / f"{name}.duckdb"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.unlink(missing_ok=True)
    shutil.copy(SRC_PATH, dest_path)

    conn = duckdb.connect(str(dest_path))
    conn.sql(sql)

    # Show the damage as the "dashboard" sees it: last 3 days, all regions
    print(f"\n=== {name} ===")
    conn.sql("""
        SELECT * FROM daily_revenue
        ORDER BY order_date DESC, region
        LIMIT 15
    """).show()
    conn.close()


# 1. missing_day: today's load never arrived
make_case("missing_day", f"""
    DELETE FROM orders WHERE o_orderdate = '{TODAY}'
""")

# 2. duplicate_load: yesterday's batch was loaded twice
make_case("duplicate_load", """
    INSERT INTO orders SELECT * FROM orders WHERE o_orderdate = '1998-08-01'
""")

# 3. null_prices: prices arrived empty for ASIA today
#    (TPC-H declares the column NOT NULL, raw tables in real life usually don't)
make_case("null_prices", f"""
    ALTER TABLE orders ALTER COLUMN o_totalprice DROP NOT NULL;
    UPDATE orders SET o_totalprice = NULL
    WHERE o_orderdate = '{TODAY}'
      AND o_custkey IN ({REGION_CUSTOMERS.format(region='ASIA')})
""")

# 4. unit_change: today's prices arrived in cents instead of dollars
make_case("unit_change", f"""
    UPDATE orders SET o_totalprice = o_totalprice * 100
    WHERE o_orderdate = '{TODAY}'
""")

# 5. real_drop (control): EUROPE genuinely loses half its orders over 7 days.
#    Line items are removed too, so the data stays consistent: not a data bug.
make_case("real_drop", f"""
    DELETE FROM orders
    WHERE o_orderdate > DATE '{TODAY}' - INTERVAL 7 DAY
      AND o_orderkey % 2 = 0
      AND o_custkey IN ({REGION_CUSTOMERS.format(region='EUROPE')});
    DELETE FROM lineitem
    WHERE l_orderkey NOT IN (SELECT o_orderkey FROM orders);
""")