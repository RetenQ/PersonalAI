plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}
val pushKey = providers.gradleProperty("jpushAppKey").orElse("").get()
android {
    namespace = "app.personalai.mobile"
    compileSdk = 35
    defaultConfig {
        applicationId = "app.personalai.mobile"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.4.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        manifestPlaceholders["JPUSH_PKGNAME"] = applicationId!!
        manifestPlaceholders["JPUSH_APPKEY"] = pushKey
        manifestPlaceholders["JPUSH_CHANNEL"] = "personal"
        buildConfigField("boolean", "PUSH_CONFIGURED", pushKey.isNotBlank().toString())
    }
    buildFeatures { compose = true; buildConfig = true }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    if (pushKey.isNotBlank()) {
        sourceSets["main"].java.srcDir("src/jpush/java")
        sourceSets["main"].manifest.srcFile("src/jpush/AndroidManifest.xml")
    }
    buildTypes { release { isMinifyEnabled = false } }
}
dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.04.01"))
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.work:work-runtime-ktx:2.10.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.1")
    if (pushKey.isNotBlank()) {
        implementation("cn.jiguang.sdk:jpush:6.2.1")
        implementation("cn.jiguang.sdk:jcore:5.5.7") { version { strictly("5.5.7") } }
    }
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
