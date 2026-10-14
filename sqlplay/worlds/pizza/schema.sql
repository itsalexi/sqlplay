CREATE TABLE customer (
    customerid  int PRIMARY KEY,
    lastname    varchar(20) NOT NULL,
    firstname   varchar(20) NOT NULL,
    address     varchar(30),
    city        varchar(20),
    state       char(2),
    zip         varchar(5),
    referredby  int REFERENCES customer(customerid)
);

CREATE TABLE supplier (
    supplierid  int PRIMARY KEY,
    suppliername varchar(25) NOT NULL,
    contact     varchar(25),
    phone       varchar(12)
);

CREATE TABLE pizza (
    pizzaid     int PRIMARY KEY,
    pizzaname   varchar(25) NOT NULL,
    launchdate  date,
    supplierid  int REFERENCES supplier(supplierid),
    cost        numeric(6,2),
    price       numeric(6,2),
    category    varchar(12),
    CHECK (price > cost)
);

CREATE TABLE orders (
    orderid        int PRIMARY KEY,
    customerid     int REFERENCES customer(customerid),
    orderdate      date NOT NULL,
    deliverydate   date,
    deliverystreet varchar(30),
    deliverycity   varchar(20),
    deliverystate  char(2),
    deliveryzip    varchar(5)
);

CREATE TABLE orderline (
    orderid   int REFERENCES orders(orderid),
    lineno    int,
    pizzaid   int REFERENCES pizza(pizzaid),
    quantity  int CHECK (quantity > 0),
    PRIMARY KEY (orderid, lineno)
);

CREATE TABLE topping (
    toppingid    int PRIMARY KEY,
    toppingname  varchar(20) NOT NULL,
    toppingtype  varchar(10)
);

CREATE TABLE pizzatopping (
    pizzaid    int REFERENCES pizza(pizzaid),
    toppingid  int REFERENCES topping(toppingid),
    PRIMARY KEY (pizzaid, toppingid)
);
