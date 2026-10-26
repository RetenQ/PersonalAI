package app.personalai.mobile

import android.content.Context
import android.content.Intent
import androidx.work.*
import cn.jpush.android.api.JPushInterface
import cn.jpush.android.api.NotificationMessage
import cn.jpush.android.service.JPushMessageReceiver
import cn.jiguang.api.JCoreInterface
import org.json.JSONObject

/** Compiled only for an explicitly configured AppKey. No server secret belongs in APK. */
object OptionalPush {
    @JvmStatic fun start(context: Context) {
        JPushInterface.setDebugMode(false)
        JPushInterface.init(context)
        JPushInterface.resumePush(context)
        val id = JPushInterface.getRegistrationID(context)
        if (!id.isNullOrBlank()) register(context, id)
    }
    @JvmStatic fun stop(context: Context) { JPushInterface.stopPush(context) }
    fun register(context: Context, id: String) {
        SecureStore(context).update { it.put("push_registration", id) }
        WorkManager.getInstance(context).enqueueUniqueWork("personalai-push-register", ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<PushRegistrationWorker>().setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build())
    }
}
class PushRegistrationWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val store = SecureStore(applicationContext); val local = store.read()
        if (!local.has("tokens") || !local.optBoolean("push_consent")) return Result.success()
        return try {
            Api(store).request("/device", JSONObject().put("notifications", local.optBoolean("notifications")).put("push_registration", local.getString("push_registration")))
            Result.success()
        } catch (_: Exception) { Result.failure() }
    }
}
class PushReceiver : JPushMessageReceiver() {
    override fun onRegister(context: Context, registrationId: String) { if (SecureStore(context).read().optBoolean("push_consent")) OptionalPush.register(context, registrationId) }
    override fun onNotifyMessageOpened(context: Context, message: NotificationMessage) {
        // Provider data is never executed or used as an endpoint. Fetch authorized server data.
        context.startActivity(Intent(context, MainActivity::class.java).putExtra("messages", true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP))
    }
    override fun onNotifyMessageArrived(context: Context, message: NotificationMessage) {
        WorkManager.getInstance(context).enqueueUniqueWork("personalai-push-sync", ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<SyncWorker>().setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build())
    }
}
