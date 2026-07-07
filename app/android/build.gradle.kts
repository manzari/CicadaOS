allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

// Some plugins (via flutter_plugin_android_lifecycle) require compiling against
// API 36, but the bundled Flutter defaults plugin modules to a lower compileSdk.
// Override it AFTER each module's build script runs (which is where the plugin
// sets 34), guarding against modules already evaluated via evaluationDependsOn.
subprojects {
    val bump = {
        val ext = extensions.findByName("android")
        if (ext is com.android.build.gradle.BaseExtension) {
            ext.compileSdkVersion(36)
        }
    }
    if (state.executed) bump() else afterEvaluate { bump() }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
