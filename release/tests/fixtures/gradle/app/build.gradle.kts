plugins {
    alias(libs.plugins.android.application)
}

android {
    namespace = "com.example.gradleapp"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.example.gradleapp"
        minSdk = 26
        targetSdk = 37
        versionCode = 26
        versionName = "1.9.0"
    }
}
