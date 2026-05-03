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


f = open('server.py', 'r', encoding='utf-8')
content = f.read()
f.close()

endpoints = '''

class RegisterModel(BaseModel):
    driver_name: str
    vehicle: Optional[str] = None


@app.post("/register")
def register_ambulance(data: RegisterModel):
    new_id = "amb-" + str(uuid.uuid4())[:6]
    new_amb = {"id": new_id, "driver_name": data.driver_name, "vehicle": data.vehicle, "status": "pending"}
    supabase.table("ambulances").insert(new_amb).execute()
    return new_amb


@app.get("/ambulances/{amb_id}")
def get_ambulance(amb_id: str):
    result = supabase.table("ambulances").select("*").eq("id", amb_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Not found")
    return result.data[0]


@app.post("/ambulances/{amb_id}/approve")
def approve_ambulance(amb_id: str):
    supabase.table("ambulances").update({"status": "idle"}).eq("id", amb_id).execute()
    return {"status": "approved"}


@app.delete("/ambulances/{amb_id}")
def delete_ambulance(amb_id: str):
    supabase.table("ambulances").delete().eq("id", amb_id).execute()
    return {"status": "deleted"}

'''

content += endpoints

f = open('server.py', 'w', encoding='utf-8')
f.write(content)
f.close()
print('done')

f = open('server.py', 'r', encoding='utf-8')
content = f.read()
f.close()

content += '''

@app.get("/trafficlight")
def trafficlight_page():
    html_path = Path(__file__).resolve().parent / "trafficlight.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), media_type="text/html")
'''

f = open('server.py', 'w', encoding='utf-8')
f.write(content)
f.close()
print('done')

f = open('server.py', 'r', encoding='utf-8')
content = f.read()
f.close()

content = content.replace(
    'Path(__file__).resolve().parent / "hq.html"',
    'Path(__file__).resolve().parent / "pages" / "hq.html"'
)
content = content.replace(
    'Path(__file__).resolve().parent / "navigate.html"',
    'Path(__file__).resolve().parent / "pages" / "navigate.html"'
)
content = content.replace(
    'Path(__file__).resolve().parent / "trafficlight.html"',
    'Path(__file__).resolve().parent / "pages" / "trafficlight.html"'
)
content = content.replace(
    'Path(__file__).resolve().parent / "map.html"',
    'Path(__file__).resolve().parent / "pages" / "map.html"'
)
content = content.replace(
    'Path(__file__).resolve().parent / "mobile_sender.html"',
    'Path(__file__).resolve().parent / "pages" / "mobile_sender.html"'
)

f = open('server.py', 'w', encoding='utf-8')
f.write(content)
f.close()
print('done')
f = open('server.py', 'r', encoding='utf-8')
content = f.read()
f.close()

content += '''

@app.get("/hq2")
def hq2_page():
    html_path = Path(__file__).resolve().parent / "pages" / "v2" / "hq_v2.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), media_type="text/html")


@app.delete("/emergencies/{emergency_id}")
def delete_emergency(emergency_id: str):
    supabase.table("emergencies").delete().eq("id", emergency_id).execute()
    return {"status": "deleted"}
'''

f = open('server.py', 'w', encoding='utf-8')
f.write(content)
f.close()
print('done')