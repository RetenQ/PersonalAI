package app.personalai.mobile

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.compose.runtime.*
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject

class ClientModel(application: Application) : AndroidViewModel(application) {
    private val store = SecureStore(application)
    private val api = Api(store)
    var local by mutableStateOf(JSONObject()); private set
    var busy by mutableStateOf(false); private set
    var error by mutableStateOf(""); private set
    var notice by mutableStateOf(""); private set
    var review by mutableStateOf<JSONObject?>(null)
    var detail by mutableStateOf<JSONObject?>(null)
    var analysisPreview by mutableStateOf<JSONObject?>(null)
    var analysisRequest by mutableStateOf<JSONObject?>(null)
    var analysisPath by mutableStateOf("")
    var schedule by mutableStateOf<JSONObject?>(null)
    var page by mutableIntStateOf(0)
    private var watcher: Job? = null
    init { reload() }
    val snapshot: JSONObject get() = local.optJSONObject("snapshot") ?: JSONObject()
    val paired: Boolean get() = local.has("tokens")
    val drafts: List<JSONObject> get() = local.optJSONArray("drafts").objects()
    fun items(name: String) = snapshot.optJSONObject("data")?.optJSONArray(name).objects()
    private fun reload() { try { local = store.read() } catch (_: Exception) { error = "本机加密缓存无法读取。请先保留应用数据，检查系统密钥是否可用。" } }
    private fun run(action: suspend () -> Unit) {
        if (busy) return
        busy = true; error = ""; notice = ""
        viewModelScope.launch {
            try { action() } catch (e: Exception) {
                if (e is CancellationException) throw e
                error = if (e is ApiError || e is IllegalArgumentException) e.message ?: "操作未完成" else "连接或保存未完成，输入及草稿仍保留。"
            } finally { reload(); busy = false }
        }
    }
    fun pair(server: String, name: String) = run { withContext(Dispatchers.IO) { api.pair(server, name) }; notice = "请在已登录网页批准配对码。" }
    fun poll() = run {
        val result = withContext(Dispatchers.IO) { api.pollPair() }
        if (result.optString("status") == "paired") {
            withContext(Dispatchers.IO) {
                val capabilities = api.request("/capabilities")
                store.update { it.put("notifications", capabilities.optBoolean("notifications", false)) }
                api.sync(); Reminders.reconcile(getApplication())
            }
            notice = "设备已连接。"; startWatching()
        } else notice = "等待网页批准。"
    }
    fun sync() = run { withContext(Dispatchers.IO) { api.sync(); Reminders.reconcile(getApplication()) }; notice = "已同步服务器资料。" }
    fun saveDraft(command: JSONObject): Boolean {
        return try {
            store.update { data -> data.put("drafts", JSONArray(data.optJSONArray("drafts").objects().filter { it.getString("request_id") != command.getString("request_id") } + command)) }
            reload(); notice = "已保存在本机草稿，尚未提交服务器。"
            true
        } catch (_: Exception) { error = "草稿保存失败，请保留输入。"; false }
    }
    fun discard(id: String) { store.update { it.put("drafts", JSONArray(it.optJSONArray("drafts").objects().filter { d -> d.getString("request_id") != id })) }; reload() }
    fun submit(command: JSONObject) = run {
        // Persist before any network call. Never automatically send drafts in sync workers.
        withContext(Dispatchers.IO) { store.update { it.put("drafts", JSONArray(it.optJSONArray("drafts").objects().filter { d -> d.getString("request_id") != command.getString("request_id") } + command)) } }
        val result = withContext(Dispatchers.IO) { api.sync(); api.request("/commands", command) }
        discard(command.getString("request_id"))
        review = result.optJSONObject("change") ?: result.optJSONObject("proposal") ?: result.optJSONObject("entity")?.takeIf { it.optString("kind") == "core/client-change" }
        notice = if (review != null) "修改已进入待确认，请检查差异。" else "服务器已保存。"
        withContext(Dispatchers.IO) { api.sync(); Reminders.reconcile(getApplication()) }
    }
    fun decide(item: JSONObject, accept: Boolean) {
        val command = Protocol.command("decide", JSONObject().put("decision", if (accept) "accept" else "reject"), id = item.getString("id"))
        review = null; submit(command)
    }
    fun history(id: String) = run { detail = withContext(Dispatchers.IO) { api.request("/history/" + java.net.URLEncoder.encode(id, "UTF-8")) } }
    fun previewGoal(goal: JSONObject, tasks: List<String>, logs: List<String>) = run {
        val selection = JSONObject().put("goal_id", goal.getString("id")).put("task_ids", JSONArray(tasks)).put("log_ids", JSONArray(logs))
        val preview = withContext(Dispatchers.IO) { api.request("/analyses/preview", selection) }
        analysisPath = "/analyses"
        analysisRequest = JSONObject(selection.toString()).put("sources", preview.getJSONObject("input").getJSONObject("sources"))
            .put("settings_version", preview.getInt("settings_version")).put("approved", true).put("request_id", java.util.UUID.randomUUID().toString())
        analysisPreview = preview
    }
    fun loadSchedule() = run { schedule = withContext(Dispatchers.IO) { api.request("/schedule") } }
    fun previewSchedule(value: JSONObject) = run {
        val preview = withContext(Dispatchers.IO) { api.request("/schedule/preview", JSONObject().put("data", value).put("expected_version", schedule?.optInt("version") ?: 0)) }
        analysisPath = "/schedule/confirm"
        analysisRequest = JSONObject().put("approval_token", preview.getString("approval_token")).put("approved", true).put("request_id", java.util.UUID.randomUUID().toString())
        analysisPreview = preview
    }
    fun confirmAnalysis() = run {
        val body = analysisRequest ?: return@run
        withContext(Dispatchers.IO) { api.request(analysisPath, body) }
        analysisPreview = null; analysisRequest = null
        withContext(Dispatchers.IO) { api.sync() }; notice = "服务器已处理；正式计划和进度未自动更改。"
    }
    fun notifications(enabled: Boolean) = run {
        withContext(Dispatchers.IO) {
            api.request("/device", JSONObject().put("notifications", enabled).apply { local.optString("push_registration").takeIf { it.isNotBlank() }?.let { put("push_registration", it) } })
            store.update { it.put("notifications", enabled) }; Reminders.reconcile(getApplication())
        }
    }
    fun receipt(item: JSONObject, snooze: Boolean) = run {
        if (snooze) Reminders.snooze(getApplication(), item, 10)
        withContext(Dispatchers.IO) { api.request("/commands", Protocol.command("receipt", JSONObject().put("action", if (snooze) "snooze" else "read").put("minutes", 10), id = item.getString("id"))); api.sync() }
        notice = if (snooze) "本机将在十分钟后提醒；任务状态未改变。" else "已标为已读；任务状态未改变。"
    }
    fun pushConsent(enabled: Boolean) {
        store.update { it.put("push_consent", enabled) }; reload()
        if (enabled) PushBridge.start(getApplication()) else {
            PushBridge.stop(getApplication())
            if (paired) run { withContext(Dispatchers.IO) { api.request("/device", JSONObject().put("notifications", local.optBoolean("notifications")).put("push_registration", JSONObject.NULL)) } }
        }
    }
    fun disconnect() {
        watcher?.cancel(); Reminders.cancelAll(getApplication()); PushBridge.stop(getApplication())
        store.clear(); reload(); notice = "本机连接与缓存已清除。服务器授权请在网页撤销。"
    }
    fun startWatching() {
        if (watcher?.isActive == true) return
        watcher = viewModelScope.launch {
            while (isActive && paired) {
                try {
                    val updated = withContext(Dispatchers.IO) { api.awaitUpdate() }
                    if (updated && !busy) { withContext(Dispatchers.IO) { api.sync(); Reminders.reconcile(getApplication()) }; reload() }
                    delay(1500)
                } catch (e: Exception) {
                    if (e is CancellationException) throw e
                    error = if (e is ApiError && e.status == 401) "设备授权已失效，请重新配对。" else "实时连接中断，保留缓存；可以手动同步。"
                    if (e is ApiError && e.status == 401) break
                    delay(15000)
                }
            }
        }
    }
    fun stopWatching() { watcher?.cancel(); watcher = null }
}
