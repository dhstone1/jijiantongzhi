# 2. AppLayout.vue - visibleGroups 修改
with open(r'E:\22_codex\jijiantongzhi\frontend\src\components\AppLayout.vue', 'r', encoding='utf-8') as f:
    c = f.read()

old = 'const visibleGroups = computed(() =>\n  groups.filter((group) => !group.adminOnly || store.isAdmin),\n)'
new = '''const visibleGroups = computed(() => {
  // 管理员看到全部
  if (store.isAdmin) return groups
  // 非管理员：只显示基础菜单
  return groups.filter((group) => group.label === '')
})'''
c = c.replace(old, new)

with open(r'E:\22_codex\jijiantongzhi\frontend\src\components\AppLayout.vue', 'w', encoding='utf-8') as f:
    f.write(c)
print('AppLayout.vue OK')
