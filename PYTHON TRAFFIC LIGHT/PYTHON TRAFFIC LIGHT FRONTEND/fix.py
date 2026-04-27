f = open('traffic_light_frontend.py')
lines = f.readlines()
f.close()
lines[168] = '            url = f"wss://{server}/ws/traffic-light" if "onrender.com" in server else f"ws://{server}/ws/traffic-light"\n'
f = open('traffic_light_frontend.py', 'w')
f.writelines(lines)
f.close()
print('done')
