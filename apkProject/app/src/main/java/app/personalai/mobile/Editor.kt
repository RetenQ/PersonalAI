package app.personalai.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject

data class EditSpec(val kind: String, val data: JSONObject, val id: String? = null, val version: Int = 0)

@Composable fun Editor(spec: EditSpec, vm: ClientModel, close: () -> Unit) {
    var data by remember { mutableStateOf(JSONObject(spec.data.toString())) }
    var problem by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf<JSONObject?>(null) }
    var expanded by remember { mutableStateOf(spec.kind != "quick") }
    var invalidNumbers by remember { mutableStateOf(setOf<String>()) }
    fun valid(key: String, ok: Boolean) { invalidNumbers = if (ok) invalidNumbers - key else invalidNumbers + key }
    fun set(key: String, value: Any?) { data = JSONObject(data.toString()).put(key, value ?: JSONObject.NULL) }
    fun command(): JSONObject {
        require(invalidNumbers.isEmpty()) { "请修正标红的数字输入，不能用旧值代替本次输入。" }
        val source = JSONObject(data.toString())
        fun fields(vararg keys: String): JSONObject = JSONObject().apply { keys.forEach { if (source.has(it)) put(it, source.get(it)) } }
        val kind = spec.kind
        if (kind == "quick") {
            require(source.optString("text").isNotBlank()) { "请先填写内容。" }
            val payload = fields("text", "date").apply { if (!has("date")) put("date", today()) }
            return if (source.text("task_id", "").isNotBlank()) Protocol.command("write_entity", payload.put("task_id", source.getString("task_id")), "log")
            else Protocol.command("create_record", payload.put("kind", "note").put("category", source.optString("category", "uncategorized")))
        }
        if (kind == "task" || kind == "record") {
            val payload = fields("text", "date", "category", "status").apply {
                if (!has("date")) put("date", today()); if (!has("status")) put("status", "open")
            }
            require(payload.optString("text").isNotBlank()) { "请填写任务或记录内容。" }
            if (spec.id == null) payload.put("kind", if (kind == "task") "task" else "note")
            return Protocol.command(if (spec.id == null) "create_record" else "revise_record", payload, id = spec.id, version = spec.version)
        }
        val allowed = when (kind) {
            "goal" -> arrayOf("title", "criteria", "due", "mode", "unit", "baseline", "target", "current", "milestones")
            "tracking" -> arrayOf("task_id", "goal_id", "progress", "tags")
            "log" -> arrayOf("date", "slot", "task_id", "goal_id", "text", "result", "obstacle", "completed")
            "checkin" -> arrayOf("date", "slot", "goal_id", "response", "obstacle")
            "state" -> arrayOf("date", "energy", "mood", "obstacle", "note")
            "profile" -> arrayOf("personality", "values", "preferences", "boundaries")
            "user" -> arrayOf("name", "bio", "focus")
            "ui" -> arrayOf("order", "hidden")
            "reminder" -> arrayOf("title", "start_date", "time", "repeat", "weekdays", "end_date", "timezone", "task_id", "checkin_slot", "enabled")
            "models" -> arrayOf("bindings")
            else -> error("不支持的编辑类型")
        }
        val payload = fields(*allowed)
        if (kind in listOf("log", "checkin", "state") && !payload.has("date")) payload.put("date", today())
        if (kind == "checkin" && !payload.has("slot")) payload.put("slot", "morning")
        if (kind == "reminder" && !payload.has("start_date")) payload.put("start_date", today())
        return Protocol.command(when (kind) { "user", "ui" -> "settings"; "models" -> "model_binding"; "reminder" -> "reminder"; else -> "write_entity" },
            if (kind == "models") payload.getJSONObject("bindings") else payload, kind = kind.takeUnless { it in listOf("models", "reminder") }, id = spec.id, version = spec.version)
    }
    AlertDialog(onDismissRequest = close, title = { Text(if (spec.id == null) "添加记录" else "编辑并预览") }, text = {
        Column(Modifier.fillMaxWidth().heightIn(max = 480.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (problem.isNotBlank()) Text(problem, color = MaterialTheme.colorScheme.error)
            when (spec.kind) {
                "quick", "task", "record", "log" -> {
                    EditField("内容", data.text("text", "")) { set("text", it) }
                    if (spec.kind == "quick") TextButton(onClick = { expanded = !expanded }) { Text("关联任务与补充选项") }
                    if (expanded) {
                        EditField("日期（YYYY-MM-DD）", data.text("date", today())) { set("date", it) }
                        if (spec.kind in listOf("quick", "log")) SelectField("关联任务", data.text("task_id", ""), listOf("" to "不关联，保存为普通记录") + vm.items("tasks").map { it.getString("id") to it.text("text") }) { set("task_id", it.ifBlank { null }) }
                        if (spec.kind in listOf("task", "record")) SelectField("状态", data.text("status", "open"), listOf("open" to "进行中", "partial" to "部分完成", "done" to "已完成")) { set("status", it) }
                        if (spec.kind == "log") { EditField("结果", data.text("result", "")) { set("result", it) }; EditField("阻碍", data.text("obstacle", "")) { set("obstacle", it) } }
                    }
                }
                "goal" -> {
                    EditField("目标名称", data.text("title", "")) { set("title", it) }; EditField("完成标准", data.text("criteria", "")) { set("criteria", it) }
                    EditField("目标期限（选填 YYYY-MM-DD）", data.text("due", "")) { set("due", it.ifBlank { null }) }
                    SelectField("计算方式", data.text("mode", "metric"), listOf("metric" to "数值指标", "milestones" to "里程碑")) { set("mode", it) }
                    if (data.optString("mode", "metric") == "metric") {
                        EditField("单位", data.text("unit", "")) { set("unit", it) }
                        listOf("baseline" to "起点", "target" to "目标值", "current" to "当前值").forEach { (k, label) -> NumberField("$label（空缺为未知）", data, k, { valid(k, it) }) { set(k, it) } }
                    } else {
                        data.optJSONArray("milestones").objects().forEachIndexed { i, milestone ->
                            fun update(k: String, v: Any?) { val list = JSONArray(data.getJSONArray("milestones").toString()); list.getJSONObject(i).put(k, v ?: JSONObject.NULL); set("milestones", list) }
                            EditField("里程碑 ${i + 1}", milestone.text("title", "")) { update("title", it) }
                            NumberField("权重", milestone, "weight", { valid("weight:$i", it) }) { update("weight", it) }; NumberField("进度 0–100（空缺未知）", milestone, "progress", { valid("progress:$i", it) }) { update("progress", it) }
                            TextButton(onClick = { set("milestones", JSONArray(data.getJSONArray("milestones").objects().filterIndexed { index, _ -> index != i })) }) { Text("移除这项里程碑") }
                        }
                        TextButton(onClick = { set("milestones", JSONArray(data.optJSONArray("milestones").objects() + JSONObject().put("title", "").put("weight", 1).put("progress", JSONObject.NULL))) }) { Text("添加里程碑") }
                    }
                }
                "tracking" -> {
                    SelectField("主要目标", data.text("goal_id", ""), listOf("" to "暂不关联") + vm.items("goals").map { it.getString("id") to it.text("title") }) { set("goal_id", it.ifBlank { null }) }
                    NumberField("任务进度 0–100（空缺为未知）", data, "progress", { valid("progress", it) }) { set("progress", it) }
                    Text("完成任务不直接等于目标达到相同比例。")
                    val types = vm.items("settings").find { it.optString("id") == "types" }?.optJSONObject("data")?.optJSONArray("task_types").objects()
                    types.forEach { type -> if (type.optBoolean("active")) { val ids = data.optJSONArray("tags").objectsAndStrings().map { it.toString() }; Row { Checkbox(type.getString("id") in ids, { yes -> set("tags", JSONArray(if (yes) ids + type.getString("id") else ids - type.getString("id"))) }); Text(type.text("name")) } } }
                }
                "checkin", "state" -> {
                    EditField("日期（YYYY-MM-DD）", data.text("date", today())) { set("date", it) }
                    if (spec.kind == "checkin") { SelectField("时段", data.text("slot", "morning"), listOf("morning" to "早", "noon" to "中", "evening" to "晚")) { set("slot", it) }; EditField("进展与回应", data.text("response", "")) { set("response", it) } }
                    else listOf("energy" to "精力", "mood" to "心情", "note" to "备注").forEach { (k, label) -> EditField(label, data.text(k, "")) { set(k, it) } }
                    EditField("阻碍", data.text("obstacle", "")) { set("obstacle", it) }
                }
                "user", "profile" -> {
                    val fields = if (spec.kind == "user") listOf("name" to "展示名称", "bio" to "简介", "focus" to "近期关注") else listOf("personality" to "个性", "values" to "价值取向", "preferences" to "偏好", "boundaries" to "边界")
                    fields.forEach { (k, label) -> EditField(label, data.text(k, "")) { set(k, it) } }
                }
                "ui" -> {
                    val order = data.optJSONArray("order").objectsAndStrings().map { it.toString() }; val hidden = data.optJSONArray("hidden").objectsAndStrings().map { it.toString() }
                    val labels = mapOf("profile" to "个人情况", "state" to "当前状态", "year" to "年度时间", "goals" to "目标", "logs" to "日志", "other" to "其他事项", "checkins" to "回顾", "pending" to "待确认")
                    order.forEachIndexed { index, id -> Row { Checkbox(id !in hidden, { visible -> set("hidden", JSONArray(if (visible) hidden - id else hidden + id)) }); Text(labels[id] ?: id, Modifier.weight(1f)); TextButton(enabled = index > 0, onClick = { val list = order.toMutableList(); java.util.Collections.swap(list, index, index - 1); set("order", JSONArray(list)) }) { Text("上移") } } }
                }
                "models" -> {
                    val bindings = data.optJSONObject("bindings") ?: JSONObject()
                    listOf("goal" to "目标分析", "schedule" to "定时分析").forEach { (key, label) -> SelectField(label, bindings.text(key, ""), listOf("" to "不绑定") + data.optJSONArray("connections").objects().filter { it.optBoolean("enabled") }.map { it.getString("id") to it.text("name") }) { value -> set("bindings", JSONObject(bindings.toString()).put(key, value.ifBlank { null } ?: JSONObject.NULL)) } }
                    Text("更换连接后，自动分析需要重新预览授权。密钥仅由网页管理。")
                }
                "reminder" -> {
                    EditField("提醒名称", data.text("title", "")) { set("title", it) }; EditField("开始日期", data.text("start_date", today())) { set("start_date", it) }; EditField("上海时间（HH:MM）", data.text("time", "")) { set("time", it) }
                    SelectField("重复", data.text("repeat", "once"), listOf("once" to "一次", "daily" to "每天", "weekly" to "每周")) { set("repeat", it) }
                    if (data.optString("repeat") == "weekly") { val days = data.optJSONArray("weekdays").objectsAndStrings().map { (it as Number).toInt() }; listOf("一", "二", "三", "四", "五", "六", "日").forEachIndexed { i, label -> Row { Checkbox(i in days, { checked -> set("weekdays", JSONArray(if (checked) days + i else days - i)) }); Text("周$label") } } }
                    SelectField("关联任务", data.text("task_id", ""), listOf("" to "不关联") + vm.items("tasks").map { it.getString("id") to it.text("text") }) { set("task_id", it.ifBlank { null }) }
                    Row { Switch(data.optBoolean("enabled", true), { set("enabled", it) }); Text("启用") }
                }
            }
        }
    }, confirmButton = { Button(onClick = { try { confirm = command(); problem = "" } catch (e: Exception) { problem = e.message ?: "请检查输入" } }, enabled = !vm.busy) { Text("预览提交") } }, dismissButton = { Row { TextButton(onClick = { try { if (vm.saveDraft(command())) close() } catch (e: Exception) { problem = e.message ?: "请检查输入" } }) { Text("存为草稿") }; TextButton(onClick = close) { Text("取消") } } })
    confirm?.let { c -> AlertDialog(onDismissRequest = { confirm = null }, title = { Text("检查这次提交") }, text = { Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState())) { if (spec.id != null) { Text("修改前"); FriendlyData(spec.data) }; Text("提交内容"); FriendlyData(c.getJSONObject("data")); Text("正式修改会进入待确认；离线或提交失败保留为本机草稿。") } }, confirmButton = { Button(onClick = { if (vm.saveDraft(c)) { vm.submit(c); close() } }) { Text("提交服务器") } }, dismissButton = { TextButton(onClick = { confirm = null }) { Text("返回编辑") } }) }
}

@Composable fun EditField(label: String, value: String, changed: (String) -> Unit) { OutlinedTextField(value, changed, label = { Text(label) }, modifier = Modifier.fillMaxWidth()) }
@Composable fun NumberField(label: String, data: JSONObject, key: String, validity: (Boolean) -> Unit, changed: (Double?) -> Unit) {
    var text by remember { mutableStateOf(data.text(key, "")) }
    var invalid by remember { mutableStateOf(false) }
    OutlinedTextField(text, { text = it; invalid = it.isNotBlank() && it.toDoubleOrNull()?.isFinite() != true; validity(!invalid); if (!invalid) changed(it.toDoubleOrNull()) }, label = { Text(label) }, isError = invalid, supportingText = { if (invalid) Text("请填写有效数字") }, modifier = Modifier.fillMaxWidth())
}
@Composable fun SelectField(label: String, value: String, options: List<Pair<String, String>>, changed: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box { OutlinedButton(onClick = { open = true }, modifier = Modifier.fillMaxWidth()) { Text("$label：" + (options.find { it.first == value }?.second ?: "请选择")) }; DropdownMenu(expanded = open, onDismissRequest = { open = false }) { options.forEach { (id, name) -> DropdownMenuItem(text = { Text(name) }, onClick = { changed(id); open = false }) } } }
}
