f = open('server.py', 'r', encoding='utf-8')
content = f.read()
f.close()

# Find and replace the navigate function
nav_start = content.find('@app.get("/navigate")')
nav_end = content.find('@app.get("/map")')

new_nav = '''@app.get("/navigate")
def navigate_page():
    html_path = Path(__file__).resolve().parent / "navigate.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), media_type="text/html")


'''

content = content[:nav_start] + new_nav + content[nav_end:]

f = open('server.py', 'w', encoding='utf-8')
f.write(content)
f.close()
print('done')

f = open('server.py', 'r', encoding='utf-8')
lines = f.readlines()
f.close()
lines[320] = ''
f = open('server.py', 'w', encoding='utf-8')
f.writelines(lines)
f.close()
print('done')
f = open('server.py', 'r', encoding='utf-8')
content = f.read()
f.close()

hq_endpoint = '''
@app.get("/hq")
def hq_page():
    html_path = Path(__file__).resolve().parent / "hq.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), media_type="text/html")

'''

# Insert before the /map endpoint
content = content.replace('@app.get("/map")', hq_endpoint + '@app.get("/map")')

f = open('server.py', 'w', encoding='utf-8')
f.write(content)
f.close()
print('done')
f = open('server.py', 'r', encoding='utf-8')
content = f.read()
f.close()

content += '''

@app.get("/hq")
def hq_page():
    html_path = Path(__file__).resolve().parent / "hq.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), media_type="text/html")


@app.get("/map")
def map_page():
    html_path = Path(__file__).resolve().parent / "map.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), media_type="text/html")
'''

f = open('server.py', 'w', encoding='utf-8')
f.write(content)
f.close()
print('done')