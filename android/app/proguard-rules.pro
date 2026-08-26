# kotlinx.serialization generates serializers reflectively at the boundary;
# R8 cannot see those uses, so keep them.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class com.mlev.app.data.remote.** { *; }
-keep,includedescriptorclasses class com.mlev.app.**$$serializer { *; }
-keepclassmembers class com.mlev.app.** { *** Companion; }
-keepclasseswithmembers class com.mlev.app.** { kotlinx.serialization.KSerializer serializer(...); }

# ViewModels are constructed through a factory rather than reflection, but
# SavedStateHandle restoration and Compose tooling still reach for these.
-keepclassmembers class * extends androidx.lifecycle.ViewModel {
    <init>(...);
}

# Room's generated implementation is looked up by name at runtime.
-keep class * extends androidx.room.RoomDatabase { <init>(); }
-keep @androidx.room.Entity class * { *; }

# Glance instantiates the receiver and the widget from the manifest.
-keep class com.mlev.app.widget.** { *; }
-keep class * extends androidx.glance.appwidget.GlanceAppWidgetReceiver { *; }

# WorkManager instantiates workers by class name.
-keep class * extends androidx.work.ListenableWorker { <init>(...); }
