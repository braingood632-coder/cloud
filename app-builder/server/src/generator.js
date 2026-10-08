'use strict';
// AppSpec -> map of { relativePath: fileContent } describing a complete Gradle/Compose project.

const { COMPONENTS } = require('./components');

const PKG_RE = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/;
const COLOR_RE = /^#[0-9a-fA-F]{6}$/;

function normalizeSpec(input) {
  const s = input || {};
  const lang = s.lang === 'en' ? 'en' : 'ar';
  // Keep only characters that are safe inside Kotlin strings and XML attributes.
  let name = String(s.name || '').replace(/[^\p{L}\p{N} _-]/gu, '').trim().slice(0, 30);
  if (!name) name = lang === 'ar' ? 'تطبيقي' : 'My App';
  const packageName = PKG_RE.test(s.packageName || '') ? s.packageName : 'com.appbuilder.app';
  const color = COLOR_RE.test(s.color || '') ? s.color : '#00796B';
  const seen = new Set();
  const components = [];
  for (const id of s.components || []) {
    if (COMPONENTS[id] && !seen.has(id)) { seen.add(id); components.push(id); }
  }
  if (!components.length) components.push('about');
  return { name, packageName, lang, color, components };
}

function mixWithWhite(hex, amount) {
  const n = parseInt(hex.slice(1), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(c => Math.round(c + (255 - c) * amount));
  return ch.map(c => c.toString(16).padStart(2, '0')).join('').toUpperCase();
}

const xmlEscape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function baseFiles(spec) {
  return {
    'settings.gradle.kts': `pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "GeneratedApp"
include(":app")
`,
    'build.gradle.kts': `plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}
`,
    'gradle.properties': `org.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8
android.useAndroidX=true
kotlin.code.style=official
`,
    'app/build.gradle.kts': `plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "${spec.packageName}"
    compileSdk = 34

    defaultConfig {
        applicationId = "${spec.packageName}"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
    composeOptions { kotlinCompilerExtensionVersion = "1.5.14" }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.09.00"))
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
}
`,
    'app/src/main/AndroidManifest.xml': `<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application
        android:allowBackup="true"
        android:label="${xmlEscape(spec.name)}"
        android:supportsRtl="true"
        android:theme="@android:style/Theme.Material.NoActionBar">
        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
`,
  };
}

function javaDir(spec) {
  return `app/src/main/java/${spec.packageName.replace(/\./g, '/')}`;
}

function mainActivity(spec) {
  const t = (ar, en) => (spec.lang === 'ar' ? ar : en);
  const comps = spec.components.map(id => COMPONENTS[id]);
  const labels = comps.map(c => `"${c.label[spec.lang]}"`).join(', ');
  const icons = comps.map(c => `"${c.icon}"`).join(', ');
  const branches = comps.map((c, i) => `                    ${i} -> ${c.fn}()`).join('\n');
  const dir = spec.lang === 'ar' ? 'Rtl' : 'Ltr';
  const hex = spec.color.slice(1).toUpperCase();
  const light = mixWithWhite(spec.color, 0.45);
  return `package ${spec.packageName}

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { AppTheme { AppRoot() } }
    }
}

@Composable
fun AppTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val scheme = if (dark) darkColorScheme(primary = Color(0xFF${light})) else lightColorScheme(primary = Color(0xFF${hex}))
    MaterialTheme(colorScheme = scheme) {
        Surface(color = MaterialTheme.colorScheme.background, content = content)
    }
}

@Composable
fun AppRoot() {
    var selected by remember { mutableIntStateOf(0) }
    val labels = listOf(${labels})
    val icons = listOf(${icons})
    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.${dir}) {
        Scaffold(
            bottomBar = {
                if (labels.size > 1) {
                    NavigationBar {
                        labels.forEachIndexed { i, l ->
                            NavigationBarItem(
                                selected = selected == i,
                                onClick = { selected = i },
                                icon = { Text(icons[i]) },
                                label = { Text(l) }
                            )
                        }
                    }
                }
            }
        ) { pad ->
            Box(Modifier.padding(pad)) {
                when (selected) {
${branches}
                    else -> {}
                }
            }
        }
    }
}
`;
}

function templateFiles(spec) {
  const t = (ar, en) => (spec.lang === 'ar' ? ar : en);
  const dir = javaDir(spec);
  const files = { [`${dir}/MainActivity.kt`]: mainActivity(spec) };
  for (const id of spec.components) {
    const c = COMPONENTS[id];
    files[`${dir}/${c.fn}.kt`] = `package ${spec.packageName}\n\n` + c.kotlin(t, spec);
  }
  return files;
}

function generate(rawSpec) {
  const spec = normalizeSpec(rawSpec);
  return { spec, files: { ...baseFiles(spec), ...templateFiles(spec) } };
}

module.exports = { generate, normalizeSpec, baseFiles, templateFiles, javaDir };
