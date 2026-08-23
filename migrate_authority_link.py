"""Add users.authority_id and backfill existing authority accounts.

Idempotent: safe to re-run. Backfill matches an authority in the user's own
district, preferring a name/username overlap, else the district's first.
"""
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else 'instance/hackforge.db'
con = sqlite3.connect(DB)
cur = con.cursor()

cols = [r[1] for r in cur.execute('PRAGMA table_info(users)')]
if 'authority_id' not in cols:
    cur.execute('ALTER TABLE users ADD COLUMN authority_id INTEGER REFERENCES authorities(id)')
    print('added users.authority_id')

authorities = cur.execute('SELECT id, name, district_id FROM authorities').fetchall()
users = cur.execute(
    "SELECT id, username, district_id FROM users "
    "WHERE role IN ('authority','admin') AND authority_id IS NULL").fetchall()

for uid, username, district_id in users:
    same_district = [a for a in authorities if a[2] == district_id]
    words = {w for w in username.lower().replace('_', ' ').split() if len(w) > 3}
    match = next((a for a in same_district if words & set(a[1].lower().split())), None)
    match = match or (same_district[0] if same_district else None)
    if match:
        cur.execute('UPDATE users SET authority_id = ? WHERE id = ?', (match[0], uid))
        print('linked %s -> %s' % (username, match[1]))
    else:
        print('NO authority in district for %s (left unlinked)' % username)

con.commit()
for row in cur.execute(
        'SELECT u.username, u.role, a.name FROM users u '
        'LEFT JOIN authorities a ON a.id = u.authority_id'):
    print(row)
con.close()
