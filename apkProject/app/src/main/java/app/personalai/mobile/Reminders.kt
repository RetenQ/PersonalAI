package app.personalai.mobile

import android.Manifest
import android.app.*
import android.content.*
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.util.concurrent.TimeUnit

class PersonalApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Reminders.channel(this)
        val job = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork("personalai-sync", ExistingPeriodicWorkPolicy.KEEP, job)
        PushBridge.start(this)
    }
}

object PushBridge {
    fun start(context: Context) {
        if (BuildConfig.PUSH_CONFIGURED && runCatching { SecureStore(context).read().optBoolean("push_consent") }.getOrDefault(false)) {
            runCatching { Class.forName("app.personalai.mobile.OptionalPush").getMethod("start", Context::class.java).invoke(null, context) }
        }
    }
    fun stop(context: Context) {
        if (BuildConfig.PUSH_CONFIGURED) runCatching { Class.forName("app.personalai.mobile.OptionalPush").getMethod("stop", Context::class.java).invoke(null, context) }
    }
}

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val store = SecureStore(applicationContext)
        try {
            if (!store.read().has("tokens")) return@withContext Result.success()
            val api = Api(store)
            api.sync()
            val local = store.read()
            if (!local.optBoolean("push_consent") && local.has("push_registration"))
                api.request("/device", JSONObject().put("notifications", local.optBoolean("notifications")).put("push_registration", JSONObject.NULL))
            Reminders.reconcile(applicationContext)
            store.update { it.remove("sync_error") }
            Result.success()
        } catch (e: Exception) {
            store.update { it.put("sync_error", if (e is ApiError && e.status == 401) "设备授权已失效，请重新配对。" else "后台同步失败，保留上次缓存。") }
            Result.failure() // The next scheduled cycle may try again; never submits drafts.
        }
    }
}

object Reminders {
    private const val CHANNEL = "personalai-reminders"
    fun channel(context: Context) {
        context.getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "日程提醒", NotificationManager.IMPORTANCE_DEFAULT))
    }
    fun exact(context: Context): Boolean = Build.VERSION.SDK_INT < 31 || context.getSystemService(AlarmManager::class.java).canScheduleExactAlarms()
    fun allowed(context: Context): Boolean = (Build.VERSION.SDK_INT < 33 || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) && context.getSystemService(NotificationManager::class.java).areNotificationsEnabled()
    private fun alarm(context: Context, id: String): PendingIntent = PendingIntent.getBroadcast(context, 0,
        Intent(context, ReminderReceiver::class.java).setData(Uri.parse("personalai://reminder/" + Uri.encode(id))),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    @Synchronized fun reconcile(context: Context) {
        val store = SecureStore(context); val local = store.read()
        val manager = context.getSystemService(AlarmManager::class.java)
        local.optJSONArray("alarms").objectsAndStrings().forEach { manager.cancel(alarm(context, it.toString())) }
        val shown = local.optJSONArray("shown").objectsAndStrings().map { it.toString() }.toSet()
        val snapshot = local.optJSONObject("snapshot")
        val items = (snapshot?.optJSONArray("occurrences").objects() + local.optJSONArray("snoozed").objects())
            .distinctBy { it.getString("id") }.filter { Instant.parse(it.getString("due_at")).isAfter(Instant.now()) && it.getString("id") !in shown }
        val enabled = local.optBoolean("notifications", false) && local.has("tokens")
        val selected = if (enabled) items else emptyList()
        selected.forEach { item ->
            val timestamp = Instant.parse(item.getString("due_at")).toEpochMilli()
            try {
                if (exact(context)) manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, timestamp, alarm(context, item.getString("id")))
                else manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, timestamp, alarm(context, item.getString("id")))
            } catch (_: SecurityException) { manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, timestamp, alarm(context, item.getString("id"))) }
        }
        store.update { it.put("alarms", JSONArray(selected.map { e -> e.getString("id") })) }
    }
    fun show(context: Context, id: String) {
        val store = SecureStore(context); val local = store.read()
        if (!local.optBoolean("notifications") || !local.has("tokens") || !allowed(context)) return
        val shown = local.optJSONArray("shown").objectsAndStrings().map { it.toString() }
        if (id in shown || id !in local.optJSONArray("alarms").objectsAndStrings()) return
        val intent = PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java)
            .setData(Uri.parse("personalai://reminder/" + Uri.encode(id))).putExtra("messages", true), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        channel(context)
        context.getSystemService(NotificationManager::class.java).notify(id, 1, NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_popup_reminder).setContentTitle("PersonalAI 日程提醒")
            .setContentText("到约定的提醒时间了，打开查看安排。")
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setContentIntent(intent).setAutoCancel(true).build())
        store.update { it.put("shown", JSONArray((shown + id).takeLast(3000))) }
    }
    fun snooze(context: Context, item: JSONObject, minutes: Int) {
        val value = JSONObject(item.toString()).put("id", item.getString("id") + ":snooze:" + java.util.UUID.randomUUID())
            .put("due_at", Instant.now().plusSeconds(minutes * 60L).toString())
        SecureStore(context).update { local ->
            val upcoming = local.optJSONArray("snoozed").objects().filter { Instant.parse(it.getString("due_at")).isAfter(Instant.now()) }
            local.put("snoozed", JSONArray(upcoming + value))
        }
        reconcile(context)
    }
    fun cancelAll(context: Context) {
        val manager = context.getSystemService(AlarmManager::class.java)
        SecureStore(context).read().optJSONArray("alarms").objectsAndStrings().forEach { manager.cancel(alarm(context, it.toString())) }
    }
}

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        intent.data?.lastPathSegment?.let { id -> runCatching { Reminders.show(context, id) } }
    }
}
class RestoreReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action !in setOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_TIMEZONE_CHANGED,
                Intent.ACTION_TIME_CHANGED, Intent.ACTION_MY_PACKAGE_REPLACED, "android.app.action.SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED")) return
        runCatching { Reminders.reconcile(context) }
    }
}
