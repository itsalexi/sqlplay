from sqlplay.engine.grader import grade


def g(db, level, sql):
    return grade(db, level, sql)


def test_pass_any_style(db, level):
    lv = level("fl")
    v = g(db, lv, """SELECT customerid AS "Customer Number", firstname || ' ' || lastname AS "Customer Name"
                     FROM customer WHERE state='FL' ORDER BY 1 DESC""")
    assert v.passed, v.message


def test_wrong_order(db, level):
    v = g(db, level("fl"), """SELECT customerid AS "Customer Number", CONCAT(firstname,' ',lastname) AS "Customer Name"
                             FROM customer WHERE state='FL' ORDER BY customerid""")
    assert v.kind == "order" and "reversed" in v.tip


def test_labels(db, level):
    v = g(db, level("fl"), """SELECT customerid AS "Customer Number", CONCAT(firstname,' ',lastname)
                             FROM customer WHERE state='FL' ORDER BY customerid DESC""")
    assert v.kind == "labels" and "Customer Name" in v.message


def test_missing_filter(db, level):
    v = g(db, level("fl"), """SELECT customerid AS "Customer Number", CONCAT(firstname,' ',lastname) AS "Customer Name"
                             FROM customer ORDER BY customerid DESC""")
    assert v.kind == "rows" and "Too many" in v.message


def test_column_count(db, level):
    v = g(db, level("fl"), "SELECT customerid FROM customer WHERE state='FL'")
    assert v.kind == "columns"


def test_error_explained(db, level):
    v = g(db, level("fl"), "SELECT customer_number FROM customer")
    assert v.kind == "error" and "does not exist" in v.message and v.tip


def test_double_quote_value(db, level):
    v = g(db, level("fl"), 'SELECT customerid, firstname FROM customer WHERE state = "FL"')
    assert v.kind == "error" and "single quotes" in v.tip


def test_group_error(db, level):
    v = g(db, level("never"), "SELECT name, MAX(price) FROM product")
    assert v.kind == "error" and "subquery" in v.tip


def test_duplicates(db, level):
    v = g(db, level("never"), "SELECT p.name FROM product p, product q WHERE p.name IN ('POT','WIDGET') AND q.productid IN (10,11) AND p.productid <> 12")
    assert not v.passed


def test_left_join(db, level):
    v = g(db, level("never"), "SELECT name FROM product WHERE productid NOT IN (SELECT productid FROM orders)")
    assert v.passed
    v2 = g(db, level("never"), "SELECT p.name FROM product p JOIN orders o ON p.productid = o.productid")
    assert not v2.passed


def test_summary_row_hint(db, level, mini):
    from sqlplay.engine.levels import Level
    lv = Level(id="mini-x", world="mini", topic="aggregates", difficulty=2, question="q",
               answer="SELECT COUNT(*), MAX(price) FROM product")
    v = g(db, lv, "SELECT productid, price FROM product")
    assert "single row" in v.message


def test_no_join_no_pairing_blame(db, level, mini):
    from sqlplay.engine.levels import Level
    lv = Level(id="mini-y", world="mini", topic="select", difficulty=2, question="q",
               answer="SELECT name FROM product WHERE price > 14")
    v = g(db, lv, "SELECT category FROM product")
    assert "joined" not in v.tip
