f = open('server.py', 'r', encoding='utf-8')
content = f.read()
f.close()

content = content.replace(
    "onclick=\"approveAmb(''+a.id+'')\"",
    "onclick=\"approveAmb(`\"+a.id+\"`)\"" 
)
content = content.replace(
    "onclick=\"rejectAmb(''+a.id+'')\"",
    "onclick=\"rejectAmb(`\"+a.id+\"`)\"" 
)

f = open('server.py', 'w', encoding='utf-8')
f.write(content)
f.close()
print('done')