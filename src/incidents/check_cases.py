import duckdb
import yaml

# Run each case's evidence query against its own database
with open("src/incidents/cases.yaml") as f:
    cases = yaml.safe_load(f)

for case in cases:
    print(f"\n=== {case['id']} ===")
    con = duckdb.connect(case["db"], read_only=True)
    con.sql(case["evidence_sql"]).show()
    con.close()