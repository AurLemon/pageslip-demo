#!/usr/bin/env python3
"""Run the transfer and two-session isolation experiments on a dedicated MySQL lab."""

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
from queue import Empty, Queue
import shlex
import subprocess
from threading import Thread
from time import monotonic, sleep


PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_MYSQL = [
    "docker", "compose", "exec", "-T", "-e", "MYSQL_PWD=pageslip-local", "db",
    "mysql", "-u", "pageslip", "--default-character-set=utf8mb4",
]
LEVELS = ("READ UNCOMMITTED", "READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE")
BALANCE = "SELECT balance FROM account WHERE account_id = 1"
ACCOUNT_RANGE = "SELECT COUNT(*) FROM account WHERE account_id BETWEEN 9 AND 11"
RAISE_BALANCE = "UPDATE account SET balance = balance + 100 WHERE account_id = 1"
ADD_ACCOUNT = "INSERT INTO account VALUES (11, '幻读实验账户', 11000.00)"
BALANCES = """
SELECT
    MAX(CASE WHEN account_id = 1 THEN balance END),
    MAX(CASE WHEN account_id = 2 THEN balance END),
    SUM(balance)
FROM account
""".strip()
MARKER = "__pageslip_sql_finished__"


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


class MysqlError(RuntimeError):
    pass


class Session:
    def __init__(self, mysql, role, evidence):
        self.role = role
        self.evidence = evidence
        self.pending = None
        self.lines = Queue()
        self.process = subprocess.Popen(
            [*mysql, "--batch", "--raw", "--skip-column-names", "--force",
             "--unbuffered", "bank_lab"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", cwd=PROJECT,
        )
        self.reader = Thread(target=self.read_lines, daemon=True)
        self.reader.start()

    def read_lines(self):
        for line in self.process.stdout:
            self.lines.put(line.rstrip("\r\n"))
        self.lines.put(None)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        finally:
            self.reader.join(timeout=1)
            self.process.stdout.close()

    def start(self, sql):
        check(self.pending is None, f"Session {self.role} already has a pending query")
        event = {
            "session": self.role, "sql": sql, "output": [],
            "order": len(self.evidence) + 1,
        }
        self.evidence.append(event)
        self.pending = event
        self.process.stdin.write(f"{sql};\nSELECT '{MARKER}';\n")
        self.process.stdin.flush()

    def finish(self, *, error=None):
        check(self.pending is not None, f"No pending query in session {self.role}")
        event = self.pending
        deadline = monotonic() + 20
        while True:
            try:
                line = self.lines.get(timeout=max(0, deadline - monotonic()))
            except Empty as exc:
                raise RuntimeError(f"MySQL timeout for {event['sql']}") from exc
            check(line is not None, f"MySQL exited before finishing {event['sql']}")
            if line == MARKER:
                break
            event["output"].append(line)

        self.pending = None
        errors = [line for line in event["output"] if line.startswith("ERROR ")]
        if error is not None:
            check(
                len(errors) == 1 and errors[0].startswith(f"ERROR {error} "),
                f"Expected MySQL error {error} for {event['sql']}, got {errors}",
            )
            return errors[0]
        if errors:
            raise MysqlError("\n".join(errors))
        return event["output"]

    def run(self, sql, *, error=None):
        self.start(sql)
        return self.finish(error=error)

    def one(self, sql):
        rows = self.run(sql)
        check(len(rows) == 1, f"Expected one row for {sql}: {rows}")
        return rows[0]

    def begin(self, level):
        self.run(f"SET SESSION TRANSACTION ISOLATION LEVEL {level}")
        self.run("SET SESSION innodb_lock_wait_timeout = 2")
        self.run("START TRANSACTION")


def fixture_case(mysql, cases):
    with Session(mysql, "A", cases.setdefault("transfer", [])) as session:
        version = session.one("SELECT VERSION()")
        engine = session.one(
            "SELECT ENGINE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = 'bank_lab' AND TABLE_NAME = 'account'"
        )
        check(engine == "InnoDB", f"Expected InnoDB, got {engine}")
        fixtures = [
            row.split("\t") for row in session.run(
                "SELECT account_id, account_name, balance FROM account ORDER BY account_id"
            )
        ]
        check(len(fixtures) == 10, f"Expected 10 lab accounts, got {len(fixtures)}")
        before = session.one(BALANCES).split("\t")
        check(before == ["1000.00", "2000.00", "55000.00"], f"Wrong starting balances: {before}")
        session.run("CALL transfer_funds(1, 2, 500.00, 0)")
        success = session.one(BALANCES).split("\t")
        check(success == ["500.00", "2500.00", "55000.00"], f"Wrong transfer result: {success}")
        insufficient = session.run("CALL transfer_funds(1, 2, 600.00, 0)", error=1644)
        unchanged = session.one(BALANCES).split("\t")
        check("INSUFFICIENT_FUNDS" in insufficient and unchanged == success, unchanged)
        abort = session.run("CALL transfer_funds(1, 2, 100.00, 1)", error=1644)
        rolled_back = session.one(BALANCES).split("\t")
        check("LAB_ABORT_AFTER_DEBIT" in abort and rolled_back == success, rolled_back)
        reset_transfer_pair(session)
        return {
            "mysqlVersion": version, "engine": engine, "fixtures": fixtures,
            "transfer": {
                "before": before,
                "success": {"balances": success},
                "insufficient": {"error": insufficient, "balances": unchanged},
                "forcedAbort": {"error": abort, "balances": rolled_back},
            },
        }


def reset_transfer_pair(session):
    session.run("UPDATE account SET balance = account_id * 1000 WHERE account_id IN (1, 2)")


def dirty_read(writer, reader, level):
    writer.begin("REPEATABLE READ")
    writer.run(RAISE_BALANCE)
    reader.begin(level)
    wait_error = None
    if level == "SERIALIZABLE":
        wait_error = reader.run(BALANCE, error=1205)
        value = None
    else:
        value = reader.one(BALANCE)
    writer.run("ROLLBACK")
    restored = reader.one(BALANCE)
    reader.run("COMMIT")

    check(restored == "1000.00", f"Unexpected dirty-read rollback balance: {restored}")
    expected = "1100.00" if level == "READ UNCOMMITTED" else "1000.00"
    check(wait_error or value == expected, f"Unexpected dirty read in {level}: {value}")
    return {
        "observed": value == "1100.00", "value": value, "afterRollback": restored,
        "blocked": wait_error is not None, "waitError": wait_error,
    }


def twice(reader, writer, level, query, write, cleanup, initial, changed):
    reader.begin(level)
    before = reader.one(query)
    writer.begin("REPEATABLE READ")
    wait_error = None
    if level == "SERIALIZABLE":
        wait_error = writer.run(write, error=1205)
        writer.run("ROLLBACK")
    else:
        writer.run(write)
        writer.run("COMMIT")

    after = reader.one(query)
    reader.run("COMMIT")

    if wait_error:
        # The same writer can finish after the reader releases its shared lock.
        writer.run(write)
    writer.run(cleanup)

    changed_in_snapshot = level in ("READ UNCOMMITTED", "READ COMMITTED")
    expected = changed if changed_in_snapshot else initial
    check((before, after) == (initial, expected), f"Unexpected {level} reads: {before}, {after}")
    return {
        "observed": before != after, "before": before, "after": after,
        "blocked": wait_error is not None, "waitError": wait_error,
    }


def isolation_case(mysql, cases, level, kind):
    trace = cases.setdefault(f"{level}/{kind}", [])
    with Session(mysql, "A", trace) as a, Session(mysql, "B", trace) as b:
        a.one("SELECT CONNECTION_ID()")
        b.one("SELECT CONNECTION_ID()")
        if kind == "dirty":
            return dirty_read(a, b, level)
        if kind == "nonrepeatable":
            return twice(
                a, b, level, BALANCE, RAISE_BALANCE,
                "UPDATE account SET balance = 1000 WHERE account_id = 1",
                "1000.00", "1100.00",
            )
        return twice(
            a, b, level, ACCOUNT_RANGE, ADD_ACCOUNT,
            "DELETE FROM account WHERE account_id = 11", "2", "3",
        )


def lock_row(account_id):
    return f"SELECT balance FROM account WHERE account_id = {account_id} FOR UPDATE"


def wait_until_running(monitor, connection, sql):
    # A second MySQL connection confirms the first request reached the server.
    # The caller still holds the conflicting row lock while this poll runs.
    deadline = monotonic() + 2
    while monotonic() < deadline:
        for row in monitor.run("SHOW FULL PROCESSLIST"):
            fields = row.split("\t")
            if fields[0] == connection and fields[7].rstrip(";") == sql:
                return
        sleep(0.02)
    raise RuntimeError(f"MySQL did not report the pending query on connection {connection}")


def begin_pair(a, b):
    a_id = a.one("SELECT CONNECTION_ID()")
    b_id = b.one("SELECT CONNECTION_ID()")
    for session in (a, b):
        session.run("SET SESSION innodb_lock_wait_timeout = 10")
        session.run("START TRANSACTION")
    return a_id, b_id


def deadlock_case(mysql, cases):
    with ExitStack() as stack:
        trace = cases.setdefault("deadlock", [])
        a = stack.enter_context(Session(mysql, "A", trace))
        b = stack.enter_context(Session(mysql, "B", trace))
        monitor = stack.enter_context(Session(mysql, "观察", cases.setdefault("monitor deadlock", [])))
        a_id, _ = begin_pair(a, b)
        a.run("UPDATE account SET balance = balance + 10 WHERE account_id = 1")
        b.run("UPDATE account SET balance = balance + 20 WHERE account_id = 2")
        a.start(lock_row(2))
        wait_until_running(monitor, a_id, lock_row(2))
        b.start(lock_row(1))

        # Either transaction may be chosen as the victim. Keep its exact server error.
        errors = {}
        for session in (a, b):
            try:
                session.finish()
            except MysqlError as exc:
                message = str(exc)
                if not message.startswith("ERROR 1213 (40001)"):
                    raise
                errors[session.role] = message

        check(len(errors) == 1, f"Expected exactly one deadlock victim: {errors}")
        victim, message = next(iter(errors.items()))
        survivor = b if victim == "A" else a
        survivor.run("COMMIT")
        final = monitor.one(BALANCES).split("\t")[:2]
        expected = ["1000.00", "2020.00"] if victim == "A" else ["1010.00", "2000.00"]
        check(final == expected, f"Deadlock victim changed committed balances: {final}")
        reset_transfer_pair(monitor)
        return {"victim": victim, "error": message, "survivor": survivor.role, "final": final}


def fixed_order_case(mysql, cases):
    with ExitStack() as stack:
        trace = cases.setdefault("fixed order", [])
        a = stack.enter_context(Session(mysql, "A", trace))
        b = stack.enter_context(Session(mysql, "B", trace))
        monitor = stack.enter_context(Session(mysql, "观察", cases.setdefault("monitor fixed order", [])))
        _, b_id = begin_pair(a, b)
        a.run(lock_row(1))
        b.start(lock_row(1))
        wait_until_running(monitor, b_id, lock_row(1))
        a.run(lock_row(2))
        a.run("COMMIT")
        b.finish()
        b.run(lock_row(2))
        b.run("COMMIT")
        final = monitor.one(BALANCES).split("\t")[:2]
        check(final == ["1000.00", "2000.00"], f"Lock-only case changed balances: {final}")
        return {"first": "A", "second": "B", "final": final}


def export(directory, data):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bank.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    transcripts = directory / "transcripts"
    transcripts.mkdir(exist_ok=True)
    for name, trace in data["cases"].items():
        file_name = name.lower().replace(" ", "-").replace("/", "-")
        for role in dict.fromkeys(step["session"] for step in trace):
            lines = []
            for step in trace:
                if step["session"] == role:
                    lines.append(f"[{step['order']:02d}] mysql> {step['sql']};")
                    lines.extend(step["output"])
            (transcripts / f"{file_name}-{role}.txt").write_text(
                "\n".join(lines) + "\n", encoding="utf-8",
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / ".evidence" / "bank")
    parser.add_argument("--mysql-cmd", help="Override the MySQL client command")
    args = parser.parse_args()
    mysql = shlex.split(args.mysql_cmd) if args.mysql_cmd else DEFAULT_MYSQL

    with Path(__file__).with_name("01-setup.sql").open("rb") as setup:
        subprocess.run(mysql, stdin=setup, check=True, cwd=PROJECT)

    cases = {}
    data = fixture_case(mysql, cases)
    data["isolation"] = [
        {
            "level": level,
            **{
                kind: isolation_case(mysql, cases, level, kind)
                for kind in ("dirty", "nonrepeatable", "phantom")
            },
        }
        for level in LEVELS
    ]
    data["deadlock"] = deadlock_case(mysql, cases)
    data["fixedOrder"] = fixed_order_case(mysql, cases)
    data["cases"] = cases
    export(args.output, data)

    print(f"MySQL {data['mysqlVersion']} / {data['engine']}")
    print(f"Transfer balances: {data['transfer']['success']['balances']}")
    for row in data["isolation"]:
        values = [row[kind]["observed"] for kind in ("dirty", "nonrepeatable", "phantom")]
        print(f"{row['level']}: {values}")
    print(f"Deadlock victim {data['deadlock']['victim']}: {data['deadlock']['error']}")
    print(f"Evidence: {args.output.resolve()}")


if __name__ == "__main__":
    main()
