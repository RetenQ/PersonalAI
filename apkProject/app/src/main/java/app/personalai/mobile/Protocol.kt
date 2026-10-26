package app.personalai.mobile

import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.util.UUID

object Protocol {
    const val prefix = "/api/clients/v1"
    fun endpoint(value: String, debug: Boolean): String {
        val uri = URI(value.trim())
        require(uri.host != null && uri.userInfo == null && uri.query == null && uri.fragment == null && uri.path in listOf("", "/")) { "请填写不带路径和凭据的服务器地址" }
        require(uri.scheme == "https" || debug && uri.scheme == "http" && uri.host in listOf("127.0.0.1", "localhost", "10.0.2.2")) { "服务器必须使用 HTTPS" }
        return value.trim().trimEnd('/')
    }
    fun command(operation: String, data: JSONObject, kind: String? = null, id: String? = null, version: Int = 0): JSONObject =
        JSONObject().put("request_id", UUID.randomUUID().toString()).put("operation", operation).put("data", data)
            .put("expected_version", version).apply { if (kind != null) put("kind", kind); if (id != null) put("id", id) }
    fun merge(snapshot: JSONObject, changes: JSONObject): JSONObject {
        val result = JSONObject(snapshot.toString())
        val old = result.optJSONObject("data") ?: JSONObject().also { result.put("data", it) }
        val data = changes.getJSONObject("data")
        val replace = changes.optJSONArray("replace").objectsAndStrings().map { it.toString() }.toSet()
        data.keys().forEach { resource ->
            if (resource in replace) old.put(resource, data.getJSONArray(resource))
            else {
                val index = linkedMapOf<String, JSONObject>()
                old.optJSONArray(resource).objects().forEach { index[it.getString("id")] = it }
                data.getJSONArray(resource).objects().forEach { index[it.getString("id")] = it }
                old.put(resource, JSONArray(index.values.toList()))
            }
        }
        result.put("cursor", changes.getString("cursor"))
        if (changes.has("occurrences")) result.put("occurrences", changes.getJSONArray("occurrences"))
        if (changes.has("receipts")) result.put("receipts", changes.getJSONArray("receipts"))
        if (changes.has("year")) result.put("year", changes.getJSONObject("year"))
        result.put("synced_at", java.time.Instant.now().toString())
        return result
    }
}
fun JSONArray?.objects(): List<JSONObject> = if (this == null) emptyList() else (0 until length()).mapNotNull { optJSONObject(it) }
fun JSONArray?.objectsAndStrings(): List<Any> = if (this == null) emptyList() else (0 until length()).map { get(it) }
