"""
Synthetic Sales Dataset Generator
----------------------------------
Generates a realistic multi-year retail sales dataset (orders, customers,
products, regions) used to seed the Business Intelligence & Sales
Analytics System when no dataset has been uploaded yet.

Run:  python data/generate_data.py
Output: data/sales_data.csv
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import random

random.seed(42)
np.random.seed(42)

REGIONS = ["North", "South", "East", "West", "Central"]
CATEGORIES = {
    "Electronics": ["Laptop", "Smartphone", "Headphones", "Smartwatch", "Tablet", "Bluetooth Speaker"],
    "Furniture": ["Office Chair", "Study Table", "Bookshelf", "Sofa", "Bed Frame"],
    "Clothing": ["T-Shirt", "Jeans", "Jacket", "Sneakers", "Formal Shirt"],
    "Groceries": ["Rice Pack", "Cooking Oil", "Snack Box", "Beverage Pack", "Spice Set"],
    "Sports": ["Yoga Mat", "Dumbbell Set", "Cricket Bat", "Football", "Running Shoes"],
    "Beauty": ["Face Cream", "Perfume", "Hair Dryer", "Makeup Kit", "Trimmer"],
}
PAYMENT_METHODS = ["Credit Card", "Debit Card", "UPI", "Net Banking", "Cash on Delivery"]
ORDER_STATUS = ["Delivered", "Delivered", "Delivered", "Delivered", "Returned", "Cancelled"]

N_CUSTOMERS = 1200
N_ORDERS = 9000
START_DATE = datetime(2023, 1, 1)
END_DATE = datetime(2025, 12, 31)

first_names = ["Aarav","Vivaan","Aditya","Vihaan","Arjun","Sai","Reyansh","Krishna","Ishaan","Rohan",
               "Ananya","Diya","Saanvi","Aadhya","Myra","Anika","Navya","Riya","Sara","Isha",
               "Rahul","Priya","Amit","Neha","Karan","Pooja","Vikram","Sneha","Manish","Kavya"]
last_names = ["Sharma","Verma","Gupta","Singh","Kumar","Patel","Reddy","Iyer","Nair","Mehta",
              "Joshi","Chopra","Malhotra","Agarwal","Kapoor","Bhatt","Rao","Desai","Pillai","Saxena"]

def random_date(start, end):
    delta = end - start
    return start + timedelta(days=random.randint(0, delta.days))

# Build customer base with signup dates and a home region (drives some behavioral skew)
customers = []
for cid in range(1, N_CUSTOMERS + 1):
    signup = random_date(START_DATE, END_DATE - timedelta(days=30))
    customers.append({
        "customer_id": f"CUST{cid:05d}",
        "customer_name": f"{random.choice(first_names)} {random.choice(last_names)}",
        "region": random.choices(REGIONS, weights=[0.25, 0.2, 0.22, 0.18, 0.15])[0],
        "signup_date": signup,
        # latent behavior traits so segments/churn/CLV are learnable, not pure noise
        "loyalty": np.random.beta(2, 5),      # higher -> more frequent / recent buyer
        "spend_power": np.random.lognormal(mean=3.2, sigma=0.55),  # base order value multiplier
        "discount_sensitivity": np.random.beta(2, 3),
    })
cust_df = pd.DataFrame(customers)

# Build product catalog with base price & base cost (drives profit)
products = []
pid = 1
for cat, items in CATEGORIES.items():
    for item in items:
        base_price = {
            "Electronics": np.random.uniform(1500, 55000),
            "Furniture": np.random.uniform(2000, 25000),
            "Clothing": np.random.uniform(400, 4000),
            "Groceries": np.random.uniform(80, 900),
            "Sports": np.random.uniform(300, 6000),
            "Beauty": np.random.uniform(150, 3500),
        }[cat]
        margin = np.random.uniform(0.12, 0.45)
        products.append({
            "product_id": f"PRD{pid:04d}",
            "product_name": item,
            "category": cat,
            "unit_price": round(base_price, 2),
            "unit_cost": round(base_price * (1 - margin), 2),
        })
        pid += 1
prod_df = pd.DataFrame(products)

# Seasonality multipliers by month (festive Q4 boost, summer dip) - used for order date weighting
month_weight = {1: 0.9, 2: 0.85, 3: 0.95, 4: 0.9, 5: 0.85, 6: 0.8,
                7: 0.85, 8: 0.9, 9: 1.0, 10: 1.25, 11: 1.35, 12: 1.2}

def weighted_order_date():
    while True:
        d = random_date(START_DATE, END_DATE)
        if random.random() < month_weight[d.month]:
            return d

rows = []
order_id = 1
# Give higher-loyalty customers more orders (power-law-ish)
cust_weights = (cust_df["loyalty"] + 0.05).values
cust_weights = cust_weights / cust_weights.sum()

for _ in range(N_ORDERS):
    cust = cust_df.iloc[np.random.choice(len(cust_df), p=cust_weights)]
    order_date = weighted_order_date()
    if order_date < cust["signup_date"]:
        order_date = cust["signup_date"] + timedelta(days=random.randint(0, 10))

    prod = prod_df.sample(1).iloc[0]
    qty = np.random.choice([1, 1, 1, 2, 2, 3, 4], p=[0.35,0.2,0.15,0.12,0.08,0.06,0.04])

    # discount influenced by customer sensitivity + random promo events
    discount_pct = round(np.clip(np.random.beta(2, 10) * (0.6 + cust["discount_sensitivity"]), 0, 0.45), 2)

    unit_price = prod["unit_price"] * (0.9 + 0.2 * cust["spend_power"] / cust_df["spend_power"].median())
    gross = unit_price * qty
    discount_amt = gross * discount_pct
    revenue = round(gross - discount_amt, 2)
    cost = round(prod["unit_cost"] * qty, 2)
    profit = round(revenue - cost, 2)

    status = random.choices(ORDER_STATUS, weights=[0.72, 0.1, 0.05, 0.05, 0.03, 0.05])[0]
    if status in ("Returned", "Cancelled"):
        profit = round(profit - abs(profit) * 0.4, 2)  # returns/cancellations hurt profit

    rows.append({
        "order_id": f"ORD{order_id:06d}",
        "order_date": order_date.strftime("%Y-%m-%d"),
        "customer_id": cust["customer_id"],
        "customer_name": cust["customer_name"],
        "region": cust["region"],
        "product_id": prod["product_id"],
        "product_name": prod["product_name"],
        "category": prod["category"],
        "quantity": int(qty),
        "unit_price": round(unit_price, 2),
        "discount_pct": discount_pct,
        "revenue": revenue,
        "cost": cost,
        "profit": profit,
        "payment_method": random.choice(PAYMENT_METHODS),
        "order_status": status,
    })
    order_id += 1

df = pd.DataFrame(rows).sort_values("order_date").reset_index(drop=True)

# Inject a small amount of realistic messiness for the data-quality module to detect & clean
messy_idx = df.sample(frac=0.015, random_state=1).index
df.loc[messy_idx[: len(messy_idx)//3], "revenue"] = np.nan
df.loc[messy_idx[len(messy_idx)//3: 2*len(messy_idx)//3], "quantity"] = -1
dup_rows = df.sample(frac=0.005, random_state=2)
df = pd.concat([df, dup_rows], ignore_index=True)

out_path = "data/sales_data.csv"
df.to_csv(out_path, index=False)
print(f"Generated {len(df)} rows -> {out_path}")
