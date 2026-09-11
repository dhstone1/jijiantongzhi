<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">{{ isEdit ? '编辑推送规则' : '新建推送规则' }}</h1>
        <p class="page-sub">
          从数据表里挑字段、配条件，右侧实时看到取数结果和消息效果。全程不需要写 SQL。
        </p>
      </div>
      <div class="head-actions">
        <el-button @click="router.back()">返回</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存规则</el-button>
      </div>
    </div>

    <div class="editor">
      <div class="editor-main">
        <section v-if="!isEdit" class="panel">
          <div class="panel-head">
            <div class="panel-title">场景模板</div>
            <span class="muted">选一个最接近的，帮你把触发条件和频率先填好，之后都能改</span>
          </div>
          <div class="panel-body">
            <div class="scenario-grid">
              <button
                v-for="item in scenarios"
                :key="item.key"
                class="scenario-card"
                :class="{ active: activeScenario === item.key }"
                @click="applyScenario(item)"
              >
                <div class="scenario-icon">{{ item.icon }}</div>
                <div class="scenario-title">{{ item.title }}</div>
                <div class="scenario-desc">{{ item.desc }}</div>
              </button>
            </div>
            <div v-if="scenarioHint" class="scenario-hint">{{ scenarioHint }}</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">基本信息</div>
          </div>
          <div class="panel-body form-grid">
            <div class="field">
              <label>规则名称</label>
              <el-input v-model="form.name" placeholder="例如：移动网故障日通报" maxlength="60" />
            </div>
            <div class="field">
              <label>归属地</label>
              <el-select v-model="form.region_name" placeholder="全部归属地" clearable filterable>
                <el-option label="全部归属地（不按归属地过滤）" value="" />
                <el-option v-for="r in regions" :key="r.id" :label="r.standard_name" :value="r.standard_name" />
              </el-select>
              <div class="hint">非管理员只能看到自己归属地的规则。</div>
            </div>
            <div class="field">
              <label>发送方式</label>
              <el-radio-group v-model="form.msg_type" :disabled="form.image.enabled">
                <el-radio-button value="markdown">Markdown</el-radio-button>
                <el-radio-button value="text">纯文本</el-radio-button>
              </el-radio-group>
              <div v-if="form.image.enabled" class="hint">
                图片只能走 Markdown（钉钉限制），已经自动锁定。
              </div>
            </div>
            <div class="field">
              <label>图片发送</label>
              <el-switch v-model="form.image.enabled" active-text="以图片形式发送报表" />
              <div class="hint">把结果画成一张图发到群里，手机上不用左右滑动。</div>
            </div>
            <div class="field">
              <label>发送Excel</label>
              <el-switch v-model="form.send_excel" active-text="同时发送 Excel 数据文件" />
              <div class="hint">生成 .xlsx 文件并在消息中附上下载链接。</div>
            </div>
            <div class="field">
              <label>状态</label>
              <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">数据来源</div>
            <el-button size="small" text type="primary" @click="sampleVisible = true">
              <el-icon><Upload /></el-icon> 上传样例报表
            </el-button>
          </div>
          <div class="panel-body form-grid">
            <div class="field">
              <label>数据源</label>
              <el-select v-model="form.data_source_id" placeholder="请选择数据源" @change="onDatasourceChange">
                <el-option v-for="ds in datasources" :key="ds.id" :label="ds.name" :value="ds.id" />
              </el-select>
            </div>
            <div class="field">
              <label>数据表</label>
              <el-select
                v-model="form.table_name"
                placeholder="请选择数据表"
                filterable
                :disabled="!form.data_source_id"
                @change="onTableChange"
              >
                <el-option v-for="t in tables" :key="t.name" :value="t.name" :label="t.name">
                  <span>{{ t.name }}</span>
                  <span class="opt-tag">{{ t.kind === 'view' ? '视图' : '表' }}</span>
                </el-option>
              </el-select>
            </div>
            <div class="field span-2">
              <label>归属地字段</label>
              <el-select v-model="form.region_field" placeholder="不按归属地过滤" clearable filterable>
                <el-option label="不按归属地过滤" value="" />
                <el-option v-for="c in columns" :key="c.name" :label="c.name" :value="c.name" />
              </el-select>
              <div class="hint">
                选中后，系统会自动按当前用户归属地过滤数据，并兼容该区县的各种别名写法。
              </div>
              <el-checkbox v-model="form.query.normalize_region" :disabled="!form.region_field">
                报表里统一显示标准名（数据库里写「襄都」「桥东区」都显示为「襄都区」）
              </el-checkbox>
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">取数配置</div>
            <el-button size="small" type="primary" plain :loading="previewing" @click="runPreview">
              <el-icon><Refresh /></el-icon> 刷新预览
            </el-button>
          </div>

          <div class="panel-body">
            <div class="block">
              <div class="block-title">
                显示字段
                <span class="muted">已选 {{ form.query.select.length }} 个</span>
              </div>
              <div v-if="!columns.length" class="empty">请先选择数据表</div>
              <template v-else>
                <div class="chip-wrap">
                  <el-tag
                    v-for="(name, index) in form.query.select"
                    :key="name"
                    closable
                    class="chip"
                    @close="removeField(name)"
                  >
                    <span class="chip-index">{{ index + 1 }}</span>{{ name }}
                    <el-icon class="chip-move" @click.stop="moveField(index, -1)"><Top /></el-icon>
                    <el-icon class="chip-move" @click.stop="moveField(index, 1)"><Bottom /></el-icon>
                  </el-tag>
                  <el-select class="chip-add" placeholder="+ 添加字段" filterable @change="addField">
                    <el-option
                      v-for="c in availableColumns"
                      :key="c.name"
                      :label="c.comment ? c.name + '（' + c.comment + '）' : c.name"
                      :value="c.name"
                    />
                  </el-select>
                </div>
                <div class="hint">
                  {{
                    form.query.group_by.length
                      ? '已开启分组汇总，这里显示的即分组字段，顺序即消息里的显示顺序。'
                      : '点标签上的上下箭头可调整列顺序，顺序即消息里的显示顺序。'
                  }}
                </div>
              </template>
            </div>

            <div class="block">
              <div class="block-title">
                分组汇总
                <span class="muted">按区县 / 站点先分组，再统计条数或合计</span>
              </div>

              <div class="inline-row">
                <span class="muted">分组字段</span>
                <el-select
                  v-model="form.query.group_by"
                  multiple
                  filterable
                  collapse-tags
                  collapse-tags-tooltip
                  placeholder="不分组，逐条明细"
                  class="grow"
                  @change="onGroupByChange"
                >
                  <el-option v-for="c in columns" :key="c.name" :label="c.name" :value="c.name" />
                </el-select>
              </div>

              <div v-for="(a, i) in form.query.aggregations" :key="i" class="cond-row">
                <el-select v-model="a.func" class="cond-op" @change="onAggFuncChange(a)">
                  <el-option v-for="f in aggFuncs" :key="f.value" :label="f.label" :value="f.value" />
                </el-select>

                <template v-if="isDurationFunc(a.func)">
                  <el-select v-model="a.from" placeholder="开始时间字段" filterable class="cond-field">
                    <el-option v-for="c in columns" :key="c.name" :label="c.name" :value="c.name" />
                  </el-select>
                  <span class="muted">→</span>
                  <el-select
                    v-model="a.to"
                    placeholder="结束时间字段（未填时按当前时间算）"
                    filterable
                    clearable
                    class="cond-field"
                  >
                    <el-option v-for="c in columns" :key="c.name" :label="c.name" :value="c.name" />
                  </el-select>
                </template>
                <el-select v-else v-model="a.column" placeholder="统计字段" filterable class="cond-field">
                  <el-option v-for="c in columns" :key="c.name" :label="c.name" :value="c.name" />
                </el-select>

                <el-input v-model="a.alias" class="cond-value" placeholder="列名（留空自动生成）" />
                <el-button text type="danger" @click="form.query.aggregations.splice(i, 1)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
              <el-button size="small" text type="primary" @click="addAggregation">
                <el-icon><Plus /></el-icon> 添加汇总项
              </el-button>

              <div class="hint">
                分组字段选「区县」，汇总项选「计数 / 基站名称」，就能得到各区县故障条数；
                汇总项留空则按明细逐条发送。
              </div>
            </div>

            <div class="block">
              <div class="block-title">筛选条件</div>
              <div v-for="(f, i) in form.query.filters" :key="i" class="cond-row">
                <el-select v-model="f.column" placeholder="字段" filterable class="cond-field">
                  <el-option v-for="c in columns" :key="c.name" :label="c.name" :value="c.name" />
                </el-select>
                <el-select v-model="f.op" class="cond-op">
                  <el-option v-for="op in operators" :key="op.value" :label="op.label" :value="op.value" />
                </el-select>
                <el-input
                  v-if="!['is null', 'is not null'].includes(f.op)"
                  v-model="f.value"
                  class="cond-value"
                  :placeholder="f.op === 'in' ? '多个值用逗号分隔' : '值'"
                />
                <el-input
                  v-if="f.op === 'between'"
                  v-model="f.value2"
                  class="cond-value"
                  placeholder="结束值"
                />
                <el-button text type="danger" @click="form.query.filters.splice(i, 1)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
              <el-button size="small" text type="primary" @click="addFilter">
                <el-icon><Plus /></el-icon> 添加条件
              </el-button>
            </div>

            <div class="block">
              <div class="block-title">时间范围</div>
              <div class="inline-row">
                <el-select v-model="form.query.time_range.field" placeholder="时间字段" clearable class="cond-field">
                  <el-option v-for="c in columns" :key="c.name" :label="c.name" :value="c.name" />
                </el-select>
                <el-select v-model="form.query.time_range.type" class="cond-op">
                  <el-option v-for="t in timeRanges" :key="t.value" :label="t.label" :value="t.value" />
                </el-select>
                <el-input-number
                  v-if="['last_n_days', 'last_n_hours'].includes(form.query.time_range.type)"
                  v-model="form.query.time_range.n"
                  :min="1"
                  :max="365"
                  class="cond-num"
                />
                <span v-if="form.query.time_range.type === 'last_n_days'" class="muted">天</span>
                <span v-if="form.query.time_range.type === 'last_n_hours'" class="muted">小时</span>
              </div>
            </div>

            <div class="block">
              <div class="block-title">排序与条数</div>
              <div v-for="(o, i) in form.query.order_by" :key="i" class="cond-row">
                <el-select v-model="o.column" placeholder="排序字段" filterable class="cond-field">
                  <el-option v-for="c in columns" :key="c.name" :label="c.name" :value="c.name" />
                </el-select>
                <el-select v-model="o.direction" class="cond-op">
                  <el-option label="降序" value="desc" />
                  <el-option label="升序" value="asc" />
                </el-select>
                <el-button text type="danger" @click="form.query.order_by.splice(i, 1)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
              <div class="inline-row">
                <el-button size="small" text type="primary" @click="addOrder">
                  <el-icon><Plus /></el-icon> 添加排序
                </el-button>
                <span class="muted split">最多发送条数</span>
                <el-input-number v-model="form.query.limit" :min="1" :max="200" class="cond-num" />
              </div>
            </div>

            <div class="block">
              <div class="block-title">
                触发条件
                <span class="muted">决定什么时候才真正发出去</span>
              </div>

              <el-radio-group v-model="form.query.trigger.mode">
                <el-radio-button value="always">有数据就发送（报表）</el-radio-button>
                <el-radio-button value="threshold">满足条件才发送（告警）</el-radio-button>
              </el-radio-group>

              <template v-if="form.query.trigger.mode === 'threshold'">
                <div class="inline-row trigger-row">
                  <span class="muted">多个条件之间</span>
                  <el-radio-group v-model="form.query.trigger.logic" size="small">
                    <el-radio-button value="or">满足任一</el-radio-button>
                    <el-radio-button value="and">同时满足</el-radio-button>
                  </el-radio-group>
                </div>

                <div v-for="(c, i) in form.query.trigger.conditions" :key="i" class="cond-row trigger-row">
                  <el-select v-model="c.field" placeholder="指标" filterable class="cond-field">
                    <el-option v-for="name in outputColumns" :key="name" :label="name" :value="name" />
                  </el-select>
                  <el-select v-model="c.op" class="cond-op">
                    <el-option v-for="op in triggerOps" :key="op.value" :label="op.label" :value="op.value" />
                  </el-select>
                  <el-input v-model="c.value" class="cond-value" placeholder="阈值" />
                  <el-button text type="danger" @click="form.query.trigger.conditions.splice(i, 1)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>

                <el-button size="small" text type="primary" @click="addTriggerCondition">
                  <el-icon><Plus /></el-icon> 添加触发条件
                </el-button>

                <div class="inline-row trigger-row">
                  <span class="muted">冷却时间</span>
                  <el-input-number
                    v-model="form.query.trigger.cooldown_minutes"
                    :min="0"
                    :max="1440"
                    class="cond-num"
                  />
                  <span class="muted">分钟，防止同一条告警反复刷屏（0 = 不冷却）</span>
                </div>

                <div class="hint">
                  指标来自上面「显示字段」和「分组汇总」的结果列。比如按小区分组统计出「告警次数」，
                  这里配「告警次数 ≥ 3」，就只有达到 3 次的小区会被发出来 —— 次数触发、时长触发、
                  数量触发都是这一套。
                </div>
              </template>
            </div>

            <div class="block">
              <div class="block-title">异常高亮</div>
              <div class="inline-row">
                <el-select v-model="form.query.highlight.field" placeholder="不启用高亮" clearable filterable class="cond-field">
                  <el-option v-for="c in columns" :key="c.name" :label="c.name" :value="c.name" />
                </el-select>
                <el-select v-model="form.query.highlight.op" class="cond-op" :disabled="!form.query.highlight.field">
                  <el-option label="大于" value=">" />
                  <el-option label="大于等于" value=">=" />
                  <el-option label="小于" value="<" />
                  <el-option label="小于等于" value="<=" />
                </el-select>
                <el-input-number
                  v-model="form.query.highlight.value"
                  class="cond-num"
                  :disabled="!form.query.highlight.field"
                />
                <span class="muted">触发时该单元格在钉钉里标红</span>
              </div>
            </div>

            <div class="block">
              <div class="block-title">无数据时</div>
              <el-radio-group v-model="form.query.empty_action">
                <el-radio value="skip">跳过，不发送</el-radio>
                <el-radio value="send">照常发送（显示空表）</el-radio>
              </el-radio-group>
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">消息内容</div>
            <el-button size="small" text type="primary" @click="generateTemplate">生成模板初稿</el-button>
          </div>
          <div class="panel-body">
            <el-input
              v-model="form.template"
              type="textarea"
              :rows="7"
              :placeholder="templatePlaceholder"
            />
            <div class="tokens">
              <span class="muted">点一下插入：</span>
              <el-tag v-for="token in tokens" :key="token" class="token" @click="insertToken(token)">
                {{ token }}
              </el-tag>
            </div>
            <div class="hint">
              可用占位符：{{ help.field }} 取第一行的值、{{ help.table }} 渲染全部数据、
              {{ help.list }} 每行一条、{{ help.count }} 行数、{{ help.date }}、{{ help.time }}。
              钉钉 markdown 不支持表格，所以 {{ help.table }} 输出的是按列对齐的文本，在钉钉里显示依然整齐。
            </div>
          </div>
        </section>

        <section v-if="form.image.enabled" class="panel">
          <div class="panel-head">
            <div class="panel-title">图片设置</div>
            <span class="muted">右侧「图片效果」里能实时看到画出来的样子</span>
          </div>
          <div class="panel-body form-grid">
            <div class="field">
              <label>图片标题</label>
              <el-input v-model="form.image.title" :placeholder="form.name || '默认用规则名称'" />
            </div>
            <div class="field">
              <label>副标题</label>
              <el-input v-model="form.image.subtitle" placeholder="默认：共 N 条 · 生成时间" />
            </div>
            <div class="field">
              <label>最多显示行数</label>
              <el-input-number v-model="form.image.max_rows" :min="1" :max="100" />
              <div class="hint">超出的行不会出现在图片里，只影响图片，不影响消息正文。</div>
            </div>
            <div class="field">
              <label>图片之外</label>
              <el-checkbox v-model="form.image.with_text">附带标题和说明（不含数据表）</el-checkbox>
              <div class="hint">
                图片里已经有表格了，文字部分只发标题和说明，不会再把数据表重复发一遍。
                不勾选就是「标题 + 一张图」。
              </div>
            </div>
            <div v-if="!imageReady" class="field span-2">
              <el-alert
                type="warning"
                :closable="false"
                show-icon
                title="图片推送还没配置好"
                description="没配置之前，图片规则会自动退回文字消息发送。请到「系统设置 → 图片推送」里选好图片存到哪里（本系统服务器 / 第三方图床）。"
              />
            </div>
            <div v-else class="field span-2 hint">
              图片将通过「{{ imageModeLabel }}」生成链接发给钉钉。
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">发送目标与频率</div>
          </div>
          <div class="panel-body">
            <div class="block">
              <div class="block-title">钉钉群</div>
              <el-select v-model="form.bot_ids" multiple placeholder="请选择发送到的钉钉群" style="width: 100%">
                <el-option v-for="bot in bots" :key="bot.id" :label="bot.name" :value="bot.id" />
              </el-select>
              <div v-if="!bots.length" class="hint">
                还没有配置钉钉群，请先到「钉钉群」页面添加 Webhook。
              </div>
            </div>

            <div class="block">
              <div class="block-title">@ 人员</div>
              <el-radio-group v-model="form.at_config.mode" class="at-modes">
                <el-radio-button value="none">不 @</el-radio-button>
                <el-radio-button value="fixed">固定 @</el-radio-button>
                <el-radio-button value="region">按归属地 @ 负责人</el-radio-button>
                <el-radio-button value="field">按数据字段 @</el-radio-button>
              </el-radio-group>

              <div v-if="form.at_config.mode === 'fixed'" class="at-config">
                <el-select v-model="form.at_config.mobiles" multiple filterable placeholder="选择要 @ 的人员" style="width: 100%">
                  <el-option
                    v-for="s in staff"
                    :key="s.id"
                    :label="s.name + ' · ' + s.mobile + ' · ' + (s.region_name || '全区')"
                    :value="s.mobile"
                  />
                </el-select>
              </div>

              <div v-if="form.at_config.mode === 'region'" class="at-config">
                <div class="inline-row">
                  <span class="muted">按</span>
                  <el-select v-model="form.at_config.field" placeholder="归属地字段" filterable class="cond-field">
                    <el-option v-for="c in columns" :key="c.name" :label="c.name" :value="c.name" />
                  </el-select>
                  <span class="muted">的取值，@ 对应归属地的负责人</span>
                </div>
              </div>

              <div v-if="form.at_config.mode === 'field'" class="at-config">
                <div class="inline-row">
                  <span class="muted">按</span>
                  <el-select v-model="form.at_config.field" placeholder="人员姓名字段" filterable class="cond-field">
                    <el-option v-for="c in columns" :key="c.name" :label="c.name" :value="c.name" />
                  </el-select>
                  <span class="muted">的取值匹配人员姓名后 @ 他</span>
                </div>
              </div>

              <div v-if="form.at_config.mode !== 'none'" class="at-config">
                <el-checkbox v-model="form.at_config.at_all">同时 @ 所有人</el-checkbox>
                <div class="inline-row cond-condition">
                  <el-checkbox v-model="conditionEnabled">仅在满足条件时 @</el-checkbox>
                  <template v-if="conditionEnabled">
                    <el-select v-model="form.at_config.condition.field" placeholder="字段" filterable class="cond-field">
                      <el-option v-for="c in columns" :key="c.name" :label="c.name" :value="c.name" />
                    </el-select>
                    <el-select v-model="form.at_config.condition.op" class="cond-op">
                      <el-option label="大于" value=">" />
                      <el-option label="大于等于" value=">=" />
                      <el-option label="小于" value="<" />
                      <el-option label="小于等于" value="<=" />
                      <el-option label="等于" value="=" />
                    </el-select>
                    <el-input-number v-model="form.at_config.condition.value" class="cond-num" />
                  </template>
                </div>
              </div>
            </div>

            <div class="block">
              <div class="block-title">发送频率</div>
              <el-radio-group v-model="form.schedule_type">
                <el-radio-button value="manual">仅手动</el-radio-button>
                <el-radio-button value="hourly">每小时</el-radio-button>
                <el-radio-button value="daily">每天</el-radio-button>
                <el-radio-button value="weekly">每周</el-radio-button>
              </el-radio-group>

              <div v-if="form.schedule_type === 'hourly'" class="at-config">
                <div class="inline-row">
                  <span class="muted">每</span>
                  <el-input-number v-model="form.schedule.interval_hours" :min="1" :max="24" class="cond-num" />
                  <span class="muted">小时执行一次（小时级准实时）</span>
                </div>
              </div>

              <div v-if="form.schedule_type === 'daily'" class="at-config">
                <div class="inline-row">
                  <span class="muted">每天</span>
                  <el-time-select v-model="dailyTime" start="00:00" step="00:05" end="23:55" style="width: 140px" />
                  <span class="muted">执行</span>
                </div>
              </div>

              <div v-if="form.schedule_type === 'weekly'" class="at-config">
                <div class="inline-row">
                  <span class="muted">每周</span>
                  <el-select v-model="form.schedule.day_of_week" style="width: 100px">
                    <el-option v-for="d in weekDays" :key="d.value" :label="d.label" :value="d.value" />
                  </el-select>
                  <el-time-select v-model="dailyTime" start="00:00" step="00:05" end="23:55" style="width: 140px" />
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
      <aside class="editor-side">
        <div class="preview-card">
          <div class="preview-head">
            <span>数据预览</span>
            <span class="muted">
              <template v-if="preview.trigger && preview.trigger.mode === 'threshold'">
                命中 {{ preview.trigger.hit_count }} / {{ preview.trigger.total }} 行
              </template>
              <template v-else>{{ preview.row_count ?? '—' }} 行</template>
            </span>
          </div>
          <div class="preview-body">
            <div v-if="previewError" class="preview-error">{{ previewError }}</div>
            <template v-else-if="preview.columns && preview.columns.length">
              <div
                v-if="preview.trigger && preview.trigger.mode === 'threshold'"
                class="trigger-banner"
                :class="preview.trigger.hit ? 'ok' : 'bad'"
              >
                {{ preview.trigger.hit ? '本次将发送命中的行：' : '当前无命中，本次不会发送：' }}
                {{ preview.trigger.summary }}
              </div>
              <el-table
                :data="preview.rows"
                size="small"
                border
                max-height="260"
                style="width: 100%"
                :row-class-name="previewRowClass"
              >
                <el-table-column
                  v-for="col in preview.columns"
                  :key="col"
                  :prop="col"
                  :label="col"
                  min-width="110"
                  show-overflow-tooltip
                />
              </el-table>
            </template>
            <div v-else class="empty">点「刷新预览」查看取数结果</div>
          </div>
        </div>

        <div v-if="preview.warnings && preview.warnings.length" class="preview-card">
          <div class="preview-head"><span>提示</span></div>
          <div class="preview-body">
            <div v-for="(msg, i) in preview.warnings" :key="i" class="warn-line">· {{ msg }}</div>
          </div>
        </div>

        <div v-if="form.image.enabled" class="preview-card">
          <div class="preview-head">
            <span>图片效果</span>
            <span class="muted">{{ preview.image_path ? '钉钉里看到的就是这张' : '刷新预览后生成' }}</span>
          </div>
          <div class="preview-body">
            <img v-if="preview.image_path" class="report-image" :src="preview.image_path" alt="报表图片预览" />
            <div v-else class="empty">点「刷新预览」生成图片</div>
          </div>
        </div>

        <div class="preview-card">
          <div class="preview-head"><span>钉钉消息效果</span></div>
          <div class="preview-body">
            <pre v-if="preview.rendered" class="message-preview">{{ preview.rendered }}</pre>
            <div v-else class="empty">填写模板后刷新预览</div>
          </div>
        </div>

        <div class="preview-card">
          <div class="preview-head"><span>生成的 SQL</span></div>
          <div class="preview-body">
            <pre class="message-preview sql">{{ preview.sql || '—' }}</pre>
          </div>
        </div>
      </aside>
    </div>

    <el-dialog v-model="sampleVisible" title="上传样例报表" width="720px">
      <div class="hint" style="margin-bottom: 14px">
        上传一份「你希望推送出去长什么样」的 Excel / CSV。系统把它当作样式参考，
        用来推荐字段并生成模板初稿，<strong>不会从中取数</strong>。
      </div>
      <el-upload
        drag
        :auto-upload="false"
        :show-file-list="false"
        accept=".xlsx,.xlsm,.csv"
        :on-change="handleSampleUpload"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">把文件拖到这里，或<em>点击选择</em></div>
      </el-upload>

      <div v-if="sampleResult" class="sample-result">
        <div class="sample-line">
          解析到 <strong>{{ sampleResult.sheet_count }}</strong> 个 Sheet
        </div>
        <div v-for="sheet in sampleResult.sheets" :key="sheet.name" class="sample-sheet">
          <div class="sample-sheet-head">
            <strong>{{ sheet.name }}</strong>
            <span class="muted">
              表头第 {{ sheet.header_row }} 行 · {{ sheet.row_count }} 行数据 ·
              归属地列「{{ sheet.region_column || '未识别' }}」
            </span>
          </div>
          <div v-if="sheet.summary_row_count" class="hint">
            识别到 {{ sheet.summary_row_count }} 行汇总行（{{ sheet.summary_rows.map((r) => r.label).join('、') }}），已自动排除
          </div>
          <div v-if="sheet.unknown_regions && sheet.unknown_regions.length" class="hint warn-text">
            未识别的归属地：{{ sheet.unknown_regions.join('、') }} —— 建议补进归属地字典的别名
          </div>
          <div class="column-chips">
            <el-tag v-for="c in sheet.columns.filter((x) => !x.is_empty)" :key="c.index" size="small" class="col-chip">
              {{ c.name }}
            </el-tag>
          </div>
        </div>

        <template v-if="sampleResult.recommendations && sampleResult.recommendations.length">
          <el-divider content-position="left">字段推荐</el-divider>
          <div v-for="rec in sampleResult.recommendations" :key="rec.sheet" class="sample-sheet">
            <div class="sample-sheet-head">
              <strong>{{ rec.sheet }}</strong>
              <span class="muted">建议数据表：{{ rec.suggested_table || '未匹配到' }}</span>
            </div>
            <div class="match-list">
              <div
                v-for="m in rec.column_matches.filter((x) => x.recommended)"
                :key="m.sample_column"
                class="match-item"
              >
                <span class="match-from">{{ m.sample_column }}</span>
                <el-icon><Right /></el-icon>
                <span class="match-to">{{ m.db_column }}</span>
                <span class="match-score">{{ Math.round(m.score * 100) }}%</span>
              </div>
              <div v-if="!rec.column_matches.filter((x) => x.recommended).length" class="hint">
                暂无匹配，请先在左侧选好数据表和归属地字段。
              </div>
            </div>
            <el-button
              v-if="rec.suggested_table"
              size="small"
              type="primary"
              plain
              @click="applyRecommendation(rec)"
            >
              应用推荐
            </el-button>
          </div>
        </template>
      </div>

      <template #footer>
        <el-button @click="sampleVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { useUserStore } from '../stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const isEdit = computed(() => !!route.params.id)

const datasources = ref([])
const tables = ref([])
const columns = ref([])
const regions = ref([])
const bots = ref([])
const staff = ref([])

const saving = ref(false)
const previewing = ref(false)
const previewError = ref('')
const sampleVisible = ref(false)
const sampleResult = ref(null)
const conditionEnabled = ref(false)

const preview = reactive({
  columns: [],
  rows: [],
  row_count: null,
  hit_count: null,
  hit_indexes: [],
  trigger: null,
  rendered: '',
  image_path: '',
  sql: '',
  warnings: [],
})

// 图片没配置好的话，图片规则会自动退回文字，这里提前提示
const imageReady = ref(true)
const imageModeLabel = ref('')

const activeScenario = ref('')
const scenarioHint = ref('')

const aggFuncs = [
  { label: '计数', value: 'count' },
  { label: '求和', value: 'sum' },
  { label: '平均', value: 'avg' },
  { label: '最大', value: 'max' },
  { label: '最小', value: 'min' },
  { label: '最长时长', value: 'duration_max' },
  { label: '平均时长', value: 'duration_avg' },
  { label: '最短时长', value: 'duration_min' },
]

// 触发条件可用的比较符
const triggerOps = [
  { label: '大于等于', value: '>=' },
  { label: '大于', value: '>' },
  { label: '小于等于', value: '<=' },
  { label: '小于', value: '<' },
  { label: '等于', value: '=' },
  { label: '不等于', value: '!=' },
  { label: '包含', value: 'contains' },
]

// 场景模板：把常见诉求预置好，用户选完再微调
const scenarios = [
  {
    key: 'report',
    icon: '📊',
    title: '统计报表',
    desc: '按区县 / 网格 / 个人分组统计，定期把整张结果发出来。日报、周报、月报都用它。',
    hint: '下一步：选数据表 → 在「分组汇总」里选分组字段和统计项 → 想按小时出数就把「时间范围」设成最近 N 小时。',
    trigger: { mode: 'always', logic: 'or', conditions: [], cooldown_minutes: 0 },
    schedule_type: 'daily',
    template: '',
  },
  {
    key: 'count',
    icon: '🔔',
    title: '次数触发',
    desc: '同一个对象在一段时间内发生 N 次才提醒，例如同一个小区退服 ≥ 3 次。',
    hint: '下一步：分组字段选对象（小区 / 基站）→ 加一个「计数」统计项 → 在「触发条件」里把指标指向它、阈值填成你要的次数。',
    trigger: {
      mode: 'threshold',
      logic: 'or',
      conditions: [{ field: '', op: '>=', value: 3 }],
      cooldown_minutes: 120,
    },
    schedule_type: 'hourly',
    template: '#### 次数超限告警\n\n> 同一对象在一段时间内累计次数达到阈值\n\n{{表格}}\n\n共 {{行数}} 条',
  },
  {
    key: 'duration',
    icon: '⏱',
    title: '时长触发',
    desc: '问题持续超过 N 分钟还没解决才提醒。还没恢复的按当前时间算，所以"一直没好"会一直被盯着。',
    hint: '下一步：分组字段选对象 → 加一个「最长时长」统计项，开始时间选「发生时间」、结束时间选「清除时间」→ 触发条件填分钟数。',
    trigger: {
      mode: 'threshold',
      logic: 'or',
      conditions: [{ field: '', op: '>=', value: 240 }],
      cooldown_minutes: 60,
    },
    schedule_type: 'hourly',
    template: '#### 超时未恢复告警\n\n> 持续时长已超过阈值，请尽快处理\n\n{{表格}}\n\n共 {{行数}} 条',
  },
  {
    key: 'volume',
    icon: '📈',
    title: '数量触发',
    desc: '某个区域在一段时间内问题数量超过 N 个才提醒。',
    hint: '下一步：分组字段选「区县」→ 加一个「计数」统计项 → 触发条件里填数量阈值。',
    trigger: {
      mode: 'threshold',
      logic: 'or',
      conditions: [{ field: '', op: '>=', value: 10 }],
      cooldown_minutes: 60,
    },
    schedule_type: 'hourly',
    template: '#### 区域问题量告警\n\n> 该区域内问题数量已超过阈值\n\n{{表格}}\n\n共 {{行数}} 条',
  },
]

const operators = [
  { label: '等于', value: '=' },
  { label: '不等于', value: '!=' },
  { label: '大于', value: '>' },
  { label: '大于等于', value: '>=' },
  { label: '小于', value: '<' },
  { label: '小于等于', value: '<=' },
  { label: '包含', value: 'like' },
  { label: '不包含', value: 'not like' },
  { label: '属于', value: 'in' },
  { label: '不属于', value: 'not in' },
  { label: '区间', value: 'between' },
  { label: '为空', value: 'is null' },
  { label: '不为空', value: 'is not null' },
]

const timeRanges = [
  { label: '不限时间', value: 'none' },
  { label: '今天', value: 'today' },
  { label: '昨天', value: 'yesterday' },
  { label: '最近 N 天', value: 'last_n_days' },
  { label: '最近 N 小时', value: 'last_n_hours' },
  { label: '本周', value: 'this_week' },
  { label: '本月', value: 'this_month' },
]

const weekDays = [
  { label: '周一', value: 'mon' },
  { label: '周二', value: 'tue' },
  { label: '周三', value: 'wed' },
  { label: '周四', value: 'thu' },
  { label: '周五', value: 'fri' },
  { label: '周六', value: 'sat' },
  { label: '周日', value: 'sun' },
]

const tokens = ['{{表格}}', '{{列表}}', '{{行数}}', '{{日期}}', '{{时间}}', '{{#each}}', '{{/each}}']

// 花括号占位符不能直接写在模板语法的表达式里，统一用常量引用
const help = {
  field: '{{字段名}}',
  table: '{{表格}}',
  list: '{{列表}}',
  count: '{{行数}}',
  date: '{{日期}}',
  time: '{{时间}}',
}
const templatePlaceholder = '#### 标题\n{{表格}}\n\n共 {{行数}} 条'

function emptyQuery() {
  return {
    mode: 'builder',
    table: '',
    select: [],
    filters: [],
    group_by: [],
    aggregations: [],
    order_by: [],
    time_range: { type: 'none', field: '', n: 1 },
    normalize_region: true,
    limit: 50,
    empty_action: 'skip',
    highlight: { field: '', op: '>', value: 0 },
    trigger: { mode: 'always', logic: 'or', conditions: [], cooldown_minutes: 0 },
  }
}

const form = reactive({
  name: '',
  region_name: '',
  data_source_id: null,
  table_name: '',
  query: emptyQuery(),
  region_field: '',
  time_field: '',
  template: '',
  msg_type: 'markdown',
  image: { enabled: false, title: '', subtitle: '', max_rows: 30, with_text: true },
  bot_ids: [],
  at_config: {
    mode: 'none',
    mobiles: [],
    field: '',
    at_all: false,
    condition: { field: '', op: '>', value: 0 },
  },
  schedule_type: 'manual',
  schedule: { interval_hours: 1, hour: 8, minute: 30, day_of_week: 'mon' },
  enabled: true,
  sample: {},
})

const dailyTime = computed({
  get() {
    const h = String(form.schedule.hour ?? 8).padStart(2, '0')
    const m = String(form.schedule.minute ?? 30).padStart(2, '0')
    return h + ':' + m
  },
  set(value) {
    if (!value) return
    const parts = value.split(':')
    form.schedule.hour = Number(parts[0])
    form.schedule.minute = Number(parts[1])
  },
})

const availableColumns = computed(() =>
  columns.value.filter((c) => !form.query.select.includes(c.name)),
)

function isDurationFunc(func) {
  return String(func || '').toLowerCase().startsWith('duration_')
}

// 与后端 _agg_alias 保持一致，否则触发条件里选不到指标
function aggAlias(agg) {
  if (agg.alias) return agg.alias
  const func = String(agg.func || 'sum').toLowerCase()
  if (func.startsWith('duration_')) return '时长_' + func.split('_')[1]
  return func + '_' + (agg.column || '')
}

// 触发条件能选的指标 = 显示字段 + 汇总项别名
const outputColumns = computed(() => {
  const names = [...form.query.select]
  for (const agg of form.query.aggregations) {
    if (!agg.column && !isDurationFunc(agg.func)) continue
    const alias = aggAlias(agg)
    if (alias && !names.includes(alias)) names.push(alias)
  }
  return names
})

const hitIndexSet = computed(() => new Set(preview.hit_indexes || []))

function previewRowClass({ rowIndex }) {
  if (!preview.trigger || preview.trigger.mode !== 'threshold') return ''
  return hitIndexSet.value.has(rowIndex) ? 'row-hit' : 'row-miss'
}

// 归属地列名候选，按优先级排列（越靠前越可能是「区县」这一级）
const REGION_COLUMN_HINTS = ['区县', '归属地', '地市', '城市', '单位', '区域', '分公司', '区局', '县分']

function guessRegionField(names) {
  for (const hint of REGION_COLUMN_HINTS) {
    const hit = names.find((name) => name === hint || name.includes(hint))
    if (hit) return hit
  }
  return ''
}

function guessTimeColumns() {
  const names = columns.value.map((c) => c.name)
  const pick = (keys) => names.find((name) => keys.some((k) => name.toLowerCase().includes(k))) || ''
  return {
    from: pick(['发生', '开始', 'start', 'begin', 'create', '起']),
    to: pick(['清除', '结束', '恢复', 'end', 'finish', 'resolve', '止']),
  }
}

function onAggFuncChange(agg) {
  if (!isDurationFunc(agg.func)) {
    delete agg.from
    delete agg.to
    return
  }
  const guessed = guessTimeColumns()
  if (!agg.from) agg.from = guessed.from
  if (!agg.to) agg.to = guessed.to
  if (!agg.alias) agg.alias = agg.func === 'duration_avg' ? '平均时长' : '最长时长'
  delete agg.column
}

function addTriggerCondition() {
  form.query.trigger.conditions.push({ field: '', op: '>=', value: '' })
}

function applyScenario(item) {
  activeScenario.value = item.key
  scenarioHint.value = item.hint
  form.query.trigger = {
    mode: item.trigger.mode,
    logic: item.trigger.logic,
    conditions: item.trigger.conditions.map((c) => ({ ...c })),
    cooldown_minutes: item.trigger.cooldown_minutes,
  }
  form.schedule_type = item.schedule_type
  if (item.template && !form.template) form.template = item.template
}

onMounted(async () => {
  const [ds, rg, bt, st, settings] = await Promise.all([
    api.listDatasources(store.user?.mobile),
    api.listRegions(),
    api.listBots(store.user?.mobile),
    api.listStaff(),
    api.getSettings().catch(() => ({})),
  ])
  datasources.value = ds
  regions.value = rg
  bots.value = bt
  staff.value = st
  imageReady.value = settings ? settings.image_ready !== false : true
  imageModeLabel.value =
    settings?.image_upload_mode === 'beeimg' ? '第三方图床' : '本系统服务器'

  if (isEdit.value) {
    await loadRule(Number(route.params.id))
  } else {
    form.region_name = store.isAdmin ? '' : store.user?.region_name || ''
    if (ds.length) {
      form.data_source_id = ds[0].id
      await onDatasourceChange(ds[0].id)
    }
  }
})

async function loadRule(id) {
  const rule = await api.getRule(id)
  form.name = rule.name
  form.region_name = rule.region_name
  form.data_source_id = rule.data_source_id
  form.table_name = rule.table_name
  form.query = { ...emptyQuery(), ...(rule.query || {}) }
  form.query.table = rule.table_name
  if (!form.query.highlight) form.query.highlight = { field: '', op: '>', value: 0 }
  form.query.trigger = {
    mode: 'always',
    logic: 'or',
    conditions: [],
    cooldown_minutes: 0,
    ...(form.query.trigger || {}),
  }
  if (!Array.isArray(form.query.trigger.conditions)) form.query.trigger.conditions = []
  form.region_field = rule.region_field || ''
  form.time_field = rule.time_field || ''
  form.template = rule.template
  form.msg_type = rule.msg_type
  form.image = {
    enabled: false,
    title: '',
    subtitle: '',
    max_rows: 30,
    with_text: true,
    ...(rule.image || {}),
  }
  form.bot_ids = rule.bot_ids || []
  form.at_config = {
    mode: 'none',
    mobiles: [],
    field: '',
    at_all: false,
    condition: { field: '', op: '>', value: 0 },
    ...(rule.at_config || {}),
  }
  if (!form.at_config.condition) {
    form.at_config.condition = { field: '', op: '>', value: 0 }
  }
  conditionEnabled.value = !!form.at_config.condition.field
  form.schedule_type = rule.schedule_type
  form.schedule = { ...form.schedule, ...(rule.schedule || {}) }
  form.enabled = rule.enabled

  if (form.data_source_id) {
    await onDatasourceChange(form.data_source_id, form.table_name)
  }
  runPreview()
}

async function onDatasourceChange(id, keepTable) {
  columns.value = []
  if (!id) return
  tables.value = await api.listTables(id)
  const target = keepTable || form.table_name
  if (target && tables.value.some((t) => t.name === target)) {
    form.table_name = target
    await onTableChange(target)
  }
}

async function onTableChange(table) {
  form.query.table = table
  if (!table || !form.data_source_id) return
  columns.value = await api.listColumns(form.data_source_id, table)
  form.query.select = form.query.select.filter((name) => columns.value.some((c) => c.name === name))
  if (!form.query.select.length) {
    form.query.select = columns.value.slice(0, 6).map((c) => c.name)
  }
  // 归属地字段决定权限过滤和别名归一，没选过就自动认一个，避免用户漏配
  if (!form.region_field) {
    const guessed = guessRegionField(columns.value.map((c) => c.name))
    if (guessed) form.region_field = guessed
  }
}

function addField(name) {
  if (!name || form.query.select.includes(name)) return
  form.query.select.push(name)
  if (form.query.group_by.length && !form.query.group_by.includes(name)) {
    form.query.group_by.push(name)
  }
}

function removeField(name) {
  form.query.select = form.query.select.filter((item) => item !== name)
  form.query.group_by = form.query.group_by.filter((item) => item !== name)
}

function moveField(index, offset) {
  const target = index + offset
  const list = form.query.select
  if (target < 0 || target >= list.length) return
  const tmp = list[index]
  list[index] = list[target]
  list[target] = tmp
  if (form.query.group_by.length) {
    const grouped = new Set(form.query.group_by)
    form.query.group_by = list.filter((name) => grouped.has(name))
  }
}

function addFilter() {
  form.query.filters.push({ column: '', op: '=', value: '', logic: 'and' })
}

let selectBackup = null

function addAggregation() {
  form.query.aggregations.push({ func: 'count', column: '', alias: '' })
}

// 分组字段就是显示字段：两者保持一致，SQL 才不会出现非分组列
function onGroupByChange(value) {
  const groups = [...(value || [])]
  if (groups.length) {
    if (selectBackup === null) selectBackup = [...form.query.select]
    form.query.select = groups
  } else if (selectBackup !== null) {
    form.query.select = selectBackup.filter((name) => columns.value.some((c) => c.name === name))
    selectBackup = null
  }
}

function addOrder() {
  form.query.order_by.push({ column: '', direction: 'desc' })
}

function insertToken(token) {
  form.template = (form.template || '') + token
}

watch(
  () => form.image.enabled,
  (value) => {
    if (value) form.msg_type = 'markdown'
  },
  { immediate: true },
)

async function generateTemplate() {
  const result = await api.suggestTemplate({
    title: form.name || '数据通报',
    columns: form.query.select,
    time_field: form.query.time_range.field || '',
  })
  form.template = result.template
}

async function runPreview() {
  const hasOutput = form.query.select.length || form.query.aggregations.length
  if (!form.data_source_id || !form.table_name || !hasOutput) {
    previewError.value = '请先选择数据源、数据表，并至少选一个字段或汇总项'
    return
  }
  previewing.value = true
  previewError.value = ''
  try {
    const result = await api.previewRule({
      data_source_id: form.data_source_id,
      query: {
        ...form.query,
        table: form.table_name,
        limit: form.query.limit,
        highlight: form.query.highlight.field ? form.query.highlight : null,
      },
      region_field: form.region_field,
      region_name: form.region_name,
      template: form.template,
      limit: Math.min(form.query.limit || 50, 100),
      image: { ...form.image, max_rows: Number(form.image.max_rows) || 30 },
    })
    preview.columns = result.columns
    preview.rows = result.rows
    preview.row_count = result.row_count
    preview.hit_count = result.hit_count
    preview.hit_indexes = result.hit_indexes || []
    preview.trigger = result.trigger || null
    preview.rendered = result.rendered
    preview.image_path = result.image_path || ''
    preview.sql = result.sql
    preview.warnings = result.warnings || []
  } catch (error) {
    previewError.value = error?.response?.data?.detail || '预览失败'
    preview.columns = []
    preview.rows = []
    preview.rendered = ''
    preview.image_path = ''
  } finally {
    previewing.value = false
  }
}

let previewTimer = null
watch(
  () => [
    JSON.stringify(form.query.select),
    JSON.stringify(form.query.group_by),
    JSON.stringify(form.query.aggregations),
    JSON.stringify(form.query.trigger),
    JSON.stringify(form.image),
    form.region_field,
    form.region_name,
    form.table_name,
  ],
  () => {
    clearTimeout(previewTimer)
    previewTimer = setTimeout(runPreview, 400)
  },
)

async function handleSampleUpload(uploadFile) {
  const file = uploadFile.raw
  if (!file) return
  sampleResult.value = await api.parseSample(file, form.data_source_id || undefined)
}

async function applyRecommendation(rec) {
  if (rec.suggested_table) {
    form.table_name = rec.suggested_table
    await onTableChange(rec.suggested_table)
  }
  const picked = rec.column_matches.filter((m) => m.recommended && m.db_column).map((m) => m.db_column)
  if (picked.length) form.query.select = picked
  sampleVisible.value = false
  ElMessage.success('已应用推荐')
  runPreview()
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写规则名称')
  if (!form.data_source_id || !form.table_name) return ElMessage.warning('请选择数据源和数据表')
  if (!form.query.select.length) return ElMessage.warning('请至少选择一个字段')
  if (!form.bot_ids.length) return ElMessage.warning('请至少选择一个发送的钉钉群')

  const atConfig = { ...form.at_config }
  if (atConfig.mode !== 'none' && !conditionEnabled.value) atConfig.condition = null

  const payload = {
    name: form.name.trim(),
    region_name: form.region_name,
    data_source_id: form.data_source_id,
    table_name: form.table_name,
    query: {
      ...form.query,
      table: form.table_name,
      highlight: form.query.highlight.field ? form.query.highlight : null,
    },
    region_field: form.region_field,
    time_field: form.query.time_range.field || '',
    template: form.template,
    msg_type: form.msg_type,
    image: { ...form.image, max_rows: Number(form.image.max_rows) || 30 },
    bot_ids: form.bot_ids,
    at_config: atConfig,
    schedule_type: form.schedule_type,
    schedule: form.schedule,
    enabled: form.enabled,
    sample: form.sample || {},
  }

  saving.value = true
  try {
    if (isEdit.value) {
      await api.updateRule(Number(route.params.id), payload, store.user?.mobile)
      ElMessage.success('已保存')
    } else {
      await api.createRule(payload, store.user?.mobile)
      ElMessage.success('规则已创建')
    }
    router.push({ name: 'rules' })
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.editor {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.editor-main {
  flex: 1;
  min-width: 0;
}

.editor-side {
  width: 430px;
  flex: 0 0 430px;
  position: sticky;
  top: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.head-actions {
  display: flex;
  gap: 8px;
}

.report-image {
  display: block;
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 20px;
}

.form-grid .span-2 {
  grid-column: span 2;
}

.field label {
  display: block;
  font-size: 12.5px;
  color: var(--ink-700);
  margin-bottom: 7px;
  font-weight: 500;
}

.field .el-select,
.field .el-input {
  width: 100%;
}

.opt-tag {
  float: right;
  color: var(--ink-400);
  font-size: 11px;
}

.block + .block {
  margin-top: 22px;
  padding-top: 20px;
  border-top: 1px dashed var(--line);
}

.block-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-800);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.chip-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.chip {
  height: 28px;
  padding: 0 6px 0 4px;
}

.chip-index {
  display: inline-block;
  min-width: 15px;
  height: 15px;
  line-height: 15px;
  text-align: center;
  border-radius: 4px;
  background: var(--brand-100);
  color: var(--brand-700);
  font-size: 10px;
  margin-right: 4px;
}

.chip-move {
  cursor: pointer;
  font-size: 11px;
  margin-left: 3px;
  color: var(--ink-400);
}

.chip-move:hover {
  color: var(--brand-600);
}

.chip-add {
  width: 150px;
}

.cond-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.cond-field {
  width: 200px;
}

.cond-op {
  width: 130px;
}

.cond-value {
  flex: 1;
}

.cond-num {
  width: 120px;
}

/* 场景模板 */
.scenario-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 10px;
}

.scenario-card {
  display: block;
  text-align: left;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fcfcfd;
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
}

.scenario-card:hover {
  border-color: var(--brand-500);
  background: var(--brand-50);
}

.scenario-card.active {
  border-color: var(--brand-500);
  background: var(--brand-50);
  box-shadow: 0 0 0 2px rgba(46, 75, 216, 0.12);
}

.scenario-icon {
  font-size: 18px;
  line-height: 1;
  margin-bottom: 6px;
}

.scenario-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink-900);
  margin-bottom: 4px;
}

.scenario-desc {
  font-size: 12px;
  color: var(--ink-500);
  line-height: 1.6;
}

.scenario-hint {
  margin-top: 10px;
  padding: 9px 12px;
  border-radius: 8px;
  background: var(--brand-50);
  border: 1px solid #dbe3fb;
  color: var(--ink-700);
  font-size: 12.5px;
  line-height: 1.7;
}

/* 触发条件 */
.trigger-row {
  margin-top: 10px;
}

.trigger-banner {
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 12.5px;
  line-height: 1.6;
}

.trigger-banner.ok {
  background: #ecfdf3;
  border: 1px solid #a6f4c5;
  color: #027a48;
}

.trigger-banner.bad {
  background: #fffbfa;
  border: 1px solid #fecdca;
  color: #b42318;
}

/* 命中的行高亮，未命中的行淡化 */
:deep(.row-hit),
:deep(.row-hit td) {
  background: #f6fef9 !important;
}

:deep(.row-miss) {
  color: var(--ink-400);
}

.inline-row .grow {
  flex: 1;
  min-width: 220px;
}

.inline-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.inline-row .split {
  margin-left: 14px;
}

.cond-condition {
  margin-top: 10px;
}

.at-modes,
.at-config {
  margin-bottom: 12px;
}

.at-config:last-child {
  margin-bottom: 0;
}

.tokens {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-top: 10px;
}

.token {
  cursor: pointer;
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 11px;
}

.token:hover {
  color: var(--brand-600);
  border-color: var(--brand-500);
}

.preview-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line-soft);
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-800);
}

.preview-body {
  padding: 12px 14px;
}

.preview-body .empty {
  padding: 24px 0;
}

.preview-error {
  padding: 10px 12px;
  border-radius: 8px;
  background: #fef3f2;
  border: 1px solid #fecdca;
  color: #b42318;
  font-size: 12.5px;
}

.warn-line {
  font-size: 12px;
  color: #b54708;
  line-height: 1.8;
}

.sql {
  max-height: 150px;
  color: var(--ink-500);
}

.sample-result {
  margin-top: 16px;
}

.sample-line {
  font-size: 13px;
  margin-bottom: 12px;
}

.sample-sheet {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 10px;
}

.sample-sheet-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.column-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 8px;
}

.col-chip {
  margin: 0;
}

.warn-text {
  color: #b54708;
}

.match-list {
  margin: 8px 0 10px;
}

.match-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  padding: 4px 0;
}

.match-from {
  color: var(--ink-500);
}

.match-to {
  color: var(--ink-900);
  font-weight: 600;
}

.match-score {
  color: var(--brand-600);
  font-size: 11.5px;
}
</style>
