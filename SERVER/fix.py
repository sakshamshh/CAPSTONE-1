f = open('server.py', 'r', encoding='utf-8')
content = f.read()
f.close()

if '/override' not in content:
    content += '''

class OverrideModel(BaseModel):
    status: str

@app.post("/override")
async def override_light(data: OverrideModel):
    message = {"status": data.status, "override": True, "traffic_lights": [], "ambulance": None}
    await manager.broadcast(message)
    return {"status": data.status}
'''
    f = open('server.py', 'w', encoding='utf-8')
    f.write(content)
    f.close()
    print('done')
else:
    print('already exists')