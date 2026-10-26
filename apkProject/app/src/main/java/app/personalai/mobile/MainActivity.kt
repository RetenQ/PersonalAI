package app.personalai.mobile

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.ZoneId

class MainActivity : ComponentActivity() {
    private val model: ClientModel by viewModels()
    private var notificationStatus by mutableStateOf("")
    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { refreshPermissions() }
    private fun refreshPermissions() {
        notificationStatus = (if (Reminders.allowed(this)) "通知已允许" else "通知未允许，无法展示提醒") + " · " + (if (Reminders.exact(this)) "精确安排可用" else "按系统允许时间提醒，可能延迟")
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        if (intent.getBooleanExtra("messages", false)) model.page = 3
        setContentView()
    }
    override fun onResume() { super.onResume(); refreshPermissions(); model.startWatching(); runCatching { Reminders.reconcile(this) } }
    override fun onPause() { model.stopWatching(); super.onPause() }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); if (intent.getBooleanExtra("messages", false)) model.page = 3; model.sync() }
    private fun setContentView(): Unit = setContent {
        MaterialTheme(colorScheme = lightColorScheme(primary = Color(0xFF52665A), secondary = Color(0xFF8A6D4C),
            background = Color(0xFFF5F3EE), surface = Color(0xFFFCFBF8), surfaceVariant = Color(0xFFEAE7DF))) {
            PersonalScreen(model, requestNotifications = { if (Build.VERSION.SDK_INT >= 33) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS) },
                requestExact = { if (Build.VERSION.SDK_INT >= 31) startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:$packageName"))) },
                reminderStatus = notificationStatus)
        }
    }
}

fun today(): String = LocalDate.now(ZoneId.of("Asia/Shanghai")).toString()
fun JSONObject.text(key: String, fallback: String = "未记录"): String = if (isNull(key) || optString(key).isBlank()) fallback else optString(key)

@Composable fun PersonalScreen(vm: ClientModel, requestNotifications: () -> Unit, requestExact: () -> Unit, reminderStatus: String) {
    val names = listOf("今日", "目标与任务", "记录与回顾", "消息与报告", "我的")
    val icons = listOf(Icons.Outlined.Today, Icons.Outlined.Flag, Icons.Outlined.EditNote, Icons.Outlined.Notifications, Icons.Outlined.Person)
    var editor by remember { mutableStateOf<EditSpec?>(null) }
    var disconnect by remember { mutableStateOf(false) }
    val splitDetails = LocalConfiguration.current.screenWidthDp >= 1000
    BoxWithConstraints(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).systemBarsPadding()) {
        val wide = maxWidth >= 700.dp
        Row {
            if (wide && vm.paired) NavigationRail { names.forEachIndexed { i, s -> NavigationRailItem(selected = vm.page == i, onClick = { vm.page = i }, icon = { Icon(icons[i], s) }, label = { Text(s) }) } }
            Scaffold(modifier = Modifier.weight(1f), containerColor = Color.Transparent, bottomBar = {
                if (!wide && vm.paired) NavigationBar { names.forEachIndexed { i, s -> NavigationBarItem(selected = vm.page == i, onClick = { vm.page = i }, icon = { Icon(icons[i], s) }, label = { Text(s) }) } }
            }) { padding ->
                Column(Modifier.padding(padding).padding(horizontal = if (wide) 32.dp else 20.dp).verticalScroll(rememberScrollState()).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    Spacer(Modifier.height(8.dp))
                    Text("PERSONAL AI", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                    Text(if (vm.paired) names[vm.page] else "连接你的 PersonalAI", style = MaterialTheme.typography.headlineLarge)
                    if (vm.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                    if (vm.error.isNotBlank()) CardBlock("暂未完成") { Text(vm.error, color = MaterialTheme.colorScheme.error) }
                    if (vm.notice.isNotBlank()) Text(vm.notice, color = MaterialTheme.colorScheme.primary)
                    if (!vm.paired) Pairing(vm) else {
                        Text("最后同步：" + vm.snapshot.text("synced_at") + " · 草稿 ${vm.drafts.size}", style = MaterialTheme.typography.bodySmall)
                        if (vm.local.has("sync_error")) Text(vm.local.getString("sync_error"), color = MaterialTheme.colorScheme.error)
                        OutlinedButton(onClick = vm::sync, enabled = !vm.busy) { Text("同步最新资料") }
                        when (vm.page) {
                            0 -> {
                                CardBlock("下一步") {
                                    Text("${today()} · 上海时间")
                                    Text("待确认 ${vm.items("pending").size} 项 · 今日计划 ${vm.items("tasks").count { it.optString("planned_date") == today() && it.optString("status") != "done" }} 项")
                                    Button(onClick = { editor = EditSpec("quick", JSONObject()) }) { Text("记下进展") }
                                    TextButton(onClick = { vm.page = 3 }) { Text("处理待确认") }
                                    vm.items("states").filter { it.optJSONObject("data")?.optString("date") == today() }.forEach { Text("阻碍：" + it.getJSONObject("data").text("obstacle")) }
                                }
                                CardBlock("年度时间") { val y = vm.snapshot.optJSONObject("year"); Text("今年还剩 ${y?.optInt("remaining_days") ?: "—"} 天（含今天）"); Text("这是日历时间，不是目标完成度。", style = MaterialTheme.typography.bodySmall) }
                                vm.items("tasks").filter { it.optString("planned_date") == today() }.forEach { TaskCard(it, vm) { spec -> editor = spec } }
                                if (vm.items("tasks").none { it.optString("planned_date") == today() }) Empty("今天没有已记录的任务，可以先记下正在做的事。")
                            }
                            1 -> {
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Button(onClick = { editor = EditSpec("goal", JSONObject()) }) { Text("新目标") }; OutlinedButton(onClick = { editor = EditSpec("task", JSONObject()) }) { Text("新任务") } }
                                vm.items("goals").forEach { g -> CardBlock(g.text("title")) {
                                    Text(g.text("criteria")); Progress(g, "已确认目标进度")
                                    Text("目标期限：" + g.text("due"), style = MaterialTheme.typography.bodySmall)
                                    val ai = vm.items("reports").lastOrNull { it.optJSONObject("sources")?.has(g.getString("id")) == true }
                                    val assessment = ai?.optJSONObject("assessment")
                                    Text("AI 估计：" + if (assessment == null || assessment.isNull("low")) "证据不足或尚未分析" else "${assessment.optDouble("low")}–${assessment.optDouble("high")}%" + if (ai.optBoolean("stale")) " · 依据已变化" else "")
                                    Row { TextButton(onClick = { editor = EditSpec("goal", g.getJSONObject("data"), g.getString("id"), g.getInt("version")) }) { Text("修改") }; TextButton(onClick = { vm.history(g.getString("id")) }) { Text("历史与来源") } }
                                    GoalAnalysis(g, vm)
                                    vm.items("tasks").filter { it.optString("goal_id") == g.getString("id") }.forEach { t -> TaskCard(t, vm) { editor = it } }
                                } }
                                Text("未关联目标的任务", style = MaterialTheme.typography.titleLarge)
                                vm.items("tasks").filter { it.isNull("goal_id") || it.optString("goal_id").isBlank() }.forEach { TaskCard(it, vm) { spec -> editor = spec } }
                                if (vm.items("goals").isEmpty()) Empty("尚未创建目标。任务可以暂不关联目标。")
                            }
                            2 -> {
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Button(onClick = { editor = EditSpec("quick", JSONObject()) }) { Text("快捷记录") }; TextButton(onClick = { editor = EditSpec("checkin", JSONObject()) }) { Text("早中晚回顾") }; TextButton(onClick = { editor = EditSpec("state", JSONObject()) }) { Text("现状") } }
                                vm.drafts.forEach { d -> CardBlock("未提交草稿") { FriendlyData(d.getJSONObject("data")); Text("草稿不代表服务器已保存。冲突时请刷新相关记录，重新编辑。", style = MaterialTheme.typography.bodySmall); Button(onClick = { vm.submit(d) }, enabled = !vm.busy) { Text("联网提交这份草稿") }; TextButton(onClick = { vm.discard(d.getString("request_id")) }) { Text("删除本机草稿") } } }
                                listOf("logs" to "活动日志", "checkins" to "早中晚回顾", "states" to "当前状态", "records" to "原文记录").forEach { (resource, title) ->
                                    Text(title, style = MaterialTheme.typography.titleLarge)
                                    vm.items(resource).asReversed().forEach { item -> CardBlock(item.text("date", item.optJSONObject("data")?.text("date") ?: title)) {
                                        val data = item.optJSONObject("data") ?: item; FriendlyData(data)
                                        val task = vm.items("tasks").find { it.getString("id") == data.optString("task_id") }
                                        if (task != null) TextButton(onClick = { vm.detail = task }) { Text("关联任务：" + task.text("text")) }
                                        TextButton(onClick = { vm.history(item.getString("id")) }) { Text("查看来源与历史") }
                                        TextButton(onClick = { editor = EditSpec(mapOf("logs" to "log", "checkins" to "checkin", "states" to "state", "records" to "record").getValue(resource), data, item.getString("id"), item.getInt("version")) }) { Text("更正记录") }
                                    } }
                                    if (vm.items(resource).isEmpty()) Empty("未记录，不代表没有完成。")
                                }
                            }
                            3 -> {
                                Text("待本人确认", style = MaterialTheme.typography.titleLarge)
                                vm.items("pending").forEach { p -> CardBlock(p.text("reason", p.optJSONObject("data")?.text("reason", "待确认建议") ?: "待确认建议")) { Button(onClick = { vm.review = p }) { Text("查看差异") } } }
                                if (vm.items("pending").isEmpty()) Empty("当前没有待确认事项。")
                                Text("未来提醒", style = MaterialTheme.typography.titleLarge)
                                (vm.local.optJSONArray("reminder_history").objects() + vm.snapshot.optJSONArray("occurrences").objects()).takeLast(100).forEach { r -> CardBlock(r.text("title")) {
                                    val read = vm.snapshot.optJSONArray("receipts").objects().any { it.optJSONObject("data")?.optString("message_id") == r.getString("id") && it.getJSONObject("data").optString("action") == "read" }
                                    Text(r.text("due_at") + if (read) " · 已读" else ""); Row { TextButton(onClick = { vm.receipt(r, false) }, enabled = !vm.busy && !read) { Text("已读") }; TextButton(onClick = { vm.receipt(r, true) }, enabled = !vm.busy) { Text("十分钟后提醒") } }
                                } }
                                Text("分析报告", style = MaterialTheme.typography.titleLarge)
                                vm.items("reports").asReversed().forEach { r -> CardBlock(if (r.optBoolean("stale")) "依据已变化" else "分析结果") { Text(r.text("status")); Text(r.text("message", "")); FriendlyData(r.optJSONObject("assessment") ?: JSONObject()); TextButton(onClick = { vm.detail = r }) { Text("查看依据与版本") } } }
                            }
                            4 -> {
                                CardBlock("资料与偏好") {
                                    val user = vm.items("settings").find { it.optString("id") == "user" }
                                    FriendlyData(user?.optJSONObject("data") ?: JSONObject())
                                    Button(onClick = { editor = EditSpec("user", user?.optJSONObject("data") ?: JSONObject(), version = user?.optInt("version") ?: 0) }) { Text("修改展示资料") }
                                    val profile = vm.items("profile").firstOrNull()
                                    TextButton(onClick = { editor = EditSpec("profile", profile?.optJSONObject("data") ?: JSONObject(), profile?.optString("id") ?: "profile", profile?.optInt("version") ?: 0) }) { Text("个性、偏好与边界") }
                                    val ui = vm.items("settings").find { it.optString("id") == "ui" }
                                    TextButton(onClick = { editor = EditSpec("ui", ui?.optJSONObject("data") ?: JSONObject(), version = ui?.optInt("version") ?: 0) }) { Text("首页模块显示与排序") }
                                    val models = vm.items("settings").find { it.optString("id") == "models" }
                                    TextButton(onClick = { editor = EditSpec("models", models?.optJSONObject("data") ?: JSONObject(), version = models?.optInt("version") ?: 0) }) { Text("选择模型连接") }
                                }
                                CardBlock("本机提醒") {
                                    Text(reminderStatus); Text("手机系统限制可能延迟通知。离线时保留最近一次同步的日程。")
                                    Row { Switch(checked = vm.local.optBoolean("notifications"), onCheckedChange = vm::notifications); Text("在这台设备提醒") }
                                    TextButton(onClick = requestNotifications) { Text("申请通知权限") }; TextButton(onClick = requestExact) { Text("检查精确提醒权限") }
                                    Button(onClick = { editor = EditSpec("reminder", JSONObject()) }) { Text("新建日程提醒") }
                                    vm.items("reminders").forEach { r -> TextButton(onClick = { editor = EditSpec("reminder", r.getJSONObject("data"), r.getString("id"), r.getInt("version")) }) { Text(r.getJSONObject("data").text("title")) } }
                                    if (BuildConfig.PUSH_CONFIGURED) { Text("开启服务器推送后，极光会处理设备标识；通知不含个人资料正文。")
                                        Row { Switch(checked = vm.local.optBoolean("push_consent"), onCheckedChange = vm::pushConsent); Text("同意启用普通推送") }
                                    } else Text("此安装包未配置推送通道；本地日程提醒仍可使用。")
                                }
                                CardBlock("连接") { Text(vm.local.text("server")); Text("模型密钥和服务器配置由网页管理。离线时不能确认正式修改。"); TextButton(onClick = { disconnect = true }) { Text("断开并清除本机资料") } }
                                SchedulePanel(vm)
                            }
                        }
                    }
                    Spacer(Modifier.height(24.dp))
                }
            }
            if (splitDetails && vm.detail != null) Column(Modifier.width(340.dp).fillMaxHeight().padding(16.dp).verticalScroll(rememberScrollState())) {
                Text("详情与来源", style = MaterialTheme.typography.titleLarge)
                TextButton(onClick = { vm.detail = null }) { Text("关闭详情") }
                FriendlyData(vm.detail)
            }
        }
    }
    editor?.let { spec -> Editor(spec, vm, close = { editor = null }) }
    vm.review?.let { p -> AlertDialog(onDismissRequest = { vm.review = null }, title = { Text("本人确认") }, text = {
        Column(Modifier.heightIn(max = 430.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            val data = p.optJSONObject("data") ?: p
            Text("修改前", style = MaterialTheme.typography.titleMedium); FriendlyData(data.opt("before"))
            Text("修改后 / 建议", style = MaterialTheme.typography.titleMedium); FriendlyData(data.opt("after") ?: data.opt("sections") ?: data)
            Text("保存后保留旧版；资料已更新时会拒绝过期确认。")
        }
    }, confirmButton = { Button(onClick = { vm.decide(p, true) }, enabled = !vm.busy) { Text("确认保存") } }, dismissButton = { TextButton(onClick = { vm.decide(p, false) }, enabled = !vm.busy) { Text("拒绝") } }) }
    if (!splitDetails) vm.detail?.let { d -> AlertDialog(onDismissRequest = { vm.detail = null }, title = { Text("详情与来源") }, text = { Column(Modifier.heightIn(max = 480.dp).verticalScroll(rememberScrollState())) { FriendlyData(d) } }, confirmButton = { TextButton(onClick = { vm.detail = null }) { Text("关闭") } }) }
    vm.analysisPreview?.let { p -> AlertDialog(onDismissRequest = { vm.analysisPreview = null }, title = { Text("确认分析资料范围") }, text = { Column(Modifier.heightIn(max = 430.dp).verticalScroll(rememberScrollState())) { Text(p.text("notice", "以下资料将发送至所选模型，可能产生费用。")); FriendlyData(p) } }, confirmButton = { Button(onClick = vm::confirmAnalysis, enabled = !vm.busy) { Text("确认授权") } }, dismissButton = { TextButton(onClick = { vm.analysisPreview = null }) { Text("取消") } }) }
    if (disconnect) AlertDialog(onDismissRequest = { disconnect = false }, title = { Text("清除本机缓存与草稿？") }, text = { Text("未提交草稿会丢失。服务器正式资料保留，设备授权需要在网页单独撤销。") }, confirmButton = { Button(onClick = { vm.disconnect(); disconnect = false }) { Text("确认清除") } }, dismissButton = { TextButton(onClick = { disconnect = false }) { Text("保留") } })
}

@Composable fun CardBlock(title: String, content: @Composable ColumnScope.() -> Unit) { Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(20.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) { Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) { Text(title, style = MaterialTheme.typography.titleMedium); content() } } }
@Composable fun Empty(text: String) { Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
@Composable fun Progress(item: JSONObject, label: String) {
    if (item.isNull("confirmed_progress")) Text("$label：尚无法计算") else { val p = item.optDouble("confirmed_progress"); Text("$label：$p%"); LinearProgressIndicator(progress = { (p / 100).toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth()) }
}
@Composable fun TaskCard(task: JSONObject, vm: ClientModel, edit: (EditSpec) -> Unit) {
    CardBlock(task.text("text")) {
        Text("计划日期：${task.text("planned_date")} · ${mapOf("open" to "进行中", "partial" to "部分完成", "done" to "已完成")[task.optString("status")] ?: "未知"}")
        Progress(task, "任务自身进度")
        Row { TextButton(onClick = { edit(EditSpec("task", task.getJSONObject("record"), task.getString("id"), task.getInt("version"))) }) { Text("修改任务") }; TextButton(onClick = { val t = task.optJSONObject("tracking"); edit(EditSpec("tracking", t?.getJSONObject("data") ?: JSONObject().put("task_id", task.getString("id")), "tracking:" + task.getString("id"), t?.getInt("version") ?: 0)) }) { Text("进度与归属") } }
        Row { TextButton(onClick = { edit(EditSpec("quick", JSONObject().put("task_id", task.getString("id")))) }) { Text("记进展") }; TextButton(onClick = { vm.history(task.getString("id")) }) { Text("历史") } }
    }
}
@Composable private fun Pairing(vm: ClientModel) {
    var server by remember { mutableStateOf(vm.local.optString("server")) }; var name by remember { mutableStateOf("我的安卓设备") }
    Text("在已登录网页确认配对码后，手机才能读取资料。正式连接使用 HTTPS。")
    OutlinedTextField(server, { server = it }, label = { Text("服务器地址") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
    OutlinedTextField(name, { name = it }, label = { Text("设备名称") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
    Button(onClick = { vm.pair(server, name) }, enabled = !vm.busy && server.isNotBlank() && name.isNotBlank()) { Text("获取配对码") }
    vm.local.optJSONObject("pairing")?.let { p -> CardBlock("配对码：" + p.text("code")) { Text("配对码十分钟内有效。请在网页设置 → 设备、Agent 与提醒中批准。"); Button(onClick = vm::poll, enabled = !vm.busy) { Text("我已在网页批准，完成连接") } } }
}

private val fieldNames = mapOf("text" to "内容", "date" to "日期", "title" to "名称", "response" to "回应", "obstacle" to "阻碍", "result" to "结果", "energy" to "精力", "mood" to "心情", "note" to "备注", "name" to "展示名称", "bio" to "简介", "focus" to "近期关注", "criteria" to "完成标准", "current" to "当前值", "target" to "目标值", "baseline" to "起点", "progress" to "进度", "assessment" to "分析", "missing" to "缺失信息", "suggestions" to "建议", "facts" to "事实", "reflection" to "进展分析", "issues" to "问题", "next_steps" to "下一步", "long_term" to "长期关系", "sources" to "依据版本", "source_ids" to "来源编号", "id" to "编号", "version" to "版本", "updated_at" to "更新时间", "data" to "内容", "items" to "历史", "explanation" to "说明", "confidence" to "证据强度", "personality" to "个性", "values" to "价值取向", "preferences" to "偏好", "boundaries" to "边界")
@Composable fun FriendlyData(value: Any?, depth: Int = 0) {
    if (depth > 7) { Text("内容较深，请到网页查看完整详情。"); return }
    when (value) {
        null, JSONObject.NULL -> Text("未记录")
        is JSONObject -> value.keys().asSequence().filter { it !in setOf("request_id", "base_url", "model_fingerprint") }.forEach { key ->
            val item = value.opt(key)
            if (item is JSONObject || item is JSONArray) { Text(fieldNames[key] ?: key, style = MaterialTheme.typography.labelLarge); Column(Modifier.padding(start = 10.dp)) { FriendlyData(item, depth + 1) } }
            else Text("${fieldNames[key] ?: key}：${if (item == null || item == JSONObject.NULL || item.toString().isBlank()) "未记录" else item}", style = MaterialTheme.typography.bodyMedium)
        }
        is JSONArray -> value.objectsAndStrings().forEach { FriendlyData(it, depth + 1) }
        else -> Text(value.toString())
    }
}
