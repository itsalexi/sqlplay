from sqlplay.engine import sandbox


def test_select_works(db, mini):
    r = sandbox.run(db, "mini", "SELECT name FROM product ORDER BY name;")
    assert r.ok and r.rows[0] == ("GADGET",)


def test_multi_statement_rejected(db, mini):
    r = sandbox.run(db, "mini", "SELECT 1; DROP TABLE product")
    assert r.error.kind == "multi"


def test_write_rejected(db, mini):
    for sql in ["DELETE FROM product", "UPDATE product SET price = 0", "DROP TABLE product",
                "CREATE TABLE x (i int)", "INSERT INTO product VALUES (1,'a','b',1,1)"]:
        r = sandbox.run(db, "mini", sql)
        assert r.error and r.error.kind == "not_select", sql


def test_select_into_blocked(db, mini):
    r = sandbox.run(db, "mini", "SELECT * INTO stolen FROM product")
    assert not r.ok


def test_function_write_blocked(db, mini):
    r = sandbox.run(db, "mini", "SELECT nextval('x')")
    assert not r.ok


def test_cannot_read_app_schema(db, mini):
    r = sandbox.run(db, "mini", "SELECT * FROM sqlplay.levels")
    assert not r.ok and "permission denied" in r.error.message


def test_timeout(db, mini):
    r = sandbox.run(db, "mini", "SELECT pg_sleep(10)")
    assert r.error and r.error.kind == "timeout"


def test_data_unchanged(db, mini):
    r = sandbox.run(db, "mini", "SELECT count(*) FROM product")
    assert r.rows[0][0] == 4


def test_row_cap(db, mini):
    r = sandbox.run(db, "mini", "SELECT * FROM generate_series(1, 2000)")
    assert r.truncated and len(r.rows) == sandbox.ROW_LIMIT


def test_psql_error_format(db, mini):
    r = sandbox.run(db, "mini", "SELECT nope FROM product")
    text = r.error.psql_text(r.sql)
    assert text.startswith("ERROR:") and "LINE 1:" in text and "^" in text
