f = open('server.py', 'r')
content = f.read()
f.close()

old = """          div.innerHTML = '<button class="tl-delete" onclick="deleteLight(`'+tl.id+'`)">Delete</button><span>'+tl.name+'</span><small>'+tl.latitude.toFixed(5)+', '+tl.longitude.toFixed(5)+'</small>';<small>'+tl.latitude.toFixed(5)+', '+tl.longitude.toFixed(5)+'</small>';"""

new = """          div.innerHTML = '<button class="tl-delete" onclick="deleteLight(`'+tl.id+'`)">Delete</button><span>'+tl.name+'</span><small>'+tl.latitude.toFixed(5)+', '+tl.longitude.toFixed(5)+'</small>';"""

content = content.replace(old, new)
f = open('server.py', 'w')
f.write(content)
f.close()
print('done')
