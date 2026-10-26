package app.personalai.mobile

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

class ApiError(val status: Int, message: String) : Exception(message)

class Api(private val store: SecureStore) {
    private fun raw(base: String, path: String, body: JSONObject?, token: String = ""): JSONObject {
        val connection = URL(base + path).openConnection() as HttpURLConnection
        connection.instanceFollowRedirects = false
        connection.connectTimeout = 10000; connection.readTimeout = 70000
        connection.setRequestProperty("Accept", "application/json")
        if (token.isNotBlank()) connection.setRequestProperty("Authorization", "Bearer $token")
        try {
            if (body != null) {
                connection.requestMethod = "POST"; connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.use { input ->
                val buffer = java.io.ByteArrayOutputStream(); val chunk = ByteArray(8192)
                while (true) { val count = input.read(chunk); if (count < 0) break; require(buffer.size() + count <= 8 * 1024 * 1024) { "服务器响应过大" }; buffer.write(chunk, 0, count) }
                buffer.toString("UTF-8")
            } ?: "{}"
            val json = runCatching { JSONObject(text) }.getOrDefault(JSONObject())
            if (status !in 200..299) throw ApiError(status, json.optString("detail", "连接未完成（$status）"))
            return json
        } finally { connection.disconnect() }
    }
    fun pair(base: String, name: String): JSONObject {
        val endpoint = Protocol.endpoint(base, BuildConfig.DEBUG)
        val current = store.read()
        require(current.optString("server").isBlank() || current.optString("server") == endpoint) { "请先在设置中断开旧服务器，避免混用数据" }
        val result = raw(endpoint, Protocol.prefix + "/pairings", JSONObject().put("name", name))
        store.update { it.put("server", endpoint).put("pairing", result) }
        return result
    }
    fun pollPair(): JSONObject {
        val local = store.read(); val pair = local.getJSONObject("pairing")
        val result = raw(local.getString("server"), Protocol.prefix + "/pairings/poll",
            JSONObject().put("pairing_id", pair.getString("pairing_id")).put("poll_secret", pair.getString("poll_secret")))
        if (result.optString("status") == "paired") store.update { it.put("tokens", result); it.remove("pairing") }
        return result
    }
    fun request(path: String, body: JSONObject? = null): JSONObject = synchronized(lock) {
        var local = store.read()
        if (!local.has("tokens")) throw ApiError(401, "请先配对设备")
        try { raw(local.getString("server"), Protocol.prefix + path, body, local.getJSONObject("tokens").getString("access_token")) }
        catch (e: ApiError) {
            if (e.status != 401) throw e
            val refreshed = raw(local.getString("server"), Protocol.prefix + "/auth/refresh",
                JSONObject().put("refresh_token", local.getJSONObject("tokens").getString("refresh_token")))
            store.update { it.put("tokens", refreshed) }; local = store.read()
            raw(local.getString("server"), Protocol.prefix + path, body, refreshed.getString("access_token"))
        }
    }
    fun sync(): JSONObject = synchronized(lock) {
        val cached = store.read().optJSONObject("snapshot")
        val value = if (cached == null) request("/snapshot") else try {
            Protocol.merge(cached, request("/changes?cursor=" + URLEncoder.encode(cached.getString("cursor"), "UTF-8")))
        } catch (e: ApiError) { if (e.status == 410) request("/snapshot") else throw e }
        store.update { local ->
            val history = (local.optJSONArray("reminder_history").objects() + cached?.optJSONArray("occurrences").objects())
                .filter { java.time.Instant.parse(it.getString("due_at")).isBefore(java.time.Instant.now()) }.distinctBy { it.getString("id") }.takeLast(300)
            local.put("snapshot", value).put("reminder_history", org.json.JSONArray(history))
        }
        request("/sync/ack", JSONObject().put("cursor", value.getString("cursor")))
        value
    }
    /** One bounded SSE subscription. Caller reconnects with its last committed cursor. */
    fun awaitUpdate(): Boolean {
        val local = store.read(); val cursor = local.optJSONObject("snapshot")?.optString("cursor") ?: return true
        val token = local.optJSONObject("tokens")?.optString("access_token") ?: return false
        val connection = URL(local.getString("server") + Protocol.prefix + "/events?cursor=" + URLEncoder.encode(cursor, "UTF-8")).openConnection() as HttpURLConnection
        connection.instanceFollowRedirects = false; connection.connectTimeout = 10000; connection.readTimeout = 35000
        connection.setRequestProperty("Authorization", "Bearer $token")
        try {
            if (connection.responseCode != 200) return true
            connection.inputStream.bufferedReader().use { reader ->
                while (true) { val line = reader.readLine() ?: return false; if (line == "event: update") return true }
            }
        } finally { connection.disconnect() }
    }
    companion object { private val lock = Any() }
}
