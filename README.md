# bankHuMan

A local-first personal-finance registry. Track balances and valuations for bank
accounts, investments, cash, debts, or any other financial product in a SQLite
database.

Each registry records a product, its amount, a date, currency, optional labels,
and arbitrary metadata. This makes it suitable both for current balances and
historical snapshots.

## Start

Requires Python 3.9 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m ensurepip --upgrade  # Only needed if pip is missing
pip install -e .
bankhuman
```

If the environment is based on an older Anaconda Python, use `python -m pip`
instead of invoking `pip` directly. This avoids a stale `pip.exe` launcher:

```powershell
python -m pip install -e .
```

The interactive menu creates `data/bankhuman.db` automatically. To choose a
different location:

```powershell
bankhuman --database path\to\money.db
```

## Data model

- **Product**: a financial thing you own or owe, such as “Main checking” or
  “Vanguard global ETF”. It has a type, institution, currency and optional
  metadata.
- **Registry**: a dated value for one product. Use it for a balance, portfolio
  value, or debt at a particular point in time.
- **Labels**: free-form categories such as `emergency-fund`, `retirement`, or
  `joint`.

Amounts use `Decimal`, not floating-point numbers. Negative values are allowed
for liabilities.

## Commands

Run `bankhuman --help` for command-line options. The menu supports adding and
listing products and registries, and showing a current summary by product type.

Run the test suite with:

```powershell
python -m unittest discover -s tests -v
```
