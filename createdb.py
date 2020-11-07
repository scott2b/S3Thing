import sqlite3

conn = sqlite3.connect('db.db')
c = conn.cursor()
c.execute('''CREATE TABLE purchases
             (key text, files text, fulfilled int)''')
conn.commit()
conn.close()
