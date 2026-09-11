# 5. RulesView.vue - listBots 加 mobile
with open(r'E:\22_codex\jijiantongzhi\frontend\src\views\RulesView.vue', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('api.listBots()', 'api.listBots(store.user?.mobile)')
with open(r'E:\22_codex\jijiantongzhi\frontend\src\views\RulesView.vue', 'w', encoding='utf-8') as f:
    f.write(c)
print('RulesView.vue OK')
