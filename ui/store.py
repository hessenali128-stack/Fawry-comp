"""Accounts + wallet store (SQLite, persisted in DATA_DIR). First start seeds the existing customers (seed_customers.csv,
the same ids the model knows); every sign-up after that is appended and gets the next id."""
import csv, hashlib, hmac, os, secrets, sqlite3, threading
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent / "data")); DATA_DIR.mkdir(parents=True, exist_ok=True)
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "fawry123")  # password of the seeded (pre-existing) customers
_L = threading.Lock()
_db = sqlite3.connect(DATA_DIR / "accounts.db", check_same_thread=False); _db.row_factory = sqlite3.Row
FIRST = {"M": ["Ahmed", "Mohamed", "Mahmoud", "Omar", "Youssef", "Ali", "Hassan", "Karim", "Khaled", "Mostafa", "Tarek", "Amr"],
         "F": ["Nour", "Salma", "Mariam", "Fatma", "Hana", "Yasmin", "Aya", "Rana", "Dina", "Layla", "Heba", "Mona"]}
LAST = ["Hassan", "Ibrahim", "Salem", "Fouad", "Nasser", "Mansour", "Saleh", "Farouk", "Gamal", "Adel", "Sherif", "Zaki"]


def _h(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()


def init():
    with _L:
        _db.executescript("""CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY, name TEXT, phone TEXT, email TEXT,
          salt TEXT, pw TEXT, gov TEXT, balance REAL DEFAULT 0, has_card INT DEFAULT 0, seeded INT DEFAULT 0,
          created TEXT DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE IF NOT EXISTS tx(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, title TEXT, kind TEXT,
          amount REAL, ts TEXT DEFAULT CURRENT_TIMESTAMP);
          CREATE INDEX IF NOT EXISTS tx_u ON tx(user_id, id);""")
        if _db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            seed = Path(__file__).with_name("seed_customers.csv")
            rows = []
            if seed.exists():
                for r in csv.DictReader(open(seed, encoding="utf-8")):
                    n = int(hashlib.md5(r["user_id"].encode()).hexdigest(), 16)
                    g = "F" if r["gender"] == "F" else "M"
                    name = f"{FIRST[g][n % 12]} {LAST[(n // 12) % 12]}"
                    gov = "" if r["governorate"].lower() in ("unknown", "other", "") else r["governorate"].title()
                    rows.append((r["user_id"], name, "", "", gov, round(200 + (n // 144) % 18000 + (n % 100) / 100, 2), n % 3 == 0))
            _db.executemany("INSERT INTO users(user_id,name,phone,email,gov,balance,has_card,seeded) VALUES(?,?,?,?,?,?,?,1)",
                            [(a, b, c, d, e, f, int(g)) for a, b, c, d, e, f, g in rows]); _db.commit()


def _row(r): return dict(r) if r else None


def find(ident):
    i = ident.strip()
    with _L:
        return _row(_db.execute("SELECT * FROM users WHERE lower(user_id)=lower(?) OR (phone!='' AND phone=?) OR (email!='' AND lower(email)=lower(?))", (i, i, i)).fetchone())


def login(ident, pw):
    u = find(ident)
    if not u: return None, "No account found. Check your ID / phone / email, or create an account."
    ok = pw == DEMO_PASSWORD if u["seeded"] else hmac.compare_digest(_h(pw, u["salt"]), u["pw"])
    if not ok: return None, "Wrong password."
    if u["seeded"] and not tx(u["user_id"], 1):
        n = int(hashlib.md5(u["user_id"].encode()).hexdigest(), 16)
        for k, (t, a) in enumerate([("North Cairo Electricity", 342.0), ("Vodafone recharge", 100.0), ("Cairo Water Company", 86.5)]):
            add_tx(u["user_id"], t, "bill", -round(a + n % (k + 7), 2))
    return u, None


def signup(name, phone, email, pw):
    phone = "".join(c for c in phone if c.isdigit())
    if len(phone) < 10: return None, "Enter a valid mobile number."
    if "@" not in email: return None, "Enter a valid email."
    if len(pw) < 6: return None, "Password must be at least 6 characters."
    with _L:
        if _db.execute("SELECT 1 FROM users WHERE phone=? OR lower(email)=lower(?)", (phone, email.strip())).fetchone():
            return None, "An account with this phone or email already exists."
        nxt = max(10001, (_db.execute("SELECT MAX(CAST(SUBSTR(user_id,6) AS INT)) FROM users WHERE user_id LIKE 'CUST_%'").fetchone()[0] or 0) + 1)
        uid, salt = f"CUST_{nxt}", secrets.token_hex(8)
        _db.execute("INSERT INTO users(user_id,name,phone,email,salt,pw,gov,balance) VALUES(?,?,?,?,?,?,?,0)",
                    (uid, name.strip(), phone, email.strip().lower(), salt, _h(pw, salt), "")); _db.commit()
    return find(uid), None


def get(uid): return find(uid)


def tx(uid, n=10):
    with _L:
        return [dict(r) for r in _db.execute("SELECT * FROM tx WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, n))]


def add_tx(uid, title, kind, amount):
    """amount < 0 = money out. Refuses to overdraw. -> (ok, error)"""
    with _L:
        bal = _db.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()["balance"]
        if bal + amount < 0: return False, "Insufficient balance. Top up your wallet first."
        _db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, uid))
        _db.execute("INSERT INTO tx(user_id,title,kind,amount) VALUES(?,?,?,?)", (uid, title, kind, amount)); _db.commit()
    return True, None


def request_card(uid):
    with _L: _db.execute("UPDATE users SET has_card=1 WHERE user_id=?", (uid,)); _db.commit()


init()
