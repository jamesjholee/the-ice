"""SQLite pick log."""
import sqlite3, os

DB = os.environ.get("NHL_DB", "picks.db")


def conn():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS picks (
        id INTEGER PRIMARY KEY, date TEXT, pid INTEGER, name TEXT, team TEXT, opp TEXT,
        market TEXT, line REAL, odds INTEGER, stake REAL, model_p REAL, book_p REAL,
        close_odds INTEGER, result INTEGER, pnl REAL, note TEXT)""")
    return c


def add_pick(date, pid, name, team, opp, market, line, odds, stake, model_p, book_p, note=""):
    c = conn()
    c.execute("INSERT INTO picks(date,pid,name,team,opp,market,line,odds,stake,model_p,book_p,note) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (date, pid, name, team, opp, market, line, odds, stake, model_p, book_p, note))
    c.commit(); c.close()


def ungraded(date=None):
    c = conn()
    q = "SELECT id,date,pid,name,team,opp,market,line,odds,stake,model_p,book_p FROM picks WHERE result IS NULL"
    rows = c.execute(q + (" AND date=?" if date else ""), (date,) if date else ()).fetchall()
    c.close()
    return rows


def grade(pick_id, result, pnl, close_odds=None):
    c = conn()
    c.execute("UPDATE picks SET result=?, pnl=?, close_odds=COALESCE(?, close_odds) WHERE id=?",
              (result, pnl, close_odds, pick_id))
    c.commit(); c.close()


def record():
    c = conn()
    rows = c.execute("SELECT market, COUNT(*), SUM(result), SUM(pnl), SUM(stake), AVG(model_p), AVG(book_p) "
                     "FROM picks WHERE result IS NOT NULL GROUP BY market").fetchall()
    tot = c.execute("SELECT COUNT(*), SUM(result), SUM(pnl), SUM(stake) FROM picks WHERE result IS NOT NULL").fetchone()
    c.close()
    return rows, tot
