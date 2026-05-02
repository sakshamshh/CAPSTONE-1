f = open('server.py', 'r', encoding='utf-8')
lines = f.readlines()
f.close()
lines[851] = "          card.innerHTML = '<div class=\"amb-name\">' + (a.driver_name || a.id) + '</div><div class=\"amb-detail\">' + (a.vehicle || '') + '</div><div class=\"pending-actions\"><button class=\"btn-approve\" data-id=\"' + a.id + '\" onclick=\"approveAmb(this.dataset.id)\">Approve</button><button class=\"btn-reject\" data-id=\"' + a.id + '\" onclick=\"rejectAmb(this.dataset.id)\">Reject</button></div>';\n"
f = open('server.py', 'w', encoding='utf-8')
f.writelines(lines)
f.close()
print('done')