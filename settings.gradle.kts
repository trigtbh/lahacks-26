pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()

        // Meta Wearables DAT SDK — requires GitHub Packages token in local.properties
        maven {
            url = uri("https://maven.pkg.github.com/facebook/meta-wearables-dat-android")
            credentials {
                val props = java.util.Properties()
                val localPropsFile = File(rootDir, "local.properties")
                if (localPropsFile.exists()) props.load(localPropsFile.inputStream())
                username = props.getProperty("github_username") ?: System.getenv("GITHUB_ACTOR") ?: ""
                password = props.getProperty("github_token") ?: System.getenv("GITHUB_PACKAGES_TOKEN") ?: ""
            }
        }
    }
}

rootProject.name = "Flow"
include(":app")
