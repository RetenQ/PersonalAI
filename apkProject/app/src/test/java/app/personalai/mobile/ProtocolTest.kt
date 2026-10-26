package app.personalai.mobile

import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject

class ProtocolTest {
    @Test fun productionEndpointsRejectCredentialsAndCleartext() {
        listOf("http://example.com", "https://user:pass@example.com", "https://example.com/?token=secret", "https://example.com/api").forEach { address ->
            assertTrue(runCatching { Protocol.endpoint(address, false) }.isFailure)
        }
        assertEquals("https://example.com", Protocol.endpoint("https://example.com/", false))
        assertEquals("http://10.0.2.2:8765", Protocol.endpoint("http://10.0.2.2:8765", true))
        assertTrue(runCatching { Protocol.endpoint("http://192.168.1.5", true) }.isFailure)
    }
    @Test fun changesReplaceDerivedCollectionsAndPreserveUnchangedRecords() {
        val snapshot = JSONObject("""{"cursor":"old","data":{"tasks":[{"id":"t1"}],"logs":[{"id":"l1","version":1},{"id":"l2","version":1}],"pending":[{"id":"p1"}]},"receipts":[]}""")
        val changes = JSONObject("""{"cursor":"new","data":{"tasks":[],"logs":[{"id":"l1","version":2}],"pending":[]},"replace":["tasks","pending"],"receipts":[{"id":"read1"}],"occurrences":[],"year":{"remaining_days":12}}""")
        val value = Protocol.merge(snapshot, changes)
        assertEquals(0, value.getJSONObject("data").getJSONArray("tasks").length())
        assertEquals(2, value.getJSONObject("data").getJSONArray("logs").length())
        assertEquals(2, value.getJSONObject("data").getJSONArray("logs").getJSONObject(0).getInt("version"))
        assertEquals("old", snapshot.getString("cursor"))
        assertEquals(1, value.getJSONArray("receipts").length())
        assertEquals(12, value.getJSONObject("year").getInt("remaining_days"))
    }
    @Test fun persistedCommandsKeepIdentityAndVersion() {
        val command = Protocol.command("write_entity", JSONObject().put("current", JSONObject.NULL), "goal", "goal-1", 3)
        val saved = JSONObject(command.toString())
        assertEquals(command.getString("request_id"), saved.getString("request_id"))
        assertEquals(3, saved.getInt("expected_version"))
        assertTrue(saved.getJSONObject("data").isNull("current"))
    }
}
