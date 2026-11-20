#!/usr/bin/env python3
"""Run the task 5 comparison in the demo database and save MySQL evidence."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


BOOK_SQL = Path(__file__).resolve().parent
PROJECT = BOOK_SQL.parents[1]
QUERY_LABELS = (
    ("name_prefix", "书名前缀", "idx_book_name"),
    ("category_price", "分类、状态和价格", "idx_book_category_status_price"),
    ("seller", "卖家学号", "idx_book_seller"),
    ("equality", "书名等值", "idx_book_name"),
    ("upper", "对书名调用 UPPER", None),
)
ACTUAL = re.compile(
    r"\(actual time=[\d.e+-]+\.\.([\d.e+-]+) rows=([\d.e+-]+) loops=(\d+)\)"
)
DISTRIBUTION_SQL = """SELECT COUNT(*) AS row_count,
       COUNT(DISTINCT seller_id) AS sellers,
       MIN(price) AS min_price, MAX(price) AS max_price,
       SUM(status = '在售') AS on_sale,
       SUM(book_name LIKE '数据库%') AS name_prefix,
       SUM(book_name = '数据库') AS name_exact,
       SUM(seller_id = '2023001') AS target_seller
FROM book;"""


def mysql(sql, *options):
    user = os.environ.get("PAGESLIP_DB_USER", "pageslip")
    password = os.environ.get("PAGESLIP_DB_PASSWORD", "pageslip-local")
    completed = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "-e", f"MYSQL_PWD={password}", "db",
            "mysql", "-u", user, "--default-character-set=utf8mb4",
            "--database=book_lab", *options,
        ],
        input=sql,
        text=True,
        capture_output=True,
        check=False,
        cwd=PROJECT,
    )
    if completed.returncode:
        raise SystemExit(completed.stderr.strip() or "MySQL command failed")
    return completed.stdout.rstrip("\n")


def batch(sql, *, header=False):
    options = ["--batch", "--raw"]
    if not header:
        options.append("--skip-column-names")
    return mysql(sql, *options)


def terminal(output, name, sql):
    (output / f"{name}.txt").write_text(
        mysql(sql, "--table", "--verbose") + "\n", encoding="utf-8"
    )


def statements():
    marker = "EXPLAIN "
    sql = [
        line.removeprefix(marker).removesuffix(";")
        for line in (BOOK_SQL / "04-queries.sql").read_text(encoding="utf-8").splitlines()
        if line.startswith("EXPLAIN SELECT ")
    ]
    return [
        {"id": name, "label": label, "index": index, "sql": statement}
        for (name, label, index), statement in zip(QUERY_LABELS, sql, strict=True)
    ]


def summarize_plan(sql, samples):
    explain_sql = f"EXPLAIN FORMAT=TRADITIONAL {sql};"
    columns, row = batch(explain_sql, header=True).splitlines()
    plan = dict(zip(columns.split("\t"), row.split("\t"), strict=True))
    analyze_sql = f"EXPLAIN ANALYZE FORMAT=TREE {sql};"
    batch(analyze_sql)
    runs = []
    for _ in range(samples):
        tree = batch(analyze_sql)
        actual = ACTUAL.findall(tree)
        if not actual:
            raise SystemExit(f"EXPLAIN ANALYZE did not return execution metrics:\n{tree}")
        root_ms, root_rows, root_loops = actual[0]
        _, leaf_rows, leaf_loops = actual[-1]
        if (root_loops, leaf_loops) != ("1", "1"):
            raise SystemExit("The single-table comparison expects one loop per iterator")
        runs.append((float(root_ms), int(float(root_rows)), int(float(leaf_rows)), tree))
    times_ms = [run[0] for run in runs]
    median_ms, returned_rows, scan_rows, tree = sorted(runs)[samples // 2]
    result = sorted(batch(sql + ";").splitlines())
    if not result or len(result) != returned_rows:
        raise SystemExit(f"Unexpected query results for {sql}")
    return {
        "type": plan["type"],
        "key": None if plan["key"] == "NULL" else plan["key"],
        "rows": int(plan["rows"]),
        "plan": plan,
        "returned_rows": returned_rows,
        "scan_rows": scan_rows,
        "analyze_tree": tree,
        "median_ms": median_ms,
        "samples_ms": times_ms,
        "result_sha256": hashlib.sha256("\n".join(result).encode("utf-8")).hexdigest(),
    }


def collect(output, samples):
    output.mkdir(parents=True, exist_ok=True)
    mysql("DROP TABLE IF EXISTS book;")
    for name in ("01-schema.sql", "02-seed.sql"):
        mysql((BOOK_SQL / name).read_text(encoding="utf-8"))

    mysql("ANALYZE TABLE book;")
    columns, row = batch(DISTRIBUTION_SQL, header=True).splitlines()
    distribution = dict(zip(columns.split("\t"), row.split("\t"), strict=True))
    for column in ("row_count", "sellers", "on_sale", "name_prefix", "name_exact", "target_seller"):
        distribution[column] = int(distribution[column])
    if distribution["row_count"] != 100_000:
        raise SystemExit("Expected 100,000 rows")
    distribution["categories"] = {
        category: int(count)
        for category, count in (
            line.split("\t") for line in batch(
                "SELECT category, COUNT(*) FROM book GROUP BY category ORDER BY category;"
            ).splitlines()
        )
    }
    terminal(output, "distribution", "SELECT VERSION();\n" + DISTRIBUTION_SQL)
    queries = statements()
    three, functions = queries[:3], queries[3:]
    plans_sql = "\n".join(f"EXPLAIN {query['sql']};" for query in three)

    terminal(output, "before", plans_sql)
    for query in three:
        query["before"] = summarize_plan(query["sql"], samples)
        terminal(output, f"{query['id']}-before", f"EXPLAIN {query['sql']};")

    terminal(output, "indexes", (BOOK_SQL / "03-indexes.sql").read_text(encoding="utf-8"))
    terminal(output, "after", plans_sql)
    for query in three:
        query["after"] = summarize_plan(query["sql"], samples)
        terminal(output, f"{query['id']}-after", f"EXPLAIN {query['sql']};")
        if query["before"]["result_sha256"] != query["after"]["result_sha256"]:
            raise SystemExit(f"Results changed after indexing: {query['id']}")

    terminal(output, "function", "\n".join(f"EXPLAIN {query['sql']};" for query in functions))
    function_check = {
        query["id"]: {**query, **summarize_plan(query["sql"], samples)}
        for query in functions
    }
    if function_check["equality"]["result_sha256"] != function_check["upper"]["result_sha256"]:
        raise SystemExit("The equality and UPPER() results differ")

    evidence = {
        "mysql_version": batch("SELECT VERSION();"),
        "row_count": distribution["row_count"],
        "distribution": distribution,
        "sample_count": samples,
        "queries": three,
        "function_check": function_check,
    }
    (output / "book.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Evidence output directory")
    parser.add_argument("--samples", type=int, default=7, help="Odd count of timed runs per query")
    args = parser.parse_args()
    if args.samples < 1 or args.samples % 2 == 0:
        parser.error("--samples must be a positive odd number")
    collect(args.output, args.samples)
    print(f"Evidence saved to {args.output.resolve()}")


if __name__ == "__main__":
    main()
