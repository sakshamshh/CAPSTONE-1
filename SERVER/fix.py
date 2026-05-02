f = open('server.py', 'r', encoding='utf-8')
lines = f.readlines()
f.close()
lines[471] = '          div.innerHTML = \'<button class="tl-delete" onclick="deleteLight(`\'+tl.id+\'`)">Delete</button><span>\'+tl.name+\'</span><small>\'+tl.latitude.toFixed(5)+\', \'+tl.longitude.toFixed(5)+\'</small>\';\n'
f = open('server.py', 'w', encoding='utf-8')
f.writelines(lines)
f.close()
print('done')