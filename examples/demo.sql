-- storelens 演示脚本：建表 -> 导入 JSON -> 查询/聚合 -> 修正脏数据 -> 删除
CREATE TABLE products (sku INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL);
CREATE TABLE orders (order_id INTEGER PRIMARY KEY, store TEXT, sku INTEGER, qty INTEGER, amount REAL);
CREATE TABLE inventory (store TEXT, sku INTEGER, stock INTEGER);

.import products examples/products.json
.import orders examples/orders.json
.import inventory examples/inventory.json

-- 各门店销售汇总：WHERE + GROUP BY + HAVING + ORDER BY + LIMIT
SELECT store, COUNT(*) AS orders, SUM(amount) AS revenue, AVG(amount) AS avg_ticket
FROM orders
WHERE amount IS NOT NULL
GROUP BY store
HAVING SUM(amount) >= 10
ORDER BY revenue DESC
LIMIT 3;

-- 修正门店上报的脏数据：S03 缺金额的单据按商品价目补录
UPDATE orders SET amount = 9.9 WHERE order_id = 90007;

-- 删除库存快照中的无效行
DELETE FROM inventory WHERE stock IS NULL;

SELECT store, sku, stock FROM inventory ORDER BY store, sku LIMIT 5;
