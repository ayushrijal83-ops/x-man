plugins {
    id("com.android.application")
}

android {
    namespace = "np.xman.fieldnode"
    compileSdk = 37

    defaultConfig {
        applicationId = "np.xman.fieldnode"
        minSdk = 26
        targetSdk = 37
        versionCode = 2
        versionName = "0.2.0-mlive04"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    // ComponentActivity: lifecycle owner for CameraX + runtime permission contracts. No AppCompat/Material.
    implementation("androidx.activity:activity-ktx:1.13.0")
    implementation("androidx.camera:camera-camera2:1.6.2")
    implementation("androidx.camera:camera-lifecycle:1.6.2")
    implementation("androidx.camera:camera-view:1.6.2")

    testImplementation("junit:junit:4.13.2")
    // org.json is part of Android but only stubbed in JVM unit tests
    testImplementation("org.json:json:20260814")

    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
}
