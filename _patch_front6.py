# 6. RuleEditView.vue - listDatasources/Bots 加 mobile, send_excel 开关
with open(r'E:\22_codex\jijiantongzhi\frontend\src\views\RuleEditView.vue', 'r', encoding='utf-8') as f:
    c = f.read()

# listDatasources/Bots 加 mobile
c = c.replace('api.listDatasources(),', 'api.listDatasources(store.user?.mobile),')
c = c.replace('api.listBots(),', 'api.listBots(store.user?.mobile),')

# 在 '状态' field 之前添加 send_excel 开关
old = '''            <div class="field">
              <label>状态</label>
              <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
            </div>'''
new = '''            <div class="field">
              <label>发送Excel</label>
              <el-switch v-model="form.send_excel" active-text="同时发送 Excel 数据文件" />
              <div class="hint">生成 .xlsx 文件并在消息中附上下载链接。</div>
            </div>
            <div class="field">
              <label>状态</label>
              <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
            </div>'''
c = c.replace(old, new)

with open(r'E:\22_codex\jijiantongzhi\frontend\src\views\RuleEditView.vue', 'w', encoding='utf-8') as f:
    f.write(c)
print('RuleEditView.vue OK')
