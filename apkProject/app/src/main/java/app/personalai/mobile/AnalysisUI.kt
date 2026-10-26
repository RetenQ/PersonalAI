package app.personalai.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import org.json.JSONArray
import org.json.JSONObject

@Composable fun GoalAnalysis(goal: JSONObject, vm: ClientModel) {
    var open by remember { mutableStateOf(false) }
    var tasks by remember { mutableStateOf(listOf<String>()) }
    var logs by remember { mutableStateOf(listOf<String>()) }
    TextButton(onClick = { open = !open }) { Text("分析目标") }
    if (open) {
        Text("选择本次提供的任务和日志，下一步会展示完整发送内容。")
        vm.items("tasks").filter { it.optString("goal_id") == goal.getString("id") }.forEach { t -> Row { Checkbox(t.getString("id") in tasks, { yes -> tasks = if (yes) tasks + t.getString("id") else tasks - t.getString("id") }); Text(t.text("text")) } }
        vm.items("logs").filter { it.optString("goal_id") == goal.getString("id") }.forEach { l -> Row { Checkbox(l.getString("id") in logs, { yes -> logs = if (yes) logs + l.getString("id") else logs - l.getString("id") }); Text(l.text("text")) } }
        Button(onClick = { vm.previewGoal(goal, tasks, logs) }, enabled = !vm.busy) { Text("预览发送范围") }
    }
}
@Composable fun SchedulePanel(vm: ClientModel) {
    var edit by remember { mutableStateOf(false) }
    var times by remember { mutableStateOf("") }
    var scopes by remember { mutableStateOf(listOf<String>()) }
    var enabled by remember { mutableStateOf(false) }
    LaunchedEffect(vm.schedule) {
        vm.schedule?.optJSONObject("config")?.let { c -> times = c.optJSONArray("times").objectsAndStrings().joinToString(", "); scopes = c.optJSONArray("scopes").objectsAndStrings().map { it.toString() }; enabled = c.optBoolean("enabled") }
    }
    CardBlock("定时分析") {
        Text("分析时刻与手机通知时刻分别设置；更换模型连接或发送范围需重新授权。")
        TextButton(onClick = { vm.loadSchedule(); edit = true }, enabled = !vm.busy) { Text("读取与修改分析安排") }
        if (edit && vm.schedule != null) {
            Text(if (vm.schedule!!.optBoolean("active")) "已授权运行" else "当前未启用或需要重新授权")
            EditField("上海时间，逗号分隔（例如 09:15）", times) { times = it }
            listOf("records" to "原文", "goals" to "目标", "tasks" to "任务", "logs" to "日志", "checkins" to "回顾", "states" to "现状").forEach { (id, label) -> Row { Checkbox(id in scopes, { yes -> scopes = if (yes) scopes + id else scopes - id }); Text(label) } }
            Row { Switch(enabled, { enabled = it }); Text("启用定时分析") }
            Button(onClick = { vm.previewSchedule(JSONObject().put("enabled", enabled).put("times", JSONArray(times.split(',', '，').map { it.trim() }.filter { it.isNotBlank() })).put("scopes", JSONArray(scopes))) }, enabled = !vm.busy) { Text("预览并授权") }
        }
    }
}
