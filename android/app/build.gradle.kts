import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
}

/**
 * versionCode must only ever increase, or Android refuses the install as a
 * downgrade. CI passes the run number in; a local build falls back to the base
 * so it can never accidentally exceed a CI build and block a later update.
 */
val versionBase = 3
val ciBuildNumber = (System.getenv("MLEV_BUILD_NUMBER") ?: "").toIntOrNull()
val computedVersionCode = ciBuildNumber?.let { versionBase + it } ?: versionBase

/**
 * Release signing. The keystore lives outside the repository — see
 * android/signing.gradle.example and the README. Without it a release build is
 * still produced but signed with the debug identity, and it is labelled as such
 * because it cannot update a properly signed install.
 */
val keystoreProperties = Properties().apply {
    val file = rootProject.file("keystore.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

fun signingValue(key: String, env: String): String? =
    keystoreProperties.getProperty(key) ?: System.getenv(env)

val releaseStoreFile = signingValue("storeFile", "ANDROID_KEYSTORE_PATH")
val hasReleaseSigning = releaseStoreFile != null && file(releaseStoreFile).exists()

android {
    namespace = "com.mlev.app"
    compileSdk = 35

    defaultConfig {
        // Permanent. Changing it makes Android treat a build as a different app
        // and breaks upgrade-in-place, which would strand saved prices.
        applicationId = "com.mlev.app"
        minSdk = 26
        targetSdk = 35
        versionCode = computedVersionCode
        versionName = "2.0.1"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // Room exports schemas so migrations can be written against real history.
        ksp { arg("room.schemaLocation", "$projectDir/schemas") }
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(releaseStoreFile!!)
                storePassword = signingValue("storePassword", "ANDROID_KEYSTORE_PASSWORD")
                keyAlias = signingValue("keyAlias", "ANDROID_KEY_ALIAS")
                keyPassword = signingValue("keyPassword", "ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            // Minification is off until a release build has been confirmed
            // working on a real device.
            //
            // R8 renames and strips based on what it can see statically, and
            // anything reached reflectively — ViewModel constructors, Room's
            // generated classes, kotlinx.serialization serializers — depends on
            // keep rules being exactly right. Those failures appear only in the
            // build you ship, which is the one hardest to test. The rules in
            // proguard-rules.pro look correct and the mapping file confirms the
            // serializers survive, but "looks correct" is not verification, and
            // the two megabytes it saves are not worth an unverifiable crash.
            //
            // To re-enable: set both to true, build, install on a device, and
            // check the app opens, downloads a bundle, and the widget renders.
            isMinifyEnabled = false
            isShrinkResources = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = if (hasReleaseSigning) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
        debug {
            // A separate id so a debug build can sit beside the real app instead
            // of fighting it for the same install.
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
    packaging { resources { excludes += "/META-INF/{AL2.0,LGPL2.1}" } }
    testOptions { unitTests { isIncludeAndroidResources = true } }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.splashscreen)
    implementation(libs.androidx.lifecycle.runtime)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.material.icons)
    debugImplementation(libs.compose.ui.tooling)

    implementation(libs.adaptive)
    implementation(libs.adaptive.layout)
    implementation(libs.adaptive.navigation)
    implementation(libs.androidx.navigation.compose)

    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
    ksp(libs.androidx.room.compiler)

    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.work.runtime)

    implementation(libs.glance.appwidget)
    implementation(libs.glance.material3)

    implementation(libs.kotlinx.serialization.json)

    testImplementation(libs.junit)
    testImplementation(libs.robolectric)
    // Launching the real activity on the JVM: this is what catches a crash in
    // the startup path, which unit-testing the maths never could.
    testImplementation(libs.androidx.test.core)
    testImplementation(libs.androidx.test.junit)
    testImplementation(platform(libs.compose.bom))
    testImplementation(libs.compose.ui.test.junit4)
    debugImplementation(libs.compose.ui.test.manifest)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.androidx.room.testing)
}
