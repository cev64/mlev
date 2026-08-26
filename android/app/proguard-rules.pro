# kotlinx.serialization generates serializers reflectively at the boundary;
# R8 cannot see those uses, so keep them.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class com.mlev.app.data.remote.** { *; }
-keep,includedescriptorclasses class com.mlev.app.**$$serializer { *; }
-keepclassmembers class com.mlev.app.** { *** Companion; }
-keepclasseswithmembers class com.mlev.app.** { kotlinx.serialization.KSerializer serializer(...); }
