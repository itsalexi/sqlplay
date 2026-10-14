CREATE TABLE customer (
    customerid int PRIMARY KEY,
    firstname varchar(20),
    lastname varchar(20),
    state char(2),
    referredby int REFERENCES customer(customerid)
);
CREATE TABLE product (
    productid int PRIMARY KEY,
    name varchar(30),
    category varchar(15),
    cost numeric(6,2),
    price numeric(6,2)
);
CREATE TABLE orders (
    orderid int PRIMARY KEY,
    customerid int REFERENCES customer(customerid),
    productid int REFERENCES product(productid),
    qty int
);
