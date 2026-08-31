-keep class com.screenrecorder.** { *; }
-keepclassmembers class * extends android.app.Activity {
    public void *(android.view.View);
}
-dontwarn kotlinx.**
