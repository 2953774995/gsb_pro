-- sqlq demo script
CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT, price REAL, stock INTEGER);
INSERT INTO products VALUES (1, 'book', 12.5, 10);
INSERT INTO products VALUES (2, 'book', 25.0, 3);
INSERT INTO products VALUES (3, 'pen', 2.0, 100);
INSERT INTO products VALUES (4, 'pen', NULL, 5);
INSERT INTO products VALUES (5, 'lamp', 80.0, 0);

-- WHERE + GROUP BY + HAVING + ORDER BY + LIMIT in one statement
SELECT category, COUNT(*) AS n, SUM(stock) AS total_stock, AVG(price) AS avg_price
FROM products
WHERE id > 1
GROUP BY category
HAVING COUNT(*) >= 1
ORDER BY total_stock DESC
LIMIT 2;

UPDATE products SET price = price * 0.9 WHERE category = 'book';
DELETE FROM products WHERE stock = 0;
SELECT DISTINCT category FROM products ORDER BY category ASC LIMIT 10 OFFSET 0;
