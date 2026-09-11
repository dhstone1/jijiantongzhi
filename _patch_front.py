with open(r'E:\22_codex\jijiantongzhi\frontend\src\api\index.js', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('listBots: () => http.get(\"/bots\"),', 'listBots: (mobile) => http.get(\"/bots\", { params: { mobile } }),')
c = c.replace('listDatasources: () => http.get(\"/datasources\"),', 'listDatasources: (mobile) => http.get(\"/datasources\", { params: { mobile } }),')

old = '  testBot: (id) => http.post(\"/bots/\" + id + \"/test\", {}),'
new = '''  testBot: (id) => http.post(\"/bots/\" + id + \"/test\", {}),

  // 权限
  listPermissions: (resourceType, resourceId) =>
    http.get(\"/permissions\", { params: { resource_type: resourceType, resource_id: resourceId } }),
  grantPermissions: (resourceType, resourceId, mobiles) =>
    http.post(\"/permissions\", { resource_type: resourceType, resource_id: resourceId, mobiles }),'''
c = c.replace(old, new)

with open(r'E:\22_codex\jijiantongzhi\frontend\src\api\index.js', 'w', encoding='utf-8') as f:
    f.write(c)
print('API OK')
